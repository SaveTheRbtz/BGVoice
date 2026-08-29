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
from bgvoice.storage_records import ExtractionRunRecord, VoiceResourceRecord

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
    voice_catalogs: int = Field(gt=0)
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
    voice_id: str
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
        recordings, lines, runs, attribution = await asyncio.gather(
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
            reader.attribution_snapshot(),
        )
        assets, source_game = _content_assets(
            cast(list[_ExportRecording], recordings),
            cast(list[_ExportLine], lines),
            cast(list[ExtractionRunRecord], runs),
            attribution.voices,
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
    voices: list[VoiceResourceRecord],
) -> tuple[list[_ContentAsset], Path]:
    assert recordings, "pipeline database has no generated audio to export"
    wanted = {record.dialogue_line_id for record in recordings}
    by_id = {line.id: line for line in lines if line.id in wanted}
    missing = wanted - by_id.keys()
    assert not missing, f"generated audio references missing dialogue lines: {sorted(missing)[:5]}"

    voices_by_id = {voice.voice_id: voice for voice in voices}
    missing_voices = {record.voice_id for record in recordings} - voices_by_id.keys()
    assert not missing_voices, (
        f"generated audio references missing voices: {sorted(missing_voices)[:5]}"
    )
    for voice in voices_by_id.values():
        assert voice.voice_id == voice.display_name.casefold(), (
            f"voice id must be the normalized display name: {voice.voice_id!r}"
        )

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
            candidate[1].voice_id,
            candidate[0].text,
            candidate[0].dialogue_resource_name.casefold(),
            candidate[0].state_index,
            candidate[1].id,
        )
    )
    assets: list[_ContentAsset] = []
    content_keys: set[tuple[str, str]] = set()
    for line, recording in candidates:
        assert line.text is not None
        key = (recording.voice_id, line.text)
        if key in content_keys:
            continue
        content_keys.add(key)
        assets.append(
            _ContentAsset(
                voice_id=recording.voice_id,
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
        grouped[asset.voice_id].append(asset)

    with tempfile.TemporaryDirectory(
        dir=destination.parent,
        prefix=f".{destination.name}-",
    ) as temporary:
        root = Path(temporary) / destination.name
        audio = root / _MOD_FOLDER / "audio"
        catalogs = root / _MOD_FOLDER / "catalog"
        library = root / _MOD_FOLDER / "lib"
        audio.mkdir(parents=True)
        catalogs.mkdir()
        library.mkdir()

        shutil.copy2(installer, root / _SETUP_EXE)
        (root / _SETUP_TP2).write_text(_tp2(version), encoding="utf-8", newline="\n")
        (library / "install.tpa").write_text(_INSTALL_TPA, encoding="utf-8", newline="\n")
        for index, (voice_id, rows) in enumerate(
            sorted(grouped.items(), key=lambda item: item[0].casefold())
        ):
            (catalogs / f"{index:06d}.tpa").write_text(
                _voice_catalog(voice_id, rows, f"{index:06d}"),
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
        voice_catalogs=len(grouped),
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


def _voice_catalog(
    voice_id: str,
    assets: list[_ContentAsset],
    catalog: str,
) -> str:
    entries = "\n".join(
        f"OUTER_SPRINT bgv_key {_weidu_string(asset.text)}\n"
        f'OUTER_SPRINT $bgv_recordings(~{catalog}~ "%bgv_key%") ~{asset.sound_resref}~\n'
        "OUTER_SET bgv_packaged_recordings += 1"
        for asset in assets
    )
    return f"""OUTER_SPRINT bgv_voice {_weidu_string(voice_id)}
OUTER_SPRINT $bgv_catalog_by_name("%bgv_voice%") ~{catalog}~
OUTER_SET bgv_packaged_voices += 1
{entries}
"""


def _weidu_string(value: str) -> str:
    assert "~~~~~" not in value, "dialogue text contains WeiDU's long-string delimiter"
    return f"~~~~~{value}~~~~~"


def _readme(
    assets: list[_ContentAsset],
    generated_lines: int,
    voice_catalog_count: int,
    audio_bytes: int,
    version: str,
) -> str:
    return f"""# BGVoice EET dialogue audio

Version {version}.

This export contains {len(assets):,} canonical recordings covering
{generated_lines:,} generated NPC lines for {voice_catalog_count:,} character voices
({audio_bytes:,} bytes).

## Install

1. Install every dialogue/content mod you want.
2. Copy this export's entire contents into the EET game directory.
3. Run `setup-bgvoice.exe` and install BGVoice.
4. Install `EET_end` if the EET installation has not yet been finalized.

BGVoice replaces the audio on every matched dialogue occurrence.

The installer discovers character dialogue ownership from the target game's CRE,
CAMPAIGN, INTERDIA, and PDIALOG resources. It patches only an exact character-name
and resolved-English-text intersection, so DLG names, state numbers, TLK string
references, EET versions, and installed content mods may differ from the source.
Missing characters, resources, and changed text are skipped. If one DLG/text could
belong to different character voices, that occurrence is left unchanged rather than
guessing. WeiDU prints aggregate coverage totals and manages backups and
uninstallation. BGVoice works both before and after `EET_end`; installing before it
lets `EET_end` carry patched source dialogue strings into its final merges. If you
later change earlier mods, uninstall later components in reverse order and reinstall
them in their original order.
"""


def _tp2(version: str) -> str:
    return f"""BACKUP ~bgvoice/backup~
SUPPORT ~BGVoice project~
VERSION ~{version}~
README ~bgvoice/README.md~

BEGIN ~Install generated dialogue audio~
DESIGNATED 0
LABEL ~install-generated-audio~
REQUIRE_PREDICATE GAME_IS ~eet~ ~BGVoice requires an EET installation.~
REQUIRE_PREDICATE (~%EE_LANGUAGE%~ STRING_EQUAL_CASE ~en_US~) ~This BGVoice export requires the en_US game language.~
INCLUDE ~bgvoice/lib/install.tpa~
"""


_INSTALL_TPA = r"""DEFINE_PATCH_FUNCTION BGVOICE_PAD_2DA
INT_VAR
  columns = 0
BEGIN
  PRETTY_PRINT_2DA
  SET bgv_line = 0
  REPLACE_EVALUATE ~^.+$~ BEGIN
    PATCH_IF bgv_line > 2 BEGIN
      INNER_PATCH_SAVE MATCH0 ~%MATCH0%~ BEGIN
        COUNT_REGEXP_INSTANCES ~[^ %TAB%%MNL%]+~ bgv_fields
        FOR (bgv_column = bgv_fields; bgv_column < columns; ++bgv_column) BEGIN
          REPLACE_TEXTUALLY ~$~ ~ ***~
        END
      END
    END
    SET bgv_line += 1
  END ~%MATCH0%~
END

DEFINE_PATCH_FUNCTION BGVOICE_ADD_OWNER
STR_VAR
  dialogue = ~~
  catalog = ~~
RET_ARRAY
  bgv_dialogue_owners
BEGIN
  TO_UPPER dialogue
  PATCH_IF (NOT ~%dialogue%~ STRING_EQUAL_CASE ~~)
        AND (NOT ~%dialogue%~ STRING_EQUAL_CASE ~NONE~)
        AND (NOT ~%dialogue%~ STRING_EQUAL_CASE ~***~)
        AND (FILE_EXISTS_IN_GAME ~%dialogue%.DLG~) BEGIN
    TEXT_SPRINT $bgv_dialogue_owners(~%dialogue%~ ~%catalog%~) ~1~
  END
END

DEFINE_PATCH_FUNCTION BGVOICE_ADD_DV_DIALOGUE
STR_VAR
  death_variable = ~~
  dialogue = ~~
RET_ARRAY
  bgv_dialogue_owners
BEGIN
  TO_UPPER death_variable
  PATCH_IF (~%death_variable%~ STRING_EQUAL_CASE ~IMOEN~)
        OR (~%death_variable%~ STRING_EQUAL_CASE ~IMOEN_~) BEGIN
    TEXT_SPRINT death_variable ~IMOEN2~
  END
  PATCH_PHP_EACH bgv_catalogs_by_dv AS bgv_owner => bgv_unused BEGIN
    PATCH_IF ~%bgv_owner_0%~ STRING_EQUAL_CASE ~%death_variable%~ BEGIN
      LPF BGVOICE_ADD_OWNER
        STR_VAR dialogue = EVAL ~%dialogue%~ catalog = EVAL ~%bgv_owner_1%~
        RET_ARRAY bgv_dialogue_owners
      END
    END
  END
END

DEFINE_PATCH_FUNCTION BGVOICE_INSTALL_LINE
INT_VAR
  text_offset = 0
STR_VAR
  sound = ~~
BEGIN
  READ_STRREF text_offset bgv_male_text
  READ_STRREF_F text_offset bgv_female_text
  SAY text_offset ~%bgv_male_text%~ [%sound%] ~%bgv_female_text%~ [%sound%]
END

OUTER_SET bgv_packaged_voices = 0
OUTER_SET bgv_packaged_recordings = 0
OUTER_SET bgv_states_scanned = 0
OUTER_SET bgv_exact_patches = 0
OUTER_SET bgv_ambiguous_states = 0

ACTION_BASH_FOR ~bgvoice/catalog~ ~.*\.tpa$~ BEGIN
  ACTION_INCLUDE ~%BASH_FOR_FILESPEC%~
END

COPY_EXISTING_REGEXP GLOB ~.+\.CRE$~ ~override~
  PATCH_IF SOURCE_SIZE >= 0x2d4 BEGIN
    READ_ASCII 0x00 bgv_signature (4)
    READ_ASCII 0x04 bgv_version (4)
    PATCH_IF (~%bgv_signature%~ STRING_EQUAL_CASE ~CRE ~)
          AND (~%bgv_version%~ STRING_EQUAL_CASE ~V1.0~) BEGIN
      READ_LONG 0x0c bgv_name_strref
      TEXT_SPRINT bgv_name ~~
      PATCH_IF bgv_name_strref != 0xffffffff BEGIN
        READ_STRREF 0x0c bgv_name
      END
      PATCH_IF ~%bgv_name%~ STRING_EQUAL_CASE ~~ BEGIN
        READ_LONG 0x08 bgv_name_strref
        PATCH_IF bgv_name_strref != 0xffffffff BEGIN
          READ_STRREF 0x08 bgv_name
        END
      END
      PATCH_IF ~%bgv_name%~ STRING_EQUAL_CASE ~~ BEGIN
        TEXT_SPRINT bgv_name ~%SOURCE_RES%~
      END
      INNER_PATCH_SAVE bgv_name ~%bgv_name%~ BEGIN
        REPLACE_TEXTUALLY CASE_INSENSITIVE EVALUATE_REGEXP ~^0x[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]~ ~~
        REPLACE_TEXTUALLY CASE_SENSITIVE EVALUATE_REGEXP ~^-~ ~~
        REPLACE_TEXTUALLY CASE_SENSITIVE EVALUATE_REGEXP ~^[ %TAB%]+~ ~~
        REPLACE_TEXTUALLY CASE_SENSITIVE EVALUATE_REGEXP ~[ %TAB%]+$~ ~~
      END
      TO_LOWER bgv_name
      PATCH_IF VARIABLE_IS_SET $bgv_catalog_by_name(~%bgv_name%~) BEGIN
        TEXT_SPRINT bgv_catalog $bgv_catalog_by_name(~%bgv_name%~)
        TEXT_SPRINT $bgv_target_names(~%bgv_name%~) ~1~
        READ_ASCII 0x280 bgv_death_variable (32) NULL
        READ_ASCII 0x2cc bgv_dialogue (8) NULL
        TO_UPPER bgv_death_variable
        PATCH_IF (~%bgv_death_variable%~ STRING_EQUAL_CASE ~IMOEN~)
              OR (~%bgv_death_variable%~ STRING_EQUAL_CASE ~IMOEN_~) BEGIN
          TEXT_SPRINT bgv_death_variable ~IMOEN2~
        END
        PATCH_IF (NOT ~%bgv_death_variable%~ STRING_EQUAL_CASE ~~)
              AND (NOT ~%bgv_death_variable%~ STRING_EQUAL_CASE ~NONE~) BEGIN
          TEXT_SPRINT $bgv_catalogs_by_dv(~%bgv_death_variable%~ ~%bgv_catalog%~) ~1~
        END
        LPF BGVOICE_ADD_OWNER
          STR_VAR dialogue = EVAL ~%bgv_dialogue%~ catalog = EVAL ~%bgv_catalog%~
          RET_ARRAY bgv_dialogue_owners
        END
      END
    END
  END
BUT_ONLY

COPY_EXISTING - ~CAMPAIGN.2DA~ ~.../bgvoice-campaign.2da~
  READ_2DA_ENTRIES_NOW bgv_campaigns 32
  FOR (bgv_row = 0; bgv_row < bgv_campaigns; ++bgv_row) BEGIN
    READ_2DA_ENTRY_FORMER bgv_campaigns bgv_row 4 bgv_table
    TO_UPPER bgv_table
    PATCH_IF FILE_EXISTS_IN_GAME ~%bgv_table%.2DA~ BEGIN
      TEXT_SPRINT $bgv_banter_tables(~%bgv_table%~) ~1~
    END
    READ_2DA_ENTRY_FORMER bgv_campaigns bgv_row 11 bgv_table
    TO_UPPER bgv_table
    PATCH_IF FILE_EXISTS_IN_GAME ~%bgv_table%.2DA~ BEGIN
      TEXT_SPRINT $bgv_party_tables(~%bgv_table%~) ~1~
    END
  END

ACTION_PHP_EACH bgv_banter_tables AS bgv_table => bgv_unused BEGIN
  COPY_EXISTING - ~%bgv_table%.2DA~ ~.../bgvoice-banter.2da~
    COUNT_2DA_COLS bgv_columns
    LPF BGVOICE_PAD_2DA INT_VAR columns = bgv_columns END
    COUNT_2DA_ROWS bgv_columns bgv_rows
    FOR (bgv_row = 0; bgv_row < bgv_rows; ++bgv_row) BEGIN
      READ_2DA_ENTRY bgv_row 0 bgv_columns bgv_death_variable
      READ_2DA_ENTRY bgv_row 1 bgv_columns bgv_dialogue
      LPF BGVOICE_ADD_DV_DIALOGUE
        STR_VAR death_variable = EVAL ~%bgv_death_variable%~ dialogue = EVAL ~%bgv_dialogue%~
        RET_ARRAY bgv_dialogue_owners
      END
      PATCH_IF bgv_columns > 2 BEGIN
        READ_2DA_ENTRY bgv_row 2 bgv_columns bgv_dialogue
        LPF BGVOICE_ADD_DV_DIALOGUE
          STR_VAR death_variable = EVAL ~%bgv_death_variable%~ dialogue = EVAL ~%bgv_dialogue%~
          RET_ARRAY bgv_dialogue_owners
        END
      END
    END
END

ACTION_PHP_EACH bgv_party_tables AS bgv_table => bgv_unused BEGIN
  COPY_EXISTING - ~%bgv_table%.2DA~ ~.../bgvoice-party.2da~
    COUNT_2DA_COLS bgv_columns
    LPF BGVOICE_PAD_2DA INT_VAR columns = bgv_columns END
    COUNT_2DA_ROWS bgv_columns bgv_rows
    FOR (bgv_row = 0; bgv_row < bgv_rows; ++bgv_row) BEGIN
      READ_2DA_ENTRY bgv_row 0 bgv_columns bgv_death_variable
      READ_2DA_ENTRY bgv_row 1 bgv_columns bgv_dialogue
      LPF BGVOICE_ADD_DV_DIALOGUE
        STR_VAR death_variable = EVAL ~%bgv_death_variable%~ dialogue = EVAL ~%bgv_dialogue%~
        RET_ARRAY bgv_dialogue_owners
      END
      READ_2DA_ENTRY bgv_row 2 bgv_columns bgv_dialogue
      LPF BGVOICE_ADD_DV_DIALOGUE
        STR_VAR death_variable = EVAL ~%bgv_death_variable%~ dialogue = EVAL ~%bgv_dialogue%~
        RET_ARRAY bgv_dialogue_owners
      END
      PATCH_IF bgv_columns > 5 BEGIN
        READ_2DA_ENTRY bgv_row 4 bgv_columns bgv_dialogue
        LPF BGVOICE_ADD_DV_DIALOGUE
          STR_VAR death_variable = EVAL ~%bgv_death_variable%~ dialogue = EVAL ~%bgv_dialogue%~
          RET_ARRAY bgv_dialogue_owners
        END
        READ_2DA_ENTRY bgv_row 5 bgv_columns bgv_dialogue
        LPF BGVOICE_ADD_DV_DIALOGUE
          STR_VAR death_variable = EVAL ~%bgv_death_variable%~ dialogue = EVAL ~%bgv_dialogue%~
          RET_ARRAY bgv_dialogue_owners
        END
      END
    END
END

// Target-version Imoen aliases that EET keeps outside CAMPAIGN's dialogue tables.
ACTION_IF FILE_EXISTS ~EET_end/lib/tables.tph~ BEGIN
  ACTION_INCLUDE ~EET_end/lib/tables.tph~
  ACTION_PHP_EACH table_append_dlg AS bgv_source => bgv_unused BEGIN
    ACTION_IF NOT ~%bgv_source_1%~ STRING_EQUAL_CASE ~~ BEGIN
      ACTION_PHP_EACH bgv_dialogue_owners AS bgv_owner => bgv_owner_unused BEGIN
        ACTION_IF ~%bgv_owner_0%~ STRING_EQUAL_CASE ~%bgv_source_1%~ BEGIN
          OUTER_SPRINT $bgv_seed_owners(~%bgv_source%~ ~%bgv_owner_1%~) ~1~
        END
      END
    END
  END
  ACTION_PHP_EACH bgv_seed_owners AS bgv_owner => bgv_owner_unused BEGIN
    ACTION_IF FILE_EXISTS_IN_GAME ~%bgv_owner_0%.DLG~ BEGIN
      OUTER_SPRINT $bgv_dialogue_owners(~%bgv_owner_0%~ ~%bgv_owner_1%~) ~1~
    END
  END
END

OUTER_SET bgv_target_voice_count = 0
ACTION_PHP_EACH bgv_target_names AS bgv_name => bgv_unused BEGIN
  OUTER_SET bgv_target_voice_count += 1
END

OUTER_SET bgv_dialogue_count = 0
ACTION_PHP_EACH bgv_dialogue_owners AS bgv_owner => bgv_owner_unused BEGIN
  ACTION_IF NOT VARIABLE_IS_SET $bgv_dialogue_ids(~%bgv_owner_0%~) BEGIN
    OUTER_SET bgv_dialogue_count += 1
    OUTER_SPRINT $bgv_dialogue_ids(~%bgv_owner_0%~) ~%bgv_dialogue_count%~
  END
  OUTER_SPRINT bgv_dialogue_id $bgv_dialogue_ids(~%bgv_owner_0%~)
  OUTER_SPRINT bgv_owner_array ~bgv_owners_%bgv_dialogue_id%~
  OUTER_SPRINT $EVAL ~%bgv_owner_array%~(~%bgv_owner_1%~) ~1~
END

OUTER_SET bgv_shared_dialogues = 0
ACTION_PHP_EACH bgv_dialogue_ids AS bgv_dialogue => bgv_dialogue_id BEGIN
  OUTER_SPRINT bgv_owner_array ~bgv_owners_%bgv_dialogue_id%~
  OUTER_SET bgv_owner_count = 0
  ACTION_PHP_EACH ~%bgv_owner_array%~ AS bgv_catalog => bgv_owner_unused BEGIN
    OUTER_SET bgv_owner_count += 1
  END
  ACTION_IF bgv_owner_count > 1 BEGIN
    OUTER_SET bgv_shared_dialogues += 1
  END

  COPY_EXISTING ~%bgv_dialogue%.DLG~ ~override~
    READ_LONG 0x08 bgv_state_count
    READ_LONG 0x0c bgv_state_table
    SET bgv_states_scanned += bgv_state_count
    FOR (bgv_state = 0; bgv_state < bgv_state_count; ++bgv_state) BEGIN
      SET bgv_text_offset = bgv_state_table + bgv_state * 0x10
      READ_STRREF bgv_text_offset bgv_text
      SET bgv_candidate_count = 0
      TEXT_SPRINT bgv_candidate_sound ~~
      PHP_EACH EVAL ~%bgv_owner_array%~ AS bgv_catalog => bgv_owner_unused BEGIN
        PATCH_IF VARIABLE_IS_SET $bgv_recordings(~%bgv_catalog%~ ~%bgv_text%~) BEGIN
          TEXT_SPRINT bgv_sound $bgv_recordings(~%bgv_catalog%~ ~%bgv_text%~)
          PATCH_IF bgv_candidate_count = 0 BEGIN
            TEXT_SPRINT bgv_candidate_sound ~%bgv_sound%~
            SET bgv_candidate_count = 1
          END ELSE PATCH_IF NOT ~%bgv_candidate_sound%~ STRING_EQUAL_CASE ~%bgv_sound%~ BEGIN
            SET bgv_candidate_count = 2
          END
        END
      END
      PATCH_IF bgv_candidate_count = 1 BEGIN
        LPF BGVOICE_INSTALL_LINE
          INT_VAR text_offset = bgv_text_offset
          STR_VAR sound = EVAL ~%bgv_candidate_sound%~
        END
        TEXT_SPRINT $bgv_used_recordings(~%bgv_candidate_sound%~) ~1~
        SET bgv_exact_patches += 1
      END ELSE PATCH_IF bgv_candidate_count > 1 BEGIN
        SET bgv_ambiguous_states += 1
      END
    END
  BUT_ONLY_IF_IT_CHANGES
END

OUTER_SET bgv_used_recording_count = 0
ACTION_PHP_EACH bgv_used_recordings AS bgv_sound => bgv_unused BEGIN
  COPY ~bgvoice/audio/%bgv_sound%.wav~ ~override/%bgv_sound%.wav~
  OUTER_SET bgv_used_recording_count += 1
END

PRINT ~BGVoice coverage: %bgv_target_voice_count%/%bgv_packaged_voices% target voices; %bgv_dialogue_count% DLGs (%bgv_shared_dialogues% shared); %bgv_states_scanned% states scanned.~
PRINT ~BGVoice installed %bgv_exact_patches% exact dialogue occurrences using %bgv_used_recording_count%/%bgv_packaged_recordings% recordings; skipped %bgv_ambiguous_states% ambiguous occurrences.~
"""
