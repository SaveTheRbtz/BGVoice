"""Deterministic generation workload and critical speech-input behavior."""

import asyncio
import json
import re
import wave
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace, TracebackType
from typing import Any, ClassVar, Self, cast

import av
import httpx
import pytest
from av.container import InputContainer

import bgvoice.generation as generation_module
from bgvoice.game_audio import encode_game_audio
from bgvoice.generation import (
    generate,
    load_workloads,
    round_robin_lines,
)
from bgvoice.generation_ai import (
    CharacterDirectedDialogue,
    DirectedLinePlan,
    DirectionBatchPlan,
    NarratorDirectedDialogue,
    VoiceDesignPlan,
    VoiceProfile,
)
from bgvoice.generation_store import GenerationStore
from bgvoice.inworld import BatchOperation, InworldClient, OperationError, PublishedVoice
from bgvoice.model_types import DialogueLineKind, RunStatus
from bgvoice.reader import PipelineReader
from bgvoice.storage_records import DialogueLineRecord, TtsBatchRecord


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
    dialogues = {
        "B.DLG": [_line("B.DLG", 3), _line("B.DLG", 0)],
        "A.DLG": [_line("A.DLG", 6), _line("A.DLG", 2), _line("A.DLG", 4)],
    }
    expected = [
        ("A.DLG", 2),
        ("B.DLG", 0),
        ("A.DLG", 4),
        ("B.DLG", 3),
        ("A.DLG", 6),
    ]
    assert [
        (line.dialogue_resource_name, line.state_index) for line in round_robin_lines(dialogues, 5)
    ] == expected
    assert [
        (line.dialogue_resource_name, line.state_index) for line in round_robin_lines(dialogues, 6)
    ] == expected
    assert [
        (line.dialogue_resource_name, line.state_index)
        for line in round_robin_lines(dialogues, None)
    ] == expected


@pytest.mark.anyio
async def test_current_voice_workload_uses_attributed_nonempty_npc_lines(
    shared_scenario_database: Path,
) -> None:
    reader = await PipelineReader.open(shared_scenario_database)
    try:
        workload = (await load_workloads(reader, ["Aerie"], 3))[0]
        complete_workload = (await load_workloads(reader, ["Aerie"], None))[0]
        deduplicated = await load_workloads(reader, ["Aerie", "aerie"], None)
    finally:
        reader.close()

    assert complete_workload.lines == workload.lines
    assert deduplicated == [complete_workload]
    assert workload.voice.voice_id == "aerie"
    assert len(workload.lines) == 2
    assert all(line.line_kind is DialogueLineKind.NPC and line.text for line in workload.lines)
    assert workload.ability_scores.render() == ("STR 10, DEX 17, CON 9, INT 16, WIS 16, CHA 14")
    assert workload.portrait_png == b"\x89PNG\r\n\x1a\nfixture"


def test_provider_audio_is_encoded_for_the_enhanced_edition() -> None:
    first = BytesIO()
    with wave.open(first, "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(44_100)
        audio.writeframes(b"\0\0" * 2 * 4_410)

    second = BytesIO()
    with wave.open(second, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22_050)
        audio.writeframes(b"\0\0" * 2_205)

    encoded = encode_game_audio(first.getvalue() + second.getvalue())
    identification = encoded.index(b"\x01vorbis")
    with cast(InputContainer, av.open(BytesIO(encoded))) as container:
        samples = sum(frame.samples for frame in container.decode(audio=0))

    assert encoded.startswith(b"OggS")
    assert samples / 22_050 == pytest.approx(0.2, abs=0.015)
    assert encoded[identification + 11] == 1
    assert int.from_bytes(encoded[identification + 12 : identification + 16], "little") == 22_050
    assert int.from_bytes(encoded[identification + 20 : identification + 24], "little") >= 89_000


class _FakeResponses:
    calls: ClassVar[list[dict[str, object]]] = []

    async def parse(self, **arguments: object) -> object:
        self.calls.append(arguments)
        if arguments["text_format"] is VoiceDesignPlan:
            return SimpleNamespace(
                output_parsed=VoiceDesignPlan(
                    language_code="en-GB",
                    profile=VoiceProfile(
                        dialect="English with a subtle northern English accent",
                        gender="female",
                        age="young adult",
                        emotion="earnest and hopeful",
                        tone="warm and conversational",
                        pitch="medium-high",
                        volume="moderate",
                        speed="quick but articulate",
                        clarity="clear",
                        fluency="fluent",
                        personality="compassionate and resilient",
                        texture="bright and lightly breathy",
                    ),
                    preview_text=("We travel together, and we shall face whatever waits ahead."),
                    research_summary="Game evidence agrees with published character references.",
                    source_urls=["https://example.com/aerie"],
                ),
                output=[SimpleNamespace(type="web_search_call")],
            )

        messages = cast(list[dict[str, object]], arguments["input"])
        content = cast(str, messages[1]["content"])
        identifiers = re.findall(r"^Requested ID: (.+)$", content, re.MULTILINE)
        return SimpleNamespace(
            output_parsed=DirectionBatchPlan(
                items=[
                    DirectedLinePlan(
                        id=identifier,
                        result=(
                            CharacterDirectedDialogue(
                                speaker="character",
                                directed_dialogue="[warmly] A quest for another day.",
                            )
                            if index == 0
                            else NarratorDirectedDialogue(
                                speaker="narrator",
                                directed_dialogue=(
                                    "[narrate calmly] The road grows quiet as night falls."
                                ),
                            )
                        ),
                    )
                    for index, identifier in enumerate(identifiers)
                ]
            )
        )


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


class _ReusableVoiceProvider:
    async def list_voices(self) -> list[PublishedVoice]:
        return [
            PublishedVoice(
                name="workspaces/test/voices/aerie-existing",
                voiceId="aerie-existing",
                displayName="Aerie",
                description="An existing carefully designed voice.",
                langCode="EN_GB",
                tags=["bgvoice"],
                source="IVC",
            )
        ]


class _FailedBatchProvider:
    async def poll_operation(self, name: str) -> BatchOperation:
        return BatchOperation(
            name=name,
            done=True,
            error=OperationError(code=13, message="provider synthesis failed"),
        )


@pytest.mark.anyio
async def test_bounded_scheduler_settles_every_task_before_propagating_failure() -> None:
    active = 0
    peak = 0
    seen: set[int] = set()
    saturated = asyncio.Event()
    release = asyncio.Event()

    async def process(batch: int) -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        seen.add(batch)
        if active == 4:
            saturated.set()
        await release.wait()
        active -= 1

    running = asyncio.create_task(
        generation_module._run_concurrently(list(range(5)), process, asyncio.Semaphore(4))
    )
    await asyncio.wait_for(saturated.wait(), timeout=1)
    assert active == peak == 4
    release.set()
    await running

    assert seen == set(range(5))

    settled = False

    async def fail_or_settle(batch: int) -> None:
        nonlocal settled
        if batch == 0:
            raise RuntimeError("provider failed")
        await asyncio.sleep(0)
        settled = True

    with pytest.raises(RuntimeError, match="provider failed"):
        await generation_module._run_concurrently([0, 1], fail_or_settle, asyncio.Semaphore(2))
    assert settled


@pytest.mark.anyio
async def test_provider_voice_is_reused_when_local_generation_is_missing(
    scenario_database: Path,
) -> None:
    store = await GenerationStore.open(scenario_database)
    try:
        record = await generation_module._reuse_existing_voice(
            cast(InworldClient, _ReusableVoiceProvider()),
            store,
            "aerie",
            "Aerie",
        )
        persisted = await store.generated_voice("aerie")
    finally:
        store.close()

    assert record == persisted
    assert record is not None
    assert record.inworld_voice_id == "aerie-existing"
    assert record.description.language_code == "en-GB"


@pytest.mark.anyio
async def test_failed_provider_batch_is_persisted_without_audio(
    scenario_database: Path,
) -> None:
    batch = TtsBatchRecord(
        operation_name="workspaces/test/ttsBatchJobs/failed/operations/op",
        status=RunStatus.RUNNING,
        started_at="2026-08-27T12:00:00+00:00",
    )
    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_batches([batch])
        await generation_module._resume_batches(
            store,
            cast(InworldClient, _FailedBatchProvider()),
        )
        persisted = {record.operation_name: record for record in await store.batches()}[
            batch.operation_name
        ]
        audio = await store.generated_audio()
    finally:
        store.close()

    assert audio == []
    assert persisted.status is RunStatus.FAILED
    assert persisted.error == "provider synthesis failed"
    assert persisted.completed_at is not None


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
    voice_list_requests = 0
    operations: dict[str, list[str]] = {}
    published: dict[str, dict[str, object]] = {}
    published_names: list[str] = []
    deleted_voice_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal draft, batch, voice_list_requests
        path = request.url.path
        if path == "/voices/v1/voices" and request.method == "GET":
            voice_list_requests += 1
            return httpx.Response(200, json={"voices": list(published.values())})
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
            voice_id = f"voice-{display_name.casefold().replace(' ', '-')}-{draft}"
            voice = {
                "name": f"workspaces/test/voices/{voice_id}",
                "voiceId": voice_id,
                "displayName": display_name,
                "description": body["description"],
                "langCode": "EN_GB",
                "tags": ["bgvoice"],
                "source": "IVC",
            }
            published[voice_id] = voice
            published_names.append(display_name)
            return httpx.Response(200, json=voice)
        if path.startswith("/voices/v1/voices/") and request.method == "DELETE":
            voice_id = path.rsplit("/", 1)[1]
            assert voice_id in published
            del published[voice_id]
            deleted_voice_ids.append(voice_id)
            return httpx.Response(200)
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

    transport = httpx.MockTransport(handler)
    client_type = httpx.AsyncClient
    monkeypatch.setattr(generation_module, "AsyncOpenAI", _FakeOpenAI)
    monkeypatch.setattr(generation_module, "AUDIO_WRITE_BATCH_SIZE", 1)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_: client_type(transport=transport),
    )
    _FakeResponses.calls.clear()

    first_summary = await generate(
        scenario_database,
        ["Aerie"],
        2,
        "openai-test",
        "inworld-test",
    )
    store = await GenerationStore.open(scenario_database)
    try:
        first_voices = await store.generated_voices()
        first_recordings = await store.generated_audio(["aerie"])
    finally:
        store.close()

    resumed_summary = await generate(
        scenario_database,
        ["Aerie"],
        2,
        "openai-test",
        "inworld-test",
    )
    second_summary = await generate(
        scenario_database,
        ["Aerie"],
        2,
        "openai-test",
        "inworld-test",
        recreate_voices=True,
    )
    store = await GenerationStore.open(scenario_database)
    try:
        voices = await store.generated_voices()
        directions = await store.directed_lines(["aerie"])
        recordings = await store.generated_audio(["aerie"])
        batches = await store.batches()
    finally:
        store.close()

    expected_summary = {
        "voices": 1,
        "selected_lines": 2,
        "directed_lines": 2,
        "generated_audio": 2,
    }
    assert first_summary.model_dump() == expected_summary
    assert resumed_summary.model_dump() == expected_summary
    assert second_summary.model_dump() == expected_summary
    assert set(voices) == {"aerie", "narrator"}
    assert sum(line.character is not None for line in directions) == 1
    assert sum(line.narrator is not None for line in directions) == 1
    assert all(record.audio.startswith(b"OggS") for record in recordings)
    assert {record.batch_operation_name for record in first_recordings}.isdisjoint(
        record.batch_operation_name for record in recordings
    )
    assert all(batch.status.value == "complete" for batch in batches)
    assert len(batches) == 2

    first_character_voice_id = first_voices["aerie"].inworld_voice_id
    narrator_voice_id = first_voices["narrator"].inworld_voice_id
    assert voices["aerie"].inworld_voice_id != first_character_voice_id
    assert voices["narrator"].inworld_voice_id == narrator_voice_id
    assert deleted_voice_ids == [first_character_voice_id]
    assert narrator_voice_id in published
    assert published_names == ["Aerie", "Narrator", "Aerie"]
    assert voice_list_requests == 3
    assert {record.inworld_voice_id for record in recordings} == {
        voices["aerie"].inworld_voice_id,
        narrator_voice_id,
    }

    voice_calls = [call for call in _FakeResponses.calls if call["text_format"] is VoiceDesignPlan]
    direction_calls = [
        call for call in _FakeResponses.calls if call["text_format"] is DirectionBatchPlan
    ]
    assert len(voice_calls) == 2
    assert len(direction_calls) == 2
    assert all(
        call["tools"] == [{"type": "web_search"}] and call["tool_choice"] == "required"
        for call in voice_calls
    )
    assert all(call["tools"] == [] and call["tool_choice"] == "none" for call in direction_calls)
    direction_prompts = [
        cast(str, cast(list[dict[str, object]], call["input"])[1]["content"])
        for call in direction_calls
    ]
    assert all(
        "Previous NPC/scene line: Hello." in prompt and "Player response: Hi." in prompt
        for prompt in direction_prompts
    )
