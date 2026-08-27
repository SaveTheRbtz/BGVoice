"""Tests for effective IDS/2DA/TLK metadata extraction."""

import threading
import time
from pathlib import Path

import pytest

from bgvoice.metadata import (
    _parse_uint,
    _resolve_strings,
    build_metadata,
    parse_2da,
    parse_ids,
)
from bgvoice.models import (
    CampaignResourceKind,
    CharacterResourceRole,
    HappinessAlignment,
    IdentifierKind,
    InteractionKind,
    ResourceTargetType,
    StringReference,
)

_CAMPAIGN_COLUMNS = (
    "WORLDSCRIPT",
    "DESCRIPTION",
    "ICON",
    "INTERDIA",
    "LOADHINT",
    "MASTAREA",
    "MUSIC",
    "NAME",
    "NPCLEVEL",
    "TBPPARTY",
    "PDIALOG",
    "SAVE_DIR",
    "STARTARE",
    "STRTGOLD",
    "STARTPOS",
    "STWEAPON",
    "25STWEAP",
    "XPCAP",
    "XPLIST",
    "WORLDMAP",
    "WORLDSCRIPT",
    "MAP_DROPSHADOW",
    "MAP_FONTCOLOR",
    "KEEP_POWERS",
    "INTRO_MOVIE",
    "IMPORT",
    "INTERACT",
    "YEARS",
    "REPUTATION",
    "CLASTEXT",
    "RACETEXT",
)


class FakeMetadataClient:
    """Thread-safe in-memory implementation of the metadata client protocol."""

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
        time.sleep(0.005)
        with self._lock:
            self._active -= 1
        return StringReference(strref=strref, text=f"text {strref}")


def test_ids_parser_accepts_real_headers_hex_aliases_and_duplicates() -> None:
    definitions = parse_ids(
        """
        IDS V1.0
        15
        0x4000 TRUECLASS
        ignored header text
        16384 MAGESCHOOL_GENERALIST // alias
        0x4007 FERALAN
        0x4007 FERALAN
        """,
        kind=IdentifierKind.KIT,
        source_resource="KIT.IDS",
    )

    assert [definition.value for definition in definitions] == [0x4000, 0x4007]
    assert definitions[0].ordinal == 0
    assert definitions[0].symbols == ["TRUECLASS", "MAGESCHOOL_GENERALIST"]
    assert definitions[1].symbols == ["FERALAN", "FERALAN"]
    assert definitions[1].kind is IdentifierKind.KIT
    assert parse_ids("IDS\n", kind=IdentifierKind.RACE, source_resource="RACE.IDS") == []


def test_2da_parser_is_positional_and_preserves_duplicate_columns() -> None:
    table = parse_2da(
        '2DA V1.0\n*\nNAME NAME\n// ignored\nROW "two words" VALUE\n',
        source_resource="DUPLICAT.2DA",
    )

    assert table.default_value == "*"
    assert table.columns == ("NAME", "NAME")
    assert table.rows[0].ordinal == 0
    assert table.rows[0].row_name == "ROW"
    assert table.rows[0].values == ("two words", "VALUE")

    padded = parse_2da(
        "2DA V1.0\nNONE\nFILE 25FILE\nAERIE BAERIE\n",
        source_resource="INTERDIA.2DA",
    )
    assert padded.rows[0].values == ("BAERIE", "NONE")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("2DA V1.0\n*\n", "missing its 2DA header"),
        ("2DA V2.0\n*\nA\n", "does not begin"),
        ("2DA V1.0\n* extra\nA\n", "default value"),
        ("2DA V1.0\n*\nA B\nROW one two three\n", "has 3 cells; expected at most 2"),
        ('2DA V1.0\n*\nA\n"" VALUE\n', "missing its row label"),
    ],
)
def test_2da_parser_rejects_structural_corruption(text: str, message: str) -> None:
    with pytest.raises(AssertionError, match=message):
        parse_2da(text, source_resource="BROKEN.2DA")


def test_build_metadata_follows_campaign_bindings_and_resolves_unique_strrefs(
    tmp_path: Path,
) -> None:
    resources = _metadata_resources()
    client = FakeMetadataClient(resources)

    extraction = build_metadata(client, tmp_path / "game" / ".." / "game", workers=3)

    assert extraction.source_resource_count == 28
    assert extraction.resolved_strref_count == 21
    assert len(extraction.identifiers) == 13
    class_alias = next(
        definition
        for definition in extraction.identifiers
        if definition.kind is IdentifierKind.CLASS and definition.value == 202
    )
    assert class_alias.symbols == ["LONG_BOW", "MAGE_ALL"]

    assert [campaign.campaign_id for campaign in extraction.campaigns] == ["SOA", "TOB", "BP1"]
    assert len(extraction.campaign_resource_bindings) == 18
    assert [
        binding.resource_resref
        for binding in extraction.campaign_resource_bindings
        if binding.campaign_id == "BP1"
    ] == [None] * 6
    assert [
        binding.resource_kind
        for binding in extraction.campaign_resource_bindings
        if binding.campaign_id == "SOA"
    ] == [
        CampaignResourceKind.BANTER_DIALOGUES,
        CampaignResourceKind.PARTY_DIALOGUES,
        CampaignResourceKind.INTERACTIONS,
        CampaignResourceKind.CALENDAR,
        CampaignResourceKind.CLASS_TEXT,
        CampaignResourceKind.RACE_TEXT,
    ]

    assert len(extraction.character_resource_links) == 22
    padded_link = next(
        link
        for link in extraction.character_resource_links
        if link.death_variable == "LATE" and link.source_column == "25POST_DIALOG_FILE"
    )
    assert (
        padded_link.target_resref,
        padded_link.role,
        padded_link.target_type,
    ) == (
        "multig",
        CharacterResourceRole.POST_DIALOGUE,
        ResourceTargetType.DIALOGUE,
    )
    dangling_link = next(
        link for link in extraction.character_resource_links if link.target_resref == "LOSTDLG"
    )
    assert dangling_link.source_column == "POST_DIALOG_FILE"
    assert [rule.kind for rule in extraction.interaction_rules] == [
        InteractionKind.INSULT,
        InteractionKind.COMPLIMENT,
        InteractionKind.SPECIAL,
    ]
    assert extraction.interaction_rules[0].target_death_variable == "OTHER"

    assert [
        (line.soundset_name, line.slot_id, line.strref, line.text)
        for line in extraction.soundset_lines
    ] == [
        ("MALE", 1, 200, "text 200"),
        ("FEMALE", 55, 201, "text 201"),
    ]
    assert [suffix.file_suffix for suffix in extraction.sound_slot_suffixes] == [None, "a", "!x"]
    assert [
        (group.row_name, group.offset, group.count) for group in extraction.sound_slot_groups
    ] == [
        ("*", None, None),
        ("INITIAL_MEETING", 0, 1),
        ("SELECT", None, None),
        ("BATTLE_CRY", 9, 5),
    ]
    assert [
        (enemy.row_name, enemy.race_id, enemy.name, enemy.help_text)
        for enemy in extraction.favored_enemies
    ] == [
        ("BEHOLDER", 123, "text 208", "text 209"),
        ("ORC", 143, "text 210", "text 211"),
    ]
    assert len(extraction.happiness_rules) == 60
    assert extraction.happiness_rules[0].model_dump() == {
        "source_resource": "HAPPY.2DA",
        "reputation": 1,
        "alignment": HappinessAlignment.GOOD,
        "happiness": -300,
    }
    assert extraction.happiness_rules[-1].model_dump() == {
        "source_resource": "HAPPY.2DA",
        "reputation": 20,
        "alignment": HappinessAlignment.EVIL,
        "happiness": -300,
    }
    assert extraction.banter_timing.model_dump() == {
        "source_resource": "BANTTIMG.2DA",
        "frequency": 480,
        "probability": 10,
        "replay_delay": 150,
        "special_probability": 40,
    }
    assert [(row.key, row.text) for row in extraction.engine_strings] == [
        ("ENGINE_A", "text 202"),
        ("ENGINE_B", "text 203"),
        ("ENGINE_EMPTY", None),
    ]
    assert extraction.engine_strings[2].strref is None
    assert [(month.month_id, month.days, month.name) for month in extraction.months] == [
        (0, 30, "text 204"),
        (1, 1, "text 205"),
    ]
    assert len(extraction.campaign_calendars) == 1
    calendar = extraction.campaign_calendars[0]
    assert (
        calendar.source_resource,
        calendar.start_time,
        calendar.start_year,
        calendar.normal_format,
        calendar.special_format,
    ) == ("YEARS.2DA", 878400, 1369, "text 206", "text 207")

    assert len(extraction.race_text_rows) == 1
    race = extraction.race_text_rows[0]
    assert (race.row_name, race.race_id, race.name, race.biography_strref) == (
        "HUMAN",
        1,
        "text 100",
        None,
    )
    character_class = extraction.class_text_rows[0]
    assert (character_class.class_id, character_class.class_text_kit_id) == (2, 0x4000)
    assert character_class.description == "text 111"
    assert character_class.fallen is False

    assert len(extraction.kits) == 2
    reserve, berserker = extraction.kits
    assert reserve.row_id == 0
    assert reserve.kit_ids_value is None
    assert reserve.class_text_kit_id is None
    assert (berserker.row_id, berserker.kit_ids_value, berserker.class_text_kit_id) == (
        1,
        0x4001,
        1,
    )
    assert berserker.lower_name == "text 110"
    assert (berserker.abilities, berserker.proficiency, berserker.unusable) == (
        "CLABFI02",
        29,
        1,
    )

    assert sorted(strref for _root, strref in client.resolve_calls) == [
        100,
        101,
        102,
        110,
        111,
        112,
        113,
        121,
        122,
        200,
        201,
        202,
        203,
        204,
        205,
        206,
        207,
        208,
        209,
        210,
        211,
    ]
    assert client.max_active > 1
    assert len(client.resolve_threads) > 1
    assert [name for _root, name in client.read_calls].count("RACETEXT.2DA") == 1
    assert [name for _root, name in client.read_calls].count("CLASTEXT.2DA") == 1
    assert [name for _root, name in client.read_calls].count("INTERDIA.2DA") == 1
    assert [name for _root, name in client.read_calls].count("PDIALOG.2DA") == 1
    assert all(root == (tmp_path / "game").resolve() for root, _name in client.read_calls)


def test_metadata_projectors_allow_extra_columns_rows_and_changed_order(
    tmp_path: Path,
) -> None:
    resources = _metadata_resources()
    resources |= {
        "CAMPAIGN.2DA": """2DA V1.0
*
RACETEXT EXTRA INTERACT CLASTEXT YEARS PDIALOG INTERDIA
SOA RACETEXT ignored INTERACT CLASTEXT YEARS PDIALOG INTERDIA
TOB RACETEXT ignored INTERACT CLASTEXT YEARS PDIALOG INTERDIA
BP1 * ignored * * * * *
""",
        "INTERDIA.2DA": """2DA V1.0
NONE
EXTRA 25FILE FILE
NPC ignored BNPC25 BNPC
""",
        "PDIALOG.2DA": """2DA V1.0
multig
EXTRA 25OVERRIDE_SCRIPT_FILE DREAM_SCRIPT_FILE JOIN_DIALOG_FILE POST_DIALOG_FILE
NPC ignored NPC25O NPCD NPCJ NPCP
""",
        "INTERACT.2DA": """2DA V1.0
*
OTHER NPC FUTURE
NPC i 0 c
OTHER c s 0
""",
        "SPEECH.2DA": """2DA V1.0
0
EXTRA NUM OFFSET
EXTENDED ignored 2 99
SELECT ignored * *
""",
        "HATERACE.2DA": """2DA V1.0
4294967296
EXTRA IDS STRREF_HELP STRREF
ORC ignored 143 211 210
""",
        "HAPPY.2DA": """2DA V1.0
0
EVIL EXTRA GOOD NEUTRAL
20 -300 ignored 80 0
1 80 ignored -300 -300
""",
        "BANTTIMG.2DA": """2DA V1.0
0
EXTRA VALUE
SPECIALPROBABILITY ignored 40
FUTURE ignored 999
REPLAYDELAY ignored 150
FREQUENCY ignored 480
PROBABILITY ignored 10
""",
        "YEARS.2DA": """2DA V1.0
0
EXTRA VALUE
SPECIALDAYMONTHFORMAT ignored 207
FUTURE ignored 999
STARTYEAR ignored 1369
NORMALDAYMONTHFORMAT ignored 206
STARTTIME ignored 878400
""",
    }

    extraction = build_metadata(FakeMetadataClient(resources), tmp_path, workers=2)

    assert [
        (group.row_name, group.offset, group.count) for group in extraction.sound_slot_groups
    ] == [
        ("EXTENDED", 99, 2),
        ("SELECT", None, None),
    ]
    assert [(enemy.row_name, enemy.race_id) for enemy in extraction.favored_enemies] == [
        ("ORC", 143)
    ]
    assert {(rule.reputation, rule.alignment) for rule in extraction.happiness_rules} == {
        (reputation, alignment) for reputation in (1, 20) for alignment in HappinessAlignment
    }
    assert extraction.banter_timing.frequency == 480
    assert extraction.campaign_calendars[0].start_year == 1369
    assert {link.source_column for link in extraction.character_resource_links} == {
        "FILE",
        "25FILE",
        "POST_DIALOG_FILE",
        "JOIN_DIALOG_FILE",
        "DREAM_SCRIPT_FILE",
        "25OVERRIDE_SCRIPT_FILE",
    }
    assert len(extraction.interaction_rules) == 4


def test_campaign_bound_resource_deduplication_is_case_insensitive(tmp_path: Path) -> None:
    resources = _metadata_resources()
    campaign_lines = resources["CAMPAIGN.2DA"].splitlines()
    campaign_lines[4] = campaign_lines[4].replace("RACETEXT", "racetext")
    resources["CAMPAIGN.2DA"] = "\n".join(campaign_lines)

    extraction = build_metadata(FakeMetadataClient(resources), tmp_path)

    assert len(extraction.race_text_rows) == 1


def test_optional_2da_numbers_accept_all_asterisk_sentinels(tmp_path: Path) -> None:
    resources = _metadata_resources()
    resources["KITLIST.2DA"] = resources["KITLIST.2DA"].replace(
        "0 RESERVE * * * * * * * *",
        "0 RESERVE ** *** **** ***** ** *** **** *****",
    )

    extraction = build_metadata(FakeMetadataClient(resources), tmp_path)
    reserve = extraction.kits[0]

    assert (
        reserve.lower_name_strref,
        reserve.mixed_name_strref,
        reserve.help_strref,
        reserve.abilities,
        reserve.proficiency,
        reserve.unusable,
        reserve.class_id,
        reserve.kit_ids_value,
        reserve.class_text_kit_id,
    ) == (None,) * 9


def test_build_metadata_rejects_bad_worker_count_and_missing_required_column(
    tmp_path: Path,
) -> None:
    client = FakeMetadataClient(_metadata_resources())
    with pytest.raises(AssertionError, match="workers"):
        build_metadata(client, tmp_path, workers=0)

    client.resources["RACETEXT.2DA"] = client.resources["RACETEXT.2DA"].replace("DESCSTR", "WRONG")
    with pytest.raises(AssertionError, match=r"missing required column 'DESCSTR'"):
        build_metadata(client, tmp_path)


def test_fallen_and_unsigned_cells_are_strictly_validated(tmp_path: Path) -> None:
    client = FakeMetadataClient(_metadata_resources())
    client.resources["CLASTEXT.2DA"] = client.resources["CLASTEXT.2DA"].replace(
        "-1 0 113", "-1 2 113"
    )
    with pytest.raises(AssertionError, match=r"CLASTEXT\.FALLEN"):
        build_metadata(client, tmp_path)

    with pytest.raises(AssertionError, match="outside"):
        _parse_uint("256", field="byte", maximum=255)
    with pytest.raises(ValueError):
        _parse_uint("not-a-number", field="value")


def test_tlk_resolution_skips_empty_work(tmp_path: Path) -> None:
    assert _resolve_strings(FakeMetadataClient({}), tmp_path, [], workers=1) == {}


def _metadata_resources() -> dict[str, str]:
    identifier_resources = {
        "RACE.IDS": "IDS V1.0\n1 HUMAN\n7 HALFORC\n",
        "CLASS.IDS": "IDS V1.0\n1 MAGE\n202 LONG_BOW\n202 MAGE_ALL\n",
        "GENDER.IDS": "\n1 MALE\n",
        "ALIGNMEN.IDS": "15\n0x11 LAWFUL_GOOD\n",
        "EA.IDS": "10\n128 NEUTRAL\n",
        "GENERAL.IDS": "30\n1 HUMANOID\n",
        "SPECIFIC.IDS": "5\n0 NONE\n",
        "ANIMATE.IDS": "IDS V1.0\n0x6202 HUMAN_MALE\n",
        "KIT.IDS": "IDS\n0x4000 TRUECLASS\n0x4000 MAGESCHOOL_GENERALIST\n",
        "SNDSLOT.IDS": "IDS V1.0\n0 INITIAL_MEETING\n55 MISCELLANEOUS\n55 RESPONSE_TO_COMPLIMENT1\n",
    }
    rows = []
    for campaign, banter, party, has_metadata in (
        ("SOA", "INTERDIA", "PDIALOG", True),
        ("TOB", "25BANTER", "25DIALOG", True),
        ("BP1", "*", "*", False),
    ):
        values = ["*"] * len(_CAMPAIGN_COLUMNS)
        if has_metadata:
            values[3] = banter
            values[10] = party
            values[26] = "INTERACT"
            values[27] = "YEARS"
            values[29] = "CLASTEXT"
            values[30] = "RACETEXT"
        rows.append(" ".join((campaign, *values)))
    campaign = "\n".join(("2DA V1.0", "*", " ".join(_CAMPAIGN_COLUMNS), *rows, ""))
    race_text = "\n".join(
        (
            "2DA V1.0",
            "-1",
            "ID NAME DESCSTR UPPERCASE BIOGRAPHY",
            "HUMAN 1 100 101 102 -1",
            "",
        )
    )
    class_text = "\n".join(
        (
            "2DA V1.0",
            "-1",
            "CLASSID KITID LOWER DESCSTR MIXED BIOGRAPHY FALLEN BRIEFDESC FALLEN_NOTICE",
            "FIGHTER 2 16384 110 111 112 -1 0 113 -1",
            "",
        )
    )
    kitlist = "\n".join(
        (
            "2DA V1.0",
            "*",
            "ROWNAME LOWER MIXED HELP ABILITIES PROFICIENCY UNUSABLE CLASS KITIDS",
            "0 RESERVE * * * * * * * *",
            "1 BERSERKER 110 121 122 CLABFI02 29 0x00000001 2 0x00004001",
            "",
        )
    )
    interdia = "\n".join(
        (
            "2DA V1.0",
            "NONE",
            "FILE 25FILE",
            "NPC BNPC BNPC25",
            "LATE BLATE",
            "EMPTY NONE ***",
            "",
        )
    )
    pdialog = "\n".join(
        (
            "2DA V1.0",
            "multig",
            "POST_DIALOG_FILE JOIN_DIALOG_FILE DREAM_SCRIPT_FILE 25POST_DIALOG_FILE "
            "25JOIN_DIALOG_FILE 25DREAM_SCRIPT_FILE 25OVERRIDE_SCRIPT_FILE",
            "NPC NPCP NPCJ NPCD NPC25P NPC25J NPC25D NPC25O",
            "LATE LATEP LATEJ LATED",
            "EMPTY *** **** -1 NONE * -1 ***",
            "DANGLE LOSTDLG *** *** *** *** *** ***",
            "",
        )
    )
    banter_25 = "2DA V1.0\nNONE\nFILE\nNPC BNPC25\n"
    dialog_25 = "\n".join(
        (
            "2DA V1.0",
            "multig",
            "POST_DIALOG_FILE JOIN_DIALOG_FILE DREAM_SCRIPT_FILE",
            "NPC NPC25P NPC25J NPC25D",
            "",
        )
    )
    interact = "\n".join(
        (
            "2DA V1.0",
            "0",
            "NPC OTHER",
            "NPC 0 i",
            "OTHER c s",
            "",
        )
    )
    charsnd = "\n".join(
        (
            "2DA V1.0",
            "-1",
            "MALE FEMALE",
            "1 200 -1",
            "55 -1 201",
            "",
        )
    )
    csound = "\n".join(
        (
            "2DA V1.0",
            "*",
            "LETTER",
            "0 *",
            "1 a",
            "55 !x",
            "",
        )
    )
    enginest = "\n".join(
        (
            "2DA V1.0",
            "0",
            "StrRef",
            "ENGINE_A 202",
            "ENGINE_B 203",
            "ENGINE_EMPTY -1",
            "",
        )
    )
    months = "\n".join(
        (
            "2DA V1.0",
            "0",
            "DAYS NAME",
            "0 30 204",
            "1 1 205",
            "",
        )
    )
    years = "\n".join(
        (
            "2DA V1.0",
            "0",
            "VALUE",
            "STARTTIME 878400",
            "STARTYEAR 1369",
            "NORMALDAYMONTHFORMAT 206",
            "SPECIALDAYMONTHFORMAT 207",
            "",
        )
    )
    speech = "\n".join(
        (
            "2DA V1.0",
            "0",
            "OFFSET NUM",
            "* * *",
            "INITIAL_MEETING 0 1",
            "SELECT * *",
            "BATTLE_CRY 9 5",
            "",
        )
    )
    favored_enemies = "\n".join(
        (
            "2DA V1.0",
            "4294967296",
            "STRREF IDS STRREF_HELP",
            "BEHOLDER 208 123 209",
            "ORC 210 143 211",
            "",
        )
    )
    happiness = "\n".join(
        (
            "2DA V1.0",
            "0",
            "GOOD NEUTRAL EVIL",
            "1 -300 -300 80",
            "2 -300 -160 80",
            "3 -160 -160 80",
            "4 -160 -80 80",
            "5 -160 -80 80",
            "6 -80 0 80",
            "7 -80 80 0",
            "8 -80 80 0",
            "9 0 80 0",
            "10 0 80 0",
            "11 0 80 0",
            "12 0 80 0",
            "13 80 80 -80",
            "14 80 80 -80",
            "15 80 80 -80",
            "16 80 0 -160",
            "17 80 0 -160",
            "18 80 0 -160",
            "19 80 0 -300",
            "20 80 0 -300",
            "",
        )
    )
    banter_timing = "\n".join(
        (
            "2DA V1.0",
            "0",
            "VALUE",
            "FREQUENCY 480",
            "PROBABILITY 10",
            "REPLAYDELAY 150",
            "SPECIALPROBABILITY 40",
            "",
        )
    )
    return identifier_resources | {
        "CAMPAIGN.2DA": campaign,
        "RACETEXT.2DA": race_text,
        "CLASTEXT.2DA": class_text,
        "KITLIST.2DA": kitlist,
        "INTERDIA.2DA": interdia,
        "25BANTER.2DA": banter_25,
        "PDIALOG.2DA": pdialog,
        "25DIALOG.2DA": dialog_25,
        "INTERACT.2DA": interact,
        "CHARSND.2DA": charsnd,
        "CSOUND.2DA": csound,
        "ENGINEST.2DA": enginest,
        "MONTHS.2DA": months,
        "YEARS.2DA": years,
        "SPEECH.2DA": speech,
        "HATERACE.2DA": favored_enemies,
        "HAPPY.2DA": happiness,
        "BANTTIMG.2DA": banter_timing,
    }
