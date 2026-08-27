"""Read-only HTTP API and production SPA host for pipeline inspection."""

import asyncio
import re
from collections import Counter
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal, cast

import lancedb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from lancedb.db import AsyncConnection
from lancedb.expr import Expr, col, lit
from lancedb.pydantic import LanceModel
from lancedb.query import AsyncFTSQuery, BooleanQuery, ColumnOrdering, MatchQuery, Occur
from lancedb.table import AsyncTable
from pydantic import BaseModel, ConfigDict, Field

from bgvoice.database import (
    TABLE_INDEXES,
    TABLE_NAMES,
    CharacterRecord,
    DialogueLineRecord,
    DialogueRecord,
    ExtractionRunRecord,
)
from bgvoice.models import (
    AttributionStatus,
    CharacterDetail,
    DetailStatus,
    DialogueDetail,
    DialogueLineKind,
    RunKind,
    RunStatus,
    SourceKind,
)

type CharacterSort = Literal[
    "resource_name",
    "display_name",
    "source_kind",
    "serialized_size",
    "dialogue_line_count",
    "npc_line_count",
    "player_line_count",
    "dialogue_state_count",
    "dialogue_transition_count",
    "updated_at",
]
type DialogueSort = Literal[
    "resource_name",
    "source_kind",
    "serialized_size",
    "dialogue_line_count",
    "npc_line_count",
    "player_line_count",
    "character_count",
    "updated_at",
]
type LineSort = Literal[
    "dialogue_resource_name",
    "line_kind",
    "strref",
    "serialized_size",
    "state_index",
    "transition_index",
]
type SortDirection = Literal["asc", "desc"]
type StableColumn = Literal["resource_name", "id"]

_SEARCH_TOKEN = re.compile(r"[\w-]+", re.UNICODE)


class ApiModel(BaseModel):
    """Strict response model for the HTTP boundary."""

    model_config = ConfigDict(strict=True, extra="forbid")


class PageQuery(BaseModel):
    """Shared pagination fields accepted from URL query strings."""

    model_config = ConfigDict(strict=False, extra="forbid")

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=10, le=100)


class CharacterQuery(PageQuery):
    q: str | None = Field(default=None, max_length=200)
    status: DetailStatus | None = None
    source_kind: SourceKind | None = None
    has_dialog: bool | None = None
    gender_id: int | None = Field(default=None, ge=0)
    race_id: int | None = Field(default=None, ge=0)
    class_id: int | None = Field(default=None, ge=0)
    attribution_status: AttributionStatus | None = None
    sort: CharacterSort | None = None
    direction: SortDirection = "desc"


class DialogueQuery(PageQuery):
    q: str | None = Field(default=None, max_length=200)
    status: DetailStatus | None = None
    source_kind: SourceKind | None = None
    attributed: bool | None = None
    sort: DialogueSort | None = None
    direction: SortDirection = "desc"


class LineQuery(PageQuery):
    q: str | None = Field(default=None, max_length=300)
    line_kind: DialogueLineKind | None = None
    source_kind: SourceKind | None = None
    attributed: bool | None = None
    sort: LineSort | None = None
    direction: SortDirection = "desc"


class CharacterRow(ApiModel):
    resource_name: str
    display_name: str | None
    resref: str
    source_kind: SourceKind
    dialog_resref: str | None
    gender_id: int | None
    race_id: int | None
    class_id: int | None
    detail_status: DetailStatus
    detail_error: str | None
    attribution_status: AttributionStatus | None
    serialized_size: int | None
    dialogue_status: DetailStatus | None
    dialogue_line_count: int | None
    npc_line_count: int | None
    player_line_count: int | None
    journal_line_count: int | None
    dialogue_state_count: int | None
    dialogue_transition_count: int | None
    dialogue_serialized_size: int | None
    updated_at: str


class CharacterPage(ApiModel):
    items: list[CharacterRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: CharacterSort | Literal["relevance"]
    direction: SortDirection


class DialogueRow(ApiModel):
    resource_name: str
    resref: str
    source_kind: SourceKind
    source_path: str
    detail_status: DetailStatus
    detail_error: str | None
    serialized_size: int | None
    dialogue_line_count: int | None
    npc_line_count: int | None
    player_line_count: int | None
    journal_line_count: int | None
    character_count: int
    updated_at: str


class DialoguePage(ApiModel):
    items: list[DialogueRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: DialogueSort | Literal["relevance"]
    direction: SortDirection


class DialogueLineRow(ApiModel):
    id: str
    dialogue_resource_name: str
    dialogue_resref: str
    source_kind: SourceKind
    line_kind: DialogueLineKind
    state_index: int
    transition_index: int | None
    strref: int
    text: str | None
    serialized_size: int
    character_count: int


class DialogueLinePage(ApiModel):
    items: list[DialogueLineRow]
    page: int
    page_size: int
    total: int
    page_count: int
    sort: LineSort | Literal["relevance"]
    direction: SortDirection


class FacetValue(ApiModel):
    value: str | int
    count: int = Field(ge=0)


class FilterOptions(ApiModel):
    source_kinds: list[FacetValue]
    gender_ids: list[FacetValue]
    race_ids: list[FacetValue]
    class_ids: list[FacetValue]


class ExtractionRunSummary(ApiModel):
    id: str
    run_kind: RunKind
    started_at: str
    completed_at: str | None
    status: RunStatus
    resources_discovered: int
    details_attempted: int
    details_extracted: int
    failures: int
    error: str | None


class PipelineStats(ApiModel):
    database_path: str
    database_size: int = Field(ge=0)
    characters_total: int = Field(ge=0)
    characters_complete: int = Field(ge=0)
    characters_failed: int = Field(ge=0)
    characters_with_dialogue: int = Field(ge=0)
    attribution_completed_at: str | None
    characters_unavailable: int = Field(ge=0)
    characters_matched: int = Field(ge=0)
    characters_missing_dialogue: int = Field(ge=0)
    characters_dialogue_failed: int = Field(ge=0)
    characters_without_dialogue: int = Field(ge=0)
    dialogues_total: int = Field(ge=0)
    dialogues_complete: int = Field(ge=0)
    dialogue_lines: int = Field(ge=0)
    line_records_total: int = Field(ge=0)
    dialogues_attributed: int = Field(ge=0)
    dialogues_unattributed: int = Field(ge=0)
    attributed_dialogue_lines: int = Field(ge=0)
    unattributed_dialogue_lines: int = Field(ge=0)
    latest_runs: list[ExtractionRunSummary]


class CharacterDetailResponse(ApiModel):
    character: CharacterDetail
    dialogue: DialogueDetail | None
    source_kind: SourceKind
    source_path: str
    character_serialized_size: int
    dialogue_serialized_size: int | None
    updated_at: str
    attribution_status: AttributionStatus | None


class HealthResponse(ApiModel):
    status: Literal["ok"]
    storage: Literal["lancedb"]


class _Projection(LanceModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class _AttributionMarker(_Projection):
    attribution_completed_at: str | None


class _CharacterStats(_AttributionMarker):
    detail_status: DetailStatus = Field(strict=False)
    has_dialog: bool
    attribution_status: AttributionStatus | None = Field(strict=False)


class _DialogueStats(_Projection):
    detail_status: DetailStatus = Field(strict=False)
    dialogue_line_count: int | None
    character_count: int
    attribution_completed_at: str | None


class _CharacterFacets(_Projection):
    source_kind: SourceKind = Field(strict=False)
    gender_id: int | None
    race_id: int | None
    class_id: int | None


class _CharacterSearchResult(CharacterRecord):
    score: float = Field(alias="_score")


class _DialogueSearchResult(DialogueRecord):
    score: float = Field(alias="_score")


class _LineSearchResult(DialogueLineRecord):
    score: float = Field(alias="_score")


@dataclass(frozen=True, slots=True)
class PipelineReader:
    """Strongly consistent typed reads over one local LanceDB database."""

    path: Path
    _connection: AsyncConnection
    characters_table: AsyncTable
    dialogues_table: AsyncTable
    lines_table: AsyncTable
    runs_table: AsyncTable

    @classmethod
    async def open(cls, path: Path) -> PipelineReader:
        resolved_path = path.expanduser().resolve()
        assert resolved_path.is_dir(), f"pipeline database does not exist: {resolved_path}"
        connection = await lancedb.connect_async(
            resolved_path,
            read_consistency_interval=timedelta(0),
        )
        table_names = frozenset((await connection.list_tables(limit=None)).tables)
        assert table_names == TABLE_NAMES, (
            f"pipeline database tables are {sorted(table_names)}; "
            f"expected {sorted(TABLE_NAMES)}. Rebuild the generated database."
        )

        characters, dialogues, lines, runs = await asyncio.gather(
            connection.open_table("characters"),
            connection.open_table("dialogues"),
            connection.open_table("dialogue_lines"),
            connection.open_table("extraction_runs"),
        )
        character_schema, dialogue_schema, line_schema, run_schema = await asyncio.gather(
            characters.schema(),
            dialogues.schema(),
            lines.schema(),
            runs.schema(),
        )
        character_indexes, dialogue_indexes, line_indexes, run_indexes = await asyncio.gather(
            characters.list_indices(),
            dialogues.list_indices(),
            lines.list_indices(),
            runs.list_indices(),
        )
        assert character_schema.equals(CharacterRecord.to_arrow_schema(), check_metadata=True), (
            "characters table schema does not match CharacterRecord"
        )
        assert dialogue_schema.equals(DialogueRecord.to_arrow_schema(), check_metadata=True), (
            "dialogues table schema does not match DialogueRecord"
        )
        assert line_schema.equals(DialogueLineRecord.to_arrow_schema(), check_metadata=True), (
            "dialogue_lines table schema does not match DialogueLineRecord"
        )
        assert run_schema.equals(ExtractionRunRecord.to_arrow_schema(), check_metadata=True), (
            "extraction_runs table schema does not match ExtractionRunRecord"
        )
        actual_indexes = {
            "characters": frozenset(
                (index.name, index.index_type, tuple(index.columns)) for index in character_indexes
            ),
            "dialogues": frozenset(
                (index.name, index.index_type, tuple(index.columns)) for index in dialogue_indexes
            ),
            "dialogue_lines": frozenset(
                (index.name, index.index_type, tuple(index.columns)) for index in line_indexes
            ),
            "extraction_runs": frozenset(
                (index.name, index.index_type, tuple(index.columns)) for index in run_indexes
            ),
        }
        expected_indexes = {
            name: frozenset(
                (spec.name, type(spec.config).__name__, (spec.column,)) for spec in specs
            )
            for name, specs in TABLE_INDEXES.items()
        }
        assert actual_indexes == expected_indexes, (
            f"pipeline database indexes are {actual_indexes}; expected {expected_indexes}. "
            "Rebuild the generated database."
        )
        return cls(resolved_path, connection, characters, dialogues, lines, runs)

    def close(self) -> None:
        self._connection.close()

    def health(self) -> HealthResponse:
        return HealthResponse(status="ok", storage="lancedb")

    async def stats(self) -> PipelineStats:
        character_rows, dialogue_rows, run_rows, line_records_total = await asyncio.gather(
            self.characters_table.query()
            .select(list(_CharacterStats.model_fields))
            .to_pydantic(_CharacterStats),
            self.dialogues_table.query()
            .select(list(_DialogueStats.model_fields))
            .to_pydantic(_DialogueStats),
            self.runs_table.query()
            .order_by(
                [
                    ColumnOrdering(column_name="started_at", ascending=False, nulls_first=False),
                    ColumnOrdering(column_name="id", ascending=False, nulls_first=False),
                ]
            )
            .limit(8)
            .to_pydantic(ExtractionRunRecord),
            self.lines_table.count_rows(),
        )
        characters = cast(list[_CharacterStats], character_rows)
        dialogues = cast(list[_DialogueStats], dialogue_rows)
        latest_runs = cast(list[ExtractionRunRecord], run_rows)

        attribution_completed_at = _published_attribution_timestamp(characters)
        if attribution_completed_at is None:
            attribution_counts: Counter[AttributionStatus | None] = Counter()
            attributed_dialogues: list[_DialogueStats] = []
            unattributed_dialogues: list[_DialogueStats] = []
        else:
            attribution_counts = Counter(row.attribution_status for row in characters)
            attributed_dialogues = [
                row
                for row in dialogues
                if row.attribution_completed_at == attribution_completed_at
                and row.character_count > 0
            ]
            unattributed_dialogues = [
                row
                for row in dialogues
                if row.attribution_completed_at != attribution_completed_at
                or row.character_count == 0
            ]

        return PipelineStats(
            database_path=str(self.path),
            database_size=sum(
                file.stat().st_size for file in self.path.rglob("*") if file.is_file()
            ),
            characters_total=len(characters),
            characters_complete=sum(
                row.detail_status is DetailStatus.COMPLETE for row in characters
            ),
            characters_failed=sum(row.detail_status is DetailStatus.FAILED for row in characters),
            characters_with_dialogue=sum(row.has_dialog for row in characters),
            attribution_completed_at=attribution_completed_at,
            characters_unavailable=attribution_counts[AttributionStatus.CHARACTER_UNAVAILABLE],
            characters_matched=attribution_counts[AttributionStatus.MATCHED],
            characters_missing_dialogue=attribution_counts[AttributionStatus.MISSING_DIALOGUE],
            characters_dialogue_failed=attribution_counts[AttributionStatus.DIALOGUE_FAILED],
            characters_without_dialogue=attribution_counts[AttributionStatus.NO_DIALOGUE],
            dialogues_total=len(dialogues),
            dialogues_complete=sum(row.detail_status is DetailStatus.COMPLETE for row in dialogues),
            dialogue_lines=sum(row.dialogue_line_count or 0 for row in dialogues),
            line_records_total=line_records_total,
            dialogues_attributed=len(attributed_dialogues),
            dialogues_unattributed=len(unattributed_dialogues),
            attributed_dialogue_lines=sum(
                row.dialogue_line_count or 0 for row in attributed_dialogues
            ),
            unattributed_dialogue_lines=sum(
                row.dialogue_line_count or 0 for row in unattributed_dialogues
            ),
            latest_runs=[
                ExtractionRunSummary.model_validate(run, from_attributes=True)
                for run in latest_runs
            ],
        )

    async def filter_options(self) -> FilterOptions:
        characters = cast(
            list[_CharacterFacets],
            await self.characters_table.query()
            .select(list(_CharacterFacets.model_fields))
            .to_pydantic(_CharacterFacets),
        )
        return FilterOptions(
            source_kinds=_string_facets(row.source_kind for row in characters),
            gender_ids=_integer_facets(
                row.gender_id for row in characters if row.gender_id is not None
            ),
            race_ids=_integer_facets(row.race_id for row in characters if row.race_id is not None),
            class_ids=_integer_facets(
                row.class_id for row in characters if row.class_id is not None
            ),
        )

    async def _attribution_marker(self) -> str | None:
        rows = cast(
            list[_AttributionMarker],
            await self.characters_table.query()
            .select(list(_AttributionMarker.model_fields))
            .to_pydantic(_AttributionMarker),
        )
        return _published_attribution_timestamp(rows)

    async def characters(self, query: CharacterQuery) -> CharacterPage:
        conditions: list[Expr] = []
        if query.status is not None:
            conditions.append(col("detail_status") == lit(query.status))
        if query.source_kind is not None:
            conditions.append(col("source_kind") == lit(query.source_kind))
        if query.gender_id is not None:
            conditions.append(col("gender_id") == lit(query.gender_id))
        if query.race_id is not None:
            conditions.append(col("race_id") == lit(query.race_id))
        if query.class_id is not None:
            conditions.append(col("class_id") == lit(query.class_id))
        if query.attribution_status is not None:
            conditions.append(col("attribution_status") == lit(query.attribution_status))
        if query.has_dialog is not None:
            conditions.append(col("has_dialog") == lit(query.has_dialog))
        predicate = _combine(conditions)
        tokens = _search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "serialized_size")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        total, records = await _records_page(
            table=self.characters_table,
            model=CharacterRecord,
            search_model=_CharacterSearchResult,
            stable_column="resource_name",
            predicate=predicate,
            tokens=tokens,
            ordering=(None if sort == "relevance" else _ordering(sort, direction, "resource_name")),
            page=query,
        )

        return CharacterPage(
            items=[CharacterRow.model_validate(record, from_attributes=True) for record in records],
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=_page_count(total, query.page_size),
            sort=sort,
            direction=direction,
        )

    async def dialogues(self, query: DialogueQuery) -> DialoguePage:
        attribution_marker = await self._attribution_marker()
        conditions: list[Expr] = []
        if query.status is not None:
            conditions.append(col("detail_status") == lit(query.status))
        if query.source_kind is not None:
            conditions.append(col("source_kind") == lit(query.source_kind))
        if query.attributed is not None:
            conditions.append(_attribution_filter(query.attributed, attribution_marker))
        predicate = _combine(conditions)
        tokens = _search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "dialogue_line_count")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        total, records = await _records_page(
            table=self.dialogues_table,
            model=DialogueRecord,
            search_model=_DialogueSearchResult,
            stable_column="resource_name",
            predicate=predicate,
            tokens=tokens,
            ordering=(None if sort == "relevance" else _ordering(sort, direction, "resource_name")),
            page=query,
        )

        return DialoguePage(
            items=[
                DialogueRow.model_validate(
                    record.model_dump(include=set(DialogueRow.model_fields))
                    | {
                        "character_count": _published_character_count(
                            record.character_count,
                            record.attribution_completed_at,
                            attribution_marker,
                        )
                    }
                )
                for record in records
            ],
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=_page_count(total, query.page_size),
            sort=sort,
            direction=direction,
        )

    async def lines(self, query: LineQuery) -> DialogueLinePage:
        attribution_marker = await self._attribution_marker()
        conditions: list[Expr] = []
        if query.line_kind is not None:
            conditions.append(col("line_kind") == lit(query.line_kind))
        if query.source_kind is not None:
            conditions.append(col("source_kind") == lit(query.source_kind))
        if query.attributed is not None:
            conditions.append(_attribution_filter(query.attributed, attribution_marker))
        predicate = _combine(conditions)
        tokens = _search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "serialized_size")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        total, records = await _records_page(
            table=self.lines_table,
            model=DialogueLineRecord,
            search_model=_LineSearchResult,
            stable_column="id",
            predicate=predicate,
            tokens=tokens,
            ordering=None if sort == "relevance" else _ordering(sort, direction, "id"),
            page=query,
        )

        return DialogueLinePage(
            items=[
                DialogueLineRow.model_validate(
                    record.model_dump(include=set(DialogueLineRow.model_fields))
                    | {
                        "character_count": _published_character_count(
                            record.character_count,
                            record.attribution_completed_at,
                            attribution_marker,
                        )
                    }
                )
                for record in records
            ],
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=_page_count(total, query.page_size),
            sort=sort,
            direction=direction,
        )

    async def character_detail(self, resource_name: str) -> CharacterDetailResponse | None:
        records = cast(
            list[CharacterRecord],
            await self.characters_table.query()
            .where(col("resource_name") == lit(resource_name))
            .limit(1)
            .to_pydantic(CharacterRecord),
        )
        if not records or records[0].detail_status is not DetailStatus.COMPLETE:
            return None
        record = records[0]
        assert record.serialized_size is not None
        character = CharacterDetail.model_validate(record, from_attributes=True)

        dialogue: DialogueDetail | None = None
        if record.dialogue_status is DetailStatus.COMPLETE:
            assert record.dialog_resref is not None
            assert record.dialogue_state_count is not None
            assert record.dialogue_transition_count is not None
            assert record.npc_line_count is not None
            assert record.player_line_count is not None
            assert record.journal_line_count is not None
            assert record.dialogue_line_count is not None
            assert record.dialogue_serialized_size is not None
            dialogue = DialogueDetail(
                resource_name=f"{record.dialog_resref}.DLG",
                resref=record.dialog_resref,
                dlg_version="V1.0",
                state_count=record.dialogue_state_count,
                transition_count=record.dialogue_transition_count,
                npc_line_count=record.npc_line_count,
                player_line_count=record.player_line_count,
                journal_line_count=record.journal_line_count,
                dialogue_line_count=record.dialogue_line_count,
                pydantic_json_size=record.dialogue_serialized_size,
            )

        return CharacterDetailResponse(
            character=character,
            dialogue=dialogue,
            source_kind=record.source_kind,
            source_path=record.source_path,
            character_serialized_size=record.serialized_size,
            dialogue_serialized_size=record.dialogue_serialized_size,
            updated_at=record.updated_at,
            attribution_status=record.attribution_status,
        )


def create_app(
    database_path: Path = Path("data/bgvoice.lancedb"),
    frontend_dist: Path | None = None,
) -> FastAPI:
    """Create the API and optionally serve the compiled SPA from the same origin."""
    database: PipelineReader | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal database
        database = await PipelineReader.open(database_path)
        try:
            yield
        finally:
            database.close()
            database = None

    def reader() -> PipelineReader:
        assert database is not None, (
            "pipeline reader is unavailable outside the application lifespan"
        )
        return database

    app = FastAPI(title="BGVoice Pipeline Browser", version="0.1.0", lifespan=lifespan)

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return reader().health()

    @app.get("/api/stats", response_model=PipelineStats)
    async def stats() -> PipelineStats:
        return await reader().stats()

    @app.get("/api/filter-options", response_model=FilterOptions)
    async def filter_options() -> FilterOptions:
        return await reader().filter_options()

    @app.get("/api/characters", response_model=CharacterPage)
    async def characters(query: Annotated[CharacterQuery, Query()]) -> CharacterPage:
        return await reader().characters(query)

    @app.get("/api/characters/{resource_name}", response_model=CharacterDetailResponse)
    async def character_detail(resource_name: str) -> CharacterDetailResponse:
        detail = await reader().character_detail(resource_name)
        if detail is None:
            raise HTTPException(status_code=404, detail="character detail not found")
        return detail

    @app.get("/api/dialogues", response_model=DialoguePage)
    async def dialogues(query: Annotated[DialogueQuery, Query()]) -> DialoguePage:
        return await reader().dialogues(query)

    @app.get("/api/lines", response_model=DialogueLinePage)
    async def lines(query: Annotated[LineQuery, Query()]) -> DialogueLinePage:
        return await reader().lines(query)

    dist = (frontend_dist or Path("frontend/dist")).expanduser().resolve()
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{spa_path:path}", include_in_schema=False)
        def spa(spa_path: str) -> FileResponse:
            candidate = (dist / spa_path).resolve()
            if spa_path and candidate.is_relative_to(dist) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


async def _records_page[Record: LanceModel](
    *,
    table: AsyncTable,
    model: type[Record],
    search_model: type[Record],
    stable_column: StableColumn,
    predicate: Expr | None,
    tokens: tuple[str, ...],
    ordering: list[ColumnOrdering] | None,
    page: PageQuery,
) -> tuple[int, list[Record]]:
    """Run the one typed pagination path shared by all three browser tables."""
    if tokens:

        def search() -> AsyncFTSQuery:
            query = table.query().nearest_to_text(_fts_query(tokens))
            return query.where(predicate) if predicate is not None else query

        match_limit = max(1, await table.count_rows())
        if ordering is not None:
            matches = cast(
                list[Record],
                await search()
                .order_by(ordering)
                .limit(match_limit)
                .select([*model.model_fields, "_score"])
                .to_pydantic(search_model),
            )
            offset = _page_offset(page)
            return len(matches), matches[offset : offset + page.page_size]

        matches = (
            await search().limit(match_limit).select([*model.model_fields, "_score"]).to_arrow()
        )
        page_rows = (
            matches.sort_by([("_score", "descending"), (stable_column, "ascending")])
            .slice(_page_offset(page), page.page_size)
            .to_pylist()
        )
        return cast(int, matches.num_rows), [search_model.model_validate(row) for row in page_rows]

    assert ordering is not None
    page_query = table.query()
    if predicate is not None:
        page_query = page_query.where(predicate)
    total, record_rows = await asyncio.gather(
        table.count_rows(predicate.to_sql() if predicate is not None else None),
        page_query.order_by(ordering)
        .offset(_page_offset(page))
        .limit(page.page_size)
        .to_pydantic(model),
    )
    return total, cast(list[Record], record_rows)


def _published_attribution_timestamp(rows: Sequence[_AttributionMarker]) -> str | None:
    if not rows:
        return None
    timestamp = rows[0].attribution_completed_at
    if timestamp is None or any(row.attribution_completed_at != timestamp for row in rows):
        return None
    return timestamp


def _attribution_filter(attributed: bool, published_at: str | None) -> Expr:
    character_count = col("character_count")
    if published_at is None:
        return character_count < lit(0) if attributed else character_count >= lit(0)

    same_generation = col("attribution_completed_at") == lit(published_at)
    if attributed:
        return same_generation.and_(character_count > lit(0))
    return (character_count == lit(0)).or_(col("attribution_completed_at") != lit(published_at))


def _published_character_count(
    character_count: int,
    attributed_at: str | None,
    published_at: str | None,
) -> int:
    if published_at is None or attributed_at != published_at:
        return 0
    return character_count


def _combine(conditions: list[Expr]) -> Expr | None:
    if not conditions:
        return None
    predicate = conditions[0]
    for condition in conditions[1:]:
        predicate &= condition
    return predicate


def _search_tokens(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(match.group(0) for match in _SEARCH_TOKEN.finditer(value.strip()))


def _fts_query(tokens: tuple[str, ...]) -> BooleanQuery:
    assert tokens
    return BooleanQuery([(Occur.MUST, MatchQuery(token, "search_text")) for token in tokens])


def _ordering(column: str, direction: SortDirection, stable_column: str) -> list[ColumnOrdering]:
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


def _page_offset(query: PageQuery) -> int:
    return (query.page - 1) * query.page_size


def _page_count(total: int, page_size: int) -> int:
    return max(1, (total + page_size - 1) // page_size)


def _string_facets(values: Iterable[str]) -> list[FacetValue]:
    counts = Counter(values)
    return [
        FacetValue(value=value, count=count)
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _integer_facets(values: Iterable[int]) -> list[FacetValue]:
    counts = Counter(values)
    return [
        FacetValue(value=value, count=count)
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
