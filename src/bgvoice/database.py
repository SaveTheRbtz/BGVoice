"""SQLModel persistence for the extraction pipeline.

SQLite-specific SQL is deliberately limited to FTS5 and PRAGMA settings.
Ordinary reads and writes use ORM sessions.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Self

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Text,
    delete,
    func,
    inspect,
    text,
    update,
)
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, col, create_engine, select

from bgvoice.models import (
    AttributionStatus,
    AttributionSummary,
    CharacterDetail,
    CreResource,
    DatabaseStats,
    DetailStatus,
    DialogueDetail,
    DialogueExtraction,
    DialogueLine,
    DialogueLineKind,
    DlgResource,
    RunKind,
    RunStatus,
    SourceKind,
    TerminalRunStatus,
    utc_now,
)

SCHEMA_VERSION = "1"


class SchemaMetadata(SQLModel, table=True):
    __tablename__ = "schema_metadata"
    __table_args__ = {"sqlite_strict": True, "sqlite_with_rowid": False}

    key: str = Field(sa_column=Column(Text, primary_key=True, nullable=False))
    value: str = Field(sa_type=Text)


class ExtractionRun(SQLModel, table=True):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        CheckConstraint("run_kind IN ('characters', 'dialogues')"),
        CheckConstraint("status IN ('running', 'complete', 'complete_with_errors', 'failed')"),
        CheckConstraint("resources_discovered >= 0"),
        CheckConstraint("details_attempted >= 0"),
        CheckConstraint("details_extracted >= 0"),
        CheckConstraint("failures >= 0"),
        {"sqlite_strict": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    run_kind: RunKind = Field(default="characters", sa_type=Text)
    started_at: str = Field(sa_type=Text)
    completed_at: str | None = Field(default=None, sa_type=Text)
    game_root: str = Field(sa_type=Text)
    iecli_version: str = Field(sa_type=Text)
    status: RunStatus = Field(default="running", sa_type=Text)
    resources_discovered: int = 0
    details_attempted: int = 0
    details_extracted: int = 0
    failures: int = 0
    error: str | None = Field(default=None, sa_type=Text)


class Character(SQLModel, table=True):
    __tablename__ = "characters"
    __table_args__ = (
        CheckConstraint("source_kind IN ('override', 'bif', 'dlc')"),
        CheckConstraint("active IN (0, 1)"),
        CheckConstraint("serialized_size IS NULL OR serialized_size >= 0"),
        CheckConstraint("detail_status IN ('pending', 'complete', 'failed')"),
        Index(
            "characters_display_name_idx",
            "display_name",
            sqlite_where=text("active = 1"),
        ),
        Index(
            "characters_dialog_idx",
            "dialog_resref",
            sqlite_where=text("active = 1 AND dialog_resref IS NOT NULL"),
        ),
        Index(
            "characters_death_variable_idx",
            "death_variable",
            sqlite_where=text("active = 1 AND death_variable IS NOT NULL"),
        ),
        {"sqlite_strict": True, "sqlite_with_rowid": False},
    )

    resource_name: str = Field(
        sa_column=Column(Text(collation="NOCASE"), primary_key=True, nullable=False)
    )
    resref: str = Field(sa_type=Text)
    source_kind: SourceKind = Field(sa_type=Text)
    source_path: str = Field(sa_type=Text)
    active: int = 1
    display_name: str | None = Field(
        default=None, sa_column=Column(Text(collation="NOCASE"), nullable=True)
    )
    short_name: str | None = Field(default=None, sa_type=Text)
    short_name_strref: int | None = None
    long_name: str | None = Field(default=None, sa_type=Text)
    long_name_strref: int | None = None
    death_variable: str | None = Field(
        default=None, sa_column=Column(Text(collation="NOCASE"), nullable=True)
    )
    dialog_resref: str | None = Field(
        default=None, sa_column=Column(Text(collation="NOCASE"), nullable=True)
    )
    gender_id: int | None = None
    race_id: int | None = None
    class_id: int | None = None
    alignment_id: int | None = None
    enemy_ally_id: int | None = None
    general_id: int | None = None
    specific_id: int | None = None
    override_script: str | None = Field(default=None, sa_type=Text)
    class_script: str | None = Field(default=None, sa_type=Text)
    race_script: str | None = Field(default=None, sa_type=Text)
    general_script: str | None = Field(default=None, sa_type=Text)
    default_script: str | None = Field(default=None, sa_type=Text)
    small_portrait: str | None = Field(default=None, sa_type=Text)
    large_portrait: str | None = Field(default=None, sa_type=Text)
    cre_version: str | None = Field(default=None, sa_type=Text)
    detail_json: str | None = Field(default=None, sa_type=Text)
    serialized_size: int | None = None
    detail_status: DetailStatus = Field(default="pending", sa_type=Text)
    detail_error: str | None = Field(default=None, sa_type=Text)
    last_seen_run_id: int = Field(foreign_key="extraction_runs.id")
    updated_at: str = Field(sa_type=Text)


class Dialogue(SQLModel, table=True):
    __tablename__ = "dialogues"
    __table_args__ = (
        CheckConstraint("source_kind IN ('override', 'bif', 'dlc')"),
        CheckConstraint("active IN (0, 1)"),
        CheckConstraint("state_count IS NULL OR state_count >= 0"),
        CheckConstraint("transition_count IS NULL OR transition_count >= 0"),
        CheckConstraint("npc_line_count IS NULL OR npc_line_count >= 0"),
        CheckConstraint("player_line_count IS NULL OR player_line_count >= 0"),
        CheckConstraint("journal_line_count IS NULL OR journal_line_count >= 0"),
        CheckConstraint("dialogue_line_count IS NULL OR dialogue_line_count >= 0"),
        CheckConstraint("serialized_size IS NULL OR serialized_size >= 0"),
        CheckConstraint("detail_status IN ('pending', 'complete', 'failed')"),
        {"sqlite_strict": True, "sqlite_with_rowid": False},
    )

    resource_name: str = Field(
        sa_column=Column(Text(collation="NOCASE"), primary_key=True, nullable=False)
    )
    resref: str = Field(sa_type=Text)
    source_kind: SourceKind = Field(sa_type=Text)
    source_path: str = Field(sa_type=Text)
    active: int = 1
    dlg_version: str | None = Field(default=None, sa_type=Text)
    state_count: int | None = None
    transition_count: int | None = None
    npc_line_count: int | None = None
    player_line_count: int | None = None
    journal_line_count: int | None = None
    dialogue_line_count: int | None = None
    detail_json: str | None = Field(default=None, sa_type=Text)
    serialized_size: int | None = None
    detail_status: DetailStatus = Field(default="pending", sa_type=Text)
    detail_error: str | None = Field(default=None, sa_type=Text)
    last_seen_run_id: int = Field(foreign_key="extraction_runs.id")
    updated_at: str = Field(sa_type=Text)


class AttributionRun(SQLModel, table=True):
    __tablename__ = "attribution_runs"
    __table_args__ = (
        CheckConstraint("characters_total >= 0"),
        CheckConstraint("characters_matched >= 0"),
        CheckConstraint("characters_missing_dialogue >= 0"),
        CheckConstraint("characters_dialogue_failed >= 0"),
        CheckConstraint("characters_without_dialogue >= 0"),
        CheckConstraint("characters_unavailable >= 0"),
        CheckConstraint("dialogues_total >= 0"),
        CheckConstraint("dialogues_attributed >= 0"),
        CheckConstraint("dialogues_unattributed >= 0"),
        CheckConstraint("attributed_dialogue_lines >= 0"),
        CheckConstraint("unattributed_dialogue_lines >= 0"),
        {"sqlite_strict": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    completed_at: str = Field(sa_type=Text)
    characters_total: int = 0
    characters_matched: int = 0
    characters_missing_dialogue: int = 0
    characters_dialogue_failed: int = 0
    characters_without_dialogue: int = 0
    characters_unavailable: int = 0
    dialogues_total: int = 0
    dialogues_attributed: int = 0
    dialogues_unattributed: int = 0
    attributed_dialogue_lines: int = 0
    unattributed_dialogue_lines: int = 0


class DialogueLineRecord(SQLModel, table=True):
    __tablename__ = "dialogue_lines"
    __table_args__ = (
        CheckConstraint("line_kind IN ('npc', 'player', 'journal')"),
        CheckConstraint(
            "(line_kind = 'npc' AND transition_index IS NULL) OR "
            "(line_kind IN ('player', 'journal') AND transition_index IS NOT NULL)"
        ),
        CheckConstraint("state_index >= 0"),
        CheckConstraint("transition_index IS NULL OR transition_index >= 0"),
        CheckConstraint("strref >= 0"),
        CheckConstraint("serialized_size >= 0"),
        Index(
            "dialogue_lines_npc_unique_idx",
            "dialogue_resource_name",
            "state_index",
            unique=True,
            sqlite_where=text("transition_index IS NULL"),
        ),
        Index(
            "dialogue_lines_transition_unique_idx",
            "dialogue_resource_name",
            "line_kind",
            "state_index",
            "transition_index",
            unique=True,
            sqlite_where=text("transition_index IS NOT NULL"),
        ),
        Index("dialogue_lines_dialogue_idx", "dialogue_resource_name"),
        Index("dialogue_lines_kind_idx", "line_kind", "dialogue_resource_name"),
        {"sqlite_strict": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    dialogue_resource_name: str = Field(
        sa_column=Column(
            Text(collation="NOCASE"),
            ForeignKey("dialogues.resource_name"),
            nullable=False,
        )
    )
    line_kind: DialogueLineKind = Field(sa_type=Text)
    state_index: int
    transition_index: int | None = None
    strref: int
    text: str | None = Field(default=None, sa_type=Text)
    serialized_size: int
    updated_at: str = Field(sa_type=Text)


class CharacterAttribution(SQLModel, table=True):
    __tablename__ = "character_dialogue_attributions"
    __table_args__ = (
        CheckConstraint(
            "attribution_status IN "
            "('matched', 'missing_dialogue', 'dialogue_failed', 'no_dialogue', "
            "'character_unavailable')"
        ),
        CheckConstraint("dialogue_line_count IS NULL OR dialogue_line_count >= 0"),
        CheckConstraint("npc_line_count IS NULL OR npc_line_count >= 0"),
        CheckConstraint("player_line_count IS NULL OR player_line_count >= 0"),
        CheckConstraint("journal_line_count IS NULL OR journal_line_count >= 0"),
        CheckConstraint("dialogue_state_count IS NULL OR dialogue_state_count >= 0"),
        CheckConstraint("dialogue_transition_count IS NULL OR dialogue_transition_count >= 0"),
        Index("character_dialogue_attribution_status_idx", "attribution_status"),
        Index(
            "character_dialogue_attribution_dlg_idx",
            "dialogue_resource_name",
            sqlite_where=text("dialogue_resource_name IS NOT NULL"),
        ),
        {"sqlite_strict": True, "sqlite_with_rowid": False},
    )

    character_resource_name: str = Field(
        sa_column=Column(
            Text(collation="NOCASE"),
            ForeignKey("characters.resource_name"),
            primary_key=True,
            nullable=False,
        )
    )
    dialog_resref: str | None = Field(default=None, sa_type=Text)
    dialogue_resource_name: str | None = Field(
        default=None,
        sa_column=Column(
            Text(collation="NOCASE"),
            ForeignKey("dialogues.resource_name"),
            nullable=True,
        ),
    )
    attribution_status: AttributionStatus = Field(sa_type=Text)
    dialogue_line_count: int | None = None
    npc_line_count: int | None = None
    player_line_count: int | None = None
    journal_line_count: int | None = None
    dialogue_state_count: int | None = None
    dialogue_transition_count: int | None = None
    attribution_run_id: int = Field(foreign_key="attribution_runs.id")
    updated_at: str = Field(sa_type=Text)


_CHARACTER_TABLE = Character.__tablename__
_DIALOGUE_TABLE = Dialogue.__tablename__
_DIALOGUE_LINE_TABLE = DialogueLineRecord.__tablename__

_CHARACTER_FTS = f"{_CHARACTER_TABLE}_fts"
_DIALOGUE_FTS = f"{_DIALOGUE_TABLE}_fts"
_DIALOGUE_LINE_FTS = f"{_DIALOGUE_LINE_TABLE}_fts"
_FTS_TABLES = (_CHARACTER_FTS, _DIALOGUE_FTS, _DIALOGUE_LINE_FTS)

_CHARACTER_FTS_DDL = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS {_CHARACTER_FTS} USING fts5(
    resource_name, resref, display_name, short_name, long_name, death_variable,
    dialog_resref, scripts, tokenize = 'unicode61 remove_diacritics 2'
);
"""

_DIALOGUE_FTS_DDL = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS {_DIALOGUE_FTS} USING fts5(
    resource_name, resref, source_path,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

_DIALOGUE_LINE_FTS_DDL = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS {_DIALOGUE_LINE_FTS} USING fts5(
    line_id UNINDEXED, dialogue_resource_name, text,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

_SQLITE_FEATURE_DDL = (
    _CHARACTER_FTS_DDL,
    _DIALOGUE_FTS_DDL,
    _DIALOGUE_LINE_FTS_DDL,
)


class CharacterDatabase:
    """Single-writer SQLModel repository for the extraction pipeline."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self.path.exists() or self.path.stat().st_size == 0
        self._engine = self._create_engine()
        try:
            if not is_new:
                self._validate_schema_version()
            self._configure_sqlite()
            SQLModel.metadata.create_all(self._engine)
            if is_new:
                self._write_schema_version()
            self._install_sqlite_features()
        except BaseException:
            self._engine.dispose()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        """Release the database connection."""
        self._engine.dispose()

    def start_run(
        self,
        game_root: Path,
        iecli_version: str,
        *,
        run_kind: RunKind = "characters",
    ) -> int:
        """Create a durable extraction-run record."""
        run = ExtractionRun(
            run_kind=run_kind,
            started_at=utc_now().isoformat(),
            game_root=str(game_root.resolve()),
            iecli_version=iecli_version,
            status="running",
        )
        with Session(self._engine) as session, session.begin():
            session.add(run)
            session.flush()
            assert run.id is not None, "SQLite did not create an extraction run id"
            return run.id

    def replace_inventory(self, run_id: int, resources: Sequence[CreResource]) -> None:
        """Replace the active CRE inventory while retaining historical rows."""
        timestamp = utc_now().isoformat()
        with Session(self._engine) as session, session.begin():
            run = self._run(session, run_id, expected_kind="characters")
            self._invalidate_attributions(session)
            session.exec(update(Character).where(col(Character.active) == 1).values(active=0))

            existing = self._characters_by_name(session, (r.resource_name for r in resources))
            for resource in resources:
                character = existing.get(resource.resource_name.casefold())
                if character is None:
                    session.add(
                        Character(
                            resource_name=resource.resource_name,
                            resref=resource.resref,
                            source_kind=resource.source_kind,
                            source_path=resource.source_path,
                            last_seen_run_id=run_id,
                            updated_at=timestamp,
                        )
                    )
                    continue

                changed = (
                    character.resref != resource.resref
                    or character.source_kind != resource.source_kind
                    or character.source_path != resource.source_path
                )
                character.resref = resource.resref
                character.source_kind = resource.source_kind
                character.source_path = resource.source_path
                character.active = 1
                character.last_seen_run_id = run_id
                character.updated_at = timestamp
                if changed:
                    self._clear_character_detail(character)
                    character.detail_status = "pending"
                    character.detail_error = None

            run.resources_discovered = len(resources)
            session.flush()
            self._rebuild_character_fts(session.connection())

    def detail_targets(self, *, refresh: bool) -> set[str]:
        """Return active CRE resources that need detail extraction."""
        statement = select(Character.resource_name).where(Character.active == 1)
        if not refresh:
            statement = statement.where(Character.detail_status != "complete")
        with Session(self._engine) as session:
            return set(session.exec(statement))

    def apply_detail_batch(
        self,
        details: Sequence[CharacterDetail],
        failures: Iterable[tuple[str, str]],
    ) -> None:
        """Persist a bounded batch of successful and failed CRE details."""
        timestamp = utc_now().isoformat()
        failures = list(failures)
        names = [detail.resource_name for detail in details]
        names.extend(resource_name for resource_name, _ in failures)

        with Session(self._engine) as session, session.begin():
            characters = self._characters_by_name(session, names)
            self._assert_batch_resources(characters, names, kind="CRE")
            for detail in details:
                character = characters[detail.resource_name.casefold()]
                for field, value in detail.model_dump(exclude={"resource_name"}).items():
                    setattr(character, field, value)
                detail_json = detail.model_dump_json()
                character.detail_json = detail_json
                character.serialized_size = len(detail_json.encode())
                character.detail_status = "complete"
                character.detail_error = None
                character.updated_at = timestamp

            for resource_name, error in failures:
                character = characters[resource_name.casefold()]
                self._clear_character_detail(character)
                character.detail_status = "failed"
                character.detail_error = error[:2000]
                character.updated_at = timestamp

            session.flush()
            self._sync_character_fts(
                session.connection(),
                (character.resource_name for character in characters.values()),
            )

    def replace_dialogue_inventory(self, run_id: int, resources: Sequence[DlgResource]) -> None:
        """Replace the complete active DLG inventory reported by ie-cli."""
        timestamp = utc_now().isoformat()
        with Session(self._engine) as session, session.begin():
            run = self._run(session, run_id, expected_kind="dialogues")
            self._invalidate_attributions(session)
            session.exec(update(Dialogue).where(col(Dialogue.active) == 1).values(active=0))

            existing = self._dialogues_by_name(session, (r.resource_name for r in resources))
            for resource in resources:
                dialogue = existing.get(resource.resource_name.casefold())
                if dialogue is None:
                    session.add(
                        Dialogue(
                            resource_name=resource.resource_name,
                            resref=resource.resref,
                            source_kind=resource.source_kind,
                            source_path=resource.source_path,
                            last_seen_run_id=run_id,
                            updated_at=timestamp,
                        )
                    )
                    continue

                changed = (
                    dialogue.resref != resource.resref
                    or dialogue.source_kind != resource.source_kind
                    or dialogue.source_path != resource.source_path
                )
                dialogue.resref = resource.resref
                dialogue.source_kind = resource.source_kind
                dialogue.source_path = resource.source_path
                dialogue.active = 1
                dialogue.last_seen_run_id = run_id
                dialogue.updated_at = timestamp
                if changed:
                    self._clear_dialogue_detail(dialogue)
                    dialogue.detail_status = "pending"
                    dialogue.detail_error = None
                    session.exec(
                        delete(DialogueLineRecord).where(
                            col(DialogueLineRecord.dialogue_resource_name) == dialogue.resource_name
                        )
                    )

            run.resources_discovered = len(resources)
            session.flush()
            connection = session.connection()
            self._rebuild_dialogue_fts(connection)
            self._rebuild_dialogue_line_fts(connection)

    def dialogue_targets(self, *, refresh: bool) -> list[str]:
        """Return active DLG resources that need metric extraction."""
        statement = select(Dialogue.resource_name).where(Dialogue.active == 1)
        if not refresh:
            statement = statement.where(Dialogue.detail_status != "complete")
        with Session(self._engine) as session:
            return list(session.exec(statement.order_by(Dialogue.resource_name)))

    def apply_dialogue_batch(
        self,
        details: Sequence[DialogueExtraction],
        failures: Iterable[tuple[str, str]],
    ) -> None:
        """Persist one bounded batch of DLG metrics, lines, and failures."""
        timestamp = utc_now().isoformat()
        failures = list(failures)
        names = [extraction.detail.resource_name for extraction in details]
        names.extend(resource_name for resource_name, _ in failures)

        with Session(self._engine) as session, session.begin():
            dialogues = self._dialogues_by_name(session, names)
            self._assert_batch_resources(dialogues, names, kind="DLG")
            for extraction in details:
                detail = extraction.detail
                dialogue = dialogues[detail.resource_name.casefold()]
                self._apply_dialogue_detail(dialogue, detail, timestamp)
                session.exec(
                    delete(DialogueLineRecord).where(
                        col(DialogueLineRecord.dialogue_resource_name) == detail.resource_name
                    )
                )
                session.add_all(self._line_record(line, timestamp) for line in extraction.lines)

            for resource_name, error in failures:
                dialogue = dialogues[resource_name.casefold()]
                self._clear_dialogue_detail(dialogue)
                session.exec(
                    delete(DialogueLineRecord).where(
                        col(DialogueLineRecord.dialogue_resource_name) == dialogue.resource_name
                    )
                )
                dialogue.detail_status = "failed"
                dialogue.detail_error = error[:2000]
                dialogue.updated_at = timestamp

            session.flush()
            self._sync_dialogue_line_fts(
                session.connection(),
                (dialogue.resource_name for dialogue in dialogues.values()),
            )

    def rebuild_attributions(self) -> AttributionSummary:
        """Account for every active character and DLG in one atomic snapshot."""
        timestamp = utc_now().isoformat()
        with Session(self._engine) as session, session.begin():
            characters = list(session.exec(select(Character).where(Character.active == 1)))
            dialogues = list(session.exec(select(Dialogue).where(Dialogue.active == 1)))
            dialogues_by_name = {
                dialogue.resource_name.casefold(): dialogue for dialogue in dialogues
            }

            session.exec(delete(CharacterAttribution))
            run = AttributionRun(completed_at=timestamp)
            session.add(run)
            session.flush()
            assert run.id is not None, "SQLite did not create an attribution run id"

            attributions = [
                self._attribute_character(character, dialogues_by_name, run.id, timestamp)
                for character in characters
            ]
            session.add_all(attributions)
            summary = self._summarize_attributions(characters, dialogues, attributions)
            for field, value in summary.model_dump().items():
                setattr(run, field, value)
            return summary

    def finish_run(
        self,
        run_id: int,
        *,
        status: TerminalRunStatus,
        attempted: int,
        extracted: int,
        failures: int,
        error: str | None = None,
    ) -> None:
        """Finalize extraction counters and status."""
        with Session(self._engine) as session, session.begin():
            run = self._run(session, run_id)
            run.completed_at = utc_now().isoformat()
            run.status = status
            run.details_attempted = attempted
            run.details_extracted = extracted
            run.failures = failures
            run.error = error[:2000] if error else None

    def stats(self) -> DatabaseStats:
        """Return validated counts for the active CRE inventory."""
        statement = select(Character.detail_status, Character.dialog_resref).where(
            Character.active == 1
        )
        with Session(self._engine) as session:
            characters = list(session.exec(statement))
        statuses = Counter(status for status, _ in characters)
        return DatabaseStats(
            total=len(characters),
            complete=statuses["complete"],
            failed=statuses["failed"],
            pending=statuses["pending"],
            with_dialog=sum(
                status == "complete" and dialog_resref is not None
                for status, dialog_resref in characters
            ),
        )

    def integrity_check(self) -> str:
        """Verify SQLite storage, each FTS5 index, and FTS/source row counts."""
        with self._engine.connect() as connection:
            result = connection.exec_driver_sql("PRAGMA integrity_check").scalar_one()
        sqlite_result = str(result)
        if sqlite_result != "ok":
            return sqlite_result
        return self._fts_integrity_error() or sqlite_result

    def _create_engine(self) -> Engine:
        return create_engine(
            URL.create("sqlite+pysqlite", database=str(self.path)),
            connect_args={"timeout": 30.0},
            poolclass=StaticPool,
        )

    def _configure_sqlite(self) -> None:
        with self._engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys = ON")
            connection.exec_driver_sql("PRAGMA journal_mode = WAL")
            connection.exec_driver_sql("PRAGMA synchronous = NORMAL")

    def _install_sqlite_features(self) -> None:
        """Install the small amount of schema that SQLModel cannot represent."""
        with self._engine.begin() as connection:
            for ddl in _SQLITE_FEATURE_DDL:
                connection.exec_driver_sql(ddl)

    def _validate_schema_version(self) -> None:
        """Reject existing databases that do not exactly match this schema."""
        assert inspect(self._engine).has_table(SchemaMetadata.__tablename__), (
            "existing database has no schema version; rebuild it from the EET installation"
        )
        with Session(self._engine) as session:
            metadata = session.get(SchemaMetadata, "schema_version")
        assert metadata is not None, (
            "existing database has no schema version; rebuild it from the EET installation"
        )
        assert metadata.value == SCHEMA_VERSION, (
            f"database schema is {metadata.value}; expected {SCHEMA_VERSION}. "
            "Rebuild the generated database from the EET installation."
        )

    def _write_schema_version(self) -> None:
        """Mark a newly created database with the current schema version."""
        with Session(self._engine) as session, session.begin():
            session.add(SchemaMetadata(key="schema_version", value=SCHEMA_VERSION))

    @staticmethod
    def _rebuild_character_fts(connection: Connection) -> None:
        connection.exec_driver_sql(f"DELETE FROM {_CHARACTER_FTS}")
        connection.exec_driver_sql(
            f"""
            INSERT INTO {_CHARACTER_FTS} (
                resource_name, resref, display_name, short_name, long_name, death_variable,
                dialog_resref, scripts
            )
            SELECT resource_name, resref, display_name, short_name, long_name, death_variable,
                   dialog_resref,
                   trim(coalesce(override_script, '') || ' ' || coalesce(class_script, '') ||
                        ' ' || coalesce(race_script, '') || ' ' ||
                        coalesce(general_script, '') || ' ' || coalesce(default_script, ''))
            FROM {_CHARACTER_TABLE}
            WHERE active = 1
            """
        )

    @staticmethod
    def _sync_character_fts(connection: Connection, resource_names: Iterable[str]) -> None:
        names = tuple(dict.fromkeys(resource_names))
        if not names:
            return
        placeholders = ", ".join("?" for _ in names)
        connection.exec_driver_sql(
            f"DELETE FROM {_CHARACTER_FTS} WHERE resource_name IN ({placeholders})",
            names,
        )
        connection.exec_driver_sql(
            f"""
            INSERT INTO {_CHARACTER_FTS} (
                resource_name, resref, display_name, short_name, long_name, death_variable,
                dialog_resref, scripts
            )
            SELECT resource_name, resref, display_name, short_name, long_name, death_variable,
                   dialog_resref,
                   trim(coalesce(override_script, '') || ' ' || coalesce(class_script, '') ||
                        ' ' || coalesce(race_script, '') || ' ' ||
                        coalesce(general_script, '') || ' ' || coalesce(default_script, ''))
            FROM {_CHARACTER_TABLE}
            WHERE resource_name = ? AND active = 1
            """,
            [(name,) for name in names],
        )

    @staticmethod
    def _rebuild_dialogue_fts(connection: Connection) -> None:
        connection.exec_driver_sql(f"DELETE FROM {_DIALOGUE_FTS}")
        connection.exec_driver_sql(
            f"""
            INSERT INTO {_DIALOGUE_FTS} (resource_name, resref, source_path)
            SELECT resource_name, resref, source_path
            FROM {_DIALOGUE_TABLE}
            WHERE active = 1
            """
        )

    @staticmethod
    def _rebuild_dialogue_line_fts(connection: Connection) -> None:
        connection.exec_driver_sql(f"DELETE FROM {_DIALOGUE_LINE_FTS}")
        connection.exec_driver_sql(
            f"""
            INSERT INTO {_DIALOGUE_LINE_FTS} (line_id, dialogue_resource_name, text)
            SELECT line.id, line.dialogue_resource_name, line.text
            FROM {_DIALOGUE_LINE_TABLE} AS line
            JOIN {_DIALOGUE_TABLE} AS dialogue
              ON dialogue.resource_name = line.dialogue_resource_name
            WHERE dialogue.active = 1
            """
        )

    @staticmethod
    def _sync_dialogue_line_fts(connection: Connection, resource_names: Iterable[str]) -> None:
        names = tuple(dict.fromkeys(resource_names))
        if not names:
            return
        placeholders = ", ".join("?" for _ in names)
        connection.exec_driver_sql(
            f"DELETE FROM {_DIALOGUE_LINE_FTS} WHERE dialogue_resource_name IN ({placeholders})",
            names,
        )
        connection.exec_driver_sql(
            f"""
            INSERT INTO {_DIALOGUE_LINE_FTS} (line_id, dialogue_resource_name, text)
            SELECT line.id, line.dialogue_resource_name, line.text
            FROM {_DIALOGUE_LINE_TABLE} AS line
            JOIN {_DIALOGUE_TABLE} AS dialogue
              ON dialogue.resource_name = line.dialogue_resource_name
            WHERE line.dialogue_resource_name = ? AND dialogue.active = 1
            """,
            [(name,) for name in names],
        )

    def _fts_integrity_error(self) -> str | None:
        """Run FTS5's native check and verify each index covers its source rows."""
        with Session(self._engine) as session:
            expected_counts = {
                _CHARACTER_FTS: session.exec(
                    select(func.count()).select_from(Character).where(col(Character.active) == 1)
                ).one(),
                _DIALOGUE_FTS: session.exec(
                    select(func.count()).select_from(Dialogue).where(col(Dialogue.active) == 1)
                ).one(),
                _DIALOGUE_LINE_FTS: session.exec(
                    select(func.count())
                    .select_from(DialogueLineRecord)
                    .join(
                        Dialogue,
                        col(Dialogue.resource_name)
                        == col(DialogueLineRecord.dialogue_resource_name),
                    )
                    .where(col(Dialogue.active) == 1)
                ).one(),
            }

        with self._engine.begin() as connection:
            for fts_table in _FTS_TABLES:
                connection.exec_driver_sql(
                    f"INSERT INTO {fts_table}({fts_table}) VALUES ('integrity-check')"
                )
                indexed = int(
                    connection.exec_driver_sql(f"SELECT COUNT(*) FROM {fts_table}").scalar_one()
                )
                expected = expected_counts[fts_table]
                if indexed != expected:
                    return f"{fts_table} has {indexed} rows; expected {expected}"
        return None

    @staticmethod
    def _run(
        session: Session,
        run_id: int,
        *,
        expected_kind: RunKind | None = None,
    ) -> ExtractionRun:
        run = session.get(ExtractionRun, run_id)
        assert run is not None, f"Unknown extraction run: {run_id}"
        assert expected_kind is None or run.run_kind == expected_kind, (
            f"Extraction run {run_id} is {run.run_kind}; expected {expected_kind}"
        )
        return run

    @staticmethod
    def _invalidate_attributions(session: Session) -> None:
        session.exec(delete(CharacterAttribution))
        session.exec(delete(AttributionRun))

    @staticmethod
    def _assert_batch_resources(
        resources: Mapping[str, Character | Dialogue],
        resource_names: Iterable[str],
        *,
        kind: str,
    ) -> None:
        requested = {name.casefold(): name for name in resource_names}
        missing = [requested[name] for name in requested.keys() - resources.keys()]
        assert not missing, (
            f"{kind} batch contains resources outside the active inventory: {missing}"
        )
        inactive = [
            resource.resource_name for resource in resources.values() if resource.active != 1
        ]
        assert not inactive, f"{kind} batch contains inactive resources: {inactive}"

    @staticmethod
    def _characters_by_name(
        session: Session, resource_names: Iterable[str]
    ) -> dict[str, Character]:
        names = list(resource_names)
        if not names:
            return {}
        rows = session.exec(select(Character).where(col(Character.resource_name).in_(names)))
        return {row.resource_name.casefold(): row for row in rows}

    @staticmethod
    def _dialogues_by_name(session: Session, resource_names: Iterable[str]) -> dict[str, Dialogue]:
        names = list(resource_names)
        if not names:
            return {}
        rows = session.exec(select(Dialogue).where(col(Dialogue.resource_name).in_(names)))
        return {row.resource_name.casefold(): row for row in rows}

    @staticmethod
    def _apply_dialogue_detail(dialogue: Dialogue, detail: DialogueDetail, timestamp: str) -> None:
        assert detail.resref == dialogue.resref, (
            f"DLG detail {detail.resource_name!r} has resref {detail.resref!r}; "
            f"inventory has {dialogue.resref!r}"
        )
        for field, value in detail.model_dump(
            exclude={"resource_name", "resref", "pydantic_json_size"}
        ).items():
            setattr(dialogue, field, value)
        dialogue.detail_json = detail.model_dump_json()
        dialogue.serialized_size = detail.pydantic_json_size
        dialogue.detail_status = "complete"
        dialogue.detail_error = None
        dialogue.updated_at = timestamp

    @staticmethod
    def _clear_character_detail(character: Character) -> None:
        for field in CharacterDetail.model_fields.keys() - {"resource_name"}:
            setattr(character, field, None)
        character.detail_json = None
        character.serialized_size = None

    @staticmethod
    def _clear_dialogue_detail(dialogue: Dialogue) -> None:
        excluded = {"resource_name", "resref", "pydantic_json_size"}
        for field in DialogueDetail.model_fields.keys() - excluded:
            setattr(dialogue, field, None)
        dialogue.detail_json = None
        dialogue.serialized_size = None

    @staticmethod
    def _line_record(line: DialogueLine, timestamp: str) -> DialogueLineRecord:
        line_json = line.model_dump_json()
        return DialogueLineRecord(
            **line.model_dump(),
            serialized_size=len(line_json.encode()),
            updated_at=timestamp,
        )

    @staticmethod
    def _attribute_character(
        character: Character,
        dialogues: dict[str, Dialogue],
        run_id: int,
        timestamp: str,
    ) -> CharacterAttribution:
        dialogue = (
            dialogues.get(f"{character.dialog_resref}.DLG".casefold())
            if character.dialog_resref is not None
            else None
        )
        status: AttributionStatus
        if character.detail_status != "complete":
            status = "character_unavailable"
        elif character.dialog_resref is None:
            status = "no_dialogue"
        elif dialogue is None:
            status = "missing_dialogue"
        elif dialogue.detail_status != "complete":
            status = "dialogue_failed"
        else:
            status = "matched"

        return CharacterAttribution(
            character_resource_name=character.resource_name,
            dialog_resref=character.dialog_resref,
            dialogue_resource_name=dialogue.resource_name if dialogue else None,
            attribution_status=status,
            dialogue_line_count=dialogue.dialogue_line_count if dialogue else None,
            npc_line_count=dialogue.npc_line_count if dialogue else None,
            player_line_count=dialogue.player_line_count if dialogue else None,
            journal_line_count=dialogue.journal_line_count if dialogue else None,
            dialogue_state_count=dialogue.state_count if dialogue else None,
            dialogue_transition_count=dialogue.transition_count if dialogue else None,
            attribution_run_id=run_id,
            updated_at=timestamp,
        )

    @staticmethod
    def _summarize_attributions(
        characters: Sequence[Character],
        dialogues: Sequence[Dialogue],
        attributions: Sequence[CharacterAttribution],
    ) -> AttributionSummary:
        statuses = Counter(attribution.attribution_status for attribution in attributions)
        attributed = {
            attribution.dialogue_resource_name.casefold()
            for attribution in attributions
            if attribution.dialogue_resource_name is not None
        }
        attributed_dialogues = [
            dialogue for dialogue in dialogues if dialogue.resource_name.casefold() in attributed
        ]
        unattributed_dialogues = [
            dialogue
            for dialogue in dialogues
            if dialogue.resource_name.casefold() not in attributed
        ]
        return AttributionSummary(
            characters_total=len(characters),
            characters_matched=statuses["matched"],
            characters_missing_dialogue=statuses["missing_dialogue"],
            characters_dialogue_failed=statuses["dialogue_failed"],
            characters_without_dialogue=statuses["no_dialogue"],
            characters_unavailable=statuses["character_unavailable"],
            dialogues_total=len(dialogues),
            dialogues_attributed=len(attributed_dialogues),
            dialogues_unattributed=len(unattributed_dialogues),
            attributed_dialogue_lines=sum(
                dialogue.dialogue_line_count or 0 for dialogue in attributed_dialogues
            ),
            unattributed_dialogue_lines=sum(
                dialogue.dialogue_line_count or 0 for dialogue in unattributed_dialogues
            ),
        )
