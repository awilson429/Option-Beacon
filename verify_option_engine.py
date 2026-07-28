"""Safe command-line verification for Option Engine Phase 1."""

from __future__ import annotations

import hashlib
import importlib.util
import math
import os
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from option_trade_engine import (
    DEFAULT_LEDGER_FILE,
    OptionTradeLedger,
    PaperOptionTrade,
    TradierOptionChainProvider,
    capture_qualified_signal,
)
from trade_evidence import scanner_entry_eligibility
from tradier_options import tradier_configured


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


class TrackingProvider:
    """Record provider metadata without retaining or printing raw responses."""

    def __init__(self, provider):
        self.provider = provider
        self.listed_expirations: list[str] = []
        self.requested_expiration: str | None = None

    def expirations(self, ticker):
        expirations, error = self.provider.expirations(ticker)
        self.listed_expirations = list(expirations or [])
        return expirations, error

    def chain(self, ticker, expiration):
        self.requested_expiration = expiration
        return self.provider.chain(ticker, expiration)


class MockOptionProvider:
    """Deterministic provider used only when live Tradier cannot be validated."""

    def __init__(self, now: datetime):
        expiration = _verification_expiration(now)
        self.expiration = expiration
        self.calls = 0

    def expirations(self, ticker):
        self.calls += 1
        return [self.expiration], ""

    def chain(self, ticker, expiration):
        self.calls += 1
        return [
            {
                "symbol": f"{ticker}MOCKC00500000",
                "option_type": "call",
                "expiration_date": expiration,
                "strike": 500,
                "bid": 4.80,
                "ask": 5.20,
                "greeks": {"delta": 0.51, "mid_iv": 0.24},
                "open_interest": 4200,
                "volume": 850,
            },
            {
                "symbol": f"{ticker}MOCKC00505000",
                "option_type": "call",
                "expiration_date": expiration,
                "strike": 505,
                "bid": 3.90,
                "ask": 4.30,
                "greeks": {"delta": 0.43, "mid_iv": 0.25},
                "open_interest": 3100,
                "volume": 620,
            },
        ], ""


def protected_paths(root: str | Path = ".") -> list[Path]:
    root = Path(root)
    paths = [root / DEFAULT_LEDGER_FILE, root / "signal_history.jsonl"]
    paths.extend(sorted(root.glob("signal_history.backup*.jsonl")))
    return list(dict.fromkeys(paths))


def file_fingerprint(path: Path) -> dict:
    if not path.exists():
        return {"exists": False, "sha256": None, "mtime_ns": None, "size": None}
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    stat = path.stat()
    return {
        "exists": True,
        "sha256": digest.hexdigest(),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def snapshot_files(paths) -> dict[str, dict]:
    return {str(path): file_fingerprint(Path(path)) for path in paths}


def synthetic_signal(now: datetime) -> dict:
    return {
        "symbol": "SPY",
        "bias": "Bullish",
        "signal": "BULLISH SETUP",
        "confidence": 80,
        "score": 82,
        "timestamp": now.isoformat(),
        "setup_stage": "Armed",
        "entry_timing": "Watch closely",
        "entry_timing_reason": "Synthetic verification of a qualified trigger.",
        "price": 500,
        "trade_plan": {
            "direction": "Bullish",
            "setup_type": "Verification breakout",
            "trigger_price": 500,
            "technical_stop": 495,
            "target_1": 510,
        },
    }


def verify_capture(
    *,
    provider,
    now: datetime,
    mode: str,
    protected_root: str | Path = ".",
) -> tuple[list[Check], PaperOptionTrade | None]:
    paths = protected_paths(protected_root)
    before = snapshot_files(paths)
    signal = synthetic_signal(now)
    eligibility = scanner_entry_eligibility(signal)
    tracking = TrackingProvider(provider)
    checks = [
        Check(
            "scanner eligibility passed",
            eligibility["eligible"],
            ", ".join(eligibility["reasons"]) if eligibility["reasons"] else "QUALIFIED",
        )
    ]

    with tempfile.TemporaryDirectory(prefix="option-engine-verify-") as directory:
        ledger_path = Path(directory) / "verification-ledger.jsonl"
        repository = OptionTradeLedger(ledger_path)
        first = capture_qualified_signal(
            signal,
            repository=repository,
            provider=tracking,
            now=now,
        )
        second = capture_qualified_signal(
            signal,
            repository=repository,
            provider=tracking,
            now=now,
        )
        reloaded = OptionTradeLedger(ledger_path)
        third = capture_qualified_signal(
            signal,
            repository=reloaded,
            provider=tracking,
            now=now,
        )
        records = reloaded.records()

        qualified = first is not None and first.status == "QUALIFIED"
        checks.extend(
            _contract_checks(
                first,
                tracking,
                now,
                qualified=qualified,
            )
        )
        checks.extend(
            [
                Check(
                    "duplicate prevention works during repeated calls",
                    first == second and len(records) == 1,
                ),
                Check(
                    "duplicate prevention works after repository reload",
                    first == third and len(records) == 1,
                ),
                Check(
                    "temporary ledger contains exactly one record",
                    len(records) == 1,
                    str(ledger_path),
                ),
            ]
        )

    after = snapshot_files(paths)
    unchanged = before == after
    production_ledger = str(Path(protected_root) / DEFAULT_LEDGER_FILE)
    signal_history = str(Path(protected_root) / "signal_history.jsonl")
    checks.extend(
        [
            Check(
                "production ledger was not modified",
                before.get(production_ledger) == after.get(production_ledger),
            ),
            Check(
                "signal history was not modified",
                before.get(signal_history) == after.get(signal_history),
            ),
            Check("all backup history files were unchanged", unchanged),
        ]
    )
    return checks, first


def run_verification(
    *,
    live_provider=None,
    credentials_found: bool | None = None,
    now: datetime | None = None,
    protected_root: str | Path = ".",
) -> tuple[str, list[Check], PaperOptionTrade | None]:
    now = now or datetime.now(timezone.utc)
    credentials = (
        tradier_configured() if credentials_found is None else credentials_found
    )
    diagnostic = credential_lookup_diagnostic()
    credential_check = Check(
        "Tradier credentials found",
        credentials,
        "application credential loader resolved a token"
        if credentials
        else diagnostic,
    )

    provider = live_provider or TradierOptionChainProvider()
    live_checks, live_record = verify_capture(
        provider=provider,
        now=now,
        mode="LIVE PROVIDER VALIDATION",
        protected_root=protected_root,
    )
    if live_record is not None and live_record.status == "QUALIFIED":
        return "LIVE PROVIDER VALIDATION", [
            credential_check,
            Check("provider connection succeeded", True),
            *live_checks,
        ], live_record

    mock_checks, record = verify_capture(
        provider=MockOptionProvider(now),
        now=now,
        mode="MOCK PROVIDER VALIDATION",
        protected_root=protected_root,
    )
    return "MOCK PROVIDER VALIDATION", [
        credential_check,
        Check(
            "provider connection succeeded",
            False,
            (
                "live provider validation was not completed"
                if live_record is None
                else "application provider returned DATA_UNAVAILABLE"
            ),
        ),
        *mock_checks,
    ], record


def credential_lookup_diagnostic(root: str | Path = ".") -> str:
    """Explain the canonical loader's available sources without reading secrets."""
    expected = "TRADIER_ACCESS_TOKEN"
    if os.getenv(expected):
        return f"{expected} is set in the command environment"
    streamlit_available = importlib.util.find_spec("streamlit") is not None
    secrets_path = Path(root) / ".streamlit" / "secrets.toml"
    keys = set()
    if secrets_path.exists():
        try:
            with secrets_path.open("rb") as source:
                keys = set(tomllib.load(source))
        except Exception:
            pass
    details = [f"{expected} is absent from the command environment"]
    if not streamlit_available:
        details.append("Streamlit is unavailable to this Python interpreter")
    elif expected not in keys:
        details.append(f"{expected} is absent from Streamlit secrets")
    if "TRADIER_TOKEN" in keys and expected not in keys:
        details.append("Streamlit secrets contains TRADIER_TOKEN instead")
    return "; ".join(details)


def _contract_checks(record, provider: TrackingProvider, now, *, qualified):
    if record is None:
        return [Check("immutable snapshot was created", False, "no record returned")]
    bid_ask_honest = (
        record.ask is not None
        and record.ask > 0
        and (record.bid is None or 0 <= record.bid <= record.ask)
    )
    expected_mid = (
        (record.bid + record.ask) / 2
        if record.bid is not None and record.ask is not None
        else None
    )
    midpoint_correct = (
        record.mid is None if expected_mid is None else _close(record.mid, expected_mid)
    )
    expected_spread = (
        (record.ask - record.bid) / expected_mid * 100
        if record.bid is not None and expected_mid
        else None
    )
    spread_correct = (
        record.spread_percent is None
        if expected_spread is None
        else _close(record.spread_percent, expected_spread)
    )
    same_day_ok = (
        now.weekday() < 3
        or record.expiration is None
        or record.expiration != now.date().isoformat()
    )
    return [
        Check("correct call/put mapping", record.option_type == "call"),
        Check(
            "valid listed expiration selected",
            record.expiration in provider.listed_expirations,
        ),
        Check("same-day expiration avoided when applicable", same_day_ok),
        Check("strike is valid", bool(record.strike and record.strike > 0)),
        Check("bid/ask are valid or handled honestly", bid_ask_honest),
        Check("midpoint calculation is correct", midpoint_correct),
        Check("spread calculation is correct", spread_correct),
        Check(
            "delta is near 0.50 when available",
            record.delta is None or abs(abs(record.delta) - 0.50) <= 0.20,
            "delta unavailable and not fabricated" if record.delta is None else "",
        ),
        Check("option symbol is present", bool(record.option_symbol)),
        Check(
            "immutable snapshot was created",
            qualified and PaperOptionTrade.__dataclass_params__.frozen,
        ),
    ]


def _verification_expiration(now: datetime) -> str:
    days = (4 - now.weekday()) % 7
    if now.weekday() >= 3:
        days += 7
    return (now.date() + timedelta(days=days)).isoformat()


def _close(left, right) -> bool:
    return (
        left is not None
        and right is not None
        and math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)
    )


def print_report(mode: str, checks: list[Check], record) -> None:
    print(f"Option Engine Phase 1 Verification — {mode}")
    for check in checks:
        result = "PASS" if check.passed else "FAIL"
        detail = f" — {check.detail}" if check.detail else ""
        print(f"[{result}] {check.name}{detail}")
    if record is not None:
        print("\nSelected contract (sanitized)")
        values = (
            ("ticker", record.ticker),
            ("direction", record.direction),
            ("option type", record.option_type),
            ("expiration", record.expiration),
            ("strike", record.strike),
            ("option symbol", record.option_symbol),
            ("delta", record.delta),
            ("IV", record.implied_volatility),
            ("bid", record.bid),
            ("ask", record.ask),
            ("midpoint", record.mid),
            ("spread percent", record.spread_percent),
            ("open interest", record.open_interest),
            ("volume", record.volume),
            ("status", record.status),
        )
        for label, value in values:
            display = (
                "—"
                if value is None
                else f"{value:.4f}".rstrip("0").rstrip(".")
                if isinstance(value, float)
                else value
            )
            print(f"  {label}: {display}")
    if mode == "MOCK PROVIDER VALIDATION":
        print("\nLive provider validation was not completed.")


def main() -> int:
    mode, checks, record = run_verification()
    print_report(mode, checks, record)
    required_checks = [
        check
        for check in checks
        if check.name
        not in {"Tradier credentials found", "provider connection succeeded"}
    ]
    return 0 if all(check.passed for check in required_checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
