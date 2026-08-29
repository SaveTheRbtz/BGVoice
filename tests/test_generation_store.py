"""Behavioral tests for durable generation state."""

from datetime import timedelta
from pathlib import Path

import pytest
from lancedb.table import AsyncTable
from pydantic import ValidationError

from bgvoice.generation_store import GenerationStore
from bgvoice.model_types import GenerationFailureStage, RunStatus
from bgvoice.storage_records import (
    CharacterDirection,
    DirectedLineRecord,
    GeneratedAudioRecord,
    GeneratedVoiceRecord,
    GenerationFailureRecord,
    NarratorDirection,
    TtsBatchRecord,
    VoiceDescription,
)


@pytest.mark.anyio
async def test_generated_assets_round_trip_upsert_filter_and_delete(
    scenario_database: Path,
) -> None:
    store = await GenerationStore.open(scenario_database)
    try:
        imoen_voice = GeneratedVoiceRecord(
            voice_id="imoen",
            inworld_voice_id="voice-imoen-v1",
            description=VoiceDescription(
                text="A bright, warm young adventurer with quick, playful delivery.",
                language_code="en-GB",
            ),
            created_at="2026-08-27T10:00:00+00:00",
        )
        gorion_voice = GeneratedVoiceRecord(
            voice_id="gorion",
            inworld_voice_id="voice-gorion",
            description=VoiceDescription(
                text="A calm, learned older mentor with measured and reassuring delivery.",
                language_code="en-GB",
            ),
            created_at="2026-08-27T10:00:00+00:00",
        )
        updated_imoen = imoen_voice.model_copy(update={"inworld_voice_id": "voice-imoen-v2"})
        await store.upsert_generated_voices([imoen_voice, gorion_voice])
        await store.upsert_generated_voices([updated_imoen])

        line_id = "IMOEN2J.DLG:npc:0:-"
        imoen_line = DirectedLineRecord(
            id=DirectedLineRecord.id_for("imoen", line_id),
            voice_id="imoen",
            dialogue_line_id=line_id,
            character=CharacterDirection(directed_dialogue="[cheerfully] I am ready."),
            narrator=None,
            created_at="2026-08-27T10:01:00+00:00",
        )
        gorion_line = DirectedLineRecord(
            id=DirectedLineRecord.id_for("gorion", line_id),
            voice_id="gorion",
            dialogue_line_id=line_id,
            character=None,
            narrator=NarratorDirection(directed_dialogue="[quietly] The road awaits."),
            created_at="2026-08-27T10:01:00+00:00",
        )
        await store.upsert_directed_lines([imoen_line, gorion_line])
        await store.upsert_directed_lines([imoen_line])

        imoen_audio = GeneratedAudioRecord(
            id=imoen_line.id,
            voice_id="imoen",
            dialogue_line_id=line_id,
            inworld_voice_id="voice-imoen-v2",
            batch_operation_name="operations/batch-1",
            audio=b"OggSvoice audio",
            created_at="2026-08-27T10:02:00+00:00",
        )
        gorion_audio = GeneratedAudioRecord(
            id=gorion_line.id,
            voice_id="gorion",
            dialogue_line_id=line_id,
            inworld_voice_id="voice-gorion",
            batch_operation_name="operations/batch-1",
            audio=b"OggSnarration",
            created_at="2026-08-27T10:02:00+00:00",
        )
        await store.upsert_generated_audio([imoen_audio, gorion_audio])
        await store.upsert_generated_audio([imoen_audio])

        imoen_failure = GenerationFailureRecord(
            id=GenerationFailureRecord.id_for(
                GenerationFailureStage.DIALOGUE_DIRECTION,
                "imoen",
                line_id,
            ),
            stage=GenerationFailureStage.DIALOGUE_DIRECTION,
            voice_id="imoen",
            dialogue_line_id=line_id,
            error_type="DirectionError",
            error_code=None,
            error="invalid structured output",
            failed_at="2026-08-27T10:03:00+00:00",
        )
        gorion_failure = GenerationFailureRecord(
            id=GenerationFailureRecord.id_for(
                GenerationFailureStage.VOICE_CREATION,
                "gorion",
            ),
            stage=GenerationFailureStage.VOICE_CREATION,
            voice_id="gorion",
            dialogue_line_id=None,
            error_type="HTTPStatusError",
            error_code="429",
            error="provider rate limit",
            failed_at="2026-08-27T10:03:00+00:00",
        )
        updated_imoen_failure = imoen_failure.model_copy(
            update={"error": "source wrappers remained in the directed line"}
        )
        await store.upsert_failures([imoen_failure, gorion_failure])
        await store.upsert_failures([updated_imoen_failure])

        voices = await store.generated_voices()
        assert voices["imoen"].description.language_code == "en-GB"
        assert voices["imoen"].inworld_voice_id == "voice-imoen-v2"
        assert set(await store.generated_voices(["imoen"])) == {"imoen"}
        assert await store.generated_voices([]) == {}
        assert await store.generated_voice("imoen") == updated_imoen
        assert await store.generated_voice("unknown") is None
        stored_directions = await store.directed_lines()
        assert {line.id for line in stored_directions if line.character is not None} == {
            imoen_line.id
        }
        assert {line.id for line in stored_directions if line.narrator is not None} == {
            gorion_line.id
        }
        assert {line.id for line in await store.directed_lines(["imoen"])} == {imoen_line.id}
        assert await store.directed_lines([]) == []
        assert (await store.audio(imoen_audio.id)) == imoen_audio
        assert (await store.generated_audio(["imoen"]))[0].audio == imoen_audio.audio
        identities = await store.generated_audio_identities(["imoen"])
        assert [identity.model_dump() for identity in identities] == [
            {
                "id": imoen_audio.id,
                "voice_id": "imoen",
                "dialogue_line_id": line_id,
            }
        ]
        assert await store.generated_audio_identities([]) == []
        await store.upsert_directed_lines([])
        assert {audio.id for audio in await store.generated_audio()} == {
            imoen_audio.id,
            gorion_audio.id,
        }
        assert await store.failures(["imoen"]) == [updated_imoen_failure]
        assert await store.failures([]) == []
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
        assert {line.voice_id for line in await store.directed_lines()} == {"gorion"}
        assert {audio.voice_id for audio in await store.generated_audio()} == {"gorion"}
        assert await store.failures() == [gorion_failure]
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
            "generated_voices",
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
        running = TtsBatchRecord(
            operation_name="operations/batch-1",
            custom_ids=["d-first", "d-second"],
            status=RunStatus.RUNNING,
            started_at="2026-08-27T10:00:00+00:00",
        )
        await store.upsert_batches([running])
        assert await store.running_batches() == [running]

        complete = TtsBatchRecord(
            operation_name=running.operation_name,
            custom_ids=running.custom_ids,
            status=RunStatus.COMPLETE,
            started_at=running.started_at,
            completed_at="2026-08-27T10:03:00+00:00",
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
