import inspect
import json
from contextlib import nullcontext
from datetime import datetime, timezone

import app
import analysis.production_forensic_access as access
from analysis.production_forensic_access import (
    database_fingerprint, pairing_summary, read_only_connection,
    run_production_audit,
)
from production_forensic_dashboard import render_production_forensic_audit


class FakeStreamlit:
    def __init__(self, clicked=False):
        self.clicked = clicked
        self.calls = []
    def expander(self, *args, **kwargs): self.calls.append(("expander", args)); return nullcontext()
    def warning(self, value): self.calls.append(("warning", value))
    def caption(self, value): self.calls.append(("caption", value))
    def button(self, *args, **kwargs): self.calls.append(("button", args)); return self.clicked
    def error(self, value): self.calls.append(("error", value))
    def spinner(self, value): return nullcontext()
    def dataframe(self, *args, **kwargs): self.calls.append(("dataframe", None))
    def markdown(self, value): self.calls.append(("markdown", value))
    def json(self, value): self.calls.append(("json", value))
    def download_button(self, *args, **kwargs): self.calls.append(("download", None))


def test_developer_tools_page_load_is_query_on_demand():
    st, calls = FakeStreamlit(clicked=False), []
    result = render_production_forensic_audit(
        st, database_resolver=lambda _: calls.append("resolved"),
        audit_runner=lambda *_args, **_kwargs: calls.append("queried"),
    )
    assert result is None and calls == []
    assert "render_production_forensic_audit(st)" in inspect.getsource(app.render_developer_tools)


def test_explicit_click_uses_dashboard_resolver_and_safe_fingerprint():
    st, calls = FakeStreamlit(clicked=True), []
    url = "postgresql://private:secret@production.example/optionbeacon"
    stopped = {"status": "STOPPED", "reason": "NO_COMPLETE_SESSIONS",
        "database": {"engine": "postgresql", "schema": "public", "fingerprint": database_fingerprint(url),
                     "durability": "DURABLE", "table_presence": {}},
        "reconciliation": {}, "sessions": {"analyzable": []}}
    render_production_forensic_audit(st, database_resolver=lambda _: url,
        audit_runner=lambda received, **kwargs: calls.append((received, kwargs)) or stopped)
    assert calls[0][0] == url
    rendered = json.dumps(st.calls)
    assert "private" not in rendered and "secret" not in rendered and "production.example" not in rendered


class FakeConnection:
    def __init__(self): self.session = None; self.rolled_back = self.closed = False
    def set_session(self, **kwargs): self.session = kwargs
    def rollback(self): self.rolled_back = True
    def close(self): self.closed = True


def test_database_enforced_read_only_transaction():
    connection = FakeConnection()
    def connector(*args, **kwargs):
        assert kwargs["options"] == "-c default_transaction_read_only=on"
        return connection
    with read_only_connection("postgresql://redacted", connector): pass
    assert connection.session == {"readonly": True, "autocommit": False}
    assert connection.rolled_back and connection.closed


def test_reconciliation_mismatch_and_missing_mirror_tables_stop_before_reader(monkeypatch):
    presence = {table: {"status": "PRESENT", "missing_columns": []} for table in access.REQUIRED_TABLE_COLUMNS}
    monkeypatch.setattr(access, "table_presence", lambda *_args: presence)
    monkeypatch.setattr(access, "reconciliation_snapshot", lambda *_args: {"mirror_total": 4, "marks_total": 20})
    monkeypatch.setattr(access, "discover_sessions", lambda *_args: {"discovered": ["2026-08-12"], "analyzable": ["2026-08-12"], "excluded": [], "first": "2026-08-12", "last": "2026-08-12"})
    called = []
    result = run_production_audit("postgresql://x@y/db", dashboard_fingerprint="different",
                                  connector=lambda: None, reader=lambda *_a, **_k: called.append(True))
    assert result["status"] == "STOPPED" and result["reason"] == "DATABASE_FINGERPRINT_MISMATCH"
    assert called == []
    presence["mirror_execution_marks"]["status"] = "ABSENT"
    result = run_production_audit("postgresql://x@y/db", connector=lambda: None)
    assert result["reason"] == "MIRROR_LEDGER_MISMATCH"


def test_exact_pairing_and_broad_profile_filtering():
    report = {"translation_matrix": [{"n": 2}], "analysis_window": {"authoritative_opportunities": 3},
              "data_integrity": {"orphaned_records": {"mirror_without_authoritative": ["orphan"]}}}
    paper = [{"source_signal_id": "a"}, {"source_signal_id": "b"}]
    journal = [
        {"accepted": 1, "metadata_json": '{"simulation_profile":"BROAD"}'},
        {"accepted": 1, "metadata_json": '{"simulation_profile":"SAFE"}'},
        {"accepted": 0, "metadata_json": '{"simulation_profile":"BROAD"}'},
        {"accepted": 1, "metadata_json": "{}"},
    ]
    result = pairing_summary(report, paper, journal)
    assert result["mirror_matches"] == 2 and result["unmatched_authoritative"] == 1
    assert result["unmatched_mirror"] == 1 and result["broad_evaluated"] == 2
    assert result["broad_accepted"] == result["broad_rejected"] == 1


def test_same_database_resolution_no_provider_writes_or_trade_desk_limit_dependency():
    cli = inspect.getsource(__import__("analysis.run_post_run_forensic_audit", fromlist=["main"]))
    dashboard = inspect.getsource(render_production_forensic_audit)
    access_source = inspect.getsource(access)
    assert "dashboard_database_url()" in cli
    assert "database_resolver=dashboard_database_url" in dashboard
    for forbidden in ("option_quote", "tradier", "insert ", "update ", "delete ", "create table", "alter table", "commit("):
        assert forbidden not in access_source.lower()
    assert "trade desk" not in access_source.lower() and "history_limit" not in access_source.lower()
    assert "information_schema.columns" in access_source and "limit" not in inspect.getsource(access.reconciliation_snapshot).lower()
