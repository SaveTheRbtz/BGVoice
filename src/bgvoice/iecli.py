"""Typed access to the bundled ``iecli`` executable."""

import subprocess
from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter

from bgvoice.models import CreDump, CreResource, DlgDump, DlgResource

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
        assert dump.resource_name == resource_name, (
            f"iecli returned {dump.resource_name!r} for requested CRE {resource_name!r}"
        )
        return dump

    def dump_dialogue(self, game_root: Path, resource_name: str) -> DlgDump:
        """Dump and validate one DLG resource."""
        dump = DlgDump.model_validate_json(
            self._dump_resource(game_root, resource_name),
            strict=True,
        )
        assert dump.resource_name == resource_name, (
            f"iecli returned {dump.resource_name!r} for requested DLG {resource_name!r}"
        )
        return dump

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
