"""Typed LanceDB storage for the EET extraction pipeline."""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Self
from uuid import uuid4

import lancedb
import pyarrow as pa
from lancedb.expr import col
from lancedb.index import FTS, BTree
from lancedb.pydantic import LanceModel
from lancedb.table import Table
from pydantic import ConfigDict, Field, model_validator

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

_CHARACTERS = "characters"
_DIALOGUES = "dialogues"
_DIALOGUE_LINES = "dialogue_lines"
_EXTRACTION_RUNS = "extraction_runs"
TABLE_NAMES = frozenset({_CHARACTERS, _DIALOGUES, _DIALOGUE_LINES, _EXTRACTION_RUNS})

_FTS = FTS(
    base_tokenizer="simple",
    language="English",
    with_position=True,
    max_token_length=64,
    lower_case=True,
    stem=True,
    remove_stop_words=False,
    ascii_folding=True,
)


@dataclass(frozen=True, slots=True)
class IndexSpec:
    column: str
    config: BTree | FTS
    name: str


TABLE_INDEXES: dict[str, tuple[IndexSpec, ...]] = {
    _CHARACTERS: (
        IndexSpec("resource_name", BTree(), "characters_resource_name_btree"),
        IndexSpec("search_text", _FTS, "characters_search_fts"),
    ),
    _DIALOGUES: (
        IndexSpec("resource_name", BTree(), "dialogues_resource_name_btree"),
        IndexSpec("search_text", _FTS, "dialogues_search_fts"),
    ),
    _DIALOGUE_LINES: (
        IndexSpec("id", BTree(), "dialogue_lines_id_btree"),
        IndexSpec(
            "dialogue_resource_name",
            BTree(),
            "dialogue_lines_dialogue_btree",
        ),
        IndexSpec("search_text", _FTS, "dialogue_lines_search_fts"),
    ),
    _EXTRACTION_RUNS: (),
}


class _Record(LanceModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    @classmethod
    def to_arrow_schema(cls) -> pa.Schema:
        """Store typed string enums as ordinary UTF-8 Lance columns."""
        schema = super().to_arrow_schema()
        fields = [
            pa.field(field.name, pa.string(), field.nullable, field.metadata)
            if pa.types.is_dictionary(field.type)
            else field
            for field in schema
        ]
        return pa.schema(fields, metadata=schema.metadata)


class CharacterRecord(_Record):
    """One effective CRE and its current extraction and attribution state."""

    resource_name: str = Field(min_length=1)
    resref: str = Field(min_length=1, max_length=8)
    source_kind: SourceKind = Field(strict=False)
    source_path: str = Field(min_length=1)

    display_name: str | None = None
    short_name: str | None = None
    short_name_strref: int | None = Field(default=None, ge=0)
    long_name: str | None = None
    long_name_strref: int | None = Field(default=None, ge=0)
    death_variable: str | None = None
    dialog_resref: str | None = None
    gender_id: int | None = Field(default=None, ge=0)
    race_id: int | None = Field(default=None, ge=0)
    class_id: int | None = Field(default=None, ge=0)
    alignment_id: int | None = Field(default=None, ge=0)
    enemy_ally_id: int | None = Field(default=None, ge=0)
    general_id: int | None = Field(default=None, ge=0)
    specific_id: int | None = Field(default=None, ge=0)
    override_script: str | None = None
    class_script: str | None = None
    race_script: str | None = None
    general_script: str | None = None
    default_script: str | None = None
    small_portrait: str | None = None
    large_portrait: str | None = None
    cre_version: str | None = None

    serialized_size: int | None = Field(default=None, ge=0)
    detail_status: DetailStatus = Field(strict=False)
    detail_error: str | None = None
    updated_at: str = Field(min_length=1)
    has_dialog: bool

    attribution_status: AttributionStatus | None = Field(default=None, strict=False)
    dialogue_status: DetailStatus | None = Field(default=None, strict=False)
    dialogue_line_count: int | None = Field(default=None, ge=0)
    npc_line_count: int | None = Field(default=None, ge=0)
    player_line_count: int | None = Field(default=None, ge=0)
    journal_line_count: int | None = Field(default=None, ge=0)
    dialogue_state_count: int | None = Field(default=None, ge=0)
    dialogue_transition_count: int | None = Field(default=None, ge=0)
    dialogue_serialized_size: int | None = Field(default=None, ge=0)
    attribution_completed_at: str | None = None
    search_text: str

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.detail_status is DetailStatus.COMPLETE:
            required = (
                self.display_name,
                self.short_name_strref,
                self.long_name_strref,
                self.gender_id,
                self.race_id,
                self.class_id,
                self.alignment_id,
                self.enemy_ally_id,
                self.general_id,
                self.specific_id,
                self.cre_version,
                self.serialized_size,
            )
            assert all(value is not None for value in required), (
                "complete character record is missing required CRE detail"
            )
        assert self.has_dialog == (
            self.detail_status is DetailStatus.COMPLETE and self.dialog_resref is not None
        ), "has_dialog disagrees with the extracted CRE detail"
        assert (self.attribution_status is None) == (self.attribution_completed_at is None), (
            "character attribution status and completion time must be set together"
        )
        return self


class DialogueRecord(_Record):
    """One effective DLG and its current extraction and attribution state."""

    resource_name: str = Field(min_length=1)
    resref: str = Field(min_length=1, max_length=8)
    source_kind: SourceKind = Field(strict=False)
    source_path: str = Field(min_length=1)

    dlg_version: str | None = None
    state_count: int | None = Field(default=None, ge=0)
    transition_count: int | None = Field(default=None, ge=0)
    npc_line_count: int | None = Field(default=None, ge=0)
    player_line_count: int | None = Field(default=None, ge=0)
    journal_line_count: int | None = Field(default=None, ge=0)
    dialogue_line_count: int | None = Field(default=None, ge=0)
    serialized_size: int | None = Field(default=None, ge=0)
    detail_status: DetailStatus = Field(strict=False)
    detail_error: str | None = None
    updated_at: str = Field(min_length=1)

    character_count: int = Field(ge=0)
    attribution_completed_at: str | None = None
    search_text: str

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        metrics = (
            self.state_count,
            self.transition_count,
            self.npc_line_count,
            self.player_line_count,
            self.journal_line_count,
            self.dialogue_line_count,
            self.serialized_size,
        )
        if self.detail_status is DetailStatus.COMPLETE:
            assert self.dlg_version is not None and all(value is not None for value in metrics), (
                "complete dialogue record is missing required DLG detail"
            )
            assert self.dialogue_line_count is not None
            assert self.npc_line_count is not None
            assert self.player_line_count is not None
            assert self.dialogue_line_count == self.npc_line_count + self.player_line_count, (
                "dialogue line count must equal NPC plus player lines"
            )
        assert self.attribution_completed_at is not None or self.character_count == 0, (
            "unattributed dialogue cannot have a character count"
        )
        return self


class DialogueLineRecord(_Record):
    """One stable, addressable DLG line."""

    id: str = Field(min_length=1)
    dialogue_resource_name: str = Field(min_length=1)
    dialogue_resref: str = Field(min_length=1, max_length=8)
    source_kind: SourceKind = Field(strict=False)
    line_kind: DialogueLineKind = Field(strict=False)
    state_index: int = Field(ge=0)
    transition_index: int | None = Field(default=None, ge=0)
    strref: int = Field(ge=0)
    text: str | None
    serialized_size: int = Field(ge=0)
    character_count: int = Field(ge=0)
    attribution_completed_at: str | None = None
    search_text: str

    @model_validator(mode="after")
    def validate_coordinates(self) -> Self:
        assert (self.line_kind is DialogueLineKind.NPC) == (self.transition_index is None), (
            "NPC lines must omit transition_index; player and journal lines must include it"
        )
        expected_id = _line_id(
            self.dialogue_resource_name,
            self.line_kind,
            self.state_index,
            self.transition_index,
        )
        assert self.id == expected_id, f"dialogue line id must be {expected_id!r}"
        assert self.attribution_completed_at is not None or self.character_count == 0, (
            "unattributed dialogue line cannot have a character count"
        )
        return self


class ExtractionRunRecord(_Record):
    """Durable lifecycle record for one inventory and detail extraction run."""

    id: str = Field(min_length=1)
    run_kind: RunKind = Field(strict=False)
    started_at: str = Field(min_length=1)
    completed_at: str | None = None
    game_root: str = Field(min_length=1)
    iecli_version: str = Field(min_length=1)
    status: RunStatus = Field(strict=False)
    resources_discovered: int = Field(ge=0)
    details_attempted: int = Field(ge=0)
    details_extracted: int = Field(ge=0)
    failures: int = Field(ge=0)
    error: str | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        assert (self.status is RunStatus.RUNNING) == (self.completed_at is None), (
            "running runs must be open and terminal runs must have a completion time"
        )
        return self


class PipelineDatabase:
    """Single-writer LanceDB repository for the extraction pipeline."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        is_new = not self.path.exists()
        assert is_new or self.path.is_dir(), f"LanceDB path is not a directory: {self.path}"
        self.path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(self.path, read_consistency_interval=timedelta(0))
        existing = frozenset(self._db.list_tables(limit=None).tables)
        assert (is_new and not existing) or existing == TABLE_NAMES, (
            f"LanceDB tables are {sorted(existing)}; expected {sorted(TABLE_NAMES)}"
        )
        self._ensure_table(_CHARACTERS, CharacterRecord)
        self._ensure_table(_DIALOGUES, DialogueRecord)
        self._ensure_table(_DIALOGUE_LINES, DialogueLineRecord)
        self._ensure_table(_EXTRACTION_RUNS, ExtractionRunRecord)

    def start_run(
        self,
        game_root: Path,
        iecli_version: str,
        *,
        run_kind: RunKind = RunKind.CHARACTERS,
    ) -> str:
        """Create a durable extraction-run record."""
        run_id = uuid4().hex
        assert not self._find_runs(run_id), f"Duplicate extraction run id: {run_id}"
        self._table(_EXTRACTION_RUNS).add(
            [
                ExtractionRunRecord(
                    id=run_id,
                    run_kind=run_kind,
                    started_at=utc_now().isoformat(),
                    completed_at=None,
                    game_root=str(game_root.expanduser().resolve()),
                    iecli_version=iecli_version,
                    status=RunStatus.RUNNING,
                    resources_discovered=0,
                    details_attempted=0,
                    details_extracted=0,
                    failures=0,
                    error=None,
                )
            ]
        )
        return run_id

    def replace_inventory(self, run_id: str, resources: Sequence[CreResource]) -> None:
        """Replace the complete CRE inventory, preserving unchanged extracted details."""
        run = self._run(run_id, expected_kind=RunKind.CHARACTERS)
        self._assert_unique_names(
            [resource.resource_name for resource in resources], kind="CRE inventory"
        )
        timestamp = utc_now().isoformat()
        existing = {
            record.resource_name.casefold(): record
            for record in self._records(_CHARACTERS, CharacterRecord)
        }
        replacement: list[CharacterRecord] = []
        for resource in resources:
            key = resource.resource_name.casefold()
            if key in existing and _same_identity(existing[key], resource):
                replacement.append(
                    _validated_character_copy(
                        existing[key],
                        resource_name=resource.resource_name,
                        updated_at=timestamp,
                        clear_attribution=True,
                    )
                )
            else:
                replacement.append(_pending_character(resource, timestamp))

        updated_run = ExtractionRunRecord.model_validate(
            run.model_dump() | {"resources_discovered": len(resources)}
        )
        self._replace(_CHARACTERS, "resource_name", CharacterRecord, replacement)
        self._invalidate_other_attributions(invalidate_characters=False)
        self._merge(_EXTRACTION_RUNS, "id", [updated_run])

    def detail_targets(self, *, refresh: bool) -> set[str]:
        """Return CRE resources that need detail extraction."""
        characters = self._records(_CHARACTERS, CharacterRecord)
        return {
            character.resource_name
            for character in characters
            if refresh or character.detail_status is not DetailStatus.COMPLETE
        }

    def apply_detail_batch(
        self,
        details: Sequence[CharacterDetail],
        failures: Iterable[tuple[str, str]],
    ) -> None:
        """Persist one validated batch of successful and failed CRE details."""
        failures = list(failures)
        success_names = [detail.resource_name for detail in details]
        failure_names = [resource_name for resource_name, _ in failures]
        self._assert_batch_names(success_names, failure_names, kind="CRE")
        characters = {
            record.resource_name.casefold(): record
            for record in self._records(_CHARACTERS, CharacterRecord)
        }
        requested = success_names + failure_names
        missing = [name for name in requested if name.casefold() not in characters]
        assert not missing, f"CRE batch contains resources outside the inventory: {missing}"

        timestamp = utc_now().isoformat()
        updates = [
            _completed_character(characters[detail.resource_name.casefold()], detail, timestamp)
            for detail in details
        ]
        updates.extend(
            _failed_character(characters[resource_name.casefold()], error, timestamp)
            for resource_name, error in failures
        )
        self._merge(_CHARACTERS, "resource_name", updates)

    def replace_dialogue_inventory(
        self,
        run_id: str,
        resources: Sequence[DlgResource],
    ) -> None:
        """Replace the complete DLG inventory and discard lines for changed identities."""
        run = self._run(run_id, expected_kind=RunKind.DIALOGUES)
        self._assert_unique_names(
            [resource.resource_name for resource in resources], kind="DLG inventory"
        )
        timestamp = utc_now().isoformat()
        existing = {
            record.resource_name.casefold(): record
            for record in self._records(_DIALOGUES, DialogueRecord)
        }
        replacement: list[DialogueRecord] = []
        retained_names: set[str] = set()
        for resource in resources:
            key = resource.resource_name.casefold()
            if key in existing and _same_identity(existing[key], resource):
                replacement.append(
                    _validated_dialogue_copy(
                        existing[key],
                        resource_name=resource.resource_name,
                        updated_at=timestamp,
                        clear_attribution=True,
                    )
                )
                retained_names.add(existing[key].resource_name)
            else:
                replacement.append(_pending_dialogue(resource, timestamp))

        discarded_names = sorted(
            dialogue.resource_name
            for dialogue in existing.values()
            if dialogue.resource_name not in retained_names
        )
        updated_run = ExtractionRunRecord.model_validate(
            run.model_dump() | {"resources_discovered": len(resources)}
        )
        self._invalidate_other_attributions(invalidate_dialogues=False)
        if discarded_names:
            self._table(_DIALOGUE_LINES).delete(col("dialogue_resource_name").isin(discarded_names))
        self._replace(_DIALOGUES, "resource_name", DialogueRecord, replacement)
        self._merge(_EXTRACTION_RUNS, "id", [updated_run])

    def dialogue_targets(self, *, refresh: bool) -> list[str]:
        """Return DLG resources that need metric and line extraction."""
        dialogues = self._records(_DIALOGUES, DialogueRecord)
        return sorted(
            (
                dialogue.resource_name
                for dialogue in dialogues
                if refresh or dialogue.detail_status is not DetailStatus.COMPLETE
            ),
            key=str.casefold,
        )

    def apply_dialogue_batch(
        self,
        details: Sequence[DialogueExtraction],
        failures: Iterable[tuple[str, str]],
    ) -> None:
        """Persist one validated batch of DLG metrics, lines, and failures."""
        failures = list(failures)
        success_names = [extraction.detail.resource_name for extraction in details]
        failure_names = [resource_name for resource_name, _ in failures]
        self._assert_batch_names(success_names, failure_names, kind="DLG")
        dialogues = {
            record.resource_name.casefold(): record
            for record in self._records(_DIALOGUES, DialogueRecord)
        }
        requested = success_names + failure_names
        missing = [name for name in requested if name.casefold() not in dialogues]
        assert not missing, f"DLG batch contains resources outside the inventory: {missing}"

        timestamp = utc_now().isoformat()
        dialogue_updates: list[DialogueRecord] = []
        line_records: list[DialogueLineRecord] = []
        for extraction in details:
            detail = extraction.detail
            dialogue = dialogues[detail.resource_name.casefold()]
            assert detail.resref == dialogue.resref, (
                f"DLG detail {detail.resource_name!r} has resref {detail.resref!r}; "
                f"inventory has {dialogue.resref!r}"
            )
            dialogue_updates.append(_completed_dialogue(dialogue, detail, timestamp))
            line_records.extend(_dialogue_line_record(dialogue, line) for line in extraction.lines)
        dialogue_updates.extend(
            _failed_dialogue(dialogues[resource_name.casefold()], error, timestamp)
            for resource_name, error in failures
        )
        self._assert_unique_names([line.id for line in line_records], kind="DLG line batch")

        stored_names = [dialogues[name.casefold()].resource_name for name in requested]
        if requested:
            self._merge(
                _DIALOGUES,
                "resource_name",
                [
                    _pending_dialogue_refresh(dialogues[name.casefold()], timestamp)
                    for name in requested
                ],
            )
        if line_records:
            self._upsert(_DIALOGUE_LINES, "id", line_records)
        if requested:
            stale_lines = col("dialogue_resource_name").isin(stored_names)
            if line_records:
                stale_lines &= ~col("id").isin([line.id for line in line_records])
            self._table(_DIALOGUE_LINES).delete(stale_lines)
        self._merge(_DIALOGUES, "resource_name", dialogue_updates)

    def rebuild_attributions(self) -> AttributionSummary:
        """Account for every current character, dialogue, and spoken line."""
        timestamp = utc_now().isoformat()
        characters = self._records(_CHARACTERS, CharacterRecord)
        dialogues = self._records(_DIALOGUES, DialogueRecord)
        lines = self._records(_DIALOGUE_LINES, DialogueLineRecord)
        self._assert_dialogue_lines(dialogues, lines)
        dialogues_by_name = {dialogue.resource_name.casefold(): dialogue for dialogue in dialogues}

        character_counts: Counter[str] = Counter()
        for character in characters:
            if character.dialog_resref is None:
                continue
            dialogue_name = f"{character.dialog_resref}.DLG".casefold()
            if dialogue_name in dialogues_by_name:
                character_counts[dialogue_name] += 1

        dialogue_updates = [
            DialogueRecord.model_validate(
                dialogue.model_dump()
                | {
                    "character_count": character_counts[dialogue.resource_name.casefold()],
                    "attribution_completed_at": timestamp,
                }
            )
            for dialogue in dialogues
        ]
        updated_dialogues = {
            dialogue.resource_name.casefold(): dialogue for dialogue in dialogue_updates
        }
        character_updates = [
            _attributed_character(character, updated_dialogues, timestamp)
            for character in characters
        ]
        line_updates = [
            DialogueLineRecord.model_validate(
                line.model_dump()
                | {
                    "character_count": character_counts[line.dialogue_resource_name.casefold()],
                    "attribution_completed_at": timestamp,
                }
            )
            for line in lines
        ]

        statuses = Counter(character.attribution_status for character in character_updates)
        attributed_dialogues = [
            dialogue for dialogue in dialogue_updates if dialogue.character_count > 0
        ]
        unattributed_dialogues = [
            dialogue for dialogue in dialogue_updates if dialogue.character_count == 0
        ]
        attributed_lines = sum(
            dialogue.dialogue_line_count or 0 for dialogue in attributed_dialogues
        )
        unattributed_lines = sum(
            dialogue.dialogue_line_count or 0 for dialogue in unattributed_dialogues
        )
        all_spoken_lines = sum(dialogue.dialogue_line_count or 0 for dialogue in dialogues)
        assert attributed_lines + unattributed_lines == all_spoken_lines, (
            "attributed and unattributed DLG line totals do not reconcile"
        )
        summary = AttributionSummary(
            characters_total=len(character_updates),
            characters_matched=statuses[AttributionStatus.MATCHED],
            characters_missing_dialogue=statuses[AttributionStatus.MISSING_DIALOGUE],
            characters_dialogue_failed=statuses[AttributionStatus.DIALOGUE_FAILED],
            characters_without_dialogue=statuses[AttributionStatus.NO_DIALOGUE],
            characters_unavailable=statuses[AttributionStatus.CHARACTER_UNAVAILABLE],
            dialogues_total=len(dialogue_updates),
            dialogues_attributed=len(attributed_dialogues),
            dialogues_unattributed=len(unattributed_dialogues),
            attributed_dialogue_lines=attributed_lines,
            unattributed_dialogue_lines=unattributed_lines,
        )
        if any(character.attribution_completed_at is not None for character in characters):
            self._merge(
                _CHARACTERS,
                "resource_name",
                [
                    _validated_character_copy(character, clear_attribution=True)
                    for character in characters
                ],
            )
        self._merge(_DIALOGUES, "resource_name", dialogue_updates)
        self._merge(_DIALOGUE_LINES, "id", line_updates)
        self._optimize(_DIALOGUES, self._table(_DIALOGUES))
        self._optimize(_DIALOGUE_LINES, self._table(_DIALOGUE_LINES))
        self._merge(_CHARACTERS, "resource_name", character_updates)
        self._optimize(_CHARACTERS, self._table(_CHARACTERS))
        return summary

    def finish_run(
        self,
        run_id: str,
        *,
        status: TerminalRunStatus,
        attempted: int,
        extracted: int,
        failures: int,
        error: str | None = None,
    ) -> None:
        """Finalize extraction counters and rebuild indexes for the completed stage."""
        run = self._run(run_id)
        updated = ExtractionRunRecord.model_validate(
            run.model_dump()
            | {
                "completed_at": utc_now().isoformat(),
                "status": status,
                "details_attempted": attempted,
                "details_extracted": extracted,
                "failures": failures,
                "error": error[:2000] if error else None,
            }
        )
        if status is not RunStatus.FAILED:
            if run.run_kind is RunKind.CHARACTERS:
                self._optimize(_CHARACTERS, self._table(_CHARACTERS))
            else:
                self._optimize(_DIALOGUES, self._table(_DIALOGUES))
                self._optimize(_DIALOGUE_LINES, self._table(_DIALOGUE_LINES))
        self._merge(_EXTRACTION_RUNS, "id", [updated])

    def stats(self) -> DatabaseStats:
        """Return validated counts for the current CRE inventory."""
        characters = self._records(_CHARACTERS, CharacterRecord)
        statuses = Counter(character.detail_status for character in characters)
        return DatabaseStats(
            total=len(characters),
            complete=statuses[DetailStatus.COMPLETE],
            failed=statuses[DetailStatus.FAILED],
            pending=statuses[DetailStatus.PENDING],
            with_dialog=sum(character.has_dialog for character in characters),
        )

    def _ensure_table[Record: LanceModel](self, name: str, model: type[Record]) -> None:
        names = set(self._db.list_tables(limit=None).tables)
        if name not in names:
            table = self._db.create_table(name, schema=model)
            self._create_indexes(name, table)
        table = self._table(name)
        self._assert_schema(name, table, model)
        self._assert_indexes(name, table)

    def _replace[Record: LanceModel](
        self,
        name: str,
        key: str,
        model: type[Record],
        records: Sequence[Record],
    ) -> None:
        rows = list(records)
        data = rows or pa.Table.from_pylist([], schema=model.to_arrow_schema())
        table = self._table(name)
        result = (
            table.merge_insert(key)
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .when_not_matched_by_source_delete()
            .execute(data)
        )
        assert result.num_rows == len(rows), (
            f"{name} replaced {result.num_rows} rows; expected {len(rows)}"
        )
        row_count = table.count_rows()
        assert row_count == len(rows), f"{name} contains {row_count} rows; expected {len(rows)}"
        self._assert_schema(name, table, model)
        self._assert_indexes(name, table)

    def _records[Record: LanceModel](
        self,
        table_name: str,
        model: type[Record],
    ) -> list[Record]:
        return self._table(table_name).search().limit(None).to_pydantic(model)

    def _find_runs(self, run_id: str) -> list[ExtractionRunRecord]:
        return (
            self._table(_EXTRACTION_RUNS)
            .search()
            .where(col("id") == run_id)
            .limit(2)
            .to_pydantic(ExtractionRunRecord)
        )

    def _run(
        self,
        run_id: str,
        *,
        expected_kind: RunKind | None = None,
    ) -> ExtractionRunRecord:
        matches = self._find_runs(run_id)
        assert matches, f"Unknown extraction run: {run_id}"
        assert len(matches) == 1, f"Duplicate extraction run id: {run_id}"
        run = matches[0]
        assert run.status is RunStatus.RUNNING, f"Extraction run {run_id} is already {run.status}"
        assert expected_kind is None or run.run_kind == expected_kind, (
            f"Extraction run {run_id} is {run.run_kind}; expected {expected_kind}"
        )
        return run

    def _invalidate_other_attributions(
        self,
        *,
        invalidate_characters: bool = True,
        invalidate_dialogues: bool = True,
    ) -> None:
        if invalidate_characters:
            characters = self._records(_CHARACTERS, CharacterRecord)
            if any(character.attribution_completed_at is not None for character in characters):
                self._merge(
                    _CHARACTERS,
                    "resource_name",
                    [
                        _validated_character_copy(character, clear_attribution=True)
                        for character in characters
                    ],
                )
        if invalidate_dialogues:
            dialogues = self._records(_DIALOGUES, DialogueRecord)
            if any(dialogue.attribution_completed_at is not None for dialogue in dialogues):
                self._merge(
                    _DIALOGUES,
                    "resource_name",
                    [
                        _validated_dialogue_copy(dialogue, clear_attribution=True)
                        for dialogue in dialogues
                    ],
                )
        lines = self._records(_DIALOGUE_LINES, DialogueLineRecord)
        if any(line.attribution_completed_at is not None for line in lines):
            self._merge(
                _DIALOGUE_LINES,
                "id",
                [
                    DialogueLineRecord.model_validate(
                        line.model_dump()
                        | {
                            "character_count": 0,
                            "attribution_completed_at": None,
                        }
                    )
                    for line in lines
                ],
            )

    def _merge[Record: LanceModel](
        self,
        table_name: str,
        key: str,
        records: Sequence[Record],
    ) -> None:
        if not records:
            return
        result = (
            self._table(table_name)
            .merge_insert(key)
            .when_matched_update_all()
            .execute(list(records))
        )
        assert result.num_updated_rows == len(records), (
            f"{table_name} updated {result.num_updated_rows} rows; expected {len(records)}"
        )

    def _upsert[Record: LanceModel](
        self,
        table_name: str,
        key: str,
        records: Sequence[Record],
    ) -> None:
        result = (
            self._table(table_name)
            .merge_insert(key)
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(list(records))
        )
        changed = result.num_updated_rows + result.num_inserted_rows
        assert changed == len(records), (
            f"{table_name} upserted {changed} rows; expected {len(records)}"
        )

    def _table(self, name: str) -> Table:
        return self._db.open_table(name)

    @staticmethod
    def _assert_schema[Record: LanceModel](
        name: str,
        table: Table,
        model: type[Record],
    ) -> None:
        expected = model.to_arrow_schema()
        assert table.schema.equals(expected, check_metadata=True), (
            f"LanceDB table {name!r} has schema {table.schema}; expected {expected}"
        )

    @staticmethod
    def _create_indexes(name: str, table: Table) -> None:
        for index in TABLE_INDEXES[name]:
            table.create_index(index.column, config=index.config, name=index.name)

    @classmethod
    def _optimize(cls, name: str, table: Table) -> None:
        table.optimize()
        cls._assert_indexes(name, table)

    @staticmethod
    def _assert_indexes(name: str, table: Table) -> None:
        actual = {
            (index.name, index.index_type, tuple(index.columns)) for index in table.list_indices()
        }
        expected = {
            (index.name, type(index.config).__name__, (index.column,))
            for index in TABLE_INDEXES[name]
        }
        assert actual == expected, (
            f"LanceDB table {name!r} has indexes {sorted(actual)}; expected {sorted(expected)}"
        )

    @staticmethod
    def _assert_unique_names(names: Sequence[str], *, kind: str) -> None:
        folded = [name.casefold() for name in names]
        counts = Counter(folded)
        duplicates = sorted({name for name in folded if counts[name] > 1})
        assert not duplicates, f"{kind} contains duplicate keys: {duplicates}"

    @classmethod
    def _assert_batch_names(
        cls,
        success_names: Sequence[str],
        failure_names: Sequence[str],
        *,
        kind: str,
    ) -> None:
        cls._assert_unique_names(success_names, kind=f"{kind} successes")
        cls._assert_unique_names(failure_names, kind=f"{kind} failures")
        overlap = sorted(
            {name.casefold() for name in success_names}
            & {name.casefold() for name in failure_names}
        )
        assert not overlap, f"{kind} batch has both success and failure for: {overlap}"

    @staticmethod
    def _assert_dialogue_lines(
        dialogues: Sequence[DialogueRecord],
        lines: Sequence[DialogueLineRecord],
    ) -> None:
        dialogue_names = {dialogue.resource_name.casefold() for dialogue in dialogues}
        unknown = sorted(
            {
                line.dialogue_resource_name
                for line in lines
                if line.dialogue_resource_name.casefold() not in dialogue_names
            }
        )
        assert not unknown, f"dialogue lines reference unknown DLG resources: {unknown}"

        counts = Counter((line.dialogue_resource_name.casefold(), line.line_kind) for line in lines)
        for dialogue in dialogues:
            key = dialogue.resource_name.casefold()
            actual = tuple(
                counts[(key, kind)]
                for kind in (
                    DialogueLineKind.NPC,
                    DialogueLineKind.PLAYER,
                    DialogueLineKind.JOURNAL,
                )
            )
            expected = (
                (
                    dialogue.npc_line_count,
                    dialogue.player_line_count,
                    dialogue.journal_line_count,
                )
                if dialogue.detail_status is DetailStatus.COMPLETE
                else (0, 0, 0)
            )
            assert actual == expected, (
                f"{dialogue.resource_name} stores line counts {actual}; expected {expected}"
            )


def _pending_character(resource: CreResource, timestamp: str) -> CharacterRecord:
    return CharacterRecord(
        resource_name=resource.resource_name,
        resref=resource.resref,
        source_kind=resource.source_kind,
        source_path=resource.source_path,
        detail_status=DetailStatus.PENDING,
        detail_error=None,
        updated_at=timestamp,
        has_dialog=False,
        search_text=_search_text(resource.resource_name, resource.resref),
    )


def _completed_character(
    character: CharacterRecord,
    detail: CharacterDetail,
    timestamp: str,
) -> CharacterRecord:
    serialized_size = len(detail.model_dump_json().encode("utf-8"))
    return CharacterRecord(
        resource_name=character.resource_name,
        resref=character.resref,
        source_kind=character.source_kind,
        source_path=character.source_path,
        display_name=detail.display_name,
        short_name=detail.short_name,
        short_name_strref=detail.short_name_strref,
        long_name=detail.long_name,
        long_name_strref=detail.long_name_strref,
        death_variable=detail.death_variable,
        dialog_resref=detail.dialog_resref,
        gender_id=detail.gender_id,
        race_id=detail.race_id,
        class_id=detail.class_id,
        alignment_id=detail.alignment_id,
        enemy_ally_id=detail.enemy_ally_id,
        general_id=detail.general_id,
        specific_id=detail.specific_id,
        override_script=detail.override_script,
        class_script=detail.class_script,
        race_script=detail.race_script,
        general_script=detail.general_script,
        default_script=detail.default_script,
        small_portrait=detail.small_portrait,
        large_portrait=detail.large_portrait,
        cre_version=detail.cre_version,
        serialized_size=serialized_size,
        detail_status=DetailStatus.COMPLETE,
        detail_error=None,
        updated_at=timestamp,
        has_dialog=detail.dialog_resref is not None,
        search_text=_search_text(
            character.resource_name,
            character.resref,
            detail.display_name,
            detail.short_name,
            detail.long_name,
            detail.death_variable,
            detail.dialog_resref,
            detail.override_script,
            detail.class_script,
            detail.race_script,
            detail.general_script,
            detail.default_script,
        ),
    )


def _failed_character(
    character: CharacterRecord,
    error: str,
    timestamp: str,
) -> CharacterRecord:
    return CharacterRecord(
        resource_name=character.resource_name,
        resref=character.resref,
        source_kind=character.source_kind,
        source_path=character.source_path,
        detail_status=DetailStatus.FAILED,
        detail_error=error[:2000],
        updated_at=timestamp,
        has_dialog=False,
        search_text=_search_text(character.resource_name, character.resref),
    )


def _validated_character_copy(
    character: CharacterRecord,
    *,
    resource_name: str | None = None,
    updated_at: str | None = None,
    clear_attribution: bool,
) -> CharacterRecord:
    update: dict[str, object] = {}
    if resource_name is not None:
        update["resource_name"] = resource_name
    if updated_at is not None:
        update["updated_at"] = updated_at
    if clear_attribution:
        update |= {
            "attribution_status": None,
            "dialogue_status": None,
            "dialogue_line_count": None,
            "npc_line_count": None,
            "player_line_count": None,
            "journal_line_count": None,
            "dialogue_state_count": None,
            "dialogue_transition_count": None,
            "dialogue_serialized_size": None,
            "attribution_completed_at": None,
        }
    return CharacterRecord.model_validate(character.model_dump() | update)


def _pending_dialogue(resource: DlgResource, timestamp: str) -> DialogueRecord:
    return DialogueRecord(
        resource_name=resource.resource_name,
        resref=resource.resref,
        source_kind=resource.source_kind,
        source_path=resource.source_path,
        detail_status=DetailStatus.PENDING,
        detail_error=None,
        updated_at=timestamp,
        character_count=0,
        attribution_completed_at=None,
        search_text=_search_text(resource.resource_name, resource.resref, resource.source_path),
    )


def _completed_dialogue(
    dialogue: DialogueRecord,
    detail: DialogueDetail,
    timestamp: str,
) -> DialogueRecord:
    return DialogueRecord(
        resource_name=dialogue.resource_name,
        resref=dialogue.resref,
        source_kind=dialogue.source_kind,
        source_path=dialogue.source_path,
        dlg_version=detail.dlg_version,
        state_count=detail.state_count,
        transition_count=detail.transition_count,
        npc_line_count=detail.npc_line_count,
        player_line_count=detail.player_line_count,
        journal_line_count=detail.journal_line_count,
        dialogue_line_count=detail.dialogue_line_count,
        serialized_size=detail.pydantic_json_size,
        detail_status=DetailStatus.COMPLETE,
        detail_error=None,
        updated_at=timestamp,
        character_count=0,
        attribution_completed_at=None,
        search_text=dialogue.search_text,
    )


def _failed_dialogue(
    dialogue: DialogueRecord,
    error: str,
    timestamp: str,
) -> DialogueRecord:
    return DialogueRecord(
        resource_name=dialogue.resource_name,
        resref=dialogue.resref,
        source_kind=dialogue.source_kind,
        source_path=dialogue.source_path,
        detail_status=DetailStatus.FAILED,
        detail_error=error[:2000],
        updated_at=timestamp,
        character_count=0,
        attribution_completed_at=None,
        search_text=dialogue.search_text,
    )


def _pending_dialogue_refresh(
    dialogue: DialogueRecord,
    timestamp: str,
) -> DialogueRecord:
    return DialogueRecord(
        resource_name=dialogue.resource_name,
        resref=dialogue.resref,
        source_kind=dialogue.source_kind,
        source_path=dialogue.source_path,
        detail_status=DetailStatus.PENDING,
        detail_error=None,
        updated_at=timestamp,
        character_count=0,
        attribution_completed_at=None,
        search_text=dialogue.search_text,
    )


def _validated_dialogue_copy(
    dialogue: DialogueRecord,
    *,
    resource_name: str | None = None,
    updated_at: str | None = None,
    clear_attribution: bool,
) -> DialogueRecord:
    update: dict[str, object] = {}
    if resource_name is not None:
        update["resource_name"] = resource_name
    if updated_at is not None:
        update["updated_at"] = updated_at
    if clear_attribution:
        update |= {"character_count": 0, "attribution_completed_at": None}
    return DialogueRecord.model_validate(dialogue.model_dump() | update)


def _dialogue_line_record(
    dialogue: DialogueRecord,
    line: DialogueLine,
) -> DialogueLineRecord:
    return DialogueLineRecord(
        id=_line_id(
            line.dialogue_resource_name,
            line.line_kind,
            line.state_index,
            line.transition_index,
        ),
        dialogue_resource_name=dialogue.resource_name,
        dialogue_resref=dialogue.resref,
        source_kind=dialogue.source_kind,
        line_kind=line.line_kind,
        state_index=line.state_index,
        transition_index=line.transition_index,
        strref=line.strref,
        text=line.text,
        serialized_size=len(line.model_dump_json().encode("utf-8")),
        character_count=0,
        attribution_completed_at=None,
        search_text=_search_text(dialogue.resource_name, line.text),
    )


def _attributed_character(
    character: CharacterRecord,
    dialogues: dict[str, DialogueRecord],
    timestamp: str,
) -> CharacterRecord:
    dialogue: DialogueRecord | None = None
    if character.dialog_resref is not None:
        dialogue_name = f"{character.dialog_resref}.DLG".casefold()
        if dialogue_name in dialogues:
            dialogue = dialogues[dialogue_name]

    status: AttributionStatus
    if character.detail_status is not DetailStatus.COMPLETE:
        status = AttributionStatus.CHARACTER_UNAVAILABLE
    elif character.dialog_resref is None:
        status = AttributionStatus.NO_DIALOGUE
    elif dialogue is None:
        status = AttributionStatus.MISSING_DIALOGUE
    elif dialogue.detail_status is not DetailStatus.COMPLETE:
        status = AttributionStatus.DIALOGUE_FAILED
    else:
        status = AttributionStatus.MATCHED

    update = {
        "attribution_status": status,
        "dialogue_status": dialogue.detail_status if dialogue is not None else None,
        "dialogue_line_count": dialogue.dialogue_line_count if dialogue is not None else None,
        "npc_line_count": dialogue.npc_line_count if dialogue is not None else None,
        "player_line_count": dialogue.player_line_count if dialogue is not None else None,
        "journal_line_count": dialogue.journal_line_count if dialogue is not None else None,
        "dialogue_state_count": dialogue.state_count if dialogue is not None else None,
        "dialogue_transition_count": dialogue.transition_count if dialogue is not None else None,
        "dialogue_serialized_size": dialogue.serialized_size if dialogue is not None else None,
        "attribution_completed_at": timestamp,
    }
    return CharacterRecord.model_validate(character.model_dump() | update)


def _line_id(
    dialogue_resource_name: str,
    line_kind: DialogueLineKind,
    state_index: int,
    transition_index: int | None,
) -> str:
    transition = "-" if transition_index is None else str(transition_index)
    return f"{dialogue_resource_name}:{line_kind}:{state_index}:{transition}"


def _search_text(*values: str | None) -> str:
    return " ".join(value for value in values if value)


def _same_identity(
    record: CharacterRecord | DialogueRecord,
    resource: CreResource | DlgResource,
) -> bool:
    return (
        record.resource_name == resource.resource_name
        and record.resref == resource.resref
        and record.source_kind == resource.source_kind
        and record.source_path == resource.source_path
    )
