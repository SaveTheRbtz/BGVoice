"""WeiDU mod export from completed dialogue audio."""

import re
from pathlib import Path
from zipfile import ZipFile

import pytest

from bgvoice import mod_export
from bgvoice.generation_store import GenerationStore
from bgvoice.mod_export import create_archive, export_mod, sound_resref
from bgvoice.model_types import DialogueLineKind, RunKind, RunStatus
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
async def test_export_builds_an_installable_weidu_mod_from_generated_audio(
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
    assert (output / "setup-bgvoice.tp2").is_file()
    installer_library = (output / "bgvoice" / "lib" / "install.tpa").read_text(encoding="utf-8")
    assert "[%sound%]" in installer_library
    assert '["%sound%"]' not in installer_library
    readme = (output / "bgvoice" / "README.md").read_text(encoding="utf-8")
    assert "Version 0.9.0." in readme

    catalog_scripts = list((output / "bgvoice" / "catalog").glob("*.tpa"))
    assert [script.name for script in catalog_scripts] == ["000000.tpa"]
    voice_catalog = catalog_scripts[0].read_text(encoding="utf-8")
    assert "OUTER_SPRINT bgv_voice ~~~~~aerie~~~~~" in voice_catalog
    assert "AERIE.DLG" not in voice_catalog
    assert "state_index" not in voice_catalog
    assert "source_strref" not in voice_catalog
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
    assert "READ_STRREF bgv_text_offset bgv_text" in installer_library
    assert "COPY_EXISTING_REGEXP GLOB ~.+\\.CRE$~" in installer_library
    assert "READ_STRREF 0x0c bgv_name" in installer_library
    assert "READ_STRREF 0x08 bgv_name" in installer_library
    assert "TEXT_SPRINT bgv_name ~%SOURCE_RES%~" in installer_library
    assert "REPLACE_TEXTUALLY CASE_INSENSITIVE EVALUATE_REGEXP" in installer_library
    assert "READ_ASCII 0x280 bgv_death_variable (32) NULL" in installer_library
    assert "READ_ASCII 0x2cc bgv_dialogue (8) NULL" in installer_library
    assert "~CAMPAIGN.2DA~" in installer_library
    assert "bgv_row 4 bgv_table" in installer_library
    assert "bgv_row 11 bgv_table" in installer_library
    assert "LPF BGVOICE_PAD_2DA" in installer_library
    assert "COUNT_2DA_ROWS bgv_columns" in installer_library
    assert "RET_ARRAY bgv_dialogue_owners" in installer_library
    assert "EET_end/lib/tables.tph" in installer_library
    assert "bgv_candidate_count" in installer_library
    assert "BGVoice coverage:" in installer_library
    assert "EET/temp/append" not in installer_library

    setup = (output / "setup-bgvoice.tp2").read_text(encoding="utf-8").casefold()
    assert "version ~0.9.0~" in setup
    assert setup.count("begin ~") == 1
    assert "begin ~install generated dialogue audio~" in setup
    assert "designated 0" in setup
    assert "subcomponent" not in setup
    assert "bgv_replace" not in setup
    assert "fill missing" not in setup

    output = tmp_path / "not-an-export"
    output.mkdir()
    important = output / "important.txt"
    important.write_text("keep me", encoding="utf-8")

    with pytest.raises(AssertionError, match="not a BGVoice export"):
        await export_mod(scenario_database, output)

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
    voices = [
        VoiceResourceRecord(
            key=f"attribution:{voice_id}",
            run_id="attribution",
            voice_id=voice_id,
            display_name=voice_id.title(),
            prompt=f"Name: {voice_id.title()}",
            variant_resource_names=[voice_id.upper()],
            dialogue_resrefs=[],
            search_text=voice_id,
        )
        for voice_id in sorted(set(recording_voices))
    ]

    assets, source_game = mod_export._content_assets(recordings, lines, [run], voices)

    assert source_game == game_root.resolve()
    assert [(asset.voice_id, asset.recording_id) for asset in assets] == expected


def test_archive_contains_files_directly_at_its_root(tmp_path: Path) -> None:
    output = tmp_path / "mod"
    (output / "bgvoice").mkdir(parents=True)
    (output / "setup-bgvoice.tp2").write_text("VERSION ~1.0.0~", encoding="utf-8")
    (output / "bgvoice" / "README.md").write_text("BGVoice", encoding="utf-8")
    archive = tmp_path / "BGVoice-v1.0.0.zip"

    assert create_archive(output, archive) == 2

    with ZipFile(archive) as package:
        assert package.namelist() == ["bgvoice/README.md", "setup-bgvoice.tp2"]
