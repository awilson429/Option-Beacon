"""Isolated FILTERED paper lane derived from BROAD decisions and MIRROR quotes."""
from __future__ import annotations

import hashlib
import json
import math
import os
import logging
from datetime import datetime, timezone
from statistics import mean

from trade_repository import utc_iso

SPREAD_CAP_PERCENT = 20.0
LANE = "FILTERED"
LOGGER = logging.getLogger(__name__)


def filtered_enabled(environ=None):
    return str((environ or os.environ).get("OPTIONBEACON_FILTERED_ENABLED", "true")).lower() in {"1","true","yes","on"}


def signal_age_bucket(seconds):
    if seconds <= 60: return "LE_60"
    if seconds <= 120: return "61_120"
    if seconds <= 180: return "121_180"
    if seconds <= 300: return "181_300"
    return "GT_300"


def spread_percent(bid, ask):
    try: bid, ask = float(bid), float(ask)
    except (TypeError, ValueError): return None
    mid = (bid + ask) / 2
    return (ask - bid) / mid * 100 if mid > 0 and 0 <= bid <= ask else None


class FilteredExecutionRepository:
    def __init__(self, repository, *, initialize=True):
        self.repository = repository
        if initialize: self.initialize()

    def initialize(self):
        with self.repository.connection() as connection:
            self.repository._execute(connection, """CREATE TABLE IF NOT EXISTS filtered_execution_trades (
                filtered_trade_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL UNIQUE, source_signal_id TEXT NOT NULL,
                authoritative_event_at TEXT, broad_decision TEXT NOT NULL,broad_reason TEXT,execution_eligible INTEGER NOT NULL,
                execution_rejection_reason TEXT,symbol TEXT,direction TEXT,option_symbol TEXT,option_type TEXT,expiration TEXT,
                strike REAL,dte INTEGER,entry_bid REAL,entry_ask REAL,entry_mid REAL,spread_dollars REAL,spread_percent REAL,
                entry_fill REAL,total_debit REAL,quantity INTEGER NOT NULL,contract_multiplier INTEGER NOT NULL,
                signal_age_seconds REAL,signal_age_bucket TEXT,eligible_60s INTEGER,eligible_120s INTEGER,
                eligible_180s INTEGER,eligible_300s INTEGER,opened_at TEXT,closed_at TEXT,status TEXT NOT NULL,exit_reason TEXT,
                exit_fill REAL,realized_pnl REAL,realized_return_percent REAL,mfe_pct REAL,mae_pct REAL,peak_return_pct REAL,
                giveback_pct REAL,shadow_30_return REAL,shadow_30_pnl REAL,shadow_45_return REAL,shadow_45_pnl REAL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""").close()
            self.repository._execute(connection, """CREATE TABLE IF NOT EXISTS filtered_execution_runtime_state (
                scanner_id TEXT PRIMARY KEY,enabled INTEGER NOT NULL,status TEXT NOT NULL,last_cycle_at TEXT,
                evaluated INTEGER,opened INTEGER,spread_rejected INTEGER,updated_at TEXT NOT NULL)""").close()

    def rows(self, *, limit=5000):
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, """SELECT filtered_trade_id,opportunity_id,source_signal_id,
                broad_decision,broad_reason,execution_eligible,execution_rejection_reason,symbol,direction,option_symbol,
                spread_percent,entry_fill,total_debit,signal_age_seconds,signal_age_bucket,opened_at,closed_at,status,
                realized_pnl,realized_return_percent,mfe_pct,mae_pct,peak_return_pct,giveback_pct,
                shadow_30_return,shadow_30_pnl,shadow_45_return,shadow_45_pnl FROM filtered_execution_trades
                ORDER BY created_at DESC LIMIT ?""", (int(limit),))

    def save_runtime_state(self, scanner_id, *, enabled, status, result, now):
        with self.repository.connection() as connection:
            current=self.repository._fetchone(connection,"SELECT scanner_id FROM filtered_execution_runtime_state WHERE scanner_id=?",(scanner_id,))
            values=(1 if enabled else 0,status,utc_iso(now),int(result.get("evaluated") or 0),int(result.get("opened") or 0),int(result.get("spread_rejected") or 0),utc_iso(now))
            if current:
                self.repository._execute(connection,"""UPDATE filtered_execution_runtime_state SET enabled=?,status=?,last_cycle_at=?,evaluated=?,opened=?,spread_rejected=?,updated_at=? WHERE scanner_id=?""",(*values,scanner_id)).close()
            else:
                self.repository._execute(connection,"""INSERT INTO filtered_execution_runtime_state (enabled,status,last_cycle_at,evaluated,opened,spread_rejected,updated_at,scanner_id) VALUES (?,?,?,?,?,?,?,?)""",(*values,scanner_id)).close()

    def get(self, opportunity_id):
        with self.repository.connection() as connection:
            return self.repository._fetchone(connection, "SELECT * FROM filtered_execution_trades WHERE opportunity_id=?", (opportunity_id,))

    def record(self, opportunity_id, event, broad, mirror, now):
        existing = self.get(opportunity_id)
        if existing: return existing
        accepted = bool(broad and broad.get("accepted"))
        spread = _number(mirror.get("spread_percent")) if mirror else None
        reason = "BROAD_REJECTED" if not accepted else "SPREAD_TOO_WIDE" if spread is not None and spread > SPREAD_CAP_PERCENT else None
        eligible = accepted and mirror and mirror.get("status") in {"OPEN","CLOSED","EXIT_PENDING"} and reason is None
        if accepted and not mirror: reason = "MIRROR_EXECUTION_UNAVAILABLE"
        event_at = _dt(event.get("event_timestamp")); age = max(0.0, (now-event_at).total_seconds())
        trade_id = hashlib.sha256(f"{opportunity_id}|{LANE}".encode()).hexdigest()
        bid, ask = _number((mirror or {}).get("entry_bid")), _number((mirror or {}).get("entry_ask"))
        mid = (bid+ask)/2 if bid is not None and ask is not None else None
        values = (trade_id,opportunity_id,opportunity_id,utc_iso(event_at),"ACCEPTED" if accepted else "REJECTED",
            (broad or {}).get("reason_code"),1 if eligible else 0,reason,event.get("symbol"),(mirror or {}).get("direction"),
            (mirror or {}).get("option_symbol"),(mirror or {}).get("option_type"),(mirror or {}).get("expiration"),
            (mirror or {}).get("strike"),(mirror or {}).get("dte"),bid,ask,mid,(ask-bid if bid is not None and ask is not None else None),
            spread,(mirror or {}).get("entry_fill"),(mirror or {}).get("total_debit"),1,100,age,signal_age_bucket(age),
            int(age<=60),int(age<=120),int(age<=180),int(age<=300),(mirror or {}).get("opened_at") if eligible else None,
            "OPEN" if eligible else "REJECTED",utc_iso(now),utc_iso(now))
        with self.repository.connection() as connection:
            self.repository._execute(connection, """INSERT INTO filtered_execution_trades (
                filtered_trade_id,opportunity_id,source_signal_id,authoritative_event_at,broad_decision,broad_reason,
                execution_eligible,execution_rejection_reason,symbol,direction,option_symbol,option_type,expiration,strike,dte,
                entry_bid,entry_ask,entry_mid,spread_dollars,spread_percent,entry_fill,total_debit,quantity,contract_multiplier,
                signal_age_seconds,signal_age_bucket,eligible_60s,eligible_120s,eligible_180s,eligible_300s,opened_at,status,
                created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(opportunity_id) DO NOTHING""", values).close()
        try:
            self.repository.enrich_opportunity_context(opportunity_id, {"lifecycle": {
                "filtered_evaluated_at": utc_iso(now), "filtered_opened_at": (mirror or {}).get("opened_at") if eligible else None,
                "authoritative_to_filtered_open_seconds": age if eligible else None, "signal_age_bucket": signal_age_bucket(age)}})
        except Exception:
            LOGGER.exception("Could not enrich shadow opportunity context %s", opportunity_id)
        return self.get(opportunity_id)

    def sync(self, filtered, mirror, marks, now):
        if not filtered or not filtered.get("execution_eligible") or not mirror: return
        returns = [_number(mark.get("return_pct")) for mark in marks]
        returns = [value for value in returns if value is not None]
        mfe, mae = (max(returns), min(returns)) if returns else (None,None)
        final = _number(mirror.get("realized_return_percent"))
        giveback = max(0,mfe-final) if mfe is not None and final is not None else None
        shadow30 = next((v for v in returns if v <= -30), final)
        shadow45 = next((v for v in returns if v <= -45), final)
        debit = _number(filtered.get("total_debit"))
        with self.repository.connection() as connection:
            self.repository._execute(connection, """UPDATE filtered_execution_trades SET closed_at=?,status=?,exit_reason=?,
                exit_fill=?,realized_pnl=?,realized_return_percent=?,mfe_pct=?,mae_pct=?,peak_return_pct=?,giveback_pct=?,
                shadow_30_return=?,shadow_30_pnl=?,shadow_45_return=?,shadow_45_pnl=?,updated_at=? WHERE opportunity_id=?""", (
                mirror.get("exit_quote_at"),"CLOSED" if mirror.get("status")=="CLOSED" else "OPEN",
                mirror.get("authoritative_exit_reason"),mirror.get("exit_fill"),mirror.get("realized_pnl"),final,mfe,mae,mfe,giveback,
                shadow30,debit*shadow30/100 if debit is not None and shadow30 is not None else None,
                shadow45,debit*shadow45/100 if debit is not None and shadow45 is not None else None,utc_iso(now),filtered["opportunity_id"])).close()


def run_filtered_execution(repository, filtered_repository, paper_repository, mirror_repository, entry_events, *, enabled, scanner_id, now=None):
    now = now or datetime.now(timezone.utc)
    if not enabled:
        result={"status":"DISABLED","evaluated":0,"opened":0,"spread_rejected":0}
        filtered_repository.save_runtime_state(scanner_id,enabled=False,status="DISABLED",result=result,now=now)
        return result
    events = {str(e.get("opportunity_id") or e.get("trade_id")):e for e in entry_events}
    ids = list(events)
    decisions = paper_repository.analytics_decisions(ids, limit=max(1,len(ids)*5))
    broad = {}
    for row in decisions:
        meta = _json(row.get("metadata_json"))
        if str(meta.get("simulation_profile") or "").upper()=="BROAD": broad[str(row.get("source_signal_id"))]=row
    evaluated=opened=rejected=0
    for identity,event in events.items():
        if filtered_repository.get(identity): continue
        mirror = mirror_repository.get(identity)
        row = filtered_repository.record(identity,event,broad.get(identity),mirror,now)
        evaluated += 1; opened += bool(row and row.get("execution_eligible")); rejected += (row or {}).get("execution_rejection_reason")=="SPREAD_TOO_WIDE"
        reason=(row or {}).get("execution_rejection_reason")
        LOGGER.info(json.dumps({"event":"filtered_rejected_broad" if reason=="BROAD_REJECTED" else "filtered_rejected_spread" if reason=="SPREAD_TOO_WIDE" else "filtered_paper_opened" if (row or {}).get("execution_eligible") else "filtered_candidate_evaluated",
            "opportunity_id":identity,"trade_id":(row or {}).get("filtered_trade_id"),"symbol":event.get("symbol"),
            "contract":(row or {}).get("option_symbol"),"spread_percent":(row or {}).get("spread_percent"),
            "signal_age_seconds":(row or {}).get("signal_age_seconds"),"variant":LANE},sort_keys=True))
    for row in filtered_repository.rows(limit=5000):
        mirror = mirror_repository.get(row["opportunity_id"])
        marks = mirror_repository.marks(mirror.get("mirror_trade_id")) if mirror else []
        filtered_repository.sync(row,mirror,marks,now)
        if row.get("execution_eligible") and mirror:
            LOGGER.info(json.dumps({"event":"filtered_trade_closed" if mirror.get("status")=="CLOSED" else "filtered_position_updated",
                "opportunity_id":row["opportunity_id"],"trade_id":row.get("filtered_trade_id"),"symbol":row.get("symbol"),
                "contract":row.get("option_symbol"),"spread_percent":row.get("spread_percent"),
                "signal_age_seconds":row.get("signal_age_seconds"),"variant":LANE,
                "pnl":mirror.get("realized_pnl") if mirror.get("status")=="CLOSED" else mirror.get("unrealized_pnl")},sort_keys=True))
    result={"status":"ACTIVE","evaluated":evaluated,"opened":opened,"spread_rejected":rejected}
    filtered_repository.save_runtime_state(scanner_id,enabled=True,status="ACTIVE",result=result,now=now)
    LOGGER.info(json.dumps({"event":"filtered_cycle_summary","scanner_id":scanner_id,**result},sort_keys=True))
    return result


def filtered_summary(rows):
    rows=list(rows); closed=[r for r in rows if r.get("status")=="CLOSED" and _number(r.get("realized_pnl")) is not None]
    wins=[r for r in closed if _number(r.get("realized_pnl"))>0]; losses=[r for r in closed if _number(r.get("realized_pnl"))<0]
    gp=sum(_number(r.get("realized_pnl")) for r in wins); gl=abs(sum(_number(r.get("realized_pnl")) for r in losses))
    opened=[r for r in rows if r.get("execution_eligible")]
    returns=[v for r in closed if (v:=_number(r.get("realized_return_percent"))) is not None]
    spreads=[v for r in opened if (v:=_number(r.get("spread_percent"))) is not None]
    ages=[v for r in rows if (v:=_number(r.get("signal_age_seconds"))) is not None]
    points=[]
    for row in opened:
        debit=_number(row.get("total_debit")); start=row.get("opened_at"); end=row.get("closed_at")
        if debit is not None and start: points.append((_dt(start),1,debit))
        if debit is not None and end: points.append((_dt(end),-1,debit))
    capital=peak=0.0
    for _,kind,debit in sorted(points,key=lambda item:(item[0],item[1])):
        capital += kind*debit; peak=max(peak,capital)
    net=sum(_number(r.get("realized_pnl")) or 0 for r in closed)
    return {"evaluated":len(rows),"broad_eligible":sum(r.get("broad_decision")=="ACCEPTED" for r in rows),
        "spread_rejected":sum(r.get("execution_rejection_reason")=="SPREAD_TOO_WIDE" for r in rows),"opened":len(opened),
        "closed":len(closed),"wins":len(wins),"losses":len(losses),"win_rate":len(wins)/len(closed)*100 if closed else None,
        "pnl":net,"average_return":mean(returns) if returns else None,
        "profit_factor":gp/gl if gl else math.inf if gp else None,"participation":len(opened)/len(rows)*100 if rows else None,
        "average_spread":mean(spreads) if spreads else None,
        "average_signal_age":mean(ages) if ages else None,
        "peak_capital":peak,"return_on_peak_capital":net/peak*100 if peak else None,
        "governance":"INSUFFICIENT DATA" if len(closed)<30 else "DESCRIPTIVE ONLY" if len(closed)<50 else "VALIDATION REQUIRED"}


def _number(value):
    try:
        value=float(value); return value if math.isfinite(value) else None
    except (TypeError,ValueError): return None
def _dt(value):
    value=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00")); return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
def _json(value):
    if isinstance(value,dict): return value
    try:return json.loads(value or "{}")
    except (TypeError,json.JSONDecodeError):return {}
