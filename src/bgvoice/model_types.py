"""Shared validated types for Infinity Engine resources and pipeline state."""

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from io import BytesIO
from typing import Annotated, Literal, NewType, Self

from PIL import Image
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
    PORTRAITS = "portraits"
    READABLE_ITEMS = "readable_items"
    METADATA = "metadata"
    ATTRIBUTION = "attribution"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETE = "complete"
    COMPLETE_WITH_ERRORS = "complete_with_errors"
    FAILED = "failed"


class GenerationFailureStage(StrEnum):
    """Generation unit that most recently failed to produce its durable output."""

    VOICE_CREATION = "voice_creation"
    DIALOGUE_DIRECTION = "dialogue_direction"
    AUDIO_GENERATION = "audio_generation"


type TerminalRunStatus = Literal[
    RunStatus.COMPLETE,
    RunStatus.COMPLETE_WITH_ERRORS,
    RunStatus.FAILED,
]


class SourceKind(StrEnum):
    OVERRIDE = "override"
    BIF = "bif"
    DLC = "dlc"


class ReadableItemKind(StrEnum):
    """Readable inventory-item presentation used by the game UI."""

    BOOK = "book"
    SCROLL = "scroll"


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

BIOGRAPHY_SOUND_SLOT_ID = SoundSlotId(74)

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


class PortraitResource(IeCliProjection):
    """One effective BMP resource returned by ``iecli list``."""

    resource_name: str = Field(min_length=1)
    resref: ResRef
    source_kind: SourceKind = Field(strict=False)
    source_path: str = Field(min_length=1)
    resource_type: Literal["BMP"] = Field(alias="type")


class ItmResource(IeCliProjection):
    """One effective ITM resource returned by ``iecli list``."""

    resource_name: str = Field(min_length=1)
    resref: ResRef
    source_kind: SourceKind = Field(strict=False)
    source_path: str = Field(min_length=1)
    resource_type: Literal["ITM"] = Field(alias="type")


class ResourceSource(StrictModel):
    """Physical origin of one effective Infinity Engine resource."""

    kind: SourceKind = Field(strict=False)
    path: str = Field(min_length=1)

    @classmethod
    def from_resource(
        cls,
        resource: CreResource | DlgResource | PortraitResource | ItmResource,
    ) -> Self:
        return cls(kind=resource.source_kind, path=resource.source_path)


class PortraitImage(StrictModel):
    """One canonical portrait encoded as browser-ready PNG bytes."""

    resref: ResRef
    source: ResourceSource
    width: PositiveInt
    height: PositiveInt
    png: Annotated[bytes, Field(min_length=1)]

    @classmethod
    def from_bmp(cls, resource: PortraitResource, bmp: bytes) -> Self:
        """Convert one effective Infinity Engine BMP portrait to optimized RGB PNG."""
        with Image.open(BytesIO(bmp)) as source:
            width, height = source.size
            image = source.convert("RGB")
        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        return cls(
            resref=resource.resref.upper(),
            source=ResourceSource.from_resource(resource),
            width=width,
            height=height,
            png=output.getvalue(),
        )


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


def optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def optional_resref(value: str | None) -> str | None:
    stripped = optional_text(value)
    if stripped is None or stripped.upper() == "NONE":
        return None
    return stripped
