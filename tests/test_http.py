"""Public-path integration through extraction, LanceDB, Connect, and FastAPI."""

from io import BytesIO
from pathlib import Path

import lancedb
import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from PIL import Image

from bgvoice.character_models import CreDump
from bgvoice.database import PipelineDatabase
from bgvoice.dialogue_models import DlgDump
from bgvoice.model_types import (
    CreResource,
    DlgResource,
    GenerationFailureStage,
    PortraitResource,
    RunKind,
    StringReference,
)
from bgvoice.pipeline import extract_characters, extract_dialogues, extract_portraits
from bgvoice.storage_records import DirectedLineRecord
from bgvoice.web import create_app
from tests.factories import (
    make_dialogue_dump,
    make_dialogue_resource,
    make_direction,
    make_dump,
    make_generated_audio,
    make_generation_failure,
    make_portrait_resource,
    make_resource,
    make_voice_generation,
    make_voice_profile,
)
from tests.scenarios import finish_empty_stage

pytestmark = pytest.mark.integration

_PARENT = "installations/bg2ee-eet"
_CONNECT_HEADERS = {
    "content-type": "application/json",
    "connect-protocol-version": "1",
}


def _bmp() -> bytes:
    output = BytesIO()
    Image.new("RGB", (54, 84), (1, 2, 3)).save(output, format="BMP")
    return output.getvalue()


class PipelineClient:
    """One-resource ie-cli implementation for the public integration path."""

    def version(self) -> str:
        return "iecli integration"

    def list_creatures(self, game_root: Path) -> list[CreResource]:
        return [make_resource()]

    def list_dialogues(self, game_root: Path) -> list[DlgResource]:
        return [make_dialogue_resource()]

    def list_portraits(self, game_root: Path) -> list[PortraitResource]:
        return [make_portrait_resource()]

    def dump_creature(self, game_root: Path, resource_name: str) -> CreDump:
        return make_dump(resource_name)

    def dump_dialogue(self, game_root: Path, resource_name: str) -> DlgDump:
        return make_dialogue_dump(resource_name)

    def read_raw_resource(self, game_root: Path, resource_name: str) -> bytes:
        return _bmp()

    def read_text_resource(self, game_root: Path, resource_name: str) -> str:
        raise AssertionError("metadata is outside this focused integration scenario")

    def resolve_string(self, game_root: Path, strref: int) -> StringReference:
        return StringReference(strref=strref, text=f"text {strref}")


def _connect(client: TestClient, method: str, payload: dict[str, object]) -> Response:
    return client.post(
        f"/connect/bgvoice.v1.PipelineService/{method}",
        headers=_CONNECT_HEADERS,
        json=payload,
    )


def _seed_generated_audio(path: Path) -> DirectedLineRecord:
    line_id = "AERIE.DLG:npc:0:-"
    direction = make_direction("aerie", line_id, directed_dialogue="[warmly] Hello.")
    records = {
        "voice_profiles": make_voice_profile(
            description="A gentle young adventurer with a warm, earnest delivery."
        ),
        "voice_generations": make_voice_generation(),
        "directed_lines": direction,
        "generated_audio": make_generated_audio(direction, operation_name="operations/complete"),
    }
    connection = lancedb.connect(path)
    for table_name, record in records.items():
        connection.open_table(table_name).add([record.model_dump()])
    connection.open_table("generation_failures").add(
        [
            make_generation_failure(
                stage,
                line_id=line_id,
                error=f"{stage.value} failed",
            ).model_dump()
            for stage in GenerationFailureStage
        ]
    )
    return direction


def test_pipeline_output_is_browsable_over_connect_and_portrait_http(
    empty_database: PipelineDatabase,
    tmp_path: Path,
) -> None:
    database = empty_database
    path = database.path
    game_root = tmp_path / "game"
    client = PipelineClient()

    assert extract_characters(client, database, game_root, workers=2).status == "complete"
    assert extract_dialogues(client, database, game_root, workers=2).status == "complete"
    finish_empty_stage(database, game_root, RunKind.METADATA)
    assert extract_portraits(client, database, game_root, workers=2).extracted == 1
    summary = database.rebuild_attributions()
    assert (summary.characters_matched, summary.attributed_dialogue_lines) == (1, 4)
    direction = _seed_generated_audio(path)

    with TestClient(create_app(path)) as web:
        installation = _connect(web, "GetInstallation", {"name": _PARENT}).json()
        voices = _connect(
            web,
            "ListVoices",
            {"parent": _PARENT, "pageSize": 10, "filter": 'search("Aerie")'},
        )
        assert voices.status_code == 200
        voice = voices.json()["voices"][0]
        assert (voice["displayName"], voice["npcLineCount"]) == ("Aerie", "2")
        assert voice["characters"][0]["engineResourceName"] == "AERIE.CRE"

        corpus_lines = _connect(
            web,
            "ListDialogueLines",
            {
                "parent": _PARENT,
                "pageSize": 10,
                "filter": 'line_kind = "npc"',
                "orderBy": "text_length desc",
            },
        )
        assert corpus_lines.status_code == 200
        dialogue_lines = corpus_lines.json()["dialogueLines"]
        assert dialogue_lines[0]["text"] == "A quest for <DAYANDMONTH>."
        assert {line["text"] for line in dialogue_lines} == {
            "Hello.",
            "A quest for <DAYANDMONTH>.",
        }

        portrait = web.get(f"/v1/{_PARENT}/portraits/aeries:download")
        assert portrait.status_code == 200
        assert portrait.headers["content-type"] == "image/png"
        assert portrait.content.startswith(b"\x89PNG\r\n\x1a\n")

        voice = _connect(
            web,
            "ListVoices",
            {"parent": _PARENT, "filter": 'search("Aerie")'},
        ).json()["voices"][0]
        generated_lines = _connect(
            web,
            "ListDialogueLines",
            {
                "parent": _PARENT,
                "filter": 'voice_id = "aerie" AND directed = true AND voiced = true',
            },
        ).json()["dialogueLines"]
        audio_url = generated_lines[0]["directions"][0]["audioUrl"]
        audio = web.get(audio_url)
        missing_audio = web.get(f"/v1/{_PARENT}/generatedAudios/missing:download")

        pipeline_summary = installation["summary"]
        assert (
            pipeline_summary["generatedVoices"],
            pipeline_summary["uniqueInworldVoices"],
            pipeline_summary["directedLines"],
            pipeline_summary["generatedAudios"],
        ) == ("1", "1", "1", "1")
        assert voice["generatedVoice"]["inworldVoiceId"] == "voice-aerie"
        assert (voice["directedLineCount"], voice["generatedAudioCount"]) == ("1", "1")
        direction_json = generated_lines[0]["directions"][0]
        assert direction_json["id"] == direction.id
        assert direction_json["character"] == {"directedDialogue": "[warmly] Hello."}
        assert "narrator" not in direction_json
        assert (audio.status_code, audio.headers["content-type"], audio.content) == (
            200,
            "audio/ogg",
            b"OggSgenerated audio",
        )
        assert missing_audio.status_code == 404


def test_connect_browser_contract_uses_typed_resources_and_errors(
    shared_scenario_database: Path,
) -> None:
    collections = [
        ("ListVoices", "voices", "prompt"),
        ("ListCharacters", "characters", "detail"),
        ("ListDialogues", "dialogues", "detail"),
        ("ListDialogueLines", "dialogueLines", "text"),
        ("ListDialogueTransitions", "dialogueTransitions", "flagsRaw"),
        ("ListCharacterSounds", "characterSounds", "text"),
        ("ListRaces", "races", "lore"),
        ("ListCharacterClasses", "characterClasses", "texts"),
        ("ListKits", "kits", "displayName"),
        ("ListIdentifierDefinitions", "identifierDefinitions", "symbols"),
        ("ListReadableItems", "readableItems", "text"),
        ("ListExtractionRuns", "extractionRuns", "runId"),
    ]
    listed_resources: dict[str, dict[str, object]] = {}

    with TestClient(create_app(shared_scenario_database)) as client:
        for list_method, response_field, full_field in collections:
            payload: dict[str, object] = {"parent": _PARENT, "pageSize": 2}
            if list_method == "ListRaces":
                payload["filter"] = 'search("Floating aberrations")'
            elif list_method == "ListCharacterClasses":
                payload["filter"] = "class_id = 14"
            response = _connect(client, list_method, payload)
            body = response.json()
            resources = body[response_field]

            assert response.status_code == 200, list_method
            assert resources, list_method
            assert int(body["totalSize"]) >= len(resources), list_method
            assert full_field in resources[0], list_method
            listed_resources[response_field] = resources[0]
            if list_method == "ListRaces":
                assert resources[0]["displayName"] == "Beholder"
                assert resources[0]["lore"]["description"] == "Floating aberrations."

        for response_field, get_method in (
            ("voices", "GetVoice"),
            ("characters", "GetCharacter"),
            ("dialogues", "GetDialogue"),
        ):
            expected = listed_resources[response_field]
            fetched = _connect(client, get_method, {"name": expected["name"]})
            assert fetched.status_code == 200, get_method
            assert fetched.json() == expected, get_method

        installation = _connect(client, "GetInstallation", {"name": _PARENT})
        first = _connect(
            client,
            "ListCharacters",
            {"parent": _PARENT, "pageSize": 10, "orderBy": "engine_resource_name asc"},
        )
        resized = _connect(
            client,
            "ListCharacters",
            {
                "parent": _PARENT,
                "pageSize": 1,
                "pageToken": first.json()["nextPageToken"],
                "orderBy": "engine_resource_name asc",
            },
        )
        invalid_filter = _connect(
            client,
            "ListCharacters",
            {"parent": _PARENT, "filter": 'source_kind = "archive"'},
        )
        changed_token = _connect(
            client,
            "ListCharacters",
            {
                "parent": _PARENT,
                "pageSize": 10,
                "pageToken": first.json()["nextPageToken"],
                "orderBy": "engine_resource_name desc",
            },
        )
        missing = _connect(client, "GetVoice", {"name": f"{_PARENT}/voices/missing"})
        missing_installation = _connect(
            client,
            "GetInstallation",
            {"name": "installations/missing"},
        )
        missing_portrait = client.get(f"/v1/{_PARENT}/portraits/missing:download")
        wrong_installation = client.get("/v1/installations/missing/portraits/aeries:download")

    assert installation.status_code == 200
    assert installation.json()["summary"]["characters"] == "12"
    assert (len(first.json()["characters"]), len(resized.json()["characters"])) == (10, 1)
    assert resized.json()["nextPageToken"]
    assert invalid_filter.status_code == 400
    assert changed_token.status_code == 400
    assert missing.status_code == 404
    assert missing_installation.status_code == 404
    assert missing_portrait.status_code == 404
    assert wrong_installation.status_code == 404


def test_spa_static_assets_and_deep_links_share_one_host(
    shared_scenario_database: Path,
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<h1>BGVoice SPA</h1>", encoding="utf-8")
    (dist / "assets" / "app.css").write_text("body{}", encoding="utf-8")

    with TestClient(create_app(shared_scenario_database, dist)) as client:
        assert "BGVoice SPA" in client.get("/voices/aerie").text
        assert client.get("/assets/app.css").text == "body{}"
        assert client.get("/missing-route").text == "<h1>BGVoice SPA</h1>"
