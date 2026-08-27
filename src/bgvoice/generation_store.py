"""Async persistence for generated voices, directed lines, and audio."""

import asyncio
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
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
    GeneratedAudioRecord,
    GeneratedVoiceRecord,
    TtsBatchRecord,
)
from bgvoice.storage_schema import (
    _DIRECTED_LINES,
    _GENERATED_AUDIO,
    _GENERATED_VOICES,
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
        generated_voices, directed_lines, generated_audio, tts_batches = await asyncio.gather(
            connection.open_table(_GENERATED_VOICES),
            connection.open_table(_DIRECTED_LINES),
            connection.open_table(_GENERATED_AUDIO),
            connection.open_table(_TTS_BATCHES),
        )
        return cls(
            resolved,
            connection,
            generated_voices,
            directed_lines,
            generated_audio,
            tts_batches,
        )

    def close(self) -> None:
        self._connection.close()

    async def generated_voices(self) -> dict[str, GeneratedVoiceRecord]:
        records = await _records(self._generated_voices, GeneratedVoiceRecord)
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

    async def audio(self, audio_id: str) -> GeneratedAudioRecord | None:
        return await _record(self._generated_audio, GeneratedAudioRecord, "id", audio_id)

    async def batches(self) -> list[TtsBatchRecord]:
        return await _records(self._tts_batches, TtsBatchRecord)

    async def running_batches(self) -> list[TtsBatchRecord]:
        return cast(
            list[TtsBatchRecord],
            await self._tts_batches.query()
            .where(col("status") == lit(RunStatus.RUNNING.value))
            .to_pydantic(TtsBatchRecord),
        )

    async def upsert_generated_voices(self, records: Sequence[GeneratedVoiceRecord]) -> None:
        await _upsert(self._generated_voices, "voice_id", records)

    async def upsert_directed_lines(self, records: Sequence[DirectedLineRecord]) -> None:
        await _upsert(self._directed_lines, "id", records)

    async def upsert_generated_audio(self, records: Sequence[GeneratedAudioRecord]) -> None:
        await _upsert(self._generated_audio, "id", records)

    async def upsert_batches(self, records: Sequence[TtsBatchRecord]) -> None:
        await _upsert(self._tts_batches, "operation_name", records)

    async def delete_audio(self, audio_ids: Sequence[str]) -> None:
        if audio_ids:
            await self._generated_audio.delete(col("id").isin(audio_ids))

    async def delete_voice_generation(self, voice_id: str) -> None:
        """Remove every regenerable artifact owned by one canonical character voice."""
        predicate = col("voice_id") == lit(voice_id)
        await self._generated_audio.delete(predicate)
        await self._directed_lines.delete(predicate)
        await self._generated_voices.delete(predicate)


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
