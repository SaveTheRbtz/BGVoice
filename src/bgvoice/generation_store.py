"""Async persistence for generated voices, directed lines, and audio."""

import asyncio
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import cast

import lancedb
from lancedb.db import AsyncConnection
from lancedb.expr import col, lit
from lancedb.pydantic import LanceModel
from lancedb.table import AsyncTable

from bgvoice.model_types import RunStatus
from bgvoice.storage_records import (
    DirectedLineRecord,
    GeneratedAudioIdentity,
    GeneratedAudioRecord,
    GeneratedVoiceRecord,
    GenerationFailureRecord,
    TtsBatchRecord,
)
from bgvoice.storage_schema import (
    _DIRECTED_LINES,
    _GENERATED_AUDIO,
    _GENERATED_VOICES,
    _GENERATION_FAILURES,
    _TTS_BATCHES,
    TABLE_NAMES,
)


@dataclass(slots=True)
class GenerationStore:
    """Typed, strongly consistent access to generation-owned Lance tables."""

    path: Path
    _connection: AsyncConnection
    _generated_voices: AsyncTable
    _directed_lines: AsyncTable
    _generated_audio: AsyncTable
    _tts_batches: AsyncTable
    _generation_failures: AsyncTable
    _write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @classmethod
    async def open(cls, path: Path) -> GenerationStore:
        resolved = path.expanduser().resolve()
        assert resolved.is_dir(), f"pipeline database does not exist: {resolved}"
        connection = await lancedb.connect_async(
            resolved,
            read_consistency_interval=timedelta(0),
        )
        existing = frozenset((await connection.list_tables(limit=None)).tables)
        assert existing == TABLE_NAMES, (
            f"LanceDB tables are {sorted(existing)}; expected {sorted(TABLE_NAMES)}"
        )
        (
            generated_voices,
            directed_lines,
            generated_audio,
            tts_batches,
            failures,
        ) = await asyncio.gather(
            connection.open_table(_GENERATED_VOICES),
            connection.open_table(_DIRECTED_LINES),
            connection.open_table(_GENERATED_AUDIO),
            connection.open_table(_TTS_BATCHES),
            connection.open_table(_GENERATION_FAILURES),
        )
        return cls(
            resolved,
            connection,
            generated_voices,
            directed_lines,
            generated_audio,
            tts_batches,
            failures,
        )

    def close(self) -> None:
        self._connection.close()

    async def generated_voices(
        self,
        voice_ids: Sequence[str] | None = None,
    ) -> dict[str, GeneratedVoiceRecord]:
        records = await _records(self._generated_voices, GeneratedVoiceRecord, voice_ids)
        return {record.voice_id: record for record in records}

    async def generated_voice(self, voice_id: str) -> GeneratedVoiceRecord | None:
        return await _record(self._generated_voices, GeneratedVoiceRecord, "voice_id", voice_id)

    async def directed_lines(
        self,
        voice_ids: Sequence[str] | None = None,
    ) -> list[DirectedLineRecord]:
        return await _records(self._directed_lines, DirectedLineRecord, voice_ids)

    async def generated_audio(
        self,
        voice_ids: Sequence[str] | None = None,
    ) -> list[GeneratedAudioRecord]:
        return await _records(self._generated_audio, GeneratedAudioRecord, voice_ids)

    async def generated_audio_identities(
        self,
        voice_ids: Sequence[str] | None = None,
    ) -> list[GeneratedAudioIdentity]:
        return await _projected_records(
            self._generated_audio,
            GeneratedAudioIdentity,
            voice_ids,
        )

    async def audio(self, audio_id: str) -> GeneratedAudioRecord | None:
        return await _record(self._generated_audio, GeneratedAudioRecord, "id", audio_id)

    async def batches(self) -> list[TtsBatchRecord]:
        return await _records(self._tts_batches, TtsBatchRecord)

    async def failures(
        self,
        voice_ids: Sequence[str] | None = None,
    ) -> list[GenerationFailureRecord]:
        return await _records(self._generation_failures, GenerationFailureRecord, voice_ids)

    async def running_batches(self) -> list[TtsBatchRecord]:
        return cast(
            list[TtsBatchRecord],
            await self._tts_batches.query()
            .where(col("status") == lit(RunStatus.RUNNING.value))
            .to_pydantic(TtsBatchRecord),
        )

    async def upsert_generated_voices(self, records: Sequence[GeneratedVoiceRecord]) -> None:
        async with self._write_lock:
            await _upsert(self._generated_voices, "voice_id", records)

    async def upsert_directed_lines(self, records: Sequence[DirectedLineRecord]) -> None:
        async with self._write_lock:
            await _upsert(self._directed_lines, "id", records)

    async def upsert_generated_audio(self, records: Sequence[GeneratedAudioRecord]) -> None:
        async with self._write_lock:
            await _upsert(self._generated_audio, "id", records)

    async def upsert_batches(self, records: Sequence[TtsBatchRecord]) -> None:
        async with self._write_lock:
            await _upsert(self._tts_batches, "operation_name", records)

    async def upsert_failures(self, records: Sequence[GenerationFailureRecord]) -> None:
        async with self._write_lock:
            await _upsert(self._generation_failures, "id", records)

    async def delete_failures(self, ids: Sequence[str]) -> None:
        if not ids:
            return
        async with self._write_lock:
            await self._generation_failures.delete(col("id").isin(ids))

    async def delete_line_generation(self, ids: Sequence[str]) -> None:
        """Invalidate selected directions and their generated audio."""
        if not ids:
            return
        predicate = col("id").isin(ids)
        async with self._write_lock:
            await self._generated_audio.delete(predicate)
            await self._directed_lines.delete(predicate)

    async def delete_voice_generation(self, voice_id: str) -> None:
        """Remove every regenerable artifact owned by one canonical character voice."""
        predicate = col("voice_id") == lit(voice_id)
        async with self._write_lock:
            await self._generated_audio.delete(predicate)
            await self._directed_lines.delete(predicate)
            await self._generated_voices.delete(predicate)
            await self._generation_failures.delete(predicate)


async def _records[Record: LanceModel](
    table: AsyncTable,
    model: type[Record],
    voice_ids: Sequence[str] | None = None,
) -> list[Record]:
    if voice_ids is not None and not voice_ids:
        return []
    query = table.query()
    if voice_ids is not None:
        query = query.where(col("voice_id").isin(voice_ids))
    return cast(list[Record], await query.to_pydantic(model))


async def _projected_records[Record: LanceModel](
    table: AsyncTable,
    model: type[Record],
    voice_ids: Sequence[str] | None = None,
) -> list[Record]:
    if voice_ids is not None and not voice_ids:
        return []
    query = table.query()
    if voice_ids is not None:
        query = query.where(col("voice_id").isin(voice_ids))
    return cast(
        list[Record],
        await query.select(list(model.model_fields)).to_pydantic(model),
    )


async def _record[Record: LanceModel](
    table: AsyncTable,
    model: type[Record],
    column: str,
    key: str,
) -> Record | None:
    records = cast(
        list[Record],
        await table.query().where(col(column) == lit(key)).limit(1).to_pydantic(model),
    )
    return records[0] if records else None


async def _upsert[Record: LanceModel](
    table: AsyncTable,
    key: str,
    records: Sequence[Record],
) -> None:
    if not records:
        return
    operation = table.merge_insert(key).when_matched_update_all().when_not_matched_insert_all()
    await cast(Awaitable[object], operation.execute(list(records)))
