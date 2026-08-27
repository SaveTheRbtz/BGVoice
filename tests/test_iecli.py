"""Tests for the direct ie-cli subprocess adapter."""

import json
import subprocess
from pathlib import Path
from typing import Never

import pytest
from pydantic import ValidationError

from bgvoice.iecli import IeCli
from tests.factories import (
    make_dialogue_dump,
    make_dialogue_resource,
    make_dump,
    make_portrait_resource,
    make_resource,
)


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
            json.dumps([make_portrait_resource().model_dump(by_alias=True)]),
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
    assert client.list_portraits(game_root)[0].resref == "AERIES"
    assert client.dump_creature(game_root, "MONKTU 8.CRE").resource_name == "MONKTU 8.CRE"
    assert client.dump_dialogue(game_root, "AERIE.DLG").header.num_states == 2

    program = str(executable.resolve())
    assert [command for command, _options in calls] == [
        [program, "--version"],
        [program, "list", "--game", str(game_root), "--type", "CRE", "--format", "json"],
        [program, "list", "--game", str(game_root), "--type", "DLG", "--format", "json"],
        [program, "list", "--game", str(game_root), "--type", "BMP", "--format", "json"],
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


def test_dump_resource_identity_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    responses = iter(
        [
            make_dump("aerie.cre").model_dump_json(by_alias=True),
            make_dialogue_dump("aerie.dlg").model_dump_json(by_alias=True),
        ]
    )

    def run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout=next(responses), stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    client = IeCli(tmp_path / "iecli.exe")

    assert client.dump_creature(tmp_path, "AERIE.CRE").resource_name == "aerie.cre"
    assert client.dump_dialogue(tmp_path, "AERIE.DLG").resource_name == "aerie.dlg"


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


def test_iecli_reads_raw_text_resources_and_resolves_tlk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "iecli.exe"
    game_root = tmp_path / "game"
    calls: list[list[str]] = []

    def run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[1] == "dump-raw":
            output = Path(command[command.index("--output") + 1])
            output.write_bytes(b"IDS V1.0\r\n1 CAF\xe9\r\n")
            stdout = "future non-JSON dump metadata"
        else:
            stdout = json.dumps(
                {
                    "strref": 7193,
                    "text": "human",
                    "future_tlk_metadata": {"sound": "HUMAN"},
                }
            )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    client = IeCli(executable)

    assert client.read_text_resource(game_root, "RACE.IDS") == "IDS V1.0\r\n1 CAFé\r\n"
    assert client.resolve_string(game_root, 7193).model_dump() == {
        "strref": 7193,
        "text": "human",
    }
    assert calls[0][1:7] == [
        "dump-raw",
        "--game",
        str(game_root),
        "--resource",
        "RACE.IDS",
        "--output",
    ]
    assert calls[1][1:] == ["tlk", "--game", str(game_root), "--strref", "7193"]


def test_iecli_returns_raw_resource_bytes_exactly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw = b"BM\x00\xff\x80portrait"
    calls: list[list[str]] = []

    def run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        output = Path(command[command.index("--output") + 1])
        output.write_bytes(raw)
        return subprocess.CompletedProcess(command, 0, stdout="ignored", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    client = IeCli(tmp_path / "iecli.exe")

    assert client.read_raw_resource(tmp_path / "game", "AERIES.BMP") == raw
    assert calls[0][1:7] == [
        "dump-raw",
        "--game",
        str(tmp_path / "game"),
        "--resource",
        "AERIES.BMP",
        "--output",
    ]


def test_tlk_result_must_match_the_requested_strref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    response = {
        "dialog_tlk": str(tmp_path / "dialog.tlk"),
        "language": "en_US",
        "strref": 2,
        "text": "wrong",
    }

    def run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(response), stderr="")

    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(AssertionError, match="requested strref 1"):
        IeCli(tmp_path / "iecli.exe").resolve_string(tmp_path, 1)


def test_tlk_result_preserves_unresolved_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    response = {
        "strref": 1,
        "text": None,
    }

    def run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(response), stderr="")

    monkeypatch.setattr(subprocess, "run", run)

    assert IeCli(tmp_path / "iecli.exe").resolve_string(tmp_path, 1).text is None


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
