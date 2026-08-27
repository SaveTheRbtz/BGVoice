"""Tests for the shared concurrent extraction lifecycle."""

import re
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Event

import lancedb
import pytest

import bgvoice.pipeline as pipeline
from bgvoice.database import ExtractionRunRecord, PipelineDatabase
from bgvoice.models import (
    BanterTimingSettings,
    CharacterDetail,
    CreDump,
    CreResource,
    DlgDump,
    DlgResource,
    ExtractionProgress,
    ExtractionSummary,
    MetadataExtraction,
    RunKind,
    StringReference,
)
from bgvoice.pipeline import extract_characters, extract_dialogues, extract_metadata
from tests.factories import make_dialogue_dump, make_dialogue_resource, make_dump, make_resource

type Extractor = Callable[..., ExtractionSummary]


def _empty_metadata(source_count: int = 3) -> MetadataExtraction:
    return MetadataExtraction(
        source_resource_count=source_count,
        resolved_strref_count=0,
        identifiers=[],
        campaigns=[],
        campaign_resource_bindings=[],
        character_resource_links=[],
        interaction_rules=[],
        soundset_lines=[],
        sound_slot_suffixes=[],
        sound_slot_groups=[],
        favored_enemies=[],
        happiness_rules=[],
        banter_timing=BanterTimingSettings(
            source_resource="BANTTIMG.2DA",
            frequency=1,
            probability=0,
            replay_delay=1,
            special_probability=0,
        ),
        engine_strings=[],
        months=[],
        campaign_calendars=[],
        race_text_rows=[],
        class_text_rows=[],
        kits=[],
    )


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
        self._raise_inventory_failure(RunKind.CHARACTERS)
        return self.creatures

    def list_dialogues(self, game_root: Path) -> list[DlgResource]:
        self._raise_inventory_failure(RunKind.DIALOGUES)
        return self.dialogues

    def dump_creature(self, game_root: Path, resource_name: str) -> CreDump:
        self._record_dump(resource_name)
        return make_dump(resource_name, dialog=resource_name.removesuffix(".CRE"))

    def dump_dialogue(self, game_root: Path, resource_name: str) -> DlgDump:
        self._record_dump(resource_name)
        return make_dialogue_dump(resource_name)

    def read_text_resource(self, game_root: Path, resource_name: str) -> str:
        raise AssertionError("metadata builder is replaced in pipeline lifecycle tests")

    def resolve_string(self, game_root: Path, strref: int) -> StringReference:
        raise AssertionError("metadata builder is replaced in pipeline lifecycle tests")

    def _record_dump(self, resource_name: str) -> None:
        self.dumped.append(resource_name)
        if resource_name in self.failures:
            raise RuntimeError(f"cannot dump {resource_name}")

    def _raise_inventory_failure(self, run_kind: RunKind) -> None:
        if self.inventory_failure == run_kind:
            raise RuntimeError(f"cannot list {run_kind}")


def test_metadata_extraction_replaces_all_metadata_and_records_its_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = FakeIeCli()
    database = PipelineDatabase(tmp_path / "metadata.lancedb")
    calls: list[tuple[Path, int]] = []

    def build(_client: object, game_root: Path, *, workers: int) -> MetadataExtraction:
        calls.append((game_root, workers))
        return _empty_metadata()

    monkeypatch.setattr(pipeline, "build_metadata", build)
    summary = extract_metadata(client, database, tmp_path, workers=6)

    assert calls == [(tmp_path.resolve(), 6)]
    assert (summary.discovered, summary.attempted, summary.extracted, summary.status) == (
        3,
        3,
        3,
        "complete",
    )
    run = (
        lancedb.connect(database.path)
        .open_table("extraction_runs")
        .search()
        .to_pydantic(ExtractionRunRecord)
    )[0]
    assert (run.run_kind, run.resources_discovered, run.details_extracted) == (
        RunKind.METADATA,
        3,
        3,
    )


def test_metadata_extraction_failure_is_finalized_and_propagated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = RuntimeError("cannot import metadata")

    def fail(*_args: object, **_options: object) -> MetadataExtraction:
        raise expected

    monkeypatch.setattr(pipeline, "build_metadata", fail)
    database = PipelineDatabase(tmp_path / "metadata-failure.lancedb")
    with pytest.raises(RuntimeError) as raised:
        extract_metadata(FakeIeCli(), database, tmp_path)

    assert raised.value is expected
    run = (
        lancedb.connect(database.path)
        .open_table("extraction_runs")
        .search()
        .to_pydantic(ExtractionRunRecord)
    )[0]
    assert (run.run_kind, run.status, run.error) == (
        RunKind.METADATA,
        "failed",
        str(expected),
    )


def test_character_inventory_can_skip_detail_extraction(tmp_path: Path) -> None:
    """Inventory-only mode persists every CRE without invoking dump commands."""
    client = FakeIeCli()
    database = PipelineDatabase(tmp_path / "pipeline.lancedb")
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
        (extract_characters, RunKind.CHARACTERS, "MINSC.CRE"),
        (extract_dialogues, RunKind.DIALOGUES, "MINSC.DLG"),
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

    database = PipelineDatabase(tmp_path / f"{run_kind}.lancedb")
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
        (extract_characters, RunKind.CHARACTERS),
        (extract_dialogues, RunKind.DIALOGUES),
    ],
)
def test_fatal_inventory_errors_are_persisted_and_propagated(
    tmp_path: Path,
    extractor: Extractor,
    run_kind: RunKind,
) -> None:
    """Discovery failures finalize the durable run before reaching the caller."""
    path = tmp_path / f"{run_kind}.lancedb"
    client = FakeIeCli()
    client.inventory_failure = run_kind
    database = PipelineDatabase(path)

    with pytest.raises(RuntimeError, match=f"cannot list {run_kind}"):
        extractor(client, database, tmp_path)

    runs = (
        lancedb.connect(path)
        .open_table("extraction_runs")
        .search()
        .to_pydantic(ExtractionRunRecord)
    )
    assert len(runs) == 1
    run = runs[0]
    assert (run.run_kind, run.status, run.error) == (
        run_kind,
        "failed",
        f"cannot list {run_kind}",
    )
    assert run.completed_at is not None


def test_fatal_batch_write_preserves_committed_run_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "partial.lancedb"
    database = PipelineDatabase(path)
    client = FakeIeCli()
    original_save = database.apply_detail_batch
    save_count = 0

    def fail_second_save(
        details: Sequence[CharacterDetail],
        failures: Sequence[tuple[str, str]],
    ) -> None:
        nonlocal save_count
        save_count += 1
        if save_count == 2:
            raise OSError("simulated Lance write failure")
        original_save(details, failures)

    monkeypatch.setattr(pipeline, "_WRITE_BATCH_SIZE", 1)
    monkeypatch.setattr(database, "apply_detail_batch", fail_second_save)
    with pytest.raises(OSError, match="simulated Lance write failure"):
        extract_characters(client, database, tmp_path, workers=1)

    run = (
        lancedb.connect(path)
        .open_table("extraction_runs")
        .search()
        .to_pydantic(ExtractionRunRecord)
    )[0]
    assert (run.status, run.details_attempted, run.details_extracted, run.failures) == (
        "failed",
        2,
        1,
        0,
    )


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
    database = PipelineDatabase(tmp_path / "pipeline.lancedb")
    monkeypatch.setattr(database, "finish_run", fail_finalization)

    with pytest.raises(RuntimeError) as raised:
        extract_characters(client, database, tmp_path)

    assert raised.value is original
    assert len(raised.value.__notes__) == 1
    assert re.fullmatch(
        r"Failed to finalize extraction run [0-9a-f]{32}: "
        r"OSError\('cannot finalize run'\)",
        raised.value.__notes__[0],
    )


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
                committed=lambda _succeeded, _failed: None,
            )

        assert raised.value is fatal_error
        assert running_started.is_set()
        assert not queued_started.is_set()
    finally:
        release_running.set()

    assert running_finished.wait(2)
    assert not queued_started.wait(0.2)
