"""Public repository and HTTP contracts for the read-only pipeline browser."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import lancedb
import pytest
from fastapi.testclient import TestClient
from lancedb.pydantic import LanceModel

from bgvoice.database import (
    CharacterRecord,
    DialogueLineRecord,
    DialogueRecord,
    PipelineDatabase,
)
from bgvoice.models import CharacterDetail, DialogueExtraction, RunKind, RunStatus
from bgvoice.web import CharacterQuery, PipelineReader, create_app
from tests.factories import make_dialogue_dump, make_dialogue_resource, make_dump, make_resource


@pytest.fixture
def web_database(tmp_path: Path) -> Path:
    """Build enough representative data to exercise every browser collection."""
    path = tmp_path / "pipeline.lancedb"
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

    database = PipelineDatabase(path)
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [aerie, minsc, empty, ghost, *extras])
    database.apply_detail_batch(details, [])
    database.finish_run(
        character_run,
        status=RunStatus.COMPLETE,
        attempted=len(details),
        extracted=len(details),
        failures=0,
    )

    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
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
        status=RunStatus.COMPLETE_WITH_ERRORS,
        attempted=3,
        extracted=2,
        failures=1,
    )
    database.rebuild_attributions()

    return path


@pytest.fixture
def api(web_database: Path) -> Iterator[TestClient]:
    with TestClient(create_app(web_database, web_database.parent / "missing-dist")) as client:
        yield client


def test_reader_is_healthy_and_reports_pipeline_totals(web_database: Path) -> None:
    async def verify() -> None:
        reader = await PipelineReader.open(web_database)
        try:
            assert reader.health().model_dump() == {"status": "ok", "storage": "lancedb"}
            stats = await reader.stats()
            assert stats.database_size > 0
            assert (
                stats.characters_total,
                stats.characters_complete,
                stats.characters_with_dialogue,
            ) == (12, 12, 3)
            assert (stats.dialogues_total, stats.dialogues_complete, stats.dialogue_lines) == (
                3,
                2,
                8,
            )
            assert stats.line_records_total == 10
            assert (
                stats.characters_matched,
                stats.characters_missing_dialogue,
                stats.characters_dialogue_failed,
            ) == (1, 1, 1)
            assert stats.attribution_completed_at is not None
            assert stats.characters_unavailable == 0
            assert (stats.dialogues_attributed, stats.dialogues_unattributed) == (2, 1)
            assert (stats.attributed_dialogue_lines, stats.unattributed_dialogue_lines) == (4, 4)
            assert [run.run_kind for run in stats.latest_runs] == ["dialogues", "characters"]
            assert all(type(run.id) is str for run in stats.latest_runs)
        finally:
            reader.close()

    asyncio.run(verify())


def test_reader_observes_committed_writes_from_another_connection(web_database: Path) -> None:
    async def verify() -> None:
        reader = await PipelineReader.open(web_database)
        try:
            assert (await reader.stats()).characters_total == 12

            resource = make_resource("NEW.CRE")
            writer = PipelineDatabase(web_database)
            run_id = writer.start_run(web_database.parent, "iecli test")
            writer.replace_inventory(run_id, [resource])
            writer.apply_detail_batch(
                [
                    CharacterDetail.from_dump(
                        resource,
                        make_dump(
                            "NEW.CRE",
                            short_name="Freshvoice",
                            long_name=None,
                            dialog=None,
                        ),
                    )
                ],
                [],
            )

            page = await reader.characters(CharacterQuery(q="Freshvoice", page_size=10))
            assert [row.resource_name for row in page.items] == ["NEW.CRE"]
            assert (await reader.stats()).characters_total == 1

            writer.finish_run(
                run_id,
                status=RunStatus.COMPLETE,
                attempted=1,
                extracted=1,
                failures=0,
            )
        finally:
            reader.close()

    asyncio.run(verify())


def test_character_api_supports_filters_sort_fts_pagination_and_detail(
    api: TestClient,
) -> None:
    assert api.get("/api/health").json() == {"status": "ok", "storage": "lancedb"}
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
    out_of_range = api.get("/api/characters", params={"page": 99, "page_size": 10}).json()
    assert out_of_range["items"] == []
    assert out_of_range["page_count"] == 2

    search = api.get("/api/characters", params={"q": "Minsc", "page_size": 10}).json()
    assert [item["resource_name"] for item in search["items"]] == ["MINSC.CRE"]
    assert api.get("/api/characters", params={"q": "Mins", "page_size": 10}).json()["total"] == 0
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
        params={"attributed": "false", "page_size": 10, "q": "UNUSED"},
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
    assert type(line["id"]) is str
    assert line["dialogue_resource_name"] == "UNUSED.DLG"
    assert line["transition_index"] == 2
    assert line["source_kind"] == "override"

    schemas = api.get("/openapi.json").json()["components"]["schemas"]
    assert {"source_kind", "source_path"} <= set(schemas["DialogueRow"]["required"])
    assert "source_kind" in schemas["DialogueLineRow"]["required"]


def test_fts_pagination_sorts_the_complete_match_set(tmp_path: Path) -> None:
    path = tmp_path / "fts-pages.lancedb"
    resources = [make_resource(f"R{index:02}.CRE") for index in range(35)]
    details = [
        CharacterDetail.from_dump(
            resource,
            make_dump(
                resource.resource_name,
                short_name="alpha alpha" if index == 0 else "alpha",
                long_name=None,
                dialog=None,
            ),
        )
        for index, resource in enumerate(resources)
    ]
    database = PipelineDatabase(path)
    run_id = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(run_id, resources)
    database.apply_detail_batch(details, [])
    database.finish_run(
        run_id,
        status=RunStatus.COMPLETE,
        attempted=len(details),
        extracted=len(details),
        failures=0,
    )
    dialogue_resources = [make_dialogue_resource(f"D{index:02}.DLG") for index in range(35)]
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, dialogue_resources)
    database.apply_dialogue_batch(
        [
            DialogueExtraction.from_dump(make_dialogue_dump(resource.resource_name))
            for resource in dialogue_resources
        ],
        [],
    )
    database.finish_run(
        dialogue_run,
        status=RunStatus.COMPLETE,
        attempted=len(dialogue_resources),
        extracted=len(dialogue_resources),
        failures=0,
    )
    with TestClient(create_app(path, tmp_path / "missing-dist")) as client:
        relevance = client.get(
            "/api/characters",
            params={"q": "alpha", "page_size": 10},
        ).json()
        assert (relevance["sort"], relevance["direction"]) == ("relevance", "desc")
        assert relevance["items"][0]["resource_name"] == "R00.CRE"
        relevance_names = [
            item["resource_name"]
            for page in range(1, 5)
            for item in client.get(
                "/api/characters",
                params={"q": "alpha", "page": page, "page_size": 10},
            ).json()["items"]
        ]
        assert relevance_names == [resource.resource_name for resource in resources]

        explicit = client.get(
            "/api/characters",
            params={
                "q": "alpha",
                "sort": "resource_name",
                "direction": "desc",
                "page_size": 10,
            },
        ).json()
        assert (explicit["sort"], explicit["direction"]) == ("resource_name", "desc")
        assert explicit["items"][0]["resource_name"] == "R34.CRE"

        explicit_names = [
            item["resource_name"]
            for page in range(1, 5)
            for item in client.get(
                "/api/characters",
                params={
                    "q": "alpha",
                    "sort": "resource_name",
                    "direction": "asc",
                    "page": page,
                    "page_size": 10,
                },
            ).json()["items"]
        ]
        dialogue_names = [
            item["resource_name"]
            for page in range(1, 5)
            for item in client.get(
                "/api/dialogues",
                params={"q": "game", "page": page, "page_size": 10},
            ).json()["items"]
        ]
        line_ids = [
            item["id"]
            for page in range(1, 5)
            for item in client.get(
                "/api/lines",
                params={"q": "Hello", "page": page, "page_size": 10},
            ).json()["items"]
        ]
    assert explicit_names == [resource.resource_name for resource in resources]
    assert dialogue_names == [resource.resource_name for resource in dialogue_resources]
    assert line_ids == [f"{resource.resource_name}:npc:0:-" for resource in dialogue_resources]


def test_create_app_serves_assets_files_and_spa_fallback(
    web_database: Path, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<h1>BGVoice SPA</h1>", encoding="utf-8")
    (assets / "app.css").write_text("body{}", encoding="utf-8")
    (dist / "robots.txt").write_text("User-agent: *", encoding="utf-8")
    with TestClient(create_app(web_database, dist)) as client:
        assert "BGVoice SPA" in client.get("/characters/AERIE.CRE").text
        assert client.get("/assets/app.css").text == "body{}"
        assert client.get("/robots.txt").text == "User-agent: *"
        assert client.get("/missing-route").text == "<h1>BGVoice SPA</h1>"
        assert client.get("/api/health").headers["content-type"].startswith("application/json")


def test_reader_requires_expected_tables_and_exact_schemas(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="does not exist"):
        asyncio.run(PipelineReader.open(tmp_path / "missing.lancedb"))

    empty_path = tmp_path / "empty.lancedb"
    empty_path.mkdir()
    with pytest.raises(AssertionError, match=r"expected.*characters"):
        asyncio.run(PipelineReader.open(empty_path))

    schema_path = tmp_path / "wrong-schema.lancedb"
    PipelineDatabase(schema_path)
    connection = lancedb.connect(schema_path)
    connection.drop_table("characters")

    class WrongCharacterRecord(LanceModel):
        resource_name: str

    connection.create_table("characters", schema=WrongCharacterRecord)
    with pytest.raises(AssertionError, match="characters table schema"):
        asyncio.run(PipelineReader.open(schema_path))


def test_empty_database_and_missing_attribution_are_zeroed(tmp_path: Path) -> None:
    path = tmp_path / "empty.lancedb"
    PipelineDatabase(path)

    async def verify() -> None:
        reader = await PipelineReader.open(path)
        try:
            stats = await reader.stats()
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
        finally:
            reader.close()

    asyncio.run(verify())


def test_mixed_character_attribution_generation_is_not_published(web_database: Path) -> None:
    connection = lancedb.connect(web_database)
    table = connection.open_table("characters")
    records = table.search().limit(None).to_pydantic(CharacterRecord)
    changed = CharacterRecord.model_validate(
        records[0]
        .model_copy(update={"attribution_completed_at": "2000-01-01T00:00:00+00:00"})
        .model_dump()
    )
    table.merge_insert("resource_name").when_matched_update_all().execute([changed])

    async def verify() -> None:
        reader = await PipelineReader.open(web_database)
        try:
            stats = await reader.stats()
            assert stats.attribution_completed_at is None
            assert (
                stats.characters_matched,
                stats.characters_missing_dialogue,
                stats.characters_dialogue_failed,
                stats.characters_without_dialogue,
                stats.dialogues_attributed,
                stats.dialogues_unattributed,
                stats.attributed_dialogue_lines,
                stats.unattributed_dialogue_lines,
            ) == (0,) * 8
        finally:
            reader.close()

    asyncio.run(verify())

    with TestClient(create_app(web_database, web_database.parent / "missing-dist")) as client:
        for endpoint, total in (("dialogues", 3), ("lines", 10)):
            unfiltered = client.get(f"/api/{endpoint}", params={"page_size": 100}).json()
            assert unfiltered["total"] == total
            assert all(item["character_count"] == 0 for item in unfiltered["items"])
            assert (
                client.get(
                    f"/api/{endpoint}",
                    params={"attributed": "true", "page_size": 100},
                ).json()["total"]
                == 0
            )
            assert (
                client.get(
                    f"/api/{endpoint}",
                    params={"attributed": "false", "page_size": 100},
                ).json()["total"]
                == total
            )


def test_endpoints_mask_rows_from_a_different_attribution_generation(
    web_database: Path,
) -> None:
    changed_at = "2000-01-01T00:00:00+00:00"
    connection = lancedb.connect(web_database)

    dialogues = connection.open_table("dialogues")
    dialogue = next(
        record
        for record in dialogues.search().limit(None).to_pydantic(DialogueRecord)
        if record.resource_name == "AERIE.DLG"
    )
    changed_dialogue = DialogueRecord.model_validate(
        dialogue.model_copy(update={"attribution_completed_at": changed_at}).model_dump()
    )
    dialogues.merge_insert("resource_name").when_matched_update_all().execute([changed_dialogue])

    lines = connection.open_table("dialogue_lines")
    changed_lines = [
        DialogueLineRecord.model_validate(
            line.model_copy(update={"attribution_completed_at": changed_at}).model_dump()
        )
        for line in lines.search().limit(None).to_pydantic(DialogueLineRecord)
        if line.dialogue_resource_name == "AERIE.DLG"
    ]
    lines.merge_insert("id").when_matched_update_all().execute(changed_lines)

    with TestClient(create_app(web_database, web_database.parent / "missing-dist")) as client:
        unfiltered_dialogues = client.get("/api/dialogues", params={"page_size": 100}).json()
        dialogue_counts = {
            item["resource_name"]: item["character_count"] for item in unfiltered_dialogues["items"]
        }
        assert dialogue_counts == {"AERIE.DLG": 0, "MINSC.DLG": 1, "UNUSED.DLG": 0}

        attributed_dialogues = client.get(
            "/api/dialogues", params={"attributed": "true", "page_size": 100}
        ).json()
        assert [item["resource_name"] for item in attributed_dialogues["items"]] == ["MINSC.DLG"]
        unattributed_dialogues = client.get(
            "/api/dialogues", params={"attributed": "false", "page_size": 100}
        ).json()
        assert {item["resource_name"] for item in unattributed_dialogues["items"]} == {
            "AERIE.DLG",
            "UNUSED.DLG",
        }

        unfiltered_lines = client.get("/api/lines", params={"page_size": 100}).json()
        assert unfiltered_lines["total"] == 10
        assert all(item["character_count"] == 0 for item in unfiltered_lines["items"])
        assert (
            client.get("/api/lines", params={"attributed": "true", "page_size": 100}).json()[
                "total"
            ]
            == 0
        )
        assert (
            client.get("/api/lines", params={"attributed": "false", "page_size": 100}).json()[
                "total"
            ]
            == 10
        )

        stats = client.get("/api/stats").json()
        assert (stats["dialogues_attributed"], stats["dialogues_unattributed"]) == (1, 2)
        assert (stats["attributed_dialogue_lines"], stats["unattributed_dialogue_lines"]) == (
            0,
            8,
        )


def test_reader_rejects_missing_native_index(web_database: Path) -> None:
    connection = lancedb.connect(web_database)
    connection.open_table("dialogues").drop_index("dialogues_search_fts")

    with pytest.raises(AssertionError, match=r"database indexes.*Rebuild"):
        asyncio.run(PipelineReader.open(web_database))
