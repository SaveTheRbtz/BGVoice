"""Read-only HTTP API and production SPA host for pipeline inspection."""

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, func, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped
from sqlalchemy.pool import NullPool
from sqlalchemy.sql.elements import TextClause
from sqlmodel import Session, col, create_engine, select

from bgvoice.database import (
    SCHEMA_VERSION,
    AttributionRun,
    Character,
    CharacterAttribution,
    Dialogue,
    DialogueLineRecord,
    ExtractionRun,
    SchemaMetadata,
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

_SEARCH_TOKEN = re.compile(r"[\w-]+", re.UNICODE)

_ATTRIBUTION_COUNTS = (
    select(
        col(CharacterAttribution.dialogue_resource_name).label("dialogue_resource_name"),
        func.count().label("character_count"),
    )
    .where(col(CharacterAttribution.dialogue_resource_name).is_not(None))
    .group_by(CharacterAttribution.dialogue_resource_name)
    .subquery()
)
_CHARACTER_COUNT = func.coalesce(_ATTRIBUTION_COUNTS.c.character_count, 0)

_CHARACTER_SORT_COLUMNS = {
    "resource_name": col(Character.resource_name).collate("NOCASE"),
    "display_name": col(Character.display_name).collate("NOCASE"),
    "source_kind": col(Character.source_kind).collate("NOCASE"),
    "serialized_size": col(Character.serialized_size),
    "dialogue_line_count": col(Dialogue.dialogue_line_count),
    "npc_line_count": col(Dialogue.npc_line_count),
    "player_line_count": col(Dialogue.player_line_count),
    "dialogue_state_count": col(CharacterAttribution.dialogue_state_count),
    "dialogue_transition_count": col(CharacterAttribution.dialogue_transition_count),
    "updated_at": col(Character.updated_at),
}
_DIALOGUE_SORT_COLUMNS = {
    "resource_name": col(Dialogue.resource_name).collate("NOCASE"),
    "source_kind": col(Dialogue.source_kind).collate("NOCASE"),
    "serialized_size": col(Dialogue.serialized_size),
    "dialogue_line_count": col(Dialogue.dialogue_line_count),
    "npc_line_count": col(Dialogue.npc_line_count),
    "player_line_count": col(Dialogue.player_line_count),
    "character_count": _CHARACTER_COUNT,
    "updated_at": col(Dialogue.updated_at),
}
_LINE_SORT_COLUMNS = {
    "dialogue_resource_name": col(DialogueLineRecord.dialogue_resource_name).collate("NOCASE"),
    "line_kind": col(DialogueLineRecord.line_kind),
    "strref": col(DialogueLineRecord.strref),
    "serialized_size": col(DialogueLineRecord.serialized_size),
    "state_index": col(DialogueLineRecord.state_index),
    "transition_index": col(DialogueLineRecord.transition_index),
}


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
    sort: CharacterSort = "serialized_size"
    direction: SortDirection = "desc"


class DialogueQuery(PageQuery):
    q: str | None = Field(default=None, max_length=200)
    status: DetailStatus | None = None
    source_kind: SourceKind | None = None
    attributed: bool | None = None
    sort: DialogueSort = "dialogue_line_count"
    direction: SortDirection = "desc"


class LineQuery(PageQuery):
    q: str | None = Field(default=None, max_length=300)
    line_kind: DialogueLineKind | None = None
    source_kind: SourceKind | None = None
    attributed: bool | None = None
    sort: LineSort = "serialized_size"
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
    sort: CharacterSort
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
    sort: DialogueSort
    direction: SortDirection


class DialogueLineRow(ApiModel):
    id: int
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
    sort: LineSort
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
    id: int
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
    sqlite_query_only: bool
    schema_version: int


class ReadOnlyPipelineDatabase:
    """Short-lived SQLModel sessions over a read-only SQLite URI."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        assert self.path.is_file(), f"pipeline database does not exist: {self.path}"
        self._engine = self._create_engine()

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Open one short-lived typed read session."""
        with Session(self._engine) as session:
            yield session

    def health(self) -> HealthResponse:
        with self.session() as session:
            query_only = session.connection().exec_driver_sql("PRAGMA query_only").scalar_one()
            metadata = session.get(SchemaMetadata, "schema_version")
        assert metadata is not None, (
            f"database schema metadata is missing: {self.path}. "
            "Rebuild the generated database from the EET installation."
        )
        assert metadata.value == SCHEMA_VERSION, (
            f"database schema is {metadata.value}; expected {SCHEMA_VERSION}. "
            "Rebuild the generated database from the EET installation."
        )
        return HealthResponse(
            status="ok",
            sqlite_query_only=bool(query_only),
            schema_version=int(metadata.value),
        )

    def stats(self) -> PipelineStats:
        with self.session() as session:
            character = session.exec(
                select(
                    func.count(col(Character.resource_name)),
                    func.count().filter(col(Character.detail_status) == "complete"),
                    func.count().filter(col(Character.detail_status) == "failed"),
                    func.count().filter(
                        col(Character.detail_status) == "complete",
                        col(Character.dialog_resref).is_not(None),
                    ),
                ).where(col(Character.active) == 1)
            ).one()
            dialogue = session.exec(
                select(
                    func.count(col(Dialogue.resource_name)),
                    func.count().filter(col(Dialogue.detail_status) == "complete"),
                    func.coalesce(
                        func.sum(col(Dialogue.dialogue_line_count)).filter(
                            col(Dialogue.detail_status) == "complete"
                        ),
                        0,
                    ),
                ).where(col(Dialogue.active) == 1)
            ).one()
            line_count = session.exec(
                select(func.count(col(DialogueLineRecord.id)))
                .select_from(DialogueLineRecord)
                .join(
                    Dialogue,
                    col(Dialogue.resource_name) == col(DialogueLineRecord.dialogue_resource_name),
                )
                .where(Dialogue.active == 1)
            ).one()
            latest_runs = list(
                session.exec(select(ExtractionRun).order_by(col(ExtractionRun.id).desc()).limit(8))
            )
            attribution = session.exec(
                select(AttributionRun).order_by(col(AttributionRun.id).desc()).limit(1)
            ).first()

        return PipelineStats(
            database_path=str(self.path),
            database_size=self.path.stat().st_size,
            characters_total=int(character[0]),
            characters_complete=int(character[1]),
            characters_failed=int(character[2]),
            characters_with_dialogue=int(character[3]),
            attribution_completed_at=attribution.completed_at if attribution else None,
            characters_unavailable=attribution.characters_unavailable if attribution else 0,
            characters_matched=attribution.characters_matched if attribution else 0,
            characters_missing_dialogue=(
                attribution.characters_missing_dialogue if attribution else 0
            ),
            characters_dialogue_failed=(
                attribution.characters_dialogue_failed if attribution else 0
            ),
            characters_without_dialogue=(
                attribution.characters_without_dialogue if attribution else 0
            ),
            dialogues_total=int(dialogue[0]),
            dialogues_complete=int(dialogue[1]),
            dialogue_lines=int(dialogue[2] or 0),
            line_records_total=int(line_count),
            dialogues_attributed=attribution.dialogues_attributed if attribution else 0,
            dialogues_unattributed=attribution.dialogues_unattributed if attribution else 0,
            attributed_dialogue_lines=(attribution.attributed_dialogue_lines if attribution else 0),
            unattributed_dialogue_lines=(
                attribution.unattributed_dialogue_lines if attribution else 0
            ),
            latest_runs=[
                ExtractionRunSummary.model_validate(run, from_attributes=True)
                for run in latest_runs
            ],
        )

    def filter_options(self) -> FilterOptions:
        with self.session() as session:
            return FilterOptions(
                source_kinds=self._facet(session, col(Character.source_kind)),
                gender_ids=self._facet(session, col(Character.gender_id)),
                race_ids=self._facet(session, col(Character.race_id)),
                class_ids=self._facet(session, col(Character.class_id)),
            )

    def characters(self, query: CharacterQuery) -> CharacterPage:
        conditions = [col(Character.active) == 1]
        if query.status is not None:
            conditions.append(col(Character.detail_status) == query.status)
        if query.source_kind is not None:
            conditions.append(col(Character.source_kind) == query.source_kind)
        if query.gender_id is not None:
            conditions.append(col(Character.gender_id) == query.gender_id)
        if query.race_id is not None:
            conditions.append(col(Character.race_id) == query.race_id)
        if query.class_id is not None:
            conditions.append(col(Character.class_id) == query.class_id)
        if query.attribution_status is not None:
            conditions.append(
                col(CharacterAttribution.attribution_status) == query.attribution_status
            )
        if query.has_dialog is not None:
            has_dialog = col(Character.dialog_resref).is_not(None)
            conditions.append(has_dialog if query.has_dialog else ~has_dialog)
        if (fts_query := _fts_query(query.q)) is not None:
            conditions.append(_fts_condition("characters", fts_query))

        statement = (
            select(Character, CharacterAttribution, Dialogue)
            .select_from(Character)
            .outerjoin(
                CharacterAttribution,
                col(CharacterAttribution.character_resource_name) == col(Character.resource_name),
            )
            .outerjoin(
                Dialogue,
                (col(Dialogue.resource_name) == col(CharacterAttribution.dialogue_resource_name))
                & (col(Dialogue.active) == 1),
            )
            .where(*conditions)
        )
        count_statement = select(func.count()).select_from(statement.subquery())
        statement = statement.order_by(
            _ordered(_CHARACTER_SORT_COLUMNS[query.sort], query.direction),
            col(Character.resource_name).collate("NOCASE").asc(),
        ).slice(*_page_slice(query))

        with self.session() as session:
            total = int(session.exec(count_statement).one())
            rows = session.exec(statement).all()
        return CharacterPage(
            items=[self._character_row(*row) for row in rows],
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=_page_count(total, query.page_size),
            sort=query.sort,
            direction=query.direction,
        )

    def dialogues(self, query: DialogueQuery) -> DialoguePage:
        conditions = [col(Dialogue.active) == 1]
        if query.status is not None:
            conditions.append(col(Dialogue.detail_status) == query.status)
        if query.source_kind is not None:
            conditions.append(col(Dialogue.source_kind) == query.source_kind)
        if query.attributed is not None:
            attributed = _ATTRIBUTION_COUNTS.c.character_count.is_not(None)
            conditions.append(attributed if query.attributed else ~attributed)
        if (fts_query := _fts_query(query.q)) is not None:
            conditions.append(_fts_condition("dialogues", fts_query))

        statement = (
            select(Dialogue, _CHARACTER_COUNT.label("character_count"))
            .select_from(Dialogue)
            .outerjoin(
                _ATTRIBUTION_COUNTS,
                _ATTRIBUTION_COUNTS.c.dialogue_resource_name == col(Dialogue.resource_name),
            )
            .where(*conditions)
        )
        count_statement = select(func.count()).select_from(statement.subquery())
        statement = statement.order_by(
            _ordered(_DIALOGUE_SORT_COLUMNS[query.sort], query.direction),
            col(Dialogue.resource_name).collate("NOCASE").asc(),
        ).slice(*_page_slice(query))

        with self.session() as session:
            total = int(session.exec(count_statement).one())
            rows = session.exec(statement).all()
        return DialoguePage(
            items=[self._dialogue_row(*row) for row in rows],
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=_page_count(total, query.page_size),
            sort=query.sort,
            direction=query.direction,
        )

    def lines(self, query: LineQuery) -> DialogueLinePage:
        conditions = [col(Dialogue.active) == 1]
        if query.line_kind is not None:
            conditions.append(col(DialogueLineRecord.line_kind) == query.line_kind)
        if query.source_kind is not None:
            conditions.append(col(Dialogue.source_kind) == query.source_kind)
        if query.attributed is not None:
            attributed = _ATTRIBUTION_COUNTS.c.character_count.is_not(None)
            conditions.append(attributed if query.attributed else ~attributed)
        if (fts_query := _fts_query(query.q)) is not None:
            conditions.append(_fts_condition("dialogue_lines", fts_query))

        statement = (
            select(DialogueLineRecord, Dialogue, _CHARACTER_COUNT.label("character_count"))
            .select_from(DialogueLineRecord)
            .join(
                Dialogue,
                col(Dialogue.resource_name) == col(DialogueLineRecord.dialogue_resource_name),
            )
            .outerjoin(
                _ATTRIBUTION_COUNTS,
                _ATTRIBUTION_COUNTS.c.dialogue_resource_name == col(Dialogue.resource_name),
            )
            .where(*conditions)
        )
        count_statement = select(func.count()).select_from(statement.subquery())
        statement = statement.order_by(
            _ordered(_LINE_SORT_COLUMNS[query.sort], query.direction),
            col(DialogueLineRecord.id).asc(),
        ).slice(*_page_slice(query))

        with self.session() as session:
            total = int(session.exec(count_statement).one())
            rows = session.exec(statement).all()
        return DialogueLinePage(
            items=[self._line_row(*row) for row in rows],
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=_page_count(total, query.page_size),
            sort=query.sort,
            direction=query.direction,
        )

    def character_detail(self, resource_name: str) -> CharacterDetailResponse | None:
        statement = (
            select(Character, CharacterAttribution, Dialogue)
            .select_from(Character)
            .outerjoin(
                CharacterAttribution,
                col(CharacterAttribution.character_resource_name) == col(Character.resource_name),
            )
            .outerjoin(
                Dialogue,
                (col(Dialogue.resource_name) == col(CharacterAttribution.dialogue_resource_name))
                & (col(Dialogue.active) == 1),
            )
            .where(
                col(Character.active) == 1,
                col(Character.resource_name) == resource_name,
            )
        )
        with self.session() as session:
            row = session.exec(statement).first()
        if row is None:
            return None
        character, attribution, dialogue = row
        if character.detail_json is None or character.serialized_size is None:
            return None
        return CharacterDetailResponse(
            character=CharacterDetail.model_validate_json(character.detail_json, strict=True),
            dialogue=(
                DialogueDetail.model_validate_json(dialogue.detail_json, strict=True)
                if dialogue is not None and dialogue.detail_json is not None
                else None
            ),
            source_kind=character.source_kind,
            source_path=character.source_path,
            character_serialized_size=character.serialized_size,
            dialogue_serialized_size=dialogue.serialized_size if dialogue else None,
            updated_at=character.updated_at,
            attribution_status=attribution.attribution_status if attribution else None,
        )

    @staticmethod
    def _character_row(
        character: Character,
        attribution: CharacterAttribution | None,
        dialogue: Dialogue | None,
    ) -> CharacterRow:
        return CharacterRow(
            resource_name=character.resource_name,
            display_name=character.display_name,
            resref=character.resref,
            source_kind=character.source_kind,
            dialog_resref=character.dialog_resref,
            gender_id=character.gender_id,
            race_id=character.race_id,
            class_id=character.class_id,
            detail_status=character.detail_status,
            detail_error=character.detail_error,
            attribution_status=attribution.attribution_status if attribution else None,
            serialized_size=character.serialized_size,
            dialogue_status=dialogue.detail_status if dialogue else None,
            dialogue_line_count=dialogue.dialogue_line_count if dialogue else None,
            npc_line_count=dialogue.npc_line_count if dialogue else None,
            player_line_count=dialogue.player_line_count if dialogue else None,
            journal_line_count=dialogue.journal_line_count if dialogue else None,
            dialogue_state_count=attribution.dialogue_state_count if attribution else None,
            dialogue_transition_count=(
                attribution.dialogue_transition_count if attribution else None
            ),
            dialogue_serialized_size=dialogue.serialized_size if dialogue else None,
            updated_at=character.updated_at,
        )

    @staticmethod
    def _dialogue_row(dialogue: Dialogue, character_count: int) -> DialogueRow:
        return DialogueRow(
            resource_name=dialogue.resource_name,
            resref=dialogue.resref,
            source_kind=dialogue.source_kind,
            source_path=dialogue.source_path,
            detail_status=dialogue.detail_status,
            detail_error=dialogue.detail_error,
            serialized_size=dialogue.serialized_size,
            dialogue_line_count=dialogue.dialogue_line_count,
            npc_line_count=dialogue.npc_line_count,
            player_line_count=dialogue.player_line_count,
            journal_line_count=dialogue.journal_line_count,
            character_count=int(character_count),
            updated_at=dialogue.updated_at,
        )

    @staticmethod
    def _line_row(
        line: DialogueLineRecord, dialogue: Dialogue, character_count: int
    ) -> DialogueLineRow:
        assert line.id is not None, "stored dialogue line has no id"
        return DialogueLineRow(
            id=line.id,
            dialogue_resource_name=line.dialogue_resource_name,
            dialogue_resref=dialogue.resref,
            source_kind=dialogue.source_kind,
            line_kind=line.line_kind,
            state_index=line.state_index,
            transition_index=line.transition_index,
            strref=line.strref,
            text=line.text,
            serialized_size=line.serialized_size,
            character_count=int(character_count),
        )

    @staticmethod
    def _facet[Value: str | int | None](
        session: Session, column: Mapped[Value]
    ) -> list[FacetValue]:
        count = func.count().label("count")
        rows = session.exec(
            select(column.label("value"), count)
            .where(col(Character.active) == 1, column.is_not(None))
            .group_by(column)
            .order_by(count.desc(), column.asc())
        ).all()
        return [FacetValue(value=cast(str | int, row[0]), count=int(row[1])) for row in rows]

    def _create_engine(self) -> Engine:
        return create_engine(
            "sqlite+pysqlite://",
            creator=self._open_connection,
            poolclass=NullPool,
        )

    def _open_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"{self.path.as_uri()}?mode=ro",
            uri=True,
            autocommit=False,
            timeout=5.0,
        )
        connection.execute("PRAGMA query_only = ON")
        return connection


def create_app(
    database_path: Path = Path("data/bgvoice.sqlite3"),
    frontend_dist: Path | None = None,
) -> FastAPI:
    """Create the API and optionally serve the compiled SPA from the same origin."""
    database = ReadOnlyPipelineDatabase(database_path)
    app = FastAPI(title="BGVoice Pipeline Browser", version="0.1.0")

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return database.health()

    @app.get("/api/stats", response_model=PipelineStats)
    def stats() -> PipelineStats:
        return database.stats()

    @app.get("/api/filter-options", response_model=FilterOptions)
    def filter_options() -> FilterOptions:
        return database.filter_options()

    @app.get("/api/characters", response_model=CharacterPage)
    def characters(query: Annotated[CharacterQuery, Query()]) -> CharacterPage:
        return database.characters(query)

    @app.get("/api/characters/{resource_name}", response_model=CharacterDetailResponse)
    def character_detail(resource_name: str) -> CharacterDetailResponse:
        detail = database.character_detail(resource_name)
        if detail is None:
            raise HTTPException(status_code=404, detail="character detail not found")
        return detail

    @app.get("/api/dialogues", response_model=DialoguePage)
    def dialogues(query: Annotated[DialogueQuery, Query()]) -> DialoguePage:
        return database.dialogues(query)

    @app.get("/api/lines", response_model=DialogueLinePage)
    def lines(query: Annotated[LineQuery, Query()]) -> DialogueLinePage:
        return database.lines(query)

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


def _ordered(column: object, direction: SortDirection) -> ColumnElement[object]:
    expression = cast(ColumnElement[object], column)
    ordered = expression.asc() if direction == "asc" else expression.desc()
    return ordered.nulls_last()


def _page_slice(query: PageQuery) -> tuple[int, int]:
    start = (query.page - 1) * query.page_size
    return start, start + query.page_size


def _page_count(total: int, page_size: int) -> int:
    return max(1, (total + page_size - 1) // page_size)


def _fts_condition(
    table: Literal["characters", "dialogues", "dialogue_lines"], query: str
) -> TextClause:
    clauses = {
        "characters": (
            "characters.resource_name IN "
            "(SELECT resource_name FROM characters_fts WHERE characters_fts MATCH :fts_query)"
        ),
        "dialogues": (
            "dialogues.resource_name IN "
            "(SELECT resource_name FROM dialogues_fts WHERE dialogues_fts MATCH :fts_query)"
        ),
        "dialogue_lines": (
            "dialogue_lines.id IN "
            "(SELECT line_id FROM dialogue_lines_fts WHERE dialogue_lines_fts MATCH :fts_query)"
        ),
    }
    return text(clauses[table]).bindparams(fts_query=query)


def _fts_query(value: str | None) -> str | None:
    if value is None:
        return None
    tokens = _SEARCH_TOKEN.findall(value.strip())
    if not tokens:
        return None
    return " AND ".join(f'"{token}"*' for token in tokens)
