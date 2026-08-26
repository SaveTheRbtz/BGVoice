"""Public repository and HTTP contracts for the read-only pipeline browser."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from bgvoice.database import Character, CharacterDatabase
from bgvoice.models import CharacterDetail, DialogueExtraction
from bgvoice.web import ReadOnlyPipelineDatabase, create_app
from tests.factories import make_dialogue_dump, make_dialogue_resource, make_dump, make_resource


@pytest.fixture
def web_database(tmp_path: Path) -> Path:
    """Build enough representative data to exercise every browser collection."""
    path = tmp_path / "pipeline.sqlite3"
    aerie = make_resource()
    minsc = make_resource("MINSC.CRE")
    empty = make_resource("EMPTY.CRE")
    ghost = make_resource("GHOST.CRE")
    extras = [make_resource(f"EXTRA{index}.CRE") for index in range(8)]

    details = [
        CharacterDetail.from_dump(aerie, make_dump()),
        CharacterDetail.from_dump(
            minsc,
            make_dump("MINSC.CRE", short_name="Minsc", long_name="Minsc", dialog="MINSC"),
        ),
        CharacterDetail.from_dump(
            empty,
            make_dump("EMPTY.CRE", short_name="Nameless", long_name=None, dialog="NONE"),
        ),
        CharacterDetail.from_dump(
            ghost,
            make_dump("GHOST.CRE", short_name="Ghost", long_name="Ghost", dialog="GHOST"),
        ),
        *[
            CharacterDetail.from_dump(
                resource,
                make_dump(
                    resource.resource_name,
                    short_name=resource.resref.title(),
                    long_name=None,
                    dialog="NONE",
                ),
            )
            for resource in extras
        ],
    ]

    with CharacterDatabase(path) as database:
        character_run = database.start_run(tmp_path, "iecli test")
        database.replace_inventory(character_run, [aerie, minsc, empty, ghost, *extras])
        database.apply_detail_batch(details, [])
        database.finish_run(
            character_run,
            status="complete",
            attempted=len(details),
            extracted=len(details),
            failures=0,
        )

        dialogue_run = database.start_run(tmp_path, "iecli test", run_kind="dialogues")
        database.replace_dialogue_inventory(
            dialogue_run,
            [
                make_dialogue_resource(),
                make_dialogue_resource("MINSC.DLG"),
                make_dialogue_resource("UNUSED.DLG"),
            ],
        )
        database.apply_dialogue_batch(
            [
                DialogueExtraction.from_dump(make_dialogue_dump()),
                DialogueExtraction.from_dump(make_dialogue_dump("UNUSED.DLG")),
            ],
            [("MINSC.DLG", "missing test dialogue")],
        )
        database.finish_run(
            dialogue_run,
            status="complete_with_errors",
            attempted=3,
            extracted=2,
            failures=1,
        )
        database.rebuild_attributions()

    return path


@pytest.fixture
def api(web_database: Path) -> TestClient:
    return TestClient(create_app(web_database, web_database.parent / "missing-dist"))


def test_repository_is_healthy_read_only_and_reports_pipeline_totals(web_database: Path) -> None:
    database = ReadOnlyPipelineDatabase(web_database)

    health = database.health()
    assert health.status == "ok"
    assert health.sqlite_query_only is True
    assert health.schema_version == 1

    stats = database.stats()
    assert (stats.characters_total, stats.characters_complete, stats.characters_with_dialogue) == (
        12,
        12,
        3,
    )
    assert (stats.dialogues_total, stats.dialogues_complete, stats.dialogue_lines) == (3, 2, 8)
    assert stats.line_records_total == 10
    assert (
        stats.characters_matched,
        stats.characters_missing_dialogue,
        stats.characters_dialogue_failed,
    ) == (1, 1, 1)
    assert stats.attribution_completed_at is not None
    assert stats.characters_unavailable == 0
    assert (stats.dialogues_attributed, stats.dialogues_unattributed) == (2, 1)
    assert [run.run_kind for run in stats.latest_runs] == ["dialogues", "characters"]


def test_read_session_keeps_one_snapshot_without_blocking_a_writer(web_database: Path) -> None:
    database = ReadOnlyPipelineDatabase(web_database)

    with database.session() as session:
        before = set(session.exec(select(Character.resource_name).where(Character.active == 1)))

        with CharacterDatabase(web_database) as writer:
            run_id = writer.start_run(web_database.parent, "iecli test")
            writer.replace_inventory(run_id, [make_resource("NEW.CRE")])
            writer.finish_run(
                run_id,
                status="complete",
                attempted=0,
                extracted=0,
                failures=0,
            )

        during = set(session.exec(select(Character.resource_name).where(Character.active == 1)))

    assert during == before
    assert database.stats().characters_total == 1


def test_character_api_supports_filters_sort_fts_pagination_and_detail(
    api: TestClient,
) -> None:
    assert api.get("/api/health").json()["sqlite_query_only"] is True
    assert api.post("/api/characters").status_code == 405
    assert api.get("/api/stats").json()["characters_total"] == 12

    options = api.get("/api/filter-options").json()
    assert options["source_kinds"] == [{"value": "override", "count": 12}]
    assert options["gender_ids"] == [{"value": 2, "count": 12}]

    first_page = api.get(
        "/api/characters",
        params={
            "page": 1,
            "page_size": 10,
            "sort": "resource_name",
            "direction": "asc",
        },
    ).json()
    second_page = api.get(
        "/api/characters",
        params={
            "page": 2,
            "page_size": 10,
            "sort": "resource_name",
            "direction": "asc",
        },
    ).json()
    assert (first_page["total"], first_page["page_count"], len(first_page["items"])) == (
        12,
        2,
        10,
    )
    assert [item["resource_name"] for item in second_page["items"]] == [
        "GHOST.CRE",
        "MINSC.CRE",
    ]

    search = api.get("/api/characters", params={"q": "Mins", "page_size": 10}).json()
    assert [item["resource_name"] for item in search["items"]] == ["MINSC.CRE"]
    assert api.get("/api/characters", params={"q": " !!! ", "page_size": 100}).json()["total"] == 12
    escaped_syntax = api.get("/api/characters", params={"q": 'Aerie OR "Minsc"', "page_size": 10})
    assert escaped_syntax.status_code == 200
    assert escaped_syntax.json()["total"] == 0

    assert (
        api.get("/api/characters", params={"has_dialog": "false", "page_size": 100}).json()["total"]
        == 9
    )
    assert (
        api.get(
            "/api/characters",
            params={
                "gender_id": 2,
                "source_kind": "override",
                "status": "complete",
                "page_size": 100,
            },
        ).json()["total"]
        == 12
    )
    missing = api.get(
        "/api/characters",
        params={"attribution_status": "missing_dialogue", "page_size": 10},
    ).json()
    assert [item["resource_name"] for item in missing["items"]] == ["GHOST.CRE"]

    sorted_rows = api.get(
        "/api/characters",
        params={"sort": "dialogue_transition_count", "direction": "desc", "page_size": 10},
    ).json()
    assert sorted_rows["items"][0]["resource_name"] == "AERIE.CRE"
    assert sorted_rows["items"][0]["dialogue_transition_count"] == 3
    assert api.get("/api/characters", params={"sort": "DROP TABLE"}).status_code == 422

    detail = api.get("/api/characters/AERIE.CRE")
    assert detail.status_code == 200
    assert detail.json()["character"]["display_name"] == "Aerie"
    assert detail.json()["dialogue"]["dialogue_line_count"] == 4
    empty_detail = api.get("/api/characters/EMPTY.CRE").json()
    assert empty_detail["dialogue"] is None
    assert empty_detail["attribution_status"] == "no_dialogue"
    assert api.get("/api/characters/UNKNOWN.CRE").status_code == 404


def test_dialogue_and_line_apis_support_fts_filters_and_sorting(api: TestClient) -> None:
    dialogues = api.get(
        "/api/dialogues",
        params={"attributed": "false", "page_size": 10, "q": "Unus"},
    )
    assert dialogues.status_code == 200
    assert dialogues.json()["total"] == 1
    dialogue = dialogues.json()["items"][0]
    assert dialogue["resource_name"] == "UNUSED.DLG"
    assert dialogue["character_count"] == 0
    assert (dialogue["source_kind"], dialogue["source_path"]) == (
        "override",
        "C:/game/override/UNUSED.DLG",
    )

    attributed = api.get(
        "/api/dialogues",
        params={
            "attributed": "true",
            "status": "complete",
            "source_kind": "override",
            "sort": "character_count",
            "direction": "asc",
            "page_size": 10,
        },
    ).json()
    assert [item["resource_name"] for item in attributed["items"]] == ["AERIE.DLG"]

    lines = api.get(
        "/api/lines",
        params={
            "q": "Quest",
            "line_kind": "journal",
            "source_kind": "override",
            "attributed": "false",
            "sort": "transition_index",
            "direction": "desc",
            "page_size": 10,
        },
    )
    assert lines.status_code == 200
    assert lines.json()["total"] == 1
    line = lines.json()["items"][0]
    assert line["dialogue_resource_name"] == "UNUSED.DLG"
    assert line["transition_index"] == 2
    assert line["source_kind"] == "override"

    schemas = api.get("/openapi.json").json()["components"]["schemas"]
    assert {"source_kind", "source_path"} <= set(schemas["DialogueRow"]["required"])
    assert "source_kind" in schemas["DialogueLineRow"]["required"]


def test_create_app_serves_assets_files_and_spa_fallback(
    web_database: Path, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<h1>BGVoice SPA</h1>", encoding="utf-8")
    (assets / "app.css").write_text("body{}", encoding="utf-8")
    (dist / "robots.txt").write_text("User-agent: *", encoding="utf-8")
    client = TestClient(create_app(web_database, dist))

    assert "BGVoice SPA" in client.get("/characters/AERIE.CRE").text
    assert client.get("/assets/app.css").text == "body{}"
    assert client.get("/robots.txt").text == "User-agent: *"
    assert client.get("/missing-route").text == "<h1>BGVoice SPA</h1>"
    assert client.get("/api/health").headers["content-type"].startswith("application/json")


def test_repository_requires_an_existing_database_and_handles_an_empty_one(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="does not exist"):
        ReadOnlyPipelineDatabase(tmp_path / "missing.sqlite3")

    empty_path = tmp_path / "empty.sqlite3"
    with CharacterDatabase(empty_path):
        pass

    database = ReadOnlyPipelineDatabase(empty_path)
    stats = database.stats()
    assert stats.characters_total == 0
    assert stats.dialogues_total == 0
    assert stats.attribution_completed_at is None
    assert (
        stats.characters_unavailable,
        stats.characters_matched,
        stats.characters_missing_dialogue,
        stats.characters_dialogue_failed,
        stats.characters_without_dialogue,
        stats.dialogues_attributed,
        stats.dialogues_unattributed,
        stats.attributed_dialogue_lines,
        stats.unattributed_dialogue_lines,
    ) == (0,) * 9

    with CharacterDatabase(empty_path) as writer:
        run_id = writer.start_run(tmp_path, "iecli test")
        writer.replace_inventory(run_id, [make_resource("BROKEN.CRE")])
        writer.apply_detail_batch([], [("BROKEN.CRE", "broken test resource")])
        writer.finish_run(
            run_id,
            status="complete_with_errors",
            attempted=1,
            extracted=0,
            failures=1,
        )
        writer.rebuild_attributions()

    attributed = database.stats()
    assert attributed.attribution_completed_at is not None
    assert attributed.characters_unavailable == 1


def test_health_reports_missing_schema_metadata(tmp_path: Path) -> None:
    path = tmp_path / "missing-metadata.sqlite3"
    with CharacterDatabase(path):
        pass
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DELETE FROM schema_metadata WHERE key = 'schema_version'")
        connection.commit()

    with pytest.raises(AssertionError, match=r"schema metadata is missing.*Rebuild"):
        ReadOnlyPipelineDatabase(path).health()


def test_health_rejects_an_incompatible_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "wrong-version.sqlite3"
    with CharacterDatabase(path):
        pass
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("UPDATE schema_metadata SET value = '999'")
        connection.commit()

    with pytest.raises(AssertionError, match=r"database schema is 999; expected 1.*Rebuild"):
        ReadOnlyPipelineDatabase(path).health()
