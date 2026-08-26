"""Behavioral contracts for the SQLModel pipeline repository."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine, select

from bgvoice.database import (
    AttributionRun,
    Character,
    CharacterAttribution,
    CharacterDatabase,
    Dialogue,
    DialogueLineRecord,
)
from bgvoice.models import CharacterDetail, DialogueExtraction
from tests.factories import make_dialogue_dump, make_dialogue_resource, make_dump, make_resource


def _reader(path: Path) -> Engine:
    return create_engine(URL.create("sqlite+pysqlite", database=str(path)))


def _match_count(reader: Engine, table: str, query: str) -> int:
    with reader.connect() as connection:
        return int(
            connection.exec_driver_sql(
                f"SELECT COUNT(*) FROM {table} WHERE {table} MATCH ?",
                (query,),
            ).scalar_one()
        )


def test_committed_batches_are_searchable_before_run_finalization(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.sqlite3"
    character = make_resource().model_copy(update={"resref": "VOICE"})
    dialogue = make_dialogue_resource()

    with CharacterDatabase(path) as database:
        character_run = database.start_run(tmp_path, "iecli test")
        database.replace_inventory(character_run, [character])

        reader = _reader(path)
        try:
            assert _match_count(reader, "characters_fts", "AERIE") == 1
            assert _match_count(reader, "characters_fts", "VOICE") == 1

            database.apply_detail_batch(
                [
                    CharacterDetail.from_dump(
                        character,
                        make_dump(short_name="Winged Cleric", long_name="Winged Cleric"),
                    )
                ],
                [],
            )
            assert _match_count(reader, "characters_fts", "Winged") == 1

            dialogue_run = database.start_run(tmp_path, "iecli test", run_kind="dialogues")
            database.replace_dialogue_inventory(dialogue_run, [dialogue])
            assert _match_count(reader, "dialogues_fts", "AERIE") == 1

            database.apply_dialogue_batch(
                [DialogueExtraction.from_dump(make_dialogue_dump())],
                [],
            )
            assert _match_count(reader, "dialogue_lines_fts", "Quest") == 2
            assert database.integrity_check() == "ok"
        finally:
            reader.dispose()


def test_dialogue_detail_resref_must_match_inventory_without_staling_fts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pipeline.sqlite3"
    dialogue = make_dialogue_resource().model_copy(update={"resref": "SPEECH"})
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())

    with CharacterDatabase(path) as database:
        run_id = database.start_run(tmp_path, "iecli test", run_kind="dialogues")
        database.replace_dialogue_inventory(run_id, [dialogue])

        with pytest.raises(AssertionError, match="has resref 'AERIE'; inventory has 'SPEECH'"):
            database.apply_dialogue_batch([extraction], [])

        reader = _reader(path)
        try:
            with Session(reader) as session:
                stored = session.get(Dialogue, dialogue.resource_name)
                assert stored is not None
                assert (stored.resref, stored.detail_status) == ("SPEECH", "pending")
                assert session.exec(select(DialogueLineRecord)).all() == []
            assert _match_count(reader, "dialogues_fts", "SPEECH") == 1
        finally:
            reader.dispose()


def test_integrity_check_reports_fts_row_count_drift(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.sqlite3"
    with CharacterDatabase(path) as database:
        run_id = database.start_run(tmp_path, "iecli test")
        database.replace_inventory(run_id, [make_resource()])

        reader = _reader(path)
        try:
            with reader.begin() as connection:
                connection.exec_driver_sql("DELETE FROM characters_fts")
            assert database.integrity_check() == "characters_fts has 0 rows; expected 1"
        finally:
            reader.dispose()


def test_failed_refresh_clears_stale_details_lines_and_search(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.sqlite3"
    character = make_resource()
    dialogue = make_dialogue_resource()

    with CharacterDatabase(path) as database:
        character_run = database.start_run(tmp_path, "iecli test")
        database.replace_inventory(character_run, [character])
        database.apply_detail_batch(
            [
                CharacterDetail.from_dump(
                    character,
                    make_dump(short_name="Winged Cleric", long_name="Winged Cleric"),
                )
            ],
            [],
        )
        dialogue_run = database.start_run(tmp_path, "iecli test", run_kind="dialogues")
        database.replace_dialogue_inventory(dialogue_run, [dialogue])
        database.apply_dialogue_batch(
            [DialogueExtraction.from_dump(make_dialogue_dump())],
            [],
        )

        next_character_run = database.start_run(tmp_path, "iecli test")
        database.replace_inventory(next_character_run, [character])
        next_dialogue_run = database.start_run(tmp_path, "iecli test", run_kind="dialogues")
        database.replace_dialogue_inventory(next_dialogue_run, [dialogue])
        database.apply_detail_batch([], [(character.resource_name, "bad CRE refresh")])
        database.apply_dialogue_batch([], [(dialogue.resource_name, "bad DLG refresh")])

        reader = _reader(path)
        try:
            with Session(reader) as session:
                stored_character = session.get(Character, character.resource_name)
                stored_dialogue = session.get(Dialogue, dialogue.resource_name)
                assert stored_character is not None
                assert stored_character.detail_json is None
                assert stored_character.display_name is None
                assert stored_character.serialized_size is None
                assert stored_dialogue is not None
                assert stored_dialogue.detail_json is None
                assert stored_dialogue.state_count is None
                assert stored_dialogue.serialized_size is None
                assert session.exec(select(DialogueLineRecord)).all() == []

            assert _match_count(reader, "characters_fts", "Winged") == 0
            assert _match_count(reader, "characters_fts", "AERIE") == 1
            assert _match_count(reader, "dialogue_lines_fts", "Quest") == 0
        finally:
            reader.dispose()
        assert database.integrity_check() == "ok"


def test_changed_source_identity_clears_stale_details_and_lines(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.sqlite3"
    character = make_resource()
    dialogue = make_dialogue_resource()

    with CharacterDatabase(path) as database:
        character_run = database.start_run(tmp_path, "iecli test")
        database.replace_inventory(character_run, [character])
        database.apply_detail_batch(
            [CharacterDetail.from_dump(character, make_dump(short_name="Winged Cleric"))], []
        )
        dialogue_run = database.start_run(tmp_path, "iecli test", run_kind="dialogues")
        database.replace_dialogue_inventory(dialogue_run, [dialogue])
        database.apply_dialogue_batch(
            [DialogueExtraction.from_dump(make_dialogue_dump())],
            [],
        )

        changed_character = character.model_copy(
            update={"source_path": "C:/game/override/replaced/AERIE.CRE"}
        )
        changed_dialogue = dialogue.model_copy(
            update={"source_path": "C:/game/override/replaced/AERIE.DLG"}
        )
        next_character_run = database.start_run(tmp_path, "iecli test")
        database.replace_inventory(next_character_run, [changed_character])
        next_dialogue_run = database.start_run(tmp_path, "iecli test", run_kind="dialogues")
        database.replace_dialogue_inventory(next_dialogue_run, [changed_dialogue])

        reader = _reader(path)
        try:
            with Session(reader) as session:
                stored_character = session.get(Character, character.resource_name)
                stored_dialogue = session.get(Dialogue, dialogue.resource_name)
                assert stored_character is not None
                assert (stored_character.detail_status, stored_character.detail_json) == (
                    "pending",
                    None,
                )
                assert stored_character.display_name is None
                assert stored_dialogue is not None
                assert (stored_dialogue.detail_status, stored_dialogue.detail_json) == (
                    "pending",
                    None,
                )
                assert stored_dialogue.state_count is None
                assert session.exec(select(DialogueLineRecord)).all() == []

            assert _match_count(reader, "characters_fts", "Winged") == 0
            assert _match_count(reader, "dialogue_lines_fts", "Quest") == 0
            assert _match_count(reader, "dialogues_fts", "replaced") == 1
        finally:
            reader.dispose()


def test_attribution_counts_incomplete_characters_and_inventory_invalidates_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pipeline.sqlite3"
    aerie = make_resource()
    minsc = make_resource("MINSC.CRE")

    with CharacterDatabase(path) as database:
        character_run = database.start_run(tmp_path, "iecli test")
        database.replace_inventory(character_run, [aerie, minsc])
        database.apply_detail_batch(
            [CharacterDetail.from_dump(aerie, make_dump())],
            [],
        )
        dialogue_run = database.start_run(tmp_path, "iecli test", run_kind="dialogues")
        database.replace_dialogue_inventory(dialogue_run, [make_dialogue_resource()])
        database.apply_dialogue_batch(
            [DialogueExtraction.from_dump(make_dialogue_dump())],
            [],
        )

        attribution = database.rebuild_attributions()
        assert attribution.characters_total == 2
        assert attribution.characters_matched == 1
        assert attribution.characters_unavailable == 1

        reader = _reader(path)
        try:
            with Session(reader) as session:
                assert len(session.exec(select(CharacterAttribution)).all()) == 2
                assert len(session.exec(select(AttributionRun)).all()) == 1

            next_run = database.start_run(tmp_path, "iecli test")
            database.replace_inventory(next_run, [aerie, minsc])
            with Session(reader) as session:
                assert session.exec(select(CharacterAttribution)).all() == []
                assert session.exec(select(AttributionRun)).all() == []
        finally:
            reader.dispose()


def test_dialogue_line_coordinates_are_strict_and_atomic(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.sqlite3"
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())

    with CharacterDatabase(path) as database:
        dialogue_run = database.start_run(tmp_path, "iecli test", run_kind="dialogues")
        database.replace_dialogue_inventory(dialogue_run, [make_dialogue_resource()])
        database.apply_dialogue_batch([extraction], [])

        npc = extraction.lines[0]
        player = extraction.lines[1]
        invalid_lines = (
            [npc, npc.model_copy(update={"strref": npc.strref + 1})],
            [player, player.model_copy(update={"strref": player.strref + 1})],
            [npc.model_copy(update={"transition_index": 0})],
            [player.model_copy(update={"transition_index": None})],
        )
        for lines in invalid_lines:
            with pytest.raises(IntegrityError):
                database.apply_dialogue_batch(
                    [DialogueExtraction(detail=extraction.detail, lines=lines)],
                    [],
                )

        reader = _reader(path)
        try:
            with Session(reader) as session:
                assert len(session.exec(select(DialogueLineRecord)).all()) == len(extraction.lines)
        finally:
            reader.dispose()
        assert database.dialogue_targets(refresh=False) == []
        assert database.integrity_check() == "ok"


def test_run_and_batch_invariants_fail_before_mutation(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.sqlite3"
    character = make_resource()
    dialogue = make_dialogue_resource()

    with CharacterDatabase(path) as database:
        character_run = database.start_run(tmp_path, "iecli test")
        database.replace_inventory(character_run, [character])
        dialogue_run = database.start_run(tmp_path, "iecli test", run_kind="dialogues")
        database.replace_dialogue_inventory(dialogue_run, [dialogue])

        with pytest.raises(AssertionError, match="Unknown extraction run"):
            database.replace_inventory(999, [])
        with pytest.raises(AssertionError, match="Unknown extraction run"):
            database.replace_dialogue_inventory(999, [])
        with pytest.raises(AssertionError, match="expected characters"):
            database.replace_inventory(dialogue_run, [])
        with pytest.raises(AssertionError, match="expected dialogues"):
            database.replace_dialogue_inventory(character_run, [])

        unknown_character = make_resource("OTHER.CRE")
        with pytest.raises(AssertionError, match="outside the active inventory"):
            database.apply_detail_batch(
                [CharacterDetail.from_dump(unknown_character, make_dump("OTHER.CRE"))],
                [],
            )
        with pytest.raises(AssertionError, match="outside the active inventory"):
            database.apply_dialogue_batch(
                [DialogueExtraction.from_dump(make_dialogue_dump("OTHER.DLG"))],
                [],
            )

        assert database.detail_targets(refresh=True) == {character.resource_name}
        assert database.dialogue_targets(refresh=True) == [dialogue.resource_name]
        assert database.integrity_check() == "ok"


def test_existing_database_requires_exact_schema_metadata(tmp_path: Path) -> None:
    missing_table = tmp_path / "missing-table.sqlite3"
    with closing(sqlite3.connect(missing_table)) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.commit()
    with pytest.raises(AssertionError, match="no schema version"):
        CharacterDatabase(missing_table)

    missing_row = tmp_path / "missing-row.sqlite3"
    with CharacterDatabase(missing_row):
        pass
    with closing(sqlite3.connect(missing_row)) as connection:
        connection.execute("DELETE FROM schema_metadata WHERE key = 'schema_version'")
        connection.commit()
    with pytest.raises(AssertionError, match="no schema version"):
        CharacterDatabase(missing_row)

    wrong_version = tmp_path / "wrong-version.sqlite3"
    with CharacterDatabase(wrong_version):
        pass
    with closing(sqlite3.connect(wrong_version)) as connection:
        connection.execute("UPDATE schema_metadata SET value = '999' WHERE key = 'schema_version'")
        connection.commit()
    with pytest.raises(AssertionError, match="schema is 999; expected 1"):
        CharacterDatabase(wrong_version)
