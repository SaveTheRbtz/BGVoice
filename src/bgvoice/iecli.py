"""Typed access to the bundled ``iecli`` executable."""

import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter

from bgvoice.models import (
    CreDump,
    CreResource,
    DlgDump,
    DlgResource,
    StringReference,
)

_CRE_RESOURCES = TypeAdapter(list[CreResource])
_DLG_RESOURCES = TypeAdapter(list[DlgResource])
_LOCAL_IECLI = Path(".tools/iecli/v0.3.0-rc.1/iecli.exe")


class CharacterIeCliClient(Protocol):
    """The ie-cli operations used by character extraction."""

    def version(self) -> str: ...

    def list_creatures(self, game_root: Path) -> list[CreResource]: ...

    def dump_creature(self, game_root: Path, resource_name: str) -> CreDump: ...


class DialogueIeCliClient(Protocol):
    """The ie-cli operations used by dialogue extraction."""

    def version(self) -> str: ...

    def list_dialogues(self, game_root: Path) -> list[DlgResource]: ...

    def dump_dialogue(self, game_root: Path, resource_name: str) -> DlgDump: ...


class MetadataIeCliClient(Protocol):
    """The read-only ie-cli operations used by metadata extraction."""

    def version(self) -> str: ...

    def read_text_resource(self, game_root: Path, resource_name: str) -> str: ...

    def resolve_string(self, game_root: Path, strref: int) -> StringReference: ...


class IeCli:
    """Run ie-cli and validate its JSON output."""

    def __init__(
        self,
        executable: Path = _LOCAL_IECLI,
        *,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.executable = executable.expanduser().resolve()
        self.timeout_seconds = timeout_seconds

    def version(self) -> str:
        """Return the version reported by ie-cli."""
        return self._run("--version").strip()

    def list_creatures(self, game_root: Path) -> list[CreResource]:
        """List every effective CRE resource."""
        return _CRE_RESOURCES.validate_json(
            self._run(
                "list",
                "--game",
                str(game_root),
                "--type",
                "CRE",
                "--format",
                "json",
            ),
            strict=True,
        )

    def list_dialogues(self, game_root: Path) -> list[DlgResource]:
        """List every effective DLG resource."""
        return _DLG_RESOURCES.validate_json(
            self._run(
                "list",
                "--game",
                str(game_root),
                "--type",
                "DLG",
                "--format",
                "json",
            ),
            strict=True,
        )

    def dump_creature(self, game_root: Path, resource_name: str) -> CreDump:
        """Dump and validate one CRE resource."""
        dump = CreDump.model_validate_json(
            self._dump_resource(game_root, resource_name),
            strict=True,
        )
        assert dump.resource_name.casefold() == resource_name.casefold(), (
            f"iecli returned {dump.resource_name!r} for requested CRE {resource_name!r}"
        )
        return dump

    def dump_dialogue(self, game_root: Path, resource_name: str) -> DlgDump:
        """Dump and validate one DLG resource."""
        dump = DlgDump.model_validate_json(
            self._dump_resource(game_root, resource_name),
            strict=True,
        )
        assert dump.resource_name.casefold() == resource_name.casefold(), (
            f"iecli returned {dump.resource_name!r} for requested DLG {resource_name!r}"
        )
        return dump

    def read_text_resource(self, game_root: Path, resource_name: str) -> str:
        """Dump one effective IDS or 2DA resource and decode its raw text."""
        with tempfile.TemporaryDirectory(prefix="bgvoice-iecli-") as temporary_directory:
            output = Path(temporary_directory, "resource.bin")
            self._run(
                "dump-raw",
                "--game",
                str(game_root),
                "--resource",
                resource_name,
                "--output",
                str(output),
            )
            data = output.read_bytes()
        return _decode_text_resource(data)

    def resolve_string(self, game_root: Path, strref: int) -> StringReference:
        """Resolve one unsigned dialog.tlk string reference."""
        result = StringReference.model_validate_json(
            self._run("tlk", "--game", str(game_root), "--strref", str(strref)),
            strict=True,
        )
        assert result.strref == strref, (
            f"iecli returned strref {result.strref} for requested strref {strref}"
        )
        return result

    def _dump_resource(self, game_root: Path, resource_name: str) -> str:
        return self._run(
            "dump",
            "--game",
            str(game_root),
            "--resource",
            resource_name,
            "--format",
            "json",
            "--strings",
            "both",
        )

    def _run(self, *arguments: str) -> str:
        return subprocess.run(
            [str(self.executable), *arguments],
            capture_output=True,
            check=True,
            encoding="utf-8",
            timeout=self.timeout_seconds,
        ).stdout


def _decode_text_resource(data: bytes) -> str:
    return data.decode("cp1252")
