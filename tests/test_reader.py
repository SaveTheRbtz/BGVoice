"""Typed read-model contracts for the pipeline browser."""

import asyncio
from pathlib import Path
from typing import ClassVar, Self

import lancedb
import pytest
from lancedb.pydantic import LanceModel
from pydantic import model_validator

import bgvoice.reader as reader_module
from bgvoice.character_models import (
    CharacterExtraction,
)
from bgvoice.database import PipelineDatabase
from bgvoice.dialogue_models import (
    DialogueExtraction,
)
from bgvoice.metadata_models import (
    IdentifierDefinition,
    SoundSlotGroup,
)
from bgvoice.model_types import (
    AttributionStatus,
    DetailStatus,
    DialogueLineKind,
    IdentifierKind,
    RaceId,
    RunKind,
    RunStatus,
    SoundSlotId,
    SourceKind,
)
from bgvoice.reader import PipelineReader
from bgvoice.reader_models import (
    CharacterQuery,
    ClassQuery,
    DialogueQuery,
    IdentifierQuery,
    KitQuery,
    LineQuery,
    RaceQuery,
    SoundQuery,
    TransitionQuery,
    VoiceQuery,
)
from bgvoice.storage_records import (
    CharacterAttributionRecord,
    CharacterRecord,
)
from tests.factories import make_dialogue_dump, make_dialogue_resource, make_dump, make_resource
from tests.test_database import make_metadata_extraction


@pytest.fixture
def web_database(tmp_path: Path) -> Path:
    """Build enough representative data to exercise every browser collection."""
    path = tmp_path / "pipeline.lancedb"
    aerie = make_resource()
    minsc = make_resource("MINSC.CRE")
    empty = make_resource("EMPTY.CRE")
    ghost = make_resource("GHOST.CRE")
    extras = [make_resource(f"EXTRA{index}.CRE") for index in range(8)]

    aerie_dump = make_dump()
    aerie_dump = aerie_dump.model_copy(
        update={"header": aerie_dump.header.model_copy(update={"racial_enemy": RaceId(123)})}
    )
    details = [
        CharacterExtraction.from_dump(aerie, aerie_dump),
        CharacterExtraction.from_dump(
            minsc,
            make_dump(
                "MINSC.CRE",
                short_name="Minsc",
                long_name="Minsc",
                death_variable="Minsc",
                dialog="MINSC",
            ),
        ),
        CharacterExtraction.from_dump(
            empty,
            make_dump(
                "EMPTY.CRE",
                short_name="Nameless",
                long_name=None,
                death_variable="Empty",
                dialog="NONE",
            ),
        ),
        CharacterExtraction.from_dump(
            ghost,
            make_dump(
                "GHOST.CRE",
                short_name="Ghost",
                long_name="Ghost",
                death_variable="Ghost",
                dialog="GHOST",
            ),
        ),
        *[
            CharacterExtraction.from_dump(
                resource,
                make_dump(
                    resource.resource_name,
                    short_name=resource.resref.title(),
                    long_name=None,
                    death_variable=resource.resref,
                    dialog="NONE",
                ),
            )
            for resource in extras
        ],
    ]

    database = PipelineDatabase(path)
    metadata = make_metadata_extraction()
    metadata.identifiers.append(
        IdentifierDefinition(
            kind=IdentifierKind.SOUND_SLOT,
            value=9,
            source_resource="SNDSLOT.IDS",
            ordinal=len(metadata.identifiers),
            symbols=["ATTACK_VOICE"],
        )
    )
    metadata.sound_slot_groups.extend(
        [
            SoundSlotGroup(
                source_resource="SPEECH.2DA",
                ordinal=2,
                row_name="BATTLE_CRIES",
                offset=SoundSlotId(8),
                count=4,
            ),
            SoundSlotGroup(
                source_resource="SPEECH.2DA",
                ordinal=3,
                row_name="COMBAT_VOICE",
                offset=SoundSlotId(9),
                count=1,
            ),
        ]
    )
    metadata_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)
    database.replace_metadata(metadata_run, metadata)
    database.finish_run(
        metadata_run,
        status=RunStatus.COMPLETE,
        attempted=metadata.source_resource_count,
        extracted=metadata.source_resource_count,
        failures=0,
    )
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [aerie, minsc, empty, ghost, *extras])
    database.apply_detail_batch(character_run, details, [])
    database.finish_run(
        character_run,
        status=RunStatus.COMPLETE,
        attempted=len(details),
        extracted=len(details),
        failures=0,
    )

    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(
        dialogue_run,
        [
            make_dialogue_resource(),
            make_dialogue_resource("MINSC.DLG"),
            make_dialogue_resource("UNUSED.DLG"),
        ],
    )
    database.apply_dialogue_batch(
        dialogue_run,
        [
            DialogueExtraction.from_dump(make_dialogue_dump()),
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
    database.rebuild_attributions()

    return path


def test_reader_reports_pipeline_totals(web_database: Path) -> None:
    async def verify() -> None:
        reader = await PipelineReader.open(web_database)
        try:
            stats = await reader.stats()
            assert stats.database_size > 0
            assert (
                stats.characters_total,
                stats.characters_complete,
                stats.characters_with_dialogue,
            ) == (12, 12, 3)
            assert (stats.dialogues_total, stats.dialogues_complete, stats.dialogue_lines) == (
                3,
                2,
                8,
            )
            assert stats.line_records_total == 10
            assert stats.voices_total == 1
            assert (
                stats.character_sounds_total,
                stats.soundset_lines_total,
                stats.transition_edges_total,
                stats.character_resource_links_total,
                stats.interaction_rules_total,
                stats.engine_strings_total,
            ) == (24, 1, 6, 3, 1, 2)
            assert (
                stats.sound_slot_groups_total,
                stats.favored_enemies_total,
                stats.happiness_rules_total,
                stats.banter_timing_settings_total,
            ) == (4, 1, 3, 1)
            assert (
                stats.characters_matched,
                stats.characters_partially_matched,
                stats.characters_missing_dialogue,
                stats.characters_dialogue_failed,
            ) == (1, 1, 1, 1)
            assert stats.attribution_publication == "published"
            assert stats.attribution_completed_at is not None
            assert stats.characters_unavailable == 0
            assert (stats.dialogues_attributed, stats.dialogues_unattributed) == (2, 1)
            assert (stats.attributed_dialogue_lines, stats.unattributed_dialogue_lines) == (4, 4)
            assert (
                stats.races_total,
                stats.classes_total,
                stats.kits_total,
                stats.identifiers_total,
                stats.campaigns_total,
            ) == (4, 3, 1, 8, 2)
            assert [run.run_kind for run in stats.latest_runs] == [
                "attribution",
                "dialogues",
                "characters",
                "metadata",
            ]
            assert all(type(run.id) is str for run in stats.latest_runs)
        finally:
            reader.close()

    asyncio.run(verify())


def test_reader_observes_committed_writes_from_another_connection(web_database: Path) -> None:
    async def verify() -> None:
        reader = await PipelineReader.open(web_database)
        try:
            assert (await reader.stats()).characters_total == 12

            resource = make_resource("NEW.CRE")
            writer = PipelineDatabase(web_database)
            run_id = writer.start_run(web_database.parent, "iecli test")
            writer.replace_inventory(run_id, [resource])
            writer.apply_detail_batch(
                run_id,
                [
                    CharacterExtraction.from_dump(
                        resource,
                        make_dump(
                            "NEW.CRE",
                            short_name="Freshvoice",
                            long_name=None,
                            dialog=None,
                        ),
                    )
                ],
                [],
            )

            page = await reader.characters(CharacterQuery(q="Freshvoice", page_size=10))
            assert [row.resource_name for row in page.items] == ["NEW.CRE"]
            assert (await reader.stats()).characters_total == 1

            writer.finish_run(
                run_id,
                status=RunStatus.COMPLETE,
                attempted=1,
                extracted=1,
                failures=0,
            )
        finally:
            reader.close()

    asyncio.run(verify())


def test_character_queries_cover_search_filters_sorting_and_pagination(
    web_database: Path,
) -> None:
    async def verify() -> None:
        reader = await PipelineReader.open(web_database)
        try:
            first_page = await reader.characters(
                CharacterQuery(
                    page_size=10,
                    sort="resource_name",
                    direction="asc",
                )
            )
            second_page = await reader.characters(
                CharacterQuery(
                    page=2,
                    page_size=10,
                    sort="resource_name",
                    direction="asc",
                )
            )
            assert (first_page.total, first_page.page_count, len(first_page.items)) == (12, 2, 10)
            assert [row.resource_name for row in second_page.items] == ["GHOST.CRE", "MINSC.CRE"]

            search = await reader.characters(CharacterQuery(q="Minsc", page_size=10))
            assert (search.sort, search.direction) == ("relevance", "desc")
            assert [row.resource_name for row in search.items] == ["MINSC.CRE"]
            row = search.items[0]
            assert (
                row.gender_label,
                row.race_label,
                row.class_label,
                row.alignment_label,
                row.enemy_ally_label,
                row.animation_label,
                row.racial_enemy_label,
                row.kit_label,
            ) == (
                "Female",
                "Elf",
                "Cleric / Mage",
                "Lawful Good",
                "Goodcutoff / Ally",
                "Elf Female",
                "No Race",
                "Trueclass",
            )
            assert (row.first_class_level, row.second_class_level, row.third_class_level) == (
                7,
                7,
                0,
            )

            assert (await reader.characters(CharacterQuery(q="Mins", page_size=10))).total == 0
            assert (await reader.characters(CharacterQuery(q=" !!! ", page_size=100))).total == 12
            assert (
                await reader.characters(CharacterQuery(has_dialog=False, page_size=100))
            ).total == 9
            assert (
                await reader.characters(
                    CharacterQuery(
                        gender_id=2,
                        source_kind=SourceKind.OVERRIDE,
                        status=DetailStatus.COMPLETE,
                        page_size=100,
                    )
                )
            ).total == 12

            missing = await reader.characters(
                CharacterQuery(
                    attribution_status=AttributionStatus.MISSING_DIALOGUE,
                    page_size=10,
                )
            )
            assert [item.resource_name for item in missing.items] == ["GHOST.CRE"]
            ordered = await reader.characters(
                CharacterQuery(
                    sort="dialogue_transition_count",
                    direction="desc",
                    page_size=10,
                )
            )
            assert (
                ordered.items[0].resource_name,
                ordered.items[0].dialogue_transition_count,
            ) == ("AERIE.CRE", 3)
        finally:
            reader.close()

    asyncio.run(verify())


def test_metadata_queries_outer_merge_filter_and_use_native_fts(web_database: Path) -> None:
    async def verify() -> None:
        reader = await PipelineReader.open(web_database)
        try:
            races = await reader.races(
                RaceQuery(sort="source_resource", direction="asc", page_size=100)
            )
            assert races.total == 5
            human = next(row for row in races.items if row.race_id == 1)
            assert human.symbols == ["HUMAN"]
            assert human.source_resource is None
            assert human.campaigns == []
            gnome = next(row for row in races.items if row.race_id == 7)
            assert gnome.symbols == []
            assert gnome.campaigns == ["SOA"]

            soa_races = await reader.races(RaceQuery(campaign="soa", page_size=100))
            assert {row.name for row in soa_races.items} == {"Elf", "Gnome"}
            human_search = await reader.races(RaceQuery(q="Human", page_size=100))
            assert (human_search.sort, human_search.direction) == ("relevance", "desc")
            assert [row.race_id for row in human_search.items] == [1]
            elf_search = await reader.races(
                RaceQuery(q="Elf", sort="source_resource", page_size=100)
            )
            assert {row.source_resource for row in elf_search.items} == {
                "RACETEXT.2DA",
                "BGRACTXT.2DA",
            }

            classes = await reader.classes(ClassQuery(class_id=14, fallen=False, page_size=100))
            assert classes.total == 2
            assert {tuple(row.campaigns) for row in classes.items} == {("SOA",), ("BG1",)}
            canonical_class = await reader.classes(ClassQuery(q="Fighter", page_size=100))
            assert canonical_class.items[0].source_resource is None
            assert canonical_class.items[0].class_id == 2
            assert (await reader.classes(ClassQuery(fallen=True, page_size=100))).total == 0

            kits = await reader.kits(
                KitQuery(
                    q="Berserker",
                    class_id=2,
                    sort="lower_name",
                    direction="desc",
                    page_size=100,
                )
            )
            assert kits.total == 1
            assert (
                kits.items[0].row_name,
                kits.items[0].mixed_name,
                kits.items[0].class_symbols,
                kits.items[0].kit_symbols,
            ) == ("BERSERKER", "Berserker", ["FIGHTER"], ["BERSERKER"])

            identifiers = await reader.identifiers(
                IdentifierQuery(
                    kind=IdentifierKind.GENDER,
                    q="Female",
                    page_size=100,
                )
            )
            assert identifiers.total == 1
            assert identifiers.items[0].symbols == ["FEMALE"]
            assert (await reader.identifiers(IdentifierQuery(q="Human", page_size=100))).total == 0
        finally:
            reader.close()

    asyncio.run(verify())


def test_dialogue_voice_sound_and_transition_queries(web_database: Path) -> None:
    async def verify() -> None:
        reader = await PipelineReader.open(web_database)
        try:
            dialogues = await reader.dialogues(
                DialogueQuery(attributed=False, q="UNUSED", page_size=10)
            )
            assert dialogues.total == 1
            dialogue = dialogues.items[0]
            assert (
                dialogue.resource_name,
                dialogue.character_count,
                dialogue.source_kind,
                dialogue.source_path,
            ) == ("UNUSED.DLG", 0, SourceKind.OVERRIDE, "C:/game/override/UNUSED.DLG")

            attributed = await reader.dialogues(
                DialogueQuery(
                    attributed=True,
                    status=DetailStatus.COMPLETE,
                    source_kind=SourceKind.OVERRIDE,
                    sort="character_count",
                    direction="asc",
                    page_size=10,
                )
            )
            assert [row.resource_name for row in attributed.items] == ["AERIE.DLG"]

            lines = await reader.lines(
                LineQuery(
                    q="Quest",
                    line_kind=DialogueLineKind.JOURNAL,
                    source_kind=SourceKind.OVERRIDE,
                    attributed=False,
                    sort="transition_index",
                    direction="desc",
                    page_size=10,
                )
            )
            assert lines.total == 1
            assert (
                lines.items[0].dialogue_resource_name,
                lines.items[0].transition_index,
            ) == ("UNUSED.DLG", 2)
            triggered = await reader.lines(
                LineQuery(
                    q="Hello",
                    line_kind=DialogueLineKind.NPC,
                    attributed=True,
                    page_size=10,
                )
            )
            assert triggered.items[0].state_trigger_text == 'Global("MetAerie","GLOBAL",0)'
            tokenized = await reader.lines(
                LineQuery(
                    q="DAYANDMONTH",
                    line_kind=DialogueLineKind.NPC,
                    attributed=True,
                    page_size=10,
                )
            )
            assert tokenized.items[0].tokens == ["DAYANDMONTH"]

            voices = await reader.voices(VoiceQuery(page_size=10))
            assert (voices.total, voices.sort, voices.direction) == (
                1,
                "npc_line_count",
                "desc",
            )
            aerie = voices.items[0]
            assert (
                aerie.id,
                aerie.variant_resource_names,
                aerie.dialogue_resrefs,
                aerie.npc_line_count,
            ) == ("aerie", ["AERIE.CRE"], ["AERIE"], 2)
            assert "Aerie" in aerie.prompt
            assert (
                await reader.voices(VoiceQuery(q="AERIE.CRE", voice_id="aerie", page_size=10))
            ).total == 1

            sounds = await reader.sounds(SoundQuery(q="fallen", slot_id=9, page_size=10))
            assert (sounds.total, sounds.sort, sounds.direction) == (12, "relevance", "desc")
            sound = sounds.items[0]
            assert (
                sound.text,
                sound.slot_symbols,
                sound.slot_groups,
            ) == (
                "For the fallen!",
                ["ATTACK_VOICE"],
                ["BATTLE_CRIES", "COMBAT_VOICE"],
            )
            named_sounds = await reader.sounds(SoundQuery(q="Minsc", page_size=10))
            assert {row.character_resource_name for row in named_sounds.items} == {"MINSC.CRE"}

            transitions = await reader.transitions(TransitionQuery(page_size=10))
            assert [row.id for row in transitions.items] == [
                "AERIE.DLG:0:0",
                "AERIE.DLG:0:1",
                "AERIE.DLG:1:2",
                "UNUSED.DLG:0:0",
                "UNUSED.DLG:0:1",
                "UNUSED.DLG:1:2",
            ]
            actions = await reader.transitions(
                TransitionQuery(q="SetGlobal", terminates_dialog=False, page_size=10)
            )
            edge = next(row for row in actions.items if row.dialogue_resource_name == "AERIE.DLG")
            assert (
                edge.action_text,
                edge.next_dialog,
                edge.next_state_index,
                edge.terminates_dialog,
            ) == ('SetGlobal("Quest","GLOBAL",1)', "MINSC", 7, False)
            terminal = await reader.transitions(
                TransitionQuery(
                    terminates_dialog=True,
                    sort="dialogue_resource_name",
                    direction="asc",
                    page_size=10,
                )
            )
            assert [row.id for row in terminal.items] == [
                "AERIE.DLG:0:1",
                "UNUSED.DLG:0:1",
            ]
        finally:
            reader.close()

    asyncio.run(verify())


def test_fts_pagination_sorts_the_complete_match_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "fts-pages.lancedb"
    resources = [make_resource(f"R{index:02}.CRE") for index in range(35)]
    details = [
        CharacterExtraction.from_dump(
            resource,
            make_dump(
                resource.resource_name,
                short_name="alpha alpha" if index == 0 else "alpha",
                long_name=None,
                dialog=None,
            ),
        )
        for index, resource in enumerate(resources)
    ]
    database = PipelineDatabase(path)
    run_id = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(run_id, resources)
    database.apply_detail_batch(run_id, details, [])
    database.finish_run(
        run_id,
        status=RunStatus.COMPLETE,
        attempted=len(details),
        extracted=len(details),
        failures=0,
    )
    dialogue_resources = [make_dialogue_resource(f"D{index:02}.DLG") for index in range(35)]
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, dialogue_resources)
    database.apply_dialogue_batch(
        dialogue_run,
        [
            DialogueExtraction.from_dump(make_dialogue_dump(resource.resource_name))
            for resource in dialogue_resources
        ],
        [],
    )
    database.finish_run(
        dialogue_run,
        status=RunStatus.COMPLETE,
        attempted=len(dialogue_resources),
        extracted=len(dialogue_resources),
        failures=0,
    )

    async def verify() -> None:
        reader = await PipelineReader.open(path)
        try:
            relevance = await reader.characters(CharacterQuery(q="alpha", page_size=10))
            assert (relevance.sort, relevance.direction) == ("relevance", "desc")
            assert relevance.items[0].resource_name == "R00.CRE"
            relevance_names = [
                item.resource_name
                for page in range(1, 5)
                for item in (
                    await reader.characters(CharacterQuery(q="alpha", page=page, page_size=10))
                ).items
            ]
            assert relevance_names == [resource.resource_name for resource in resources]

            class CountingCharacterRecord(CharacterRecord):
                deserialized: ClassVar[int] = 0

                @model_validator(mode="after")
                def count_deserialization(self) -> Self:
                    type(self).deserialized += 1
                    return self

            monkeypatch.setattr(reader_module, "CharacterRecord", CountingCharacterRecord)
            explicit = await reader.characters(
                CharacterQuery(
                    q="alpha",
                    sort="resource_name",
                    direction="desc",
                    page_size=10,
                )
            )
            assert (explicit.sort, explicit.direction) == ("resource_name", "desc")
            assert explicit.items[0].resource_name == "R34.CRE"
            assert CountingCharacterRecord.deserialized == len(resources)

            explicit_names = [
                item.resource_name
                for page in range(1, 5)
                for item in (
                    await reader.characters(
                        CharacterQuery(
                            q="alpha",
                            sort="resource_name",
                            direction="asc",
                            page=page,
                            page_size=10,
                        )
                    )
                ).items
            ]
            dialogue_names = [
                item.resource_name
                for page in range(1, 5)
                for item in (
                    await reader.dialogues(DialogueQuery(q="game", page=page, page_size=10))
                ).items
            ]
            line_ids = [
                item.id
                for page in range(1, 5)
                for item in (
                    await reader.lines(LineQuery(q="Hello", page=page, page_size=10))
                ).items
            ]
            assert explicit_names == [resource.resource_name for resource in resources]
            assert dialogue_names == [resource.resource_name for resource in dialogue_resources]
            assert line_ids == [
                f"{resource.resource_name}:npc:0:-" for resource in dialogue_resources
            ]
        finally:
            reader.close()

    asyncio.run(verify())


def test_reader_requires_expected_tables_but_allows_extra_tables_and_schemas(
    tmp_path: Path,
) -> None:
    with pytest.raises(AssertionError, match="does not exist"):
        asyncio.run(PipelineReader.open(tmp_path / "missing.lancedb"))

    empty_path = tmp_path / "empty.lancedb"
    empty_path.mkdir()
    with pytest.raises(AssertionError, match=r"missing tables.*characters"):
        asyncio.run(PipelineReader.open(empty_path))

    schema_path = tmp_path / "wrong-schema.lancedb"
    PipelineDatabase(schema_path)
    connection = lancedb.connect(schema_path)
    connection.drop_table("characters")

    class WrongCharacterRecord(LanceModel):
        resource_name: str

    connection.create_table("characters", schema=WrongCharacterRecord)
    connection.create_table("future_table", schema=WrongCharacterRecord)
    reader = asyncio.run(PipelineReader.open(schema_path))
    reader.close()


def test_empty_database_and_missing_attribution_are_zeroed(tmp_path: Path) -> None:
    path = tmp_path / "empty.lancedb"
    PipelineDatabase(path)

    async def verify() -> None:
        reader = await PipelineReader.open(path)
        try:
            stats = await reader.stats()
            assert stats.characters_total == 0
            assert stats.dialogues_total == 0
            assert stats.attribution_publication == "missing"
            assert stats.attribution_completed_at is None
            assert (
                stats.characters_unavailable,
                stats.characters_matched,
                stats.characters_partially_matched,
                stats.characters_missing_dialogue,
                stats.characters_dialogue_failed,
                stats.characters_without_dialogue,
                stats.dialogues_attributed,
                stats.dialogues_unattributed,
                stats.attributed_dialogue_lines,
                stats.unattributed_dialogue_lines,
            ) == (0,) * 10
        finally:
            reader.close()

    asyncio.run(verify())


def test_newer_upstream_run_invalidates_published_attribution(web_database: Path) -> None:
    writer = PipelineDatabase(web_database)
    writer.start_run(web_database.parent, "iecli test", run_kind=RunKind.CHARACTERS)

    async def verify() -> None:
        reader = await PipelineReader.open(web_database)
        try:
            stats = await reader.stats()
            assert stats.attribution_publication == "stale"
            assert stats.attribution_completed_at is None
            assert (
                stats.characters_matched,
                stats.characters_partially_matched,
                stats.characters_missing_dialogue,
                stats.characters_dialogue_failed,
                stats.characters_without_dialogue,
                stats.dialogues_attributed,
                stats.dialogues_unattributed,
                stats.attributed_dialogue_lines,
                stats.unattributed_dialogue_lines,
            ) == (0, 0, 0, 0, 0, 0, 3, 0, 8)

            character = (await reader.characters(CharacterQuery(q="Aerie", page_size=10))).items[0]
            assert character.voice_id is None
            assert character.attribution_status is None
            assert (await reader.voices(VoiceQuery(page_size=10))).total == 0

            dialogues = await reader.dialogues(DialogueQuery(page_size=100))
            lines = await reader.lines(LineQuery(page_size=100))
            assert (dialogues.total, lines.total) == (3, 10)
            assert all(row.character_count == 0 for row in dialogues.items)
            assert all(row.character_count == 0 for row in lines.items)
            assert (
                await reader.dialogues(DialogueQuery(attributed=True, page_size=100))
            ).total == 0
            assert (
                await reader.dialogues(DialogueQuery(attributed=False, page_size=100))
            ).total == 3
            assert (await reader.lines(LineQuery(attributed=True, page_size=100))).total == 0
            assert (await reader.lines(LineQuery(attributed=False, page_size=100))).total == 10
        finally:
            reader.close()

    asyncio.run(verify())


def test_reader_ignores_incomplete_attribution_generation(web_database: Path) -> None:
    writer = PipelineDatabase(web_database)
    run_id = writer.start_run(
        web_database.parent,
        "iecli test",
        run_kind=RunKind.ATTRIBUTION,
    )
    connection = lancedb.connect(web_database)
    table = connection.open_table("character_dialogues")
    aerie = next(
        record
        for record in table.search().limit(None).to_pydantic(CharacterAttributionRecord)
        if record.character_resource_name == "AERIE.CRE"
    )
    unpublished = CharacterAttributionRecord.model_validate(
        aerie.model_copy(
            update={
                "key": CharacterAttributionRecord.key_for(run_id, aerie.character_resource_name),
                "run_id": run_id,
                "resolved_dialogue_resource_names": ["UNUSED.DLG"],
            }
        ).model_dump()
    )
    table.add([unpublished])

    async def verify() -> None:
        reader = await PipelineReader.open(web_database)
        try:
            dialogues = await reader.dialogues(DialogueQuery(page_size=100))
            assert {row.resource_name: row.character_count for row in dialogues.items} == {
                "AERIE.DLG": 1,
                "MINSC.DLG": 1,
                "UNUSED.DLG": 0,
            }
            assert {
                row.resource_name
                for row in (
                    await reader.dialogues(DialogueQuery(attributed=True, page_size=100))
                ).items
            } == {"AERIE.DLG", "MINSC.DLG"}
            assert {
                row.resource_name
                for row in (
                    await reader.dialogues(DialogueQuery(attributed=False, page_size=100))
                ).items
            } == {"UNUSED.DLG"}

            lines = await reader.lines(LineQuery(page_size=100))
            assert lines.total == 10
            assert {row.dialogue_resource_name: row.character_count for row in lines.items} == {
                "AERIE.DLG": 1,
                "UNUSED.DLG": 0,
            }
            assert (await reader.lines(LineQuery(attributed=True, page_size=100))).total == 5
            assert (await reader.lines(LineQuery(attributed=False, page_size=100))).total == 5

            stats = await reader.stats()
            assert (stats.dialogues_attributed, stats.dialogues_unattributed) == (2, 1)
            assert (
                stats.attributed_dialogue_lines,
                stats.unattributed_dialogue_lines,
            ) == (4, 4)
        finally:
            reader.close()

    asyncio.run(verify())


def test_reader_opens_without_native_index(web_database: Path) -> None:
    connection = lancedb.connect(web_database)
    connection.open_table("dialogues").drop_index("dialogues_search_fts")

    reader = asyncio.run(PipelineReader.open(web_database))
    reader.close()
