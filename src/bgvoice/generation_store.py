"""Async persistence for generated voices, directed lines, and audio."""

import asyncio
from collections.abc import Awaitable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import cast

import lancedb
from lancedb.db import AsyncConnection
from lancedb.expr import col, lit
from lancedb.pydantic import LanceModel
from lancedb.table import AsyncTable

from bgvoice.model_types import RunStatus, VoiceProfileKind
from bgvoice.storage_records import (
    DirectedLineRecord,
    GeneratedAudioIdentity,
    GeneratedAudioRecord,
    GenerationFailureRecord,
    TtsBatchRecord,
    VoiceGenerationRecord,
    VoiceProfileRecord,
)
from bgvoice.storage_schema import (
    _DIRECTED_LINES,
    _GENERATED_AUDIO,
    _GENERATION_FAILURES,
    _TTS_BATCHES,
    _VOICE_GENERATIONS,
    _VOICE_PROFILES,
    TABLE_NAMES,
)


@dataclass(slots=True)
class GenerationStore:
    """Typed, strongly consistent access to generation-owned Lance tables."""

    path: Path
    _connection: AsyncConnection
    _voice_profiles: AsyncTable
    _voice_generations: AsyncTable
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
            voice_profiles,
            voice_generations,
            directed_lines,
            generated_audio,
            tts_batches,
            failures,
        ) = await asyncio.gather(
            connection.open_table(_VOICE_PROFILES),
            connection.open_table(_VOICE_GENERATIONS),
            connection.open_table(_DIRECTED_LINES),
            connection.open_table(_GENERATED_AUDIO),
            connection.open_table(_TTS_BATCHES),
            connection.open_table(_GENERATION_FAILURES),
        )
        return cls(
            resolved,
            connection,
            voice_profiles,
            voice_generations,
            directed_lines,
            generated_audio,
            tts_batches,
            failures,
        )

    def close(self) -> None:
        self._connection.close()

    async def optimize(self) -> None:
        """Compact generation tables and remove superseded versions."""
        async with self._write_lock:
            for table in (
                self._voice_profiles,
                self._voice_generations,
                self._directed_lines,
                self._generated_audio,
                self._tts_batches,
                self._generation_failures,
            ):
                await table.optimize(cleanup_older_than=timedelta(0))

    async def voice_profiles(
        self,
        profile_ids: Sequence[str] | None = None,
    ) -> dict[str, VoiceProfileRecord]:
        records = await _records(
            self._voice_profiles,
            VoiceProfileRecord,
            "profile_id",
            profile_ids,
        )
        return {record.profile_id: record for record in records}

    async def voice_profile(self, profile_id: str) -> VoiceProfileRecord | None:
        return await _record(
            self._voice_profiles,
            VoiceProfileRecord,
            "profile_id",
            profile_id,
        )

    async def voice_generations(
        self,
        voice_ids: Sequence[str] | None = None,
    ) -> dict[str, VoiceGenerationRecord]:
        records = await _records(
            self._voice_generations,
            VoiceGenerationRecord,
            "voice_id",
            voice_ids,
        )
        return {record.voice_id: record for record in records}

    async def generated_voices(
        self,
        voice_ids: Sequence[str] | None = None,
    ) -> dict[str, VoiceProfileRecord]:
        generations = await self.voice_generations(voice_ids)
        profiles = await self.voice_profiles(
            sorted({record.profile_id for record in generations.values()})
        )
        missing = {record.profile_id for record in generations.values()} - profiles.keys()
        assert not missing, f"voice generations reference missing profiles: {sorted(missing)}"
        return {
            voice_id: profiles[generation.profile_id]
            for voice_id, generation in generations.items()
        }

    async def generated_voice(self, voice_id: str) -> VoiceProfileRecord | None:
        generation = await _record(
            self._voice_generations,
            VoiceGenerationRecord,
            "voice_id",
            voice_id,
        )
        if generation is None:
            return None
        profile = await self.voice_profile(generation.profile_id)
        assert profile is not None, (
            f"voice generation {voice_id!r} references missing profile {generation.profile_id!r}"
        )
        return profile

    async def assert_exclusive_profile_assignment(
        self,
        profile_id: str,
        voice_id: str,
    ) -> None:
        """Require a provider profile to belong only to one logical voice."""
        assigned_voice_ids = await self.profile_voice_ids(profile_id)
        assert assigned_voice_ids == {voice_id}, (
            f"voice profile {profile_id!r} is assigned to {sorted(assigned_voice_ids)}, "
            f"not exclusively to {voice_id!r}"
        )

    async def profile_voice_ids(self, profile_id: str) -> set[str]:
        """Return the logical voices currently backed by one provider profile."""
        assignments = await _records(
            self._voice_generations,
            VoiceGenerationRecord,
            "profile_id",
            [profile_id],
        )
        return {assignment.voice_id for assignment in assignments}

    async def directed_lines(
        self,
        voice_ids: Sequence[str] | None = None,
    ) -> list[DirectedLineRecord]:
        return await _records(self._directed_lines, DirectedLineRecord, "voice_id", voice_ids)

    async def generated_audio(
        self,
        voice_ids: Sequence[str] | None = None,
    ) -> list[GeneratedAudioRecord]:
        return await _records(self._generated_audio, GeneratedAudioRecord, "voice_id", voice_ids)

    async def generated_audio_identities(
        self,
        voice_ids: Sequence[str] | None = None,
    ) -> list[GeneratedAudioIdentity]:
        return await _projected_records(
            self._generated_audio,
            GeneratedAudioIdentity,
            "voice_id",
            voice_ids,
        )

    async def audio(self, audio_id: str) -> GeneratedAudioRecord | None:
        return await _record(self._generated_audio, GeneratedAudioRecord, "id", audio_id)

    async def batches(self) -> list[TtsBatchRecord]:
        return await _records(self._tts_batches, TtsBatchRecord, "operation_name")

    async def failures(
        self,
        voice_ids: Sequence[str] | None = None,
    ) -> list[GenerationFailureRecord]:
        return await _records(
            self._generation_failures,
            GenerationFailureRecord,
            "voice_id",
            voice_ids,
        )

    async def running_batches(self) -> list[TtsBatchRecord]:
        return cast(
            list[TtsBatchRecord],
            await self._tts_batches.query()
            .where(col("status") == lit(RunStatus.RUNNING.value))
            .to_pydantic(TtsBatchRecord),
        )

    async def upsert_voice_profiles(self, records: Sequence[VoiceProfileRecord]) -> None:
        async with self._write_lock:
            await _upsert(self._voice_profiles, "profile_id", records)

    async def upsert_voice_generations(self, records: Sequence[VoiceGenerationRecord]) -> None:
        async with self._write_lock:
            await self._require_profiles(record.profile_id for record in records)
            await _upsert(self._voice_generations, "voice_id", records)

    async def assign_voice(self, generation: VoiceGenerationRecord) -> None:
        """Assign a profile and invalidate audio when the provider voice changes."""
        async with self._write_lock:
            profile = await _record(
                self._voice_profiles,
                VoiceProfileRecord,
                "profile_id",
                generation.profile_id,
            )
            assert profile is not None, (
                f"voice generations reference missing profiles: {[generation.profile_id]}"
            )
            if profile.kind is VoiceProfileKind.DEDICATED:
                assigned_voice_ids = await self.profile_voice_ids(profile.profile_id)
                other_voice_ids = assigned_voice_ids - {generation.voice_id}
                assert not other_voice_ids, (
                    f"dedicated voice profile {profile.profile_id!r} is already assigned to "
                    f"{sorted(other_voice_ids)}"
                )
            existing = await _record(
                self._voice_generations,
                VoiceGenerationRecord,
                "voice_id",
                generation.voice_id,
            )
            if existing is not None and existing.profile_id != generation.profile_id:
                await self._generated_audio.delete(col("voice_id") == lit(generation.voice_id))
            await _upsert(self._voice_generations, "voice_id", [generation])

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
        """Remove one logical voice's provider assignment and provider-dependent audio."""
        predicate = col("voice_id") == lit(voice_id)
        async with self._write_lock:
            await self._generated_audio.delete(predicate)
            await self._voice_generations.delete(predicate)
            await self._generation_failures.delete(predicate)

    async def delete_voice_profile(self, profile_id: str) -> None:
        """Remove an unassigned provider profile."""
        async with self._write_lock:
            assigned = await self._voice_generations.count_rows(
                (col("profile_id") == lit(profile_id)).to_sql()
            )
            assert assigned == 0, f"voice profile {profile_id!r} is still assigned"
            await self._voice_profiles.delete(col("profile_id") == lit(profile_id))

    async def _require_profiles(self, profile_ids: Iterable[str]) -> None:
        ids = sorted(set(profile_ids))
        profiles = await _records(self._voice_profiles, VoiceProfileRecord, "profile_id", ids)
        missing = set(ids) - {profile.profile_id for profile in profiles}
        assert not missing, f"voice generations reference missing profiles: {sorted(missing)}"


async def _records[Record: LanceModel](
    table: AsyncTable,
    model: type[Record],
    column: str,
    keys: Sequence[str] | None = None,
) -> list[Record]:
    if keys is not None and not keys:
        return []
    query = table.query()
    if keys is not None:
        query = query.where(col(column).isin(keys))
    return cast(list[Record], await query.to_pydantic(model))


async def _projected_records[Record: LanceModel](
    table: AsyncTable,
    model: type[Record],
    column: str,
    keys: Sequence[str] | None = None,
) -> list[Record]:
    if keys is not None and not keys:
        return []
    query = table.query()
    if keys is not None:
        query = query.where(col(column).isin(keys))
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
