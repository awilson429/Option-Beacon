from datetime import datetime, timezone

import pytest

from verify_option_engine import (
    MockOptionProvider,
    credential_lookup_diagnostic,
    file_fingerprint,
    print_report,
    run_verification,
    snapshot_files,
    synthetic_signal,
)


NOW = datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc)  # Thursday


class LiveProvider(MockOptionProvider):
    pass


class FailedProvider:
    def expirations(self, ticker):
        return [], "provider unavailable"

    def chain(self, ticker, expiration):
        raise AssertionError("chain should not be called")


def check_map(checks):
    return {check.name: check for check in checks}


def test_synthetic_signal_passes_canonical_eligibility():
    from trade_evidence import scanner_entry_eligibility

    assert scanner_entry_eligibility(synthetic_signal(NOW))["eligible"] is True


def test_live_provider_verification_uses_temporary_ledger(tmp_path):
    mode, checks, record = run_verification(
        live_provider=LiveProvider(NOW),
        credentials_found=True,
        now=NOW,
        protected_root=tmp_path,
    )
    results = check_map(checks)
    assert mode == "LIVE PROVIDER VALIDATION"
    assert results["Tradier credentials found"].passed is True
    assert results["provider connection succeeded"].passed is True
    assert results["same-day expiration avoided when applicable"].passed is True
    assert results["duplicate prevention works during repeated calls"].passed is True
    assert results["duplicate prevention works after repository reload"].passed is True
    assert results["temporary ledger contains exactly one record"].passed is True
    assert record.status == "QUALIFIED"
    assert not (tmp_path / "paper_option_trades.jsonl").exists()


def test_missing_credentials_uses_mock_provider(tmp_path):
    mode, checks, record = run_verification(
        live_provider=FailedProvider(),
        credentials_found=False,
        now=NOW,
        protected_root=tmp_path,
    )
    results = check_map(checks)
    assert mode == "MOCK PROVIDER VALIDATION"
    assert results["Tradier credentials found"].passed is False
    assert results["provider connection succeeded"].passed is False
    assert results["immutable snapshot was created"].passed is True
    assert record.option_symbol == "SPYMOCKC00500000"


def test_live_provider_failure_falls_back_without_crashing(tmp_path):
    mode, checks, record = run_verification(
        live_provider=FailedProvider(),
        credentials_found=True,
        now=NOW,
        protected_root=tmp_path,
    )
    assert mode == "MOCK PROVIDER VALIDATION"
    assert record.status == "QUALIFIED"
    assert check_map(checks)["provider connection succeeded"].passed is False


def test_provider_is_attempted_even_when_precheck_is_false(tmp_path):
    provider = LiveProvider(NOW)
    mode, checks, record = run_verification(
        live_provider=provider,
        credentials_found=False,
        now=NOW,
        protected_root=tmp_path,
    )
    assert mode == "LIVE PROVIDER VALIDATION"
    assert provider.calls == 2
    assert record.status == "QUALIFIED"
    assert check_map(checks)["provider connection succeeded"].passed is True


def test_credential_diagnostic_names_keys_without_values(tmp_path, monkeypatch):
    secrets = tmp_path / ".streamlit" / "secrets.toml"
    secrets.parent.mkdir()
    secrets.write_text('TRADIER_TOKEN = "do-not-print"\n', encoding="utf-8")
    monkeypatch.delenv("TRADIER_ACCESS_TOKEN", raising=False)
    diagnostic = credential_lookup_diagnostic(tmp_path)
    assert "TRADIER_ACCESS_TOKEN is absent" in diagnostic
    assert "TRADIER_TOKEN" in diagnostic
    assert "do-not-print" not in diagnostic


def test_midpoint_spread_and_contract_fields_are_verified(tmp_path):
    _mode, checks, record = run_verification(
        live_provider=FailedProvider(),
        credentials_found=False,
        now=NOW,
        protected_root=tmp_path,
    )
    results = check_map(checks)
    assert results["correct call/put mapping"].passed is True
    assert results["valid listed expiration selected"].passed is True
    assert results["strike is valid"].passed is True
    assert results["bid/ask are valid or handled honestly"].passed is True
    assert results["midpoint calculation is correct"].passed is True
    assert results["spread calculation is correct"].passed is True
    assert results["delta is near 0.50 when available"].passed is True
    assert results["option symbol is present"].passed is True
    assert record.mid == 5
    assert record.spread_percent == pytest.approx(8)


def test_protected_files_remain_byte_and_timestamp_identical(tmp_path):
    history = tmp_path / "signal_history.jsonl"
    backup = tmp_path / "signal_history.backup-2026-07-28.jsonl"
    ledger = tmp_path / "paper_option_trades.jsonl"
    history.write_text("history\n", encoding="utf-8")
    backup.write_text("backup\n", encoding="utf-8")
    ledger.write_text("ledger\n", encoding="utf-8")
    paths = [history, backup, ledger]
    before = snapshot_files(paths)

    _mode, checks, _record = run_verification(
        live_provider=FailedProvider(),
        credentials_found=False,
        now=NOW,
        protected_root=tmp_path,
    )

    assert snapshot_files(paths) == before
    results = check_map(checks)
    assert results["production ledger was not modified"].passed is True
    assert results["signal history was not modified"].passed is True
    assert results["all backup history files were unchanged"].passed is True


def test_file_fingerprint_reports_missing_file(tmp_path):
    assert file_fingerprint(tmp_path / "missing.jsonl") == {
        "exists": False,
        "sha256": None,
        "mtime_ns": None,
        "size": None,
    }


def test_report_is_sanitized_and_labels_mock_mode(tmp_path, capsys):
    mode, checks, record = run_verification(
        live_provider=FailedProvider(),
        credentials_found=False,
        now=NOW,
        protected_root=tmp_path,
    )
    print_report(mode, checks, record)
    output = capsys.readouterr().out
    assert "MOCK PROVIDER VALIDATION" in output
    assert "Selected contract (sanitized)" in output
    assert "Authorization" not in output
    assert "Bearer" not in output


@pytest.mark.live_provider
def test_live_tradier_verification_is_explicitly_opt_in(tmp_path):
    """Manual integration test; excluded unless the explicit live flag is set."""
    mode, checks, record = run_verification(
        credentials_found=True,
        now=NOW,
        protected_root=tmp_path,
    )
    assert mode == "LIVE PROVIDER VALIDATION"
    assert record is not None and record.status == "QUALIFIED"
    assert check_map(checks)["provider connection succeeded"].passed is True
