"""Typed, read-only LanceDB queries for pipeline inspection."""

import asyncio
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Literal, Protocol, cast

import lancedb
from lancedb.db import AsyncConnection
from lancedb.expr import col, lit
from lancedb.query import (
    ColumnOrdering,
)
from lancedb.table import AsyncTable
from pydantic import Field

from bgvoice.model_types import (
    AttributionPublicationStatus,
    DetailStatus,
    DialogueLineKind,
    GenerationFailureStage,
    IdentifierKind,
    RunKind,
    RunStatus,
)
from bgvoice.reader_generation import GenerationSnapshot
from bgvoice.reader_metadata import (
    LabelResolver,
    MetadataSnapshot,
    class_rows,
    fts_scores,
    identifier_symbols,
    identifier_value_scores,
    kit_rows,
    race_rows,
    sound_slot_group_names,
)
from bgvoice.reader_models import (
    SIMPLE_IDENTIFIER_KINDS,
    CharacterPage,
    CharacterQuery,
    ClassPage,
    ClassQuery,
    ClassSort,
    DialogueLinePage,
    DialoguePage,
    DialogueQuery,
    IdentifierPage,
    IdentifierQuery,
    IdentifierRow,
    IdentifierSort,
    KitPage,
    KitQuery,
    KitSort,
    LineQuery,
    PipelineStats,
    RacePage,
    RaceQuery,
    RaceSort,
    ReadableItemPage,
    ReadableItemQuery,
    ReadableItemRow,
    ReadableItemSort,
    SortDirection,
    SoundPage,
    SoundQuery,
    SoundRow,
    TransitionPage,
    TransitionQuery,
    VoicePage,
    VoiceQuery,
)
from bgvoice.reader_query import (
    browse_order,
    child_generation_predicate,
    combine,
    count_rows,
    ordering,
    page_count,
    page_items,
    records_all,
    records_page,
    search_tokens,
)
from bgvoice.reader_stats import (
    AttributionSnapshot,
    StatsTableCounts,
    pipeline_stats,
)
from bgvoice.reader_views import (
    character_row,
    dialogue_line_row,
    dialogue_row,
    transition_row,
    voice_row,
)
from bgvoice.storage_records import (
    CampaignDefinitionRecord,
    CampaignResourceBindingRecord,
    CharacterAttributionRecord,
    CharacterRecord,
    CharacterSoundRecord,
    ClassTextRecord,
    DialogueLineRecord,
    DialogueRecord,
    DialogueTransitionRecord,
    ExtractionRunRecord,
    FavoredEnemyRecord,
    IdentifierDefinitionRecord,
    KitDefinitionRecord,
    RaceTextRecord,
    ReadableItemRecord,
    SoundSlotGroupRecord,
    VoiceResourceRecord,
)
from bgvoice.storage_schema import TABLE_MODELS


class _CharacterSearchResult(CharacterRecord):
    score: float = Field(alias="_score")


class _DialogueSearchResult(DialogueRecord):
    score: float = Field(alias="_score")


class _VoiceSearchResult(VoiceResourceRecord):
    score: float = Field(alias="_score")


class _LineSearchResult(DialogueLineRecord):
    score: float = Field(alias="_score")


@dataclass(frozen=True, slots=True)
class PipelineReader:
    """Strongly consistent typed reads over one local LanceDB database."""

    path: Path
    _connection: AsyncConnection
    characters_table: AsyncTable
    character_sounds_table: AsyncTable
    portrait_images_table: AsyncTable
    character_dialogues_table: AsyncTable
    voices_table: AsyncTable
    voice_profiles_table: AsyncTable
    voice_generations_table: AsyncTable
    directed_lines_table: AsyncTable
    generated_audio_table: AsyncTable
    tts_batches_table: AsyncTable
    generation_failures_table: AsyncTable
    dialogues_table: AsyncTable
    lines_table: AsyncTable
    transitions_table: AsyncTable
    runs_table: AsyncTable
    identifiers_table: AsyncTable
    campaigns_table: AsyncTable
    bindings_table: AsyncTable
    character_resource_links_table: AsyncTable
    interaction_rules_table: AsyncTable
    soundset_lines_table: AsyncTable
    sound_slot_groups_table: AsyncTable
    favored_enemies_table: AsyncTable
    happiness_rules_table: AsyncTable
    banter_timing_settings_table: AsyncTable
    engine_strings_table: AsyncTable
    race_texts_table: AsyncTable
    class_texts_table: AsyncTable
    kits_table: AsyncTable
    readable_items_table: AsyncTable

    @classmethod
    async def open(cls, path: Path) -> PipelineReader:
        resolved_path = path.expanduser().resolve()
        assert resolved_path.is_dir(), f"pipeline database does not exist: {resolved_path}"
        connection = await lancedb.connect_async(
            resolved_path,
            read_consistency_interval=timedelta(0),
        )
        names = tuple(TABLE_MODELS)
        table_names = frozenset((await connection.list_tables(limit=None)).tables)
        missing = frozenset(names) - table_names
        assert not missing, f"pipeline database is missing tables: {sorted(missing)}"
        opened = await asyncio.gather(*(connection.open_table(name) for name in names))
        tables = dict(zip(names, opened, strict=True))
        return cls(
            resolved_path,
            connection,
            tables["characters"],
            tables["character_sounds"],
            tables["portrait_images"],
            tables["character_dialogues"],
            tables["voice_resources"],
            tables["voice_profiles"],
            tables["voice_generations"],
            tables["directed_lines"],
            tables["generated_audio"],
            tables["tts_batches"],
            tables["generation_failures"],
            tables["dialogues"],
            tables["dialogue_lines"],
            tables["dialogue_transitions"],
            tables["extraction_runs"],
            tables["identifier_definitions"],
            tables["campaigns"],
            tables["campaign_resource_bindings"],
            tables["character_resource_links"],
            tables["interaction_rules"],
            tables["soundset_lines"],
            tables["sound_slot_groups"],
            tables["favored_enemies"],
            tables["happiness_rules"],
            tables["banter_timing_settings"],
            tables["engine_strings"],
            tables["race_texts"],
            tables["class_texts"],
            tables["kits"],
            tables["readable_items"],
        )

    def close(self) -> None:
        self._connection.close()

    async def metadata_snapshot(self) -> MetadataSnapshot:
        rows = await asyncio.gather(
            self.identifiers_table.query().to_pydantic(IdentifierDefinitionRecord),
            self.campaigns_table.query().to_pydantic(CampaignDefinitionRecord),
            self.bindings_table.query().to_pydantic(CampaignResourceBindingRecord),
            self.race_texts_table.query().to_pydantic(RaceTextRecord),
            self.class_texts_table.query().to_pydantic(ClassTextRecord),
            self.kits_table.query().to_pydantic(KitDefinitionRecord),
            self.favored_enemies_table.query().to_pydantic(FavoredEnemyRecord),
        )
        return MetadataSnapshot(
            identifiers=cast(list[IdentifierDefinitionRecord], rows[0]),
            campaigns=cast(list[CampaignDefinitionRecord], rows[1]),
            bindings=cast(list[CampaignResourceBindingRecord], rows[2]),
            race_texts=cast(list[RaceTextRecord], rows[3]),
            class_texts=cast(list[ClassTextRecord], rows[4]),
            kits=cast(list[KitDefinitionRecord], rows[5]),
            favored_enemies=cast(list[FavoredEnemyRecord], rows[6]),
        )

    async def attribution_snapshot(self) -> AttributionSnapshot:
        runs = cast(
            list[ExtractionRunRecord],
            await self.runs_table.query().to_pydantic(ExtractionRunRecord),
        )
        completed = [
            run
            for run in runs
            if run.run_kind is RunKind.ATTRIBUTION and run.status is RunStatus.COMPLETE
        ]
        if not completed:
            return _empty_attribution_snapshot(AttributionPublicationStatus.MISSING)
        run = max(completed, key=_completed_run_order)
        latest_inputs = {
            kind: _latest_run_id(runs, kind)
            for kind in (RunKind.CHARACTERS, RunKind.DIALOGUES, RunKind.METADATA)
        }
        if latest_inputs != {
            RunKind.CHARACTERS: run.character_input_run_id,
            RunKind.DIALOGUES: run.dialogue_input_run_id,
            RunKind.METADATA: run.metadata_input_run_id,
        }:
            return _empty_attribution_snapshot(AttributionPublicationStatus.STALE)

        attribution_rows, voice_rows = await asyncio.gather(
            self.character_dialogues_table.query()
            .where(col("run_id") == lit(run.id))
            .to_pydantic(CharacterAttributionRecord),
            self.voices_table.query()
            .where(col("run_id") == lit(run.id))
            .to_pydantic(VoiceResourceRecord),
        )
        attributions = cast(list[CharacterAttributionRecord], attribution_rows)
        voices = cast(list[VoiceResourceRecord], voice_rows)
        return _published_attribution(run, attributions, voices)

    async def generation_snapshot(
        self,
        attribution: AttributionSnapshot | None = None,
    ) -> GenerationSnapshot:
        current = attribution or await self.attribution_snapshot()
        return await GenerationSnapshot.load(
            self.voice_profiles_table,
            self.voice_generations_table,
            self.directed_lines_table,
            self.generated_audio_table,
            self.tts_batches_table,
            current.voices,
        )

    async def stats(self) -> PipelineStats:
        character_rows, dialogue_rows, metadata = await asyncio.gather(
            self.characters_table.query().to_pydantic(CharacterRecord),
            self.dialogues_table.query().to_pydantic(DialogueRecord),
            self.metadata_snapshot(),
        )
        characters = cast(list[CharacterRecord], character_rows)
        dialogues = cast(list[DialogueRecord], dialogue_rows)
        attribution = await self.attribution_snapshot()
        generation = await self.generation_snapshot(attribution)
        return pipeline_stats(
            self.path,
            characters,
            dialogues,
            metadata,
            attribution,
            await self._stats_table_counts(characters, dialogues, attribution, generation),
        )

    async def _stats_table_counts(
        self,
        characters: list[CharacterRecord],
        dialogues: list[DialogueRecord],
        attribution: AttributionSnapshot,
        generation: GenerationSnapshot,
    ) -> StatsTableCounts:
        character_children = child_generation_predicate(
            "character_resource_name",
            (
                (row.resource_name, row.extraction.run_id)
                for row in characters
                if row.extraction.status is DetailStatus.COMPLETE
            ),
        )
        dialogue_children = child_generation_predicate(
            "dialogue_resource_name",
            (
                (row.resource_name, row.extraction.run_id)
                for row in dialogues
                if row.extraction.status is DetailStatus.COMPLETE
            ),
        )
        counts = await asyncio.gather(
            self.readable_items_table.count_rows(),
            count_rows(self.character_sounds_table, character_children),
            self.soundset_lines_table.count_rows(),
            count_rows(self.lines_table, dialogue_children),
            count_rows(self.transitions_table, dialogue_children),
            self.character_resource_links_table.count_rows(),
            self.interaction_rules_table.count_rows(),
            self.engine_strings_table.count_rows(),
            self.sound_slot_groups_table.count_rows(),
            self.favored_enemies_table.count_rows(),
            self.happiness_rules_table.count_rows(),
            self.banter_timing_settings_table.count_rows(),
        )
        failure_counts = dict(
            zip(
                GenerationFailureStage,
                await asyncio.gather(
                    *(
                        count_rows(
                            self.generation_failures_table,
                            col("stage") == lit(stage.value),
                        )
                        for stage in GenerationFailureStage
                    )
                ),
                strict=True,
            )
        )
        return StatsTableCounts(
            *counts,
            *generation.pipeline_counts(attribution.voices),
            *(
                failure_counts[stage]
                for stage in (
                    GenerationFailureStage.VOICE_CREATION,
                    GenerationFailureStage.DIALOGUE_DIRECTION,
                    GenerationFailureStage.AUDIO_GENERATION,
                )
            ),
        )

    async def characters(self, query: CharacterQuery) -> CharacterPage:
        tokens = search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "serialized_size")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        matches, dialogue_rows, metadata = await asyncio.gather(
            records_all(
                table=self.characters_table,
                model=CharacterRecord,
                search_model=_CharacterSearchResult,
                tokens=tokens,
                predicate=None,
                key_of=lambda row: row.resource_name,
                score_of=lambda row: row.score,
            ),
            self.dialogues_table.query().to_pydantic(DialogueRecord),
            self.metadata_snapshot(),
        )
        records, scores = matches
        attribution = await self.attribution_snapshot()
        dialogues = {
            row.resource_name.casefold(): row for row in cast(list[DialogueRecord], dialogue_rows)
        }
        labels = LabelResolver.from_snapshot(metadata)
        rows = [
            character_row(
                record,
                attribution.by_character.get(record.resource_name.casefold()),
                attribution.voice_by_character.get(record.resource_name.casefold()),
                dialogues,
                labels,
            )
            for record in records
        ]
        rows = _filter_value(rows, query.status, lambda row, value: row.detail_status is value)
        rows = _filter_value(rows, query.source_kind, lambda row, value: row.source_kind is value)
        rows = _filter_value(rows, query.gender_id, lambda row, value: row.gender_id == value)
        rows = _filter_value(rows, query.race_id, lambda row, value: row.race_id == value)
        rows = _filter_value(rows, query.class_id, lambda row, value: row.class_id == value)
        rows = _filter_value(
            rows,
            query.attribution_status,
            lambda row, value: row.attribution_status is value,
        )
        rows = _filter_value(
            rows,
            query.has_dialog,
            lambda row, value: (row.dialog_resref is not None) is value,
        )
        rows = browse_order(rows, sort, direction, scores, lambda row: row.resource_name)

        return CharacterPage(
            items=page_items(rows, query),
            page=query.page,
            page_size=query.page_size,
            total=len(rows),
            page_count=page_count(len(rows), query.page_size),
            sort=sort,
            direction=direction,
        )

    async def dialogues(self, query: DialogueQuery) -> DialoguePage:
        tokens = search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "dialogue_line_count")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        records, scores = await records_all(
            table=self.dialogues_table,
            model=DialogueRecord,
            search_model=_DialogueSearchResult,
            tokens=tokens,
            predicate=None,
            key_of=lambda row: row.resource_name,
            score_of=lambda row: row.score,
        )
        attribution = await self.attribution_snapshot()
        generation = await self.generation_snapshot(attribution)
        directed_counts, audio_counts = generation.dialogue_counts()
        rows = [
            dialogue_row(
                record,
                attribution.character_count_by_dialogue[record.resource_name.casefold()],
                directed_counts[record.resource_name.casefold()],
                audio_counts[record.resource_name.casefold()],
            )
            for record in records
        ]
        rows = _filter_value(rows, query.status, lambda row, value: row.detail_status is value)
        rows = _filter_value(rows, query.source_kind, lambda row, value: row.source_kind is value)
        rows = _filter_value(
            rows,
            query.attributed,
            lambda row, value: (row.character_count > 0) is value,
        )
        rows = browse_order(rows, sort, direction, scores, lambda row: row.resource_name)

        return DialoguePage(
            items=page_items(rows, query),
            page=query.page,
            page_size=query.page_size,
            total=len(rows),
            page_count=page_count(len(rows), query.page_size),
            sort=sort,
            direction=direction,
        )

    async def lines(self, query: LineQuery) -> DialogueLinePage:
        dialogue_rows = cast(
            list[DialogueRecord],
            await self.dialogues_table.query().to_pydantic(DialogueRecord),
        )
        attribution = await self.attribution_snapshot()
        generation = await self.generation_snapshot(attribution)
        dialogues = {row.resource_name.casefold(): row for row in dialogue_rows}
        allowed_dialogues = [
            row for row in dialogues.values() if row.extraction.status is DetailStatus.COMPLETE
        ]
        allowed_dialogues = _filter_value(
            allowed_dialogues,
            query.source_kind,
            lambda row, value: row.source.kind is value,
        )
        if query.dialogue_resource_name is not None:
            dialogue_name = query.dialogue_resource_name.casefold()
            allowed_dialogues = [
                row for row in allowed_dialogues if row.resource_name.casefold() == dialogue_name
            ]
        if query.voice_id is not None:
            voice_id = query.voice_id.casefold()
            voice = next(
                (row for row in attribution.voices if row.voice_id.casefold() == voice_id),
                None,
            )
            voice_dialogues = (
                set() if voice is None else {resref.casefold() for resref in voice.dialogue_resrefs}
            )
            allowed_dialogues = [
                row for row in allowed_dialogues if row.resref.casefold() in voice_dialogues
            ]
        allowed_dialogues = _filter_value(
            allowed_dialogues,
            query.attributed,
            lambda row, value: (
                (attribution.character_count_by_dialogue[row.resource_name.casefold()] > 0) is value
            ),
        )
        tokens = search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "serialized_size")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        child_generation = child_generation_predicate(
            "dialogue_resource_name",
            (
                (dialogue.resource_name, dialogue.extraction.run_id)
                for dialogue in allowed_dialogues
            ),
        )
        if child_generation is None:
            return DialogueLinePage(
                items=[],
                page=query.page,
                page_size=query.page_size,
                total=0,
                page_count=1,
                sort=sort,
                direction=direction,
            )
        conditions = [child_generation]
        if query.line_kind is not None:
            conditions.append(col("line_kind") == lit(query.line_kind))
        if query.voice_id is not None:
            conditions.append(col("line_kind") == lit(DialogueLineKind.NPC))
        predicate = combine(conditions)
        if query.directed is None and query.voiced is None and sort != "text_length":
            total, records = await records_page(
                table=self.lines_table,
                model=DialogueLineRecord,
                stable_column="id",
                predicate=predicate,
                tokens=tokens,
                ordering=None if sort == "relevance" else ordering(sort, direction, "id"),
                page=query,
            )
        else:
            records, scores = await records_all(
                table=self.lines_table,
                model=DialogueLineRecord,
                search_model=_LineSearchResult,
                tokens=tokens,
                predicate=predicate,
                key_of=lambda row: row.id,
                score_of=lambda row: row.score,
            )
            voice_id = None if query.voice_id is None else query.voice_id.casefold()

            def has_direction(record: DialogueLineRecord) -> bool:
                directions = generation.directions_by_line.get(record.id, ())
                return any(
                    voice_id is None or row.voice_id.casefold() == voice_id for row in directions
                )

            def has_audio(record: DialogueLineRecord) -> bool:
                voices = generation.audio_voices_by_line.get(record.id, set())
                return bool(voices) if voice_id is None else voice_id in voices

            records = _filter_value(
                records, query.directed, lambda row, value: has_direction(row) is value
            )
            records = _filter_value(
                records, query.voiced, lambda row, value: has_audio(row) is value
            )
            if sort == "text_length":
                resolved = [row for row in records if row.text is not None]
                unresolved = sorted(
                    (row for row in records if row.text is None),
                    key=lambda row: row.id,
                )
                resolved.sort(key=lambda row: row.id)
                resolved.sort(
                    key=lambda row: len(row.text or ""),
                    reverse=direction == "desc",
                )
                records = [*resolved, *unresolved]
            else:
                records = browse_order(records, sort, direction, scores, lambda row: row.id)
            total = len(records)
            records = page_items(records, query)

        return DialogueLinePage(
            items=[
                dialogue_line_row(
                    record,
                    dialogues[record.dialogue_resource_name.casefold()],
                    attribution.character_count_by_dialogue[
                        record.dialogue_resource_name.casefold()
                    ],
                    generation.line_directions(record.id),
                )
                for record in records
            ],
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=page_count(total, query.page_size),
            sort=sort,
            direction=direction,
        )

    async def voices(self, query: VoiceQuery) -> VoicePage:
        tokens = search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "npc_line_count")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        dialogue_rows, character_rows, metadata = await asyncio.gather(
            self.dialogues_table.query().to_pydantic(DialogueRecord),
            self.characters_table.query().to_pydantic(CharacterRecord),
            self.metadata_snapshot(),
        )
        dialogues = cast(list[DialogueRecord], dialogue_rows)
        characters = cast(list[CharacterRecord], character_rows)
        labels = LabelResolver.from_snapshot(metadata)
        attribution = await self.attribution_snapshot()
        generation = await self.generation_snapshot(attribution)
        if attribution.run is None:
            records: list[VoiceResourceRecord] = []
            scores: dict[str, float] = {}
        else:
            records, scores = await records_all(
                table=self.voices_table,
                model=VoiceResourceRecord,
                search_model=_VoiceSearchResult,
                tokens=tokens,
                predicate=col("run_id") == lit(attribution.run.id),
                key_of=lambda row: row.voice_id,
                score_of=lambda row: row.score,
            )
        dialogues_by_resref = {row.resref.casefold(): row for row in dialogues}
        characters_by_name = {row.resource_name.casefold(): row for row in characters}
        rows = []
        for record in records:
            directed_count, audio_count = generation.voice_counts(record.voice_id)
            rows.append(
                voice_row(
                    record,
                    dialogues_by_resref,
                    characters_by_name,
                    labels,
                    generation.generated_voice(record.voice_id),
                    directed_count,
                    audio_count,
                )
            )
        if query.voice_id is not None:
            rows = [row for row in rows if row.id == query.voice_id]
        rows = browse_order(rows, sort, direction, scores, lambda row: row.id)
        return VoicePage(
            items=page_items(rows, query),
            page=query.page,
            page_size=query.page_size,
            total=len(rows),
            page_count=page_count(len(rows), query.page_size),
            sort=sort,
            direction=direction,
        )

    async def sounds(self, query: SoundQuery) -> SoundPage:
        character_rows, group_rows, metadata = await asyncio.gather(
            self.characters_table.query().to_pydantic(CharacterRecord),
            self.sound_slot_groups_table.query().to_pydantic(SoundSlotGroupRecord),
            self.metadata_snapshot(),
        )
        characters = cast(list[CharacterRecord], character_rows)
        groups = cast(list[SoundSlotGroupRecord], group_rows)
        complete_characters = [
            character
            for character in characters
            if character.extraction.status is DetailStatus.COMPLETE
        ]
        sound_generation = child_generation_predicate(
            "character_resource_name",
            (
                (character.resource_name, character.extraction.run_id)
                for character in complete_characters
            ),
        )
        tokens = search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "serialized_size")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        if sound_generation is None:
            return SoundPage(
                items=[],
                page=query.page,
                page_size=query.page_size,
                total=0,
                page_count=1,
                sort=sort,
                direction=direction,
            )
        conditions = [sound_generation]
        if query.character_resource_name is not None:
            conditions.append(col("character_resource_name") == lit(query.character_resource_name))
        if query.slot_id is not None:
            conditions.append(col("slot_id") == lit(query.slot_id))
        total, records = await records_page(
            table=self.character_sounds_table,
            model=CharacterSoundRecord,
            stable_column="id",
            predicate=combine(conditions),
            tokens=tokens,
            ordering=None if sort == "relevance" else ordering(sort, direction, "id"),
            page=query,
        )
        by_resource = {row.resource_name.casefold(): row for row in complete_characters}
        symbols = identifier_symbols(metadata.identifiers)
        items: list[SoundRow] = []
        for record in records:
            character = by_resource[record.character_resource_name.casefold()]
            assert character.detail is not None
            items.append(
                SoundRow(
                    key=record.id,
                    character_resource_name=record.character_resource_name,
                    character_name=character.detail.display_name,
                    slot_id=record.slot_id,
                    slot_symbols=list(symbols.get((IdentifierKind.SOUND_SLOT, record.slot_id), ())),
                    slot_groups=sound_slot_group_names(groups, record.slot_id),
                    strref=record.strref,
                    text=record.text,
                    serialized_size=record.serialized_size,
                )
            )
        return SoundPage(
            items=items,
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=page_count(total, query.page_size),
            sort=sort,
            direction=direction,
        )

    async def transitions(self, query: TransitionQuery) -> TransitionPage:
        dialogue_rows = cast(
            list[DialogueRecord],
            await self.dialogues_table.query().to_pydantic(DialogueRecord),
        )
        dialogues = {row.resource_name.casefold(): row for row in dialogue_rows}
        tokens = search_tokens(query.q)
        sort = query.sort or ("relevance" if tokens else "location")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        complete_dialogues = [
            row for row in dialogue_rows if row.extraction.status is DetailStatus.COMPLETE
        ]
        predicate = child_generation_predicate(
            "dialogue_resource_name",
            ((row.resource_name, row.extraction.run_id) for row in complete_dialogues),
        )
        if predicate is None:
            return TransitionPage(
                items=[],
                page=query.page,
                page_size=query.page_size,
                total=0,
                page_count=1,
                sort=sort,
                direction=direction,
            )
        if query.dialogue_resource_name is not None:
            predicate &= col("dialogue_resource_name") == lit(query.dialogue_resource_name)
        if query.terminates_dialog is not None:
            predicate &= col("terminates_dialog") == lit(query.terminates_dialog)
        transition_order = (
            ordering(sort, direction, "id")
            if sort != "location"
            else [
                ColumnOrdering(
                    column_name=column,
                    ascending=direction == "asc",
                    nulls_first=False,
                )
                for column in ("dialogue_resource_name", "state_index", "transition_index")
            ]
        )
        total, records = await records_page(
            table=self.transitions_table,
            model=DialogueTransitionRecord,
            stable_column="id",
            predicate=predicate,
            tokens=tokens,
            ordering=None if sort == "relevance" else transition_order,
            page=query,
        )
        return TransitionPage(
            items=[
                transition_row(
                    record,
                    dialogues[record.dialogue_resource_name.casefold()],
                )
                for record in records
            ],
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=page_count(total, query.page_size),
            sort=sort,
            direction=direction,
        )

    async def races(self, query: RaceQuery) -> RacePage:
        metadata = await self.metadata_snapshot()
        rows = race_rows(metadata)
        rows = _filter_value(
            rows,
            query.campaign,
            lambda row, campaign: any(
                _campaign_matches(text, campaign) for text in row.campaign_texts
            ),
        )

        tokens = search_tokens(query.q)
        scores: dict[str, float] = {}
        if tokens:
            text_scores, lore_scores, identifier_scores = await asyncio.gather(
                fts_scores(self.race_texts_table, tokens),
                fts_scores(self.favored_enemies_table, tokens),
                fts_scores(
                    self.identifiers_table,
                    tokens,
                    col("kind") == lit(IdentifierKind.RACE.value),
                ),
            )
            race_id_scores = identifier_value_scores(
                metadata,
                identifier_scores,
                IdentifierKind.RACE,
            )
            rows, scores = _scored_rows(
                rows,
                lambda row: max(
                    lore_scores.get(row.lore.key, 0.0) if row.lore is not None else 0.0,
                    race_id_scores.get(row.race_id, 0.0),
                    *(text_scores.get(text.record.key, 0.0) for text in row.campaign_texts),
                ),
            )

        sort: RaceSort | Literal["relevance"] = query.sort or ("relevance" if tokens else "race_id")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        if sort == "display_name":
            rows.sort(
                key=lambda row: (row.display_name.casefold(), row.key),
                reverse=direction == "desc",
            )
        else:
            rows = browse_order(rows, sort, direction, scores, lambda row: row.key)
        return RacePage(
            items=page_items(rows, query),
            page=query.page,
            page_size=query.page_size,
            total=len(rows),
            page_count=page_count(len(rows), query.page_size),
            sort=sort,
            direction=direction,
        )

    async def classes(self, query: ClassQuery) -> ClassPage:
        metadata = await self.metadata_snapshot()
        rows = class_rows(metadata)
        rows = _filter_value(rows, query.campaign, _campaign_matches)
        rows = _filter_value(rows, query.fallen, lambda row, value: row.fallen is value)
        rows = _filter_value(rows, query.class_id, lambda row, value: row.class_id == value)

        tokens = search_tokens(query.q)
        scores: dict[str, float] = {}
        if tokens:
            text_scores, identifier_scores = await asyncio.gather(
                fts_scores(self.class_texts_table, tokens),
                fts_scores(
                    self.identifiers_table,
                    tokens,
                    col("kind") == lit(IdentifierKind.CLASS.value),
                ),
            )
            class_id_scores = identifier_value_scores(
                metadata,
                identifier_scores,
                IdentifierKind.CLASS,
            )
            rows, scores = _scored_rows(
                rows,
                lambda row: max(
                    text_scores.get(row.key, 0.0),
                    class_id_scores.get(row.class_id, 0.0),
                ),
            )

        sort: ClassSort | Literal["relevance"] = query.sort or (
            "relevance" if tokens else "class_id"
        )
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        rows = browse_order(rows, sort, direction, scores, lambda row: row.key)
        return ClassPage(
            items=page_items(rows, query),
            page=query.page,
            page_size=query.page_size,
            total=len(rows),
            page_count=page_count(len(rows), query.page_size),
            sort=sort,
            direction=direction,
        )

    async def kits(self, query: KitQuery) -> KitPage:
        metadata = await self.metadata_snapshot()
        rows = kit_rows(metadata)
        rows = _filter_value(rows, query.class_id, lambda row, value: row.class_id == value)

        tokens = search_tokens(query.q)
        scores: dict[str, float] = {}
        if tokens:
            kit_scores, class_identifier_scores, kit_identifier_scores = await asyncio.gather(
                fts_scores(self.kits_table, tokens),
                fts_scores(
                    self.identifiers_table,
                    tokens,
                    col("kind") == lit(IdentifierKind.CLASS.value),
                ),
                fts_scores(
                    self.identifiers_table,
                    tokens,
                    col("kind") == lit(IdentifierKind.KIT.value),
                ),
            )
            class_id_scores = identifier_value_scores(
                metadata,
                class_identifier_scores,
                IdentifierKind.CLASS,
            )
            kit_id_scores = identifier_value_scores(
                metadata,
                kit_identifier_scores,
                IdentifierKind.KIT,
            )
            rows, scores = _scored_rows(
                rows,
                lambda row: max(
                    kit_scores.get(row.key, 0.0),
                    class_id_scores.get(row.class_id, 0.0),
                    kit_id_scores.get(row.kit_ids_value, 0.0),
                ),
            )

        sort: KitSort | Literal["relevance"] = query.sort or ("relevance" if tokens else "row_id")
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        rows = browse_order(rows, sort, direction, scores, lambda row: row.key)
        return KitPage(
            items=page_items(rows, query),
            page=query.page,
            page_size=query.page_size,
            total=len(rows),
            page_count=page_count(len(rows), query.page_size),
            sort=sort,
            direction=direction,
        )

    async def identifiers(self, query: IdentifierQuery) -> IdentifierPage:
        conditions = [col("kind").isin([kind.value for kind in SIMPLE_IDENTIFIER_KINDS])]
        if query.kind is not None:
            conditions.append(col("kind") == lit(query.kind.value))
        predicate = combine(conditions)
        assert predicate is not None
        tokens = search_tokens(query.q)
        sort: IdentifierSort | Literal["relevance"] = query.sort or (
            "relevance" if tokens else "kind"
        )
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        total, records = await records_page(
            table=self.identifiers_table,
            model=IdentifierDefinitionRecord,
            stable_column="key",
            predicate=predicate,
            tokens=tokens,
            ordering=None if sort == "relevance" else ordering(sort, direction, "key"),
            page=query,
        )
        return IdentifierPage(
            items=[
                IdentifierRow.model_validate(record, from_attributes=True) for record in records
            ],
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=page_count(total, query.page_size),
            sort=sort,
            direction=direction,
        )

    async def readable_items(self, query: ReadableItemQuery) -> ReadableItemPage:
        predicate = None if query.kind is None else col("kind") == lit(query.kind.value)
        tokens = search_tokens(query.q)
        sort: ReadableItemSort | Literal["relevance"] = query.sort or (
            "relevance" if tokens else "display_title"
        )
        direction: SortDirection = "desc" if sort == "relevance" else query.direction
        total, records = await records_page(
            table=self.readable_items_table,
            model=ReadableItemRecord,
            stable_column="resource_name",
            predicate=predicate,
            tokens=tokens,
            ordering=(None if sort == "relevance" else ordering(sort, direction, "resource_name")),
            page=query,
        )
        return ReadableItemPage(
            items=[
                ReadableItemRow.model_validate(record, from_attributes=True) for record in records
            ],
            page=query.page,
            page_size=query.page_size,
            total=total,
            page_count=page_count(total, query.page_size),
            sort=sort,
            direction=direction,
        )


def _filter_value[Row, Value](
    rows: list[Row],
    value: Value | None,
    matches: Callable[[Row, Value], bool],
) -> list[Row]:
    if value is None:
        return rows
    return [row for row in rows if matches(row, value)]


class _Keyed(Protocol):
    key: str


class _CampaignRow(Protocol):
    campaigns: list[str]


def _campaign_matches(row: _CampaignRow, campaign: str) -> bool:
    return campaign.casefold() in {value.casefold() for value in row.campaigns}


def _scored_rows[Row: _Keyed](
    rows: list[Row],
    score_for: Callable[[Row], float],
) -> tuple[list[Row], dict[str, float]]:
    scores = {row.key: score_for(row) for row in rows}
    scores = {key: score for key, score in scores.items() if score}
    return [row for row in rows if row.key in scores], scores


def _latest_run_id(runs: Sequence[ExtractionRunRecord], kind: RunKind) -> str | None:
    matches = [run for run in runs if run.run_kind is kind]
    if not matches:
        return None
    return max(matches, key=lambda run: (run.started_at, run.id)).id


def _completed_run_order(run: ExtractionRunRecord) -> tuple[str, str]:
    assert run.completed_at is not None, f"completed run {run.id} has no completion time"
    return run.completed_at, run.id


def _empty_attribution_snapshot(
    publication: AttributionPublicationStatus,
) -> AttributionSnapshot:
    return AttributionSnapshot(
        publication=publication,
        run=None,
        by_character={},
        character_count_by_dialogue=Counter(),
        voices=[],
        voice_by_character={},
    )


def _published_attribution(
    run: ExtractionRunRecord,
    attributions: list[CharacterAttributionRecord],
    voices: list[VoiceResourceRecord],
) -> AttributionSnapshot:
    by_character = {row.character_resource_name.casefold(): row for row in attributions}
    assert len(by_character) == len(attributions), (
        "published attribution contains duplicate character rows"
    )
    dialogue_counts: Counter[str] = Counter()
    for row in attributions:
        dialogue_counts.update(name.casefold() for name in row.resolved_dialogue_resource_names)
    voice_by_character: dict[str, VoiceResourceRecord] = {}
    for voice in voices:
        for resource_name in voice.variant_resource_names:
            key = resource_name.casefold()
            assert key not in voice_by_character, (
                f"published voices assign {resource_name!r} more than once"
            )
            voice_by_character[key] = voice
    return AttributionSnapshot(
        publication=AttributionPublicationStatus.PUBLISHED,
        run=run,
        by_character=by_character,
        character_count_by_dialogue=dialogue_counts,
        voices=voices,
        voice_by_character=voice_by_character,
    )
