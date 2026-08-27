"""Typed, read-only LanceDB queries for pipeline inspection."""

import asyncio
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from operator import attrgetter
from pathlib import Path
from typing import Literal, cast

import lancedb
from lancedb.db import AsyncConnection
from lancedb.expr import Expr, col, lit
from lancedb.pydantic import LanceModel
from lancedb.query import (
    BooleanQuery,
    ColumnOrdering,
    FullTextOperator,
    MatchQuery,
    Occur,
)
from lancedb.table import AsyncTable
from pydantic import BaseModel, ConfigDict, Field

from bgvoice.database import (
    TABLE_MODELS,
    CampaignDefinitionRecord,
    CampaignResourceBindingRecord,
    CharacterAttributionRecord,
    CharacterRecord,
    CharacterSoundRecord,
    ClassTextRecord,
    DialogueData,
    DialogueLineRecord,
    DialogueRecord,
    DialogueTransitionRecord,
    ExtractionRunRecord,
    FavoredEnemyRecord,
    IdentifierDefinitionRecord,
    KitDefinitionRecord,
    RaceTextRecord,
    SoundSlotGroupRecord,
    VoiceResourceRecord,
)
from bgvoice.models import (
    AttributionPublicationStatus,
    AttributionStatus,
    CampaignResourceKind,
    DetailStatus,
    DialogueLineKind,
    IdentifierKind,
    RunKind,
    RunStatus,
    SourceKind,
    VoiceId,
    VoiceResource,
)

type CharacterSort = Literal[
    "resource_name",
    "display_name",
    "source_kind",
    "serialized_size",
    "dialogue_line_count",
    "npc_line_count",
    "player_line_count",
    "dialogue_state_count",
    "dialogue_transition_count",
    "updated_at",
]
type DialogueSort = Literal[
    "resource_name",
    "source_kind",
    "serialized_size",
    "dialogue_line_count",
    "npc_line_count",
    "player_line_count",
    "character_count",
    "updated_at",
]
type LineSort = Literal[
    "dialogue_resource_name",
    "line_kind",
    "strref",
    "serialized_size",
    "state_index",
    "transition_index",
]
type SortDirection = Literal["asc", "desc"]
type StableColumn = Literal["resource_name", "id", "key"]
type ChildParentColumn = Literal["character_resource_name", "dialogue_resource_name"]
type RaceSort = Literal["race_id", "row_name", "name", "source_resource"]
type ClassSort = Literal["class_id", "row_name", "lower_name", "fallen"]
type KitSort = Literal["row_id", "row_name", "lower_name", "class_id"]
type IdentifierSort = Literal["kind", "value", "source_resource"]
type VoiceSort = Literal[
    "display_name",
    "variant_count",
    "dialogue_count",
    "npc_line_count",
    "serialized_size",
]
type SoundSort = Literal[
    "character_resource_name",
    "slot_id",
    "strref",
    "serialized_size",
]
type TransitionSort = Literal[
    "location",
    "dialogue_resource_name",
    "state_index",
    "transition_index",
    "serialized_size",
]
type SimpleIdentifierKind = Literal[
    IdentifierKind.GENDER,
    IdentifierKind.ALIGNMENT,
    IdentifierKind.ENEMY_ALLY,
    IdentifierKind.GENERAL,
    IdentifierKind.SPECIFIC,
    IdentifierKind.ANIMATION,
    IdentifierKind.SOUND_SLOT,
]

_SEARCH_TOKEN = re.compile(r"[\w-]+", re.UNICODE)


class _ReaderModel(BaseModel):
    """Strict projection returned by the pipeline reader."""

    model_config = ConfigDict(strict=True, extra="forbid")


class PageQuery(BaseModel):
    """Internal page window used by LanceDB browse queries."""

    model_config = ConfigDict(strict=False, extra="forbid")

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=10, le=100)


class CharacterQuery(PageQuery):
    q: str | None = Field(default=None, max_length=200)
    status: DetailStatus | None = None
    source_kind: SourceKind | None = None
    has_dialog: bool | None = None
    gender_id: int | None = Field(default=None, ge=0)
    race_id: int | None = Field(default=None, ge=0)
    class_id: int | None = Field(default=None, ge=0)
    attribution_status: AttributionStatus | None = None
    sort: CharacterSort | None = None
    direction: SortDirection = "desc"


class DialogueQuery(PageQuery):
    q: str | None = Field(default=None, max_length=200)
    status: DetailStatus | None = None
    source_kind: SourceKind | None = None
    attributed: bool | None = None
    sort: DialogueSort | None = None
    direction: SortDirection = "desc"


class LineQuery(PageQuery):
    q: str | None = Field(default=None, max_length=300)
    line_kind: DialogueLineKind | None = None
    source_kind: SourceKind | None = None
    attributed: bool | None = None
    sort: LineSort | None = None
    direction: SortDirection = "desc"


class RaceQuery(PageQuery):
    q: str | None = Field(default=None, max_length=300)
    campaign: str | None = Field(default=None, max_length=64)
    sort: RaceSort | None = None
    direction: SortDirection = "asc"


class ClassQuery(PageQuery):
    q: str | None = Field(default=None, max_length=300)
    campaign: str | None = Field(default=None, max_length=64)
    fallen: bool | None = None
    class_id: int | None = Field(default=None, ge=0)
    sort: ClassSort | None = None
    direction: SortDirection = "asc"


class KitQuery(PageQuery):
    q: str | None = Field(default=None, max_length=300)
    class_id: int | None = Field(default=None, ge=0)
    sort: KitSort | None = None
    direction: SortDirection = "asc"


class IdentifierQuery(PageQuery):
    q: str | None = Field(default=None, max_length=300)
    kind: SimpleIdentifierKind | None = None
    sort: IdentifierSort | None = None
    direction: SortDirection = "asc"


class VoiceQuery(PageQuery):
    q: str | None = Field(default=None, max_length=300)
    voice_id: str | None = Field(default=None, min_length=1, max_length=300)
    sort: VoiceSort | None = None
    direction: SortDirection = "desc"


class SoundQuery(PageQuery):
    q: str | None = Field(default=None, max_length=300)
    slot_id: int | None = Field(default=None, ge=0, le=0xFF)
    sort: SoundSort | None = None
    direction: SortDirection = "desc"


class TransitionQuery(PageQuery):
    q: str | None = Field(default=None, max_length=500)
    terminates_dialog: bool | None = None
    sort: TransitionSort | None = None
    direction: SortDirection = "asc"


class CharacterRow(_ReaderModel):
    resource_name: str
    display_name: str | None
    voice_id: str | None
    resref: str
    source_kind: SourceKind
    dialog_resref: str | None
    gender_id: int | None
    gender_label: str | None
    race_id: int | None
    race_label: str | None
    class_id: int | None
    class_label: str | None
    alignment_id: int | None
    alignment_label: str | None
    enemy_ally_id: int | None
    enemy_ally_label: str | None
    general_id: int | None
    general_label: str | None
    specific_id: int | None
    specific_label: str | None
    animation_id: int | None
    animation_label: str | None
    racial_enemy_id: int | None
    racial_enemy_label: str | None
    cre_kit_value: int | None
    kit_ids_value: int | None
    kit_label: str | None
    first_class_level: int | None
    second_class_level: int | None
    third_class_level: int | None
    detail_status: DetailStatus
    detail_error: str | None
    attribution_status: AttributionStatus | None
    serialized_size: int | None
    dialogue_status: DetailStatus | None
    declared_dialogue_count: int | None
    resolved_dialogue_count: int | None
    dialogue_line_count: int | None
    npc_line_count: int | None
    player_line_count: int | None
    journal_line_count: int | None
    dialogue_state_count: int | None
    dialogue_transition_count: int | None
    dialogue_serialized_size: int | None
    updated_at: str


class CharacterPage(_ReaderModel):
    items: list[CharacterRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: CharacterSort | Literal["relevance"]
    direction: SortDirection


class DialogueRow(_ReaderModel):
    resource_name: str
    resref: str
    source_kind: SourceKind
    source_path: str
    detail_status: DetailStatus
    detail_error: str | None
    serialized_size: int | None
    dialogue_line_count: int | None
    npc_line_count: int | None
    player_line_count: int | None
    journal_line_count: int | None
    character_count: int
    updated_at: str


class DialoguePage(_ReaderModel):
    items: list[DialogueRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: DialogueSort | Literal["relevance"]
    direction: SortDirection


class DialogueLineRow(_ReaderModel):
    id: str
    dialogue_resource_name: str
    dialogue_resref: str
    source_kind: SourceKind
    line_kind: DialogueLineKind
    state_index: int
    state_trigger_index: int | None
    state_trigger_text: str | None
    transition_index: int | None
    strref: int
    text: str | None
    tokens: list[str]
    serialized_size: int
    character_count: int


class DialogueLinePage(_ReaderModel):
    items: list[DialogueLineRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: LineSort | Literal["relevance"]
    direction: SortDirection


class VoiceRow(_ReaderModel):
    id: str
    display_name: str
    prompt: str
    variant_resource_names: list[str]
    dialogue_resrefs: list[str]
    variant_count: int
    dialogue_count: int
    npc_line_count: int
    serialized_size: int


class VoicePage(_ReaderModel):
    items: list[VoiceRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: VoiceSort | Literal["relevance"]
    direction: SortDirection


class SoundRow(_ReaderModel):
    key: str
    character_resource_name: str
    character_name: str
    slot_id: int
    slot_symbols: list[str]
    slot_groups: list[str]
    strref: int
    text: str | None
    serialized_size: int


class SoundPage(_ReaderModel):
    items: list[SoundRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: SoundSort | Literal["relevance"]
    direction: SortDirection


class TransitionRow(_ReaderModel):
    id: str
    dialogue_resource_name: str
    dialogue_resref: str
    source_kind: SourceKind
    state_index: int
    transition_index: int
    flags_raw: int
    flags_decoded: list[str]
    trigger_index: int | None
    trigger_text: str | None
    action_index: int | None
    action_text: str | None
    next_dialog: str | None
    next_state_index: int | None
    terminates_dialog: bool
    serialized_size: int


class TransitionPage(_ReaderModel):
    items: list[TransitionRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: TransitionSort | Literal["relevance"]
    direction: SortDirection


class RaceRow(_ReaderModel):
    key: str
    race_id: int
    symbols: list[str]
    source_resource: str | None
    ordinal: int | None
    campaigns: list[str]
    row_name: str | None
    name_strref: int | None
    name: str | None
    description_strref: int | None
    description: str | None
    uppercase_name_strref: int | None
    uppercase_name: str | None
    biography_strref: int | None
    biography: str | None


class RacePage(_ReaderModel):
    items: list[RaceRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: RaceSort | Literal["relevance"]
    direction: SortDirection


class ClassRow(_ReaderModel):
    key: str
    class_id: int
    symbols: list[str]
    source_resource: str | None
    ordinal: int | None
    campaigns: list[str]
    row_name: str | None
    class_text_kit_id: int | None
    lower_name_strref: int | None
    lower_name: str | None
    description_strref: int | None
    description: str | None
    mixed_name_strref: int | None
    mixed_name: str | None
    biography_strref: int | None
    biography: str | None
    fallen: bool | None
    brief_description_strref: int | None
    brief_description: str | None
    fallen_notice_strref: int | None
    fallen_notice: str | None


class ClassPage(_ReaderModel):
    items: list[ClassRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: ClassSort | Literal["relevance"]
    direction: SortDirection


class KitRow(_ReaderModel):
    key: str
    source_resource: str
    ordinal: int
    row_id: int
    row_name: str
    lower_name_strref: int | None
    lower_name: str | None
    mixed_name_strref: int | None
    mixed_name: str | None
    help_strref: int | None
    help_text: str | None
    abilities_resref: str | None
    proficiency_column: int | None
    unusable_mask: int | None
    class_id: int | None
    class_symbols: list[str]
    kit_ids_value: int | None
    kit_symbols: list[str]
    class_text_kit_id: int | None


class KitPage(_ReaderModel):
    items: list[KitRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: KitSort | Literal["relevance"]
    direction: SortDirection


class IdentifierRow(_ReaderModel):
    key: str
    kind: SimpleIdentifierKind
    value: int
    symbols: list[str]
    source_resource: str


class IdentifierPage(_ReaderModel):
    items: list[IdentifierRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: IdentifierSort | Literal["relevance"]
    direction: SortDirection


class ExtractionRunSummary(_ReaderModel):
    id: str
    run_kind: RunKind
    started_at: str
    completed_at: str | None
    status: RunStatus
    resources_discovered: int
    details_attempted: int
    details_extracted: int
    failures: int
    error: str | None


class PipelineStats(_ReaderModel):
    database_path: str
    database_size: int = Field(ge=0)
    characters_total: int = Field(ge=0)
    characters_complete: int = Field(ge=0)
    characters_failed: int = Field(ge=0)
    characters_with_dialogue: int = Field(ge=0)
    attribution_publication: AttributionPublicationStatus
    attribution_completed_at: str | None
    characters_unavailable: int = Field(ge=0)
    characters_matched: int = Field(ge=0)
    characters_partially_matched: int = Field(ge=0)
    characters_missing_dialogue: int = Field(ge=0)
    characters_dialogue_failed: int = Field(ge=0)
    characters_without_dialogue: int = Field(ge=0)
    dialogues_total: int = Field(ge=0)
    dialogues_complete: int = Field(ge=0)
    dialogue_lines: int = Field(ge=0)
    line_records_total: int = Field(ge=0)
    voices_total: int = Field(ge=0)
    character_sounds_total: int = Field(ge=0)
    soundset_lines_total: int = Field(ge=0)
    transition_edges_total: int = Field(ge=0)
    character_resource_links_total: int = Field(ge=0)
    interaction_rules_total: int = Field(ge=0)
    engine_strings_total: int = Field(ge=0)
    sound_slot_groups_total: int = Field(ge=0)
    favored_enemies_total: int = Field(ge=0)
    happiness_rules_total: int = Field(ge=0)
    banter_timing_settings_total: int = Field(ge=0)
    races_total: int = Field(ge=0)
    classes_total: int = Field(ge=0)
    kits_total: int = Field(ge=0)
    identifiers_total: int = Field(ge=0)
    campaigns_total: int = Field(ge=0)
    dialogues_attributed: int = Field(ge=0)
    dialogues_unattributed: int = Field(ge=0)
    attributed_dialogue_lines: int = Field(ge=0)
    unattributed_dialogue_lines: int = Field(ge=0)
    latest_runs: list[ExtractionRunSummary]


class _Projection(LanceModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class _CharacterSearchResult(CharacterRecord):
    score: float = Field(alias="_score")


class _DialogueSearchResult(DialogueRecord):
    score: float = Field(alias="_score")


class _VoiceSearchResult(VoiceResourceRecord):
    score: float = Field(alias="_score")


class _MetadataScore(_Projection):
    key: str
    score: float = Field(alias="_score")


_SIMPLE_IDENTIFIER_KINDS: tuple[SimpleIdentifierKind, ...] = (
    IdentifierKind.GENDER,
    IdentifierKind.ALIGNMENT,
    IdentifierKind.ENEMY_ALLY,
    IdentifierKind.GENERAL,
    IdentifierKind.SPECIFIC,
    IdentifierKind.ANIMATION,
    IdentifierKind.SOUND_SLOT,
)


@dataclass(frozen=True, slots=True)
class _MetadataSnapshot:
    identifiers: list[IdentifierDefinitionRecord]
    campaigns: list[CampaignDefinitionRecord]
    bindings: list[CampaignResourceBindingRecord]
    race_texts: list[RaceTextRecord]
    class_texts: list[ClassTextRecord]
    kits: list[KitDefinitionRecord]
    favored_enemies: list[FavoredEnemyRecord]


@dataclass(frozen=True, slots=True)
class _AttributionSnapshot:
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
class _CharacterDialogueMetrics:
    attribution_status: AttributionStatus | None = None
    dialogue_status: DetailStatus | None = None
    declared_dialogue_count: int | None = None
    resolved_dialogue_count: int | None = None
    dialogue_line_count: int | None = None
    npc_line_count: int | None = None
    player_line_count: int | None = None
    journal_line_count: int | None = None
    dialogue_state_count: int | None = None
    dialogue_transition_count: int | None = None
    dialogue_serialized_size: int | None = None


@dataclass(frozen=True, slots=True)
class PipelineReader:
    """Strongly consistent typed reads over one local LanceDB database."""

    path: Path
    _connection: AsyncConnection
    characters_table: AsyncTable
    character_sounds_table: AsyncTable
    portrait_images_table: AsyncTable
    character_dialogues_table: AsyncTable
    voices_table: AsyncTable
    dialogues_table: AsyncTable
    lines_table: AsyncTable
    transitions_table: AsyncTable
    runs_table: AsyncTable
    identifiers_table: AsyncTable
    campaigns_table: AsyncTable
    bindings_table: AsyncTable
    character_resource_links_table: AsyncTable
    interaction_rules_table: AsyncTable
    soundset_lines_table: AsyncTable
    sound_slot_groups_table: AsyncTable
    favored_enemies_table: AsyncTable
    happiness_rules_table: AsyncTable
    banter_timing_settings_table: AsyncTable
    engine_strings_table: AsyncTable
    race_texts_table: AsyncTable
    class_texts_table: AsyncTable
    kits_table: AsyncTable

    @classmethod
    async def open(cls, path: Path) -> PipelineReader:
        resolved_path = path.expanduser().resolve()
        assert resolved_path.is_dir(), f"pipeline database does not exist: {resolved_path}"
        connection = await lancedb.connect_async(
            resolved_path,
            read_consistency_interval=timedelta(0),
        )
        names = tuple(TABLE_MODELS)
        table_names = frozenset((await connection.list_tables(limit=None)).tables)
        missing = frozenset(names) - table_names
        assert not missing, f"pipeline database is missing tables: {sorted(missing)}"
        opened = await asyncio.gather(*(connection.open_table(name) for name in names))
        tables = dict(zip(names, opened, strict=True))
        return cls(
            resolved_path,
            connection,
            tables["characters"],
            tables["character_sounds"],
            tables["portrait_images"],
            tables["character_dialogues"],
            tables["voice_resources"],
            tables["dialogues"],
            tables["dialogue_lines"],
            tables["dialogue_transitions"],
            tables["extraction_runs"],
            tables["identifier_definitions"],
            tables["campaigns"],
            tables["campaign_resource_bindings"],
            tables["character_resource_links"],
            tables["interaction_rules"],
            tables["soundset_lines"],
            tables["sound_slot_groups"],
            tables["favored_enemies"],
            tables["happiness_rules"],
            tables["banter_timing_settings"],
            tables["engine_strings"],
            tables["race_texts"],
            tables["class_texts"],
            tables["kits"],
        )

    def close(self) -> None:
        self._connection.close()

    async def _metadata_snapshot(self) -> _MetadataSnapshot:
        rows = await asyncio.gather(
            self.identifiers_table.query().to_pydantic(IdentifierDefinitionRecord),
            self.campaigns_table.query().to_pydantic(CampaignDefinitionRecord),
            self.bindings_table.query().to_pydantic(CampaignResourceBindingRecord),
            self.race_texts_table.query().to_pydantic(RaceTextRecord),
            self.class_texts_table.query().to_pydantic(ClassTextRecord),
            self.kits_table.query().to_pydantic(KitDefinitionRecord),
            self.favored_enemies_table.query().to_pydantic(FavoredEnemyRecord),
        )
        return _MetadataSnapshot(
            identifiers=cast(list[IdentifierDefinitionRecord], rows[0]),
            campaigns=cast(list[CampaignDefinitionRecord], rows[1]),
            bindings=cast(list[CampaignResourceBindingRecord], rows[2]),
            race_texts=cast(list[RaceTextRecord], rows[3]),
            class_texts=cast(list[ClassTextRecord], rows[4]),
            kits=cast(list[KitDefinitionRecord], rows[5]),
            favored_enemies=cast(list[FavoredEnemyRecord], rows[6]),
        )

    async def _attribution_snapshot(self) -> _AttributionSnapshot:
        runs = cast(
            list[ExtractionRunRecord],
            await self.runs_table.query().to_pydantic(ExtractionRunRecord),
        )
        completed = [
            run
            for run in runs
            if run.run_kind is RunKind.ATTRIBUTION and run.status is RunStatus.COMPLETE
        ]
        if not completed:
            return _empty_attribution_snapshot(AttributionPublicationStatus.MISSING)
        run = max(completed, key=_completed_run_order)
        latest_inputs = {
            kind: _latest_run_id(runs, kind)
            for kind in (RunKind.CHARACTERS, RunKind.DIALOGUES, RunKind.METADATA)
        }
        if latest_inputs != {
            RunKind.CHARACTERS: run.character_input_run_id,
            RunKind.DIALOGUES: run.dialogue_input_run_id,
            RunKind.METADATA: run.metadata_input_run_id,
        }:
            return _empty_attribution_snapshot(AttributionPublicationStatus.STALE)

        attribution_rows, voice_rows = await asyncio.gather(
            self.character_dialogues_table.query()
            .where(col("run_id") == lit(run.id))
            .to_pydantic(CharacterAttributionRecord),
            self.voices_table.query()
            .where(col("run_id") == lit(run.id))
            .to_pydantic(VoiceResourceRecord),
        )
        attributions = cast(list[CharacterAttributionRecord], attribution_rows)
        voices = cast(list[VoiceResourceRecord], voice_rows)
        by_character = {row.character_resource_name.casefold(): row for row in attributions}
        assert len(by_character) == len(attributions), (
            "published attribution contains duplicate character rows"
        )
        character_count_by_dialogue: Counter[str] = Counter()
        for row in attributions:
            character_count_by_dialogue.update(
                name.casefold() for name in row.resolved_dialogue_resource_names
            )
        voice_by_character: dict[str, VoiceResourceRecord] = {}
        for voice in voices:
            for resource_name in voice.variant_resource_names:
                key = resource_name.casefold()
                assert key not in voice_by_character, (
                    f"published voices assign {resource_name!r} more than once"
                )
                voice_by_character[key] = voice
        return _AttributionSnapshot(
            publication=AttributionPublicationStatus.PUBLISHED,
            run=run,
            by_character=by_character,
            character_count_by_dialogue=character_count_by_dialogue,
            voices=voices,
            voice_by_character=voice_by_character,
        )

    async def stats(self) -> PipelineStats:
        character_rows, dialogue_rows, run_rows, metadata = await asyncio.gather(
            self.characters_table.query().to_pydantic(CharacterRecord),
            self.dialogues_table.query().to_pydantic(DialogueRecord),
            self.runs_table.query()
            .order_by(
                [
                    ColumnOrdering(column_name="started_at", ascending=False, nulls_first=False),
                    ColumnOrdering(column_name="id", ascending=False, nulls_first=False),
                ]
            )
            .limit(8)
            .to_pydantic(ExtractionRunRecord),
            self._metadata_snapshot(),
        )
        characters = cast(list[CharacterRecord], character_rows)
        dialogues = cast(list[DialogueRecord], dialogue_rows)
        attribution = await self._attribution_snapshot()
        character_children = _child_generation_predicate(
            "character_resource_name",
            (
                (row.resource_name, row.extraction.run_id)
                for row in characters
                if row.extraction.status is DetailStatus.COMPLETE
            ),
        )
        dialogue_children = _child_generation_predicate(
            "dialogue_resource_name",
            (
                (row.resource_name, row.extraction.run_id)
                for row in dialogues
                if row.extraction.status is DetailStatus.COMPLETE
            ),
        )
        (
            character_sounds_total,
            soundset_lines_total,
            line_records_total,
            transition_edges_total,
            character_resource_links_total,
            interaction_rules_total,
            engine_strings_total,
            sound_slot_groups_total,
            favored_enemies_total,
            happiness_rules_total,
            banter_timing_settings_total,
        ) = await asyncio.gather(
            _count_rows(self.character_sounds_table, character_children),
            self.soundset_lines_table.count_rows(),
            _count_rows(self.lines_table, dialogue_children),
            _count_rows(self.transitions_table, dialogue_children),
            self.character_resource_links_table.count_rows(),
            self.interaction_rules_table.count_rows(),
            self.engine_strings_table.count_rows(),
            self.sound_slot_groups_table.count_rows(),
            self.favored_enemies_table.count_rows(),
            self.happiness_rules_table.count_rows(),
            self.banter_timing_settings_table.count_rows(),
        )
        latest_runs = cast(list[ExtractionRunRecord], run_rows)
        attribution_counts = Counter(row.status for row in attribution.by_character.values())
        attributed_dialogues = [
            row
            for row in dialogues
            if attribution.character_count_by_dialogue[row.resource_name.casefold()] > 0
        ]
        unattributed_dialogues = [
            row
            for row in dialogues
            if attribution.character_count_by_dialogue[row.resource_name.casefold()] == 0
        ]

        return PipelineStats(
            database_path=str(self.path),
            database_size=sum(
                file.stat().st_size for file in self.path.rglob("*") if file.is_file()
            ),
            characters_total=len(characters),
            characters_complete=sum(
                row.extraction.status is DetailStatus.COMPLETE for row in characters
            ),
            characters_failed=sum(
                row.extraction.status is DetailStatus.FAILED for row in characters
            ),
            characters_with_dialogue=sum(
                row.detail is not None and row.detail.dialog_resref is not None
                for row in characters
            ),
            attribution_publication=attribution.publication,
            attribution_completed_at=attribution.completed_at,
            characters_unavailable=attribution_counts[AttributionStatus.CHARACTER_UNAVAILABLE],
            characters_matched=attribution_counts[AttributionStatus.MATCHED],
            characters_partially_matched=attribution_counts[AttributionStatus.PARTIAL_MATCH],
            characters_missing_dialogue=attribution_counts[AttributionStatus.MISSING_DIALOGUE],
            characters_dialogue_failed=sum(
                row.dialogue_status is DetailStatus.FAILED
                for row in attribution.by_character.values()
            ),
            characters_without_dialogue=attribution_counts[AttributionStatus.NO_DIALOGUE],
            dialogues_total=len(dialogues),
            dialogues_complete=sum(
                row.extraction.status is DetailStatus.COMPLETE for row in dialogues
            ),
            dialogue_lines=sum(
                _dialogue_metric(row, lambda detail: detail.dialogue_line_count)
                for row in dialogues
            ),
            line_records_total=line_records_total,
            voices_total=len(attribution.voices),
            character_sounds_total=character_sounds_total,
            soundset_lines_total=soundset_lines_total,
            transition_edges_total=transition_edges_total,
            character_resource_links_total=character_resource_links_total,
            interaction_rules_total=interaction_rules_total,
            engine_strings_total=engine_strings_total,
            sound_slot_groups_total=sound_slot_groups_total,
            favored_enemies_total=favored_enemies_total,
            happiness_rules_total=happiness_rules_total,
            banter_timing_settings_total=banter_timing_settings_total,
            races_total=len(
                {row.value for row in metadata.identifiers if row.kind is IdentifierKind.RACE}
                | {row.race_id for row in metadata.race_texts}
            ),
            classes_total=len(
                {row.value for row in metadata.identifiers if row.kind is IdentifierKind.CLASS}
                | {row.class_id for row in metadata.class_texts}
            ),
            kits_total=len(metadata.kits),
            identifiers_total=sum(
                row.kind in _SIMPLE_IDENTIFIER_KINDS for row in metadata.identifiers
            ),
            campaigns_total=len(metadata.campaigns),
            dialogues_attributed=len(attributed_dialogues),
            dialogues_unattributed=len(unattributed_dialogues),
            attributed_dialogue_lines=sum(
                _dialogue_metric(row, lambda detail: detail.dialogue_line_count)
                for row in attributed_dialogues
            ),
            unattributed_dialogue_lines=sum(
                _dialogue_metric(row, lambda detail: detail.dialogue_line_count)
                for row in unattributed_dialogues
            ),
            latest_runs=[
                ExtractionRunSummary.model_validate(run, from_attributes=True)
                for run in latest_runs
            ],
        )

    async def characters(self, query: CharacterQuery) -> CharacterPage:
        tokens = _search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "serialized_size")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        matches, dialogue_rows, metadata = await asyncio.gather(
            _records_all(
                table=self.characters_table,
                model=CharacterRecord,
                search_model=_CharacterSearchResult,
                tokens=tokens,
                predicate=None,
                key_of=lambda row: row.resource_name,
                score_of=lambda row: row.score,
            ),
            self.dialogues_table.query().to_pydantic(DialogueRecord),
            self._metadata_snapshot(),
        )
        records, scores = matches
        attribution = await self._attribution_snapshot()
        dialogues = {
            row.resource_name.casefold(): row for row in cast(list[DialogueRecord], dialogue_rows)
        }
        labels = _LabelResolver.from_snapshot(metadata)
        rows: list[CharacterRow] = []
        for record in records:
            key = record.resource_name.casefold()
            character_attribution = attribution.by_character.get(key)
            voice = attribution.voice_by_character.get(key)
            rows.append(
                _character_row(
                    record,
                    character_attribution,
                    voice,
                    dialogues,
                    labels,
                )
            )
        if query.status is not None:
            rows = [row for row in rows if row.detail_status is query.status]
        if query.source_kind is not None:
            rows = [row for row in rows if row.source_kind is query.source_kind]
        if query.gender_id is not None:
            rows = [row for row in rows if row.gender_id == query.gender_id]
        if query.race_id is not None:
            rows = [row for row in rows if row.race_id == query.race_id]
        if query.class_id is not None:
            rows = [row for row in rows if row.class_id == query.class_id]
        if query.attribution_status is not None:
            rows = [row for row in rows if row.attribution_status is query.attribution_status]
        if query.has_dialog is not None:
            rows = [row for row in rows if (row.dialog_resref is not None) is query.has_dialog]
        rows = (
            _relevance_order(rows, scores, lambda row: row.resource_name)
            if sort == "relevance"
            else _metadata_order(rows, sort, direction, lambda row: row.resource_name)
        )

        return CharacterPage(
            items=_page_items(rows, query),
            page=query.page,
            page_size=query.page_size,
            total=len(rows),
            page_count=_page_count(len(rows), query.page_size),
            sort=sort,
            direction=direction,
        )

    async def dialogues(self, query: DialogueQuery) -> DialoguePage:
        tokens = _search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "dialogue_line_count")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        records, scores = await _records_all(
            table=self.dialogues_table,
            model=DialogueRecord,
            search_model=_DialogueSearchResult,
            tokens=tokens,
            predicate=None,
            key_of=lambda row: row.resource_name,
            score_of=lambda row: row.score,
        )
        attribution = await self._attribution_snapshot()
        rows = [
            _dialogue_row(
                record,
                attribution.character_count_by_dialogue[record.resource_name.casefold()],
            )
            for record in records
        ]
        if query.status is not None:
            rows = [row for row in rows if row.detail_status is query.status]
        if query.source_kind is not None:
            rows = [row for row in rows if row.source_kind is query.source_kind]
        if query.attributed is not None:
            rows = [row for row in rows if (row.character_count > 0) is query.attributed]
        rows = (
            _relevance_order(rows, scores, lambda row: row.resource_name)
            if sort == "relevance"
            else _metadata_order(rows, sort, direction, lambda row: row.resource_name)
        )

        return DialoguePage(
            items=_page_items(rows, query),
            page=query.page,
            page_size=query.page_size,
            total=len(rows),
            page_count=_page_count(len(rows), query.page_size),
            sort=sort,
            direction=direction,
        )

    async def lines(self, query: LineQuery) -> DialogueLinePage:
        dialogue_rows = cast(
            list[DialogueRecord],
            await self.dialogues_table.query().to_pydantic(DialogueRecord),
        )
        attribution = await self._attribution_snapshot()
        dialogues = {row.resource_name.casefold(): row for row in dialogue_rows}
        allowed_dialogues = [
            dialogue
            for dialogue in dialogues.values()
            if dialogue.extraction.status is DetailStatus.COMPLETE
            and (query.source_kind is None or dialogue.source.kind is query.source_kind)
            and (
                query.attributed is None
                or (attribution.character_count_by_dialogue[dialogue.resource_name.casefold()] > 0)
                is query.attributed
            )
        ]
        tokens = _search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "serialized_size")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        child_generation = _child_generation_predicate(
            "dialogue_resource_name",
            (
                (dialogue.resource_name, dialogue.extraction.run_id)
                for dialogue in allowed_dialogues
            ),
        )
        if child_generation is None:
            return DialogueLinePage(
                items=[],
                page=query.page,
                page_size=query.page_size,
                total=0,
                page_count=1,
                sort=sort,
                direction=direction,
            )
        conditions = [child_generation]
        if query.line_kind is not None:
            conditions.append(col("line_kind") == lit(query.line_kind))
        predicate = _combine(conditions)
        total, records = await _records_page(
            table=self.lines_table,
            model=DialogueLineRecord,
            stable_column="id",
            predicate=predicate,
            tokens=tokens,
            ordering=None if sort == "relevance" else _ordering(sort, direction, "id"),
            page=query,
        )

        return DialogueLinePage(
            items=[
                _dialogue_line_row(
                    record,
                    dialogues[record.dialogue_resource_name.casefold()],
                    attribution.character_count_by_dialogue[
                        record.dialogue_resource_name.casefold()
                    ],
                )
                for record in records
            ],
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=_page_count(total, query.page_size),
            sort=sort,
            direction=direction,
        )

    async def voices(self, query: VoiceQuery) -> VoicePage:
        tokens = _search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "npc_line_count")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        dialogue_rows = cast(
            list[DialogueRecord],
            await self.dialogues_table.query().to_pydantic(DialogueRecord),
        )
        attribution = await self._attribution_snapshot()
        if attribution.run is None:
            records: list[VoiceResourceRecord] = []
            scores: dict[str, float] = {}
        else:
            records, scores = await _records_all(
                table=self.voices_table,
                model=VoiceResourceRecord,
                search_model=_VoiceSearchResult,
                tokens=tokens,
                predicate=col("run_id") == lit(attribution.run.id),
                key_of=lambda row: row.voice_id,
                score_of=lambda row: row.score,
            )
        dialogues_by_resref = {row.resref.casefold(): row for row in dialogue_rows}
        rows = [_voice_row(record, dialogues_by_resref) for record in records]
        if query.voice_id is not None:
            rows = [row for row in rows if row.id == query.voice_id]
        rows = (
            _relevance_order(rows, scores, lambda row: row.id)
            if sort == "relevance"
            else _metadata_order(rows, sort, direction, lambda row: row.id)
        )
        return VoicePage(
            items=_page_items(rows, query),
            page=query.page,
            page_size=query.page_size,
            total=len(rows),
            page_count=_page_count(len(rows), query.page_size),
            sort=sort,
            direction=direction,
        )

    async def sounds(self, query: SoundQuery) -> SoundPage:
        character_rows, group_rows, metadata = await asyncio.gather(
            self.characters_table.query().to_pydantic(CharacterRecord),
            self.sound_slot_groups_table.query().to_pydantic(SoundSlotGroupRecord),
            self._metadata_snapshot(),
        )
        characters = cast(list[CharacterRecord], character_rows)
        groups = cast(list[SoundSlotGroupRecord], group_rows)
        complete_characters = [
            character
            for character in characters
            if character.extraction.status is DetailStatus.COMPLETE
        ]
        sound_generation = _child_generation_predicate(
            "character_resource_name",
            (
                (character.resource_name, character.extraction.run_id)
                for character in complete_characters
            ),
        )
        tokens = _search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "serialized_size")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        if sound_generation is None:
            return SoundPage(
                items=[],
                page=query.page,
                page_size=query.page_size,
                total=0,
                page_count=1,
                sort=sort,
                direction=direction,
            )
        conditions = [sound_generation]
        if query.slot_id is not None:
            conditions.append(col("slot_id") == lit(query.slot_id))
        total, records = await _records_page(
            table=self.character_sounds_table,
            model=CharacterSoundRecord,
            stable_column="id",
            predicate=_combine(conditions),
            tokens=tokens,
            ordering=None if sort == "relevance" else _ordering(sort, direction, "id"),
            page=query,
        )
        characters_by_resource = {
            character.resource_name.casefold(): character for character in complete_characters
        }
        symbols = _identifier_symbols(metadata.identifiers)
        items: list[SoundRow] = []
        for record in records:
            character = characters_by_resource[record.character_resource_name.casefold()]
            assert character.detail is not None
            items.append(
                SoundRow(
                    key=record.id,
                    character_resource_name=record.character_resource_name,
                    character_name=character.detail.display_name,
                    slot_id=record.slot_id,
                    slot_symbols=list(symbols.get((IdentifierKind.SOUND_SLOT, record.slot_id), ())),
                    slot_groups=_sound_slot_group_names(groups, record.slot_id),
                    strref=record.strref,
                    text=record.text,
                    serialized_size=record.serialized_size,
                )
            )
        return SoundPage(
            items=items,
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=_page_count(total, query.page_size),
            sort=sort,
            direction=direction,
        )

    async def transitions(self, query: TransitionQuery) -> TransitionPage:
        dialogue_rows = cast(
            list[DialogueRecord],
            await self.dialogues_table.query().to_pydantic(DialogueRecord),
        )
        dialogues = {row.resource_name.casefold(): row for row in dialogue_rows}
        allowed_dialogues = [
            row for row in dialogue_rows if row.extraction.status is DetailStatus.COMPLETE
        ]
        tokens = _search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "location")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        child_generation = _child_generation_predicate(
            "dialogue_resource_name",
            (
                (dialogue.resource_name, dialogue.extraction.run_id)
                for dialogue in allowed_dialogues
            ),
        )
        if child_generation is None:
            return TransitionPage(
                items=[],
                page=query.page,
                page_size=query.page_size,
                total=0,
                page_count=1,
                sort=sort,
                direction=direction,
            )
        conditions = [child_generation]
        if query.terminates_dialog is not None:
            conditions.append(col("terminates_dialog") == lit(query.terminates_dialog))
        predicate = _combine(conditions)
        total, records = await _records_page(
            table=self.transitions_table,
            model=DialogueTransitionRecord,
            stable_column="id",
            predicate=predicate,
            tokens=tokens,
            ordering=None if sort == "relevance" else _transition_ordering(sort, direction),
            page=query,
        )
        return TransitionPage(
            items=[
                _transition_row(
                    record,
                    dialogues[record.dialogue_resource_name.casefold()],
                )
                for record in records
            ],
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=_page_count(total, query.page_size),
            sort=sort,
            direction=direction,
        )

    async def races(self, query: RaceQuery) -> RacePage:
        metadata = await self._metadata_snapshot()
        rows = _race_rows(metadata)
        if query.campaign is not None:
            campaign = query.campaign.casefold()
            rows = [
                row for row in rows if campaign in {value.casefold() for value in row.campaigns}
            ]

        tokens = _search_tokens(query.q)
        scores: dict[str, float] = {}
        if tokens:
            text_scores, identifier_scores = await asyncio.gather(
                _fts_scores(self.race_texts_table, tokens),
                _fts_scores(
                    self.identifiers_table,
                    tokens,
                    col("kind") == lit(IdentifierKind.RACE.value),
                ),
            )
            race_id_scores = _identifier_value_scores(
                metadata,
                identifier_scores,
                IdentifierKind.RACE,
            )
            for row in rows:
                score = max(text_scores.get(row.key, 0.0), race_id_scores.get(row.race_id, 0.0))
                if score:
                    scores[row.key] = score
            rows = [row for row in rows if row.key in scores]

        sort: RaceSort | Literal["relevance"] = query.sort or ("relevance" if tokens else "race_id")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        rows = (
            _relevance_order(rows, scores, lambda row: row.key)
            if sort == "relevance"
            else _metadata_order(rows, sort, direction, lambda row: row.key)
        )
        return RacePage(
            items=_page_items(rows, query),
            page=query.page,
            page_size=query.page_size,
            total=len(rows),
            page_count=_page_count(len(rows), query.page_size),
            sort=sort,
            direction=direction,
        )

    async def classes(self, query: ClassQuery) -> ClassPage:
        metadata = await self._metadata_snapshot()
        rows = _class_rows(metadata)
        if query.campaign is not None:
            campaign = query.campaign.casefold()
            rows = [
                row for row in rows if campaign in {value.casefold() for value in row.campaigns}
            ]
        if query.fallen is not None:
            rows = [row for row in rows if row.fallen is query.fallen]
        if query.class_id is not None:
            rows = [row for row in rows if row.class_id == query.class_id]

        tokens = _search_tokens(query.q)
        scores: dict[str, float] = {}
        if tokens:
            text_scores, identifier_scores = await asyncio.gather(
                _fts_scores(self.class_texts_table, tokens),
                _fts_scores(
                    self.identifiers_table,
                    tokens,
                    col("kind") == lit(IdentifierKind.CLASS.value),
                ),
            )
            class_id_scores = _identifier_value_scores(
                metadata,
                identifier_scores,
                IdentifierKind.CLASS,
            )
            for row in rows:
                score = max(
                    text_scores.get(row.key, 0.0),
                    class_id_scores.get(row.class_id, 0.0),
                )
                if score:
                    scores[row.key] = score
            rows = [row for row in rows if row.key in scores]

        sort: ClassSort | Literal["relevance"] = query.sort or (
            "relevance" if tokens else "class_id"
        )
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        rows = (
            _relevance_order(rows, scores, lambda row: row.key)
            if sort == "relevance"
            else _metadata_order(rows, sort, direction, lambda row: row.key)
        )
        return ClassPage(
            items=_page_items(rows, query),
            page=query.page,
            page_size=query.page_size,
            total=len(rows),
            page_count=_page_count(len(rows), query.page_size),
            sort=sort,
            direction=direction,
        )

    async def kits(self, query: KitQuery) -> KitPage:
        metadata = await self._metadata_snapshot()
        rows = _kit_rows(metadata)
        if query.class_id is not None:
            rows = [row for row in rows if row.class_id == query.class_id]

        tokens = _search_tokens(query.q)
        scores: dict[str, float] = {}
        if tokens:
            kit_scores, class_identifier_scores, kit_identifier_scores = await asyncio.gather(
                _fts_scores(self.kits_table, tokens),
                _fts_scores(
                    self.identifiers_table,
                    tokens,
                    col("kind") == lit(IdentifierKind.CLASS.value),
                ),
                _fts_scores(
                    self.identifiers_table,
                    tokens,
                    col("kind") == lit(IdentifierKind.KIT.value),
                ),
            )
            class_id_scores = _identifier_value_scores(
                metadata,
                class_identifier_scores,
                IdentifierKind.CLASS,
            )
            kit_id_scores = _identifier_value_scores(
                metadata,
                kit_identifier_scores,
                IdentifierKind.KIT,
            )
            for row in rows:
                score = max(
                    kit_scores.get(row.key, 0.0),
                    class_id_scores.get(row.class_id, 0.0),
                    kit_id_scores.get(row.kit_ids_value, 0.0),
                )
                if score:
                    scores[row.key] = score
            rows = [row for row in rows if row.key in scores]

        sort: KitSort | Literal["relevance"] = query.sort or ("relevance" if tokens else "row_id")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        rows = (
            _relevance_order(rows, scores, lambda row: row.key)
            if sort == "relevance"
            else _metadata_order(rows, sort, direction, lambda row: row.key)
        )
        return KitPage(
            items=_page_items(rows, query),
            page=query.page,
            page_size=query.page_size,
            total=len(rows),
            page_count=_page_count(len(rows), query.page_size),
            sort=sort,
            direction=direction,
        )

    async def identifiers(self, query: IdentifierQuery) -> IdentifierPage:
        conditions = [col("kind").isin([kind.value for kind in _SIMPLE_IDENTIFIER_KINDS])]
        if query.kind is not None:
            conditions.append(col("kind") == lit(query.kind.value))
        predicate = _combine(conditions)
        assert predicate is not None
        tokens = _search_tokens(query.q)
        sort: IdentifierSort | Literal["relevance"] = query.sort or (
            "relevance" if tokens else "kind"
        )
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        total, records = await _records_page(
            table=self.identifiers_table,
            model=IdentifierDefinitionRecord,
            stable_column="key",
            predicate=predicate,
            tokens=tokens,
            ordering=None if sort == "relevance" else _ordering(sort, direction, "key"),
            page=query,
        )
        return IdentifierPage(
            items=[
                IdentifierRow.model_validate(record, from_attributes=True) for record in records
            ],
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=_page_count(total, query.page_size),
            sort=sort,
            direction=direction,
        )


@dataclass(frozen=True, slots=True)
class _LabelResolver:
    symbols: Mapping[tuple[IdentifierKind, int], tuple[str, ...]]
    race_labels: Mapping[int, str]
    class_labels: Mapping[int, str]
    kit_names: Mapping[int, str]
    favored_enemy_labels: Mapping[int, str]

    @classmethod
    def from_snapshot(cls, metadata: _MetadataSnapshot) -> _LabelResolver:
        symbols = _identifier_symbols(metadata.identifiers)
        race_rows: dict[int, list[RaceTextRecord]] = defaultdict(list)
        for row in metadata.race_texts:
            race_rows[row.race_id].append(row)
        class_rows: dict[int, list[ClassTextRecord]] = defaultdict(list)
        for row in metadata.class_texts:
            if not row.fallen and row.class_text_kit_id == 0x4000:
                class_rows[row.class_id].append(row)

        soa_race_resources = _campaign_resources(
            metadata.bindings,
            CampaignResourceKind.RACE_TEXT,
            "SOA",
        )
        soa_class_resources = _campaign_resources(
            metadata.bindings,
            CampaignResourceKind.CLASS_TEXT,
            "SOA",
        )
        race_ids = {value for kind, value in symbols if kind is IdentifierKind.RACE} | set(
            race_rows
        )
        class_ids = {value for kind, value in symbols if kind is IdentifierKind.CLASS} | set(
            class_rows
        )
        race_labels = {
            race_id: _preferred_campaign_text(
                race_rows.get(race_id, []),
                soa_race_resources,
                lambda row: row.name,
            )
            or _symbol_label(symbols.get((IdentifierKind.RACE, race_id), ()), race_id)
            for race_id in race_ids
        }
        class_labels = {
            class_id: _preferred_campaign_text(
                class_rows.get(class_id, []),
                soa_class_resources,
                lambda row: row.mixed_name or row.lower_name,
            )
            or _symbol_label(symbols.get((IdentifierKind.CLASS, class_id), ()), class_id)
            for class_id in class_ids
        }

        kit_names: dict[int, str] = {}
        kits_by_value: dict[int, list[KitDefinitionRecord]] = defaultdict(list)
        for row in metadata.kits:
            if row.kit_ids_value is not None:
                kits_by_value[row.kit_ids_value].append(row)
        for value, rows in kits_by_value.items():
            names = _distinct_text(row.mixed_name or row.lower_name for row in rows)
            if len(names) == 1:
                kit_names[value] = names[0]

        favored_enemy_labels: dict[int, str] = {}
        for row in sorted(metadata.favored_enemies, key=lambda row: (row.ordinal, row.key)):
            if row.name is not None:
                favored_enemy_labels.setdefault(row.race_id, row.name)

        return cls(
            symbols=symbols,
            race_labels=race_labels,
            class_labels=class_labels,
            kit_names=kit_names,
            favored_enemy_labels=favored_enemy_labels,
        )

    def identifier_label(self, kind: IdentifierKind, value: int) -> str:
        return _symbol_label(self.symbols.get((kind, value), ()), value)

    def identifier_labels(self, kind: IdentifierKind) -> dict[int, str]:
        return {
            value: _symbol_label(symbols, value)
            for (symbol_kind, value), symbols in self.symbols.items()
            if symbol_kind is kind
        }

    def race_label(self, value: int) -> str:
        return self.race_labels.get(
            value,
            self.identifier_label(IdentifierKind.RACE, value),
        )

    def class_label(self, value: int) -> str:
        return self.class_labels.get(
            value,
            self.identifier_label(IdentifierKind.CLASS, value),
        )

    def favored_enemy_label(self, value: int) -> str:
        return self.favored_enemy_labels.get(value, self.race_label(value))

    def kit_label(self, value: int | None, class_id: int | None) -> str | None:
        if value is None:
            return None
        if value == 0x4000:
            return "Generalist" if class_id == 1 else "Trueclass"
        if value in self.kit_names:
            return self.kit_names[value]
        return self.identifier_label(IdentifierKind.KIT, value)


def _character_row(
    record: CharacterRecord,
    attribution: CharacterAttributionRecord | None,
    voice: VoiceResourceRecord | None,
    dialogues: Mapping[str, DialogueRecord],
    labels: _LabelResolver,
) -> CharacterRow:
    detail = record.detail
    metrics = _character_dialogue_metrics(attribution, dialogues)
    resolved_labels = _character_labels(record, labels)
    return CharacterRow(
        resource_name=record.resource_name,
        display_name=None if detail is None else detail.display_name,
        voice_id=None if voice is None else voice.voice_id,
        resref=record.resref,
        source_kind=record.source.kind,
        dialog_resref=None if detail is None else detail.dialog_resref,
        gender_id=None if detail is None else detail.gender_id,
        race_id=None if detail is None else detail.race_id,
        class_id=None if detail is None else detail.class_id,
        alignment_id=None if detail is None else detail.alignment_id,
        enemy_ally_id=None if detail is None else detail.enemy_ally_id,
        general_id=None if detail is None else detail.general_id,
        specific_id=None if detail is None else detail.specific_id,
        animation_id=None if detail is None else detail.animation_id,
        racial_enemy_id=None if detail is None else detail.racial_enemy_id,
        cre_kit_value=None if detail is None else detail.cre_kit_value,
        kit_ids_value=None if detail is None else detail.kit_ids_value,
        first_class_level=(None if detail is None else detail.class_levels.first_class),
        second_class_level=(None if detail is None else detail.class_levels.second_class),
        third_class_level=(None if detail is None else detail.class_levels.third_class),
        detail_status=record.extraction.status,
        detail_error=record.extraction.error,
        attribution_status=metrics.attribution_status,
        serialized_size=record.serialized_size,
        dialogue_status=metrics.dialogue_status,
        declared_dialogue_count=metrics.declared_dialogue_count,
        resolved_dialogue_count=metrics.resolved_dialogue_count,
        dialogue_line_count=metrics.dialogue_line_count,
        npc_line_count=metrics.npc_line_count,
        player_line_count=metrics.player_line_count,
        journal_line_count=metrics.journal_line_count,
        dialogue_state_count=metrics.dialogue_state_count,
        dialogue_transition_count=metrics.dialogue_transition_count,
        dialogue_serialized_size=metrics.dialogue_serialized_size,
        updated_at=record.extraction.updated_at,
        **resolved_labels,
    )


def _character_labels(record: CharacterRecord, labels: _LabelResolver) -> dict[str, str | None]:
    detail = record.detail
    return {
        "gender_label": _optional_identifier_label(
            labels,
            IdentifierKind.GENDER,
            None if detail is None else detail.gender_id,
        ),
        "race_label": None if detail is None else labels.race_label(detail.race_id),
        "class_label": None if detail is None else labels.class_label(detail.class_id),
        "alignment_label": _optional_identifier_label(
            labels,
            IdentifierKind.ALIGNMENT,
            None if detail is None else detail.alignment_id,
        ),
        "enemy_ally_label": _optional_identifier_label(
            labels,
            IdentifierKind.ENEMY_ALLY,
            None if detail is None else detail.enemy_ally_id,
        ),
        "general_label": _optional_identifier_label(
            labels,
            IdentifierKind.GENERAL,
            None if detail is None else detail.general_id,
        ),
        "specific_label": _optional_identifier_label(
            labels,
            IdentifierKind.SPECIFIC,
            None if detail is None else detail.specific_id,
        ),
        "animation_label": _optional_identifier_label(
            labels,
            IdentifierKind.ANIMATION,
            None if detail is None else detail.animation_id,
        ),
        "racial_enemy_label": (
            None if detail is None else labels.favored_enemy_label(detail.racial_enemy_id)
        ),
        "kit_label": (
            None if detail is None else labels.kit_label(detail.kit_ids_value, detail.class_id)
        ),
    }


def _character_dialogue_metrics(
    attribution: CharacterAttributionRecord | None,
    dialogues: Mapping[str, DialogueRecord],
) -> _CharacterDialogueMetrics:
    if attribution is None:
        return _CharacterDialogueMetrics()
    resolved = [
        dialogues[name.casefold()]
        for name in attribution.resolved_dialogue_resource_names
        if name.casefold() in dialogues
    ]
    if not resolved:
        return _CharacterDialogueMetrics(
            attribution_status=attribution.status,
            dialogue_status=attribution.dialogue_status,
            declared_dialogue_count=len(attribution.declared_dialogue_resrefs),
            resolved_dialogue_count=0,
        )
    return _CharacterDialogueMetrics(
        attribution_status=attribution.status,
        dialogue_status=attribution.dialogue_status,
        declared_dialogue_count=len(attribution.declared_dialogue_resrefs),
        resolved_dialogue_count=len(resolved),
        dialogue_line_count=sum(
            _dialogue_metric(row, lambda detail: detail.dialogue_line_count) for row in resolved
        ),
        npc_line_count=sum(
            _dialogue_metric(row, lambda detail: detail.npc_line_count) for row in resolved
        ),
        player_line_count=sum(
            _dialogue_metric(row, lambda detail: detail.player_line_count) for row in resolved
        ),
        journal_line_count=sum(
            _dialogue_metric(row, lambda detail: detail.journal_line_count) for row in resolved
        ),
        dialogue_state_count=sum(
            _dialogue_metric(row, lambda detail: detail.state_count) for row in resolved
        ),
        dialogue_transition_count=sum(
            _dialogue_metric(row, lambda detail: detail.transition_count) for row in resolved
        ),
        dialogue_serialized_size=sum(row.serialized_size or 0 for row in resolved),
    )


def _dialogue_row(record: DialogueRecord, character_count: int) -> DialogueRow:
    detail = record.detail
    return DialogueRow(
        resource_name=record.resource_name,
        resref=record.resref,
        source_kind=record.source.kind,
        source_path=record.source.path,
        detail_status=record.extraction.status,
        detail_error=record.extraction.error,
        serialized_size=record.serialized_size,
        dialogue_line_count=(None if detail is None else detail.dialogue_line_count),
        npc_line_count=None if detail is None else detail.npc_line_count,
        player_line_count=None if detail is None else detail.player_line_count,
        journal_line_count=None if detail is None else detail.journal_line_count,
        character_count=character_count,
        updated_at=record.extraction.updated_at,
    )


def _dialogue_metric(
    record: DialogueRecord,
    select: Callable[[DialogueData], int],
) -> int:
    return 0 if record.detail is None else select(record.detail)


def _dialogue_line_row(
    record: DialogueLineRecord,
    dialogue: DialogueRecord,
    character_count: int,
) -> DialogueLineRow:
    return DialogueLineRow(
        id=record.id,
        dialogue_resource_name=record.dialogue_resource_name,
        dialogue_resref=dialogue.resref,
        source_kind=dialogue.source.kind,
        line_kind=record.line_kind,
        state_index=record.state_index,
        state_trigger_index=record.state_trigger_index,
        state_trigger_text=record.state_trigger_text,
        transition_index=record.transition_index,
        strref=record.strref,
        text=record.text,
        tokens=record.tokens,
        serialized_size=record.serialized_size,
        character_count=character_count,
    )


def _transition_row(
    record: DialogueTransitionRecord,
    dialogue: DialogueRecord,
) -> TransitionRow:
    return TransitionRow(
        id=record.id,
        dialogue_resource_name=record.dialogue_resource_name,
        dialogue_resref=dialogue.resref,
        source_kind=dialogue.source.kind,
        state_index=record.state_index,
        transition_index=record.transition_index,
        flags_raw=record.flags_raw,
        flags_decoded=record.flags_decoded,
        trigger_index=record.trigger_index,
        trigger_text=record.trigger_text,
        action_index=record.action_index,
        action_text=record.action_text,
        next_dialog=record.next_dialog,
        next_state_index=record.next_state_index,
        terminates_dialog=record.terminates_dialog,
        serialized_size=record.serialized_size,
    )


def _voice_row(
    record: VoiceResourceRecord,
    dialogues: Mapping[str, DialogueRecord],
) -> VoiceRow:
    voice = VoiceResource(
        id=VoiceId(record.voice_id),
        display_name=record.display_name,
        prompt=record.prompt,
        variant_resource_names=record.variant_resource_names,
        dialogue_resrefs=record.dialogue_resrefs,
    )
    ordered_dialogues = [
        dialogues[resref.casefold()]
        for resref in voice.dialogue_resrefs
        if resref.casefold() in dialogues
    ]
    return VoiceRow(
        id=voice.id,
        display_name=voice.display_name,
        prompt=voice.prompt,
        variant_resource_names=voice.variant_resource_names,
        dialogue_resrefs=[row.resref for row in ordered_dialogues],
        variant_count=voice.variant_count,
        dialogue_count=len(ordered_dialogues),
        npc_line_count=sum(
            _dialogue_metric(row, lambda detail: detail.npc_line_count) for row in ordered_dialogues
        ),
        serialized_size=len(voice.model_dump_json().encode("utf-8")),
    )


def _optional_identifier_label(
    labels: _LabelResolver,
    kind: IdentifierKind,
    value: int | None,
) -> str | None:
    return None if value is None else labels.identifier_label(kind, value)


def _race_rows(metadata: _MetadataSnapshot) -> list[RaceRow]:
    symbols = _identifier_symbols(metadata.identifiers)
    race_symbols = {
        value: list(aliases)
        for (kind, value), aliases in symbols.items()
        if kind is IdentifierKind.RACE
    }
    campaigns = _campaigns_by_resource(metadata, CampaignResourceKind.RACE_TEXT)
    text_rows: dict[int, list[RaceTextRecord]] = defaultdict(list)
    for row in metadata.race_texts:
        text_rows[row.race_id].append(row)

    rows: list[RaceRow] = []
    for race_id in sorted(set(race_symbols) | set(text_rows)):
        details = sorted(
            text_rows.get(race_id, []),
            key=lambda row: (row.source_resource.casefold(), row.ordinal, row.key),
        )
        if not details:
            rows.append(
                RaceRow(
                    key=f"race:{race_id}",
                    race_id=race_id,
                    symbols=race_symbols.get(race_id, []),
                    source_resource=None,
                    ordinal=None,
                    campaigns=[],
                    row_name=None,
                    name_strref=None,
                    name=None,
                    description_strref=None,
                    description=None,
                    uppercase_name_strref=None,
                    uppercase_name=None,
                    biography_strref=None,
                    biography=None,
                )
            )
            continue
        rows.extend(
            RaceRow(
                key=row.key,
                race_id=race_id,
                symbols=race_symbols.get(race_id, []),
                source_resource=row.source_resource,
                ordinal=row.ordinal,
                campaigns=campaigns.get(_resource_key(row.source_resource), []),
                row_name=row.row_name,
                name_strref=row.name_strref,
                name=row.name,
                description_strref=row.description_strref,
                description=row.description,
                uppercase_name_strref=row.uppercase_name_strref,
                uppercase_name=row.uppercase_name,
                biography_strref=row.biography_strref,
                biography=row.biography,
            )
            for row in details
        )
    return rows


def _class_rows(metadata: _MetadataSnapshot) -> list[ClassRow]:
    symbols = _identifier_symbols(metadata.identifiers)
    class_symbols = {
        value: list(aliases)
        for (kind, value), aliases in symbols.items()
        if kind is IdentifierKind.CLASS
    }
    campaigns = _campaigns_by_resource(metadata, CampaignResourceKind.CLASS_TEXT)
    text_rows: dict[int, list[ClassTextRecord]] = defaultdict(list)
    for row in metadata.class_texts:
        text_rows[row.class_id].append(row)

    rows: list[ClassRow] = []
    for class_id in sorted(set(class_symbols) | set(text_rows)):
        details = sorted(
            text_rows.get(class_id, []),
            key=lambda row: (row.source_resource.casefold(), row.ordinal, row.key),
        )
        if not details:
            rows.append(
                ClassRow(
                    key=f"class:{class_id}",
                    class_id=class_id,
                    symbols=class_symbols.get(class_id, []),
                    source_resource=None,
                    ordinal=None,
                    campaigns=[],
                    row_name=None,
                    class_text_kit_id=None,
                    lower_name_strref=None,
                    lower_name=None,
                    description_strref=None,
                    description=None,
                    mixed_name_strref=None,
                    mixed_name=None,
                    biography_strref=None,
                    biography=None,
                    fallen=None,
                    brief_description_strref=None,
                    brief_description=None,
                    fallen_notice_strref=None,
                    fallen_notice=None,
                )
            )
            continue
        rows.extend(
            ClassRow(
                key=row.key,
                class_id=class_id,
                symbols=class_symbols.get(class_id, []),
                source_resource=row.source_resource,
                ordinal=row.ordinal,
                campaigns=campaigns.get(_resource_key(row.source_resource), []),
                row_name=row.row_name,
                class_text_kit_id=row.class_text_kit_id,
                lower_name_strref=row.lower_name_strref,
                lower_name=row.lower_name,
                description_strref=row.description_strref,
                description=row.description,
                mixed_name_strref=row.mixed_name_strref,
                mixed_name=row.mixed_name,
                biography_strref=row.biography_strref,
                biography=row.biography,
                fallen=row.fallen,
                brief_description_strref=row.brief_description_strref,
                brief_description=row.brief_description,
                fallen_notice_strref=row.fallen_notice_strref,
                fallen_notice=row.fallen_notice,
            )
            for row in details
        )
    return rows


def _kit_rows(metadata: _MetadataSnapshot) -> list[KitRow]:
    symbols = _identifier_symbols(metadata.identifiers)
    return [
        KitRow(
            key=row.key,
            source_resource=row.source_resource,
            ordinal=row.ordinal,
            row_id=row.row_id,
            row_name=row.row_name,
            lower_name_strref=row.lower_name_strref,
            lower_name=row.lower_name,
            mixed_name_strref=row.mixed_name_strref,
            mixed_name=row.mixed_name,
            help_strref=row.help_strref,
            help_text=row.help_text,
            abilities_resref=row.abilities,
            proficiency_column=row.proficiency,
            unusable_mask=row.unusable,
            class_id=row.class_id,
            class_symbols=(
                []
                if row.class_id is None
                else list(symbols.get((IdentifierKind.CLASS, row.class_id), ()))
            ),
            kit_ids_value=row.kit_ids_value,
            kit_symbols=(
                []
                if row.kit_ids_value is None
                else list(symbols.get((IdentifierKind.KIT, row.kit_ids_value), ()))
            ),
            class_text_kit_id=row.class_text_kit_id,
        )
        for row in sorted(metadata.kits, key=lambda row: (row.row_id, row.key))
    ]


def _identifier_symbols(
    definitions: Sequence[IdentifierDefinitionRecord],
) -> dict[tuple[IdentifierKind, int], tuple[str, ...]]:
    values: dict[tuple[IdentifierKind, int], list[str]] = defaultdict(list)
    for row in sorted(definitions, key=lambda row: (row.source_resource, row.ordinal, row.key)):
        aliases = values[(row.kind, row.value)]
        aliases.extend(symbol for symbol in row.symbols if symbol not in aliases)
    return {key: tuple(aliases) for key, aliases in values.items()}


def _sound_slot_group_names(
    groups: Sequence[SoundSlotGroupRecord],
    slot_id: int,
) -> list[str]:
    return [
        group.row_name
        for group in sorted(groups, key=lambda group: (group.ordinal, group.key))
        if group.offset is not None
        and group.count is not None
        and group.offset <= slot_id < group.offset + group.count
    ]


def _campaigns_by_resource(
    metadata: _MetadataSnapshot,
    kind: CampaignResourceKind,
) -> dict[str, list[str]]:
    order = {
        row.campaign_id.casefold(): (row.ordinal, row.campaign_id.casefold())
        for row in metadata.campaigns
    }
    values: dict[str, list[str]] = defaultdict(list)
    for row in metadata.bindings:
        if row.resource_kind is not kind or row.resource_resref is None:
            continue
        campaigns = values[_resource_key(row.resource_resref)]
        if row.campaign_id not in campaigns:
            campaigns.append(row.campaign_id)
    for campaigns in values.values():
        campaigns.sort(key=lambda value: order.get(value.casefold(), (2**31, value.casefold())))
    return dict(values)


def _campaign_resources(
    bindings: Sequence[CampaignResourceBindingRecord],
    kind: CampaignResourceKind,
    campaign_id: str,
) -> frozenset[str]:
    return frozenset(
        _resource_key(row.resource_resref)
        for row in bindings
        if row.resource_kind is kind
        and row.campaign_id.casefold() == campaign_id.casefold()
        and row.resource_resref is not None
    )


def _preferred_campaign_text[Record: RaceTextRecord | ClassTextRecord](
    rows: Sequence[Record],
    preferred_resources: frozenset[str],
    value: Callable[[Record], str | None],
) -> str | None:
    preferred = [row for row in rows if _resource_key(row.source_resource) in preferred_resources]
    if preferred:
        texts = _distinct_text(value(row) for row in preferred)
        return texts[0] if len(texts) == 1 else None
    texts = _distinct_text(value(row) for row in rows)
    return texts[0] if len(texts) == 1 else None


def _distinct_text(values: Iterable[str | None]) -> list[str]:
    distinct: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None or not value.strip():
            continue
        key = value.strip().casefold()
        if key not in seen:
            seen.add(key)
            distinct.append(value.strip())
    return distinct


def _resource_key(value: str) -> str:
    return value.casefold().removesuffix(".2da")


def _symbol_label(symbols: Sequence[str], value: int) -> str:
    if not symbols:
        return f"Unknown ({value})"
    return " / ".join(_prettify_symbol(symbol) for symbol in symbols)


def _prettify_symbol(symbol: str) -> str:
    return " ".join(part.capitalize() for part in symbol.replace("-", "_").split("_") if part)


async def _fts_scores(
    table: AsyncTable,
    tokens: tuple[str, ...],
    predicate: Expr | None = None,
) -> dict[str, float]:
    assert tokens
    count = await table.count_rows(predicate.to_sql() if predicate is not None else None)
    if count == 0:
        return {}
    query = table.query().nearest_to_text(_fts_query(tokens))
    if predicate is not None:
        query = query.where(predicate)
    rows = cast(
        list[_MetadataScore],
        await query.limit(count).select(["key", "_score"]).to_pydantic(_MetadataScore),
    )
    return {row.key: row.score for row in rows}


def _identifier_value_scores(
    metadata: _MetadataSnapshot,
    key_scores: Mapping[str, float],
    kind: IdentifierKind,
) -> dict[int, float]:
    scores: dict[int, float] = {}
    for row in metadata.identifiers:
        if row.kind is kind and row.key in key_scores:
            scores[row.value] = max(scores.get(row.value, float("-inf")), key_scores[row.key])
    return scores


def _relevance_order[Row](
    rows: Sequence[Row],
    scores: Mapping[str, float],
    key_of: Callable[[Row], str],
) -> list[Row]:
    return sorted(rows, key=lambda row: (-scores[key_of(row)], key_of(row)))


def _metadata_order[Row](
    rows: Sequence[Row],
    column: str,
    direction: SortDirection,
    key_of: Callable[[Row], str],
) -> list[Row]:
    non_null = [row for row in rows if getattr(row, column) is not None]
    null = sorted(
        (row for row in rows if getattr(row, column) is None),
        key=key_of,
    )
    non_null.sort(key=key_of)
    non_null.sort(key=attrgetter(column), reverse=direction == "desc")
    return [*non_null, *null]


def _page_items[Row](rows: Sequence[Row], query: PageQuery) -> list[Row]:
    offset = _page_offset(query)
    return list(rows[offset : offset + query.page_size])


async def _records_all[Record: LanceModel, SearchRecord: LanceModel](
    *,
    table: AsyncTable,
    model: type[Record],
    search_model: type[SearchRecord],
    tokens: tuple[str, ...],
    predicate: Expr | None,
    key_of: Callable[[Record], str],
    score_of: Callable[[SearchRecord], float],
) -> tuple[list[Record], dict[str, float]]:
    if not tokens:
        query = table.query()
        if predicate is not None:
            query = query.where(predicate)
        rows = cast(list[Record], await query.to_pydantic(model))
        return rows, {}

    limit = await table.count_rows(predicate.to_sql() if predicate is not None else None)
    if limit == 0:
        return [], {}
    search = table.query().nearest_to_text(_fts_query(tokens))
    if predicate is not None:
        search = search.where(predicate)
    scored = cast(
        list[SearchRecord],
        await search.limit(limit).select([*model.model_fields, "_score"]).to_pydantic(search_model),
    )
    records = [model.model_validate(row.model_dump(exclude={"score"})) for row in scored]
    return records, {
        key_of(record): score_of(row) for record, row in zip(records, scored, strict=True)
    }


async def _records_page[Record: LanceModel](
    *,
    table: AsyncTable,
    model: type[Record],
    stable_column: StableColumn,
    predicate: Expr | None,
    tokens: tuple[str, ...],
    ordering: list[ColumnOrdering] | None,
    page: PageQuery,
) -> tuple[int, list[Record]]:
    """Run the typed pagination path shared by record-backed browser tables."""
    if tokens:
        match_limit = await table.count_rows(predicate.to_sql() if predicate is not None else None)
        if match_limit == 0:
            return 0, []
        projected_columns = list(
            dict.fromkeys(
                [
                    stable_column,
                    *(item.column_name for item in ordering or []),
                    "_score",
                ]
            )
        )
        search = table.query().nearest_to_text(_fts_query(tokens))
        if predicate is not None:
            search = search.where(predicate)
        matches = await search.limit(match_limit).select(projected_columns).to_arrow()
        if matches.num_rows == 0:
            return 0, []

        sort_order = (
            [
                (
                    item.column_name,
                    "ascending" if item.ascending else "descending",
                    "at_start" if item.nulls_first else "at_end",
                )
                for item in ordering
            ]
            if ordering is not None
            else [("_score", "descending", "at_end"), (stable_column, "ascending", "at_end")]
        )
        matches = matches.sort_by(sort_order)
        page_keys = cast(
            list[str],
            matches.column(stable_column).slice(_page_offset(page), page.page_size).to_pylist(),
        )
        if not page_keys:
            return cast(int, matches.num_rows), []

        unordered_rows = cast(
            list[Record],
            await table.query()
            .where(col(stable_column).isin(page_keys))
            .limit(len(page_keys))
            .to_pydantic(model),
        )
        rows_by_key = {
            cast(str, getattr(record, stable_column)): record for record in unordered_rows
        }
        assert rows_by_key.keys() == set(page_keys)
        return cast(int, matches.num_rows), [rows_by_key[key] for key in page_keys]

    assert ordering is not None
    page_query = table.query()
    if predicate is not None:
        page_query = page_query.where(predicate)
    total, record_rows = await asyncio.gather(
        table.count_rows(predicate.to_sql() if predicate is not None else None),
        page_query.order_by(ordering)
        .offset(_page_offset(page))
        .limit(page.page_size)
        .to_pydantic(model),
    )
    return total, cast(list[Record], record_rows)


def _latest_run_id(runs: Sequence[ExtractionRunRecord], kind: RunKind) -> str | None:
    matches = [run for run in runs if run.run_kind is kind]
    if not matches:
        return None
    return max(matches, key=lambda run: (run.started_at, run.id)).id


def _completed_run_order(run: ExtractionRunRecord) -> tuple[str, str]:
    assert run.completed_at is not None, f"completed run {run.id} has no completion time"
    return run.completed_at, run.id


def _empty_attribution_snapshot(
    publication: AttributionPublicationStatus,
) -> _AttributionSnapshot:
    return _AttributionSnapshot(
        publication=publication,
        run=None,
        by_character={},
        character_count_by_dialogue=Counter(),
        voices=[],
        voice_by_character={},
    )


def _child_generation_predicate(
    parent_column: ChildParentColumn,
    parents: Iterable[tuple[str, str]],
) -> Expr | None:
    names_by_run: dict[str, list[str]] = defaultdict(list)
    for resource_name, run_id in parents:
        names_by_run[run_id].append(resource_name)
    predicates = [
        (col("run_id") == lit(run_id)) & col(parent_column).isin(resource_names)
        for run_id, resource_names in names_by_run.items()
    ]
    if not predicates:
        return None
    result = predicates[0]
    for predicate in predicates[1:]:
        result |= predicate
    return result


async def _count_rows(table: AsyncTable, predicate: Expr | None) -> int:
    return 0 if predicate is None else await table.count_rows(predicate.to_sql())


def _combine(conditions: list[Expr]) -> Expr | None:
    if not conditions:
        return None
    predicate = conditions[0]
    for condition in conditions[1:]:
        predicate &= condition
    return predicate


def _search_tokens(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(match.group(0) for match in _SEARCH_TOKEN.finditer(value.strip()))


def _fts_query(tokens: tuple[str, ...]) -> BooleanQuery:
    assert tokens
    return BooleanQuery(
        [
            (
                Occur.MUST,
                MatchQuery(token, "search_text", operator=FullTextOperator.AND),
            )
            for token in tokens
        ]
    )


def _ordering(column: str, direction: SortDirection, stable_column: str) -> list[ColumnOrdering]:
    ordering = [
        ColumnOrdering(
            column_name=column,
            ascending=direction == "asc",
            nulls_first=False,
        )
    ]
    if column != stable_column:
        ordering.append(
            ColumnOrdering(
                column_name=stable_column,
                ascending=True,
                nulls_first=False,
            )
        )
    return ordering


def _transition_ordering(
    sort: TransitionSort,
    direction: SortDirection,
) -> list[ColumnOrdering]:
    if sort != "location":
        return _ordering(sort, direction, "id")
    return [
        ColumnOrdering(
            column_name=column,
            ascending=direction == "asc",
            nulls_first=False,
        )
        for column in ("dialogue_resource_name", "state_index", "transition_index")
    ]


def _page_offset(query: PageQuery) -> int:
    return (query.page - 1) * query.page_size


def _page_count(total: int, page_size: int) -> int:
    return max(1, (total + page_size - 1) // page_size)
