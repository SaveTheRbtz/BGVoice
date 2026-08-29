"""Resumable one-time normalization of game audio encoded before the current policy."""

import asyncio
import hashlib
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from bgvoice.game_audio import encode_game_audio
from bgvoice.generation_store import GenerationStore
from bgvoice.storage_records import GeneratedAudioRecord

logger = logging.getLogger(__name__)


class AudioNormalizationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scanned: int
    normalized: int


async def normalize_existing_audio(
    database_path: Path,
    checkpoint_path: Path,
    workers: int,
) -> AudioNormalizationSummary:
    """Re-encode old rows once at the current gain, limiter, and bitrate settings."""
    assert workers > 0, "audio normalization workers must be positive"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = _read_checkpoint(checkpoint_path)
    store = await GenerationStore.open(database_path)
    scanned = 0
    normalized = 0
    try:
        loop = asyncio.get_running_loop()
        with ProcessPoolExecutor(max_workers=workers) as executor:
            async for records in store.generated_audio_batches(workers * 2):
                pending: list[GeneratedAudioRecord] = []
                new_entries: list[tuple[str, str]] = []
                for record in records:
                    source_hash = hashlib.blake2s(record.audio).hexdigest()
                    original_hash = checkpoint.get(record.id)
                    if original_hash is not None and original_hash != source_hash:
                        continue
                    pending.append(record)
                    if original_hash is None:
                        checkpoint[record.id] = source_hash
                        new_entries.append((record.id, source_hash))

                _append_checkpoint(checkpoint_path, new_entries)
                audio = await asyncio.gather(
                    *(
                        loop.run_in_executor(executor, encode_game_audio, record.audio)
                        for record in pending
                    )
                )
                await store.upsert_generated_audio(
                    [
                        record.model_copy(update={"audio": normalized_audio})
                        for record, normalized_audio in zip(pending, audio, strict=True)
                    ]
                )
                scanned += len(records)
                normalized += len(pending)
                logger.info("audio_normalization scanned=%d normalized=%d", scanned, normalized)
    finally:
        store.close()
    return AudioNormalizationSummary(scanned=scanned, normalized=normalized)


def _read_checkpoint(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return dict(line.split("\t", 1) for line in path.read_text(encoding="ascii").splitlines())


def _append_checkpoint(path: Path, entries: list[tuple[str, str]]) -> None:
    if not entries:
        return
    with path.open("a", encoding="ascii", newline="\n") as output:
        output.writelines(f"{audio_id}\t{source_hash}\n" for audio_id, source_hash in entries)
        output.flush()
        os.fsync(output.fileno())
