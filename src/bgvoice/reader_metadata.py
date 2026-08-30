"""Metadata-backed labels and browser projections."""

from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from lancedb.expr import Expr
from lancedb.pydantic import LanceModel
from lancedb.table import AsyncTable
from pydantic import ConfigDict, Field

from bgvoice.model_types import (
    CampaignResourceKind,
    IdentifierKind,
)
from bgvoice.reader_models import ClassRow, KitRow, RaceCampaignTextRow, RaceRow
from bgvoice.reader_query import fts_query
from bgvoice.storage_records import (
    CampaignDefinitionRecord,
    CampaignResourceBindingRecord,
    ClassTextRecord,
    FavoredEnemyRecord,
    IdentifierDefinitionRecord,
    KitDefinitionRecord,
    RaceTextRecord,
    SoundSlotGroupRecord,
)


class _MetadataScore(LanceModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    key: str
    score: float = Field(alias="_score")


@dataclass(frozen=True, slots=True)
class MetadataSnapshot:
    identifiers: list[IdentifierDefinitionRecord]
    campaigns: list[CampaignDefinitionRecord]
    bindings: list[CampaignResourceBindingRecord]
    race_texts: list[RaceTextRecord]
    class_texts: list[ClassTextRecord]
    kits: list[KitDefinitionRecord]
    favored_enemies: list[FavoredEnemyRecord]


@dataclass(frozen=True, slots=True)
class LabelResolver:
    symbols: Mapping[tuple[IdentifierKind, int], tuple[str, ...]]
    race_labels: Mapping[int, str]
    class_labels: Mapping[int, str]
    race_descriptions: Mapping[int, str]
    class_descriptions: Mapping[int, str]
    kit_names: Mapping[int, str]
    favored_enemy_labels: Mapping[int, str]

    @classmethod
    def from_snapshot(cls, metadata: MetadataSnapshot) -> LabelResolver:
        symbols = identifier_symbols(metadata.identifiers)
        return cls(
            symbols=symbols,
            race_labels=_race_labels(metadata, symbols),
            class_labels=_class_labels(metadata, symbols),
            race_descriptions=_race_descriptions(metadata),
            class_descriptions=_class_descriptions(metadata),
            kit_names=_kit_names(metadata.kits),
            favored_enemy_labels=_favored_enemy_labels(metadata.favored_enemies),
        )

    def identifier_label(self, kind: IdentifierKind, value: int) -> str:
        return _symbol_label(self.symbols.get((kind, value), ()), value)

    def optional_identifier_label(
        self,
        kind: IdentifierKind,
        value: int | None,
    ) -> str | None:
        return None if value is None else self.identifier_label(kind, value)

    def identifier_labels(self, kind: IdentifierKind) -> dict[int, str]:
        return {
            value: _symbol_label(symbols, value)
            for (symbol_kind, value), symbols in self.symbols.items()
            if symbol_kind is kind
        }

    def race_label(self, value: int) -> str:
        return self.race_labels.get(
            value,
            self.identifier_label(IdentifierKind.RACE, value),
        )

    def class_label(self, value: int) -> str:
        return self.class_labels.get(
            value,
            self.identifier_label(IdentifierKind.CLASS, value),
        )

    def race_description(self, value: int) -> str | None:
        return self.race_descriptions.get(value)

    def class_description(self, value: int) -> str | None:
        return self.class_descriptions.get(value)

    def favored_enemy_label(self, value: int) -> str:
        return self.favored_enemy_labels.get(value, self.race_label(value))

    def kit_label(self, value: int | None, class_id: int | None) -> str | None:
        if value is None:
            return None
        if value == 0x4000:
            return "Generalist" if class_id == 1 else "Trueclass"
        if value in self.kit_names:
            return self.kit_names[value]
        return self.identifier_label(IdentifierKind.KIT, value)


def _race_labels(
    metadata: MetadataSnapshot,
    symbols: Mapping[tuple[IdentifierKind, int], tuple[str, ...]],
) -> dict[int, str]:
    rows = _group_by(metadata.race_texts, lambda row: row.race_id)
    labels = _text_labels(
        rows,
        symbols,
        IdentifierKind.RACE,
        _campaign_resources(metadata.bindings, CampaignResourceKind.RACE_TEXT, "SOA"),
        lambda row: row.name,
    )
    lore_labels = _favored_enemy_labels(metadata.favored_enemies)
    for race_id in {row.race_id for row in metadata.favored_enemies}:
        if not any(row.name is not None for row in rows.get(race_id, [])):
            labels[race_id] = lore_labels.get(race_id) or _symbol_label(
                symbols.get((IdentifierKind.RACE, race_id), ()),
                race_id,
            )
    return labels


def _class_labels(
    metadata: MetadataSnapshot,
    symbols: Mapping[tuple[IdentifierKind, int], tuple[str, ...]],
) -> dict[int, str]:
    rows = _group_by(
        (row for row in metadata.class_texts if not row.fallen and row.class_text_kit_id == 0x4000),
        lambda row: row.class_id,
    )
    return _text_labels(
        rows,
        symbols,
        IdentifierKind.CLASS,
        _campaign_resources(metadata.bindings, CampaignResourceKind.CLASS_TEXT, "SOA"),
        lambda row: row.mixed_name or row.lower_name,
    )


def _race_descriptions(metadata: MetadataSnapshot) -> dict[int, str]:
    preferred = _campaign_resources(metadata.bindings, CampaignResourceKind.RACE_TEXT, "SOA")
    race_texts = _group_by(metadata.race_texts, lambda row: row.race_id)
    lore = _group_by(metadata.favored_enemies, lambda row: row.race_id)
    descriptions: dict[int, str] = {}
    for race_id in race_texts.keys() | lore.keys():
        description = _preferred_text(
            race_texts.get(race_id, []),
            preferred,
            lambda row: row.description,
        )
        if description is None:
            description = next(
                (
                    row.help_text.strip()
                    for row in sorted(lore.get(race_id, []), key=lambda row: (row.ordinal, row.key))
                    if row.help_text is not None and row.help_text.strip()
                ),
                None,
            )
        if description is not None:
            descriptions[race_id] = description
    return descriptions


def _class_descriptions(metadata: MetadataSnapshot) -> dict[int, str]:
    preferred = _campaign_resources(metadata.bindings, CampaignResourceKind.CLASS_TEXT, "SOA")
    rows = _group_by(
        (row for row in metadata.class_texts if not row.fallen and row.class_text_kit_id == 0x4000),
        lambda row: row.class_id,
    )
    descriptions: dict[int, str] = {}
    for class_id, class_rows in rows.items():
        description = _preferred_text(class_rows, preferred, lambda row: row.description)
        if description is not None:
            descriptions[class_id] = description
    return descriptions


def _preferred_text[Row: RaceTextRecord | ClassTextRecord](
    rows: Sequence[Row],
    preferred_resources: frozenset[str],
    text: Callable[[Row], str | None],
) -> str | None:
    ordered = sorted(
        rows,
        key=lambda row: (
            _resource_key(row.source_resource) not in preferred_resources,
            row.source_resource.casefold(),
            row.ordinal,
            row.key,
        ),
    )
    for row in ordered:
        value = text(row)
        if value is not None and value.strip():
            return value.strip()
    return None


def _text_labels[Row: RaceTextRecord | ClassTextRecord](
    rows: Mapping[int, list[Row]],
    symbols: Mapping[tuple[IdentifierKind, int], tuple[str, ...]],
    kind: IdentifierKind,
    preferred_resources: frozenset[str],
    text: Callable[[Row], str | None],
) -> dict[int, str]:
    ids = {value for symbol_kind, value in symbols if symbol_kind is kind} | rows.keys()
    labels: dict[int, str] = {}
    for row_id in ids:
        candidates = rows.get(row_id, [])
        preferred = [
            row for row in candidates if _resource_key(row.source_resource) in preferred_resources
        ]
        values = _distinct_text(text(row) for row in preferred or candidates)
        labels[row_id] = (
            values[0]
            if len(values) == 1
            else _symbol_label(symbols.get((kind, row_id), ()), row_id)
        )
    return labels


def _kit_names(rows: Iterable[KitDefinitionRecord]) -> dict[int, str]:
    by_value = _group_by(
        (row for row in rows if row.kit_ids_value is not None),
        lambda row: cast(int, row.kit_ids_value),
    )
    names = {
        value: _distinct_text(row.mixed_name or row.lower_name for row in grouped)
        for value, grouped in by_value.items()
    }
    return {value: values[0] for value, values in names.items() if len(values) == 1}


def _favored_enemy_labels(rows: Iterable[FavoredEnemyRecord]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for row in sorted(rows, key=lambda row: (row.ordinal, row.key)):
        if row.name is not None:
            labels.setdefault(row.race_id, row.name)
    return labels


def _group_by[Row, Key: Hashable](
    rows: Iterable[Row],
    key: Callable[[Row], Key],
) -> dict[Key, list[Row]]:
    grouped: dict[Key, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    return dict(grouped)


def race_rows(metadata: MetadataSnapshot) -> list[RaceRow]:
    symbols = identifier_symbols(metadata.identifiers)
    race_symbols = {
        value: list(aliases)
        for (kind, value), aliases in symbols.items()
        if kind is IdentifierKind.RACE
    }
    campaigns = _campaigns_by_resource(metadata, CampaignResourceKind.RACE_TEXT)
    text_rows: dict[int, list[RaceTextRecord]] = defaultdict(list)
    for row in metadata.race_texts:
        text_rows[row.race_id].append(row)
    lore_rows = _group_by(metadata.favored_enemies, lambda row: row.race_id)
    labels = _race_labels(metadata, symbols)

    rows: list[RaceRow] = []
    for race_id in sorted(set(race_symbols) | set(text_rows) | set(lore_rows)):
        campaign_texts = [
            RaceCampaignTextRow(
                record=row,
                campaigns=campaigns.get(_resource_key(row.source_resource), []),
            )
            for row in sorted(
                text_rows.get(race_id, []),
                key=lambda row: (row.source_resource.casefold(), row.ordinal, row.key),
            )
        ]
        lore = min(
            lore_rows.get(race_id, []),
            key=lambda row: (row.ordinal, row.key),
            default=None,
        )
        rows.append(
            RaceRow(
                key=f"race:{race_id}",
                race_id=race_id,
                symbols=race_symbols.get(race_id, []),
                display_name=labels[race_id],
                campaign_texts=campaign_texts,
                lore=lore,
            )
        )
    return rows


def class_rows(metadata: MetadataSnapshot) -> list[ClassRow]:
    symbols = identifier_symbols(metadata.identifiers)
    class_symbols = {
        value: list(aliases)
        for (kind, value), aliases in symbols.items()
        if kind is IdentifierKind.CLASS
    }
    campaigns = _campaigns_by_resource(metadata, CampaignResourceKind.CLASS_TEXT)
    text_rows: dict[int, list[ClassTextRecord]] = defaultdict(list)
    for row in metadata.class_texts:
        text_rows[row.class_id].append(row)

    rows: list[ClassRow] = []
    for class_id in sorted(set(class_symbols) | set(text_rows)):
        details = sorted(
            text_rows.get(class_id, []),
            key=lambda row: (row.source_resource.casefold(), row.ordinal, row.key),
        )
        if not details:
            rows.append(
                ClassRow(
                    key=f"class:{class_id}",
                    class_id=class_id,
                    symbols=class_symbols.get(class_id, []),
                    source_resource=None,
                    ordinal=None,
                    campaigns=[],
                    row_name=None,
                    class_text_kit_id=None,
                    lower_name_strref=None,
                    lower_name=None,
                    description_strref=None,
                    description=None,
                    mixed_name_strref=None,
                    mixed_name=None,
                    biography_strref=None,
                    biography=None,
                    fallen=None,
                    brief_description_strref=None,
                    brief_description=None,
                    fallen_notice_strref=None,
                    fallen_notice=None,
                )
            )
            continue
        rows.extend(
            ClassRow(
                key=row.key,
                class_id=class_id,
                symbols=class_symbols.get(class_id, []),
                source_resource=row.source_resource,
                ordinal=row.ordinal,
                campaigns=campaigns.get(_resource_key(row.source_resource), []),
                row_name=row.row_name,
                class_text_kit_id=row.class_text_kit_id,
                lower_name_strref=row.lower_name_strref,
                lower_name=row.lower_name,
                description_strref=row.description_strref,
                description=row.description,
                mixed_name_strref=row.mixed_name_strref,
                mixed_name=row.mixed_name,
                biography_strref=row.biography_strref,
                biography=row.biography,
                fallen=row.fallen,
                brief_description_strref=row.brief_description_strref,
                brief_description=row.brief_description,
                fallen_notice_strref=row.fallen_notice_strref,
                fallen_notice=row.fallen_notice,
            )
            for row in details
        )
    return rows


def kit_rows(metadata: MetadataSnapshot) -> list[KitRow]:
    symbols = identifier_symbols(metadata.identifiers)
    return [
        KitRow(
            key=row.key,
            source_resource=row.source_resource,
            ordinal=row.ordinal,
            row_id=row.row_id,
            row_name=row.row_name,
            lower_name_strref=row.lower_name_strref,
            lower_name=row.lower_name,
            mixed_name_strref=row.mixed_name_strref,
            mixed_name=row.mixed_name,
            help_strref=row.help_strref,
            help_text=row.help_text,
            abilities_resref=row.abilities,
            proficiency_column=row.proficiency,
            unusable_mask=row.unusable,
            class_id=row.class_id,
            class_symbols=(
                []
                if row.class_id is None
                else list(symbols.get((IdentifierKind.CLASS, row.class_id), ()))
            ),
            kit_ids_value=row.kit_ids_value,
            kit_symbols=(
                []
                if row.kit_ids_value is None
                else list(symbols.get((IdentifierKind.KIT, row.kit_ids_value), ()))
            ),
            class_text_kit_id=row.class_text_kit_id,
        )
        for row in sorted(metadata.kits, key=lambda row: (row.row_id, row.key))
    ]


def identifier_symbols(
    definitions: Sequence[IdentifierDefinitionRecord],
) -> dict[tuple[IdentifierKind, int], tuple[str, ...]]:
    values: dict[tuple[IdentifierKind, int], list[str]] = defaultdict(list)
    for row in sorted(definitions, key=lambda row: (row.source_resource, row.ordinal, row.key)):
        aliases = values[(row.kind, row.value)]
        aliases.extend(symbol for symbol in row.symbols if symbol not in aliases)
    return {key: tuple(aliases) for key, aliases in values.items()}


def sound_slot_group_names(
    groups: Sequence[SoundSlotGroupRecord],
    slot_id: int,
) -> list[str]:
    return [
        group.row_name
        for group in sorted(groups, key=lambda group: (group.ordinal, group.key))
        if group.offset is not None
        and group.count is not None
        and group.offset <= slot_id < group.offset + group.count
    ]


def _campaigns_by_resource(
    metadata: MetadataSnapshot,
    kind: CampaignResourceKind,
) -> dict[str, list[str]]:
    order = {
        row.campaign_id.casefold(): (row.ordinal, row.campaign_id.casefold())
        for row in metadata.campaigns
    }
    values: dict[str, list[str]] = defaultdict(list)
    for row in metadata.bindings:
        if row.resource_kind is not kind or row.resource_resref is None:
            continue
        campaigns = values[_resource_key(row.resource_resref)]
        if row.campaign_id not in campaigns:
            campaigns.append(row.campaign_id)
    for campaigns in values.values():
        campaigns.sort(key=lambda value: order.get(value.casefold(), (2**31, value.casefold())))
    return dict(values)


def _campaign_resources(
    bindings: Sequence[CampaignResourceBindingRecord],
    kind: CampaignResourceKind,
    campaign_id: str,
) -> frozenset[str]:
    return frozenset(
        _resource_key(row.resource_resref)
        for row in bindings
        if row.resource_kind is kind
        and row.campaign_id.casefold() == campaign_id.casefold()
        and row.resource_resref is not None
    )


def _distinct_text(values: Iterable[str | None]) -> list[str]:
    distinct: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None or not value.strip():
            continue
        key = value.strip().casefold()
        if key not in seen:
            seen.add(key)
            distinct.append(value.strip())
    return distinct


def _resource_key(value: str) -> str:
    return value.casefold().removesuffix(".2da")


def _symbol_label(symbols: Sequence[str], value: int) -> str:
    if not symbols:
        return f"Unknown ({value})"
    return " / ".join(
        " ".join(part.capitalize() for part in symbol.replace("-", "_").split("_") if part)
        for symbol in symbols
    )


async def fts_scores(
    table: AsyncTable,
    tokens: tuple[str, ...],
    predicate: Expr | None = None,
) -> dict[str, float]:
    assert tokens
    count = await table.count_rows(predicate.to_sql() if predicate is not None else None)
    if count == 0:
        return {}
    query = table.query().nearest_to_text(fts_query(tokens))
    if predicate is not None:
        query = query.where(predicate)
    rows = cast(
        list[_MetadataScore],
        await query.limit(count).select(["key", "_score"]).to_pydantic(_MetadataScore),
    )
    return {row.key: row.score for row in rows}


def identifier_value_scores(
    metadata: MetadataSnapshot,
    key_scores: Mapping[str, float],
    kind: IdentifierKind,
) -> dict[int, float]:
    scores: dict[int, float] = {}
    for row in metadata.identifiers:
        if row.kind is kind and row.key in key_scores:
            scores[row.value] = max(scores.get(row.value, float("-inf")), key_scores[row.key])
    return scores
