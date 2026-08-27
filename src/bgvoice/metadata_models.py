"""Typed normalized IDS and 2DA metadata models."""

from typing import Annotated, Self

from pydantic import Field, PositiveInt, model_validator

from bgvoice.model_types import (
    CampaignResourceKind,
    CharacterResourceRole,
    ClassIdField,
    ClassTextKitIdField,
    HappinessAlignment,
    IdentifierKind,
    InteractionKind,
    KitIdsValueField,
    KitListRowIdField,
    RaceIdField,
    ResourceTargetType,
    ResRef,
    SoundSlotIdField,
    StrictModel,
    UInt32,
    compose_search_text,
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
