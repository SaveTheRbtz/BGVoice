"""Resumable repair of audio created before the current encode policy."""

import hashlib
import math
import wave
from io import BytesIO
from pathlib import Path

import pytest

from bgvoice.audio_normalization import normalize_existing_audio
from bgvoice.game_audio import encode_game_audio
from bgvoice.generation_store import GenerationStore
from bgvoice.storage_records import DirectedLineRecord, GeneratedAudioRecord


@pytest.mark.anyio
async def test_existing_audio_is_normalized_once(
    scenario_database: Path,
    tmp_path: Path,
) -> None:
    source = BytesIO()
    with wave.open(source, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22_050)
        audio.writeframes(
            b"".join(
                int(0.05 * 32_767 * math.sin(2 * math.pi * 440 * index / 22_050)).to_bytes(
                    2, "little", signed=True
                )
                for index in range(5_512)
            )
        )
    original = encode_game_audio(source.getvalue())
    dialogue_line_id = "TEST.DLG:npc:0:-"
    audio_id = DirectedLineRecord.id_for("test", dialogue_line_id)
    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_generated_audio(
            [
                GeneratedAudioRecord(
                    id=audio_id,
                    voice_id="test",
                    dialogue_line_id=dialogue_line_id,
                    inworld_voice_id="provider-test",
                    batch_operation_name="operations/test",
                    audio=original,
                    created_at="2026-08-29T00:00:00Z",
                )
            ]
        )
    finally:
        store.close()

    checkpoint = tmp_path / "normalization.tsv"
    first = await normalize_existing_audio(scenario_database, checkpoint, workers=1)
    store = await GenerationStore.open(scenario_database)
    try:
        normalized = await store.audio(audio_id)
        assert normalized is not None
        first_hash = hashlib.blake2s(normalized.audio).hexdigest()
    finally:
        store.close()
    second = await normalize_existing_audio(scenario_database, checkpoint, workers=1)
    store = await GenerationStore.open(scenario_database)
    try:
        unchanged = await store.audio(audio_id)
        assert unchanged is not None
    finally:
        store.close()

    assert first.model_dump() == {"scanned": 1, "normalized": 1}
    assert second.model_dump() == {"scanned": 1, "normalized": 0}
    assert first_hash != hashlib.blake2s(original).hexdigest()
    assert hashlib.blake2s(unchanged.audio).hexdigest() == first_hash
