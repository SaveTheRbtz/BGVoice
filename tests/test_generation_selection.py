"""Deterministic voice workload selection and profile rules."""

from pathlib import Path

import pytest

import bgvoice.generation as generation_module
from bgvoice.generation import GenericVoiceProfile, load_workloads, round_robin_lines
from bgvoice.model_types import DialogueLineKind, ProviderGender, RaceId
from bgvoice.reader import PipelineReader
from tests.factories import make_dialogue_line


@pytest.mark.parametrize("limit", [3, 5, None, 99])
def test_round_robin_orders_dialogues_and_deduplicates_exact_text(
    limit: int | None,
) -> None:
    dialogues = {
        "B.DLG": [
            make_dialogue_line("B.DLG", 5, "Last"),
            make_dialogue_line("B.DLG", 1, "Same"),
            make_dialogue_line("B.DLG", 3, "case"),
        ],
        "A.DLG": [
            make_dialogue_line("A.DLG", 4, " Same "),
            make_dialogue_line("A.DLG", 2, "Case"),
            make_dialogue_line("A.DLG", 0, "Same"),
        ],
    }
    selected = round_robin_lines(dialogues, limit)
    expected = [
        "A.DLG:npc:0:-",
        "A.DLG:npc:2:-",
        "B.DLG:npc:3:-",
        "A.DLG:npc:4:-",
        "B.DLG:npc:5:-",
    ]
    assert [line.id for line in selected] == expected[:limit]


@pytest.mark.parametrize("line_count", [0, 5, 40])
def test_voice_design_dialogue_samples_are_stable_and_bounded(line_count: int) -> None:
    eligible = [
        f"Distinct substantive dialogue line {state} with enough context to reveal the voice."
        for state in range(line_count)
    ]
    lines = [
        make_dialogue_line("A.DLG", 100, "Hmm."),
        make_dialogue_line("A.DLG", 101, "x" * generation_module.VOICE_DESIGN_SAMPLE_MIN_CHARS),
        *[make_dialogue_line("A.DLG", state, text) for state, text in enumerate(eligible)],
    ]
    forward = generation_module._dialogue_samples("aerie", {"A.DLG": lines})
    reversed_input = generation_module._dialogue_samples("aerie", {"A.DLG": lines[::-1]})

    assert forward == reversed_input
    assert len(forward) == min(line_count, generation_module.VOICE_DESIGN_SAMPLE_COUNT)
    assert len(forward) == len(set(forward))
    assert set(forward) <= set(eligible)


@pytest.mark.anyio
async def test_current_voice_workload_uses_attributed_nonempty_npc_lines(
    shared_scenario_database: Path,
) -> None:
    reader = await PipelineReader.open(shared_scenario_database)
    try:
        workload = (await load_workloads(reader, ["Aerie"], 1))[0]
        complete_workload = (await load_workloads(reader, ["Aerie"], None))[0]
        deduplicated = await load_workloads(reader, ["Aerie", "aerie"], None)
    finally:
        reader.close()

    assert workload.lines == complete_workload.lines[:1]
    assert workload.dialogue_samples == complete_workload.dialogue_samples
    assert deduplicated == [complete_workload]
    assert workload.voice.voice_id == "aerie"
    assert len(workload.lines) == 1
    assert all(line.line_kind is DialogueLineKind.NPC and line.text for line in workload.lines)
    assert workload.dialogue_samples == ()
    assert workload.ability_scores.render() == ("STR 10, DEX 17, CON 9, INT 16, WIS 16, CHA 14")
    assert workload.portrait_png == b"\x89PNG\r\n\x1a\nfixture"
    assert (workload.race_description, workload.class_description) == (
        "The Tel'Quessir.",
        "A multiclass spellcaster.",
    )
    assert (
        workload.generic_profile.gender,
        workload.generic_profile.race_id,
        workload.generic_profile.race_name,
        workload.generic_profile.display_name,
    ) == (ProviderGender.FEMALE, RaceId(2), "Elf", "BGVoice Generic · Female · Elf")


@pytest.mark.parametrize(
    ("gender_id", "expected"),
    [
        (1, ProviderGender.MALE),
        (2, ProviderGender.FEMALE),
        (0, ProviderGender.NEUTRAL),
        (4, ProviderGender.NEUTRAL),
        (66, ProviderGender.NEUTRAL),
    ],
)
def test_provider_gender_collapses_engine_categories(
    gender_id: int,
    expected: ProviderGender,
) -> None:
    assert ProviderGender.from_engine_id(gender_id) is expected


@pytest.mark.parametrize(
    ("profile", "expected_id"),
    [
        (
            GenericVoiceProfile(ProviderGender.FEMALE, RaceId(2), "Elf"),
            "generic:gender:female:race:2",
        ),
        (
            GenericVoiceProfile(ProviderGender.NEUTRAL, None, None),
            "generic:gender:neutral:race:other",
        ),
    ],
)
def test_generic_profile_identity_uses_bounded_gender_and_race_buckets(
    profile: GenericVoiceProfile,
    expected_id: str,
) -> None:
    assert profile.id == expected_id


def test_generic_voice_races_use_nine_named_buckets_and_other() -> None:
    race_ids = [0] * 100 + [255] * 100
    for race_id in range(1, 13):
        race_ids.extend([race_id] * (20 - race_id))
    assert generation_module._common_default_race_ids(race_ids) == frozenset(range(1, 10))
