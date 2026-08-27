"""Effective IDS, 2DA, and TLK metadata extraction behavior."""

import threading
import time
from pathlib import Path

import pytest

from bgvoice.metadata import build_metadata, parse_2da, parse_ids
from bgvoice.model_types import (
    CampaignResourceKind,
    CharacterResourceRole,
    HappinessAlignment,
    IdentifierKind,
    InteractionKind,
    ResourceTargetType,
    StringReference,
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


def test_ids_parser_handles_real_headers_hex_aliases_and_duplicate_rows() -> None:
    definitions = parse_ids(
        """
        IDS V1.0
        ignored header text
        0x4000 TRUECLASS
        16384 MAGESCHOOL_GENERALIST // alias
        0x4007 FERALAN
        0x4007 FERALAN
        """,
        kind=IdentifierKind.KIT,
        source_resource="KIT.IDS",
    )

    assert [(row.value, row.symbols) for row in definitions] == [
        (0x4000, ["TRUECLASS", "MAGESCHOOL_GENERALIST"]),
        (0x4007, ["FERALAN", "FERALAN"]),
    ]
    assert [row.ordinal for row in definitions] == [0, 2]


def test_2da_parser_is_positional_and_preserves_quoted_and_duplicate_columns() -> None:
    table = parse_2da(
        '2DA V1.0\nNONE\nNAME NAME EXTRA\n// ignored\nROW "two words" VALUE\n',
        source_resource="DUPLICAT.2DA",
    )

    assert table.default_value == "NONE"
    assert table.columns == ("NAME", "NAME", "EXTRA")
    assert (table.rows[0].row_name, table.rows[0].values) == (
        "ROW",
        ("two words", "VALUE", "NONE"),
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("2DA V1.0\n*\n", "missing its 2DA header"),
        ("2DA V2.0\n*\nA\n", "does not begin"),
        ("2DA V1.0\n* extra\nA\n", "default value"),
        ("2DA V1.0\n*\nA B\nROW one two three\n", "expected at most 2"),
        ('2DA V1.0\n*\nA\n"" VALUE\n', "missing its row label"),
    ],
)
def test_2da_parser_rejects_structural_corruption(text: str, message: str) -> None:
    with pytest.raises(AssertionError, match=message):
        parse_2da(text, source_resource="BROKEN.2DA")


def test_metadata_build_follows_campaign_resources_and_resolves_each_strref_once(
    tmp_path: Path,
) -> None:
    client = MetadataClient(_resources())
    extraction = build_metadata(client, tmp_path / "game" / ".." / "game", workers=3)

    assert extraction.source_resource_count == len(client.resources)
    assert extraction.resolved_strref_count == len(client.resolve_calls)
    assert len({strref for _root, strref in client.resolve_calls}) == len(client.resolve_calls)
    assert client.max_active > 1
    assert len(client.resolve_threads) > 1
    assert all(root == (tmp_path / "game").resolve() for root, _ in client.read_calls)

    alias = next(row for row in extraction.identifiers if row.kind == "class")
    assert alias.symbols == ["MAGE", "MAGE_ALL"]
    assert [row.campaign_id for row in extraction.campaigns] == ["SOA"]
    assert [row.resource_kind for row in extraction.campaign_resource_bindings] == [
        CampaignResourceKind.BANTER_DIALOGUES,
        CampaignResourceKind.PARTY_DIALOGUES,
        CampaignResourceKind.INTERACTIONS,
        CampaignResourceKind.CALENDAR,
        CampaignResourceKind.CLASS_TEXT,
        CampaignResourceKind.RACE_TEXT,
    ]
    assert [
        (link.role, link.target_type, link.target_resref)
        for link in extraction.character_resource_links
    ] == [
        (CharacterResourceRole.BANTER_DIALOGUE, ResourceTargetType.DIALOGUE, "BAERIE"),
        (CharacterResourceRole.POST_DIALOGUE, ResourceTargetType.DIALOGUE, "AERIE"),
        (CharacterResourceRole.JOIN_DIALOGUE, ResourceTargetType.DIALOGUE, "AERIEJ"),
        (CharacterResourceRole.DREAM_SCRIPT, ResourceTargetType.SCRIPT, "DRAERIE"),
    ]
    assert [(rule.kind, rule.target_death_variable) for rule in extraction.interaction_rules] == [
        (InteractionKind.INSULT, "MINSC"),
        (InteractionKind.COMPLIMENT, "AERIE"),
    ]
    assert [(line.slot_id, line.text) for line in extraction.soundset_lines] == [(9, "text 200")]
    assert [
        (group.row_name, group.offset, group.count) for group in extraction.sound_slot_groups
    ] == [
        ("BATTLE_CRY", 9, 5),
        ("SELECT", None, None),
    ]
    assert extraction.happiness_rules[0].alignment is HappinessAlignment.GOOD
    assert extraction.banter_timing.frequency == 480

    race = extraction.race_text_rows[0]
    character_class = extraction.class_text_rows[0]
    kit = extraction.kits[0]
    assert (race.race_id, race.name, race.biography) == (1, "text 100", None)
    assert (
        character_class.class_id,
        character_class.class_text_kit_id,
        character_class.description,
        character_class.fallen,
    ) == (2, 0x4000, "text 111", False)
    assert (kit.row_name, kit.kit_ids_value, kit.class_text_kit_id, kit.lower_name) == (
        "BERSERKER",
        0x4001,
        1,
        "text 110",
    )
    assert (extraction.favored_enemies[0].name, extraction.months[0].name) == (
        "text 208",
        "text 204",
    )
    assert extraction.campaign_calendars[0].start_year == 1369


@pytest.mark.parametrize(
    ("resource", "old", "new", "message"),
    [
        ("RACETEXT.2DA", "DESCSTR", "WRONG", "missing required column"),
        ("CLASTEXT.2DA", "-1 0 113", "-1 2 113", "CLASTEXT.FALLEN"),
        ("INTERACT.2DA", "AERIE 0 i", "AERIE 0 x", "invalid interaction"),
    ],
)
def test_metadata_build_rejects_corrupt_engine_cells(
    resource: str,
    old: str,
    new: str,
    message: str,
    tmp_path: Path,
) -> None:
    resources = _resources()
    resources[resource] = resources[resource].replace(old, new)
    with pytest.raises(AssertionError, match=message):
        build_metadata(MetadataClient(resources), tmp_path)


def _resources() -> dict[str, str]:
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
