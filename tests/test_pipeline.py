"""Tests for the shared concurrent extraction lifecycle."""

from collections.abc import Callable, Sequence
from io import BytesIO
from pathlib import Path

import lancedb
import pytest
from PIL import Image

import bgvoice.pipeline as pipeline
from bgvoice.character_models import (
    CharacterExtraction,
    CreDump,
)
from bgvoice.database import PipelineDatabase
from bgvoice.dialogue_models import (
    DlgDump,
)
from bgvoice.metadata_models import MetadataExtraction
from bgvoice.model_types import (
    CreResource,
    DlgResource,
    ItmResource,
    PortraitImage,
    PortraitResource,
    RunKind,
    StringReference,
)
from bgvoice.pipeline import (
    extract_characters,
    extract_dialogues,
    extract_metadata,
    extract_portraits,
    extract_readable_items,
)
from bgvoice.pipeline_models import (
    ExtractionProgress,
    ExtractionSummary,
)
from bgvoice.readable_models import ItmDump
from bgvoice.reader import PipelineReader
from bgvoice.reader_models import ClassQuery, KitQuery, RaceQuery
from bgvoice.storage_records import ExtractionRunRecord
from tests.factories import (
    MetadataClient,
    make_dialogue_dump,
    make_dialogue_resource,
    make_dump,
    make_item_dump,
    make_item_resource,
    make_portrait_resource,
    make_resource,
    metadata_resources,
)

pytestmark = pytest.mark.integration

type Extractor = Callable[..., ExtractionSummary]


def _bmp(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), color).save(output, format="BMP")
    return output.getvalue()


class FakeIeCli:
    """A deterministic client spanning both resource kinds."""

    def __init__(self) -> None:
        self.creatures = [make_resource(), make_resource("MINSC.CRE")]
        self.dialogues = [make_dialogue_resource(), make_dialogue_resource("MINSC.DLG")]
        self.items: list[ItmResource] = []
        self.portraits: list[PortraitResource] = []
        self.raw_resources: dict[str, bytes] = {}
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

    def list_portraits(self, game_root: Path) -> list[PortraitResource]:
        self._raise_inventory_failure(RunKind.PORTRAITS)
        return self.portraits

    def list_items(self, game_root: Path) -> list[ItmResource]:
        self._raise_inventory_failure(RunKind.READABLE_ITEMS)
        return self.items

    def dump_creature(self, game_root: Path, resource_name: str) -> CreDump:
        self._record_dump(resource_name)
        return make_dump(resource_name, dialog=resource_name.removesuffix(".CRE"))

    def dump_dialogue(self, game_root: Path, resource_name: str) -> DlgDump:
        self._record_dump(resource_name)
        return make_dialogue_dump(resource_name)

    def dump_item(self, game_root: Path, resource_name: str) -> ItmDump:
        self._record_dump(resource_name)
        if resource_name == "SCROLL.ITM":
            return make_item_dump(
                resource_name,
                category=11,
                ground_icon="GSCRL01",
            )
        if resource_name == "SWORD.ITM":
            return make_item_dump(
                resource_name,
                category=20,
                ground_icon=None,
            )
        return make_item_dump(resource_name)

    def read_raw_resource(self, game_root: Path, resource_name: str) -> bytes:
        self._record_dump(resource_name)
        return self.raw_resources[resource_name]

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


@pytest.mark.anyio
async def test_metadata_extraction_publishes_engine_definitions(
    tmp_path: Path,
) -> None:
    client = MetadataClient(metadata_resources())
    database = PipelineDatabase(tmp_path / "metadata.lancedb")
    summary = extract_metadata(client, database, tmp_path, workers=6)
    reader = await PipelineReader.open(database.path)
    try:
        races = await reader.races(RaceQuery(page_size=100))
        classes = await reader.classes(ClassQuery(class_id=2, page_size=10))
        kits = await reader.kits(KitQuery(class_id=2, page_size=10))
    finally:
        reader.close()

    assert summary.status == "complete"
    run = (
        lancedb.connect(database.path)
        .open_table("extraction_runs")
        .search()
        .to_pydantic(ExtractionRunRecord)
    )[0]
    assert (run.run_kind, run.resources_discovered, run.details_extracted) == (
        RunKind.METADATA,
        len(client.resources),
        len(client.resources),
    )
    human = next(race for race in races.items if race.race_id == 1)
    beholder = next(race for race in races.items if race.race_id == 123)
    assert human.campaign_texts[0].record.description == "text 101"
    assert beholder.lore is not None
    assert beholder.lore.help_text == "text 209"
    assert classes.items[0].description == "text 111"
    assert kits.items[0].help_text == "text 122"


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


def test_portrait_extraction_deduplicates_and_persists_only_referenced_bmps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = FakeIeCli()
    client.portraits = [
        make_portrait_resource("UNUSED.BMP"),
        make_portrait_resource("MINSCM.BMP"),
        make_portrait_resource("AERIES.BMP"),
    ]
    client.raw_resources = {
        "AERIES.BMP": _bmp(54, 84, (1, 2, 3)),
        "MINSCM.BMP": _bmp(169, 266, (4, 5, 6)),
    }
    database = PipelineDatabase(tmp_path / "portraits.lancedb")
    monkeypatch.setattr(
        database,
        "referenced_portrait_resrefs",
        lambda: {"AERIES", "aeries", "minscm"},
    )
    replacements: list[list[PortraitImage]] = []
    replace_portraits = database.replace_portraits

    def replace(run_id: str, images: Sequence[PortraitImage]) -> None:
        replacements.append(list(images))
        replace_portraits(run_id, images)

    monkeypatch.setattr(database, "replace_portraits", replace)
    summary = extract_portraits(client, database, tmp_path, workers=2)

    assert (
        summary.discovered,
        summary.attempted,
        summary.extracted,
        summary.skipped,
        summary.status,
    ) == (3, 2, 2, 1, "complete")
    assert sorted(client.dumped, key=str.casefold) == ["AERIES.BMP", "MINSCM.BMP"]
    assert [[image.resref for image in images] for images in replacements] == [["AERIES", "MINSCM"]]
    portraits = database.portraits()
    assert [(row.resref, row.width, row.height) for row in portraits] == [
        ("AERIES", 54, 84),
        ("MINSCM", 169, 266),
    ]
    assert all(row.png.startswith(b"\x89PNG\r\n\x1a\n") for row in portraits)


def test_portrait_extraction_failure_is_finalized_and_propagated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = OSError("cannot read portrait")
    client = FakeIeCli()
    client.portraits = [make_portrait_resource()]

    def fail(_game_root: Path, _resource_name: str) -> bytes:
        raise expected

    monkeypatch.setattr(client, "read_raw_resource", fail)
    database = PipelineDatabase(tmp_path / "portrait-failure.lancedb")
    monkeypatch.setattr(database, "referenced_portrait_resrefs", lambda: {"aeries"})
    with pytest.raises(OSError) as raised:
        extract_portraits(client, database, tmp_path)

    assert raised.value is expected
    run = (
        lancedb.connect(database.path)
        .open_table("extraction_runs")
        .search()
        .to_pydantic(ExtractionRunRecord)
    )[0]
    assert (
        run.run_kind,
        run.status,
        run.resources_discovered,
        run.details_attempted,
        run.details_extracted,
        run.error,
    ) == (RunKind.PORTRAITS, "failed", 1, 1, 0, str(expected))
    assert database.portraits() == []


def test_readable_extraction_scans_all_items_and_publishes_only_texts(
    tmp_path: Path,
) -> None:
    client = FakeIeCli()
    client.items = [
        make_item_resource("BOOK.ITM"),
        make_item_resource("SCROLL.ITM"),
        make_item_resource("SWORD.ITM"),
        make_item_resource("BROKEN.ITM"),
    ]
    client.failures.add("BROKEN.ITM")
    progress: list[ExtractionProgress] = []
    database = PipelineDatabase(tmp_path / "readables.lancedb")

    summary = extract_readable_items(
        client,
        database,
        tmp_path,
        workers=2,
        progress=progress.append,
    )

    assert (
        summary.discovered,
        summary.attempted,
        summary.extracted,
        summary.failed,
        summary.status,
    ) == (4, 4, 2, 1, "complete_with_errors")
    assert summary.skipped == 1
    assert progress == [ExtractionProgress(completed=4, total=4, succeeded=3, failed=1)]
    assert sorted(client.dumped) == ["BOOK.ITM", "BROKEN.ITM", "SCROLL.ITM", "SWORD.ITM"]
    assert [(item.resource_name, item.kind) for item in database.readable_items()] == [
        ("BOOK.ITM", "book"),
        ("SCROLL.ITM", "scroll"),
    ]

    client.items = [make_item_resource("SCROLL.ITM")]
    client.failures.clear()
    client.dumped.clear()
    rerun = extract_readable_items(client, database, tmp_path)

    assert (rerun.extracted, client.dumped) == (1, ["SCROLL.ITM"])
    assert [item.resource_name for item in database.readable_items()] == ["SCROLL.ITM"]


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
        run_id: str,
        details: Sequence[CharacterExtraction],
        failures: Sequence[tuple[str, str]],
    ) -> None:
        nonlocal save_count
        save_count += 1
        if save_count == 2:
            raise OSError("simulated Lance write failure")
        original_save(run_id, details, failures)

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
