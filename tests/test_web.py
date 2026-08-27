"""Thin-host integration tests for Connect, portraits, and the compiled SPA."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bgvoice.database import PipelineDatabase
from bgvoice.model_types import (
    PortraitImage,
    ResourceSource,
    RunKind,
    RunStatus,
    SourceKind,
)
from bgvoice.web import create_app
from bgvoice.web_contract import INSTALLATION_ID, resource_id
from tests.test_reader import web_database as web_database


@pytest.fixture
def portrait_database(web_database: Path) -> Path:
    database = PipelineDatabase(web_database)
    run_id = database.start_run(
        web_database.parent,
        "iecli test",
        run_kind=RunKind.PORTRAITS,
    )
    database.replace_portraits(
        run_id,
        [
            PortraitImage(
                resref="AERIES",
                source=ResourceSource(
                    kind=SourceKind.OVERRIDE,
                    path=str(web_database.parent / "AERIES.BMP"),
                ),
                width=54,
                height=84,
                png=b"\x89PNG\r\n\x1a\nfixture",
            ),
            PortraitImage(
                resref="R#ISRAL",
                source=ResourceSource(
                    kind=SourceKind.OVERRIDE,
                    path=str(web_database.parent / "R#ISRAL.BMP"),
                ),
                width=54,
                height=84,
                png=b"\x89PNG\r\n\x1a\nnonconforming",
            ),
        ],
    )
    database.finish_run(
        run_id,
        status=RunStatus.COMPLETE,
        attempted=2,
        extracted=2,
        failures=0,
    )
    return web_database


def test_app_serves_connect_and_spa(web_database: Path, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<h1>BGVoice SPA</h1>", encoding="utf-8")
    (assets / "app.css").write_text("body{}", encoding="utf-8")
    (dist / "robots.txt").write_text("User-agent: *", encoding="utf-8")

    with TestClient(create_app(web_database, dist)) as client:
        response = client.post(
            "/connect/bgvoice.v1.PipelineService/GetInstallation",
            headers={
                "content-type": "application/json",
                "connect-protocol-version": "1",
            },
            json={"name": f"installations/{INSTALLATION_ID}"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == f"installations/{INSTALLATION_ID}"

        assert "BGVoice SPA" in client.get("/voices/aerie").text
        assert client.get("/assets/app.css").text == "body{}"
        assert client.get("/robots.txt").text == "User-agent: *"
        assert client.get("/missing-route").text == "<h1>BGVoice SPA</h1>"


def test_app_downloads_portraits_as_png(portrait_database: Path) -> None:
    with TestClient(create_app(portrait_database)) as client:
        response = client.get(
            f"/v1/installations/{INSTALLATION_ID}/portraits/{resource_id('AERIES')}:download"
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "public, max-age=86400"
        assert response.content == b"\x89PNG\r\n\x1a\nfixture"
        assert (
            client.get(
                f"/v1/installations/{INSTALLATION_ID}/portraits/{resource_id('R#ISRAL')}:download"
            ).content
            == b"\x89PNG\r\n\x1a\nnonconforming"
        )
        assert (
            client.get(
                f"/v1/installations/unknown/portraits/{resource_id('AERIES')}:download"
            ).status_code
            == 404
        )
