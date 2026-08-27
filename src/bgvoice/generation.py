"""Iterative voice design, dialogue direction, and batch speech synthesis."""

import asyncio
import base64
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, cast

from lancedb.expr import col, lit
from openai import AsyncOpenAI
from openai.types.responses import ResponseInputParam
from pydantic import BaseModel, ConfigDict, Field

from bgvoice.game_audio import encode_game_audio
from bgvoice.generation_store import GenerationStore
from bgvoice.inworld import (
    BatchResult,
    BatchSynthesisItem,
    InworldClient,
    VoiceDesignRequest,
    pack_synthesis_items,
)
from bgvoice.model_types import DialogueLineKind, RunStatus, Speaker, utc_now
from bgvoice.reader import PipelineReader
from bgvoice.storage_records import (
    CharacterRecord,
    DialogueLineRecord,
    DialogueRecord,
    DirectedLineRecord,
    GeneratedAudioRecord,
    GeneratedVoiceRecord,
    PortraitImageRecord,
    TtsBatchRecord,
    VoiceDescription,
    VoiceResourceRecord,
)

VOICE_DESIGN_MODEL = "gpt-5.6-sol"
DIRECTION_MODEL = "gpt-5.6-luna"
DIRECTION_BATCH_SIZE = 10
NARRATOR_VOICE_ID = "narrator"

_NARRATOR_DESCRIPTION = (
    "A warm, resonant older male voice with a clear British accent, calm authority, measured "
    "pacing, and natural storytelling cadence. Perfect broadcast quality audio."
)
_NARRATOR_PREVIEW = (
    "History is a patient teacher. Listen closely as the old stones surrender their secrets, "
    "and let each measured word guide you through the tale."
)

_DIRECTION_INSTRUCTIONS = """Direct Baldur's Gate dialogue for Inworld TTS-2.

Return every requested line exactly once, preserving its id. Choose `character` for spoken
character dialogue and `narrator` only for authorial scene, action, dream, or visual narration.
Rewrite Infinity Engine angle-bracket macros naturally without inventing names, genders, races,
classes, titles, or party members. Remove source-only parentheses and asterisk directions.

Add concise square-bracket delivery instructions only where they improve the performance. Useful
forms include [say warmly], [sound concerned], [speak quietly], [say with deliberate pauses],
[laugh], [sigh], and [reset]. A tag remains active until changed or reset. Convert audible stage
directions into such tags and remove purely visual actions. Preserve the original meaning,
personality, and wording. Never add markdown, speaker labels, quotation marks, or new spoken facts.
"""


class _StructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VoiceDesignPlan(_StructuredOutput):
    """Transient structured output used to create one Inworld voice."""

    description: Annotated[
        str,
        Field(
            min_length=30,
            max_length=250,
            pattern=r"^[\x20-\x7E\r\n]+$",
            description="Concrete provider-ready vocal description; never name a real performer.",
        ),
    ]
    language_code: Literal["en-GB"]
    preview_text: Annotated[
        str,
        Field(min_length=50, max_length=400, description="A short original casting line."),
    ]


class DirectedLinePlan(_StructuredOutput):
    id: Annotated[str, Field(min_length=1, max_length=63)]
    speaker: Speaker
    text: Annotated[str, Field(min_length=1, max_length=2000)]


class DirectionBatchPlan(_StructuredOutput):
    lines: list[DirectedLinePlan]


class GenerationSummary(_StructuredOutput):
    voices: int
    selected_lines: int
    directed_lines: int
    generated_audio: int


@dataclass(frozen=True, slots=True)
class VoiceWorkload:
    voice: VoiceResourceRecord
    lines: tuple[DialogueLineRecord, ...]
    portrait_png: bytes | None


def round_robin_lines(
    dialogues: Mapping[str, Sequence[DialogueLineRecord]],
    limit: int,
) -> list[DialogueLineRecord]:
    """Take each DLG's lowest remaining state in deterministic rounds."""
    assert limit > 0, "line limit must be positive"
    groups = [
        sorted(dialogues[name], key=lambda line: (line.state_index, line.id))
        for name in sorted(dialogues)
        if dialogues[name]
    ]
    selected: list[DialogueLineRecord] = []
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index < len(group):
                selected.append(group[index])
                if len(selected) == limit:
                    return selected
    return selected


async def load_workloads(
    reader: PipelineReader,
    requested_voices: Sequence[str],
    lines_per_voice: int,
) -> list[VoiceWorkload]:
    """Resolve requested current voices and their deterministic NPC workloads."""
    attribution = await reader.attribution_snapshot()
    assert attribution.run is not None, "voice generation requires published attribution"
    dialogue_rows = cast(
        list[DialogueRecord],
        await reader.dialogues_table.query().to_pydantic(DialogueRecord),
    )
    dialogues_by_resref = {row.resref.casefold(): row for row in dialogue_rows}
    workloads: list[VoiceWorkload] = []

    for requested in requested_voices:
        folded = requested.casefold()
        matches = [
            voice
            for voice in attribution.voices
            if folded in (voice.voice_id.casefold(), voice.display_name.casefold())
        ]
        assert len(matches) == 1, f"voice {requested!r} resolved to {len(matches)} resources"
        voice = matches[0]
        dialogue_names = sorted(
            {
                dialogues_by_resref[resref.casefold()].resource_name
                for resref in voice.dialogue_resrefs
                if resref.casefold() in dialogues_by_resref
            }
        )
        assert dialogue_names, f"voice {voice.display_name!r} has no extracted dialogues"
        rows = cast(
            list[DialogueLineRecord],
            await reader.lines_table.query()
            .where(
                col("dialogue_resource_name").isin(dialogue_names)
                & (col("line_kind") == lit(DialogueLineKind.NPC))
            )
            .to_pydantic(DialogueLineRecord),
        )
        groups = {
            name: [line for line in rows if line.dialogue_resource_name == name and line.text]
            for name in dialogue_names
        }
        lines = tuple(round_robin_lines(groups, lines_per_voice))
        assert len(lines) == lines_per_voice, (
            f"voice {voice.display_name!r} has only {len(lines)} non-empty NPC lines"
        )
        workloads.append(
            VoiceWorkload(
                voice=voice,
                lines=lines,
                portrait_png=await _voice_portrait(reader, voice),
            )
        )
    return workloads


async def _voice_portrait(
    reader: PipelineReader,
    voice: VoiceResourceRecord,
) -> bytes | None:
    characters = cast(
        list[CharacterRecord],
        await reader.characters_table.query()
        .where(col("resource_name").isin(voice.variant_resource_names))
        .to_pydantic(CharacterRecord),
    )
    by_name = {row.resource_name: row for row in characters}
    resrefs = [
        resref
        for name in voice.variant_resource_names
        if (character := by_name.get(name)) is not None and character.detail is not None
        for resref in (character.detail.small_portrait, character.detail.large_portrait)
        if resref is not None
    ]
    if not resrefs:
        return None
    portraits = cast(
        list[PortraitImageRecord],
        await reader.portrait_images_table.query()
        .where(col("resref").isin(resrefs))
        .to_pydantic(PortraitImageRecord),
    )
    by_resref = {row.resref.casefold(): row.png for row in portraits}
    return next(
        (by_resref[resref.casefold()] for resref in resrefs if resref.casefold() in by_resref), None
    )


async def generate(
    database_path: Path,
    requested_voices: Sequence[str],
    lines_per_voice: int,
    openai_api_key: str,
    inworld_api_key: str,
) -> GenerationSummary:
    """Run all missing generation stages and persist each completed unit."""
    import httpx

    reader = await PipelineReader.open(database_path)
    store = await GenerationStore.open(database_path)
    try:
        workloads = await load_workloads(reader, requested_voices, lines_per_voice)
        async with (
            AsyncOpenAI(api_key=openai_api_key) as openai,
            httpx.AsyncClient(timeout=httpx.Timeout(120)) as http,
        ):
            inworld = InworldClient(http, inworld_api_key)
            await _resume_batches(store, inworld)
            for workload in workloads:
                await _ensure_character_voice(openai, inworld, store, workload)
                await _direct_workload(openai, store, workload)
            if any(
                line.speaker is Speaker.NARRATOR
                for line in await store.directed_lines(
                    [workload.voice.voice_id for workload in workloads]
                )
            ):
                await _ensure_narrator_voice(inworld, store)
            for workload in workloads:
                await _synthesize_workload(store, inworld, workload)

        voice_ids = [workload.voice.voice_id for workload in workloads]
        directions = await store.directed_lines(voice_ids)
        audio = await store.generated_audio(voice_ids)
        selected = {
            (workload.voice.voice_id, line.id) for workload in workloads for line in workload.lines
        }
        return GenerationSummary(
            voices=len(workloads),
            selected_lines=len(selected),
            directed_lines=sum(
                (line.voice_id, line.dialogue_line_id) in selected for line in directions
            ),
            generated_audio=sum((row.voice_id, row.dialogue_line_id) in selected for row in audio),
        )
    finally:
        reader.close()
        store.close()


async def _ensure_character_voice(
    openai: AsyncOpenAI,
    inworld: InworldClient,
    store: GenerationStore,
    workload: VoiceWorkload,
) -> GeneratedVoiceRecord:
    existing = await store.generated_voice(workload.voice.voice_id)
    if existing is not None:
        return existing
    reused = await _reuse_existing_voice(
        inworld,
        store,
        workload.voice.voice_id,
        workload.voice.display_name,
    )
    if reused is not None:
        return reused

    content: list[dict[str, object]] = [
        {"type": "input_text", "text": _voice_design_prompt(workload.voice)}
    ]
    if workload.portrait_png is not None:
        encoded = base64.b64encode(workload.portrait_png).decode()
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:image/png;base64,{encoded}",
                "detail": "high",
            }
        )
    response = await openai.responses.parse(
        model=VOICE_DESIGN_MODEL,
        reasoning={"effort": "medium"},
        tools=[{"type": "web_search"}],
        tool_choice="required",
        max_tool_calls=4,
        store=False,
        input=cast(
            ResponseInputParam,
            [
                {
                    "role": "developer",
                    "content": (
                        "You are an expert casting director. Research carefully, use only "
                        "abstract vocal qualities, never imitate or name a real performer, and "
                        "return only the supplied structured output."
                    ),
                },
                {"role": "user", "content": content},
            ],
        ),
        text_format=VoiceDesignPlan,
    )
    plan = response.output_parsed
    assert plan is not None, f"{VOICE_DESIGN_MODEL} returned no voice design"
    return await _publish_voice(
        inworld, store, workload.voice.voice_id, workload.voice.display_name, plan
    )


def _voice_design_prompt(voice: VoiceResourceRecord) -> str:
    return f"""Design an original synthetic voice for {voice.display_name} from Baldur's Gate.

Use current web research for characterization while treating this installation's extracted source
metadata as authoritative. Translate fictional accents to the nearest real-world vocal analogue.
The final description must be concrete and ordered roughly as distinctive qualities, gender,
real-world language/accent, age, tone, delivery, pacing, texture, and audio quality. Avoid vague or
conflicting traits, use printable ASCII only, and finish with "Perfect broadcast quality audio."

Source metadata:
{voice.prompt}
"""


async def _publish_voice(
    inworld: InworldClient,
    store: GenerationStore,
    voice_id: str,
    display_name: str,
    plan: VoiceDesignPlan,
) -> GeneratedVoiceRecord:
    design = await inworld.design_voice(
        VoiceDesignRequest(
            language_code=plan.language_code,
            design_prompt=plan.description,
            preview_text=plan.preview_text,
        )
    )
    published = await inworld.publish_voice(
        design.preview_voices[0].voice_id,
        display_name=display_name,
        description=plan.description,
        tags=("bgvoice",),
    )
    record = GeneratedVoiceRecord(
        voice_id=voice_id,
        inworld_voice_id=published.voice_id,
        description=VoiceDescription(text=plan.description, language_code=plan.language_code),
        created_at=utc_now().isoformat(),
    )
    await store.upsert_generated_voices([record])
    return record


async def _ensure_narrator_voice(
    inworld: InworldClient,
    store: GenerationStore,
) -> GeneratedVoiceRecord:
    existing = await store.generated_voice(NARRATOR_VOICE_ID)
    if existing is not None:
        return existing
    reused = await _reuse_existing_voice(
        inworld,
        store,
        NARRATOR_VOICE_ID,
        "BGVoice Narrator",
    )
    if reused is not None:
        return reused
    return await _publish_voice(
        inworld,
        store,
        NARRATOR_VOICE_ID,
        "BGVoice Narrator",
        VoiceDesignPlan(
            description=_NARRATOR_DESCRIPTION,
            language_code="en-GB",
            preview_text=_NARRATOR_PREVIEW,
        ),
    )


async def _reuse_existing_voice(
    inworld: InworldClient,
    store: GenerationStore,
    voice_id: str,
    display_name: str,
) -> GeneratedVoiceRecord | None:
    matches = [
        voice
        for voice in await inworld.list_voices()
        if voice.display_name.casefold() == display_name.casefold()
    ]
    assert len(matches) <= 1, f"multiple reusable Inworld voices are named {display_name!r}"
    if not matches:
        return None
    voice = matches[0]
    language = voice.language_code or voice.legacy_language_code
    assert language is not None, f"Inworld voice {voice.voice_id!r} has no language"
    parts = language.replace("_", "-").split("-")
    language_code = "-".join((parts[0].lower(), *(part.upper() for part in parts[1:])))
    record = GeneratedVoiceRecord(
        voice_id=voice_id,
        inworld_voice_id=voice.voice_id,
        description=VoiceDescription(text=voice.description, language_code=language_code),
        created_at=utc_now().isoformat(),
    )
    await store.upsert_generated_voices([record])
    return record


async def _direct_workload(
    openai: AsyncOpenAI,
    store: GenerationStore,
    workload: VoiceWorkload,
) -> None:
    existing = {
        line.dialogue_line_id for line in await store.directed_lines([workload.voice.voice_id])
    }
    missing = [line for line in workload.lines if line.id not in existing]
    for start in range(0, len(missing), DIRECTION_BATCH_SIZE):
        source = missing[start : start + DIRECTION_BATCH_SIZE]
        response = await openai.responses.parse(
            model=DIRECTION_MODEL,
            reasoning={"effort": "medium"},
            store=False,
            input=cast(
                ResponseInputParam,
                [
                    {
                        "role": "developer",
                        "content": (
                            "Return only the supplied structured output.\n\n"
                            + _DIRECTION_INSTRUCTIONS
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Character source metadata:\n{workload.voice.prompt}\n\n"
                            "Lines to direct:\n"
                            + "\n".join(
                                f"{DirectedLineRecord.id_for(workload.voice.voice_id, line.id)}"
                                f"\t{line.text}"
                                for line in source
                            )
                        ),
                    },
                ],
            ),
            text_format=DirectionBatchPlan,
        )
        plan = response.output_parsed
        assert plan is not None, f"{DIRECTION_MODEL} returned no direction batch"
        expected = {
            DirectedLineRecord.id_for(workload.voice.voice_id, line.id): line.id for line in source
        }
        assert len(plan.lines) == len(expected), "direction batch returned the wrong line count"
        assert {line.id for line in plan.lines} == set(expected), (
            "direction batch returned unexpected line IDs"
        )
        records = [
            DirectedLineRecord(
                id=line.id,
                voice_id=workload.voice.voice_id,
                dialogue_line_id=expected[line.id],
                speaker=line.speaker,
                text=_validated_direction(line.text),
                created_at=utc_now().isoformat(),
            )
            for line in plan.lines
        ]
        await store.delete_audio([record.id for record in records])
        await store.upsert_directed_lines(records)


def _validated_direction(text: str) -> str:
    directed = text.strip()
    assert directed, "directed dialogue is empty"
    assert "<" not in directed and ">" not in directed, (
        "directed dialogue contains an unresolved Infinity Engine token"
    )
    assert "*" not in directed, "directed dialogue contains an asterisk stage direction"
    assert "```" not in directed, "directed dialogue contains a Markdown code fence"
    return directed


async def _synthesize_workload(
    store: GenerationStore,
    inworld: InworldClient,
    workload: VoiceWorkload,
) -> None:
    by_source_line = {
        line.dialogue_line_id: line
        for line in await store.directed_lines([workload.voice.voice_id])
    }
    directions = [by_source_line[line.id] for line in workload.lines if line.id in by_source_line]
    existing = {audio.id for audio in await store.generated_audio([workload.voice.voice_id])}
    voices = await store.generated_voices()
    for speaker in Speaker:
        pending = [
            line for line in directions if line.speaker is speaker and line.id not in existing
        ]
        if not pending:
            continue
        generated_voice = voices[
            workload.voice.voice_id if speaker is Speaker.CHARACTER else NARRATOR_VOICE_ID
        ]
        items = [
            BatchSynthesisItem(
                custom_id=line.id,
                text=line.text,
                voice_id=generated_voice.inworld_voice_id,
                language_code=generated_voice.description.language_code,
            )
            for line in pending
        ]
        for batch in pack_synthesis_items(items):
            operation = await inworld.submit_batch(batch)
            record = TtsBatchRecord(
                operation_name=operation.name,
                status=RunStatus.RUNNING,
                started_at=utc_now().isoformat(),
            )
            await store.upsert_batches([record])
            await _complete_batch(store, inworld, record)


async def _resume_batches(store: GenerationStore, inworld: InworldClient) -> None:
    for batch in await store.running_batches():
        await _complete_batch(store, inworld, batch)


async def _complete_batch(
    store: GenerationStore,
    inworld: InworldClient,
    batch: TtsBatchRecord,
) -> int:
    operation = await inworld.poll_operation(batch.operation_name)
    if operation.error is not None:
        await store.upsert_batches(
            [
                batch.model_copy(
                    update={
                        "status": RunStatus.FAILED,
                        "completed_at": utc_now().isoformat(),
                        "error": operation.error.message,
                    }
                )
            ]
        )
        return 0
    assert operation.response is not None, "completed Inworld batch has no result manifest"
    results = await inworld.download_results(operation.response.results_uri)
    directions = {line.id: line for line in await store.directed_lines()}
    voices = await store.generated_voices()
    workers = os.process_cpu_count() or 1
    conversion_slots = asyncio.Semaphore(workers)

    async def download(result: BatchResult) -> GeneratedAudioRecord | None:
        if result.audio_uri is None:
            return None
        direction = directions[result.custom_id]
        generated_voice = voices[
            direction.voice_id if direction.speaker is Speaker.CHARACTER else NARRATOR_VOICE_ID
        ]
        async with conversion_slots:
            source = await inworld.download_audio(result.audio_uri)
            audio = await asyncio.to_thread(encode_game_audio, source)
        return GeneratedAudioRecord(
            id=direction.id,
            voice_id=direction.voice_id,
            dialogue_line_id=direction.dialogue_line_id,
            inworld_voice_id=generated_voice.inworld_voice_id,
            batch_operation_name=batch.operation_name,
            audio=audio,
            created_at=utc_now().isoformat(),
        )

    records = [
        record
        for record in await asyncio.gather(*(download(result) for result in results.results))
        if record is not None
    ]
    await store.upsert_generated_audio(records)
    status = RunStatus.COMPLETE_WITH_ERRORS if results.failed_items else RunStatus.COMPLETE
    await store.upsert_batches(
        [batch.model_copy(update={"status": status, "completed_at": utc_now().isoformat()})]
    )
    return len(records)
