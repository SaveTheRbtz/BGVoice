"""Behavior at the external ie-cli process boundary."""

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from bgvoice.iecli import IeCli
from tests.factories import (
    make_dialogue_dump,
    make_dialogue_resource,
    make_dump,
    make_item_dump,
    make_item_resource,
    make_portrait_resource,
    make_resource,
)


def _responses(
    monkeypatch: pytest.MonkeyPatch,
    outputs: Iterator[str],
) -> list[tuple[list[str], dict[str, object]]]:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_json_commands_are_exact_and_responses_are_typed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "iecli.exe"
    game_root = tmp_path / "BG2EE-EET"
    calls = _responses(
        monkeypatch,
        iter(
            [
                "iecli 0.3.0-rc.1\n",
                json.dumps([make_resource().model_dump(by_alias=True)]),
                json.dumps([make_dialogue_resource().model_dump(by_alias=True)]),
                json.dumps([make_portrait_resource().model_dump(by_alias=True)]),
                json.dumps([make_item_resource().model_dump(by_alias=True)]),
                make_dump("MONKTU 8.CRE").model_dump_json(by_alias=True),
                make_dialogue_dump().model_dump_json(by_alias=True),
                make_item_dump().model_dump_json(by_alias=True),
            ]
        ),
    )
    client = IeCli(executable, timeout_seconds=5)

    assert client.version() == "iecli 0.3.0-rc.1"
    assert client.list_creatures(game_root)[0].resref == "AERIE"
    assert client.list_dialogues(game_root)[0].resource_type == "DLG"
    assert client.list_portraits(game_root)[0].resref == "AERIES"
    assert client.list_items(game_root)[0].resource_type == "ITM"
    assert client.dump_creature(game_root, "MONKTU 8.CRE").resource_name == "MONKTU 8.CRE"
    assert client.dump_dialogue(game_root, "AERIE.DLG").header.num_states == 2
    assert client.dump_item(game_root, "BOOK.ITM").header.category.raw == 0

    program = str(executable.resolve())
    assert [command for command, _ in calls] == [
        [program, "--version"],
        [program, "list", "--game", str(game_root), "--type", "CRE", "--format", "json"],
        [program, "list", "--game", str(game_root), "--type", "DLG", "--format", "json"],
        [program, "list", "--game", str(game_root), "--type", "BMP", "--format", "json"],
        [program, "list", "--game", str(game_root), "--type", "ITM", "--format", "json"],
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
        [
            program,
            "dump",
            "--game",
            str(game_root),
            "--resource",
            "BOOK.ITM",
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
            "timeout": 5,
        }
        for _, options in calls
    )


@pytest.mark.parametrize(
    ("kind", "returned", "requested", "valid"),
    [
        ("CRE", "aerie.cre", "AERIE.CRE", True),
        ("DLG", "aerie.dlg", "AERIE.DLG", True),
        ("ITM", "book.itm", "BOOK.ITM", True),
        ("CRE", "MINSC.CRE", "AERIE.CRE", False),
        ("DLG", "MINSC.DLG", "AERIE.DLG", False),
        ("ITM", "TOME.ITM", "BOOK.ITM", False),
    ],
)
def test_dump_identity_is_case_insensitive_but_must_match(
    kind: str,
    returned: str,
    requested: str,
    valid: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if kind == "CRE":
        output = make_dump(returned).model_dump_json(by_alias=True)
    elif kind == "DLG":
        output = make_dialogue_dump(returned).model_dump_json(by_alias=True)
    else:
        output = make_item_dump(returned).model_dump_json(by_alias=True)
    _responses(monkeypatch, iter([output]))
    client = IeCli(tmp_path / "iecli.exe")
    dumps = {
        "CRE": client.dump_creature,
        "DLG": client.dump_dialogue,
        "ITM": client.dump_item,
    }
    dump = dumps[kind]

    if valid:
        assert dump(tmp_path, requested).resource_name == returned
    else:
        with pytest.raises(AssertionError, match="requested"):
            dump(tmp_path, requested)


@pytest.mark.parametrize(
    ("operation", "output"),
    [("list", "not json"), ("dump", '{"resource_name":"broken"}')],
)
def test_malformed_json_fails_at_the_typed_boundary(
    operation: str,
    output: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _responses(monkeypatch, iter([output]))
    client = IeCli(tmp_path / "iecli.exe")

    with pytest.raises(ValidationError):
        if operation == "list":
            client.list_creatures(tmp_path)
        else:
            client.dump_dialogue(tmp_path, "AERIE.DLG")


def test_raw_resources_preserve_bytes_and_decode_cp1252_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw_outputs = iter([b"IDS V1.0\r\n1 CAF\xe9\r\n", b"BM\x00\xff\x80portrait"])
    calls: list[list[str]] = []

    def run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        Path(command[command.index("--output") + 1]).write_bytes(next(raw_outputs))
        return subprocess.CompletedProcess(command, 0, stdout="ignored", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    client = IeCli(tmp_path / "iecli.exe")

    assert client.read_text_resource(tmp_path, "RACE.IDS").endswith("CAFé\r\n")
    assert client.read_raw_resource(tmp_path, "AERIES.BMP") == b"BM\x00\xff\x80portrait"
    assert all(command[1] == "dump-raw" for command in calls)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"strref": 7193, "text": "human", "future": True}, "human"),
        ({"strref": 7193, "text": None}, None),
    ],
)
def test_tlk_resolution_is_typed_and_allows_unresolved_text(
    response: dict[str, object],
    expected: str | None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _responses(monkeypatch, iter([json.dumps(response)]))
    assert IeCli(tmp_path / "iecli.exe").resolve_string(tmp_path, 7193).text == expected


def test_tlk_result_must_match_requested_strref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _responses(monkeypatch, iter([json.dumps({"strref": 2, "text": "wrong"})]))
    with pytest.raises(AssertionError, match="requested strref 1"):
        IeCli(tmp_path / "iecli.exe").resolve_string(tmp_path, 1)
