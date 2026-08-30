"""Single-writer LanceDB repository for the EET extraction pipeline."""

from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import lancedb
import pyarrow as pa
from lancedb.expr import col
from lancedb.pydantic import LanceModel
from lancedb.table import Table

from bgvoice.attribution import build_attributions
from bgvoice.character_models import CharacterExtraction
from bgvoice.dialogue_models import DialogueExtraction
from bgvoice.metadata_models import (
    CampaignDefinition,
    CampaignResourceBinding,
    ClassTextRow,
    IdentifierDefinition,
    KitDefinition,
    MetadataExtraction,
    RaceTextRow,
)
from bgvoice.model_types import (
    CreResource,
    DetailStatus,
    DlgResource,
    PortraitImage,
    ProviderGender,
    RunKind,
    RunStatus,
    TerminalRunStatus,
    VoiceProfileKind,
    utc_now,
)
from bgvoice.pipeline_models import AttributionSummary, DatabaseStats
from bgvoice.readable_models import ReadableItem
from bgvoice.record_builders import (
    character_batch_records,
    dialogue_batch_records,
    metadata_records,
    pending_character,
    pending_character_refresh,
    pending_dialogue,
    pending_dialogue_refresh,
    retained_character,
    retained_dialogue,
    same_identity,
)
from bgvoice.storage_records import (
    BanterTimingSettingsRecord,
    CampaignCalendarRecord,
    CampaignDefinitionRecord,
    CampaignResourceBindingRecord,
    CharacterRecord,
    CharacterResourceLinkRecord,
    CharacterSoundRecord,
    ClassTextRecord,
    DialogueLineRecord,
    DialogueRecord,
    DirectedLineRecord,
    EngineStringRecord,
    ExtractionRunRecord,
    FavoredEnemyRecord,
    GeneratedAudioIdentity,
    GenerationFailureRecord,
    HappinessRuleRecord,
    IdentifierDefinitionRecord,
    InteractionRuleRecord,
    KeyedRecord,
    KitDefinitionRecord,
    MonthDefinitionRecord,
    PortraitImageRecord,
    RaceTextRecord,
    ReadableItemRecord,
    SoundsetLineRecord,
    SoundSlotGroupRecord,
    SoundSlotSuffixRecord,
    TtsBatchRecord,
    VoiceGenerationRecord,
    VoiceProfileRecord,
    VoiceResourceRecord,
)
from bgvoice.storage_schema import (
    _BANTER_TIMING_SETTINGS,
    _CAMPAIGN_CALENDARS,
    _CAMPAIGN_RESOURCE_BINDINGS,
    _CAMPAIGNS,
    _CHARACTER_DIALOGUES,
    _CHARACTER_RESOURCE_LINKS,
    _CHARACTER_SOUNDS,
    _CHARACTERS,
    _CLASS_TEXTS,
    _DIALOGUE_LINES,
    _DIALOGUE_TRANSITIONS,
    _DIALOGUES,
    _DIRECTED_LINES,
    _ENGINE_STRINGS,
    _EXTRACTION_RUNS,
    _FAVORED_ENEMIES,
    _GENERATED_AUDIO,
    _GENERATION_FAILURES,
    _HAPPINESS_RULES,
    _IDENTIFIER_DEFINITIONS,
    _INTERACTION_RULES,
    _KITS,
    _METADATA_TABLES,
    _MONTHS,
    _PORTRAIT_IMAGES,
    _RACE_TEXTS,
    _READABLE_ITEMS,
    _SOUND_SLOT_GROUPS,
    _SOUND_SLOT_SUFFIXES,
    _SOUNDSET_LINES,
    _TTS_BATCHES,
    _VOICE_GENERATIONS,
    _VOICE_PROFILES,
    _VOICE_RESOURCES,
    TABLE_INDEXES,
    TABLE_MODELS,
    TABLE_NAMES,
)


class PipelineDatabase:
    """Single-writer LanceDB repository for the extraction pipeline."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        is_new = not self.path.exists()
        assert is_new or self.path.is_dir(), f"LanceDB path is not a directory: {self.path}"
        self.path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(self.path, read_consistency_interval=timedelta(0))
        existing = frozenset(self._db.list_tables(limit=None).tables)
        assert (is_new and not existing) or existing == TABLE_NAMES, (
            f"LanceDB tables are {sorted(existing)}; expected {sorted(TABLE_NAMES)}"
        )
        for name, model in TABLE_MODELS.items():
            self._ensure_table(name, model)

    def start_run(
        self,
        game_root: Path,
        iecli_version: str,
        *,
        run_kind: RunKind = RunKind.CHARACTERS,
        character_input_run_id: str | None = None,
        dialogue_input_run_id: str | None = None,
        metadata_input_run_id: str | None = None,
    ) -> str:
        """Create a durable extraction-run record."""
        run_id = uuid4().hex
        assert not self._find_runs(run_id), f"Duplicate extraction run id: {run_id}"
        self._table(_EXTRACTION_RUNS).add(
            [
                ExtractionRunRecord(
                    id=run_id,
                    run_kind=run_kind,
                    started_at=utc_now().isoformat(),
                    completed_at=None,
                    game_root=str(game_root.expanduser().resolve()),
                    iecli_version=iecli_version,
                    character_input_run_id=character_input_run_id,
                    dialogue_input_run_id=dialogue_input_run_id,
                    metadata_input_run_id=metadata_input_run_id,
                    status=RunStatus.RUNNING,
                    resources_discovered=0,
                    details_attempted=0,
                    details_extracted=0,
                    failures=0,
                    error=None,
                )
            ]
        )
        return run_id

    def replace_metadata(self, run_id: str, extraction: MetadataExtraction) -> None:
        """Exactly replace every normalized IDS/2DA metadata collection."""
        run = self._run(run_id, expected_kind=RunKind.METADATA)
        replacements: tuple[
            tuple[str, type[KeyedRecord], Sequence[KeyedRecord]],
            ...,
        ] = (
            (
                _IDENTIFIER_DEFINITIONS,
                IdentifierDefinitionRecord,
                metadata_records(IdentifierDefinitionRecord, extraction.identifiers),
            ),
            (
                _CAMPAIGNS,
                CampaignDefinitionRecord,
                metadata_records(CampaignDefinitionRecord, extraction.campaigns),
            ),
            (
                _CAMPAIGN_RESOURCE_BINDINGS,
                CampaignResourceBindingRecord,
                metadata_records(
                    CampaignResourceBindingRecord,
                    extraction.campaign_resource_bindings,
                ),
            ),
            (
                _CHARACTER_RESOURCE_LINKS,
                CharacterResourceLinkRecord,
                metadata_records(
                    CharacterResourceLinkRecord,
                    extraction.character_resource_links,
                ),
            ),
            (
                _INTERACTION_RULES,
                InteractionRuleRecord,
                metadata_records(InteractionRuleRecord, extraction.interaction_rules),
            ),
            (
                _SOUNDSET_LINES,
                SoundsetLineRecord,
                metadata_records(SoundsetLineRecord, extraction.soundset_lines),
            ),
            (
                _SOUND_SLOT_SUFFIXES,
                SoundSlotSuffixRecord,
                metadata_records(SoundSlotSuffixRecord, extraction.sound_slot_suffixes),
            ),
            (
                _SOUND_SLOT_GROUPS,
                SoundSlotGroupRecord,
                metadata_records(SoundSlotGroupRecord, extraction.sound_slot_groups),
            ),
            (
                _FAVORED_ENEMIES,
                FavoredEnemyRecord,
                metadata_records(FavoredEnemyRecord, extraction.favored_enemies),
            ),
            (
                _HAPPINESS_RULES,
                HappinessRuleRecord,
                metadata_records(HappinessRuleRecord, extraction.happiness_rules),
            ),
            (
                _BANTER_TIMING_SETTINGS,
                BanterTimingSettingsRecord,
                metadata_records(BanterTimingSettingsRecord, (extraction.banter_timing,)),
            ),
            (
                _ENGINE_STRINGS,
                EngineStringRecord,
                metadata_records(EngineStringRecord, extraction.engine_strings),
            ),
            (
                _MONTHS,
                MonthDefinitionRecord,
                metadata_records(MonthDefinitionRecord, extraction.months),
            ),
            (
                _CAMPAIGN_CALENDARS,
                CampaignCalendarRecord,
                metadata_records(CampaignCalendarRecord, extraction.campaign_calendars),
            ),
            (
                _RACE_TEXTS,
                RaceTextRecord,
                metadata_records(RaceTextRecord, extraction.race_text_rows),
            ),
            (
                _CLASS_TEXTS,
                ClassTextRecord,
                metadata_records(ClassTextRecord, extraction.class_text_rows),
            ),
            (
                _KITS,
                KitDefinitionRecord,
                metadata_records(KitDefinitionRecord, extraction.kits),
            ),
        )
        for name, _, records in replacements:
            self._assert_unique_names(
                [record.key for record in records],
                kind=f"{name} replacement",
            )

        updated_run = ExtractionRunRecord.model_validate(
            run.model_dump() | {"resources_discovered": extraction.source_resource_count}
        )
        for name, model, records in replacements:
            self._replace(name, "key", model, records)
        self._merge(_EXTRACTION_RUNS, "id", [updated_run])

    def identifier_definitions(self) -> list[IdentifierDefinition]:
        """Return all persisted effective IDS definitions in source order."""
        records = self._records(_IDENTIFIER_DEFINITIONS, IdentifierDefinitionRecord)
        return [
            IdentifierDefinition.model_validate(
                record.model_dump(include=set(IdentifierDefinition.model_fields))
            )
            for record in sorted(records, key=lambda row: (row.source_resource, row.ordinal))
        ]

    def campaigns(self) -> list[CampaignDefinition]:
        """Return persisted CAMPAIGN.2DA definitions in source order."""
        records = self._records(_CAMPAIGNS, CampaignDefinitionRecord)
        return [
            CampaignDefinition.model_validate(
                record.model_dump(include=set(CampaignDefinition.model_fields))
            )
            for record in sorted(records, key=lambda row: (row.source_resource, row.ordinal))
        ]

    def campaign_resource_bindings(self) -> list[CampaignResourceBinding]:
        """Return persisted campaign-selected resource relationships."""
        records = self._records(_CAMPAIGN_RESOURCE_BINDINGS, CampaignResourceBindingRecord)
        return [
            CampaignResourceBinding.model_validate(
                record.model_dump(include=set(CampaignResourceBinding.model_fields))
            )
            for record in sorted(records, key=lambda row: (row.campaign_id, row.resource_kind))
        ]

    def race_text_rows(self) -> list[RaceTextRow]:
        """Return persisted RACETEXT-compatible rows."""
        records = self._records(_RACE_TEXTS, RaceTextRecord)
        return [
            RaceTextRow.model_validate(record.model_dump(include=set(RaceTextRow.model_fields)))
            for record in sorted(records, key=lambda row: (row.source_resource, row.ordinal))
        ]

    def class_text_rows(self) -> list[ClassTextRow]:
        """Return persisted CLASTEXT-compatible rows."""
        records = self._records(_CLASS_TEXTS, ClassTextRecord)
        return [
            ClassTextRow.model_validate(record.model_dump(include=set(ClassTextRow.model_fields)))
            for record in sorted(records, key=lambda row: (row.source_resource, row.ordinal))
        ]

    def kits(self) -> list[KitDefinition]:
        """Return persisted KITLIST.2DA definitions."""
        records = self._records(_KITS, KitDefinitionRecord)
        return [
            KitDefinition.model_validate(record.model_dump(include=set(KitDefinition.model_fields)))
            for record in sorted(records, key=lambda row: (row.source_resource, row.ordinal))
        ]

    def replace_inventory(self, run_id: str, resources: Sequence[CreResource]) -> None:
        """Replace the complete CRE inventory, preserving unchanged extracted details."""
        run = self._run(run_id, expected_kind=RunKind.CHARACTERS)
        self._assert_unique_names(
            [resource.resource_name for resource in resources], kind="CRE inventory"
        )
        timestamp = utc_now().isoformat()
        existing = {
            record.resource_name.casefold(): record
            for record in self._records(_CHARACTERS, CharacterRecord)
        }
        replacement: list[CharacterRecord] = []
        retained_keys: set[str] = set()
        for resource in resources:
            key = resource.resource_name.casefold()
            if key in existing and same_identity(existing[key], resource):
                replacement.append(retained_character(existing[key], resource))
                retained_keys.add(key)
            else:
                replacement.append(pending_character(resource, run_id, timestamp))

        discarded_names = sorted(
            character.resource_name
            for key, character in existing.items()
            if key not in retained_keys
        )
        updated_run = ExtractionRunRecord.model_validate(
            run.model_dump() | {"resources_discovered": len(resources)}
        )
        self._replace(_CHARACTERS, "resource_name", CharacterRecord, replacement)
        if discarded_names:
            self._table(_CHARACTER_SOUNDS).delete(
                col("character_resource_name").isin(discarded_names)
            )
        self._merge(_EXTRACTION_RUNS, "id", [updated_run])

    def detail_targets(self, *, refresh: bool) -> set[str]:
        """Return CRE resources that need detail extraction."""
        characters = self._records(_CHARACTERS, CharacterRecord)
        return {
            character.resource_name
            for character in characters
            if refresh or character.extraction.status is not DetailStatus.COMPLETE
        }

    def referenced_portrait_resrefs(self) -> set[str]:
        """Return every portrait referenced by a successfully extracted CRE."""
        return {
            resref
            for character in self._records(_CHARACTERS, CharacterRecord)
            if character.detail is not None
            for resref in (character.detail.small_portrait, character.detail.large_portrait)
            if resref is not None
        }

    def replace_portraits(self, run_id: str, images: Sequence[PortraitImage]) -> None:
        """Replace the complete set of effective character portrait images."""
        self._run(run_id, expected_kind=RunKind.PORTRAITS)
        records = [
            PortraitImageRecord.model_validate(image, from_attributes=True) for image in images
        ]
        self._assert_unique_names([record.resref for record in records], kind="portrait images")
        self._replace(_PORTRAIT_IMAGES, "resref", PortraitImageRecord, records)

    def portraits(self) -> list[PortraitImageRecord]:
        """Return stored portraits in stable resource order."""
        return sorted(
            self._records(_PORTRAIT_IMAGES, PortraitImageRecord),
            key=lambda portrait: (portrait.resref.casefold(), portrait.resref),
        )

    def replace_readable_items(
        self,
        run_id: str,
        items: Sequence[ReadableItem],
    ) -> None:
        """Replace the complete set of effective books and scrolls."""
        self._run(run_id, expected_kind=RunKind.READABLE_ITEMS)
        records = [ReadableItemRecord.model_validate(item, from_attributes=True) for item in items]
        self._assert_unique_names(
            [record.resource_name for record in records],
            kind="readable items",
        )
        self._replace(_READABLE_ITEMS, "resource_name", ReadableItemRecord, records)

    def readable_items(self) -> list[ReadableItemRecord]:
        """Return readable items in stable resource order."""
        return sorted(
            self._records(_READABLE_ITEMS, ReadableItemRecord),
            key=lambda item: (item.resource_name.casefold(), item.resource_name),
        )

    def apply_detail_batch(
        self,
        run_id: str,
        extractions: Sequence[CharacterExtraction],
        failures: Iterable[tuple[str, str]],
    ) -> None:
        """Persist one validated batch of successful and failed CRE details."""
        self._run(run_id, expected_kind=RunKind.CHARACTERS)
        failures = tuple(failures)
        success_names = [extraction.resource_name for extraction in extractions]
        characters, requested = self._batch_inventory(
            _CHARACTERS,
            CharacterRecord,
            success_names,
            failures,
            kind="CRE",
        )
        timestamp = utc_now().isoformat()
        updates, sounds = character_batch_records(
            run_id, timestamp, characters, extractions, failures
        )
        self._assert_unique_names([sound.id for sound in sounds], kind="CRE sound batch")
        stored_names = [characters[name.casefold()].resource_name for name in requested]
        self._merge(
            _CHARACTERS,
            "resource_name",
            [
                pending_character_refresh(characters[name.casefold()], run_id, timestamp)
                for name in requested
            ],
        )
        self._replace_children(
            _CHARACTER_SOUNDS,
            "character_resource_name",
            stored_names,
            sounds,
            [sound.id for sound in sounds],
        )
        self._merge(_CHARACTERS, "resource_name", updates)

    def replace_dialogue_inventory(
        self,
        run_id: str,
        resources: Sequence[DlgResource],
    ) -> None:
        """Replace the complete DLG inventory and discard lines for changed identities."""
        run = self._run(run_id, expected_kind=RunKind.DIALOGUES)
        self._assert_unique_names(
            [resource.resource_name for resource in resources], kind="DLG inventory"
        )
        timestamp = utc_now().isoformat()
        existing = {
            record.resource_name.casefold(): record
            for record in self._records(_DIALOGUES, DialogueRecord)
        }
        replacement: list[DialogueRecord] = []
        retained_keys: set[str] = set()
        for resource in resources:
            key = resource.resource_name.casefold()
            if key in existing and same_identity(existing[key], resource):
                replacement.append(retained_dialogue(existing[key], resource))
                retained_keys.add(key)
            else:
                replacement.append(pending_dialogue(resource, run_id, timestamp))

        discarded_names = sorted(
            dialogue.resource_name for key, dialogue in existing.items() if key not in retained_keys
        )
        updated_run = ExtractionRunRecord.model_validate(
            run.model_dump() | {"resources_discovered": len(resources)}
        )
        self._replace(_DIALOGUES, "resource_name", DialogueRecord, replacement)
        if discarded_names:
            self._table(_DIALOGUE_LINES).delete(col("dialogue_resource_name").isin(discarded_names))
            self._table(_DIALOGUE_TRANSITIONS).delete(
                col("dialogue_resource_name").isin(discarded_names)
            )
        self._merge(_EXTRACTION_RUNS, "id", [updated_run])

    def dialogue_targets(self, *, refresh: bool) -> list[str]:
        """Return DLG resources that need metric and line extraction."""
        dialogues = self._records(_DIALOGUES, DialogueRecord)
        return sorted(
            (
                dialogue.resource_name
                for dialogue in dialogues
                if refresh or dialogue.extraction.status is not DetailStatus.COMPLETE
            ),
            key=str.casefold,
        )

    def apply_dialogue_batch(
        self,
        run_id: str,
        details: Sequence[DialogueExtraction],
        failures: Iterable[tuple[str, str]],
    ) -> None:
        """Persist one validated batch of DLG metrics, lines, and failures."""
        self._run(run_id, expected_kind=RunKind.DIALOGUES)
        failures = tuple(failures)
        success_names = [extraction.resource_name for extraction in details]
        dialogues, requested = self._batch_inventory(
            _DIALOGUES,
            DialogueRecord,
            success_names,
            failures,
            kind="DLG",
        )
        timestamp = utc_now().isoformat()
        updates, lines, transitions = dialogue_batch_records(
            run_id, timestamp, dialogues, details, failures
        )
        self._assert_unique_names([line.id for line in lines], kind="DLG line batch")
        self._assert_unique_names(
            [transition.id for transition in transitions],
            kind="DLG transition batch",
        )
        stored_names = [dialogues[name.casefold()].resource_name for name in requested]
        self._merge(
            _DIALOGUES,
            "resource_name",
            [
                pending_dialogue_refresh(dialogues[name.casefold()], run_id, timestamp)
                for name in requested
            ],
        )
        self._replace_children(
            _DIALOGUE_LINES,
            "dialogue_resource_name",
            stored_names,
            lines,
            [line.id for line in lines],
        )
        self._replace_children(
            _DIALOGUE_TRANSITIONS,
            "dialogue_resource_name",
            stored_names,
            transitions,
            [transition.id for transition in transitions],
        )
        self._merge(_DIALOGUES, "resource_name", updates)

    def rebuild_attributions(self) -> AttributionSummary:
        """Publish one complete, run-scoped character attribution generation."""
        input_runs = {
            kind: self._attribution_input_run(kind)
            for kind in (RunKind.CHARACTERS, RunKind.DIALOGUES, RunKind.METADATA)
        }
        game_roots = {Path(run.game_root).expanduser().resolve() for run in input_runs.values()}
        assert len(game_roots) == 1, "attribution inputs must come from the same game install"
        context = max(input_runs.values(), key=lambda run: (run.started_at, run.id))
        run_id = self.start_run(
            Path(context.game_root),
            context.iecli_version,
            run_kind=RunKind.ATTRIBUTION,
            character_input_run_id=input_runs[RunKind.CHARACTERS].id,
            dialogue_input_run_id=input_runs[RunKind.DIALOGUES].id,
            metadata_input_run_id=input_runs[RunKind.METADATA].id,
        )

        try:
            build = build_attributions(
                run_id,
                self._records(_CHARACTERS, CharacterRecord),
                self._records(_DIALOGUES, DialogueRecord),
                self._records(_DIALOGUE_LINES, DialogueLineRecord),
                self._records(_CHARACTER_SOUNDS, CharacterSoundRecord),
                self._records(_CHARACTER_RESOURCE_LINKS, CharacterResourceLinkRecord),
                self._records(_IDENTIFIER_DEFINITIONS, IdentifierDefinitionRecord),
            )
            self._upsert(_CHARACTER_DIALOGUES, "key", build.records)
            self._upsert(_VOICE_RESOURCES, "key", build.voices)
            self._reconcile_generation(build.voices)
            self.finish_run(
                run_id,
                status=RunStatus.COMPLETE,
                discovered=len(build.records),
                attempted=len(build.records),
                extracted=len(build.records),
                failures=0,
            )
            return build.summary
        except BaseException as error:
            self._fail_attribution_run(run_id, error)
            raise

    def _reconcile_generation(self, voices: Sequence[VoiceResourceRecord]) -> None:
        """Retain only generation state owned by the new voice publication."""
        current_voice_ids = {voice.voice_id for voice in voices} | {"narrator"}
        assignments = self._records(_VOICE_GENERATIONS, VoiceGenerationRecord)
        profiles = {
            profile.profile_id: profile
            for profile in self._records(_VOICE_PROFILES, VoiceProfileRecord)
        }
        missing_profiles = {row.profile_id for row in assignments} - profiles.keys()
        assert not missing_profiles, (
            f"voice generations reference missing profiles: {sorted(missing_profiles)}"
        )

        variants = {
            (voice.family_id, voice.gender): voice.voice_id
            for voice in voices
            if voice.voice_id != voice.family_id and voice.gender is not None
        }
        assert len(variants) == sum(
            voice.voice_id != voice.family_id and voice.gender is not None for voice in voices
        ), "voice publication contains duplicate family/gender variants"

        assigned_voice_ids = {row.voice_id for row in assignments}
        remapped: list[VoiceGenerationRecord] = []
        updated_profiles: dict[str, VoiceProfileRecord] = {}
        stale_assignments = [row for row in assignments if row.voice_id not in current_voice_ids]
        for assignment in stale_assignments:
            profile = profiles[assignment.profile_id]
            neutral_target = variants.get((assignment.voice_id, ProviderGender.NEUTRAL))
            if neutral_target is not None and profile.kind is VoiceProfileKind.DEDICATED:
                if neutral_target not in assigned_voice_ids:
                    remapped.append(
                        VoiceGenerationRecord(
                            voice_id=neutral_target,
                            profile_id=assignment.profile_id,
                        )
                    )
                    updated_profiles[profile.profile_id] = profile.model_copy(
                        update={"gender": ProviderGender.NEUTRAL}
                    )
                    assigned_voice_ids.add(neutral_target)
                continue
            if profile.gender is None:
                continue
            selector = (assignment.voice_id, profile.gender)
            if selector not in variants:
                continue
            target = variants[selector]
            if target not in assigned_voice_ids:
                remapped.append(
                    VoiceGenerationRecord(voice_id=target, profile_id=assignment.profile_id)
                )
                assigned_voice_ids.add(target)
        dialogue_name_by_resref = {
            dialogue.resref.casefold(): dialogue.resource_name.casefold()
            for dialogue in self._records(_DIALOGUES, DialogueRecord)
        }
        owned_dialogues = {
            voice.voice_id: {
                dialogue_name_by_resref[resref.casefold()] for resref in voice.dialogue_resrefs
            }
            for voice in voices
        }
        line_dialogues = {
            line.id: line.dialogue_resource_name.casefold()
            for line in self._records(_DIALOGUE_LINES, DialogueLineRecord)
        }

        def owns(voice_id: str, line_id: str) -> bool:
            return (
                voice_id in owned_dialogues
                and line_id in line_dialogues
                and line_dialogues[line_id] in owned_dialogues[voice_id]
            )

        directions = self._records(_DIRECTED_LINES, DirectedLineRecord)
        audio = (
            self._table(_GENERATED_AUDIO)
            .search()
            .select(list(GeneratedAudioIdentity.model_fields))
            .limit(None)
            .to_pydantic(GeneratedAudioIdentity)
        )
        failures = self._records(_GENERATION_FAILURES, GenerationFailureRecord)
        stale_direction_ids = [
            row.id for row in directions if not owns(row.voice_id, row.dialogue_line_id)
        ]
        stale_audio_ids = [row.id for row in audio if not owns(row.voice_id, row.dialogue_line_id)]
        stale_failure_ids = [
            row.id
            for row in failures
            if (row.dialogue_line_id is None and row.voice_id not in current_voice_ids)
            or (row.dialogue_line_id is not None and not owns(row.voice_id, row.dialogue_line_id))
        ]
        running_custom_ids = {
            custom_id
            for batch in self._records(_TTS_BATCHES, TtsBatchRecord)
            if batch.status is RunStatus.RUNNING
            for custom_id in batch.custom_ids
        }
        orphaned = running_custom_ids & set(stale_direction_ids + stale_audio_ids)
        assert not orphaned, (
            "cannot reconcile generation while running TTS batches reference stale lines: "
            f"{sorted(orphaned)}"
        )

        self._upsert(
            _VOICE_PROFILES,
            "profile_id",
            list(updated_profiles.values()),
        )
        self._upsert(_VOICE_GENERATIONS, "voice_id", remapped)
        self._delete_values(
            _VOICE_GENERATIONS,
            "voice_id",
            [row.voice_id for row in stale_assignments],
        )
        self._delete_values(
            _DIRECTED_LINES,
            "id",
            stale_direction_ids,
        )
        self._delete_values(
            _GENERATED_AUDIO,
            "id",
            stale_audio_ids,
        )
        self._delete_values(
            _GENERATION_FAILURES,
            "id",
            stale_failure_ids,
        )

    def finish_run(
        self,
        run_id: str,
        *,
        status: TerminalRunStatus,
        discovered: int | None = None,
        attempted: int,
        extracted: int,
        failures: int,
        error: str | None = None,
    ) -> None:
        """Finalize extraction counters and rebuild indexes for the completed stage."""
        run = self._run(run_id)
        updated = ExtractionRunRecord.model_validate(
            run.model_dump()
            | {
                "completed_at": utc_now().isoformat(),
                "status": status,
                "resources_discovered": (
                    run.resources_discovered if discovered is None else discovered
                ),
                "details_attempted": attempted,
                "details_extracted": extracted,
                "failures": failures,
                "error": error[:2000] if error else None,
            }
        )
        if status is not RunStatus.FAILED:
            if run.run_kind is RunKind.CHARACTERS:
                self._optimize(_CHARACTERS, self._table(_CHARACTERS))
                self._optimize(_CHARACTER_SOUNDS, self._table(_CHARACTER_SOUNDS))
            elif run.run_kind is RunKind.PORTRAITS:
                self._optimize(_PORTRAIT_IMAGES, self._table(_PORTRAIT_IMAGES))
            elif run.run_kind is RunKind.READABLE_ITEMS:
                self._optimize(_READABLE_ITEMS, self._table(_READABLE_ITEMS))
            elif run.run_kind is RunKind.DIALOGUES:
                self._optimize(_DIALOGUES, self._table(_DIALOGUES))
                self._optimize(_DIALOGUE_LINES, self._table(_DIALOGUE_LINES))
                self._optimize(
                    _DIALOGUE_TRANSITIONS,
                    self._table(_DIALOGUE_TRANSITIONS),
                )
            elif run.run_kind is RunKind.METADATA:
                for name in _METADATA_TABLES:
                    self._optimize(name, self._table(name))
            else:
                assert run.run_kind is RunKind.ATTRIBUTION
                self._optimize(
                    _CHARACTER_DIALOGUES,
                    self._table(_CHARACTER_DIALOGUES),
                )
                self._optimize(_VOICE_RESOURCES, self._table(_VOICE_RESOURCES))
        self._merge(_EXTRACTION_RUNS, "id", [updated])

    def stats(self) -> DatabaseStats:
        """Return validated counts for the current CRE inventory."""
        characters = self._records(_CHARACTERS, CharacterRecord)
        statuses = Counter(character.extraction.status for character in characters)
        return DatabaseStats(
            total=len(characters),
            complete=statuses[DetailStatus.COMPLETE],
            failed=statuses[DetailStatus.FAILED],
            pending=statuses[DetailStatus.PENDING],
            with_dialog=sum(
                character.detail is not None and character.detail.dialog_resref is not None
                for character in characters
            ),
        )

    def _fail_attribution_run(self, run_id: str, error: BaseException) -> None:
        try:
            self.finish_run(
                run_id,
                status=RunStatus.FAILED,
                discovered=0,
                attempted=0,
                extracted=0,
                failures=1,
                error=str(error),
            )
        except BaseException as finalization_error:
            error.add_note(f"Failed to finalize attribution run {run_id}: {finalization_error!r}")

    def _ensure_table[Record: LanceModel](self, name: str, model: type[Record]) -> None:
        names = set(self._db.list_tables(limit=None).tables)
        if name not in names:
            table = self._db.create_table(name, schema=model)
            self._create_indexes(name, table)
        table = self._table(name)
        self._assert_schema(name, table, model)
        self._assert_indexes(name, table)

    def _replace[Record: LanceModel](
        self,
        name: str,
        key: str,
        model: type[Record],
        records: Sequence[Record],
    ) -> None:
        rows = list(records)
        data = rows or pa.Table.from_pylist([], schema=model.to_arrow_schema())
        table = self._table(name)
        result = (
            table.merge_insert(key)
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .when_not_matched_by_source_delete()
            .execute(data)
        )
        assert result.num_rows == len(rows), (
            f"{name} replaced {result.num_rows} rows; expected {len(rows)}"
        )
        row_count = table.count_rows()
        assert row_count == len(rows), f"{name} contains {row_count} rows; expected {len(rows)}"
        self._assert_schema(name, table, model)
        self._assert_indexes(name, table)

    def _records[Record: LanceModel](
        self,
        table_name: str,
        model: type[Record],
    ) -> list[Record]:
        return self._table(table_name).search().limit(None).to_pydantic(model)

    def _delete_values(self, table_name: str, column: str, values: Sequence[str]) -> None:
        table = self._table(table_name)
        unique = sorted(set(values))
        for start in range(0, len(unique), 1_000):
            table.delete(col(column).isin(unique[start : start + 1_000]))

    def _batch_inventory[Record: CharacterRecord | DialogueRecord](
        self,
        table_name: str,
        model: type[Record],
        success_names: Sequence[str],
        failures: Sequence[tuple[str, str]],
        *,
        kind: str,
    ) -> tuple[dict[str, Record], list[str]]:
        failure_names = [name for name, _ in failures]
        self._assert_batch_names(success_names, failure_names, kind=kind)
        records = {
            record.resource_name.casefold(): record for record in self._records(table_name, model)
        }
        requested = [*success_names, *failure_names]
        missing = [name for name in requested if name.casefold() not in records]
        assert not missing, f"{kind} batch contains resources outside the inventory: {missing}"
        return records, requested

    def _replace_children[Record: LanceModel](
        self,
        table_name: str,
        parent_column: str,
        parent_names: Sequence[str],
        records: Sequence[Record],
        record_ids: Sequence[str],
    ) -> None:
        self._upsert(table_name, "id", records)
        if not parent_names:
            return
        stale = col(parent_column).isin(parent_names)
        if record_ids:
            stale &= ~col("id").isin(record_ids)
        self._table(table_name).delete(stale)

    def _find_runs(self, run_id: str) -> list[ExtractionRunRecord]:
        return (
            self._table(_EXTRACTION_RUNS)
            .search()
            .where(col("id") == run_id)
            .limit(2)
            .to_pydantic(ExtractionRunRecord)
        )

    def _run(
        self,
        run_id: str,
        *,
        expected_kind: RunKind | None = None,
    ) -> ExtractionRunRecord:
        matches = self._find_runs(run_id)
        assert matches, f"Unknown extraction run: {run_id}"
        assert len(matches) == 1, f"Duplicate extraction run id: {run_id}"
        run = matches[0]
        assert run.status is RunStatus.RUNNING, f"Extraction run {run_id} is already {run.status}"
        assert expected_kind is None or run.run_kind == expected_kind, (
            f"Extraction run {run_id} is {run.run_kind}; expected {expected_kind}"
        )
        return run

    def _latest_run(self, kind: RunKind) -> ExtractionRunRecord | None:
        matches = [
            run
            for run in self._records(_EXTRACTION_RUNS, ExtractionRunRecord)
            if run.run_kind is kind
        ]
        if not matches:
            return None
        return max(matches, key=lambda run: (run.started_at, run.id))

    def _attribution_input_run(self, kind: RunKind) -> ExtractionRunRecord:
        run = self._latest_run(kind)
        assert run is not None, f"attribution requires a {kind.value} run"
        assert run.status in (RunStatus.COMPLETE, RunStatus.COMPLETE_WITH_ERRORS), (
            f"attribution requires a terminal successful {kind.value} run"
        )
        return run

    def _merge[Record: LanceModel](
        self,
        table_name: str,
        key: str,
        records: Sequence[Record],
    ) -> None:
        if not records:
            return
        result = (
            self._table(table_name)
            .merge_insert(key)
            .when_matched_update_all()
            .execute(list(records))
        )
        assert result.num_updated_rows == len(records), (
            f"{table_name} updated {result.num_updated_rows} rows; expected {len(records)}"
        )

    def _upsert[Record: LanceModel](
        self,
        table_name: str,
        key: str,
        records: Sequence[Record],
    ) -> None:
        if not records:
            return
        result = (
            self._table(table_name)
            .merge_insert(key)
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(list(records))
        )
        changed = result.num_updated_rows + result.num_inserted_rows
        assert changed == len(records), (
            f"{table_name} upserted {changed} rows; expected {len(records)}"
        )

    def _table(self, name: str) -> Table:
        return self._db.open_table(name)

    @staticmethod
    def _assert_schema[Record: LanceModel](
        name: str,
        table: Table,
        model: type[Record],
    ) -> None:
        expected = model.to_arrow_schema()
        assert table.schema.equals(expected, check_metadata=True), (
            f"LanceDB table {name!r} has schema {table.schema}; expected {expected}"
        )

    @staticmethod
    def _create_indexes(name: str, table: Table) -> None:
        for index in TABLE_INDEXES[name]:
            table.create_index(index.column, config=index.config, name=index.name)

    @classmethod
    def _optimize(cls, name: str, table: Table) -> None:
        table.optimize()
        cls._assert_indexes(name, table)

    @staticmethod
    def _assert_indexes(name: str, table: Table) -> None:
        actual = {
            (index.name, index.index_type, tuple(index.columns)) for index in table.list_indices()
        }
        expected = {
            (index.name, type(index.config).__name__, (index.column,))
            for index in TABLE_INDEXES[name]
        }
        assert actual == expected, (
            f"LanceDB table {name!r} has indexes {sorted(actual)}; expected {sorted(expected)}"
        )

    @staticmethod
    def _assert_unique_names(names: Sequence[str], *, kind: str) -> None:
        folded = [name.casefold() for name in names]
        counts = Counter(folded)
        duplicates = sorted({name for name in folded if counts[name] > 1})
        assert not duplicates, f"{kind} contains duplicate keys: {duplicates}"

    @classmethod
    def _assert_batch_names(
        cls,
        success_names: Sequence[str],
        failure_names: Sequence[str],
        *,
        kind: str,
    ) -> None:
        cls._assert_unique_names(success_names, kind=f"{kind} successes")
        cls._assert_unique_names(failure_names, kind=f"{kind} failures")
        overlap = sorted(
            {name.casefold() for name in success_names}
            & {name.casefold() for name in failure_names}
        )
        assert not overlap, f"{kind} batch has both success and failure for: {overlap}"
