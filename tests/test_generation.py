"""Deterministic generation workload and critical speech-input behavior."""

import json
import wave
from io import BytesIO
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast

import httpx
import pytest

import bgvoice.generation as generation_module
from bgvoice.game_audio import encode_game_audio
from bgvoice.generation import (
    DirectedLinePlan,
    DirectionBatchPlan,
    VoiceDesignPlan,
    _validated_direction,
    generate,
    load_workloads,
    round_robin_lines,
)
from bgvoice.generation_store import GenerationStore
from bgvoice.model_types import DialogueLineKind, Speaker
from bgvoice.reader import PipelineReader
from bgvoice.storage_records import DialogueLineRecord


def _line(dialogue: str, state: int) -> DialogueLineRecord:
    identifier = f"{dialogue}:npc:{state}:-"
    return DialogueLineRecord(
        id=identifier,
        run_id="run",
        dialogue_resource_name=dialogue,
        line_kind=DialogueLineKind.NPC,
        state_index=state,
        strref=state,
        text=f"Line {state}",
        tokens=[],
        serialized_size=10,
        search_text=f"Line {state}",
    )


def test_round_robin_takes_each_dialogues_lowest_remaining_state() -> None:
    selected = round_robin_lines(
        {
            "B.DLG": [_line("B.DLG", 3), _line("B.DLG", 0)],
            "A.DLG": [_line("A.DLG", 6), _line("A.DLG", 2), _line("A.DLG", 4)],
        },
        5,
    )

    assert [(line.dialogue_resource_name, line.state_index) for line in selected] == [
        ("A.DLG", 2),
        ("B.DLG", 0),
        ("A.DLG", 4),
        ("B.DLG", 3),
        ("A.DLG", 6),
    ]


@pytest.mark.anyio
async def test_current_voice_workload_uses_attributed_nonempty_npc_lines(
    shared_scenario_database: Path,
) -> None:
    reader = await PipelineReader.open(shared_scenario_database)
    try:
        workload = (await load_workloads(reader, ["Aerie"], 2))[0]
    finally:
        reader.close()

    assert workload.voice.voice_id == "aerie"
    assert len(workload.lines) == 2
    assert all(line.line_kind is DialogueLineKind.NPC and line.text for line in workload.lines)


@pytest.mark.parametrize(
    "text",
    ["Hello, <CHARNAME>.", "*whispers* Hello.", "```Hello```", "   "],
)
def test_direction_rejects_only_content_that_cannot_be_synthesized(text: str) -> None:
    with pytest.raises(AssertionError):
        _validated_direction(text)


def test_direction_preserves_valid_tts_instructions() -> None:
    assert _validated_direction(" [speak quietly] We should go. ") == (
        "[speak quietly] We should go."
    )


def test_provider_audio_is_encoded_for_the_enhanced_edition() -> None:
    source = BytesIO()
    with wave.open(source, "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(44_100)
        audio.writeframes(b"\0\0" * 2 * 4_410)

    encoded = encode_game_audio(source.getvalue())
    identification = encoded.index(b"\x01vorbis")

    assert encoded.startswith(b"OggS")
    assert encoded[identification + 11] == 1
    assert int.from_bytes(encoded[identification + 12 : identification + 16], "little") == 22_050
    assert int.from_bytes(encoded[identification + 20 : identification + 24], "little") >= 89_000


class _FakeResponses:
    async def parse(self, **arguments: object) -> object:
        if arguments["text_format"] is VoiceDesignPlan:
            return type(
                "VoiceResponse",
                (),
                {
                    "output_parsed": VoiceDesignPlan(
                        description=(
                            "A clear, warm British voice with an earnest, measured delivery. "
                            "Perfect broadcast quality audio."
                        ),
                        language_code="en-GB",
                        preview_text="We travel together, and we shall face whatever waits ahead.",
                    )
                },
            )()

        messages = cast(list[dict[str, object]], arguments["input"])
        content = cast(str, messages[1]["content"])
        source = content.split("Lines to direct:\n", 1)[1].splitlines()
        return type(
            "DirectionResponse",
            (),
            {
                "output_parsed": DirectionBatchPlan(
                    lines=[
                        DirectedLinePlan(
                            id=line.partition("\t")[0],
                            speaker=(Speaker.CHARACTER if index == 0 else Speaker.NARRATOR),
                            text=(
                                "[warmly] A quest for another day."
                                if "<" in line
                                else f"[warmly] {line.partition('\t')[2]}"
                            ),
                        )
                        for index, line in enumerate(source)
                    ]
                )
            },
        )()


class _FakeOpenAI:
    def __init__(self, *, api_key: str) -> None:
        assert api_key == "openai-test"
        self.responses = _FakeResponses()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


@pytest.mark.anyio
async def test_generation_runs_from_voice_design_through_game_audio(
    scenario_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_audio = BytesIO()
    with wave.open(provider_audio, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22_050)
        audio.writeframes(b"\0\0" * 2_205)

    draft = 0
    batch = 0
    operations: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal draft, batch
        path = request.url.path
        if path == "/voices/v1/voices" and request.method == "GET":
            return httpx.Response(200, json={"voices": []})
        if path == "/voices/v1/voices:design":
            draft += 1
            return httpx.Response(
                200,
                json={
                    "langCode": "EN_GB",
                    "previewVoices": [
                        {
                            "voiceId": f"draft-{draft}",
                            "previewText": "Ready.",
                            "previewAudio": "UklGRg==",
                        }
                    ],
                },
            )
        if path.endswith(":publish"):
            body = cast(dict[str, Any], json.loads(request.content))
            display_name = cast(str, body["displayName"])
            return httpx.Response(
                200,
                json={
                    "name": f"workspaces/test/voices/{draft}",
                    "voiceId": f"voice-{display_name.casefold().replace(' ', '-')}",
                    "displayName": display_name,
                    "description": body["description"],
                    "langCode": "EN_GB",
                    "tags": ["bgvoice"],
                    "source": "IVC",
                },
            )
        if path == "/tts/v1/voice:synthesizeBatch":
            batch += 1
            body = cast(dict[str, Any], json.loads(request.content))
            custom_ids = [cast(str, item["customId"]) for item in body["items"]]
            name = f"workspaces/test/ttsBatchJobs/{batch}/operations/op"
            operations[name] = custom_ids
            return httpx.Response(200, json={"name": name})
        if path.startswith("/lro/v1alpha/"):
            name = path.removeprefix("/lro/v1alpha/")
            assert name in operations
            return httpx.Response(
                200,
                json={
                    "name": name,
                    "done": True,
                    "response": {
                        "resultsUri": f"https://signed.example/results/{name.split('/')[3]}",
                        "expireTime": "2026-09-03T12:00:00Z",
                    },
                },
            )
        if request.url.host == "signed.example" and path.startswith("/results/"):
            batch_number = path.rsplit("/", 1)[1]
            name = f"workspaces/test/ttsBatchJobs/{batch_number}/operations/op"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "customId": custom_id,
                            "audioUri": f"https://signed.example/audio/{custom_id}.wav",
                        }
                        for custom_id in operations[name]
                    ]
                },
            )
        if request.url.host == "signed.example" and path.startswith("/audio/"):
            return httpx.Response(200, content=provider_audio.getvalue())
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(generation_module, "AsyncOpenAI", _FakeOpenAI)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: http)

    summary = await generate(
        scenario_database,
        ["Aerie"],
        2,
        "openai-test",
        "inworld-test",
    )
    store = await GenerationStore.open(scenario_database)
    try:
        voices = await store.generated_voices()
        directions = await store.directed_lines(["aerie"])
        recordings = await store.generated_audio(["aerie"])
        batches = await store.batches()
    finally:
        store.close()

    assert summary.model_dump() == {
        "voices": 1,
        "selected_lines": 2,
        "directed_lines": 2,
        "generated_audio": 2,
    }
    assert set(voices) == {"aerie", "narrator"}
    assert {line.speaker for line in directions} == {Speaker.CHARACTER, Speaker.NARRATOR}
    assert all(record.audio.startswith(b"OggS") for record in recordings)
    assert all(batch.status.value == "complete" for batch in batches)
