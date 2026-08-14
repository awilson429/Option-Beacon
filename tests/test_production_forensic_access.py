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
from production_forensic_dashboard import forensic_export_filename, forensic_export_json


class FakeStreamlit:
    def __init__(self, clicked=False):
        self.clicked = clicked
        self.calls = []
        self.session_state = {}
    def expander(self, *args, **kwargs): self.calls.append(("expander", args)); return nullcontext()
    def warning(self, value): self.calls.append(("warning", value))
    def caption(self, value): self.calls.append(("caption", value))
    def button(self, *args, **kwargs): self.calls.append(("button", args)); return self.clicked
    def error(self, value): self.calls.append(("error", value))
    def spinner(self, value): return nullcontext()
    def dataframe(self, *args, **kwargs): self.calls.append(("dataframe", None))
    def markdown(self, value): self.calls.append(("markdown", value))
    def json(self, value): self.calls.append(("json", value))
    def download_button(self, *args, **kwargs): self.calls.append(("download", args, kwargs))


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


def test_complete_export_preserves_nested_source_and_per_trade_records_without_secrets():
    result = {"status": "COMPLETED", "database": {"fingerprint": "abc", "DATABASE_URL": "postgresql://secret"},
              "reconciliation": {"mirror_total": 1}, "sessions": {"analyzable": ["2026-08-13"]},
              "pairing": {"mirror_matches": 1},
              "report": {"translation_matrix": [{"outcome": "AUTH WIN / MIRROR LOSS", "n": 1}],
                         "auth_win_mirror_loss": {"rows": [{"opportunity_id": "auth-1", "mirror_trade_id": "mirror-1",
                             "marks": [{"mark_id": "mark-1", "return_pct": 20}], "mfe": 20, "mae": -5, "giveback": 30}]},
                         "counterfactual_exits": {"results": [{"variant": "TP20"}]},
                         "biggest_observed_leak": {"failure_mode": "GIVEBACK"}},
              "source_records": {"authoritative_outcomes": [{"outcome": {"opportunity_id": "auth-1"}}],
                  "paper_trades": [{"trade_id": "paper-1", "source_signal_id": "auth-1"}],
                  "broad_journal": [{"trade_id": "paper-1", "accepted": 0}],
                  "mirror_trades": [{"mirror_trade_id": "mirror-1", "opportunity_id": "auth-1"}],
                  "mirror_marks": [{"mark_id": "mark-1", "mirror_trade_id": "mirror-1"}],
                  "access_token": "hidden"}}
    exported = json.loads(forensic_export_json(result))
    assert exported["report"] == result["report"]
    assert exported["source_records"]["mirror_marks"] == result["source_records"]["mirror_marks"]
    assert exported["source_records"]["paper_trades"][0]["source_signal_id"] == "auth-1"
    encoded = json.dumps(exported)
    assert "postgresql://secret" not in encoded and "hidden" not in encoded
    assert forensic_export_filename(datetime(2026, 8, 13, 16, tzinfo=timezone.utc)) == "optionbeacon_forensic_audit_2026-08-13.json"


def test_cached_completed_export_does_not_rerun_audit_or_write_database():
    st, runner_calls = FakeStreamlit(clicked=True), []
    result = {"status": "COMPLETED", "reason": None,
              "database": {"engine": "postgresql", "schema": "public", "fingerprint": "abc", "durability": "DURABLE", "table_presence": {}},
              "reconciliation": {}, "sessions": {}, "pairing": {}, "report": {}, "source_records": {}}
    runner = lambda *_args, **_kwargs: runner_calls.append("audit") or result
    render_production_forensic_audit(st, database_resolver=lambda _: "postgresql://redacted", audit_runner=runner)
    st.clicked = False
    render_production_forensic_audit(st, database_resolver=lambda _: (_ for _ in ()).throw(AssertionError("resolved again")), audit_runner=runner)
    assert runner_calls == ["audit"]
    downloads = [call for call in st.calls if call[0] == "download"]
    assert len(downloads) == 2
    assert downloads[-1][1][0] == "Download Full Forensic Report"
    assert json.loads(downloads[-1][1][1]) == result
    export_source = inspect.getsource(forensic_export_json)
    assert all(token not in export_source.lower() for token in ("insert ", "update ", "delete ", "create ", "execute("))


def test_completed_audit_retains_every_in_memory_source_collection(monkeypatch):
    presence = {table: {"status": "PRESENT", "missing_columns": []} for table in access.REQUIRED_TABLE_COLUMNS}
    sessions = {"discovered": ["2026-08-13"], "analyzable": ["2026-08-13"], "excluded": [],
                "first": "2026-08-13", "last": "2026-08-13"}
    values = ([{"snapshot": {"opportunity_id": "auth-1"}}],
              [{"outcome": {"opportunity_id": "auth-1"}}],
              [{"mirror_trade_id": "mirror-1", "opportunity_id": "auth-1"}],
              [{"mark_id": "mark-1", "mirror_trade_id": "mirror-1"}],
              [{"trade_id": "paper-1", "source_signal_id": "auth-1"}],
              [{"trade_id": "paper-1", "accepted": 1}], {"query": "READ_ONLY"})
    monkeypatch.setattr(access, "table_presence", lambda *_args: presence)
    monkeypatch.setattr(access, "reconciliation_snapshot", lambda *_args: {"mirror_total": 1})
    monkeypatch.setattr(access, "discover_sessions", lambda *_args: sessions)
    monkeypatch.setattr(access, "build_forensic_report", lambda *_args: {
        "translation_matrix": [{"n": 1}], "analysis_window": {"authoritative_opportunities": 1},
        "data_integrity": {"orphaned_records": {"mirror_without_authoritative": []}}})
    result = run_production_audit("postgresql://x@y/db", reader=lambda *_a, **_k: values)
    assert result["status"] == "COMPLETED"
    assert result["source_records"] == {
        "authoritative_snapshots": values[0], "authoritative_outcomes": values[1],
        "mirror_trades": values[2], "mirror_marks": values[3],
        "paper_trades": values[4], "broad_journal": values[5],
    }


class FakeConnection:
    def __init__(self): self.autocommit = None; self.rolled_back = self.closed = False; self.statements = []
    def cursor(self): return FakeCursor(self)
    def rollback(self): self.rolled_back = True
    def close(self): self.closed = True


class FakeCursor:
    def __init__(self, connection): self.connection = connection
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def execute(self, statement):
        normalized = " ".join(statement.upper().split())
        self.connection.statements.append(normalized)
        if normalized.startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")):
            raise RuntimeError("cannot execute in a read-only transaction")
    def fetchone(self): return {"value": 1}


def test_database_enforced_read_only_transaction():
    connection = FakeConnection()
    def connector(*args, **kwargs):
        assert "options" not in kwargs
        return connection
    with read_only_connection("postgresql://host-pooler.example/db", connector) as opened:
        with opened.cursor() as cursor:
            cursor.execute("SELECT 1")
    assert connection.autocommit is False
    assert connection.statements[:3] == ["BEGIN", "SET TRANSACTION READ ONLY", "SELECT 1"]
    assert connection.rolled_back and connection.closed


def test_database_enforced_read_only_rejects_dml_and_ddl():
    for statement in ("INSERT INTO x VALUES (1)", "UPDATE x SET y=1", "DELETE FROM x",
                      "CREATE TABLE x(y int)", "ALTER TABLE x ADD y int", "DROP TABLE x"):
        connection = FakeConnection()
        try:
            with read_only_connection("postgresql://host-pooler.example/db", lambda *a, **k: connection) as opened:
                with opened.cursor() as cursor: cursor.execute(statement)
        except RuntimeError as error:
            assert "read-only transaction" in str(error)
        else:
            raise AssertionError(f"write unexpectedly succeeded: {statement}")
        assert connection.rolled_back and connection.closed


def test_read_only_initialization_failure_is_sanitized(caplog):
    class FailingCursor(FakeCursor):
        def execute(self, statement):
            if statement == "SET TRANSACTION READ ONLY":
                raise RuntimeError("password=secret host=private.pooler.neon.tech")
            super().execute(statement)
    connection = FakeConnection()
    connection.cursor = lambda: FailingCursor(connection)
    try:
        with read_only_connection("postgresql://user:secret@private.pooler.neon.tech/db", lambda *a, **k: connection): pass
    except access.ReadOnlyTransactionError as error:
        assert str(error) == "Could not establish a read-only database transaction."
    logs = caplog.text
    assert "failure_stage" in logs and "read_only_transaction" in logs
    assert "secret" not in logs and "private.pooler.neon.tech" not in logs


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
    assert "default_transaction_read_only" not in access_source
    assert 'cursor.execute("SET TRANSACTION READ ONLY")' in access_source


def test_normal_repository_connection_semantics_are_unchanged():
    from trade_repository import TradeRepository
    source = inspect.getsource(TradeRepository.connection)
    assert "default_transaction_read_only" not in source
    assert "SET TRANSACTION READ ONLY" not in source
