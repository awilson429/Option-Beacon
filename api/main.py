"""OptionBeacon read-only FastAPI application."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies import default_service
from api.live_events import LiveEventHub, run_identity_watcher, watch_seconds
from api.routes import (capital, health, live, market, options_desk, provenance, scanner,
                        system, trade_desk, trades)

logger = logging.getLogger(__name__)


def cors_origins(environ=None) -> list[str]:
    environment = os.environ if environ is None else environ
    raw = environment.get("OPTIONBEACON_CORS_ORIGINS", "http://localhost:3000")
    return [value.strip() for value in raw.split(",") if value.strip() and value.strip() != "*"]


def create_app(*, service=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        hub = LiveEventHub()
        application.state.live_events = hub
        watched = service if service is not None else getattr(application.state, "service", None) or default_service()
        stop = asyncio.Event()
        interval = watch_seconds()
        logger.info("sse.watch.started interval=%s", interval)
        task = asyncio.create_task(run_identity_watcher(watched, hub, stop, interval=interval), name="optionbeacon-sse-watch")
        try:
            yield
        finally:
            logger.info("sse.watch.stopped")
            stop.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    application = FastAPI(title="OptionBeacon API", version="1.0.0",
        description="Read-only API boundary over authoritative OptionBeacon state.",
        lifespan=lifespan)
    if service is not None:
        application.state.service = service
    application.add_middleware(CORSMiddleware, allow_origins=cors_origins(), allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Accept", "Content-Type", "Last-Event-ID", "Cache-Control"])
    for router in (health.router, live.router, market.router, trade_desk.router, options_desk.router,
                   trades.router, provenance.router, scanner.router, system.router,
                   capital.router):
        application.include_router(router, prefix="/api")
    return application


app = create_app()
