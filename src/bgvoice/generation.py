"""Iterative voice design, dialogue direction, and batch speech synthesis."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from lancedb.expr import col, lit
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict

from bgvoice.dialogue_context import DialogueHistoryIndex, dialogue_history
from bgvoice.game_audio import encode_game_audio
from bgvoice.generation_ai import (
    CharacterAbilityScores,
    DialogueDirectionSource,
    DirectionBatchSource,
    VoiceDesignSource,
    create_direction_batch,
    create_voice_design_plan,
)
from bgvoice.generation_store import GenerationStore
from bgvoice.inworld import (
    INWORLD_BATCH_CONCURRENCY,
    BatchSynthesisItem,
    InworldClient,
    PublishedVoice,
    VoiceDesignRequest,
    pack_synthesis_items,
)
from bgvoice.model_types import DialogueLineKind, RunStatus, utc_now
from bgvoice.reader import PipelineReader
from bgvoice.reader_stats import AttributionSnapshot
from bgvoice.storage_records import (
    CharacterDirection,
    CharacterRecord,
    DialogueLineRecord,
    DialogueRecord,
    DirectedLineRecord,
    GeneratedAudioRecord,
    GeneratedVoiceRecord,
    NarratorDirection,
    PortraitImageRecord,
    TtsBatchRecord,
    VoiceDescription,
    VoiceResourceRecord,
)

VOICE_DESIGN_MODEL = "gpt-5.6-sol"
DIRECTION_MODEL = "gpt-5.6-luna"
DIRECTION_BATCH_SIZE = 10
AUDIO_WRITE_BATCH_SIZE = 25
VOICE_CONCURRENCY = 75
OPENAI_CONCURRENCY = 100
NARRATOR_VOICE_ID = "narrator"

_NARRATOR_DISPLAY_NAME = "Narrator"
_NARRATOR_DESCRIPTION = (
    "An old wise male scholar voice with a clear British accent, speaking at a steady pace and "
    "neutral tone. The timbre is warm and resonant, conveying a sense of calm and authority, "
    "suitable for narrations."
)
_NARRATOR_PREVIEW = (
    "History is a patient teacher. Listen closely as the old stones surrender their secrets, "
    "and let each measured word guide you through the tale."
)


class _StructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerationSummary(_StructuredOutput):
    voices: int
    selected_lines: int
    directed_lines: int
    generated_audio: int


@dataclass(frozen=True, slots=True)
class VoiceWorkload:
    voice: VoiceResourceRecord
    lines: tuple[DialogueLineRecord, ...]
    ability_scores: CharacterAbilityScores
    portrait_png: bytes | None


def round_robin_lines(
    dialogues: Mapping[str, Sequence[DialogueLineRecord]],
    limit: int | None,
) -> list[DialogueLineRecord]:
    """Take each DLG's lowest remaining state in deterministic rounds."""
    assert limit is None or limit > 0, "line limit must be positive"
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
                if limit is not None and len(selected) == limit:
                    return selected
    return selected


async def load_workloads(
    reader: PipelineReader,
    requested_voices: Sequence[str],
    lines_per_voice: int | None,
) -> list[VoiceWorkload]:
    """Resolve requested current voices and their deterministic NPC workloads."""
    attribution = await reader.attribution_snapshot()
    assert attribution.run is not None, "voice generation requires published attribution"
    dialogue_rows = cast(
        list[DialogueRecord],
        await reader.dialogues_table.query().to_pydantic(DialogueRecord),
    )
    dialogues_by_resref = {row.resref.casefold(): row for row in dialogue_rows}
    dialogues_by_name = {row.resource_name.casefold(): row for row in dialogue_rows}
    workloads: list[VoiceWorkload] = []
    selected_voice_ids: set[str] = set()

    for requested in requested_voices:
        folded = requested.casefold()
        matches = [
            voice
            for voice in attribution.voices
            if folded in (voice.voice_id.casefold(), voice.display_name.casefold())
        ]
        assert len(matches) == 1, f"voice {requested!r} resolved to {len(matches)} resources"
        voice = matches[0]
        if voice.voice_id in selected_voice_ids:
            continue
        selected_voice_ids.add(voice.voice_id)
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
        assert lines, f"voice {voice.display_name!r} has no non-empty NPC lines"
        ability_scores, portrait_png = await _voice_evidence(
            reader,
            voice,
            attribution,
            dialogues_by_name,
        )
        workloads.append(
            VoiceWorkload(
                voice=voice,
                lines=lines,
                ability_scores=ability_scores,
                portrait_png=portrait_png,
            )
        )
    return workloads


async def _voice_evidence(
    reader: PipelineReader,
    voice: VoiceResourceRecord,
    attribution: AttributionSnapshot,
    dialogues: dict[str, DialogueRecord],
) -> tuple[CharacterAbilityScores, bytes | None]:
    """Choose the most-used CRE and return its ability scores and best portrait."""
    characters = cast(
        list[CharacterRecord],
        await reader.characters_table.query()
        .where(col("resource_name").isin(voice.variant_resource_names))
        .to_pydantic(CharacterRecord),
    )
    assert characters, f"voice {voice.display_name!r} has no extracted character variants"
    resrefs = [
        resref
        for character in characters
        if character.detail is not None
        for resref in (character.detail.small_portrait, character.detail.large_portrait)
        if resref is not None
    ]
    portraits = (
        cast(
            list[PortraitImageRecord],
            await reader.portrait_images_table.query()
            .where(col("resref").isin(resrefs))
            .to_pydantic(PortraitImageRecord),
        )
        if resrefs
        else []
    )
    by_resref = {row.resref.casefold(): row.png for row in portraits}
    representative = min(
        (character for character in characters if character.detail is not None),
        key=lambda character: _representative_priority(
            character,
            attribution,
            dialogues,
            by_resref,
        ),
    )
    detail = representative.detail
    assert detail is not None
    portrait = next(
        (
            by_resref[resref.casefold()]
            for resref in (detail.large_portrait, detail.small_portrait)
            if resref is not None and resref.casefold() in by_resref
        ),
        None,
    )
    attributes = detail.base_attributes
    ability_scores = CharacterAbilityScores(
        strength=attributes.strength,
        strength_bonus=attributes.strength_bonus,
        intelligence=attributes.intelligence,
        wisdom=attributes.wisdom,
        dexterity=attributes.dexterity,
        constitution=attributes.constitution,
        charisma=attributes.charisma,
    )
    return ability_scores, portrait


def _representative_priority(
    character: CharacterRecord,
    attribution: AttributionSnapshot,
    dialogues: dict[str, DialogueRecord],
    portraits: dict[str, bytes],
) -> tuple[int, int, bool, str, str]:
    record = attribution.by_character[character.resource_name.casefold()]
    details = [
        dialogue.detail
        for name in record.resolved_dialogue_resource_names
        if (dialogue := dialogues[name.casefold()]).detail is not None
    ]
    detail = character.detail
    assert detail is not None
    has_portrait = any(
        resref is not None and resref.casefold() in portraits
        for resref in (detail.large_portrait, detail.small_portrait)
    )
    return (
        -sum(item.npc_line_count for item in details if item is not None),
        -sum(item.dialogue_line_count for item in details if item is not None),
        not has_portrait,
        character.resource_name.casefold(),
        character.resource_name,
    )


async def generate(
    database_path: Path,
    requested_voices: Sequence[str],
    lines_per_voice: int | None,
    openai_api_key: str,
    inworld_api_key: str,
    *,
    recreate_voices: bool = False,
) -> GenerationSummary:
    """Run all missing generation stages and persist each completed unit."""
    import httpx

    reader = await PipelineReader.open(database_path)
    store = await GenerationStore.open(database_path)
    try:
        workloads = await load_workloads(reader, requested_voices, lines_per_voice)
        history_index = await DialogueHistoryIndex.load(reader)
        async with (
            AsyncOpenAI(api_key=openai_api_key) as openai,
            httpx.AsyncClient(timeout=httpx.Timeout(120)) as http,
        ):
            inworld = InworldClient(http, inworld_api_key)
            openai_capacity = asyncio.Semaphore(OPENAI_CONCURRENCY)
            inworld_capacity = asyncio.Semaphore(INWORLD_BATCH_CONCURRENCY)
            await _resume_batches(store, inworld, inworld_capacity)
            provider_voices = _provider_voice_catalog(await inworld.list_voices())

            narrator_lock = asyncio.Lock()
            narrator_voice: GeneratedVoiceRecord | None = None

            async def ensure_narrator() -> GeneratedVoiceRecord:
                nonlocal narrator_voice
                async with narrator_lock:
                    if narrator_voice is None:
                        narrator_voice = await _ensure_narrator_voice(
                            inworld,
                            store,
                            provider_voices,
                        )
                    return narrator_voice

            async def prepare(workload: VoiceWorkload) -> None:
                await _ensure_character_voice(
                    openai,
                    inworld,
                    store,
                    workload,
                    openai_capacity,
                    provider_voices,
                    recreate=recreate_voices,
                )
                await _direct_workload(
                    openai,
                    store,
                    workload,
                    history_index,
                    openai_capacity,
                )

            async def synthesize(workload: VoiceWorkload) -> None:
                await _synthesize_workload(
                    store,
                    inworld,
                    workload,
                    ensure_narrator,
                    inworld_capacity,
                )

            await _run_workload_pipeline(
                workloads,
                prepare,
                synthesize,
                asyncio.Semaphore(VOICE_CONCURRENCY),
            )

        voice_ids = [workload.voice.voice_id for workload in workloads]
        directions = await store.directed_lines(voice_ids)
        audio = await store.generated_audio_identities(voice_ids)
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
    openai_capacity: asyncio.Semaphore,
    provider_voices: Mapping[str, PublishedVoice],
    *,
    recreate: bool,
) -> GeneratedVoiceRecord:
    existing = await store.generated_voice(workload.voice.voice_id)
    if recreate:
        named_voice = provider_voices.get(workload.voice.display_name.casefold())
        provider_ids = set() if named_voice is None else {named_voice.voice_id}
        if existing is not None and any(
            voice.voice_id == existing.inworld_voice_id for voice in provider_voices.values()
        ):
            provider_ids.add(existing.inworld_voice_id)
        await store.delete_voice_generation(workload.voice.voice_id)
        for provider_id in sorted(provider_ids):
            await inworld.delete_voice(provider_id)
        existing = None
    if existing is not None:
        return existing
    if not recreate:
        reused = await _reuse_existing_voice(
            store,
            provider_voices,
            workload.voice.voice_id,
            workload.voice.display_name,
        )
        if reused is not None:
            return reused

    metadata, biography = _metadata_and_biography(workload.voice.prompt)
    async with openai_capacity:
        plan = await create_voice_design_plan(
            openai,
            VoiceDesignSource(
                display_name=workload.voice.display_name,
                metadata=metadata,
                biography=biography,
                ability_scores=workload.ability_scores,
                portrait_png=workload.portrait_png,
            ),
            model=VOICE_DESIGN_MODEL,
        )
    return await _publish_voice(
        inworld,
        store,
        workload.voice.voice_id,
        workload.voice.display_name,
        description=plan.profile.render(),
        language_code=plan.language_code,
        preview_text=plan.preview_text,
    )


def _metadata_and_biography(prompt: str) -> tuple[str, str | None]:
    metadata, separator, biography = prompt.partition("\n\nBiography:\n")
    cleaned_biography = biography.strip() if separator else ""
    return metadata.strip(), cleaned_biography or None


async def _publish_voice(
    inworld: InworldClient,
    store: GenerationStore,
    voice_id: str,
    display_name: str,
    *,
    description: str,
    language_code: str,
    preview_text: str,
) -> GeneratedVoiceRecord:
    design = await inworld.design_voice(
        VoiceDesignRequest(
            language_code=language_code,
            design_prompt=description,
            preview_text=preview_text,
        )
    )
    published = await inworld.publish_voice(
        design.preview_voices[0].voice_id,
        display_name=display_name,
        description=description,
        tags=("bgvoice",),
    )
    record = GeneratedVoiceRecord(
        voice_id=voice_id,
        inworld_voice_id=published.voice_id,
        description=VoiceDescription(text=description, language_code=language_code),
        created_at=utc_now().isoformat(),
    )
    await store.upsert_generated_voices([record])
    return record


async def _ensure_narrator_voice(
    inworld: InworldClient,
    store: GenerationStore,
    provider_voices: Mapping[str, PublishedVoice],
) -> GeneratedVoiceRecord:
    existing = await store.generated_voice(NARRATOR_VOICE_ID)
    if existing is not None:
        return existing
    reused = await _reuse_existing_voice(
        store,
        provider_voices,
        NARRATOR_VOICE_ID,
        _NARRATOR_DISPLAY_NAME,
    )
    if reused is not None:
        return reused
    return await _publish_voice(
        inworld,
        store,
        NARRATOR_VOICE_ID,
        _NARRATOR_DISPLAY_NAME,
        description=_NARRATOR_DESCRIPTION,
        language_code="en-GB",
        preview_text=_NARRATOR_PREVIEW,
    )


async def _reuse_existing_voice(
    store: GenerationStore,
    provider_voices: Mapping[str, PublishedVoice],
    voice_id: str,
    display_name: str,
) -> GeneratedVoiceRecord | None:
    voice = provider_voices.get(display_name.casefold())
    if voice is None:
        return None
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


def _provider_voice_catalog(voices: Sequence[PublishedVoice]) -> dict[str, PublishedVoice]:
    catalog: dict[str, PublishedVoice] = {}
    for voice in voices:
        key = voice.display_name.casefold()
        assert key not in catalog, (
            f"multiple reusable Inworld voices are named {voice.display_name!r}"
        )
        catalog[key] = voice
    return catalog


async def _direct_workload(
    openai: AsyncOpenAI,
    store: GenerationStore,
    workload: VoiceWorkload,
    history_index: DialogueHistoryIndex,
    openai_capacity: asyncio.Semaphore,
) -> None:
    existing = {
        line.dialogue_line_id for line in await store.directed_lines([workload.voice.voice_id])
    }
    missing = [line for line in workload.lines if line.id not in existing]
    metadata, _biography = _metadata_and_biography(workload.voice.prompt)
    batches = [
        missing[start : start + DIRECTION_BATCH_SIZE]
        for start in range(0, len(missing), DIRECTION_BATCH_SIZE)
    ]

    async def direct(source_lines: list[DialogueLineRecord]) -> None:
        histories = [dialogue_history(history_index, line) for line in source_lines]
        sources = [
            DialogueDirectionSource(
                id=str(index),
                text=cast(str, line.text),
                dialogue_history=history,
            )
            for index, (line, history) in enumerate(
                zip(source_lines, histories, strict=True),
                start=1,
            )
        ]
        async with openai_capacity:
            plan = await create_direction_batch(
                openai,
                DirectionBatchSource(
                    display_name=workload.voice.display_name,
                    metadata=metadata,
                    lines=sources,
                ),
                model=DIRECTION_MODEL,
            )
        expected = {source.id: line.id for source, line in zip(sources, source_lines, strict=True)}
        records: list[DirectedLineRecord] = []
        for item in plan.items:
            result = item.result
            character = (
                CharacterDirection(directed_dialogue=result.directed_dialogue)
                if result.speaker == "character"
                else None
            )
            narrator = (
                NarratorDirection(directed_dialogue=result.directed_dialogue)
                if result.speaker == "narrator"
                else None
            )
            records.append(
                DirectedLineRecord(
                    id=DirectedLineRecord.id_for(
                        workload.voice.voice_id,
                        expected[item.id],
                    ),
                    voice_id=workload.voice.voice_id,
                    dialogue_line_id=expected[item.id],
                    character=character,
                    narrator=narrator,
                    created_at=utc_now().isoformat(),
                )
            )
        await store.upsert_directed_lines(records)

    await _wait_for_all([asyncio.create_task(direct(batch)) for batch in batches])


async def _synthesize_workload(
    store: GenerationStore,
    inworld: InworldClient,
    workload: VoiceWorkload,
    ensure_narrator: Callable[[], Awaitable[GeneratedVoiceRecord]],
    capacity: asyncio.Semaphore,
) -> None:
    selected = {line.id for line in workload.lines}
    direction_rows = await store.directed_lines([workload.voice.voice_id])
    if any(
        line.dialogue_line_id in selected and line.narrator is not None for line in direction_rows
    ):
        await ensure_narrator()
    voices = await store.generated_voices()
    directions = {line.dialogue_line_id: line for line in direction_rows}
    existing = {
        audio.id for audio in await store.generated_audio_identities([workload.voice.voice_id])
    }
    items_by_provider_voice: dict[str, list[BatchSynthesisItem]] = {}
    for source_line in workload.lines:
        direction = directions[source_line.id]
        if direction.id in existing:
            continue
        generated_voice = voices[
            workload.voice.voice_id if direction.character is not None else NARRATOR_VOICE_ID
        ]
        text = (
            direction.character.directed_dialogue
            if direction.character is not None
            else cast(NarratorDirection, direction.narrator).directed_dialogue
        )
        items_by_provider_voice.setdefault(generated_voice.inworld_voice_id, []).append(
            BatchSynthesisItem(
                custom_id=direction.id,
                text=text,
                voice_id=generated_voice.inworld_voice_id,
                language_code=generated_voice.description.language_code,
            )
        )

    batches = pack_synthesis_items(
        [item for items in items_by_provider_voice.values() for item in items]
    )
    directions_by_id = {line.id: line for line in direction_rows}

    async def synthesize(batch: list[BatchSynthesisItem]) -> None:
        operation = await inworld.submit_batch(batch)
        record = TtsBatchRecord(
            operation_name=operation.name,
            status=RunStatus.RUNNING,
            started_at=utc_now().isoformat(),
        )
        await store.upsert_batches([record])
        await _complete_batch(store, inworld, record, directions_by_id, voices)

    await _run_concurrently(
        batches,
        synthesize,
        capacity,
    )


async def _run_workload_pipeline[Workload](
    workloads: Sequence[Workload],
    prepare: Callable[[Workload], Awaitable[None]],
    synthesize: Callable[[Workload], Awaitable[None]],
    capacity: asyncio.Semaphore,
) -> None:
    synthesis_tasks: list[asyncio.Task[None]] = []

    async def prepare_and_schedule(workload: Workload) -> None:
        await prepare(workload)

        async def run_synthesis() -> None:
            await synthesize(workload)

        synthesis_tasks.append(asyncio.create_task(run_synthesis()))

    preparation_failure: BaseException | None = None
    try:
        await _run_concurrently(workloads, prepare_and_schedule, capacity)
    except BaseException as error:
        preparation_failure = error

    synthesis_failure: BaseException | None = None
    try:
        await _wait_for_all(synthesis_tasks)
    except BaseException as error:
        synthesis_failure = error

    if preparation_failure is not None:
        raise preparation_failure
    if synthesis_failure is not None:
        raise synthesis_failure


async def _run_concurrently[Item](
    items: Sequence[Item],
    process: Callable[[Item], Awaitable[None]],
    capacity: asyncio.Semaphore,
) -> None:
    async def run(item: Item) -> None:
        async with capacity:
            await process(item)

    await _wait_for_all([asyncio.create_task(run(item)) for item in items])


async def _wait_for_all(tasks: Sequence[asyncio.Task[None]]) -> None:
    if tasks:
        await asyncio.wait(tasks)
    failure: BaseException | None = None
    for task in tasks:
        try:
            task.result()
        except BaseException as error:
            failure = failure or error
    if failure is not None:
        raise failure


async def _resume_batches(
    store: GenerationStore,
    inworld: InworldClient,
    capacity: asyncio.Semaphore,
) -> None:
    batches = await store.running_batches()
    if not batches:
        return
    directions = {line.id: line for line in await store.directed_lines()}
    voices = await store.generated_voices()

    async def resume(batch: TtsBatchRecord) -> None:
        await _complete_batch(store, inworld, batch, directions, voices)

    await _run_concurrently(
        batches,
        resume,
        capacity,
    )


async def _complete_batch(
    store: GenerationStore,
    inworld: InworldClient,
    batch: TtsBatchRecord,
    directions: Mapping[str, DirectedLineRecord],
    voices: Mapping[str, GeneratedVoiceRecord],
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

    generated = 0
    records: list[GeneratedAudioRecord] = []
    for result in results.results:
        if result.audio_uri is None:
            continue
        source = await inworld.download_audio(result.audio_uri)
        direction = directions[result.custom_id]
        generated_voice = voices[
            direction.voice_id if direction.character is not None else NARRATOR_VOICE_ID
        ]
        records.append(
            GeneratedAudioRecord(
                id=direction.id,
                voice_id=direction.voice_id,
                dialogue_line_id=direction.dialogue_line_id,
                inworld_voice_id=generated_voice.inworld_voice_id,
                batch_operation_name=batch.operation_name,
                audio=await asyncio.to_thread(encode_game_audio, source),
                created_at=utc_now().isoformat(),
            )
        )
        if len(records) == AUDIO_WRITE_BATCH_SIZE:
            await store.upsert_generated_audio(records)
            generated += len(records)
            records.clear()
    status = RunStatus.COMPLETE_WITH_ERRORS if results.failed_items else RunStatus.COMPLETE
    await store.upsert_generated_audio(records)
    await store.upsert_batches(
        [batch.model_copy(update={"status": status, "completed_at": utc_now().isoformat()})]
    )
    return generated + len(records)
