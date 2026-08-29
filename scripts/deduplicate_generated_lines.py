"""One-time collapse of pre-deduplication direction and audio rows."""

import asyncio
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import cast

from lancedb.expr import col, lit

from bgvoice.generation_store import GenerationStore
from bgvoice.model_types import DialogueLineKind
from bgvoice.reader import PipelineReader
from bgvoice.storage_records import DialogueLineRecord, DirectedLineRecord

DATABASE = Path("data/bgvoice.lancedb")
EXPECTED_REDUNDANT_ROWS = 12_716
EXPECTED_MANIFEST_SHA256 = "73c8866b78cee187a3f0bb1c41e51d0ce0d7239f97546b95482404b93baa7b8a"


async def main() -> None:
    reader = await PipelineReader.open(DATABASE)
    store = await GenerationStore.open(DATABASE)
    try:
        line_rows = await (
            reader.lines_table.query()
            .where(col("line_kind") == lit(DialogueLineKind.NPC.value))
            .to_pydantic(DialogueLineRecord)
        )
        lines = [
            line
            for line in cast(list[DialogueLineRecord], line_rows)
            if line.text and line.text.strip()
        ]
        lines_by_dialogue: dict[str, list[DialogueLineRecord]] = defaultdict(list)
        for line in lines:
            lines_by_dialogue[line.dialogue_resource_name].append(line)

        order: dict[str, tuple[int, str, int, str]] = {}
        for dialogue_name, dialogue_lines in lines_by_dialogue.items():
            for ordinal, line in enumerate(
                sorted(dialogue_lines, key=lambda item: (item.state_index, item.id))
            ):
                order[line.id] = (ordinal, dialogue_name, line.state_index, line.id)

        directions = {row.id: row for row in await store.directed_lines()}
        audio = {row.id: row for row in await store.generated_audio_identities()}
        assert directions.keys() == audio.keys(), "direction and audio IDs differ"
        assert all(
            (direction.voice_id, direction.dialogue_line_id)
            == (audio[row_id].voice_id, audio[row_id].dialogue_line_id)
            for row_id, direction in directions.items()
        ), "direction and audio identities differ"

        line_by_id = {line.id: line for line in lines}
        canonical: dict[tuple[str, str], DirectedLineRecord] = {}
        for direction in directions.values():
            line = line_by_id[direction.dialogue_line_id]
            assert line.text is not None
            key = (direction.voice_id, line.text)
            if key not in canonical or order[line.id] < order[canonical[key].dialogue_line_id]:
                canonical[key] = direction

        keep = {direction.id for direction in canonical.values()}
        redundant = sorted(directions.keys() - keep)
        manifest = hashlib.sha256(("\n".join(redundant) + "\n").encode()).hexdigest()
        assert len(redundant) == EXPECTED_REDUNDANT_ROWS
        assert manifest == EXPECTED_MANIFEST_SHA256

        await store.delete_line_generation(redundant)
        remaining_directions, remaining_audio = await asyncio.gather(
            store._directed_lines.count_rows(),
            store._generated_audio.count_rows(),
        )
        assert remaining_directions == remaining_audio == len(canonical)
        print(
            json.dumps(
                {
                    "removed_direction_rows": len(redundant),
                    "removed_audio_rows": len(redundant),
                    "remaining_unique_voice_texts": len(canonical),
                    "manifest_sha256": manifest,
                },
                indent=2,
            )
        )
    finally:
        reader.close()
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
