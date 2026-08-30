"""Behavioral tests for durable generation state."""

from datetime import timedelta
from pathlib import Path

import pytest
from lancedb.table import AsyncTable
from pydantic import ValidationError

from bgvoice.generation_store import GenerationStore
from bgvoice.model_types import (
    GenerationFailureStage,
    ProviderGender,
    RaceId,
    RunStatus,
    VoiceProfileKind,
)
from bgvoice.storage_records import (
    GenerationFailureRecord,
    TtsBatchRecord,
)
from tests.factories import (
    make_direction,
    make_generated_audio,
    make_generation_failure,
    make_tts_batch,
    make_voice_generation,
    make_voice_profile,
)


@pytest.mark.anyio
async def test_generated_state_upserts_idempotently_and_deletes_at_ownership_boundaries(
    scenario_database: Path,
) -> None:
    store = await GenerationStore.open(scenario_database)
    try:
        imoen_profile = make_voice_profile(
            "imoen",
            inworld_voice_id="voice-imoen-v1",
            description="A bright, warm young adventurer with quick, playful delivery.",
        )
        gorion_profile = make_voice_profile(
            "gorion",
            description="A calm, learned older mentor with measured and reassuring delivery.",
        )
        updated_imoen = imoen_profile.model_copy(update={"inworld_voice_id": "voice-imoen-v2"})
        generations = [make_voice_generation("imoen"), make_voice_generation("gorion")]
        await store.upsert_voice_profiles([imoen_profile, gorion_profile])
        await store.upsert_voice_profiles([updated_imoen])
        await store.upsert_voice_generations(generations)

        line_id = "IMOEN2J.DLG:npc:0:-"
        imoen_line = make_direction(
            "imoen",
            line_id,
            directed_dialogue="[cheerfully] I am ready.",
        )
        gorion_line = make_direction(
            "gorion",
            line_id,
            directed_dialogue="[quietly] The road awaits.",
            narrator=True,
        )
        await store.upsert_directed_lines([imoen_line, gorion_line])
        await store.upsert_directed_lines([imoen_line])

        imoen_audio = make_generated_audio(
            imoen_line,
            inworld_voice_id="voice-imoen-v2",
            operation_name="operations/batch-1",
            audio=b"OggSvoice audio",
        )
        gorion_audio = make_generated_audio(
            gorion_line,
            operation_name="operations/batch-1",
            audio=b"OggSnarration",
        )
        await store.upsert_generated_audio([imoen_audio, gorion_audio])
        await store.upsert_generated_audio([imoen_audio])

        imoen_failure = make_generation_failure(
            GenerationFailureStage.DIALOGUE_DIRECTION,
            "imoen",
            line_id,
            error_type="DirectionError",
            error="invalid structured output",
        )
        gorion_failure = make_generation_failure(
            GenerationFailureStage.VOICE_CREATION,
            "gorion",
            error_type="HTTPStatusError",
            error_code="429",
            error="provider rate limit",
        )
        updated_imoen_failure = imoen_failure.model_copy(
            update={"error": "source wrappers remained in the directed line"}
        )
        await store.upsert_failures([imoen_failure, gorion_failure])
        await store.upsert_failures([updated_imoen_failure])

        assert await store.generated_voices() == {
            "imoen": updated_imoen,
            "gorion": gorion_profile,
        }
        assert {line.id: line for line in await store.directed_lines()} == {
            imoen_line.id: imoen_line,
            gorion_line.id: gorion_line,
        }
        assert {audio.id: audio for audio in await store.generated_audio()} == {
            imoen_audio.id: imoen_audio,
            gorion_audio.id: gorion_audio,
        }
        assert await store.failures(["imoen"]) == [updated_imoen_failure]
        await store.delete_failures([gorion_failure.id])
        assert await store.failures() == [updated_imoen_failure]
        await store.upsert_failures([gorion_failure])

        await store.delete_line_generation([imoen_line.id])
        assert {line.id for line in await store.directed_lines()} == {gorion_line.id}
        assert {audio.id for audio in await store.generated_audio()} == {gorion_audio.id}
        assert set(await store.generated_voices()) == {"imoen", "gorion"}
        await store.upsert_directed_lines([imoen_line])
        await store.upsert_generated_audio([imoen_audio])

        await store.delete_voice_generation("imoen")
        assert set(await store.generated_voices()) == {"gorion"}
        assert await store.voice_profile("imoen") == updated_imoen
        assert {line.voice_id for line in await store.directed_lines()} == {"imoen", "gorion"}
        assert {audio.voice_id for audio in await store.generated_audio()} == {"gorion"}
        assert await store.failures() == [gorion_failure]
        await store.delete_voice_profile("imoen")
        assert await store.voice_profile("imoen") is None
    finally:
        store.close()


@pytest.mark.anyio
async def test_logical_voices_share_one_provider_profile(scenario_database: Path) -> None:
    store = await GenerationStore.open(scenario_database)
    try:
        profile = make_voice_profile(
            "generic~g=male",
            inworld_voice_id="voice-generic-male",
            gender=ProviderGender.MALE,
            race_id=RaceId(1),
            kind=VoiceProfileKind.GENERIC,
        )
        assignments = [
            make_voice_generation("cobbler~g=male", profile.profile_id),
            make_voice_generation("servant~g=male", profile.profile_id),
        ]
        with pytest.raises(AssertionError, match="missing profiles"):
            await store.assign_voice(assignments[0])
        await store.upsert_voice_profiles([profile])
        for assignment in assignments:
            await store.assign_voice(assignment)

        assert await store.generated_voices() == {
            assignment.voice_id: profile for assignment in assignments
        }
        with pytest.raises(AssertionError, match="not exclusively"):
            await store.assert_exclusive_profile_assignment(
                profile.profile_id,
                assignments[0].voice_id,
            )
        with pytest.raises(AssertionError, match="still assigned"):
            await store.delete_voice_profile(profile.profile_id)

        cobbler = assignments[0].voice_id
        direction = make_direction(cobbler)
        audio = make_generated_audio(direction, inworld_voice_id=profile.inworld_voice_id)
        await store.upsert_directed_lines([direction])
        await store.upsert_generated_audio([audio])
        dedicated = make_voice_profile(cobbler)
        await store.upsert_voice_profiles([dedicated])
        await store.assign_voice(make_voice_generation(cobbler))

        assert await store.generated_voice(cobbler) == dedicated
        await store.assert_exclusive_profile_assignment(dedicated.profile_id, cobbler)
        with pytest.raises(AssertionError, match="already assigned"):
            await store.assign_voice(make_voice_generation("another-cobbler", dedicated.profile_id))
        assert await store.directed_lines([cobbler]) == [direction]
        assert await store.generated_audio([cobbler]) == []
        assert await store.generated_voice(assignments[1].voice_id) == profile
    finally:
        store.close()


@pytest.mark.anyio
async def test_optimize_vacuums_every_generation_table(
    scenario_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    optimized: list[tuple[str, dict[str, object]]] = []

    async def optimize(table: AsyncTable, **options: object) -> object:
        optimized.append((table.name, options))
        return object()

    monkeypatch.setattr(AsyncTable, "optimize", optimize)
    store = await GenerationStore.open(scenario_database)
    try:
        await store.optimize()
    finally:
        store.close()

    assert optimized == [
        (name, {"cleanup_older_than": timedelta(0)})
        for name in (
            "voice_profiles",
            "voice_generations",
            "directed_lines",
            "generated_audio",
            "tts_batches",
            "generation_failures",
        )
    ]


@pytest.mark.anyio
async def test_batch_upsert_advances_the_durable_lifecycle(scenario_database: Path) -> None:
    store = await GenerationStore.open(scenario_database)
    try:
        running = make_tts_batch(["d-first", "d-second"], operation_name="operations/batch-1")
        await store.upsert_batches([running])
        assert await store.running_batches() == [running]

        complete = running.model_copy(
            update={
                "status": RunStatus.COMPLETE,
                "completed_at": "2026-08-27T10:03:00+00:00",
            }
        )
        await store.upsert_batches([complete])
        assert await store.running_batches() == []
        assert await store.batches() == [complete]
    finally:
        store.close()


@pytest.mark.parametrize(
    ("stage", "dialogue_line_id"),
    [
        (GenerationFailureStage.VOICE_CREATION, "AERIE.DLG:npc:0:-"),
        (GenerationFailureStage.DIALOGUE_DIRECTION, None),
    ],
)
def test_generation_failures_enforce_stage_scope(
    stage: GenerationFailureStage,
    dialogue_line_id: str | None,
) -> None:
    with pytest.raises(ValidationError, match="direction and audio failures"):
        GenerationFailureRecord(
            id=GenerationFailureRecord.id_for(stage, "aerie", dialogue_line_id),
            stage=stage,
            voice_id="aerie",
            dialogue_line_id=dialogue_line_id,
            error_type="RuntimeError",
            error_code=None,
            error="failed",
            failed_at="2026-08-27T10:03:00+00:00",
        )


def test_generation_failures_enforce_deterministic_id() -> None:
    with pytest.raises(ValidationError, match="generation failure id"):
        GenerationFailureRecord(
            id="wrong",
            stage=GenerationFailureStage.VOICE_CREATION,
            voice_id="aerie",
            dialogue_line_id=None,
            error_type="RuntimeError",
            error_code=None,
            error="failed",
            failed_at="2026-08-27T10:03:00+00:00",
        )


@pytest.mark.parametrize("custom_ids", [[""], ["duplicate", "duplicate"]])
def test_tts_batches_reject_invalid_custom_ids(custom_ids: list[str]) -> None:
    with pytest.raises(ValidationError, match="TTS batch custom IDs"):
        TtsBatchRecord(
            operation_name="operations/batch-1",
            custom_ids=custom_ids,
            status=RunStatus.RUNNING,
            started_at="2026-08-27T10:00:00+00:00",
        )
