"""Deterministic generation workload and critical speech-input behavior."""

import asyncio
import json
import wave
from collections import Counter
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace, TracebackType
from typing import Any, ClassVar, Self, cast

import av
import httpx
import pytest
from av.container import InputContainer

import bgvoice.generation as generation_module
from bgvoice.dialogue_context import DialogueHistoryIndex
from bgvoice.game_audio import encode_game_audio
from bgvoice.generation import (
    generate,
    load_workloads,
    round_robin_lines,
)
from bgvoice.generation_ai import (
    CharacterDirectedDialogue,
    DirectionPlan,
    DirectionSource,
    NarratorDirectedDialogue,
    VoiceDesignPlan,
    VoiceProfile,
)
from bgvoice.generation_store import GenerationStore
from bgvoice.inworld import (
    BatchItemError,
    BatchOperation,
    BatchOperationResponse,
    BatchResult,
    BatchResults,
    BatchSynthesisItem,
    InworldClient,
    OperationError,
    PublishedVoice,
)
from bgvoice.model_types import DialogueLineKind, GenerationFailureStage, RunStatus
from bgvoice.reader import PipelineReader
from bgvoice.storage_records import (
    CharacterDirection,
    DialogueLineRecord,
    DirectedLineRecord,
    GeneratedVoiceRecord,
    GenerationFailureRecord,
    TtsBatchRecord,
    VoiceDescription,
)


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


@pytest.mark.anyio
async def test_directions_continue_skip_persisted_and_clear_failures(
    scenario_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = await PipelineReader.open(scenario_database)
    store = await GenerationStore.open(scenario_database)
    try:
        workload = (await load_workloads(reader, ["Aerie"], 2))[0]
        skipped_text = workload.lines[0].text
        history = await DialogueHistoryIndex.load(reader)
        calls: list[tuple[str, str]] = []
        writes: list[list[str]] = []
        failing = True

        upsert = GenerationStore.upsert_directed_lines

        async def track_writes(
            target: GenerationStore,
            records: list[DirectedLineRecord],
        ) -> None:
            writes.append([record.dialogue_line_id for record in records])
            await upsert(target, records)

        async def direct_line(
            _client: object,
            source: DirectionSource,
            *,
            model: str,
        ) -> DirectionPlan:
            calls.append((source.text, model))
            if failing and source.text == skipped_text:
                raise RuntimeError(f"{model} returned invalid structured output")
            return DirectionPlan(
                result=CharacterDirectedDialogue(
                    speaker="character",
                    directed_dialogue="[speak clearly] Ready.",
                )
            )

        monkeypatch.setattr(generation_module, "create_direction", direct_line)
        monkeypatch.setattr(GenerationStore, "upsert_directed_lines", track_writes)
        await generation_module._direct_workload(
            cast(Any, object()),
            store,
            workload,
            history,
            asyncio.Semaphore(100),
        )
        directions = await store.directed_lines([workload.voice.voice_id])
        failures = await store.failures([workload.voice.voice_id])

        failing = False
        await generation_module._direct_workload(
            cast(Any, object()),
            store,
            workload,
            history,
            asyncio.Semaphore(100),
        )
        recovered_directions = await store.directed_lines([workload.voice.voice_id])
        recovered_failures = await store.failures([workload.voice.voice_id])
    finally:
        reader.close()
        store.close()

    assert Counter(calls) == Counter(
        {
            (cast(str, skipped_text), generation_module.DIRECTION_MODEL): 2,
            (cast(str, skipped_text), generation_module.DIRECTION_FALLBACK_MODEL): 1,
            (cast(str, workload.lines[1].text), generation_module.DIRECTION_MODEL): 1,
        }
    )
    assert writes == [[workload.lines[1].id], [workload.lines[0].id]]
    assert {line.dialogue_line_id for line in directions} == {workload.lines[1].id}
    assert [(failure.stage, failure.dialogue_line_id) for failure in failures] == [
        (GenerationFailureStage.DIALOGUE_DIRECTION, workload.lines[0].id)
    ]
    assert {line.dialogue_line_id for line in recovered_directions} == {
        line.id for line in workload.lines
    }
    assert (
        next(line for line in recovered_directions if line.dialogue_line_id == workload.lines[1].id)
        == directions[0]
    )
    assert recovered_failures == []


class _FakeHttp:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class _EmptyVoiceProvider:
    async def list_voices(self) -> list[PublishedVoice]:
        return []


@pytest.mark.anyio
async def test_voice_failure_does_not_block_direction_and_is_cleared_on_retry(
    scenario_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    directed: list[str] = []
    synthesized: list[str] = []

    async def ensure_voice(*_: object, **__: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("voice design unavailable")

    async def direct(
        _openai: object,
        _store: GenerationStore,
        workload: generation_module.VoiceWorkload,
        *_: object,
    ) -> None:
        directed.append(workload.voice.voice_id)

    async def synthesize(
        _store: GenerationStore,
        _inworld: object,
        workload: generation_module.VoiceWorkload,
        *_: object,
    ) -> None:
        synthesized.append(workload.voice.voice_id)

    async def resume(*_: object) -> None:
        return None

    monkeypatch.setattr(generation_module, "AsyncOpenAI", _FakeOpenAI)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _FakeHttp())
    monkeypatch.setattr(generation_module, "InworldClient", lambda *_: _EmptyVoiceProvider())
    monkeypatch.setattr(generation_module, "_resume_batches", resume)
    monkeypatch.setattr(generation_module, "_ensure_character_voice", ensure_voice)
    monkeypatch.setattr(generation_module, "_direct_workload", direct)
    monkeypatch.setattr(generation_module, "_synthesize_workload", synthesize)

    stale_failures = [
        GenerationFailureRecord(
            id=GenerationFailureRecord.id_for(stage, "aerie", "AERIE.DLG:npc:999:-"),
            stage=stage,
            voice_id="aerie",
            dialogue_line_id="AERIE.DLG:npc:999:-",
            error_type="RuntimeError",
            error="outside this run",
            failed_at="2026-08-27T10:03:00+00:00",
        )
        for stage in (
            GenerationFailureStage.DIALOGUE_DIRECTION,
            GenerationFailureStage.AUDIO_GENERATION,
        )
    ]
    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_failures(stale_failures)
    finally:
        store.close()

    failed = await generate(
        scenario_database,
        ["Aerie"],
        2,
        "openai-test",
        "inworld-test",
    )
    store = await GenerationStore.open(scenario_database)
    try:
        failures = await store.failures(["aerie"])
        await store.delete_failures([failure.id for failure in stale_failures])
    finally:
        store.close()

    recovered = await generate(
        scenario_database,
        ["Aerie"],
        2,
        "openai-test",
        "inworld-test",
    )
    store = await GenerationStore.open(scenario_database)
    try:
        recovered_failures = await store.failures(["aerie"])
    finally:
        store.close()

    assert failed.voice_creation_failures == 1
    assert (failed.dialogue_direction_failures, failed.audio_generation_failures) == (0, 0)
    assert recovered.voice_creation_failures == 0
    assert directed == ["aerie", "aerie"]
    assert synthesized == ["aerie"]
    assert [
        (failure.stage, failure.error)
        for failure in failures
        if failure.stage is GenerationFailureStage.VOICE_CREATION
    ] == [(GenerationFailureStage.VOICE_CREATION, "voice design unavailable")]
    assert recovered_failures == []


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
                id="voice-design-response",
                usage=SimpleNamespace(
                    input_tokens=120,
                    input_tokens_details=SimpleNamespace(cached_tokens=80, cache_write_tokens=0),
                    output_tokens=40,
                    output_tokens_details=SimpleNamespace(reasoning_tokens=30),
                    total_tokens=160,
                ),
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
        return SimpleNamespace(
            id="direction-response",
            usage=SimpleNamespace(
                input_tokens=120,
                input_tokens_details=SimpleNamespace(cached_tokens=80, cache_write_tokens=0),
                output_tokens=40,
                output_tokens_details=SimpleNamespace(reasoning_tokens=30),
                total_tokens=160,
            ),
            output_parsed=DirectionPlan(
                result=(
                    NarratorDirectedDialogue(
                        speaker="narrator",
                        directed_dialogue="[narrate calmly] The road grows quiet as night falls.",
                    )
                    if "A quest for <DAYANDMONTH>." in content
                    else CharacterDirectedDialogue(
                        speaker="character",
                        directed_dialogue="[warmly] Hello.",
                    )
                )
            ),
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


class _MixedBatchProvider:
    def __init__(self, custom_ids: list[str]) -> None:
        self.custom_ids = custom_ids
        self.recovered = False
        self.downloads: list[str] = []

    async def poll_operation(self, name: str) -> BatchOperation:
        return BatchOperation(
            name=name,
            done=True,
            response=BatchOperationResponse(
                results_uri="https://signed.example/results",
                expire_time=datetime(2026, 9, 3, tzinfo=UTC),
            ),
        )

    async def download_results(self, _results_uri: str) -> BatchResults:
        if self.recovered:
            return BatchResults(
                results=[
                    BatchResult(custom_id=custom_id, audio_uri=f"audio:{index}")
                    for index, custom_id in enumerate(self.custom_ids)
                ]
            )
        return BatchResults(
            results=[
                BatchResult(
                    custom_id=self.custom_ids[0],
                    error=BatchItemError(code="bad-input", message="text was rejected"),
                ),
                BatchResult(custom_id=self.custom_ids[1]),
                BatchResult(custom_id=self.custom_ids[2], audio_uri="audio:broken"),
                BatchResult(custom_id=self.custom_ids[3], audio_uri="audio:good"),
            ],
            failed_items=3,
        )

    async def download_audio(self, audio_uri: str) -> bytes:
        self.downloads.append(audio_uri)
        if not self.recovered and audio_uri == "audio:broken":
            raise RuntimeError("signed audio download failed")
        return audio_uri.encode()


class _RecordingBatchProvider:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    async def submit_batch(self, items: list[BatchSynthesisItem]) -> BatchOperation:
        self.submitted.extend(item.custom_id for item in items)
        return BatchOperation(name="workspaces/test/ttsBatchJobs/new/operations/op")


@pytest.mark.anyio
async def test_batch_scheduler_respects_provider_concurrency() -> None:
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


@pytest.mark.anyio
async def test_concurrent_runner_lets_started_work_finish_before_raising() -> None:
    sibling_started = asyncio.Event()
    release_sibling = asyncio.Event()
    sibling_finished = False

    async def process(item: str) -> None:
        nonlocal sibling_finished
        if item == "sibling":
            sibling_started.set()
            await release_sibling.wait()
            sibling_finished = True
            return
        await sibling_started.wait()
        raise RuntimeError("unexpected local failure")

    running = asyncio.create_task(
        generation_module._run_concurrently(
            ["failure", "sibling"],
            process,
            asyncio.Semaphore(2),
        )
    )
    await sibling_started.wait()
    await asyncio.sleep(0)
    assert not running.done()

    release_sibling.set()
    with pytest.raises(RuntimeError, match="unexpected local failure"):
        await running
    assert sibling_finished


@pytest.mark.anyio
async def test_provider_voice_is_reused_when_local_generation_is_missing(
    scenario_database: Path,
) -> None:
    store = await GenerationStore.open(scenario_database)
    try:
        provider = _ReusableVoiceProvider()
        record = await generation_module._reuse_existing_voice(
            store,
            generation_module._provider_voice_catalog(await provider.list_voices()),
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


def test_provider_voice_catalog_rejects_case_insensitive_name_duplicates() -> None:
    existing = PublishedVoice(
        name="workspaces/test/voices/aerie-existing",
        voiceId="aerie-existing",
        displayName="Aerie",
        description="An existing carefully designed voice.",
        langCode="EN_GB",
    )
    duplicate = existing.model_copy(
        update={
            "name": "workspaces/test/voices/aerie-copy",
            "voice_id": "aerie-copy",
            "display_name": "aERIE",
        }
    )

    with pytest.raises(AssertionError, match="multiple reusable Inworld voices"):
        generation_module._provider_voice_catalog([existing, duplicate])


@pytest.mark.anyio
async def test_failed_provider_batch_is_persisted_without_audio(
    scenario_database: Path,
) -> None:
    line_id = "AERIE.DLG:npc:0:-"
    direction = DirectedLineRecord(
        id=DirectedLineRecord.id_for("aerie", line_id),
        voice_id="aerie",
        dialogue_line_id=line_id,
        character=CharacterDirection(directed_dialogue="[firmly] Not now."),
        created_at="2026-08-27T12:00:00+00:00",
    )
    batch = TtsBatchRecord(
        operation_name="workspaces/test/ttsBatchJobs/failed/operations/op",
        custom_ids=[direction.id],
        status=RunStatus.RUNNING,
        started_at="2026-08-27T12:00:00+00:00",
    )
    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_directed_lines([direction])
        await store.upsert_batches([batch])
        await generation_module._resume_batches(
            store,
            cast(InworldClient, _FailedBatchProvider()),
            asyncio.Semaphore(75),
        )
        persisted = {record.operation_name: record for record in await store.batches()}[
            batch.operation_name
        ]
        audio = await store.generated_audio()
        failures = await store.failures(["aerie"])
    finally:
        store.close()

    assert audio == []
    assert persisted.status is RunStatus.FAILED
    assert persisted.error == "provider synthesis failed"
    assert persisted.completed_at is not None
    assert [(failure.stage, failure.dialogue_line_id) for failure in failures] == [
        (GenerationFailureStage.AUDIO_GENERATION, line_id)
    ]


@pytest.mark.anyio
async def test_synthesis_skips_lines_owned_by_running_batches(
    scenario_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = await PipelineReader.open(scenario_database)
    store = await GenerationStore.open(scenario_database)
    try:
        workload = (await load_workloads(reader, ["Aerie"], 2))[0]
        directions = [
            DirectedLineRecord(
                id=DirectedLineRecord.id_for(workload.voice.voice_id, line.id),
                voice_id=workload.voice.voice_id,
                dialogue_line_id=line.id,
                character=CharacterDirection(directed_dialogue="[clearly] Ready."),
                created_at="2026-08-27T12:00:00+00:00",
            )
            for line in workload.lines
        ]
        voice = GeneratedVoiceRecord(
            voice_id=workload.voice.voice_id,
            inworld_voice_id="voice-aerie",
            description=VoiceDescription(
                text="A warm, clear voice with steady delivery.",
                language_code="en-GB",
            ),
            created_at="2026-08-27T12:00:00+00:00",
        )
        running = TtsBatchRecord(
            operation_name="workspaces/test/ttsBatchJobs/running/operations/op",
            custom_ids=[directions[0].id],
            status=RunStatus.RUNNING,
            started_at="2026-08-27T12:00:00+00:00",
        )
        await store.upsert_generated_voices([voice])
        await store.upsert_directed_lines(directions)
        await store.upsert_batches([running])

        async def complete(*_: object) -> None:
            return None

        async def narrator() -> GeneratedVoiceRecord:
            raise AssertionError("character-only workload must not request the narrator")

        provider = _RecordingBatchProvider()
        monkeypatch.setattr(generation_module, "_complete_batch", complete)
        await generation_module._synthesize_workload(
            store,
            cast(InworldClient, provider),
            workload,
            narrator,
            asyncio.Semaphore(1),
        )
    finally:
        reader.close()
        store.close()

    assert provider.submitted == [directions[1].id]


@pytest.mark.anyio
async def test_mixed_tts_batch_keeps_good_audio_and_clears_failures_on_retry(
    scenario_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directions = [
        DirectedLineRecord(
            id=DirectedLineRecord.id_for("aerie", f"AERIE.DLG:npc:{state}:-"),
            voice_id="aerie",
            dialogue_line_id=f"AERIE.DLG:npc:{state}:-",
            character=CharacterDirection(directed_dialogue=f"[clearly] Line {state}."),
            created_at="2026-08-27T12:00:00+00:00",
        )
        for state in range(4)
    ]
    batch = TtsBatchRecord(
        operation_name="workspaces/test/ttsBatchJobs/mixed/operations/op",
        custom_ids=[direction.id for direction in directions],
        status=RunStatus.RUNNING,
        started_at="2026-08-27T12:00:00+00:00",
    )
    voice = GeneratedVoiceRecord(
        voice_id="aerie",
        inworld_voice_id="voice-aerie",
        description=VoiceDescription(
            text="A warm, clear voice with steady delivery.",
            language_code="en-GB",
        ),
        created_at="2026-08-27T12:00:00+00:00",
    )
    provider = _MixedBatchProvider(batch.custom_ids)
    monkeypatch.setattr(
        generation_module,
        "encode_game_audio",
        lambda source: b"OggS" + source,
    )
    monkeypatch.setattr(generation_module, "AUDIO_WRITE_BATCH_SIZE", 1)

    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_generated_voices([voice])
        await store.upsert_directed_lines(directions)
        await store.upsert_batches([batch])
        direction_map = {direction.id: direction for direction in directions}
        await generation_module._complete_batch(
            store,
            cast(InworldClient, provider),
            batch,
            direction_map,
            {voice.voice_id: voice},
        )
        partial_audio = await store.generated_audio(["aerie"])
        original_audio = partial_audio[0]
        failures = await store.failures(["aerie"])
        failed_batch = (await store.batches())[0]

        provider.recovered = True
        await generation_module._complete_batch(
            store,
            cast(InworldClient, provider),
            batch,
            direction_map,
            {voice.voice_id: voice},
        )
        recovered_audio = await store.generated_audio(["aerie"])
        recovered_failures = await store.failures(["aerie"])
        recovered_batch = (await store.batches())[0]
    finally:
        store.close()

    assert [audio.dialogue_line_id for audio in partial_audio] == [directions[3].dialogue_line_id]
    assert {
        (failure.dialogue_line_id, failure.error_code, failure.error) for failure in failures
    } == {
        (directions[0].dialogue_line_id, "bad-input", "text was rejected"),
        (
            directions[1].dialogue_line_id,
            None,
            "Inworld returned neither audio nor an error for this item",
        ),
        (directions[2].dialogue_line_id, None, "signed audio download failed"),
    }
    assert failed_batch.status is RunStatus.COMPLETE_WITH_ERRORS
    assert {audio.dialogue_line_id for audio in recovered_audio} == {
        direction.dialogue_line_id for direction in directions
    }
    assert (
        next(audio for audio in recovered_audio if audio.id == original_audio.id) == original_audio
    )
    assert provider.downloads.count("audio:good") == 1
    assert recovered_failures == []
    assert recovered_batch.status is RunStatus.COMPLETE


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
    read_generated_audio = GenerationStore.generated_audio

    async def reject_blob_scan(*_: object, **__: object) -> None:
        raise AssertionError("generation must use blob-free audio identities")

    monkeypatch.setattr(GenerationStore, "generated_audio", reject_blob_scan)
    _FakeResponses.calls.clear()

    first_summary = await generate(
        scenario_database,
        ["Aerie"],
        2,
        "openai-test",
        "inworld-test",
    )
    assert voice_list_requests == 1
    store = await GenerationStore.open(scenario_database)
    try:
        first_voices = await store.generated_voices()
        first_recordings = await read_generated_audio(store, ["aerie"])
    finally:
        store.close()

    resumed_summary = await generate(
        scenario_database,
        ["Aerie"],
        2,
        "openai-test",
        "inworld-test",
    )
    assert voice_list_requests == 2
    second_summary = await generate(
        scenario_database,
        ["Aerie"],
        2,
        "openai-test",
        "inworld-test",
        recreate_voices=True,
    )
    assert voice_list_requests == 3
    store = await GenerationStore.open(scenario_database)
    try:
        voices = await store.generated_voices()
        directions = await store.directed_lines(["aerie"])
        recordings = await read_generated_audio(store, ["aerie"])
        batches = await store.batches()
    finally:
        store.close()

    expected_summary = {
        "voices": 1,
        "selected_lines": 2,
        "directed_lines": 2,
        "generated_audio": 2,
        "voice_creation_failures": 0,
        "dialogue_direction_failures": 0,
        "audio_generation_failures": 0,
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
        call for call in _FakeResponses.calls if call["text_format"] is DirectionPlan
    ]
    assert len(voice_calls) == 2
    assert len(direction_calls) == 4
    assert all(
        call["tools"] == [{"type": "web_search"}] and call["tool_choice"] == "required"
        for call in voice_calls
    )
    assert all(call["tools"] == [] and call["tool_choice"] == "none" for call in direction_calls)
    direction_prompts = [
        cast(str, cast(list[dict[str, object]], call["input"])[1]["content"])
        for call in direction_calls
    ]
    assert all(prompt.count("<requested_item>") == 1 for prompt in direction_prompts)
    assert any(
        "Previous NPC/scene line: Hello." in prompt and "Player response: Hi." in prompt
        for prompt in direction_prompts
    )
