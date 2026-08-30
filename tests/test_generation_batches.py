"""Concurrent TTS scheduling, persistence, and retry behavior."""

import asyncio
from pathlib import Path
from typing import Never, cast

import pytest

import bgvoice.generation as generation_module
from bgvoice.generation import load_workloads
from bgvoice.generation_store import GenerationStore
from bgvoice.inworld import InworldClient
from bgvoice.model_types import GenerationFailureStage, ProviderGender, RunStatus, VoiceProfileKind
from bgvoice.reader import PipelineReader
from tests.factories import (
    make_direction,
    make_tts_batch,
    make_voice_generation,
    make_voice_profile,
)
from tests.generation_fakes import (
    FailedBatchProvider,
    MixedBatchProvider,
    RecordingBatchProvider,
)


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
async def test_failed_provider_batch_is_persisted_without_audio(
    scenario_database: Path,
) -> None:
    line_id = "AERIE.DLG:npc:0:-"
    direction = make_direction(
        "aerie",
        line_id,
        directed_dialogue="[firmly] Not now.",
    )
    batch = make_tts_batch(
        [direction.id],
        operation_name="workspaces/test/ttsBatchJobs/failed/operations/op",
    )
    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_directed_lines([direction])
        await store.upsert_batches([batch])
        await generation_module._resume_batches(
            store,
            cast(InworldClient, FailedBatchProvider()),
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
async def test_synthesis_resolves_assigned_profile_and_skips_running_lines(
    scenario_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = await PipelineReader.open(scenario_database)
    store = await GenerationStore.open(scenario_database)
    try:
        workload = (await load_workloads(reader, ["Aerie"], 2))[0]
        directions = [make_direction(workload.voice.voice_id, line.id) for line in workload.lines]
        profile = make_voice_profile(
            "shared-female",
            inworld_voice_id="voice-aerie",
            description="A warm, clear voice with steady delivery.",
            gender=ProviderGender.FEMALE,
            kind=VoiceProfileKind.GENERIC,
        )
        running = make_tts_batch(
            [directions[0].id],
            operation_name="workspaces/test/ttsBatchJobs/running/operations/op",
        )
        await store.upsert_voice_profiles([profile])
        await store.upsert_voice_generations(
            [make_voice_generation(workload.voice.voice_id, profile.profile_id)]
        )
        await store.upsert_directed_lines(directions)
        await store.upsert_batches([running])

        async def complete(*_: object) -> None:
            return None

        async def narrator() -> Never:
            raise AssertionError("character-only workload must not request the narrator")

        provider = RecordingBatchProvider()
        monkeypatch.setattr(generation_module, "_complete_batch", complete)
        await generation_module._synthesize_workloads(
            store,
            cast(InworldClient, provider),
            [workload],
            narrator,
            asyncio.Semaphore(1),
            set(running.custom_ids),
        )
    finally:
        reader.close()
        store.close()

    assert [(item.custom_id, item.voice_id) for item in provider.submitted] == [
        (directions[1].id, "voice-aerie")
    ]


@pytest.mark.anyio
async def test_mixed_tts_batch_keeps_good_audio_and_clears_failures_on_retry(
    scenario_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directions = [
        make_direction(
            "aerie" if state % 2 == 0 else "imoen",
            f"AERIE.DLG:npc:{state}:-",
            directed_dialogue=f"[clearly] Line {state}.",
        )
        for state in range(4)
    ]
    batch = make_tts_batch(
        [direction.id for direction in directions],
        operation_name="workspaces/test/ttsBatchJobs/mixed/operations/op",
    )
    voices = {
        voice_id: make_voice_profile(
            voice_id,
            description="A warm, clear voice with steady delivery.",
        )
        for voice_id in ("aerie", "imoen")
    }
    provider = MixedBatchProvider(batch.custom_ids)
    monkeypatch.setattr(
        generation_module,
        "encode_game_audio",
        lambda source: b"OggS" + source,
    )
    monkeypatch.setattr(generation_module, "AUDIO_WRITE_BATCH_SIZE", 1)

    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_voice_profiles(list(voices.values()))
        await store.upsert_voice_generations(
            [make_voice_generation(voice_id) for voice_id in voices]
        )
        await store.upsert_directed_lines(directions)
        await store.upsert_batches([batch])
        direction_map = {direction.id: direction for direction in directions}
        await generation_module._complete_batch(
            store,
            cast(InworldClient, provider),
            batch,
            direction_map,
            voices,
        )
        partial_audio = await store.generated_audio()
        original_audio = partial_audio[0]
        failures = await store.failures()
        failed_batch = (await store.batches())[0]

        provider.recovered = True
        await generation_module._complete_batch(
            store,
            cast(InworldClient, provider),
            batch,
            direction_map,
            voices,
        )
        recovered_audio = await store.generated_audio()
        recovered_failures = await store.failures()
        recovered_batch = (await store.batches())[0]
    finally:
        store.close()

    assert [audio.dialogue_line_id for audio in partial_audio] == [directions[3].dialogue_line_id]
    assert {
        (failure.voice_id, failure.dialogue_line_id, failure.error_code, failure.error)
        for failure in failures
    } == {
        ("aerie", directions[0].dialogue_line_id, "bad-input", "text was rejected"),
        (
            "imoen",
            directions[1].dialogue_line_id,
            None,
            "Inworld returned neither audio nor an error for this item",
        ),
        ("aerie", directions[2].dialogue_line_id, None, "signed audio download failed"),
    }
    assert failed_batch.status is RunStatus.COMPLETE_WITH_ERRORS
    assert {
        (audio.voice_id, audio.dialogue_line_id, audio.inworld_voice_id)
        for audio in recovered_audio
    } == {
        (
            direction.voice_id,
            direction.dialogue_line_id,
            voices[direction.voice_id].inworld_voice_id,
        )
        for direction in directions
    }
    assert (
        next(audio for audio in recovered_audio if audio.id == original_audio.id) == original_audio
    )
    assert provider.downloads.count("audio:good") == 1
    assert recovered_failures == []
    assert recovered_batch.status is RunStatus.COMPLETE
