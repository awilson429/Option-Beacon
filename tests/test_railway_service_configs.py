from pathlib import Path


def test_primary_railway_service_keeps_authoritative_worker_entrypoint():
    railway = Path("railway.toml").read_text(encoding="utf-8")

    assert 'startCommand = "python -m optionbeacon.worker.run"' in railway
    assert "optionbeacon.worker.intraday" not in railway


def test_intraday_railway_service_has_dedicated_worker_entrypoint():
    railway = Path("railway.intraday.toml").read_text(encoding="utf-8")

    assert (
        'startCommand = "python -m optionbeacon.worker.intraday '
        '--interval-seconds 60"' in railway
    )
    assert "optionbeacon.worker.run\"" not in railway
    assert 'restartPolicyType = "ON_FAILURE"' in railway
    assert "restartPolicyMaxRetries = 10" in railway


def test_api_railway_template_is_fastapi_and_does_not_replace_the_worker():
    api = Path("railway.api.toml").read_text(encoding="utf-8")
    worker = Path("railway.toml").read_text(encoding="utf-8")
    assert "uvicorn api.main:app" in api
    assert "healthcheckPath = \"/api/health\"" in api
    assert "--workers" not in api
    assert 'startCommand = "python -m optionbeacon.worker.run"' in worker
    assert "uvicorn" not in worker
