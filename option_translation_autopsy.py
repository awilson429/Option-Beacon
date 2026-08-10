"""Read-only attribution of authoritative signals to persisted MIRROR outcomes."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")
SNAPSHOT_MINUTES = (1, 2, 3, 5, 10, 15, 30)
SNAPSHOT_TOLERANCE_SECONDS = 45
MIN_TOTAL = 20
MIN_DEVELOPMENT = 10
MIN_VALIDATION = 6
OUTCOMES = (
    "AUTH WIN / MIRROR WIN", "AUTH WIN / MIRROR LOSS",
    "AUTH LOSS / MIRROR WIN", "AUTH LOSS / MIRROR LOSS",
    "AUTH OPEN / MIRROR OPEN", "AUTH CLOSED / MIRROR DATA INCOMPLETE",
)


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _dt(value):
    if not value:
        return None
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def _avg(values):
    values = [value for value in values if value is not None]
    return mean(values) if values else None


def _profit_factor(rows):
    pnl = [row["mirror_pnl"] for row in rows if row.get("mirror_pnl") is not None]
    positive, negative = sum(value for value in pnl if value > 0), abs(sum(value for value in pnl if value < 0))
    return positive / negative if negative else math.inf if positive else None


def chronological_split(rows):
    """Oldest 70% development, newest 30% validation; never shuffled."""
    ordered = sorted(rows, key=lambda row: _dt(row.get("opened_at") or row.get("entry_at")) or datetime.min.replace(tzinfo=timezone.utc))
    if len(ordered) < 2:
        return ordered, []
    validation_n = max(1, math.ceil(len(ordered) * .30))
    return ordered[:-validation_n], ordered[-validation_n:]


def underlying_magnitude_bucket(value):
    value = _number(value)
    if value is None: return "DATA UNAVAILABLE"
    value = abs(value)
    if value <= .10: return "0% to 0.10%"
    if value <= .25: return "0.10% to 0.25%"
    if value <= .50: return "0.25% to 0.50%"
    if value <= 1.00: return "0.50% to 1.00%"
    return ">1.00%"


def spread_bucket(value):
    value = _number(value)
    if value is None: return "DATA UNAVAILABLE"
    if value <= 2: return "<=2%"
    if value <= 5: return "2-5%"
    if value <= 10: return "5-10%"
    if value <= 20: return "10-20%"
    return ">20%"


def dte_bucket(value):
    value = _number(value)
    if value is None: return "DATA UNAVAILABLE"
    if value <= 0: return "0DTE"
    if value == 1: return "1DTE"
    if value <= 4: return "2-4 DTE"
    if value <= 9: return "5-9 DTE"
    return "10+ DTE"


def moneyness_bucket(option_type, strike, underlying):
    strike, underlying = _number(strike), _number(underlying)
    if strike is None or not underlying: return "DATA UNAVAILABLE"
    signed = (underlying - strike) if str(option_type).upper() == "CALL" else (strike - underlying)
    distance = signed / underlying * 100
    return "ATM / near ATM" if abs(distance) <= .5 else "ITM" if distance > 0 else "OTM"


def _marks_path(mirror, marks):
    valid = sorted((mark for mark in marks if _number(mark.get("return_pct")) is not None), key=lambda row: _dt(row.get("observed_at")))
    returns = [_number(mark["return_pct"]) for mark in valid]
    final = _number(mirror.get("realized_return_percent"))
    peak = max(returns) if returns else _number(mirror.get("mfe_pct") or mirror.get("peak_return_pct"))
    mae = min(returns) if returns else _number(mirror.get("mae_pct"))
    peak_mark = next((mark for mark in valid if _number(mark["return_pct"]) == peak), None)
    opened, exited = _dt(mirror.get("opened_at")), _dt(mirror.get("exit_quote_at"))
    peak_at = _dt((peak_mark or {}).get("observed_at"))
    giveback = max(0, peak - final) if peak is not None and final is not None else None
    return {"marks": valid, "mark_count": len(valid), "mfe": peak, "mae": mae,
            "peak_return": peak, "peak_pnl": _number((peak_mark or {}).get("unrealized_pnl")) or _number(mirror.get("peak_unrealized_pnl")),
            "giveback": giveback, "ever_profitable": peak is not None and peak > 0,
            "profitable_then_loser": bool(peak is not None and peak > 0 and final is not None and final < 0),
            "time_to_peak_minutes": (peak_at - opened).total_seconds() / 60 if peak_at and opened else None,
            "peak_to_exit_minutes": (exited - peak_at).total_seconds() / 60 if exited and peak_at else None}


def timing_snapshots(opened_at, marks, tolerance_seconds=SNAPSHOT_TOLERANCE_SECONDS):
    """Choose a persisted nearest mark only when inside tolerance; never interpolate."""
    opened = _dt(opened_at)
    result = {}
    for minute in SNAPSHOT_MINUTES:
        target = opened + timedelta(minutes=minute) if opened else None
        candidates = [(abs((_dt(mark.get("observed_at")) - target).total_seconds()), mark)
                      for mark in marks if target and _dt(mark.get("observed_at")) and _number(mark.get("return_pct")) is not None]
        nearest = min(candidates, key=lambda item: (item[0], str(item[1].get("mark_id")))) if candidates else None
        result[f"return_{minute}m"] = _number(nearest[1].get("return_pct")) if nearest and nearest[0] <= tolerance_seconds else None
    return result


def _outcome(auth_return, mirror_return, auth_closed, mirror_status):
    if auth_closed and mirror_return is None: return "AUTH CLOSED / MIRROR DATA INCOMPLETE"
    if not auth_closed and str(mirror_status).upper() == "OPEN": return "AUTH OPEN / MIRROR OPEN"
    if auth_return is None or auth_return == 0 or mirror_return is None or mirror_return == 0: return "AUTH CLOSED / MIRROR DATA INCOMPLETE"
    return f'AUTH {"WIN" if auth_return > 0 else "LOSS"} / MIRROR {"WIN" if mirror_return > 0 else "LOSS"}'


def _failure(row):
    if row["outcome"].startswith("AUTH LOSS"): return ("WRONG UNDERLYING DIRECTION", "SUPPORTED")
    if row["telemetry_coverage"] == "DATA UNAVAILABLE": return ("MISSING / UNAVAILABLE DATA", "DATA UNAVAILABLE")
    if row["profitable_then_loser"]: return ("PROFITABLE OPTION REVERSED INTO LOSER", "SUPPORTED")
    if row.get("giveback") is not None and row["giveback"] > 10: return ("EXIT TIMING / EXCESSIVE GIVEBACK", "SUPPORTED")
    if row.get("spread_percent") is not None and row["spread_percent"] > 10: return ("EXCESSIVE SPREAD / FILL FRICTION", "LIKELY")
    if row.get("dte") == 0 and (row.get("hold_minutes") or 0) >= 30: return ("THETA / DTE EXPOSURE", "LIKELY")
    if row.get("moneyness") == "OTM": return ("CONTRACT SELECTION", "LIKELY")
    if row.get("auth_return") is not None and 0 < row["auth_return"] <= .10: return ("CORRECT DIRECTION / INSUFFICIENT MAGNITUDE", "LIKELY")
    if row.get("mae") is not None and row["mae"] < 0 and row.get("mfe") is not None and row["mfe"] > 0: return ("ADVERSE EXCURSION / ENTRY TIMING", "LIKELY")
    return ("TRANSLATION CAUSE", "INCONCLUSIVE")


def _summary(rows):
    decided = [row for row in rows if row.get("mirror_return") is not None]
    pnl = [row["mirror_pnl"] for row in decided if row.get("mirror_pnl") is not None]
    return {"n": len(rows), "win_rate": sum(row["mirror_return"] > 0 for row in decided) / len(decided) * 100 if decided else None,
            "auth_average_return": _avg(row.get("auth_return") for row in rows),
            "mirror_average_return": _avg(row.get("mirror_return") for row in rows), "mirror_net_pnl": sum(pnl),
            "average_debit": _avg(row.get("debit") for row in rows), "average_spread": _avg(row.get("spread_percent") for row in rows),
            "average_dte": _avg(row.get("dte") for row in rows), "average_hold": _avg(row.get("hold_minutes") for row in rows),
            "average_mfe": _avg(row.get("mfe") for row in rows), "average_mae": _avg(row.get("mae") for row in rows),
            "average_giveback": _avg(row.get("giveback") for row in rows), "profit_factor": _profit_factor(rows)}


def _groups(rows, key):
    grouped = defaultdict(list)
    for row in rows: grouped[str(row.get(key) or "DATA UNAVAILABLE")].append(row)
    return [{"group": label, **_summary(items), **_capital(items)} for label, items in sorted(grouped.items())]


def _peak_capital(rows):
    points = []
    for row in rows:
        debit, opened, closed = _number(row.get("debit")), _dt(row.get("opened_at")), _dt(row.get("closed_at"))
        if debit is None or opened is None: continue
        points.append((opened, 1, debit))
        if closed: points.append((closed, -1, debit))
    deployed = peak = 0
    for _, kind, debit in sorted(points, key=lambda item: (item[0], item[1])):
        deployed += kind * debit; peak = max(peak, deployed)
    return peak


def _capital(rows):
    debits = [row["debit"] for row in rows if row.get("debit") is not None]
    pnl = sum(row["mirror_pnl"] for row in rows if row.get("mirror_pnl") is not None)
    peak = _peak_capital(rows)
    return {"cumulative_gross_debit": sum(debits), "peak_capital": peak, "net_pnl": pnl,
            "return_on_peak_capital": pnl / peak * 100 if peak else None,
            "return_on_cumulative_debit": pnl / sum(debits) * 100 if debits and sum(debits) else None,
            "average_debit": _avg(debits), "median_debit": median(debits) if debits else None,
            "pnl_per_100_debit": pnl / sum(debits) * 100 if debits and sum(debits) else None}


def _entry_timing(rows):
    losers = [row for row in rows if row.get("mirror_return") is not None and row["mirror_return"] < 0]
    def profitable_within(row, minutes):
        opened = _dt(row.get("opened_at"))
        return any(_number(mark.get("return_pct")) > 0 and opened and
                   0 <= (_dt(mark.get("observed_at")) - opened).total_seconds() <= minutes * 60
                   for mark in row.get("marks", []) if _dt(mark.get("observed_at")))
    return {"final_losers": len(losers),
            "profitable_within_5_pct": sum(profitable_within(row, 5) for row in losers) / len(losers) * 100 if losers else None,
            "profitable_within_10_pct": sum(profitable_within(row, 10) for row in losers) / len(losers) * 100 if losers else None,
            "profitable_within_15_pct": sum(profitable_within(row, 15) for row in losers) / len(losers) * 100 if losers else None,
            "never_profitable_pct": sum(not row.get("ever_profitable") for row in losers) / len(losers) * 100 if losers else None,
            "adverse_before_profitable_pct": sum(row.get("mae") is not None and row["mae"] <= -5 and row.get("ever_profitable") for row in losers) / len(losers) * 100 if losers else None}


def _max_drawdown(rows):
    cumulative = peak = drawdown = 0.0
    for row in sorted(rows, key=lambda item: _dt(item.get("closed_at")) or datetime.max.replace(tzinfo=timezone.utc)):
        cumulative += _number(row.get("mirror_pnl")) or 0
        peak = max(peak, cumulative); drawdown = max(drawdown, peak - cumulative)
    return drawdown


def simulate_exit(row, rule):
    marks = row.get("marks") or []
    entry = _number(row.get("entry_fill")); quantity = int(row.get("quantity") or 1); multiplier = int(row.get("multiplier") or 100)
    if not marks or not entry: return None
    peak = -math.inf
    for mark in marks:
        value, elapsed = _number(mark.get("return_pct")), _number(mark.get("time_since_entry_seconds"))
        if value is None: continue
        peak = max(peak, value)
        hit = ((rule.startswith("TP") and value >= float(rule[2:])) or
               (rule == "TRAIL10_AFTER15" and peak >= 15 and value <= peak - 10) or
               (rule == "TRAIL10_AFTER20" and peak >= 20 and value <= peak - 10) or
               (rule == "BREAKEVEN_AFTER10" and peak >= 10 and value <= 0) or
               (rule == "MAX30" and elapsed is not None and elapsed >= 1800) or
               (rule == "MAX45" and elapsed is not None and elapsed >= 2700))
        if hit:
            mark_price = _number(mark.get("conservative_mark"))
            return {"return": value, "pnl": (mark_price - entry) * quantity * multiplier if mark_price is not None else entry * quantity * multiplier * value / 100,
                    "observed_at": mark.get("observed_at")}
    return {"return": row.get("mirror_return"), "pnl": row.get("mirror_pnl"), "observed_at": row.get("closed_at")}


def _validation_label(all_rows, development, validation, control_validation=None):
    if len(all_rows) < MIN_TOTAL or len(development) < MIN_DEVELOPMENT or len(validation) < MIN_VALIDATION: return "INSUFFICIENT DATA"
    current, control = _summary(validation), _summary(control_validation or [])
    improves = sum((current.get(key) or -math.inf) > (control.get(key) or -math.inf) for key in ("mirror_net_pnl", "mirror_average_return", "profit_factor"))
    return "PROMISING" if improves >= 2 else "NO IMPROVEMENT" if improves == 0 else "UNSTABLE"


def _what_ifs(rows):
    candidates = (
        ("EXCLUDE SPREAD >20%", lambda row: row.get("spread_bucket") != ">20%"),
        ("EXCLUDE UNDERLYING MOVE <=0.10%", lambda row: row.get("magnitude_bucket") != "0% to 0.10%"),
        ("EXCLUDE 0DTE", lambda row: row.get("dte_bucket") != "0DTE"),
        ("REQUIRE CONFIDENCE >=70", lambda row: row.get("confidence") is not None and row["confidence"] >= 70),
    )
    results = []
    for name, predicate in candidates:
        retained = [row for row in rows if predicate(row)]
        dev, validation = chronological_split(retained); _, control_validation = chronological_split(rows)
        results.append({"variant": name, "retained": len(retained), "participation": len(retained) / len(rows) * 100 if rows else None,
                        **_summary(retained), **_capital(retained), "avoided_losers": sum(row.get("mirror_return", 0) < 0 for row in rows if row not in retained),
                        "excluded_winners": sum(row.get("mirror_return", 0) > 0 for row in rows if row not in retained),
                        "development_n": len(dev), "validation_n": len(validation),
                        "validation_label": _validation_label(retained, dev, validation, control_validation)})
    return results


def _exit_what_ifs(rows):
    eligible = [row for row in rows if row.get("marks") and row.get("entry_fill")]
    control_dev, control_validation = chronological_split(eligible)
    control = {"variant": "CONTROL", "eligible": len(eligible), "coverage": len(eligible) / len(rows) * 100 if rows else None,
               **_summary(eligible), **_capital(eligible), "max_drawdown": _max_drawdown(eligible),
               "development_n": len(control_dev), "validation_n": len(control_validation),
               "validation_label": "CONTROL", "difference_vs_control": 0}
    results = [control]
    for rule in ("TP10", "TP15", "TP20", "TP25", "TRAIL10_AFTER15", "TRAIL10_AFTER20", "BREAKEVEN_AFTER10", "MAX30", "MAX45"):
        simulated = [{**row, "mirror_return": result["return"], "mirror_pnl": result["pnl"]}
                     for row in eligible if (result := simulate_exit(row, rule)) is not None]
        dev, validation = chronological_split(simulated)
        result = {"variant": rule, "eligible": len(simulated), "coverage": len(simulated) / len(rows) * 100 if rows else None,
                        **_summary(simulated), **_capital(simulated), "development_n": len(dev), "validation_n": len(validation),
                        "max_drawdown": _max_drawdown(simulated),
                        "validation_label": _validation_label(simulated, dev, validation, control_validation)}
        result["difference_vs_control"] = result["mirror_net_pnl"] - control["mirror_net_pnl"]
        results.append(result)
    return results


def analyze_option_translation(snapshot_rows, outcome_rows, mirror_rows, mirror_marks):
    """Build a deterministic autopsy from persisted rows and immutable IDs only."""
    snapshots = {str((row.get("snapshot") or row).get("opportunity_id")): row.get("snapshot") or row for row in snapshot_rows}
    outcomes = {str((row.get("outcome") or row).get("opportunity_id")): row.get("outcome") or row for row in outcome_rows}
    marks_by_trade = defaultdict(list)
    for mark in mirror_marks: marks_by_trade[str(mark.get("mirror_trade_id"))].append(mark)
    rows, exclusions = [], Counter()
    for mirror in sorted(mirror_rows, key=lambda row: str(row.get("entry_event_at") or row.get("opened_at") or "")):
        identity = str(mirror.get("opportunity_id") or "")
        snapshot, outcome = snapshots.get(identity), outcomes.get(identity)
        if not identity or (snapshot is None and outcome is None): exclusions["missing_exact_authoritative_record"] += 1; continue
        snapshot = snapshot or {}
        if outcome is None: outcome = {}
        features, scoring = snapshot.get("features") or {}, snapshot.get("scoring") or {}
        marks = marks_by_trade.get(str(mirror.get("mirror_trade_id") or ""), [])
        path = _marks_path(mirror, marks)
        auth_return = _number(outcome.get("realized_return")); mirror_return = _number(mirror.get("realized_return_percent"))
        entry_mid, entry_fill = _number(mirror.get("entry_mid")), _number(mirror.get("entry_fill"))
        exit_mid, exit_fill = _number(mirror.get("exit_mid")), _number(mirror.get("exit_fill"))
        quantity, multiplier = int(mirror.get("quantity") or 1), int(mirror.get("contract_multiplier") or 100)
        entry_drag = (entry_fill - entry_mid) * quantity * multiplier if entry_fill is not None and entry_mid is not None else None
        exit_drag = (exit_mid - exit_fill) * quantity * multiplier if exit_fill is not None and exit_mid is not None else None
        underlying = _number(outcome.get("entry_price")) or _number(mirror.get("underlying_entry_price"))
        row = {"opportunity_id": identity, "mirror_trade_id": mirror.get("mirror_trade_id"), "symbol": snapshot.get("symbol") or mirror.get("symbol"),
               "direction": snapshot.get("direction") or mirror.get("direction"), "setup": snapshot.get("setup_type"),
               "entry_at": snapshot.get("entry_timestamp") or mirror.get("entry_event_at"), "opened_at": mirror.get("opened_at"), "closed_at": mirror.get("exit_quote_at"),
               "auth_entry": underlying, "auth_exit": _number(outcome.get("exit_price")), "auth_return": auth_return,
               "auth_closed": bool(outcome.get("exit_timestamp") or auth_return is not None), "mirror_return": mirror_return,
               "mirror_pnl": _number(mirror.get("realized_pnl")), "status": mirror.get("status"), "contract": mirror.get("option_symbol"),
               "expiration": mirror.get("expiration"), "strike": _number(mirror.get("strike")), "option_type": str(mirror.get("option_type") or "").upper() or None,
               "dte": _number(mirror.get("dte")), "entry_bid": _number(mirror.get("entry_bid")), "entry_ask": _number(mirror.get("entry_ask")),
               "entry_mid": entry_mid, "entry_fill": entry_fill, "spread_dollars": _number(mirror.get("spread_dollars")),
               "spread_percent": _number(mirror.get("spread_percent")), "debit": _number(mirror.get("total_debit")),
               "exit_bid": _number(mirror.get("exit_bid")), "exit_ask": _number(mirror.get("exit_ask")), "exit_mid": exit_mid, "exit_fill": exit_fill,
               "entry_fill_drag": entry_drag, "exit_fill_drag": exit_drag, "round_trip_drag": entry_drag + exit_drag if entry_drag is not None and exit_drag is not None else None,
               "drag_percent_debit": (entry_drag + exit_drag) / _number(mirror.get("total_debit")) * 100 if entry_drag is not None and exit_drag is not None and _number(mirror.get("total_debit")) else None,
               "drag_percent_total_loss": (entry_drag + exit_drag) / abs(_number(mirror.get("realized_pnl"))) * 100 if entry_drag is not None and exit_drag is not None and _number(mirror.get("realized_pnl")) is not None and _number(mirror.get("realized_pnl")) < 0 else None,
               "hold_minutes": ((_dt(mirror.get("exit_quote_at")) - _dt(mirror.get("opened_at"))).total_seconds() / 60 if _dt(mirror.get("exit_quote_at")) and _dt(mirror.get("opened_at")) else None),
               "exit_reason": mirror.get("authoritative_exit_reason"), "quantity": quantity, "multiplier": multiplier,
               "confidence": _number(scoring.get("confidence")), "rule_score": _number(scoring.get("quality")),
               "relative_volume": _number(features.get("relative_volume") or features.get("volume_ratio")), "rsi": _number(features.get("rsi")),
               "vwap_distance": _number(features.get("distance_from_vwap")), "ema9_slope": _number(features.get("ema9_slope")), "atr": _number(features.get("atr")),
               "breakout_distance": _number(features.get("breakout_distance")), "trend_alignment": features.get("trend_alignment"),
               "regime": (snapshot.get("market_regime") or {}).get("regime"), "marks": path["marks"], **{key: value for key, value in path.items() if key != "marks"}}
        row["outcome"] = _outcome(auth_return, mirror_return, row["auth_closed"], row["status"])
        row["magnitude_bucket"] = underlying_magnitude_bucket(auth_return); row["spread_bucket"] = spread_bucket(row["spread_percent"])
        row["dte_bucket"] = dte_bucket(row["dte"]); row["moneyness"] = moneyness_bucket(row["option_type"], row["strike"], underlying)
        row["telemetry_coverage"] = "SUPPORTED" if path["mark_count"] else "DATA UNAVAILABLE"
        row.update(timing_snapshots(row["opened_at"], path["marks"]))
        row["failure_mode"], row["causal_confidence"] = _failure(row)
        rows.append(row)
    matrix = []
    for label in OUTCOMES:
        selected = [row for row in rows if row["outcome"] == label]
        matrix.append({"outcome": label, "percent": len(selected) / len(rows) * 100 if rows else 0, **_summary(selected)})
    closed = [row for row in rows if row.get("mirror_return") is not None]
    exit_groups = []
    definitions = (
        ("A. NEVER PROFITABLE", lambda row: not row["ever_profitable"]),
        ("B. PROFITABLE, EXITED PROFITABLE", lambda row: row["ever_profitable"] and row["mirror_return"] > 0 and (row.get("giveback") or 0) <= .25 * max(row["peak_return"], 0)),
        ("C. PROFITABLE, GAVE BACK >25% OF PEAK", lambda row: row["mirror_return"] >= 0 and row.get("giveback") is not None and .25 * max(row["peak_return"], 0) < row["giveback"] <= .50 * max(row["peak_return"], 0)),
        ("D. PROFITABLE, GAVE BACK >50% OF PEAK", lambda row: row["mirror_return"] >= 0 and row.get("giveback") is not None and row["giveback"] > .50 * max(row["peak_return"], 0)),
        ("E. PROFITABLE -> FINAL LOSER", lambda row: row["profitable_then_loser"]),
    )
    for label, predicate in definitions:
        selected = [row for row in closed if predicate(row)]; exit_groups.append({"group": label, "percent": len(selected) / len(closed) * 100 if closed else 0, **_summary(selected)})
    sessions = {str(row.get("entry_at"))[:10] for row in rows if row.get("entry_at")}; symbols = Counter(row.get("symbol") for row in rows if row.get("symbol"))
    auth_winners = [row for row in rows if row.get("auth_return") is not None and row["auth_return"] > 0]
    feature_groups = []
    for feature in ("confidence", "rule_score", "relative_volume", "rsi", "vwap_distance", "ema9_slope", "atr", "breakout_distance", "trend_alignment", "regime", "symbol", "direction", "setup"):
        winners = [row for row in auth_winners if row["outcome"] == "AUTH WIN / MIRROR WIN"]
        losers = [row for row in auth_winners if row["outcome"] == "AUTH WIN / MIRROR LOSS"]
        feature_groups.append({"feature": feature, "mirror_winner_average": _avg(_number(row.get(feature)) for row in winners),
                               "mirror_loser_average": _avg(_number(row.get(feature)) for row in losers),
                               "winner_mode": Counter(str(row.get(feature)) for row in winners).most_common(1)[0][0] if winners else None,
                               "loser_mode": Counter(str(row.get(feature)) for row in losers).most_common(1)[0][0] if losers else None,
                               "winner_n": len(winners), "loser_n": len(losers)})
    return {"rows": rows, "eligible": len(rows), "excluded": dict(exclusions), "outcome_matrix": matrix,
            "auth_win_mirror_loss": [row for row in rows if row["outcome"] == "AUTH WIN / MIRROR LOSS"],
            "exit_efficiency": exit_groups, "magnitude": _groups(auth_winners, "magnitude_bucket"),
            "spread": _groups(closed, "spread_bucket"), "dte": _groups(closed, "dte_bucket"), "moneyness": _groups(closed, "moneyness"),
            "contract": _groups(closed, "option_type"),
            "entry_timing": _entry_timing(closed), "capital": _capital(closed),
            "capital_comparisons": [{"group": label, **_capital(selected)} for label, selected in (
                ("AUTH WIN / MIRROR WIN", [row for row in closed if row["outcome"] == "AUTH WIN / MIRROR WIN"]),
                ("AUTH WIN / MIRROR LOSS", [row for row in closed if row["outcome"] == "AUTH WIN / MIRROR LOSS"]),
                ("NEVER PROFITABLE", [row for row in closed if not row["ever_profitable"]]),
                ("PROFITABLE THEN LOSER", [row for row in closed if row["profitable_then_loser"]]))],
            "feature_attribution": feature_groups, "selective_what_if": _what_ifs(closed),
            "exit_what_if": _exit_what_ifs(closed), "coverage": {"marks": sum(row["mark_count"] > 0 for row in rows), "delta": "NOT PERSISTED", "iv": "NOT PERSISTED"},
            "sample": {"eligible": len(rows), "excluded": sum(exclusions.values()), "sessions": len(sessions), "symbols": len(symbols),
                       "call_count": sum(row["option_type"] == "CALL" for row in rows), "put_count": sum(row["option_type"] == "PUT" for row in rows),
                       "preliminary": len(rows) < MIN_TOTAL, "concentration_warning": bool(symbols and symbols.most_common(1)[0][1] / len(rows) > .30)}}
