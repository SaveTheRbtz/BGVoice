"""Typed LanceDB storage for the EET extraction pipeline."""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Self
from uuid import uuid4

import lancedb
import pyarrow as pa
from lancedb.expr import col
from lancedb.index import FTS, BTree
from lancedb.pydantic import LanceModel
from lancedb.table import Table
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bgvoice.models import (
    AttributionStatus,
    AttributionSummary,
    CampaignDefinition,
    CampaignResourceBinding,
    CampaignResourceKind,
    CharacterDetail,
    CharacterExtraction,
    CharacterResourceRole,
    CharacterSound,
    ClassTextRow,
    CreResource,
    DatabaseStats,
    DetailStatus,
    DialogueExtraction,
    DialogueLine,
    DialogueLineKind,
    DialogueTransitionEdge,
    DlgResource,
    ExtractionState,
    HappinessAlignment,
    IdentifierDefinition,
    IdentifierKind,
    InteractionKind,
    KitDefinition,
    MetadataExtraction,
    RaceTextRow,
    ResourceSource,
    ResourceTargetType,
    RunKind,
    RunStatus,
    TerminalRunStatus,
    VoiceId,
    VoiceResource,
    compose_search_text,
    proposed_voice_id,
    utc_now,
)

_CHARACTERS = "characters"
_CHARACTER_SOUNDS = "character_sounds"
_CHARACTER_DIALOGUES = "character_dialogues"
_VOICE_RESOURCES = "voice_resources"
_DIALOGUES = "dialogues"
_DIALOGUE_LINES = "dialogue_lines"
_DIALOGUE_TRANSITIONS = "dialogue_transitions"
_EXTRACTION_RUNS = "extraction_runs"
_IDENTIFIER_DEFINITIONS = "identifier_definitions"
_CAMPAIGNS = "campaigns"
_CAMPAIGN_RESOURCE_BINDINGS = "campaign_resource_bindings"
_CHARACTER_RESOURCE_LINKS = "character_resource_links"
_INTERACTION_RULES = "interaction_rules"
_SOUNDSET_LINES = "soundset_lines"
_SOUND_SLOT_SUFFIXES = "sound_slot_suffixes"
_SOUND_SLOT_GROUPS = "sound_slot_groups"
_FAVORED_ENEMIES = "favored_enemies"
_HAPPINESS_RULES = "happiness_rules"
_BANTER_TIMING_SETTINGS = "banter_timing_settings"
_ENGINE_STRINGS = "engine_strings"
_MONTHS = "months"
_CAMPAIGN_CALENDARS = "campaign_calendars"
_RACE_TEXTS = "race_texts"
_CLASS_TEXTS = "class_texts"
_KITS = "kits"
_METADATA_TABLES = (
    _IDENTIFIER_DEFINITIONS,
    _CAMPAIGNS,
    _CAMPAIGN_RESOURCE_BINDINGS,
    _CHARACTER_RESOURCE_LINKS,
    _INTERACTION_RULES,
    _SOUNDSET_LINES,
    _SOUND_SLOT_SUFFIXES,
    _SOUND_SLOT_GROUPS,
    _FAVORED_ENEMIES,
    _HAPPINESS_RULES,
    _BANTER_TIMING_SETTINGS,
    _ENGINE_STRINGS,
    _MONTHS,
    _CAMPAIGN_CALENDARS,
    _RACE_TEXTS,
    _CLASS_TEXTS,
    _KITS,
)
TABLE_NAMES = frozenset(
    {
        _CHARACTERS,
        _CHARACTER_SOUNDS,
        _CHARACTER_DIALOGUES,
        _VOICE_RESOURCES,
        _DIALOGUES,
        _DIALOGUE_LINES,
        _DIALOGUE_TRANSITIONS,
        _EXTRACTION_RUNS,
        *_METADATA_TABLES,
    }
)

_FTS = FTS(
    base_tokenizer="simple",
    language="English",
    with_position=True,
    max_token_length=64,
    lower_case=True,
    stem=True,
    remove_stop_words=False,
    ascii_folding=True,
)


@dataclass(frozen=True, slots=True)
class IndexSpec:
    column: str
    config: BTree | FTS
    name: str


TABLE_INDEXES: dict[str, tuple[IndexSpec, ...]] = {
    _CHARACTERS: (
        IndexSpec("resource_name", BTree(), "characters_resource_name_btree"),
        IndexSpec("search_text", _FTS, "characters_search_fts"),
    ),
    _CHARACTER_SOUNDS: (
        IndexSpec("id", BTree(), "character_sounds_id_btree"),
        IndexSpec(
            "character_resource_name",
            BTree(),
            "character_sounds_character_btree",
        ),
        IndexSpec("slot_id", BTree(), "character_sounds_slot_btree"),
        IndexSpec("search_text", _FTS, "character_sounds_search_fts"),
    ),
    _CHARACTER_DIALOGUES: (
        IndexSpec("key", BTree(), "character_dialogues_key_btree"),
        IndexSpec("run_id", BTree(), "character_dialogues_run_btree"),
        IndexSpec(
            "character_resource_name",
            BTree(),
            "character_dialogues_character_btree",
        ),
    ),
    _VOICE_RESOURCES: (
        IndexSpec("key", BTree(), "voice_resources_key_btree"),
        IndexSpec("run_id", BTree(), "voice_resources_run_btree"),
        IndexSpec("voice_id", BTree(), "voice_resources_voice_id_btree"),
        IndexSpec("search_text", _FTS, "voice_resources_search_fts"),
    ),
    _DIALOGUES: (
        IndexSpec("resource_name", BTree(), "dialogues_resource_name_btree"),
        IndexSpec("search_text", _FTS, "dialogues_search_fts"),
    ),
    _DIALOGUE_LINES: (
        IndexSpec("id", BTree(), "dialogue_lines_id_btree"),
        IndexSpec(
            "dialogue_resource_name",
            BTree(),
            "dialogue_lines_dialogue_btree",
        ),
        IndexSpec("search_text", _FTS, "dialogue_lines_search_fts"),
    ),
    _DIALOGUE_TRANSITIONS: (
        IndexSpec("id", BTree(), "dialogue_transitions_id_btree"),
        IndexSpec(
            "dialogue_resource_name",
            BTree(),
            "dialogue_transitions_dialogue_btree",
        ),
        IndexSpec("next_dialog", BTree(), "dialogue_transitions_next_dialog_btree"),
        IndexSpec("search_text", _FTS, "dialogue_transitions_search_fts"),
    ),
    _EXTRACTION_RUNS: (),
    _IDENTIFIER_DEFINITIONS: (
        IndexSpec("key", BTree(), "identifier_definitions_key_btree"),
        IndexSpec("kind", BTree(), "identifier_definitions_kind_btree"),
        IndexSpec("value", BTree(), "identifier_definitions_value_btree"),
        IndexSpec("search_text", _FTS, "identifier_definitions_search_fts"),
    ),
    _CAMPAIGNS: (
        IndexSpec("key", BTree(), "campaigns_key_btree"),
        IndexSpec("campaign_id", BTree(), "campaigns_campaign_id_btree"),
    ),
    _CAMPAIGN_RESOURCE_BINDINGS: (
        IndexSpec("key", BTree(), "campaign_resource_bindings_key_btree"),
        IndexSpec("campaign_id", BTree(), "campaign_resource_bindings_campaign_btree"),
        IndexSpec(
            "resource_resref",
            BTree(),
            "campaign_resource_bindings_resource_btree",
        ),
    ),
    _CHARACTER_RESOURCE_LINKS: (
        IndexSpec("key", BTree(), "character_resource_links_key_btree"),
        IndexSpec(
            "death_variable",
            BTree(),
            "character_resource_links_death_variable_btree",
        ),
        IndexSpec(
            "target_resref",
            BTree(),
            "character_resource_links_target_btree",
        ),
        IndexSpec("search_text", _FTS, "character_resource_links_search_fts"),
    ),
    _INTERACTION_RULES: (
        IndexSpec("key", BTree(), "interaction_rules_key_btree"),
        IndexSpec(
            "speaker_death_variable",
            BTree(),
            "interaction_rules_speaker_btree",
        ),
        IndexSpec(
            "target_death_variable",
            BTree(),
            "interaction_rules_target_btree",
        ),
        IndexSpec("search_text", _FTS, "interaction_rules_search_fts"),
    ),
    _SOUNDSET_LINES: (
        IndexSpec("key", BTree(), "soundset_lines_key_btree"),
        IndexSpec("soundset_name", BTree(), "soundset_lines_soundset_btree"),
        IndexSpec("slot_id", BTree(), "soundset_lines_slot_btree"),
        IndexSpec("search_text", _FTS, "soundset_lines_search_fts"),
    ),
    _SOUND_SLOT_SUFFIXES: (
        IndexSpec("key", BTree(), "sound_slot_suffixes_key_btree"),
        IndexSpec("slot_id", BTree(), "sound_slot_suffixes_slot_btree"),
    ),
    _SOUND_SLOT_GROUPS: (
        IndexSpec("key", BTree(), "sound_slot_groups_key_btree"),
        IndexSpec("row_name", BTree(), "sound_slot_groups_row_name_btree"),
        IndexSpec("search_text", _FTS, "sound_slot_groups_search_fts"),
    ),
    _FAVORED_ENEMIES: (
        IndexSpec("key", BTree(), "favored_enemies_key_btree"),
        IndexSpec("race_id", BTree(), "favored_enemies_race_id_btree"),
        IndexSpec("search_text", _FTS, "favored_enemies_search_fts"),
    ),
    _HAPPINESS_RULES: (
        IndexSpec("key", BTree(), "happiness_rules_key_btree"),
        IndexSpec("reputation", BTree(), "happiness_rules_reputation_btree"),
        IndexSpec("alignment", BTree(), "happiness_rules_alignment_btree"),
    ),
    _BANTER_TIMING_SETTINGS: (IndexSpec("key", BTree(), "banter_timing_settings_key_btree"),),
    _ENGINE_STRINGS: (
        IndexSpec("key", BTree(), "engine_strings_key_btree"),
        IndexSpec("strref", BTree(), "engine_strings_strref_btree"),
        IndexSpec("search_text", _FTS, "engine_strings_search_fts"),
    ),
    _MONTHS: (
        IndexSpec("key", BTree(), "months_key_btree"),
        IndexSpec("month_id", BTree(), "months_month_id_btree"),
        IndexSpec("search_text", _FTS, "months_search_fts"),
    ),
    _CAMPAIGN_CALENDARS: (
        IndexSpec("key", BTree(), "campaign_calendars_key_btree"),
        IndexSpec("search_text", _FTS, "campaign_calendars_search_fts"),
    ),
    _RACE_TEXTS: (
        IndexSpec("key", BTree(), "race_texts_key_btree"),
        IndexSpec("race_id", BTree(), "race_texts_race_id_btree"),
        IndexSpec("source_resource", BTree(), "race_texts_source_resource_btree"),
        IndexSpec("search_text", _FTS, "race_texts_search_fts"),
    ),
    _CLASS_TEXTS: (
        IndexSpec("key", BTree(), "class_texts_key_btree"),
        IndexSpec("class_id", BTree(), "class_texts_class_id_btree"),
        IndexSpec("source_resource", BTree(), "class_texts_source_resource_btree"),
        IndexSpec("search_text", _FTS, "class_texts_search_fts"),
    ),
    _KITS: (
        IndexSpec("key", BTree(), "kits_key_btree"),
        IndexSpec("row_id", BTree(), "kits_row_id_btree"),
        IndexSpec("class_id", BTree(), "kits_class_id_btree"),
        IndexSpec("kit_ids_value", BTree(), "kits_kit_ids_value_btree"),
        IndexSpec("search_text", _FTS, "kits_search_fts"),
    ),
}


class _Record(LanceModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    @classmethod
    def to_arrow_schema(cls) -> pa.Schema:
        """Store typed string enums as ordinary UTF-8 Lance columns."""
        schema = super().to_arrow_schema()
        fields = [_string_enum_field(field) for field in schema]
        return pa.schema(fields, metadata=schema.metadata)


def _string_enum_field(field: pa.Field, parent_nullable: bool = False) -> pa.Field:
    field_type = field.type
    if pa.types.is_dictionary(field_type):
        field_type = pa.string()
    elif pa.types.is_struct(field_type):
        field_type = pa.struct(
            [_string_enum_field(child, parent_nullable or field.nullable) for child in field_type]
        )
    return pa.field(
        field.name,
        field_type,
        field.nullable or parent_nullable,
        field.metadata,
    )


class _KeyedRecord(_Record):
    """A persisted metadata row with a stable domain-owned key."""

    key: str = Field(min_length=1)


class CharacterClassLevels(BaseModel):
    """Storage-compatible CRE class levels."""

    model_config = ConfigDict(strict=True, extra="forbid")

    first_class: int = Field(ge=0, le=0xFF)
    second_class: int = Field(ge=0, le=0xFF)
    third_class: int = Field(ge=0, le=0xFF)


class CharacterBaseAttributes(BaseModel):
    """Storage-compatible CRE ability scores."""

    model_config = ConfigDict(strict=True, extra="forbid")

    strength: int = Field(ge=0, le=0xFF)
    strength_bonus: int = Field(ge=0, le=100)
    intelligence: int = Field(ge=0, le=0xFF)
    wisdom: int = Field(ge=0, le=0xFF)
    dexterity: int = Field(ge=0, le=0xFF)
    constitution: int = Field(ge=0, le=0xFF)
    charisma: int = Field(ge=0, le=0xFF)


class CharacterData(BaseModel):
    """Storage-compatible intrinsic CRE detail."""

    model_config = ConfigDict(strict=True, extra="forbid")

    display_name: str
    short_name: str | None
    short_name_strref: int = Field(ge=0)
    long_name: str | None
    long_name_strref: int = Field(ge=0)
    death_variable: str | None
    dialog_resref: str | None
    gender_id: int = Field(ge=0)
    race_id: int = Field(ge=0)
    class_id: int = Field(ge=0)
    alignment_id: int = Field(ge=0)
    enemy_ally_id: int = Field(ge=0)
    general_id: int = Field(ge=0)
    specific_id: int = Field(ge=0)
    animation_id: int = Field(ge=0)
    racial_enemy_id: int = Field(ge=0)
    class_levels: CharacterClassLevels
    base_attributes: CharacterBaseAttributes
    morale: int = Field(ge=0)
    morale_break: int = Field(ge=0)
    morale_recovery_time: int = Field(ge=0)
    reputation: int = Field(ge=0)
    kit_raw_bytes: list[int]
    cre_kit_value: int = Field(ge=0)
    kit_ids_value: int | None = Field(default=None, ge=0)
    override_script: str | None
    class_script: str | None
    race_script: str | None
    general_script: str | None
    default_script: str | None
    small_portrait: str | None
    large_portrait: str | None
    cre_version: str


class DialogueData(BaseModel):
    """Storage-compatible intrinsic DLG detail."""

    model_config = ConfigDict(strict=True, extra="forbid")

    dlg_version: str
    state_count: int = Field(ge=0)
    transition_count: int = Field(ge=0)
    npc_line_count: int = Field(ge=0)
    player_line_count: int = Field(ge=0)
    journal_line_count: int = Field(ge=0)
    dialogue_line_count: int = Field(ge=0)


class CharacterRecord(_Record):
    """One effective CRE and only the detail owned by CRE extraction."""

    resource_name: str = Field(min_length=1)
    resref: str = Field(min_length=1, max_length=8)
    source: ResourceSource
    extraction: ExtractionState
    detail: CharacterData | None = None
    serialized_size: int | None = Field(default=None, ge=0)
    search_text: str

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        complete = self.extraction.status is DetailStatus.COMPLETE
        assert complete == (self.detail is not None), "only complete CREs carry detail"
        assert complete == (self.serialized_size is not None), (
            "only complete CREs carry a serialized size"
        )
        return self


class CharacterSoundRecord(_Record):
    """One populated CRE soundset slot."""

    id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    character_resource_name: str = Field(min_length=1)
    slot_id: int = Field(ge=0, le=0xFF)
    strref: int = Field(ge=0, le=0xFFFF_FFFF)
    text: str | None
    serialized_size: int = Field(ge=0)
    search_text: str

    @model_validator(mode="after")
    def validate_id(self) -> Self:
        expected = CharacterSound.id_for(self.character_resource_name, self.slot_id)
        assert self.id == expected, f"character sound id must be {expected!r}"
        return self


class CharacterAttributionRecord(_Record):
    """One character's run-scoped dialogue attribution result."""

    key: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    character_resource_name: str = Field(min_length=1)
    status: AttributionStatus = Field(strict=False)
    dialogue_status: DetailStatus | None = Field(default=None, strict=False)
    declared_dialogue_resrefs: list[str]
    missing_dialogue_resrefs: list[str]
    resolved_dialogue_resource_names: list[str]

    @staticmethod
    def key_for(run_id: str, character_resource_name: str) -> str:
        return f"{run_id}:{character_resource_name.upper()}"

    @model_validator(mode="after")
    def validate_key(self) -> Self:
        expected = self.key_for(self.run_id, self.character_resource_name)
        assert self.key == expected, f"character attribution key must be {expected!r}"
        return self


class VoiceResourceRecord(_Record):
    """One run-scoped canonical voice and its CRE membership."""

    key: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    voice_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    variant_resource_names: list[str] = Field(min_length=1)
    dialogue_resrefs: list[str]
    search_text: str

    @staticmethod
    def key_for(run_id: str, voice_id: str) -> str:
        return f"{run_id}:{voice_id}"

    @model_validator(mode="after")
    def validate_key(self) -> Self:
        expected = self.key_for(self.run_id, self.voice_id)
        assert self.key == expected, f"voice resource key must be {expected!r}"
        return self


class DialogueRecord(_Record):
    """One effective DLG and only the detail owned by DLG extraction."""

    resource_name: str = Field(min_length=1)
    resref: str = Field(min_length=1, max_length=8)
    source: ResourceSource
    extraction: ExtractionState
    detail: DialogueData | None = None
    serialized_size: int | None = Field(default=None, ge=0)
    search_text: str

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        complete = self.extraction.status is DetailStatus.COMPLETE
        assert complete == (self.detail is not None), "only complete DLGs carry detail"
        assert complete == (self.serialized_size is not None), (
            "only complete DLGs carry a serialized size"
        )
        return self


class DialogueLineRecord(_Record):
    """One stable, addressable DLG line."""

    id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    dialogue_resource_name: str = Field(min_length=1)
    line_kind: DialogueLineKind = Field(strict=False)
    state_index: int = Field(ge=0)
    state_trigger_index: int | None = Field(default=None, ge=0)
    state_trigger_text: str | None = None
    transition_index: int | None = Field(default=None, ge=0)
    strref: int = Field(ge=0)
    text: str | None
    tokens: list[str]
    serialized_size: int = Field(ge=0)
    search_text: str

    @model_validator(mode="after")
    def validate_coordinates(self) -> Self:
        assert (self.line_kind is DialogueLineKind.NPC) == (self.transition_index is None), (
            "NPC lines must omit transition_index; player and journal lines must include it"
        )
        assert self.state_trigger_text is None or self.state_trigger_index is not None, (
            "state trigger text requires a trigger index"
        )
        assert self.line_kind is DialogueLineKind.NPC or self.state_trigger_index is None, (
            "only NPC state rows carry DLG state triggers"
        )
        expected_id = DialogueLine.id_for(
            self.dialogue_resource_name,
            self.line_kind,
            self.state_index,
            self.transition_index,
        )
        assert self.id == expected_id, f"dialogue line id must be {expected_id!r}"
        return self


class DialogueTransitionRecord(_Record):
    """One stable edge in a DLG state machine."""

    id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    dialogue_resource_name: str = Field(min_length=1)
    state_index: int = Field(ge=0)
    transition_index: int = Field(ge=0)
    flags_raw: int = Field(ge=0, le=0xFFFF_FFFF)
    flags_decoded: list[str]
    trigger_index: int | None = Field(default=None, ge=0)
    trigger_text: str | None
    action_index: int | None = Field(default=None, ge=0)
    action_text: str | None
    next_dialog: str | None = Field(default=None, min_length=1, max_length=8)
    next_state_index: int | None = Field(default=None, ge=0)
    terminates_dialog: bool
    serialized_size: int = Field(ge=0)
    search_text: str

    @model_validator(mode="after")
    def validate_edge(self) -> Self:
        expected = DialogueTransitionEdge.id_for(
            self.dialogue_resource_name,
            self.state_index,
            self.transition_index,
        )
        assert self.id == expected, f"dialogue transition id must be {expected!r}"
        assert self.trigger_text is None or self.trigger_index is not None, (
            "transition trigger text requires a trigger index"
        )
        assert self.action_text is None or self.action_index is not None, (
            "transition action text requires an action index"
        )
        assert (self.next_state_index is None) == self.terminates_dialog, (
            "transition must terminate exactly when it has no destination state"
        )
        return self


class ExtractionRunRecord(_Record):
    """Durable lifecycle record for one inventory and detail extraction run."""

    id: str = Field(min_length=1)
    run_kind: RunKind = Field(strict=False)
    started_at: str = Field(min_length=1)
    completed_at: str | None = None
    game_root: str = Field(min_length=1)
    iecli_version: str = Field(min_length=1)
    character_input_run_id: str | None = None
    dialogue_input_run_id: str | None = None
    metadata_input_run_id: str | None = None
    status: RunStatus = Field(strict=False)
    resources_discovered: int = Field(ge=0)
    details_attempted: int = Field(ge=0)
    details_extracted: int = Field(ge=0)
    failures: int = Field(ge=0)
    error: str | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        assert (self.status is RunStatus.RUNNING) == (self.completed_at is None), (
            "running runs must be open and terminal runs must have a completion time"
        )
        return self


class IdentifierDefinitionRecord(_KeyedRecord):
    """One normalized IDS value and all aliases from its effective resource."""

    kind: IdentifierKind = Field(strict=False)
    value: int = Field(ge=0)
    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    symbols: list[str]
    search_text: str


class CampaignDefinitionRecord(_KeyedRecord):
    """One campaign row from the effective CAMPAIGN.2DA."""

    campaign_id: str = Field(min_length=1)
    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)


class CampaignResourceBindingRecord(_KeyedRecord):
    """One campaign-selected effective resource relationship."""

    campaign_id: str = Field(min_length=1)
    resource_kind: CampaignResourceKind = Field(strict=False)
    resource_resref: str | None = None


class CharacterResourceLinkRecord(_KeyedRecord):
    """One dialogue or script associated with a character death variable."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    death_variable: str = Field(min_length=1)
    source_column: str = Field(min_length=1)
    role: CharacterResourceRole = Field(strict=False)
    target_type: ResourceTargetType = Field(strict=False)
    target_resref: str = Field(min_length=1, max_length=8)
    search_text: str


class InteractionRuleRecord(_KeyedRecord):
    """One non-empty party interaction matrix edge."""

    source_resource: str = Field(min_length=1)
    speaker_ordinal: int = Field(ge=0)
    target_ordinal: int = Field(ge=0)
    speaker_death_variable: str = Field(min_length=1)
    target_death_variable: str = Field(min_length=1)
    kind: InteractionKind = Field(strict=False)
    search_text: str


class SoundsetLineRecord(_KeyedRecord):
    """One populated CHARSND soundset/slot cell."""

    source_resource: str = Field(min_length=1)
    soundset_name: str = Field(min_length=1)
    slot_id: int = Field(ge=0, le=0xFF)
    strref: int = Field(ge=0, le=0xFFFF_FFFF)
    text: str | None
    search_text: str


class SoundSlotSuffixRecord(_KeyedRecord):
    """One CSOUND slot-to-audio-filename suffix mapping."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    slot_id: int = Field(ge=0, le=0xFF)
    file_suffix: str | None


class SoundSlotGroupRecord(_KeyedRecord):
    """One named SPEECH.2DA range over CRE soundset slots."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    row_name: str = Field(min_length=1)
    offset: int | None = Field(default=None, ge=0, le=0xFF)
    count: int | None = Field(default=None, gt=0)
    search_text: str

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        assert (self.offset is None) == (self.count is None), (
            "SPEECH offset and count must both be present or absent"
        )
        return self


class FavoredEnemyRecord(_KeyedRecord):
    """One localized HATERACE.2DA racial-enemy choice."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    row_name: str = Field(min_length=1)
    name_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    name: str | None
    race_id: int = Field(ge=0, le=0xFF)
    help_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    help_text: str | None
    search_text: str


class HappinessRuleRecord(_KeyedRecord):
    """One HAPPY.2DA alignment/reputation matrix cell."""

    source_resource: str = Field(min_length=1)
    reputation: int = Field(ge=1, le=20)
    alignment: HappinessAlignment = Field(strict=False)
    happiness: int


class BanterTimingSettingsRecord(_KeyedRecord):
    """Effective BANTTIMG.2DA controls for party-member banter."""

    source_resource: str = Field(min_length=1)
    frequency: int = Field(ge=0, le=0xFFFF_FFFF)
    probability: int = Field(ge=0, le=0xFFFF_FFFF)
    replay_delay: int = Field(ge=0, le=0xFFFF_FFFF)
    special_probability: int = Field(ge=0, le=0xFFFF_FFFF)


class EngineStringRecord(_KeyedRecord):
    """One named engine string with resolved TLK text."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    strref: int | None = Field(default=None, ge=0, le=0xFFFF_FFFF)
    text: str | None
    search_text: str


class MonthDefinitionRecord(_KeyedRecord):
    """One MONTHS.2DA calendar segment."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    month_id: int = Field(ge=0, le=0xFFFF_FFFF)
    days: int = Field(gt=0)
    name_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    name: str | None
    search_text: str


class CampaignCalendarRecord(_KeyedRecord):
    """One campaign year resource with resolved date formats."""

    source_resource: str = Field(min_length=1)
    start_time: int = Field(ge=0, le=0xFFFF_FFFF)
    start_year: int = Field(ge=0, le=0xFFFF_FFFF)
    normal_format_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    normal_format: str | None
    special_format_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    special_format: str | None
    search_text: str


class RaceTextRecord(_KeyedRecord):
    """One normalized RACETEXT-compatible row."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    row_name: str = Field(min_length=1)
    race_id: int = Field(ge=0)
    name_strref: int | None = Field(default=None, ge=0)
    name: str | None = None
    description_strref: int | None = Field(default=None, ge=0)
    description: str | None = None
    uppercase_name_strref: int | None = Field(default=None, ge=0)
    uppercase_name: str | None = None
    biography_strref: int | None = Field(default=None, ge=0)
    biography: str | None = None
    search_text: str


class ClassTextRecord(_KeyedRecord):
    """One normalized CLASTEXT-compatible row."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    row_name: str = Field(min_length=1)
    class_id: int = Field(ge=0)
    class_text_kit_id: int = Field(ge=0)
    lower_name_strref: int | None = Field(default=None, ge=0)
    lower_name: str | None = None
    description_strref: int | None = Field(default=None, ge=0)
    description: str | None = None
    mixed_name_strref: int | None = Field(default=None, ge=0)
    mixed_name: str | None = None
    biography_strref: int | None = Field(default=None, ge=0)
    biography: str | None = None
    fallen: bool
    brief_description_strref: int | None = Field(default=None, ge=0)
    brief_description: str | None = None
    fallen_notice_strref: int | None = Field(default=None, ge=0)
    fallen_notice: str | None = None
    search_text: str


class KitDefinitionRecord(_KeyedRecord):
    """One normalized KITLIST.2DA row."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    row_id: int = Field(ge=0)
    row_name: str = Field(min_length=1)
    lower_name_strref: int | None = Field(default=None, ge=0)
    lower_name: str | None = None
    mixed_name_strref: int | None = Field(default=None, ge=0)
    mixed_name: str | None = None
    help_strref: int | None = Field(default=None, ge=0)
    help_text: str | None = None
    abilities: str | None = None
    proficiency: int | None = Field(default=None, ge=0)
    unusable: int | None = Field(default=None, ge=0)
    class_id: int | None = Field(default=None, ge=0)
    kit_ids_value: int | None = Field(default=None, ge=0)
    class_text_kit_id: int | None = Field(default=None, ge=0)
    search_text: str


TABLE_MODELS: dict[str, type[LanceModel]] = {
    _CHARACTERS: CharacterRecord,
    _CHARACTER_SOUNDS: CharacterSoundRecord,
    _CHARACTER_DIALOGUES: CharacterAttributionRecord,
    _VOICE_RESOURCES: VoiceResourceRecord,
    _DIALOGUES: DialogueRecord,
    _DIALOGUE_LINES: DialogueLineRecord,
    _DIALOGUE_TRANSITIONS: DialogueTransitionRecord,
    _EXTRACTION_RUNS: ExtractionRunRecord,
    _IDENTIFIER_DEFINITIONS: IdentifierDefinitionRecord,
    _CAMPAIGNS: CampaignDefinitionRecord,
    _CAMPAIGN_RESOURCE_BINDINGS: CampaignResourceBindingRecord,
    _CHARACTER_RESOURCE_LINKS: CharacterResourceLinkRecord,
    _INTERACTION_RULES: InteractionRuleRecord,
    _SOUNDSET_LINES: SoundsetLineRecord,
    _SOUND_SLOT_SUFFIXES: SoundSlotSuffixRecord,
    _SOUND_SLOT_GROUPS: SoundSlotGroupRecord,
    _FAVORED_ENEMIES: FavoredEnemyRecord,
    _HAPPINESS_RULES: HappinessRuleRecord,
    _BANTER_TIMING_SETTINGS: BanterTimingSettingsRecord,
    _ENGINE_STRINGS: EngineStringRecord,
    _MONTHS: MonthDefinitionRecord,
    _CAMPAIGN_CALENDARS: CampaignCalendarRecord,
    _RACE_TEXTS: RaceTextRecord,
    _CLASS_TEXTS: ClassTextRecord,
    _KITS: KitDefinitionRecord,
}


class PipelineDatabase:
    """Single-writer LanceDB repository for the extraction pipeline."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        is_new = not self.path.exists()
        assert is_new or self.path.is_dir(), f"LanceDB path is not a directory: {self.path}"
        self.path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(self.path, read_consistency_interval=timedelta(0))
        existing = frozenset(self._db.list_tables(limit=None).tables)
        assert (is_new and not existing) or existing == TABLE_NAMES, (
            f"LanceDB tables are {sorted(existing)}; expected {sorted(TABLE_NAMES)}"
        )
        for name, model in TABLE_MODELS.items():
            self._ensure_table(name, model)

    def start_run(
        self,
        game_root: Path,
        iecli_version: str,
        *,
        run_kind: RunKind = RunKind.CHARACTERS,
        character_input_run_id: str | None = None,
        dialogue_input_run_id: str | None = None,
        metadata_input_run_id: str | None = None,
    ) -> str:
        """Create a durable extraction-run record."""
        run_id = uuid4().hex
        assert not self._find_runs(run_id), f"Duplicate extraction run id: {run_id}"
        self._table(_EXTRACTION_RUNS).add(
            [
                ExtractionRunRecord(
                    id=run_id,
                    run_kind=run_kind,
                    started_at=utc_now().isoformat(),
                    completed_at=None,
                    game_root=str(game_root.expanduser().resolve()),
                    iecli_version=iecli_version,
                    character_input_run_id=character_input_run_id,
                    dialogue_input_run_id=dialogue_input_run_id,
                    metadata_input_run_id=metadata_input_run_id,
                    status=RunStatus.RUNNING,
                    resources_discovered=0,
                    details_attempted=0,
                    details_extracted=0,
                    failures=0,
                    error=None,
                )
            ]
        )
        return run_id

    def replace_metadata(self, run_id: str, extraction: MetadataExtraction) -> None:
        """Exactly replace every normalized IDS/2DA metadata collection."""
        run = self._run(run_id, expected_kind=RunKind.METADATA)
        replacements: tuple[
            tuple[str, type[_KeyedRecord], Sequence[_KeyedRecord]],
            ...,
        ] = (
            (
                _IDENTIFIER_DEFINITIONS,
                IdentifierDefinitionRecord,
                _metadata_records(IdentifierDefinitionRecord, extraction.identifiers),
            ),
            (
                _CAMPAIGNS,
                CampaignDefinitionRecord,
                _metadata_records(CampaignDefinitionRecord, extraction.campaigns),
            ),
            (
                _CAMPAIGN_RESOURCE_BINDINGS,
                CampaignResourceBindingRecord,
                _metadata_records(
                    CampaignResourceBindingRecord,
                    extraction.campaign_resource_bindings,
                ),
            ),
            (
                _CHARACTER_RESOURCE_LINKS,
                CharacterResourceLinkRecord,
                _metadata_records(
                    CharacterResourceLinkRecord,
                    extraction.character_resource_links,
                ),
            ),
            (
                _INTERACTION_RULES,
                InteractionRuleRecord,
                _metadata_records(InteractionRuleRecord, extraction.interaction_rules),
            ),
            (
                _SOUNDSET_LINES,
                SoundsetLineRecord,
                _metadata_records(SoundsetLineRecord, extraction.soundset_lines),
            ),
            (
                _SOUND_SLOT_SUFFIXES,
                SoundSlotSuffixRecord,
                _metadata_records(SoundSlotSuffixRecord, extraction.sound_slot_suffixes),
            ),
            (
                _SOUND_SLOT_GROUPS,
                SoundSlotGroupRecord,
                _metadata_records(SoundSlotGroupRecord, extraction.sound_slot_groups),
            ),
            (
                _FAVORED_ENEMIES,
                FavoredEnemyRecord,
                _metadata_records(FavoredEnemyRecord, extraction.favored_enemies),
            ),
            (
                _HAPPINESS_RULES,
                HappinessRuleRecord,
                _metadata_records(HappinessRuleRecord, extraction.happiness_rules),
            ),
            (
                _BANTER_TIMING_SETTINGS,
                BanterTimingSettingsRecord,
                _metadata_records(BanterTimingSettingsRecord, (extraction.banter_timing,)),
            ),
            (
                _ENGINE_STRINGS,
                EngineStringRecord,
                _metadata_records(EngineStringRecord, extraction.engine_strings),
            ),
            (
                _MONTHS,
                MonthDefinitionRecord,
                _metadata_records(MonthDefinitionRecord, extraction.months),
            ),
            (
                _CAMPAIGN_CALENDARS,
                CampaignCalendarRecord,
                _metadata_records(CampaignCalendarRecord, extraction.campaign_calendars),
            ),
            (
                _RACE_TEXTS,
                RaceTextRecord,
                _metadata_records(RaceTextRecord, extraction.race_text_rows),
            ),
            (
                _CLASS_TEXTS,
                ClassTextRecord,
                _metadata_records(ClassTextRecord, extraction.class_text_rows),
            ),
            (
                _KITS,
                KitDefinitionRecord,
                _metadata_records(KitDefinitionRecord, extraction.kits),
            ),
        )
        for name, _, records in replacements:
            self._assert_unique_names(
                [record.key for record in records],
                kind=f"{name} replacement",
            )

        updated_run = ExtractionRunRecord.model_validate(
            run.model_dump() | {"resources_discovered": extraction.source_resource_count}
        )
        for name, model, records in replacements:
            self._replace(name, "key", model, records)
        self._merge(_EXTRACTION_RUNS, "id", [updated_run])

    def identifier_definitions(self) -> list[IdentifierDefinition]:
        """Return all persisted effective IDS definitions in source order."""
        records = self._records(_IDENTIFIER_DEFINITIONS, IdentifierDefinitionRecord)
        return [
            IdentifierDefinition.model_validate(
                record.model_dump(include=set(IdentifierDefinition.model_fields))
            )
            for record in sorted(records, key=lambda row: (row.source_resource, row.ordinal))
        ]

    def campaigns(self) -> list[CampaignDefinition]:
        """Return persisted CAMPAIGN.2DA definitions in source order."""
        records = self._records(_CAMPAIGNS, CampaignDefinitionRecord)
        return [
            CampaignDefinition.model_validate(
                record.model_dump(include=set(CampaignDefinition.model_fields))
            )
            for record in sorted(records, key=lambda row: (row.source_resource, row.ordinal))
        ]

    def campaign_resource_bindings(self) -> list[CampaignResourceBinding]:
        """Return persisted campaign-selected resource relationships."""
        records = self._records(_CAMPAIGN_RESOURCE_BINDINGS, CampaignResourceBindingRecord)
        return [
            CampaignResourceBinding.model_validate(
                record.model_dump(include=set(CampaignResourceBinding.model_fields))
            )
            for record in sorted(records, key=lambda row: (row.campaign_id, row.resource_kind))
        ]

    def race_text_rows(self) -> list[RaceTextRow]:
        """Return persisted RACETEXT-compatible rows."""
        records = self._records(_RACE_TEXTS, RaceTextRecord)
        return [
            RaceTextRow.model_validate(record.model_dump(include=set(RaceTextRow.model_fields)))
            for record in sorted(records, key=lambda row: (row.source_resource, row.ordinal))
        ]

    def class_text_rows(self) -> list[ClassTextRow]:
        """Return persisted CLASTEXT-compatible rows."""
        records = self._records(_CLASS_TEXTS, ClassTextRecord)
        return [
            ClassTextRow.model_validate(record.model_dump(include=set(ClassTextRow.model_fields)))
            for record in sorted(records, key=lambda row: (row.source_resource, row.ordinal))
        ]

    def kits(self) -> list[KitDefinition]:
        """Return persisted KITLIST.2DA definitions."""
        records = self._records(_KITS, KitDefinitionRecord)
        return [
            KitDefinition.model_validate(record.model_dump(include=set(KitDefinition.model_fields)))
            for record in sorted(records, key=lambda row: (row.source_resource, row.ordinal))
        ]

    def replace_inventory(self, run_id: str, resources: Sequence[CreResource]) -> None:
        """Replace the complete CRE inventory, preserving unchanged extracted details."""
        run = self._run(run_id, expected_kind=RunKind.CHARACTERS)
        self._assert_unique_names(
            [resource.resource_name for resource in resources], kind="CRE inventory"
        )
        timestamp = utc_now().isoformat()
        existing = {
            record.resource_name.casefold(): record
            for record in self._records(_CHARACTERS, CharacterRecord)
        }
        replacement: list[CharacterRecord] = []
        retained_keys: set[str] = set()
        for resource in resources:
            key = resource.resource_name.casefold()
            if key in existing and _same_identity(existing[key], resource):
                replacement.append(_retained_character(existing[key], resource))
                retained_keys.add(key)
            else:
                replacement.append(_pending_character(resource, run_id, timestamp))

        discarded_names = sorted(
            character.resource_name
            for key, character in existing.items()
            if key not in retained_keys
        )
        updated_run = ExtractionRunRecord.model_validate(
            run.model_dump() | {"resources_discovered": len(resources)}
        )
        self._replace(_CHARACTERS, "resource_name", CharacterRecord, replacement)
        if discarded_names:
            self._table(_CHARACTER_SOUNDS).delete(
                col("character_resource_name").isin(discarded_names)
            )
        self._merge(_EXTRACTION_RUNS, "id", [updated_run])

    def detail_targets(self, *, refresh: bool) -> set[str]:
        """Return CRE resources that need detail extraction."""
        characters = self._records(_CHARACTERS, CharacterRecord)
        return {
            character.resource_name
            for character in characters
            if refresh or character.extraction.status is not DetailStatus.COMPLETE
        }

    def apply_detail_batch(
        self,
        run_id: str,
        extractions: Sequence[CharacterExtraction],
        failures: Iterable[tuple[str, str]],
    ) -> None:
        """Persist one validated batch of successful and failed CRE details."""
        self._run(run_id, expected_kind=RunKind.CHARACTERS)
        failures = list(failures)
        success_names = [extraction.resource_name for extraction in extractions]
        failure_names = [resource_name for resource_name, _ in failures]
        self._assert_batch_names(success_names, failure_names, kind="CRE")
        characters = {
            record.resource_name.casefold(): record
            for record in self._records(_CHARACTERS, CharacterRecord)
        }
        requested = success_names + failure_names
        missing = [name for name in requested if name.casefold() not in characters]
        assert not missing, f"CRE batch contains resources outside the inventory: {missing}"

        timestamp = utc_now().isoformat()
        updates = [
            _completed_character(
                characters[extraction.resource_name.casefold()],
                extraction,
                run_id,
                timestamp,
            )
            for extraction in extractions
        ]
        updates.extend(
            _failed_character(characters[resource_name.casefold()], error, run_id, timestamp)
            for resource_name, error in failures
        )
        sound_records = [
            _character_sound_record(
                run_id,
                characters[extraction.resource_name.casefold()],
                extraction.detail,
                sound,
            )
            for extraction in extractions
            for sound in extraction.sounds
        ]
        self._assert_unique_names(
            [sound.id for sound in sound_records],
            kind="CRE sound batch",
        )
        stored_names = [characters[name.casefold()].resource_name for name in requested]
        if requested:
            self._merge(
                _CHARACTERS,
                "resource_name",
                [
                    _pending_character_refresh(characters[name.casefold()], run_id, timestamp)
                    for name in requested
                ],
            )
        if sound_records:
            self._upsert(_CHARACTER_SOUNDS, "id", sound_records)
        if requested:
            stale_sounds = col("character_resource_name").isin(stored_names)
            if sound_records:
                stale_sounds &= ~col("id").isin([sound.id for sound in sound_records])
            self._table(_CHARACTER_SOUNDS).delete(stale_sounds)
        self._merge(_CHARACTERS, "resource_name", updates)

    def replace_dialogue_inventory(
        self,
        run_id: str,
        resources: Sequence[DlgResource],
    ) -> None:
        """Replace the complete DLG inventory and discard lines for changed identities."""
        run = self._run(run_id, expected_kind=RunKind.DIALOGUES)
        self._assert_unique_names(
            [resource.resource_name for resource in resources], kind="DLG inventory"
        )
        timestamp = utc_now().isoformat()
        existing = {
            record.resource_name.casefold(): record
            for record in self._records(_DIALOGUES, DialogueRecord)
        }
        replacement: list[DialogueRecord] = []
        retained_keys: set[str] = set()
        for resource in resources:
            key = resource.resource_name.casefold()
            if key in existing and _same_identity(existing[key], resource):
                replacement.append(_retained_dialogue(existing[key], resource))
                retained_keys.add(key)
            else:
                replacement.append(_pending_dialogue(resource, run_id, timestamp))

        discarded_names = sorted(
            dialogue.resource_name for key, dialogue in existing.items() if key not in retained_keys
        )
        updated_run = ExtractionRunRecord.model_validate(
            run.model_dump() | {"resources_discovered": len(resources)}
        )
        self._replace(_DIALOGUES, "resource_name", DialogueRecord, replacement)
        if discarded_names:
            self._table(_DIALOGUE_LINES).delete(col("dialogue_resource_name").isin(discarded_names))
            self._table(_DIALOGUE_TRANSITIONS).delete(
                col("dialogue_resource_name").isin(discarded_names)
            )
        self._merge(_EXTRACTION_RUNS, "id", [updated_run])

    def dialogue_targets(self, *, refresh: bool) -> list[str]:
        """Return DLG resources that need metric and line extraction."""
        dialogues = self._records(_DIALOGUES, DialogueRecord)
        return sorted(
            (
                dialogue.resource_name
                for dialogue in dialogues
                if refresh or dialogue.extraction.status is not DetailStatus.COMPLETE
            ),
            key=str.casefold,
        )

    def apply_dialogue_batch(
        self,
        run_id: str,
        details: Sequence[DialogueExtraction],
        failures: Iterable[tuple[str, str]],
    ) -> None:
        """Persist one validated batch of DLG metrics, lines, and failures."""
        self._run(run_id, expected_kind=RunKind.DIALOGUES)
        failures = list(failures)
        success_names = [extraction.resource_name for extraction in details]
        failure_names = [resource_name for resource_name, _ in failures]
        self._assert_batch_names(success_names, failure_names, kind="DLG")
        dialogues = {
            record.resource_name.casefold(): record
            for record in self._records(_DIALOGUES, DialogueRecord)
        }
        requested = success_names + failure_names
        missing = [name for name in requested if name.casefold() not in dialogues]
        assert not missing, f"DLG batch contains resources outside the inventory: {missing}"

        timestamp = utc_now().isoformat()
        dialogue_updates: list[DialogueRecord] = []
        line_records: list[DialogueLineRecord] = []
        transition_records: list[DialogueTransitionRecord] = []
        for extraction in details:
            dialogue = dialogues[extraction.resource_name.casefold()]
            dialogue_updates.append(_completed_dialogue(dialogue, extraction, run_id, timestamp))
            line_records.extend(
                _dialogue_line_record(run_id, dialogue, line) for line in extraction.lines
            )
            transition_records.extend(
                _dialogue_transition_record(run_id, dialogue, edge) for edge in extraction.edges
            )
        dialogue_updates.extend(
            _failed_dialogue(dialogues[resource_name.casefold()], error, run_id, timestamp)
            for resource_name, error in failures
        )
        self._assert_unique_names([line.id for line in line_records], kind="DLG line batch")
        self._assert_unique_names(
            [transition.id for transition in transition_records],
            kind="DLG transition batch",
        )

        stored_names = [dialogues[name.casefold()].resource_name for name in requested]
        if requested:
            self._merge(
                _DIALOGUES,
                "resource_name",
                [
                    _pending_dialogue_refresh(dialogues[name.casefold()], run_id, timestamp)
                    for name in requested
                ],
            )
        if line_records:
            self._upsert(_DIALOGUE_LINES, "id", line_records)
        if transition_records:
            self._upsert(_DIALOGUE_TRANSITIONS, "id", transition_records)
        if requested:
            stale_lines = col("dialogue_resource_name").isin(stored_names)
            if line_records:
                stale_lines &= ~col("id").isin([line.id for line in line_records])
            self._table(_DIALOGUE_LINES).delete(stale_lines)
            stale_transitions = col("dialogue_resource_name").isin(stored_names)
            if transition_records:
                stale_transitions &= ~col("id").isin(
                    [transition.id for transition in transition_records]
                )
            self._table(_DIALOGUE_TRANSITIONS).delete(stale_transitions)
        self._merge(_DIALOGUES, "resource_name", dialogue_updates)

    def rebuild_attributions(self) -> AttributionSummary:
        """Publish one complete, run-scoped character attribution generation."""
        input_runs = {
            kind: self._attribution_input_run(kind)
            for kind in (RunKind.CHARACTERS, RunKind.DIALOGUES, RunKind.METADATA)
        }
        game_roots = {Path(run.game_root).expanduser().resolve() for run in input_runs.values()}
        assert len(game_roots) == 1, "attribution inputs must come from the same game install"
        context = max(input_runs.values(), key=lambda run: (run.started_at, run.id))
        run_id = self.start_run(
            Path(context.game_root),
            context.iecli_version,
            run_kind=RunKind.ATTRIBUTION,
            character_input_run_id=input_runs[RunKind.CHARACTERS].id,
            dialogue_input_run_id=input_runs[RunKind.DIALOGUES].id,
            metadata_input_run_id=input_runs[RunKind.METADATA].id,
        )

        characters_total = 0
        try:
            characters = self._records(_CHARACTERS, CharacterRecord)
            characters_total = len(characters)
            dialogues = self._records(_DIALOGUES, DialogueRecord)
            links = self._records(_CHARACTER_RESOURCE_LINKS, CharacterResourceLinkRecord)
            identifiers = self._records(_IDENTIFIER_DEFINITIONS, IdentifierDefinitionRecord)
            dialogues_by_resref = {dialogue.resref.casefold(): dialogue for dialogue in dialogues}
            links_by_death_variable: dict[str, list[CharacterResourceLinkRecord]] = {}
            for link in links:
                if link.target_type is ResourceTargetType.DIALOGUE:
                    links_by_death_variable.setdefault(link.death_variable.casefold(), []).append(
                        link
                    )

            attribution_records: list[CharacterAttributionRecord] = []
            character_counts: Counter[str] = Counter()
            for character in characters:
                declared = _character_dialogue_resrefs(character, links_by_death_variable)
                resolved = tuple(
                    dialogues_by_resref[resref.casefold()]
                    for resref in declared
                    if resref.casefold() in dialogues_by_resref
                )
                record = _character_attribution_record(run_id, character, declared, resolved)
                attribution_records.append(record)
                character_counts.update(dialogue.resource_name.casefold() for dialogue in resolved)

            voice_ids = _voice_ids(characters)
            voice_records = [
                _voice_resource_record(run_id, resource)
                for resource in _voice_resources(characters, identifiers, voice_ids)
            ]
            statuses = Counter(record.status for record in attribution_records)
            attributed_dialogues = [
                dialogue
                for dialogue in dialogues
                if character_counts[dialogue.resource_name.casefold()] > 0
            ]
            unattributed_dialogues = [
                dialogue
                for dialogue in dialogues
                if character_counts[dialogue.resource_name.casefold()] == 0
            ]
            attributed_lines = sum(
                _dialogue_line_count(dialogue) for dialogue in attributed_dialogues
            )
            unattributed_lines = sum(
                _dialogue_line_count(dialogue) for dialogue in unattributed_dialogues
            )
            summary = AttributionSummary(
                run_id=run_id,
                characters_total=len(attribution_records),
                characters_matched=statuses[AttributionStatus.MATCHED],
                characters_partially_matched=statuses[AttributionStatus.PARTIAL_MATCH],
                characters_missing_dialogue=statuses[AttributionStatus.MISSING_DIALOGUE],
                characters_dialogue_failed=sum(
                    record.dialogue_status is DetailStatus.FAILED for record in attribution_records
                ),
                characters_without_dialogue=statuses[AttributionStatus.NO_DIALOGUE],
                characters_unavailable=statuses[AttributionStatus.CHARACTER_UNAVAILABLE],
                dialogues_total=len(dialogues),
                dialogues_attributed=len(attributed_dialogues),
                dialogues_unattributed=len(unattributed_dialogues),
                attributed_dialogue_lines=attributed_lines,
                unattributed_dialogue_lines=unattributed_lines,
            )
            self._upsert(_CHARACTER_DIALOGUES, "key", attribution_records)
            self._upsert(_VOICE_RESOURCES, "key", voice_records)
            self.finish_run(
                run_id,
                status=RunStatus.COMPLETE,
                discovered=characters_total,
                attempted=characters_total,
                extracted=len(attribution_records),
                failures=0,
            )
            return summary
        except BaseException as error:
            try:
                self.finish_run(
                    run_id,
                    status=RunStatus.FAILED,
                    discovered=characters_total,
                    attempted=characters_total,
                    extracted=0,
                    failures=1,
                    error=str(error),
                )
            except BaseException as finalization_error:
                error.add_note(
                    f"Failed to finalize attribution run {run_id}: {finalization_error!r}"
                )
            raise

    def finish_run(
        self,
        run_id: str,
        *,
        status: TerminalRunStatus,
        discovered: int | None = None,
        attempted: int,
        extracted: int,
        failures: int,
        error: str | None = None,
    ) -> None:
        """Finalize extraction counters and rebuild indexes for the completed stage."""
        run = self._run(run_id)
        updated = ExtractionRunRecord.model_validate(
            run.model_dump()
            | {
                "completed_at": utc_now().isoformat(),
                "status": status,
                "resources_discovered": (
                    run.resources_discovered if discovered is None else discovered
                ),
                "details_attempted": attempted,
                "details_extracted": extracted,
                "failures": failures,
                "error": error[:2000] if error else None,
            }
        )
        if status is not RunStatus.FAILED:
            if run.run_kind is RunKind.CHARACTERS:
                self._optimize(_CHARACTERS, self._table(_CHARACTERS))
                self._optimize(_CHARACTER_SOUNDS, self._table(_CHARACTER_SOUNDS))
            elif run.run_kind is RunKind.DIALOGUES:
                self._optimize(_DIALOGUES, self._table(_DIALOGUES))
                self._optimize(_DIALOGUE_LINES, self._table(_DIALOGUE_LINES))
                self._optimize(
                    _DIALOGUE_TRANSITIONS,
                    self._table(_DIALOGUE_TRANSITIONS),
                )
            elif run.run_kind is RunKind.METADATA:
                for name in _METADATA_TABLES:
                    self._optimize(name, self._table(name))
            else:
                assert run.run_kind is RunKind.ATTRIBUTION
                self._optimize(
                    _CHARACTER_DIALOGUES,
                    self._table(_CHARACTER_DIALOGUES),
                )
                self._optimize(_VOICE_RESOURCES, self._table(_VOICE_RESOURCES))
        self._merge(_EXTRACTION_RUNS, "id", [updated])

    def stats(self) -> DatabaseStats:
        """Return validated counts for the current CRE inventory."""
        characters = self._records(_CHARACTERS, CharacterRecord)
        statuses = Counter(character.extraction.status for character in characters)
        return DatabaseStats(
            total=len(characters),
            complete=statuses[DetailStatus.COMPLETE],
            failed=statuses[DetailStatus.FAILED],
            pending=statuses[DetailStatus.PENDING],
            with_dialog=sum(
                character.detail is not None and character.detail.dialog_resref is not None
                for character in characters
            ),
        )

    def _ensure_table[Record: LanceModel](self, name: str, model: type[Record]) -> None:
        names = set(self._db.list_tables(limit=None).tables)
        if name not in names:
            table = self._db.create_table(name, schema=model)
            self._create_indexes(name, table)
        table = self._table(name)
        self._assert_schema(name, table, model)
        self._assert_indexes(name, table)

    def _replace[Record: LanceModel](
        self,
        name: str,
        key: str,
        model: type[Record],
        records: Sequence[Record],
    ) -> None:
        rows = list(records)
        data = rows or pa.Table.from_pylist([], schema=model.to_arrow_schema())
        table = self._table(name)
        result = (
            table.merge_insert(key)
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .when_not_matched_by_source_delete()
            .execute(data)
        )
        assert result.num_rows == len(rows), (
            f"{name} replaced {result.num_rows} rows; expected {len(rows)}"
        )
        row_count = table.count_rows()
        assert row_count == len(rows), f"{name} contains {row_count} rows; expected {len(rows)}"
        self._assert_schema(name, table, model)
        self._assert_indexes(name, table)

    def _records[Record: LanceModel](
        self,
        table_name: str,
        model: type[Record],
    ) -> list[Record]:
        return self._table(table_name).search().limit(None).to_pydantic(model)

    def _find_runs(self, run_id: str) -> list[ExtractionRunRecord]:
        return (
            self._table(_EXTRACTION_RUNS)
            .search()
            .where(col("id") == run_id)
            .limit(2)
            .to_pydantic(ExtractionRunRecord)
        )

    def _run(
        self,
        run_id: str,
        *,
        expected_kind: RunKind | None = None,
    ) -> ExtractionRunRecord:
        matches = self._find_runs(run_id)
        assert matches, f"Unknown extraction run: {run_id}"
        assert len(matches) == 1, f"Duplicate extraction run id: {run_id}"
        run = matches[0]
        assert run.status is RunStatus.RUNNING, f"Extraction run {run_id} is already {run.status}"
        assert expected_kind is None or run.run_kind == expected_kind, (
            f"Extraction run {run_id} is {run.run_kind}; expected {expected_kind}"
        )
        return run

    def _latest_run(self, kind: RunKind) -> ExtractionRunRecord | None:
        matches = [
            run
            for run in self._records(_EXTRACTION_RUNS, ExtractionRunRecord)
            if run.run_kind is kind
        ]
        if not matches:
            return None
        return max(matches, key=lambda run: (run.started_at, run.id))

    def _attribution_input_run(self, kind: RunKind) -> ExtractionRunRecord:
        run = self._latest_run(kind)
        assert run is not None, f"attribution requires a {kind.value} run"
        assert run.status in (RunStatus.COMPLETE, RunStatus.COMPLETE_WITH_ERRORS), (
            f"attribution requires a terminal successful {kind.value} run"
        )
        return run

    def _merge[Record: LanceModel](
        self,
        table_name: str,
        key: str,
        records: Sequence[Record],
    ) -> None:
        if not records:
            return
        result = (
            self._table(table_name)
            .merge_insert(key)
            .when_matched_update_all()
            .execute(list(records))
        )
        assert result.num_updated_rows == len(records), (
            f"{table_name} updated {result.num_updated_rows} rows; expected {len(records)}"
        )

    def _upsert[Record: LanceModel](
        self,
        table_name: str,
        key: str,
        records: Sequence[Record],
    ) -> None:
        if not records:
            return
        result = (
            self._table(table_name)
            .merge_insert(key)
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(list(records))
        )
        changed = result.num_updated_rows + result.num_inserted_rows
        assert changed == len(records), (
            f"{table_name} upserted {changed} rows; expected {len(records)}"
        )

    def _table(self, name: str) -> Table:
        return self._db.open_table(name)

    @staticmethod
    def _assert_schema[Record: LanceModel](
        name: str,
        table: Table,
        model: type[Record],
    ) -> None:
        expected = model.to_arrow_schema()
        assert table.schema.equals(expected, check_metadata=True), (
            f"LanceDB table {name!r} has schema {table.schema}; expected {expected}"
        )

    @staticmethod
    def _create_indexes(name: str, table: Table) -> None:
        for index in TABLE_INDEXES[name]:
            table.create_index(index.column, config=index.config, name=index.name)

    @classmethod
    def _optimize(cls, name: str, table: Table) -> None:
        table.optimize()
        cls._assert_indexes(name, table)

    @staticmethod
    def _assert_indexes(name: str, table: Table) -> None:
        actual = {
            (index.name, index.index_type, tuple(index.columns)) for index in table.list_indices()
        }
        expected = {
            (index.name, type(index.config).__name__, (index.column,))
            for index in TABLE_INDEXES[name]
        }
        assert actual == expected, (
            f"LanceDB table {name!r} has indexes {sorted(actual)}; expected {sorted(expected)}"
        )

    @staticmethod
    def _assert_unique_names(names: Sequence[str], *, kind: str) -> None:
        folded = [name.casefold() for name in names]
        counts = Counter(folded)
        duplicates = sorted({name for name in folded if counts[name] > 1})
        assert not duplicates, f"{kind} contains duplicate keys: {duplicates}"

    @classmethod
    def _assert_batch_names(
        cls,
        success_names: Sequence[str],
        failure_names: Sequence[str],
        *,
        kind: str,
    ) -> None:
        cls._assert_unique_names(success_names, kind=f"{kind} successes")
        cls._assert_unique_names(failure_names, kind=f"{kind} failures")
        overlap = sorted(
            {name.casefold() for name in success_names}
            & {name.casefold() for name in failure_names}
        )
        assert not overlap, f"{kind} batch has both success and failure for: {overlap}"


def _pending_character(
    resource: CreResource,
    run_id: str,
    timestamp: str,
) -> CharacterRecord:
    return CharacterRecord(
        resource_name=resource.resource_name,
        resref=resource.resref,
        source=ResourceSource.from_resource(resource),
        extraction=_extraction_state(run_id, DetailStatus.PENDING, timestamp),
        detail=None,
        serialized_size=None,
        search_text=resource.search_text,
    )


def _retained_character(
    character: CharacterRecord,
    resource: CreResource,
) -> CharacterRecord:
    return CharacterRecord(
        resource_name=resource.resource_name,
        resref=resource.resref,
        source=ResourceSource.from_resource(resource),
        extraction=character.extraction,
        detail=character.detail,
        serialized_size=character.serialized_size,
        search_text=_character_search_text(resource.search_text, character.detail),
    )


def _completed_character(
    character: CharacterRecord,
    extraction: CharacterExtraction,
    run_id: str,
    timestamp: str,
) -> CharacterRecord:
    detail = CharacterData.model_validate(extraction.detail, from_attributes=True)
    return CharacterRecord(
        resource_name=character.resource_name,
        resref=character.resref,
        source=character.source,
        extraction=_extraction_state(run_id, DetailStatus.COMPLETE, timestamp),
        detail=detail,
        serialized_size=extraction.serialized_size,
        search_text=_character_search_text(_resource_search_text(character), detail),
    )


def _failed_character(
    character: CharacterRecord,
    error: str,
    run_id: str,
    timestamp: str,
) -> CharacterRecord:
    return CharacterRecord(
        resource_name=character.resource_name,
        resref=character.resref,
        source=character.source,
        extraction=_extraction_state(run_id, DetailStatus.FAILED, timestamp, error[:2000]),
        detail=None,
        serialized_size=None,
        search_text=_resource_search_text(character),
    )


def _pending_character_refresh(
    character: CharacterRecord,
    run_id: str,
    timestamp: str,
) -> CharacterRecord:
    return CharacterRecord(
        resource_name=character.resource_name,
        resref=character.resref,
        source=character.source,
        extraction=_extraction_state(run_id, DetailStatus.PENDING, timestamp),
        detail=None,
        serialized_size=None,
        search_text=_resource_search_text(character),
    )


def _pending_dialogue(
    resource: DlgResource,
    run_id: str,
    timestamp: str,
) -> DialogueRecord:
    return DialogueRecord(
        resource_name=resource.resource_name,
        resref=resource.resref,
        source=ResourceSource.from_resource(resource),
        extraction=_extraction_state(run_id, DetailStatus.PENDING, timestamp),
        detail=None,
        serialized_size=None,
        search_text=resource.search_text,
    )


def _retained_dialogue(
    dialogue: DialogueRecord,
    resource: DlgResource,
) -> DialogueRecord:
    return DialogueRecord(
        resource_name=resource.resource_name,
        resref=resource.resref,
        source=ResourceSource.from_resource(resource),
        extraction=dialogue.extraction,
        detail=dialogue.detail,
        serialized_size=dialogue.serialized_size,
        search_text=resource.search_text,
    )


def _completed_dialogue(
    dialogue: DialogueRecord,
    extraction: DialogueExtraction,
    run_id: str,
    timestamp: str,
) -> DialogueRecord:
    return DialogueRecord(
        resource_name=dialogue.resource_name,
        resref=dialogue.resref,
        source=dialogue.source,
        extraction=_extraction_state(run_id, DetailStatus.COMPLETE, timestamp),
        detail=DialogueData.model_validate(extraction.detail, from_attributes=True),
        serialized_size=extraction.serialized_size,
        search_text=dialogue.search_text,
    )


def _failed_dialogue(
    dialogue: DialogueRecord,
    error: str,
    run_id: str,
    timestamp: str,
) -> DialogueRecord:
    return DialogueRecord(
        resource_name=dialogue.resource_name,
        resref=dialogue.resref,
        source=dialogue.source,
        extraction=_extraction_state(run_id, DetailStatus.FAILED, timestamp, error[:2000]),
        detail=None,
        serialized_size=None,
        search_text=dialogue.search_text,
    )


def _pending_dialogue_refresh(
    dialogue: DialogueRecord,
    run_id: str,
    timestamp: str,
) -> DialogueRecord:
    return DialogueRecord(
        resource_name=dialogue.resource_name,
        resref=dialogue.resref,
        source=dialogue.source,
        extraction=_extraction_state(run_id, DetailStatus.PENDING, timestamp),
        detail=None,
        serialized_size=None,
        search_text=dialogue.search_text,
    )


def _dialogue_line_record(
    run_id: str,
    dialogue: DialogueRecord,
    line: DialogueLine,
) -> DialogueLineRecord:
    canonical = line.model_copy(update={"dialogue_resource_name": dialogue.resource_name})
    return DialogueLineRecord(
        id=canonical.id,
        run_id=run_id,
        dialogue_resource_name=canonical.dialogue_resource_name,
        line_kind=canonical.line_kind,
        state_index=canonical.state_index,
        state_trigger_index=canonical.state_trigger_index,
        state_trigger_text=canonical.state_trigger_text,
        transition_index=canonical.transition_index,
        strref=canonical.strref,
        text=canonical.text,
        tokens=canonical.tokens,
        serialized_size=len(canonical.model_dump_json().encode("utf-8")),
        search_text=canonical.search_text,
    )


def _character_sound_record(
    run_id: str,
    character: CharacterRecord,
    detail: CharacterDetail,
    sound: CharacterSound,
) -> CharacterSoundRecord:
    return CharacterSoundRecord(
        id=CharacterSound.id_for(character.resource_name, sound.slot_id),
        run_id=run_id,
        character_resource_name=character.resource_name,
        slot_id=sound.slot_id,
        strref=sound.strref,
        text=sound.text,
        serialized_size=len(sound.model_dump_json().encode("utf-8")),
        search_text=compose_search_text(
            character.resource_name,
            character.resref,
            detail.display_name,
            str(sound.slot_id),
            str(sound.strref),
            sound.text,
        ),
    )


def _voice_resources(
    characters: Sequence[CharacterRecord],
    identifiers: Sequence[IdentifierDefinitionRecord],
    voice_ids: dict[str, str],
) -> list[VoiceResource]:
    members_by_voice: dict[str, list[CharacterRecord]] = {}
    for character in characters:
        if character.detail is not None:
            voice_id = voice_ids[character.resource_name.casefold()]
            members_by_voice.setdefault(voice_id, []).append(character)

    labels = {
        (definition.kind, definition.value): " / ".join(
            _prettify_symbol(symbol) for symbol in definition.symbols
        )
        for definition in identifiers
    }
    resources: list[VoiceResource] = []
    for voice_id, unsorted_members in sorted(members_by_voice.items()):
        members = sorted(unsorted_members, key=lambda member: member.resource_name.casefold())
        representative = _voice_representative(members)
        assert representative.detail is not None
        dialogue_resrefs: dict[str, str] = {}
        for member in members:
            assert member.detail is not None
            if member.detail.dialog_resref is not None:
                dialogue_resrefs.setdefault(
                    member.detail.dialog_resref.casefold(),
                    member.detail.dialog_resref,
                )
        resources.append(
            VoiceResource(
                id=VoiceId(voice_id),
                display_name=representative.detail.display_name,
                prompt=_voice_prompt(representative, labels),
                variant_resource_names=[member.resource_name for member in members],
                dialogue_resrefs=sorted(dialogue_resrefs.values(), key=str.casefold),
            )
        )
    return resources


def _voice_ids(characters: Sequence[CharacterRecord]) -> dict[str, str]:
    """Resolve false collisions where one script variable names several speakers."""
    groups: dict[VoiceId, list[CharacterRecord]] = {}
    for character in characters:
        detail = character.detail
        if detail is None:
            continue
        voice_id = proposed_voice_id(
            detail.death_variable,
            detail.dialog_resref,
            _character_name_strref(character),
            character.resref,
        )
        groups.setdefault(voice_id, []).append(character)

    resolved: dict[str, str] = {}
    for voice_id, members in groups.items():
        named_members: dict[str, list[CharacterRecord]] = {}
        unnamed_members: list[CharacterRecord] = []
        for character in members:
            if _character_name_strref(character) is None:
                unnamed_members.append(character)
            else:
                assert character.detail is not None
                named_members.setdefault(character.detail.display_name.casefold(), []).append(
                    character
                )

        if not str(voice_id).startswith("dv:") or len(named_members) <= 1:
            for character in members:
                resolved[character.resource_name.casefold()] = str(voice_id)
            continue

        for same_name_members in named_members.values():
            strrefs = Counter(
                name_strref
                for character in same_name_members
                if (name_strref := _character_name_strref(character)) is not None
            )
            canonical_strref = min(strrefs, key=lambda value: (-strrefs[value], value))
            for character in same_name_members:
                resolved[character.resource_name.casefold()] = f"{voice_id}:name:{canonical_strref}"
        for character in unnamed_members:
            resolved[character.resource_name.casefold()] = (
                f"{voice_id}:cre:{character.resref.casefold()}"
            )
    return resolved


def _character_name_strref(character: CharacterRecord) -> int | None:
    detail = character.detail
    if detail is None:
        return None
    if detail.short_name is not None:
        return detail.short_name_strref
    if detail.long_name is not None:
        return detail.long_name_strref
    return None


def _voice_representative(members: Sequence[CharacterRecord]) -> CharacterRecord:
    """Choose one real CRE for both the canonical name and prompt metadata."""
    assert all(character.detail is not None for character in members)
    metadata_counts = Counter(_voice_metadata(character) for character in members)
    return min(
        members,
        key=lambda character: (
            character.detail is None
            or (character.detail.short_name is None and character.detail.long_name is None),
            -metadata_counts[_voice_metadata(character)],
            character.resource_name.casefold(),
            character.resource_name,
        ),
    )


def _voice_metadata(character: CharacterRecord) -> tuple[int, int, int, int | None, int]:
    detail = character.detail
    assert detail is not None
    return (
        detail.gender_id,
        detail.race_id,
        detail.class_id,
        detail.kit_ids_value,
        detail.alignment_id,
    )


def _voice_prompt(
    character: CharacterRecord,
    labels: dict[tuple[IdentifierKind, int], str],
) -> str:
    detail = character.detail
    assert detail is not None
    lines = [
        f"Name: {detail.display_name}",
        f"Gender: {labels.get((IdentifierKind.GENDER, detail.gender_id), str(detail.gender_id))}",
        f"Race: {labels.get((IdentifierKind.RACE, detail.race_id), str(detail.race_id))}",
        f"Class: {labels.get((IdentifierKind.CLASS, detail.class_id), str(detail.class_id))}",
    ]
    kit_id = detail.kit_ids_value
    if kit_id not in (None, 0, 0x4000):
        lines.append(f"Kit: {labels.get((IdentifierKind.KIT, kit_id), str(kit_id))}")
    lines.append(
        f"Alignment: {labels.get((IdentifierKind.ALIGNMENT, detail.alignment_id), str(detail.alignment_id))}"
    )
    return "\n".join(lines)


def _prettify_symbol(symbol: str) -> str:
    return " ".join(part.capitalize() for part in symbol.replace("-", "_").split("_") if part)


def _voice_resource_record(
    run_id: str,
    resource: VoiceResource,
) -> VoiceResourceRecord:
    voice_id = str(resource.id)
    return VoiceResourceRecord(
        key=VoiceResourceRecord.key_for(run_id, voice_id),
        run_id=run_id,
        voice_id=voice_id,
        display_name=resource.display_name,
        prompt=resource.prompt,
        variant_resource_names=resource.variant_resource_names,
        dialogue_resrefs=resource.dialogue_resrefs,
        search_text=resource.search_text,
    )


def _dialogue_transition_record(
    run_id: str,
    dialogue: DialogueRecord,
    edge: DialogueTransitionEdge,
) -> DialogueTransitionRecord:
    canonical = edge.model_copy(update={"dialogue_resource_name": dialogue.resource_name})
    return DialogueTransitionRecord(
        id=canonical.id,
        run_id=run_id,
        dialogue_resource_name=canonical.dialogue_resource_name,
        state_index=canonical.state_index,
        transition_index=canonical.transition_index,
        flags_raw=canonical.flags_raw,
        flags_decoded=canonical.flags_decoded,
        trigger_index=canonical.trigger_index,
        trigger_text=canonical.trigger_text,
        action_index=canonical.action_index,
        action_text=canonical.action_text,
        next_dialog=canonical.next_dialog,
        next_state_index=canonical.next_state_index,
        terminates_dialog=canonical.terminates_dialog,
        serialized_size=len(canonical.model_dump_json().encode("utf-8")),
        search_text=canonical.search_text,
    )


def _character_attribution_record(
    run_id: str,
    character: CharacterRecord,
    declared_resrefs: tuple[str, ...],
    dialogues: tuple[DialogueRecord, ...],
) -> CharacterAttributionRecord:
    resolved_resrefs = {dialogue.resref.casefold() for dialogue in dialogues}
    missing_resrefs = [
        resref for resref in declared_resrefs if resref.casefold() not in resolved_resrefs
    ]
    status: AttributionStatus
    if character.detail is None:
        status = AttributionStatus.CHARACTER_UNAVAILABLE
    elif not declared_resrefs:
        status = AttributionStatus.NO_DIALOGUE
    elif len(missing_resrefs) == len(declared_resrefs):
        status = AttributionStatus.MISSING_DIALOGUE
    elif missing_resrefs:
        status = AttributionStatus.PARTIAL_MATCH
    else:
        status = AttributionStatus.MATCHED

    dialogue_status: DetailStatus | None = None
    if dialogues:
        if any(dialogue.extraction.status is DetailStatus.FAILED for dialogue in dialogues):
            dialogue_status = DetailStatus.FAILED
        elif any(dialogue.extraction.status is DetailStatus.PENDING for dialogue in dialogues):
            dialogue_status = DetailStatus.PENDING
        else:
            dialogue_status = DetailStatus.COMPLETE

    return CharacterAttributionRecord(
        key=CharacterAttributionRecord.key_for(run_id, character.resource_name),
        run_id=run_id,
        character_resource_name=character.resource_name,
        status=status,
        dialogue_status=dialogue_status,
        declared_dialogue_resrefs=list(declared_resrefs),
        missing_dialogue_resrefs=missing_resrefs,
        resolved_dialogue_resource_names=[dialogue.resource_name for dialogue in dialogues],
    )


def _character_dialogue_resrefs(
    character: CharacterRecord,
    links_by_death_variable: dict[str, list[CharacterResourceLinkRecord]],
) -> tuple[str, ...]:
    resrefs: dict[str, str] = {}
    detail = character.detail
    if detail is None:
        return ()
    if detail.dialog_resref is not None:
        resrefs[detail.dialog_resref.casefold()] = detail.dialog_resref
    if detail.death_variable is not None:
        for link in links_by_death_variable.get(detail.death_variable.casefold(), []):
            resrefs.setdefault(link.target_resref.casefold(), link.target_resref)
    return tuple(sorted(resrefs.values(), key=lambda value: (value.casefold(), value)))


def _extraction_state(
    run_id: str,
    status: DetailStatus,
    timestamp: str,
    error: str | None = None,
) -> ExtractionState:
    return ExtractionState(
        run_id=run_id,
        status=status,
        error=error,
        updated_at=timestamp,
    )


def _resource_search_text(record: CharacterRecord | DialogueRecord) -> str:
    return compose_search_text(
        record.resource_name,
        record.resref,
        record.source.path,
    )


def _character_search_text(
    resource_search_text: str,
    detail: CharacterData | None,
) -> str:
    if detail is None:
        return resource_search_text
    return compose_search_text(
        resource_search_text,
        detail.display_name,
        detail.short_name,
        detail.long_name,
        detail.death_variable,
        detail.dialog_resref,
        detail.override_script,
        detail.class_script,
        detail.race_script,
        detail.general_script,
        detail.default_script,
    )


def _dialogue_line_count(dialogue: DialogueRecord) -> int:
    return 0 if dialogue.detail is None else dialogue.detail.dialogue_line_count


def _metadata_records[Record: _KeyedRecord](
    record_type: type[Record],
    rows: Iterable[BaseModel],
) -> list[Record]:
    return [record_type.model_validate(row, from_attributes=True) for row in rows]


def _same_identity(
    record: CharacterRecord | DialogueRecord,
    resource: CreResource | DlgResource,
) -> bool:
    return (
        record.resource_name == resource.resource_name
        and record.resref.casefold() == resource.resref.casefold()
        and record.source.kind == resource.source_kind
        and record.source.path == resource.source_path
    )
