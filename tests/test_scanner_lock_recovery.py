import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from optionbeacon.worker.lock_lease import ScannerLockLease, ScannerLockOwnershipLost
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


def test_live_lease_cannot_be_extended_by_reacquisition_even_by_same_owner(tmp_path):
    repo = repository(tmp_path)
    assert repo.acquire_scan_lock("railway-primary", owner_id="same-process")
    assert repo.acquire_scan_lock("railway-primary", owner_id="same-process") is None


def test_exact_owner_renews_and_non_owner_cannot_renew(tmp_path, monkeypatch):
    import trade_repository
    repo = repository(tmp_path)
    monkeypatch.setattr(trade_repository, "utc_now", lambda: NOW)
    assert repo.acquire_scan_lock(
        "railway-primary", owner_id="deployment-a", ttl_seconds=60
    )
    original_expiry = repo.get_scan_lock("railway-primary")["expires_at"]
    monkeypatch.setattr(trade_repository, "utc_now", lambda: NOW + timedelta(seconds=30))
    assert repo.renew_scan_lock(
        "railway-primary", "deployment-a", ttl_seconds=60
    ) is True
    renewed_expiry = repo.get_scan_lock("railway-primary")["expires_at"]
    assert renewed_expiry > original_expiry
    assert repo.renew_scan_lock(
        "railway-primary", "deployment-b", ttl_seconds=600
    ) is False
    assert repo.get_scan_lock("railway-primary")["expires_at"] == renewed_expiry


def test_old_owner_cannot_renew_or_release_after_expired_takeover(tmp_path, monkeypatch):
    import trade_repository
    repo = repository(tmp_path)
    monkeypatch.setattr(trade_repository, "utc_now", lambda: NOW)
    assert repo.acquire_scan_lock(
        "railway-primary", owner_id="old-process", ttl_seconds=60
    )
    monkeypatch.setattr(trade_repository, "utc_now", lambda: NOW + timedelta(seconds=61))
    assert repo.acquire_scan_lock(
        "railway-primary", owner_id="replacement", ttl_seconds=60
    ) == "replacement"
    replacement_expiry = repo.get_scan_lock("railway-primary")["expires_at"]
    assert repo.renew_scan_lock("railway-primary", "old-process") is False
    assert repo.release_scan_lock("railway-primary", "old-process") is False
    current = repo.get_scan_lock("railway-primary")
    assert current["owner_id"] == "replacement"
    assert current["expires_at"] == replacement_expiry


def test_simultaneous_expired_takeover_has_exactly_one_winner(tmp_path, monkeypatch):
    import trade_repository
    database = tmp_path / "takeover.db"
    seed = TradeRepository(database, database_url="")
    monkeypatch.setattr(trade_repository, "utc_now", lambda: NOW)
    assert seed.acquire_scan_lock("railway-primary", owner_id="dead", ttl_seconds=1)
    monkeypatch.setattr(trade_repository, "utc_now", lambda: NOW + timedelta(seconds=2))
    repositories = [
        TradeRepository(database, database_url=""),
        TradeRepository(database, database_url=""),
    ]
    barrier = threading.Barrier(2)
    outcomes = []

    def takeover(repo, owner):
        barrier.wait()
        outcomes.append(repo.acquire_scan_lock("railway-primary", owner_id=owner))

    threads = [
        threading.Thread(target=takeover, args=(repo, owner))
        for repo, owner in zip(repositories, ("replacement-a", "replacement-b"))
    ]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert sum(value is not None for value in outcomes) == 1


def test_renewal_thread_stops_cleanly_and_reports_lost_ownership():
    class FakeRepository:
        def __init__(self):
            self.calls = 0
            self.accept = True

        def renew_scan_lock(self, scanner_id, owner_id, *, ttl_seconds):
            self.calls += 1
            return self.accept

        def get_scan_lock(self, scanner_id):
            return {"owner_id": "replacement", "expires_at": utc_iso(NOW)}

    repo = FakeRepository()
    lease = ScannerLockLease(
        repo, "railway-primary", "process-a", ttl_seconds=.2,
        renewal_seconds=.02,
    ).start()
    time.sleep(.06)
    lease.stop()
    calls_after_stop = repo.calls
    time.sleep(.05)
    assert repo.calls == calls_after_stop
    repo.accept = False
    assert lease.renew_once() is False
    with pytest.raises(ScannerLockOwnershipLost):
        lease.ensure_owned()


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
