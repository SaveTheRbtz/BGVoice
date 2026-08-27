"""Behavioral contracts for the typed LanceDB pipeline repository."""

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import lancedb
import pytest
from lancedb.index import FTS
from lancedb.pydantic import LanceModel
from pydantic import ValidationError

from bgvoice.database import (
    TABLE_INDEXES,
    BanterTimingSettingsRecord,
    CampaignCalendarRecord,
    CampaignDefinitionRecord,
    CampaignResourceBindingRecord,
    CharacterAttributionRecord,
    CharacterRecord,
    CharacterResourceLinkRecord,
    CharacterSoundRecord,
    ClassTextRecord,
    DialogueLineRecord,
    DialogueRecord,
    DialogueTransitionRecord,
    EngineStringRecord,
    ExtractionRunRecord,
    FavoredEnemyRecord,
    HappinessRuleRecord,
    IdentifierDefinitionRecord,
    InteractionRuleRecord,
    KitDefinitionRecord,
    MonthDefinitionRecord,
    PipelineDatabase,
    RaceTextRecord,
    SoundsetLineRecord,
    SoundSlotGroupRecord,
    SoundSlotSuffixRecord,
    VoiceResourceRecord,
)
from bgvoice.models import (
    AlignmentId,
    BanterTimingSettings,
    CampaignCalendarDefinition,
    CampaignDefinition,
    CampaignResourceBinding,
    CampaignResourceKind,
    CharacterExtraction,
    CharacterResourceLink,
    CharacterResourceRole,
    ClassId,
    ClassTextKitId,
    ClassTextRow,
    DetailStatus,
    DialogueExtraction,
    DlgDump,
    EngineString,
    ExtractionState,
    FavoredEnemyDefinition,
    HappinessAlignment,
    HappinessRule,
    IdentifierDefinition,
    IdentifierKind,
    InteractionKind,
    InteractionRule,
    KitDefinition,
    KitIdsValue,
    KitListRowId,
    MetadataExtraction,
    MonthDefinition,
    RaceId,
    RaceTextRow,
    ResourceSource,
    ResourceTargetType,
    RunKind,
    RunStatus,
    SoundsetLine,
    SoundSlotGroup,
    SoundSlotId,
    SoundSlotSuffix,
    SourceKind,
)
from tests.factories import make_dialogue_dump, make_dialogue_resource, make_dump, make_resource


def make_metadata_extraction() -> MetadataExtraction:
    """Create representative canonical, campaign-text, and kit metadata."""
    identifiers = [
        IdentifierDefinition(
            kind=kind,
            value=value,
            source_resource=source,
            ordinal=ordinal,
            symbols=symbols,
        )
        for ordinal, (kind, value, source, symbols) in enumerate(
            [
                (IdentifierKind.RACE, 1, "RACE.IDS", ["HUMAN"]),
                (IdentifierKind.RACE, 2, "RACE.IDS", ["ELF"]),
                (IdentifierKind.RACE, 255, "RACE.IDS", ["NO_RACE"]),
                (IdentifierKind.CLASS, 1, "CLASS.IDS", ["MAGE"]),
                (IdentifierKind.CLASS, 2, "CLASS.IDS", ["FIGHTER"]),
                (IdentifierKind.CLASS, 14, "CLASS.IDS", ["CLERIC_MAGE"]),
                (IdentifierKind.GENDER, 2, "GENDER.IDS", ["FEMALE"]),
                (IdentifierKind.ALIGNMENT, 17, "ALIGN.IDS", ["LAWFUL_GOOD"]),
                (IdentifierKind.ENEMY_ALLY, 128, "EA.IDS", ["GOODCUTOFF", "ALLY"]),
                (IdentifierKind.GENERAL, 1, "GENERAL.IDS", ["HUMANOID"]),
                (IdentifierKind.SPECIFIC, 0, "SPECIFIC.IDS", ["NONE"]),
                (IdentifierKind.ANIMATION, 0x6202, "ANIMATE.IDS", ["ELF_FEMALE"]),
                (
                    IdentifierKind.KIT,
                    0x4000,
                    "KIT.IDS",
                    ["TRUECLASS", "MAGESCHOOL_GENERALIST"],
                ),
                (IdentifierKind.KIT, 0x4001, "KIT.IDS", ["BERSERKER"]),
                (IdentifierKind.SOUND_SLOT, 0, "SNDSLOT.IDS", ["INITIAL_MEETING"]),
            ]
        )
    ]
    campaigns = [
        CampaignDefinition(campaign_id="SOA", source_resource="CAMPAIGN.2DA", ordinal=0),
        CampaignDefinition(campaign_id="BG1", source_resource="CAMPAIGN.2DA", ordinal=1),
    ]
    bindings = [
        CampaignResourceBinding(
            campaign_id="SOA",
            resource_kind=CampaignResourceKind.RACE_TEXT,
            resource_resref="RACETEXT",
        ),
        CampaignResourceBinding(
            campaign_id="SOA",
            resource_kind=CampaignResourceKind.CLASS_TEXT,
            resource_resref="CLASTEXT",
        ),
        CampaignResourceBinding(
            campaign_id="BG1",
            resource_kind=CampaignResourceKind.RACE_TEXT,
            resource_resref="BGRACTXT",
        ),
        CampaignResourceBinding(
            campaign_id="BG1",
            resource_kind=CampaignResourceKind.CLASS_TEXT,
            resource_resref="BGCLATXT",
        ),
        CampaignResourceBinding(
            campaign_id="SOA",
            resource_kind=CampaignResourceKind.BANTER_DIALOGUES,
            resource_resref="INTERDIA",
        ),
    ]
    character_resource_links = [
        CharacterResourceLink(
            source_resource="INTERDIA.2DA",
            ordinal=0,
            death_variable="Aerie",
            source_column="FILE",
            role=CharacterResourceRole.BANTER_DIALOGUE,
            target_type=ResourceTargetType.DIALOGUE,
            target_resref="BAERIE",
        ),
        CharacterResourceLink(
            source_resource="PDIALOG.2DA",
            ordinal=0,
            death_variable="Aerie",
            source_column="POST_DIALOG_FILE",
            role=CharacterResourceRole.POST_DIALOGUE,
            target_type=ResourceTargetType.DIALOGUE,
            target_resref="AERIE",
        ),
        CharacterResourceLink(
            source_resource="PDIALOG.2DA",
            ordinal=0,
            death_variable="Aerie",
            source_column="DREAM_SCRIPT_FILE",
            role=CharacterResourceRole.DREAM_SCRIPT,
            target_type=ResourceTargetType.SCRIPT,
            target_resref="DRAERIE",
        ),
    ]
    interaction_rules = [
        InteractionRule(
            source_resource="INTERACT.2DA",
            speaker_ordinal=0,
            target_ordinal=1,
            speaker_death_variable="Aerie",
            target_death_variable="Minsc",
            kind=InteractionKind.COMPLIMENT,
        )
    ]
    soundset_lines = [
        SoundsetLine(
            source_resource="CHARSND.2DA",
            soundset_name="FEMALE1",
            slot_id=SoundSlotId(0),
            strref=4000,
            text="Greetings.",
        )
    ]
    sound_slot_suffixes = [
        SoundSlotSuffix(
            source_resource="CSOUND.2DA",
            ordinal=0,
            slot_id=SoundSlotId(0),
            file_suffix="a",
        )
    ]
    sound_slot_groups = [
        SoundSlotGroup(
            source_resource="SPEECH.2DA",
            ordinal=0,
            row_name="INITIAL_MEETING",
            offset=SoundSlotId(0),
            count=1,
        ),
        SoundSlotGroup(
            source_resource="SPEECH.2DA",
            ordinal=1,
            row_name="SELECT",
            offset=None,
            count=None,
        ),
    ]
    favored_enemies = [
        FavoredEnemyDefinition(
            source_resource="HATERACE.2DA",
            ordinal=0,
            row_name="BEHOLDER",
            name_strref=54770,
            name="Beholder",
            race_id=RaceId(123),
            help_strref=54772,
            help_text="Beholders are floating aberrations.",
        )
    ]
    happiness_rules = [
        HappinessRule(
            source_resource="HAPPY.2DA",
            reputation=1,
            alignment=alignment,
            happiness=value,
        )
        for alignment, value in (
            (HappinessAlignment.GOOD, -300),
            (HappinessAlignment.NEUTRAL, -300),
            (HappinessAlignment.EVIL, 80),
        )
    ]
    banter_timing = BanterTimingSettings(
        source_resource="BANTTIMG.2DA",
        frequency=480,
        probability=10,
        replay_delay=150,
        special_probability=40,
    )
    engine_strings = [
        EngineString(
            source_resource="ENGINEST.2DA",
            ordinal=0,
            key="DAYMONTH",
            strref=5000,
            text="Day <DAY>, <MONTHNAME>",
        ),
        EngineString(
            source_resource="ENGINEST.2DA",
            ordinal=1,
            key="UNUSED",
            strref=None,
            text=None,
        ),
    ]
    months = [
        MonthDefinition(
            source_resource="MONTHS.2DA",
            ordinal=0,
            month_id=0,
            days=30,
            name_strref=5001,
            name="Hammer",
        )
    ]
    campaign_calendars = [
        CampaignCalendarDefinition(
            source_resource="YEARS.2DA",
            start_time=0,
            start_year=1368,
            normal_format_strref=5002,
            normal_format="<DAY> <MONTHNAME>",
            special_format_strref=5003,
            special_format="Festival",
        )
    ]
    race_texts = [
        RaceTextRow(
            source_resource=source,
            ordinal=ordinal,
            row_name=row_name,
            race_id=RaceId(race_id),
            name_strref=1000 + ordinal,
            name=name,
            description_strref=1100 + ordinal,
            description=description,
            uppercase_name_strref=1200 + ordinal,
            uppercase_name=name.upper(),
            biography_strref=1300 + ordinal,
            biography=f"{name} biography",
        )
        for ordinal, (source, row_name, race_id, name, description) in enumerate(
            [
                ("RACETEXT.2DA", "ELF", 2, "Elf", "The Tel'Quessir."),
                ("BGRACTXT.2DA", "ELF", 2, "Elf", "An elf in the Sword Coast."),
                ("RACETEXT.2DA", "GNOME", 7, "Gnome", "A text-only race."),
            ]
        )
    ]
    class_texts = [
        ClassTextRow(
            source_resource=source,
            ordinal=ordinal,
            row_name=row_name,
            class_id=ClassId(class_id),
            class_text_kit_id=ClassTextKitId(0x4000),
            lower_name_strref=2000 + ordinal,
            lower_name=lower_name,
            description_strref=2100 + ordinal,
            description=description,
            mixed_name_strref=2200 + ordinal,
            mixed_name=mixed_name,
            biography_strref=2300 + ordinal,
            biography=f"{mixed_name} biography",
            fallen=False,
            brief_description_strref=2400 + ordinal,
            brief_description=f"Brief {mixed_name}",
            fallen_notice_strref=None,
            fallen_notice=None,
        )
        for ordinal, (source, row_name, class_id, lower_name, mixed_name, description) in enumerate(
            [
                ("CLASTEXT.2DA", "MAGE", 1, "mage", "Mage", "A practitioner of magic."),
                (
                    "CLASTEXT.2DA",
                    "CLERIC_MAGE",
                    14,
                    "cleric/mage",
                    "Cleric / Mage",
                    "A multiclass spellcaster.",
                ),
                (
                    "BGCLATXT.2DA",
                    "CLERIC_MAGE",
                    14,
                    "cleric/mage",
                    "Cleric / Mage",
                    "A Sword Coast spellcaster.",
                ),
            ]
        )
    ]
    kits = [
        KitDefinition(
            source_resource="KITLIST.2DA",
            ordinal=0,
            row_id=KitListRowId(0),
            row_name="BERSERKER",
            lower_name_strref=3000,
            lower_name="berserker",
            mixed_name_strref=3001,
            mixed_name="Berserker",
            help_strref=3002,
            help_text="A furious fighter.",
            abilities="K_BERS",
            proficiency=1,
            unusable=0x10,
            class_id=ClassId(2),
            kit_ids_value=KitIdsValue(0x4001),
            class_text_kit_id=ClassTextKitId(1),
        )
    ]
    return MetadataExtraction(
        source_resource_count=15,
        resolved_strref_count=30,
        identifiers=identifiers,
        campaigns=campaigns,
        campaign_resource_bindings=bindings,
        character_resource_links=character_resource_links,
        interaction_rules=interaction_rules,
        soundset_lines=soundset_lines,
        sound_slot_suffixes=sound_slot_suffixes,
        sound_slot_groups=sound_slot_groups,
        favored_enemies=favored_enemies,
        happiness_rules=happiness_rules,
        banter_timing=banter_timing,
        engine_strings=engine_strings,
        months=months,
        campaign_calendars=campaign_calendars,
        race_text_rows=race_texts,
        class_text_rows=class_texts,
        kits=kits,
    )


def _rows[Record: LanceModel](
    path: Path,
    table_name: str,
    model: type[Record],
) -> list[Record]:
    database = lancedb.connect(path, read_consistency_interval=timedelta(0))
    return database.open_table(table_name).search().limit(None).to_pydantic(model)


def _character_rows(path: Path) -> list[CharacterRecord]:
    return _rows(path, "characters", CharacterRecord)


def _sound_rows(path: Path) -> list[CharacterSoundRecord]:
    return _rows(path, "character_sounds", CharacterSoundRecord)


def _attribution_rows(path: Path) -> list[CharacterAttributionRecord]:
    return _rows(path, "character_dialogues", CharacterAttributionRecord)


def _voice_rows(path: Path) -> list[VoiceResourceRecord]:
    return _rows(path, "voice_resources", VoiceResourceRecord)


def _dialogue_rows(path: Path) -> list[DialogueRecord]:
    return _rows(path, "dialogues", DialogueRecord)


def _line_rows(path: Path) -> list[DialogueLineRecord]:
    return _rows(path, "dialogue_lines", DialogueLineRecord)


def _transition_rows(path: Path) -> list[DialogueTransitionRecord]:
    return _rows(path, "dialogue_transitions", DialogueTransitionRecord)


def _finish_successful_run(database: PipelineDatabase, run_id: str) -> None:
    database.finish_run(
        run_id,
        status=RunStatus.COMPLETE,
        attempted=0,
        extracted=0,
        failures=0,
    )


def _finish_empty_stage(database: PipelineDatabase, game_root: Path, kind: RunKind) -> str:
    run_id = database.start_run(game_root, "iecli test", run_kind=kind)
    _finish_successful_run(database, run_id)
    return run_id


def _with_character_detail(
    extraction: CharacterExtraction,
    **updates: object,
) -> CharacterExtraction:
    return extraction.model_copy(update={"detail": extraction.detail.model_copy(update=updates)})


def test_database_creates_exact_typed_schemas_and_native_indexes(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    PipelineDatabase(path)
    database = lancedb.connect(path, read_consistency_interval=timedelta(0))
    tables = set(database.list_tables(limit=None).tables)
    assert tables == {
        "characters",
        "character_sounds",
        "character_dialogues",
        "voice_resources",
        "dialogues",
        "dialogue_lines",
        "dialogue_transitions",
        "extraction_runs",
        "identifier_definitions",
        "campaigns",
        "campaign_resource_bindings",
        "character_resource_links",
        "interaction_rules",
        "soundset_lines",
        "sound_slot_suffixes",
        "sound_slot_groups",
        "favored_enemies",
        "happiness_rules",
        "banter_timing_settings",
        "engine_strings",
        "months",
        "campaign_calendars",
        "race_texts",
        "class_texts",
        "kits",
    }

    models: dict[str, type[LanceModel]] = {
        "characters": CharacterRecord,
        "character_sounds": CharacterSoundRecord,
        "character_dialogues": CharacterAttributionRecord,
        "voice_resources": VoiceResourceRecord,
        "dialogues": DialogueRecord,
        "dialogue_lines": DialogueLineRecord,
        "dialogue_transitions": DialogueTransitionRecord,
        "extraction_runs": ExtractionRunRecord,
        "identifier_definitions": IdentifierDefinitionRecord,
        "campaigns": CampaignDefinitionRecord,
        "campaign_resource_bindings": CampaignResourceBindingRecord,
        "character_resource_links": CharacterResourceLinkRecord,
        "interaction_rules": InteractionRuleRecord,
        "soundset_lines": SoundsetLineRecord,
        "sound_slot_suffixes": SoundSlotSuffixRecord,
        "sound_slot_groups": SoundSlotGroupRecord,
        "favored_enemies": FavoredEnemyRecord,
        "happiness_rules": HappinessRuleRecord,
        "banter_timing_settings": BanterTimingSettingsRecord,
        "engine_strings": EngineStringRecord,
        "months": MonthDefinitionRecord,
        "campaign_calendars": CampaignCalendarRecord,
        "race_texts": RaceTextRecord,
        "class_texts": ClassTextRecord,
        "kits": KitDefinitionRecord,
    }
    for name, model in models.items():
        table = database.open_table(name)
        assert table.schema.equals(model.to_arrow_schema(), check_metadata=True)
        indexes = {
            (index.name, index.index_type, tuple(index.columns)) for index in table.list_indices()
        }
        assert indexes == {
            (spec.name, type(spec.config).__name__, (spec.column,)) for spec in TABLE_INDEXES[name]
        }

    fts = FTS(
        base_tokenizer="simple",
        language="English",
        with_position=True,
        max_token_length=64,
        lower_case=True,
        stem=True,
        remove_stop_words=False,
        ascii_folding=True,
    )
    fts_indexes = [
        spec.config
        for specs in TABLE_INDEXES.values()
        for spec in specs
        if spec.name.endswith("_fts")
    ]
    assert fts_indexes
    assert all(config == fts for config in fts_indexes)


def test_metadata_replacement_readers_and_run_lifecycle(tmp_path: Path) -> None:
    path = tmp_path / "metadata.lancedb"
    database = PipelineDatabase(path)
    extraction = make_metadata_extraction()
    run_id = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)

    database.replace_metadata(run_id, extraction)

    assert len(database.identifier_definitions()) == len(extraction.identifiers)
    assert {row.campaign_id for row in database.campaigns()} == {"SOA", "BG1"}
    assert len(database.campaign_resource_bindings()) == len(extraction.campaign_resource_bindings)
    assert len(_rows(path, "character_resource_links", CharacterResourceLinkRecord)) == 3
    assert len(_rows(path, "interaction_rules", InteractionRuleRecord)) == 1
    assert len(_rows(path, "soundset_lines", SoundsetLineRecord)) == 1
    assert len(_rows(path, "sound_slot_suffixes", SoundSlotSuffixRecord)) == 1
    assert len(_rows(path, "sound_slot_groups", SoundSlotGroupRecord)) == 2
    assert len(_rows(path, "favored_enemies", FavoredEnemyRecord)) == 1
    assert len(_rows(path, "happiness_rules", HappinessRuleRecord)) == 3
    assert len(_rows(path, "banter_timing_settings", BanterTimingSettingsRecord)) == 1
    assert len(_rows(path, "engine_strings", EngineStringRecord)) == 2
    assert len(_rows(path, "months", MonthDefinitionRecord)) == 1
    assert len(_rows(path, "campaign_calendars", CampaignCalendarRecord)) == 1
    assert {row.name for row in database.race_text_rows()} == {"Elf", "Gnome"}
    assert {row.mixed_name for row in database.class_text_rows()} == {
        "Mage",
        "Cleric / Mage",
    }
    assert [row.row_name for row in database.kits()] == ["BERSERKER"]
    stored_run = next(
        row for row in _rows(path, "extraction_runs", ExtractionRunRecord) if row.id == run_id
    )
    assert stored_run.resources_discovered == extraction.source_resource_count

    database.finish_run(
        run_id,
        status=RunStatus.COMPLETE,
        attempted=extraction.source_resource_count,
        extracted=extraction.source_resource_count,
        failures=0,
    )
    for table_name in (
        "identifier_definitions",
        "campaigns",
        "campaign_resource_bindings",
        "character_resource_links",
        "interaction_rules",
        "soundset_lines",
        "sound_slot_suffixes",
        "sound_slot_groups",
        "favored_enemies",
        "happiness_rules",
        "banter_timing_settings",
        "engine_strings",
        "months",
        "campaign_calendars",
        "race_texts",
        "class_texts",
        "kits",
    ):
        indexes = {
            index.name for index in lancedb.connect(path).open_table(table_name).list_indices()
        }
        assert indexes == {index.name for index in TABLE_INDEXES[table_name]}

    empty = MetadataExtraction(
        source_resource_count=0,
        resolved_strref_count=0,
        identifiers=[],
        campaigns=[],
        campaign_resource_bindings=[],
        character_resource_links=[],
        interaction_rules=[],
        soundset_lines=[],
        sound_slot_suffixes=[],
        sound_slot_groups=[],
        favored_enemies=[],
        happiness_rules=[],
        banter_timing=BanterTimingSettings(
            source_resource="BANTTIMG.2DA",
            frequency=1,
            probability=0,
            replay_delay=1,
            special_probability=0,
        ),
        engine_strings=[],
        months=[],
        campaign_calendars=[],
        race_text_rows=[],
        class_text_rows=[],
        kits=[],
    )
    second_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)
    database.replace_metadata(second_run, empty)
    assert database.identifier_definitions() == []
    assert database.campaigns() == []
    assert database.campaign_resource_bindings() == []
    assert _rows(path, "sound_slot_groups", SoundSlotGroupRecord) == []
    assert _rows(path, "favored_enemies", FavoredEnemyRecord) == []
    assert _rows(path, "happiness_rules", HappinessRuleRecord) == []
    assert len(_rows(path, "banter_timing_settings", BanterTimingSettingsRecord)) == 1
    assert database.race_text_rows() == []
    assert database.class_text_rows() == []
    assert database.kits() == []


def test_metadata_replacement_rejects_duplicate_stable_keys(tmp_path: Path) -> None:
    database = PipelineDatabase(tmp_path / "duplicate-metadata.lancedb")
    extraction = make_metadata_extraction()
    duplicate = extraction.identifiers[0].model_copy(update={"ordinal": 999})
    invalid = extraction.model_copy(update={"identifiers": [*extraction.identifiers, duplicate]})
    run_id = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)

    with pytest.raises(AssertionError, match="duplicate keys"):
        database.replace_metadata(run_id, invalid)

    assert database.identifier_definitions() == []


def test_failed_metadata_replacement_preserves_published_attribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "failed-metadata.lancedb"
    database = PipelineDatabase(path)
    metadata = make_metadata_extraction()
    metadata_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)
    database.replace_metadata(metadata_run, metadata)
    _finish_successful_run(database, metadata_run)

    character = make_resource()
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    database.apply_detail_batch(
        character_run, [CharacterExtraction.from_dump(character, make_dump())], []
    )
    dialogue = make_dialogue_resource()
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, [dialogue])
    database.apply_dialogue_batch(
        dialogue_run, [DialogueExtraction.from_dump(make_dialogue_dump())], []
    )
    _finish_successful_run(database, character_run)
    _finish_successful_run(database, dialogue_run)
    first = database.rebuild_attributions()
    published_attributions = _attribution_rows(path)
    published_voices = _voice_rows(path)
    assert {row.run_id for row in published_attributions} == {first.run_id}

    replacement = metadata.model_copy(
        update={
            "character_resource_links": [
                metadata.character_resource_links[0].model_copy(update={"target_resref": "NEWDLG"}),
                *metadata.character_resource_links[1:],
            ]
        }
    )
    replacement_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)
    original_replace = database._replace

    def fail_after_character_links(
        name: str,
        key: str,
        model: type[LanceModel],
        records: Sequence[LanceModel],
    ) -> None:
        if name == "interaction_rules":
            raise OSError("simulated metadata write failure")
        original_replace(name, key, model, records)

    monkeypatch.setattr(database, "_replace", fail_after_character_links)
    with pytest.raises(OSError, match="simulated metadata write failure"):
        database.replace_metadata(replacement_run, replacement)

    links = _rows(path, "character_resource_links", CharacterResourceLinkRecord)
    assert any(link.target_resref == "NEWDLG" for link in links)
    assert _attribution_rows(path) == published_attributions
    assert _voice_rows(path) == published_voices
    completed_attribution_runs = [
        run
        for run in _rows(path, "extraction_runs", ExtractionRunRecord)
        if run.run_kind is RunKind.ATTRIBUTION and run.status is RunStatus.COMPLETE
    ]
    assert [run.id for run in completed_attribution_runs] == [first.run_id]


def test_existing_table_requires_the_exact_arrow_schema(tmp_path: Path) -> None:
    path = tmp_path / "wrong.lancedb"
    PipelineDatabase(path)

    class WrongCharacter(LanceModel):
        resource_name: str

    database = lancedb.connect(path)
    database.drop_table("characters")
    database.create_table("characters", schema=WrongCharacter)
    with pytest.raises(AssertionError, match="has schema"):
        PipelineDatabase(path)


def test_existing_table_requires_the_exact_indexes(tmp_path: Path) -> None:
    path = tmp_path / "missing-index.lancedb"
    PipelineDatabase(path)
    lancedb.connect(path).open_table("characters").drop_index("characters_search_fts")

    with pytest.raises(AssertionError, match="has indexes"):
        PipelineDatabase(path)


def test_non_pipeline_database_is_rejected_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "unrelated.lancedb"

    class UnrelatedRecord(LanceModel):
        value: str

    connection = lancedb.connect(path)
    connection.create_table("unrelated", schema=UnrelatedRecord)
    with pytest.raises(AssertionError, match="LanceDB tables are"):
        PipelineDatabase(path)
    assert connection.list_tables(limit=None).tables == ["unrelated"]


def test_existing_empty_directory_is_rejected_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "empty"
    path.mkdir()

    with pytest.raises(AssertionError, match="LanceDB tables are"):
        PipelineDatabase(path)

    assert list(path.iterdir()) == []


def test_unchanged_inventory_resumes_and_changed_identity_clears_details(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    dialogue = make_dialogue_resource()

    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    pending_character = _character_rows(path)[0]
    assert pending_character.source.kind is SourceKind.OVERRIDE
    assert pending_character.extraction.status is DetailStatus.PENDING
    database.apply_detail_batch(
        character_run,
        [CharacterExtraction.from_dump(character, make_dump(short_name="Winged Cleric"))],
        [],
    )
    complete_character = _character_rows(path)[0]
    assert complete_character.detail is not None
    assert (
        complete_character.detail.base_attributes.strength,
        complete_character.detail.base_attributes.strength_bonus,
        complete_character.detail.base_attributes.intelligence,
        complete_character.detail.base_attributes.wisdom,
        complete_character.detail.base_attributes.dexterity,
        complete_character.detail.base_attributes.constitution,
        complete_character.detail.base_attributes.charisma,
    ) == (10, 0, 16, 16, 17, 9, 14)
    assert (
        complete_character.detail.morale,
        complete_character.detail.morale_break,
        complete_character.detail.morale_recovery_time,
        complete_character.detail.reputation,
    ) == (10, 5, 60, 0)
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, [dialogue])
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())
    database.apply_dialogue_batch(dialogue_run, [extraction], [])
    line_ids = {line.id for line in _line_rows(path)}
    sound_ids = {sound.id for sound in _sound_rows(path)}
    transition_ids = {transition.id for transition in _transition_rows(path)}

    same_character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(same_character_run, [character])
    same_dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(same_dialogue_run, [dialogue])
    assert database.detail_targets(refresh=False) == set()
    assert database.dialogue_targets(refresh=False) == []
    assert {line.id for line in _line_rows(path)} == line_ids
    assert {sound.id for sound in _sound_rows(path)} == sound_ids
    assert {transition.id for transition in _transition_rows(path)} == transition_ids

    changed_character = character.model_copy(
        update={"source_path": "C:/game/override/replaced/AERIE.CRE"}
    )
    changed_dialogue = dialogue.model_copy(
        update={"source_path": "C:/game/override/replaced/AERIE.DLG"}
    )
    changed_character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(changed_character_run, [changed_character])
    changed_dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(changed_dialogue_run, [changed_dialogue])

    stored_character = _character_rows(path)[0]
    stored_dialogue = _dialogue_rows(path)[0]
    assert (stored_character.extraction.status, stored_character.detail) == ("pending", None)
    assert (stored_dialogue.extraction.status, stored_dialogue.detail) == ("pending", None)
    assert _sound_rows(path) == []
    assert _line_rows(path) == []
    assert _transition_rows(path) == []


def test_failed_character_inventory_replacement_keeps_published_children(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "characters.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    run_id = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(run_id, [character])
    database.apply_detail_batch(
        run_id,
        [CharacterExtraction.from_dump(character, make_dump())],
        [],
    )
    published_character = _character_rows(path)
    published_sounds = _sound_rows(path)
    changed = character.model_copy(update={"source_path": "C:/changed/AERIE.CRE"})
    replacement_run = database.start_run(tmp_path, "iecli test")

    def fail_replace(
        table_name: str,
        _key: str,
        _model: type[LanceModel],
        _records: Sequence[LanceModel],
    ) -> None:
        assert table_name == "characters"
        raise OSError("simulated character inventory failure")

    monkeypatch.setattr(database, "_replace", fail_replace)
    with pytest.raises(OSError, match="simulated character inventory failure"):
        database.replace_inventory(replacement_run, [changed])

    assert _character_rows(path) == published_character
    assert _sound_rows(path) == published_sounds


def test_failed_dialogue_inventory_replacement_keeps_published_children(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "dialogues.lancedb"
    database = PipelineDatabase(path)
    dialogue = make_dialogue_resource()
    run_id = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(run_id, [dialogue])
    database.apply_dialogue_batch(
        run_id,
        [DialogueExtraction.from_dump(make_dialogue_dump())],
        [],
    )
    published_dialogue = _dialogue_rows(path)
    published_lines = _line_rows(path)
    published_transitions = _transition_rows(path)
    changed = dialogue.model_copy(update={"source_path": "C:/changed/AERIE.DLG"})
    replacement_run = database.start_run(
        tmp_path,
        "iecli test",
        run_kind=RunKind.DIALOGUES,
    )

    def fail_replace(
        table_name: str,
        _key: str,
        _model: type[LanceModel],
        _records: Sequence[LanceModel],
    ) -> None:
        assert table_name == "dialogues"
        raise OSError("simulated dialogue inventory failure")

    monkeypatch.setattr(database, "_replace", fail_replace)
    with pytest.raises(OSError, match="simulated dialogue inventory failure"):
        database.replace_dialogue_inventory(replacement_run, [changed])

    assert _dialogue_rows(path) == published_dialogue
    assert _line_rows(path) == published_lines
    assert _transition_rows(path) == published_transitions


def test_inventory_replacement_preserves_live_indexes(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    connection = lancedb.connect(path, read_consistency_interval=timedelta(0))
    table = connection.open_table("characters")
    original_indexes = {index.name: index.index_uuid for index in table.list_indices()}

    character = make_resource()
    run_id = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(run_id, [character])
    database.apply_detail_batch(
        run_id,
        [CharacterExtraction.from_dump(character, make_dump(short_name="Fresh voice"))],
        [],
    )

    current_indexes = {index.name: index.index_uuid for index in table.list_indices()}
    assert current_indexes == original_indexes
    assert table.search("Fresh", query_type="fts").limit(1).to_arrow().num_rows == 1


def test_character_sound_slots_are_replaced_by_successful_refresh(tmp_path: Path) -> None:
    path = tmp_path / "sounds.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    run_id = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(run_id, [character])
    extraction = CharacterExtraction.from_dump(character, make_dump(short_name="Winged Cleric"))

    database.apply_detail_batch(run_id, [extraction], [])
    sounds = sorted(_sound_rows(path), key=lambda sound: sound.slot_id)
    assert [(sound.id, sound.strref) for sound in sounds] == [
        ("AERIE.CRE:9", 2001),
        ("AERIE.CRE:44", 2044),
    ]
    assert all(sound.serialized_size > 0 for sound in sounds)
    sound_table = lancedb.connect(path).open_table("character_sounds")
    assert sound_table.search("Winged", query_type="fts").limit(10).to_arrow().num_rows == 2

    database.apply_detail_batch(
        run_id,
        [extraction.model_copy(update={"sounds": extraction.sounds[:1]})],
        [],
    )
    assert [sound.id for sound in _sound_rows(path)] == ["AERIE.CRE:9"]


def test_interrupted_sound_upsert_keeps_slots_and_marks_character_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "sound-failure.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    run_id = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(run_id, [character])
    extraction = CharacterExtraction.from_dump(character, make_dump())
    database.apply_detail_batch(run_id, [extraction], [])
    old_sounds = _sound_rows(path)

    def fail_sound_upsert(
        table_name: str,
        key: str,
        records: Sequence[LanceModel],
    ) -> None:
        assert (table_name, key, len(records)) == ("character_sounds", "id", 2)
        raise OSError("simulated sound write failure")

    monkeypatch.setattr(database, "_upsert", fail_sound_upsert)
    with pytest.raises(OSError, match="simulated sound write failure"):
        database.apply_detail_batch(run_id, [extraction], [])

    assert _sound_rows(path) == old_sounds
    assert _character_rows(path)[0].extraction.status == "pending"
    assert database.detail_targets(refresh=False) == {"AERIE.CRE"}


def test_failed_refresh_clears_stale_fields_lines_and_search_text(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    dialogue = make_dialogue_resource()
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    database.apply_detail_batch(
        character_run,
        [CharacterExtraction.from_dump(character, make_dump(short_name="Winged Cleric"))],
        [],
    )
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, [dialogue])
    database.apply_dialogue_batch(
        dialogue_run, [DialogueExtraction.from_dump(make_dialogue_dump())], []
    )
    assert len(_sound_rows(path)) == 2
    assert len(_transition_rows(path)) == 3

    refresh_character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(refresh_character_run, [character])
    refresh_dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(refresh_dialogue_run, [dialogue])
    database.apply_detail_batch(
        refresh_character_run, [], [(character.resource_name, "bad CRE refresh")]
    )
    database.apply_dialogue_batch(
        refresh_dialogue_run, [], [(dialogue.resource_name, "bad DLG refresh")]
    )
    database.finish_run(
        refresh_character_run,
        status=RunStatus.COMPLETE_WITH_ERRORS,
        attempted=1,
        extracted=0,
        failures=1,
    )
    database.finish_run(
        refresh_dialogue_run,
        status=RunStatus.COMPLETE_WITH_ERRORS,
        attempted=1,
        extracted=0,
        failures=1,
    )

    stored_character = _character_rows(path)[0]
    stored_dialogue = _dialogue_rows(path)[0]
    assert stored_character.detail is None
    assert stored_character.serialized_size is None
    assert stored_character.extraction.error == "bad CRE refresh"
    assert "Winged" not in stored_character.search_text
    assert character.source_path in stored_character.search_text
    assert stored_dialogue.detail is None
    assert stored_dialogue.serialized_size is None
    assert stored_dialogue.extraction.error == "bad DLG refresh"
    assert _sound_rows(path) == []
    assert _line_rows(path) == []
    assert _transition_rows(path) == []


def test_invalid_batches_are_rejected_before_mutation(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    dialogue = make_dialogue_resource()
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, [dialogue])
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())
    database.apply_dialogue_batch(dialogue_run, [extraction], [])
    before_characters = _character_rows(path)
    before_sounds = _sound_rows(path)
    before_dialogues = _dialogue_rows(path)
    before_lines = _line_rows(path)
    before_transitions = _transition_rows(path)

    detail = CharacterExtraction.from_dump(character, make_dump())
    with pytest.raises(AssertionError, match="duplicate keys"):
        database.apply_detail_batch(character_run, [detail, detail], [])
    duplicate_sounds = detail.model_copy(update={"sounds": [detail.sounds[0]] * 2})
    with pytest.raises(AssertionError, match="duplicate keys"):
        database.apply_detail_batch(character_run, [duplicate_sounds], [])
    with pytest.raises(AssertionError, match="both success and failure"):
        database.apply_detail_batch(character_run, [detail], [(character.resource_name, "bad")])
    with pytest.raises(AssertionError, match="outside the inventory"):
        unknown = make_resource("OTHER.CRE")
        database.apply_detail_batch(
            character_run,
            [CharacterExtraction.from_dump(unknown, make_dump("OTHER.CRE"))],
            [],
        )

    mismatched = extraction.model_copy(update={"resource_name": "OTHER.DLG"})
    with pytest.raises(AssertionError, match="outside the inventory"):
        database.apply_dialogue_batch(dialogue_run, [mismatched], [])
    duplicate_lines = DialogueExtraction(
        resource_name=extraction.resource_name,
        detail=extraction.detail,
        lines=[
            extraction.lines[0],
            extraction.lines[0],
            extraction.lines[1],
            extraction.lines[3],
            extraction.lines[4],
        ],
        edges=extraction.edges,
        serialized_size=extraction.serialized_size,
    )
    with pytest.raises(AssertionError, match="duplicate keys"):
        database.apply_dialogue_batch(dialogue_run, [duplicate_lines], [])
    invalid_coordinate = DialogueExtraction(
        resource_name=extraction.resource_name,
        detail=extraction.detail,
        lines=[
            extraction.lines[0].model_copy(update={"transition_index": 0}),
            *extraction.lines[1:],
        ],
        edges=extraction.edges,
        serialized_size=extraction.serialized_size,
    )
    with pytest.raises(ValidationError, match="NPC lines must omit"):
        database.apply_dialogue_batch(dialogue_run, [invalid_coordinate], [])
    duplicate_edges = extraction.model_copy(
        update={"edges": [extraction.edges[0], extraction.edges[0], extraction.edges[2]]}
    )
    with pytest.raises(AssertionError, match="duplicate keys"):
        database.apply_dialogue_batch(dialogue_run, [duplicate_edges], [])

    assert _character_rows(path) == before_characters
    assert _sound_rows(path) == before_sounds
    assert _dialogue_rows(path) == before_dialogues
    assert _line_rows(path) == before_lines
    assert _transition_rows(path) == before_transitions


def test_line_ids_are_stable_and_replacement_does_not_duplicate_rows(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, [make_dialogue_resource()])
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())
    database.apply_dialogue_batch(dialogue_run, [extraction], [])
    first_ids = [line.id for line in _line_rows(path)]
    first_transition_ids = [transition.id for transition in _transition_rows(path)]
    database.apply_dialogue_batch(dialogue_run, [extraction], [])
    second_ids = [line.id for line in _line_rows(path)]
    second_transition_ids = [transition.id for transition in _transition_rows(path)]

    assert sorted(first_ids) == sorted(second_ids)
    assert len(second_ids) == len(set(second_ids)) == len(extraction.lines)
    assert "AERIE.DLG:npc:0:-" in second_ids
    assert "AERIE.DLG:player:1:2" in second_ids
    npc_state = next(row for row in _line_rows(path) if row.id == "AERIE.DLG:npc:0:-")
    token_line = next(row for row in _line_rows(path) if row.id == "AERIE.DLG:npc:1:-")
    assert (
        npc_state.state_trigger_index,
        npc_state.state_trigger_text,
        npc_state.tokens,
    ) == (0, 'Global("MetAerie","GLOBAL",0)', [])
    assert token_line.tokens == ["DAYANDMONTH"]
    assert sorted(first_transition_ids) == sorted(second_transition_ids)
    assert len(second_transition_ids) == len(set(second_transition_ids)) == 3
    assert "AERIE.DLG:1:2" in second_transition_ids
    edge = next(row for row in _transition_rows(path) if row.id == "AERIE.DLG:1:2")
    assert edge.trigger_text == 'Global("Quest","GLOBAL",0)'
    assert edge.action_text == 'SetGlobal("Quest","GLOBAL",1)'
    assert (edge.next_dialog, edge.next_state_index, edge.terminates_dialog) == (
        "MINSC",
        7,
        False,
    )


def test_dialogue_batch_preserves_unresolved_scripts_and_ignored_exit_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    run_id = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(run_id, [make_dialogue_resource()])
    payload = make_dialogue_dump("aerie.dlg").model_dump()
    payload["states"][0]["trigger_text"] = None
    payload["states"][0]["transitions"][1]["next_dialog"] = "AERIE"
    payload["states"][1]["transitions"][0]["trigger_text"] = None
    payload["states"][1]["transitions"][0]["action_text"] = None
    extraction = DialogueExtraction.from_dump(DlgDump.model_validate(payload, strict=True))

    database.apply_dialogue_batch(run_id, [extraction], [])

    state = next(row for row in _line_rows(path) if row.id == "AERIE.DLG:npc:0:-")
    exit_edge = next(row for row in _transition_rows(path) if row.id == "AERIE.DLG:0:1")
    scripted_edge = next(row for row in _transition_rows(path) if row.id == "AERIE.DLG:1:2")
    assert state.dialogue_resource_name == "AERIE.DLG"
    assert exit_edge.dialogue_resource_name == "AERIE.DLG"
    assert (state.state_trigger_index, state.state_trigger_text) == (0, None)
    assert (exit_edge.next_dialog, exit_edge.terminates_dialog) == ("AERIE", True)
    assert (scripted_edge.trigger_index, scripted_edge.trigger_text) == (3, None)
    assert (scripted_edge.action_index, scripted_edge.action_text) == (4, None)


def test_interrupted_line_upsert_keeps_old_lines_and_marks_dialogue_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    dialogue = make_dialogue_resource()
    run_id = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(run_id, [dialogue])
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())
    database.apply_dialogue_batch(run_id, [extraction], [])
    old_lines = _line_rows(path)

    def fail_line_upsert(
        table_name: str,
        key: str,
        records: Sequence[LanceModel],
    ) -> None:
        assert (table_name, key, len(records)) == ("dialogue_lines", "id", 5)
        raise OSError("simulated Lance write failure")

    monkeypatch.setattr(database, "_upsert", fail_line_upsert)
    with pytest.raises(OSError, match="simulated Lance write failure"):
        database.apply_dialogue_batch(run_id, [extraction], [])

    assert _line_rows(path) == old_lines
    assert _dialogue_rows(path)[0].extraction.status == "pending"
    assert database.dialogue_targets(refresh=False) == ["AERIE.DLG"]


def test_interrupted_transition_upsert_keeps_graph_and_marks_dialogue_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "transition-failure.lancedb"
    database = PipelineDatabase(path)
    dialogue = make_dialogue_resource()
    run_id = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(run_id, [dialogue])
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())
    database.apply_dialogue_batch(run_id, [extraction], [])
    old_transitions = _transition_rows(path)
    original_upsert = database._upsert

    def fail_transition_upsert(
        table_name: str,
        key: str,
        records: Sequence[LanceModel],
    ) -> None:
        if table_name == "dialogue_transitions":
            assert (key, len(records)) == ("id", 3)
            raise OSError("simulated transition write failure")
        original_upsert(table_name, key, records)

    monkeypatch.setattr(database, "_upsert", fail_transition_upsert)
    with pytest.raises(OSError, match="simulated transition write failure"):
        database.apply_dialogue_batch(run_id, [extraction], [])

    assert _transition_rows(path) == old_transitions
    assert _dialogue_rows(path)[0].extraction.status == "pending"
    assert database.dialogue_targets(refresh=False) == ["AERIE.DLG"]


def test_attribution_reconciles_every_character_dialogue_and_line(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    resources = [
        make_resource("AERIE.CRE"),
        make_resource("CLONE.CRE"),
        make_resource("NODLG.CRE"),
        make_resource("MISSING.CRE"),
        make_resource("PENDING.CRE"),
        make_resource("FAILDLG.CRE"),
    ]
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, resources)
    details = [
        CharacterExtraction.from_dump(resources[0], make_dump("AERIE.CRE", dialog="AERIE")),
        CharacterExtraction.from_dump(resources[1], make_dump("CLONE.CRE", dialog="AERIE")),
        CharacterExtraction.from_dump(resources[2], make_dump("NODLG.CRE", dialog=None)),
        CharacterExtraction.from_dump(resources[3], make_dump("MISSING.CRE", dialog="GHOST")),
        CharacterExtraction.from_dump(resources[5], make_dump("FAILDLG.CRE", dialog="FAIL")),
    ]
    database.apply_detail_batch(character_run, details, [])

    dialogues = [
        make_dialogue_resource("AERIE.DLG"),
        make_dialogue_resource("FAIL.DLG"),
        make_dialogue_resource("UNUSED.DLG"),
    ]
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, dialogues)
    database.apply_dialogue_batch(
        dialogue_run,
        [
            DialogueExtraction.from_dump(make_dialogue_dump("AERIE.DLG")),
            DialogueExtraction.from_dump(make_dialogue_dump("UNUSED.DLG")),
        ],
        [("FAIL.DLG", "broken DLG")],
    )
    _finish_successful_run(database, character_run)
    _finish_successful_run(database, dialogue_run)
    _finish_empty_stage(database, tmp_path, RunKind.METADATA)

    summary = database.rebuild_attributions()
    assert summary.model_dump() == {
        "run_id": summary.run_id,
        "characters_total": 6,
        "characters_unavailable": 1,
        "characters_matched": 3,
        "characters_partially_matched": 0,
        "characters_missing_dialogue": 1,
        "characters_dialogue_failed": 1,
        "characters_without_dialogue": 1,
        "dialogues_total": 3,
        "dialogues_attributed": 2,
        "dialogues_unattributed": 1,
        "attributed_dialogue_lines": 4,
        "unattributed_dialogue_lines": 4,
    }
    attributions = {
        row.character_resource_name: row
        for row in _attribution_rows(path)
        if row.run_id == summary.run_id
    }
    assert attributions["FAILDLG.CRE"].status == "matched"
    assert attributions["FAILDLG.CRE"].dialogue_status == "failed"
    assert attributions["AERIE.CRE"].resolved_dialogue_resource_names == ["AERIE.DLG"]
    assert attributions["CLONE.CRE"].resolved_dialogue_resource_names == ["AERIE.DLG"]
    assert attributions["MISSING.CRE"].resolved_dialogue_resource_names == []
    assert all(not hasattr(row, "character_count") for row in _line_rows(path))
    connection = lancedb.connect(path)
    for table_name in ("character_dialogues", "voice_resources"):
        table = connection.open_table(table_name)
        for index in TABLE_INDEXES[table_name]:
            stats = table.index_stats(index.name)
            assert stats is not None
            assert stats.num_unindexed_rows == 0

    published_attributions = _attribution_rows(path)
    published_voices = _voice_rows(path)
    next_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(next_run, resources)
    assert _attribution_rows(path) == published_attributions
    assert _voice_rows(path) == published_voices


def test_attribution_requires_current_successful_inputs_from_one_install(tmp_path: Path) -> None:
    database = PipelineDatabase(tmp_path / "pipeline.lancedb")
    _finish_empty_stage(database, tmp_path, RunKind.CHARACTERS)
    with pytest.raises(AssertionError, match="requires a dialogues run"):
        database.rebuild_attributions()

    _finish_empty_stage(database, tmp_path, RunKind.DIALOGUES)
    _finish_empty_stage(database, tmp_path / "other-game", RunKind.METADATA)
    with pytest.raises(AssertionError, match="same game install"):
        database.rebuild_attributions()

    _finish_empty_stage(database, tmp_path, RunKind.METADATA)
    database.start_run(tmp_path, "iecli test", run_kind=RunKind.CHARACTERS)
    with pytest.raises(AssertionError, match="terminal successful characters run"):
        database.rebuild_attributions()


def test_attribution_includes_normalized_party_dialogue_links(tmp_path: Path) -> None:
    path = tmp_path / "linked-dialogues.lancedb"
    database = PipelineDatabase(path)
    metadata = make_metadata_extraction()
    metadata = metadata.model_copy(
        update={
            "character_resource_links": [
                *metadata.character_resource_links,
                CharacterResourceLink(
                    source_resource="PDIALOG.2DA",
                    ordinal=2,
                    death_variable="AERIE",
                    source_column="POST_DIALOG_FILE",
                    role=CharacterResourceRole.POST_DIALOGUE,
                    target_type=ResourceTargetType.DIALOGUE,
                    target_resref="AERIE",
                ),
                CharacterResourceLink(
                    source_resource="PDIALOG.2DA",
                    ordinal=3,
                    death_variable="aerie",
                    source_column="JOIN_DIALOG_FILE",
                    role=CharacterResourceRole.JOIN_DIALOGUE,
                    target_type=ResourceTargetType.DIALOGUE,
                    target_resref="GHOST",
                ),
            ]
        }
    )
    metadata_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)
    database.replace_metadata(metadata_run, metadata)
    _finish_successful_run(database, metadata_run)

    character = make_resource()
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    database.apply_detail_batch(
        character_run,
        [CharacterExtraction.from_dump(character, make_dump(dialog="AERIE"))],
        [],
    )

    dialogue_resources = [
        make_dialogue_resource("AERIE.DLG"),
        make_dialogue_resource("BAERIE.DLG"),
    ]
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, dialogue_resources)
    database.apply_dialogue_batch(
        dialogue_run,
        [
            DialogueExtraction.from_dump(make_dialogue_dump("AERIE.DLG")),
            DialogueExtraction.from_dump(make_dialogue_dump("BAERIE.DLG")),
        ],
        [],
    )
    _finish_successful_run(database, character_run)
    _finish_successful_run(database, dialogue_run)

    summary = database.rebuild_attributions()
    attribution = next(row for row in _attribution_rows(path) if row.run_id == summary.run_id)
    assert summary.attributed_dialogue_lines == 8
    assert attribution.status.value == "partial_match"
    assert attribution.dialogue_status is DetailStatus.COMPLETE
    assert attribution.declared_dialogue_resrefs == ["AERIE", "BAERIE", "GHOST"]
    assert attribution.missing_dialogue_resrefs == ["GHOST"]
    assert attribution.resolved_dialogue_resource_names == ["AERIE.DLG", "BAERIE.DLG"]


def test_attribution_builds_voice_resources_from_shared_cre_variants(
    tmp_path: Path,
) -> None:
    path = tmp_path / "voices.lancedb"
    database = PipelineDatabase(path)
    metadata = make_metadata_extraction()
    metadata_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)
    database.replace_metadata(metadata_run, metadata)
    _finish_successful_run(database, metadata_run)

    resources = [
        make_resource(name)
        for name in (
            "OHHEX8.CRE",
            "OHHEX9.CRE",
            "OHHEX25.CRE",
            "OHHEXFL.CRE",
            "OHHEXMS.CRE",
        )
    ]
    direct_dialogues = ("HEXXAT", "hexxat", "HEXXA25A", "FAIL", "GHOST")
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, resources)
    details: list[CharacterExtraction] = []
    for index, (resource, dialog) in enumerate(zip(resources, direct_dialogues, strict=True)):
        extraction = CharacterExtraction.from_dump(
            resource,
            make_dump(
                resource.resource_name,
                short_name="Hexxat",
                long_name="Hexxat",
                death_variable="HEXXAT" if index % 2 else "hexxat",
                dialog=dialog,
            ),
        )
        if index < 3:
            extraction = extraction.model_copy(
                update={
                    "detail": extraction.detail.model_copy(
                        update={"kit_ids_value": KitIdsValue(0x4001)}
                    )
                }
            )
        details.append(extraction)
    database.apply_detail_batch(character_run, details, [])

    dialogue_resources = [
        make_dialogue_resource("HEXXAT.DLG"),
        make_dialogue_resource("HEXXA25A.DLG"),
        make_dialogue_resource("FAIL.DLG"),
    ]
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, dialogue_resources)
    database.apply_dialogue_batch(
        dialogue_run,
        [
            DialogueExtraction.from_dump(make_dialogue_dump("HEXXAT.DLG")),
            DialogueExtraction.from_dump(make_dialogue_dump("HEXXA25A.DLG")),
        ],
        [("FAIL.DLG", "broken DLG")],
    )
    _finish_successful_run(database, character_run)
    _finish_successful_run(database, dialogue_run)

    summary = database.rebuild_attributions()

    voices = [voice for voice in _voice_rows(path) if voice.run_id == summary.run_id]
    assert len(voices) == 1
    voice = voices[0]
    assert voice.voice_id == "hexxat"
    assert voice.display_name == "Hexxat"
    assert voice.variant_resource_names == sorted(
        [resource.resource_name for resource in resources], key=str.casefold
    )
    assert voice.dialogue_resrefs == ["HEXXA25A", "HEXXAT"]
    assert voice.prompt == (
        "Name: Hexxat\nGender: Female\nRace: Elf\nClass: Cleric Mage\nKit: Berserker\n"
        "Alignment: Lawful Good"
    )
    voice_table = lancedb.connect(path).open_table("voice_resources")
    assert voice_table.search("Hexxat", query_type="fts").limit(10).to_arrow().num_rows == 1
    assert voice_table.search("HEXXA25A", query_type="fts").limit(10).to_arrow().num_rows == 1

    refresh_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(refresh_run, resources)
    assert _voice_rows(path) == voices


def test_attribution_groups_voices_by_name_and_omits_zero_line_groups(
    tmp_path: Path,
) -> None:
    path = tmp_path / "voice-identities.lancedb"
    database = PipelineDatabase(path)
    resources = [make_resource(name) for name in ("ALHEL.CRE", "ALHEL2.CRE", "JOLUS.CRE")]
    run_id = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(run_id, resources)

    alhel = CharacterExtraction.from_dump(
        resources[0],
        make_dump(
            "ALHEL.CRE",
            short_name="Alhelor",
            long_name="Alhelor",
            death_variable="NOBLEORDER",
            dialog="ALHEL",
        ),
    )
    alhel_variant = CharacterExtraction.from_dump(
        resources[1],
        make_dump(
            "ALHEL2.CRE",
            short_name="alhelor",
            long_name="alhelor",
            death_variable="ANOTHERORDER",
            dialog="ALHEL2",
        ),
    )
    jolus = CharacterExtraction.from_dump(
        resources[2],
        make_dump(
            "JOLUS.CRE",
            short_name="Sir Jolus",
            long_name="Sir Jolus",
            death_variable="NOBLEORDER",
            dialog=None,
        ),
    )
    database.apply_detail_batch(run_id, [alhel, alhel_variant, jolus], [])
    _finish_successful_run(database, run_id)
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    dialogue_resources = [
        make_dialogue_resource("ALHEL.DLG"),
        make_dialogue_resource("ALHEL2.DLG"),
    ]
    database.replace_dialogue_inventory(dialogue_run, dialogue_resources)
    database.apply_dialogue_batch(
        dialogue_run,
        [
            DialogueExtraction.from_dump(make_dialogue_dump(resource.resource_name))
            for resource in dialogue_resources
        ],
        [],
    )
    _finish_successful_run(database, dialogue_run)
    _finish_empty_stage(database, tmp_path, RunKind.METADATA)

    summary = database.rebuild_attributions()

    voices = {
        voice.voice_id: voice for voice in _voice_rows(path) if voice.run_id == summary.run_id
    }
    assert list(voices) == ["alhelor"]
    assert voices["alhelor"].variant_resource_names == ["ALHEL.CRE", "ALHEL2.CRE"]
    assert voices["alhelor"].dialogue_resrefs == ["ALHEL", "ALHEL2"]


def test_voice_prompt_uses_one_actual_cre_metadata_tuple(tmp_path: Path) -> None:
    path = tmp_path / "voice-prompt.lancedb"
    database = PipelineDatabase(path)
    metadata = make_metadata_extraction()
    metadata_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)
    database.replace_metadata(metadata_run, metadata)
    _finish_successful_run(database, metadata_run)

    resources = [make_resource("SENDAI.CRE"), make_resource("SENDAI_.CRE")]
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, resources)
    elf_cleric_mage = CharacterExtraction.from_dump(
        resources[0],
        make_dump(
            "SENDAI.CRE",
            short_name="Sendai",
            long_name="Sendai",
            death_variable="SENDAI",
            dialog="SENDAI",
        ),
    )
    human_fighter = _with_character_detail(
        CharacterExtraction.from_dump(
            resources[1],
            make_dump(
                "SENDAI_.CRE",
                short_name="Sendai",
                long_name="Sendai",
                death_variable="SENDAI",
                dialog="SENDAI",
            ),
        ),
        race_id=RaceId(1),
        class_id=ClassId(2),
        alignment_id=AlignmentId(33),
    )
    database.apply_detail_batch(character_run, [elf_cleric_mage, human_fighter], [])
    _finish_successful_run(database, character_run)
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    dialogue_resource = make_dialogue_resource("SENDAI.DLG")
    database.replace_dialogue_inventory(dialogue_run, [dialogue_resource])
    database.apply_dialogue_batch(
        dialogue_run,
        [DialogueExtraction.from_dump(make_dialogue_dump("SENDAI.DLG"))],
        [],
    )
    _finish_successful_run(database, dialogue_run)

    summary = database.rebuild_attributions()

    voice = next(voice for voice in _voice_rows(path) if voice.run_id == summary.run_id)
    assert voice.voice_id == "sendai"
    assert voice.prompt == (
        "Name: Sendai\nGender: Female\nRace: Elf\nClass: Cleric Mage\nAlignment: Lawful Good"
    )


def test_interrupted_attribution_is_not_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    character = make_resource()
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    database.apply_detail_batch(
        character_run,
        [CharacterExtraction.from_dump(character, make_dump())],
        [],
    )
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, [make_dialogue_resource()])
    database.apply_dialogue_batch(
        dialogue_run,
        [DialogueExtraction.from_dump(make_dialogue_dump())],
        [],
    )
    _finish_successful_run(database, character_run)
    _finish_successful_run(database, dialogue_run)
    _finish_empty_stage(database, tmp_path, RunKind.METADATA)
    published = database.rebuild_attributions()
    published_attributions = [
        row for row in _attribution_rows(path) if row.run_id == published.run_id
    ]
    published_voices = [row for row in _voice_rows(path) if row.run_id == published.run_id]

    original_upsert = database._upsert

    def fail_voice_publication(
        table_name: str,
        key: str,
        records: Sequence[LanceModel],
    ) -> None:
        if table_name == "voice_resources":
            raise OSError("simulated attribution write failure")
        original_upsert(table_name, key, records)

    monkeypatch.setattr(database, "_upsert", fail_voice_publication)
    with pytest.raises(OSError, match="simulated attribution write failure"):
        database.rebuild_attributions()

    runs = _rows(path, "extraction_runs", ExtractionRunRecord)
    completed = [
        run
        for run in runs
        if run.run_kind is RunKind.ATTRIBUTION and run.status is RunStatus.COMPLETE
    ]
    failed = [
        run
        for run in runs
        if run.run_kind is RunKind.ATTRIBUTION and run.status is RunStatus.FAILED
    ]
    assert [run.id for run in completed] == [published.run_id]
    assert len(failed) == 1
    assert [
        row for row in _attribution_rows(path) if row.run_id == published.run_id
    ] == published_attributions
    assert [row for row in _voice_rows(path) if row.run_id == published.run_id] == published_voices
    assert not [row for row in _voice_rows(path) if row.run_id == failed[0].id]


def test_stats_runs_and_full_text_indexes_follow_completed_batches(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    resources = [make_resource(), make_resource("MINSC.CRE"), make_resource("JAHEIRA.CRE")]
    run_id = database.start_run(tmp_path, "iecli test")
    assert len(run_id) == 32
    database.replace_inventory(run_id, resources)
    database.apply_detail_batch(
        run_id,
        [
            CharacterExtraction.from_dump(
                resources[0], make_dump(short_name="The Winged Cleric", dialog="AERIE")
            )
        ],
        [("MINSC.CRE", "bad CRE")],
    )
    assert database.stats().model_dump() == {
        "total": 3,
        "complete": 1,
        "failed": 1,
        "pending": 1,
        "with_dialog": 1,
    }
    database.finish_run(
        run_id,
        status=RunStatus.COMPLETE_WITH_ERRORS,
        attempted=2,
        extracted=1,
        failures=1,
        error="partial",
    )
    stored_run = _rows(path, "extraction_runs", ExtractionRunRecord)[0]
    assert stored_run.id == run_id
    assert stored_run.status == "complete_with_errors"
    assert stored_run.resources_discovered == 3
    assert stored_run.error == "partial"

    table = lancedb.connect(path).open_table("characters")
    assert table.search("Winged", query_type="fts").limit(10).to_arrow().num_rows == 1
    assert table.search("clerics", query_type="fts").limit(10).to_arrow().num_rows == 1
    assert table.search("the", query_type="fts").limit(10).to_arrow().num_rows == 1
    assert table.search("MINSC", query_type="fts").limit(10).to_arrow().num_rows == 1
    for index in TABLE_INDEXES["characters"]:
        stats = table.index_stats(index.name)
        assert stats is not None
        assert stats.num_unindexed_rows == 0


def test_run_and_inventory_invariants_fail_without_changes(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    character_run = database.start_run(tmp_path, "iecli test")
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)

    with pytest.raises(AssertionError, match="Unknown extraction run"):
        database.replace_inventory("missing", [])
    with pytest.raises(AssertionError, match="expected characters"):
        database.replace_inventory(dialogue_run, [])
    with pytest.raises(AssertionError, match="expected dialogues"):
        database.replace_dialogue_inventory(character_run, [])
    duplicate = make_resource()
    with pytest.raises(AssertionError, match="duplicate keys"):
        database.replace_inventory(character_run, [duplicate, duplicate])
    assert _character_rows(path) == []

    database.finish_run(
        character_run,
        status=RunStatus.COMPLETE,
        attempted=0,
        extracted=0,
        failures=0,
    )
    with pytest.raises(AssertionError, match="already complete"):
        database.replace_inventory(character_run, [])


def test_index_failure_leaves_run_open_for_failed_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "pipeline.lancedb"
    database = PipelineDatabase(path)
    run_id = database.start_run(tmp_path, "iecli test")

    def fail_optimization(_name: str, _table: object) -> None:
        raise OSError("simulated index failure")

    monkeypatch.setattr(database, "_optimize", fail_optimization)
    with pytest.raises(OSError, match="simulated index failure"):
        database.finish_run(
            run_id,
            status=RunStatus.COMPLETE,
            attempted=0,
            extracted=0,
            failures=0,
        )
    assert _rows(path, "extraction_runs", ExtractionRunRecord)[0].status is RunStatus.RUNNING

    database.finish_run(
        run_id,
        status=RunStatus.FAILED,
        attempted=0,
        extracted=0,
        failures=0,
        error="simulated index failure",
    )
    stored = _rows(path, "extraction_runs", ExtractionRunRecord)[0]
    assert stored.status is RunStatus.FAILED
    assert stored.error == "simulated index failure"


def test_storage_models_enforce_non_relational_invariants() -> None:
    with pytest.raises(ValidationError, match="Input should be"):
        ResourceSource(kind="archive", path="A.DLG")
    source = ResourceSource(kind=SourceKind.OVERRIDE, path="A.DLG")
    pending = ExtractionState(
        run_id="run", status=DetailStatus.PENDING, error=None, updated_at="now"
    )
    with pytest.raises(ValidationError, match="only complete DLGs carry a serialized size"):
        DialogueRecord(
            resource_name="A.DLG",
            resref="A",
            source=source,
            extraction=pending,
            serialized_size=1,
            search_text="A",
        )
    with pytest.raises(ValidationError, match="dialogue line id must be"):
        DialogueLineRecord(
            id="wrong",
            run_id="run",
            dialogue_resource_name="A.DLG",
            line_kind="npc",
            state_index=0,
            transition_index=None,
            strref=1,
            text="Hello",
            tokens=[],
            serialized_size=1,
            search_text="A Hello",
        )
    with pytest.raises(ValidationError, match="character sound id must be"):
        CharacterSoundRecord(
            id="wrong",
            run_id="run",
            character_resource_name="A.CRE",
            slot_id=9,
            strref=1,
            text="Attack!",
            serialized_size=1,
            search_text="A Attack",
        )
    implicit_current_dialog = DialogueTransitionRecord(
        id="A.DLG:0:0",
        run_id="run",
        dialogue_resource_name="A.DLG",
        state_index=0,
        transition_index=0,
        flags_raw=0,
        flags_decoded=[],
        trigger_index=None,
        trigger_text=None,
        action_index=None,
        action_text=None,
        next_dialog=None,
        next_state_index=0,
        terminates_dialog=False,
        serialized_size=1,
        search_text="A",
    )
    assert implicit_current_dialog.next_state_index == 0
    with pytest.raises(ValidationError, match="no destination state"):
        DialogueTransitionRecord.model_validate(
            implicit_current_dialog.model_dump() | {"next_state_index": None},
            strict=True,
        )
    terminating = DialogueTransitionRecord.model_validate(
        implicit_current_dialog.model_dump()
        | {
            "trigger_index": 1,
            "trigger_text": None,
            "action_index": 2,
            "action_text": None,
            "next_dialog": "A",
            "next_state_index": None,
            "terminates_dialog": True,
        },
        strict=True,
    )
    assert (terminating.next_dialog, terminating.trigger_text, terminating.action_text) == (
        "A",
        None,
        None,
    )
