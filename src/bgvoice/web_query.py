"""Connect List parsing, pagination, and resource lookup."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, cast

from connectrpc.code import Code
from connectrpc.errors import ConnectError
from lancedb.expr import col, lit
from lancedb.pydantic import LanceModel
from lancedb.table import AsyncTable
from pydantic import TypeAdapter, ValidationError

from bgvoice.reader_models import (
    CharacterSort,
    ClassSort,
    DialogueSort,
    IdentifierSort,
    KitSort,
    LineSort,
    RaceSort,
    SortDirection,
    SoundSort,
    TransitionSort,
    VoiceSort,
)
from bgvoice.v1 import pipeline_pb2 as pb
from bgvoice.web_contract import (
    INSTALLATION_ID,
    Collection,
    ResourceView,
    encode_page_token,
    resource_name,
)

INSTALLATION_NAME: Final = f"installations/{INSTALLATION_ID}"
DEFAULT_PAGE_SIZE: Final = 25
READER_PAGE_SIZE: Final = 100
MAX_PAGE_SIZE: Final = 100

_TEXT = TypeAdapter(str)
_INTEGER = TypeAdapter(int)
_BOOLEAN = TypeAdapter(bool)

VOICE_ORDER: Final[dict[str, VoiceSort]] = {
    "display_name": "display_name",
    "character_count": "variant_count",
    "dialogue_count": "dialogue_count",
    "npc_line_count": "npc_line_count",
    "serialized_size": "serialized_size",
}
CHARACTER_ORDER: Final[dict[str, CharacterSort]] = {
    "display_name": "display_name",
    "engine_resource_name": "resource_name",
    "source_kind": "source_kind",
    "npc_line_count": "npc_line_count",
    "player_line_count": "player_line_count",
    "state_count": "dialogue_state_count",
    "transition_count": "dialogue_transition_count",
    "serialized_size": "serialized_size",
}
DIALOGUE_ORDER: Final[dict[str, DialogueSort]] = {
    "engine_resource_name": "resource_name",
    "source_kind": "source_kind",
    "dialogue_line_count": "dialogue_line_count",
    "npc_line_count": "npc_line_count",
    "player_line_count": "player_line_count",
    "character_count": "character_count",
    "serialized_size": "serialized_size",
}
LINE_ORDER: Final[dict[str, LineSort]] = {
    "dialogue": "dialogue_resource_name",
    "line_kind": "line_kind",
    "strref": "strref",
    "state_index": "state_index",
    "transition_index": "transition_index",
    "serialized_size": "serialized_size",
}
SOUND_ORDER: Final[dict[str, SoundSort]] = {
    "character": "character_resource_name",
    "slot_id": "slot_id",
    "strref": "strref",
    "serialized_size": "serialized_size",
}
TRANSITION_ORDER: Final[dict[str, TransitionSort]] = {
    "location": "location",
    "dialogue": "dialogue_resource_name",
    "state_index": "state_index",
    "transition_index": "transition_index",
    "serialized_size": "serialized_size",
}
RACE_ORDER: Final[dict[str, RaceSort]] = {
    "race_id": "race_id",
    "display_name": "name",
    "source_resource": "source_resource",
}
CLASS_ORDER: Final[dict[str, ClassSort]] = {
    "class_id": "class_id",
    "display_name": "lower_name",
    "fallen": "fallen",
}
KIT_ORDER: Final[dict[str, KitSort]] = {
    "row_id": "row_id",
    "display_name": "lower_name",
    "character_class": "class_id",
}
IDENTIFIER_ORDER: Final[dict[str, IdentifierSort]] = {
    "kind": "kind",
    "value": "value",
    "source_resource": "source_resource",
}


class ReaderPage[T](Protocol):
    items: list[T]
    total: int


@dataclass(frozen=True, slots=True)
class ListPage:
    size: int
    offset: int
    view: ResourceView


@dataclass(slots=True)
class Filter:
    search: str | None
    clauses: dict[str, str]

    @classmethod
    def parse(cls, raw: str) -> Filter:
        search: str | None = None
        clauses: dict[str, str] = {}
        expressions = raw.strip().split(" AND ") if raw.strip() else []
        assert all(expressions), "filter contains an empty expression"
        for expression in expressions:
            if expression.startswith("search(") and expression.endswith(")"):
                assert search is None, "filter contains more than one search expression"
                search = _json_value(_TEXT, expression[7:-1], "search")
                continue
            field_name, separator, value = expression.partition(" = ")
            assert separator, f"unsupported filter expression: {expression!r}"
            assert field_name and field_name not in clauses, (
                f"filter field {field_name!r} appears more than once"
            )
            clauses[field_name] = value
        return cls(search=search, clauses=clauses)

    def text(self, name: str) -> str | None:
        return self._value(name, _TEXT)

    def integer(self, name: str) -> int | None:
        return self._value(name, _INTEGER)

    def boolean(self, name: str) -> bool | None:
        return self._value(name, _BOOLEAN)

    def enum[E: StrEnum](self, name: str, enum_type: type[E]) -> E | None:
        value = self.text(name)
        if value is None:
            return None
        try:
            return enum_type(value)
        except ValueError as error:
            raise AssertionError(f"invalid {name}: {value!r}") from error

    def finish(self) -> None:
        assert not self.clauses, f"unsupported filter fields: {', '.join(self.clauses)}"

    def _value[T](self, name: str, adapter: TypeAdapter[T]) -> T | None:
        if name not in self.clauses:
            return None
        return _json_value(adapter, self.clauses.pop(name), name)


def _json_value[T](adapter: TypeAdapter[T], raw: str, field_name: str) -> T:
    try:
        return adapter.validate_json(raw, strict=True)
    except ValidationError as error:
        raise AssertionError(f"invalid {field_name}: {raw!r}") from error


def parse_order[T: str](
    raw: str,
    aliases: Mapping[str, T],
) -> tuple[T | None, SortDirection]:
    if not raw.strip():
        return None, "desc"
    parts = raw.split()
    assert len(parts) <= 2, "order_by accepts one field and an optional direction"
    field_name = parts[0]
    assert field_name in aliases, f"unsupported order_by field: {field_name!r}"
    direction: SortDirection = "asc"
    if len(parts) == 2:
        assert parts[1] in {"asc", "desc"}, f"invalid order_by direction: {parts[1]!r}"
        direction = parts[1]
    return aliases[field_name], direction


def parse_view(value: pb.View, *, default: ResourceView) -> ResourceView:
    if value == pb.VIEW_UNSPECIFIED:
        return default
    if value == pb.VIEW_BASIC:
        return ResourceView.BASIC
    if value == pb.VIEW_FULL:
        return ResourceView.FULL
    raise AssertionError(f"unknown view: {value}")


def validate_parent(parent: str) -> None:
    assert parent == INSTALLATION_NAME, f"parent must be {INSTALLATION_NAME!r}"


async def read_window[T](
    offset: int,
    size: int,
    load: Callable[[int], Awaitable[ReaderPage[T]]],
) -> tuple[list[T], int]:
    page_number = offset // READER_PAGE_SIZE + 1
    within_page = offset % READER_PAGE_SIZE
    first = await load(page_number)
    items = first.items[within_page : within_page + size]
    if len(items) < size and offset + len(items) < first.total:
        second = await load(page_number + 1)
        items.extend(second.items[: size - len(items)])
    return items, first.total


async def resource_key[Key: (str, int)](
    table: AsyncTable,
    column: str,
    collection: Collection,
    name: str,
) -> Key:
    """Resolve an opaque canonical name while reading only one scalar column once."""
    values = cast(
        list[Key],
        (await table.query().select([column]).to_arrow()).column(column).to_pylist(),
    )
    matches = {value for value in values if resource_name(collection, str(value)) == name}
    if not matches:
        raise ConnectError(Code.NOT_FOUND, f"resource not found: {name}")
    assert len(matches) == 1, f"canonical resource name {name!r} is ambiguous"
    return matches.pop()


async def record_by_key[Record: LanceModel, Key: (str, int)](
    table: AsyncTable,
    model: type[Record],
    column: str,
    key: Key,
) -> Record:
    rows = cast(
        list[Record],
        await table.query().where(col(column) == lit(key)).limit(2).to_pydantic(model),
    )
    assert len(rows) == 1, f"expected one {model.__name__} for {column}={key!r}"
    return rows[0]


async def resource_record[Record: LanceModel, Key: (str, int)](
    table: AsyncTable,
    model: type[Record],
    column: str,
    collection: Collection,
    name: str,
) -> Record:
    key = await resource_key(table, column, collection, name)
    return await record_by_key(table, model, column, key)


async def all_rows[T](
    load: Callable[[int], Awaitable[ReaderPage[T]]],
) -> list[T]:
    rows: list[T] = []
    page_number = 1
    while True:
        page = await load(page_number)
        rows.extend(page.items)
        if page_number * READER_PAGE_SIZE >= page.total:
            return rows
        page_number += 1


def next_token(
    collection: Collection,
    request_filter: str,
    order_by: str,
    page: ListPage,
    returned: int,
    total: int,
) -> str:
    next_offset = page.offset + returned
    if returned == 0 or next_offset >= total:
        return ""
    return encode_page_token(
        collection,
        filter=request_filter,
        order_by=order_by,
        view=page.view,
        page_size=page.size,
        offset=next_offset,
    )
