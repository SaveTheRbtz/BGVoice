"""Generation state follows the current attribution publication."""

from pathlib import Path

import pytest

from bgvoice.database import PipelineDatabase
from bgvoice.generation_store import GenerationStore
from bgvoice.model_types import (
    GenerationFailureStage,
    ProviderGender,
    RunStatus,
)
from bgvoice.storage_records import DialogueLineRecord, VoiceResourceRecord
from tests.factories import (
    make_direction,
    make_generated_audio,
    make_generation_failure,
    make_tts_batch,
    make_voice_generation,
    make_voice_profile,
)
from tests.scenarios import rows


@pytest.mark.anyio
@pytest.mark.integration
async def test_reconciliation_remaps_provider_and_prunes_stale_line_state(
    scenario_database: Path,
) -> None:
    lines = rows(scenario_database, "dialogue_lines", DialogueLineRecord)
    owned_line = next(row for row in lines if row.dialogue_resource_name == "AERIE.DLG")
    foreign_line = next(row for row in lines if row.dialogue_resource_name == "UNUSED.DLG")
    previous = next(
        row
        for row in rows(scenario_database, "voice_resources", VoiceResourceRecord)
        if row.voice_id == "aerie"
    )
    variant_id = "aerie~g=female"
    current = VoiceResourceRecord.model_validate(
        previous.model_dump()
        | {
            "key": VoiceResourceRecord.key_for(previous.run_id, variant_id),
            "voice_id": variant_id,
            "family_id": "aerie",
            "gender": ProviderGender.FEMALE,
        }
    )

    old_direction = make_direction("aerie", owned_line.id)
    kept_direction = make_direction(variant_id, owned_line.id)
    foreign_direction = make_direction(variant_id, foreign_line.id)
    kept_failure = make_generation_failure(
        GenerationFailureStage.DIALOGUE_DIRECTION,
        variant_id,
        owned_line.id,
    )
    stale_failures = [
        make_generation_failure(GenerationFailureStage.VOICE_CREATION, "aerie"),
        make_generation_failure(
            GenerationFailureStage.AUDIO_GENERATION,
            variant_id,
            foreign_line.id,
        ),
    ]
    history = make_tts_batch(
        [old_direction.id, kept_direction.id],
        operation_name="operations/completed-before-reattribution",
        status=RunStatus.COMPLETE,
    )

    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_voice_profiles(
            [make_voice_profile("aerie", gender=ProviderGender.FEMALE)]
        )
        await store.upsert_voice_generations([make_voice_generation("aerie")])
        await store.upsert_directed_lines([old_direction, kept_direction, foreign_direction])
        await store.upsert_generated_audio(
            [
                make_generated_audio(old_direction),
                make_generated_audio(kept_direction),
                make_generated_audio(foreign_direction),
            ]
        )
        await store.upsert_failures([kept_failure, *stale_failures])
        await store.upsert_batches([history])
    finally:
        store.close()

    PipelineDatabase(scenario_database)._reconcile_generation([current])

    store = await GenerationStore.open(scenario_database)
    try:
        assert await store.voice_generations() == {
            variant_id: make_voice_generation(variant_id, "aerie")
        }
        assert await store.directed_lines() == [kept_direction]
        audio = await store.generated_audio_identities()
        assert [(row.id, row.voice_id, row.dialogue_line_id) for row in audio] == [
            (kept_direction.id, variant_id, owned_line.id)
        ]
        assert await store.failures() == [kept_failure]
        assert await store.batches() == [history]
    finally:
        store.close()


@pytest.mark.anyio
@pytest.mark.integration
async def test_reconciliation_collapses_unsuffixed_dedicated_voice_into_neutral_variant(
    scenario_database: Path,
) -> None:
    previous = next(
        row
        for row in rows(scenario_database, "voice_resources", VoiceResourceRecord)
        if row.voice_id == "aerie"
    )
    neutral_id = "aerie~g=neutral"
    neutral = VoiceResourceRecord.model_validate(
        previous.model_dump()
        | {
            "key": VoiceResourceRecord.key_for(previous.run_id, neutral_id),
            "voice_id": neutral_id,
            "family_id": "aerie",
            "gender": ProviderGender.NEUTRAL,
        }
    )
    legacy_profile = make_voice_profile("aerie", gender=ProviderGender.FEMALE)

    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_voice_profiles([legacy_profile])
        await store.upsert_voice_generations([make_voice_generation("aerie")])
    finally:
        store.close()

    PipelineDatabase(scenario_database)._reconcile_generation([neutral])

    store = await GenerationStore.open(scenario_database)
    try:
        assert await store.voice_generations() == {
            neutral_id: make_voice_generation(neutral_id, legacy_profile.profile_id)
        }
        assert await store.voice_profile(legacy_profile.profile_id) == legacy_profile.model_copy(
            update={"gender": ProviderGender.NEUTRAL}
        )
    finally:
        store.close()


@pytest.mark.anyio
@pytest.mark.integration
async def test_reconciliation_leaves_redundant_unsuffixed_profile_orphaned(
    scenario_database: Path,
) -> None:
    previous = next(
        row
        for row in rows(scenario_database, "voice_resources", VoiceResourceRecord)
        if row.voice_id == "aerie"
    )
    neutral_id = "aerie~g=neutral"
    male_id = "aerie~g=male"
    neutral, male = [
        VoiceResourceRecord.model_validate(
            previous.model_dump()
            | {
                "key": VoiceResourceRecord.key_for(previous.run_id, voice_id),
                "voice_id": voice_id,
                "family_id": "aerie",
                "gender": gender,
            }
        )
        for voice_id, gender in (
            (neutral_id, ProviderGender.NEUTRAL),
            (male_id, ProviderGender.MALE),
        )
    ]
    legacy_profile = make_voice_profile("aerie", gender=ProviderGender.MALE)
    neutral_profile = make_voice_profile(neutral_id, gender=ProviderGender.NEUTRAL)
    neutral_assignment = make_voice_generation(neutral_id)

    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_voice_profiles([legacy_profile, neutral_profile])
        await store.upsert_voice_generations([make_voice_generation("aerie"), neutral_assignment])
    finally:
        store.close()

    PipelineDatabase(scenario_database)._reconcile_generation([neutral, male])

    store = await GenerationStore.open(scenario_database)
    try:
        assert await store.voice_generations() == {neutral_id: neutral_assignment}
        assert await store.voice_profile(legacy_profile.profile_id) == legacy_profile
        assert await store.profile_voice_ids(legacy_profile.profile_id) == set()
    finally:
        store.close()


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.parametrize("artifact", ["direction", "audio"])
async def test_reconciliation_refuses_to_orphan_running_tts_work(
    scenario_database: Path,
    artifact: str,
) -> None:
    line = next(
        row
        for row in rows(scenario_database, "dialogue_lines", DialogueLineRecord)
        if row.dialogue_resource_name == "AERIE.DLG"
    )
    previous = next(
        row
        for row in rows(scenario_database, "voice_resources", VoiceResourceRecord)
        if row.voice_id == "aerie"
    )
    current = VoiceResourceRecord.model_validate(
        previous.model_dump()
        | {
            "key": VoiceResourceRecord.key_for(previous.run_id, "aerie~g=neutral"),
            "voice_id": "aerie~g=neutral",
            "family_id": "aerie",
            "gender": ProviderGender.NEUTRAL,
        }
    )
    direction = make_direction("aerie", line.id)
    profile = make_voice_profile("aerie", gender=ProviderGender.FEMALE)
    assignment = make_voice_generation("aerie")
    batch = make_tts_batch([direction.id])

    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_voice_profiles([profile])
        await store.upsert_voice_generations([assignment])
        if artifact == "direction":
            await store.upsert_directed_lines([direction])
        else:
            await store.upsert_generated_audio([make_generated_audio(direction)])
        await store.upsert_batches([batch])
    finally:
        store.close()

    with pytest.raises(AssertionError, match="running TTS batches reference stale lines"):
        PipelineDatabase(scenario_database)._reconcile_generation([current])

    store = await GenerationStore.open(scenario_database)
    try:
        assert await store.voice_generations() == {"aerie": assignment}
        assert await store.directed_lines() == ([direction] if artifact == "direction" else [])
        assert [row.id for row in await store.generated_audio_identities()] == (
            [direction.id] if artifact == "audio" else []
        )
        assert await store.voice_profile(profile.profile_id) == profile
        assert await store.batches() == [batch]
    finally:
        store.close()
