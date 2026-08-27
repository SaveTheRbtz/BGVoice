"""Connect resource contract tests over a representative pipeline database."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

import pytest
from connectrpc.code import Code
from connectrpc.errors import ConnectError
from connectrpc.request import RequestContext
from google.protobuf.message import Message

from bgvoice.database import PipelineDatabase
from bgvoice.model_types import (
    PortraitImage,
    ResourceSource,
    RunKind,
    RunStatus,
    SourceKind,
)
from bgvoice.reader import PipelineReader
from bgvoice.v1 import pipeline_pb2 as pb
from bgvoice.web_contract import Collection, resource_name
from bgvoice.web_service import PipelineService
from tests.test_reader import web_database as web_database

_PARENT = "installations/bg2ee-eet"


@pytest.fixture
def service_database(web_database: Path) -> Path:
    database = PipelineDatabase(web_database)
    run_id = database.start_run(
        web_database.parent,
        "iecli test",
        run_kind=RunKind.PORTRAITS,
    )
    database.replace_portraits(
        run_id,
        [
            PortraitImage(
                resref="AERIES",
                source=ResourceSource(
                    kind=SourceKind.OVERRIDE,
                    path=str(web_database.parent / "AERIES.BMP"),
                ),
                width=54,
                height=84,
                png=b"\x89PNG\r\n\x1a\nfixture",
            )
        ],
    )
    database.finish_run(
        run_id,
        status=RunStatus.COMPLETE,
        attempted=1,
        extracted=1,
        failures=0,
    )
    return web_database


def _context[I: Message, O: Message](
    _request: I,
    _response: type[O],
) -> RequestContext[I, O]:
    return cast(RequestContext[I, O], None)


async def _run_service(
    path: Path,
    check: Callable[[PipelineService], Awaitable[None]],
) -> None:
    reader = await PipelineReader.open(path)
    try:
        service = PipelineService(lambda: reader)
        await check(service)
    finally:
        reader.close()


def test_installation_voice_character_and_dialogue_resources(service_database: Path) -> None:
    async def verify(service: PipelineService) -> None:
        installation_request = pb.GetInstallationRequest(name=_PARENT)
        installation = await service.get_installation(
            installation_request,
            _context(installation_request, pb.Installation),
        )
        assert installation.name == _PARENT
        assert installation.summary.characters == 12
        assert installation.summary.voices == 1
        assert installation.attribution_completed_at.ToJsonString().endswith("Z")

        voice_request = pb.ListVoicesRequest(
            parent=_PARENT,
            page_size=10,
            filter='search("Aerie")',
            order_by="npc_line_count desc",
        )
        voices = await service.list_voices(
            voice_request,
            _context(voice_request, pb.ListVoicesResponse),
        )
        assert voices.total_size == 1
        assert voices.voices[0].display_name == "Aerie"
        assert voices.voices[0].portrait.endswith("/aeries")
        assert voices.voices[0].characters[0].engine_resource_name == "AERIE.CRE"
        assert voices.voices[0].characters[0].npc_line_count == 2
        assert voices.voices[0].dialogues[0].engine_resource_name == "AERIE.DLG"
        assert voices.voices[0].dialogues[0].npc_line_count == 2
        get_voice_request = pb.GetVoiceRequest(name=voices.voices[0].name)
        assert (
            await service.get_voice(
                get_voice_request,
                _context(get_voice_request, pb.Voice),
            )
        ).prompt.startswith("Name: Aerie")

        first_request = pb.ListCharactersRequest(
            parent=_PARENT,
            page_size=10,
            order_by="engine_resource_name asc",
            view=pb.VIEW_FULL,
        )
        first = await service.list_characters(
            first_request,
            _context(first_request, pb.ListCharactersResponse),
        )
        assert (first.total_size, len(first.characters)) == (12, 10)
        assert first.next_page_token
        assert first.characters[0].detail.cre_version == "V1.0"
        assert first.characters[0].extraction.run.startswith(f"{_PARENT}/extractionRuns/")

        second_request = pb.ListCharactersRequest(
            parent=_PARENT,
            page_size=10,
            page_token=first.next_page_token,
            order_by="engine_resource_name asc",
            view=pb.VIEW_FULL,
        )
        second = await service.list_characters(
            second_request,
            _context(second_request, pb.ListCharactersResponse),
        )
        assert len(second.characters) == 2
        assert not second.next_page_token

        character_request = pb.GetCharacterRequest(name=first.characters[0].name)
        character = await service.get_character(
            character_request,
            _context(character_request, pb.Character),
        )
        assert character.name == first.characters[0].name
        assert character.source.path
        assert character.direct_dialogue == resource_name(Collection.DIALOGUES, "AERIE.DLG")

        all_dialogues_request = pb.ListDialoguesRequest(
            parent=_PARENT,
            page_size=10,
            order_by="dialogue_line_count desc",
            view=pb.VIEW_FULL,
        )
        dialogues = await service.list_dialogues(
            all_dialogues_request,
            _context(all_dialogues_request, pb.ListDialoguesResponse),
        )
        assert dialogues.total_size == 3
        assert dialogues.dialogues[0].detail.state_count > 0
        dialogue_request = pb.GetDialogueRequest(name=dialogues.dialogues[0].name)
        assert (
            await service.get_dialogue(
                dialogue_request,
                _context(dialogue_request, pb.Dialogue),
            )
        ).detail.dlg_version == "V1.0"

    asyncio.run(_run_service(service_database, verify))


def test_dialogue_lines_sounds_and_transitions(service_database: Path) -> None:
    async def verify(service: PipelineService) -> None:
        lines_request = pb.ListDialogueLinesRequest(
            parent=_PARENT,
            page_size=3,
            filter='line_kind = "npc" AND source_kind = "override"',
            order_by="state_index asc",
        )
        lines = await service.list_dialogue_lines(
            lines_request,
            _context(lines_request, pb.ListDialogueLinesResponse),
        )
        assert lines.total_size == 4
        assert len(lines.dialogue_lines) == 3
        line_request = pb.GetDialogueLineRequest(name=lines.dialogue_lines[0].name)
        assert (
            await service.get_dialogue_line(
                line_request,
                _context(line_request, pb.DialogueLine),
            )
        ).line_kind == pb.DIALOGUE_LINE_KIND_NPC

        sounds_request = pb.ListCharacterSoundsRequest(
            parent=_PARENT,
            page_size=5,
            filter="slot_id = 9",
            order_by="character asc",
        )
        sounds = await service.list_character_sounds(
            sounds_request,
            _context(sounds_request, pb.ListCharacterSoundsResponse),
        )
        assert sounds.total_size == 12
        assert all(sound.slot_id == 9 for sound in sounds.character_sounds)
        sound_request = pb.GetCharacterSoundRequest(name=sounds.character_sounds[0].name)
        assert (
            await service.get_character_sound(
                sound_request,
                _context(sound_request, pb.CharacterSound),
            )
        ).character_display_name

        transitions_request = pb.ListDialogueTransitionsRequest(
            parent=_PARENT,
            page_size=4,
            filter="terminates_dialog = true",
            order_by="location asc",
        )
        transitions = await service.list_dialogue_transitions(
            transitions_request,
            _context(transitions_request, pb.ListDialogueTransitionsResponse),
        )
        assert transitions.total_size == 2
        assert all(item.terminates_dialogue for item in transitions.dialogue_transitions)
        transition_request = pb.GetDialogueTransitionRequest(
            name=transitions.dialogue_transitions[0].name
        )
        assert (
            await service.get_dialogue_transition(
                transition_request,
                _context(transition_request, pb.DialogueTransition),
            )
        ).terminates_dialogue

        linked_request = pb.ListDialogueTransitionsRequest(
            parent=_PARENT,
            page_size=4,
            filter="terminates_dialog = false",
            order_by="location asc",
        )
        linked = await service.list_dialogue_transitions(
            linked_request,
            _context(linked_request, pb.ListDialogueTransitionsResponse),
        )
        assert linked.dialogue_transitions[0].next_dialogue.startswith(f"{_PARENT}/dialogues/")

    asyncio.run(_run_service(service_database, verify))


def test_portrait_metadata_and_run_resources(service_database: Path) -> None:
    async def verify(service: PipelineService) -> None:
        portraits_request = pb.ListPortraitsRequest(
            parent=_PARENT,
            page_size=10,
            filter='search("AERIES")',
            order_by="height desc",
        )
        portraits = await service.list_portraits(
            portraits_request,
            _context(portraits_request, pb.ListPortraitsResponse),
        )
        assert portraits.total_size == 1
        portrait_request = pb.GetPortraitRequest(name=portraits.portraits[0].name)
        assert (
            await service.get_portrait(
                portrait_request,
                _context(portrait_request, pb.Portrait),
            )
        ).media_type == "image/png"
        download_request = pb.DownloadPortraitRequest(name=portraits.portraits[0].name)
        content = await service.download_portrait(
            download_request,
            _context(download_request, pb.PortraitContent),
        )
        assert content.png.startswith(b"\x89PNG")

        races_request = pb.ListRacesRequest(
            parent=_PARENT,
            page_size=10,
            filter='campaign = "SOA"',
            order_by="race_id asc",
            view=pb.VIEW_FULL,
        )
        races = await service.list_races(
            races_request,
            _context(races_request, pb.ListRacesResponse),
        )
        assert races.races and races.races[0].texts
        race_request = pb.GetRaceRequest(name=races.races[0].name)
        assert (
            await service.get_race(
                race_request,
                _context(race_request, pb.Race),
            )
        ).display_name

        classes_request = pb.ListCharacterClassesRequest(
            parent=_PARENT,
            page_size=10,
            filter="class_id = 14",
            order_by="display_name asc",
            view=pb.VIEW_FULL,
        )
        classes = await service.list_character_classes(
            classes_request,
            _context(classes_request, pb.ListCharacterClassesResponse),
        )
        assert [item.class_id for item in classes.character_classes] == [14]
        class_request = pb.GetCharacterClassRequest(name=classes.character_classes[0].name)
        assert (
            await service.get_character_class(
                class_request,
                _context(class_request, pb.CharacterClass),
            )
        ).texts

        kits_request = pb.ListKitsRequest(
            parent=_PARENT,
            page_size=10,
            filter="class_id = 2",
            order_by="row_id asc",
        )
        kits = await service.list_kits(
            kits_request,
            _context(kits_request, pb.ListKitsResponse),
        )
        assert kits.total_size == 1
        kit_request = pb.GetKitRequest(name=kits.kits[0].name)
        assert (
            await service.get_kit(
                kit_request,
                _context(kit_request, pb.Kit),
            )
        ).display_name

        identifiers_request = pb.ListIdentifierDefinitionsRequest(
            parent=_PARENT,
            page_size=10,
            filter='kind = "gender"',
            order_by="display_name asc",
        )
        identifiers = await service.list_identifier_definitions(
            identifiers_request,
            _context(identifiers_request, pb.ListIdentifierDefinitionsResponse),
        )
        assert identifiers.identifier_definitions[0].kind == pb.IDENTIFIER_KIND_GENDER
        identifier_request = pb.GetIdentifierDefinitionRequest(
            name=identifiers.identifier_definitions[0].name
        )
        assert (
            await service.get_identifier_definition(
                identifier_request,
                _context(identifier_request, pb.IdentifierDefinition),
            )
        ).symbols

        campaigns_request = pb.ListCampaignsRequest(
            parent=_PARENT,
            page_size=10,
            order_by="ordinal asc",
        )
        campaigns = await service.list_campaigns(
            campaigns_request,
            _context(campaigns_request, pb.ListCampaignsResponse),
        )
        assert campaigns.total_size == 2
        campaign_request = pb.GetCampaignRequest(name=campaigns.campaigns[0].name)
        assert (
            await service.get_campaign(
                campaign_request,
                _context(campaign_request, pb.Campaign),
            )
        ).campaign_id == "SOA"

        runs_request = pb.ListExtractionRunsRequest(
            parent=_PARENT,
            page_size=10,
            order_by="started_at desc",
        )
        runs = await service.list_extraction_runs(
            runs_request,
            _context(runs_request, pb.ListExtractionRunsResponse),
        )
        assert runs.total_size == 5
        assert runs.extraction_runs[0].started_at.ToJsonString().endswith("Z")
        run_request = pb.GetExtractionRunRequest(name=runs.extraction_runs[0].name)
        assert (
            await service.get_extraction_run(
                run_request,
                _context(run_request, pb.ExtractionRun),
            )
        ).run_id

    asyncio.run(_run_service(service_database, verify))


def test_invalid_requests_are_typed_connect_errors(service_database: Path) -> None:
    async def verify(service: PipelineService) -> None:
        invalid_parent = pb.ListVoicesRequest(parent="installations/other")
        with pytest.raises(ConnectError) as parent_error:
            await service.list_voices(
                invalid_parent,
                _context(invalid_parent, pb.ListVoicesResponse),
            )
        assert parent_error.value.code is Code.INVALID_ARGUMENT

        invalid_filter = pb.ListCharactersRequest(
            parent=_PARENT,
            filter='source_kind = "archive"',
        )
        with pytest.raises(ConnectError) as filter_error:
            await service.list_characters(
                invalid_filter,
                _context(invalid_filter, pb.ListCharactersResponse),
            )
        assert filter_error.value.code is Code.INVALID_ARGUMENT

        invalid_order = pb.ListDialoguesRequest(
            parent=_PARENT,
            order_by="unknown desc",
        )
        with pytest.raises(ConnectError) as order_error:
            await service.list_dialogues(
                invalid_order,
                _context(invalid_order, pb.ListDialoguesResponse),
            )
        assert order_error.value.code is Code.INVALID_ARGUMENT

        missing = pb.GetVoiceRequest(name=f"{_PARENT}/voices/missing")
        with pytest.raises(ConnectError) as missing_error:
            await service.get_voice(missing, _context(missing, pb.Voice))
        assert missing_error.value.code is Code.NOT_FOUND

        first_request = pb.ListCharactersRequest(parent=_PARENT, page_size=10)
        first = await service.list_characters(
            first_request,
            _context(first_request, pb.ListCharactersResponse),
        )
        changed_request = pb.ListCharactersRequest(
            parent=_PARENT,
            page_size=25,
            page_token=first.next_page_token,
        )
        with pytest.raises(ConnectError) as token_error:
            await service.list_characters(
                changed_request,
                _context(changed_request, pb.ListCharactersResponse),
            )
        assert token_error.value.code is Code.INVALID_ARGUMENT

    asyncio.run(_run_service(service_database, verify))
