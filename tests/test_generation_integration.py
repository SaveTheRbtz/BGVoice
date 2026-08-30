"""End-to-end generation through provider HTTP boundaries and mod export."""

from pathlib import Path

import httpx
import pytest

import bgvoice.generation as generation_module
from bgvoice.database import PipelineDatabase
from bgvoice.generation import generate
from bgvoice.generation_ai import DirectionPlan, VoiceDesignPlan
from bgvoice.generation_store import GenerationStore
from bgvoice.mod_export import export_mod
from bgvoice.model_types import ProviderGender, VoiceProfileKind
from bgvoice.storage_records import ExtractionRunRecord, VoiceResourceRecord
from tests.generation_fakes import FakeOpenAI, FakeResponses, InworldService
from tests.scenarios import rows


def provider_fakes(monkeypatch: pytest.MonkeyPatch) -> InworldService:
    provider = InworldService()
    transport = httpx.MockTransport(provider.handle)
    client_type = httpx.AsyncClient
    monkeypatch.setattr(generation_module, "AsyncOpenAI", FakeOpenAI)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client_type(transport=transport))
    return provider


def qualify_aerie_voice(database_path: Path) -> str:
    voice = next(
        row
        for row in rows(database_path, "voice_resources", VoiceResourceRecord)
        if row.voice_id == "aerie"
    )
    voice_id = "aerie~g=female"
    qualified = voice.model_copy(
        update={
            "key": VoiceResourceRecord.key_for(voice.run_id, voice_id),
            "voice_id": voice_id,
            "family_id": "aerie",
            "gender": ProviderGender.FEMALE,
            "display_name": "Aerie · Female",
        }
    )
    PipelineDatabase(database_path)._replace(
        "voice_resources",
        "key",
        VoiceResourceRecord,
        [qualified],
    )
    return voice_id


@pytest.mark.anyio
@pytest.mark.integration
async def test_generation_runs_from_voice_design_through_game_audio(
    scenario_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = provider_fakes(monkeypatch)
    monkeypatch.setattr(generation_module, "AUDIO_WRITE_BATCH_SIZE", 1)

    read_generated_audio = GenerationStore.generated_audio

    async def reject_blob_scan(*_: object, **__: object) -> None:
        raise AssertionError("generation must use blob-free audio identities")

    monkeypatch.setattr(GenerationStore, "generated_audio", reject_blob_scan)
    FakeResponses.calls.clear()

    first_summary = await generate(
        scenario_database,
        ["Aerie"],
        2,
        "openai-test",
        "inworld-test",
        generic_max_lines=0,
    )
    assert provider.voice_list_requests == 1
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
        generic_max_lines=0,
    )
    assert provider.voice_list_requests == 2
    second_summary = await generate(
        scenario_database,
        ["Aerie"],
        2,
        "openai-test",
        "inworld-test",
        recreate_voices=True,
        generic_max_lines=0,
    )
    assert provider.voice_list_requests == 3
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
    assert provider.deleted_voice_ids == [first_character_voice_id]
    assert narrator_voice_id in provider.published
    assert provider.published_names == ["Aerie", "Narrator", "Aerie"]
    assert provider.voice_list_requests == 3
    assert sum(call["text_format"] is VoiceDesignPlan for call in FakeResponses.calls) == 2
    assert sum(call["text_format"] is DirectionPlan for call in FakeResponses.calls) == 2
    assert {record.inworld_voice_id for record in recordings} == {
        voices["aerie"].inworld_voice_id,
        narrator_voice_id,
    }

    game_roots = {
        Path(run.game_root)
        for run in rows(scenario_database, "extraction_runs", ExtractionRunRecord)
    }
    assert len(game_roots) == 1
    game_root = game_roots.pop()
    game_root.mkdir(parents=True, exist_ok=True)
    (game_root / "setup-eet.exe").write_bytes(b"fake WeiDU executable")

    exported = await export_mod(scenario_database, tmp_path / "generated-mod", version="test")
    assert exported.generated_lines == 2
    assert exported.audio_files == 2
    assert exported.voice_catalogs == 1
    assert len(list((tmp_path / "generated-mod" / "bgvoice" / "audio").glob("*.wav"))) == 2


@pytest.mark.anyio
@pytest.mark.integration
async def test_generate_routes_sparse_gender_variant_through_shared_profile(
    scenario_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    voice_id = qualify_aerie_voice(scenario_database)
    provider = provider_fakes(monkeypatch)
    FakeResponses.calls.clear()

    first = await generate(
        scenario_database,
        ["Aerie"],
        1,
        "openai-test",
        "inworld-test",
        generic_max_lines=5,
    )
    resumed = await generate(
        scenario_database,
        ["Aerie"],
        1,
        "openai-test",
        "inworld-test",
        generic_max_lines=5,
    )

    store = await GenerationStore.open(scenario_database)
    try:
        profiles = await store.voice_profiles()
        assignments = await store.voice_generations([voice_id])
        directions = await store.directed_lines([voice_id])
        audio = await store.generated_audio([voice_id])
    finally:
        store.close()

    generic_id = "generic:gender:female:race:2"
    assert first == resumed
    assert first.model_dump() == {
        "voices": 1,
        "selected_lines": 1,
        "directed_lines": 1,
        "generated_audio": 1,
        "voice_creation_failures": 0,
        "dialogue_direction_failures": 0,
        "audio_generation_failures": 0,
    }
    assert profiles[generic_id].kind is VoiceProfileKind.GENERIC
    assert profiles[generic_id].gender is ProviderGender.FEMALE
    assert voice_id not in profiles
    assert assignments[voice_id].profile_id == generic_id
    assert len(directions) == len(audio) == 1
    assert audio[0].inworld_voice_id == profiles[generic_id].inworld_voice_id
    assert audio[0].audio.startswith(b"OggS")
    assert provider.published_names == ["BGVoice Generic · Female · Elf"]
    assert provider.batch_count == 1
    assert sum(call["text_format"] is VoiceDesignPlan for call in FakeResponses.calls) == 1
    assert sum(call["text_format"] is DirectionPlan for call in FakeResponses.calls) == 1
