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
    RunKind,
    RunStatus,
    SourceKind,
)
from bgvoice.reader import PipelineReader
from bgvoice.reader_generation import GenerationSnapshot
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
    CharacterDirection,
    DirectedLineRecord,
    GeneratedAudioRecord,
    GeneratedVoiceRecord,
    GenerationFailureRecord,
    TtsBatchRecord,
    VoiceDescription,
    VoiceResourceRecord,
)
from tests.factories import make_dump, make_resource


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


def test_generation_counts_distinguish_assignments_from_inworld_voices() -> None:
    records = {
        voice_id: GeneratedVoiceRecord(
            voice_id=voice_id,
            inworld_voice_id=("shared-provider-voice" if voice_id != "default:male" else "default"),
            description=VoiceDescription(
                text="A clear reusable voice description for this focused test.",
                language_code="en-GB",
            ),
            created_at="2026-08-29T00:00:00+00:00",
        )
        for voice_id in ("aerie", "minsc", "default:male")
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
        classes = await reader.classes(ClassQuery(class_id=14, fallen=False, page_size=100))
        kits = await reader.kits(KitQuery(q="Berserker", class_id=2, page_size=100))
        identifiers = await reader.identifiers(
            IdentifierQuery(kind=IdentifierKind.GENDER, q="Female", page_size=100)
        )
    finally:
        reader.close()

    human = next(row for row in races.items if row.race_id == 1)
    gnome = next(row for row in races.items if row.race_id == 7)
    assert (human.symbols, human.source_resource, human.campaigns) == (["HUMAN"], None, [])
    assert (gnome.symbols, gnome.campaigns) == ([], ["SOA"])
    assert {row.name for row in soa_races.items} == {"Elf", "Gnome"}
    assert {row.source_resource for row in elf_search.items} == {
        "RACETEXT.2DA",
        "BGRACTXT.2DA",
    }
    assert classes.total == 2
    assert {tuple(row.campaigns) for row in classes.items} == {("SOA",), ("BG1",)}
    assert (kits.total, kits.items[0].class_symbols, kits.items[0].kit_symbols) == (
        1,
        ["FIGHTER"],
        ["BERSERKER"],
    )
    assert (identifiers.total, identifiers.items[0].symbols) == (1, ["FEMALE"])


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
        voices = await reader.voices(VoiceQuery(page_size=10))
        sounds = await reader.sounds(SoundQuery(q="fallen", slot_id=9, page_size=20))
        actions = await reader.transitions(
            TransitionQuery(q="SetGlobal", terminates_dialog=False, page_size=10)
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
    assert (voices.total, voices.sort, voices.items[0].id) == (1, "npc_line_count", "aerie")
    assert (voices.items[0].npc_line_count, voices.items[0].dialogue_resrefs) == (2, ["AERIE"])
    assert (sounds.total, sounds.sort) == (12, "relevance")
    assert (sounds.items[0].slot_symbols, sounds.items[0].slot_groups) == (
        ["ATTACK_VOICE"],
        ["BATTLE_CRIES"],
    )
    edge = next(row for row in actions.items if row.dialogue_resource_name == "AERIE.DLG")
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
    direction = DirectedLineRecord(
        id=DirectedLineRecord.id_for("aerie", line_id),
        voice_id="aerie",
        dialogue_line_id=line_id,
        character=CharacterDirection(directed_dialogue="[warmly] Hello."),
        narrator=None,
        created_at="2026-08-27T10:01:00+00:00",
    )
    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_generated_voices(
            [
                GeneratedVoiceRecord(
                    voice_id="aerie",
                    inworld_voice_id="voice-aerie",
                    description=VoiceDescription(
                        text="A gentle young adventurer with a warm, earnest delivery.",
                        language_code="en-GB",
                    ),
                    created_at="2026-08-27T10:00:00+00:00",
                ),
                GeneratedVoiceRecord(
                    voice_id="narrator",
                    inworld_voice_id="voice-narrator",
                    description=VoiceDescription(
                        text="A restrained storyteller with a clear and neutral delivery.",
                        language_code="en-GB",
                    ),
                    created_at="2026-08-27T10:00:00+00:00",
                ),
            ]
        )
        await store.upsert_directed_lines([direction])
        await store.upsert_generated_audio(
            [
                GeneratedAudioRecord(
                    id=direction.id,
                    voice_id=direction.voice_id,
                    dialogue_line_id=line_id,
                    inworld_voice_id="voice-aerie",
                    batch_operation_name="operations/complete",
                    audio=b"OggSgenerated audio",
                    created_at="2026-08-27T10:02:00+00:00",
                )
            ]
        )
        await store.upsert_batches(
            [
                TtsBatchRecord(
                    operation_name="operations/running",
                    custom_ids=["d-running"],
                    status=RunStatus.RUNNING,
                    started_at="2026-08-27T10:02:00+00:00",
                ),
                TtsBatchRecord(
                    operation_name="operations/failed",
                    custom_ids=["d-failed"],
                    status=RunStatus.FAILED,
                    started_at="2026-08-27T10:02:00+00:00",
                    completed_at="2026-08-27T10:03:00+00:00",
                    error="provider rejected the batch",
                ),
            ]
        )
        await store.upsert_failures(
            [
                GenerationFailureRecord(
                    id=GenerationFailureRecord.id_for(
                        stage,
                        "aerie",
                        None if stage is GenerationFailureStage.VOICE_CREATION else line_id,
                    ),
                    stage=stage,
                    voice_id="aerie",
                    dialogue_line_id=(
                        None if stage is GenerationFailureStage.VOICE_CREATION else line_id
                    ),
                    error_type="RuntimeError",
                    error=f"{stage.value} failed",
                    failed_at="2026-08-27T10:04:00+00:00",
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
