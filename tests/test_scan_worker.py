from datetime import datetime, timezone

from optionbeacon.worker.scan_once import run_scan_once
from trade_repository import TradeRepository


def test_scan_worker_records_success_and_releases_lock(tmp_path, monkeypatch):
    repo = TradeRepository(tmp_path / "state.db", database_url="")
    monkeypatch.setattr(
        "optionbeacon.worker.scan_once.load_trade_outcomes",
        lambda: [],
    )
    saved = []
    result = run_scan_once(
        repository=repo,
        symbol_groups_loader=lambda: ({"Core": ["SPY"]}, "test", ""),
        signal_generator=lambda symbol: {
            "symbol": symbol,
            "signal": "WAIT",
            "price": 500,
        },
        snapshot_writer=lambda results: saved.append(results),
    )

    assert result == 0
    assert saved[0]["SPY"]["price"] == 500
    health = repo.get_scan_health()
    assert health["last_success_at"] is not None
    assert health["last_symbols_processed"] == 1
    assert repo.acquire_scan_lock() is not None


def test_scan_worker_failure_records_error_and_returns_nonzero(tmp_path):
    repo = TradeRepository(tmp_path / "state.db", database_url="")

    def fail():
        raise RuntimeError("provider token secret")

    result = run_scan_once(
        repository=repo,
        symbol_groups_loader=fail,
        snapshot_writer=lambda results: None,
    )

    assert result == 1
    health = repo.get_scan_health()
    assert health["last_error_at"] is not None
    assert "secret" not in health["last_error_message"]


def test_overlapping_scan_is_rejected(tmp_path):
    repo = TradeRepository(tmp_path / "state.db", database_url="")
    owner = repo.acquire_scan_lock()
    result = run_scan_once(repository=repo)
    repo.release_scan_lock("optionbeacon-scanner", owner)

    assert result == 2
