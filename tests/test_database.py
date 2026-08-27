"""Behavioral contracts for the typed LanceDB pipeline repository."""

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import lancedb
import pytest
from lancedb.expr import col, lit
from lancedb.index import FTS
from lancedb.pydantic import LanceModel
from pydantic import ValidationError

from bgvoice.database import (
    TABLE_INDEXES,
    CharacterRecord,
    DialogueLineRecord,
    DialogueRecord,
    ExtractionRunRecord,
    PipelineDatabase,
)
from bgvoice.models import (
    CharacterDetail,
    DetailStatus,
    DialogueExtraction,
    RunKind,
    RunStatus,
    SourceKind,
)
from tests.factories import make_dialogue_dump, make_dialogue_resource, make_dump, make_resource


def _rows[Record: LanceModel](
    path: Path,
    table_name: str,
    model: type[Record],
) -> list[Record]:
    database = lancedb.connect(path, read_consistency_interval=timedelta(0))
    return database.open_table(table_name).search().limit(None).to_pydantic(model)


def _character_rows(path: Path) -> list[CharacterRecord]:
    return _rows(path, "characters", CharacterRecord)


def _dialogue_rows(path: Path) -> list[DialogueRecord]:
    return _rows(path, "dialogues", DialogueRecord)


def _line_rows(path: Path) -> list[DialogueLineRecord]:
    return _rows(path, "dialogue_lines", DialogueLineRecord)


def test_database_creates_exact_typed_schemas_and_native_indexes(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    PipelineDatabase(path)
    database = lancedb.connect(path, read_consistency_interval=timedelta(0))
    tables = set(database.list_tables(limit=None).tables)
    assert tables == {"characters", "dialogues", "dialogue_lines", "extraction_runs"}

    models: dict[str, type[LanceModel]] = {
        "characters": CharacterRecord,
        "dialogues": DialogueRecord,
        "dialogue_lines": DialogueLineRecord,
        "extraction_runs": ExtractionRunRecord,
    }
    for name, model in models.items():
        table = database.open_table(name)
        assert table.schema.equals(model.to_arrow_schema(), check_metadata=True)
        indexes = {
            (index.name, index.index_type, tuple(index.columns)) for index in table.list_indices()
        }
        assert indexes == {
            (spec.name, type(spec.config).__name__, (spec.column,)) for spec in TABLE_INDEXES[name]
        }

    fts = FTS(
        base_tokenizer="simple",
        language="English",
        with_position=True,
        max_token_length=64,
        lower_case=True,
        stem=True,
        remove_stop_words=False,
        ascii_folding=True,
    )
    assert [
        spec.config
        for specs in TABLE_INDEXES.values()
        for spec in specs
        if spec.name.endswith("_fts")
    ] == [fts, fts, fts]


def test_existing_table_requires_the_exact_arrow_schema(tmp_path: Path) -> None:
    path = tmp_path / "wrong.lancedb"
    PipelineDatabase(path)

    class WrongCharacter(LanceModel):
        resource_name: str

    database = lancedb.connect(path)
    database.drop_table("characters")
    database.create_table("characters", schema=WrongCharacter)
    with pytest.raises(AssertionError, match="has schema"):
        PipelineDatabase(path)


def test_existing_table_requires_the_exact_indexes(tmp_path: Path) -> None:
    path = tmp_path / "missing-index.lancedb"
    PipelineDatabase(path)
    lancedb.connect(path).open_table("characters").drop_index("characters_search_fts")

    with pytest.raises(AssertionError, match="has indexes"):
        PipelineDatabase(path)


def test_non_pipeline_database_is_rejected_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "unrelated.lancedb"

    class UnrelatedRecord(LanceModel):
        value: str

    connection = lancedb.connect(path)
    connection.create_table("unrelated", schema=UnrelatedRecord)
    with pytest.raises(AssertionError, match="LanceDB tables are"):
        PipelineDatabase(path)
    assert connection.list_tables(limit=None).tables == ["unrelated"]


def test_existing_empty_directory_is_rejected_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "empty"
    path.mkdir()

    with pytest.raises(AssertionError, match="LanceDB tables are"):
        PipelineDatabase(path)

    assert list(path.iterdir()) == []


def test_unchanged_inventory_resumes_and_changed_identity_clears_details(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    dialogue = make_dialogue_resource()

    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    pending_character = _character_rows(path)[0]
    assert pending_character.source_kind is SourceKind.OVERRIDE
    assert pending_character.detail_status is DetailStatus.PENDING
    database.apply_detail_batch(
        [CharacterDetail.from_dump(character, make_dump(short_name="Winged Cleric"))], []
    )
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, [dialogue])
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())
    database.apply_dialogue_batch([extraction], [])
    line_ids = {line.id for line in _line_rows(path)}

    same_character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(same_character_run, [character])
    same_dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(same_dialogue_run, [dialogue])
    assert database.detail_targets(refresh=False) == set()
    assert database.dialogue_targets(refresh=False) == []
    assert {line.id for line in _line_rows(path)} == line_ids

    changed_character = character.model_copy(
        update={"source_path": "C:/game/override/replaced/AERIE.CRE"}
    )
    changed_dialogue = dialogue.model_copy(
        update={"source_path": "C:/game/override/replaced/AERIE.DLG"}
    )
    changed_character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(changed_character_run, [changed_character])
    changed_dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(changed_dialogue_run, [changed_dialogue])

    stored_character = _character_rows(path)[0]
    stored_dialogue = _dialogue_rows(path)[0]
    assert (stored_character.detail_status, stored_character.display_name) == ("pending", None)
    assert (stored_dialogue.detail_status, stored_dialogue.state_count) == ("pending", None)
    assert _line_rows(path) == []


def test_inventory_replacement_preserves_live_indexes(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    connection = lancedb.connect(path, read_consistency_interval=timedelta(0))
    table = connection.open_table("characters")
    original_indexes = {index.name: index.index_uuid for index in table.list_indices()}

    character = make_resource()
    run_id = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(run_id, [character])
    database.apply_detail_batch(
        [CharacterDetail.from_dump(character, make_dump(short_name="Fresh voice"))],
        [],
    )

    current_indexes = {index.name: index.index_uuid for index in table.list_indices()}
    assert current_indexes == original_indexes
    assert table.search("Fresh", query_type="fts").limit(1).to_arrow().num_rows == 1


def test_failed_refresh_clears_stale_fields_lines_and_search_text(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    dialogue = make_dialogue_resource()
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    database.apply_detail_batch(
        [CharacterDetail.from_dump(character, make_dump(short_name="Winged Cleric"))], []
    )
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, [dialogue])
    database.apply_dialogue_batch([DialogueExtraction.from_dump(make_dialogue_dump())], [])

    refresh_character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(refresh_character_run, [character])
    refresh_dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(refresh_dialogue_run, [dialogue])
    database.apply_detail_batch([], [(character.resource_name, "bad CRE refresh")])
    database.apply_dialogue_batch([], [(dialogue.resource_name, "bad DLG refresh")])
    database.finish_run(
        refresh_character_run,
        status=RunStatus.COMPLETE_WITH_ERRORS,
        attempted=1,
        extracted=0,
        failures=1,
    )
    database.finish_run(
        refresh_dialogue_run,
        status=RunStatus.COMPLETE_WITH_ERRORS,
        attempted=1,
        extracted=0,
        failures=1,
    )

    stored_character = _character_rows(path)[0]
    stored_dialogue = _dialogue_rows(path)[0]
    assert stored_character.display_name is None
    assert stored_character.serialized_size is None
    assert stored_character.detail_error == "bad CRE refresh"
    assert "Winged" not in stored_character.search_text
    assert stored_dialogue.state_count is None
    assert stored_dialogue.serialized_size is None
    assert stored_dialogue.detail_error == "bad DLG refresh"
    assert _line_rows(path) == []


def test_invalid_batches_are_rejected_before_mutation(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    dialogue = make_dialogue_resource()
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, [dialogue])
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())
    database.apply_dialogue_batch([extraction], [])
    before_characters = _character_rows(path)
    before_dialogues = _dialogue_rows(path)
    before_lines = _line_rows(path)

    detail = CharacterDetail.from_dump(character, make_dump())
    with pytest.raises(AssertionError, match="duplicate keys"):
        database.apply_detail_batch([detail, detail], [])
    with pytest.raises(AssertionError, match="both success and failure"):
        database.apply_detail_batch([detail], [(character.resource_name, "bad")])
    with pytest.raises(AssertionError, match="outside the inventory"):
        unknown = make_resource("OTHER.CRE")
        database.apply_detail_batch(
            [CharacterDetail.from_dump(unknown, make_dump("OTHER.CRE"))], []
        )

    mismatched = extraction.model_copy(
        update={"detail": extraction.detail.model_copy(update={"resref": "OTHER"})}
    )
    with pytest.raises(AssertionError, match="inventory has"):
        database.apply_dialogue_batch([mismatched], [])
    duplicate_lines = DialogueExtraction(
        detail=extraction.detail,
        lines=[
            extraction.lines[0],
            extraction.lines[0],
            extraction.lines[1],
            extraction.lines[3],
            extraction.lines[4],
        ],
    )
    with pytest.raises(AssertionError, match="duplicate keys"):
        database.apply_dialogue_batch([duplicate_lines], [])
    invalid_coordinate = DialogueExtraction(
        detail=extraction.detail,
        lines=[
            extraction.lines[0].model_copy(update={"transition_index": 0}),
            *extraction.lines[1:],
        ],
    )
    with pytest.raises(ValidationError, match="NPC lines must omit"):
        database.apply_dialogue_batch([invalid_coordinate], [])

    assert _character_rows(path) == before_characters
    assert _dialogue_rows(path) == before_dialogues
    assert _line_rows(path) == before_lines


def test_line_ids_are_stable_and_replacement_does_not_duplicate_rows(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, [make_dialogue_resource()])
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())
    database.apply_dialogue_batch([extraction], [])
    first_ids = [line.id for line in _line_rows(path)]
    database.apply_dialogue_batch([extraction], [])
    second_ids = [line.id for line in _line_rows(path)]

    assert sorted(first_ids) == sorted(second_ids)
    assert len(second_ids) == len(set(second_ids)) == len(extraction.lines)
    assert "AERIE.DLG:npc:0:-" in second_ids
    assert "AERIE.DLG:player:1:2" in second_ids


def test_interrupted_line_upsert_keeps_old_lines_and_marks_dialogue_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    dialogue = make_dialogue_resource()
    run_id = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(run_id, [dialogue])
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())
    database.apply_dialogue_batch([extraction], [])
    old_lines = _line_rows(path)

    def fail_line_upsert(
        table_name: str,
        key: str,
        records: Sequence[LanceModel],
    ) -> None:
        assert (table_name, key, len(records)) == ("dialogue_lines", "id", 5)
        raise OSError("simulated Lance write failure")

    monkeypatch.setattr(database, "_upsert", fail_line_upsert)
    with pytest.raises(OSError, match="simulated Lance write failure"):
        database.apply_dialogue_batch([extraction], [])

    assert _line_rows(path) == old_lines
    assert _dialogue_rows(path)[0].detail_status == "pending"
    assert database.dialogue_targets(refresh=False) == ["AERIE.DLG"]


def test_attribution_reconciles_every_character_dialogue_and_line(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    resources = [
        make_resource("AERIE.CRE"),
        make_resource("CLONE.CRE"),
        make_resource("NODLG.CRE"),
        make_resource("MISSING.CRE"),
        make_resource("PENDING.CRE"),
        make_resource("FAILDLG.CRE"),
    ]
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, resources)
    details = [
        CharacterDetail.from_dump(resources[0], make_dump("AERIE.CRE", dialog="AERIE")),
        CharacterDetail.from_dump(resources[1], make_dump("CLONE.CRE", dialog="AERIE")),
        CharacterDetail.from_dump(resources[2], make_dump("NODLG.CRE", dialog=None)),
        CharacterDetail.from_dump(resources[3], make_dump("MISSING.CRE", dialog="GHOST")),
        CharacterDetail.from_dump(resources[5], make_dump("FAILDLG.CRE", dialog="FAIL")),
    ]
    database.apply_detail_batch(details, [])

    dialogues = [
        make_dialogue_resource("AERIE.DLG"),
        make_dialogue_resource("FAIL.DLG"),
        make_dialogue_resource("UNUSED.DLG"),
    ]
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, dialogues)
    database.apply_dialogue_batch(
        [
            DialogueExtraction.from_dump(make_dialogue_dump("AERIE.DLG")),
            DialogueExtraction.from_dump(make_dialogue_dump("UNUSED.DLG")),
        ],
        [("FAIL.DLG", "broken DLG")],
    )

    summary = database.rebuild_attributions()
    assert summary.model_dump() == {
        "characters_total": 6,
        "characters_unavailable": 1,
        "characters_matched": 2,
        "characters_missing_dialogue": 1,
        "characters_dialogue_failed": 1,
        "characters_without_dialogue": 1,
        "dialogues_total": 3,
        "dialogues_attributed": 2,
        "dialogues_unattributed": 1,
        "attributed_dialogue_lines": 4,
        "unattributed_dialogue_lines": 4,
    }
    characters = {row.resource_name: row for row in _character_rows(path)}
    stored_dialogues = {row.resource_name: row for row in _dialogue_rows(path)}
    assert characters["FAILDLG.CRE"].attribution_status == "dialogue_failed"
    assert stored_dialogues["AERIE.DLG"].character_count == 2
    assert stored_dialogues["FAIL.DLG"].character_count == 1
    assert stored_dialogues["UNUSED.DLG"].character_count == 0
    assert {
        line.character_count
        for line in _line_rows(path)
        if line.dialogue_resource_name == "AERIE.DLG"
    } == {2}
    connection = lancedb.connect(path)
    for table_name in ("characters", "dialogues", "dialogue_lines"):
        table = connection.open_table(table_name)
        for index in TABLE_INDEXES[table_name]:
            stats = table.index_stats(index.name)
            assert stats is not None
            assert stats.num_unindexed_rows == 0

    next_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(next_run, resources)
    assert all(row.attribution_status is None for row in _character_rows(path))
    assert all(
        row.character_count == 0 and row.attribution_completed_at is None
        for row in _dialogue_rows(path)
    )
    assert all(
        row.character_count == 0 and row.attribution_completed_at is None
        for row in _line_rows(path)
    )


def test_attribution_rejects_incomplete_stored_line_sets(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    database.apply_detail_batch(
        [CharacterDetail.from_dump(character, make_dump(dialog="AERIE"))],
        [],
    )
    run_id = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(run_id, [make_dialogue_resource()])
    database.apply_dialogue_batch(
        [DialogueExtraction.from_dump(make_dialogue_dump())],
        [],
    )
    database.rebuild_attributions()
    published_at = _character_rows(path)[0].attribution_completed_at
    assert published_at is not None
    lines = lancedb.connect(path).open_table("dialogue_lines")
    lines.delete(col("id") == lit("AERIE.DLG:npc:0:-"))

    with pytest.raises(AssertionError, match="stores line counts"):
        database.rebuild_attributions()
    assert _character_rows(path)[0].attribution_completed_at == published_at


def test_interrupted_attribution_is_not_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    database.apply_detail_batch(
        [CharacterDetail.from_dump(character, make_dump())],
        [],
    )
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, [make_dialogue_resource()])
    database.apply_dialogue_batch(
        [DialogueExtraction.from_dump(make_dialogue_dump())],
        [],
    )
    database.rebuild_attributions()

    original_merge = database._merge

    def fail_line_publication(
        table_name: str,
        key: str,
        records: Sequence[LanceModel],
    ) -> None:
        if table_name == "dialogue_lines":
            raise OSError("simulated attribution write failure")
        original_merge(table_name, key, records)

    monkeypatch.setattr(database, "_merge", fail_line_publication)
    with pytest.raises(OSError, match="simulated attribution write failure"):
        database.rebuild_attributions()

    assert _character_rows(path)[0].attribution_completed_at is None


def test_stats_runs_and_full_text_indexes_follow_completed_batches(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    resources = [make_resource(), make_resource("MINSC.CRE"), make_resource("JAHEIRA.CRE")]
    run_id = database.start_run(tmp_path, "iecli test")
    assert len(run_id) == 32
    database.replace_inventory(run_id, resources)
    database.apply_detail_batch(
        [
            CharacterDetail.from_dump(
                resources[0], make_dump(short_name="The Winged Cleric", dialog="AERIE")
            )
        ],
        [("MINSC.CRE", "bad CRE")],
    )
    assert database.stats().model_dump() == {
        "total": 3,
        "complete": 1,
        "failed": 1,
        "pending": 1,
        "with_dialog": 1,
    }
    database.finish_run(
        run_id,
        status=RunStatus.COMPLETE_WITH_ERRORS,
        attempted=2,
        extracted=1,
        failures=1,
        error="partial",
    )
    stored_run = _rows(path, "extraction_runs", ExtractionRunRecord)[0]
    assert stored_run.id == run_id
    assert stored_run.status == "complete_with_errors"
    assert stored_run.resources_discovered == 3
    assert stored_run.error == "partial"

    table = lancedb.connect(path).open_table("characters")
    assert table.search("Winged", query_type="fts").limit(10).to_arrow().num_rows == 1
    assert table.search("clerics", query_type="fts").limit(10).to_arrow().num_rows == 1
    assert table.search("the", query_type="fts").limit(10).to_arrow().num_rows == 1
    assert table.search("MINSC", query_type="fts").limit(10).to_arrow().num_rows == 1
    for index in TABLE_INDEXES["characters"]:
        stats = table.index_stats(index.name)
        assert stats is not None
        assert stats.num_unindexed_rows == 0


def test_run_and_inventory_invariants_fail_without_changes(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    character_run = database.start_run(tmp_path, "iecli test")
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)

    with pytest.raises(AssertionError, match="Unknown extraction run"):
        database.replace_inventory("missing", [])
    with pytest.raises(AssertionError, match="expected characters"):
        database.replace_inventory(dialogue_run, [])
    with pytest.raises(AssertionError, match="expected dialogues"):
        database.replace_dialogue_inventory(character_run, [])
    duplicate = make_resource()
    with pytest.raises(AssertionError, match="duplicate keys"):
        database.replace_inventory(character_run, [duplicate, duplicate])
    assert _character_rows(path) == []

    database.finish_run(
        character_run,
        status=RunStatus.COMPLETE,
        attempted=0,
        extracted=0,
        failures=0,
    )
    with pytest.raises(AssertionError, match="already complete"):
        database.replace_inventory(character_run, [])


def test_index_failure_leaves_run_open_for_failed_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    run_id = database.start_run(tmp_path, "iecli test")

    def fail_optimization(_name: str, _table: object) -> None:
        raise OSError("simulated index failure")

    monkeypatch.setattr(database, "_optimize", fail_optimization)
    with pytest.raises(OSError, match="simulated index failure"):
        database.finish_run(
            run_id,
            status=RunStatus.COMPLETE,
            attempted=0,
            extracted=0,
            failures=0,
        )
    assert _rows(path, "extraction_runs", ExtractionRunRecord)[0].status is RunStatus.RUNNING

    database.finish_run(
        run_id,
        status=RunStatus.FAILED,
        attempted=0,
        extracted=0,
        failures=0,
        error="simulated index failure",
    )
    stored = _rows(path, "extraction_runs", ExtractionRunRecord)[0]
    assert stored.status is RunStatus.FAILED
    assert stored.error == "simulated index failure"


def test_storage_models_enforce_non_relational_invariants() -> None:
    with pytest.raises(ValidationError, match="Input should be"):
        DialogueRecord(
            resource_name="A.DLG",
            resref="A",
            source_kind="archive",
            source_path="A.DLG",
            detail_status=DetailStatus.PENDING,
            updated_at="now",
            character_count=0,
            search_text="A",
        )
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        DialogueRecord(
            resource_name="A.DLG",
            resref="A",
            source_kind="override",
            source_path="A.DLG",
            detail_status="pending",
            updated_at="now",
            character_count=-1,
            search_text="A",
        )
    with pytest.raises(ValidationError, match="dialogue line id must be"):
        DialogueLineRecord(
            id="wrong",
            dialogue_resource_name="A.DLG",
            dialogue_resref="A",
            source_kind="override",
            line_kind="npc",
            state_index=0,
            transition_index=None,
            strref=1,
            text="Hello",
            serialized_size=1,
            character_count=0,
            search_text="A Hello",
        )
