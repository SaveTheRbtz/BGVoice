"""Typed model factories for tests."""

from typing import Literal

from bgvoice.models import CreDump, CreResource, DlgDump, DlgResource, PortraitResource


def _resource_data(name: str, resource_type: Literal["BMP", "CRE", "DLG"]) -> dict[str, object]:
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


def make_dialogue_resource(name: str = "AERIE.DLG") -> DlgResource:
    """Create a representative DLG inventory entry."""
    return DlgResource.model_validate(_resource_data(name, "DLG"))


def make_portrait_resource(name: str = "AERIES.BMP") -> PortraitResource:
    """Create a representative BMP inventory entry."""
    return PortraitResource.model_validate(_resource_data(name, "BMP"))


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
