"""Dialogue attribution, voice grouping, and generation publication behavior."""

from collections.abc import Sequence
from pathlib import Path

import pytest
from lancedb.pydantic import LanceModel

from bgvoice.attribution import _voice_family, _VoiceDraft
from bgvoice.character_models import CharacterExtraction, CharacterSound
from bgvoice.database import PipelineDatabase
from bgvoice.dialogue_models import DialogueExtraction
from bgvoice.metadata_models import CharacterResourceLink
from bgvoice.model_types import (
    BIOGRAPHY_SOUND_SLOT_ID,
    CharacterResourceRole,
    DetailStatus,
    KitIdsValue,
    ProviderGender,
    ResourceTargetType,
    RunKind,
    RunStatus,
)
from bgvoice.storage_records import (
    CharacterAttributionRecord,
    CharacterRecord,
    DialogueRecord,
    ExtractionRunRecord,
    VoiceResourceRecord,
)
from tests.factories import make_dialogue_dump, make_dialogue_resource, make_dump, make_resource
from tests.scenarios import finish_empty_stage, finish_run, make_metadata, rows


def _attributions(path: Path) -> list[CharacterAttributionRecord]:
    return rows(path, "character_dialogues", CharacterAttributionRecord)


def _voices(path: Path) -> list[VoiceResourceRecord]:
    return rows(path, "voice_resources", VoiceResourceRecord)


def _biography(
    extraction: CharacterExtraction,
    *,
    strref: int,
    text: str,
) -> CharacterExtraction:
    sounds = [sound for sound in extraction.sounds if sound.slot_id != BIOGRAPHY_SOUND_SLOT_ID]
    sounds.append(CharacterSound(slot_id=BIOGRAPHY_SOUND_SLOT_ID, strref=strref, text=text))
    return extraction.model_copy(update={"sounds": sounds})


def test_attribution_accounts_for_every_character_dialogue_and_spoken_line(
    scenario_database: Path,
) -> None:
    database = PipelineDatabase(scenario_database)
    summary = database.rebuild_attributions()

    assert (
        summary.characters_total,
        summary.characters_unavailable,
        summary.characters_matched,
        summary.characters_missing_dialogue,
        summary.characters_dialogue_failed,
        summary.characters_without_dialogue,
    ) == (12, 0, 2, 1, 1, 9)
    assert (
        summary.dialogues_total,
        summary.dialogues_attributed,
        summary.dialogues_unattributed,
        summary.attributed_dialogue_lines,
        summary.unattributed_dialogue_lines,
    ) == (3, 2, 1, 4, 4)

    current = {
        row.character_resource_name: row
        for row in _attributions(scenario_database)
        if row.run_id == summary.run_id
    }
    assert current["AERIE.CRE"].status == "matched"
    assert current["MINSC.CRE"].dialogue_status == "failed"
    assert current["GHOST.CRE"].status == "missing_dialogue"
    assert current["EMPTY.CRE"].status == "no_dialogue"
    assert current["AERIE.CRE"].resolved_dialogue_resource_names == ["AERIE.DLG"]
    assert [
        voice.voice_id for voice in _voices(scenario_database) if voice.run_id == summary.run_id
    ] == ["aerie"]


def test_metadata_dialogue_links_are_normalized_deduplicated_and_report_partial_matches(
    tmp_path: Path,
) -> None:
    path = tmp_path / "linked.lancedb"
    database = PipelineDatabase(path)
    metadata = make_metadata()
    metadata = metadata.model_copy(
        update={
            "character_resource_links": [
                *metadata.character_resource_links,
                CharacterResourceLink(
                    source_resource="INTERDIA.2DA",
                    ordinal=1,
                    death_variable="aerie",
                    source_column="FILE",
                    role=CharacterResourceRole.BANTER_DIALOGUE,
                    target_type=ResourceTargetType.DIALOGUE,
                    target_resref="BAERIE",
                ),
                CharacterResourceLink(
                    source_resource="PDIALOG.2DA",
                    ordinal=2,
                    death_variable="AERIE",
                    source_column="JOIN_DIALOG_FILE",
                    role=CharacterResourceRole.JOIN_DIALOGUE,
                    target_type=ResourceTargetType.DIALOGUE,
                    target_resref="GHOST",
                ),
            ]
        }
    )
    metadata_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)
    database.replace_metadata(metadata_run, metadata)
    finish_run(database, metadata_run)

    character = make_resource()
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [character])
    database.apply_detail_batch(
        character_run,
        [CharacterExtraction.from_dump(character, make_dump(dialog="AERIE"))],
        [],
    )
    finish_run(database, character_run)

    resources = [make_dialogue_resource("AERIE.DLG"), make_dialogue_resource("BAERIE.DLG")]
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, resources)
    database.apply_dialogue_batch(
        dialogue_run,
        [
            DialogueExtraction.from_dump(make_dialogue_dump(item.resource_name))
            for item in resources
        ],
        [],
    )
    finish_run(database, dialogue_run)

    summary = database.rebuild_attributions()
    result = next(row for row in _attributions(path) if row.run_id == summary.run_id)
    assert result.status == "partial_match"
    assert result.dialogue_status is DetailStatus.COMPLETE
    assert result.declared_dialogue_resrefs == ["AERIE", "BAERIE", "GHOST"]
    assert result.missing_dialogue_resrefs == ["GHOST"]
    assert result.resolved_dialogue_resource_names == ["AERIE.DLG", "BAERIE.DLG"]
    assert summary.attributed_dialogue_lines == 8


def test_voices_group_by_name_omit_zero_line_groups_and_choose_deterministic_prompt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "voices.lancedb"
    database = PipelineDatabase(path)
    metadata = make_metadata()
    metadata_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.METADATA)
    database.replace_metadata(metadata_run, metadata)
    finish_run(database, metadata_run)

    resources = [make_resource(name) for name in ("OHHEX8.CRE", "OHHEX9.CRE", "OHHEX25.CRE")]
    zero_line = make_resource("JOLUS.CRE")
    character_run = database.start_run(tmp_path, "iecli test")
    database.replace_inventory(character_run, [*resources, zero_line])
    details: list[CharacterExtraction] = []
    for index, (resource, dialogue) in enumerate(
        zip(resources, ("HEXXAT", "hexxat", "HEXXA25A"), strict=True)
    ):
        extraction = CharacterExtraction.from_dump(
            resource,
            make_dump(
                resource.resource_name,
                short_name="Hexxat" if index != 1 else "hexxat",
                long_name="Hexxat",
                death_variable=f"UNRELATED{index}",
                dialog=dialogue,
            ),
        )
        extraction = extraction.model_copy(
            update={
                "detail": extraction.detail.model_copy(
                    update={"kit_ids_value": KitIdsValue(0x4001)}
                )
            }
        )
        details.append(
            _biography(
                extraction,
                strref=(900, 700, 700)[index],
                text=(
                    "Short history.",
                    "A much longer personal biography.",
                    "  A much longer personal biography.  ",
                )[index],
            )
        )
    details.append(
        CharacterExtraction.from_dump(
            zero_line,
            make_dump(
                "JOLUS.CRE",
                short_name="Sir Jolus",
                long_name="Sir Jolus",
                death_variable="HEXXAT",
                dialog=None,
            ),
        )
    )
    database.apply_detail_batch(character_run, details, [])
    finish_run(database, character_run)

    dialogue_resources = [
        make_dialogue_resource("HEXXAT.DLG"),
        make_dialogue_resource("HEXXA25A.DLG"),
    ]
    dialogue_run = database.start_run(tmp_path, "iecli test", run_kind=RunKind.DIALOGUES)
    database.replace_dialogue_inventory(dialogue_run, dialogue_resources)
    database.apply_dialogue_batch(
        dialogue_run,
        [
            DialogueExtraction.from_dump(make_dialogue_dump(resource.resource_name))
            for resource in dialogue_resources
        ],
        [],
    )
    finish_run(database, dialogue_run)

    summary = database.rebuild_attributions()
    voices = [voice for voice in _voices(path) if voice.run_id == summary.run_id]

    assert [voice.voice_id for voice in voices] == ["hexxat"]
    voice = voices[0]
    assert (voice.family_id, voice.gender) == ("hexxat", ProviderGender.FEMALE)
    assert voice.variant_resource_names == ["OHHEX25.CRE", "OHHEX8.CRE", "OHHEX9.CRE"]
    assert voice.dialogue_resrefs == ["HEXXA25A", "HEXXAT"]
    assert voice.biography_sound_id == "OHHEX25.CRE:74"
    assert voice.prompt == (
        "Name: Hexxat\nGender: Female\nRace: Elf\nClass: Cleric Mage\nKit: Berserker\n"
        "Alignment: Lawful Good\n\nBiography:\nA much longer personal biography."
    )


def test_gender_split_uses_stable_qualified_ids_without_mixed_dialogues(
    shared_scenario_database: Path,
) -> None:
    characters = rows(shared_scenario_database, "characters", CharacterRecord)
    dialogues = rows(shared_scenario_database, "dialogues", DialogueRecord)
    attributions = rows(
        shared_scenario_database,
        "character_dialogues",
        CharacterAttributionRecord,
    )
    character_seed = next(row for row in characters if row.detail is not None)
    dialogue_seed = next(row for row in dialogues if row.detail is not None)
    attribution_seed = attributions[0]

    members: list[CharacterRecord] = []
    attribution_by_character: dict[str, CharacterAttributionRecord] = {}
    dialogues_by_resource: dict[str, DialogueRecord] = {}
    texts_by_dialogue: dict[str, set[str]] = {}
    for gender, prefix in ((ProviderGender.FEMALE, "F"), (ProviderGender.MALE, "M")):
        for index in range(2):
            resref = f"G{prefix}{index}"
            resource_name = f"{resref}.CRE"
            dialogue_name = f"{resref}.DLG"
            detail = character_seed.detail
            assert detail is not None
            member = character_seed.model_copy(
                update={
                    "resource_name": resource_name,
                    "resref": resref,
                    "detail": detail.model_copy(
                        update={
                            "display_name": "Guard",
                            "death_variable": resref,
                            "dialog_resref": resref,
                            "gender_id": 2 if gender is ProviderGender.FEMALE else 1,
                        }
                    ),
                }
            )
            members.append(member)
            attribution_by_character[resource_name.casefold()] = attribution_seed.model_copy(
                update={
                    "key": CharacterAttributionRecord.key_for("test", resource_name),
                    "run_id": "test",
                    "character_resource_name": resource_name,
                    "declared_dialogue_resrefs": [resref],
                    "missing_dialogue_resrefs": [],
                    "resolved_dialogue_resource_names": [dialogue_name],
                }
            )
            dialogues_by_resource[dialogue_name.casefold()] = dialogue_seed.model_copy(
                update={"resource_name": dialogue_name, "resref": resref}
            )
            texts_by_dialogue[dialogue_name.casefold()] = {
                f"{resref} first line",
                f"{resref} second line",
                f"{resref} third line",
            }

    def family(
        family_id: str,
        family_members: list[CharacterRecord],
        family_attributions: dict[str, CharacterAttributionRecord],
        family_texts: dict[str, set[str]],
    ) -> list[_VoiceDraft]:
        return _voice_family(
            family_id,
            family_members,
            family_attributions,
            dialogues_by_resource,
            family_texts,
            [],
            {},
        )

    voices = family("guardian", members, attribution_by_character, texts_by_dialogue)
    assert [(voice.voice_id, voice.gender) for voice in voices] == [
        ("guardian~g=female", ProviderGender.FEMALE),
        ("guardian~g=male", ProviderGender.MALE),
    ]

    sparse_members = [
        next(member for member in members if member.resource_name == "GF0.CRE"),
        next(member for member in members if member.resource_name == "GM0.CRE"),
    ]
    neutral_detail = sparse_members[1].detail
    assert neutral_detail is not None
    sparse_members[1] = sparse_members[1].model_copy(
        update={"detail": neutral_detail.model_copy(update={"gender_id": 0})}
    )
    for index, member in enumerate(sparse_members):
        detail = member.detail
        assert detail is not None
        sparse_members[index] = member.model_copy(
            update={"detail": detail.model_copy(update={"death_variable": "shared"})}
        )
    sparse_texts = {
        "gf0.dlg": {f"Female line {index}" for index in range(6)},
        "gm0.dlg": {"Neutral line"},
    }
    sparse_voices = family("guardian", sparse_members, attribution_by_character, sparse_texts)
    assert [(voice.voice_id, voice.gender) for voice in sparse_voices] == [
        ("guardian~g=female", ProviderGender.FEMALE),
        ("guardian~g=neutral", ProviderGender.NEUTRAL),
    ]
    assert [
        voice.voice_id
        for voice in family("guard", sparse_members, attribution_by_character, sparse_texts)
    ] == ["guard"]

    assert {dialogue.resref for voice in voices for dialogue in voice.dialogues} == {
        f"G{prefix}{index}" for prefix in ("F", "M") for index in range(2)
    }
    assigned = [member.resource_name for voice in voices for member in voice.members]
    assert len(assigned) == len(set(assigned)) == 4
    assert [
        voice.voice_id
        for voice in family("guard", members, attribution_by_character, texts_by_dialogue)
    ] == ["guard"]

    shared_name = "GSHARED.DLG"
    dialogues_by_resource[shared_name.casefold()] = dialogue_seed.model_copy(
        update={"resource_name": shared_name, "resref": "GSHARED"}
    )
    texts_by_dialogue[shared_name.casefold()] = {"Shared first line", "Shared second line"}
    for resource_name in ("GF0.CRE", "GM0.CRE"):
        key = resource_name.casefold()
        attribution_by_character[key] = attribution_by_character[key].model_copy(
            update={
                "resolved_dialogue_resource_names": [
                    *attribution_by_character[key].resolved_dialogue_resource_names,
                    shared_name,
                ]
            }
        )

    with_shared = family("guardian", members, attribution_by_character, texts_by_dialogue)
    shared = next(voice for voice in with_shared if voice.gender is ProviderGender.NEUTRAL)
    assert shared.voice_id == "guardian~g=neutral"
    assert "GSHARED" in {dialogue.resref for dialogue in shared.dialogues}
    assert shared.members

    shared_male_dialogue = {
        name: (
            attribution.model_copy(update={"resolved_dialogue_resource_names": ["GM0.DLG"]})
            if name.startswith("gm")
            else attribution
        )
        for name, attribution in attribution_by_character.items()
    }
    unsplit = family("guard", members, shared_male_dialogue, texts_by_dialogue)
    assert [(voice.voice_id, voice.gender) for voice in unsplit] == [("guard", None)]


def test_attribution_requires_completed_current_inputs_from_one_install(tmp_path: Path) -> None:
    database = PipelineDatabase(tmp_path / "pipeline.lancedb")
    finish_empty_stage(database, tmp_path, RunKind.CHARACTERS)
    with pytest.raises(AssertionError, match="dialogues run"):
        database.rebuild_attributions()

    finish_empty_stage(database, tmp_path, RunKind.DIALOGUES)
    finish_empty_stage(database, tmp_path / "other-game", RunKind.METADATA)
    with pytest.raises(AssertionError, match="same game install"):
        database.rebuild_attributions()

    finish_empty_stage(database, tmp_path, RunKind.METADATA)
    database.start_run(tmp_path, "iecli test", run_kind=RunKind.CHARACTERS)
    with pytest.raises(AssertionError, match="terminal successful characters run"):
        database.rebuild_attributions()


def test_failed_attribution_generation_never_replaces_the_completed_generation(
    scenario_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = PipelineDatabase(scenario_database)
    published_runs = {row.run_id for row in _attributions(scenario_database)}
    published_voices = _voices(scenario_database)
    original_upsert = database._upsert

    def fail_voice_publication(
        table_name: str,
        key: str,
        records: Sequence[LanceModel],
    ) -> None:
        if table_name == "voice_resources":
            raise OSError("simulated attribution write failure")
        original_upsert(table_name, key, records)

    monkeypatch.setattr(database, "_upsert", fail_voice_publication)
    with pytest.raises(OSError, match="simulated attribution write failure"):
        database.rebuild_attributions()

    runs = rows(scenario_database, "extraction_runs", ExtractionRunRecord)
    completed = [
        run.id
        for run in runs
        if run.run_kind is RunKind.ATTRIBUTION and run.status is RunStatus.COMPLETE
    ]
    failed = [
        run.id
        for run in runs
        if run.run_kind is RunKind.ATTRIBUTION and run.status is RunStatus.FAILED
    ]
    assert set(completed) == published_runs
    assert len(failed) == 1
    assert _voices(scenario_database) == published_voices
    assert not [voice for voice in _voices(scenario_database) if voice.run_id == failed[0]]
