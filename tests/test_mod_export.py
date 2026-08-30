"""WeiDU mod export from completed dialogue audio."""

import re
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest

from bgvoice import mod_export
from bgvoice.generation_store import GenerationStore
from bgvoice.mod_export import create_archive, export_mod, sound_resref
from bgvoice.model_types import (
    DialogueLineKind,
    ProviderGender,
    RunKind,
    RunStatus,
)
from bgvoice.storage_records import (
    DirectedLineRecord,
    ExtractionRunRecord,
    GeneratedAudioRecord,
    VoiceResourceRecord,
)
from tests.scenarios import rows


@pytest.mark.parametrize(
    ("index", "expected"),
    [
        (0, "BGV00000"),
        (35, "BGV0000Z"),
        (36, "BGV00010"),
        (36**5 - 1, "BGVZZZZZ"),
    ],
)
def test_sound_resrefs_fill_the_five_digit_base36_namespace(
    index: int,
    expected: str,
) -> None:
    assert sound_resref(index) == expected


@pytest.mark.anyio
@pytest.mark.integration
async def test_export_preserves_content_identity_audio_and_installer_contract(
    scenario_database: Path,
    tmp_path: Path,
) -> None:
    source_audio = (b"OggSfirst line", b"OggSsecond line")
    recordings = [
        GeneratedAudioRecord(
            id=DirectedLineRecord.id_for("aerie", line_id),
            voice_id="aerie",
            dialogue_line_id=line_id,
            inworld_voice_id="voice-aerie",
            batch_operation_name="operations/test-batch",
            audio=audio,
            created_at="2026-08-27T12:00:00+00:00",
        )
        for line_id, audio in zip(
            ("AERIE.DLG:npc:0:-", "AERIE.DLG:npc:1:-"),
            source_audio,
            strict=True,
        )
    ]
    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_generated_audio(recordings)
    finally:
        store.close()

    game_roots = {
        Path(run.game_root)
        for run in rows(scenario_database, "extraction_runs", ExtractionRunRecord)
    }
    assert len(game_roots) == 1
    game_root = game_roots.pop()
    game_root.mkdir(parents=True, exist_ok=True)
    weidu = game_root / "setup-eet.exe"
    weidu.write_bytes(b"fake WeiDU executable")
    output = tmp_path / "bgvoice-mod"
    (output / "setup-bgvoice.exe").parent.mkdir(parents=True)
    (output / "setup-bgvoice.exe").write_bytes(b"old WeiDU")
    (output / "setup-bgvoice.tp2").write_text("old export", encoding="utf-8")
    stale = output / "bgvoice" / "audio" / "stale.wav"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"obsolete")

    summary = await export_mod(scenario_database, output, version="0.9.0")

    assert Path(summary.output) == output.resolve()
    assert Path(summary.source_game) == game_root.resolve()
    assert summary.generated_lines == 2
    assert summary.audio_files == 2
    assert summary.voice_catalogs == 1
    assert summary.audio_bytes == sum(map(len, source_audio))
    assert not stale.exists()
    assert (output / "setup-bgvoice.exe").read_bytes() == weidu.read_bytes()
    installer_library = (output / "bgvoice" / "lib" / "install.tpa").read_text(encoding="utf-8")
    readme = (output / "bgvoice" / "README.md").read_text(encoding="utf-8")
    assert "Version 0.9.0." in readme

    catalog_scripts = list((output / "bgvoice" / "catalog").glob("*.tpa"))
    assert [script.name for script in catalog_scripts] == ["000000.tpa"]
    voice_catalog = catalog_scripts[0].read_text(encoding="utf-8")
    assert "OUTER_SPRINT bgv_family ~~~~~aerie~~~~~" in voice_catalog
    assert "$bgv_default_catalog_by_name" in voice_catalog
    assert all(
        source_coordinate not in voice_catalog
        for source_coordinate in ("AERIE.DLG", "state_index", "source_strref")
    )
    audio_directory = output / "bgvoice" / "audio"
    for text, audio in (
        ("Hello.", source_audio[0]),
        ("A quest for <DAYANDMONTH>.", source_audio[1]),
    ):
        match = re.search(
            rf"{re.escape(text)}~~~~~\s+"
            rf'OUTER_SPRINT \$bgv_recordings\(~000000~ "%bgv_key%"\) ~(BGV\w+)~',
            voice_catalog,
        )
        assert match is not None
        assert (audio_directory / f"{match.group(1)}.wav").read_bytes() == audio
    setup = (output / "setup-bgvoice.tp2").read_text(encoding="utf-8").casefold()
    assert "version ~0.9.0~" in setup
    assert setup.count("begin ~") == 1
    assert "designated 0" in setup

    # The sole install behavior is exact-text replacement for both TLK genders.
    assert "READ_STRREF bgv_text_offset bgv_text" in installer_library
    assert "SAY text_offset ~%bgv_male_text%~ [%sound%] ~%bgv_female_text%~ [%sound%]" in (
        installer_library
    )
    assert "PATCH_IF bgv_candidate_count = 1" in installer_library
    assert "ELSE PATCH_IF bgv_candidate_count > 1" in installer_library

    unrelated = tmp_path / "not-an-export"
    unrelated.mkdir()
    important = unrelated / "important.txt"
    important.write_text("keep me", encoding="utf-8")
    with pytest.raises(AssertionError, match="not a BGVoice export"):
        await export_mod(scenario_database, unrelated)
    assert important.read_text(encoding="utf-8") == "keep me"


@pytest.mark.parametrize(
    ("recording_voices", "expected"),
    [
        (("aerie", "aerie"), [("aerie", "recording-a")]),
        (
            ("aerie", "minsc"),
            [("aerie", "recording-a"), ("minsc", "recording-b")],
        ),
    ],
)
def test_export_identity_is_voice_and_exact_text(
    tmp_path: Path,
    recording_voices: tuple[str, str],
    expected: list[tuple[str, str]],
) -> None:
    game_root = tmp_path / "game"
    game_root.mkdir()
    run = ExtractionRunRecord(
        id="dialogue-run",
        run_kind=RunKind.DIALOGUES,
        started_at="2026-08-27T12:00:00+00:00",
        completed_at="2026-08-27T12:01:00+00:00",
        game_root=str(game_root),
        iecli_version="test",
        status=RunStatus.COMPLETE,
        resources_discovered=2,
        details_attempted=2,
        details_extracted=2,
        failures=0,
    )
    lines = [
        mod_export._ExportLine(
            id=f"{resource}.DLG:npc:0:-",
            run_id=run.id,
            dialogue_resource_name=f"{resource}.DLG",
            line_kind=DialogueLineKind.NPC,
            state_index=0,
            text="Hello.",
        )
        for resource in ("A", "B")
    ]
    recordings = [
        mod_export._ExportRecording(
            id=f"recording-{resource.casefold()}",
            voice_id=voice_id,
            dialogue_line_id=line.id,
        )
        for resource, voice_id, line in zip(
            ("A", "B"),
            recording_voices,
            lines,
            strict=True,
        )
    ]
    recordings.append(
        mod_export._ExportRecording(
            id="recording-stale",
            voice_id=recording_voices[0],
            dialogue_line_id=lines[1].id,
        )
    )
    voices = [
        VoiceResourceRecord(
            key=f"attribution:{voice_id}",
            run_id="attribution",
            voice_id=voice_id,
            family_id=voice_id,
            gender=ProviderGender.FEMALE,
            display_name=voice_id.title(),
            prompt=f"Name: {voice_id.title()}",
            variant_resource_names=[voice_id.upper()],
            dialogue_resrefs=[
                resource
                for resource, assigned_voice in zip(("A", "B"), recording_voices, strict=True)
                if assigned_voice == voice_id
            ],
            search_text=voice_id,
        )
        for voice_id in sorted(set(recording_voices))
    ]

    assets, source_game = mod_export._content_assets(recordings, lines, [run], voices)

    assert source_game == game_root.resolve()
    assert [(asset.voice_id, asset.recording_id) for asset in assets] == expected


@pytest.mark.parametrize(
    ("voice_id", "gender", "registration", "absent"),
    [
        (
            "commoner~g=female",
            ProviderGender.FEMALE,
            "$bgv_catalog_by_name_gender",
            "$bgv_default_catalog_by_name",
        ),
        (
            "commoner",
            ProviderGender.FEMALE,
            "$bgv_default_catalog_by_name",
            "$bgv_catalog_by_name_gender",
        ),
    ],
)
def test_catalog_registration_distinguishes_split_variants_from_unsplit_families(
    voice_id: str,
    gender: ProviderGender | None,
    registration: str,
    absent: str,
) -> None:
    asset = mod_export._ContentAsset(
        voice_id=voice_id,
        family_id="commoner",
        gender=gender,
        run_id="dialogue-run",
        text="Move along.",
        recording_id="recording",
        sound_resref="BGV00000",
    )

    catalog = mod_export._voice_catalog(voice_id, "commoner", gender, [asset], "000000")

    assert "OUTER_SPRINT bgv_family ~~~~~commoner~~~~~" in catalog
    assert registration in catalog
    assert absent not in catalog
    if voice_id != "commoner":
        assert gender is not None
        assert f"OUTER_SPRINT bgv_gender ~{gender.value}~" in catalog


def test_archive_contains_files_directly_at_its_root(tmp_path: Path) -> None:
    output = tmp_path / "mod"
    (output / "bgvoice").mkdir(parents=True)
    (output / "setup-bgvoice.tp2").write_text("VERSION ~1.0.0~", encoding="utf-8")
    (output / "bgvoice" / "README.md").write_text("BGVoice", encoding="utf-8")
    archive = tmp_path / "BGVoice-v1.0.0.zip"

    assert create_archive(output, archive) == 2

    with ZipFile(archive) as package:
        assert package.namelist() == ["bgvoice/README.md", "setup-bgvoice.tp2"]
        assert {item.compress_type for item in package.infolist()} == {ZIP_STORED}
