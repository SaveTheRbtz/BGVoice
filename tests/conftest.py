"""Shared pytest configuration and representative database fixtures."""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from bgvoice.database import PipelineDatabase
from tests.scenarios import build_scenario_database


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def scenario_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_scenario_database(tmp_path_factory.mktemp("scenario") / "pipeline.lancedb")


@pytest.fixture(scope="session")
def empty_database_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create the empty application schema once for isolated mutation tests."""
    return PipelineDatabase(tmp_path_factory.mktemp("empty") / "pipeline.lancedb").path


@pytest.fixture
def empty_database(empty_database_template: Path, tmp_path: Path) -> PipelineDatabase:
    """Return an isolated empty database without rebuilding every table and index."""
    target = tmp_path / "pipeline.lancedb"
    shutil.copytree(empty_database_template, target)
    return PipelineDatabase(target)


@pytest.fixture
def scenario_database(scenario_template: Path, tmp_path: Path) -> Path:
    """Return an isolated copy for tests that mutate the representative database."""
    target = tmp_path / "pipeline.lancedb"
    shutil.copytree(scenario_template, target)
    return target


@pytest.fixture(scope="session")
def shared_scenario_database(scenario_template: Path) -> Iterator[Path]:
    """Share the immutable representative database between read-only tests."""
    yield scenario_template
