from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from analysis.provenance_validation import build_report, main, write_csv, write_json
from api.main import create_app
from api.services import OptionBeaconReadService


NOW = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)


class StubRepository:
    def __init__(self, **tables): self.tables = tables
    @contextmanager
    def connection(self): yield object()
    def _fetchall(self, connection, query, params=()):
        table = query.split("FROM ", 1)[1].split()[0]
        return list(self.tables.get(table, []))
    @staticmethod
    def _provenance_table_unavailable(exc): return False
    def latest_provenance_cycle(self): return None
    def list_recent_provenance_observations(self, **kwargs): return []


def cycle(**changes):
    row = {"scan_cycle_id":"c1","started_at":NOW.isoformat(),"completed_at":(NOW+timedelta(minutes=1)).isoformat(),
           "cycle_status":"COMPLETE","provenance_status":"HEALTHY"}
    row.update(changes); return row


def observation(symbol="SPY", **changes):
    row = {"observation_id":f"o-{symbol}","scan_cycle_id":"c1","symbol":symbol,"observed_at":(NOW+timedelta(seconds=1)).isoformat(),
           "qualification_state":"NO_SETUP","reason_code":"NO_TRADE_PLAN","explanation":"No canonical setup.","stale":0,"opportunity_id":None}
    row.update(changes); return row


def test_rejected_no_trade_chain_is_healthy_and_separated_by_symbol():
    report = build_report(StubRepository(provenance_scan_cycles=[cycle()], provenance_observations=[observation("SPY"),observation("QQQ")]), session_date=date(2026,8,25))
    assert report["provenance_health"]["state"] == "HEALTHY"
    assert report["qualification_distribution"][1]["count"] == 2
    assert report["symbol_breakdown"]["SPY"]["observations"] == 1
    assert report["chain_completeness"]["trade_links"] == 0


def test_empty_and_partial_first_session_are_explicit_low_data_states():
    empty = build_report(StubRepository(), session_date=date(2026,8,25))
    partial = build_report(StubRepository(provenance_scan_cycles=[cycle(completed_at=None,cycle_status="SCANNING")]), session_date=date(2026,8,25))
    assert empty["data_status"] == "NO_PROVENANCE_DATA"
    assert partial["data_status"] == "NO_PROVENANCE_DATA"
    assert not empty["research_eligible"]


def test_degraded_missing_symbol_and_zero_observations_reduce_health():
    report = build_report(StubRepository(provenance_scan_cycles=[cycle(provenance_status="DEGRADED")], provenance_observations=[observation("SPY")]), session_date=date(2026,8,25))
    assert report["session_summary"]["QQQ_observations"] == 0
    assert report["session_summary"]["observation_coverage_pct"] == 50.0
    assert any(i["issue_code"] == "DEGRADED_CYCLE" for i in report["integrity_issues"])
    assert report["provenance_health"]["state"] == "DEGRADED"


def test_identity_lane_temporal_and_chain_failures_are_reported_unreliable():
    opp={"id":"p1","symbol":"SPY","created_at":(NOW+timedelta(seconds=10)).isoformat()}
    obs=observation("SPY",qualification_state="QUALIFIED",reason_code="QUALIFIED",opportunity_id="p1")
    link={"decision_id":"d1","observation_id":obs["observation_id"],"opportunity_id":"wrong","lane":"MIRROR","decision_state":"TAKE","decided_at":NOW.isoformat(),"trade_id":"missing"}
    report=build_report(StubRepository(provenance_scan_cycles=[cycle()],provenance_observations=[obs,dict(obs)],provenance_decision_trade_links=[link],opportunities=[opp]),session_date=date(2026,8,25))
    codes={i["issue_code"] for i in report["integrity_issues"]}
    assert {"DUPLICATE_OBSERVATION","NON_DEPLOYABLE_LANE_CONTAMINATION","DECISION_OPPORTUNITY_NOT_FOUND","TRADE_NOT_FOUND"} <= codes
    assert report["provenance_health"]["state"] == "UNRELIABLE"
    assert report["provenance_health"]["score"] <= 49


def test_ob_broad_collision_and_management_lane_mismatch_are_critical():
    opp={"id":"p1","symbol":"SPY","created_at":NOW.isoformat()}; obs=observation("SPY",qualification_state="QUALIFIED",reason_code="QUALIFIED",opportunity_id="p1")
    links=[{"decision_id":f"d-{lane}","observation_id":obs["observation_id"],"opportunity_id":"p1","lane":lane,"decision_state":"TAKE","decided_at":(NOW+timedelta(seconds=2)).isoformat(),"trade_id":"t1"} for lane in ("OB","BROAD")]
    trade={"id":"t1","opportunity_id":"p1","opened_at":(NOW+timedelta(seconds=3)).isoformat(),"closed_at":None,"realized_result":None}
    management={"trade_id":"t1","opportunity_id":"p1","lane":"CONTROL_RESEARCH","captured_at":(NOW+timedelta(seconds=4)).isoformat(),"entry_timestamp":trade["opened_at"]}
    report=build_report(StubRepository(provenance_scan_cycles=[cycle()],provenance_observations=[obs],provenance_decision_trade_links=links,opportunities=[opp],authoritative_trades=[trade],trade_management_snapshots=[management]),session_date=date(2026,8,25))
    codes={i["issue_code"] for i in report["integrity_issues"]}
    assert "OB_BROAD_TRADE_COLLISION" in codes and "MANAGEMENT_LANE_MISMATCH" in codes


def test_exports_cli_and_read_only_api(tmp_path, monkeypatch):
    repo=StubRepository(provenance_scan_cycles=[cycle()],provenance_observations=[observation("SPY"),observation("QQQ")])
    report=build_report(repo,session_date=date(2026,8,25)); json_path=tmp_path/"report.json"; csv_dir=tmp_path/"csv"
    write_json(report,json_path); write_csv(report,csv_dir)
    assert json_path.exists() and (csv_dir/"integrity-issues.csv").exists()
    monkeypatch.setattr("analysis.provenance_validation.TradeRepository",lambda *a:repo)
    assert main(["--date","2026-08-25","--json-output",str(tmp_path/"cli.json")])["report_version"] == 1
    service=OptionBeaconReadService(repository=repo,now=lambda:NOW)
    response=TestClient(create_app(service=service)).get("/api/provenance/validation?date=2026-08-25")
    assert response.status_code == 200 and response.json()["provenance_health"]["state"] == "HEALTHY"


def test_counterfactual_outcomes_are_never_invented():
    report=build_report(StubRepository(provenance_scan_cycles=[cycle()],provenance_observations=[observation("SPY"),observation("QQQ")]),session_date=date(2026,8,25))
    assert report["exploratory_metrics"]["counterfactual_outcomes"] == "UNAVAILABLE_COUNTERFACTUAL_OUTCOME"
