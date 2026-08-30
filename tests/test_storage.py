"""Atomic LanceDB repository lifecycle and retry behavior."""

from collections.abc import Sequence
from pathlib import Path

import lancedb
import pytest
from lancedb.pydantic import LanceModel

from bgvoice.character_models import CharacterExtraction
from bgvoice.database import PipelineDatabase
from bgvoice.dialogue_models import DialogueExtraction
from bgvoice.metadata_models import IdentifierDefinition
from bgvoice.model_types import (
    DetailStatus,
    IdentifierKind,
    PortraitImage,
    ResourceSource,
    RunKind,
    RunStatus,
    SourceKind,
)
from bgvoice.readable_models import ReadableItem
from bgvoice.storage_records import (
    CharacterRecord,
    CharacterSoundRecord,
    DialogueLineRecord,
    DialogueRecord,
    DialogueTransitionRecord,
    ExtractionRunRecord,
)
from tests.factories import (
    make_dialogue_dump,
    make_dialogue_resource,
    make_dump,
    make_item_dump,
    make_item_resource,
    make_resource,
)
from tests.scenarios import empty_metadata, finish_run, make_metadata, rows


def _characters(path: Path) -> list[CharacterRecord]:
    return rows(path, "characters", CharacterRecord)


def _dialogues(path: Path) -> list[DialogueRecord]:
    return rows(path, "dialogues", DialogueRecord)


def _sounds(path: Path) -> list[CharacterSoundRecord]:
    return rows(path, "character_sounds", CharacterSoundRecord)


def _lines(path: Path) -> list[DialogueLineRecord]:
    return rows(path, "dialogue_lines", DialogueLineRecord)


def _edges(path: Path) -> list[DialogueTransitionRecord]:
    return rows(path, "dialogue_transitions", DialogueTransitionRecord)


def test_unrelated_lancedb_is_rejected_without_mutation(tmp_path: Path) -> None:
    class UnrelatedRecord(LanceModel):
        value: str

    path = tmp_path / "unrelated.lancedb"
    connection = lancedb.connect(path)
    connection.create_table("unrelated", data=[UnrelatedRecord(value="keep me")])

    with pytest.raises(AssertionError, match="LanceDB tables are"):
        PipelineDatabase(path)

    assert connection.list_tables(limit=None).tables == ["unrelated"]
    assert connection.open_table("unrelated").to_arrow().to_pylist() == [{"value": "keep me"}]


def test_metadata_replacement_is_a_complete_generation(tmp_path: Path) -> None:
    path = tmp_path / "metadata.lancedb"
    database = PipelineDatabase(path)
    metadata = make_metadata()
    run_id = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)

    database.replace_metadata(run_id, metadata)
    finish_run(database, run_id, attempted=metadata.source_resource_count)

    assert len(database.identifier_definitions()) == len(metadata.identifiers)
    assert {row.campaign_id for row in database.campaigns()} == {"SOA", "BG1"}
    assert {row.name for row in database.race_text_rows()} == {"Elf", "Gnome"}
    assert {row.mixed_name for row in database.class_text_rows()} == {"Mage", "Cleric / Mage"}
    assert [row.row_name for row in database.kits()] == ["BERSERKER"]

    empty_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)
    database.replace_metadata(empty_run, empty_metadata())

    assert database.identifier_definitions() == []
    assert database.campaigns() == []
    assert database.race_text_rows() == []
    assert database.class_text_rows() == []
    assert database.kits() == []


def test_metadata_duplicate_keys_fail_before_publication(tmp_path: Path) -> None:
    database = PipelineDatabase(tmp_path / "metadata.lancedb")
    metadata = make_metadata()
    duplicate = metadata.identifiers[0].model_copy(update={"ordinal": 999})
    invalid = metadata.model_copy(update={"identifiers": [*metadata.identifiers, duplicate]})
    run_id = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)

    with pytest.raises(AssertionError, match="duplicate keys"):
        database.replace_metadata(run_id, invalid)

    assert database.identifier_definitions() == []


def test_unchanged_inventory_resumes_but_changed_sources_reset_aggregate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    dialogue = make_dialogue_resource()

    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    database.apply_detail_batch(
        character_run,
        [CharacterExtraction.from_dump(character, make_dump())],
        [],
    )
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, [dialogue])
    database.apply_dialogue_batch(
        dialogue_run,
        [DialogueExtraction.from_dump(make_dialogue_dump())],
        [],
    )
    child_ids = ({row.id for row in _sounds(path)}, {row.id for row in _lines(path)})

    next_character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(next_character_run, [character])
    next_dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(next_dialogue_run, [dialogue])

    assert database.detail_targets(refresh=False) == set()
    assert database.dialogue_targets(refresh=False) == []
    assert ({row.id for row in _sounds(path)}, {row.id for row in _lines(path)}) == child_ids

    changed_character = character.model_copy(update={"source_path": "C:/changed/AERIE.CRE"})
    changed_dialogue = dialogue.model_copy(update={"source_path": "C:/changed/AERIE.DLG"})
    changed_character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(changed_character_run, [changed_character])
    changed_dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(changed_dialogue_run, [changed_dialogue])

    assert (_characters(path)[0].extraction.status, _characters(path)[0].detail) == (
        DetailStatus.PENDING,
        None,
    )
    assert (_dialogues(path)[0].extraction.status, _dialogues(path)[0].detail) == (
        DetailStatus.PENDING,
        None,
    )
    assert _sounds(path) == []
    assert _lines(path) == []
    assert _edges(path) == []


def test_successful_batches_replace_children_idempotently_and_refresh_fts(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    detail = CharacterExtraction.from_dump(character, make_dump(short_name="Winged Cleric"))
    database.apply_detail_batch(character_run, [detail], [])
    database.apply_detail_batch(
        character_run,
        [detail.model_copy(update={"sounds": detail.sounds[:1]})],
        [],
    )

    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, [make_dialogue_resource()])
    dialogue = DialogueExtraction.from_dump(make_dialogue_dump())
    database.apply_dialogue_batch(dialogue_run, [dialogue], [])
    database.apply_dialogue_batch(dialogue_run, [dialogue], [])

    assert [row.id for row in _sounds(path)] == ["AERIE.CRE:9"]
    assert len({row.id for row in _lines(path)}) == len(dialogue.lines) == 5
    assert len({row.id for row in _edges(path)}) == len(dialogue.edges) == 3
    assert next(row for row in _lines(path) if row.line_kind == "npc").state_trigger_index == 0
    scripted = next(row for row in _edges(path) if row.id == "AERIE.DLG:1:2")
    assert (scripted.trigger_index, scripted.action_index, scripted.next_dialog) == (3, 4, "MINSC")

    connection = lancedb.connect(path)
    assert (
        connection.open_table("characters").search("Winged", query_type="fts").to_arrow().num_rows
        == 1
    )
    assert (
        connection.open_table("dialogue_lines")
        .search("Quest", query_type="fts")
        .to_arrow()
        .num_rows
        == 2
    )


def test_failed_refresh_clears_stale_derived_data_and_remains_retryable(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    dialogue = make_dialogue_resource()
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    database.apply_detail_batch(
        character_run,
        [CharacterExtraction.from_dump(character, make_dump(short_name="Winged Cleric"))],
        [],
    )
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, [dialogue])
    database.apply_dialogue_batch(
        dialogue_run,
        [DialogueExtraction.from_dump(make_dialogue_dump())],
        [],
    )

    refresh_characters = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(refresh_characters, [character])
    database.apply_detail_batch(refresh_characters, [], [("AERIE.CRE", "bad CRE refresh")])
    refresh_dialogues = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(refresh_dialogues, [dialogue])
    database.apply_dialogue_batch(refresh_dialogues, [], [("AERIE.DLG", "bad DLG refresh")])

    stored_character = _characters(path)[0]
    stored_dialogue = _dialogues(path)[0]
    assert (stored_character.detail, stored_character.extraction.error) == (
        None,
        "bad CRE refresh",
    )
    assert "Winged" not in stored_character.search_text
    assert (stored_dialogue.detail, stored_dialogue.extraction.error) == (
        None,
        "bad DLG refresh",
    )
    assert database.detail_targets(refresh=False) == {"AERIE.CRE"}
    assert database.dialogue_targets(refresh=False) == ["AERIE.DLG"]
    assert _sounds(path) == []
    assert _lines(path) == []
    assert _edges(path) == []


def _fail_child_writes(
    database: PipelineDatabase,
    monkeypatch: pytest.MonkeyPatch,
    child_table: str,
) -> None:
    original_upsert = database._upsert

    def fail_selected(table_name: str, key: str, records: Sequence[LanceModel]) -> None:
        if table_name == child_table:
            raise OSError("simulated child write failure")
        original_upsert(table_name, key, records)

    monkeypatch.setattr(database, "_upsert", fail_selected)


def test_interrupted_sound_write_keeps_previous_slots_and_marks_character_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    resource = make_resource()
    run_id = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(run_id, [resource])
    extraction = CharacterExtraction.from_dump(resource, make_dump())
    database.apply_detail_batch(run_id, [extraction], [])
    old_sounds = _sounds(path)

    _fail_child_writes(database, monkeypatch, "character_sounds")
    with pytest.raises(OSError, match="simulated child write failure"):
        database.apply_detail_batch(run_id, [extraction], [])

    assert _sounds(path) == old_sounds
    assert _characters(path)[0].extraction.status is DetailStatus.PENDING


@pytest.mark.parametrize("child_table", ["dialogue_lines", "dialogue_transitions"])
def test_interrupted_graph_write_keeps_previous_children_and_marks_dialogue_retryable(
    child_table: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    resource = make_dialogue_resource()
    run_id = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(run_id, [resource])
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())
    database.apply_dialogue_batch(run_id, [extraction], [])
    old_children = _lines(path) if child_table == "dialogue_lines" else _edges(path)

    _fail_child_writes(database, monkeypatch, child_table)
    with pytest.raises(OSError, match="simulated child write failure"):
        database.apply_dialogue_batch(run_id, [extraction], [])

    current = _lines(path) if child_table == "dialogue_lines" else _edges(path)
    assert current == old_children
    assert _dialogues(path)[0].extraction.status is DetailStatus.PENDING


def test_invalid_batch_is_rejected_before_any_aggregate_mutation(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    resource = make_resource()
    run_id = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(run_id, [resource])
    detail = CharacterExtraction.from_dump(resource, make_dump())
    before = _characters(path)

    with pytest.raises(AssertionError, match="duplicate keys"):
        database.apply_detail_batch(run_id, [detail, detail], [])
    with pytest.raises(AssertionError, match="both success and failure"):
        database.apply_detail_batch(run_id, [detail], [("AERIE.CRE", "bad")])
    with pytest.raises(AssertionError, match="outside the inventory"):
        unknown = make_resource("OTHER.CRE")
        database.apply_detail_batch(
            run_id,
            [CharacterExtraction.from_dump(unknown, make_dump("OTHER.CRE"))],
            [],
        )

    assert _characters(path) == before
    assert _sounds(path) == []


def test_portraits_follow_character_references_and_replace_as_one_set(tmp_path: Path) -> None:
    database = PipelineDatabase(tmp_path / "portraits.lancedb")
    character = make_resource()
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    database.apply_detail_batch(
        character_run,
        [CharacterExtraction.from_dump(character, make_dump())],
        [],
    )
    assert database.referenced_portrait_resrefs() == {"AERIES"}

    run_id = database.start_run(tmp_path, "iecli test", run_kind=RunKind.PORTRAITS)
    database.replace_portraits(
        run_id,
        [
            PortraitImage(
                resref="AERIES",
                source=ResourceSource(kind=SourceKind.OVERRIDE, path="AERIES.BMP"),
                width=54,
                height=84,
                png=b"\x89PNG\r\n\x1a\n",
            )
        ],
    )
    finish_run(database, run_id, attempted=1)

    assert [(row.resref, row.width, row.height) for row in database.portraits()] == [
        ("AERIES", 54, 84)
    ]


def test_readable_items_replace_the_complete_published_set(tmp_path: Path) -> None:
    database = PipelineDatabase(tmp_path / "readables.lancedb")
    book = ReadableItem.from_dump(make_item_resource(), make_item_dump())
    scroll = ReadableItem.from_dump(
        make_item_resource("SCROLL.ITM"),
        make_item_dump("SCROLL.ITM", category=11, ground_icon="GSCRL01"),
    )
    assert book is not None and scroll is not None

    first_run = database.start_run(
        tmp_path,
        "iecli test",
        run_kind=RunKind.READABLE_ITEMS,
    )
    database.replace_readable_items(first_run, [book, scroll])
    finish_run(database, first_run, attempted=2)
    assert [item.resource_name for item in database.readable_items()] == [
        "BOOK.ITM",
        "SCROLL.ITM",
    ]

    second_run = database.start_run(
        tmp_path,
        "iecli test",
        run_kind=RunKind.READABLE_ITEMS,
    )
    database.replace_readable_items(second_run, [scroll])
    assert [
        (item.resource_name, item.display_title, item.text_length)
        for item in database.readable_items()
    ] == [("SCROLL.ITM", "A Fine Book", len("Identified text"))]


def test_run_lifecycle_records_progress_and_stats(tmp_path: Path) -> None:
    path = tmp_path / "runs.lancedb"
    database = PipelineDatabase(path)
    resources = [make_resource(), make_resource("MINSC.CRE"), make_resource("JAHEIRA.CRE")]
    run_id = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(run_id, resources)
    database.apply_detail_batch(
        run_id,
        [CharacterExtraction.from_dump(resources[0], make_dump())],
        [("MINSC.CRE", "bad CRE")],
    )
    database.finish_run(
        run_id,
        status=RunStatus.COMPLETE_WITH_ERRORS,
        attempted=2,
        extracted=1,
        failures=1,
        error="partial",
    )

    assert database.stats().model_dump() == {
        "total": 3,
        "complete": 1,
        "failed": 1,
        "pending": 1,
        "with_dialog": 1,
    }
    run = rows(path, "extraction_runs", ExtractionRunRecord)[0]
    assert (
        run.id,
        run.status,
        run.resources_discovered,
        run.details_attempted,
        run.details_extracted,
        run.failures,
        run.error,
    ) == (run_id, RunStatus.COMPLETE_WITH_ERRORS, 3, 2, 1, 1, "partial")


def test_identifier_metadata_accepts_aliases_with_one_stable_key(tmp_path: Path) -> None:
    database = PipelineDatabase(tmp_path / "aliases.lancedb")
    metadata = empty_metadata().model_copy(
        update={
            "identifiers": [
                IdentifierDefinition(
                    kind=IdentifierKind.CLASS,
                    value=1,
                    source_resource="CLASS.IDS",
                    ordinal=0,
                    symbols=["MAGE", "MAGE_ALL"],
                )
            ]
        }
    )
    run_id = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)
    database.replace_metadata(run_id, metadata)
    assert database.identifier_definitions()[0].symbols == ["MAGE", "MAGE_ALL"]
