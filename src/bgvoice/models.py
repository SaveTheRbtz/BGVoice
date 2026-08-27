"""Validated ``ie-cli`` projections and pipeline records.

Binary field semantics come from IESDP's CRE V1 and DLG V1 specifications:
https://gibberlings3.github.io/iesdp/file_formats/ie_formats/cre_v1.htm
https://gibberlings3.github.io/iesdp/file_formats/ie_formats/dlg_v1.htm
"""

import re
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, NewType, Self

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator


class DialogueLineKind(StrEnum):
    NPC = "npc"
    PLAYER = "player"
    JOURNAL = "journal"


class DetailStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class AttributionStatus(StrEnum):
    MATCHED = "matched"
    PARTIAL_MATCH = "partial_match"
    MISSING_DIALOGUE = "missing_dialogue"
    NO_DIALOGUE = "no_dialogue"
    CHARACTER_UNAVAILABLE = "character_unavailable"


class AttributionPublicationStatus(StrEnum):
    """Whether a completed attribution generation matches current inputs."""

    MISSING = "missing"
    STALE = "stale"
    PUBLISHED = "published"


class RunKind(StrEnum):
    CHARACTERS = "characters"
    DIALOGUES = "dialogues"
    METADATA = "metadata"
    ATTRIBUTION = "attribution"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETE = "complete"
    COMPLETE_WITH_ERRORS = "complete_with_errors"
    FAILED = "failed"


type TerminalRunStatus = Literal[
    RunStatus.COMPLETE,
    RunStatus.COMPLETE_WITH_ERRORS,
    RunStatus.FAILED,
]


class SourceKind(StrEnum):
    OVERRIDE = "override"
    BIF = "bif"
    DLC = "dlc"


type ResRef = Annotated[str, Field(min_length=1, max_length=8)]
type WireResRef = Annotated[str, Field(max_length=8)]
type UInt8 = Annotated[int, Field(ge=0, le=0xFF)]
type UInt16 = Annotated[int, Field(ge=0, le=0xFFFF)]
type UInt32 = Annotated[int, Field(ge=0, le=0xFFFF_FFFF)]
type DialogueToken = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")]
type ExceptionalStrength = Annotated[int, Field(ge=0, le=100)]

RaceId = NewType("RaceId", int)
ClassId = NewType("ClassId", int)
GenderId = NewType("GenderId", int)
AlignmentId = NewType("AlignmentId", int)
EnemyAllyId = NewType("EnemyAllyId", int)
GeneralId = NewType("GeneralId", int)
SpecificId = NewType("SpecificId", int)
AnimationId = NewType("AnimationId", int)
CreKitValue = NewType("CreKitValue", int)
KitIdsValue = NewType("KitIdsValue", int)
ClassTextKitId = NewType("ClassTextKitId", int)
KitListRowId = NewType("KitListRowId", int)
SoundSlotId = NewType("SoundSlotId", int)
VoiceId = NewType("VoiceId", str)

type RaceIdField = Annotated[RaceId, Field(ge=0, le=0xFF)]
type ClassIdField = Annotated[ClassId, Field(ge=0, le=0xFF)]
type GenderIdField = Annotated[GenderId, Field(ge=0, le=0xFF)]
type AlignmentIdField = Annotated[AlignmentId, Field(ge=0, le=0xFF)]
type EnemyAllyIdField = Annotated[EnemyAllyId, Field(ge=0, le=0xFF)]
type GeneralIdField = Annotated[GeneralId, Field(ge=0, le=0xFF)]
type SpecificIdField = Annotated[SpecificId, Field(ge=0, le=0xFF)]
type AnimationIdField = Annotated[AnimationId, Field(ge=0, le=0xFFFF)]
type CreKitValueField = Annotated[CreKitValue, Field(ge=0, le=0xFFFF_FFFF)]
type KitIdsValueField = Annotated[KitIdsValue, Field(ge=0, le=0xFFFF_FFFF)]
type ClassTextKitIdField = Annotated[ClassTextKitId, Field(ge=0, le=0xFFFF_FFFF)]
type KitListRowIdField = Annotated[KitListRowId, Field(ge=0, le=0xFFFF_FFFF)]
type SoundSlotIdField = Annotated[SoundSlotId, Field(ge=0, le=0xFF)]

_EE_COLOR_TAG: re.Pattern[str] = re.compile(r"\^(?:0x[0-9A-Fa-f]{8}|-)")
# Infinity Engine string tokens are angle-bracketed identifiers. Restricting the
# body to an ASCII identifier avoids treating ordinary prose or markup as a token.
_DIALOGUE_TOKEN: re.Pattern[str] = re.compile(r"<([A-Za-z][A-Za-z0-9_]*)>")


def compose_search_text(*values: str | None) -> str:
    """Join populated searchable values into one FTS document."""
    return " ".join(value for value in values if value)


class StrictModel(BaseModel):
    """Base model that rejects implicit coercion and unknown fields."""

    model_config = ConfigDict(strict=True, extra="forbid")


class IeCliProjection(BaseModel):
    """Strictly validate fields used here while allowing unused upstream fields."""

    model_config = ConfigDict(strict=True, extra="ignore")


class CreResource(IeCliProjection):
    """One effective CRE resource returned by ``iecli list``."""

    resource_name: str = Field(min_length=1)
    resref: ResRef
    source_kind: SourceKind = Field(strict=False)
    source_path: str = Field(min_length=1)
    resource_type: Literal["CRE"] = Field(alias="type")

    @property
    def search_text(self) -> str:
        return compose_search_text(self.resource_name, self.resref, self.source_path)


class DlgResource(IeCliProjection):
    """One effective DLG resource returned by ``iecli list``."""

    resource_name: str = Field(min_length=1)
    resref: ResRef
    source_kind: SourceKind = Field(strict=False)
    source_path: str = Field(min_length=1)
    resource_type: Literal["DLG"] = Field(alias="type")

    @property
    def search_text(self) -> str:
        return compose_search_text(self.resource_name, self.resref, self.source_path)


class ResourceSource(StrictModel):
    """Physical origin of one effective Infinity Engine resource."""

    kind: SourceKind = Field(strict=False)
    path: str = Field(min_length=1)

    @classmethod
    def from_resource(cls, resource: CreResource | DlgResource) -> Self:
        return cls(kind=resource.source_kind, path=resource.source_path)


class ExtractionState(StrictModel):
    """Lifecycle of the detail currently attached to a resource."""

    run_id: str = Field(min_length=1)
    status: DetailStatus = Field(strict=False)
    error: str | None = None
    updated_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_error(self) -> Self:
        assert (self.status is DetailStatus.FAILED) == (self.error is not None), (
            "only failed extraction states carry an error"
        )
        return self


class StringReference(IeCliProjection):
    """A TLK string reference and its resolved text."""

    strref: UInt32
    text: str | None = None


class IdentifierKind(StrEnum):
    """CRE categorical namespaces backed by effective IDS resources."""

    RACE = "race"
    CLASS = "class"
    GENDER = "gender"
    ALIGNMENT = "alignment"
    ENEMY_ALLY = "enemy_ally"
    GENERAL = "general"
    SPECIFIC = "specific"
    ANIMATION = "animation"
    KIT = "kit"
    SOUND_SLOT = "sound_slot"


class CampaignResourceKind(StrEnum):
    """Resource roles selected independently by each CAMPAIGN.2DA row."""

    RACE_TEXT = "race_text"
    CLASS_TEXT = "class_text"
    BANTER_DIALOGUES = "banter_dialogues"
    PARTY_DIALOGUES = "party_dialogues"
    INTERACTIONS = "interactions"
    CALENDAR = "calendar"


class CharacterResourceRole(StrEnum):
    """How a party-character table associates a resource with a character."""

    BANTER_DIALOGUE = "banter_dialogue"
    POST_DIALOGUE = "post_dialogue"
    JOIN_DIALOGUE = "join_dialogue"
    DREAM_SCRIPT = "dream_script"
    OVERRIDE_SCRIPT = "override_script"


class ResourceTargetType(StrEnum):
    """Infinity Engine resource family targeted by a character resource link."""

    DIALOGUE = "dialogue"
    SCRIPT = "script"


class InteractionKind(StrEnum):
    """Party interaction selected by an INTERACT-compatible matrix cell."""

    INSULT = "insult"
    COMPLIMENT = "compliment"
    SPECIAL = "special"


class HappinessAlignment(StrEnum):
    """Broad alignment column used by HAPPY.2DA."""

    GOOD = "good"
    NEUTRAL = "neutral"
    EVIL = "evil"


class CreClassification(IeCliProjection):
    """CRE V1 bytes 0x270-0x27B, interpreted through the corresponding IDS tables."""

    enemy_ally: EnemyAllyIdField
    general: GeneralIdField
    race: RaceIdField
    class_id: ClassIdField = Field(alias="class")
    specific: SpecificIdField
    gender: GenderIdField
    alignment: AlignmentIdField


class CreClassLevels(IeCliProjection):
    """CRE V1 level bytes at offsets 0x234 through 0x236."""

    first_class: UInt8
    second_class: UInt8
    third_class: UInt8


class CreBaseAttributes(IeCliProjection):
    """CRE V1 ability bytes at offsets 0x238 through 0x23E."""

    strength: UInt8
    strength_bonus: ExceptionalStrength
    intelligence: UInt8
    wisdom: UInt8
    dexterity: UInt8
    constitution: UInt8
    charisma: UInt8


class CreKit(IeCliProjection):
    """Raw CRE V1 kit bytes at 0x244; ie-cli's decoded fields are intentionally ignored."""

    raw_bytes: Annotated[list[UInt8], Field(min_length=4, max_length=4)]

    @property
    def cre_value(self) -> CreKitValue:
        """Return the little-endian CRE dword represented by ``raw_bytes``."""
        return cre_kit_value_from_bytes(self.raw_bytes)

    @property
    def kit_ids_value(self) -> KitIdsValue | None:
        """Return the corresponding KIT.IDS/KITLIST.KITIDS value."""
        return kit_ids_value_from_cre(self.cre_value)


class CreScripts(IeCliProjection):
    """CRE V1 script resrefs at 0x248-0x268, in file order."""

    override_script: WireResRef | None = None
    class_script: WireResRef | None = None
    race_script: WireResRef | None = None
    general_script: WireResRef | None = None
    default_script: WireResRef | None = None


class CreHeader(IeCliProjection):
    """Voice-relevant CRE V1 header fields, named exactly as ``ie-cli`` emits them."""

    # CRE V1 0x008 is the long name; 0x00C is the short tooltip name.
    long_name: StringReference
    short_name: StringReference
    small_portrait: WireResRef | None = None
    large_portrait: WireResRef | None = None
    reputation: UInt8
    animation_id: AnimationIdField
    class_levels: CreClassLevels
    base_attributes: CreBaseAttributes
    morale: UInt8
    morale_break: UInt8
    morale_recovery_time: UInt16
    racial_enemy: RaceIdField
    kit: CreKit
    scripts: CreScripts
    classification: CreClassification
    soundset: Annotated[list[StringReference], Field(min_length=100, max_length=100)]
    death_variable: str
    dialog: WireResRef | None = None


class CreDump(IeCliProjection):
    """Voice-relevant fields parsed from ``iecli dump`` JSON."""

    resource_name: str = Field(min_length=1)
    resource_type: Literal["CRE"]
    version: Literal["V1.0"]
    header: CreHeader


class DlgTransitionFlags(IeCliProjection):
    """Raw DLG transition flags and ie-cli's human-readable decoding."""

    raw: UInt32
    decoded: list[str]


class DlgTransition(IeCliProjection):
    """One DLG V1 transition, including its conditions, actions, and destination."""

    index: UInt32
    flags: DlgTransitionFlags
    player_text: StringReference | None = None
    journal_text: StringReference | None = None
    trigger_index: UInt32 | None = None
    trigger_text: str | None = None
    action_index: UInt32 | None = None
    action_text: str | None = None
    next_dialog: WireResRef | None = None
    next_state_index: UInt32 | None = None
    terminates_dialog: bool

    @model_validator(mode="after")
    def validate_optional_fields(self) -> Self:
        assert self.trigger_text is None or self.trigger_index is not None, (
            "DLG transition trigger text requires a trigger index"
        )
        assert self.action_text is None or self.action_index is not None, (
            "DLG transition action text requires an action index"
        )
        assert (self.next_state_index is None) == self.terminates_dialog, (
            "DLG transition must terminate exactly when it has no destination state"
        )
        return self


class DlgState(IeCliProjection):
    """One DLG V1 actor-response state and its outgoing player transitions."""

    index: UInt32
    first_transition_index: UInt32
    num_transitions: UInt32
    response_text: StringReference
    trigger_index: UInt32 | None = None
    trigger_text: str | None = None
    transitions: list[DlgTransition]

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        assert self.trigger_text is None or self.trigger_index is not None, (
            "DLG state trigger text requires a trigger index"
        )
        assert len(self.transitions) == self.num_transitions, (
            f"DLG state declares {self.num_transitions} transitions; "
            f"decoded {len(self.transitions)}"
        )
        assert all(
            transition.index == self.first_transition_index + offset
            for offset, transition in enumerate(self.transitions)
        ), "DLG state transitions must be contiguous from first_transition_index"
        return self


class DlgHeader(IeCliProjection):
    """DLG V1 table counts reported by ``ie-cli`` from header offsets 0x008 and 0x010."""

    num_states: UInt32
    num_transitions: UInt32


class DlgDump(IeCliProjection):
    """Voice-relevant fields parsed from ``iecli dump`` DLG JSON."""

    resource_name: str = Field(min_length=1)
    resource_type: Literal["DLG"]
    version: Literal["V1.0"]
    header: DlgHeader
    states: list[DlgState]

    @model_validator(mode="after")
    def validate_header_counts(self) -> Self:
        """Reject a partial or internally inconsistent decoded DLG."""
        assert len(self.states) == self.header.num_states, (
            f"DLG header declares {self.header.num_states} states; decoded {len(self.states)}"
        )
        transition_count = sum(len(state.transitions) for state in self.states)
        assert transition_count == self.header.num_transitions, (
            f"DLG header declares {self.header.num_transitions} transitions; "
            f"decoded {transition_count}"
        )
        return self


class CharacterSound(StrictModel):
    """One populated CRE soundset slot and its resolved dialog.tlk subtitle."""

    slot_id: SoundSlotIdField
    strref: UInt32
    text: str | None

    @staticmethod
    def id_for(character_resource_name: str, slot_id: int) -> str:
        """Return the stable, case-insensitive identity of one CRE sound slot."""
        return f"{character_resource_name.upper()}:{slot_id}"


class CharacterDetail(StrictModel):
    """Normalized, voice-relevant detail from one CRE resource."""

    display_name: str
    short_name: str | None
    short_name_strref: UInt32
    long_name: str | None
    long_name_strref: UInt32
    death_variable: str | None
    dialog_resref: str | None
    gender_id: GenderIdField
    race_id: RaceIdField
    class_id: ClassIdField
    alignment_id: AlignmentIdField
    enemy_ally_id: EnemyAllyIdField
    general_id: GeneralIdField
    specific_id: SpecificIdField
    animation_id: AnimationIdField
    racial_enemy_id: RaceIdField
    class_levels: CreClassLevels
    base_attributes: CreBaseAttributes
    morale: UInt8
    morale_break: UInt8
    morale_recovery_time: UInt16
    reputation: UInt8
    kit_raw_bytes: Annotated[list[UInt8], Field(min_length=4, max_length=4)]
    cre_kit_value: CreKitValueField
    kit_ids_value: KitIdsValueField | None
    override_script: str | None
    class_script: str | None
    race_script: str | None
    general_script: str | None
    default_script: str | None
    small_portrait: str | None
    large_portrait: str | None
    cre_version: str

    @classmethod
    def from_dump(cls, resource: CreResource, dump: CreDump) -> Self:
        """Project validated ie-cli data into the database model."""
        header = dump.header
        short_name = _optional_text(header.short_name.text)
        long_name = _optional_text(header.long_name.text)
        display_name = clean_display_name(short_name or long_name) or resource.resref
        classification = header.classification
        scripts = header.scripts
        return cls(
            display_name=display_name,
            short_name=short_name,
            short_name_strref=header.short_name.strref,
            long_name=long_name,
            long_name_strref=header.long_name.strref,
            death_variable=_optional_text(header.death_variable),
            dialog_resref=_optional_resref(header.dialog),
            gender_id=classification.gender,
            race_id=classification.race,
            class_id=classification.class_id,
            alignment_id=classification.alignment,
            enemy_ally_id=classification.enemy_ally,
            general_id=classification.general,
            specific_id=classification.specific,
            animation_id=header.animation_id,
            racial_enemy_id=header.racial_enemy,
            class_levels=header.class_levels,
            base_attributes=header.base_attributes,
            morale=header.morale,
            morale_break=header.morale_break,
            morale_recovery_time=header.morale_recovery_time,
            reputation=header.reputation,
            kit_raw_bytes=list(header.kit.raw_bytes),
            cre_kit_value=header.kit.cre_value,
            kit_ids_value=header.kit.kit_ids_value,
            override_script=_optional_resref(scripts.override_script),
            class_script=_optional_resref(scripts.class_script),
            race_script=_optional_resref(scripts.race_script),
            general_script=_optional_resref(scripts.general_script),
            default_script=_optional_resref(scripts.default_script),
            small_portrait=_optional_resref(header.small_portrait),
            large_portrait=_optional_resref(header.large_portrait),
            cre_version=dump.version,
        )


class CharacterExtraction(StrictModel):
    """Transient output of extracting one CRE and its normalized child rows."""

    resource_name: str = Field(min_length=1)
    detail: CharacterDetail
    sounds: list[CharacterSound]
    serialized_size: int = Field(ge=0)

    @classmethod
    def from_dump(cls, resource: CreResource, dump: CreDump) -> Self:
        assert resource.resource_name.casefold() == dump.resource_name.casefold(), (
            f"CRE inventory names {resource.resource_name!r}; dump is {dump.resource_name!r}"
        )
        detail = CharacterDetail.from_dump(resource, dump)
        return cls(
            resource_name=resource.resource_name,
            detail=detail,
            sounds=[
                CharacterSound(
                    slot_id=SoundSlotId(slot_id),
                    strref=reference.strref,
                    text=reference.text,
                )
                for slot_id, reference in enumerate(dump.header.soundset)
                if reference.strref != 0xFFFF_FFFF
            ],
            serialized_size=len(dump.model_dump_json().encode("utf-8")),
        )


class VoiceResource(StrictModel):
    """One named speaker with its concrete CREs and addressable NPC dialogue."""

    id: VoiceId
    display_name: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    variant_resource_names: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    dialogue_resrefs: list[Annotated[str, Field(min_length=1, max_length=8)]]

    @property
    def variant_count(self) -> int:
        return len(self.variant_resource_names)

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.id,
            self.display_name,
            self.prompt,
            *self.variant_resource_names,
            *self.dialogue_resrefs,
        )


class IdentifierDefinition(StrictModel):
    """One effective IDS value with every symbol retained in source order."""

    kind: IdentifierKind
    value: UInt32
    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    symbols: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.value}"

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.kind.value,
            str(self.value),
            self.source_resource,
            *self.symbols,
        )


class CampaignDefinition(StrictModel):
    """One row label from the effective CAMPAIGN.2DA resource."""

    campaign_id: str = Field(min_length=1)
    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)

    @property
    def key(self) -> str:
        return self.campaign_id


class CampaignResourceBinding(StrictModel):
    """One campaign-selected effective resource, or an explicit absent binding."""

    campaign_id: str = Field(min_length=1)
    resource_kind: CampaignResourceKind
    resource_resref: ResRef | None

    @property
    def key(self) -> str:
        return f"{self.campaign_id}:{self.resource_kind.value}"


class CharacterResourceLink(StrictModel):
    """A dialogue or script associated with a character death variable by a 2DA row."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    death_variable: str = Field(min_length=1)
    source_column: str = Field(min_length=1)
    role: CharacterResourceRole
    target_type: ResourceTargetType
    target_resref: ResRef

    @property
    def key(self) -> str:
        return f"{self.source_resource}:{self.ordinal}:{self.source_column}"

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.source_resource,
            self.death_variable,
            self.source_column,
            self.role.value,
            self.target_type.value,
            self.target_resref,
        )


class InteractionRule(StrictModel):
    """One non-empty edge from an INTERACT-compatible party interaction matrix."""

    source_resource: str = Field(min_length=1)
    speaker_ordinal: int = Field(ge=0)
    target_ordinal: int = Field(ge=0)
    speaker_death_variable: str = Field(min_length=1)
    target_death_variable: str = Field(min_length=1)
    kind: InteractionKind

    @property
    def key(self) -> str:
        return f"{self.source_resource}:{self.speaker_ordinal}:{self.target_ordinal}"

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.source_resource,
            self.speaker_death_variable,
            self.target_death_variable,
            self.kind.value,
        )


class SoundsetLine(StrictModel):
    """One populated CHARSND soundset/slot cell and its resolved subtitle."""

    source_resource: str = Field(min_length=1)
    soundset_name: str = Field(min_length=1)
    slot_id: SoundSlotIdField
    strref: UInt32
    text: str | None

    @property
    def key(self) -> str:
        return f"{self.source_resource}:{self.soundset_name}:{self.slot_id}"

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.source_resource,
            self.soundset_name,
            str(self.slot_id),
            str(self.strref),
            self.text,
        )


class SoundSlotSuffix(StrictModel):
    """A CSOUND slot-to-audio-filename suffix mapping."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    slot_id: SoundSlotIdField
    file_suffix: str | None

    @property
    def key(self) -> str:
        return f"{self.source_resource}:{self.slot_id}"


class SoundSlotGroup(StrictModel):
    """One named SPEECH.2DA range over the 100 CRE soundset slots."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    row_name: str = Field(min_length=1)
    offset: SoundSlotIdField | None
    count: PositiveInt | None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        assert (self.offset is None) == (self.count is None), (
            "SPEECH offset and count must both be present or absent"
        )
        return self

    @property
    def key(self) -> str:
        return f"{self.source_resource}:{self.ordinal}"

    @property
    def search_text(self) -> str:
        return compose_search_text(self.source_resource, self.row_name)


class FavoredEnemyDefinition(StrictModel):
    """One localized HATERACE.2DA racial-enemy choice."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    row_name: str = Field(min_length=1)
    name_strref: UInt32
    name: str | None
    race_id: RaceIdField
    help_strref: UInt32
    help_text: str | None

    @property
    def key(self) -> str:
        return f"{self.source_resource}:{self.ordinal}"

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.source_resource,
            self.row_name,
            str(self.race_id),
            self.name,
            self.help_text,
        )


class HappinessRule(StrictModel):
    """One HAPPY.2DA cell keyed by party reputation and broad alignment."""

    source_resource: str = Field(min_length=1)
    reputation: Annotated[int, Field(ge=1, le=20)]
    alignment: HappinessAlignment
    happiness: int

    @property
    def key(self) -> str:
        return f"{self.source_resource}:{self.reputation}:{self.alignment.value}"


class BanterTimingSettings(StrictModel):
    """Effective BANTTIMG.2DA controls for party-member banter."""

    source_resource: str = Field(min_length=1)
    frequency: UInt32
    probability: UInt32
    replay_delay: UInt32
    special_probability: UInt32

    @property
    def key(self) -> str:
        return self.source_resource


class EngineString(StrictModel):
    """One named engine string and its resolved dialog.tlk text."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    key: str = Field(min_length=1)
    strref: UInt32 | None
    text: str | None

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.source_resource,
            self.key,
            str(self.strref) if self.strref is not None else None,
            self.text,
        )


class MonthDefinition(StrictModel):
    """One MONTHS.2DA calendar segment and its resolved name."""

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    month_id: UInt32
    days: PositiveInt
    name_strref: UInt32
    name: str | None

    @property
    def key(self) -> str:
        return f"{self.source_resource}:{self.month_id}"

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.source_resource,
            str(self.month_id),
            self.name,
        )


class CampaignCalendarDefinition(StrictModel):
    """One campaign year resource with resolved normal and special date formats."""

    source_resource: str = Field(min_length=1)
    start_time: UInt32
    start_year: UInt32
    normal_format_strref: UInt32
    normal_format: str | None
    special_format_strref: UInt32
    special_format: str | None

    @property
    def key(self) -> str:
        return self.source_resource

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.source_resource,
            str(self.start_year),
            self.normal_format,
            self.special_format,
        )


class RaceTextRow(StrictModel):
    """A RACETEXT-compatible row with resolved dialog.tlk text.

    See https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/racetext.htm.
    """

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    row_name: str = Field(min_length=1)
    race_id: RaceIdField
    name_strref: UInt32 | None
    name: str | None
    description_strref: UInt32 | None
    description: str | None
    uppercase_name_strref: UInt32 | None
    uppercase_name: str | None
    biography_strref: UInt32 | None
    biography: str | None

    @property
    def key(self) -> str:
        return f"{self.source_resource}:{self.ordinal}"

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.source_resource,
            self.row_name,
            str(self.race_id),
            self.name,
            self.description,
            self.uppercase_name,
            self.biography,
        )


class ClassTextRow(StrictModel):
    """A CLASTEXT-compatible row with resolved dialog.tlk text.

    See https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/clastext.htm.
    """

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    row_name: str = Field(min_length=1)
    class_id: ClassIdField
    class_text_kit_id: ClassTextKitIdField
    lower_name_strref: UInt32 | None
    lower_name: str | None
    description_strref: UInt32 | None
    description: str | None
    mixed_name_strref: UInt32 | None
    mixed_name: str | None
    biography_strref: UInt32 | None
    biography: str | None
    fallen: bool
    brief_description_strref: UInt32 | None
    brief_description: str | None
    fallen_notice_strref: UInt32 | None
    fallen_notice: str | None

    @property
    def key(self) -> str:
        return f"{self.source_resource}:{self.ordinal}"

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.source_resource,
            self.row_name,
            str(self.class_id),
            str(self.class_text_kit_id),
            self.lower_name,
            self.description,
            self.mixed_name,
            self.biography,
            self.brief_description,
            self.fallen_notice,
        )


class KitDefinition(StrictModel):
    """One KITLIST.2DA row with resolved name and help strings.

    See https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/kitlist.htm.
    """

    source_resource: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    row_id: KitListRowIdField
    row_name: str = Field(min_length=1)
    lower_name_strref: UInt32 | None
    lower_name: str | None
    mixed_name_strref: UInt32 | None
    mixed_name: str | None
    help_strref: UInt32 | None
    help_text: str | None
    abilities: ResRef | None
    proficiency: int | None = Field(default=None, ge=0)
    unusable: UInt32 | None
    class_id: ClassIdField | None
    kit_ids_value: KitIdsValueField | None
    class_text_kit_id: ClassTextKitIdField | None

    @property
    def key(self) -> str:
        return f"{self.source_resource}:{self.row_id}"

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.source_resource,
            self.row_name,
            str(self.row_id),
            self.lower_name,
            self.mixed_name,
            self.help_text,
            self.abilities,
            str(self.class_id) if self.class_id is not None else None,
            str(self.kit_ids_value) if self.kit_ids_value is not None else None,
        )


class MetadataExtraction(StrictModel):
    """Normalized definitions extracted from effective IDS, 2DA, and TLK resources."""

    source_resource_count: int = Field(ge=0)
    resolved_strref_count: int = Field(ge=0)
    identifiers: list[IdentifierDefinition]
    campaigns: list[CampaignDefinition]
    campaign_resource_bindings: list[CampaignResourceBinding]
    character_resource_links: list[CharacterResourceLink]
    interaction_rules: list[InteractionRule]
    soundset_lines: list[SoundsetLine]
    sound_slot_suffixes: list[SoundSlotSuffix]
    sound_slot_groups: list[SoundSlotGroup]
    favored_enemies: list[FavoredEnemyDefinition]
    happiness_rules: list[HappinessRule]
    banter_timing: BanterTimingSettings
    engine_strings: list[EngineString]
    months: list[MonthDefinition]
    campaign_calendars: list[CampaignCalendarDefinition]
    race_text_rows: list[RaceTextRow]
    class_text_rows: list[ClassTextRow]
    kits: list[KitDefinition]


class DialogueDetail(StrictModel):
    """Normalized, sortable metrics for one DLG resource."""

    dlg_version: str
    state_count: UInt32
    transition_count: UInt32
    npc_line_count: int = Field(ge=0)
    player_line_count: int = Field(ge=0)
    journal_line_count: int = Field(ge=0)
    dialogue_line_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        assert self.npc_line_count == self.state_count, (
            "DLG state count must equal its NPC line count"
        )
        assert self.dialogue_line_count == self.npc_line_count + self.player_line_count, (
            "DLG spoken line count must equal NPC plus player lines"
        )
        return self

    @classmethod
    def from_dump(cls, dump: DlgDump) -> Self:
        """Count spoken and journal text while retaining header consistency."""
        player_lines = sum(
            transition.player_text is not None
            for state in dump.states
            for transition in state.transitions
        )
        journal_lines = sum(
            transition.journal_text is not None
            for state in dump.states
            for transition in state.transitions
        )
        npc_lines = len(dump.states)
        return cls(
            dlg_version=dump.version,
            state_count=dump.header.num_states,
            transition_count=dump.header.num_transitions,
            npc_line_count=npc_lines,
            player_line_count=player_lines,
            journal_line_count=journal_lines,
            dialogue_line_count=npc_lines + player_lines,
        )


class DialogueLine(StrictModel):
    """One actor, player, or journal strref extracted from a validated DLG."""

    dialogue_resource_name: str
    line_kind: DialogueLineKind
    state_index: UInt32
    state_trigger_index: UInt32 | None
    state_trigger_text: str | None
    transition_index: UInt32 | None = None
    strref: UInt32
    text: str | None
    tokens: list[DialogueToken]

    @model_validator(mode="after")
    def validate_state_trigger(self) -> Self:
        assert self.state_trigger_text is None or self.state_trigger_index is not None, (
            "DLG line state trigger text requires a trigger index"
        )
        assert self.line_kind is DialogueLineKind.NPC or self.state_trigger_index is None, (
            "only NPC state rows carry DLG state triggers"
        )
        return self

    @staticmethod
    def id_for(
        dialogue_resource_name: str,
        line_kind: DialogueLineKind,
        state_index: int,
        transition_index: int | None,
    ) -> str:
        transition = "-" if transition_index is None else str(transition_index)
        return f"{dialogue_resource_name.upper()}:{line_kind.value}:{state_index}:{transition}"

    @property
    def id(self) -> str:
        return self.id_for(
            self.dialogue_resource_name,
            self.line_kind,
            self.state_index,
            self.transition_index,
        )

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.dialogue_resource_name,
            self.text,
            self.state_trigger_text,
            *self.tokens,
        )

    @classmethod
    def from_dump(cls, dump: DlgDump) -> list[Self]:
        """Flatten DLG states and transitions into stable line-level records."""
        lines: list[Self] = []
        for state in dump.states:
            lines.append(
                cls(
                    dialogue_resource_name=dump.resource_name,
                    line_kind=DialogueLineKind.NPC,
                    state_index=state.index,
                    state_trigger_index=state.trigger_index,
                    state_trigger_text=state.trigger_text,
                    transition_index=None,
                    strref=state.response_text.strref,
                    text=state.response_text.text,
                    tokens=dialogue_tokens(state.response_text.text),
                )
            )
            for transition in state.transitions:
                for kind, reference in (
                    (DialogueLineKind.PLAYER, transition.player_text),
                    (DialogueLineKind.JOURNAL, transition.journal_text),
                ):
                    if reference is not None:
                        lines.append(
                            cls(
                                dialogue_resource_name=dump.resource_name,
                                line_kind=kind,
                                state_index=state.index,
                                state_trigger_index=None,
                                state_trigger_text=None,
                                transition_index=transition.index,
                                strref=reference.strref,
                                text=reference.text,
                                tokens=dialogue_tokens(reference.text),
                            )
                        )
        return lines


class DialogueTransitionEdge(StrictModel):
    """One flattened, addressable edge in a DLG state machine."""

    dialogue_resource_name: str = Field(min_length=1)
    state_index: UInt32
    transition_index: UInt32
    flags_raw: UInt32
    flags_decoded: list[str]
    trigger_index: UInt32 | None
    trigger_text: str | None
    action_index: UInt32 | None
    action_text: str | None
    next_dialog: ResRef | None
    next_state_index: UInt32 | None
    terminates_dialog: bool

    @model_validator(mode="after")
    def validate_optional_fields(self) -> Self:
        assert self.trigger_text is None or self.trigger_index is not None, (
            "DLG transition trigger text requires a trigger index"
        )
        assert self.action_text is None or self.action_index is not None, (
            "DLG transition action text requires an action index"
        )
        assert (self.next_state_index is None) == self.terminates_dialog, (
            "DLG transition must terminate exactly when it has no destination state"
        )
        return self

    @staticmethod
    def id_for(
        dialogue_resource_name: str,
        state_index: int,
        transition_index: int,
    ) -> str:
        return f"{dialogue_resource_name.upper()}:{state_index}:{transition_index}"

    @property
    def id(self) -> str:
        return self.id_for(
            self.dialogue_resource_name,
            self.state_index,
            self.transition_index,
        )

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.dialogue_resource_name,
            self.trigger_text,
            self.action_text,
            self.next_dialog,
            *self.flags_decoded,
        )

    @classmethod
    def from_dump(cls, dump: DlgDump) -> list[Self]:
        """Flatten transition topology without discarding conditions or actions."""
        return [
            cls(
                dialogue_resource_name=dump.resource_name,
                state_index=state.index,
                transition_index=transition.index,
                flags_raw=transition.flags.raw,
                flags_decoded=transition.flags.decoded,
                trigger_index=transition.trigger_index,
                trigger_text=transition.trigger_text,
                action_index=transition.action_index,
                action_text=transition.action_text,
                next_dialog=_optional_resref(transition.next_dialog),
                next_state_index=transition.next_state_index,
                terminates_dialog=transition.terminates_dialog,
            )
            for state in dump.states
            for transition in state.transitions
        ]


class DialogueExtraction(StrictModel):
    """One DLG's aggregate metrics and addressable line records."""

    resource_name: str = Field(min_length=1)
    detail: DialogueDetail
    lines: list[DialogueLine]
    edges: list[DialogueTransitionEdge]
    serialized_size: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_line_resources(self) -> Self:
        unexpected = sorted(
            {
                line.dialogue_resource_name
                for line in self.lines
                if line.dialogue_resource_name.casefold() != self.resource_name.casefold()
            }
        )
        assert not unexpected, (
            f"DLG extraction {self.resource_name!r} contains lines for {unexpected}"
        )
        counts = Counter(line.line_kind for line in self.lines)
        expected: dict[DialogueLineKind, int] = {
            DialogueLineKind.NPC: self.detail.npc_line_count,
            DialogueLineKind.PLAYER: self.detail.player_line_count,
            DialogueLineKind.JOURNAL: self.detail.journal_line_count,
        }
        assert all(counts[kind] == count for kind, count in expected.items()), (
            f"DLG extraction {self.resource_name!r} line counts are "
            f"{dict(counts)}; expected {expected}"
        )
        assert len(self.edges) == self.detail.transition_count, (
            f"DLG extraction {self.resource_name!r} contains {len(self.edges)} edges; "
            f"expected {self.detail.transition_count}"
        )
        unexpected_edges = sorted(
            {
                edge.dialogue_resource_name
                for edge in self.edges
                if edge.dialogue_resource_name.casefold() != self.resource_name.casefold()
            }
        )
        assert not unexpected_edges, (
            f"DLG extraction {self.resource_name!r} contains edges for {unexpected_edges}"
        )
        return self

    @classmethod
    def from_dump(cls, dump: DlgDump) -> Self:
        return cls(
            resource_name=dump.resource_name,
            detail=DialogueDetail.from_dump(dump),
            lines=DialogueLine.from_dump(dump),
            edges=DialogueTransitionEdge.from_dump(dump),
            serialized_size=len(dump.model_dump_json().encode("utf-8")),
        )


class ExtractionProgress(StrictModel):
    """Progress event emitted while resource details are extracted."""

    completed: int = Field(ge=0)
    total: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)


class ExtractionSummary(StrictModel):
    """Machine-readable terminal result of one extraction run."""

    run_id: str = Field(min_length=1)
    game_root: Path
    database_path: Path
    iecli_version: str
    discovered: int = Field(ge=0)
    attempted: int = Field(ge=0)
    extracted: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    status: TerminalRunStatus


class DatabaseStats(StrictModel):
    """Counts describing the active character inventory."""

    total: int = Field(ge=0)
    complete: int = Field(ge=0)
    failed: int = Field(ge=0)
    pending: int = Field(ge=0)
    with_dialog: int = Field(ge=0)


class AttributionSummary(StrictModel):
    """Complete accounting of active characters and extracted DLG resources."""

    run_id: str = Field(min_length=1)
    characters_total: int = Field(ge=0)
    characters_unavailable: int = Field(ge=0)
    characters_matched: int = Field(ge=0)
    characters_partially_matched: int = Field(ge=0)
    characters_missing_dialogue: int = Field(ge=0)
    characters_dialogue_failed: int = Field(ge=0)
    characters_without_dialogue: int = Field(ge=0)
    dialogues_total: int = Field(ge=0)
    dialogues_attributed: int = Field(ge=0)
    dialogues_unattributed: int = Field(ge=0)
    attributed_dialogue_lines: int = Field(ge=0)
    unattributed_dialogue_lines: int = Field(ge=0)


def clean_display_name(value: str | None) -> str | None:
    """Remove Enhanced Edition color tags while preserving the original text elsewhere."""
    if value is None:
        return None
    cleaned = _EE_COLOR_TAG.sub("", value).strip()
    return cleaned or None


def dialogue_tokens(text: str | None) -> list[str]:
    """Return runtime token names in occurrence order from resolved dialogue text."""
    return [match.group(1) for match in _DIALOGUE_TOKEN.finditer(text or "")]


def cre_kit_value_from_bytes(raw_bytes: Sequence[int]) -> CreKitValue:
    """Decode the four raw CRE kit bytes as the little-endian dword at offset 0x244.

    See https://gibberlings3.github.io/iesdp/file_formats/ie_formats/cre_v1.htm#CREV1_0_Header_0x244.
    """
    assert len(raw_bytes) == 4, "CRE kit data must contain exactly four bytes"
    assert all(0 <= value <= 0xFF for value in raw_bytes), (
        "CRE kit data must contain unsigned bytes"
    )
    return CreKitValue(int.from_bytes(bytes(raw_bytes), byteorder="little"))


def kit_ids_value_from_cre(cre_value: int) -> KitIdsValue | None:
    """Convert a raw CRE kit dword to the corresponding KIT.IDS value.

    The engine representation swaps the two 16-bit halves relative to KIT.IDS and
    KITLIST.KITIDS. Applying this operation again performs the inverse conversion.
    """
    assert 0 <= cre_value <= 0xFFFF_FFFF, "CRE kit value must be an unsigned 32-bit integer"
    normalized = ((cre_value & 0xFFFF) << 16) | (cre_value >> 16)
    return KitIdsValue(normalized) if normalized else None


def class_text_kit_id_from_kit_ids(kit_ids_value: int) -> ClassTextKitId:
    """Derive CLASTEXT.KITID from a non-reserve KITLIST.KITIDS value."""
    assert 0 <= kit_ids_value <= 0xFFFF_FFFF, "KIT.IDS value must be an unsigned 32-bit integer"
    value = kit_ids_value & 0x3FFF if kit_ids_value & 0x4000 else kit_ids_value
    return ClassTextKitId(value)


def utc_now() -> datetime:
    """Return an aware UTC timestamp for persisted extraction metadata."""
    return datetime.now(UTC)


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _optional_resref(value: str | None) -> str | None:
    stripped = _optional_text(value)
    if stripped is None or stripped.upper() == "NONE":
        return None
    return stripped
