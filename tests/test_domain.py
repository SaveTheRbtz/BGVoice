"""Critical Infinity Engine projections and dialogue-graph invariants."""

from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError

from bgvoice.character_models import CharacterDetail, CharacterExtraction, CreDump
from bgvoice.dialogue_models import (
    DialogueDetail,
    DialogueExtraction,
    DialogueLine,
    DialogueTransitionEdge,
    DlgDump,
    DlgTransition,
)
from bgvoice.metadata_models import SoundSlotGroup
from bgvoice.model_types import (
    DialogueLineKind,
    PortraitImage,
    SoundSlotId,
    class_text_kit_id_from_kit_ids,
    cre_kit_value_from_bytes,
    kit_ids_value_from_cre,
)
from tests.factories import make_dialogue_dump, make_dump, make_portrait_resource, make_resource


def test_cre_projection_preserves_voice_metadata_and_sound_slots() -> None:
    dump = make_dump()
    extraction = CharacterExtraction.from_dump(make_resource(), dump)
    detail = extraction.detail

    assert extraction.resource_name == "AERIE.CRE"
    assert extraction.serialized_size == len(dump.model_dump_json().encode())
    assert (
        detail.display_name,
        detail.short_name,
        detail.death_variable,
        detail.dialog_resref,
    ) == ("Aerie", "^0xFF8B7D6DAerie^-", "Aerie", "AERIE")
    assert (
        detail.gender_id,
        detail.race_id,
        detail.class_id,
        detail.alignment_id,
        detail.animation_id,
        detail.racial_enemy_id,
    ) == (2, 2, 14, 17, 0x6202, 255)
    assert detail.kit_raw_bytes == [0, 0, 0, 64]
    assert (detail.cre_kit_value, detail.kit_ids_value) == (0x40000000, 0x4000)
    assert detail.base_attributes.model_dump() == {
        "strength": 10,
        "strength_bonus": 0,
        "intelligence": 16,
        "wisdom": 16,
        "dexterity": 17,
        "constitution": 9,
        "charisma": 14,
    }
    assert [(sound.slot_id, sound.strref, sound.text) for sound in extraction.sounds] == [
        (9, 2001, "For the fallen!"),
        (44, 2044, "What is it, <CHARNAME>?"),
    ]


def test_cre_wire_boundary_ignores_new_fields_and_normalizes_optional_resrefs() -> None:
    payload = make_dump().model_dump(by_alias=True)
    payload["future_dump_field"] = True
    payload["header"]["future_header_field"] = 1
    payload["header"] |= {"dialog": "", "small_portrait": "NONE", "large_portrait": ""}
    payload["header"]["scripts"] = dict.fromkeys(payload["header"]["scripts"], "")

    dump = CreDump.model_validate(payload, strict=True)
    detail = CharacterDetail.from_dump(make_resource(), dump)

    assert detail.dialog_resref is None
    assert detail.small_portrait is None
    assert detail.large_portrait is None
    assert {
        detail.override_script,
        detail.class_script,
        detail.race_script,
        detail.general_script,
        detail.default_script,
    } == {None}


def test_character_name_fallback_and_resource_identity() -> None:
    detail = CharacterDetail.from_dump(
        make_resource("EMPTY.CRE"),
        make_dump("EMPTY.CRE", short_name="  ", long_name=None, dialog="NONE"),
    )
    assert (detail.display_name, detail.short_name, detail.long_name, detail.dialog_resref) == (
        "EMPTY",
        None,
        None,
        None,
    )

    with pytest.raises(AssertionError, match="inventory names"):
        CharacterExtraction.from_dump(make_resource("AERIE.CRE"), make_dump("MINSC.CRE"))


def test_portrait_conversion_produces_exact_rgb_png() -> None:
    palette = Image.new("P", (3, 2))
    palette.putpalette([255, 0, 0, 0, 255, 0, *([0] * 762)])
    palette.putdata([0, 1, 0, 1, 0, 1])
    bmp = BytesIO()
    palette.save(bmp, format="BMP")

    portrait = PortraitImage.from_bmp(make_portrait_resource("aeries.bmp"), bmp.getvalue())

    assert (portrait.resref, portrait.width, portrait.height) == ("AERIES", 3, 2)
    with Image.open(BytesIO(portrait.png)) as png:
        assert (png.format, png.mode, png.size) == ("PNG", "RGB", (3, 2))
        assert png.tobytes() == b"\xff\x00\x00\x00\xff\x00" * 3


@pytest.mark.parametrize(
    ("raw_bytes", "cre_value", "kit_ids_value", "class_text_kit_id"),
    [
        ([0, 0, 1, 64], 0x40010000, 0x4001, 1),
        ([0, 0, 128, 0], 0x00800000, 0x0080, 0x0080),
        ([0, 128, 0, 0], 0x00008000, 0x80000000, 0x80000000),
        ([0, 0, 0, 0], 0, None, None),
    ],
)
def test_kit_identifiers_use_verified_engine_byte_order(
    raw_bytes: list[int],
    cre_value: int,
    kit_ids_value: int | None,
    class_text_kit_id: int | None,
) -> None:
    assert cre_kit_value_from_bytes(raw_bytes) == cre_value
    assert kit_ids_value_from_cre(cre_value) == kit_ids_value
    if kit_ids_value is not None:
        assert class_text_kit_id_from_kit_ids(kit_ids_value) == class_text_kit_id


@pytest.mark.parametrize("raw_bytes", [[], [0, 0, 0, 0, 0], [0, 0, 0, 256]])
def test_kit_data_rejects_structurally_invalid_bytes(raw_bytes: list[int]) -> None:
    with pytest.raises(AssertionError, match=r"four|unsigned"):
        cre_kit_value_from_bytes(raw_bytes)


@pytest.mark.parametrize(
    ("resource", "mutation"),
    [
        ("CRE", ("version", "V2.0")),
        ("DLG", ("version", "V2.0")),
        ("DLG", ("num_states", 3)),
        ("DLG", ("num_transitions", 4)),
    ],
)
def test_wire_resources_reject_unsupported_or_partial_graphs(
    resource: str,
    mutation: tuple[str, object],
) -> None:
    field, value = mutation
    if resource == "CRE":
        payload = make_dump().model_dump()
        payload[field] = value
        model = CreDump
    else:
        payload = make_dialogue_dump().model_dump()
        (payload["header"] if field.startswith("num_") else payload)[field] = value
        model = DlgDump

    with pytest.raises(ValidationError):
        model.model_validate(payload, strict=True)


def test_dialogue_projection_preserves_spoken_lines_tokens_and_graph_edges() -> None:
    dump = make_dialogue_dump()
    extraction = DialogueExtraction.from_dump(dump)
    detail = extraction.detail

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
        for line in extraction.lines
    ] == [
        (DialogueLineKind.NPC, 0, None, 1),
        (DialogueLineKind.PLAYER, 0, 0, 2),
        (DialogueLineKind.NPC, 1, None, 3),
        (DialogueLineKind.PLAYER, 1, 2, 4),
        (DialogueLineKind.JOURNAL, 1, 2, 5),
    ]
    assert [line.tokens for line in extraction.lines] == [
        [],
        [],
        ["DAYANDMONTH"],
        ["CHARNAME"],
        [],
    ]
    assert extraction.lines[0].state_trigger_text == 'Global("MetAerie","GLOBAL",0)'
    assert [edge.id for edge in extraction.edges] == [
        "AERIE.DLG:0:0",
        "AERIE.DLG:0:1",
        "AERIE.DLG:1:2",
    ]
    assert extraction.edges[1].terminates_dialog is True
    assert (
        extraction.edges[2].trigger_index,
        extraction.edges[2].action_index,
        extraction.edges[2].next_dialog,
        extraction.edges[2].next_state_index,
    ) == (3, 4, "MINSC", 7)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trigger_text", "True()"),
        ("action_text", "DoSomething()"),
        ("next_state_index", None),
    ],
)
def test_transition_requires_structural_indices_and_one_exit_mode(
    field: str,
    value: object,
) -> None:
    payload = make_dialogue_dump().states[0].transitions[0].model_dump()
    payload[field] = value

    with pytest.raises(ValidationError):
        DlgTransition.model_validate(payload, strict=True)


def test_terminating_transition_preserves_ignored_destination_bytes() -> None:
    payload = make_dialogue_dump().states[0].transitions[1].model_dump()
    payload["next_dialog"] = "AERIE"

    transition = DlgTransition.model_validate(payload, strict=True)
    assert (transition.next_dialog, transition.next_state_index, transition.terminates_dialog) == (
        "AERIE",
        None,
        True,
    )


def test_unresolved_scripts_preserve_their_structural_indices() -> None:
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


@pytest.mark.parametrize("invalid_child", ["line_resource", "line_count", "edge_resource"])
def test_dialogue_extraction_rejects_inconsistent_children(invalid_child: str) -> None:
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())
    payload = extraction.model_dump()
    if invalid_child == "line_resource":
        payload["lines"][0]["dialogue_resource_name"] = "MINSC.DLG"
    elif invalid_child == "line_count":
        payload["lines"] = []
    else:
        payload["edges"][0]["dialogue_resource_name"] = "MINSC.DLG"

    with pytest.raises(ValidationError):
        DialogueExtraction.model_validate(payload)


def test_dialogue_aggregate_rejects_impossible_spoken_counts() -> None:
    detail = DialogueDetail.from_dump(make_dialogue_dump())
    with pytest.raises(ValidationError, match="spoken line count"):
        DialogueDetail.model_validate(
            detail.model_dump() | {"dialogue_line_count": detail.dialogue_line_count + 1}
        )


def test_sound_slot_groups_require_offset_and_count_together() -> None:
    with pytest.raises(ValidationError, match="both be present"):
        SoundSlotGroup(
            source_resource="SPEECH.2DA",
            ordinal=0,
            row_name="SELECT",
            offset=SoundSlotId(9),
            count=None,
        )
