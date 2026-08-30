"""Voice-profile creation, reuse, migration, and replacement behavior."""

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

import bgvoice.generation as generation_module
from bgvoice.generation import generate, load_workloads
from bgvoice.generation_ai import DirectionPlan, VoiceDesignPlan
from bgvoice.generation_store import GenerationStore
from bgvoice.inworld import InworldClient, PublishedVoice
from bgvoice.model_types import ProviderGender, RaceId, VoiceProfileKind
from bgvoice.reader import PipelineReader
from tests.factories import (
    make_direction,
    make_generated_audio,
    make_voice_generation,
    make_voice_profile,
)
from tests.generation_fakes import (
    FakeHttp,
    FakeOpenAI,
    FakeResponses,
    VoiceProviderFake,
)


async def load_aerie_workload(
    database: Path,
    line_limit: int | None = 1,
) -> generation_module.VoiceWorkload:
    reader = await PipelineReader.open(database)
    try:
        return (await load_workloads(reader, ["Aerie"], line_limit))[0]
    finally:
        reader.close()


@pytest.mark.anyio
async def test_shared_generic_generation_is_persisted_and_idempotent(
    scenario_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = VoiceProviderFake()
    synthesized: list[list[str]] = []

    async def synthesize(
        _store: GenerationStore,
        _inworld: object,
        workloads: list[generation_module.VoiceWorkload],
        *_: object,
    ) -> None:
        synthesized.append([workload.voice.voice_id for workload in workloads])

    monkeypatch.setattr(generation_module, "AsyncOpenAI", FakeOpenAI)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: FakeHttp())
    monkeypatch.setattr(generation_module, "InworldClient", lambda *_: provider)
    monkeypatch.setattr(generation_module, "_synthesize_workloads", synthesize)
    FakeResponses.calls.clear()

    excluded = await generate(
        scenario_database,
        None,
        None,
        "openai-test",
        "inworld-test",
        generic_max_lines=1,
    )
    first = await generate(
        scenario_database,
        None,
        None,
        "openai-test",
        "inworld-test",
        generic_max_lines=5,
    )
    second = await generate(
        scenario_database,
        None,
        None,
        "openai-test",
        "inworld-test",
        generic_max_lines=5,
    )
    workload = await load_aerie_workload(scenario_database, None)
    store = await GenerationStore.open(scenario_database)
    try:
        copied_voice = workload.voice.model_copy(
            update={
                "key": workload.voice.key_for(workload.voice.run_id, "aerie-copy"),
                "voice_id": "aerie-copy",
                "display_name": "Aerie Copy",
            }
        )
        master = await store.voice_profile("generic:gender:female:race:2")
        assert master is not None
        await generation_module._ensure_character_voice(
            cast(Any, object()),
            cast(InworldClient, provider),
            store,
            replace(workload, voice=copied_voice),
            asyncio.Semaphore(1),
            {},
            recreate=False,
            generic_profile=asyncio.sleep(0, result=master),
        )
        voices = await store.generated_voices()
        profiles = await store.voice_profiles()
    finally:
        store.close()

    generic_id = "generic:gender:female:race:2"
    assert excluded.voices == 0
    assert first.directed_lines == second.directed_lines == 2
    assert provider.designs == provider.publishes == provider.updates == 1
    assert set(voices) == {"aerie", "aerie-copy"}
    assert generic_id in profiles
    assert {
        voices["aerie"].inworld_voice_id,
        voices["aerie-copy"].inworld_voice_id,
    } == {"generic-female-elf"}
    assert voices["aerie"].profile_id == voices["aerie-copy"].profile_id == generic_id
    assert sum(call["text_format"] is VoiceDesignPlan for call in FakeResponses.calls) == 1
    assert sum(call["text_format"] is DirectionPlan for call in FakeResponses.calls) == 2
    assert synthesized == [["aerie"], ["aerie"]]


@pytest.mark.anyio
async def test_provider_profile_is_reused_by_stable_tag_when_local_record_is_missing(
    scenario_database: Path,
) -> None:
    store = await GenerationStore.open(scenario_database)
    try:
        provider = VoiceProviderFake("aerie")
        catalog = generation_module._provider_voice_catalog(await provider.list_voices())
        record = await generation_module._reuse_existing_profile(
            store,
            catalog,
            "aerie",
            ProviderGender.FEMALE,
            None,
            VoiceProfileKind.DEDICATED,
        )
        persisted = await store.voice_profile("aerie")
    finally:
        store.close()

    assert set(catalog) == {generation_module.voice_profile_tag("aerie")}
    assert record == persisted
    assert record is not None
    assert record.inworld_voice_id == "aerie-existing"
    assert record.description.language_code == "en-GB"


@pytest.mark.anyio
async def test_existing_exclusive_dedicated_assignment_is_reused(
    scenario_database: Path,
) -> None:
    workload = await load_aerie_workload(scenario_database)
    store = await GenerationStore.open(scenario_database)
    try:
        profile = make_voice_profile(
            "existing-aerie",
            gender=ProviderGender.FEMALE,
            kind=VoiceProfileKind.DEDICATED,
        )
        await store.upsert_voice_profiles([profile])
        await store.upsert_voice_generations(
            [make_voice_generation(workload.voice.voice_id, profile.profile_id)]
        )
        result = await generation_module._ensure_character_voice(
            cast(Any, object()),
            cast(InworldClient, VoiceProviderFake("aerie")),
            store,
            workload,
            asyncio.Semaphore(1),
            {},
            recreate=False,
        )
    finally:
        store.close()

    assert result == profile


@pytest.mark.anyio
async def test_profile_identity_owned_by_another_voice_gets_a_dedicated_namespace(
    scenario_database: Path,
) -> None:
    workload = await load_aerie_workload(scenario_database)
    store = await GenerationStore.open(scenario_database)
    try:
        workload = replace(workload, voice=workload.voice.model_copy(update={"gender": None}))
        occupied = make_voice_profile(
            workload.voice.voice_id,
            gender=ProviderGender.FEMALE,
        )
        existing_owner = f"{workload.voice.voice_id}~g=female"
        await store.upsert_voice_profiles([occupied])
        await store.upsert_voice_generations(
            [make_voice_generation(existing_owner, occupied.profile_id)]
        )

        provider = VoiceProviderFake()
        generated = await generation_module._ensure_character_voice(
            cast(Any, FakeOpenAI(api_key="openai-test")),
            cast(InworldClient, provider),
            store,
            workload,
            asyncio.Semaphore(1),
            {},
            recreate=False,
        )
        assignments = await store.voice_generations()
    finally:
        store.close()

    assert generated.profile_id == f"dedicated:{workload.voice.voice_id}"
    assert generated.gender is ProviderGender.FEMALE
    assert assignments == {
        existing_owner: make_voice_generation(existing_owner, occupied.profile_id),
        workload.voice.voice_id: make_voice_generation(
            workload.voice.voice_id,
            generated.profile_id,
        ),
    }
    assert provider.designs == provider.publishes == 1


@pytest.mark.anyio
async def test_force_recreate_keeps_local_state_when_provider_delete_fails(
    scenario_database: Path,
) -> None:
    workload = await load_aerie_workload(scenario_database)
    store = await GenerationStore.open(scenario_database)
    try:
        voice_id = workload.voice.voice_id
        profile = make_voice_profile(voice_id, inworld_voice_id="voice-aerie")
        generation = make_voice_generation(voice_id)
        direction = make_direction(voice_id, workload.lines[0].id)
        audio = make_generated_audio(direction, inworld_voice_id=profile.inworld_voice_id)
        await store.upsert_voice_profiles([profile])
        await store.upsert_voice_generations([generation])
        await store.upsert_directed_lines([direction])
        await store.upsert_generated_audio([audio])

        def reject_delete(request: httpx.Request) -> httpx.Response:
            assert request.method == "DELETE"
            assert request.url.path.endswith(f"/{profile.inworld_voice_id}")
            return httpx.Response(503, text="provider unavailable")

        async with httpx.AsyncClient(transport=httpx.MockTransport(reject_delete)) as http:
            with pytest.raises(httpx.HTTPStatusError, match="503"):
                await generation_module._ensure_character_voice(
                    cast(Any, FakeOpenAI(api_key="openai-test")),
                    InworldClient(http, "inworld-test"),
                    store,
                    workload,
                    asyncio.Semaphore(1),
                    {},
                    recreate=True,
                )

        assert await store.voice_profile(profile.profile_id) == profile
        assert await store.voice_generations([voice_id]) == {voice_id: generation}
        assert await store.directed_lines([voice_id]) == [direction]
        assert await store.generated_audio([voice_id]) == [audio]
    finally:
        store.close()


@pytest.mark.anyio
async def test_dedicated_promotion_preserves_directions_and_invalidates_generic_audio(
    scenario_database: Path,
) -> None:
    workload = await load_aerie_workload(scenario_database)
    store = await GenerationStore.open(scenario_database)
    try:
        generic = make_voice_profile(
            workload.generic_profile.id,
            inworld_voice_id="generic-female-elf",
            gender=ProviderGender.FEMALE,
            race_id=RaceId(2),
            kind=VoiceProfileKind.GENERIC,
        )
        direction = make_direction(workload.voice.voice_id, workload.lines[0].id)
        await store.upsert_voice_profiles([generic])
        await store.upsert_voice_generations(
            [make_voice_generation(workload.voice.voice_id, generic.profile_id)]
        )
        await store.upsert_directed_lines([direction])
        await store.upsert_generated_audio(
            [make_generated_audio(direction, inworld_voice_id=generic.inworld_voice_id)]
        )

        provider = VoiceProviderFake("aerie")
        promoted = await generation_module._ensure_character_voice(
            cast(Any, object()),
            cast(InworldClient, provider),
            store,
            workload,
            asyncio.Semaphore(1),
            generation_module._provider_voice_catalog(await provider.list_voices()),
            recreate=False,
        )
        persisted = await store.generated_voice(workload.voice.voice_id)
        directions = await store.directed_lines([workload.voice.voice_id])
        audio = await store.generated_audio([workload.voice.voice_id])
        generic_still_shared = await store.voice_profile(generic.profile_id)
    finally:
        store.close()

    assert promoted == persisted
    assert promoted.kind is VoiceProfileKind.DEDICATED
    assert promoted.profile_id == workload.voice.voice_id
    assert directions == [direction]
    assert audio == []
    assert generic_still_shared == generic


def test_provider_voice_catalog_uses_stable_tags_not_display_names() -> None:
    voices = [
        PublishedVoice(
            name=f"workspaces/test/voices/{profile_id}",
            voiceId=f"provider-{profile_id}",
            displayName="Commoner",
            description="An existing carefully designed voice.",
            langCode="EN_GB",
            tags=["bgvoice", generation_module.voice_profile_tag(profile_id)],
        )
        for profile_id in ("commoner~g=male", "commoner~g=female")
    ]

    catalog = generation_module._provider_voice_catalog(voices)

    assert set(catalog) == {
        generation_module.voice_profile_tag("commoner~g=male"),
        generation_module.voice_profile_tag("commoner~g=female"),
    }
