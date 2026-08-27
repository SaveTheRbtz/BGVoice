"""Shared pytest configuration and representative database fixtures."""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.scenarios import build_scenario_database


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def scenario_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_scenario_database(tmp_path_factory.mktemp("scenario") / "pipeline.lancedb")


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
