import inspect
import json
from decimal import Decimal
from contextlib import nullcontext
from datetime import datetime, timezone
from uuid import UUID

import app
import analysis.production_strategic_audit as access
from analysis.production_strategic_audit import (StrategicAuditFailure, _et_day,
    production_reconciliation, run_production_strategic_audit)
from dashboard_storage_config import dashboard_database_url
from strategic_audit_dashboard import (render_production_strategic_audit,
    strategic_export_filename, strategic_export_json)


class FakeStreamlit:
    def __init__(self, clicked=False): self.clicked=clicked; self.calls=[]; self.session_state={}
    def expander(self,*a,**k): self.calls.append(("expander",a)); return nullcontext()
    def warning(self,v): self.calls.append(("warning",v))
    def caption(self,v): self.calls.append(("caption",v))
    def button(self,*a,**k): self.calls.append(("button",a)); return self.clicked
    def error(self,v): self.calls.append(("error",v))
    def spinner(self,v): return nullcontext()
    def markdown(self,v): self.calls.append(("markdown",v))
    def json(self,v): self.calls.append(("json",v))
    def download_button(self,*a,**k): self.calls.append(("download",a,k))


def reconciliation(**patch):
    base={"latest_authoritative_event_timestamp":"2026-08-17T20:00:00Z","mirror_total_trades":2,
        "mirror_closed_trades":2,"mirror_marks":8,"broad_paper_trades":2,"filtered_records":1,
        "spy_intraday_signals":2,"spy_intraday_trades":2,"spy_intraday_closed":1,"spy_intraday_mirror":1,
        "spy_intraday_managed":1,"spy_realized_pnl":5,"qqq_intraday_signals":1,"qqq_intraday_trades":2,
        "qqq_intraday_closed":2,"qqq_intraday_mirror":1,"qqq_intraday_managed":1,"qqq_realized_pnl":-2,
        "opportunity_context_count":2,"context_shadow_count":2,"position_context_marks_count":4,
        "sessions":{"discovered":["2026-08-17"],"complete":["2026-08-17"],"incomplete_excluded":[],
            "earliest_broad_universe_session":"2026-08-17","earliest_spy_qqq_session":None,"latest_session":"2026-08-17"},
        "table_presence":{"mirror":True,"broad_trades":True,"broad_journal":True}}
    base.update(patch); return base


def snapshot():
    row=lambda identity,symbol,variant:{"trade_id":identity,"opportunity_id":identity,"symbol":symbol,"variant":variant,
        "session":"2026-08-17","opened_at":"2026-08-17T14:00:00Z","closed_at":"2026-08-17T15:00:00Z",
        "pnl":1,"return_pct":1,"mfe":2,"mae":-1,"entry_fill":1,"debit":100}
    return {"metadata":{},"lanes":{"BROAD":[],"MIRROR":[],"FILTERED":[],
        "SPY":[row("spy-m","SPY","INTRADAY_MIRROR"),row("spy-g","SPY","INTRADAY_MANAGED")],
        "QQQ":[row("qqq-m","QQQ","INTRADAY_MIRROR"),row("qqq-g","QQQ","INTRADAY_MANAGED")]},
        "AUTHORITATIVE":[],"OPPORTUNITY_CONTEXT":[],"CONTEXT_SHADOW":[],"POSITION_CONTEXT":[],
        "DAILY_SCORECARD_ANALYTICS":[],"underlying_records":{}}


def test_page_load_is_query_free_and_uses_canonical_dashboard_resolver():
    st,calls=FakeStreamlit(),[]
    assert render_production_strategic_audit(st,database_resolver=lambda _:calls.append("resolve"),audit_runner=lambda *_a,**_k:calls.append("query")) is None
    assert calls==[]
    source=inspect.getsource(render_production_strategic_audit)
    assert "database_resolver=dashboard_database_url" in source
    assert "render_production_strategic_audit(st)" in inspect.getsource(app.render_developer_tools)
    assert dashboard_database_url is not None


def test_reconciliation_mismatch_stops_before_reader(monkeypatch):
    bad=reconciliation(mirror_total_trades=0,broad_paper_trades=0)
    monkeypatch.setattr(access,"production_reconciliation",lambda *_a,**_k:bad)
    called=[]
    result=run_production_strategic_audit("postgresql://x@y/db",reader=lambda *_a,**_k:called.append(True))
    assert result["status"]=="STOPPED" and result["reason"]=="PRODUCTION_LEDGER_MISMATCH"
    assert called==[]


def test_discovered_et_window_is_passed_to_bounded_reader(monkeypatch):
    data=reconciliation()
    monkeypatch.setattr(access,"production_reconciliation",lambda *_a,**_k:data)
    calls=[]
    result=run_production_strategic_audit("postgresql://x@y/db",reader=lambda url,**kwargs:calls.append((url,kwargs)) or snapshot())
    assert result["status"]=="COMPLETED"
    assert calls[0][1]["start_utc"].astimezone(access.EASTERN).date().isoformat()=="2026-08-17"
    assert calls[0][1]["end_utc"].astimezone(access.EASTERN).date().isoformat()=="2026-08-18"
    assert result["report"]["performance"]["SPY"]["closed_trades"]==2
    assert result["report"]["performance"]["QQQ"]["closed_trades"]==2
    assert result["report"]["performance"]["MIRROR"]["closed_trades"]==0


def test_cached_download_does_not_rerun_and_sanitizes_secrets():
    st,calls=FakeStreamlit(True),[]
    result={"status":"COMPLETED","reason":None,"database":{"fingerprint":"safe"},"reconciliation":{},"sessions":{},
        "report":{"rows":[{"trade_id":"exact","nested":[1,2]}],"DATABASE_URL":"postgresql://user:secret@host/db"}}
    runner=lambda *_a,**_k:calls.append("run") or result
    render_production_strategic_audit(st,database_resolver=lambda _:"postgresql://redacted",audit_runner=runner)
    st.clicked=False
    render_production_strategic_audit(st,database_resolver=lambda _:(_ for _ in ()).throw(AssertionError()),audit_runner=runner)
    assert calls==["run"]
    exported=json.loads(strategic_export_json(result))
    assert exported["report"]["rows"][0]["nested"]==[1,2]
    assert "DATABASE_URL" not in json.dumps(exported) and "secret" not in json.dumps(exported)
    assert strategic_export_filename(datetime(2026,8,18,12,tzinfo=timezone.utc))=="optionbeacon_spy_qqq_strategic_audit_2026-08-18.json"


def test_access_is_read_only_projected_bounded_provider_free_and_no_local_db_assumption():
    orchestration=inspect.getsource(access).lower()
    reader=inspect.getsource(__import__("analysis.run_spy_qqq_strategic_audit",fromlist=["read_snapshot"])).lower()
    assert "read_only_connection" in orchestration and "dashboard_database_url" not in orchestration
    assert "select *" not in reader and "limit %s" in reader and "start_utc" in reader and "end_utc" in reader
    for forbidden in ("insert ","update ","delete ","create table","option_quote","chain_provider","tradier"):
        assert forbidden not in orchestration and forbidden not in reader
    assert "sqlite" not in orchestration and "default_transaction_read_only" not in orchestration


def test_no_sessions_returns_completed_insufficient_report(monkeypatch):
    data=reconciliation(sessions={"discovered":[],"complete":[],"incomplete_excluded":[],
        "earliest_broad_universe_session":None,"earliest_spy_qqq_session":None,"latest_session":None})
    monkeypatch.setattr(access,"production_reconciliation",lambda *_a,**_k:data)
    result=run_production_strategic_audit("postgresql://x@y/db",reader=lambda *_a,**_k:(_ for _ in ()).throw(AssertionError()))
    assert result["status"]=="COMPLETED"
    assert result["report"]["audit_metadata"]["operational_status"]=="INSUFFICIENT DATA"
    assert result["report"]["performance"]["SPY"]["closed_trades"]==0


def test_null_and_postgres_timestamps_are_safe():
    assert _et_day(None) is None
    assert _et_day(datetime(2026,8,18,14,tzinfo=timezone.utc))=="2026-08-18"


def test_missing_optional_variant_column_skips_query_in_read_only_transaction():
    class Cursor:
        def __init__(self): self.statement=""; self.statements=[]
        def __enter__(self): return self
        def __exit__(self,*_): return False
        def execute(self,statement,*_): self.statement=statement; self.statements.append(statement)
        def fetchall(self):
            if "information_schema.columns" in self.statement:
                return [{"table_name":"intraday_paper_trades","column_name":name} for name in ("trade_id","symbol","status")]
            return []
        def fetchone(self): return {"value":0}
    class Connection:
        def __init__(self): self.autocommit=None;self.item=Cursor()
        def cursor(self): return self.item
        def rollback(self): pass
        def close(self): pass
    connection=Connection()
    result=production_reconciliation("postgresql://pooler/db",connector=lambda *_a,**_k:connection,
        now=datetime(2026,8,18,20,tzinfo=timezone.utc))
    assert result["spy_intraday_trades"]==0
    assert result["spy_intraday_mirror"] is None and result["spy_intraday_managed"] is None
    assert not any("variant=" in statement for statement in connection.item.statements)


def test_every_session_union_branch_has_stable_session_date_alias():
    source=inspect.getsource(production_reconciliation)
    session_selects=[line for line in source.splitlines() if "session_queries.append" in line]
    assert len(session_selects)==3
    assert all("AS session_date" in line for line in session_selects)


def test_dashboard_displays_sanitized_stage_without_raw_exception():
    st=FakeStreamlit(True)
    failure=StrategicAuditFailure("SESSION_DISCOVERY","ProgrammingError","schema unavailable")
    render_production_strategic_audit(st,database_resolver=lambda _:"postgresql://redacted",
        audit_runner=lambda *_a,**_k:(_ for _ in ()).throw(failure))
    rendered=json.dumps(st.calls)
    assert "Strategic audit failed during SESSION_DISCOVERY (ProgrammingError)." in rendered
    assert "schema unavailable" not in rendered and "postgresql://" not in rendered


def test_completed_report_serializes_postgres_scalar_types():
    result={"status":"COMPLETED","report":{"pnl":Decimal("12.34"),
        "observed_at":datetime(2026,8,18,14,tzinfo=timezone.utc),
        "trade_id":UUID("12345678-1234-5678-1234-567812345678")}}
    encoded=strategic_export_json(result)
    decoded=json.loads(encoded)
    assert decoded["report"]["pnl"]=="12.34"
    assert decoded["report"]["trade_id"]=="12345678-1234-5678-1234-567812345678"
