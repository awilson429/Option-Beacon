"""OptionBeacon read-only FastAPI application."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import capital, health, market, options_desk, scanner, system, trade_desk, trades


def cors_origins(environ=None) -> list[str]:
    environment = os.environ if environ is None else environ
    raw = environment.get("OPTIONBEACON_CORS_ORIGINS", "http://localhost:3000")
    return [value.strip() for value in raw.split(",") if value.strip() and value.strip() != "*"]


def create_app(*, service=None) -> FastAPI:
    application = FastAPI(title="OptionBeacon API", version="1.0.0",
        description="Read-only API boundary over authoritative OptionBeacon state.")
    if service is not None:
        application.state.service = service
    application.add_middleware(CORSMiddleware, allow_origins=cors_origins(), allow_credentials=True,
        allow_methods=["GET"], allow_headers=["Accept", "Content-Type"])
    for router in (health.router, market.router, trade_desk.router, options_desk.router, trades.router, scanner.router, system.router, capital.router):
        application.include_router(router, prefix="/api")
    return application


app = create_app()
