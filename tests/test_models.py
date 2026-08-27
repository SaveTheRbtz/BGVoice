"""Tests for IESDP-backed model constraints and voice-data projections."""

from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError

from bgvoice.models import (
    BanterTimingSettings,
    CampaignCalendarDefinition,
    CampaignResourceBinding,
    CampaignResourceKind,
    CharacterDetail,
    CharacterExtraction,
    CharacterResourceLink,
    CharacterResourceRole,
    CharacterSound,
    CreClassification,
    CreDump,
    CreResource,
    DialogueDetail,
    DialogueExtraction,
    DialogueLine,
    DialogueLineKind,
    DialogueTransitionEdge,
    DlgDump,
    DlgTransition,
    EngineString,
    FavoredEnemyDefinition,
    HappinessAlignment,
    HappinessRule,
    IdentifierKind,
    InteractionKind,
    InteractionRule,
    MonthDefinition,
    PortraitImage,
    RaceId,
    ResourceTargetType,
    SoundsetLine,
    SoundSlotGroup,
    SoundSlotId,
    SoundSlotSuffix,
    SourceKind,
    StringReference,
    VoiceId,
    VoiceResource,
    class_text_kit_id_from_kit_ids,
    clean_display_name,
    cre_kit_value_from_bytes,
    kit_ids_value_from_cre,
)
from tests.factories import make_dialogue_dump, make_dump, make_portrait_resource, make_resource


def test_character_detail_projects_voice_fields() -> None:
    dump = make_dump()
    extraction = CharacterExtraction.from_dump(make_resource(), dump)
    detail = extraction.detail

    assert extraction.resource_name == "AERIE.CRE"
    assert extraction.serialized_size == len(dump.model_dump_json().encode("utf-8"))
    assert detail.display_name == "Aerie"
    assert detail.short_name == "^0xFF8B7D6DAerie^-"
    assert detail.death_variable == "Aerie"
    assert detail.dialog_resref == "AERIE"
    assert (detail.gender_id, detail.class_id) == (2, 14)
    assert (detail.animation_id, detail.racial_enemy_id) == (0x6202, 255)
    assert detail.class_levels.model_dump() == {
        "first_class": 7,
        "second_class": 7,
        "third_class": 0,
    }
    assert detail.base_attributes.model_dump() == {
        "strength": 10,
        "strength_bonus": 0,
        "intelligence": 16,
        "wisdom": 16,
        "dexterity": 17,
        "constitution": 9,
        "charisma": 14,
    }
    assert (
        detail.morale,
        detail.morale_break,
        detail.morale_recovery_time,
        detail.reputation,
    ) == (10, 5, 60, 0)
    assert detail.kit_raw_bytes == [0, 0, 0, 64]
    assert detail.cre_kit_value == 0x40000000
    assert detail.kit_ids_value == 0x4000
    assert (detail.general_script, detail.race_script, detail.large_portrait) == (None, None, None)
    assert [sound.model_dump() for sound in extraction.sounds] == [
        {"slot_id": 9, "strref": 2001, "text": "For the fallen!"},
        {"slot_id": 44, "strref": 2044, "text": "What is it, <CHARNAME>?"},
    ]
    assert {"resource_name", "sounds", "serialized_size"}.isdisjoint(CharacterDetail.model_fields)


def test_portrait_image_converts_palette_bmp_to_optimized_rgb_png() -> None:
    palette = Image.new("P", (3, 2))
    palette.putpalette([255, 0, 0, 0, 255, 0, *([0] * 762)])
    palette.putdata([0, 1, 0, 1, 0, 1])
    bmp = BytesIO()
    palette.save(bmp, format="BMP")

    portrait = PortraitImage.from_bmp(
        make_portrait_resource("aeries.bmp"),
        bmp.getvalue(),
    )

    assert portrait.resref == "AERIES"
    assert portrait.source.model_dump() == {
        "kind": SourceKind.OVERRIDE,
        "path": "C:/game/override/aeries.bmp",
    }
    assert (portrait.width, portrait.height) == (3, 2)
    assert portrait.png.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(portrait.png)) as png:
        assert (png.format, png.mode, png.size) == ("PNG", "RGB", (3, 2))
        assert png.tobytes() == b"\xff\x00\x00\x00\xff\x00" * 3


def test_character_extraction_rejects_a_dump_for_another_resource() -> None:
    with pytest.raises(AssertionError, match=r"inventory names.*dump"):
        CharacterExtraction.from_dump(make_resource("AERIE.CRE"), make_dump("MINSC.CRE"))


def test_character_detail_falls_back_to_resref() -> None:
    detail = CharacterDetail.from_dump(
        make_resource("EMPTY.CRE"),
        make_dump("EMPTY.CRE", short_name="  ", long_name=None, dialog="NONE"),
    )

    assert detail.display_name == "EMPTY"
    assert detail.short_name is None
    assert detail.long_name is None
    assert detail.dialog_resref is None


def test_voice_resource_owns_members_and_derived_fields() -> None:
    voice = VoiceResource(
        id=VoiceId("hexxat"),
        display_name="Hexxat",
        prompt="Name: Hexxat\nGender: Female",
        variant_resource_names=["OHHEX8.CRE", "OHHEX25.CRE"],
        dialogue_resrefs=["HEXXA25A", "HEXXAT"],
    )

    assert voice.variant_count == 2
    assert voice.search_text == (
        "hexxat Hexxat Name: Hexxat\nGender: Female OHHEX8.CRE OHHEX25.CRE HEXXA25A HEXXAT"
    )


def test_clean_display_name_handles_empty_values() -> None:
    assert clean_display_name(None) is None
    assert clean_display_name(" ^0xFFFFFFFF^- ") is None


def test_resrefs_are_limited_to_eight_characters() -> None:
    resource = make_resource("ABCDEFGH.CRE")
    assert resource.resref == "ABCDEFGH"
    assert resource.source_kind is SourceKind.OVERRIDE

    payload = resource.model_dump(by_alias=True)
    payload["resref"] = "ABCDEFGHI"
    with pytest.raises(ValidationError):
        CreResource.model_validate(payload, strict=True)


def test_resource_kinds_reject_values_outside_the_enum() -> None:
    payload = make_resource().model_dump(by_alias=True)
    payload["source_kind"] = "archive"

    with pytest.raises(ValidationError, match="override"):
        CreResource.model_validate(payload)


def test_iecli_wire_projections_ignore_unknown_fields() -> None:
    creature = make_resource().model_dump(by_alias=True)
    creature["future_inventory_field"] = {"value": 1}
    assert CreResource.model_validate(creature).resref == "AERIE"

    cre = make_dump().model_dump(by_alias=True)
    cre["future_dump_field"] = True
    cre["header"]["future_header_field"] = 1
    cre["header"]["short_name"]["future_string_field"] = "AERIEW"
    cre["header"]["classification"]["future_classification_field"] = 1
    cre["header"]["class_levels"]["future_level_field"] = 1
    cre["header"]["base_attributes"]["future_attribute_field"] = 1
    cre["header"]["scripts"]["future_script_field"] = "AERIE2"
    assert CreDump.model_validate(cre, strict=True).header.short_name.strref == 100

    dialogue = make_dialogue_dump().model_dump()
    dialogue["future_dump_field"] = True
    dialogue["header"]["future_header_field"] = 1
    dialogue["states"][0]["future_state_field"] = 1
    dialogue["states"][0]["response_text"]["future_string_field"] = "AERIEW"
    transition = dialogue["states"][0]["transitions"][0]
    transition["future_transition_field"] = 1
    transition["flags"]["future_flag_field"] = 1
    assert DlgDump.model_validate(dialogue, strict=True).header.num_states == 2


def test_blank_optional_wire_resrefs_are_normalized() -> None:
    cre = make_dump().model_dump(by_alias=True)
    cre["header"] |= {"dialog": "", "small_portrait": "", "large_portrait": ""}
    cre["header"]["scripts"] = dict.fromkeys(cre["header"]["scripts"], "")
    detail = CharacterDetail.from_dump(make_resource(), CreDump.model_validate(cre, strict=True))

    assert detail.dialog_resref is None
    assert detail.small_portrait is None
    assert detail.large_portrait is None
    assert all(
        script is None
        for script in (
            detail.override_script,
            detail.class_script,
            detail.race_script,
            detail.general_script,
            detail.default_script,
        )
    )

    dialogue = make_dialogue_dump().model_dump()
    dialogue["states"][0]["transitions"][0]["next_dialog"] = ""
    dump = DlgDump.model_validate(dialogue, strict=True)
    assert DialogueTransitionEdge.from_dump(dump)[0].next_dialog is None


def test_omitted_optional_wire_fields_default_to_none() -> None:
    assert StringReference.model_validate({"strref": 1}).text is None

    cre = make_dump().model_dump(by_alias=True)
    header = cre["header"]
    for field in ("dialog", "small_portrait", "large_portrait"):
        header.pop(field)
    header["scripts"].pop("race_script")
    detail = CharacterDetail.from_dump(make_resource(), CreDump.model_validate(cre, strict=True))

    assert detail.dialog_resref is None
    assert detail.small_portrait is None
    assert detail.large_portrait is None
    assert detail.race_script is None

    dialogue = make_dialogue_dump().model_dump()
    state = dialogue["states"][1]
    state.pop("trigger_index")
    state.pop("trigger_text")
    transition = dialogue["states"][0]["transitions"][1]
    for field in (
        "player_text",
        "journal_text",
        "trigger_index",
        "trigger_text",
        "action_index",
        "action_text",
        "next_dialog",
        "next_state_index",
    ):
        transition.pop(field)

    dump = DlgDump.model_validate(dialogue, strict=True)

    assert dump.states[1].trigger_index is None
    assert dump.states[1].trigger_text is None
    assert dump.states[0].transitions[1].next_state_index is None


@pytest.mark.parametrize("value", [-1, 0x100])
def test_cre_byte_fields_are_unsigned(value: int) -> None:
    payload = make_dump().header.classification.model_dump(by_alias=True)
    payload["gender"] = value

    with pytest.raises(ValidationError):
        CreClassification.model_validate(payload, strict=True)


def test_cre_byte_fields_accept_the_unsigned_maximum() -> None:
    payload = make_dump().header.classification.model_dump(by_alias=True)
    payload["gender"] = 0xFF

    assert CreClassification.model_validate(payload, strict=True).gender == 0xFF


def test_cre_ability_bytes_preserve_modded_values_above_tabletop_limits() -> None:
    payload = make_dump().model_dump(by_alias=True)
    payload["header"]["base_attributes"] |= {
        "strength": 28,
        "constitution": 28,
        "charisma": 30,
    }

    dump = CreDump.model_validate(payload, strict=True)

    assert (
        dump.header.base_attributes.strength,
        dump.header.base_attributes.constitution,
        dump.header.base_attributes.charisma,
    ) == (28, 28, 30)

    payload["header"]["base_attributes"]["strength"] = 256
    with pytest.raises(ValidationError):
        CreDump.model_validate(payload, strict=True)


@pytest.mark.parametrize(
    ("raw_bytes", "cre_value", "kit_ids_value", "class_text_kit_id"),
    [
        ([0, 0, 1, 64], 0x40010000, 0x4001, 1),
        ([0, 0, 128, 0], 0x00800000, 0x0080, 0x0080),
        ([0, 128, 0, 0], 0x00008000, 0x80000000, 0x80000000),
    ],
)
def test_cre_kit_values_use_raw_bytes_not_iecli_decoding(
    raw_bytes: list[int],
    cre_value: int,
    kit_ids_value: int,
    class_text_kit_id: int,
) -> None:
    assert cre_kit_value_from_bytes(raw_bytes) == cre_value
    assert kit_ids_value_from_cre(cre_value) == kit_ids_value
    assert class_text_kit_id_from_kit_ids(kit_ids_value) == class_text_kit_id


def test_zero_cre_kit_has_no_canonical_kit_foreign_key() -> None:
    assert kit_ids_value_from_cre(0) is None


@pytest.mark.parametrize("raw_bytes", [[], [0, 0, 0, 0, 0], [0, 0, 0, 256]])
def test_cre_kit_bytes_must_be_exactly_four_unsigned_bytes(raw_bytes: list[int]) -> None:
    with pytest.raises(AssertionError, match=r"four|unsigned"):
        cre_kit_value_from_bytes(raw_bytes)


@pytest.mark.parametrize("value", [-1, 0x1_0000_0000])
def test_cre_and_class_text_kit_values_are_unsigned(value: int) -> None:
    with pytest.raises(AssertionError, match="unsigned 32-bit"):
        kit_ids_value_from_cre(value)
    with pytest.raises(AssertionError, match="unsigned 32-bit"):
        class_text_kit_id_from_kit_ids(value)


@pytest.mark.parametrize("value", [-1, 0x1_0000_0000])
def test_strrefs_are_unsigned_32_bit_values(value: int) -> None:
    with pytest.raises(ValidationError):
        StringReference(strref=value, text=None)


def test_strrefs_accept_the_unsigned_32_bit_maximum() -> None:
    assert StringReference(strref=0xFFFF_FFFF, text=None).strref == 0xFFFF_FFFF


def test_cre_soundsets_contain_exactly_one_hundred_slots() -> None:
    payload = make_dump().model_dump()
    payload["header"]["soundset"] = payload["header"]["soundset"][:-1]

    with pytest.raises(ValidationError, match="at least 100"):
        CreDump.model_validate(payload, strict=True)


def test_only_v1_resource_versions_are_accepted() -> None:
    cre = make_dump().model_dump()
    cre["version"] = "V2.0"
    with pytest.raises(ValidationError):
        CreDump.model_validate(cre, strict=True)

    dialogue = make_dialogue_dump().model_dump()
    dialogue["version"] = "V2.0"
    with pytest.raises(ValidationError):
        DlgDump.model_validate(dialogue, strict=True)


@pytest.mark.parametrize(
    ("header_field", "declared", "message"),
    [
        ("num_states", 3, "DLG header declares 3 states; decoded 2"),
        ("num_transitions", 4, "DLG header declares 4 transitions; decoded 3"),
    ],
)
def test_dialogue_header_counts_must_match_decoded_graph(
    header_field: str,
    declared: int,
    message: str,
) -> None:
    payload = make_dialogue_dump().model_dump()
    payload["header"][header_field] = declared

    with pytest.raises(ValidationError) as raised:
        DlgDump.model_validate(payload, strict=True)

    assert message in str(raised.value)


def test_dialogue_metrics_and_lines_preserve_dlg_semantics() -> None:
    dump = make_dialogue_dump()
    detail = DialogueDetail.from_dump(dump)

    assert (
        detail.state_count,
        detail.transition_count,
        detail.npc_line_count,
        detail.player_line_count,
        detail.journal_line_count,
        detail.dialogue_line_count,
    ) == (2, 3, 2, 2, 1, 4)
    assert [
        (line.line_kind, line.state_index, line.transition_index, line.strref)
        for line in DialogueLine.from_dump(dump)
    ] == [
        (DialogueLineKind.NPC, 0, None, 1),
        (DialogueLineKind.PLAYER, 0, 0, 2),
        (DialogueLineKind.NPC, 1, None, 3),
        (DialogueLineKind.PLAYER, 1, 2, 4),
        (DialogueLineKind.JOURNAL, 1, 2, 5),
    ]
    lines = DialogueLine.from_dump(dump)
    assert (lines[0].state_trigger_index, lines[0].state_trigger_text) == (
        0,
        'Global("MetAerie","GLOBAL",0)',
    )
    assert all(line.state_trigger_index is None for line in lines if line.line_kind != "npc")
    assert [line.tokens for line in lines] == [[], [], ["DAYANDMONTH"], ["CHARNAME"], []]

    edges = DialogueTransitionEdge.from_dump(dump)
    assert len(edges) == 3
    assert edges[0].next_dialog == "AERIE"
    assert edges[1].terminates_dialog is True
    assert (edges[1].next_dialog, edges[1].next_state_index) == (None, None)
    assert (edges[2].trigger_index, edges[2].action_index) == (3, 4)
    assert lines[0].id == "AERIE.DLG:npc:0:-"
    assert edges[2].id == "AERIE.DLG:1:2"
    assert "DAYANDMONTH" in lines[2].search_text
    assert "SetGlobal" in edges[2].search_text


def test_dialogue_extraction_owns_identity_children_and_serialized_size() -> None:
    dump = make_dialogue_dump()
    extraction = DialogueExtraction.from_dump(dump)

    assert extraction.resource_name == "AERIE.DLG"
    assert extraction.serialized_size == len(dump.model_dump_json().encode("utf-8"))
    assert (len(extraction.lines), len(extraction.edges)) == (5, 3)
    assert {"resource_name", "serialized_size"}.isdisjoint(DialogueDetail.model_fields)


def test_domain_search_text_and_ids_are_case_insensitive_at_resource_boundaries() -> None:
    resource = make_resource()
    dialogue = make_dialogue_dump("aerie.dlg")
    extraction = DialogueExtraction.from_dump(dialogue)
    line = DialogueLine.from_dump(dialogue)[0]
    edge = DialogueTransitionEdge.from_dump(dialogue)[0]

    assert resource.source_path in resource.search_text
    assert CharacterSound.id_for("aerie.cre", 9) == "AERIE.CRE:9"
    assert extraction.resource_name == "aerie.dlg"
    assert line.id == "AERIE.DLG:npc:0:-"
    assert edge.id == "AERIE.DLG:0:0"


def test_dialogue_extraction_rejects_lines_from_another_resource() -> None:
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())
    wrong_line = extraction.lines[0].model_copy(update={"dialogue_resource_name": "MINSC.DLG"})

    with pytest.raises(ValidationError, match=r"contains lines for.*MINSC\.DLG"):
        DialogueExtraction.model_validate(
            extraction.model_dump() | {"lines": [wrong_line.model_dump()]}
        )


def test_dialogue_extraction_reconciles_aggregate_and_line_records() -> None:
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())

    with pytest.raises(ValidationError, match="line counts"):
        DialogueExtraction.model_validate(extraction.model_dump() | {"lines": []})


def test_dialogue_transition_allows_implicit_current_dialog_destination() -> None:
    payload = make_dialogue_dump().states[0].transitions[0].model_dump()
    payload |= {
        "flags": {"raw": 0, "decoded": []},
        "next_dialog": None,
        "next_state_index": 0,
        "terminates_dialog": False,
    }

    transition = DlgTransition.model_validate(payload, strict=True)

    assert (transition.next_dialog, transition.next_state_index) == (None, 0)


def test_dialogue_transition_rejects_nonterminating_edge_without_state() -> None:
    payload = make_dialogue_dump().states[0].transitions[0].model_dump()
    payload["next_state_index"] = None

    with pytest.raises(ValidationError, match="no destination state"):
        DlgTransition.model_validate(payload, strict=True)


@pytest.mark.parametrize(
    ("transition_index", "terminates_dialog"),
    [(0, True), (1, False)],
)
def test_dialogue_transition_requires_exactly_one_exit_mode(
    transition_index: int,
    terminates_dialog: bool,
) -> None:
    payload = make_dialogue_dump().states[0].transitions[transition_index].model_dump()
    payload["terminates_dialog"] = terminates_dialog

    with pytest.raises(ValidationError, match="no destination state"):
        DlgTransition.model_validate(payload, strict=True)


def test_dialogue_transition_allows_ignored_destination_when_terminating() -> None:
    payload = make_dialogue_dump().states[0].transitions[1].model_dump()
    payload["next_dialog"] = "AERIE"

    transition = DlgTransition.model_validate(payload, strict=True)
    assert transition.next_dialog == "AERIE"


def test_unresolved_trigger_and_action_text_do_not_discard_structural_indices() -> None:
    payload = make_dialogue_dump().model_dump()
    payload["states"][0]["trigger_text"] = None
    transition = payload["states"][1]["transitions"][0]
    transition["trigger_text"] = None
    transition["action_text"] = None

    dump = DlgDump.model_validate(payload, strict=True)
    lines = DialogueLine.from_dump(dump)
    edges = DialogueTransitionEdge.from_dump(dump)

    assert (lines[0].state_trigger_index, lines[0].state_trigger_text) == (0, None)
    assert (edges[2].trigger_index, edges[2].trigger_text) == (3, None)
    assert (edges[2].action_index, edges[2].action_text) == (4, None)


def test_resolved_trigger_text_still_requires_an_index() -> None:
    payload = make_dialogue_dump().states[0].transitions[0].model_dump()
    payload["trigger_text"] = "True()"

    with pytest.raises(ValidationError, match="requires a trigger index"):
        DlgTransition.model_validate(payload, strict=True)


def test_metadata_models_capture_voice_and_campaign_resources() -> None:
    assert IdentifierKind.SOUND_SLOT == "sound_slot"
    binding = CampaignResourceBinding(
        campaign_id="SOA",
        resource_kind=CampaignResourceKind.BANTER_DIALOGUES,
        resource_resref="INTERDIA",
    )
    link = CharacterResourceLink(
        source_resource="INTERDIA.2DA",
        ordinal=0,
        death_variable="AERIE",
        source_column="FILE",
        role=CharacterResourceRole.BANTER_DIALOGUE,
        target_type=ResourceTargetType.DIALOGUE,
        target_resref="BAERIE",
    )
    rule = InteractionRule(
        source_resource="INTERACT.2DA",
        speaker_ordinal=0,
        target_ordinal=1,
        speaker_death_variable="AERIE",
        target_death_variable="MINSC",
        kind=InteractionKind.COMPLIMENT,
    )
    soundset_line = SoundsetLine(
        source_resource="CHARSND.2DA",
        soundset_name="FEMALE1",
        slot_id=SoundSlotId(9),
        strref=2001,
        text="For the fallen!",
    )
    suffix = SoundSlotSuffix(
        source_resource="CSOUND.2DA",
        ordinal=9,
        slot_id=SoundSlotId(9),
        file_suffix="a",
    )
    engine_string = EngineString(
        source_resource="ENGINEST.2DA",
        ordinal=0,
        key="STRREF_GAME_DAY",
        strref=15980,
        text="Day",
    )
    month = MonthDefinition(
        source_resource="MONTHS.2DA",
        ordinal=0,
        month_id=0,
        days=30,
        name_strref=15934,
        name="Hammer",
    )
    calendar = CampaignCalendarDefinition(
        source_resource="YEARS.2DA",
        start_time=0,
        start_year=1369,
        normal_format_strref=15980,
        normal_format="Day <DAY>, <MONTHNAME>",
        special_format_strref=15981,
        special_format="<DAYANDMONTH>",
    )

    assert binding.resource_resref == "INTERDIA"
    assert (link.role, link.target_type) == ("banter_dialogue", "dialogue")
    assert rule.kind == "compliment"
    assert (soundset_line.slot_id, suffix.file_suffix) == (9, "a")
    assert (engine_string.strref, month.days, calendar.start_year) == (15980, 30, 1369)


def test_voice_behavior_metadata_models_enforce_engine_dimensions() -> None:
    group = SoundSlotGroup(
        source_resource="SPEECH.2DA",
        ordinal=0,
        row_name="BATTLE_CRY",
        offset=SoundSlotId(9),
        count=5,
    )
    enemy = FavoredEnemyDefinition(
        source_resource="HATERACE.2DA",
        ordinal=0,
        row_name="BEHOLDER",
        name_strref=54770,
        name="Beholder",
        race_id=RaceId(123),
        help_strref=54772,
        help_text="Beholders are dangerous aberrations.",
    )
    happiness = HappinessRule(
        source_resource="HAPPY.2DA",
        reputation=1,
        alignment=HappinessAlignment.GOOD,
        happiness=-300,
    )
    timing = BanterTimingSettings(
        source_resource="BANTTIMG.2DA",
        frequency=480,
        probability=10,
        replay_delay=150,
        special_probability=40,
    )

    assert (group.offset, group.count) == (9, 5)
    assert (enemy.race_id, enemy.help_strref) == (123, 54772)
    assert (happiness.alignment, timing.frequency) == (HappinessAlignment.GOOD, 480)

    with pytest.raises(ValidationError, match="both be present"):
        SoundSlotGroup(
            source_resource="SPEECH.2DA",
            ordinal=0,
            row_name="SELECT",
            offset=None,
            count=1,
        )
    extended_group = SoundSlotGroup(
        source_resource="SPEECH.2DA",
        ordinal=0,
        row_name="EXTENDED",
        offset=SoundSlotId(99),
        count=2,
    )
    assert (extended_group.offset, extended_group.count) == (99, 2)
    with pytest.raises(ValidationError):
        HappinessRule(
            source_resource="HAPPY.2DA",
            reputation=21,
            alignment=HappinessAlignment.GOOD,
            happiness=0,
        )
