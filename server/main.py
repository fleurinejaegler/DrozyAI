import asyncio
from contextlib import asynccontextmanager
import logging
import secrets
import sqlite3

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from .config import Config
from .schema import Batch
from .storage import BatchConflict, Store

log = logging.getLogger("garmin")


def create_app(config: Config | None = None):
    config = config or Config.from_env()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(config)
        log.info("Receiver ready; writing CSVs to %s", config.data_dir.resolve())
        async def report_status():
            last = None
            while True:
                current = app.state.store.status()
                if current["watch"] != last:
                    log.info("Watch connection: %s | last upload: %s", current["watch"], current["last_upload_epoch_s"])
                    last = current["watch"]
                await asyncio.sleep(5)
        monitor = asyncio.create_task(report_status())
        try:
            yield
        finally:
            monitor.cancel()
            try:
                await monitor
            except asyncio.CancelledError:
                pass
            app.state.store.close()

    app = FastAPI(title="DrowsyAlert Garmin sensor receiver", lifespan=lifespan)

    @app.get("/health")
    def health():
        # Public liveness only; sensor/session information requires authentication.
        return {"status": "ok", "service": "garmin_receiver", "schema_version": 1}

    def authenticate(authorization):
        if not authorization or not secrets.compare_digest(authorization.encode("utf-8"), ("Bearer " + config.token).encode("utf-8")):
            raise HTTPException(401, "Invalid API token", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/garmin/status")
    def status(authorization: str | None = Header(default=None)):
        authenticate(authorization)
        return app.state.store.status()

    @app.post("/garmin/data")
    async def data(request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > config.max_body_bytes:
                raise HTTPException(413, "Batch exceeds 64 KiB; reduce batch size")
        try:
            batch = Batch.model_validate_json(bytes(body))
        except ValidationError as ex:
            log.warning("Rejected sensor batch: schema/measurement validation failed")
            raise HTTPException(422, ex.errors(include_input=False, include_context=False)) from ex
        try:
            return await run_in_threadpool(app.state.store.ingest, batch)
        except BatchConflict as ex:
            log.warning("Rejected conflicting/out-of-order batch")
            raise HTTPException(409, str(ex)) from ex
        except (OSError, RuntimeError, sqlite3.Error) as ex:
            log.error("CSV storage failed; batch not acknowledged: %s", type(ex).__name__)
            raise HTTPException(503, "Storage unavailable; retry same batch") from ex

    return app
