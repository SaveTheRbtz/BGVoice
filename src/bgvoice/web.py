"""Read-only HTTP API and production SPA host for pipeline inspection."""

import asyncio
import re
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from operator import attrgetter
from pathlib import Path
from typing import Annotated, Literal, Protocol, cast

import lancedb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from lancedb.db import AsyncConnection
from lancedb.expr import Expr, col, lit
from lancedb.pydantic import LanceModel
from lancedb.query import (
    AsyncFTSQuery,
    BooleanQuery,
    ColumnOrdering,
    FullTextOperator,
    MatchQuery,
    Occur,
)
from lancedb.table import AsyncTable
from pydantic import BaseModel, ConfigDict, Field

from bgvoice.database import (
    TABLE_INDEXES,
    TABLE_MODELS,
    TABLE_NAMES,
    CampaignDefinitionRecord,
    CampaignResourceBindingRecord,
    CharacterRecord,
    CharacterSoundRecord,
    ClassTextRecord,
    DialogueLineRecord,
    DialogueRecord,
    DialogueTransitionRecord,
    ExtractionRunRecord,
    FavoredEnemyRecord,
    IdentifierDefinitionRecord,
    KitDefinitionRecord,
    RaceTextRecord,
    SoundSlotGroupRecord,
)
from bgvoice.models import (
    AttributionStatus,
    CampaignResourceKind,
    DetailStatus,
    DialogueDetail,
    DialogueLineKind,
    IdentifierKind,
    RunKind,
    RunStatus,
    SourceKind,
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
type RaceSort = Literal["race_id", "row_name", "name", "source_resource"]
type ClassSort = Literal["class_id", "row_name", "lower_name", "fallen"]
type KitSort = Literal["row_id", "row_name", "lower_name", "class_id"]
type IdentifierSort = Literal["kind", "value", "source_resource"]
type VoiceSort = Literal["character_resource_name", "slot_id", "strref", "serialized_size"]
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


class ApiModel(BaseModel):
    """Strict response model for the HTTP boundary."""

    model_config = ConfigDict(strict=True, extra="forbid")


class _Keyed(Protocol):
    key: str


class PageQuery(BaseModel):
    """Shared pagination fields accepted from URL query strings."""

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
    slot_id: int | None = Field(default=None, ge=0, le=0xFF)
    sort: VoiceSort | None = None
    direction: SortDirection = "desc"


class TransitionQuery(PageQuery):
    q: str | None = Field(default=None, max_length=500)
    terminates_dialog: bool | None = None
    sort: TransitionSort | None = None
    direction: SortDirection = "asc"


class CharacterRow(ApiModel):
    resource_name: str
    display_name: str | None
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


class CharacterPage(ApiModel):
    items: list[CharacterRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: CharacterSort | Literal["relevance"]
    direction: SortDirection


class DialogueRow(ApiModel):
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


class DialoguePage(ApiModel):
    items: list[DialogueRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: DialogueSort | Literal["relevance"]
    direction: SortDirection


class DialogueLineRow(ApiModel):
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


class DialogueLinePage(ApiModel):
    items: list[DialogueLineRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: LineSort | Literal["relevance"]
    direction: SortDirection


class VoiceRow(ApiModel):
    key: str
    character_resource_name: str
    character_name: str | None
    slot_id: int
    slot_symbols: list[str]
    slot_groups: list[str]
    strref: int
    text: str | None
    serialized_size: int


class VoicePage(ApiModel):
    items: list[VoiceRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: VoiceSort | Literal["relevance"]
    direction: SortDirection


class TransitionRow(ApiModel):
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


class TransitionPage(ApiModel):
    items: list[TransitionRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: TransitionSort | Literal["relevance"]
    direction: SortDirection


class RaceRow(ApiModel):
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


class RacePage(ApiModel):
    items: list[RaceRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: RaceSort | Literal["relevance"]
    direction: SortDirection


class ClassRow(ApiModel):
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


class ClassPage(ApiModel):
    items: list[ClassRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: ClassSort | Literal["relevance"]
    direction: SortDirection


class KitRow(ApiModel):
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


class KitPage(ApiModel):
    items: list[KitRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: KitSort | Literal["relevance"]
    direction: SortDirection


class IdentifierRow(ApiModel):
    key: str
    kind: SimpleIdentifierKind
    value: int
    symbols: list[str]
    source_resource: str


class IdentifierPage(ApiModel):
    items: list[IdentifierRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: IdentifierSort | Literal["relevance"]
    direction: SortDirection


class FacetValue(ApiModel):
    value: str | int
    label: str | None
    count: int = Field(ge=0)


class FilterOptions(ApiModel):
    source_kinds: list[FacetValue]
    gender_ids: list[FacetValue]
    race_ids: list[FacetValue]
    class_ids: list[FacetValue]
    metadata_class_ids: list[FacetValue]
    sound_slot_ids: list[FacetValue]
    campaigns: list[str]
    identifier_kinds: list[SimpleIdentifierKind]


class ExtractionRunSummary(ApiModel):
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


class PipelineStats(ApiModel):
    database_path: str
    database_size: int = Field(ge=0)
    characters_total: int = Field(ge=0)
    characters_complete: int = Field(ge=0)
    characters_failed: int = Field(ge=0)
    characters_with_dialogue: int = Field(ge=0)
    attribution_completed_at: str | None
    characters_unavailable: int = Field(ge=0)
    characters_matched: int = Field(ge=0)
    characters_missing_dialogue: int = Field(ge=0)
    characters_dialogue_failed: int = Field(ge=0)
    characters_without_dialogue: int = Field(ge=0)
    dialogues_total: int = Field(ge=0)
    dialogues_complete: int = Field(ge=0)
    dialogue_lines: int = Field(ge=0)
    line_records_total: int = Field(ge=0)
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


class CharacterDetailPayload(ApiModel):
    resource_name: str
    display_name: str
    short_name: str | None
    short_name_strref: int
    long_name: str | None
    long_name_strref: int
    death_variable: str | None
    dialog_resref: str | None
    gender_id: int
    gender_label: str
    race_id: int
    race_label: str
    class_id: int
    class_label: str
    alignment_id: int
    alignment_label: str
    enemy_ally_id: int
    enemy_ally_label: str
    general_id: int
    general_label: str
    specific_id: int
    specific_label: str
    animation_id: int
    animation_label: str
    racial_enemy_id: int
    racial_enemy_label: str
    cre_kit_value: int
    kit_ids_value: int | None
    kit_label: str | None
    first_class_level: int
    second_class_level: int
    third_class_level: int
    strength: int
    strength_bonus: int
    intelligence: int
    wisdom: int
    dexterity: int
    constitution: int
    charisma: int
    morale: int
    morale_break: int
    morale_recovery_time: int
    reputation: int
    override_script: str | None
    class_script: str | None
    race_script: str | None
    general_script: str | None
    default_script: str | None
    small_portrait: str | None
    large_portrait: str | None
    cre_version: str


class CharacterDetailResponse(ApiModel):
    character: CharacterDetailPayload
    dialogue: DialogueDetail | None
    source_kind: SourceKind
    source_path: str
    character_serialized_size: int
    dialogue_serialized_size: int | None
    updated_at: str
    attribution_status: AttributionStatus | None


class HealthResponse(ApiModel):
    status: Literal["ok"]
    storage: Literal["lancedb"]


class _Projection(LanceModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class _AttributionMarker(_Projection):
    attribution_completed_at: str | None


class _CharacterStats(_AttributionMarker):
    detail_status: DetailStatus = Field(strict=False)
    has_dialog: bool
    attribution_status: AttributionStatus | None = Field(strict=False)


class _DialogueStats(_Projection):
    detail_status: DetailStatus = Field(strict=False)
    dialogue_line_count: int | None
    character_count: int
    attribution_completed_at: str | None


class _CharacterFacets(_Projection):
    source_kind: SourceKind = Field(strict=False)
    gender_id: int | None
    race_id: int | None
    class_id: int | None


class _CharacterName(_Projection):
    resource_name: str
    display_name: str | None


class _SoundSlotFacet(_Projection):
    slot_id: int


class _CharacterSearchResult(CharacterRecord):
    score: float = Field(alias="_score")


class _DialogueSearchResult(DialogueRecord):
    score: float = Field(alias="_score")


class _LineSearchResult(DialogueLineRecord):
    score: float = Field(alias="_score")


class _VoiceSearchResult(CharacterSoundRecord):
    score: float = Field(alias="_score")


class _VoiceCandidate(_Projection):
    id: str
    character_resource_name: str
    slot_id: int
    strref: int
    serialized_size: int


class _VoiceSearchCandidate(_VoiceCandidate):
    score: float = Field(alias="_score")


class _TransitionSearchResult(DialogueTransitionRecord):
    score: float = Field(alias="_score")


class _IdentifierSearchResult(IdentifierDefinitionRecord):
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
    sound_slot_groups: list[SoundSlotGroupRecord]


@dataclass(frozen=True, slots=True)
class PipelineReader:
    """Strongly consistent typed reads over one local LanceDB database."""

    path: Path
    _connection: AsyncConnection
    characters_table: AsyncTable
    character_sounds_table: AsyncTable
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
        table_names = frozenset((await connection.list_tables(limit=None)).tables)
        assert table_names == TABLE_NAMES, (
            f"pipeline database tables are {sorted(table_names)}; "
            f"expected {sorted(TABLE_NAMES)}. Rebuild the generated database."
        )

        names = tuple(TABLE_MODELS)
        opened = await asyncio.gather(*(connection.open_table(name) for name in names))
        tables = dict(zip(names, opened, strict=True))
        schemas = await asyncio.gather(*(tables[name].schema() for name in names))
        indexes = await asyncio.gather(*(tables[name].list_indices() for name in names))
        for name, schema in zip(names, schemas, strict=True):
            assert schema.equals(TABLE_MODELS[name].to_arrow_schema(), check_metadata=True), (
                f"{name} table schema does not match {TABLE_MODELS[name].__name__}"
            )
        actual_indexes = {
            name: frozenset(
                (index.name, index.index_type, tuple(index.columns)) for index in table_indexes
            )
            for name, table_indexes in zip(names, indexes, strict=True)
        }
        expected_indexes = {
            name: frozenset(
                (spec.name, type(spec.config).__name__, (spec.column,)) for spec in specs
            )
            for name, specs in TABLE_INDEXES.items()
        }
        assert actual_indexes == expected_indexes, (
            f"pipeline database indexes are {actual_indexes}; expected {expected_indexes}. "
            "Rebuild the generated database."
        )
        return cls(
            resolved_path,
            connection,
            tables["characters"],
            tables["character_sounds"],
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

    def health(self) -> HealthResponse:
        return HealthResponse(status="ok", storage="lancedb")

    async def _metadata_snapshot(self) -> _MetadataSnapshot:
        rows = await asyncio.gather(
            self.identifiers_table.query().to_pydantic(IdentifierDefinitionRecord),
            self.campaigns_table.query().to_pydantic(CampaignDefinitionRecord),
            self.bindings_table.query().to_pydantic(CampaignResourceBindingRecord),
            self.race_texts_table.query().to_pydantic(RaceTextRecord),
            self.class_texts_table.query().to_pydantic(ClassTextRecord),
            self.kits_table.query().to_pydantic(KitDefinitionRecord),
            self.favored_enemies_table.query().to_pydantic(FavoredEnemyRecord),
            self.sound_slot_groups_table.query().to_pydantic(SoundSlotGroupRecord),
        )
        return _MetadataSnapshot(
            identifiers=cast(list[IdentifierDefinitionRecord], rows[0]),
            campaigns=cast(list[CampaignDefinitionRecord], rows[1]),
            bindings=cast(list[CampaignResourceBindingRecord], rows[2]),
            race_texts=cast(list[RaceTextRecord], rows[3]),
            class_texts=cast(list[ClassTextRecord], rows[4]),
            kits=cast(list[KitDefinitionRecord], rows[5]),
            favored_enemies=cast(list[FavoredEnemyRecord], rows[6]),
            sound_slot_groups=cast(list[SoundSlotGroupRecord], rows[7]),
        )

    async def stats(self) -> PipelineStats:
        (
            character_rows,
            dialogue_rows,
            run_rows,
            line_records_total,
            metadata,
        ) = await asyncio.gather(
            self.characters_table.query()
            .select(list(_CharacterStats.model_fields))
            .to_pydantic(_CharacterStats),
            self.dialogues_table.query()
            .select(list(_DialogueStats.model_fields))
            .to_pydantic(_DialogueStats),
            self.runs_table.query()
            .order_by(
                [
                    ColumnOrdering(column_name="started_at", ascending=False, nulls_first=False),
                    ColumnOrdering(column_name="id", ascending=False, nulls_first=False),
                ]
            )
            .limit(8)
            .to_pydantic(ExtractionRunRecord),
            self.lines_table.count_rows(),
            self._metadata_snapshot(),
        )
        (
            character_sounds_total,
            soundset_lines_total,
            transition_edges_total,
            character_resource_links_total,
            interaction_rules_total,
            engine_strings_total,
            sound_slot_groups_total,
            favored_enemies_total,
            happiness_rules_total,
            banter_timing_settings_total,
        ) = await asyncio.gather(
            self.character_sounds_table.count_rows(),
            self.soundset_lines_table.count_rows(),
            self.transitions_table.count_rows(),
            self.character_resource_links_table.count_rows(),
            self.interaction_rules_table.count_rows(),
            self.engine_strings_table.count_rows(),
            self.sound_slot_groups_table.count_rows(),
            self.favored_enemies_table.count_rows(),
            self.happiness_rules_table.count_rows(),
            self.banter_timing_settings_table.count_rows(),
        )
        characters = cast(list[_CharacterStats], character_rows)
        dialogues = cast(list[_DialogueStats], dialogue_rows)
        latest_runs = cast(list[ExtractionRunRecord], run_rows)

        attribution_completed_at = _published_attribution_timestamp(characters)
        if attribution_completed_at is None:
            attribution_counts: Counter[AttributionStatus | None] = Counter()
            attributed_dialogues: list[_DialogueStats] = []
            unattributed_dialogues: list[_DialogueStats] = []
        else:
            attribution_counts = Counter(row.attribution_status for row in characters)
            attributed_dialogues = [
                row
                for row in dialogues
                if row.attribution_completed_at == attribution_completed_at
                and row.character_count > 0
            ]
            unattributed_dialogues = [
                row
                for row in dialogues
                if row.attribution_completed_at != attribution_completed_at
                or row.character_count == 0
            ]

        return PipelineStats(
            database_path=str(self.path),
            database_size=sum(
                file.stat().st_size for file in self.path.rglob("*") if file.is_file()
            ),
            characters_total=len(characters),
            characters_complete=sum(
                row.detail_status is DetailStatus.COMPLETE for row in characters
            ),
            characters_failed=sum(row.detail_status is DetailStatus.FAILED for row in characters),
            characters_with_dialogue=sum(row.has_dialog for row in characters),
            attribution_completed_at=attribution_completed_at,
            characters_unavailable=attribution_counts[AttributionStatus.CHARACTER_UNAVAILABLE],
            characters_matched=attribution_counts[AttributionStatus.MATCHED],
            characters_missing_dialogue=attribution_counts[AttributionStatus.MISSING_DIALOGUE],
            characters_dialogue_failed=attribution_counts[AttributionStatus.DIALOGUE_FAILED],
            characters_without_dialogue=attribution_counts[AttributionStatus.NO_DIALOGUE],
            dialogues_total=len(dialogues),
            dialogues_complete=sum(row.detail_status is DetailStatus.COMPLETE for row in dialogues),
            dialogue_lines=sum(row.dialogue_line_count or 0 for row in dialogues),
            line_records_total=line_records_total,
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
            races_total=len(_race_rows(metadata)),
            classes_total=len(_class_rows(metadata)),
            kits_total=len(metadata.kits),
            identifiers_total=sum(
                row.kind in _SIMPLE_IDENTIFIER_KINDS for row in metadata.identifiers
            ),
            campaigns_total=len(metadata.campaigns),
            dialogues_attributed=len(attributed_dialogues),
            dialogues_unattributed=len(unattributed_dialogues),
            attributed_dialogue_lines=sum(
                row.dialogue_line_count or 0 for row in attributed_dialogues
            ),
            unattributed_dialogue_lines=sum(
                row.dialogue_line_count or 0 for row in unattributed_dialogues
            ),
            latest_runs=[
                ExtractionRunSummary.model_validate(run, from_attributes=True)
                for run in latest_runs
            ],
        )

    async def filter_options(self) -> FilterOptions:
        character_rows, sound_rows, metadata = await asyncio.gather(
            self.characters_table.query()
            .select(list(_CharacterFacets.model_fields))
            .to_pydantic(_CharacterFacets),
            self.character_sounds_table.query()
            .select(list(_SoundSlotFacet.model_fields))
            .to_pydantic(_SoundSlotFacet),
            self._metadata_snapshot(),
        )
        characters = cast(list[_CharacterFacets], character_rows)
        sounds = cast(list[_SoundSlotFacet], sound_rows)
        labels = _LabelResolver.from_snapshot(metadata)
        metadata_class_ids = [
            row.value for row in metadata.identifiers if row.kind is IdentifierKind.CLASS
        ]
        return FilterOptions(
            source_kinds=_string_facets(row.source_kind for row in characters),
            gender_ids=_integer_facets(
                (row.gender_id for row in characters if row.gender_id is not None),
                labels.identifier_labels(IdentifierKind.GENDER),
            ),
            race_ids=_integer_facets(
                (row.race_id for row in characters if row.race_id is not None),
                labels.race_labels,
            ),
            class_ids=_integer_facets(
                (row.class_id for row in characters if row.class_id is not None),
                labels.class_labels,
            ),
            metadata_class_ids=_integer_facets(metadata_class_ids, labels.class_labels),
            sound_slot_ids=_integer_facets(
                (row.slot_id for row in sounds),
                labels.identifier_labels(IdentifierKind.SOUND_SLOT),
            ),
            campaigns=[
                row.campaign_id for row in sorted(metadata.campaigns, key=lambda row: row.ordinal)
            ],
            identifier_kinds=[
                kind
                for kind in _SIMPLE_IDENTIFIER_KINDS
                if any(row.kind is kind for row in metadata.identifiers)
            ],
        )

    async def _attribution_marker(self) -> str | None:
        rows = cast(
            list[_AttributionMarker],
            await self.characters_table.query()
            .select(list(_AttributionMarker.model_fields))
            .to_pydantic(_AttributionMarker),
        )
        return _published_attribution_timestamp(rows)

    async def characters(self, query: CharacterQuery) -> CharacterPage:
        conditions: list[Expr] = []
        if query.status is not None:
            conditions.append(col("detail_status") == lit(query.status))
        if query.source_kind is not None:
            conditions.append(col("source_kind") == lit(query.source_kind))
        if query.gender_id is not None:
            conditions.append(col("gender_id") == lit(query.gender_id))
        if query.race_id is not None:
            conditions.append(col("race_id") == lit(query.race_id))
        if query.class_id is not None:
            conditions.append(col("class_id") == lit(query.class_id))
        if query.attribution_status is not None:
            conditions.append(col("attribution_status") == lit(query.attribution_status))
        if query.has_dialog is not None:
            conditions.append(col("has_dialog") == lit(query.has_dialog))
        predicate = _combine(conditions)
        tokens = _search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "serialized_size")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        page_result, metadata = await asyncio.gather(
            _records_page(
                table=self.characters_table,
                model=CharacterRecord,
                search_model=_CharacterSearchResult,
                stable_column="resource_name",
                predicate=predicate,
                tokens=tokens,
                ordering=(
                    None if sort == "relevance" else _ordering(sort, direction, "resource_name")
                ),
                page=query,
            ),
            self._metadata_snapshot(),
        )
        total, records = page_result
        labels = _LabelResolver.from_snapshot(metadata)

        return CharacterPage(
            items=[_character_row(record, labels) for record in records],
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=_page_count(total, query.page_size),
            sort=sort,
            direction=direction,
        )

    async def dialogues(self, query: DialogueQuery) -> DialoguePage:
        attribution_marker = await self._attribution_marker()
        conditions: list[Expr] = []
        if query.status is not None:
            conditions.append(col("detail_status") == lit(query.status))
        if query.source_kind is not None:
            conditions.append(col("source_kind") == lit(query.source_kind))
        if query.attributed is not None:
            conditions.append(_attribution_filter(query.attributed, attribution_marker))
        predicate = _combine(conditions)
        tokens = _search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "dialogue_line_count")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        total, records = await _records_page(
            table=self.dialogues_table,
            model=DialogueRecord,
            search_model=_DialogueSearchResult,
            stable_column="resource_name",
            predicate=predicate,
            tokens=tokens,
            ordering=(None if sort == "relevance" else _ordering(sort, direction, "resource_name")),
            page=query,
        )

        return DialoguePage(
            items=[
                DialogueRow.model_validate(
                    record.model_dump(include=set(DialogueRow.model_fields))
                    | {
                        "character_count": _published_character_count(
                            record.character_count,
                            record.attribution_completed_at,
                            attribution_marker,
                        )
                    }
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

    async def lines(self, query: LineQuery) -> DialogueLinePage:
        attribution_marker = await self._attribution_marker()
        conditions: list[Expr] = []
        if query.line_kind is not None:
            conditions.append(col("line_kind") == lit(query.line_kind))
        if query.source_kind is not None:
            conditions.append(col("source_kind") == lit(query.source_kind))
        if query.attributed is not None:
            conditions.append(_attribution_filter(query.attributed, attribution_marker))
        predicate = _combine(conditions)
        tokens = _search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "serialized_size")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        total, records = await _records_page(
            table=self.lines_table,
            model=DialogueLineRecord,
            search_model=_LineSearchResult,
            stable_column="id",
            predicate=predicate,
            tokens=tokens,
            ordering=None if sort == "relevance" else _ordering(sort, direction, "id"),
            page=query,
        )

        return DialogueLinePage(
            items=[
                DialogueLineRow.model_validate(
                    record.model_dump(include=set(DialogueLineRow.model_fields))
                    | {
                        "character_count": _published_character_count(
                            record.character_count,
                            record.attribution_completed_at,
                            attribution_marker,
                        )
                    }
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
        predicate = col("slot_id") == lit(query.slot_id) if query.slot_id is not None else None
        tokens = _search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "serialized_size")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        metadata = await self._metadata_snapshot()
        page_result = (
            await _voice_records_page(
                table=self.character_sounds_table,
                identifiers_table=self.identifiers_table,
                groups_table=self.sound_slot_groups_table,
                predicate=predicate,
                tokens=tokens,
                metadata=metadata,
                sort=sort,
                direction=direction,
                page=query,
            )
            if tokens
            else await _records_page(
                table=self.character_sounds_table,
                model=CharacterSoundRecord,
                search_model=_VoiceSearchResult,
                stable_column="id",
                predicate=predicate,
                tokens=(),
                ordering=_ordering(sort, direction, "id"),
                page=query,
            )
        )
        total, records = page_result
        character_names: dict[str, str | None] = {}
        if records:
            names = cast(
                list[_CharacterName],
                await self.characters_table.query()
                .where(
                    col("resource_name").isin(
                        [record.character_resource_name for record in records]
                    )
                )
                .select(list(_CharacterName.model_fields))
                .to_pydantic(_CharacterName),
            )
            character_names = {row.resource_name.casefold(): row.display_name for row in names}
        symbols = _identifier_symbols(metadata.identifiers)
        return VoicePage(
            items=[
                VoiceRow(
                    key=record.id,
                    character_resource_name=record.character_resource_name,
                    character_name=character_names.get(record.character_resource_name.casefold()),
                    slot_id=record.slot_id,
                    slot_symbols=list(symbols.get((IdentifierKind.SOUND_SLOT, record.slot_id), ())),
                    slot_groups=_sound_slot_group_names(
                        metadata.sound_slot_groups,
                        record.slot_id,
                    ),
                    strref=record.strref,
                    text=record.text,
                    serialized_size=record.serialized_size,
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

    async def transitions(self, query: TransitionQuery) -> TransitionPage:
        predicate = (
            col("terminates_dialog") == lit(query.terminates_dialog)
            if query.terminates_dialog is not None
            else None
        )
        tokens = _search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "location")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        total, records = await _records_page(
            table=self.transitions_table,
            model=DialogueTransitionRecord,
            search_model=_TransitionSearchResult,
            stable_column="id",
            predicate=predicate,
            tokens=tokens,
            ordering=None if sort == "relevance" else _transition_ordering(sort, direction),
            page=query,
        )
        return TransitionPage(
            items=[
                TransitionRow.model_validate(
                    record.model_dump(include=set(TransitionRow.model_fields))
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
            _relevance_order(rows, scores)
            if sort == "relevance"
            else _metadata_order(rows, sort, direction)
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
            _relevance_order(rows, scores)
            if sort == "relevance"
            else _metadata_order(rows, sort, direction)
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
            _relevance_order(rows, scores)
            if sort == "relevance"
            else _metadata_order(rows, sort, direction)
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
            search_model=_IdentifierSearchResult,
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

    async def character_detail(self, resource_name: str) -> CharacterDetailResponse | None:
        record_rows, metadata = await asyncio.gather(
            self.characters_table.query()
            .where(col("resource_name") == lit(resource_name))
            .limit(1)
            .to_pydantic(CharacterRecord),
            self._metadata_snapshot(),
        )
        records = cast(list[CharacterRecord], record_rows)
        if not records or records[0].detail_status is not DetailStatus.COMPLETE:
            return None
        record = records[0]
        assert record.serialized_size is not None
        character = _character_detail_payload(record, _LabelResolver.from_snapshot(metadata))

        dialogue: DialogueDetail | None = None
        dialogue_serialized_size: int | None = None
        if record.dialog_resref is not None:
            dialogue_rows = cast(
                list[DialogueRecord],
                await self.dialogues_table.query()
                .where(col("resref") == lit(record.dialog_resref))
                .limit(1)
                .to_pydantic(DialogueRecord),
            )
        else:
            dialogue_rows = []
        if dialogue_rows and dialogue_rows[0].detail_status is DetailStatus.COMPLETE:
            direct = dialogue_rows[0]
            assert direct.state_count is not None
            assert direct.transition_count is not None
            assert direct.dlg_version is not None
            assert direct.npc_line_count is not None
            assert direct.player_line_count is not None
            assert direct.journal_line_count is not None
            assert direct.dialogue_line_count is not None
            assert direct.serialized_size is not None
            dialogue_serialized_size = direct.serialized_size
            dialogue = DialogueDetail(
                resource_name=direct.resource_name,
                resref=direct.resref,
                dlg_version=direct.dlg_version,
                state_count=direct.state_count,
                transition_count=direct.transition_count,
                npc_line_count=direct.npc_line_count,
                player_line_count=direct.player_line_count,
                journal_line_count=direct.journal_line_count,
                dialogue_line_count=direct.dialogue_line_count,
                pydantic_json_size=direct.serialized_size,
            )

        return CharacterDetailResponse(
            character=character,
            dialogue=dialogue,
            source_kind=record.source_kind,
            source_path=record.source_path,
            character_serialized_size=record.serialized_size,
            dialogue_serialized_size=dialogue_serialized_size,
            updated_at=record.updated_at,
            attribution_status=record.attribution_status,
        )


def create_app(
    database_path: Path = Path("data/bgvoice.lancedb"),
    frontend_dist: Path | None = None,
) -> FastAPI:
    """Create the API and optionally serve the compiled SPA from the same origin."""
    database: PipelineReader | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal database
        database = await PipelineReader.open(database_path)
        try:
            yield
        finally:
            database.close()
            database = None

    def reader() -> PipelineReader:
        assert database is not None, (
            "pipeline reader is unavailable outside the application lifespan"
        )
        return database

    app = FastAPI(title="BGVoice Pipeline Browser", version="0.1.0", lifespan=lifespan)

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return reader().health()

    @app.get("/api/stats", response_model=PipelineStats)
    async def stats() -> PipelineStats:
        return await reader().stats()

    @app.get("/api/filter-options", response_model=FilterOptions)
    async def filter_options() -> FilterOptions:
        return await reader().filter_options()

    @app.get("/api/characters", response_model=CharacterPage)
    async def characters(query: Annotated[CharacterQuery, Query()]) -> CharacterPage:
        return await reader().characters(query)

    @app.get("/api/characters/{resource_name}", response_model=CharacterDetailResponse)
    async def character_detail(resource_name: str) -> CharacterDetailResponse:
        detail = await reader().character_detail(resource_name)
        if detail is None:
            raise HTTPException(status_code=404, detail="character detail not found")
        return detail

    @app.get("/api/dialogues", response_model=DialoguePage)
    async def dialogues(query: Annotated[DialogueQuery, Query()]) -> DialoguePage:
        return await reader().dialogues(query)

    @app.get("/api/lines", response_model=DialogueLinePage)
    async def lines(query: Annotated[LineQuery, Query()]) -> DialogueLinePage:
        return await reader().lines(query)

    @app.get("/api/voices", response_model=VoicePage)
    async def voices(query: Annotated[VoiceQuery, Query()]) -> VoicePage:
        return await reader().voices(query)

    @app.get("/api/transitions", response_model=TransitionPage)
    async def transitions(query: Annotated[TransitionQuery, Query()]) -> TransitionPage:
        return await reader().transitions(query)

    @app.get("/api/races", response_model=RacePage)
    async def races(query: Annotated[RaceQuery, Query()]) -> RacePage:
        return await reader().races(query)

    @app.get("/api/classes", response_model=ClassPage)
    async def classes(query: Annotated[ClassQuery, Query()]) -> ClassPage:
        return await reader().classes(query)

    @app.get("/api/kits", response_model=KitPage)
    async def kits(query: Annotated[KitQuery, Query()]) -> KitPage:
        return await reader().kits(query)

    @app.get("/api/identifiers", response_model=IdentifierPage)
    async def identifiers(query: Annotated[IdentifierQuery, Query()]) -> IdentifierPage:
        return await reader().identifiers(query)

    dist = (frontend_dist or Path("frontend/dist")).expanduser().resolve()
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{spa_path:path}", include_in_schema=False)
        def spa(spa_path: str) -> FileResponse:
            candidate = (dist / spa_path).resolve()
            if spa_path and candidate.is_relative_to(dist) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


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


def _character_row(record: CharacterRecord, labels: _LabelResolver) -> CharacterRow:
    data = record.model_dump(include=set(CharacterRow.model_fields) - _CHARACTER_LABEL_FIELDS)
    data |= _character_labels(record, labels)
    return CharacterRow.model_validate(data)


def _character_detail_payload(
    record: CharacterRecord,
    labels: _LabelResolver,
) -> CharacterDetailPayload:
    data = record.model_dump(
        include=set(CharacterDetailPayload.model_fields) - _CHARACTER_LABEL_FIELDS
    )
    data |= _character_labels(record, labels)
    return CharacterDetailPayload.model_validate(data)


_CHARACTER_LABEL_FIELDS = {
    "gender_label",
    "race_label",
    "class_label",
    "alignment_label",
    "enemy_ally_label",
    "general_label",
    "specific_label",
    "animation_label",
    "racial_enemy_label",
    "kit_label",
}


def _character_labels(record: CharacterRecord, labels: _LabelResolver) -> dict[str, str | None]:
    return {
        "gender_label": _optional_identifier_label(
            labels,
            IdentifierKind.GENDER,
            record.gender_id,
        ),
        "race_label": None if record.race_id is None else labels.race_label(record.race_id),
        "class_label": None if record.class_id is None else labels.class_label(record.class_id),
        "alignment_label": _optional_identifier_label(
            labels,
            IdentifierKind.ALIGNMENT,
            record.alignment_id,
        ),
        "enemy_ally_label": _optional_identifier_label(
            labels,
            IdentifierKind.ENEMY_ALLY,
            record.enemy_ally_id,
        ),
        "general_label": _optional_identifier_label(
            labels,
            IdentifierKind.GENERAL,
            record.general_id,
        ),
        "specific_label": _optional_identifier_label(
            labels,
            IdentifierKind.SPECIFIC,
            record.specific_id,
        ),
        "animation_label": _optional_identifier_label(
            labels,
            IdentifierKind.ANIMATION,
            record.animation_id,
        ),
        "racial_enemy_label": (
            None
            if record.racial_enemy_id is None
            else labels.favored_enemy_label(record.racial_enemy_id)
        ),
        "kit_label": labels.kit_label(record.kit_ids_value, record.class_id),
    }


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


def _relevance_order[Row: _Keyed](
    rows: Sequence[Row],
    scores: Mapping[str, float],
) -> list[Row]:
    return sorted(rows, key=lambda row: (-scores[row.key], row.key))


def _metadata_order[Row: _Keyed](
    rows: Sequence[Row],
    column: str,
    direction: SortDirection,
) -> list[Row]:
    non_null = [row for row in rows if getattr(row, column) is not None]
    null = sorted(
        (row for row in rows if getattr(row, column) is None),
        key=lambda row: row.key,
    )
    non_null.sort(key=lambda row: row.key)
    non_null.sort(key=attrgetter(column), reverse=direction == "desc")
    return [*non_null, *null]


def _page_items[Row](rows: Sequence[Row], query: PageQuery) -> list[Row]:
    offset = _page_offset(query)
    return list(rows[offset : offset + query.page_size])


async def _voice_records_page(
    *,
    table: AsyncTable,
    identifiers_table: AsyncTable,
    groups_table: AsyncTable,
    predicate: Expr | None,
    tokens: tuple[str, ...],
    metadata: _MetadataSnapshot,
    sort: VoiceSort | Literal["relevance"],
    direction: SortDirection,
    page: PageQuery,
) -> tuple[int, list[CharacterSoundRecord]]:
    """Merge voice-text BM25 matches with typed sound-slot metadata matches."""
    assert tokens
    candidate_columns = list(_VoiceCandidate.model_fields)
    row_count = await table.count_rows()
    sound_query = table.query().nearest_to_text(_fts_query(tokens))
    if predicate is not None:
        sound_query = sound_query.where(predicate)

    sound_rows, identifier_scores, group_scores = await asyncio.gather(
        sound_query.limit(max(1, row_count))
        .select([*candidate_columns, "_score"])
        .to_pydantic(_VoiceSearchCandidate),
        _fts_scores(
            table=identifiers_table,
            tokens=tokens,
            predicate=col("kind") == lit(IdentifierKind.SOUND_SLOT.value),
        ),
        _fts_scores(
            table=groups_table,
            tokens=tokens,
        ),
    )
    sounds = cast(list[_VoiceSearchCandidate], sound_rows)

    slot_scores: dict[int, float] = {}
    for row in metadata.identifiers:
        if row.kind is IdentifierKind.SOUND_SLOT and row.key in identifier_scores:
            slot_scores[row.value] = max(
                slot_scores.get(row.value, float("-inf")),
                identifier_scores[row.key],
            )
    for group in metadata.sound_slot_groups:
        if group.key not in group_scores or group.offset is None or group.count is None:
            continue
        for slot_id in range(group.offset, min(0x100, group.offset + group.count)):
            slot_scores[slot_id] = max(
                slot_scores.get(slot_id, float("-inf")),
                group_scores[group.key],
            )

    metadata_rows: list[_VoiceCandidate] = []
    if slot_scores:
        metadata_predicate = col("slot_id").isin(list(slot_scores))
        if predicate is not None:
            metadata_predicate = metadata_predicate.and_(predicate)
        metadata_rows = cast(
            list[_VoiceCandidate],
            await table.query()
            .where(metadata_predicate)
            .select(candidate_columns)
            .to_pydantic(_VoiceCandidate),
        )

    candidates: dict[str, _VoiceCandidate] = {row.id: row for row in sounds}
    scores = {row.id: row.score for row in sounds}
    for row in metadata_rows:
        candidates.setdefault(row.id, row)
        scores[row.id] = max(
            scores.get(row.id, float("-inf")),
            slot_scores[row.slot_id],
        )

    ordered = sorted(candidates.values(), key=lambda row: row.id)
    if sort == "relevance":
        ordered.sort(key=lambda row: scores[row.id], reverse=True)
    else:
        ordered.sort(key=attrgetter(sort), reverse=direction == "desc")

    page_ids = [row.id for row in _page_items(ordered, page)]
    if not page_ids:
        return len(ordered), []
    unordered_records = cast(
        list[CharacterSoundRecord],
        await table.query()
        .where(col("id").isin(page_ids))
        .limit(len(page_ids))
        .to_pydantic(CharacterSoundRecord),
    )
    records_by_id = {record.id: record for record in unordered_records}
    assert records_by_id.keys() == set(page_ids)
    return len(ordered), [records_by_id[record_id] for record_id in page_ids]


async def _records_page[Record: LanceModel](
    *,
    table: AsyncTable,
    model: type[Record],
    search_model: type[Record],
    stable_column: StableColumn,
    predicate: Expr | None,
    tokens: tuple[str, ...],
    ordering: list[ColumnOrdering] | None,
    page: PageQuery,
) -> tuple[int, list[Record]]:
    """Run the typed pagination path shared by record-backed browser tables."""
    if tokens:

        def search() -> AsyncFTSQuery:
            query = table.query().nearest_to_text(_fts_query(tokens))
            return query.where(predicate) if predicate is not None else query

        match_limit = max(1, await table.count_rows())
        if ordering is None:
            matches, record_rows = await asyncio.gather(
                search().limit(match_limit).select([stable_column, "_score"]).to_arrow(),
                search()
                .offset(_page_offset(page))
                .limit(page.page_size)
                .select([*model.model_fields, "_score"])
                .to_pydantic(search_model),
            )
            return cast(int, matches.num_rows), cast(list[Record], record_rows)

        projected_columns = list(
            dict.fromkeys(
                [
                    stable_column,
                    *(item.column_name for item in ordering),
                    "_score",
                ]
            )
        )
        matches = await search().limit(match_limit).select(projected_columns).to_arrow()
        if matches.num_rows == 0:
            return 0, []

        matches = matches.sort_by(
            [
                (
                    item.column_name,
                    "ascending" if item.ascending else "descending",
                    "at_start" if item.nulls_first else "at_end",
                )
                for item in ordering
            ]
        )
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


def _published_attribution_timestamp(rows: Sequence[_AttributionMarker]) -> str | None:
    if not rows:
        return None
    timestamp = rows[0].attribution_completed_at
    if timestamp is None or any(row.attribution_completed_at != timestamp for row in rows):
        return None
    return timestamp


def _attribution_filter(attributed: bool, published_at: str | None) -> Expr:
    character_count = col("character_count")
    if published_at is None:
        return character_count < lit(0) if attributed else character_count >= lit(0)

    same_generation = col("attribution_completed_at") == lit(published_at)
    if attributed:
        return same_generation.and_(character_count > lit(0))
    return (character_count == lit(0)).or_(col("attribution_completed_at") != lit(published_at))


def _published_character_count(
    character_count: int,
    attributed_at: str | None,
    published_at: str | None,
) -> int:
    if published_at is None or attributed_at != published_at:
        return 0
    return character_count


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


def _string_facets(values: Iterable[str]) -> list[FacetValue]:
    counts = Counter(values)
    return [
        FacetValue(value=value, label=None, count=count)
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _integer_facets(
    values: Iterable[int],
    labels: Mapping[int, str] | None = None,
) -> list[FacetValue]:
    counts = Counter(values)
    return [
        FacetValue(
            value=value,
            label=(None if labels is None else labels.get(value, f"Unknown ({value})")),
            count=count,
        )
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
