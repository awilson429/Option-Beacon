import json
from datetime import datetime, timezone
from types import SimpleNamespace

from developer_tools import (
    latest_production_ledger_entry,
    load_latest_diagnostic,
    hosted_configuration_status,
    option_engine_diagnostic,
    sanitize_diagnostic_result,
    save_diagnostic_result,
    verify_finnhub_connection,
    verify_position_tracking,
    verify_tradier_connection,
)
from option_trade_engine import OptionTradeLedger, PaperOptionTrade
from verify_option_engine import Check
import developer_tools
import verify_option_engine


NOW = datetime(2026, 7, 28, 15, 0, tzinfo=timezone.utc)


def test_app_developer_tool_imports_are_explicitly_exported():
    expected = {
        "hosted_configuration_status",
        "latest_production_ledger_entry",
        "load_latest_diagnostic",
        "option_engine_diagnostic",
        "save_diagnostic_result",
        "system_status",
        "verify_finnhub_connection",
        "verify_position_tracking",
        "verify_trade_plan_engine",
        "verify_tradier_connection",
    }

    assert set(developer_tools.__all__) == expected
    assert all(callable(getattr(developer_tools, name)) for name in expected)


class TradierSuccess:
    def expirations(self, ticker):
        return ["2026-07-31", "2026-08-07"], ""


class TradierUnavailable:
    def expirations(self, ticker):
        return [], "Bearer secret-token request rejected"


def option_record(**overrides):
    values = {
        "trade_id": "trade",
        "source_signal_id": "signal",
        "created_timestamp": NOW,
        "ticker": "SPY",
        "direction": "Bullish",
        "underlying_entry_price": 500,
        "confidence": 80,
        "historical_grade": "POSITIVE",
        "scanner_score": 82,
        "entry_reason": "Qualified",
        "expiration": "2026-07-31",
        "strike": 500,
        "option_type": "call",
        "option_symbol": "SPY260731C00500000",
        "delta": 0.51,
        "implied_volatility": 0.24,
        "bid": 4.8,
        "ask": 5.2,
        "mid": 5,
        "spread_percent": 8,
        "open_interest": 4200,
        "volume": 850,
    }
    values.update(overrides)
    return PaperOptionTrade(**values)


def test_tradier_success_state(monkeypatch):
    monkeypatch.setattr("developer_tools.tradier_configured", lambda: True)
    result = verify_tradier_connection(TradierSuccess(), now=NOW)
    assert result["overall_result"] == "PASS"
    assert result["expiration_count"] == 2
    assert [check["status"] for check in result["checks"]] == ["PASS"] * 3


def test_hosted_configuration_status_exposes_names_not_values(monkeypatch):
    monkeypatch.setattr("developer_tools.tradier_configured", lambda: True)
    monkeypatch.setattr("developer_tools.finnhub_api_key", lambda: "hidden-key")
    status = hosted_configuration_status()
    assert status["ready"] is True
    assert status["missing"] == []
    assert status["statuses"] == {
        "TRADIER_ACCESS_TOKEN": "Configured",
        "FINNHUB_API_KEY": "Configured",
    }
    assert "hidden-key" not in json.dumps(status)


def test_tradier_unavailable_state_is_sanitized(monkeypatch):
    monkeypatch.setattr("developer_tools.tradier_configured", lambda: False)
    result = verify_tradier_connection(TradierUnavailable(), now=NOW)
    assert result["overall_result"] == "FAIL"
    assert result["message"] == "request rejected"
    assert "secret-token" not in json.dumps(result)


def test_finnhub_success_state(monkeypatch):
    monkeypatch.setattr("developer_tools.finnhub_api_key", lambda: "not-rendered")
    result = verify_finnhub_connection(
        lambda symbol, key: {"symbol": symbol, "price": 500},
        now=NOW,
    )
    assert result["overall_result"] == "PASS"
    assert "not-rendered" not in json.dumps(result)


def test_finnhub_unavailable_and_raw_exception_are_sanitized(monkeypatch):
    monkeypatch.setattr("developer_tools.finnhub_api_key", lambda: "not-rendered")

    def fail(symbol, key):
        raise RuntimeError("Authorization: Bearer secret-token")

    result = verify_finnhub_connection(fail, now=NOW)
    assert result["overall_result"] == "FAIL"
    assert result["message"] == "provider unavailable"
    assert "secret-token" not in json.dumps(result)


def test_live_option_engine_result_uses_shared_verifier():
    record = option_record()

    def verifier(**kwargs):
        return "LIVE PROVIDER VALIDATION", [Check("selection", True)], record

    result = option_engine_diagnostic(now=NOW, verifier=verifier)
    assert result["provider_mode"] == "LIVE PROVIDER VALIDATION"
    assert result["overall_result"] == "PASS"
    assert result["contract"]["option_symbol"] == record.option_symbol


def test_cli_and_streamlit_adapter_share_core_verifier():
    assert developer_tools.run_verification is verify_option_engine.run_verification


def test_mock_fallback_renders_provider_failures_as_warnings():
    record = option_record(option_symbol="SPYMOCK")

    def verifier(**kwargs):
        return (
            "MOCK PROVIDER VALIDATION",
            [
                Check("Tradier credentials found", False, "credential unavailable"),
                Check("provider connection succeeded", False, "provider unavailable"),
                Check("selection", True),
            ],
            record,
        )

    result = option_engine_diagnostic(now=NOW, verifier=verifier)
    assert result["provider_mode"] == "MOCK PROVIDER VALIDATION"
    assert result["overall_result"] == "PASS"
    assert [check["status"] for check in result["checks"]] == [
        "WARNING",
        "WARNING",
        "PASS",
    ]


def test_position_tracking_diagnostic_uses_temporary_store(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = verify_position_tracking(now=NOW)
    assert result["overall_result"] == "PASS"
    assert [check["status"] for check in result["checks"]] == ["PASS"] * 7
    assert not (tmp_path / "paper_option_positions.json").exists()
    assert not (tmp_path / "paper_option_trades.jsonl").exists()


def test_latest_ledger_entry_and_malformed_line_handling(tmp_path):
    path = tmp_path / "paper_option_trades.jsonl"
    path.write_text("{malformed}\n", encoding="utf-8")
    OptionTradeLedger(path).append_once(option_record())
    before = path.read_bytes()
    latest = latest_production_ledger_entry(path)
    assert latest["ticker"] == "SPY"
    assert latest["option_symbol"] == "SPY260731C00500000"
    assert path.read_bytes() == before


def test_missing_ledger_is_safe(tmp_path):
    assert latest_production_ledger_entry(tmp_path / "missing.jsonl") is None


def test_latest_diagnostic_result_persistence_is_sanitized(tmp_path):
    path = tmp_path / "runtime_diagnostics.json"
    result = {
        "validation_type": "Tradier Connection",
        "timestamp": NOW.isoformat(),
        "provider_mode": "LIVE",
        "overall_result": "FAIL",
        "checks": [
            {
                "name": "provider",
                "status": "FAIL",
                "message": "Authorization: Bearer secret-token",
            }
        ],
        "message": "token=secret-token",
        "raw_response": {"token": "secret-token"},
        "elapsed_seconds": 0.1,
        "contract": None,
    }
    save_diagnostic_result(result, path)
    content = path.read_text(encoding="utf-8")
    loaded = load_latest_diagnostic(path)
    assert "secret-token" not in content
    assert "raw_response" not in content
    assert loaded["checks"][0]["message"] == "request rejected"


def test_malformed_diagnostic_file_is_safe(tmp_path):
    path = tmp_path / "runtime_diagnostics.json"
    path.write_text("{malformed}", encoding="utf-8")
    assert load_latest_diagnostic(path) is None


def test_sanitizer_never_preserves_secret_fields_or_values():
    sanitized = sanitize_diagnostic_result(
        {
            "validation_type": "Test",
            "headers": {"Authorization": "Bearer secret-token"},
            "message": "api_key=secret-token",
            "checks": [],
            "contract": {
                "ticker": "SPY",
                "token": "secret-token",
                "raw": {"secret": "secret-token"},
            },
        }
    )
    encoded = json.dumps(sanitized)
    assert "secret-token" not in encoded
    assert "Authorization" not in encoded
    assert "token" not in sanitized["contract"]


def test_pass_rows_never_contain_failure_text():
    sanitized = sanitize_diagnostic_result(
        {
            "checks": [
                {
                    "name": "Tradier credentials found",
                    "status": "PASS",
                    "message": "request rejected",
                }
            ]
        }
    )
    assert sanitized["checks"] == [
        {
            "name": "Tradier credentials found",
            "status": "PASS",
            "message": "",
        }
    ]


def test_fail_rows_always_have_meaningful_sanitized_explanation():
    sanitized = sanitize_diagnostic_result(
        {
            "checks": [
                {"name": "provider connection", "status": "FAIL", "message": ""},
                {
                    "name": "credential",
                    "status": "FAIL",
                    "message": "Authorization: Bearer secret-token",
                },
            ]
        }
    )
    assert sanitized["checks"][0]["message"] == "verification failed"
    assert sanitized["checks"][1]["message"] == "request rejected"
    assert "secret-token" not in json.dumps(sanitized)


def test_successful_retry_overwrites_failed_message(tmp_path):
    path = tmp_path / "runtime_diagnostics.json"
    failed = {
        "validation_type": "Tradier Connection",
        "checks": [
            {
                "name": "Tradier credentials found",
                "status": "FAIL",
                "message": "request rejected",
            }
        ],
    }
    passed = {
        "validation_type": "Tradier Connection",
        "checks": [
            {
                "name": "Tradier credentials found",
                "status": "PASS",
                "message": "request rejected",
            }
        ],
    }
    save_diagnostic_result(failed, path)
    assert load_latest_diagnostic(path)["checks"][0]["message"] == "request rejected"

    save_diagnostic_result(passed, path)
    latest = load_latest_diagnostic(path)
    assert latest["checks"][0]["status"] == "PASS"
    assert latest["checks"][0]["message"] == ""
    assert "request rejected" not in path.read_text(encoding="utf-8")
