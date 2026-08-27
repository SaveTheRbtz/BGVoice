"""Resource-oriented Connect service over the typed pipeline reader."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import wraps
from typing import TYPE_CHECKING, Final, Protocol, cast

from connectrpc.code import Code
from connectrpc.errors import ConnectError
from lancedb.expr import col, lit
from lancedb.pydantic import LanceModel
from lancedb.table import AsyncTable
from pydantic import ConfigDict, TypeAdapter, ValidationError

from bgvoice import reader as reader_models
from bgvoice.database import (
    CampaignDefinitionRecord,
    CharacterAttributionRecord,
    CharacterRecord,
    CharacterSoundRecord,
    DialogueLineRecord,
    DialogueRecord,
    DialogueTransitionRecord,
    ExtractionRunRecord,
    IdentifierDefinitionRecord,
    KitDefinitionRecord,
    PortraitImageRecord,
    SoundSlotGroupRecord,
)
from bgvoice.models import (
    BIOGRAPHY_SOUND_SLOT_ID,
    AttributionPublicationStatus,
    AttributionStatus,
    DetailStatus,
    DialogueLineKind,
    IdentifierKind,
    ResourceSource,
    RunKind,
    RunStatus,
    SourceKind,
)
from bgvoice.reader import (
    CharacterQuery,
    CharacterRow,
    CharacterSort,
    ClassQuery,
    ClassRow,
    ClassSort,
    DialogueLineRow,
    DialogueQuery,
    DialogueRow,
    DialogueSort,
    IdentifierQuery,
    IdentifierRow,
    IdentifierSort,
    KitQuery,
    KitRow,
    KitSort,
    LineQuery,
    LineSort,
    PipelineReader,
    RaceQuery,
    RaceRow,
    RaceSort,
    SortDirection,
    SoundQuery,
    SoundRow,
    SoundSort,
    TransitionQuery,
    TransitionRow,
    TransitionSort,
    VoiceQuery,
    VoiceRow,
    VoiceSort,
)
from bgvoice.v1 import pipeline_connect
from bgvoice.v1 import pipeline_pb2 as pb
from bgvoice.web_contract import (
    INSTALLATION_ID,
    Collection,
    ResourceView,
    decode_page_token,
    encode_page_token,
    resource_name,
)

if TYPE_CHECKING:
    from connectrpc.request import RequestContext


_INSTALLATION_NAME: Final = f"installations/{INSTALLATION_ID}"
_DEFAULT_PAGE_SIZE: Final = 25
_READER_PAGE_SIZE: Final = 100
_MAX_PAGE_SIZE: Final = 100

_TEXT = TypeAdapter(str)
_INTEGER = TypeAdapter(int)
_BOOLEAN = TypeAdapter(bool)


class _PortraitMetadata(LanceModel):
    """Portrait fields safe to hydrate while browsing; PNG bytes stay in LanceDB."""

    model_config = ConfigDict(strict=True, extra="forbid")

    resref: str
    source: ResourceSource
    width: int
    height: int


_SOURCE_KIND: Final[dict[SourceKind, pb.SourceKind]] = {
    SourceKind.OVERRIDE: pb.SOURCE_KIND_OVERRIDE,
    SourceKind.BIF: pb.SOURCE_KIND_BIF,
    SourceKind.DLC: pb.SOURCE_KIND_DLC,
}
_DETAIL_STATUS: Final[dict[DetailStatus, pb.DetailStatus]] = {
    DetailStatus.PENDING: pb.DETAIL_STATUS_PENDING,
    DetailStatus.COMPLETE: pb.DETAIL_STATUS_COMPLETE,
    DetailStatus.FAILED: pb.DETAIL_STATUS_FAILED,
}
_ATTRIBUTION_STATUS: Final[dict[AttributionStatus, pb.AttributionStatus]] = {
    AttributionStatus.MATCHED: pb.ATTRIBUTION_STATUS_MATCHED,
    AttributionStatus.PARTIAL_MATCH: pb.ATTRIBUTION_STATUS_PARTIAL_MATCH,
    AttributionStatus.MISSING_DIALOGUE: pb.ATTRIBUTION_STATUS_MISSING_DIALOGUE,
    AttributionStatus.NO_DIALOGUE: pb.ATTRIBUTION_STATUS_NO_DIALOGUE,
    AttributionStatus.CHARACTER_UNAVAILABLE: pb.ATTRIBUTION_STATUS_CHARACTER_UNAVAILABLE,
}
_ATTRIBUTION_PUBLICATION: Final[
    dict[AttributionPublicationStatus, pb.AttributionPublicationStatus]
] = {
    AttributionPublicationStatus.MISSING: pb.ATTRIBUTION_PUBLICATION_STATUS_MISSING,
    AttributionPublicationStatus.STALE: pb.ATTRIBUTION_PUBLICATION_STATUS_STALE,
    AttributionPublicationStatus.PUBLISHED: pb.ATTRIBUTION_PUBLICATION_STATUS_PUBLISHED,
}
_LINE_KIND: Final[dict[DialogueLineKind, pb.DialogueLineKind]] = {
    DialogueLineKind.NPC: pb.DIALOGUE_LINE_KIND_NPC,
    DialogueLineKind.PLAYER: pb.DIALOGUE_LINE_KIND_PLAYER,
    DialogueLineKind.JOURNAL: pb.DIALOGUE_LINE_KIND_JOURNAL,
}
_IDENTIFIER_KIND: Final[dict[IdentifierKind, pb.IdentifierKind]] = {
    IdentifierKind.RACE: pb.IDENTIFIER_KIND_RACE,
    IdentifierKind.CLASS: pb.IDENTIFIER_KIND_CLASS,
    IdentifierKind.GENDER: pb.IDENTIFIER_KIND_GENDER,
    IdentifierKind.ALIGNMENT: pb.IDENTIFIER_KIND_ALIGNMENT,
    IdentifierKind.ENEMY_ALLY: pb.IDENTIFIER_KIND_ENEMY_ALLY,
    IdentifierKind.GENERAL: pb.IDENTIFIER_KIND_GENERAL,
    IdentifierKind.SPECIFIC: pb.IDENTIFIER_KIND_SPECIFIC,
    IdentifierKind.ANIMATION: pb.IDENTIFIER_KIND_ANIMATION,
    IdentifierKind.KIT: pb.IDENTIFIER_KIND_KIT,
    IdentifierKind.SOUND_SLOT: pb.IDENTIFIER_KIND_SOUND_SLOT,
}
_RUN_KIND: Final[dict[RunKind, pb.RunKind]] = {
    RunKind.CHARACTERS: pb.RUN_KIND_CHARACTERS,
    RunKind.DIALOGUES: pb.RUN_KIND_DIALOGUES,
    RunKind.PORTRAITS: pb.RUN_KIND_PORTRAITS,
    RunKind.METADATA: pb.RUN_KIND_METADATA,
    RunKind.ATTRIBUTION: pb.RUN_KIND_ATTRIBUTION,
}
_RUN_STATUS: Final[dict[RunStatus, pb.RunStatus]] = {
    RunStatus.RUNNING: pb.RUN_STATUS_RUNNING,
    RunStatus.COMPLETE: pb.RUN_STATUS_COMPLETE,
    RunStatus.COMPLETE_WITH_ERRORS: pb.RUN_STATUS_COMPLETE_WITH_ERRORS,
    RunStatus.FAILED: pb.RUN_STATUS_FAILED,
}

_VOICE_ORDER: Final[dict[str, VoiceSort]] = {
    "display_name": "display_name",
    "character_count": "variant_count",
    "dialogue_count": "dialogue_count",
    "npc_line_count": "npc_line_count",
    "serialized_size": "serialized_size",
}
_CHARACTER_ORDER: Final[dict[str, CharacterSort]] = {
    "display_name": "display_name",
    "engine_resource_name": "resource_name",
    "source_kind": "source_kind",
    "npc_line_count": "npc_line_count",
    "player_line_count": "player_line_count",
    "state_count": "dialogue_state_count",
    "transition_count": "dialogue_transition_count",
    "serialized_size": "serialized_size",
}
_DIALOGUE_ORDER: Final[dict[str, DialogueSort]] = {
    "engine_resource_name": "resource_name",
    "source_kind": "source_kind",
    "dialogue_line_count": "dialogue_line_count",
    "npc_line_count": "npc_line_count",
    "player_line_count": "player_line_count",
    "character_count": "character_count",
    "serialized_size": "serialized_size",
}
_LINE_ORDER: Final[dict[str, LineSort]] = {
    "dialogue": "dialogue_resource_name",
    "line_kind": "line_kind",
    "strref": "strref",
    "state_index": "state_index",
    "transition_index": "transition_index",
    "serialized_size": "serialized_size",
}
_SOUND_ORDER: Final[dict[str, SoundSort]] = {
    "character": "character_resource_name",
    "slot_id": "slot_id",
    "strref": "strref",
    "serialized_size": "serialized_size",
}
_TRANSITION_ORDER: Final[dict[str, TransitionSort]] = {
    "location": "location",
    "dialogue": "dialogue_resource_name",
    "state_index": "state_index",
    "transition_index": "transition_index",
    "serialized_size": "serialized_size",
}
_RACE_ORDER: Final[dict[str, RaceSort]] = {
    "race_id": "race_id",
    "display_name": "name",
    "source_resource": "source_resource",
}
_CLASS_ORDER: Final[dict[str, ClassSort]] = {
    "class_id": "class_id",
    "display_name": "lower_name",
    "fallen": "fallen",
}
_KIT_ORDER: Final[dict[str, KitSort]] = {
    "row_id": "row_id",
    "display_name": "lower_name",
    "character_class": "class_id",
}
_IDENTIFIER_ORDER: Final[dict[str, IdentifierSort]] = {
    "kind": "kind",
    "value": "value",
    "source_resource": "source_resource",
}


class _ReaderPage[T](Protocol):
    items: list[T]
    total: int


@dataclass(frozen=True, slots=True)
class _ListPage:
    size: int
    offset: int
    view: ResourceView


@dataclass(slots=True)
class _Filter:
    search: str | None
    clauses: dict[str, str]

    @classmethod
    def parse(cls, raw: str) -> _Filter:
        search: str | None = None
        clauses: dict[str, str] = {}
        for expression in _filter_expressions(raw):
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


def _filter_expressions(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []
    expressions: list[str] = []
    start = 0
    depth = 0
    quoted = False
    escaped = False
    for index, character in enumerate(raw):
        if escaped:
            escaped = False
        elif character == "\\" and quoted:
            escaped = True
        elif character == '"':
            quoted = not quoted
        elif not quoted and character == "(":
            depth += 1
        elif not quoted and character == ")":
            depth -= 1
            assert depth >= 0, "filter has an unmatched closing parenthesis"
        elif not quoted and depth == 0 and raw[index : index + 5] == " AND ":
            expressions.append(raw[start:index])
            start = index + 5
    assert not quoted, "filter has an unterminated string"
    assert depth == 0, "filter has an unmatched opening parenthesis"
    expressions.append(raw[start:])
    assert all(expressions), "filter contains an empty expression"
    return expressions


def _json_value[T](adapter: TypeAdapter[T], raw: str, field_name: str) -> T:
    try:
        return adapter.validate_json(raw, strict=True)
    except ValidationError as error:
        raise AssertionError(f"invalid {field_name}: {raw!r}") from error


def _order[T: str](
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


def _view(value: pb.View, *, default: ResourceView) -> ResourceView:
    if value == pb.VIEW_UNSPECIFIED:
        return default
    if value == pb.VIEW_BASIC:
        return ResourceView.BASIC
    if value == pb.VIEW_FULL:
        return ResourceView.FULL
    raise AssertionError(f"unknown view: {value}")


def _parent(parent: str) -> None:
    assert parent == _INSTALLATION_NAME, f"parent must be {_INSTALLATION_NAME!r}"


async def _window[T](
    offset: int,
    size: int,
    load: Callable[[int], Awaitable[_ReaderPage[T]]],
) -> tuple[list[T], int]:
    page_number = offset // _READER_PAGE_SIZE + 1
    within_page = offset % _READER_PAGE_SIZE
    first = await load(page_number)
    items = first.items[within_page : within_page + size]
    if len(items) < size and offset + len(items) < first.total:
        second = await load(page_number + 1)
        items.extend(second.items[: size - len(items)])
    return items, first.total


async def _resource_key[Key: (str, int)](
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


async def _record_by_key[Record: LanceModel, Key: (str, int)](
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


async def _resource_record[Record: LanceModel, Key: (str, int)](
    table: AsyncTable,
    model: type[Record],
    column: str,
    collection: Collection,
    name: str,
) -> Record:
    key = await _resource_key(table, column, collection, name)
    return await _record_by_key(table, model, column, key)


async def _all_rows[T](
    load: Callable[[int], Awaitable[_ReaderPage[T]]],
) -> list[T]:
    rows: list[T] = []
    page_number = 1
    while True:
        page = await load(page_number)
        rows.extend(page.items)
        if page_number * _READER_PAGE_SIZE >= page.total:
            return rows
        page_number += 1


def _next_token(
    collection: Collection,
    request_filter: str,
    order_by: str,
    page: _ListPage,
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


def _source(kind: SourceKind, path: str) -> pb.ResourceSource:
    return pb.ResourceSource(kind=_SOURCE_KIND[kind], path=path)


def _extraction(record: CharacterRecord | DialogueRecord) -> pb.ExtractionState:
    state = pb.ExtractionState(
        status=_DETAIL_STATUS[record.extraction.status],
        updated_at=_timestamp(record.extraction.updated_at),
        run=resource_name(Collection.EXTRACTION_RUNS, record.extraction.run_id),
    )
    if record.extraction.error is not None:
        state.error = record.extraction.error
    return state


def _dialogue_summary(row: CharacterRow) -> pb.CharacterDialogueSummary:
    return pb.CharacterDialogueSummary(
        declared_dialogue_count=row.declared_dialogue_count or 0,
        resolved_dialogue_count=row.resolved_dialogue_count or 0,
        dialogue_line_count=row.dialogue_line_count or 0,
        npc_line_count=row.npc_line_count or 0,
        player_line_count=row.player_line_count or 0,
        journal_line_count=row.journal_line_count or 0,
        state_count=row.dialogue_state_count or 0,
        transition_count=row.dialogue_transition_count or 0,
        serialized_size=row.dialogue_serialized_size or 0,
    )


def _voice_character_name(
    characters: Mapping[str, CharacterRecord],
    resource: str,
) -> str:
    if resource not in characters or characters[resource].detail is None:
        return resource
    detail = characters[resource].detail
    assert detail is not None
    return detail.display_name


def _dialogue_npc_line_count(dialogue: DialogueRecord) -> int:
    return 0 if dialogue.detail is None else dialogue.detail.npc_line_count


def _optional_value[T](values: Mapping[str, T], key: str) -> T | None:
    if key not in values:
        return None
    return values[key]


def _voice(
    row: VoiceRow,
    characters: Mapping[str, CharacterRecord],
    portrait_resrefs: frozenset[str],
    attributions: Mapping[str, CharacterAttributionRecord],
    dialogues: Mapping[str, DialogueRecord],
    biography_sound_id: str | None = None,
) -> pb.Voice:
    dialogues_by_resref = {dialogue.resref.casefold(): dialogue for dialogue in dialogues.values()}
    message = pb.Voice(
        name=resource_name(Collection.VOICES, row.id),
        voice_id=row.id,
        display_name=row.display_name,
        prompt=row.prompt,
        characters=[
            pb.CharacterReference(
                name=resource_name(Collection.CHARACTERS, name),
                engine_resource_name=name,
                display_name=_voice_character_name(characters, name),
                npc_line_count=_npc_line_count(
                    attributions.get(name.casefold()),
                    dialogues,
                ),
            )
            for name in row.variant_resource_names
        ],
        dialogues=[
            pb.DialogueReference(
                name=resource_name(Collection.DIALOGUES, f"{resref}.DLG"),
                engine_resource_name=f"{resref}.DLG",
                npc_line_count=_dialogue_npc_line_count(dialogues_by_resref[resref.casefold()]),
            )
            for resref in row.dialogue_resrefs
        ],
        character_count=row.variant_count,
        dialogue_count=row.dialogue_count,
        npc_line_count=row.npc_line_count,
        serialized_size=row.serialized_size,
    )
    for character_name in row.variant_resource_names:
        if character_name not in characters:
            continue
        portrait = _portrait_resref(characters[character_name])
        if portrait is not None and portrait.casefold() in portrait_resrefs:
            message.portrait = resource_name(Collection.PORTRAITS, portrait)
            break
    if biography_sound_id is not None:
        message.biography = resource_name(Collection.CHARACTER_SOUNDS, biography_sound_id)
    return message


def _character_detail(row: CharacterRow, record: CharacterRecord) -> pb.CharacterDetail | None:
    detail = record.detail
    if detail is None:
        return None
    message = pb.CharacterDetail(
        short_name_strref=detail.short_name_strref,
        long_name_strref=detail.long_name_strref,
        gender_id=detail.gender_id,
        gender_label=row.gender_label or str(detail.gender_id),
        race_id=detail.race_id,
        race_label=row.race_label or str(detail.race_id),
        race=resource_name(Collection.RACES, str(detail.race_id)),
        class_id=detail.class_id,
        class_label=row.class_label or str(detail.class_id),
        character_class=resource_name(Collection.CHARACTER_CLASSES, str(detail.class_id)),
        alignment_id=detail.alignment_id,
        alignment_label=row.alignment_label or str(detail.alignment_id),
        enemy_ally_id=detail.enemy_ally_id,
        enemy_ally_label=row.enemy_ally_label or str(detail.enemy_ally_id),
        general_id=detail.general_id,
        general_label=row.general_label or str(detail.general_id),
        specific_id=detail.specific_id,
        specific_label=row.specific_label or str(detail.specific_id),
        animation_id=detail.animation_id,
        animation_label=row.animation_label or str(detail.animation_id),
        racial_enemy_id=detail.racial_enemy_id,
        racial_enemy_label=row.racial_enemy_label or str(detail.racial_enemy_id),
        cre_kit_value=detail.cre_kit_value,
        class_levels=pb.CharacterClassLevels(
            first_class=detail.class_levels.first_class,
            second_class=detail.class_levels.second_class,
            third_class=detail.class_levels.third_class,
        ),
        base_attributes=pb.CharacterBaseAttributes(
            strength=detail.base_attributes.strength,
            strength_bonus=detail.base_attributes.strength_bonus,
            intelligence=detail.base_attributes.intelligence,
            wisdom=detail.base_attributes.wisdom,
            dexterity=detail.base_attributes.dexterity,
            constitution=detail.base_attributes.constitution,
            charisma=detail.base_attributes.charisma,
        ),
        morale=detail.morale,
        morale_break=detail.morale_break,
        morale_recovery_time=detail.morale_recovery_time,
        reputation=detail.reputation,
        cre_version=detail.cre_version,
    )
    for field_name in (
        "short_name",
        "long_name",
        "death_variable",
        "dialog_resref",
        "override_script",
        "class_script",
        "race_script",
        "general_script",
        "default_script",
    ):
        value = getattr(detail, field_name)
        if value is not None:
            setattr(message, field_name, value)
    if detail.kit_ids_value is not None:
        message.kit_ids_value = detail.kit_ids_value
    if row.kit_label is not None:
        message.kit_label = row.kit_label
    if detail.small_portrait is not None:
        message.small_portrait_resref = detail.small_portrait
    if detail.large_portrait is not None:
        message.large_portrait_resref = detail.large_portrait
    return message


def _portrait_resref(record: CharacterRecord) -> str | None:
    if record.detail is None:
        return None
    return record.detail.large_portrait or record.detail.small_portrait


def _character(
    row: CharacterRow,
    record: CharacterRecord,
    portrait_resrefs: frozenset[str],
    biography_sound_id: str | None,
    *,
    full: bool,
) -> pb.Character:
    message = pb.Character(
        name=resource_name(Collection.CHARACTERS, row.resource_name),
        engine_resource_name=row.resource_name,
        resref=row.resref,
        source=_source(record.source.kind, record.source.path),
        extraction=_extraction(record),
        dialogue=_dialogue_summary(row),
    )
    if row.display_name is not None:
        message.display_name = row.display_name
    if row.voice_id is not None:
        message.voice = resource_name(Collection.VOICES, row.voice_id)
    if row.dialog_resref is not None and row.dialogue_status is DetailStatus.COMPLETE:
        message.direct_dialogue = resource_name(Collection.DIALOGUES, f"{row.dialog_resref}.DLG")
    portrait = _portrait_resref(record)
    if portrait is not None and portrait.casefold() in portrait_resrefs:
        message.portrait = resource_name(Collection.PORTRAITS, portrait)
    if row.attribution_status is not None:
        message.attribution_status = _ATTRIBUTION_STATUS[row.attribution_status]
    if row.serialized_size is not None:
        message.serialized_size = row.serialized_size
    if biography_sound_id is not None:
        message.biography = resource_name(Collection.CHARACTER_SOUNDS, biography_sound_id)
    if full:
        detail = _character_detail(row, record)
        if detail is not None:
            message.detail.CopyFrom(detail)
    return message


def _dialogue(row: DialogueRow, record: DialogueRecord, *, full: bool) -> pb.Dialogue:
    message = pb.Dialogue(
        name=resource_name(Collection.DIALOGUES, row.resource_name),
        engine_resource_name=row.resource_name,
        resref=row.resref,
        source=_source(record.source.kind, record.source.path),
        extraction=_extraction(record),
        character_count=row.character_count,
    )
    if row.serialized_size is not None:
        message.serialized_size = row.serialized_size
    if full and record.detail is not None:
        detail = record.detail
        message.detail.CopyFrom(
            pb.DialogueDetail(
                dlg_version=detail.dlg_version,
                state_count=detail.state_count,
                transition_count=detail.transition_count,
                npc_line_count=detail.npc_line_count,
                player_line_count=detail.player_line_count,
                journal_line_count=detail.journal_line_count,
                dialogue_line_count=detail.dialogue_line_count,
            )
        )
    return message


def _dialogue_line(row: DialogueLineRow) -> pb.DialogueLine:
    message = pb.DialogueLine(
        name=resource_name(Collection.DIALOGUE_LINES, row.id),
        dialogue=resource_name(Collection.DIALOGUES, row.dialogue_resource_name),
        dialogue_resref=row.dialogue_resref,
        source_kind=_SOURCE_KIND[row.source_kind],
        line_kind=_LINE_KIND[row.line_kind],
        state_index=row.state_index,
        strref=row.strref,
        tokens=row.tokens,
        serialized_size=row.serialized_size,
        character_count=row.character_count,
    )
    if row.state_trigger_index is not None:
        message.state_trigger_index = row.state_trigger_index
    if row.state_trigger_text is not None:
        message.state_trigger_text = row.state_trigger_text
    if row.transition_index is not None:
        message.transition_index = row.transition_index
    if row.text is not None:
        message.text = row.text
    return message


def _sound(row: SoundRow) -> pb.CharacterSound:
    message = pb.CharacterSound(
        name=resource_name(Collection.CHARACTER_SOUNDS, row.key),
        character=resource_name(Collection.CHARACTERS, row.character_resource_name),
        character_display_name=row.character_name,
        slot_id=row.slot_id,
        slot_symbols=row.slot_symbols,
        slot_groups=row.slot_groups,
        strref=row.strref,
        serialized_size=row.serialized_size,
    )
    if row.text is not None:
        message.text = row.text
    return message


def _transition(row: TransitionRow) -> pb.DialogueTransition:
    message = pb.DialogueTransition(
        name=resource_name(Collection.DIALOGUE_TRANSITIONS, row.id),
        dialogue=resource_name(Collection.DIALOGUES, row.dialogue_resource_name),
        dialogue_resref=row.dialogue_resref,
        source_kind=_SOURCE_KIND[row.source_kind],
        state_index=row.state_index,
        transition_index=row.transition_index,
        flags_raw=row.flags_raw,
        flags_decoded=row.flags_decoded,
        terminates_dialogue=row.terminates_dialog,
        serialized_size=row.serialized_size,
    )
    for field_name in ("trigger_index", "trigger_text", "action_index", "action_text"):
        value = getattr(row, field_name)
        if value is not None:
            setattr(message, field_name, value)
    if row.next_dialog is not None:
        message.next_dialogue_resref = row.next_dialog
        message.next_dialogue = resource_name(Collection.DIALOGUES, f"{row.next_dialog}.DLG")
    if row.next_state_index is not None:
        message.next_state_index = row.next_state_index
    return message


def _race(rows: Sequence[RaceRow], *, full: bool) -> pb.Race:
    assert rows, "a race resource needs at least one source row"
    row = next((candidate for candidate in rows if candidate.name is not None), rows[0])
    symbols = list(dict.fromkeys(symbol for candidate in rows for symbol in candidate.symbols))
    message = pb.Race(
        name=resource_name(Collection.RACES, str(row.race_id)),
        race_id=row.race_id,
        symbols=symbols,
        display_name=row.name or (symbols[0] if symbols else str(row.race_id)),
    )
    if full:
        for source in rows:
            if source.source_resource is None:
                continue
            text = pb.RaceText(
                source_resource=source.source_resource,
                campaigns=source.campaigns,
            )
            for field_name in (
                "row_name",
                "name_strref",
                "description_strref",
                "description",
                "uppercase_name_strref",
                "uppercase_name",
                "biography_strref",
                "biography",
            ):
                value = getattr(source, field_name)
                if value is not None:
                    setattr(text, field_name, value)
            if source.name is not None:
                text.display_name = source.name
            message.texts.append(text)
    return message


def _character_class(rows: Sequence[ClassRow], *, full: bool) -> pb.CharacterClass:
    assert rows, "a class resource needs at least one source row"
    row = next(
        (
            candidate
            for candidate in rows
            if candidate.mixed_name is not None or candidate.lower_name is not None
        ),
        rows[0],
    )
    display_name = row.mixed_name or row.lower_name
    symbols = list(dict.fromkeys(symbol for candidate in rows for symbol in candidate.symbols))
    message = pb.CharacterClass(
        name=resource_name(Collection.CHARACTER_CLASSES, str(row.class_id)),
        class_id=row.class_id,
        symbols=symbols,
        display_name=display_name or (symbols[0] if symbols else str(row.class_id)),
    )
    if full:
        for source in rows:
            if source.source_resource is None:
                continue
            text = pb.CharacterClassText(
                source_resource=source.source_resource,
                campaigns=source.campaigns,
            )
            for field_name in (
                "row_name",
                "class_text_kit_id",
                "lower_name_strref",
                "lower_name",
                "description_strref",
                "description",
                "mixed_name_strref",
                "mixed_name",
                "biography_strref",
                "biography",
                "fallen",
                "brief_description_strref",
                "brief_description",
                "fallen_notice_strref",
                "fallen_notice",
            ):
                value = getattr(source, field_name)
                if value is not None:
                    setattr(text, field_name, value)
            message.texts.append(text)
    return message


def _class_display_name(row: ClassRow) -> str:
    return row.mixed_name or row.lower_name or ""


def _kit(row: KitRow) -> pb.Kit:
    message = pb.Kit(
        name=resource_name(Collection.KITS, row.key),
        row_id=row.row_id,
        row_name=row.row_name,
        source_resource=row.source_resource,
        display_name=row.mixed_name or row.lower_name or row.row_name,
        class_symbols=row.class_symbols,
        kit_symbols=row.kit_symbols,
    )
    for field_name in (
        "lower_name",
        "mixed_name",
        "help_text",
        "kit_ids_value",
        "abilities_resref",
        "proficiency_column",
        "unusable_mask",
    ):
        value = getattr(row, field_name)
        if value is not None:
            setattr(message, field_name, value)
    if row.class_id is not None:
        message.character_class = resource_name(Collection.CHARACTER_CLASSES, str(row.class_id))
    return message


def _identifier(row: IdentifierRow) -> pb.IdentifierDefinition:
    return pb.IdentifierDefinition(
        name=resource_name(Collection.IDENTIFIER_DEFINITIONS, row.key),
        kind=_IDENTIFIER_KIND[IdentifierKind(row.kind)],
        value=row.value,
        symbols=row.symbols,
        source_resource=row.source_resource,
        display_name=(row.symbols[0].replace("_", " ").title() if row.symbols else str(row.value)),
    )


def _portrait(row: _PortraitMetadata | PortraitImageRecord) -> pb.Portrait:
    return pb.Portrait(
        name=resource_name(Collection.PORTRAITS, row.resref),
        resref=row.resref,
        source=_source(row.source.kind, row.source.path),
        width=row.width,
        height=row.height,
        media_type="image/png",
    )


def _campaign(row: CampaignDefinitionRecord) -> pb.Campaign:
    return pb.Campaign(
        name=resource_name(Collection.CAMPAIGNS, row.campaign_id),
        campaign_id=row.campaign_id,
        ordinal=row.ordinal,
        display_name=row.campaign_id.replace("_", " ").title(),
    )


def _run(row: ExtractionRunRecord) -> pb.ExtractionRun:
    message = pb.ExtractionRun(
        name=resource_name(Collection.EXTRACTION_RUNS, row.id),
        run_id=row.id,
        run_kind=_RUN_KIND[row.run_kind],
        started_at=_timestamp(row.started_at),
        status=_RUN_STATUS[row.status],
        resources_discovered=row.resources_discovered,
        details_attempted=row.details_attempted,
        details_extracted=row.details_extracted,
        failures=row.failures,
        completed_at=(_timestamp(row.completed_at) if row.completed_at is not None else None),
    )
    if row.error is not None:
        message.error = row.error
    return message


def _timestamp(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert timestamp.tzinfo is not None, "pipeline timestamps must include a UTC offset"
    return timestamp


async def _selected_characters(
    reader: PipelineReader,
    names: Sequence[str],
) -> dict[str, CharacterRecord]:
    if not names:
        return {}
    rows = cast(
        list[CharacterRecord],
        await reader.characters_table.query()
        .where(col("resource_name").isin(names))
        .to_pydantic(CharacterRecord),
    )
    return {row.resource_name: row for row in rows}


async def _selected_dialogues(
    reader: PipelineReader,
    names: Sequence[str],
) -> dict[str, DialogueRecord]:
    if not names:
        return {}
    rows = cast(
        list[DialogueRecord],
        await reader.dialogues_table.query()
        .where(col("resource_name").isin(names))
        .to_pydantic(DialogueRecord),
    )
    return {row.resource_name: row for row in rows}


async def _selected_dialogues_by_resref(
    reader: PipelineReader,
    resrefs: Sequence[str],
) -> list[DialogueRecord]:
    if not resrefs:
        return []
    return cast(
        list[DialogueRecord],
        await reader.dialogues_table.query()
        .where(col("resref").isin(resrefs))
        .to_pydantic(DialogueRecord),
    )


async def _resolved_character_row(
    reader: PipelineReader,
    record: CharacterRecord,
) -> CharacterRow:
    metadata, attribution = await asyncio.gather(
        reader._metadata_snapshot(),
        reader._attribution_snapshot(),
    )
    key = record.resource_name.casefold()
    character_attribution = _optional_value(attribution.by_character, key)
    voice = _optional_value(attribution.voice_by_character, key)
    dialogue_names = (
        []
        if character_attribution is None
        else character_attribution.resolved_dialogue_resource_names
    )
    dialogues = await _selected_dialogues(reader, dialogue_names)
    return reader_models._character_row(
        record,
        character_attribution,
        voice,
        {name.casefold(): dialogue for name, dialogue in dialogues.items()},
        reader_models._LabelResolver.from_snapshot(metadata),
    )


async def _resolved_dialogue_row(
    reader: PipelineReader,
    record: DialogueRecord,
) -> DialogueRow:
    attribution = await reader._attribution_snapshot()
    return reader_models._dialogue_row(
        record,
        attribution.character_count_by_dialogue[record.resource_name.casefold()],
    )


async def _portrait_rows(reader: PipelineReader) -> list[_PortraitMetadata]:
    return cast(
        list[_PortraitMetadata],
        await reader.portrait_images_table.query()
        .select(list(_PortraitMetadata.model_fields))
        .to_pydantic(_PortraitMetadata),
    )


async def _portrait_resrefs(reader: PipelineReader) -> frozenset[str]:
    values = cast(
        list[str],
        (await reader.portrait_images_table.query().select(["resref"]).to_arrow())
        .column("resref")
        .to_pylist(),
    )
    return frozenset(value.casefold() for value in values)


async def _biography_sounds(
    reader: PipelineReader,
    character_names: Sequence[str],
) -> dict[str, str]:
    if not character_names:
        return {}
    rows = (
        await reader.character_sounds_table.query()
        .where(
            (col("slot_id") == lit(BIOGRAPHY_SOUND_SLOT_ID))
            & col("character_resource_name").isin(character_names)
        )
        .select(["id", "character_resource_name"])
        .to_arrow()
    )
    ids = cast(list[str], rows.column("id").to_pylist())
    characters = cast(list[str], rows.column("character_resource_name").to_pylist())
    return dict(zip(characters, ids, strict=True))


def _npc_line_count(
    attribution: CharacterAttributionRecord | None,
    dialogues: Mapping[str, DialogueRecord],
) -> int:
    if attribution is None:
        return 0
    return sum(
        _dialogue_npc_line_count(dialogues[name.casefold()])
        for name in attribution.resolved_dialogue_resource_names
        if name.casefold() in dialogues
    )


async def _run_rows(reader: PipelineReader) -> list[ExtractionRunRecord]:
    return cast(
        list[ExtractionRunRecord],
        await reader.runs_table.query().to_pydantic(ExtractionRunRecord),
    )


async def _campaign_rows(reader: PipelineReader) -> list[CampaignDefinitionRecord]:
    return cast(
        list[CampaignDefinitionRecord],
        await reader.campaigns_table.query().to_pydantic(CampaignDefinitionRecord),
    )


def _invalid_arguments[**P, R](
    method: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    @wraps(method)
    async def checked(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await method(*args, **kwargs)
        except ConnectError:
            raise
        except (AssertionError, ValidationError, ValueError) as error:
            raise ConnectError(Code.INVALID_ARGUMENT, str(error)) from error

    return checked


@dataclass(slots=True)
class PipelineService(pipeline_connect.PipelineService):
    """AIP-shaped read service backed by the current application reader."""

    reader: Callable[[], PipelineReader]

    def _page(
        self,
        collection: Collection,
        *,
        parent: str,
        page_size: int,
        page_token: str,
        request_filter: str,
        order_by: str,
        view: pb.View,
    ) -> _ListPage:
        _parent(parent)
        assert page_size >= 0, "page_size must not be negative"
        size = min(page_size or _DEFAULT_PAGE_SIZE, _MAX_PAGE_SIZE)
        resource_view = _view(view, default=ResourceView.BASIC)
        offset = 0
        if page_token:
            offset = decode_page_token(
                page_token,
                collection,
                filter=request_filter,
                order_by=order_by,
                view=resource_view,
                page_size=size,
            )
        return _ListPage(size=size, offset=offset, view=resource_view)

    @_invalid_arguments
    async def get_installation(
        self,
        request: pb.GetInstallationRequest,
        _ctx: RequestContext[pb.GetInstallationRequest, pb.Installation],
    ) -> pb.Installation:
        if request.name != _INSTALLATION_NAME:
            raise ConnectError(Code.NOT_FOUND, f"resource not found: {request.name}")
        reader = self.reader()
        stats = await reader.stats()

        message = pb.Installation(
            name=_INSTALLATION_NAME,
            display_name="Baldur's Gate II: Enhanced Edition — EET",
            database_path=stats.database_path,
            database_size=stats.database_size,
            attribution_publication=_ATTRIBUTION_PUBLICATION[stats.attribution_publication],
            attribution_completed_at=(
                _timestamp(stats.attribution_completed_at)
                if stats.attribution_completed_at is not None
                else None
            ),
            summary=pb.PipelineSummary(
                voices=stats.voices_total,
                characters=stats.characters_total,
                dialogues=stats.dialogues_total,
                dialogue_lines=stats.line_records_total,
                character_sounds=stats.character_sounds_total,
                dialogue_transitions=stats.transition_edges_total,
                races=stats.races_total,
                character_classes=stats.classes_total,
                kits=stats.kits_total,
                identifier_definitions=stats.identifiers_total,
                matched_characters=stats.characters_matched,
                partially_matched_characters=stats.characters_partially_matched,
                missing_dialogue_characters=stats.characters_missing_dialogue,
                unattributed_dialogues=stats.dialogues_unattributed,
                unattributed_dialogue_lines=stats.unattributed_dialogue_lines,
            ),
        )
        return message

    @_invalid_arguments
    async def list_voices(
        self,
        request: pb.ListVoicesRequest,
        _ctx: RequestContext[pb.ListVoicesRequest, pb.ListVoicesResponse],
    ) -> pb.ListVoicesResponse:
        page = self._page(
            Collection.VOICES,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
            view=request.view,
        )
        filters = _Filter.parse(request.filter)
        filters.finish()
        sort, direction = _order(request.order_by, _VOICE_ORDER)
        query = VoiceQuery(q=filters.search, sort=sort, direction=direction)

        async def load(page_number: int) -> _ReaderPage[VoiceRow]:
            return await self.reader().voices(
                query.model_copy(update={"page": page_number, "page_size": _READER_PAGE_SIZE})
            )

        rows, total = await _window(page.offset, page.size, load)
        reader = self.reader()
        character_names = [name for row in rows for name in row.variant_resource_names]
        dialogue_resrefs = [resref for row in rows for resref in row.dialogue_resrefs]
        characters, portrait_resrefs, attribution, dialogue_records = await asyncio.gather(
            _selected_characters(reader, character_names),
            _portrait_resrefs(reader),
            reader._attribution_snapshot(),
            _selected_dialogues_by_resref(reader, dialogue_resrefs),
        )
        dialogues = {record.resource_name.casefold(): record for record in dialogue_records}
        voice_records = {record.voice_id: record for record in attribution.voices}
        return pb.ListVoicesResponse(
            voices=[
                _voice(
                    row,
                    characters,
                    portrait_resrefs,
                    attribution.by_character,
                    dialogues,
                    voice_records[row.id].biography_sound_id,
                )
                for row in rows
            ],
            next_page_token=_next_token(
                Collection.VOICES,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_voice(
        self,
        request: pb.GetVoiceRequest,
        _ctx: RequestContext[pb.GetVoiceRequest, pb.Voice],
    ) -> pb.Voice:
        _view(request.view, default=ResourceView.FULL)

        reader = self.reader()
        voice_id = await _resource_key(
            reader.voices_table,
            "voice_id",
            Collection.VOICES,
            request.name,
        )
        voice_page = await reader.voices(VoiceQuery(voice_id=voice_id, page_size=10))
        if not voice_page.items:
            raise ConnectError(Code.NOT_FOUND, f"resource not found: {request.name}")
        assert len(voice_page.items) == 1, f"duplicate current voice id: {voice_id!r}"
        row = voice_page.items[0]
        characters, portrait_resrefs, attribution, dialogue_records = await asyncio.gather(
            _selected_characters(reader, row.variant_resource_names),
            _portrait_resrefs(reader),
            reader._attribution_snapshot(),
            _selected_dialogues_by_resref(reader, row.dialogue_resrefs),
        )
        return _voice(
            row,
            characters,
            portrait_resrefs,
            attribution.by_character,
            {record.resource_name.casefold(): record for record in dialogue_records},
            next(
                record.biography_sound_id
                for record in attribution.voices
                if record.voice_id == row.id
            ),
        )

    @_invalid_arguments
    async def list_characters(
        self,
        request: pb.ListCharactersRequest,
        _ctx: RequestContext[pb.ListCharactersRequest, pb.ListCharactersResponse],
    ) -> pb.ListCharactersResponse:
        page = self._page(
            Collection.CHARACTERS,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
            view=request.view,
        )
        filters = _Filter.parse(request.filter)
        sort, direction = _order(request.order_by, _CHARACTER_ORDER)
        query = CharacterQuery(
            q=filters.search,
            status=filters.enum("detail_status", DetailStatus),
            source_kind=filters.enum("source_kind", SourceKind),
            gender_id=filters.integer("gender_id"),
            race_id=filters.integer("race_id"),
            class_id=filters.integer("class_id"),
            attribution_status=filters.enum("attribution_status", AttributionStatus),
            sort=sort,
            direction=direction,
        )
        filters.finish()

        async def load(page_number: int) -> _ReaderPage[CharacterRow]:
            return await self.reader().characters(
                query.model_copy(update={"page": page_number, "page_size": _READER_PAGE_SIZE})
            )

        rows, total = await _window(page.offset, page.size, load)
        reader = self.reader()
        character_names = [row.resource_name for row in rows]
        records, portrait_resrefs, biographies = await asyncio.gather(
            _selected_characters(reader, character_names),
            _portrait_resrefs(reader),
            _biography_sounds(reader, character_names),
        )
        return pb.ListCharactersResponse(
            characters=[
                _character(
                    row,
                    records[row.resource_name],
                    portrait_resrefs,
                    _optional_value(biographies, row.resource_name),
                    full=page.view is ResourceView.FULL,
                )
                for row in rows
            ],
            next_page_token=_next_token(
                Collection.CHARACTERS,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_character(
        self,
        request: pb.GetCharacterRequest,
        _ctx: RequestContext[pb.GetCharacterRequest, pb.Character],
    ) -> pb.Character:
        view = _view(request.view, default=ResourceView.FULL)

        reader = self.reader()
        record = await _resource_record(
            reader.characters_table,
            CharacterRecord,
            "resource_name",
            Collection.CHARACTERS,
            request.name,
        )
        row, portrait_resrefs, biographies = await asyncio.gather(
            _resolved_character_row(reader, record),
            _portrait_resrefs(reader),
            _biography_sounds(reader, [record.resource_name]),
        )
        return _character(
            row,
            record,
            portrait_resrefs,
            _optional_value(biographies, record.resource_name),
            full=view is ResourceView.FULL,
        )

    @_invalid_arguments
    async def list_dialogues(
        self,
        request: pb.ListDialoguesRequest,
        _ctx: RequestContext[pb.ListDialoguesRequest, pb.ListDialoguesResponse],
    ) -> pb.ListDialoguesResponse:
        page = self._page(
            Collection.DIALOGUES,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
            view=request.view,
        )
        filters = _Filter.parse(request.filter)
        sort, direction = _order(request.order_by, _DIALOGUE_ORDER)
        query = DialogueQuery(
            q=filters.search,
            status=filters.enum("detail_status", DetailStatus),
            source_kind=filters.enum("source_kind", SourceKind),
            attributed=filters.boolean("attributed"),
            sort=sort,
            direction=direction,
        )
        filters.finish()

        async def load(page_number: int) -> _ReaderPage[DialogueRow]:
            return await self.reader().dialogues(
                query.model_copy(update={"page": page_number, "page_size": _READER_PAGE_SIZE})
            )

        rows, total = await _window(page.offset, page.size, load)
        records = await _selected_dialogues(self.reader(), [row.resource_name for row in rows])
        return pb.ListDialoguesResponse(
            dialogues=[
                _dialogue(
                    row,
                    records[row.resource_name],
                    full=page.view is ResourceView.FULL,
                )
                for row in rows
            ],
            next_page_token=_next_token(
                Collection.DIALOGUES,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_dialogue(
        self,
        request: pb.GetDialogueRequest,
        _ctx: RequestContext[pb.GetDialogueRequest, pb.Dialogue],
    ) -> pb.Dialogue:
        view = _view(request.view, default=ResourceView.FULL)

        reader = self.reader()
        record = await _resource_record(
            reader.dialogues_table,
            DialogueRecord,
            "resource_name",
            Collection.DIALOGUES,
            request.name,
        )
        row = await _resolved_dialogue_row(reader, record)
        return _dialogue(
            row,
            record,
            full=view is ResourceView.FULL,
        )

    @_invalid_arguments
    async def list_dialogue_lines(
        self,
        request: pb.ListDialogueLinesRequest,
        _ctx: RequestContext[pb.ListDialogueLinesRequest, pb.ListDialogueLinesResponse],
    ) -> pb.ListDialogueLinesResponse:
        page = self._page(
            Collection.DIALOGUE_LINES,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
            view=request.view,
        )
        filters = _Filter.parse(request.filter)
        sort, direction = _order(request.order_by, _LINE_ORDER)
        query = LineQuery(
            q=filters.search,
            line_kind=filters.enum("line_kind", DialogueLineKind),
            source_kind=filters.enum("source_kind", SourceKind),
            attributed=filters.boolean("attributed"),
            sort=sort,
            direction=direction,
        )
        filters.finish()

        async def load(page_number: int) -> _ReaderPage[DialogueLineRow]:
            return await self.reader().lines(
                query.model_copy(update={"page": page_number, "page_size": _READER_PAGE_SIZE})
            )

        rows, total = await _window(page.offset, page.size, load)
        return pb.ListDialogueLinesResponse(
            dialogue_lines=[_dialogue_line(row) for row in rows],
            next_page_token=_next_token(
                Collection.DIALOGUE_LINES,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_dialogue_line(
        self,
        request: pb.GetDialogueLineRequest,
        _ctx: RequestContext[pb.GetDialogueLineRequest, pb.DialogueLine],
    ) -> pb.DialogueLine:
        _view(request.view, default=ResourceView.FULL)
        reader = self.reader()
        record = await _resource_record(
            reader.lines_table,
            DialogueLineRecord,
            "id",
            Collection.DIALOGUE_LINES,
            request.name,
        )
        dialogue, attribution = await asyncio.gather(
            _record_by_key(
                reader.dialogues_table,
                DialogueRecord,
                "resource_name",
                record.dialogue_resource_name,
            ),
            reader._attribution_snapshot(),
        )
        return _dialogue_line(
            reader_models._dialogue_line_row(
                record,
                dialogue,
                attribution.character_count_by_dialogue[record.dialogue_resource_name.casefold()],
            )
        )

    @_invalid_arguments
    async def list_character_sounds(
        self,
        request: pb.ListCharacterSoundsRequest,
        _ctx: RequestContext[pb.ListCharacterSoundsRequest, pb.ListCharacterSoundsResponse],
    ) -> pb.ListCharacterSoundsResponse:
        page = self._page(
            Collection.CHARACTER_SOUNDS,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
            view=request.view,
        )
        filters = _Filter.parse(request.filter)
        sort, direction = _order(request.order_by, _SOUND_ORDER)
        query = SoundQuery(
            q=filters.search,
            slot_id=filters.integer("slot_id"),
            sort=sort,
            direction=direction,
        )
        filters.finish()

        async def load(page_number: int) -> _ReaderPage[SoundRow]:
            return await self.reader().sounds(
                query.model_copy(update={"page": page_number, "page_size": _READER_PAGE_SIZE})
            )

        rows, total = await _window(page.offset, page.size, load)
        return pb.ListCharacterSoundsResponse(
            character_sounds=[_sound(row) for row in rows],
            next_page_token=_next_token(
                Collection.CHARACTER_SOUNDS,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_character_sound(
        self,
        request: pb.GetCharacterSoundRequest,
        _ctx: RequestContext[pb.GetCharacterSoundRequest, pb.CharacterSound],
    ) -> pb.CharacterSound:
        _view(request.view, default=ResourceView.FULL)
        reader = self.reader()
        record = await _resource_record(
            reader.character_sounds_table,
            CharacterSoundRecord,
            "id",
            Collection.CHARACTER_SOUNDS,
            request.name,
        )
        character, identifiers, groups = await asyncio.gather(
            _record_by_key(
                reader.characters_table,
                CharacterRecord,
                "resource_name",
                record.character_resource_name,
            ),
            reader.identifiers_table.query()
            .where(
                (col("kind") == lit(IdentifierKind.SOUND_SLOT.value))
                & (col("value") == lit(record.slot_id))
            )
            .to_pydantic(IdentifierDefinitionRecord),
            reader.sound_slot_groups_table.query().to_pydantic(SoundSlotGroupRecord),
        )
        assert character.detail is not None, "character sound belongs to an unavailable CRE"
        typed_identifiers = cast(list[IdentifierDefinitionRecord], identifiers)
        typed_groups = cast(list[SoundSlotGroupRecord], groups)
        symbols = reader_models._identifier_symbols(typed_identifiers)
        return _sound(
            SoundRow(
                key=record.id,
                character_resource_name=record.character_resource_name,
                character_name=character.detail.display_name,
                slot_id=record.slot_id,
                slot_symbols=list(symbols.get((IdentifierKind.SOUND_SLOT, record.slot_id), ())),
                slot_groups=reader_models._sound_slot_group_names(typed_groups, record.slot_id),
                strref=record.strref,
                text=record.text,
                serialized_size=record.serialized_size,
            )
        )

    @_invalid_arguments
    async def list_dialogue_transitions(
        self,
        request: pb.ListDialogueTransitionsRequest,
        _ctx: RequestContext[
            pb.ListDialogueTransitionsRequest,
            pb.ListDialogueTransitionsResponse,
        ],
    ) -> pb.ListDialogueTransitionsResponse:
        page = self._page(
            Collection.DIALOGUE_TRANSITIONS,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
            view=request.view,
        )
        filters = _Filter.parse(request.filter)
        sort, direction = _order(request.order_by, _TRANSITION_ORDER)
        query = TransitionQuery(
            q=filters.search,
            terminates_dialog=filters.boolean("terminates_dialog"),
            sort=sort,
            direction=direction,
        )
        filters.finish()

        async def load(page_number: int) -> _ReaderPage[TransitionRow]:
            return await self.reader().transitions(
                query.model_copy(update={"page": page_number, "page_size": _READER_PAGE_SIZE})
            )

        rows, total = await _window(page.offset, page.size, load)
        return pb.ListDialogueTransitionsResponse(
            dialogue_transitions=[_transition(row) for row in rows],
            next_page_token=_next_token(
                Collection.DIALOGUE_TRANSITIONS,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_dialogue_transition(
        self,
        request: pb.GetDialogueTransitionRequest,
        _ctx: RequestContext[pb.GetDialogueTransitionRequest, pb.DialogueTransition],
    ) -> pb.DialogueTransition:
        _view(request.view, default=ResourceView.FULL)
        reader = self.reader()
        record = await _resource_record(
            reader.transitions_table,
            DialogueTransitionRecord,
            "id",
            Collection.DIALOGUE_TRANSITIONS,
            request.name,
        )
        dialogue = await _record_by_key(
            reader.dialogues_table,
            DialogueRecord,
            "resource_name",
            record.dialogue_resource_name,
        )
        return _transition(reader_models._transition_row(record, dialogue))

    @_invalid_arguments
    async def list_portraits(
        self,
        request: pb.ListPortraitsRequest,
        _ctx: RequestContext[pb.ListPortraitsRequest, pb.ListPortraitsResponse],
    ) -> pb.ListPortraitsResponse:
        page = self._page(
            Collection.PORTRAITS,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
            view=request.view,
        )
        filters = _Filter.parse(request.filter)
        filters.finish()
        sort, direction = _order(
            request.order_by,
            {
                "resref": "resref",
                "source_kind": "source_kind",
                "width": "width",
                "height": "height",
            },
        )
        rows = await _portrait_rows(self.reader())
        if filters.search is not None:
            search = filters.search.casefold()
            rows = [
                row
                for row in rows
                if search in " ".join((row.resref, row.source.kind, row.source.path)).casefold()
            ]
        field_name = sort or "resref"
        rows.sort(
            key=lambda row: (
                row.resref.casefold()
                if field_name == "resref"
                else row.source.kind
                if field_name == "source_kind"
                else row.width
                if field_name == "width"
                else row.height
            ),
            reverse=direction == "desc",
        )
        total = len(rows)
        selected = rows[page.offset : page.offset + page.size]
        return pb.ListPortraitsResponse(
            portraits=[_portrait(row) for row in selected],
            next_page_token=_next_token(
                Collection.PORTRAITS,
                request.filter,
                request.order_by,
                page,
                len(selected),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_portrait(
        self,
        request: pb.GetPortraitRequest,
        _ctx: RequestContext[pb.GetPortraitRequest, pb.Portrait],
    ) -> pb.Portrait:
        _view(request.view, default=ResourceView.FULL)
        reader = self.reader()
        resref = await _resource_key(
            reader.portrait_images_table,
            "resref",
            Collection.PORTRAITS,
            request.name,
        )
        rows = cast(
            list[_PortraitMetadata],
            await reader.portrait_images_table.query()
            .where(col("resref") == lit(resref))
            .select(list(_PortraitMetadata.model_fields))
            .limit(2)
            .to_pydantic(_PortraitMetadata),
        )
        assert len(rows) == 1, f"duplicate portrait resref: {resref!r}"
        return _portrait(rows[0])

    @_invalid_arguments
    async def download_portrait(
        self,
        request: pb.DownloadPortraitRequest,
        _ctx: RequestContext[pb.DownloadPortraitRequest, pb.PortraitContent],
    ) -> pb.PortraitContent:
        row = await _resource_record(
            self.reader().portrait_images_table,
            PortraitImageRecord,
            "resref",
            Collection.PORTRAITS,
            request.name,
        )
        return pb.PortraitContent(
            portrait=resource_name(Collection.PORTRAITS, row.resref),
            png=row.png,
        )

    @_invalid_arguments
    async def list_races(
        self,
        request: pb.ListRacesRequest,
        _ctx: RequestContext[pb.ListRacesRequest, pb.ListRacesResponse],
    ) -> pb.ListRacesResponse:
        page = self._page(
            Collection.RACES,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
            view=request.view,
        )
        filters = _Filter.parse(request.filter)
        sort, direction = _order(request.order_by, _RACE_ORDER)
        query = RaceQuery(
            q=filters.search,
            campaign=filters.text("campaign"),
            sort=sort,
            direction=direction if sort is not None else "asc",
        )
        filters.finish()

        async def load(page_number: int) -> _ReaderPage[RaceRow]:
            return await self.reader().races(
                query.model_copy(update={"page": page_number, "page_size": _READER_PAGE_SIZE})
            )

        source_rows = await _all_rows(load)
        groups: dict[int, list[RaceRow]] = {}
        for row in source_rows:
            groups.setdefault(row.race_id, []).append(row)
        resources = list(groups.values())
        if sort is not None or filters.search is None:
            field_name = sort or "race_id"
            resources.sort(
                key=lambda rows: (
                    rows[0].race_id
                    if field_name == "race_id"
                    else (next((row.name for row in rows if row.name is not None), "")).casefold()
                    if field_name == "name"
                    else next(
                        (
                            row.source_resource.casefold()
                            for row in rows
                            if row.source_resource is not None
                        ),
                        "",
                    )
                ),
                reverse=direction == "desc",
            )
        total = len(resources)
        selected = resources[page.offset : page.offset + page.size]
        return pb.ListRacesResponse(
            races=[_race(rows, full=page.view is ResourceView.FULL) for rows in selected],
            next_page_token=_next_token(
                Collection.RACES,
                request.filter,
                request.order_by,
                page,
                len(selected),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_race(
        self,
        request: pb.GetRaceRequest,
        _ctx: RequestContext[pb.GetRaceRequest, pb.Race],
    ) -> pb.Race:
        view = _view(request.view, default=ResourceView.FULL)
        rows = reader_models._race_rows(await self.reader()._metadata_snapshot())
        groups: dict[int, list[RaceRow]] = {}
        for row in rows:
            groups.setdefault(row.race_id, []).append(row)
        for race_id, rows in groups.items():
            if resource_name(Collection.RACES, str(race_id)) == request.name:
                return _race(rows, full=view is ResourceView.FULL)
        raise ConnectError(Code.NOT_FOUND, f"resource not found: {request.name}")

    @_invalid_arguments
    async def list_character_classes(
        self,
        request: pb.ListCharacterClassesRequest,
        _ctx: RequestContext[
            pb.ListCharacterClassesRequest,
            pb.ListCharacterClassesResponse,
        ],
    ) -> pb.ListCharacterClassesResponse:
        page = self._page(
            Collection.CHARACTER_CLASSES,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
            view=request.view,
        )
        filters = _Filter.parse(request.filter)
        sort, direction = _order(request.order_by, _CLASS_ORDER)
        query = ClassQuery(
            q=filters.search,
            campaign=filters.text("campaign"),
            class_id=filters.integer("class_id"),
            fallen=filters.boolean("fallen"),
            sort=sort,
            direction=direction if sort is not None else "asc",
        )
        filters.finish()

        async def load(page_number: int) -> _ReaderPage[ClassRow]:
            return await self.reader().classes(
                query.model_copy(update={"page": page_number, "page_size": _READER_PAGE_SIZE})
            )

        source_rows = await _all_rows(load)
        groups: dict[int, list[ClassRow]] = {}
        for row in source_rows:
            groups.setdefault(row.class_id, []).append(row)
        resources = list(groups.values())
        if sort is not None or filters.search is None:
            field_name = sort or "class_id"
            resources.sort(
                key=lambda rows: (
                    rows[0].class_id
                    if field_name == "class_id"
                    else next(
                        (
                            _class_display_name(row).casefold()
                            for row in rows
                            if _class_display_name(row)
                        ),
                        "",
                    )
                    if field_name == "lower_name"
                    else any(row.fallen is True for row in rows)
                ),
                reverse=direction == "desc",
            )
        total = len(resources)
        selected = resources[page.offset : page.offset + page.size]
        return pb.ListCharacterClassesResponse(
            character_classes=[
                _character_class(rows, full=page.view is ResourceView.FULL) for rows in selected
            ],
            next_page_token=_next_token(
                Collection.CHARACTER_CLASSES,
                request.filter,
                request.order_by,
                page,
                len(selected),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_character_class(
        self,
        request: pb.GetCharacterClassRequest,
        _ctx: RequestContext[pb.GetCharacterClassRequest, pb.CharacterClass],
    ) -> pb.CharacterClass:
        view = _view(request.view, default=ResourceView.FULL)
        rows = reader_models._class_rows(await self.reader()._metadata_snapshot())
        groups: dict[int, list[ClassRow]] = {}
        for row in rows:
            groups.setdefault(row.class_id, []).append(row)
        for class_id, rows in groups.items():
            if resource_name(Collection.CHARACTER_CLASSES, str(class_id)) == request.name:
                return _character_class(rows, full=view is ResourceView.FULL)
        raise ConnectError(Code.NOT_FOUND, f"resource not found: {request.name}")

    @_invalid_arguments
    async def list_kits(
        self,
        request: pb.ListKitsRequest,
        _ctx: RequestContext[pb.ListKitsRequest, pb.ListKitsResponse],
    ) -> pb.ListKitsResponse:
        page = self._page(
            Collection.KITS,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
            view=request.view,
        )
        filters = _Filter.parse(request.filter)
        sort, direction = _order(request.order_by, _KIT_ORDER)
        query = KitQuery(
            q=filters.search,
            class_id=filters.integer("class_id"),
            sort=sort,
            direction=direction if sort is not None else "asc",
        )
        filters.finish()

        async def load(page_number: int) -> _ReaderPage[KitRow]:
            return await self.reader().kits(
                query.model_copy(update={"page": page_number, "page_size": _READER_PAGE_SIZE})
            )

        rows, total = await _window(page.offset, page.size, load)
        return pb.ListKitsResponse(
            kits=[_kit(row) for row in rows],
            next_page_token=_next_token(
                Collection.KITS,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_kit(
        self,
        request: pb.GetKitRequest,
        _ctx: RequestContext[pb.GetKitRequest, pb.Kit],
    ) -> pb.Kit:
        _view(request.view, default=ResourceView.FULL)
        reader = self.reader()
        record = await _resource_record(
            reader.kits_table,
            KitDefinitionRecord,
            "key",
            Collection.KITS,
            request.name,
        )
        rows = reader_models._kit_rows(await reader._metadata_snapshot())
        row = next((item for item in rows if item.key == record.key), None)
        assert row is not None, f"indexed kit {record.key!r} is missing from metadata"
        return _kit(row)

    @_invalid_arguments
    async def list_identifier_definitions(
        self,
        request: pb.ListIdentifierDefinitionsRequest,
        _ctx: RequestContext[
            pb.ListIdentifierDefinitionsRequest,
            pb.ListIdentifierDefinitionsResponse,
        ],
    ) -> pb.ListIdentifierDefinitionsResponse:
        page = self._page(
            Collection.IDENTIFIER_DEFINITIONS,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
            view=request.view,
        )
        filters = _Filter.parse(request.filter)
        display_order = request.order_by == "display_name" or request.order_by.startswith(
            "display_name "
        )
        if display_order:
            _, direction = _order(request.order_by, {"display_name": "display_name"})
            sort = None
        else:
            sort, direction = _order(request.order_by, _IDENTIFIER_ORDER)
        identifier_kind = filters.enum("kind", IdentifierKind)
        assert identifier_kind not in {
            IdentifierKind.RACE,
            IdentifierKind.CLASS,
            IdentifierKind.KIT,
        }, "kind must name a simple identifier definition"
        query = IdentifierQuery(
            q=filters.search,
            kind=identifier_kind,
            sort=sort,
            direction=direction if sort is not None else "asc",
        )
        filters.finish()

        async def load(page_number: int) -> _ReaderPage[IdentifierRow]:
            return await self.reader().identifiers(
                query.model_copy(update={"page": page_number, "page_size": _READER_PAGE_SIZE})
            )

        if display_order:
            all_rows = await _all_rows(load)
            all_rows.sort(
                key=lambda row: _identifier(row).display_name.casefold(),
                reverse=direction == "desc",
            )
            total = len(all_rows)
            rows = all_rows[page.offset : page.offset + page.size]
        else:
            rows, total = await _window(page.offset, page.size, load)
        return pb.ListIdentifierDefinitionsResponse(
            identifier_definitions=[_identifier(row) for row in rows],
            next_page_token=_next_token(
                Collection.IDENTIFIER_DEFINITIONS,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_identifier_definition(
        self,
        request: pb.GetIdentifierDefinitionRequest,
        _ctx: RequestContext[pb.GetIdentifierDefinitionRequest, pb.IdentifierDefinition],
    ) -> pb.IdentifierDefinition:
        _view(request.view, default=ResourceView.FULL)
        record = await _resource_record(
            self.reader().identifiers_table,
            IdentifierDefinitionRecord,
            "key",
            Collection.IDENTIFIER_DEFINITIONS,
            request.name,
        )
        return _identifier(IdentifierRow.model_validate(record, from_attributes=True))

    @_invalid_arguments
    async def list_campaigns(
        self,
        request: pb.ListCampaignsRequest,
        _ctx: RequestContext[pb.ListCampaignsRequest, pb.ListCampaignsResponse],
    ) -> pb.ListCampaignsResponse:
        page = self._page(
            Collection.CAMPAIGNS,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
            view=request.view,
        )
        filters = _Filter.parse(request.filter)
        filters.finish()
        sort, direction = _order(
            request.order_by,
            {
                "campaign_id": "campaign_id",
                "display_name": "campaign_id",
                "ordinal": "ordinal",
            },
        )
        rows = await _campaign_rows(self.reader())
        if filters.search is not None:
            search = filters.search.casefold()
            rows = [
                row
                for row in rows
                if search in f"{row.campaign_id} {row.source_resource}".casefold()
            ]
        field_name = sort or "ordinal"
        rows.sort(
            key=lambda row: row.ordinal if field_name == "ordinal" else row.campaign_id.casefold(),
            reverse=direction == "desc",
        )
        total = len(rows)
        selected = rows[page.offset : page.offset + page.size]
        return pb.ListCampaignsResponse(
            campaigns=[_campaign(row) for row in selected],
            next_page_token=_next_token(
                Collection.CAMPAIGNS,
                request.filter,
                request.order_by,
                page,
                len(selected),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_campaign(
        self,
        request: pb.GetCampaignRequest,
        _ctx: RequestContext[pb.GetCampaignRequest, pb.Campaign],
    ) -> pb.Campaign:
        _view(request.view, default=ResourceView.FULL)
        row = await _resource_record(
            self.reader().campaigns_table,
            CampaignDefinitionRecord,
            "campaign_id",
            Collection.CAMPAIGNS,
            request.name,
        )
        return _campaign(row)

    @_invalid_arguments
    async def list_extraction_runs(
        self,
        request: pb.ListExtractionRunsRequest,
        _ctx: RequestContext[
            pb.ListExtractionRunsRequest,
            pb.ListExtractionRunsResponse,
        ],
    ) -> pb.ListExtractionRunsResponse:
        page = self._page(
            Collection.EXTRACTION_RUNS,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
            view=request.view,
        )
        filters = _Filter.parse(request.filter)
        filters.finish()
        sort, direction = _order(
            request.order_by,
            {
                "started_at": "started_at",
                "completed_at": "completed_at",
                "run_kind": "run_kind",
                "status": "status",
            },
        )
        rows = await _run_rows(self.reader())
        if filters.search is not None:
            search = filters.search.casefold()
            rows = [
                row
                for row in rows
                if search
                in " ".join((row.id, row.run_kind, row.status, row.error or "")).casefold()
            ]
        field_name = sort or "started_at"
        rows.sort(
            key=lambda row: (
                row.started_at
                if field_name == "started_at"
                else row.completed_at or ""
                if field_name == "completed_at"
                else row.run_kind
                if field_name == "run_kind"
                else row.status
            ),
            reverse=(direction == "desc" if sort is not None else True),
        )
        total = len(rows)
        selected = rows[page.offset : page.offset + page.size]
        return pb.ListExtractionRunsResponse(
            extraction_runs=[_run(row) for row in selected],
            next_page_token=_next_token(
                Collection.EXTRACTION_RUNS,
                request.filter,
                request.order_by,
                page,
                len(selected),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_extraction_run(
        self,
        request: pb.GetExtractionRunRequest,
        _ctx: RequestContext[pb.GetExtractionRunRequest, pb.ExtractionRun],
    ) -> pb.ExtractionRun:
        _view(request.view, default=ResourceView.FULL)
        row = await _resource_record(
            self.reader().runs_table,
            ExtractionRunRecord,
            "id",
            Collection.EXTRACTION_RUNS,
            request.name,
        )
        return _run(row)
