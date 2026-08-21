from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import inspect

import app
import whole_app_audit as audit
from whole_app_audit_dashboard import RESULT_KEY, render_whole_app_audit, whole_app_audit_json


class Cursor:
    def __init__(self): self.query="";self.params=None
    def __enter__(self): return self
    def __exit__(self,*_): return False
    def execute(self,query,params=None): self.query=query;self.params=params
    def fetchall(self):
        if "information_schema.columns" in self.query:
            return [{"table_name":item[2],"column_name":column} for item in audit.INVENTORY if item[2]
                for column in ({item[3]} if item[3] else set()) | {"id"}]
        return []
    def fetchone(self):
        if "pg_total_relation_size" in self.query:return {"bytes":2048}
        return {"records":12,"first_observation":datetime(2026,8,1,tzinfo=timezone.utc),
            "last_observation":datetime(2026,8,20,tzinfo=timezone.utc)}


class Connection:
    def cursor(self): return Cursor()


@contextmanager
def readonly(*_args,**_kwargs): yield Connection()


def test_complete_inventory_is_read_only_evidence_gated_and_control_is_hidden(monkeypatch):
    monkeypatch.setattr(audit,"read_only_connection",readonly)
    monkeypatch.setattr(audit,"database_fingerprint",lambda _url:"safe-fingerprint")
    result=audit.run_whole_app_audit("postgresql://secret",now=datetime(2026,8,21,tzinfo=timezone.utc))
    assert result["status"]=="COMPLETED" and len(result["components"])>=30
    assert result["metadata"]["provider_calls"]==0 and result["metadata"]["database_writes"]==0
    assert "secret" not in whole_app_audit_json(result)
    control=next(row for row in result["components"] if row["component"]=="QQQ MIRROR Control")
    assert control["classification"]=="VALUABLE CONTROL — KEEP HIDDEN / RESEARCH ONLY"
    assert result["governance"]["minimum_evidence"]["0-9"]=="INSUFFICIENT DATA"
    assert result["table_evidence"]["intraday_paper_trades"]["records"]==12


def test_evidence_bands_and_missing_table_do_not_create_low_value_judgment():
    assert [audit.evidence_band(value) for value in (0,9,10,29,30,49,50)]==[
        "INSUFFICIENT DATA","INSUFFICIENT DATA","DESCRIPTIVE ONLY","DESCRIPTIVE ONLY","UNSTABLE","UNSTABLE","EVALUABLE"]
    item=next(row for row in audit.INVENTORY if row[0]=="QQQ FIRST_TWO")
    assert audit._classification(item,exists=True,count=3,freshness="ACTIVE / RECENT")=="UNPROVEN — INSUFFICIENT DATA"
    assert audit._classification(item,exists=False,count=0,freshness="NOT MEASURABLE")=="BROKEN / MISCONFIGURED — FIX BEFORE JUDGING"


class FakeStreamlit:
    def __init__(self,clicked=False): self.clicked=clicked;self.session_state={};self.calls=[]
    def expander(self,*args,**kwargs): self.calls.append(("expander",args,kwargs));return nullcontext()
    def warning(self,*args,**kwargs): self.calls.append(("warning",args,kwargs))
    def caption(self,*args,**kwargs): self.calls.append(("caption",args,kwargs))
    def button(self,*args,**kwargs): self.calls.append(("button",args,kwargs));return self.clicked
    def spinner(self,*args,**kwargs): return nullcontext()
    def markdown(self,*args,**kwargs): self.calls.append(("markdown",args,kwargs))
    def json(self,*args,**kwargs): self.calls.append(("json",args,kwargs))
    def download_button(self,*args,**kwargs): self.calls.append(("download",args,kwargs))
    def error(self,*args,**kwargs): self.calls.append(("error",args,kwargs))


def test_dashboard_has_no_page_load_query_and_serializes_cached_result_without_rerun():
    calls=[];st=FakeStreamlit()
    assert render_whole_app_audit(st,database_resolver=lambda *_:calls.append("resolve"),audit_runner=lambda *_:calls.append("run")) is None
    assert calls==[] and ("WHOLE APP AUDIT" in st.calls[0][1])
    result={"classification_counts":{},"recommendations":{},"components":[],"metadata":{"database_writes":0}}
    st.session_state[RESULT_KEY]=result
    assert render_whole_app_audit(st,database_resolver=lambda *_:calls.append("resolve"),audit_runner=lambda *_:calls.append("run"))==result
    assert calls==[] and any(call[0]=="download" for call in st.calls)
    source=inspect.getsource(audit.run_whole_app_audit).lower()
    for forbidden in ("insert ","update ","delete ","create table","option_quote(","option_chain("):
        assert forbidden not in source
    assert "render_whole_app_audit(st)" in inspect.getsource(app.render_developer_tools)


def test_normal_ui_demotes_mirror_while_research_access_and_backend_remain():
    desk=inspect.getsource(__import__("trade_desk_comparison").comparison_markup)
    paper=inspect.getsource(app.render_paper_trading_page)
    assert "MIRROR CAPITAL DEPLOYED" not in desk and "MIRROR OPTION P&L" not in desk
    assert "CONTROL RESEARCH" in paper and "FULL-PARTICIPATION CONTROL" in paper
    assert "MirrorExecutionRepository" in paper and "mirror_repository.rows()" in paper
