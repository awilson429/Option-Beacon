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
