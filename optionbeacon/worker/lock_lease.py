"""Exact-owner renewable scanner lease for one synchronous worker scan."""

from __future__ import annotations

import json
import logging
import threading
import time


DEFAULT_LOCK_TTL_SECONDS = 120
DEFAULT_LOCK_RENEWAL_SECONDS = 30


class ScannerLockOwnershipLost(RuntimeError):
    pass


class ScannerLockLease:
    def __init__(
        self, repository, scanner_id, owner_id, *,
        ttl_seconds=DEFAULT_LOCK_TTL_SECONDS,
        renewal_seconds=DEFAULT_LOCK_RENEWAL_SECONDS,
        logger=None,
    ):
        if renewal_seconds <= 0 or renewal_seconds >= ttl_seconds:
            raise ValueError("Lock renewal interval must be positive and shorter than TTL.")
        self.repository = repository
        self.scanner_id = scanner_id
        self.owner_id = owner_id
        self.ttl_seconds = ttl_seconds
        self.renewal_seconds = renewal_seconds
        self.logger = logger or logging.getLogger(__name__)
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = None
        self._confirmed_until = time.monotonic() + ttl_seconds

    def start(self):
        self._thread = threading.Thread(
            target=self._run,
            name=f"scanner-lock-renewal-{self.scanner_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.renewal_seconds + 1.0))

    def ensure_owned(self):
        if self._lost.is_set():
            raise ScannerLockOwnershipLost(
                f"Scanner lease ownership was lost for {self.scanner_id}."
            )

    @property
    def lost(self):
        return self._lost.is_set()

    def renew_once(self):
        try:
            renewed = self.repository.renew_scan_lock(
                self.scanner_id, self.owner_id, ttl_seconds=self.ttl_seconds
            )
        except Exception as exc:
            self.logger.exception(json.dumps({
                "event": "scanner_lock_renewal_error",
                "scanner_id": self.scanner_id,
                "requested_owner_id": self.owner_id,
                "error": type(exc).__name__,
                "reason": "database_error",
            }, sort_keys=True))
            if time.monotonic() >= self._confirmed_until:
                self._lost.set()
            return False
        if renewed:
            self._confirmed_until = time.monotonic() + self.ttl_seconds
            self.logger.info(json.dumps({
                "event": "scanner_lock_renewed",
                "scanner_id": self.scanner_id,
                "requested_owner_id": self.owner_id,
                "lease_duration_seconds": self.ttl_seconds,
            }, sort_keys=True))
            return True
        self._lost.set()
        current = self.repository.get_scan_lock(self.scanner_id) or {}
        self.logger.error(json.dumps({
            "event": "scanner_lock_renewal_rejected",
            "scanner_id": self.scanner_id,
            "requested_owner_id": self.owner_id,
            "persisted_owner_id": current.get("owner_id"),
            "expires_at": current.get("expires_at"),
            "reason": "owner_mismatch_or_expired",
        }, sort_keys=True))
        return False

    def _run(self):
        while not self._stop.wait(self.renewal_seconds):
            if not self.renew_once():
                if self._lost.is_set():
                    return
