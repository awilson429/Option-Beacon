import json
import threading
from datetime import datetime, timedelta, timezone

from optionbeacon.worker.scan_once import run_scan_once
from trade_repository import RepositoryUnavailable, TradeRepository, utc_iso


NOW = datetime(2026, 8, 3, 18, tzinfo=timezone.utc)


def repository(tmp_path):
    return TradeRepository(tmp_path / "locks.db", database_url="")


def test_normal_lock_acquisition_release_and_owner_mismatch(tmp_path):
    repo = repository(tmp_path)
    assert repo.acquire_scan_lock("railway-primary", owner_id="deployment-a") == "deployment-a"
    assert repo.acquire_scan_lock("railway-primary", owner_id="deployment-b") is None
    assert repo.release_scan_lock("railway-primary", "deployment-b") is False
    assert repo.release_scan_lock("railway-primary", "deployment-a") is True
    assert repo.get_scan_lock("railway-primary") is None


def test_concurrent_workers_only_one_acquires(tmp_path):
    database = tmp_path / "concurrent.db"
    repositories = [
        TradeRepository(database, database_url=""),
        TradeRepository(database, database_url=""),
    ]
    barrier = threading.Barrier(2)
    outcomes = []

    def acquire(repo, owner):
        barrier.wait()
        outcomes.append(repo.acquire_scan_lock("railway-primary", owner_id=owner))

    threads = [
        threading.Thread(target=acquire, args=(repo, owner))
        for repo, owner in zip(repositories, ("a", "b"))
    ]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert sum(value is not None for value in outcomes) == 1


def test_stale_deployment_lock_is_recovered_but_live_lock_is_not(tmp_path, monkeypatch):
    import trade_repository
    repo = repository(tmp_path)
    monkeypatch.setattr(trade_repository, "utc_now", lambda: NOW)
    assert repo.acquire_scan_lock("railway-primary", owner_id="old-deployment", ttl_seconds=60)
    monkeypatch.setattr(trade_repository, "utc_now", lambda: NOW + timedelta(seconds=30))
    assert repo.acquire_scan_lock("railway-primary", owner_id="new-deployment") is None
    monkeypatch.setattr(trade_repository, "utc_now", lambda: NOW + timedelta(seconds=61))
    assert repo.acquire_scan_lock("railway-primary", owner_id="new-deployment") == "new-deployment"


def test_same_worker_recovers_after_transient_release_failure(tmp_path):
    repo = repository(tmp_path)
    assert repo.acquire_scan_lock("railway-primary", owner_id="same-process")
    assert repo.acquire_scan_lock("railway-primary", owner_id="same-process") == "same-process"


def test_paper_exception_releases_lock_and_next_cycle_resumes(tmp_path):
    repo = repository(tmp_path)
    common = dict(
        repository=repo, scanner_id="railway-primary",
        symbol_groups_loader=lambda: ({"Core": ["SPY"]}, "test", ""),
        signal_generator=lambda symbol: {"symbol": symbol, "signal": "WAIT", "price": 500},
        snapshot_writer=lambda results: None,
    )
    assert run_scan_once(**common, paper_executor=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("paper failed"))) == 1
    assert repo.get_scan_lock("railway-primary") is None
    assert run_scan_once(**common, paper_executor=lambda *args, **kwargs: None) == 0


def test_provider_failure_releases_lock(tmp_path):
    repo = repository(tmp_path)
    assert run_scan_once(
        repository=repo, scanner_id="railway-primary",
        symbol_groups_loader=lambda: ({"Core": ["SPY"]}, "test", ""),
        signal_generator=lambda symbol: (_ for _ in ()).throw(RuntimeError("provider")),
        snapshot_writer=lambda results: None,
    ) == 1
    assert repo.get_scan_lock("railway-primary") is None


def test_release_database_failure_is_logged_and_lease_remains_recoverable(tmp_path, caplog):
    repo = repository(tmp_path)
    original_release = repo.release_scan_lock
    repo.release_scan_lock = lambda *args: (_ for _ in ()).throw(RepositoryUnavailable("down"))
    with caplog.at_level("ERROR"):
        result = run_scan_once(
            repository=repo, scanner_id="railway-primary", lock_owner_id="deployment-a",
            symbol_groups_loader=lambda: ({"Core": ["SPY"]}, "test", ""),
            signal_generator=lambda symbol: {"symbol": symbol, "signal": "WAIT", "price": 500},
            snapshot_writer=lambda results: None, paper_executor=lambda *args, **kwargs: None,
        )
    assert result == 0
    assert any("scanner_lock_release_failed" in record.message for record in caplog.records)
    repo.release_scan_lock = original_release
    assert repo.get_scan_lock("railway-primary")["owner_id"] == "deployment-a"


def test_second_worker_never_reaches_paper_execution(tmp_path):
    repo = repository(tmp_path)
    repo.acquire_scan_lock("railway-primary", owner_id="legitimate-worker")
    called = []
    assert run_scan_once(
        repository=repo, scanner_id="railway-primary", lock_owner_id="second-worker",
        paper_executor=lambda *args, **kwargs: called.append(True),
    ) == 2
    assert called == []
