"""Read-model search, ordering, pagination, and publication semantics."""

from collections import Counter
from pathlib import Path

import lancedb
import pytest

from bgvoice.character_models import CharacterExtraction
from bgvoice.database import PipelineDatabase
from bgvoice.generation_store import GenerationStore
from bgvoice.model_types import (
    AttributionStatus,
    DetailStatus,
    DialogueLineKind,
    GenerationFailureStage,
    IdentifierKind,
    ReadableItemKind,
    RunKind,
    RunStatus,
    SourceKind,
    VoiceProfileKind,
)
from bgvoice.reader import PipelineReader
from bgvoice.reader_generation import GenerationSnapshot
from bgvoice.reader_metadata import LabelResolver
from bgvoice.reader_models import (
    CharacterQuery,
    ClassQuery,
    DialogueQuery,
    IdentifierQuery,
    KitQuery,
    LineQuery,
    RaceQuery,
    ReadableItemQuery,
    SoundQuery,
    TransitionQuery,
    VoiceQuery,
)
from bgvoice.storage_records import (
    CharacterAttributionRecord,
    VoiceResourceRecord,
)
from tests.factories import (
    make_direction,
    make_dump,
    make_generated_audio,
    make_generation_failure,
    make_resource,
    make_tts_batch,
    make_voice_generation,
    make_voice_profile,
)


@pytest.mark.anyio
async def test_stats_report_the_published_pipeline_generation(
    shared_scenario_database: Path,
) -> None:
    reader = await PipelineReader.open(shared_scenario_database)
    try:
        stats = await reader.stats()
    finally:
        reader.close()

    assert stats.database_size > 0
    assert (
        stats.characters_total,
        stats.characters_complete,
        stats.characters_with_dialogue,
    ) == (12, 12, 3)
    assert (
        stats.dialogues_total,
        stats.dialogues_complete,
        stats.npc_lines,
        stats.player_lines,
        stats.journal_lines,
    ) == (3, 2, 4, 4, 2)
    assert (stats.line_records_total, stats.transition_edges_total, stats.voices_total) == (
        10,
        6,
        1,
    )
    assert (
        stats.characters_matched,
        stats.characters_missing_dialogue,
        stats.characters_dialogue_failed,
        stats.characters_without_dialogue,
    ) == (2, 1, 1, 9)
    assert stats.attribution_publication == "published"
    assert stats.attribution_completed_at is not None
    assert (stats.dialogues_attributed, stats.dialogues_unattributed) == (2, 1)
    assert (stats.attributed_dialogue_lines, stats.unattributed_dialogue_lines) == (4, 4)
    assert stats.readable_items_total == 2


def test_generation_counts_distinguish_assignments_from_inworld_voices() -> None:
    shared = make_voice_profile(
        "shared",
        inworld_voice_id="shared-provider-voice",
        description="A clear reusable voice description for this focused test.",
    )
    records = {
        "aerie": shared,
        "minsc": shared,
        "default:male": make_voice_profile("default:male", inworld_voice_id="default"),
    }
    snapshot = GenerationSnapshot(
        voices=records,
        directions=[],
        audio=[],
        batches=[],
        voice_names={},
        directions_by_line={},
        audio_by_id={},
        direction_count_by_voice=Counter(),
        audio_count_by_voice=Counter(),
        audio_voices_by_line={},
    )
    current_voices = [
        VoiceResourceRecord(
            key=VoiceResourceRecord.key_for("attribution", voice_id),
            run_id="attribution",
            voice_id=voice_id,
            family_id=voice_id,
            gender=None,
            display_name=voice_id.title(),
            prompt=f"Name: {voice_id.title()}",
            variant_resource_names=[f"{voice_id.upper()}.CRE"],
            dialogue_resrefs=[],
            search_text=voice_id,
        )
        for voice_id in ("aerie", "minsc")
    ]

    assert snapshot.pipeline_counts(current_voices)[:2] == (2, 1)


@pytest.mark.anyio
async def test_character_search_filters_explicit_order_and_pagination(
    shared_scenario_database: Path,
) -> None:
    reader = await PipelineReader.open(shared_scenario_database)
    try:
        first = await reader.characters(
            CharacterQuery(page_size=10, sort="resource_name", direction="asc")
        )
        second = await reader.characters(
            CharacterQuery(page=2, page_size=10, sort="resource_name", direction="asc")
        )
        search = await reader.characters(CharacterQuery(q="Minsc", page_size=10))
        filtered = await reader.characters(
            CharacterQuery(
                has_dialog=False,
                gender_id=2,
                source_kind=SourceKind.OVERRIDE,
                status=DetailStatus.COMPLETE,
                page_size=100,
            )
        )
        missing = await reader.characters(
            CharacterQuery(attribution_status=AttributionStatus.MISSING_DIALOGUE, page_size=10)
        )
        ordered = await reader.characters(
            CharacterQuery(sort="dialogue_transition_count", direction="desc", page_size=10)
        )
    finally:
        reader.close()

    assert (first.total, first.page_count, len(first.items)) == (12, 2, 10)
    assert [row.resource_name for row in second.items] == ["GHOST.CRE", "MINSC.CRE"]
    assert (search.sort, search.direction) == ("relevance", "desc")
    assert [row.resource_name for row in search.items] == ["MINSC.CRE"]
    assert (
        search.items[0].gender_label,
        search.items[0].race_label,
        search.items[0].class_label,
        search.items[0].alignment_label,
    ) == ("Female", "Elf", "Cleric / Mage", "Lawful Good")
    assert filtered.total == 9
    assert [row.resource_name for row in missing.items] == ["GHOST.CRE"]
    assert (
        ordered.items[0].resource_name,
        ordered.items[0].dialogue_transition_count,
    ) == ("AERIE.CRE", 3)


@pytest.mark.anyio
async def test_metadata_queries_merge_canonical_ids_with_campaign_text(
    shared_scenario_database: Path,
) -> None:
    reader = await PipelineReader.open(shared_scenario_database)
    try:
        races = await reader.races(RaceQuery(page_size=100))
        soa_races = await reader.races(RaceQuery(campaign="soa", page_size=100))
        elf_search = await reader.races(RaceQuery(q="Elf", page_size=100))
        lore_search = await reader.races(RaceQuery(q="Floating aberrations", page_size=100))
        named_races = await reader.races(
            RaceQuery(sort="display_name", direction="asc", page_size=100)
        )
        classes = await reader.classes(ClassQuery(class_id=14, fallen=False, page_size=100))
        kits = await reader.kits(KitQuery(q="Berserker", class_id=2, page_size=100))
        identifiers = await reader.identifiers(
            IdentifierQuery(kind=IdentifierKind.GENDER, q="Female", page_size=100)
        )
        labels = LabelResolver.from_snapshot(await reader.metadata_snapshot())
    finally:
        reader.close()

    human = next(row for row in races.items if row.race_id == 1)
    gnome = next(row for row in races.items if row.race_id == 7)
    beholder = next(row for row in races.items if row.race_id == 123)
    vampire = next(row for row in races.items if row.race_id == 125)
    assert (human.symbols, human.campaign_texts, human.lore) == (["HUMAN"], [], None)
    assert (gnome.symbols, gnome.campaign_texts[0].campaigns) == ([], ["SOA"])
    assert {row.display_name for row in soa_races.items} == {"Elf", "Gnome", "Vampire"}
    assert {text.record.source_resource for text in elf_search.items[0].campaign_texts} == {
        "RACETEXT.2DA",
        "BGRACTXT.2DA",
    }
    assert beholder.lore is not None
    assert (beholder.display_name, beholder.lore.help_text) == ("Beholder", "Floating aberrations.")
    assert (len(vampire.campaign_texts), vampire.lore is not None) == (1, True)
    assert [row.race_id for row in lore_search.items] == [123]
    assert [row.display_name for row in named_races.items] == sorted(
        (row.display_name for row in named_races.items),
        key=str.casefold,
    )
    assert classes.total == 2
    assert {tuple(row.campaigns) for row in classes.items} == {("SOA",), ("BG1",)}
    assert (kits.total, kits.items[0].class_symbols, kits.items[0].kit_symbols) == (
        1,
        ["FIGHTER"],
        ["BERSERKER"],
    )
    assert (identifiers.total, identifiers.items[0].symbols) == (1, ["FEMALE"])
    assert labels.race_description(2) == "The Tel'Quessir."
    assert labels.race_description(123) == "Floating aberrations."
    assert labels.class_description(14) == "A multiclass spellcaster."


@pytest.mark.anyio
async def test_readable_items_search_filter_and_order(
    shared_scenario_database: Path,
) -> None:
    reader = await PipelineReader.open(shared_scenario_database)
    try:
        search = await reader.readable_items(ReadableItemQuery(q="long road", page_size=10))
        scrolls = await reader.readable_items(
            ReadableItemQuery(kind=ReadableItemKind.SCROLL, page_size=10)
        )
        longest = await reader.readable_items(
            ReadableItemQuery(sort="text_length", direction="desc", page_size=10)
        )
    finally:
        reader.close()

    assert (search.total, search.sort, search.items[0].display_title) == (
        1,
        "relevance",
        "The Long Road",
    )
    assert [(item.kind, item.resource_name) for item in scrolls.items] == [
        (ReadableItemKind.SCROLL, "SCROLL.ITM")
    ]
    assert [item.resource_name for item in longest.items] == ["BOOK.ITM", "SCROLL.ITM"]


@pytest.mark.anyio
async def test_dialogue_line_voice_sound_and_transition_queries(
    shared_scenario_database: Path,
) -> None:
    reader = await PipelineReader.open(shared_scenario_database)
    try:
        dialogues = await reader.dialogues(
            DialogueQuery(attributed=False, q="UNUSED", page_size=10)
        )
        lines = await reader.lines(
            LineQuery(
                q="Quest",
                line_kind=DialogueLineKind.JOURNAL,
                attributed=False,
                page_size=10,
            )
        )
        tokenized = await reader.lines(
            LineQuery(
                q="DAYANDMONTH", line_kind=DialogueLineKind.NPC, attributed=True, page_size=10
            )
        )
        by_length = await reader.lines(
            LineQuery(
                line_kind=DialogueLineKind.PLAYER,
                sort="text_length",
                direction="desc",
                page_size=10,
            )
        )
        voices = await reader.voices(VoiceQuery(page_size=10))
        sounds = await reader.sounds(
            SoundQuery(
                q="fallen",
                character_resource_name="AERIE.CRE",
                slot_id=9,
                page_size=20,
            )
        )
        actions = await reader.transitions(
            TransitionQuery(
                q="SetGlobal",
                dialogue_resource_name="AERIE.DLG",
                terminates_dialog=False,
                page_size=10,
            )
        )
        terminal = await reader.transitions(
            TransitionQuery(terminates_dialog=True, sort="location", direction="asc", page_size=10)
        )
    finally:
        reader.close()

    assert [(row.resource_name, row.character_count) for row in dialogues.items] == [
        ("UNUSED.DLG", 0)
    ]
    assert (lines.total, lines.items[0].dialogue_resource_name) == (1, "UNUSED.DLG")
    assert tokenized.items[0].tokens == ["DAYANDMONTH"]
    assert [len(row.text or "") for row in by_length.items] == sorted(
        (len(row.text or "") for row in by_length.items),
        reverse=True,
    )
    assert (voices.total, voices.sort, voices.items[0].id) == (1, "npc_line_count", "aerie")
    assert (voices.items[0].npc_line_count, voices.items[0].dialogue_resrefs) == (2, ["AERIE"])
    assert "Race description:\nThe Tel'Quessir." in voices.items[0].prompt
    assert "Class description:\nA multiclass spellcaster." in voices.items[0].prompt
    assert (sounds.total, sounds.sort, sounds.items[0].character_resource_name) == (
        1,
        "relevance",
        "AERIE.CRE",
    )
    assert (sounds.items[0].slot_symbols, sounds.items[0].slot_groups) == (
        ["ATTACK_VOICE"],
        ["BATTLE_CRIES"],
    )
    assert {row.dialogue_resource_name for row in actions.items} == {"AERIE.DLG"}
    edge = actions.items[0]
    assert (edge.action_text, edge.next_dialog, edge.next_state_index) == (
        'SetGlobal("Quest","GLOBAL",1)',
        "MINSC",
        7,
    )
    assert [row.id for row in terminal.items] == ["AERIE.DLG:0:1", "UNUSED.DLG:0:1"]


@pytest.mark.anyio
async def test_generation_progress_enriches_and_filters_source_resources(
    scenario_database: Path,
) -> None:
    line_id = "AERIE.DLG:npc:0:-"
    direction = make_direction("aerie", line_id, directed_dialogue="[warmly] Hello.")
    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_voice_profiles(
            [
                make_voice_profile(
                    "aerie",
                    description="A gentle young adventurer with a warm, earnest delivery.",
                ),
                make_voice_profile(
                    "narrator",
                    inworld_voice_id="voice-narrator",
                    description="A restrained storyteller with a clear and neutral delivery.",
                ),
            ]
        )
        await store.upsert_voice_generations(
            [make_voice_generation("aerie"), make_voice_generation("narrator")]
        )
        await store.upsert_directed_lines([direction])
        await store.upsert_generated_audio([make_generated_audio(direction)])
        await store.upsert_batches(
            [
                make_tts_batch(["d-running"], operation_name="operations/running"),
                make_tts_batch(
                    ["d-failed"],
                    operation_name="operations/failed",
                    status=RunStatus.FAILED,
                    error="provider rejected the batch",
                ),
            ]
        )
        await store.upsert_failures(
            [
                make_generation_failure(
                    stage,
                    line_id=line_id,
                    error=f"{stage.value} failed",
                )
                for stage in GenerationFailureStage
            ]
        )
    finally:
        store.close()

    reader = await PipelineReader.open(scenario_database)
    try:
        voice = (await reader.voices(VoiceQuery(page_size=10))).items[0]
        dialogue = (await reader.dialogues(DialogueQuery(q="AERIE", page_size=10))).items[0]
        all_voice_lines = await reader.lines(LineQuery(voice_id="aerie", page_size=10))
        directed = await reader.lines(LineQuery(voice_id="aerie", directed=True, page_size=10))
        pending = await reader.lines(LineQuery(voice_id="aerie", voiced=False, page_size=10))
        by_dialogue = await reader.lines(
            LineQuery(
                dialogue_resource_name="AERIE.DLG",
                line_kind=DialogueLineKind.NPC,
                voiced=True,
                page_size=10,
            )
        )
        stats = await reader.stats()
    finally:
        reader.close()

    assert voice.generated_voice is not None
    assert (
        voice.generated_voice.profile_id,
        voice.generated_voice.kind,
    ) == ("aerie", VoiceProfileKind.DEDICATED)
    assert voice.generated_voice.inworld_voice_id == "voice-aerie"
    assert (voice.directed_line_count, voice.generated_audio_count) == (1, 1)
    assert (dialogue.directed_line_count, dialogue.generated_audio_count) == (1, 1)
    assert (all_voice_lines.total, directed.total, pending.total, by_dialogue.total) == (2, 1, 1, 1)
    assert directed.items[0].directions[0].audio_id == direction.id
    assert directed.items[0].directions[0].character == direction.character
    assert directed.items[0].directions[0].narrator is None
    assert (
        stats.generated_voices,
        stats.unique_inworld_voices,
        stats.directed_lines,
        stats.generated_audios,
        stats.running_tts_batches,
        stats.failed_tts_batches,
        stats.voice_creation_failures,
        stats.dialogue_direction_failures,
        stats.audio_generation_failures,
    ) == (1, 1, 1, 1, 1, 1, 1, 1, 1)


@pytest.mark.anyio
async def test_fts_relevance_and_explicit_sort_page_the_complete_match_set(tmp_path: Path) -> None:
    path = tmp_path / "fts.lancedb"
    resources = [make_resource(f"R{index:02}.CRE") for index in range(25)]
    database = PipelineDatabase(path)
    run_id = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(run_id, resources)
    database.apply_detail_batch(
        run_id,
        [
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
        ],
        [],
    )
    database.finish_run(
        run_id,
        status=RunStatus.COMPLETE,
        attempted=len(resources),
        extracted=len(resources),
        failures=0,
    )

    reader = await PipelineReader.open(path)
    try:
        relevant = await reader.characters(CharacterQuery(q="alpha", page_size=10))
        names = [
            row.resource_name
            for page in range(1, 4)
            for row in (
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
    finally:
        reader.close()

    assert relevant.items[0].resource_name == "R00.CRE"
    assert (relevant.sort, relevant.direction) == ("relevance", "desc")
    assert names == [resource.resource_name for resource in resources]


@pytest.mark.anyio
async def test_reader_observes_committed_writes_from_another_connection(
    scenario_database: Path,
) -> None:
    reader = await PipelineReader.open(scenario_database)
    try:
        assert (await reader.stats()).characters_total == 12
        resource = make_resource("NEW.CRE")
        writer = PipelineDatabase(scenario_database)
        run_id = writer.start_run(scenario_database.parent, "iecli test")
        writer.replace_inventory(run_id, [resource])
        writer.apply_detail_batch(
            run_id,
            [
                CharacterExtraction.from_dump(
                    resource,
                    make_dump("NEW.CRE", short_name="Freshvoice", long_name=None, dialog=None),
                )
            ],
            [],
        )

        page = await reader.characters(CharacterQuery(q="Freshvoice", page_size=10))
        stats = await reader.stats()
    finally:
        reader.close()

    assert [row.resource_name for row in page.items] == ["NEW.CRE"]
    assert stats.characters_total == 1


@pytest.mark.anyio
async def test_new_upstream_run_hides_stale_attribution(scenario_database: Path) -> None:
    PipelineDatabase(scenario_database).start_run(
        scenario_database.parent,
        "iecli test",
        run_kind=RunKind.CHARACTERS,
    )
    reader = await PipelineReader.open(scenario_database)
    try:
        stats = await reader.stats()
        character = (await reader.characters(CharacterQuery(q="Aerie", page_size=10))).items[0]
        voices = await reader.voices(VoiceQuery(page_size=10))
        dialogues = await reader.dialogues(DialogueQuery(page_size=100))
        lines = await reader.lines(LineQuery(page_size=100))
    finally:
        reader.close()

    assert stats.attribution_publication == "stale"
    assert stats.attribution_completed_at is None
    assert (stats.dialogues_attributed, stats.dialogues_unattributed) == (0, 3)
    assert (stats.attributed_dialogue_lines, stats.unattributed_dialogue_lines) == (0, 8)
    assert (character.voice_id, character.attribution_status, voices.total) == (None, None, 0)
    assert all(row.character_count == 0 for row in [*dialogues.items, *lines.items])


@pytest.mark.anyio
async def test_incomplete_attribution_generation_is_invisible(scenario_database: Path) -> None:
    writer = PipelineDatabase(scenario_database)
    run_id = writer.start_run(
        scenario_database.parent,
        "iecli test",
        run_kind=RunKind.ATTRIBUTION,
    )
    connection = lancedb.connect(scenario_database)
    table = connection.open_table("character_dialogues")
    aerie = next(
        record
        for record in table.search().limit(None).to_pydantic(CharacterAttributionRecord)
        if record.character_resource_name == "AERIE.CRE"
    )
    table.add(
        [
            CharacterAttributionRecord.model_validate(
                aerie.model_copy(
                    update={
                        "key": CharacterAttributionRecord.key_for(
                            run_id, aerie.character_resource_name
                        ),
                        "run_id": run_id,
                        "resolved_dialogue_resource_names": ["UNUSED.DLG"],
                    }
                ).model_dump()
            )
        ]
    )

    reader = await PipelineReader.open(scenario_database)
    try:
        dialogues = await reader.dialogues(DialogueQuery(page_size=100))
        lines = await reader.lines(LineQuery(page_size=100))
    finally:
        reader.close()

    assert {row.resource_name: row.character_count for row in dialogues.items} == {
        "AERIE.DLG": 1,
        "MINSC.DLG": 1,
        "UNUSED.DLG": 0,
    }
    assert {row.dialogue_resource_name: row.character_count for row in lines.items} == {
        "AERIE.DLG": 1,
        "UNUSED.DLG": 0,
    }
