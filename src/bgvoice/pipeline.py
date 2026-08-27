"""Concurrent, resumable extraction of EET resources."""

from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

from pydantic import PositiveInt

from bgvoice.database import PipelineDatabase
from bgvoice.iecli import (
    CharacterIeCliClient,
    DialogueIeCliClient,
    MetadataIeCliClient,
    PortraitIeCliClient,
)
from bgvoice.metadata import build_metadata
from bgvoice.models import (
    CharacterExtraction,
    CreResource,
    DialogueExtraction,
    DlgResource,
    ExtractionProgress,
    ExtractionSummary,
    PortraitImage,
    PortraitResource,
    RunKind,
    RunStatus,
    TerminalRunStatus,
)

type ProgressCallback = Callable[[ExtractionProgress], None]
type CommitCallback = Callable[[int, int], None]
type Failure = tuple[str, str]

_WRITE_BATCH_SIZE = 100


def extract_metadata(
    client: MetadataIeCliClient,
    database: PipelineDatabase,
    game_root: Path,
    *,
    workers: PositiveInt = 8,
) -> ExtractionSummary:
    """Import engine identifiers and campaign-specific resources."""
    root = game_root.expanduser().resolve()
    iecli_version = client.version()
    run_id = database.start_run(root, iecli_version, run_kind=RunKind.METADATA)
    discovered = 0

    try:
        metadata = build_metadata(client, root, workers=int(workers))
        discovered = metadata.source_resource_count
        database.replace_metadata(run_id, metadata)
        database.finish_run(
            run_id,
            status=RunStatus.COMPLETE,
            attempted=discovered,
            extracted=discovered,
            failures=0,
        )
        return ExtractionSummary(
            run_id=run_id,
            game_root=root,
            database_path=database.path,
            iecli_version=iecli_version,
            discovered=discovered,
            attempted=discovered,
            extracted=discovered,
            failed=0,
            skipped=0,
            status=RunStatus.COMPLETE,
        )
    except BaseException as error:
        try:
            database.finish_run(
                run_id,
                status=RunStatus.FAILED,
                discovered=discovered,
                attempted=discovered,
                extracted=0,
                failures=0,
                error=str(error),
            )
        except BaseException as finalization_error:
            error.add_note(f"Failed to finalize extraction run {run_id}: {finalization_error!r}")
        raise


def extract_portraits(
    client: PortraitIeCliClient,
    database: PipelineDatabase,
    game_root: Path,
    *,
    workers: PositiveInt = 8,
) -> ExtractionSummary:
    """Extract each effective BMP referenced by at least one character."""
    root = game_root.expanduser().resolve()
    iecli_version = client.version()
    run_id = database.start_run(root, iecli_version, run_kind=RunKind.PORTRAITS)
    discovered = attempted = extracted = 0

    try:
        resources = client.list_portraits(root)
        discovered = len(resources)
        resources_by_resref = {resource.resref.casefold(): resource for resource in resources}
        referenced = {resref.casefold() for resref in database.referenced_portrait_resrefs()}
        targets = [
            resources_by_resref[resref]
            for resref in sorted(referenced & resources_by_resref.keys())
        ]
        attempted = len(targets)

        def extract(resource: PortraitResource) -> PortraitImage:
            return PortraitImage.from_bmp(
                resource,
                client.read_raw_resource(root, resource.resource_name),
            )

        with ThreadPoolExecutor(
            max_workers=int(workers),
            thread_name_prefix="iecli-portrait",
        ) as executor:
            images = list(executor.map(extract, targets))

        database.replace_portraits(run_id, images)
        extracted = len(images)
        database.finish_run(
            run_id,
            status=RunStatus.COMPLETE,
            discovered=discovered,
            attempted=attempted,
            extracted=extracted,
            failures=0,
        )
        return ExtractionSummary(
            run_id=run_id,
            game_root=root,
            database_path=database.path,
            iecli_version=iecli_version,
            discovered=discovered,
            attempted=attempted,
            extracted=extracted,
            failed=0,
            skipped=discovered - attempted,
            status=RunStatus.COMPLETE,
        )
    except BaseException as error:
        try:
            database.finish_run(
                run_id,
                status=RunStatus.FAILED,
                discovered=discovered,
                attempted=attempted,
                extracted=extracted,
                failures=0,
                error=str(error),
            )
        except BaseException as finalization_error:
            error.add_note(f"Failed to finalize extraction run {run_id}: {finalization_error!r}")
        raise


def extract_characters(
    client: CharacterIeCliClient,
    database: PipelineDatabase,
    game_root: Path,
    *,
    include_details: bool = True,
    workers: PositiveInt = 8,
    refresh: bool = False,
    progress: ProgressCallback | None = None,
) -> ExtractionSummary:
    """Inventory every effective CRE and optionally extract its details."""
    root = game_root.expanduser().resolve()

    def select_targets(resources: Sequence[CreResource]) -> list[CreResource]:
        if not include_details:
            return []
        target_names = database.detail_targets(refresh=refresh)
        return [resource for resource in resources if resource.resource_name in target_names]

    def extract_details(
        run_id: str,
        resources: Sequence[CreResource],
        committed: CommitCallback,
    ) -> None:
        _extract_resources(
            resources,
            root,
            name=lambda resource: resource.resource_name,
            dump=client.dump_creature,
            build=CharacterExtraction.from_dump,
            save=lambda details, failures: database.apply_detail_batch(run_id, details, failures),
            workers=int(workers),
            thread_name_prefix="iecli-cre",
            progress=progress,
            committed=committed,
        )

    return _run_extraction(
        database,
        root,
        client.version(),
        run_kind=RunKind.CHARACTERS,
        discover=client.list_creatures,
        store_inventory=database.replace_inventory,
        select_targets=select_targets,
        extract_details=extract_details,
    )


def extract_dialogues(
    client: DialogueIeCliClient,
    database: PipelineDatabase,
    game_root: Path,
    *,
    workers: PositiveInt = 8,
    refresh: bool = False,
    progress: ProgressCallback | None = None,
) -> ExtractionSummary:
    """Inventory every effective DLG and extract its metrics and lines."""
    root = game_root.expanduser().resolve()

    def select_targets(_resources: Sequence[DlgResource]) -> list[str]:
        return database.dialogue_targets(refresh=refresh)

    def extract_details(
        run_id: str,
        resource_names: Sequence[str],
        committed: CommitCallback,
    ) -> None:
        _extract_resources(
            resource_names,
            root,
            name=lambda resource_name: resource_name,
            dump=client.dump_dialogue,
            build=lambda _resource_name, dump: DialogueExtraction.from_dump(dump),
            save=lambda details, failures: database.apply_dialogue_batch(run_id, details, failures),
            workers=int(workers),
            thread_name_prefix="iecli-dlg",
            progress=progress,
            committed=committed,
        )

    return _run_extraction(
        database,
        root,
        client.version(),
        run_kind=RunKind.DIALOGUES,
        discover=client.list_dialogues,
        store_inventory=database.replace_dialogue_inventory,
        select_targets=select_targets,
        extract_details=extract_details,
    )


def _run_extraction[Inventory, Target](
    database: PipelineDatabase,
    game_root: Path,
    iecli_version: str,
    *,
    run_kind: RunKind,
    discover: Callable[[Path], list[Inventory]],
    store_inventory: Callable[[str, Sequence[Inventory]], None],
    select_targets: Callable[[Sequence[Inventory]], list[Target]],
    extract_details: Callable[[str, Sequence[Target], CommitCallback], None],
) -> ExtractionSummary:
    """Run the shared inventory, detail, and durable finalization lifecycle."""
    run_id = database.start_run(game_root, iecli_version, run_kind=run_kind)
    discovered = attempted = extracted = failed = 0

    try:
        inventory = discover(game_root)
        discovered = len(inventory)
        store_inventory(run_id, inventory)

        targets = select_targets(inventory)
        attempted = len(targets)

        def record_commit(succeeded: int, failures: int) -> None:
            nonlocal extracted, failed
            extracted += succeeded
            failed += failures

        extract_details(run_id, targets, record_commit)

        status: TerminalRunStatus = RunStatus.COMPLETE_WITH_ERRORS if failed else RunStatus.COMPLETE
        database.finish_run(
            run_id,
            status=status,
            attempted=attempted,
            extracted=extracted,
            failures=failed,
        )
        return ExtractionSummary(
            run_id=run_id,
            game_root=game_root,
            database_path=database.path,
            iecli_version=iecli_version,
            discovered=discovered,
            attempted=attempted,
            extracted=extracted,
            failed=failed,
            skipped=discovered - attempted,
            status=status,
        )
    except BaseException as error:
        try:
            database.finish_run(
                run_id,
                status=RunStatus.FAILED,
                discovered=discovered,
                attempted=attempted,
                extracted=extracted,
                failures=failed,
                error=str(error),
            )
        except BaseException as finalization_error:
            error.add_note(f"Failed to finalize extraction run {run_id}: {finalization_error!r}")
        raise


def _extract_resources[Resource, Dump, Detail](
    resources: Sequence[Resource],
    game_root: Path,
    *,
    name: Callable[[Resource], str],
    dump: Callable[[Path, str], Dump],
    build: Callable[[Resource, Dump], Detail],
    save: Callable[[Sequence[Detail], Sequence[Failure]], None],
    workers: int,
    thread_name_prefix: str,
    progress: ProgressCallback | None,
    committed: CommitCallback,
) -> None:
    """Extract resources concurrently, isolating failures and writing bounded batches."""
    if not resources:
        return

    succeeded = failed = 0
    details: list[Detail] = []
    failures: list[Failure] = []

    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=thread_name_prefix)
    try:
        futures: dict[Future[Dump], Resource] = {
            executor.submit(dump, game_root, name(resource)): resource for resource in resources
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            resource = futures[future]
            try:
                details.append(build(resource, future.result()))
                succeeded += 1
            except Exception as error:  # A malformed resource must not abort unrelated work.
                failures.append((name(resource), str(error)))
                failed += 1

            if len(details) + len(failures) >= _WRITE_BATCH_SIZE:
                save(details, failures)
                committed(len(details), len(failures))
                details.clear()
                failures.clear()

            if progress is not None and (
                completed == len(resources) or completed % _WRITE_BATCH_SIZE == 0
            ):
                progress(
                    ExtractionProgress(
                        completed=completed,
                        total=len(resources),
                        succeeded=succeeded,
                        failed=failed,
                    )
                )
    except BaseException:
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown()

    if details or failures:
        save(details, failures)
        committed(len(details), len(failures))
