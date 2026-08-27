"""In-memory joins for generated voice, direction, and audio records."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import cast

from lancedb.table import AsyncTable

from bgvoice.model_types import RunStatus
from bgvoice.reader_models import DirectedLineRow, GeneratedVoiceRow
from bgvoice.storage_records import (
    DirectedLineRecord,
    GeneratedAudioRecord,
    GeneratedVoiceRecord,
    TtsBatchRecord,
    VoiceResourceRecord,
)


@dataclass(frozen=True, slots=True)
class GenerationSnapshot:
    """The small generated-data side of application-level browse joins."""

    voices: dict[str, GeneratedVoiceRecord]
    directions: list[DirectedLineRecord]
    audio: list[GeneratedAudioRecord]
    batches: list[TtsBatchRecord]
    voice_names: dict[str, str]
    directions_by_line: dict[str, list[DirectedLineRecord]]
    audio_by_id: dict[str, GeneratedAudioRecord]
    direction_count_by_voice: Counter[str]
    audio_count_by_voice: Counter[str]
    audio_voices_by_line: dict[str, set[str]]

    @classmethod
    async def load(
        cls,
        generated_voices_table: AsyncTable,
        directed_lines_table: AsyncTable,
        generated_audio_table: AsyncTable,
        tts_batches_table: AsyncTable,
        current_voices: list[VoiceResourceRecord],
    ) -> GenerationSnapshot:
        voice_rows, direction_rows, audio_rows, batch_rows = await asyncio.gather(
            generated_voices_table.query().to_pydantic(GeneratedVoiceRecord),
            directed_lines_table.query().to_pydantic(DirectedLineRecord),
            generated_audio_table.query().to_pydantic(GeneratedAudioRecord),
            tts_batches_table.query().to_pydantic(TtsBatchRecord),
        )
        directions = cast(list[DirectedLineRecord], direction_rows)
        audio = cast(list[GeneratedAudioRecord], audio_rows)
        directions_by_line: dict[str, list[DirectedLineRecord]] = defaultdict(list)
        for row in directions:
            directions_by_line[row.dialogue_line_id].append(row)
        audio_voices_by_line: dict[str, set[str]] = defaultdict(set)
        for row in audio:
            audio_voices_by_line[row.dialogue_line_id].add(row.voice_id.casefold())
        return cls(
            voices={
                row.voice_id.casefold(): row for row in cast(list[GeneratedVoiceRecord], voice_rows)
            },
            directions=directions,
            audio=audio,
            batches=cast(list[TtsBatchRecord], batch_rows),
            voice_names={row.voice_id.casefold(): row.display_name for row in current_voices},
            directions_by_line=dict(directions_by_line),
            audio_by_id={row.id: row for row in audio},
            direction_count_by_voice=Counter(row.voice_id.casefold() for row in directions),
            audio_count_by_voice=Counter(row.voice_id.casefold() for row in audio),
            audio_voices_by_line=dict(audio_voices_by_line),
        )

    def generated_voice(self, voice_id: str) -> GeneratedVoiceRow | None:
        record = self.voices.get(voice_id.casefold())
        if record is None:
            return None
        return GeneratedVoiceRow(
            description=record.description.text,
            language_code=record.description.language_code,
            inworld_voice_id=record.inworld_voice_id,
            created_at=record.created_at,
        )

    def line_directions(self, line_id: str) -> list[DirectedLineRow]:
        audio_by_id = self.audio_by_id
        rows = [
            DirectedLineRow(
                id=record.id,
                voice_id=record.voice_id,
                voice_display_name=self.voice_names.get(
                    record.voice_id.casefold(), record.voice_id
                ),
                character=record.character,
                narrator=record.narrator,
                audio_id=record.id if record.id in audio_by_id else None,
            )
            for record in self.directions_by_line.get(line_id, ())
        ]
        return sorted(rows, key=lambda row: (row.voice_display_name.casefold(), row.voice_id))

    def voice_counts(self, voice_id: str) -> tuple[int, int]:
        key = voice_id.casefold()
        return self.direction_count_by_voice[key], self.audio_count_by_voice[key]

    def dialogue_counts(self) -> tuple[Counter[str], Counter[str]]:
        directed: dict[str, set[str]] = defaultdict(set)
        audio: dict[str, set[str]] = defaultdict(set)
        for row in self.directions:
            directed[_dialogue_name(row.dialogue_line_id)].add(row.dialogue_line_id)
        for row in self.audio:
            audio[_dialogue_name(row.dialogue_line_id)].add(row.dialogue_line_id)
        return (
            Counter({name: len(ids) for name, ids in directed.items()}),
            Counter({name: len(ids) for name, ids in audio.items()}),
        )

    def pipeline_counts(self, current_voices: list[VoiceResourceRecord]) -> tuple[int, ...]:
        current_ids = {row.voice_id.casefold() for row in current_voices}
        return (
            sum(voice_id in current_ids for voice_id in self.voices if voice_id != "narrator"),
            len(self.directions),
            len(self.audio),
            sum(row.status is RunStatus.RUNNING for row in self.batches),
            sum(row.status is RunStatus.FAILED for row in self.batches),
        )


def _dialogue_name(line_id: str) -> str:
    return line_id.partition(":")[0].casefold()
