"""Shared filtering, ordering, and pagination for LanceDB reads."""

import asyncio
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from operator import attrgetter
from typing import cast

from lancedb.expr import Expr, col, lit
from lancedb.pydantic import LanceModel
from lancedb.query import BooleanQuery, ColumnOrdering, FullTextOperator, MatchQuery, Occur
from lancedb.table import AsyncTable

from bgvoice.reader_models import (
    ChildParentColumn,
    PageQuery,
    SortDirection,
    StableColumn,
)

_SEARCH_TOKEN = re.compile(r"[\w-]+", re.UNICODE)


def browse_order[Row](
    rows: Sequence[Row],
    sort: str,
    direction: SortDirection,
    scores: Mapping[str, float],
    key_of: Callable[[Row], str],
) -> list[Row]:
    if sort == "relevance":
        return sorted(rows, key=lambda row: (-scores[key_of(row)], key_of(row)))
    return field_order(rows, sort, direction, key_of)


def field_order[Row](
    rows: Sequence[Row],
    column: str,
    direction: SortDirection,
    key_of: Callable[[Row], str],
) -> list[Row]:
    non_null = [row for row in rows if getattr(row, column) is not None]
    null = sorted(
        (row for row in rows if getattr(row, column) is None),
        key=key_of,
    )
    non_null.sort(key=key_of)
    non_null.sort(key=attrgetter(column), reverse=direction == "desc")
    return [*non_null, *null]


def page_items[Row](rows: Sequence[Row], query: PageQuery) -> list[Row]:
    offset = (query.page - 1) * query.page_size
    return list(rows[offset : offset + query.page_size])


async def records_all[Record: LanceModel, SearchRecord: LanceModel](
    *,
    table: AsyncTable,
    model: type[Record],
    search_model: type[SearchRecord],
    tokens: tuple[str, ...],
    predicate: Expr | None,
    key_of: Callable[[Record], str],
    score_of: Callable[[SearchRecord], float],
) -> tuple[list[Record], dict[str, float]]:
    if not tokens:
        query = table.query()
        if predicate is not None:
            query = query.where(predicate)
        rows = cast(list[Record], await query.to_pydantic(model))
        return rows, {}

    limit = await table.count_rows(predicate.to_sql() if predicate is not None else None)
    if limit == 0:
        return [], {}
    search = table.query().nearest_to_text(fts_query(tokens))
    if predicate is not None:
        search = search.where(predicate)
    scored = cast(
        list[SearchRecord],
        await search.limit(limit).select([*model.model_fields, "_score"]).to_pydantic(search_model),
    )
    records = [model.model_validate(row.model_dump(exclude={"score"})) for row in scored]
    return records, {
        key_of(record): score_of(row) for record, row in zip(records, scored, strict=True)
    }


async def records_page[Record: LanceModel](
    *,
    table: AsyncTable,
    model: type[Record],
    stable_column: StableColumn,
    predicate: Expr | None,
    tokens: tuple[str, ...],
    ordering: list[ColumnOrdering] | None,
    page: PageQuery,
) -> tuple[int, list[Record]]:
    """Run the typed pagination path shared by record-backed browser tables."""
    if tokens:
        return await _search_page(
            table=table,
            model=model,
            stable_column=stable_column,
            predicate=predicate,
            tokens=tokens,
            ordering=ordering,
            page=page,
        )
    return await _ordered_page(
        table=table,
        model=model,
        predicate=predicate,
        ordering=ordering,
        page=page,
    )


async def _ordered_page[Record: LanceModel](
    *,
    table: AsyncTable,
    model: type[Record],
    predicate: Expr | None,
    ordering: list[ColumnOrdering] | None,
    page: PageQuery,
) -> tuple[int, list[Record]]:
    assert ordering is not None, "non-search browse requires deterministic ordering"
    page_query = table.query()
    if predicate is not None:
        page_query = page_query.where(predicate)
    total, record_rows = await asyncio.gather(
        table.count_rows(predicate.to_sql() if predicate is not None else None),
        page_query.order_by(ordering)
        .offset((page.page - 1) * page.page_size)
        .limit(page.page_size)
        .to_pydantic(model),
    )
    return total, cast(list[Record], record_rows)


async def _search_page[Record: LanceModel](
    *,
    table: AsyncTable,
    model: type[Record],
    stable_column: StableColumn,
    predicate: Expr | None,
    tokens: tuple[str, ...],
    ordering: list[ColumnOrdering] | None,
    page: PageQuery,
) -> tuple[int, list[Record]]:
    limit = await table.count_rows(predicate.to_sql() if predicate is not None else None)
    if limit == 0:
        return 0, []
    search = table.query().nearest_to_text(fts_query(tokens))
    if predicate is not None:
        search = search.where(predicate)
    columns = [stable_column, *(item.column_name for item in ordering or []), "_score"]
    matches = await search.limit(limit).select(list(dict.fromkeys(columns))).to_arrow()
    arrow_order = (
        [("_score", "descending", "at_end"), (stable_column, "ascending", "at_end")]
        if ordering is None
        else [
            (
                item.column_name,
                "ascending" if item.ascending else "descending",
                "at_start" if item.nulls_first else "at_end",
            )
            for item in ordering
        ]
    )
    matches = matches.sort_by(arrow_order)
    offset = (page.page - 1) * page.page_size
    page_keys = cast(
        list[str],
        matches.column(stable_column).slice(offset, page.page_size).to_pylist(),
    )
    if not page_keys:
        return cast(int, matches.num_rows), []

    records = cast(
        list[Record],
        await table.query()
        .where(col(stable_column).isin(page_keys))
        .limit(len(page_keys))
        .to_pydantic(model),
    )
    by_key = {cast(str, getattr(record, stable_column)): record for record in records}
    assert by_key.keys() == set(page_keys), "search projection lost indexed records"
    return cast(int, matches.num_rows), [by_key[key] for key in page_keys]


def child_generation_predicate(
    parent_column: ChildParentColumn,
    parents: Iterable[tuple[str, str]],
) -> Expr | None:
    names_by_run: dict[str, list[str]] = defaultdict(list)
    for resource_name, run_id in parents:
        names_by_run[run_id].append(resource_name)
    predicates = [
        (col("run_id") == lit(run_id)) & col(parent_column).isin(resource_names)
        for run_id, resource_names in names_by_run.items()
    ]
    if not predicates:
        return None
    result = predicates[0]
    for predicate in predicates[1:]:
        result |= predicate
    return result


async def count_rows(table: AsyncTable, predicate: Expr | None) -> int:
    return 0 if predicate is None else await table.count_rows(predicate.to_sql())


def combine(conditions: list[Expr]) -> Expr | None:
    if not conditions:
        return None
    predicate = conditions[0]
    for condition in conditions[1:]:
        predicate &= condition
    return predicate


def search_tokens(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(match.group(0) for match in _SEARCH_TOKEN.finditer(value.strip()))


def fts_query(tokens: tuple[str, ...]) -> BooleanQuery:
    assert tokens
    return BooleanQuery(
        [
            (
                Occur.MUST,
                MatchQuery(token, "search_text", operator=FullTextOperator.AND),
            )
            for token in tokens
        ]
    )


def ordering(column: str, direction: SortDirection, stable_column: str) -> list[ColumnOrdering]:
    ordering = [
        ColumnOrdering(
            column_name=column,
            ascending=direction == "asc",
            nulls_first=False,
        )
    ]
    if column != stable_column:
        ordering.append(
            ColumnOrdering(
                column_name=stable_column,
                ascending=True,
                nulls_first=False,
            )
        )
    return ordering


def page_count(total: int, page_size: int) -> int:
    return max(1, (total + page_size - 1) // page_size)
