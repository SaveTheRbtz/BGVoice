"""Pipeline summary projection from typed extraction records."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from bgvoice.model_types import (
    AttributionPublicationStatus,
    AttributionStatus,
    DetailStatus,
    IdentifierKind,
)
from bgvoice.reader_metadata import MetadataSnapshot
from bgvoice.reader_models import SIMPLE_IDENTIFIER_KINDS, ExtractionRunSummary, PipelineStats
from bgvoice.storage_records import (
    CharacterAttributionRecord,
    CharacterRecord,
    DialogueRecord,
    ExtractionRunRecord,
    VoiceResourceRecord,
)


@dataclass(frozen=True, slots=True)
class AttributionSnapshot:
    publication: AttributionPublicationStatus
    run: ExtractionRunRecord | None
    by_character: dict[str, CharacterAttributionRecord]
    character_count_by_dialogue: Counter[str]
    voices: list[VoiceResourceRecord]
    voice_by_character: dict[str, VoiceResourceRecord]

    @property
    def completed_at(self) -> str | None:
        return None if self.run is None else self.run.completed_at


@dataclass(frozen=True, slots=True)
class StatsTableCounts:
    character_sounds: int
    soundset_lines: int
    line_records: int
    transition_edges: int
    character_resource_links: int
    interaction_rules: int
    engine_strings: int
    sound_slot_groups: int
    favored_enemies: int
    happiness_rules: int
    banter_timing_settings: int


@dataclass(frozen=True, slots=True)
class _CharacterStats:
    total: int
    complete: int
    failed: int
    with_dialogue: int
    unavailable: int
    matched: int
    partially_matched: int
    missing_dialogue: int
    dialogue_failed: int
    without_dialogue: int


@dataclass(frozen=True, slots=True)
class _DialogueStats:
    total: int
    complete: int
    lines: int
    attributed: int
    unattributed: int
    attributed_lines: int
    unattributed_lines: int


@dataclass(frozen=True, slots=True)
class _MetadataStats:
    races: int
    classes: int
    kits: int
    identifiers: int
    campaigns: int


def pipeline_stats(
    path: Path,
    characters: list[CharacterRecord],
    dialogues: list[DialogueRecord],
    latest_runs: list[ExtractionRunRecord],
    metadata: MetadataSnapshot,
    attribution: AttributionSnapshot,
    tables: StatsTableCounts,
) -> PipelineStats:
    character = _character_stats(characters, attribution)
    dialogue = _dialogue_stats(dialogues, attribution)
    metadata_counts = _metadata_stats(metadata)
    return PipelineStats(
        database_path=str(path),
        database_size=sum(file.stat().st_size for file in path.rglob("*") if file.is_file()),
        characters_total=character.total,
        characters_complete=character.complete,
        characters_failed=character.failed,
        characters_with_dialogue=character.with_dialogue,
        attribution_publication=attribution.publication,
        attribution_completed_at=attribution.completed_at,
        characters_unavailable=character.unavailable,
        characters_matched=character.matched,
        characters_partially_matched=character.partially_matched,
        characters_missing_dialogue=character.missing_dialogue,
        characters_dialogue_failed=character.dialogue_failed,
        characters_without_dialogue=character.without_dialogue,
        dialogues_total=dialogue.total,
        dialogues_complete=dialogue.complete,
        dialogue_lines=dialogue.lines,
        line_records_total=tables.line_records,
        voices_total=len(attribution.voices),
        character_sounds_total=tables.character_sounds,
        soundset_lines_total=tables.soundset_lines,
        transition_edges_total=tables.transition_edges,
        character_resource_links_total=tables.character_resource_links,
        interaction_rules_total=tables.interaction_rules,
        engine_strings_total=tables.engine_strings,
        sound_slot_groups_total=tables.sound_slot_groups,
        favored_enemies_total=tables.favored_enemies,
        happiness_rules_total=tables.happiness_rules,
        banter_timing_settings_total=tables.banter_timing_settings,
        races_total=metadata_counts.races,
        classes_total=metadata_counts.classes,
        kits_total=metadata_counts.kits,
        identifiers_total=metadata_counts.identifiers,
        campaigns_total=metadata_counts.campaigns,
        dialogues_attributed=dialogue.attributed,
        dialogues_unattributed=dialogue.unattributed,
        attributed_dialogue_lines=dialogue.attributed_lines,
        unattributed_dialogue_lines=dialogue.unattributed_lines,
        latest_runs=[
            ExtractionRunSummary.model_validate(run, from_attributes=True) for run in latest_runs
        ],
    )


def _character_stats(
    characters: list[CharacterRecord],
    attribution: AttributionSnapshot,
) -> _CharacterStats:
    statuses = Counter(row.status for row in attribution.by_character.values())
    return _CharacterStats(
        total=len(characters),
        complete=sum(row.extraction.status is DetailStatus.COMPLETE for row in characters),
        failed=sum(row.extraction.status is DetailStatus.FAILED for row in characters),
        with_dialogue=sum(
            row.detail is not None and row.detail.dialog_resref is not None for row in characters
        ),
        unavailable=statuses[AttributionStatus.CHARACTER_UNAVAILABLE],
        matched=statuses[AttributionStatus.MATCHED],
        partially_matched=statuses[AttributionStatus.PARTIAL_MATCH],
        missing_dialogue=statuses[AttributionStatus.MISSING_DIALOGUE],
        dialogue_failed=sum(
            row.dialogue_status is DetailStatus.FAILED for row in attribution.by_character.values()
        ),
        without_dialogue=statuses[AttributionStatus.NO_DIALOGUE],
    )


def _dialogue_stats(
    dialogues: list[DialogueRecord],
    attribution: AttributionSnapshot,
) -> _DialogueStats:
    attributed = [
        row
        for row in dialogues
        if attribution.character_count_by_dialogue[row.resource_name.casefold()] > 0
    ]
    unattributed = [
        row
        for row in dialogues
        if attribution.character_count_by_dialogue[row.resource_name.casefold()] == 0
    ]
    return _DialogueStats(
        total=len(dialogues),
        complete=sum(row.extraction.status is DetailStatus.COMPLETE for row in dialogues),
        lines=_line_count(dialogues),
        attributed=len(attributed),
        unattributed=len(unattributed),
        attributed_lines=_line_count(attributed),
        unattributed_lines=_line_count(unattributed),
    )


def _line_count(dialogues: list[DialogueRecord]) -> int:
    return sum(row.detail.dialogue_line_count for row in dialogues if row.detail is not None)


def _metadata_stats(metadata: MetadataSnapshot) -> _MetadataStats:
    return _MetadataStats(
        races=len(
            {row.value for row in metadata.identifiers if row.kind is IdentifierKind.RACE}
            | {row.race_id for row in metadata.race_texts}
        ),
        classes=len(
            {row.value for row in metadata.identifiers if row.kind is IdentifierKind.CLASS}
            | {row.class_id for row in metadata.class_texts}
        ),
        kits=len(metadata.kits),
        identifiers=sum(row.kind in SIMPLE_IDENTIFIER_KINDS for row in metadata.identifiers),
        campaigns=len(metadata.campaigns),
    )
