"""Pure, QQQ-only winner/loser DNA and exit-forensics research."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median, pstdev
from zoneinfo import ZoneInfo

from contextual_research import simulate_shadow_exits
from strategic_spy_qqq_audit import number, performance, timestamp

EASTERN = ZoneInfo("America/New_York")
DEVELOPMENT_START = "2026-08-10"
DEVELOPMENT_END = "2026-08-13"
FORWARD_START = "2026-08-17"
MFE_THRESHOLDS = (5, 10, 15, 20, 25, 30, 40, 50)


def governance(n):
    return "INSUFFICIENT DATA" if n < 10 else "DESCRIPTIVE ONLY" if n < 30 else "UNSTABLE" if n < 50 else "CHRONOLOGICAL VALIDATION ELIGIBLE"


def et_day(value):
    parsed = timestamp(value)
    return parsed.astimezone(EASTERN).date().isoformat() if parsed else None


def time_bucket(value):
    parsed = timestamp(value)
    if not parsed:
        return "UNAVAILABLE"
    minute = parsed.astimezone(EASTERN).hour * 60 + parsed.astimezone(EASTERN).minute
    boundaries = ((570,600,"09:30-10:00"),(600,660,"10:00-11:00"),(660,720,"11:00-12:00"),
                  (720,780,"12:00-13:00"),(780,840,"13:00-14:00"),(840,900,"14:00-15:00"),(900,960,"15:00-16:00"))
    return next((label for start, end, label in boundaries if start <= minute < end), "OUTSIDE SESSION")


def compact_time_bucket(value):
    bucket = time_bucket(value)
    if bucket == "09:30-10:00": return "OPENING"
    if bucket in {"10:00-11:00", "11:00-12:00", "12:00-13:00"}: return "MIDDAY"
    if bucket in {"13:00-14:00", "14:00-15:00"}: return "AFTERNOON"
    if bucket == "15:00-16:00": return "POWER HOUR"
    return bucket


def spread_bucket(value):
    value = number(value)
    if value is None: return "UNAVAILABLE"
    if value <= .5: return "<=0.5%"
    if value <= 1: return "0.5-1%"
    if value <= 1.5: return "1-1.5%"
    if value <= 2: return "1.5-2%"
    if value <= 3: return "2-3%"
    return ">3%"


def signal_age_bucket(value):
    value = number(value)
    if value is None: return "UNAVAILABLE"
    if value <= 30: return "<=30"
    if value <= 60: return "31-60"
    if value <= 120: return "61-120"
    if value <= 180: return "121-180"
    if value <= 300: return "181-300"
    return ">300"


def alignment_bucket(value):
    value = number(value)
    if value is None: return "UNAVAILABLE"
    if value <= 25: return "0-25%"
    if value <= 50: return "25-50%"
    if value < 75: return "50-75%"
    if value < 100: return "75-100%"
    return "100%"


def scope_for(row):
    day = row.get("session") or et_day(row.get("opened_at"))
    if day and DEVELOPMENT_START <= day <= DEVELOPMENT_END: return "DEVELOPMENT"
    if day and day >= FORWARD_START: return "FORWARD TEST"
    return "OUTSIDE PREDECLARED WINDOWS"


def reentry_features(rows):
    ordered = sorted(rows, key=lambda row: timestamp(row.get("opened_at")) or datetime.max.replace(tzinfo=timezone.utc))
    previous_by_session = {}
    result = {}
    for index, row in enumerate(ordered):
        day = row.get("session") or et_day(row.get("opened_at")) or "UNAVAILABLE"
        previous = previous_by_session.get(day)
        prior = sum(1 for item in ordered[:index] if (item.get("session") or et_day(item.get("opened_at"))) == day)
        sequence = "1st" if prior == 0 else "2nd" if prior == 1 else "3rd" if prior == 2 else "4th" if prior == 3 else "10th+" if prior >= 9 else "5th+"
        minutes = None
        if previous and timestamp(previous.get("closed_at")) and timestamp(row.get("opened_at")):
            minutes = (timestamp(row["opened_at"]) - timestamp(previous["closed_at"])).total_seconds() / 60
        if not previous: classification = "FIRST ENTRY"
        elif minutes is not None and minutes <= 5: classification = "IMMEDIATE RE-ENTRY"
        elif str(previous.get("direction")) == str(row.get("direction")): classification = "SAME-DIRECTION RE-ENTRY"
        else: classification = "OPPOSITE-DIRECTION REVERSAL"
        result[str(row.get("trade_id"))] = {"trade_sequence": sequence, "prior_trades": prior,
            "minutes_since_prior_close": minutes, "reentry_class": classification,
            "repeated_setup": bool(previous and previous.get("setup") == row.get("setup")),
            "prior_stopped": bool(previous and "STOP" in str(previous.get("exit_reason") or "").upper())}
        previous_by_session[day] = row
    return result


def classify_trade(row):
    mfe, mae, realized = number(row.get("mfe")), number(row.get("mae")), number(row.get("return_pct"))
    if mfe is None or mae is None or realized is None: return "INSUFFICIENT_DATA"
    if mfe < 5 and mae <= -10: return "ENTRY_NEVER_WORKED"
    if (mfe >= 10 and realized <= 0) or (mfe >= 20 and realized <= 5) or (mfe >= 30 and realized <= 10):
        return "ENTRY_WORKED_EXIT_WEAK"
    if realized > 0 and mfe > 0 and realized / mfe >= .5: return "CLEAN_WINNER"
    if mfe >= 5 and mae <= -10: return "WHIPSAW"
    return "INSUFFICIENT_DATA"


def _profit_factor(pnls):
    wins, losses = sum(value for value in pnls if value > 0), abs(sum(value for value in pnls if value < 0))
    return wins / losses if losses else None


def metrics(rows):
    eligible = [row for row in rows if number(row.get("pnl")) is not None]
    pnls = [number(row["pnl"]) for row in eligible]
    returns = [number(row.get("return_pct")) for row in eligible if number(row.get("return_pct")) is not None]
    mfe = [number(row.get("mfe")) for row in eligible if number(row.get("mfe")) is not None]
    mae = [number(row.get("mae")) for row in eligible if number(row.get("mae")) is not None]
    winners = [value for value in pnls if value > 0]; losers = [value for value in pnls if value < 0]
    return {"n": len(eligible), "governance": governance(len(eligible)), "wins": len(winners), "losses": len(losers),
        "win_rate": len(winners)/len(eligible)*100 if eligible else None, "total_pnl": sum(pnls) if pnls else None,
        "expectancy": mean(pnls) if pnls else None, "average_return": mean(returns) if returns else None,
        "median_return": median(returns) if returns else None, "profit_factor": _profit_factor(pnls),
        "average_mfe": mean(mfe) if mfe else None, "average_mae": mean(mae) if mae else None,
        "average_winner": mean(winners) if winners else None, "average_loser": mean(losers) if losers else None,
        "mfe_captured": mean([number(row["return_pct"])/number(row["mfe"])*100 for row in eligible
            if number(row.get("return_pct")) is not None and number(row.get("mfe")) is not None and number(row.get("mfe")) > 0]) if any(
            number(row.get("return_pct")) is not None and number(row.get("mfe")) is not None and number(row.get("mfe")) > 0 for row in eligible) else None}


def grouped(rows, key):
    groups = defaultdict(list)
    for row in rows: groups[str(row.get(key) if row.get(key) is not None else "UNAVAILABLE")].append(row)
    return [{"group": name, **metrics(items)} for name, items in sorted(groups.items())]


def _daily(rows):
    groups = defaultdict(list)
    for row in rows: groups[row.get("session") or et_day(row.get("opened_at")) or "UNAVAILABLE"].append(row)
    result = []
    for day, items in sorted(groups.items()):
        values = [number(row.get("pnl")) for row in items if number(row.get("pnl")) is not None]
        result.append({"session":day,"trades":len(values),"pnl":sum(values) if values else None,
            "wins":sum(v>0 for v in values),"losses":sum(v<0 for v in values),
            "win_rate":sum(v>0 for v in values)/len(values)*100 if values else None,
            "average_trade":mean(values) if values else None,"best_trade":max(values) if values else None,"worst_trade":min(values) if values else None})
    return result


def _quality(all_rows, eligible, marks, journals):
    ids = [str(row.get("trade_id")) for row in all_rows if row.get("trade_id")]
    duplicate_n = len(ids) - len(set(ids)); trade_ids = set(ids)
    missing = lambda key: sum(row.get(key) is None for row in all_rows)
    context_fields = ("setup", "regime", "time_bucket", "vwap", "ema_alignment", "orb_state", "mtf_alignment")
    issues = duplicate_n + missing("entry_fill") + missing("opened_at") + missing("closed_at") + missing("pnl")
    if len(eligible) < 5: grade = "INSUFFICIENT"
    elif issues > len(all_rows) * .2: grade = "POOR"
    elif issues or any(missing(field) for field in context_fields): grade = "USABLE WITH LIMITATIONS"
    else: grade = "GOOD"
    return {"grade":grade,"total_records":len(all_rows),"eligible_closed":len(eligible),
        "open_or_stale":sum(str(r.get("status")).upper()=="OPEN" for r in all_rows),"missing_entries":missing("entry_fill"),
        "missing_exits":missing("closed_at"),"missing_realized_pnl":missing("pnl"),"missing_return":missing("return_pct"),
        "missing_spread":missing("spread_percent"),"missing_mfe":missing("mfe"),"missing_mae":missing("mae"),
        "missing_signal_age":missing("signal_age_seconds"),"trades_with_marks":len({str(m.get('trade_id')) for m in marks}),
        "missing_marks":max(0,len(eligible)-len({str(m.get('trade_id')) for m in marks})),
        "duplicate_identities":duplicate_n,"orphaned_journal_records":sum(str(j.get("trade_id")) not in trade_ids for j in journals),
        "missing_setup_context":{field:missing(field) for field in context_fields}}


def _mfe_paths(rows):
    output = []
    for threshold in MFE_THRESHOLDS:
        reached = [r for r in rows if number(r.get("mfe")) is not None and number(r.get("mfe")) >= threshold]
        output.append({"threshold":threshold,"n":len(reached),"closed_profitable":sum(number(r.get("return_pct")) is not None and number(r["return_pct"])>.5 for r in reached),
            "closed_breakeven_ish":sum(number(r.get("return_pct")) is not None and abs(number(r["return_pct"]))<=.5 for r in reached),
            "closed_negative":sum(number(r.get("return_pct")) is not None and number(r["return_pct"])<-.5 for r in reached),
            "stopped_out":sum("STOP" in str(r.get("exit_reason") or "").upper() for r in reached)})
    return output


def _shadow(rows, marks):
    by_trade = defaultdict(list)
    for mark in marks: by_trade[str(mark.get("trade_id"))].append(mark)
    policy_rows = defaultdict(list)
    for row in rows:
        path = by_trade.get(str(row.get("trade_id")), [])
        if not path: continue
        for policy, trigger in simulate_shadow_exits(path).items():
            if trigger and number(trigger.get("shadow_return")) is not None:
                shadow_return = number(trigger["shadow_return"])
                fraction = number(trigger.get("fraction"))
                if fraction is not None and number(row.get("return_pct")) is not None:
                    shadow_return = fraction * shadow_return + (1 - fraction) * number(row["return_pct"])
                debit = number(row.get("total_debit"))
                policy_rows[policy].append({**row,"pnl":shadow_return/100*debit if debit is not None else shadow_return,
                    "return_pct":shadow_return,"baseline_return":number(row.get("return_pct"))})
    return [{"policy":policy,"eligible_n":len(items),"changed_vs_baseline":sum(number(item.get("return_pct")) != item.get("baseline_return") for item in items),
             **metrics(items)} for policy,items in sorted(policy_rows.items())]


def _best_and_worst(groups):
    usable = [row for row in groups if row.get("n") and row.get("expectancy") is not None]
    return {"best":max(usable,key=lambda row:row["expectancy"],default=None),
            "worst":min(usable,key=lambda row:row["expectancy"],default=None)}


def _conclusions(dimensions, questions, shadow):
    direction=_best_and_worst(dimensions["direction"]);tod=_best_and_worst(dimensions["time_of_day"])
    dte=_best_and_worst(dimensions["dte"]);spread=_best_and_worst(dimensions["spread"]);setup=_best_and_worst(dimensions["setup"])
    regime=_best_and_worst(dimensions["regime"]);alignment=_best_and_worst(dimensions["multi_timeframe"]);sequence=_best_and_worst(dimensions["trade_sequence"])
    policies=[row for row in shadow if row.get("n") and row.get("expectancy") is not None]
    best_policy=max(policies,key=lambda row:row["expectancy"],default=None)
    leak=questions["biggest_observed_leak"]
    if leak=="EXIT MANAGEMENT": name,rule="QQQ breakeven-promotion shadow lane","After a persisted +10% mark, record the first subsequent mark at or below breakeven as the shadow exit."
    elif leak=="ENTRY SELECTION": name,rule="QQQ first-two-trades-only shadow lane","Shadow-accept only the first two chronological QQQ entries per Eastern session."
    else: name,rule="QQQ evidence-completeness forward observation","Record every unchanged QQQ trade and its ordered marks; apply no entry or exit exclusion."
    return {"call_vs_put":direction,"time_of_day":tod,"dte":dte,"spread":spread,"setup":setup,"regime":regime,
        "multi_timeframe":alignment,"trade_sequence":sequence,"best_shadow_policy":best_policy,
        "strong_qqq_trade_profile":{"status":"DESCRIPTIVE ONLY","direction":direction["best"],"time_window":tod["best"],
            "dte":dte["best"],"spread":spread["best"],"setup":setup["best"],"regime":regime["best"],
            "multi_timeframe":alignment["best"],"trade_sequence":sequence["best"]},
        "one_next_experiment":{"name":name,"hypothesis":f"The observed {leak.lower()} signal persists prospectively.","exact_rule":rule,
            "baseline":"unchanged current QQQ strategy","experimental_lane":"research-only shadow lane","minimum_n":50,"minimum_sessions":20,
            "primary_success_metric":"forward expectancy improvement without lower profit factor","secondary_success_metric":"improved profitable-session percentage",
            "failure_criterion":"non-positive forward expectancy improvement after minimum sample"}}


def analyze_qqq_forensics(trades, *, signals=(), contexts=(), marks=(), journals=(), metadata=None):
    """Analyze exact QQQ intraday records without I/O or mutation."""
    source = [dict(row) for row in trades]
    signal_by_id = {str(row.get("opportunity_id")): row for row in signals}
    context_by_id = {str(row.get("opportunity_id")): row for row in contexts}
    qqq = []
    excluded = []
    for raw in source:
        if str(raw.get("symbol") or "").upper() != "QQQ":
            excluded.append({"trade_id":raw.get("trade_id"),"reason":"NON_QQQ"}); continue
        row = dict(raw); signal = signal_by_id.get(str(row.get("opportunity_id")), {}); context = context_by_id.get(str(row.get("opportunity_id")), {})
        technical = context.get("technical") or {}; mtf = context.get("multi_timeframe") or {}; lifecycle = context.get("lifecycle") or {}; option = context.get("option_execution") or {}
        row.update({"setup":row.get("setup") or signal.get("setup"),"regime":row.get("regime") or signal.get("regime") or (context.get("market") or {}).get("market_regime"),
            "time_bucket":time_bucket(row.get("opened_at")),"compact_time_bucket":compact_time_bucket(row.get("opened_at")),
            "spread_bucket":spread_bucket(row.get("spread_percent")),"signal_age_bucket":signal_age_bucket(row.get("signal_age_seconds")),
            "vwap":technical.get("price_vs_vwap"),"ema_alignment":technical.get("ema_aligned"),"orb_state":technical.get("opening_range_state"),
            "mtf_alignment":technical.get("multi_timeframe_alignment") or mtf.get("multi_timeframe_alignment_pct"),
            "alignment_bucket":alignment_bucket(technical.get("multi_timeframe_alignment") or mtf.get("multi_timeframe_alignment_pct")),
            "relative_volume":technical.get("relative_volume"),"first_seen_to_entry":lifecycle.get("total_candidate_to_execution_seconds"),
            "contract_selection_latency":option.get("contract_selection_latency_seconds"),"session":row.get("session") or et_day(row.get("opened_at"))})
        qqq.append(row)
    sequence = reentry_features(qqq)
    for row in qqq: row.update(sequence.get(str(row.get("trade_id")), {})); row["failure_classification"] = classify_trade(row); row["scope"] = scope_for(row)
    eligible = [row for row in qqq if row.get("closed_at") and number(row.get("pnl")) is not None]
    for row in qqq:
        if row not in eligible: excluded.append({"trade_id":row.get("trade_id"),"reason":"OPEN_OR_MISSING_REALIZED_PNL"})
    daily = _daily(eligible); daily_pnl = [row["pnl"] for row in daily if row["pnl"] is not None]
    baseline = {**performance(eligible),"daily":daily,"daily_pnl_standard_deviation":pstdev(daily_pnl) if len(daily_pnl)>1 else None}
    dimensions = {"variant":grouped(eligible,"variant"),"direction":grouped(eligible,"direction"),"time_of_day":grouped(eligible,"time_bucket"),"compact_time":grouped(eligible,"compact_time_bucket"),
        "trade_sequence":grouped(eligible,"trade_sequence"),"reentry":grouped(eligible,"reentry_class"),"dte":grouped(eligible,"dte"),
        "spread":grouped(eligible,"spread_bucket"),"signal_age":grouped(eligible,"signal_age_bucket"),"setup":grouped(eligible,"setup"),
        "regime":grouped(eligible,"regime"),"vwap":grouped(eligible,"vwap"),"ema":grouped(eligible,"ema_alignment"),"orb":grouped(eligible,"orb_state"),
        "multi_timeframe":grouped(eligible,"alignment_bucket"),"failure_classification":grouped(eligible,"failure_classification")}
    interactions = {name:grouped([{**r,"interaction":f'{r.get(a) or "UNAVAILABLE"} x {r.get(b) or "UNAVAILABLE"}'} for r in eligible],"interaction") for name,a,b in (
        ("direction_x_time","direction","time_bucket"),("dte_x_time","dte","time_bucket"),("spread_x_dte","spread_bucket","dte"),
        ("vwap_x_ema","vwap","ema_alignment"),("orb_x_vwap","orb_state","vwap"),("regime_x_direction","regime","direction"),
        ("alignment_x_direction","alignment_bucket","direction"),("sequence_x_time","trade_sequence","time_bucket"))}
    scopes = {scope:{"baseline":metrics([r for r in eligible if r["scope"]==scope]),
        "shadow_exits":_shadow([r for r in eligible if r["scope"]==scope], marks)} for scope in ("DEVELOPMENT","FORWARD TEST")}
    shadow_all=_shadow(eligible,marks);questions=_answers(eligible,dimensions,scopes,marks)
    conclusions=_conclusions(dimensions,questions,shadow_all)
    return {"metadata":{**(metadata or {}),"research_only":True,"hindsight_tags":{"entry_features":"PRE-ENTRY SAFE","marks":"DURING-TRADE SAFE","outcomes":"POST-TRADE DESCRIPTIVE"}},
        "inventory":{"qqq_records":len(qqq),"eligible_closed":len(eligible),"open":sum(str(r.get("status")).upper()=="OPEN" for r in qqq),
            "excluded":excluded,"sessions":sorted({r["session"] for r in qqq if r.get("session")}),
            "first_eligible":min((r.get("opened_at") for r in eligible if r.get("opened_at")),default=None),
            "latest_eligible":max((r.get("closed_at") for r in eligible if r.get("closed_at")),default=None)},
        "data_quality":_quality(qqq,eligible,marks,journals),"baseline":baseline,"dimensions":dimensions,
        "winner_dna":dimensions,"loser_dna":dimensions,"interactions":interactions,
        "mfe_paths":_mfe_paths(eligible),"failure_classification":dimensions["failure_classification"],
        "shadow_exits":{"all":shadow_all,"coverage":"AVAILABLE" if marks else "UNAVAILABLE: NO EXACT QQQ ORDERED MARKS"},
        "development_vs_forward":scopes,"per_trade":[{key:row.get(key) for key in ("trade_id","opportunity_id","session","direction","pnl","return_pct","mfe","mae","setup","regime","time_bucket","trade_sequence","reentry_class","failure_classification","scope")} for row in eligible],
        "limitations":["No provider data or future bars are used.","Path-dependent exit policies require exact ordered QQQ marks.","Unavailable fields remain unavailable."],
        "primary_questions":questions,"conclusions":conclusions,"strong_qqq_trade_profile":conclusions["strong_qqq_trade_profile"],
        "biggest_observed_leak":questions["biggest_observed_leak"],"one_next_experiment":conclusions["one_next_experiment"]}


def _answers(rows, dimensions, scopes, marks):
    classification = {row["group"]:row for row in dimensions["failure_classification"]}
    exit_n = classification.get("ENTRY_WORKED_EXIT_WEAK",{}).get("n",0); entry_n = classification.get("ENTRY_NEVER_WORKED",{}).get("n",0)
    leak = "INSUFFICIENT DATA"
    if len(rows) >= 10: leak = "EXIT MANAGEMENT" if exit_n > entry_n else "ENTRY SELECTION" if entry_n > exit_n else "INSUFFICIENT DATA"
    return {"positive_expectancy_distribution":"POST-TRADE DESCRIPTIVE","entry_failure_count":entry_n,"exit_failure_count":exit_n,
        "biggest_observed_leak":leak,"forward_evidence":scopes["FORWARD TEST"]["baseline"],
        "shadow_exit_evidence":"AVAILABLE" if marks else "INSUFFICIENT DATA"}
