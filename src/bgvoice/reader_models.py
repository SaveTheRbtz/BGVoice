"""Typed query and result models for pipeline inspection."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bgvoice.model_types import (
    AttributionPublicationStatus,
    AttributionStatus,
    DetailStatus,
    DialogueLineKind,
    IdentifierKind,
    SourceKind,
)
from bgvoice.storage_records import CharacterDirection, NarratorDirection

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

SIMPLE_IDENTIFIER_KINDS: tuple[SimpleIdentifierKind, ...] = (
    IdentifierKind.GENDER,
    IdentifierKind.ALIGNMENT,
    IdentifierKind.ENEMY_ALLY,
    IdentifierKind.GENERAL,
    IdentifierKind.SPECIFIC,
    IdentifierKind.ANIMATION,
    IdentifierKind.SOUND_SLOT,
)


class _ReaderModel(BaseModel):
    """Strict projection returned by the pipeline reader."""

    model_config = ConfigDict(strict=True, extra="forbid")


class PageQuery(BaseModel):
    """Internal page window used by LanceDB browse queries."""

    model_config = ConfigDict(strict=False, extra="forbid")

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=10, le=100)


class ResultPage[Row, Sort](_ReaderModel):
    items: list[Row]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: Sort
    direction: SortDirection


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
    dialogue_resource_name: str | None = Field(default=None, min_length=1, max_length=300)
    voice_id: str | None = Field(default=None, min_length=1, max_length=300)
    directed: bool | None = None
    voiced: bool | None = None
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


class CharacterPage(ResultPage[CharacterRow, CharacterSort | Literal["relevance"]]):
    pass


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
    directed_line_count: int
    generated_audio_count: int
    updated_at: str


class DialoguePage(ResultPage[DialogueRow, DialogueSort | Literal["relevance"]]):
    pass


class DirectedLineRow(_ReaderModel):
    id: str
    voice_id: str
    voice_display_name: str
    character: CharacterDirection | None
    narrator: NarratorDirection | None
    audio_id: str | None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        assert (self.character is None) != (self.narrator is None), (
            "a directed line must contain exactly one character or narrator result"
        )
        return self


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
    directions: list[DirectedLineRow]


class DialogueLinePage(ResultPage[DialogueLineRow, LineSort | Literal["relevance"]]):
    pass


class GeneratedVoiceRow(_ReaderModel):
    description: str
    language_code: str
    inworld_voice_id: str
    created_at: str


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
    generated_voice: GeneratedVoiceRow | None
    directed_line_count: int
    generated_audio_count: int


class VoicePage(ResultPage[VoiceRow, VoiceSort | Literal["relevance"]]):
    pass


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


class SoundPage(ResultPage[SoundRow, SoundSort | Literal["relevance"]]):
    pass


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


class TransitionPage(ResultPage[TransitionRow, TransitionSort | Literal["relevance"]]):
    pass


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


class RacePage(ResultPage[RaceRow, RaceSort | Literal["relevance"]]):
    pass


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


class ClassPage(ResultPage[ClassRow, ClassSort | Literal["relevance"]]):
    pass


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


class KitPage(ResultPage[KitRow, KitSort | Literal["relevance"]]):
    pass


class IdentifierRow(_ReaderModel):
    key: str
    kind: SimpleIdentifierKind
    value: int
    symbols: list[str]
    source_resource: str


class IdentifierPage(ResultPage[IdentifierRow, IdentifierSort | Literal["relevance"]]):
    pass


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
    generated_voices: int = Field(ge=0)
    directed_lines: int = Field(ge=0)
    generated_audios: int = Field(ge=0)
    running_tts_batches: int = Field(ge=0)
    failed_tts_batches: int = Field(ge=0)
    voice_creation_failures: int = Field(ge=0)
    dialogue_direction_failures: int = Field(ge=0)
    audio_generation_failures: int = Field(ge=0)
