"""Pydantic and Arrow schemas for persisted pipeline rows."""

import hashlib
from typing import Annotated, Self

import pyarrow as pa
from lancedb.pydantic import LanceModel
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bgvoice.character_models import CharacterSound
from bgvoice.dialogue_models import DialogueLine, DialogueTransitionEdge
from bgvoice.model_types import (
    AttributionStatus,
    CampaignResourceKind,
    CharacterResourceRole,
    DetailStatus,
    DialogueLineKind,
    ExtractionState,
    GenerationFailureStage,
    HappinessAlignment,
    IdentifierKind,
    InteractionKind,
    ReadableItemKind,
    ResourceSource,
    ResourceTargetType,
    RunKind,
    RunStatus,
)


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


class KeyedRecord(_Record):
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


class PortraitImageRecord(_Record):
    """One effective CRE portrait, normalized to a directly usable PNG."""

    resref: str = Field(min_length=1, max_length=8)
    source: ResourceSource
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    png: bytes = Field(min_length=1)


class ReadableItemRecord(_Record):
    """One effective readable ITM with both source and preferred localized text."""

    resource_name: str = Field(min_length=1)
    resref: str = Field(min_length=1, max_length=8)
    source: ResourceSource
    kind: ReadableItemKind = Field(strict=False)
    item_type: int = Field(ge=0, le=0xFFFF)
    ground_icon: str | None = Field(default=None, max_length=8)
    icon: str | None = Field(default=None, max_length=8)
    description_image: str | None = Field(default=None, max_length=8)
    general_name_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    general_name: str | None
    identified_name_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    identified_name: str | None
    general_description_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    general_description: str | None
    identified_description_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    identified_description: str | None
    display_title: str = Field(min_length=1)
    title_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    text: str = Field(min_length=1)
    text_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    text_length: int = Field(gt=0)
    item_version: str = Field(min_length=1)
    serialized_size: int = Field(ge=0)
    search_text: str

    @model_validator(mode="after")
    def validate_text_length(self) -> Self:
        assert self.text_length == len(self.text), "readable item text length must match its text"
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
    biography_sound_id: str | None = None
    search_text: str

    @staticmethod
    def key_for(run_id: str, voice_id: str) -> str:
        return f"{run_id}:{voice_id}"

    @model_validator(mode="after")
    def validate_key(self) -> Self:
        expected = self.key_for(self.run_id, self.voice_id)
        assert self.key == expected, f"voice resource key must be {expected!r}"
        return self


class VoiceDescription(BaseModel):
    """Final provider-ready description of one generated voice."""

    model_config = ConfigDict(strict=True, extra="forbid")

    text: Annotated[
        str,
        Field(min_length=30, max_length=2000, pattern=r"^[\x20-\x7E\r\n]+$"),
    ]
    language_code: Annotated[str, Field(min_length=2, max_length=35)]


class GeneratedVoiceRecord(_Record):
    """One published Inworld voice keyed by its canonical local voice."""

    voice_id: str = Field(min_length=1)
    inworld_voice_id: str = Field(min_length=1)
    description: VoiceDescription
    created_at: str = Field(min_length=1)


class CharacterDirection(BaseModel):
    """Processed dialogue spoken by its attributed character."""

    model_config = ConfigDict(strict=True, extra="forbid")

    directed_dialogue: Annotated[
        str,
        Field(
            min_length=1,
            max_length=2000,
            description=(
                "The character's complete spoken text, with concise Inworld TTS-2 square-bracket "
                "instruction tags and with source-only asterisks and Infinity Engine placeholders "
                "removed or naturally rewritten."
            ),
        ),
    ]


class NarratorDirection(BaseModel):
    """Processed scene narration spoken by the shared narrator."""

    model_config = ConfigDict(strict=True, extra="forbid")

    directed_dialogue: Annotated[
        str,
        Field(
            min_length=1,
            max_length=2000,
            description=(
                "The narrator's complete spoken text, with concise Inworld TTS-2 square-bracket "
                "instruction tags and with source-only asterisks, enclosing parentheses, and "
                "Infinity Engine placeholders removed or naturally rewritten."
            ),
        ),
    ]


class DirectedLineRecord(_Record):
    """One processed line ready for speech synthesis."""

    id: str = Field(min_length=1, max_length=63)
    voice_id: str = Field(min_length=1)
    dialogue_line_id: str = Field(min_length=1)
    character: CharacterDirection | None = None
    narrator: NarratorDirection | None = None
    created_at: str = Field(min_length=1)

    @staticmethod
    def id_for(voice_id: str, dialogue_line_id: str) -> str:
        identity = f"{voice_id}\0{dialogue_line_id}".encode()
        return f"d-{hashlib.blake2s(identity, digest_size=16).hexdigest()}"

    @model_validator(mode="after")
    def validate_id(self) -> Self:
        expected = self.id_for(self.voice_id, self.dialogue_line_id)
        assert self.id == expected, f"directed line id must be {expected!r}"
        assert (self.character is None) != (self.narrator is None), (
            "a directed line must contain exactly one character or narrator result"
        )
        return self


class GeneratedAudioRecord(_Record):
    """One game-ready Ogg Vorbis recording installed later as a .WAV resource."""

    id: str = Field(min_length=1, max_length=63)
    voice_id: str = Field(min_length=1)
    dialogue_line_id: str = Field(min_length=1)
    inworld_voice_id: str = Field(min_length=1)
    batch_operation_name: str = Field(min_length=1)
    audio: bytes = Field(min_length=1)
    created_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_id(self) -> Self:
        expected = DirectedLineRecord.id_for(self.voice_id, self.dialogue_line_id)
        assert self.id == expected, f"generated audio id must be {expected!r}"
        assert self.audio.startswith(b"OggS"), "generated audio must be Ogg Vorbis"
        return self


class GeneratedAudioIdentity(_Record):
    """Blob-free projection used for joins and existence checks."""

    id: str
    voice_id: str
    dialogue_line_id: str


class GenerationFailureRecord(_Record):
    """Latest unresolved failure for one voice or dialogue-line generation stage."""

    id: str = Field(min_length=1, max_length=63)
    stage: GenerationFailureStage = Field(strict=False)
    voice_id: str = Field(min_length=1)
    dialogue_line_id: str | None = Field(default=None, min_length=1)
    error_type: str = Field(min_length=1, max_length=200)
    error_code: str | None = Field(default=None, min_length=1, max_length=200)
    error: str = Field(min_length=1, max_length=2000)
    failed_at: str = Field(min_length=1)

    @staticmethod
    def id_for(
        stage: GenerationFailureStage,
        voice_id: str,
        dialogue_line_id: str | None = None,
    ) -> str:
        identity = f"{stage.value}\0{voice_id}\0{dialogue_line_id or ''}".encode()
        return f"f-{hashlib.blake2s(identity, digest_size=16).hexdigest()}"

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        line_failure = self.stage in (
            GenerationFailureStage.DIALOGUE_DIRECTION,
            GenerationFailureStage.AUDIO_GENERATION,
        )
        assert line_failure == (self.dialogue_line_id is not None), (
            "direction and audio failures require a dialogue line; voice failures must omit it"
        )
        expected = self.id_for(self.stage, self.voice_id, self.dialogue_line_id)
        assert self.id == expected, f"generation failure id must be {expected!r}"
        return self


class TtsBatchRecord(_Record):
    """Durable handle for one asynchronous Inworld synthesis operation."""

    operation_name: str = Field(min_length=1)
    custom_ids: list[str] = Field(min_length=1)
    status: RunStatus = Field(strict=False)
    started_at: str = Field(min_length=1)
    completed_at: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        assert all(0 < len(custom_id) <= 63 for custom_id in self.custom_ids), (
            "TTS batch custom IDs must contain 1 to 63 characters"
        )
        assert len(self.custom_ids) == len(set(self.custom_ids)), (
            "TTS batch custom IDs must be unique"
        )
        running = self.status is RunStatus.RUNNING
        assert running == (self.completed_at is None), (
            "running TTS batches must be open and terminal batches must be completed"
        )
        assert (self.status is RunStatus.FAILED) == (self.error is not None), (
            "only failed TTS batches carry an error"
        )
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
    """Durable lifecycle record for one pipeline stage attempt."""

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


class IdentifierDefinitionRecord(KeyedRecord):
    """One normalized IDS value and all aliases from its effective resource."""

    kind: IdentifierKind = Field(strict=False)
    value: int = Field(ge=0)
    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    symbols: list[str]
    search_text: str


class CampaignDefinitionRecord(KeyedRecord):
    """One campaign row from the effective CAMPAIGN.2DA."""

    campaign_id: str = Field(min_length=1)
    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)


class CampaignResourceBindingRecord(KeyedRecord):
    """One campaign-selected effective resource relationship."""

    campaign_id: str = Field(min_length=1)
    resource_kind: CampaignResourceKind = Field(strict=False)
    resource_resref: str | None = None


class CharacterResourceLinkRecord(KeyedRecord):
    """One dialogue or script associated with a character death variable."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    death_variable: str = Field(min_length=1)
    source_column: str = Field(min_length=1)
    role: CharacterResourceRole = Field(strict=False)
    target_type: ResourceTargetType = Field(strict=False)
    target_resref: str = Field(min_length=1, max_length=8)
    search_text: str


class InteractionRuleRecord(KeyedRecord):
    """One non-empty party interaction matrix edge."""

    source_resource: str = Field(min_length=1)
    speaker_ordinal: int = Field(ge=0)
    target_ordinal: int = Field(ge=0)
    speaker_death_variable: str = Field(min_length=1)
    target_death_variable: str = Field(min_length=1)
    kind: InteractionKind = Field(strict=False)
    search_text: str


class SoundsetLineRecord(KeyedRecord):
    """One populated CHARSND soundset/slot cell."""

    source_resource: str = Field(min_length=1)
    soundset_name: str = Field(min_length=1)
    slot_id: int = Field(ge=0, le=0xFF)
    strref: int = Field(ge=0, le=0xFFFF_FFFF)
    text: str | None
    search_text: str


class SoundSlotSuffixRecord(KeyedRecord):
    """One CSOUND slot-to-audio-filename suffix mapping."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    slot_id: int = Field(ge=0, le=0xFF)
    file_suffix: str | None


class SoundSlotGroupRecord(KeyedRecord):
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


class FavoredEnemyRecord(KeyedRecord):
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


class HappinessRuleRecord(KeyedRecord):
    """One HAPPY.2DA alignment/reputation matrix cell."""

    source_resource: str = Field(min_length=1)
    reputation: int = Field(ge=1, le=20)
    alignment: HappinessAlignment = Field(strict=False)
    happiness: int


class BanterTimingSettingsRecord(KeyedRecord):
    """Effective BANTTIMG.2DA controls for party-member banter."""

    source_resource: str = Field(min_length=1)
    frequency: int = Field(ge=0, le=0xFFFF_FFFF)
    probability: int = Field(ge=0, le=0xFFFF_FFFF)
    replay_delay: int = Field(ge=0, le=0xFFFF_FFFF)
    special_probability: int = Field(ge=0, le=0xFFFF_FFFF)


class EngineStringRecord(KeyedRecord):
    """One named engine string with resolved TLK text."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    strref: int | None = Field(default=None, ge=0, le=0xFFFF_FFFF)
    text: str | None
    search_text: str


class MonthDefinitionRecord(KeyedRecord):
    """One MONTHS.2DA calendar segment."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    month_id: int = Field(ge=0, le=0xFFFF_FFFF)
    days: int = Field(gt=0)
    name_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    name: str | None
    search_text: str


class CampaignCalendarRecord(KeyedRecord):
    """One campaign year resource with resolved date formats."""

    source_resource: str = Field(min_length=1)
    start_time: int = Field(ge=0, le=0xFFFF_FFFF)
    start_year: int = Field(ge=0, le=0xFFFF_FFFF)
    normal_format_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    normal_format: str | None
    special_format_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    special_format: str | None
    search_text: str


class RaceTextRecord(KeyedRecord):
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


class ClassTextRecord(KeyedRecord):
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


class KitDefinitionRecord(KeyedRecord):
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
