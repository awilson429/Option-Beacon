"""Default-suite isolation from production configuration and provider networks."""

from __future__ import annotations

import os

import pytest


PRODUCTION_ENVIRONMENT_KEYS = (
    "DATABASE_URL",
    "TRADIER_ACCESS_TOKEN",
    "FINNHUB_API_KEY",
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
    "OPTIONBEACON_ENVIRONMENT",
    "OPTIONBEACON_REQUIRE_DURABLE_STORAGE",
)


def _blocked(service):
    def block(*_args, **_kwargs):
        raise AssertionError(
            f"Unexpected {service} network call in the default test suite. "
            "Inject a fake provider or mark an explicit integration test."
        )

    return block


@pytest.fixture(autouse=True)
def isolate_production_services(request, monkeypatch):
    """Make every ordinary test local-only, regardless of the host environment."""
    live = request.node.get_closest_marker("live_provider")
    integration = request.node.get_closest_marker("network_integration")
    if live and os.getenv("OPTIONBEACON_RUN_LIVE_PROVIDER_TESTS", "").lower() not in {
        "1", "true", "yes", "on",
    }:
        pytest.skip("live provider tests require OPTIONBEACON_RUN_LIVE_PROVIDER_TESTS=true")

    if live:
        return

    for key in PRODUCTION_ENVIRONMENT_KEYS:
        monkeypatch.delenv(key, raising=False)

    if integration:
        return

    import finnhub_universe
    import optionbeacon_live
    from option_trade_engine import TradierOptionChainProvider

    monkeypatch.setattr(
        TradierOptionChainProvider,
        "expirations",
        _blocked("Tradier"),
    )
    monkeypatch.setattr(
        TradierOptionChainProvider,
        "chain",
        _blocked("Tradier"),
    )
    monkeypatch.setattr(optionbeacon_live, "download_data", _blocked("Yahoo/yfinance"))
    monkeypatch.setattr(finnhub_universe, "urlopen", _blocked("Finnhub"))

    try:
        import psycopg2
    except ImportError:
        pass
    else:
        monkeypatch.setattr(psycopg2, "connect", _blocked("PostgreSQL/Neon"))
