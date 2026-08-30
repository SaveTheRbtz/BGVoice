"""Iterative voice design, dialogue direction, and batch speech synthesis."""

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import cast

from lancedb.expr import col, lit
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict

from bgvoice.attribution import voice_representative
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
    voice_profile_tag,
)
from bgvoice.model_types import (
    DialogueLineKind,
    GenerationFailureStage,
    ProviderGender,
    RaceId,
    RunStatus,
    VoiceProfileKind,
    utc_now,
)
from bgvoice.reader import PipelineReader
from bgvoice.reader_metadata import LabelResolver
from bgvoice.reader_stats import AttributionSnapshot
from bgvoice.storage_records import (
    CharacterDirection,
    CharacterRecord,
    DialogueLineRecord,
    DialogueRecord,
    DirectedLineRecord,
    GeneratedAudioRecord,
    GenerationFailureRecord,
    NarratorDirection,
    PortraitImageRecord,
    TtsBatchRecord,
    VoiceDescription,
    VoiceGenerationRecord,
    VoiceProfileRecord,
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
DEFAULT_NAMED_RACE_COUNT = 9
VOICE_DESIGN_SAMPLE_COUNT = 30
VOICE_DESIGN_SAMPLE_MIN_CHARS = 50

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
class GenericVoiceProfile:
    """Transient identity and presentation for one reusable provider voice."""

    gender: ProviderGender
    race_id: RaceId | None
    race_name: str | None

    @property
    def id(self) -> str:
        race = self.race_id if self.race_id is not None else "other"
        return f"generic:gender:{self.gender}:race:{race}"

    @property
    def display_name(self) -> str:
        race = self.race_name or "Other Race"
        return f"BGVoice Generic · {self.gender.title()} · {race}"

    @property
    def archetype(self) -> str:
        return f"unnamed {self.gender} {self.race_name or 'other-race'} character"


@dataclass(frozen=True, slots=True)
class VoiceEvidence:
    ability_scores: CharacterAbilityScores
    portrait_png: bytes | None
    gender: ProviderGender
    race_id: RaceId
    race: str
    race_description: str | None
    class_description: str | None


@dataclass(frozen=True, slots=True)
class VoiceWorkload:
    voice: VoiceResourceRecord
    lines: tuple[DialogueLineRecord, ...]
    ability_scores: CharacterAbilityScores
    portrait_png: bytes | None
    generic_profile: GenericVoiceProfile
    race_description: str | None
    class_description: str | None
    dialogue_samples: tuple[str, ...]


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
    by_voice: dict[str, list[str]] = {}
    for custom_id in custom_ids:
        direction = directions[custom_id]
        by_voice.setdefault(direction.voice_id, []).append(direction.dialogue_line_id)
    for voice_id, dialogue_line_ids in by_voice.items():
        await _record_failures(
            store,
            GenerationFailureStage.AUDIO_GENERATION,
            voice_id,
            dialogue_line_ids,
            error,
            error_code=error_code,
            error_type=error_type,
        )


def round_robin_lines(
    dialogues: Mapping[str, Sequence[DialogueLineRecord]],
    limit: int | None,
) -> list[DialogueLineRecord]:
    """Take unique exact source texts in deterministic DLG/state rounds."""
    assert limit is None or limit > 0, "line limit must be positive"
    groups = [
        sorted(dialogues[name], key=lambda line: (line.state_index, line.id))
        for name in sorted(dialogues)
        if dialogues[name]
    ]
    selected: list[DialogueLineRecord] = []
    seen_texts: set[str | None] = set()
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index >= len(group):
                continue
            line = group[index]
            if line.text in seen_texts:
                continue
            seen_texts.add(line.text)
            selected.append(line)
            if limit is not None and len(selected) == limit:
                return selected
    return selected


def _dialogue_samples(
    voice_id: str,
    dialogues: Mapping[str, Sequence[DialogueLineRecord]],
) -> tuple[str, ...]:
    """Choose a stable pseudo-random sample of distinct exact NPC texts."""
    texts = {
        line.text
        for lines in dialogues.values()
        for line in lines
        if line.text is not None and len(line.text.strip()) > VOICE_DESIGN_SAMPLE_MIN_CHARS
    }
    ranked = sorted(
        texts,
        key=lambda text: (sha256(f"{voice_id}\0{text}".encode()).digest(), text),
    )
    return tuple(ranked[:VOICE_DESIGN_SAMPLE_COUNT])


async def load_workloads(
    reader: PipelineReader,
    requested_voices: Sequence[str],
    lines_per_voice: int | None,
) -> list[VoiceWorkload]:
    """Resolve requested current voices and their deterministic NPC workloads."""
    attribution, dialogue_result, metadata = await asyncio.gather(
        reader.attribution_snapshot(),
        reader.dialogues_table.query().to_pydantic(DialogueRecord),
        reader.metadata_snapshot(),
    )
    assert attribution.run is not None, "voice generation requires published attribution"
    dialogue_rows = cast(list[DialogueRecord], dialogue_result)
    dialogues_by_resref = {row.resref.casefold(): row for row in dialogue_rows}
    dialogues_by_name = {row.resource_name.casefold(): row for row in dialogue_rows}
    labels = LabelResolver.from_snapshot(metadata)
    voices: list[VoiceResourceRecord] = []
    selected_voice_ids: set[str] = set()

    for requested in requested_voices:
        folded = requested.casefold()
        exact = [voice for voice in attribution.voices if voice.voice_id.casefold() == folded]
        matches = exact or [
            voice
            for voice in attribution.voices
            if folded in (voice.family_id.casefold(), voice.display_name.casefold())
        ]
        assert matches, f"voice {requested!r} did not resolve to a current resource"
        for voice in sorted(matches, key=lambda item: item.voice_id.casefold()):
            if voice.voice_id not in selected_voice_ids:
                selected_voice_ids.add(voice.voice_id)
                voices.append(voice)
    if not voices:
        return []

    dialogue_names_by_voice = {
        voice.voice_id: sorted(
            {
                dialogues_by_resref[resref.casefold()].resource_name
                for resref in voice.dialogue_resrefs
                if resref.casefold() in dialogues_by_resref
            }
        )
        for voice in voices
    }
    assert all(dialogue_names_by_voice.values()), "selected voices must have extracted dialogues"
    dialogue_names = sorted({name for names in dialogue_names_by_voice.values() for name in names})
    variant_names = sorted({name for voice in voices for name in voice.variant_resource_names})
    line_result, character_result = await asyncio.gather(
        reader.lines_table.query()
        .where(
            col("dialogue_resource_name").isin(dialogue_names)
            & (col("line_kind") == lit(DialogueLineKind.NPC))
        )
        .to_pydantic(DialogueLineRecord),
        reader.characters_table.query()
        .where(col("resource_name").isin(variant_names))
        .to_pydantic(CharacterRecord),
    )
    characters = cast(list[CharacterRecord], character_result)
    portrait_resrefs = sorted(
        {
            resref
            for character in characters
            if character.detail is not None
            for resref in (character.detail.small_portrait, character.detail.large_portrait)
            if resref is not None
        }
    )
    portraits = (
        cast(
            list[PortraitImageRecord],
            await reader.portrait_images_table.query()
            .where(col("resref").isin(portrait_resrefs))
            .to_pydantic(PortraitImageRecord),
        )
        if portrait_resrefs
        else []
    )
    lines_by_dialogue: dict[str, list[DialogueLineRecord]] = {}
    for line in cast(list[DialogueLineRecord], line_result):
        if line.text and line.text.strip():
            lines_by_dialogue.setdefault(line.dialogue_resource_name, []).append(line)
    characters_by_name = {row.resource_name.casefold(): row for row in characters}
    portraits_by_resref = {row.resref.casefold(): row.png for row in portraits}

    workloads: list[VoiceWorkload] = []
    for voice in voices:
        groups = {
            name: lines_by_dialogue.get(name, [])
            for name in dialogue_names_by_voice[voice.voice_id]
        }
        lines = tuple(round_robin_lines(groups, lines_per_voice))
        assert lines, f"voice {voice.display_name!r} has no non-empty NPC lines"
        evidence = _voice_evidence(
            voice,
            attribution,
            dialogues_by_name,
            labels,
            characters_by_name,
            portraits_by_resref,
        )
        workloads.append(
            VoiceWorkload(
                voice=voice,
                lines=lines,
                ability_scores=evidence.ability_scores,
                portrait_png=evidence.portrait_png,
                generic_profile=GenericVoiceProfile(
                    gender=evidence.gender,
                    race_id=evidence.race_id,
                    race_name=evidence.race,
                ),
                race_description=evidence.race_description,
                class_description=evidence.class_description,
                dialogue_samples=_dialogue_samples(voice.voice_id, groups),
            )
        )
    return workloads


def _common_default_race_ids(race_ids: Sequence[int]) -> frozenset[int]:
    """Select nine named race buckets; zero and NO_RACE always map to other."""
    counts = Counter(race_id for race_id in race_ids if race_id not in (0, 255))
    ranked = sorted(counts, key=lambda race_id: (-counts[race_id], race_id))
    return frozenset(ranked[:DEFAULT_NAMED_RACE_COUNT])


def _bucket_generic_profiles(workloads: Sequence[VoiceWorkload]) -> list[VoiceWorkload]:
    """Apply the bounded fallback taxonomy only to generic profile generation."""
    common_races = _common_default_race_ids(
        [
            workload.generic_profile.race_id
            for workload in workloads
            if workload.generic_profile.race_id is not None
        ]
    )
    return [
        replace(
            workload,
            generic_profile=replace(
                workload.generic_profile,
                race_id=(
                    workload.generic_profile.race_id
                    if workload.generic_profile.race_id in common_races
                    else None
                ),
                race_name=(
                    workload.generic_profile.race_name
                    if workload.generic_profile.race_id in common_races
                    else None
                ),
            ),
        )
        for workload in workloads
    ]


async def _sparse_voice_ids(reader: PipelineReader, max_lines: int) -> list[str]:
    assert max_lines > 0, "sparse voice line limit must be positive"
    attribution, dialogue_result, line_result = await asyncio.gather(
        reader.attribution_snapshot(),
        reader.dialogues_table.query().to_pydantic(DialogueRecord),
        reader.lines_table.query()
        .where(col("line_kind") == lit(DialogueLineKind.NPC))
        .to_pydantic(DialogueLineRecord),
    )
    assert attribution.run is not None, "generic voice generation requires published attribution"
    dialogues = {
        row.resref.casefold(): row.resource_name
        for row in cast(list[DialogueRecord], dialogue_result)
    }
    counts = Counter(
        line.dialogue_resource_name
        for line in cast(list[DialogueLineRecord], line_result)
        if line.text and line.text.strip()
    )
    return [
        voice.voice_id
        for voice in attribution.voices
        if 0
        < sum(
            counts[name]
            for name in {
                dialogues[resref.casefold()]
                for resref in voice.dialogue_resrefs
                if resref.casefold() in dialogues
            }
        )
        <= max_lines
    ]


def _voice_evidence(
    voice: VoiceResourceRecord,
    attribution: AttributionSnapshot,
    dialogues: dict[str, DialogueRecord],
    labels: LabelResolver,
    characters_by_name: Mapping[str, CharacterRecord],
    portraits: Mapping[str, bytes],
) -> VoiceEvidence:
    """Choose the most-used CRE and return its ability scores and best portrait."""
    characters = [
        characters_by_name[name.casefold()]
        for name in voice.variant_resource_names
        if name.casefold() in characters_by_name
    ]
    assert characters, f"voice {voice.display_name!r} has no extracted character variants"
    representative = min(
        (character for character in characters if character.detail is not None),
        key=lambda character: _representative_priority(
            character,
            attribution,
            dialogues,
            portraits,
        ),
    )
    detail = representative.detail
    assert detail is not None
    portrait = next(
        (
            portraits[resref.casefold()]
            for resref in (detail.large_portrait, detail.small_portrait)
            if resref is not None and resref.casefold() in portraits
        ),
        None,
    )
    attributes = detail.base_attributes
    default_detail = voice_representative(characters).detail
    assert default_detail is not None
    ability_scores = CharacterAbilityScores(
        strength=attributes.strength,
        strength_bonus=attributes.strength_bonus,
        intelligence=attributes.intelligence,
        wisdom=attributes.wisdom,
        dexterity=attributes.dexterity,
        constitution=attributes.constitution,
        charisma=attributes.charisma,
    )
    return VoiceEvidence(
        ability_scores=ability_scores,
        portrait_png=portrait,
        gender=(
            voice.gender
            if voice.gender is not None
            else ProviderGender.from_engine_id(default_detail.gender_id)
        ),
        race_id=RaceId(default_detail.race_id),
        race=labels.race_label(default_detail.race_id),
        race_description=labels.race_description(default_detail.race_id),
        class_description=labels.class_description(default_detail.class_id),
    )


def _representative_priority(
    character: CharacterRecord,
    attribution: AttributionSnapshot,
    dialogues: dict[str, DialogueRecord],
    portraits: Mapping[str, bytes],
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
    """Generate selected character voices and every missing downstream artifact."""
    return await _run_generation(
        database_path,
        requested_voices,
        lines_per_voice,
        openai_api_key,
        inworld_api_key,
        recreate_voices=recreate_voices,
        use_generic_profiles=False,
    )


async def _run_generation(
    database_path: Path,
    requested_voices: Sequence[str],
    lines_per_voice: int | None,
    openai_api_key: str,
    inworld_api_key: str,
    *,
    recreate_voices: bool,
    use_generic_profiles: bool,
) -> GenerationSummary:
    """Run all missing generation stages and persist each completed unit."""
    import httpx

    reader = await PipelineReader.open(database_path)
    store = await GenerationStore.open(database_path)
    try:
        workloads = await load_workloads(reader, requested_voices, lines_per_voice)
        if use_generic_profiles:
            workloads = _bucket_generic_profiles(workloads)
        history_index = await DialogueHistoryIndex.load(reader)
        async with (
            AsyncOpenAI(api_key=openai_api_key) as openai,
            httpx.AsyncClient(
                timeout=httpx.Timeout(120),
                transport=httpx.AsyncHTTPTransport(retries=3),
            ) as http,
        ):
            inworld = InworldClient(http, inworld_api_key)
            openai_capacity = asyncio.Semaphore(OPENAI_CONCURRENCY)
            inworld_capacity = asyncio.Semaphore(INWORLD_BATCH_CONCURRENCY)
            await _resume_batches(store, inworld, inworld_capacity)
            running_audio_ids = {
                custom_id
                for batch in await store.running_batches()
                for custom_id in batch.custom_ids
            }
            provider_voices = _provider_voice_catalog(await inworld.list_voices())

            async def create_generic(generic: GenericVoiceProfile) -> VoiceProfileRecord | None:
                profile_id = generic.id
                try:
                    profile = await _ensure_generic_profile(
                        openai,
                        inworld,
                        store,
                        generic,
                        openai_capacity,
                        provider_voices,
                    )
                except Exception as error:
                    await _record_failures(
                        store,
                        GenerationFailureStage.VOICE_CREATION,
                        profile_id,
                        [None],
                        error,
                    )
                    return None
                await _clear_failures(
                    store,
                    GenerationFailureStage.VOICE_CREATION,
                    profile_id,
                    [None],
                )
                return profile

            generic_tasks = (
                {
                    profile_id: asyncio.create_task(create_generic(generic))
                    for profile_id, generic in {
                        workload.generic_profile.id: workload.generic_profile
                        for workload in workloads
                    }.items()
                }
                if use_generic_profiles
                else {}
            )

            narrator_task: asyncio.Task[VoiceProfileRecord] | None = None

            async def create_narrator() -> VoiceProfileRecord:
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

            async def ensure_narrator() -> VoiceProfileRecord:
                nonlocal narrator_task
                if narrator_task is None:
                    narrator_task = asyncio.create_task(create_narrator())
                return await narrator_task

            voice_capacity = asyncio.Semaphore(VOICE_CONCURRENCY)

            async def process(workload: VoiceWorkload) -> VoiceWorkload | None:
                async with voice_capacity:
                    voice_ready = False
                    try:
                        await _ensure_character_voice(
                            openai,
                            inworld,
                            store,
                            workload,
                            openai_capacity,
                            provider_voices,
                            recreate=recreate_voices,
                            generic_profile=(
                                generic_tasks[workload.generic_profile.id]
                                if use_generic_profiles
                                else None
                            ),
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
                        if not use_generic_profiles:
                            await _synthesize_workloads(
                                store,
                                inworld,
                                [workload],
                                ensure_narrator,
                                inworld_capacity,
                                running_audio_ids,
                            )
                        return workload
                    return None

            processed = await _wait_for_all(
                [asyncio.create_task(process(workload)) for workload in workloads]
            )
            if use_generic_profiles:
                ready = [workload for workload in processed if workload is not None]
                if ready:
                    await _synthesize_workloads(
                        store,
                        inworld,
                        ready,
                        ensure_narrator,
                        inworld_capacity,
                        running_audio_ids,
                    )
                await _wait_for_all(list(generic_tasks.values()))

        voice_ids = [workload.voice.voice_id for workload in workloads]
        directions = await store.directed_lines(voice_ids)
        audio = await store.generated_audio_identities(voice_ids)
        failures = await store.failures(voice_ids)
        selected = {
            (workload.voice.voice_id, line.id) for workload in workloads for line in workload.lines
        }
        summary = GenerationSummary(
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
        await store.optimize()
        return summary
    finally:
        reader.close()
        store.close()


async def generate_defaults(
    database_path: Path,
    max_lines: int,
    openai_api_key: str,
    inworld_api_key: str,
) -> GenerationSummary:
    """Generate every sparse canonical voice through shared gender/race defaults."""
    reader = await PipelineReader.open(database_path)
    try:
        voice_ids = await _sparse_voice_ids(reader, max_lines)
    finally:
        reader.close()
    return await _run_generation(
        database_path,
        voice_ids,
        None,
        openai_api_key,
        inworld_api_key,
        recreate_voices=False,
        use_generic_profiles=True,
    )


async def _ensure_character_voice(
    openai: AsyncOpenAI,
    inworld: InworldClient,
    store: GenerationStore,
    workload: VoiceWorkload,
    openai_capacity: asyncio.Semaphore,
    provider_voices: Mapping[str, PublishedVoice],
    *,
    recreate: bool,
    generic_profile: Awaitable[VoiceProfileRecord | None] | None = None,
) -> VoiceProfileRecord:
    voice_id = workload.voice.voice_id
    existing = await store.generated_voice(voice_id)
    if recreate:
        if existing is not None and existing.kind is VoiceProfileKind.DEDICATED:
            await store.assert_exclusive_profile_assignment(existing.profile_id, voice_id)
            await inworld.delete_voice(existing.inworld_voice_id)
        await store.delete_voice_generation(voice_id)
        if existing is not None and existing.kind is VoiceProfileKind.DEDICATED:
            await store.delete_voice_profile(existing.profile_id)
        existing = None
    matching_existing = existing is not None and (
        (generic_profile is not None and existing.profile_id == workload.generic_profile.id)
        or (
            generic_profile is None
            and existing.kind is VoiceProfileKind.DEDICATED
            and (workload.voice.gender is None or existing.gender is workload.voice.gender)
        )
    )
    if matching_existing:
        assert existing is not None
        if existing.kind is VoiceProfileKind.GENERIC:
            return existing
        if await store.profile_voice_ids(existing.profile_id) == {voice_id}:
            return existing
    if generic_profile is not None:
        profile = await generic_profile
        assert profile is not None, f"generic profile unavailable for {voice_id}"
        await store.assign_voice(
            VoiceGenerationRecord(voice_id=voice_id, profile_id=profile.profile_id)
        )
        return profile

    profile_id = await _dedicated_profile_id(store, voice_id)
    profile = await store.voice_profile(profile_id)
    if profile is None and not recreate:
        profile = await _reuse_existing_profile(
            store,
            provider_voices,
            profile_id,
            workload.generic_profile.gender,
            None,
            VoiceProfileKind.DEDICATED,
        )
    if profile is not None:
        await store.assign_voice(
            VoiceGenerationRecord(voice_id=voice_id, profile_id=profile.profile_id)
        )
        return profile

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
                race_description=workload.race_description,
                class_description=workload.class_description,
                dialogue_samples=workload.dialogue_samples,
            ),
            model=VOICE_DESIGN_MODEL,
        )
    profile = await _publish_profile(
        inworld,
        store,
        profile_id,
        workload.generic_profile.gender,
        None,
        VoiceProfileKind.DEDICATED,
        workload.voice.display_name,
        description=plan.profile.render(),
        language_code=plan.language_code,
        preview_text=plan.preview_text,
    )
    await store.assign_voice(
        VoiceGenerationRecord(voice_id=voice_id, profile_id=profile.profile_id)
    )
    return profile


async def _dedicated_profile_id(store: GenerationStore, voice_id: str) -> str:
    """Keep legacy profile IDs unless another logical voice already owns one."""
    profile = await store.voice_profile(voice_id)
    assigned_voice_ids = await store.profile_voice_ids(voice_id)
    if profile is None:
        assert not assigned_voice_ids, f"voice profile {voice_id!r} is missing"
        return voice_id
    if profile.kind is VoiceProfileKind.DEDICATED and not (assigned_voice_ids - {voice_id}):
        return voice_id

    profile_id = f"dedicated:{voice_id}"
    profile = await store.voice_profile(profile_id)
    assigned_voice_ids = await store.profile_voice_ids(profile_id)
    assert profile is None or profile.kind is VoiceProfileKind.DEDICATED, (
        f"fallback voice profile {profile_id!r} is not dedicated"
    )
    assert not (assigned_voice_ids - {voice_id}), (
        f"fallback voice profile {profile_id!r} is already assigned to "
        f"{sorted(assigned_voice_ids - {voice_id})}"
    )
    return profile_id


async def _ensure_generic_profile(
    openai: AsyncOpenAI,
    inworld: InworldClient,
    store: GenerationStore,
    generic: GenericVoiceProfile,
    openai_capacity: asyncio.Semaphore,
    provider_voices: Mapping[str, PublishedVoice],
) -> VoiceProfileRecord:
    profile_id = generic.id
    existing = await store.voice_profile(profile_id)
    if existing is not None:
        return existing
    reused = await _reuse_existing_profile(
        store,
        provider_voices,
        profile_id,
        generic.gender,
        generic.race_id,
        VoiceProfileKind.GENERIC,
    )
    if reused is not None:
        return reused
    race = generic.race_name or "other-race"
    async with openai_capacity:
        plan = await create_voice_design_plan(
            openai,
            VoiceDesignSource(
                display_name=generic.archetype,
                metadata=(
                    "Reusable fallback for characters with very little dialogue.\n"
                    f"Gender: {generic.gender}\nRace: {race}"
                ),
                race_description=None,
                class_description=None,
                biography=None,
                dialogue_samples=(),
                ability_scores=None,
                portrait_png=None,
            ),
            model=VOICE_DESIGN_MODEL,
        )
    return await _publish_profile(
        inworld,
        store,
        profile_id,
        generic.gender,
        generic.race_id,
        VoiceProfileKind.GENERIC,
        generic.display_name,
        description=plan.profile.render(),
        language_code=plan.language_code,
        preview_text=plan.preview_text,
    )


def _metadata_and_biography(prompt: str) -> tuple[str, str | None]:
    metadata, separator, biography = prompt.partition("\n\nBiography:\n")
    cleaned_biography = biography.strip() if separator else ""
    return metadata.strip(), cleaned_biography or None


async def _publish_profile(
    inworld: InworldClient,
    store: GenerationStore,
    profile_id: str,
    gender: ProviderGender | None,
    race_id: RaceId | None,
    kind: VoiceProfileKind,
    display_name: str,
    *,
    description: str,
    language_code: str,
    preview_text: str,
) -> VoiceProfileRecord:
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
        tags=("bgvoice", voice_profile_tag(profile_id)),
    )
    if gender is not None:
        published = await inworld.update_voice(
            published.voice_id,
            display_name=display_name,
            description=description,
            tags=("bgvoice", voice_profile_tag(profile_id)),
            gender=gender,
        )
    record = VoiceProfileRecord(
        profile_id=profile_id,
        kind=kind,
        gender=gender,
        race_id=race_id,
        inworld_voice_id=published.voice_id,
        description=VoiceDescription(text=description, language_code=language_code),
        created_at=utc_now().isoformat(),
    )
    await store.upsert_voice_profiles([record])
    return record


async def _ensure_narrator_voice(
    inworld: InworldClient,
    store: GenerationStore,
    provider_voices: Mapping[str, PublishedVoice],
) -> VoiceProfileRecord:
    existing = await store.generated_voice(NARRATOR_VOICE_ID)
    if existing is not None:
        return existing
    reused = await _reuse_existing_profile(
        store,
        provider_voices,
        NARRATOR_VOICE_ID,
        ProviderGender.MALE,
        None,
        VoiceProfileKind.DEDICATED,
    )
    if reused is not None:
        await store.assign_voice(
            VoiceGenerationRecord(
                voice_id=NARRATOR_VOICE_ID,
                profile_id=reused.profile_id,
            )
        )
        return reused
    profile = await _publish_profile(
        inworld,
        store,
        NARRATOR_VOICE_ID,
        ProviderGender.MALE,
        None,
        VoiceProfileKind.DEDICATED,
        _NARRATOR_DISPLAY_NAME,
        description=_NARRATOR_DESCRIPTION,
        language_code="en-GB",
        preview_text=_NARRATOR_PREVIEW,
    )
    await store.assign_voice(
        VoiceGenerationRecord(voice_id=NARRATOR_VOICE_ID, profile_id=profile.profile_id)
    )
    return profile


async def _reuse_existing_profile(
    store: GenerationStore,
    provider_voices: Mapping[str, PublishedVoice],
    profile_id: str,
    gender: ProviderGender | None,
    race_id: RaceId | None,
    kind: VoiceProfileKind,
) -> VoiceProfileRecord | None:
    voice = provider_voices.get(voice_profile_tag(profile_id))
    if voice is None:
        return None
    language = voice.language_code or voice.legacy_language_code
    assert language is not None, f"Inworld voice {voice.voice_id!r} has no language"
    parts = language.replace("_", "-").split("-")
    language_code = "-".join((parts[0].lower(), *(part.upper() for part in parts[1:])))
    record = VoiceProfileRecord(
        profile_id=profile_id,
        kind=kind,
        gender=gender,
        race_id=race_id,
        inworld_voice_id=voice.voice_id,
        description=VoiceDescription(text=voice.description, language_code=language_code),
        created_at=utc_now().isoformat(),
    )
    await store.upsert_voice_profiles([record])
    return record


def _provider_voice_catalog(voices: Sequence[PublishedVoice]) -> dict[str, PublishedVoice]:
    catalog: dict[str, PublishedVoice] = {}
    for voice in voices:
        profile_tags = [tag for tag in voice.tags if tag.startswith("bgvoice-id:")]
        assert len(profile_tags) <= 1, f"Inworld voice {voice.voice_id!r} has multiple BGVoice IDs"
        if profile_tags:
            profile_tag = profile_tags[0]
            assert profile_tag not in catalog, f"duplicate Inworld profile tag {profile_tag!r}"
            catalog[profile_tag] = voice
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
        try:
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
                plan = await request(DIRECTION_FALLBACK_MODEL)

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
        except Exception as error:
            await _record_failures(
                store,
                GenerationFailureStage.DIALOGUE_DIRECTION,
                workload.voice.voice_id,
                [line.id],
                error,
            )
            return None

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


async def _synthesize_workloads(
    store: GenerationStore,
    inworld: InworldClient,
    workloads: Sequence[VoiceWorkload],
    ensure_narrator: Callable[[], Awaitable[VoiceProfileRecord]],
    capacity: asyncio.Semaphore,
    running_audio_ids: set[str],
) -> None:
    voice_ids = [workload.voice.voice_id for workload in workloads]
    direction_rows = await store.directed_lines(voice_ids)
    directions_by_id = {line.id: line for line in direction_rows}
    existing = {audio.id for audio in await store.generated_audio_identities(voice_ids)}
    existing.update(running_audio_ids)
    pending = [
        directions_by_id[direction_id]
        for workload in workloads
        for source_line in workload.lines
        if (direction_id := DirectedLineRecord.id_for(workload.voice.voice_id, source_line.id))
        in directions_by_id
        and direction_id not in existing
    ]
    narrator_ready = True
    narrator_ids = [direction.id for direction in pending if direction.narrator is not None]
    if narrator_ids:
        try:
            await ensure_narrator()
        except Exception as error:
            narrator_ready = False
            await _record_audio_failures(store, directions_by_id, narrator_ids, error)

    needed_voice_ids = set(voice_ids)
    if narrator_ids and narrator_ready:
        needed_voice_ids.add(NARRATOR_VOICE_ID)
    voices = await store.generated_voices(sorted(needed_voice_ids))
    items: list[BatchSynthesisItem] = []
    for direction in pending:
        if direction.narrator is not None and not narrator_ready:
            continue
        generated_voice = voices[
            direction.voice_id if direction.character is not None else NARRATOR_VOICE_ID
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
    voices: Mapping[str, VoiceProfileRecord],
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
    voice_ids = sorted({directions[custom_id].voice_id for custom_id in batch.custom_ids})
    existing = {audio.id for audio in await store.generated_audio_identities(voice_ids)}

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
