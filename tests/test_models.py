"""Tests for IESDP-backed model constraints and voice-data projections."""

import pytest
from pydantic import ValidationError

from bgvoice.models import (
    CharacterDetail,
    CreClassification,
    CreDump,
    CreResource,
    DialogueDetail,
    DialogueExtraction,
    DialogueLine,
    DlgDump,
    StringReference,
    clean_display_name,
)
from tests.factories import make_dialogue_dump, make_dump, make_resource


def test_character_detail_projects_voice_fields() -> None:
    detail = CharacterDetail.from_dump(make_resource(), make_dump())

    assert detail.display_name == "Aerie"
    assert detail.short_name == "^0xFF8B7D6DAerie^-"
    assert detail.death_variable == "Aerie"
    assert detail.dialog_resref == "AERIE"
    assert (detail.gender_id, detail.class_id) == (2, 14)
    assert (detail.general_script, detail.race_script, detail.large_portrait) == (None, None, None)


def test_character_detail_falls_back_to_resref() -> None:
    detail = CharacterDetail.from_dump(
        make_resource("EMPTY.CRE"),
        make_dump("EMPTY.CRE", short_name="  ", long_name=None, dialog="NONE"),
    )

    assert detail.display_name == "EMPTY"
    assert detail.short_name is None
    assert detail.long_name is None
    assert detail.dialog_resref is None


def test_clean_display_name_handles_empty_values() -> None:
    assert clean_display_name(None) is None
    assert clean_display_name(" ^0xFFFFFFFF^- ") is None


def test_resrefs_are_limited_to_eight_characters() -> None:
    resource = make_resource("ABCDEFGH.CRE")
    assert resource.resref == "ABCDEFGH"

    payload = resource.model_dump(by_alias=True)
    payload["resref"] = "ABCDEFGHI"
    with pytest.raises(ValidationError):
        CreResource.model_validate(payload, strict=True)


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


@pytest.mark.parametrize("value", [-1, 0x1_0000_0000])
def test_strrefs_are_unsigned_32_bit_values(value: int) -> None:
    with pytest.raises(ValidationError):
        StringReference(strref=value, text=None)


def test_strrefs_accept_the_unsigned_32_bit_maximum() -> None:
    assert StringReference(strref=0xFFFF_FFFF, text=None).strref == 0xFFFF_FFFF


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
        ("npc", 0, None, 1),
        ("player", 0, 0, 2),
        ("npc", 1, None, 3),
        ("player", 1, 2, 4),
        ("journal", 1, 2, 5),
    ]


def test_dialogue_extraction_rejects_lines_from_another_resource() -> None:
    extraction = DialogueExtraction.from_dump(make_dialogue_dump())
    wrong_line = extraction.lines[0].model_copy(update={"dialogue_resource_name": "MINSC.DLG"})

    with pytest.raises(ValidationError, match=r"contains lines for.*MINSC\.DLG"):
        DialogueExtraction(detail=extraction.detail, lines=[wrong_line])
