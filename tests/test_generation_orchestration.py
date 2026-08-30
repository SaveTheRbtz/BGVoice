"""Direction retries and top-level generation failure isolation."""

import asyncio
from collections import Counter
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

import bgvoice.generation as generation_module
from bgvoice.dialogue_context import DialogueHistoryIndex
from bgvoice.generation import generate, load_workloads
from bgvoice.generation_ai import CharacterDirectedDialogue, DirectionPlan, DirectionSource
from bgvoice.generation_store import GenerationStore
from bgvoice.model_types import GenerationFailureStage
from bgvoice.reader import PipelineReader
from bgvoice.storage_records import DirectedLineRecord
from tests.factories import make_dialogue_line, make_generation_failure
from tests.generation_fakes import FakeHttp, FakeOpenAI, VoiceProviderFake


@pytest.mark.anyio
async def test_directions_continue_skip_persisted_and_clear_failures(
    scenario_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = await PipelineReader.open(scenario_database)
    store = await GenerationStore.open(scenario_database)
    try:
        selected = (await load_workloads(reader, ["Aerie"], 2))[0]
        invalid = make_dialogue_line("AERIE.DLG", 99, "x" * 2001)
        workload = generation_module.VoiceWorkload(
            voice=selected.voice,
            lines=(*selected.lines, invalid),
            ability_scores=selected.ability_scores,
            portrait_png=selected.portrait_png,
            generic_profile=selected.generic_profile,
            race_description=selected.race_description,
            class_description=selected.class_description,
            dialogue_samples=selected.dialogue_samples,
        )
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
    assert {
        (failure.stage, failure.dialogue_line_id, failure.error_type) for failure in failures
    } == {
        (GenerationFailureStage.DIALOGUE_DIRECTION, workload.lines[0].id, "RuntimeError"),
        (GenerationFailureStage.DIALOGUE_DIRECTION, invalid.id, "ValidationError"),
    }
    assert {line.dialogue_line_id for line in recovered_directions} == {
        line.id for line in selected.lines
    }
    assert (
        next(line for line in recovered_directions if line.dialogue_line_id == workload.lines[1].id)
        == directions[0]
    )
    assert [(failure.dialogue_line_id, failure.error_type) for failure in recovered_failures] == [
        (invalid.id, "ValidationError")
    ]


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
        workloads: list[generation_module.VoiceWorkload],
        *_: object,
    ) -> None:
        synthesized.append(workloads[0].voice.voice_id)

    async def resume(*_: object) -> None:
        return None

    monkeypatch.setattr(generation_module, "AsyncOpenAI", FakeOpenAI)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: FakeHttp())
    monkeypatch.setattr(generation_module, "InworldClient", lambda *_: VoiceProviderFake())
    monkeypatch.setattr(generation_module, "_resume_batches", resume)
    monkeypatch.setattr(generation_module, "_ensure_character_voice", ensure_voice)
    monkeypatch.setattr(generation_module, "_direct_workload", direct)
    monkeypatch.setattr(generation_module, "_synthesize_workloads", synthesize)

    stale_failures = [
        make_generation_failure(
            stage,
            line_id="AERIE.DLG:npc:999:-",
            error="outside this run",
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
