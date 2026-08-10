import inspect
from datetime import datetime, timedelta, timezone

from mirror_execution import MirrorExecutionRepository
from paper_execution_repository import PaperExecutionRepository
from trade_repository import TradeRepository, query_egress_diagnostics_enabled


NOW = datetime(2026, 8, 10, 14, tzinfo=timezone.utc)


def repository(tmp_path):
    return TradeRepository(tmp_path / "state.db", database_url="")


def insert_marks(repo):
    mirror = MirrorExecutionRepository(repo)
    with repo.connection() as connection:
        for trade, offset, value in (("wanted", 0, -5), ("wanted", 1, 20), ("other", 2, 99)):
            observed = NOW + timedelta(minutes=offset)
            repo._execute(connection, """INSERT INTO mirror_execution_marks
                (mark_id,mirror_trade_id,opportunity_id,symbol,observed_at,return_pct,
                 mfe_pct,mae_pct,peak_return_pct,peak_unrealized_pnl,update_status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (f"{trade}-{offset}",trade,trade,"SPY",observed.isoformat(),value,
                 max(value,0),min(value,0),max(value,0),value,"CURRENT")).close()
    return mirror


def test_mark_summary_is_exact_trade_and_date_bounded(tmp_path):
    mirror = insert_marks(repository(tmp_path))
    all_wanted = mirror.mark_summaries(["wanted"])
    recent = mirror.mark_summaries(["wanted"], observed_after=NOW + timedelta(seconds=30))
    assert all_wanted == [{
        "mirror_trade_id": "wanted", "valid_mark_count": 2,
        "mfe_pct": 20.0, "mae_pct": -5.0, "peak_return_pct": 20.0,
        "peak_unrealized_pnl": 20.0,
        "first_observed_at": NOW.isoformat(),
        "last_observed_at": (NOW + timedelta(minutes=1)).isoformat(),
    }]
    assert recent[0]["valid_mark_count"] == 1 and recent[0]["mae_pct"] == 0.0


def test_mark_summary_matches_raw_python_aggregation(tmp_path):
    mirror = insert_marks(repository(tmp_path))
    raw = mirror.marks("wanted")
    summary = mirror.mark_summaries(["wanted"])[0]
    assert summary["valid_mark_count"] == len([row for row in raw if row["return_pct"] is not None])
    assert summary["mfe_pct"] == max(row["mfe_pct"] for row in raw)
    assert summary["mae_pct"] == min(row["mae_pct"] for row in raw)


def test_empty_and_parameterized_mark_queries_are_safe(tmp_path):
    mirror = MirrorExecutionRepository(repository(tmp_path))
    assert mirror.mark_summaries([]) == []
    source = inspect.getsource(MirrorExecutionRepository.mark_summaries)
    assert "mirror_trade_id IN" in source and "?" in source
    assert "SELECT *" not in source and "GROUP BY mirror_trade_id" in source


def test_analytics_trade_projection_is_exact_and_limited(tmp_path):
    repo = repository(tmp_path)
    mirror = MirrorExecutionRepository(repo)
    with repo.connection() as connection:
        for identity in ("a", "b"):
            repo._execute(connection, """INSERT INTO mirror_execution_trades
                (mirror_trade_id,opportunity_id,symbol,quantity,contract_multiplier,
                 status,disposition_code,fill_model,metadata_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (f"m-{identity}",identity,"SPY",1,100,"UNEXECUTABLE","TEST","TEST","{}",
                 NOW.isoformat(),NOW.isoformat())).close()
    rows = mirror.analytics_rows(["a"], limit=1)
    assert len(rows) == 1 and rows[0]["opportunity_id"] == "a"
    assert "disposition_detail" not in rows[0]


def test_broad_analytics_decisions_are_projected_and_bounded(tmp_path):
    source = inspect.getsource(PaperExecutionRepository.analytics_decisions)
    assert "source_signal_id IN" in source and "LIMIT ?" in source
    assert "SELECT *" not in source


def test_heavy_dashboards_are_query_on_demand_and_paginated():
    winner = open("winner_dna_dashboard.py", encoding="utf-8").read()
    selectivity = open("selectivity_dashboard.py", encoding="utf-8").read()
    app = open("app.py", encoding="utf-8").read()
    assert winner.index("Load Winner DNA analytics") < winner.index("list_intelligence_snapshots")
    assert selectivity.index("Load Selectivity analytics") < selectivity.index("list_intelligence_snapshots")
    assert "Winner DNA history limit" in winner and "Selectivity history limit" in selectivity
    assert "PAPER history rows" in app
    assert "mirror_repository.marks()" not in winner


def test_diagnostics_are_opt_in_and_do_not_log_payloads():
    assert query_egress_diagnostics_enabled("false") is False
    assert query_egress_diagnostics_enabled("true") is True
    source = inspect.getsource(TradeRepository._fetchall)
    assert "rows_returned" in source and "approx_result_bytes" in source and "duration_ms" in source
    assert '"params"' not in source and "DATABASE_URL" not in source


def test_streamlit_paths_add_no_writes_or_trading_hooks():
    sources = open("winner_dna_dashboard.py", encoding="utf-8").read() + open("selectivity_dashboard.py", encoding="utf-8").read()
    for forbidden in (".save(", ".append(", "record_disposition(", "update_mark(", "run_mirror_execution(", "evaluate_execution("):
        assert forbidden not in sources
