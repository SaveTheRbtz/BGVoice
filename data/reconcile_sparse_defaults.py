"""One-time repair for the interrupted raw gender/race default run."""

import asyncio
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import httpx
from dotenv import load_dotenv
from lancedb.expr import col

from bgvoice.generation import (
    _bucket_default_voices,
    _resume_batches,
    _sparse_voice_ids,
    load_workloads,
)
from bgvoice.generation_store import GenerationStore
from bgvoice.inworld import INWORLD_BATCH_CONCURRENCY, InworldClient
from bgvoice.model_types import RunStatus
from bgvoice.reader import PipelineReader
from bgvoice.storage_records import GeneratedVoiceRecord

DATABASE = Path("data/bgvoice.lancedb")
AUDIT = Path("data/sparse-default-reconciliation.json")


def is_legacy_default(voice_id: str) -> bool:
    parts = voice_id.split(":")
    return (
        len(parts) == 5
        and parts[:2] == ["default", "gender"]
        and parts[2].isdigit()
        and parts[3] == "race"
        and parts[4].isdigit()
    )


async def main() -> None:
    load_dotenv()
    reader = await PipelineReader.open(DATABASE)
    store = await GenerationStore.open(DATABASE)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120),
            transport=httpx.AsyncHTTPTransport(retries=3),
        ) as http:
            inworld = InworldClient(http, os.environ["INWORLD_API_KEY"])
            pending_operations = {
                batch.operation_name for batch in await store.running_batches()
            }
            await _resume_batches(
                store,
                inworld,
                asyncio.Semaphore(INWORLD_BATCH_CONCURRENCY),
            )
            assert not await store.running_batches(), "Inworld batches must finish before remapping"
            batches = {batch.operation_name: batch for batch in await store.batches()}
            incomplete = {
                operation: batches[operation].status
                for operation in pending_operations
                if batches[operation].status != RunStatus.COMPLETE
            }
            assert not incomplete, f"Inworld batch harvest was not clean: {incomplete}"

            voice_ids = await _sparse_voice_ids(reader, 5)
            workloads = _bucket_default_voices(await load_workloads(reader, voice_ids, None))
            records = await store.generated_voices()
            legacy = {voice_id: row for voice_id, row in records.items() if is_legacy_default(voice_id)}
            provider_to_master = {row.inworld_voice_id: row for row in legacy.values()}
            assert len(provider_to_master) == len(legacy), "legacy defaults must use unique providers"

            candidates: dict[str, Counter[str]] = defaultdict(Counter)
            for workload in workloads:
                assignment = records.get(workload.voice.voice_id)
                if assignment is not None and assignment.inworld_voice_id in provider_to_master:
                    candidates[workload.default_voice.voice_id][assignment.inworld_voice_id] += 1

            canonical: dict[str, GeneratedVoiceRecord] = {}
            for workload in workloads:
                default_id = workload.default_voice.voice_id
                if default_id in canonical:
                    continue
                existing = records.get(default_id)
                if existing is not None:
                    canonical[default_id] = existing
                    continue
                ranked = candidates[default_id]
                assert ranked, f"no reusable provider for {default_id}"
                provider_id = min(ranked, key=lambda item: (-ranked[item], item))
                canonical[default_id] = provider_to_master[provider_id].model_copy(
                    update={"voice_id": default_id}
                )

            remote = {voice.voice_id for voice in await inworld.list_voices()}
            missing = {
                row.inworld_voice_id for row in canonical.values()
            } - remote
            assert not missing, f"chosen Inworld voices no longer exist: {sorted(missing)}"
            await store.upsert_generated_voices(list(canonical.values()))
            reassignments = []
            for workload in workloads:
                assignment = records.get(workload.voice.voice_id)
                if assignment is not None and assignment.inworld_voice_id in provider_to_master:
                    reassignments.append(
                        canonical[workload.default_voice.voice_id].model_copy(
                            update={"voice_id": workload.voice.voice_id}
                        )
                    )
            await store.upsert_generated_voices(reassignments)

            updated = await store.generated_voices()
            references = {
                row.inworld_voice_id
                for voice_id, row in updated.items()
                if not is_legacy_default(voice_id)
            }
            orphaned = sorted(set(provider_to_master) - references)
            AUDIT.write_text(
                json.dumps(
                    {
                        "legacy_masters": len(legacy),
                        "canonical_masters": len(canonical),
                        "reassigned_voices": len(reassignments),
                        "preserved_custom_voices": len(workloads) - len(reassignments),
                        "canonical_provider_ids": {
                            voice_id: row.inworld_voice_id
                            for voice_id, row in sorted(canonical.items())
                        },
                        "orphaned_provider_ids": orphaned,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            for provider_id in orphaned:
                if provider_id in remote:
                    await inworld.delete_voice(provider_id)
            await store._generated_voices.delete(col("voice_id").isin(sorted(legacy)))
    finally:
        reader.close()
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
