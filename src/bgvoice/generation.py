"""Iterative voice design, dialogue direction, and batch speech synthesis."""

import asyncio
import logging
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
    DirectionPlan,
    DirectionSource,
    VoiceDesignSource,
    create_direction,
    create_voice_design_plan,
    tts_speakable_text,
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
from bgvoice.model_types import DialogueLineKind, GenerationFailureStage, RunStatus, utc_now
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
    GenerationFailureRecord,
    NarratorDirection,
    PortraitImageRecord,
    TtsBatchRecord,
    VoiceDescription,
    VoiceResourceRecord,
)

logger = logging.getLogger(__name__)

VOICE_DESIGN_MODEL = "gpt-5.6-sol"
DIRECTION_MODEL = "gpt-5.6-luna"
DIRECTION_FALLBACK_MODEL = "gpt-5.6-terra"
DIRECTION_WRITE_BATCH_SIZE = 100
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
    voice_creation_failures: int
    dialogue_direction_failures: int
    audio_generation_failures: int


@dataclass(frozen=True, slots=True)
class VoiceWorkload:
    voice: VoiceResourceRecord
    lines: tuple[DialogueLineRecord, ...]
    ability_scores: CharacterAbilityScores
    portrait_png: bytes | None


async def _record_failures(
    store: GenerationStore,
    stage: GenerationFailureStage,
    voice_id: str,
    dialogue_line_ids: Sequence[str | None],
    error: Exception,
    *,
    error_code: str | None = None,
    error_type: str | None = None,
) -> None:
    message = (str(error).strip() or repr(error))[:2000]
    records = [
        GenerationFailureRecord(
            id=GenerationFailureRecord.id_for(stage, voice_id, dialogue_line_id),
            stage=stage,
            voice_id=voice_id,
            dialogue_line_id=dialogue_line_id,
            error_type=error_type or type(error).__name__,
            error_code=error_code,
            error=message,
            failed_at=utc_now().isoformat(),
        )
        for dialogue_line_id in dialogue_line_ids
    ]
    await store.upsert_failures(records)
    for record in records:
        logger.warning(
            "generation_failure stage=%s voice_id=%s dialogue_line_id=%s "
            "error_type=%s error_code=%s error=%s",
            record.stage.value,
            record.voice_id,
            record.dialogue_line_id,
            record.error_type,
            record.error_code,
            record.error.replace("\r", " ").replace("\n", " "),
        )


async def _clear_failures(
    store: GenerationStore,
    stage: GenerationFailureStage,
    voice_id: str,
    dialogue_line_ids: Sequence[str | None],
) -> None:
    await store.delete_failures(
        [
            GenerationFailureRecord.id_for(stage, voice_id, dialogue_line_id)
            for dialogue_line_id in dialogue_line_ids
        ]
    )


async def _record_audio_failures(
    store: GenerationStore,
    directions: Mapping[str, DirectedLineRecord],
    custom_ids: Sequence[str],
    error: Exception,
    *,
    error_code: str | None = None,
    error_type: str | None = None,
) -> None:
    if not custom_ids:
        return
    await _record_failures(
        store,
        GenerationFailureStage.AUDIO_GENERATION,
        directions[custom_ids[0]].voice_id,
        [directions[custom_id].dialogue_line_id for custom_id in custom_ids],
        error,
        error_code=error_code,
        error_type=error_type,
    )


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

            narrator_task: asyncio.Task[GeneratedVoiceRecord] | None = None

            async def create_narrator() -> GeneratedVoiceRecord:
                try:
                    voice = await _ensure_narrator_voice(
                        inworld,
                        store,
                        provider_voices,
                    )
                except Exception as error:
                    await _record_failures(
                        store,
                        GenerationFailureStage.VOICE_CREATION,
                        NARRATOR_VOICE_ID,
                        [None],
                        error,
                    )
                    raise
                await _clear_failures(
                    store,
                    GenerationFailureStage.VOICE_CREATION,
                    NARRATOR_VOICE_ID,
                    [None],
                )
                return voice

            async def ensure_narrator() -> GeneratedVoiceRecord:
                nonlocal narrator_task
                if narrator_task is None:
                    narrator_task = asyncio.create_task(create_narrator())
                return await narrator_task

            voice_capacity = asyncio.Semaphore(VOICE_CONCURRENCY)

            async def process(workload: VoiceWorkload) -> None:
                voice_ready = False
                try:
                    async with voice_capacity:
                        await _ensure_character_voice(
                            openai,
                            inworld,
                            store,
                            workload,
                            openai_capacity,
                            provider_voices,
                            recreate=recreate_voices,
                        )
                except Exception as error:
                    await _record_failures(
                        store,
                        GenerationFailureStage.VOICE_CREATION,
                        workload.voice.voice_id,
                        [None],
                        error,
                    )
                else:
                    voice_ready = True
                    await _clear_failures(
                        store,
                        GenerationFailureStage.VOICE_CREATION,
                        workload.voice.voice_id,
                        [None],
                    )

                await _direct_workload(
                    openai,
                    store,
                    workload,
                    history_index,
                    openai_capacity,
                )
                if voice_ready:
                    await _synthesize_workload(
                        store,
                        inworld,
                        workload,
                        ensure_narrator,
                        inworld_capacity,
                    )

            await _wait_for_all([asyncio.create_task(process(workload)) for workload in workloads])

        voice_ids = [workload.voice.voice_id for workload in workloads]
        directions = await store.directed_lines(voice_ids)
        audio = await store.generated_audio_identities(voice_ids)
        failures = await store.failures(voice_ids)
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
            voice_creation_failures=sum(
                row.stage is GenerationFailureStage.VOICE_CREATION for row in failures
            ),
            dialogue_direction_failures=sum(
                row.stage is GenerationFailureStage.DIALOGUE_DIRECTION
                and (row.voice_id, row.dialogue_line_id) in selected
                for row in failures
            ),
            audio_generation_failures=sum(
                row.stage is GenerationFailureStage.AUDIO_GENERATION
                and (row.voice_id, row.dialogue_line_id) in selected
                for row in failures
            ),
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

    async def direct(line: DialogueLineRecord) -> DirectedLineRecord | None:
        source = DirectionSource(
            display_name=workload.voice.display_name,
            metadata=metadata,
            text=cast(str, line.text),
            dialogue_history=dialogue_history(history_index, line),
        )

        async def request(model: str) -> DirectionPlan:
            async with openai_capacity:
                return await create_direction(
                    openai,
                    source,
                    model=model,
                )

        try:
            plan = await request(DIRECTION_MODEL)
        except Exception:
            try:
                plan = await request(DIRECTION_FALLBACK_MODEL)
            except Exception as error:
                await _record_failures(
                    store,
                    GenerationFailureStage.DIALOGUE_DIRECTION,
                    workload.voice.voice_id,
                    [line.id],
                    error,
                )
                return None

        result = plan.result
        return DirectedLineRecord(
            id=DirectedLineRecord.id_for(workload.voice.voice_id, line.id),
            voice_id=workload.voice.voice_id,
            dialogue_line_id=line.id,
            character=(
                CharacterDirection(directed_dialogue=result.directed_dialogue)
                if result.speaker == "character"
                else None
            ),
            narrator=(
                NarratorDirection(directed_dialogue=result.directed_dialogue)
                if result.speaker == "narrator"
                else None
            ),
            created_at=utc_now().isoformat(),
        )

    for start in range(0, len(missing), DIRECTION_WRITE_BATCH_SIZE):
        results = await _wait_for_all(
            [
                asyncio.create_task(direct(line))
                for line in missing[start : start + DIRECTION_WRITE_BATCH_SIZE]
            ]
        )
        records = [record for record in results if record is not None]
        await store.upsert_directed_lines(records)
        await _clear_failures(
            store,
            GenerationFailureStage.DIALOGUE_DIRECTION,
            workload.voice.voice_id,
            [record.dialogue_line_id for record in records],
        )


async def _synthesize_workload(
    store: GenerationStore,
    inworld: InworldClient,
    workload: VoiceWorkload,
    ensure_narrator: Callable[[], Awaitable[GeneratedVoiceRecord]],
    capacity: asyncio.Semaphore,
) -> None:
    direction_rows = await store.directed_lines([workload.voice.voice_id])
    directions = {line.dialogue_line_id: line for line in direction_rows}
    directions_by_id = {line.id: line for line in direction_rows}
    existing = {
        audio.id for audio in await store.generated_audio_identities([workload.voice.voice_id])
    }
    existing.update(
        custom_id for batch in await store.running_batches() for custom_id in batch.custom_ids
    )
    pending = [
        directions[source_line.id]
        for source_line in workload.lines
        if source_line.id in directions and directions[source_line.id].id not in existing
    ]
    narrator_ready = True
    narrator_ids = [direction.id for direction in pending if direction.narrator is not None]
    if narrator_ids:
        try:
            await ensure_narrator()
        except Exception as error:
            narrator_ready = False
            await _record_audio_failures(store, directions_by_id, narrator_ids, error)

    voices = await store.generated_voices()
    items: list[BatchSynthesisItem] = []
    for direction in pending:
        if direction.narrator is not None and not narrator_ready:
            continue
        generated_voice = voices[
            workload.voice.voice_id if direction.character is not None else NARRATOR_VOICE_ID
        ]
        text = (
            direction.character.directed_dialogue
            if direction.character is not None
            else cast(NarratorDirection, direction.narrator).directed_dialogue
        )
        items.append(
            BatchSynthesisItem(
                custom_id=direction.id,
                text=tts_speakable_text(text),
                voice_id=generated_voice.inworld_voice_id,
                language_code=generated_voice.description.language_code,
            )
        )

    batches = pack_synthesis_items(items)

    async def synthesize(batch: list[BatchSynthesisItem]) -> None:
        custom_ids = [item.custom_id for item in batch]
        try:
            operation = await inworld.submit_batch(batch)
        except Exception as error:
            await _record_audio_failures(store, directions_by_id, custom_ids, error)
            return
        record = TtsBatchRecord(
            operation_name=operation.name,
            custom_ids=custom_ids,
            status=RunStatus.RUNNING,
            started_at=utc_now().isoformat(),
        )
        await store.upsert_batches([record])
        try:
            await _complete_batch(store, inworld, record, directions_by_id, voices)
        except Exception as error:
            await _record_audio_failures(store, directions_by_id, custom_ids, error)

    await _run_concurrently(
        batches,
        synthesize,
        capacity,
    )


async def _run_concurrently[Item](
    items: Sequence[Item],
    process: Callable[[Item], Awaitable[None]],
    capacity: asyncio.Semaphore,
) -> None:
    async def run(item: Item) -> None:
        async with capacity:
            await process(item)

    await _wait_for_all([asyncio.create_task(run(item)) for item in items])


async def _wait_for_all[Result](tasks: Sequence[asyncio.Task[Result]]) -> list[Result]:
    """Let every started operation settle before propagating the first failure."""
    if tasks:
        await asyncio.wait(tasks)
    return [task.result() for task in tasks]


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
        try:
            await _complete_batch(store, inworld, batch, directions, voices)
        except Exception as error:
            await _record_audio_failures(store, directions, batch.custom_ids, error)

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
) -> None:
    operation = await inworld.poll_operation(batch.operation_name)
    if operation.error is not None:
        await _record_audio_failures(
            store,
            directions,
            batch.custom_ids,
            RuntimeError(operation.error.message),
            error_code=str(operation.error.code),
            error_type="InworldOperationError",
        )
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
        return
    assert operation.response is not None, "completed Inworld batch has no result manifest"
    results = await inworld.download_results(operation.response.results_uri)
    voice_id = directions[batch.custom_ids[0]].voice_id
    existing = {audio.id for audio in await store.generated_audio_identities([voice_id])}

    failed = False
    records: list[GeneratedAudioRecord] = []
    for result in results.results:
        if result.custom_id in existing:
            continue
        direction = directions[result.custom_id]
        if result.error is not None:
            failed = True
            await _record_audio_failures(
                store,
                directions,
                [result.custom_id],
                RuntimeError(result.error.message),
                error_code=None if result.error.code is None else str(result.error.code),
                error_type="InworldBatchItemError",
            )
            continue
        if result.audio_uri is None:
            failed = True
            await _record_audio_failures(
                store,
                directions,
                [result.custom_id],
                RuntimeError("Inworld returned neither audio nor an error for this item"),
                error_type="InworldBatchItemError",
            )
            continue
        try:
            source = await inworld.download_audio(result.audio_uri)
            generated_voice = voices[
                direction.voice_id if direction.character is not None else NARRATOR_VOICE_ID
            ]
            audio = await asyncio.to_thread(encode_game_audio, source)
        except Exception as error:
            failed = True
            await _record_audio_failures(store, directions, [result.custom_id], error)
            continue
        records.append(
            GeneratedAudioRecord(
                id=direction.id,
                voice_id=direction.voice_id,
                dialogue_line_id=direction.dialogue_line_id,
                inworld_voice_id=generated_voice.inworld_voice_id,
                batch_operation_name=batch.operation_name,
                audio=audio,
                created_at=utc_now().isoformat(),
            )
        )
        if len(records) == AUDIO_WRITE_BATCH_SIZE:
            await store.upsert_generated_audio(records)
            await store.delete_failures(
                [
                    GenerationFailureRecord.id_for(
                        GenerationFailureStage.AUDIO_GENERATION,
                        record.voice_id,
                        record.dialogue_line_id,
                    )
                    for record in records
                ]
            )
            records.clear()
    status = (
        RunStatus.COMPLETE_WITH_ERRORS if failed or results.failed_items else RunStatus.COMPLETE
    )
    await store.upsert_generated_audio(records)
    await store.delete_failures(
        [
            GenerationFailureRecord.id_for(
                GenerationFailureStage.AUDIO_GENERATION,
                record.voice_id,
                record.dialogue_line_id,
            )
            for record in records
        ]
    )
    await store.upsert_batches(
        [batch.model_copy(update={"status": status, "completed_at": utc_now().isoformat()})]
    )
