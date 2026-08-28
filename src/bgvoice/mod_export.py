"""Export generated recordings as a content-matched WeiDU EET mod."""

import asyncio
import shutil
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from zipfile import ZIP_STORED, ZipFile

from lancedb.pydantic import LanceModel
from lancedb.table import AsyncTable
from pydantic import BaseModel, ConfigDict, Field

from bgvoice.model_types import DialogueLineKind
from bgvoice.reader import PipelineReader
from bgvoice.storage_records import ExtractionRunRecord

_MOD_FOLDER = "bgvoice"
_SETUP_EXE = "setup-bgvoice.exe"
_SETUP_TP2 = "setup-bgvoice.tp2"
_RESOURCE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_RESOURCE_CAPACITY = len(_RESOURCE_ALPHABET) ** 5


class ModExportSummary(BaseModel):
    """Reviewable result of one complete mod export."""

    model_config = ConfigDict(strict=True, extra="forbid")

    output: str = Field(min_length=1)
    source_game: str = Field(min_length=1)
    generated_lines: int = Field(gt=0)
    audio_files: int = Field(gt=0)
    dialogue_files: int = Field(gt=0)
    audio_bytes: int = Field(gt=0)


class _ExportLine(LanceModel):
    id: str
    run_id: str
    dialogue_resource_name: str
    line_kind: DialogueLineKind = Field(strict=False)
    state_index: int
    text: str | None


class _ExportRecording(LanceModel):
    id: str
    voice_id: str
    dialogue_line_id: str


class _AudioPayload(LanceModel):
    id: str
    audio: bytes


@dataclass(frozen=True, slots=True)
class _ContentAsset:
    dialogue_resource_name: str
    run_id: str
    text: str
    recording_id: str
    sound_resref: str


def sound_resref(index: int) -> str:
    """Return the collision-free eight-character resource name for an export row."""
    assert 0 <= index < _RESOURCE_CAPACITY, (
        f"BGVoice supports at most {_RESOURCE_CAPACITY:,} recordings per mod"
    )
    encoded = ""
    value = index
    for _ in range(5):
        value, digit = divmod(value, len(_RESOURCE_ALPHABET))
        encoded = _RESOURCE_ALPHABET[digit] + encoded
    return f"BGV{encoded}"


def create_archive(output: Path, archive: Path) -> int:
    """Create and CRC-check a root-layout, Zip64 release archive."""
    assert not archive.exists(), f"archive already exists: {archive}"
    assert not archive.resolve().is_relative_to(output.resolve()), (
        "archive cannot be created inside the exported mod"
    )
    files = sorted(path for path in output.rglob("*") if path.is_file())
    archive.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive, "x", compression=ZIP_STORED, allowZip64=True) as package:
        for path in files:
            package.write(path, path.relative_to(output).as_posix())
    with ZipFile(archive) as package:
        assert package.testzip() is None, "release archive failed its CRC check"
    return len(files)


async def export_mod(
    database: Path,
    output: Path,
    *,
    version: str = "1.0.0",
) -> ModExportSummary:
    """Build an installable, content-matched EET mod from generated audio."""
    assert version and "~" not in version, "mod version cannot be empty or contain '~'"
    reader = await PipelineReader.open(database)
    try:
        recordings, lines, runs = await asyncio.gather(
            reader.generated_audio_table.query()
            .select(["id", "voice_id", "dialogue_line_id"])
            .to_pydantic(_ExportRecording),
            reader.lines_table.query()
            .select(
                [
                    "id",
                    "run_id",
                    "dialogue_resource_name",
                    "line_kind",
                    "state_index",
                    "text",
                ]
            )
            .to_pydantic(_ExportLine),
            reader.runs_table.query().to_pydantic(ExtractionRunRecord),
        )
        assets, source_game = _content_assets(
            cast(list[_ExportRecording], recordings),
            cast(list[_ExportLine], lines),
            cast(list[ExtractionRunRecord], runs),
        )
        return await _write_mod(
            reader.generated_audio_table,
            output,
            source_game,
            assets,
            len(recordings),
            version,
        )
    finally:
        reader.close()


def _content_assets(
    recordings: list[_ExportRecording],
    lines: list[_ExportLine],
    runs: list[ExtractionRunRecord],
) -> tuple[list[_ContentAsset], Path]:
    assert recordings, "pipeline database has no generated audio to export"
    wanted = {record.dialogue_line_id for record in recordings}
    by_id = {line.id: line for line in lines if line.id in wanted}
    missing = wanted - by_id.keys()
    assert not missing, f"generated audio references missing dialogue lines: {sorted(missing)[:5]}"

    candidates: list[tuple[_ExportLine, _ExportRecording]] = []
    for recording in recordings:
        line = by_id[recording.dialogue_line_id]
        assert line.line_kind is DialogueLineKind.NPC, (
            f"generated audio {recording.id} targets unsupported {line.line_kind.value} text"
        )
        assert line.text, f"generated audio {recording.id} targets unresolved dialogue text"
        candidates.append((line, recording))

    candidates.sort(
        key=lambda candidate: (
            candidate[0].dialogue_resource_name.casefold(),
            candidate[0].text,
            candidate[0].state_index,
            candidate[1].voice_id,
            candidate[1].id,
        )
    )
    assets: list[_ContentAsset] = []
    content_keys: set[tuple[str, str]] = set()
    for line, recording in candidates:
        assert line.text is not None
        key = (line.dialogue_resource_name.casefold(), line.text)
        if key in content_keys:
            continue
        content_keys.add(key)
        assets.append(
            _ContentAsset(
                dialogue_resource_name=line.dialogue_resource_name,
                run_id=line.run_id,
                text=line.text,
                recording_id=recording.id,
                sound_resref=sound_resref(len(assets)),
            )
        )

    runs_by_id = {run.id: run for run in runs}
    missing_runs = {asset.run_id for asset in assets} - runs_by_id.keys()
    assert not missing_runs, f"dialogue lines reference missing runs: {sorted(missing_runs)}"
    source_games = {
        Path(runs_by_id[asset.run_id].game_root).expanduser().resolve() for asset in assets
    }
    assert len(source_games) == 1, "one mod export cannot mix dialogue lines from multiple games"
    source_game = source_games.pop()
    assert source_game.is_dir(), f"source EET installation does not exist: {source_game}"
    return assets, source_game


async def _write_mod(
    audio_table: AsyncTable,
    output: Path,
    source_game: Path,
    assets: list[_ContentAsset],
    generated_lines: int,
    version: str,
) -> ModExportSummary:
    destination = output.expanduser().absolute()
    _validate_destination(destination)
    installer = source_game / "setup-eet.exe"
    assert installer.is_file(), f"WeiDU installer does not exist: {installer}"
    destination.parent.mkdir(parents=True, exist_ok=True)

    grouped: dict[str, list[_ContentAsset]] = defaultdict(list)
    for asset in assets:
        grouped[asset.dialogue_resource_name].append(asset)
    aliases = _dialogue_aliases(source_game)

    with tempfile.TemporaryDirectory(
        dir=destination.parent,
        prefix=f".{destination.name}-",
    ) as temporary:
        root = Path(temporary) / destination.name
        audio = root / _MOD_FOLDER / "audio"
        dialogues = root / _MOD_FOLDER / "dialogue"
        library = root / _MOD_FOLDER / "lib"
        audio.mkdir(parents=True)
        dialogues.mkdir()
        library.mkdir()

        shutil.copy2(installer, root / _SETUP_EXE)
        (root / _SETUP_TP2).write_text(_tp2(version), encoding="utf-8", newline="\n")
        (library / "install.tpa").write_text(_INSTALL_TPA, encoding="utf-8", newline="\n")
        for index, (resource_name, rows) in enumerate(
            sorted(grouped.items(), key=lambda item: item[0].casefold())
        ):
            (dialogues / f"{index:06d}.tpa").write_text(
                _dialogue_patch(
                    (resource_name, *aliases.get(resource_name.casefold(), ())),
                    rows,
                    f"bgv_catalog_{index:06d}",
                ),
                encoding="utf-8",
                newline="\n",
            )

        audio_bytes = await _write_audio(audio_table, audio, assets)
        (root / _MOD_FOLDER / "README.md").write_text(
            _readme(assets, generated_lines, len(grouped), audio_bytes, version),
            encoding="utf-8",
            newline="\n",
        )
        await asyncio.to_thread(_publish_mod, root, destination)

    return ModExportSummary(
        output=str(destination),
        source_game=str(source_game),
        generated_lines=generated_lines,
        audio_files=len(assets),
        dialogue_files=len(grouped),
        audio_bytes=audio_bytes,
    )


def _validate_destination(destination: Path) -> None:
    assert destination != Path(destination.anchor), "mod output cannot be a filesystem root"
    assert not destination.is_symlink(), "mod output cannot be a symbolic link"
    if not destination.exists():
        return
    assert destination.is_dir(), f"mod output exists and is not a directory: {destination}"
    entries = {entry.name.casefold() for entry in destination.iterdir()}
    expected = {_SETUP_EXE, _SETUP_TP2, _MOD_FOLDER}
    assert not entries or entries == expected, (
        f"refusing to replace a directory that is not a BGVoice export: {destination}"
    )


async def _write_audio(
    table: AsyncTable,
    destination: Path,
    assets: list[_ContentAsset],
) -> int:
    resources = {asset.recording_id: asset.sound_resref for asset in assets}
    written: set[str] = set()
    audio_bytes = 0
    batches = await table.query().select(["id", "audio"]).to_batches(max_batch_length=64)
    async for batch in batches:
        payloads = [_AudioPayload.model_validate(row) for row in batch.to_pylist()]
        selected = [payload for payload in payloads if payload.id in resources]
        if selected:
            audio_bytes += await asyncio.to_thread(
                _write_audio_batch,
                destination,
                selected,
                resources,
            )
            written.update(payload.id for payload in selected)
    missing = resources.keys() - written
    assert not missing, f"generated audio rows disappeared during export: {sorted(missing)[:5]}"
    return audio_bytes


def _write_audio_batch(
    destination: Path,
    payloads: list[_AudioPayload],
    resources: dict[str, str],
) -> int:
    for payload in payloads:
        (destination / f"{resources[payload.id]}.wav").write_bytes(payload.audio)
    return sum(len(payload.audio) for payload in payloads)


def _publish_mod(root: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    root.replace(destination)


def _dialogue_aliases(source_game: Path) -> dict[str, tuple[str, ...]]:
    """Read the source DLGs that EET_end merged into each final DLG."""
    aliases: dict[str, set[str]] = {}
    for source in sorted((source_game / "EET" / "temp" / "append" / "dlg").glob("*.d")):
        with source.open(encoding="utf-8") as dialogue:
            declaration = dialogue.readline().strip()
        assert declaration.startswith("APPEND ~") and declaration.endswith("~"), (
            f"unexpected EET dialogue merge declaration: {source}"
        )
        target = f"{declaration.removeprefix('APPEND ~').removesuffix('~')}.DLG"
        aliases.setdefault(target.casefold(), set()).add(f"{source.stem}.DLG")
    return {target: tuple(sorted(sources, key=str.casefold)) for target, sources in aliases.items()}


def _dialogue_patch(
    resource_names: tuple[str, ...],
    assets: list[_ContentAsset],
    catalog: str,
) -> str:
    entries = "\n".join(
        f"OUTER_SPRINT bgv_key {_weidu_string(asset.text)}\n"
        f'OUTER_SPRINT ${catalog}("%bgv_key%") ~{asset.sound_resref}~'
        for asset in assets
    )
    dialogues = " ".join(f"~{resource_name}~" for resource_name in resource_names)
    return f"""{entries}

ACTION_FOR_EACH bgv_dialogue IN {dialogues} BEGIN
  COPY_EXISTING ~%bgv_dialogue%~ ~override~
    READ_LONG 0x08 bgv_state_count
    READ_LONG 0x0c bgv_state_table
    FOR (bgv_state = 0; bgv_state < bgv_state_count; ++bgv_state) BEGIN
      SET bgv_text_offset = bgv_state_table + bgv_state * 0x10
      READ_STRREF bgv_text_offset bgv_text
      PATCH_IF (VARIABLE_IS_SET ${catalog}(~%bgv_text%~)) BEGIN
        TEXT_SPRINT bgv_sound ${catalog}(~%bgv_text%~)
        LPF BGVOICE_INSTALL_LINE
          INT_VAR text_offset = bgv_text_offset
          STR_VAR sound = EVAL ~%bgv_sound%~
        END
      END
    END
  BUT_ONLY_IF_IT_CHANGES
  IF_EXISTS
END
"""


def _weidu_string(value: str) -> str:
    assert "~~~~~" not in value, "dialogue text contains WeiDU's long-string delimiter"
    return f"~~~~~{value}~~~~~"


def _readme(
    assets: list[_ContentAsset],
    generated_lines: int,
    dialogue_count: int,
    audio_bytes: int,
    version: str,
) -> str:
    return f"""# BGVoice EET dialogue audio

Version {version}.

This export contains {len(assets):,} canonical recordings covering
{generated_lines:,} generated NPC lines across {dialogue_count:,} DLG resources
({audio_bytes:,} bytes).

## Install

1. Install every dialogue/content mod you want.
2. Copy this export's entire contents into the EET game directory.
3. Run `setup-bgvoice.exe` and choose exactly one audio policy.
4. Install `EET_end` if the EET installation has not yet been finalized.

The default **replace all exported audio** policy uses generated audio on every
matched dialogue occurrence. The alternative **fill missing audio** policy patches
only lines whose male and female sound assignments are both empty.

The installer matches the current game by DLG resource name and exact resolved
English text. State numbering and TLK string references may differ from the source
installation. Missing DLG resources and unmatched or changed text are skipped.
Repeated identical text within one DLG shares one canonical recording. WeiDU
manages backups and uninstallation. Installing before `EET_end` is preferred: the
export also scans every source DLG that the source installation's `EET_end` merged.
An already-finalized EET installation can instead install BGVoice directly. If you
later change earlier mods, uninstall later components in reverse order and reinstall
them in their original order.
"""


def _tp2(version: str) -> str:
    return f"""BACKUP ~bgvoice/backup~
SUPPORT ~BGVoice project~
VERSION ~{version}~
README ~bgvoice/README.md~

BEGIN ~Replace audio on every exported dialogue occurrence~
SUBCOMPONENT ~BGVoice EET dialogue audio policy~
DESIGNATED 0
LABEL ~replace-exported-audio~
REQUIRE_PREDICATE GAME_IS ~eet~ ~BGVoice requires an EET installation.~
REQUIRE_PREDICATE (~%EE_LANGUAGE%~ STRING_EQUAL_CASE ~en_US~) ~This BGVoice export requires the en_US game language.~
OUTER_SET bgv_replace = 1
INCLUDE ~bgvoice/lib/install.tpa~

BEGIN ~Fill only dialogue occurrences without assigned audio~
SUBCOMPONENT ~BGVoice EET dialogue audio policy~
DESIGNATED 1
LABEL ~fill-missing-audio~
REQUIRE_PREDICATE GAME_IS ~eet~ ~BGVoice requires an EET installation.~
REQUIRE_PREDICATE (~%EE_LANGUAGE%~ STRING_EQUAL_CASE ~en_US~) ~This BGVoice export requires the en_US game language.~
OUTER_SET bgv_replace = 0
INCLUDE ~bgvoice/lib/install.tpa~
"""


_INSTALL_TPA = r"""DEFINE_PATCH_FUNCTION BGVOICE_INSTALL_LINE
INT_VAR
  text_offset = 0
STR_VAR
  sound = ~~
BEGIN
  READ_STRREF text_offset bgv_male_text
  READ_STRREF_F text_offset bgv_female_text
  READ_STRREF_S text_offset bgv_male_sound
  READ_STRREF_FS text_offset bgv_female_sound
  SET bgv_install = bgv_replace OR (
    (~%bgv_male_sound%~ STRING_EQUAL_CASE ~~) AND
    (~%bgv_female_sound%~ STRING_EQUAL_CASE ~~)
  )

  PATCH_IF bgv_install BEGIN
    SAY text_offset ~%bgv_male_text%~ [%sound%] ~%bgv_female_text%~ [%sound%]
    INNER_ACTION BEGIN
      COPY ~bgvoice/audio/%sound%.wav~ ~override/%sound%.wav~
    END
  END
END

ACTION_BASH_FOR ~bgvoice/dialogue~ ~.*\.tpa$~ BEGIN
  ACTION_INCLUDE ~%BASH_FOR_FILESPEC%~
END
"""
