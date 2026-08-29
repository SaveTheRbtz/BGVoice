"""WeiDU mod export from completed dialogue audio."""

import re
from pathlib import Path
from zipfile import ZipFile

import pytest

from bgvoice.generation_store import GenerationStore
from bgvoice.mod_export import create_archive, export_mod, sound_resref
from bgvoice.storage_records import (
    DirectedLineRecord,
    ExtractionRunRecord,
    GeneratedAudioRecord,
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
    merge = game_root / "EET" / "temp" / "append" / "dlg" / "AERIE25J.d"
    merge.parent.mkdir(parents=True)
    merge.write_text("APPEND ~AERIE~\n", encoding="utf-8")

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
    assert summary.dialogue_files == 1
    assert summary.audio_bytes == sum(map(len, source_audio))
    assert not stale.exists()
    assert (output / "setup-bgvoice.exe").read_bytes() == weidu.read_bytes()
    assert (output / "setup-bgvoice.tp2").is_file()
    installer_library = (output / "bgvoice" / "lib" / "install.tpa").read_text(encoding="utf-8")
    assert "[%sound%]" in installer_library
    assert '["%sound%"]' not in installer_library
    readme = (output / "bgvoice" / "README.md").read_text(encoding="utf-8")
    assert "Version 0.9.0." in readme

    dialogue_scripts = list((output / "bgvoice" / "dialogue").glob("*.tpa"))
    assert [script.name for script in dialogue_scripts] == ["000000.tpa"]
    dialogue_patch = dialogue_scripts[0].read_text(encoding="utf-8")
    assert "AERIE.DLG" in dialogue_patch
    assert "state_index" not in dialogue_patch
    assert "source_strref" not in dialogue_patch
    audio_directory = output / "bgvoice" / "audio"
    for text, audio in (
        ("Hello.", source_audio[0]),
        ("A quest for <DAYANDMONTH>.", source_audio[1]),
    ):
        match = re.search(
            rf"{re.escape(text)}~~~~~\s+"
            rf'OUTER_SPRINT \$bgv_catalog_000000\("%bgv_key%"\) ~(BGV\w+)~',
            dialogue_patch,
        )
        assert match is not None
        assert (audio_directory / f"{match.group(1)}.wav").read_bytes() == audio
    assert "READ_STRREF bgv_text_offset bgv_text" in dialogue_patch
    assert "VARIABLE_IS_SET" in dialogue_patch
    assert "VARIABLE_IS_IN_ARRAY" not in dialogue_patch
    assert "ACTION_FOR_EACH bgv_dialogue IN ~AERIE.DLG~ ~AERIE25J.DLG~" in dialogue_patch
    assert "COPY_EXISTING ~%bgv_dialogue%~" in dialogue_patch
    assert "IF_EXISTS" in dialogue_patch

    setup = (output / "setup-bgvoice.tp2").read_text(encoding="utf-8").casefold()
    assert "version ~0.9.0~" in setup
    assert setup.count("begin ~") == 1
    assert "begin ~install generated dialogue audio~" in setup
    assert "designated 0" in setup
    assert "subcomponent" not in setup
    assert "bgv_replace" not in setup
    assert "fill missing" not in setup
    assert "patch_if" not in installer_library.casefold()

    output = tmp_path / "not-an-export"
    output.mkdir()
    important = output / "important.txt"
    important.write_text("keep me", encoding="utf-8")

    with pytest.raises(AssertionError, match="not a BGVoice export"):
        await export_mod(scenario_database, output)

    assert important.read_text(encoding="utf-8") == "keep me"


def test_archive_contains_files_directly_at_its_root(tmp_path: Path) -> None:
    output = tmp_path / "mod"
    (output / "bgvoice").mkdir(parents=True)
    (output / "setup-bgvoice.tp2").write_text("VERSION ~1.0.0~", encoding="utf-8")
    (output / "bgvoice" / "README.md").write_text("BGVoice", encoding="utf-8")
    archive = tmp_path / "BGVoice-v1.0.0.zip"

    assert create_archive(output, archive) == 2

    with ZipFile(archive) as package:
        assert package.namelist() == ["bgvoice/README.md", "setup-bgvoice.tp2"]
