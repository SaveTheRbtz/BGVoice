"""Tests for the shared concurrent extraction lifecycle."""

from collections.abc import Callable
from pathlib import Path
from threading import Event

import pytest
from sqlalchemy.engine import URL
from sqlmodel import Session, create_engine, select

import bgvoice.pipeline as pipeline
from bgvoice.database import CharacterDatabase, ExtractionRun
from bgvoice.models import (
    CreDump,
    CreResource,
    DlgDump,
    DlgResource,
    ExtractionProgress,
    ExtractionSummary,
    RunKind,
)
from bgvoice.pipeline import extract_characters, extract_dialogues
from tests.factories import make_dialogue_dump, make_dialogue_resource, make_dump, make_resource

type Extractor = Callable[..., ExtractionSummary]


class FakeIeCli:
    """A deterministic client spanning both resource kinds."""

    def __init__(self) -> None:
        self.creatures = [make_resource(), make_resource("MINSC.CRE")]
        self.dialogues = [make_dialogue_resource(), make_dialogue_resource("MINSC.DLG")]
        self.failures: set[str] = set()
        self.inventory_failure: RunKind | None = None
        self.dumped: list[str] = []

    def version(self) -> str:
        return "iecli test"

    def list_creatures(self, game_root: Path) -> list[CreResource]:
        self._raise_inventory_failure("characters")
        return self.creatures

    def list_dialogues(self, game_root: Path) -> list[DlgResource]:
        self._raise_inventory_failure("dialogues")
        return self.dialogues

    def dump_creature(self, game_root: Path, resource_name: str) -> CreDump:
        self._record_dump(resource_name)
        return make_dump(resource_name, dialog=resource_name.removesuffix(".CRE"))

    def dump_dialogue(self, game_root: Path, resource_name: str) -> DlgDump:
        self._record_dump(resource_name)
        return make_dialogue_dump(resource_name)

    def _record_dump(self, resource_name: str) -> None:
        self.dumped.append(resource_name)
        if resource_name in self.failures:
            raise RuntimeError(f"cannot dump {resource_name}")

    def _raise_inventory_failure(self, run_kind: RunKind) -> None:
        if self.inventory_failure == run_kind:
            raise RuntimeError(f"cannot list {run_kind}")


def test_character_inventory_can_skip_detail_extraction(tmp_path: Path) -> None:
    """Inventory-only mode persists every CRE without invoking dump commands."""
    client = FakeIeCli()
    with CharacterDatabase(tmp_path / "pipeline.sqlite3") as database:
        summary = extract_characters(client, database, tmp_path, include_details=False)

        assert summary.discovered == 2
        assert summary.attempted == 0
        assert summary.skipped == 2
        assert summary.status == "complete"
        assert database.stats().pending == 2
    assert client.dumped == []


@pytest.mark.parametrize(
    ("extractor", "run_kind", "failed_resource"),
    [
        (extract_characters, "characters", "MINSC.CRE"),
        (extract_dialogues, "dialogues", "MINSC.DLG"),
    ],
)
def test_extraction_retries_failures_and_refreshes_completed_resources(
    tmp_path: Path,
    extractor: Extractor,
    run_kind: RunKind,
    failed_resource: str,
) -> None:
    """Only failures retry by default, while refresh extracts the full inventory."""
    client = FakeIeCli()
    client.failures.add(failed_resource)
    progress: list[ExtractionProgress] = []

    with CharacterDatabase(tmp_path / f"{run_kind}.sqlite3") as database:
        first = extractor(client, database, tmp_path, workers=2, progress=progress.append)
        assert first.status == "complete_with_errors"
        assert (first.discovered, first.attempted, first.extracted, first.failed) == (2, 2, 1, 1)
        assert progress == [ExtractionProgress(completed=2, total=2, succeeded=1, failed=1)]

        client.failures.clear()
        client.dumped.clear()
        retry = extractor(client, database, tmp_path, workers=1)
        assert (retry.attempted, retry.extracted, retry.skipped) == (1, 1, 1)
        assert client.dumped == [failed_resource]

        client.dumped.clear()
        refreshed = extractor(client, database, tmp_path, workers=2, refresh=True)
        assert (refreshed.attempted, refreshed.extracted, refreshed.skipped) == (2, 2, 0)
        expected_suffix = ".CRE" if run_kind == "characters" else ".DLG"
        assert set(client.dumped) == {f"AERIE{expected_suffix}", f"MINSC{expected_suffix}"}

        if run_kind == "characters":
            assert database.stats().complete == 2
        else:
            assert database.dialogue_targets(refresh=False) == []


@pytest.mark.parametrize(
    ("extractor", "run_kind"),
    [
        (extract_characters, "characters"),
        (extract_dialogues, "dialogues"),
    ],
)
def test_fatal_inventory_errors_are_persisted_and_propagated(
    tmp_path: Path,
    extractor: Extractor,
    run_kind: RunKind,
) -> None:
    """Discovery failures finalize the durable run before reaching the caller."""
    path = tmp_path / f"{run_kind}.sqlite3"
    client = FakeIeCli()
    client.inventory_failure = run_kind

    with (
        CharacterDatabase(path) as database,
        pytest.raises(RuntimeError, match=f"cannot list {run_kind}"),
    ):
        extractor(client, database, tmp_path)

    engine = create_engine(URL.create("sqlite+pysqlite", database=str(path)))
    with Session(engine) as session:
        run = session.exec(select(ExtractionRun)).one()
        assert (run.run_kind, run.status, run.error) == (
            run_kind,
            "failed",
            f"cannot list {run_kind}",
        )
        assert run.completed_at is not None
    engine.dispose()


def test_finalization_failure_does_not_mask_extraction_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original = RuntimeError("cannot list characters")

    def fail_discovery(_game_root: Path) -> list[CreResource]:
        raise original

    def fail_finalization(*_args: object, **_options: object) -> None:
        raise OSError("cannot finalize run")

    client = FakeIeCli()
    monkeypatch.setattr(client, "list_creatures", fail_discovery)
    with CharacterDatabase(tmp_path / "pipeline.sqlite3") as database:
        monkeypatch.setattr(database, "finish_run", fail_finalization)

        with pytest.raises(RuntimeError) as raised:
            extract_characters(client, database, tmp_path)

    assert raised.value is original
    assert raised.value.__notes__ == [
        "Failed to finalize extraction run 1: OSError('cannot finalize run')"
    ]


@pytest.mark.parametrize(
    "fatal_error",
    [OSError("cannot save batch"), KeyboardInterrupt()],
)
def test_fatal_batch_exit_cancels_queued_work_without_waiting(
    fatal_error: BaseException,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    resources = ["first", "running", "queued"]
    all_submitted = Event()
    running_started = Event()
    release_running = Event()
    running_finished = Event()
    queued_started = Event()
    named: list[str] = []

    def name(resource: str) -> str:
        named.append(resource)
        if len(named) == len(resources):
            all_submitted.set()
        return resource

    def dump(_game_root: Path, resource_name: str) -> str:
        if resource_name == "first":
            assert all_submitted.wait(2)
        elif resource_name == "running":
            running_started.set()
            try:
                if not release_running.wait(2):
                    raise TimeoutError("extractor waited for a running job")
            finally:
                running_finished.set()
        else:
            queued_started.set()
        return resource_name

    def build(resource: str, dumped: str) -> str:
        assert resource == dumped
        assert running_started.wait(2)
        return resource

    def fail_save(_details: object, _failures: object) -> None:
        raise fatal_error

    monkeypatch.setattr(pipeline, "_WRITE_BATCH_SIZE", 1)
    try:
        with pytest.raises(BaseException) as raised:
            pipeline._extract_resources(
                resources,
                tmp_path,
                name=name,
                dump=dump,
                build=build,
                save=fail_save,
                workers=1,
                thread_name_prefix="test-cancel",
                progress=None,
            )

        assert raised.value is fatal_error
        assert running_started.is_set()
        assert not queued_started.is_set()
    finally:
        release_running.set()

    assert running_finished.wait(2)
    assert not queued_started.wait(0.2)
