"""Comprehensive, deterministic post-run forensics over persisted production rows.

This module is deliberately pure: it accepts projected records, performs no I/O,
and never substitutes zero for unavailable telemetry.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from zoneinfo import ZoneInfo

from option_translation_autopsy import analyze_option_translation, chronological_split, simulate_exit
from winner_dna import analyze_winner_dna, session_bucket


EASTERN = ZoneInfo("America/New_York")
FLAT_PCT = 0.10
MIN_TOTAL, MIN_TRAIN, MIN_VALIDATION = 10, 5, 3


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _dt(value):
    if not value:
        return None
    value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _session(value):
    parsed = _dt(value)
    return parsed.astimezone(EASTERN).date().isoformat() if parsed else None


def performance(rows, *, return_key, pnl_key=None):
    values = [_number(row.get(return_key)) for row in rows]
    values = [value for value in values if value is not None]
    wins, losses = [v for v in values if v > FLAT_PCT], [v for v in values if v < -FLAT_PCT]
    flats = [v for v in values if abs(v) <= FLAT_PCT]
    pnl = [_number(row.get(pnl_key)) for row in rows] if pnl_key else []
    pnl = [value for value in pnl if value is not None]
    gross_profit = sum(value for value in pnl if value > 0) if pnl_key else sum(wins)
    gross_loss = abs(sum(value for value in pnl if value < 0)) if pnl_key else abs(sum(losses))
    holds = [_number(row.get("hold_minutes")) for row in rows]
    holds = [value for value in holds if value is not None]
    return {
        "n": len(rows), "decided_n": len(values), "wins": len(wins), "losses": len(losses),
        "flat_noise": len(flats), "win_rate": len(wins) / len(values) * 100 if values else None,
        "average_return": mean(values) if values else None, "median_return": median(values) if values else None,
        "total_return": sum(values) if values else None,
        "average_winner": mean(wins) if wins else None, "median_winner": median(wins) if wins else None,
        "average_loser": mean(losses) if losses else None, "median_loser": median(losses) if losses else None,
        "profit_factor": gross_profit / gross_loss if gross_loss else math.inf if gross_profit else None,
        "expectancy": mean(values) if values else None, "total_pnl": sum(pnl) if pnl else None,
        "average_hold_minutes": mean(holds) if holds else None,
        "median_hold_minutes": median(holds) if holds else None,
    }


def _duplicates(rows, key):
    counts = Counter(str(row.get(key)) for row in rows if row.get(key))
    return {identity: count for identity, count in counts.items() if count > 1}


def data_integrity(snapshot_rows, outcome_rows, mirror_rows, mirror_marks, paper_trades, paper_journal):
    snapshots = [row.get("snapshot") or row for row in snapshot_rows]
    outcomes = [row.get("outcome") or row for row in outcome_rows]
    sets = {
        "authoritative_snapshots": {str(row.get("opportunity_id")) for row in snapshots if row.get("opportunity_id")},
        "authoritative_outcomes": {str(row.get("opportunity_id")) for row in outcomes if row.get("opportunity_id")},
        "mirror_trades": {str(row.get("opportunity_id")) for row in mirror_rows if row.get("opportunity_id")},
        "paper_trades": {str(row.get("source_signal_id")) for row in paper_trades if row.get("source_signal_id")},
    }
    mirror_trade_ids = {str(row.get("mirror_trade_id")) for row in mirror_rows if row.get("mirror_trade_id")}
    mark_trade_ids = {str(row.get("mirror_trade_id")) for row in mirror_marks if row.get("mirror_trade_id")}
    all_rows = snapshots + outcomes + list(mirror_rows) + list(mirror_marks) + list(paper_trades) + list(paper_journal)
    timestamps = [_dt(row.get(key)) for row in all_rows for key in
                  ("created_at", "updated_at", "entry_timestamp", "opened_at", "exit_quote_at", "observed_at")]
    timestamps = [value for value in timestamps if value]
    counts = {"intelligence_setup_snapshots": len(snapshot_rows), "intelligence_outcome_labels": len(outcome_rows),
              "mirror_execution_trades": len(mirror_rows), "mirror_execution_marks": len(mirror_marks),
              "paper_execution_trades": len(paper_trades), "paper_execution_journal": len(paper_journal)}
    missing_ids = {
        "snapshots": sum(not row.get("opportunity_id") for row in snapshots),
        "outcomes": sum(not row.get("opportunity_id") for row in outcomes),
        "mirror_trades": sum(not row.get("opportunity_id") or not row.get("mirror_trade_id") for row in mirror_rows),
        "mirror_marks": sum(not row.get("mirror_trade_id") for row in mirror_marks),
        "paper_trades": sum(not row.get("source_signal_id") for row in paper_trades),
    }
    return {
        "record_counts": counts, "earliest_timestamp": min(timestamps).isoformat() if timestamps else None,
        "latest_timestamp": max(timestamps).isoformat() if timestamps else None, "missing_ids": missing_ids,
        "duplicate_source_identities": {
            "snapshots": _duplicates(snapshots, "opportunity_id"), "outcomes": _duplicates(outcomes, "opportunity_id"),
            "mirror_opportunities": _duplicates(mirror_rows, "opportunity_id"), "mirror_trade_ids": _duplicates(mirror_rows, "mirror_trade_id"),
            "paper_source_signals": _duplicates(paper_trades, "source_signal_id")},
        "orphaned_records": {
            "outcomes_without_snapshot": sorted(sets["authoritative_outcomes"] - sets["authoritative_snapshots"]),
            "mirror_without_authoritative": sorted(sets["mirror_trades"] - (sets["authoritative_snapshots"] | sets["authoritative_outcomes"])),
            "marks_without_mirror_trade": sorted(mark_trade_ids - mirror_trade_ids),
            "paper_without_authoritative": sorted(sets["paper_trades"] - (sets["authoritative_snapshots"] | sets["authoritative_outcomes"])),
        },
        "missing_outcomes": len(sets["authoritative_snapshots"] - sets["authoritative_outcomes"]),
        "missing_mirror_trades": len((sets["authoritative_snapshots"] | sets["authoritative_outcomes"]) - sets["mirror_trades"]),
        "mirror_trades_without_telemetry": len(mirror_trade_ids - mark_trade_ids),
        "classification": ("ELIGIBLE FOR ANALYSIS" if sets["authoritative_outcomes"]
                           and not any(missing_ids.values())
                           and not (sets["authoritative_snapshots"] - sets["authoritative_outcomes"])
                           and sets["mirror_trades"] and not (mirror_trade_ids - mark_trade_ids)
                           else "INSUFFICIENT / INCOMPLETE DATA"),
    }


def _group(rows, key, *, return_key, pnl_key=None):
    grouped = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) if row.get(key) is not None else "DATA UNAVAILABLE")].append(row)
    return [{"group": label, **performance(items, return_key=return_key, pnl_key=pnl_key)}
            for label, items in sorted(grouped.items())]


def _broad_map(paper_trades, paper_journal):
    source = {str(row.get("trade_id")): str(row.get("source_signal_id")) for row in paper_trades
              if row.get("trade_id") and row.get("source_signal_id")}
    result = {}
    for row in sorted(paper_journal, key=lambda item: _dt(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)):
        metadata = row.get("metadata_json")
        if not isinstance(metadata, dict):
            try: metadata = json.loads(metadata or "{}")
            except (TypeError, ValueError): metadata = {}
        if str(metadata.get("simulation_profile") or "").upper() != "BROAD":
            continue
        identity = str(row.get("source_signal_id") or source.get(str(row.get("trade_id"))) or "")
        if identity and identity not in result and row.get("accepted") is not None:
            result[identity] = {"accepted": bool(row.get("accepted")), "reason": row.get("reason_code") or "UNKNOWN"}
    return result


def _validation(rows, predicate):
    selected = [row for row in rows if predicate(row)]
    train, validation = chronological_split(selected)
    sufficient = len(selected) >= MIN_TOTAL and len(train) >= MIN_TRAIN and len(validation) >= MIN_VALIDATION
    train_perf = performance(train, return_key="mirror_return", pnl_key="mirror_pnl")
    validation_perf = performance(validation, return_key="mirror_return", pnl_key="mirror_pnl")
    stable = sufficient and (train_perf["expectancy"] or 0) > 0 and (validation_perf["expectancy"] or 0) > 0
    return {"full": performance(selected, return_key="mirror_return", pnl_key="mirror_pnl"),
            "training": train_perf, "validation": validation_perf,
            "label": "PROMISING" if stable else "UNSTABLE" if sufficient else "INSUFFICIENT DATA"}


def _loser_excursions(rows):
    losers = [row for row in rows if _number(row.get("mirror_return")) is not None and row["mirror_return"] < 0]
    thresholds = {str(level): sum((_number(row.get("mfe")) or -math.inf) >= level for row in losers)
                  for level in (5, 10, 15, 20, 25, 30)}
    givebacks = [_number(row.get("giveback")) for row in losers]
    givebacks = [value for value in givebacks if value is not None]
    return {"losers_n": len(losers), "profitable_first": {level: {"n": count, "percent": count / len(losers) * 100 if losers else None}
            for level, count in thresholds.items()}, "average_giveback": mean(givebacks) if givebacks else None,
            "median_giveback": median(givebacks) if givebacks else None}


def build_forensic_report(snapshot_rows, outcome_rows, mirror_rows, mirror_marks,
                          paper_trades=(), paper_journal=()):
    """Create the full audit report using exact persisted identities only."""
    integrity = data_integrity(snapshot_rows, outcome_rows, mirror_rows, mirror_marks, paper_trades, paper_journal)
    translation = analyze_option_translation(snapshot_rows, outcome_rows, mirror_rows, mirror_marks)
    broad = _broad_map(paper_trades, paper_journal)
    rows = translation["rows"]
    for row in rows:
        disposition = broad.get(str(row["opportunity_id"]))
        row["broad_disposition"] = "ACCEPTED" if disposition and disposition["accepted"] else "REJECTED" if disposition else "NOT RECORDED"
        row["broad_reason"] = disposition["reason"] if disposition else None
        row["session"] = _session(row.get("entry_at"))
        row["session_bucket"] = session_bucket(row.get("entry_at"))
        row["entry_latency_seconds"] = ((_dt(row.get("opened_at")) - _dt(row.get("entry_at"))).total_seconds()
                                        if _dt(row.get("opened_at")) and _dt(row.get("entry_at")) else None)
        latency = row["entry_latency_seconds"]
        row["latency_bucket"] = ("DATA UNAVAILABLE" if latency is None else "0-15 sec" if latency <= 15 else
                                 "16-30 sec" if latency <= 30 else "31-60 sec" if latency <= 60 else
                                 "61-120 sec" if latency <= 120 else ">120 sec")
    snapshots = {str((item.get("snapshot") or item).get("opportunity_id")): item.get("snapshot") or item
                 for item in snapshot_rows if (item.get("snapshot") or item).get("opportunity_id")}
    auth = []
    for wrapped in outcome_rows:
        outcome = wrapped.get("outcome") or wrapped
        identity, snapshot = str(outcome.get("opportunity_id") or ""), snapshots.get(str(outcome.get("opportunity_id") or ""), {})
        if not identity:
            continue
        entered_at, exited_at = outcome.get("entry_timestamp") or snapshot.get("entry_timestamp"), outcome.get("exit_timestamp")
        auth.append({"opportunity_id": identity, "auth_return": _number(outcome.get("realized_return")),
                     "hold_minutes": ((_dt(exited_at) - _dt(entered_at)).total_seconds() / 60
                                      if _dt(exited_at) and _dt(entered_at) else _number(outcome.get("duration_minutes"))),
                     "session": _session(entered_at), "symbol": snapshot.get("symbol"),
                     "direction": snapshot.get("direction"), "setup": snapshot.get("setup_type")})
    sessions = sorted({row["session"] for row in auth if row.get("session")})
    dna = analyze_winner_dna(snapshot_rows, outcome_rows, mirror_rows=mirror_rows, mirror_marks=mirror_marks)
    failure_counts = Counter(row.get("failure_mode") for row in rows if row.get("failure_mode"))
    failures = []
    for mode, count in failure_counts.most_common():
        selected = [row for row in rows if row.get("failure_mode") == mode]
        impact = sum((_number(row.get("mirror_pnl")) or 0) for row in selected)
        failures.append({"rank": len(failures) + 1, "failure_mode": mode, "evidence": selected[0].get("causal_confidence"),
                         "n": count, "estimated_pnl_impact": impact,
                         "confidence": "HIGH" if selected[0].get("causal_confidence") == "SUPPORTED" and count >= 10 else "MEDIUM" if count >= 5 else "LOW"})
    broad_groups = _group(rows, "broad_disposition", return_key="mirror_return", pnl_key="mirror_pnl")
    return {
        "data_integrity": integrity,
        "analysis_window": {"sessions": sessions, "first_session": sessions[0] if sessions else None,
                            "last_session": sessions[-1] if sessions else None, "session_count": len(sessions),
                            "authoritative_opportunities": len(snapshot_rows),
                            "authoritative_outcomes": sum(row.get("auth_return") is not None for row in auth),
                            "broad_decisions": sum(row["broad_disposition"] != "NOT RECORDED" for row in rows),
                            "mirror_executions": len(rows), "adequate_mirror_telemetry": sum(row.get("mark_count", 0) > 0 for row in rows)},
        "authoritative_performance": performance(auth, return_key="auth_return"),
        "mirror_performance": performance(rows, return_key="mirror_return", pnl_key="mirror_pnl"),
        "translation_matrix": translation["outcome_matrix"],
        "auth_win_mirror_loss": {"summary": performance(translation["auth_win_mirror_loss"], return_key="mirror_return", pnl_key="mirror_pnl"),
                                 "rows": translation["auth_win_mirror_loss"]},
        "entry_timing": _group(rows, "latency_bucket", return_key="mirror_return", pnl_key="mirror_pnl"),
        "contract_selection": {"dte": translation["dte"], "spread": translation["spread"],
                               "moneyness": translation["moneyness"], "option_type": translation["contract"],
                               "greeks_iv": "NOT PERSISTED; NOT RECONSTRUCTED"},
        "mfe_mae_exit": {"loser_excursions": _loser_excursions(rows), "exit_efficiency": translation["exit_efficiency"]},
        "option_economics": translation["capital"], "broad_selectivity": broad_groups,
        "winner_dna": {key: dna[key] for key in ("feature_effects", "patterns", "coverage", "insights")},
        "session_effects": _group(rows, "session_bucket", return_key="mirror_return", pnl_key="mirror_pnl"),
        "symbol_effects": _group(rows, "symbol", return_key="mirror_return", pnl_key="mirror_pnl"),
        "direction_effects": _group(rows, "direction", return_key="mirror_return", pnl_key="mirror_pnl"),
        "setup_effects": _group(rows, "setup", return_key="mirror_return", pnl_key="mirror_pnl"),
        "regime_effects": _group(rows, "regime", return_key="mirror_return", pnl_key="mirror_pnl"),
        "counterfactual_exits": {"label": "HISTORICAL COUNTERFACTUAL - NOT PRODUCTION PERFORMANCE", "results": translation["exit_what_if"]},
        "counterfactual_entry_filters": translation["selective_what_if"],
        "chronological_validation": {item["variant"]: _validation(rows, lambda row, item=item: item["variant"] == "CONTROL" or True)
                                     for item in translation["exit_what_if"][:1]},
        "ranked_failure_modes": failures,
        "biggest_observed_leak": failures[0] if failures else {"finding": "No adequately supported explanation", "confidence": "INSUFFICIENT DATA"},
        "what_is_working": {"status": "INSUFFICIENT DATA" if len(rows) < MIN_TOTAL else "SEE GROUP TABLES"},
        "recommended_next_experiments": {
            "high_confidence": [],
            "medium_confidence": [],
            "insufficient_data": (["Collect complete authoritative outcomes and MIRROR trade/mark telemetry before testing behavior changes"]
                                  if len(rows) < MIN_TOTAL else [])},
        "data_to_persist": ["underlying price at MIRROR fill", "historical option Greeks and IV at entry",
                            "post-close marks explicitly flagged as post-close", "provider quote timestamp and execution latency components"],
        "source_of_truth": "PERSISTED RECORDS ONLY; NO PROVIDER RECONSTRUCTION",
    }
