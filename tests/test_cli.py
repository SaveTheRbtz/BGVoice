"""Command-line behavior tests."""

from pathlib import Path

import pytest

import bgvoice.__main__ as cli
from bgvoice.models import (
    ExtractionProgress,
    ExtractionSummary,
    TerminalRunStatus,
)


def _summary(tmp_path: Path, status: TerminalRunStatus) -> ExtractionSummary:
    failed = int(status == "complete_with_errors")
    return ExtractionSummary(
        run_id=1,
        game_root=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        iecli_version="iecli test",
        discovered=2,
        attempted=2,
        extracted=2 - failed,
        failed=failed,
        skipped=0,
        status=status,
    )


def test_parser_uses_available_cpu_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Extraction defaults to one iecli process per available logical CPU."""
    monkeypatch.setattr(cli.os, "process_cpu_count", lambda: 12)

    options = cli.build_parser().parse_args(["extract-characters", "--game", "C:/game"])

    assert options.workers == 12


@pytest.mark.parametrize(
    "arguments",
    [
        ["extract-dialogues", "--game", "C:/game", "--workers", "0"],
        ["web", "--port", "65536"],
    ],
)
def test_parser_rejects_out_of_range_numbers(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.build_parser().parse_args(arguments)

    assert raised.value.code == 2


def test_progress_is_written_only_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    progress = ExtractionProgress(completed=4, total=5, succeeded=3, failed=1)

    cli._print_character_progress(progress)
    cli._print_dialogue_progress(progress)

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.splitlines() == [
        "CRE details 4/5 (ok=3, failed=1)",
        "DLG metrics 4/5 (ok=3, failed=1)",
    ]


def test_extraction_commands_dispatch_options_and_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    calls: dict[str, dict[str, object]] = {}
    executables: list[Path | None] = []

    def fake_iecli(executable: Path | None = None) -> object:
        executables.append(executable)
        return object()

    def fake_characters(
        _client: object,
        _database: object,
        _game_root: Path,
        **options: object,
    ) -> ExtractionSummary:
        calls["characters"] = options
        return _summary(tmp_path, "complete")

    def fake_dialogues(
        _client: object,
        _database: object,
        _game_root: Path,
        **options: object,
    ) -> ExtractionSummary:
        calls["dialogues"] = options
        return _summary(tmp_path, "complete_with_errors")

    monkeypatch.setattr(cli, "IeCli", fake_iecli)
    monkeypatch.setattr(cli, "extract_characters", fake_characters)
    monkeypatch.setattr(cli, "extract_dialogues", fake_dialogues)

    executable = tmp_path / "iecli.exe"
    database = tmp_path / "pipeline.sqlite3"
    assert (
        cli.main(
            [
                "extract-characters",
                "--game",
                str(tmp_path),
                "--iecli",
                str(executable),
                "--database",
                str(database),
                "--workers",
                "3",
                "--refresh",
                "--inventory-only",
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "extract-dialogues",
                "--game",
                str(tmp_path),
                "--database",
                str(database),
                "--workers",
                "2",
            ]
        )
        == 1
    )

    assert executables == [executable, None]
    assert calls["characters"] == {
        "include_details": False,
        "workers": 3,
        "refresh": True,
        "progress": cli._print_character_progress,
    }
    assert calls["dialogues"] == {
        "workers": 2,
        "refresh": False,
        "progress": cli._print_dialogue_progress,
    }
    output = capsys.readouterr()
    assert '"status": "complete"' in output.out
    assert '"status": "complete_with_errors"' in output.out
    assert output.err.count("SQLite integrity: ok") == 2


def test_native_extraction_errors_propagate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected = FileNotFoundError("iecli.exe")

    def fail(*_args: object, **_options: object) -> ExtractionSummary:
        raise expected

    monkeypatch.setattr(cli, "IeCli", lambda: object())
    monkeypatch.setattr(cli, "extract_characters", fail)

    with pytest.raises(FileNotFoundError) as raised:
        cli.main(
            [
                "extract-characters",
                "--game",
                str(tmp_path),
                "--database",
                str(tmp_path / "pipeline.sqlite3"),
            ]
        )

    assert raised.value is expected


@pytest.mark.parametrize("command", ["attribute-dialogues", "extract-characters"])
def test_integrity_failure_asserts_after_printing_diagnostics(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def corrupt_integrity(_database: object) -> str:
        return "corrupt"

    def fake_extraction(*_args: object, **_options: object) -> ExtractionSummary:
        return _summary(tmp_path, "complete")

    monkeypatch.setattr(cli.CharacterDatabase, "integrity_check", corrupt_integrity)
    monkeypatch.setattr(cli, "IeCli", lambda: object())
    monkeypatch.setattr(cli, "extract_characters", fake_extraction)
    arguments = [command, "--database", str(tmp_path / "pipeline.sqlite3")]
    if command == "extract-characters":
        arguments.extend(["--game", str(tmp_path)])

    with pytest.raises(AssertionError, match="SQLite integrity check failed: corrupt"):
        cli.main(arguments)

    output = capsys.readouterr()
    assert output.out.strip()
    assert "SQLite integrity: corrupt" in output.err


def test_web_and_attribution_commands_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    web_calls: list[tuple[object, str, int]] = []

    def run_web(app: object, *, host: str, port: int) -> None:
        web_calls.append((app, host, port))

    monkeypatch.setattr("uvicorn.run", run_web)

    database = tmp_path / "pipeline.sqlite3"
    assert cli.main(["attribute-dialogues", "--database", str(database)]) == 0
    assert (
        cli.main(["web", "--database", str(database), "--host", "0.0.0.0", "--port", "8123"]) == 0
    )

    assert len(web_calls) == 1
    assert web_calls[0][1:] == ("0.0.0.0", 8123)
    output = capsys.readouterr()
    assert '"characters_unavailable": 0' in output.out
    assert '"dialogues_unattributed": 0' in output.out
    assert "SQLite integrity: ok" in output.err
