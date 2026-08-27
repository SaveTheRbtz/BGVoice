"""Representative application scenarios shared by behavioral tests."""

from datetime import timedelta
from pathlib import Path

import lancedb
from lancedb.pydantic import LanceModel

from bgvoice.character_models import CharacterExtraction
from bgvoice.database import PipelineDatabase
from bgvoice.dialogue_models import DialogueExtraction
from bgvoice.metadata_models import (
    BanterTimingSettings,
    CampaignDefinition,
    CampaignResourceBinding,
    CharacterResourceLink,
    ClassTextRow,
    FavoredEnemyDefinition,
    IdentifierDefinition,
    KitDefinition,
    MetadataExtraction,
    RaceTextRow,
    SoundSlotGroup,
)
from bgvoice.model_types import (
    CampaignResourceKind,
    CharacterResourceRole,
    ClassId,
    ClassTextKitId,
    IdentifierKind,
    KitIdsValue,
    KitListRowId,
    PortraitImage,
    RaceId,
    ResourceSource,
    ResourceTargetType,
    RunKind,
    RunStatus,
    SoundSlotId,
    SourceKind,
)
from tests.factories import (
    make_dialogue_dump,
    make_dialogue_resource,
    make_dump,
    make_resource,
)


def rows[Record: LanceModel](path: Path, table_name: str, model: type[Record]) -> list[Record]:
    """Read one typed LanceDB table without stale connection caching."""
    connection = lancedb.connect(path, read_consistency_interval=timedelta(0))
    return connection.open_table(table_name).search().limit(None).to_pydantic(model)


def finish_run(database: PipelineDatabase, run_id: str, *, attempted: int = 0) -> None:
    database.finish_run(
        run_id,
        status=RunStatus.COMPLETE,
        attempted=attempted,
        extracted=attempted,
        failures=0,
    )


def finish_empty_stage(database: PipelineDatabase, game_root: Path, kind: RunKind) -> str:
    run_id = database.start_run(game_root, "iecli test", run_kind=kind)
    finish_run(database, run_id)
    return run_id


def empty_metadata(source_count: int = 0) -> MetadataExtraction:
    """Return the smallest valid metadata generation."""
    return MetadataExtraction(
        source_resource_count=source_count,
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


def make_metadata() -> MetadataExtraction:
    """Metadata sufficient for labels, attribution links, and resource browsing."""
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
                (IdentifierKind.KIT, 0x4000, "KIT.IDS", ["TRUECLASS"]),
                (IdentifierKind.KIT, 0x4001, "KIT.IDS", ["BERSERKER"]),
                (IdentifierKind.SOUND_SLOT, 9, "SNDSLOT.IDS", ["ATTACK_VOICE"]),
            ]
        )
    ]
    campaigns = [
        CampaignDefinition(campaign_id="SOA", source_resource="CAMPAIGN.2DA", ordinal=0),
        CampaignDefinition(campaign_id="BG1", source_resource="CAMPAIGN.2DA", ordinal=1),
    ]
    bindings = [
        CampaignResourceBinding(
            campaign_id=campaign,
            resource_kind=kind,
            resource_resref=resource,
        )
        for campaign, kind, resource in (
            ("SOA", CampaignResourceKind.RACE_TEXT, "RACETEXT"),
            ("SOA", CampaignResourceKind.CLASS_TEXT, "CLASTEXT"),
            ("BG1", CampaignResourceKind.RACE_TEXT, "BGRACTXT"),
            ("BG1", CampaignResourceKind.CLASS_TEXT, "BGCLATXT"),
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
            uppercase_name_strref=None,
            uppercase_name=None,
            biography_strref=None,
            biography=None,
        )
        for ordinal, (source, row_name, race_id, name, description) in enumerate(
            (
                ("RACETEXT.2DA", "ELF", 2, "Elf", "The Tel'Quessir."),
                ("BGRACTXT.2DA", "ELF", 2, "Elf", "An elf in the Sword Coast."),
                ("RACETEXT.2DA", "GNOME", 7, "Gnome", "A text-only race."),
            )
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
            lower_name=display.casefold(),
            description_strref=2100 + ordinal,
            description=description,
            mixed_name_strref=2200 + ordinal,
            mixed_name=display,
            biography_strref=None,
            biography=None,
            fallen=False,
            brief_description_strref=None,
            brief_description=None,
            fallen_notice_strref=None,
            fallen_notice=None,
        )
        for ordinal, (source, row_name, class_id, display, description) in enumerate(
            (
                ("CLASTEXT.2DA", "MAGE", 1, "Mage", "A practitioner of magic."),
                (
                    "CLASTEXT.2DA",
                    "CLERIC_MAGE",
                    14,
                    "Cleric / Mage",
                    "A multiclass spellcaster.",
                ),
                (
                    "BGCLATXT.2DA",
                    "CLERIC_MAGE",
                    14,
                    "Cleric / Mage",
                    "A Sword Coast spellcaster.",
                ),
            )
        )
    ]
    kit = KitDefinition(
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
    return empty_metadata().model_copy(
        update={
            "source_resource_count": 15,
            "resolved_strref_count": 12,
            "identifiers": identifiers,
            "campaigns": campaigns,
            "campaign_resource_bindings": bindings,
            "character_resource_links": [
                CharacterResourceLink(
                    source_resource="PDIALOG.2DA",
                    ordinal=0,
                    death_variable="Aerie",
                    source_column="POST_DIALOG_FILE",
                    role=CharacterResourceRole.POST_DIALOGUE,
                    target_type=ResourceTargetType.DIALOGUE,
                    target_resref="AERIE",
                )
            ],
            "sound_slot_groups": [
                SoundSlotGroup(
                    source_resource="SPEECH.2DA",
                    ordinal=0,
                    row_name="BATTLE_CRIES",
                    offset=SoundSlotId(8),
                    count=4,
                )
            ],
            "favored_enemies": [
                FavoredEnemyDefinition(
                    source_resource="HATERACE.2DA",
                    ordinal=0,
                    row_name="BEHOLDER",
                    name_strref=4000,
                    name="Beholder",
                    race_id=RaceId(123),
                    help_strref=4001,
                    help_text="Floating aberrations.",
                )
            ],
            "race_text_rows": race_texts,
            "class_text_rows": class_texts,
            "kits": [kit],
        }
    )


def build_scenario_database(path: Path) -> Path:
    """Publish one representative pipeline generation through public repository APIs."""
    database = PipelineDatabase(path)
    game_root = path.parent / "game"

    metadata = make_metadata()
    metadata_run = database.start_run(game_root, "iecli test", run_kind=RunKind.METADATA)
    database.replace_metadata(metadata_run, metadata)
    finish_run(database, metadata_run, attempted=metadata.source_resource_count)

    resources = [
        make_resource("AERIE.CRE"),
        make_resource("MINSC.CRE"),
        make_resource("EMPTY.CRE"),
        make_resource("GHOST.CRE"),
        *[make_resource(f"EXTRA{index}.CRE") for index in range(8)],
    ]
    details = [
        CharacterExtraction.from_dump(
            resource,
            make_dump(
                resource.resource_name,
                short_name=("Nameless" if resource.resref == "EMPTY" else resource.resref.title()),
                long_name=None,
                death_variable=resource.resref,
                dialog={
                    "AERIE": "AERIE",
                    "MINSC": "MINSC",
                    "GHOST": "GHOST",
                }.get(resource.resref),
            ),
        )
        for resource in resources
    ]
    character_run = database.start_run(game_root, "iecli test", run_kind=RunKind.CHARACTERS)
    database.replace_inventory(character_run, resources)
    database.apply_detail_batch(character_run, details, [])
    finish_run(database, character_run, attempted=len(details))

    dialogue_resources = [
        make_dialogue_resource("AERIE.DLG"),
        make_dialogue_resource("MINSC.DLG"),
        make_dialogue_resource("UNUSED.DLG"),
    ]
    dialogue_run = database.start_run(game_root, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, dialogue_resources)
    database.apply_dialogue_batch(
        dialogue_run,
        [
            DialogueExtraction.from_dump(make_dialogue_dump("AERIE.DLG")),
            DialogueExtraction.from_dump(make_dialogue_dump("UNUSED.DLG")),
        ],
        [("MINSC.DLG", "missing test dialogue")],
    )
    database.finish_run(
        dialogue_run,
        status=RunStatus.COMPLETE_WITH_ERRORS,
        attempted=3,
        extracted=2,
        failures=1,
    )

    portrait_run = database.start_run(game_root, "iecli test", run_kind=RunKind.PORTRAITS)
    database.replace_portraits(
        portrait_run,
        [
            PortraitImage(
                resref="AERIES",
                source=ResourceSource(
                    kind=SourceKind.OVERRIDE,
                    path=str(game_root / "override" / "AERIES.BMP"),
                ),
                width=54,
                height=84,
                png=b"\x89PNG\r\n\x1a\nfixture",
            )
        ],
    )
    finish_run(database, portrait_run, attempted=1)
    database.rebuild_attributions()
    return path
