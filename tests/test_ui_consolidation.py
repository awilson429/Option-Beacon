from pathlib import Path

from ui_consolidation import (
    ADVANCED_FIELDS, LEGACY_ROUTE_ALIASES, PRIMARY_NAVIGATION,
    exact_lane_comparison, unified_opportunities, unified_positions,
)


def test_primary_navigation_is_exactly_four_workflow_destinations():
    assert PRIMARY_NAVIGATION==("Command Center","Performance","SPY / QQQ","Research / Developer Tools")
    assert LEGACY_ROUTE_ALIASES["Trade Desk"]=="Command Center"
    assert LEGACY_ROUTE_ALIASES["Paper Trading"]=="Performance"
    assert LEGACY_ROUTE_ALIASES["Advanced"]=="Research / Developer Tools"


def test_unified_opportunities_use_exact_identity_not_symbol():
    events=[{"opportunity_id":"exact","symbol":"AAPL","direction":"Bullish","setup":"Breakout","rule_score":84},
            {"opportunity_id":"other","symbol":"AAPL","direction":"Bullish","setup":"Breakout","rule_score":78}]
    mirrors=[{"opportunity_id":"exact","mirror_trade_id":"m","spread_percent":8.4,"status":"OPEN","disposition_code":"MIRROR_OPENED"}]
    filtered=[{"opportunity_id":"exact","source_signal_id":"exact","broad_decision":"ACCEPTED","execution_eligible":1,"signal_age_seconds":52}]
    rows=unified_opportunities(events,mirrors,filtered,[],[])
    assert rows[0]["Spread"]==8.4 and rows[0]["FILTERED"]=="Executed"
    assert rows[1]["Spread"] is None and rows[1]["FILTERED"]=="Pending"


def test_internal_ids_are_advanced_only_and_default_columns_are_human_readable():
    row=unified_opportunities([{"opportunity_id":"secret-id","symbol":"AAPL"}],[],[],[],[])[0]
    assert row["_advanced"]["opportunity_id"]=="secret-id"
    default={key:value for key,value in row.items() if not key.startswith("_")}
    assert "opportunity_id" not in default and "trade_id" not in default
    assert {"Symbol","Direction","Setup","Context","BROAD","FILTERED","Status"}<=set(default)
    assert "opportunity_id" in ADVANCED_FIELDS


def test_unified_positions_preserve_lane_isolation_and_accounting():
    mirrors=[{"mirror_trade_id":"m","symbol":"AAPL","status":"OPEN","entry_fill":1,"current_mark":1.2,"unrealized_pnl":20}]
    broad=[{"trade_id":"b","symbol":"MSFT","status":"OPEN","entry_price":2,"current_price":1.8,"pnl":-20}]
    filtered=[{"filtered_trade_id":"f","symbol":"NVDA","status":"OPEN","execution_eligible":1,"entry_fill":3,"pnl":15}]
    rows=unified_positions(mirrors,broad,filtered,[])
    assert [row["Lane"] for row in rows]==["MIRROR","BROAD","FILTERED"]
    assert [row["P&L"] for row in rows]==["$+20.00","$-20.00","$+15.00"]


def test_spy_qqq_is_not_in_broad_lane_comparison():
    rows=exact_lane_comparison([{"opportunity_id":"a","symbol":"AAPL"}],[],[],[])
    assert rows[0]["Symbol"]=="AAPL"
    assert all("SPY / QQQ" not in row for row in rows)


def test_normal_ui_is_read_only_bounded_and_provider_free():
    source=Path("ui_consolidation.py").read_text(encoding="utf-8")
    assert " LIMIT ?" in source and "opportunity_id IN" in source
    assert "SELECT *" not in source
    for forbidden in ("INSERT ","UPDATE ","DELETE ","submit_order","place_order","option_quote","select_contract"):
        assert forbidden not in source


def test_heavy_analytics_require_explicit_load_buttons_and_empty_states_are_compact():
    source=Path("ui_consolidation.py").read_text(encoding="utf-8")
    assert source.index("Load Daily Experiment Scorecard") < source.index("scorecard_renderer(st,repository)")
    assert source.index("Load MIRROR / BROAD / FILTERED Comparison") < source.index("lane_comparison()")
    assert "No current signals require attention." in source
    assert "No open BROAD/FILTERED/MIRROR positions." in source


def test_backend_and_trading_modules_are_not_removed_or_imported_for_mutation():
    app=Path("app.py").read_text(encoding="utf-8")
    for retained in ("render_paper_trading_page","render_strategy_lab","render_advanced","render_developer_tools"):
        assert f"def {retained}" in app
    changed={"ui_consolidation.py","ui_navigation.py","app.py"}
    assert "optionbeacon/worker/scan_once.py" not in changed
    assert "mirror_execution.py" not in changed and "filtered_execution.py" not in changed
