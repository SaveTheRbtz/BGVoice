"""Behavioral tests for durable generation state."""

from pathlib import Path

import pytest

from bgvoice.generation_store import GenerationStore
from bgvoice.model_types import RunStatus, Speaker
from bgvoice.storage_records import (
    DirectedLineRecord,
    GeneratedAudioRecord,
    GeneratedVoiceRecord,
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
            speaker=Speaker.CHARACTER,
            text="[cheerfully] I am ready.",
            created_at="2026-08-27T10:01:00+00:00",
        )
        gorion_line = DirectedLineRecord(
            id=DirectedLineRecord.id_for("gorion", line_id),
            voice_id="gorion",
            dialogue_line_id=line_id,
            speaker=Speaker.NARRATOR,
            text="[quietly] The road awaits.",
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

        voices = await store.generated_voices()
        assert voices["imoen"].description.language_code == "en-GB"
        assert voices["imoen"].inworld_voice_id == "voice-imoen-v2"
        assert await store.generated_voice("imoen") == updated_imoen
        assert await store.generated_voice("unknown") is None
        assert {line.id for line in await store.directed_lines(["imoen"])} == {imoen_line.id}
        assert await store.directed_lines([]) == []
        assert (await store.audio(imoen_audio.id)) == imoen_audio
        assert (await store.generated_audio(["imoen"]))[0].audio == imoen_audio.audio

        await store.delete_audio([imoen_audio.id])
        await store.delete_audio([])
        await store.upsert_directed_lines([])
        assert await store.audio(imoen_audio.id) is None
        assert {audio.id for audio in await store.generated_audio()} == {gorion_audio.id}
    finally:
        store.close()


@pytest.mark.anyio
async def test_batch_upsert_advances_the_durable_lifecycle(scenario_database: Path) -> None:
    store = await GenerationStore.open(scenario_database)
    try:
        running = TtsBatchRecord(
            operation_name="operations/batch-1",
            status=RunStatus.RUNNING,
            started_at="2026-08-27T10:00:00+00:00",
        )
        await store.upsert_batches([running])
        assert await store.running_batches() == [running]

        complete = TtsBatchRecord(
            operation_name=running.operation_name,
            status=RunStatus.COMPLETE,
            started_at=running.started_at,
            completed_at="2026-08-27T10:03:00+00:00",
        )
        await store.upsert_batches([complete])
        assert await store.running_batches() == []
        assert await store.batches() == [complete]
    finally:
        store.close()
