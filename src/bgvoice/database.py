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
    CharacterResourceRole,
    CharacterSound,
    ClassTextRow,
    CreResource,
    DatabaseStats,
    DetailStatus,
    DialogueDetail,
    DialogueExtraction,
    DialogueLine,
    DialogueLineKind,
    DialogueTransitionEdge,
    DlgResource,
    HappinessAlignment,
    IdentifierDefinition,
    IdentifierKind,
    InteractionKind,
    KitDefinition,
    MetadataExtraction,
    RaceTextRow,
    ResourceTargetType,
    RunKind,
    RunStatus,
    SourceKind,
    TerminalRunStatus,
    compose_search_text,
    utc_now,
)

_CHARACTERS = "characters"
_CHARACTER_SOUNDS = "character_sounds"
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
        fields = [
            pa.field(field.name, pa.string(), field.nullable, field.metadata)
            if pa.types.is_dictionary(field.type)
            else field
            for field in schema
        ]
        return pa.schema(fields, metadata=schema.metadata)


class _KeyedRecord(_Record):
    """A persisted metadata row with a stable domain-owned key."""

    key: str = Field(min_length=1)


class CharacterRecord(_Record):
    """One effective CRE and its current extraction and attribution state."""

    resource_name: str = Field(min_length=1)
    resref: str = Field(min_length=1, max_length=8)
    source_kind: SourceKind = Field(strict=False)
    source_path: str = Field(min_length=1)

    display_name: str | None = None
    short_name: str | None = None
    short_name_strref: int | None = Field(default=None, ge=0)
    long_name: str | None = None
    long_name_strref: int | None = Field(default=None, ge=0)
    death_variable: str | None = None
    dialog_resref: str | None = None
    gender_id: int | None = Field(default=None, ge=0)
    race_id: int | None = Field(default=None, ge=0)
    class_id: int | None = Field(default=None, ge=0)
    alignment_id: int | None = Field(default=None, ge=0)
    enemy_ally_id: int | None = Field(default=None, ge=0)
    general_id: int | None = Field(default=None, ge=0)
    specific_id: int | None = Field(default=None, ge=0)
    animation_id: int | None = Field(default=None, ge=0)
    racial_enemy_id: int | None = Field(default=None, ge=0)
    kit_raw_bytes: list[int] | None = None
    cre_kit_value: int | None = Field(default=None, ge=0)
    kit_ids_value: int | None = Field(default=None, ge=0)
    first_class_level: int | None = Field(default=None, ge=0)
    second_class_level: int | None = Field(default=None, ge=0)
    third_class_level: int | None = Field(default=None, ge=0)
    strength: int | None = Field(default=None, ge=0, le=0xFF)
    strength_bonus: int | None = Field(default=None, ge=0, le=100)
    intelligence: int | None = Field(default=None, ge=0, le=0xFF)
    wisdom: int | None = Field(default=None, ge=0, le=0xFF)
    dexterity: int | None = Field(default=None, ge=0, le=0xFF)
    constitution: int | None = Field(default=None, ge=0, le=0xFF)
    charisma: int | None = Field(default=None, ge=0, le=0xFF)
    morale: int | None = Field(default=None, ge=0, le=0xFF)
    morale_break: int | None = Field(default=None, ge=0, le=0xFF)
    morale_recovery_time: int | None = Field(default=None, ge=0, le=0xFFFF)
    reputation: int | None = Field(default=None, ge=0, le=0xFF)
    override_script: str | None = None
    class_script: str | None = None
    race_script: str | None = None
    general_script: str | None = None
    default_script: str | None = None
    small_portrait: str | None = None
    large_portrait: str | None = None
    cre_version: str | None = None

    serialized_size: int | None = Field(default=None, ge=0)
    detail_status: DetailStatus = Field(strict=False)
    detail_error: str | None = None
    updated_at: str = Field(min_length=1)
    has_dialog: bool

    attribution_status: AttributionStatus | None = Field(default=None, strict=False)
    dialogue_status: DetailStatus | None = Field(default=None, strict=False)
    declared_dialogue_count: int | None = Field(default=None, ge=0)
    resolved_dialogue_count: int | None = Field(default=None, ge=0)
    dialogue_line_count: int | None = Field(default=None, ge=0)
    npc_line_count: int | None = Field(default=None, ge=0)
    player_line_count: int | None = Field(default=None, ge=0)
    journal_line_count: int | None = Field(default=None, ge=0)
    dialogue_state_count: int | None = Field(default=None, ge=0)
    dialogue_transition_count: int | None = Field(default=None, ge=0)
    dialogue_serialized_size: int | None = Field(default=None, ge=0)
    attribution_completed_at: str | None = None
    search_text: str

    @property
    def resource_search_text(self) -> str:
        """Return the stable inventory fields shared by every extraction state."""
        return compose_search_text(self.resource_name, self.resref, self.source_path)

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.detail_status is DetailStatus.COMPLETE:
            required = (
                self.display_name,
                self.short_name_strref,
                self.long_name_strref,
                self.gender_id,
                self.race_id,
                self.class_id,
                self.alignment_id,
                self.enemy_ally_id,
                self.general_id,
                self.specific_id,
                self.animation_id,
                self.racial_enemy_id,
                self.kit_raw_bytes,
                self.cre_kit_value,
                self.first_class_level,
                self.second_class_level,
                self.third_class_level,
                self.strength,
                self.strength_bonus,
                self.intelligence,
                self.wisdom,
                self.dexterity,
                self.constitution,
                self.charisma,
                self.morale,
                self.morale_break,
                self.morale_recovery_time,
                self.reputation,
                self.cre_version,
                self.serialized_size,
            )
            assert all(value is not None for value in required), (
                "complete character record is missing required CRE detail"
            )
        assert self.has_dialog == (
            self.detail_status is DetailStatus.COMPLETE and self.dialog_resref is not None
        ), "has_dialog disagrees with the extracted CRE detail"
        assert (self.attribution_status is None) == (self.attribution_completed_at is None), (
            "character attribution status and completion time must be set together"
        )
        assert (self.declared_dialogue_count is None) == (self.resolved_dialogue_count is None), (
            "declared and resolved dialogue counts must be set together"
        )
        assert (self.declared_dialogue_count is None) == (self.attribution_completed_at is None), (
            "dialogue reference counts are published with attribution"
        )
        if self.declared_dialogue_count is not None:
            assert self.resolved_dialogue_count is not None
            assert self.resolved_dialogue_count <= self.declared_dialogue_count, (
                "resolved dialogue count cannot exceed declared dialogue count"
            )
        return self


class CharacterSoundRecord(_Record):
    """One populated CRE soundset slot."""

    id: str = Field(min_length=1)
    character_resource_name: str = Field(min_length=1)
    character_resref: str = Field(min_length=1, max_length=8)
    source_kind: SourceKind = Field(strict=False)
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


class DialogueRecord(_Record):
    """One effective DLG and its current extraction and attribution state."""

    resource_name: str = Field(min_length=1)
    resref: str = Field(min_length=1, max_length=8)
    source_kind: SourceKind = Field(strict=False)
    source_path: str = Field(min_length=1)

    dlg_version: str | None = None
    state_count: int | None = Field(default=None, ge=0)
    transition_count: int | None = Field(default=None, ge=0)
    npc_line_count: int | None = Field(default=None, ge=0)
    player_line_count: int | None = Field(default=None, ge=0)
    journal_line_count: int | None = Field(default=None, ge=0)
    dialogue_line_count: int | None = Field(default=None, ge=0)
    serialized_size: int | None = Field(default=None, ge=0)
    detail_status: DetailStatus = Field(strict=False)
    detail_error: str | None = None
    updated_at: str = Field(min_length=1)

    character_count: int = Field(ge=0)
    attribution_completed_at: str | None = None
    search_text: str

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        metrics = (
            self.state_count,
            self.transition_count,
            self.npc_line_count,
            self.player_line_count,
            self.journal_line_count,
            self.dialogue_line_count,
            self.serialized_size,
        )
        if self.detail_status is DetailStatus.COMPLETE:
            assert self.dlg_version is not None and all(value is not None for value in metrics), (
                "complete dialogue record is missing required DLG detail"
            )
            assert self.dialogue_line_count is not None
            assert self.npc_line_count is not None
            assert self.player_line_count is not None
            assert self.dialogue_line_count == self.npc_line_count + self.player_line_count, (
                "dialogue line count must equal NPC plus player lines"
            )
        assert self.attribution_completed_at is not None or self.character_count == 0, (
            "unattributed dialogue cannot have a character count"
        )
        return self


class DialogueLineRecord(_Record):
    """One stable, addressable DLG line."""

    id: str = Field(min_length=1)
    dialogue_resource_name: str = Field(min_length=1)
    dialogue_resref: str = Field(min_length=1, max_length=8)
    source_kind: SourceKind = Field(strict=False)
    line_kind: DialogueLineKind = Field(strict=False)
    state_index: int = Field(ge=0)
    state_trigger_index: int | None = Field(default=None, ge=0)
    state_trigger_text: str | None = None
    transition_index: int | None = Field(default=None, ge=0)
    strref: int = Field(ge=0)
    text: str | None
    tokens: list[str]
    serialized_size: int = Field(ge=0)
    character_count: int = Field(ge=0)
    attribution_completed_at: str | None = None
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
        assert self.attribution_completed_at is not None or self.character_count == 0, (
            "unattributed dialogue line cannot have a character count"
        )
        return self


class DialogueTransitionRecord(_Record):
    """One stable edge in a DLG state machine."""

    id: str = Field(min_length=1)
    dialogue_resource_name: str = Field(min_length=1)
    dialogue_resref: str = Field(min_length=1, max_length=8)
    source_kind: SourceKind = Field(strict=False)
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
        self._invalidate_other_attributions()
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
        retained_names: set[str] = set()
        for resource in resources:
            key = resource.resource_name.casefold()
            if key in existing and _same_identity(existing[key], resource):
                replacement.append(
                    _validated_character_copy(
                        existing[key],
                        resource_name=resource.resource_name,
                        updated_at=timestamp,
                        clear_attribution=True,
                    )
                )
                retained_names.add(existing[key].resource_name)
            else:
                replacement.append(_pending_character(resource, timestamp))

        discarded_names = sorted(
            character.resource_name
            for character in existing.values()
            if character.resource_name not in retained_names
        )
        updated_run = ExtractionRunRecord.model_validate(
            run.model_dump() | {"resources_discovered": len(resources)}
        )
        if discarded_names:
            self._table(_CHARACTER_SOUNDS).delete(
                col("character_resource_name").isin(discarded_names)
            )
        self._replace(_CHARACTERS, "resource_name", CharacterRecord, replacement)
        self._invalidate_other_attributions(invalidate_characters=False)
        self._merge(_EXTRACTION_RUNS, "id", [updated_run])

    def detail_targets(self, *, refresh: bool) -> set[str]:
        """Return CRE resources that need detail extraction."""
        characters = self._records(_CHARACTERS, CharacterRecord)
        return {
            character.resource_name
            for character in characters
            if refresh or character.detail_status is not DetailStatus.COMPLETE
        }

    def apply_detail_batch(
        self,
        details: Sequence[CharacterDetail],
        failures: Iterable[tuple[str, str]],
    ) -> None:
        """Persist one validated batch of successful and failed CRE details."""
        failures = list(failures)
        success_names = [detail.resource_name for detail in details]
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
            _completed_character(characters[detail.resource_name.casefold()], detail, timestamp)
            for detail in details
        ]
        updates.extend(
            _failed_character(characters[resource_name.casefold()], error, timestamp)
            for resource_name, error in failures
        )
        sound_records = [
            _character_sound_record(
                characters[detail.resource_name.casefold()],
                detail,
                sound,
            )
            for detail in details
            for sound in detail.sounds
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
                    _pending_character_refresh(characters[name.casefold()], timestamp)
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
        retained_names: set[str] = set()
        for resource in resources:
            key = resource.resource_name.casefold()
            if key in existing and _same_identity(existing[key], resource):
                replacement.append(
                    _validated_dialogue_copy(
                        existing[key],
                        resource_name=resource.resource_name,
                        updated_at=timestamp,
                        clear_attribution=True,
                    )
                )
                retained_names.add(existing[key].resource_name)
            else:
                replacement.append(_pending_dialogue(resource, timestamp))

        discarded_names = sorted(
            dialogue.resource_name
            for dialogue in existing.values()
            if dialogue.resource_name not in retained_names
        )
        updated_run = ExtractionRunRecord.model_validate(
            run.model_dump() | {"resources_discovered": len(resources)}
        )
        self._invalidate_other_attributions(invalidate_dialogues=False)
        if discarded_names:
            self._table(_DIALOGUE_LINES).delete(col("dialogue_resource_name").isin(discarded_names))
            self._table(_DIALOGUE_TRANSITIONS).delete(
                col("dialogue_resource_name").isin(discarded_names)
            )
        self._replace(_DIALOGUES, "resource_name", DialogueRecord, replacement)
        self._merge(_EXTRACTION_RUNS, "id", [updated_run])

    def dialogue_targets(self, *, refresh: bool) -> list[str]:
        """Return DLG resources that need metric and line extraction."""
        dialogues = self._records(_DIALOGUES, DialogueRecord)
        return sorted(
            (
                dialogue.resource_name
                for dialogue in dialogues
                if refresh or dialogue.detail_status is not DetailStatus.COMPLETE
            ),
            key=str.casefold,
        )

    def apply_dialogue_batch(
        self,
        details: Sequence[DialogueExtraction],
        failures: Iterable[tuple[str, str]],
    ) -> None:
        """Persist one validated batch of DLG metrics, lines, and failures."""
        failures = list(failures)
        success_names = [extraction.detail.resource_name for extraction in details]
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
            detail = extraction.detail
            dialogue = dialogues[detail.resource_name.casefold()]
            assert detail.resref.casefold() == dialogue.resref.casefold(), (
                f"DLG detail {detail.resource_name!r} has resref {detail.resref!r}; "
                f"inventory has {dialogue.resref!r}"
            )
            dialogue_updates.append(_completed_dialogue(dialogue, detail, timestamp))
            line_records.extend(_dialogue_line_record(dialogue, line) for line in extraction.lines)
            transition_records.extend(
                _dialogue_transition_record(dialogue, edge) for edge in extraction.edges
            )
        dialogue_updates.extend(
            _failed_dialogue(dialogues[resource_name.casefold()], error, timestamp)
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
                    _pending_dialogue_refresh(dialogues[name.casefold()], timestamp)
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
        """Account for every current character, dialogue, and spoken line."""
        timestamp = utc_now().isoformat()
        characters = self._records(_CHARACTERS, CharacterRecord)
        dialogues = self._records(_DIALOGUES, DialogueRecord)
        lines = self._records(_DIALOGUE_LINES, DialogueLineRecord)
        transitions = self._records(_DIALOGUE_TRANSITIONS, DialogueTransitionRecord)
        links = self._records(_CHARACTER_RESOURCE_LINKS, CharacterResourceLinkRecord)
        self._assert_dialogue_lines(dialogues, lines)
        self._assert_dialogue_transitions(dialogues, transitions)
        dialogues_by_resref = {dialogue.resref.casefold(): dialogue for dialogue in dialogues}
        links_by_death_variable: dict[str, list[CharacterResourceLinkRecord]] = {}
        for link in links:
            if link.target_type is ResourceTargetType.DIALOGUE:
                links_by_death_variable.setdefault(link.death_variable.casefold(), []).append(link)

        character_counts: Counter[str] = Counter()
        character_dialogues: dict[
            str,
            tuple[tuple[str, ...], tuple[DialogueRecord, ...]],
        ] = {}
        for character in characters:
            declared = _character_dialogue_resrefs(character, links_by_death_variable)
            resolved = tuple(
                dialogues_by_resref[resref.casefold()]
                for resref in declared
                if resref.casefold() in dialogues_by_resref
            )
            character_dialogues[character.resource_name.casefold()] = (declared, resolved)
            for dialogue in resolved:
                character_counts[dialogue.resource_name.casefold()] += 1

        dialogue_updates = [
            DialogueRecord.model_validate(
                dialogue.model_dump()
                | {
                    "character_count": character_counts[dialogue.resource_name.casefold()],
                    "attribution_completed_at": timestamp,
                }
            )
            for dialogue in dialogues
        ]
        character_updates = [
            _attributed_character(
                character,
                *character_dialogues[character.resource_name.casefold()],
                timestamp,
            )
            for character in characters
        ]
        line_updates = [
            DialogueLineRecord.model_validate(
                line.model_dump()
                | {
                    "character_count": character_counts[line.dialogue_resource_name.casefold()],
                    "attribution_completed_at": timestamp,
                }
            )
            for line in lines
        ]

        statuses = Counter(character.attribution_status for character in character_updates)
        attributed_dialogues = [
            dialogue for dialogue in dialogue_updates if dialogue.character_count > 0
        ]
        unattributed_dialogues = [
            dialogue for dialogue in dialogue_updates if dialogue.character_count == 0
        ]
        attributed_lines = sum(
            dialogue.dialogue_line_count or 0 for dialogue in attributed_dialogues
        )
        unattributed_lines = sum(
            dialogue.dialogue_line_count or 0 for dialogue in unattributed_dialogues
        )
        all_spoken_lines = sum(dialogue.dialogue_line_count or 0 for dialogue in dialogues)
        assert attributed_lines + unattributed_lines == all_spoken_lines, (
            "attributed and unattributed DLG line totals do not reconcile"
        )
        summary = AttributionSummary(
            characters_total=len(character_updates),
            characters_matched=statuses[AttributionStatus.MATCHED],
            characters_missing_dialogue=statuses[AttributionStatus.MISSING_DIALOGUE],
            characters_dialogue_failed=statuses[AttributionStatus.DIALOGUE_FAILED],
            characters_without_dialogue=statuses[AttributionStatus.NO_DIALOGUE],
            characters_unavailable=statuses[AttributionStatus.CHARACTER_UNAVAILABLE],
            dialogues_total=len(dialogue_updates),
            dialogues_attributed=len(attributed_dialogues),
            dialogues_unattributed=len(unattributed_dialogues),
            attributed_dialogue_lines=attributed_lines,
            unattributed_dialogue_lines=unattributed_lines,
        )
        if any(character.attribution_completed_at is not None for character in characters):
            self._merge(
                _CHARACTERS,
                "resource_name",
                [
                    _validated_character_copy(character, clear_attribution=True)
                    for character in characters
                ],
            )
        self._merge(_DIALOGUES, "resource_name", dialogue_updates)
        self._merge(_DIALOGUE_LINES, "id", line_updates)
        self._optimize(_DIALOGUES, self._table(_DIALOGUES))
        self._optimize(_DIALOGUE_LINES, self._table(_DIALOGUE_LINES))
        self._merge(_CHARACTERS, "resource_name", character_updates)
        self._optimize(_CHARACTERS, self._table(_CHARACTERS))
        return summary

    def finish_run(
        self,
        run_id: str,
        *,
        status: TerminalRunStatus,
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
            else:
                assert run.run_kind is RunKind.METADATA
                for name in _METADATA_TABLES:
                    self._optimize(name, self._table(name))
        self._merge(_EXTRACTION_RUNS, "id", [updated])

    def stats(self) -> DatabaseStats:
        """Return validated counts for the current CRE inventory."""
        characters = self._records(_CHARACTERS, CharacterRecord)
        statuses = Counter(character.detail_status for character in characters)
        return DatabaseStats(
            total=len(characters),
            complete=statuses[DetailStatus.COMPLETE],
            failed=statuses[DetailStatus.FAILED],
            pending=statuses[DetailStatus.PENDING],
            with_dialog=sum(character.has_dialog for character in characters),
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

    def _invalidate_other_attributions(
        self,
        *,
        invalidate_characters: bool = True,
        invalidate_dialogues: bool = True,
    ) -> None:
        if invalidate_characters:
            characters = self._records(_CHARACTERS, CharacterRecord)
            if any(character.attribution_completed_at is not None for character in characters):
                self._merge(
                    _CHARACTERS,
                    "resource_name",
                    [
                        _validated_character_copy(character, clear_attribution=True)
                        for character in characters
                    ],
                )
        if invalidate_dialogues:
            dialogues = self._records(_DIALOGUES, DialogueRecord)
            if any(dialogue.attribution_completed_at is not None for dialogue in dialogues):
                self._merge(
                    _DIALOGUES,
                    "resource_name",
                    [
                        _validated_dialogue_copy(dialogue, clear_attribution=True)
                        for dialogue in dialogues
                    ],
                )
        lines = self._records(_DIALOGUE_LINES, DialogueLineRecord)
        if any(line.attribution_completed_at is not None for line in lines):
            self._merge(
                _DIALOGUE_LINES,
                "id",
                [
                    DialogueLineRecord.model_validate(
                        line.model_dump()
                        | {
                            "character_count": 0,
                            "attribution_completed_at": None,
                        }
                    )
                    for line in lines
                ],
            )

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

    @staticmethod
    def _assert_dialogue_lines(
        dialogues: Sequence[DialogueRecord],
        lines: Sequence[DialogueLineRecord],
    ) -> None:
        dialogue_names = {dialogue.resource_name.casefold() for dialogue in dialogues}
        unknown = sorted(
            {
                line.dialogue_resource_name
                for line in lines
                if line.dialogue_resource_name.casefold() not in dialogue_names
            }
        )
        assert not unknown, f"dialogue lines reference unknown DLG resources: {unknown}"

        counts = Counter((line.dialogue_resource_name.casefold(), line.line_kind) for line in lines)
        for dialogue in dialogues:
            key = dialogue.resource_name.casefold()
            actual = tuple(
                counts[(key, kind)]
                for kind in (
                    DialogueLineKind.NPC,
                    DialogueLineKind.PLAYER,
                    DialogueLineKind.JOURNAL,
                )
            )
            expected = (
                (
                    dialogue.npc_line_count,
                    dialogue.player_line_count,
                    dialogue.journal_line_count,
                )
                if dialogue.detail_status is DetailStatus.COMPLETE
                else (0, 0, 0)
            )
            assert actual == expected, (
                f"{dialogue.resource_name} stores line counts {actual}; expected {expected}"
            )

    @staticmethod
    def _assert_dialogue_transitions(
        dialogues: Sequence[DialogueRecord],
        transitions: Sequence[DialogueTransitionRecord],
    ) -> None:
        dialogue_names = {dialogue.resource_name.casefold() for dialogue in dialogues}
        unknown = sorted(
            {
                transition.dialogue_resource_name
                for transition in transitions
                if transition.dialogue_resource_name.casefold() not in dialogue_names
            }
        )
        assert not unknown, f"dialogue transitions reference unknown DLG resources: {unknown}"

        counts = Counter(transition.dialogue_resource_name.casefold() for transition in transitions)
        for dialogue in dialogues:
            actual = counts[dialogue.resource_name.casefold()]
            expected = (
                dialogue.transition_count if dialogue.detail_status is DetailStatus.COMPLETE else 0
            )
            assert actual == expected, (
                f"{dialogue.resource_name} stores {actual} transitions; expected {expected}"
            )


def _pending_character(resource: CreResource, timestamp: str) -> CharacterRecord:
    return CharacterRecord(
        resource_name=resource.resource_name,
        resref=resource.resref,
        source_kind=resource.source_kind,
        source_path=resource.source_path,
        detail_status=DetailStatus.PENDING,
        detail_error=None,
        updated_at=timestamp,
        has_dialog=False,
        search_text=resource.search_text,
    )


def _completed_character(
    character: CharacterRecord,
    detail: CharacterDetail,
    timestamp: str,
) -> CharacterRecord:
    serialized_size = len(detail.model_dump_json().encode("utf-8"))
    return CharacterRecord(
        resource_name=character.resource_name,
        resref=character.resref,
        source_kind=character.source_kind,
        source_path=character.source_path,
        display_name=detail.display_name,
        short_name=detail.short_name,
        short_name_strref=detail.short_name_strref,
        long_name=detail.long_name,
        long_name_strref=detail.long_name_strref,
        death_variable=detail.death_variable,
        dialog_resref=detail.dialog_resref,
        gender_id=detail.gender_id,
        race_id=detail.race_id,
        class_id=detail.class_id,
        alignment_id=detail.alignment_id,
        enemy_ally_id=detail.enemy_ally_id,
        general_id=detail.general_id,
        specific_id=detail.specific_id,
        animation_id=detail.animation_id,
        racial_enemy_id=detail.racial_enemy_id,
        kit_raw_bytes=detail.kit_raw_bytes,
        cre_kit_value=detail.cre_kit_value,
        kit_ids_value=detail.kit_ids_value,
        first_class_level=detail.class_levels.first_class,
        second_class_level=detail.class_levels.second_class,
        third_class_level=detail.class_levels.third_class,
        strength=detail.base_attributes.strength,
        strength_bonus=detail.base_attributes.strength_bonus,
        intelligence=detail.base_attributes.intelligence,
        wisdom=detail.base_attributes.wisdom,
        dexterity=detail.base_attributes.dexterity,
        constitution=detail.base_attributes.constitution,
        charisma=detail.base_attributes.charisma,
        morale=detail.morale,
        morale_break=detail.morale_break,
        morale_recovery_time=detail.morale_recovery_time,
        reputation=detail.reputation,
        override_script=detail.override_script,
        class_script=detail.class_script,
        race_script=detail.race_script,
        general_script=detail.general_script,
        default_script=detail.default_script,
        small_portrait=detail.small_portrait,
        large_portrait=detail.large_portrait,
        cre_version=detail.cre_version,
        serialized_size=serialized_size,
        detail_status=DetailStatus.COMPLETE,
        detail_error=None,
        updated_at=timestamp,
        has_dialog=detail.dialog_resref is not None,
        search_text=detail.search_text,
    )


def _failed_character(
    character: CharacterRecord,
    error: str,
    timestamp: str,
) -> CharacterRecord:
    return CharacterRecord(
        resource_name=character.resource_name,
        resref=character.resref,
        source_kind=character.source_kind,
        source_path=character.source_path,
        detail_status=DetailStatus.FAILED,
        detail_error=error[:2000],
        updated_at=timestamp,
        has_dialog=False,
        search_text=character.resource_search_text,
    )


def _pending_character_refresh(
    character: CharacterRecord,
    timestamp: str,
) -> CharacterRecord:
    return CharacterRecord(
        resource_name=character.resource_name,
        resref=character.resref,
        source_kind=character.source_kind,
        source_path=character.source_path,
        detail_status=DetailStatus.PENDING,
        detail_error=None,
        updated_at=timestamp,
        has_dialog=False,
        search_text=character.resource_search_text,
    )


def _validated_character_copy(
    character: CharacterRecord,
    *,
    resource_name: str | None = None,
    updated_at: str | None = None,
    clear_attribution: bool,
) -> CharacterRecord:
    update: dict[str, object] = {}
    if resource_name is not None:
        update["resource_name"] = resource_name
    if updated_at is not None:
        update["updated_at"] = updated_at
    if clear_attribution:
        update |= {
            "attribution_status": None,
            "dialogue_status": None,
            "declared_dialogue_count": None,
            "resolved_dialogue_count": None,
            "dialogue_line_count": None,
            "npc_line_count": None,
            "player_line_count": None,
            "journal_line_count": None,
            "dialogue_state_count": None,
            "dialogue_transition_count": None,
            "dialogue_serialized_size": None,
            "attribution_completed_at": None,
        }
    return CharacterRecord.model_validate(character.model_dump() | update)


def _pending_dialogue(resource: DlgResource, timestamp: str) -> DialogueRecord:
    return DialogueRecord(
        resource_name=resource.resource_name,
        resref=resource.resref,
        source_kind=resource.source_kind,
        source_path=resource.source_path,
        detail_status=DetailStatus.PENDING,
        detail_error=None,
        updated_at=timestamp,
        character_count=0,
        attribution_completed_at=None,
        search_text=resource.search_text,
    )


def _completed_dialogue(
    dialogue: DialogueRecord,
    detail: DialogueDetail,
    timestamp: str,
) -> DialogueRecord:
    return DialogueRecord(
        resource_name=dialogue.resource_name,
        resref=dialogue.resref,
        source_kind=dialogue.source_kind,
        source_path=dialogue.source_path,
        dlg_version=detail.dlg_version,
        state_count=detail.state_count,
        transition_count=detail.transition_count,
        npc_line_count=detail.npc_line_count,
        player_line_count=detail.player_line_count,
        journal_line_count=detail.journal_line_count,
        dialogue_line_count=detail.dialogue_line_count,
        serialized_size=detail.pydantic_json_size,
        detail_status=DetailStatus.COMPLETE,
        detail_error=None,
        updated_at=timestamp,
        character_count=0,
        attribution_completed_at=None,
        search_text=dialogue.search_text,
    )


def _failed_dialogue(
    dialogue: DialogueRecord,
    error: str,
    timestamp: str,
) -> DialogueRecord:
    return DialogueRecord(
        resource_name=dialogue.resource_name,
        resref=dialogue.resref,
        source_kind=dialogue.source_kind,
        source_path=dialogue.source_path,
        detail_status=DetailStatus.FAILED,
        detail_error=error[:2000],
        updated_at=timestamp,
        character_count=0,
        attribution_completed_at=None,
        search_text=dialogue.search_text,
    )


def _pending_dialogue_refresh(
    dialogue: DialogueRecord,
    timestamp: str,
) -> DialogueRecord:
    return DialogueRecord(
        resource_name=dialogue.resource_name,
        resref=dialogue.resref,
        source_kind=dialogue.source_kind,
        source_path=dialogue.source_path,
        detail_status=DetailStatus.PENDING,
        detail_error=None,
        updated_at=timestamp,
        character_count=0,
        attribution_completed_at=None,
        search_text=dialogue.search_text,
    )


def _validated_dialogue_copy(
    dialogue: DialogueRecord,
    *,
    resource_name: str | None = None,
    updated_at: str | None = None,
    clear_attribution: bool,
) -> DialogueRecord:
    update: dict[str, object] = {}
    if resource_name is not None:
        update["resource_name"] = resource_name
    if updated_at is not None:
        update["updated_at"] = updated_at
    if clear_attribution:
        update |= {"character_count": 0, "attribution_completed_at": None}
    return DialogueRecord.model_validate(dialogue.model_dump() | update)


def _dialogue_line_record(
    dialogue: DialogueRecord,
    line: DialogueLine,
) -> DialogueLineRecord:
    return DialogueLineRecord(
        id=line.id,
        dialogue_resource_name=dialogue.resource_name,
        dialogue_resref=dialogue.resref,
        source_kind=dialogue.source_kind,
        line_kind=line.line_kind,
        state_index=line.state_index,
        state_trigger_index=line.state_trigger_index,
        state_trigger_text=line.state_trigger_text,
        transition_index=line.transition_index,
        strref=line.strref,
        text=line.text,
        tokens=line.tokens,
        serialized_size=len(line.model_dump_json().encode("utf-8")),
        character_count=0,
        attribution_completed_at=None,
        search_text=line.search_text,
    )


def _character_sound_record(
    character: CharacterRecord,
    detail: CharacterDetail,
    sound: CharacterSound,
) -> CharacterSoundRecord:
    return CharacterSoundRecord(
        id=CharacterSound.id_for(character.resource_name, sound.slot_id),
        character_resource_name=character.resource_name,
        character_resref=character.resref,
        source_kind=character.source_kind,
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


def _dialogue_transition_record(
    dialogue: DialogueRecord,
    edge: DialogueTransitionEdge,
) -> DialogueTransitionRecord:
    return DialogueTransitionRecord(
        id=edge.id,
        dialogue_resource_name=dialogue.resource_name,
        dialogue_resref=dialogue.resref,
        source_kind=dialogue.source_kind,
        state_index=edge.state_index,
        transition_index=edge.transition_index,
        flags_raw=edge.flags_raw,
        flags_decoded=edge.flags_decoded,
        trigger_index=edge.trigger_index,
        trigger_text=edge.trigger_text,
        action_index=edge.action_index,
        action_text=edge.action_text,
        next_dialog=edge.next_dialog,
        next_state_index=edge.next_state_index,
        terminates_dialog=edge.terminates_dialog,
        serialized_size=len(edge.model_dump_json().encode("utf-8")),
        search_text=edge.search_text,
    )


def _attributed_character(
    character: CharacterRecord,
    declared_resrefs: tuple[str, ...],
    dialogues: tuple[DialogueRecord, ...],
    timestamp: str,
) -> CharacterRecord:
    status: AttributionStatus
    if character.detail_status is not DetailStatus.COMPLETE:
        status = AttributionStatus.CHARACTER_UNAVAILABLE
    elif not declared_resrefs:
        status = AttributionStatus.NO_DIALOGUE
    elif not dialogues:
        status = AttributionStatus.MISSING_DIALOGUE
    elif any(dialogue.detail_status is DetailStatus.FAILED for dialogue in dialogues):
        status = AttributionStatus.DIALOGUE_FAILED
    else:
        status = AttributionStatus.MATCHED

    dialogue_status: DetailStatus | None = None
    if dialogues:
        if any(dialogue.detail_status is DetailStatus.FAILED for dialogue in dialogues):
            dialogue_status = DetailStatus.FAILED
        elif any(dialogue.detail_status is DetailStatus.PENDING for dialogue in dialogues):
            dialogue_status = DetailStatus.PENDING
        else:
            dialogue_status = DetailStatus.COMPLETE

    update = {
        "attribution_status": status,
        "dialogue_status": dialogue_status,
        "declared_dialogue_count": len(declared_resrefs),
        "resolved_dialogue_count": len(dialogues),
        "dialogue_line_count": (
            sum(dialogue.dialogue_line_count or 0 for dialogue in dialogues) if dialogues else None
        ),
        "npc_line_count": (
            sum(dialogue.npc_line_count or 0 for dialogue in dialogues) if dialogues else None
        ),
        "player_line_count": (
            sum(dialogue.player_line_count or 0 for dialogue in dialogues) if dialogues else None
        ),
        "journal_line_count": (
            sum(dialogue.journal_line_count or 0 for dialogue in dialogues) if dialogues else None
        ),
        "dialogue_state_count": (
            sum(dialogue.state_count or 0 for dialogue in dialogues) if dialogues else None
        ),
        "dialogue_transition_count": (
            sum(dialogue.transition_count or 0 for dialogue in dialogues) if dialogues else None
        ),
        "dialogue_serialized_size": (
            sum(dialogue.serialized_size or 0 for dialogue in dialogues) if dialogues else None
        ),
        "attribution_completed_at": timestamp,
    }
    return CharacterRecord.model_validate(character.model_dump() | update)


def _character_dialogue_resrefs(
    character: CharacterRecord,
    links_by_death_variable: dict[str, list[CharacterResourceLinkRecord]],
) -> tuple[str, ...]:
    resrefs: dict[str, str] = {}
    if character.dialog_resref is not None:
        resrefs[character.dialog_resref.casefold()] = character.dialog_resref
    if character.death_variable is not None:
        for link in links_by_death_variable.get(character.death_variable.casefold(), []):
            resrefs.setdefault(link.target_resref.casefold(), link.target_resref)
    return tuple(resrefs.values())


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
        record.resource_name.casefold() == resource.resource_name.casefold()
        and record.resref.casefold() == resource.resref.casefold()
        and record.source_kind == resource.source_kind
        and record.source_path == resource.source_path
    )
