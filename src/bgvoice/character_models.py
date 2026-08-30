"""Validated CRE projections and canonical character models."""

from typing import Annotated, Literal, Self

from pydantic import Field

from bgvoice.model_types import (
    AlignmentIdField,
    AnimationIdField,
    ClassIdField,
    CreKitValue,
    CreKitValueField,
    CreResource,
    EnemyAllyIdField,
    ExceptionalStrength,
    GenderIdField,
    GeneralIdField,
    IeCliProjection,
    KitIdsValue,
    KitIdsValueField,
    RaceIdField,
    SoundSlotId,
    SoundSlotIdField,
    SpecificIdField,
    StrictModel,
    StringReference,
    UInt8,
    UInt16,
    UInt32,
    WireResRef,
    clean_display_name,
    cre_kit_value_from_bytes,
    kit_ids_value_from_cre,
    optional_resref,
    optional_text,
)


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
        short_name = optional_text(header.short_name.text)
        long_name = optional_text(header.long_name.text)
        display_name = clean_display_name(short_name or long_name) or resource.resref
        classification = header.classification
        scripts = header.scripts
        return cls(
            display_name=display_name,
            short_name=short_name,
            short_name_strref=header.short_name.strref,
            long_name=long_name,
            long_name_strref=header.long_name.strref,
            death_variable=optional_text(header.death_variable),
            dialog_resref=optional_resref(header.dialog),
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
            override_script=optional_resref(scripts.override_script),
            class_script=optional_resref(scripts.class_script),
            race_script=optional_resref(scripts.race_script),
            general_script=optional_resref(scripts.general_script),
            default_script=optional_resref(scripts.default_script),
            small_portrait=optional_resref(header.small_portrait),
            large_portrait=optional_resref(header.large_portrait),
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
