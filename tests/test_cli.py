"""Command-line behavior tests."""

from collections.abc import Callable
from pathlib import Path

import pytest

import bgvoice.__main__ as cli
from bgvoice.database import PipelineDatabase
from bgvoice.direction_audit import DirectionAuditSummary
from bgvoice.model_types import (
    RunKind,
    RunStatus,
    TerminalRunStatus,
)
from bgvoice.pipeline_models import (
    ExtractionProgress,
    ExtractionSummary,
)


def _summary(tmp_path: Path, status: TerminalRunStatus) -> ExtractionSummary:
    failed = int(status == "complete_with_errors")
    return ExtractionSummary(
        run_id="test-run",
        game_root=tmp_path,
        database_path=tmp_path / "db.lancedb",
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
    assert options.database == Path("data/bgvoice.lancedb")

    metadata = cli.build_parser().parse_args(["extract-metadata", "--game", "C:/game"])
    assert metadata.workers == 12
    portraits = cli.build_parser().parse_args(["extract-portraits", "--game", "C:/game"])
    assert portraits.workers == 12
    generation = cli.build_parser().parse_args(
        [
            "generate",
            "--voice",
            "Imoen",
            "--lines-per-voice",
            "all",
            "--recreate-voices",
        ]
    )
    assert generation.voice == ["Imoen"]
    assert generation.lines_per_voice is None
    assert generation.recreate_voices is True
    audit = cli.build_parser().parse_args(["audit-directions"])
    assert audit.database == Path("data/bgvoice.lancedb")
    assert audit.output == Path("data/direction-mismatches.json")
    assert audit.similarity_threshold == 25


@pytest.mark.parametrize(
    "arguments",
    [
        ["extract-dialogues", "--game", "C:/game", "--workers", "0"],
        ["web", "--port", "65536"],
        ["audit-directions", "--similarity-threshold", "101"],
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

    def extractor(
        stage: str,
        status: TerminalRunStatus,
    ) -> Callable[..., ExtractionSummary]:
        def extract(
            _client: object,
            _database: object,
            _game_root: Path,
            **options: object,
        ) -> ExtractionSummary:
            calls[stage] = options
            return _summary(tmp_path, status)

        return extract

    monkeypatch.setattr(cli, "IeCli", fake_iecli)
    monkeypatch.setattr(cli, "extract_metadata", extractor("metadata", RunStatus.COMPLETE))
    monkeypatch.setattr(cli, "extract_characters", extractor("characters", RunStatus.COMPLETE))
    monkeypatch.setattr(
        cli,
        "extract_dialogues",
        extractor("dialogues", RunStatus.COMPLETE_WITH_ERRORS),
    )
    monkeypatch.setattr(cli, "extract_portraits", extractor("portraits", RunStatus.COMPLETE))

    executable = tmp_path / "iecli.exe"
    database = tmp_path / "pipeline.lancedb"
    commands = [
        (
            [
                "extract-portraits",
                "--game",
                str(tmp_path),
                "--database",
                str(database),
                "--workers",
                "6",
            ],
            0,
        ),
        (
            [
                "extract-metadata",
                "--game",
                str(tmp_path),
                "--database",
                str(database),
                "--workers",
                "4",
            ],
            0,
        ),
        (
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
            ],
            0,
        ),
        (
            [
                "extract-dialogues",
                "--game",
                str(tmp_path),
                "--database",
                str(database),
                "--workers",
                "2",
            ],
            1,
        ),
    ]
    assert [cli.main(arguments) for arguments, _expected in commands] == [
        expected for _arguments, expected in commands
    ]

    assert executables == [None, None, executable, None]
    assert calls["metadata"] == {"workers": 4}
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
    assert calls["portraits"] == {"workers": 6}
    output = capsys.readouterr()
    assert '"status": "complete"' in output.out
    assert '"status": "complete_with_errors"' in output.out
    assert output.err.count("Active character records: 0") == 3


def test_web_and_attribution_commands_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    web_calls: list[tuple[object, str, int]] = []

    def run_web(app: object, *, host: str, port: int) -> None:
        web_calls.append((app, host, port))

    monkeypatch.setattr("uvicorn.run", run_web)

    database = tmp_path / "pipeline.lancedb"
    writer = PipelineDatabase(database)
    for kind in (RunKind.CHARACTERS, RunKind.DIALOGUES, RunKind.METADATA):
        run_id = writer.start_run(tmp_path, "iecli test", run_kind=kind)
        writer.finish_run(
            run_id,
            status=RunStatus.COMPLETE,
            attempted=0,
            extracted=0,
            failures=0,
        )
    assert cli.main(["attribute-dialogues", "--database", str(database)]) == 0
    assert (
        cli.main(["web", "--database", str(database), "--host", "0.0.0.0", "--port", "8123"]) == 0
    )

    assert len(web_calls) == 1
    assert web_calls[0][1:] == ("0.0.0.0", 8123)
    output = capsys.readouterr()
    assert '"characters_unavailable": 0' in output.out
    assert '"dialogues_unattributed": 0' in output.out
    assert output.err == ""


def test_attribution_rejects_a_missing_database(tmp_path: Path) -> None:
    path = tmp_path / "missing.lancedb"
    with pytest.raises(AssertionError, match="pipeline database does not exist"):
        cli.main(["attribute-dialogues", "--database", str(path)])
    assert not path.exists()


def test_direction_audit_command_dispatches_typed_options(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    calls: list[tuple[Path, Path, str, float]] = []

    async def audit(
        database: Path,
        output: Path,
        api_key: str,
        *,
        similarity_threshold: float,
    ) -> DirectionAuditSummary:
        calls.append((database, output, api_key, similarity_threshold))
        return DirectionAuditSummary(
            directed_lines=100,
            rapidfuzz_candidates=4,
            model_batches=1,
            mismatches=2,
            output=str(output),
        )

    monkeypatch.setattr(cli, "audit_directions", audit)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    database = tmp_path / "pipeline.lancedb"
    output = tmp_path / "mismatches.json"

    assert (
        cli.main(
            [
                "audit-directions",
                "--database",
                str(database),
                "--output",
                str(output),
                "--similarity-threshold",
                "30",
            ]
        )
        == 0
    )
    assert calls == [(database, output, "test-openai-key", 30)]
    assert '"mismatches": 2' in capsys.readouterr().out
