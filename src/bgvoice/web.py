"""Connect API and production SPA host for the read-only pipeline browser."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from lancedb.expr import col

from bgvoice.reader import PipelineReader
from bgvoice.storage_records import PortraitImageRecord
from bgvoice.v1.pipeline_connect import PipelineServiceASGIApplication
from bgvoice.web_contract import INSTALLATION_ID, resource_id
from bgvoice.web_service import PipelineService


def create_app(
    database_path: Path = Path("data/bgvoice.lancedb"),
    frontend_dist: Path | None = None,
) -> FastAPI:
    """Serve the generated Connect contract and compiled React application."""
    database: PipelineReader | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal database
        database = await PipelineReader.open(database_path)
        try:
            yield
        finally:
            database.close()
            database = None

    def reader() -> PipelineReader:
        assert database is not None, "pipeline reader is unavailable outside app lifespan"
        return database

    app = FastAPI(
        title="BGVoice Pipeline Browser",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.mount(
        "/connect",
        PipelineServiceASGIApplication(PipelineService(reader)),
        name="connect",
    )

    @app.get(
        "/v1/installations/{installation}/portraits/{portrait}:download",
        include_in_schema=False,
    )
    async def download_portrait(installation: str, portrait: str) -> Response:
        if installation != INSTALLATION_ID:
            raise HTTPException(status_code=404, detail="installation not found")
        resrefs = cast(
            list[str],
            (await reader().portrait_images_table.query().select(["resref"]).to_arrow())
            .column("resref")
            .to_pylist(),
        )
        resref = next((value for value in resrefs if resource_id(value) == portrait), None)
        if resref is None:
            raise HTTPException(status_code=404, detail="portrait not found")
        rows = cast(
            list[PortraitImageRecord],
            await reader()
            .portrait_images_table.query()
            .where(col("resref") == resref)
            .limit(1)
            .to_pydantic(PortraitImageRecord),
        )
        assert len(rows) == 1, f"portrait index returned {len(rows)} rows for {resref!r}"
        return Response(
            content=rows[0].png,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    dist = (frontend_dist or Path("frontend/dist")).expanduser().resolve()
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{spa_path:path}", include_in_schema=False)
        def spa(spa_path: str) -> FileResponse:
            candidate = (dist / spa_path).resolve()
            if spa_path and candidate.is_relative_to(dist) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app
