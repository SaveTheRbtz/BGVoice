"""Typed model factories for tests."""

from typing import Literal

from bgvoice.models import CreDump, CreResource, DlgDump, DlgResource


def _resource_data(name: str, resource_type: Literal["CRE", "DLG"]) -> dict[str, object]:
    return {
        "resource_name": name,
        "resref": name.removesuffix(f".{resource_type}"),
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


def make_dump(
    name: str = "AERIE.CRE",
    *,
    short_name: str | None = "^0xFF8B7D6DAerie^-",
    long_name: str | None = "Aerie",
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
                "death_variable": " Aerie ",
                "dialog": dialog,
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
                "small_portrait": "AERIES",
                "large_portrait": "NONE",
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
                    "index": 0,
                    "response_text": {"strref": 1, "text": "Hello."},
                    "transitions": [
                        {
                            "index": 0,
                            "player_text": {"strref": 2, "text": "Hi."},
                            "journal_text": None,
                        },
                        {"index": 1, "player_text": None, "journal_text": None},
                    ],
                },
                {
                    "index": 1,
                    "response_text": {"strref": 3, "text": "A quest."},
                    "transitions": [
                        {
                            "index": 2,
                            "player_text": {"strref": 4, "text": "Accepted."},
                            "journal_text": {"strref": 5, "text": "Quest accepted."},
                        }
                    ],
                },
            ],
        }
    )
