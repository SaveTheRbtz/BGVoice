"""Typed model factories and boundary fakes shared by tests."""

import threading
import time
from pathlib import Path
from typing import Literal

from bgvoice.character_models import (
    CreDump,
)
from bgvoice.dialogue_models import (
    DlgDump,
)
from bgvoice.model_types import (
    CreResource,
    DialogueLineKind,
    DlgResource,
    GenerationFailureStage,
    ItmResource,
    PortraitResource,
    ProviderGender,
    RaceId,
    RunStatus,
    StringReference,
    VoiceProfileKind,
)
from bgvoice.readable_models import ItmDump
from bgvoice.storage_records import (
    CharacterDirection,
    DialogueLineRecord,
    DirectedLineRecord,
    GeneratedAudioRecord,
    GenerationFailureRecord,
    NarratorDirection,
    TtsBatchRecord,
    VoiceDescription,
    VoiceGenerationRecord,
    VoiceProfileRecord,
)

_VOICE_CREATED_AT = "2026-08-27T10:00:00+00:00"
_DIRECTION_CREATED_AT = "2026-08-27T10:01:00+00:00"
_AUDIO_CREATED_AT = "2026-08-27T10:02:00+00:00"
_FAILURE_CREATED_AT = "2026-08-27T10:03:00+00:00"


def _resource_data(
    name: str,
    resource_type: Literal["BMP", "CRE", "DLG", "ITM"],
) -> dict[str, object]:
    return {
        "resource_name": name,
        "resref": name.rsplit(".", maxsplit=1)[0],
        "source_kind": "override",
        "source_path": f"C:/game/override/{name}",
        "type": resource_type,
    }


def make_resource(name: str = "AERIE.CRE") -> CreResource:
    """Create a representative CRE inventory entry."""
    return CreResource.model_validate(_resource_data(name, "CRE"))


def make_dialogue_line(
    dialogue: str = "AERIE.DLG",
    state: int = 0,
    text: str | None = None,
) -> DialogueLineRecord:
    """Create one extracted NPC line."""
    value = f"Line {state}" if text is None else text
    return DialogueLineRecord(
        id=f"{dialogue}:npc:{state}:-",
        run_id="run",
        dialogue_resource_name=dialogue,
        line_kind=DialogueLineKind.NPC,
        state_index=state,
        strref=state,
        text=value,
        tokens=[],
        serialized_size=10,
        search_text=value,
    )


def make_dialogue_resource(name: str = "AERIE.DLG") -> DlgResource:
    """Create a representative DLG inventory entry."""
    return DlgResource.model_validate(_resource_data(name, "DLG"))


def make_portrait_resource(name: str = "AERIES.BMP") -> PortraitResource:
    """Create a representative BMP inventory entry."""
    return PortraitResource.model_validate(_resource_data(name, "BMP"))


def make_item_resource(name: str = "BOOK.ITM") -> ItmResource:
    """Create a representative ITM inventory entry."""
    return ItmResource.model_validate(_resource_data(name, "ITM"))


def make_item_dump(
    name: str = "BOOK.ITM",
    *,
    category: int = 0,
    ground_icon: str | None = "GBOOK01",
    general_name: str | None = "Book",
    identified_name: str | None = "A Fine Book",
    general_description: str | None = "General text",
    identified_description: str | None = "Identified text",
) -> ItmDump:
    """Create the text projection of an ie-cli ITM dump."""
    return ItmDump.model_validate(
        {
            "resource_name": name,
            "resource_type": "ITM",
            "version": "V1  ",
            "header": {
                "category": {"raw": category, "decoded": None},
                "ground_icon": ground_icon,
                "icon": "IBOOK01",
                "description_image": "CBOOK01",
                "general_name": {"strref": 10, "text": general_name},
                "identified_name": {"strref": 11, "text": identified_name},
                "general_description": {
                    "strref": 12,
                    "text": general_description,
                },
                "identified_description": {
                    "strref": 13,
                    "text": identified_description,
                },
            },
        }
    )


def make_voice_profile(
    profile_id: str = "aerie",
    *,
    inworld_voice_id: str | None = None,
    description: str | None = None,
    gender: ProviderGender | None = None,
    race_id: RaceId | None = None,
    kind: VoiceProfileKind = VoiceProfileKind.DEDICATED,
) -> VoiceProfileRecord:
    return VoiceProfileRecord(
        profile_id=profile_id,
        kind=kind,
        gender=gender,
        race_id=race_id,
        inworld_voice_id=inworld_voice_id or f"voice-{profile_id}",
        description=VoiceDescription(
            text=description or f"A clear, expressive voice for {profile_id.title()}.",
            language_code="en-GB",
        ),
        created_at=_VOICE_CREATED_AT,
    )


def make_voice_generation(
    voice_id: str = "aerie",
    profile_id: str | None = None,
) -> VoiceGenerationRecord:
    return VoiceGenerationRecord(
        voice_id=voice_id,
        profile_id=profile_id or voice_id,
    )


def make_direction(
    voice_id: str = "aerie",
    line_id: str = "AERIE.DLG:npc:0:-",
    *,
    directed_dialogue: str = "[clearly] Ready.",
    narrator: bool = False,
) -> DirectedLineRecord:
    return DirectedLineRecord(
        id=DirectedLineRecord.id_for(voice_id, line_id),
        voice_id=voice_id,
        dialogue_line_id=line_id,
        character=(None if narrator else CharacterDirection(directed_dialogue=directed_dialogue)),
        narrator=NarratorDirection(directed_dialogue=directed_dialogue) if narrator else None,
        created_at=_DIRECTION_CREATED_AT,
    )


def make_generated_audio(
    direction: DirectedLineRecord,
    *,
    inworld_voice_id: str | None = None,
    operation_name: str = "operations/test-batch",
    audio: bytes = b"OggSgenerated audio",
) -> GeneratedAudioRecord:
    return GeneratedAudioRecord(
        id=direction.id,
        voice_id=direction.voice_id,
        dialogue_line_id=direction.dialogue_line_id,
        inworld_voice_id=inworld_voice_id or f"voice-{direction.voice_id}",
        batch_operation_name=operation_name,
        audio=audio,
        created_at=_AUDIO_CREATED_AT,
    )


def make_generation_failure(
    stage: GenerationFailureStage,
    voice_id: str = "aerie",
    line_id: str | None = None,
    *,
    error: str = "generation failed",
    error_type: str = "RuntimeError",
    error_code: str | None = None,
) -> GenerationFailureRecord:
    dialogue_line_id = (
        None if stage is GenerationFailureStage.VOICE_CREATION else line_id or "AERIE.DLG:npc:0:-"
    )
    return GenerationFailureRecord(
        id=GenerationFailureRecord.id_for(stage, voice_id, dialogue_line_id),
        stage=stage,
        voice_id=voice_id,
        dialogue_line_id=dialogue_line_id,
        error_type=error_type,
        error_code=error_code,
        error=error,
        failed_at=_FAILURE_CREATED_AT,
    )


def make_tts_batch(
    custom_ids: list[str],
    *,
    operation_name: str = "operations/test-batch",
    status: RunStatus = RunStatus.RUNNING,
    error: str | None = None,
) -> TtsBatchRecord:
    return TtsBatchRecord(
        operation_name=operation_name,
        custom_ids=custom_ids,
        status=status,
        started_at=_VOICE_CREATED_AT,
        completed_at=_FAILURE_CREATED_AT if status is not RunStatus.RUNNING else None,
        error=error,
    )


def make_dump(
    name: str = "AERIE.CRE",
    *,
    short_name: str | None = "^0xFF8B7D6DAerie^-",
    long_name: str | None = "Aerie",
    death_variable: str = "Aerie",
    dialog: str | None = "AERIE",
) -> CreDump:
    """Create the voice-relevant projection of an ie-cli CRE dump."""
    return CreDump.model_validate(
        {
            "resource_name": name,
            "resource_type": "CRE",
            "version": "V1.0",
            "header": {
                "short_name": {"strref": 100, "text": short_name},
                "long_name": {"strref": 101, "text": long_name},
                "death_variable": f" {death_variable} ",
                "dialog": dialog,
                "soundset": [
                    (
                        {"strref": 2001, "text": "For the fallen!"}
                        if slot_id == 9
                        else {"strref": 2044, "text": "What is it, <CHARNAME>?"}
                        if slot_id == 44
                        else {"strref": 0xFFFF_FFFF, "text": None}
                    )
                    for slot_id in range(100)
                ],
                "classification": {
                    "alignment": 17,
                    "class": 14,
                    "enemy_ally": 128,
                    "gender": 2,
                    "general": 1,
                    "race": 2,
                    "specific": 0,
                },
                "scripts": {
                    "class_script": "SHOUTINV",
                    "default_script": "AERIEX",
                    "general_script": "NONE",
                    "override_script": "AERIE",
                    "race_script": None,
                },
                "animation_id": 0x6202,
                "class_levels": {
                    "first_class": 7,
                    "second_class": 7,
                    "third_class": 0,
                },
                "racial_enemy": 255,
                "kit": {
                    "decoded": None,
                    "raw_big_endian": 64,
                    "raw_bytes": [0, 0, 0, 64],
                },
                "small_portrait": "AERIES",
                "large_portrait": "NONE",
                "base_attributes": {
                    "strength": 10,
                    "strength_bonus": 0,
                    "intelligence": 16,
                    "wisdom": 16,
                    "dexterity": 17,
                    "constitution": 9,
                    "charisma": 14,
                },
                "morale": 10,
                "morale_break": 5,
                "morale_recovery_time": 60,
                "reputation": 0,
            },
        }
    )


def make_dialogue_dump(name: str = "AERIE.DLG") -> DlgDump:
    """Create a small DLG with NPC, player, and journal text."""
    return DlgDump.model_validate(
        {
            "resource_name": name,
            "resource_type": "DLG",
            "version": "V1.0",
            "header": {"num_states": 2, "num_transitions": 3},
            "states": [
                {
                    "first_transition_index": 0,
                    "index": 0,
                    "num_transitions": 2,
                    "response_text": {"strref": 1, "text": "Hello."},
                    "trigger_index": 0,
                    "trigger_text": 'Global("MetAerie","GLOBAL",0)',
                    "transitions": [
                        {
                            "action_index": None,
                            "action_text": None,
                            "flags": {"decoded": ["HasText"], "raw": 1},
                            "index": 0,
                            "player_text": {"strref": 2, "text": "Hi."},
                            "journal_text": None,
                            "next_dialog": "AERIE",
                            "next_state_index": 1,
                            "terminates_dialog": False,
                            "trigger_index": None,
                            "trigger_text": None,
                        },
                        {
                            "action_index": None,
                            "action_text": None,
                            "flags": {"decoded": ["TerminatesDialog"], "raw": 8},
                            "index": 1,
                            "player_text": None,
                            "journal_text": None,
                            "next_dialog": None,
                            "next_state_index": None,
                            "terminates_dialog": True,
                            "trigger_index": None,
                            "trigger_text": None,
                        },
                    ],
                },
                {
                    "first_transition_index": 2,
                    "index": 1,
                    "num_transitions": 1,
                    "response_text": {"strref": 3, "text": "A quest for <DAYANDMONTH>."},
                    "trigger_index": None,
                    "trigger_text": None,
                    "transitions": [
                        {
                            "action_index": 4,
                            "action_text": 'SetGlobal("Quest","GLOBAL",1)',
                            "flags": {
                                "decoded": ["HasText", "HasTrigger", "HasAction"],
                                "raw": 7,
                            },
                            "index": 2,
                            "player_text": {
                                "strref": 4,
                                "text": "Accepted, <CHARNAME>.",
                            },
                            "journal_text": {"strref": 5, "text": "Quest accepted."},
                            "next_dialog": "MINSC",
                            "next_state_index": 7,
                            "terminates_dialog": False,
                            "trigger_index": 3,
                            "trigger_text": 'Global("Quest","GLOBAL",0)',
                        }
                    ],
                },
            ],
        }
    )


class MetadataClient:
    """Thread-safe effective-resource client with observable TLK concurrency."""

    def __init__(self, resources: dict[str, str]) -> None:
        self.resources = resources
        self.read_calls: list[tuple[Path, str]] = []
        self.resolve_calls: list[tuple[Path, int]] = []
        self.resolve_threads: set[str] = set()
        self._active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def version(self) -> str:
        return "iecli test"

    def read_text_resource(self, game_root: Path, resource_name: str) -> str:
        self.read_calls.append((game_root, resource_name))
        return self.resources[resource_name]

    def resolve_string(self, game_root: Path, strref: int) -> StringReference:
        with self._lock:
            self.resolve_calls.append((game_root, strref))
            self.resolve_threads.add(threading.current_thread().name)
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        time.sleep(0.003)
        with self._lock:
            self._active -= 1
        return StringReference(strref=strref, text=f"text {strref}")


def metadata_resources() -> dict[str, str]:
    """Return representative effective IDS and 2DA resources."""
    identifiers = {
        "RACE.IDS": "IDS V1.0\n1 HUMAN\n",
        "CLASS.IDS": "IDS V1.0\n1 MAGE\n1 MAGE_ALL\n",
        "GENDER.IDS": "IDS V1.0\n2 FEMALE\n",
        "ALIGNMEN.IDS": "IDS V1.0\n17 LAWFUL_GOOD\n",
        "EA.IDS": "IDS V1.0\n128 ALLY\n",
        "GENERAL.IDS": "IDS V1.0\n1 HUMANOID\n",
        "SPECIFIC.IDS": "IDS V1.0\n0 NONE\n",
        "ANIMATE.IDS": "IDS V1.0\n0x6202 ELF_FEMALE\n",
        "KIT.IDS": "IDS V1.0\n0x4000 TRUECLASS\n",
        "SNDSLOT.IDS": "IDS V1.0\n9 BATTLE_CRY\n",
    }
    tables = {
        "CAMPAIGN.2DA": (
            "2DA V1.0\n*\nRACETEXT INTERACT CLASTEXT YEARS PDIALOG INTERDIA\n"
            "SOA RACETEXT INTERACT CLASTEXT YEARS PDIALOG INTERDIA\n"
        ),
        "RACETEXT.2DA": (
            "2DA V1.0\n-1\nBIOGRAPHY ID DESCSTR NAME UPPERCASE\nHUMAN -1 1 101 100 102\n"
        ),
        "CLASTEXT.2DA": (
            "2DA V1.0\n-1\n"
            "MIXED CLASSID KITID LOWER DESCSTR BIOGRAPHY FALLEN BRIEFDESC FALLEN_NOTICE\n"
            "FIGHTER 112 2 16384 110 111 -1 0 113 -1\n"
        ),
        "KITLIST.2DA": (
            "2DA V1.0\n*\n"
            "HELP ROWNAME KITIDS LOWER MIXED ABILITIES PROFICIENCY UNUSABLE CLASS\n"
            "1 122 BERSERKER 0x4001 110 121 CLABFI02 29 1 2\n"
        ),
        "INTERDIA.2DA": "2DA V1.0\nNONE\nFILE 25FILE\nAERIE BAERIE NONE\n",
        "PDIALOG.2DA": (
            "2DA V1.0\nNONE\nPOST_DIALOG_FILE JOIN_DIALOG_FILE DREAM_SCRIPT_FILE\n"
            "AERIE AERIE AERIEJ DRAERIE\n"
        ),
        "INTERACT.2DA": "2DA V1.0\n0\nAERIE MINSC\nAERIE 0 i\nMINSC c 0\n",
        "CHARSND.2DA": "2DA V1.0\n-1\nFEMALE\n9 200\n",
        "CSOUND.2DA": "2DA V1.0\n*\nLETTER\n9 a\n",
        "ENGINEST.2DA": "2DA V1.0\n0\nStrRef\nDAYMONTH 202\n",
        "MONTHS.2DA": "2DA V1.0\n0\nNAME DAYS\n0 204 30\n",
        "YEARS.2DA": (
            "2DA V1.0\n0\nVALUE\nSTARTYEAR 1369\nSTARTTIME 878400\n"
            "SPECIALDAYMONTHFORMAT 207\nNORMALDAYMONTHFORMAT 206\n"
        ),
        "SPEECH.2DA": "2DA V1.0\n0\nNUM OFFSET\nBATTLE_CRY 5 9\nSELECT * *\n",
        "HATERACE.2DA": "2DA V1.0\n0\nIDS STRREF_HELP STRREF\nBEHOLDER 123 209 208\n",
        "HAPPY.2DA": "2DA V1.0\n0\nEVIL GOOD NEUTRAL\n1 80 -300 -300\n",
        "BANTTIMG.2DA": (
            "2DA V1.0\n0\nVALUE\nSPECIALPROBABILITY 40\nREPLAYDELAY 150\n"
            "FREQUENCY 480\nPROBABILITY 10\n"
        ),
    }
    return identifiers | tables
