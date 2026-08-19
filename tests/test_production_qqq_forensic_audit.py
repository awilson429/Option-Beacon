import inspect
import json
from contextlib import nullcontext
from datetime import datetime, timezone

import app
import analysis.production_qqq_forensic_audit as audit
from qqq_forensic_dashboard import (qqq_forensic_export_filename,
    qqq_forensic_export_json, render_production_qqq_forensic_audit)


class FakeStreamlit:
    def __init__(self,clicked=False): self.clicked=clicked; self.calls=[]; self.session_state={}
    def expander(self,*a,**k): return nullcontext()
    def warning(self,v): self.calls.append(("warning",v))
    def caption(self,v): self.calls.append(("caption",v))
    def button(self,*a,**k): return self.clicked
    def error(self,v): self.calls.append(("error",v))
    def spinner(self,v): return nullcontext()
    def markdown(self,v): pass
    def json(self,v): self.calls.append(("json",v))
    def download_button(self,*a,**k): self.calls.append(("download",a,k))


def reconciliation(**patch):
    value={"qqq_signal_count":3,"qqq_trade_count":1,"qqq_closed_trade_count":1,
        "sessions":{"discovered":["2026-08-18"],"complete":["2026-08-18"],"incomplete_excluded":[]}}
    value.update(patch); return value


def snapshot():
    return {"trades":[{"trade_id":"t1","opportunity_id":"o1","symbol":"QQQ","status":"CLOSED",
        "opened_at":"2026-08-18T14:00:00+00:00","closed_at":"2026-08-18T15:00:00+00:00","pnl":2,"return_pct":2,"mfe":5,"mae":-1}],
        "signals":[],"contexts":[],"marks":[{"trade_id":"t1","observed_at":"2026-08-18T14:30:00Z","mark_json":{"nested":[1,2]}}],
        "journals":[],"metadata":{"read_only":True,"provider_calls":0,"database_writes":0}}


def test_normal_page_load_is_query_free_and_uses_canonical_resolver():
    calls=[]
    assert render_production_qqq_forensic_audit(FakeStreamlit(),database_resolver=lambda _:calls.append("resolve"),audit_runner=lambda *_a,**_k:calls.append("run")) is None
    assert calls == []
    assert "database_resolver=dashboard_database_url" in inspect.getsource(render_production_qqq_forensic_audit)
    assert "render_production_qqq_forensic_audit(st)" in inspect.getsource(app.render_developer_tools)


def test_completed_window_uses_existing_analytics_and_preserves_exact_records(monkeypatch):
    monkeypatch.setattr(audit,"production_qqq_reconciliation",lambda *_a,**_k:reconciliation())
    calls=[]
    result=audit.run_production_qqq_forensic_audit("postgresql://x@y/db",reader=lambda url,**kwargs:calls.append(kwargs) or snapshot())
    assert result["status"] == "COMPLETED"
    assert calls[0]["start_utc"].astimezone(audit.EASTERN).date().isoformat()=="2026-08-18"
    assert result["report"]["per_trade"][0]["trade_id"]=="t1"
    assert result["report"]["underlying_records"]["marks"][0]["trade_id"]=="t1"
    assert result["report"]["underlying_records"]["marks"][0]["mark_json"]["nested"]==[1,2]
    assert result["report"]["metadata"]["provider_calls"]==0


def test_ledger_mismatch_stops_without_analytics(monkeypatch):
    monkeypatch.setattr(audit,"production_qqq_reconciliation",lambda *_a,**_k:reconciliation())
    monkeypatch.setattr(audit,"analyze_qqq_forensics",lambda *_a,**_k:(_ for _ in ()).throw(AssertionError()))
    result=audit.run_production_qqq_forensic_audit("postgresql://x@y/db",reader=lambda *_a,**_k:{**snapshot(),"trades":[]})
    assert result["status"]=="STOPPED" and result["reason"]=="PRODUCTION_QQQ_LEDGER_MISMATCH"


def test_cached_download_is_complete_secret_free_and_does_not_rerun():
    st,calls=FakeStreamlit(True),[]
    result={"status":"COMPLETED","database":{"fingerprint":"safe"},"reconciliation":{},
        "report":{"per_trade":[{"trade_id":"t1","nested":{"marks":[1,2]}}],"DATABASE_URL":"postgresql://u:secret@h/db"}}
    runner=lambda *_a,**_k:calls.append("run") or result
    render_production_qqq_forensic_audit(st,database_resolver=lambda _:"postgresql://redacted",audit_runner=runner)
    st.clicked=False
    render_production_qqq_forensic_audit(st,database_resolver=lambda _:(_ for _ in ()).throw(AssertionError()),audit_runner=runner)
    exported=json.loads(qqq_forensic_export_json(result))
    assert calls==["run"] and exported["report"]["per_trade"][0]["nested"]["marks"]==[1,2]
    assert "DATABASE_URL" not in json.dumps(exported) and "secret" not in json.dumps(exported)
    assert qqq_forensic_export_filename(datetime(2026,8,18,12,tzinfo=timezone.utc))=="optionbeacon_qqq_winner_dna_exit_forensics_2026-08-18.json"


def test_production_layer_is_read_only_provider_free_and_does_not_change_methodology():
    source=inspect.getsource(audit).lower()
    reader=inspect.getsource(__import__("analysis.run_qqq_winner_dna_exit_forensics",fromlist=["read_qqq_snapshot"])).lower()
    assert "read_only_connection" in source and "analyze_qqq_forensics" in source
    assert "trade_id = any(%s)" in reader and "order by {order}" in reader
    for forbidden in ("insert ","update ","delete ","create table","provider(","tradier"):
        assert forbidden not in source
