"""Tests for the direct ie-cli subprocess adapter."""

import json
import subprocess
from pathlib import Path
from typing import Never

import pytest
from pydantic import ValidationError

from bgvoice.iecli import IeCli
from tests.factories import make_dialogue_dump, make_dialogue_resource, make_dump, make_resource


def test_iecli_builds_commands_and_validates_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "iecli.exe"
    game_root = tmp_path / "BG2EE-EET"
    responses = iter(
        [
            "iecli 0.3.0-rc.1\n",
            json.dumps([make_resource().model_dump(by_alias=True)]),
            json.dumps([make_dialogue_resource().model_dump(by_alias=True)]),
            make_dump("MONKTU 8.CRE").model_dump_json(by_alias=True),
            make_dialogue_dump().model_dump_json(by_alias=True),
        ]
    )
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0, stdout=next(responses), stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    client = IeCli(executable, timeout_seconds=5.0)

    assert client.version() == "iecli 0.3.0-rc.1"
    assert client.list_creatures(game_root)[0].resref == "AERIE"
    assert client.list_dialogues(game_root)[0].resref == "AERIE"
    assert client.dump_creature(game_root, "MONKTU 8.CRE").resource_name == "MONKTU 8.CRE"
    assert client.dump_dialogue(game_root, "AERIE.DLG").header.num_states == 2

    program = str(executable.resolve())
    assert [command for command, _options in calls] == [
        [program, "--version"],
        [program, "list", "--game", str(game_root), "--type", "CRE", "--format", "json"],
        [program, "list", "--game", str(game_root), "--type", "DLG", "--format", "json"],
        [
            program,
            "dump",
            "--game",
            str(game_root),
            "--resource",
            "MONKTU 8.CRE",
            "--format",
            "json",
            "--strings",
            "both",
        ],
        [
            program,
            "dump",
            "--game",
            str(game_root),
            "--resource",
            "AERIE.DLG",
            "--format",
            "json",
            "--strings",
            "both",
        ],
    ]
    assert all(
        options
        == {
            "capture_output": True,
            "check": True,
            "encoding": "utf-8",
            "timeout": 5.0,
        }
        for _command, options in calls
    )


def test_dump_requires_the_requested_resource_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    responses = iter(
        [
            make_dump("MINSC.CRE").model_dump_json(by_alias=True),
            make_dialogue_dump("MINSC.DLG").model_dump_json(by_alias=True),
        ]
    )

    def run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout=next(responses), stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    client = IeCli(tmp_path / "iecli.exe")

    with pytest.raises(AssertionError) as creature_error:
        client.dump_creature(tmp_path, "AERIE.CRE")
    with pytest.raises(AssertionError) as dialogue_error:
        client.dump_dialogue(tmp_path, "AERIE.DLG")

    assert [str(creature_error.value), str(dialogue_error.value)] == [
        "iecli returned 'MINSC.CRE' for requested CRE 'AERIE.CRE'",
        "iecli returned 'MINSC.DLG' for requested DLG 'AERIE.DLG'",
    ]


def test_invalid_json_propagates_pydantic_validation_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    responses = iter(["not json", '{"resource_name":"broken"}'])

    def run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout=next(responses), stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    client = IeCli(tmp_path / "iecli.exe")

    with pytest.raises(ValidationError):
        client.list_creatures(tmp_path)
    with pytest.raises(ValidationError):
        client.dump_dialogue(tmp_path, "AERIE.DLG")


@pytest.mark.parametrize(
    "error",
    [
        subprocess.CalledProcessError(3, ["iecli"]),
        FileNotFoundError("iecli.exe"),
        subprocess.TimeoutExpired(["iecli"], 5.0),
    ],
)
def test_native_subprocess_errors_propagate(
    error: Exception, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(*_args: object, **_options: object) -> Never:
        raise error

    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(type(error)) as raised:
        IeCli(tmp_path / "iecli.exe").version()

    assert raised.value is error
