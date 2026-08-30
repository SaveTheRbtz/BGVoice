"""Typed ITM projections and normalized readable item text."""

from typing import Literal, Self

from pydantic import Field, model_validator

from bgvoice.model_types import (
    IeCliProjection,
    ItmResource,
    ReadableItemKind,
    ResourceSource,
    StrictModel,
    StringReference,
    UInt16,
    WireResRef,
    compose_search_text,
    optional_text,
)

_BOOK_ITEM_TYPE = 37
_SCROLL_ITEM_TYPE = 11
_BOOK_GROUND_ICON = "GBOOK01"
_SCROLL_GROUND_ICON = "GSCRL01"


class ItmCategory(IeCliProjection):
    """Raw ITM item type and ie-cli's optional decoded label."""

    raw: UInt16
    decoded: str | None = None


class ItmHeader(IeCliProjection):
    """Text and presentation fields used to recognize readable items."""

    category: ItmCategory
    ground_icon: WireResRef | None = None
    icon: WireResRef | None = None
    description_image: WireResRef | None = None
    general_name: StringReference
    identified_name: StringReference
    general_description: StringReference
    identified_description: StringReference


class ItmDump(IeCliProjection):
    """Readable-item fields parsed from ``iecli dump`` ITM JSON."""

    resource_name: str = Field(min_length=1)
    resource_type: Literal["ITM"]
    version: str = Field(min_length=1)
    header: ItmHeader


class ReadableItem(StrictModel):
    """One effective book or scroll with all source name and description text."""

    resource_name: str = Field(min_length=1)
    resref: str = Field(min_length=1, max_length=8)
    source: ResourceSource
    kind: ReadableItemKind = Field(strict=False)
    item_type: UInt16
    ground_icon: str | None
    icon: str | None
    description_image: str | None
    general_name_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    general_name: str | None
    identified_name_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    identified_name: str | None
    general_description_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    general_description: str | None
    identified_description_strref: int = Field(ge=0, le=0xFFFF_FFFF)
    identified_description: str | None
    item_version: str = Field(min_length=1)
    serialized_size: int = Field(ge=0)

    @property
    def display_title(self) -> str:
        return (
            optional_text(self.identified_name) or optional_text(self.general_name) or self.resref
        )

    @property
    def title_strref(self) -> int:
        return (
            self.identified_name_strref
            if optional_text(self.identified_name)
            else self.general_name_strref
        )

    @property
    def text(self) -> str:
        text = optional_text(self.identified_description) or optional_text(self.general_description)
        assert text is not None, "readable items require non-empty description text"
        return text

    @property
    def text_strref(self) -> int:
        return (
            self.identified_description_strref
            if optional_text(self.identified_description)
            else self.general_description_strref
        )

    @property
    def text_length(self) -> int:
        return len(self.text)

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.resource_name,
            self.resref,
            self.source.path,
            self.kind,
            self.general_name,
            self.identified_name,
            self.general_description,
            self.identified_description,
        )

    @model_validator(mode="after")
    def validate_text(self) -> Self:
        assert self.text, "readable items require non-empty description text"
        return self

    @classmethod
    def from_dump(cls, resource: ItmResource, dump: ItmDump) -> Self | None:
        """Return a normalized readable item, or ``None`` for unrelated ITMs."""
        assert resource.resource_name.casefold() == dump.resource_name.casefold(), (
            f"ITM inventory names {resource.resource_name!r}; dump is {dump.resource_name!r}"
        )
        kind = _readable_kind(dump.header)
        descriptions = (
            dump.header.identified_description.text,
            dump.header.general_description.text,
        )
        if kind is None or not any(optional_text(text) for text in descriptions):
            return None
        header = dump.header
        return cls(
            resource_name=resource.resource_name,
            resref=resource.resref,
            source=ResourceSource.from_resource(resource),
            kind=kind,
            item_type=header.category.raw,
            ground_icon=header.ground_icon,
            icon=header.icon,
            description_image=header.description_image,
            general_name_strref=header.general_name.strref,
            general_name=header.general_name.text,
            identified_name_strref=header.identified_name.strref,
            identified_name=header.identified_name.text,
            general_description_strref=header.general_description.strref,
            general_description=header.general_description.text,
            identified_description_strref=header.identified_description.strref,
            identified_description=header.identified_description.text,
            item_version=dump.version,
            serialized_size=len(dump.model_dump_json().encode("utf-8")),
        )


def _readable_kind(header: ItmHeader) -> ReadableItemKind | None:
    ground_icon = (header.ground_icon or "").upper()
    if ground_icon == _BOOK_GROUND_ICON:
        return ReadableItemKind.BOOK
    if ground_icon == _SCROLL_GROUND_ICON:
        return ReadableItemKind.SCROLL
    if header.category.raw == _BOOK_ITEM_TYPE:
        return ReadableItemKind.BOOK
    if header.category.raw == _SCROLL_ITEM_TYPE:
        return ReadableItemKind.SCROLL
    return None
