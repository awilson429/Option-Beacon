"""Point-in-time translation flight recorder. RESEARCH ONLY — never trades.

THE FLIGHT RECORDER DOES NOT MAKE TRADING DECISIONS.

It observes TRADE_ENTERED option-path evaluation, production capture/fill, and
open-position refresh quotes. Failures are swallowed by the worker wrappers so
authoritative paper / BROAD / OB behavior continues unchanged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from datetime import date, datetime, timezone

from option_trade_engine import (
    TradierOptionChainProvider,
    select_contract,
)
from trade_repository import utc_iso


LOGGER = logging.getLogger(__name__)

RESEARCH_VERSION = "TRANSLATION_FLIGHT_RECORDER_V1"
LANE_ROLE = "RESEARCH"
CAPTURE_TRADE_ENTERED = "TRADE_ENTERED"
CAPTURE_PRODUCTION_FILL = "PRODUCTION_FILL"

RESULT_CAPTURED = "CAPTURED"
RESULT_CHAIN_EMPTY = "CHAIN_EMPTY"
RESULT_NO_ELIGIBLE_CONTRACT = "NO_ELIGIBLE_CONTRACT"
RESULT_PROVIDER_FAILURE = "PROVIDER_FAILURE"
RESULT_CAPTURE_FAILURE = "CAPTURE_FAILURE"
RESULT_CAPTURE_UNAVAILABLE = "CAPTURE_UNAVAILABLE"
RESULT_NOT_REQUESTED_BY_PRODUCTION = "NOT_REQUESTED_BY_PRODUCTION"

OBSERVATION_SAME_CAPTURE = "SAME_CAPTURE"
OBSERVATION_DISTINCT_CAPTURE = "DISTINCT_CAPTURE"
OBSERVATION_NOT_REQUESTED = "NOT_REQUESTED"


def translation_research_enabled(environ=None):
    value = (environ or os.environ).get("OPTIONBEACON_TRANSLATION_RESEARCH_ENABLED", "true")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class ResearchCachedChainProvider:
    """One-cycle read-through cache so T0 observation can reuse the production payload."""

    def __init__(self, provider=None):
        self.provider = provider or TradierOptionChainProvider()
        self._expirations = {}
        self._chains = {}
        self._observed = {}
        self.last_requested_at = None
        self.last_responded_at = None
        self.last_ticker = None
        self.last_expiration = None
        self.last_expirations = None
        self.last_chain = None
        self.last_error = None

    def expirations(self, ticker):
        key = str(ticker or "").upper()
        if key not in self._expirations:
            requested_at = datetime.now(timezone.utc)
            self._expirations[key] = self.provider.expirations(ticker)
            responded_at = datetime.now(timezone.utc)
            error = (self._expirations[key] or (None, None))[1]
            self._observed[key] = {
                **(self._observed.get(key) or {}),
                "requested_at": requested_at,
                "responded_at": responded_at,
                "expirations": self._expirations[key],
                "error": error,
            }
        self.last_expirations = self._expirations[key]
        observed = self._observed.get(key) or {}
        self.last_requested_at = observed.get("requested_at")
        self.last_responded_at = observed.get("responded_at")
        self.last_ticker = key
        error = (self.last_expirations or (None, None))[1]
        if error:
            self.last_error = error
        return self.last_expirations

    def chain(self, ticker, expiration):
        key = (str(ticker or "").upper(), str(expiration))
        ticker_key = key[0]
        if key not in self._chains:
            requested_at = datetime.now(timezone.utc)
            self._chains[key] = self.provider.chain(ticker, expiration)
            responded_at = datetime.now(timezone.utc)
            error = (self._chains[key] or (None, None))[1]
            prior = self._observed.get(ticker_key) or {}
            self._observed[ticker_key] = {
                **prior,
                "requested_at": prior.get("requested_at") or requested_at,
                "responded_at": responded_at,
                "expiration": str(expiration),
                "chain": self._chains[key],
                "error": error or prior.get("error"),
            }
        self.last_chain = self._chains[key]
        self.last_expiration = str(expiration)
        self.last_ticker = ticker_key
        observed = self._observed.get(ticker_key) or {}
        self.last_requested_at = observed.get("requested_at")
        self.last_responded_at = observed.get("responded_at")
        error = (self.last_chain or (None, None))[1]
        if error:
            self.last_error = error
        return self.last_chain

    def observed_for(self, ticker):
        return self._observed.get(str(ticker or "").upper()) or {}


class ResearchObservingQuoteProvider:
    """Delegates to the production quote provider and retains the raw payload."""

    def __init__(self, provider):
        self.provider = provider
        self.quotes = {}
        self.requested_at = {}
        self.responded_at = {}

    def quote(self, option_symbol):
        symbol = str(option_symbol or "")
        self.requested_at[symbol] = datetime.now(timezone.utc)
        result = self.provider.quote(option_symbol)
        self.responded_at[symbol] = datetime.now(timezone.utc)
        self.quotes[symbol] = result
        return result


def cached_chain_provider(provider=None):
    if isinstance(provider, ResearchCachedChainProvider):
        return provider
    return ResearchCachedChainProvider(provider)


def capture_id_for(opportunity_id, capture_reason, *, research_version=RESEARCH_VERSION):
    raw = f"{research_version}|{opportunity_id}|{capture_reason}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def mark_id_for(paper_trade_id, recorded_at, *, research_version=RESEARCH_VERSION):
    raw = f"{research_version}|{paper_trade_id}|{utc_iso(recorded_at)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def option_type_for(result):
    plan = (result or {}).get("trade_plan") or {}
    direction = plan.get("direction") or (result or {}).get("bias")
    return {"Bullish": "call", "Bearish": "put"}.get(direction)


def trade_entered_at(result):
    value = (result or {}).get("timestamp")
    if value is None:
        return None
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp


def payload_identity_for(ticker, expiration, contracts):
    if contracts is None:
        return None
    raw = json.dumps(
        {"ticker": str(ticker or "").upper(), "expiration": expiration, "contracts": contracts},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def production_chain_observation(provider, ticker):
    """Read the chain production already requested. Never calls the provider."""
    ticker = str(ticker or "").upper()
    observed = {}
    if provider is not None and callable(getattr(provider, "observed_for", None)):
        observed = provider.observed_for(ticker) or {}
    last_chain = observed.get("chain")
    last_error = observed.get("error")
    expiration = observed.get("expiration")
    requested_at = observed.get("requested_at")
    responded_at = observed.get("responded_at")
    expirations = observed.get("expirations")
    if last_chain is None and getattr(provider, "last_ticker", None) == ticker:
        last_chain = getattr(provider, "last_chain", None)
        expiration = expiration or getattr(provider, "last_expiration", None)
        requested_at = requested_at or getattr(provider, "last_requested_at", None)
        responded_at = responded_at or getattr(provider, "last_responded_at", None)
        last_error = last_error or getattr(provider, "last_error", None)
        expirations = expirations or getattr(provider, "last_expirations", None)
    requested = any([
        last_chain is not None,
        expirations is not None,
        last_error,
        requested_at is not None,
    ])
    if not requested:
        return {
            "result": RESULT_NOT_REQUESTED_BY_PRODUCTION,
            "rejection_reason": "Production did not request option-chain data.",
            "expiration": None,
            "contracts": None,
            "requested_at": None,
            "responded_at": None,
            "payload_identity": None,
            "observation_relation": OBSERVATION_NOT_REQUESTED,
            "provider_request_occurred": False,
        }
    contracts = None
    if last_chain is not None:
        contracts, chain_error = last_chain
        if chain_error:
            last_error = chain_error
    if last_error:
        return {
            "result": RESULT_PROVIDER_FAILURE,
            "rejection_reason": _safe_reason(last_error),
            "expiration": expiration,
            "contracts": None,
            "requested_at": requested_at,
            "responded_at": responded_at,
            "payload_identity": None,
            "observation_relation": OBSERVATION_SAME_CAPTURE,
            "provider_request_occurred": True,
        }
    if contracts is None:
        expiration_rows = expirations[0] if isinstance(expirations, tuple) else expirations
        return {
            "result": RESULT_CHAIN_EMPTY,
            "rejection_reason": "No listed expiration available.",
            "expiration": expiration,
            "contracts": [] if expiration_rows == [] or expiration_rows is None else None,
            "requested_at": requested_at,
            "responded_at": responded_at,
            "payload_identity": None,
            "observation_relation": OBSERVATION_SAME_CAPTURE,
            "provider_request_occurred": True,
        }
    if not contracts:
        return {
            "result": RESULT_CHAIN_EMPTY,
            "rejection_reason": "Empty option chain.",
            "expiration": expiration,
            "contracts": [],
            "requested_at": requested_at,
            "responded_at": responded_at,
            "payload_identity": payload_identity_for(ticker, expiration, []),
            "observation_relation": OBSERVATION_SAME_CAPTURE,
            "provider_request_occurred": True,
        }
    return {
        "result": RESULT_CAPTURED,
        "rejection_reason": None,
        "expiration": expiration,
        "contracts": contracts,
        "requested_at": requested_at,
        "responded_at": responded_at,
        "payload_identity": payload_identity_for(ticker, expiration, contracts),
        "observation_relation": OBSERVATION_SAME_CAPTURE,
        "provider_request_occurred": True,
    }


def capture_unavailable_from_trade(trade):
    if trade is None:
        return RESULT_CAPTURE_UNAVAILABLE, "Production chain payload was not observable."
    reason = getattr(trade, "data_unavailable_reason", None) or "Production chain payload was not observable."
    status = getattr(trade, "status", None)
    if status == "QUALIFIED" and getattr(trade, "option_symbol", None):
        return RESULT_CAPTURE_UNAVAILABLE, reason
    lowered = str(reason).lower()
    if "no listed expiration" in lowered or "empty option chain" in lowered:
        return RESULT_CHAIN_EMPTY, reason
    if any(token in lowered for token in ("unavailable", "provider", "failed", "credentials")):
        return RESULT_PROVIDER_FAILURE, reason
    return RESULT_NO_ELIGIBLE_CONTRACT, reason


def research_candidates(contracts, *, option_type, underlying_price, as_of, expiration=None):
    """Annotate the CALL/PUT universe passed into `select_contract`. Does not change it."""
    matching = [
        raw for raw in contracts or []
        if str(raw.get("option_type") or "").lower() == str(option_type or "").lower()
    ]
    choice = None
    if option_type and underlying_price is not None and matching:
        choice = select_contract(
            contracts, option_type=option_type, underlying_price=underlying_price
        )
    choice_symbol = (choice or {}).get("option_symbol")
    rows = []
    ranked = []
    for raw in matching:
        row = _candidate_row(raw, option_type=option_type, as_of=as_of, expiration=expiration)
        ranked.append(row)
    ranked.sort(key=lambda item: _selector_sort_key(item, underlying_price))
    for index, row in enumerate(ranked, 1):
        row["selector_rank"] = index
        row["is_selector_choice"] = int(bool(choice_symbol) and row.get("option_symbol") == choice_symbol)
        rows.append(row)
    if choice_symbol is None and matching:
        result = RESULT_NO_ELIGIBLE_CONTRACT
        reason = "No valid option contract available."
    elif not matching and contracts is not None:
        result = RESULT_NO_ELIGIBLE_CONTRACT
        reason = "No contracts matched the TRADE_ENTERED direction."
    else:
        result = RESULT_CAPTURED
        reason = None
    return rows, result, reason, choice_symbol


def build_capture_record(
    *,
    opportunity_id,
    capture_reason,
    result,
    symbol,
    direction=None,
    rejection_reason=None,
    candidates=None,
    selected_option_symbol=None,
    production_option_symbol=None,
    production_fill=None,
    production_realistic_entry=None,
    underlying_price=None,
    underlying_timestamp=None,
    requested_at=None,
    provider_responded_at=None,
    trade_entered_at_value=None,
    scan_cycle_id=None,
    authoritative_trade_id=None,
    paper_trade_id=None,
    authoritative_event_id=None,
    metadata=None,
    now=None,
):
    now = now or datetime.now(timezone.utc)
    rows = list(candidates or [])
    elapsed = None
    entered = trade_entered_at_value
    if entered is not None:
        elapsed = max(0.0, (now - entered).total_seconds())
    return {
        "capture_id": capture_id_for(opportunity_id, capture_reason),
        "research_version": RESEARCH_VERSION,
        "lane_role": LANE_ROLE,
        "capture_reason": capture_reason,
        "opportunity_id": opportunity_id,
        "authoritative_trade_id": authoritative_trade_id,
        "authoritative_event_id": authoritative_event_id,
        "scan_cycle_id": scan_cycle_id,
        "paper_trade_id": paper_trade_id,
        "symbol": str(symbol or "").upper(),
        "direction": direction,
        "capture_result": result,
        "rejection_reason": rejection_reason,
        "candidate_count": None if candidates is None else len(rows),
        "eligible_candidate_count": (
            None if candidates is None else sum(1 for row in rows if row.get("passed_selector_eligibility"))
        ),
        "selected_option_symbol": selected_option_symbol,
        "production_option_symbol": production_option_symbol,
        "production_fill": production_fill,
        "production_realistic_entry": production_realistic_entry,
        "underlying_price": _optional_float(underlying_price),
        "underlying_timestamp": utc_iso(underlying_timestamp) if underlying_timestamp else None,
        "requested_at": utc_iso(requested_at or now),
        "provider_responded_at": utc_iso(provider_responded_at) if provider_responded_at else None,
        "persisted_at": utc_iso(now),
        "trade_entered_at": utc_iso(entered) if entered else None,
        "elapsed_from_trade_entered_seconds": elapsed,
        "metadata_json": json.dumps(metadata or {}, sort_keys=True),
        "candidates": rows,
    }


def build_mark_record(
    *,
    paper_trade_id,
    opportunity_id,
    symbol,
    option_symbol,
    recorded_at,
    scan_cycle_id=None,
    quote=None,
    quote_error=None,
    requested_at=None,
    responded_at=None,
    position=None,
):
    payload = quote if isinstance(quote, dict) else {}
    greeks = payload.get("greeks") if isinstance(payload.get("greeks"), dict) else {}
    bid = _optional_float(payload.get("bid"))
    ask = _optional_float(payload.get("ask"))
    last = _optional_float(payload.get("last"))
    mid = None
    if bid is not None and ask is not None:
        mid = (bid + ask) / 2
    elif last is not None:
        mid = last
    quote_timestamp = (
        payload.get("trade_date")
        or payload.get("updated_at")
        or greeks.get("updated_at")
        or (utc_iso(responded_at) if responded_at else None)
    )
    age = None
    if requested_at is not None and responded_at is not None:
        age = max(0.0, (responded_at - requested_at).total_seconds())
    underlying = _optional_float(
        payload.get("underlying") or payload.get("underlying_price")
        or getattr(position, "last_underlying_price", None)
    )
    entry = _optional_float(getattr(position, "paper_fill_price", None) or getattr(position, "entry_mid", None))
    current_return = _optional_float(getattr(position, "current_return_percent", None))
    if bid is None:
        bid = _optional_float(getattr(position, "current_bid", None))
    if ask is None:
        ask = _optional_float(getattr(position, "current_ask", None))
    if mid is None:
        mid = _optional_float(getattr(position, "current_mid", None))
    return {
        "mark_id": mark_id_for(paper_trade_id, recorded_at),
        "research_version": RESEARCH_VERSION,
        "lane_role": LANE_ROLE,
        "opportunity_id": opportunity_id,
        "paper_trade_id": paper_trade_id,
        "scan_cycle_id": scan_cycle_id,
        "symbol": str(symbol or "").upper() or None,
        "option_symbol": option_symbol,
        "recorded_at": utc_iso(recorded_at),
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "last": last,
        "quote_timestamp": str(quote_timestamp) if quote_timestamp else None,
        "provider_timestamp": utc_iso(responded_at) if responded_at else None,
        "quote_age_seconds": age,
        "volume": _optional_int(payload.get("volume")),
        "open_interest": _optional_int(payload.get("open_interest")),
        "delta": _optional_float(payload.get("delta", greeks.get("delta"))),
        "implied_volatility": _optional_float(
            payload.get("implied_volatility", greeks.get("mid_iv", greeks.get("smv_vol")))
        ),
        "gamma": _optional_float(payload.get("gamma", greeks.get("gamma"))),
        "theta": _optional_float(payload.get("theta", greeks.get("theta"))),
        "underlying_price": underlying,
        "underlying_timestamp": utc_iso(responded_at) if responded_at and underlying is not None else None,
        "entry_price": entry,
        "current_return_pct": current_return,
        "trade_status": getattr(position, "status", None),
        "lifecycle_state": getattr(position, "status", None),
        "management_state_json": json.dumps({
            "exit_reason": getattr(position, "exit_reason", None),
            "quote_error": _safe_reason(quote_error) if quote_error else None,
        }, sort_keys=True),
    }


def record_trade_entered_capture(repository, result, provider, *, now=None, scan_cycle_id=None, trade=None):
    """Persist T0 evidence. Must never raise into the authoritative path."""
    try:
        if repository is None or not translation_research_enabled():
            return None
        opportunity_id = str((result or {}).get("_authoritative_entry_id") or "").strip()
        if not opportunity_id:
            return None
        if repository.get_capture(opportunity_id, CAPTURE_TRADE_ENTERED):
            LOGGER.info(json.dumps({
                "event": "translation_research_duplicate_ignored",
                "capture_reason": CAPTURE_TRADE_ENTERED,
                "opportunity_id": opportunity_id,
                "research_version": RESEARCH_VERSION,
            }, sort_keys=True))
            return repository.get_capture(opportunity_id, CAPTURE_TRADE_ENTERED)
        ticker = str((result or {}).get("symbol") or "").upper()
        option_type = option_type_for(result)
        as_of = (now or datetime.now(timezone.utc)).date()
        loaded = production_chain_observation(provider, ticker)
        candidates = None
        selected = None
        result_code = loaded["result"]
        reason = loaded["rejection_reason"]
        if result_code == RESULT_NOT_REQUESTED_BY_PRODUCTION and trade is not None:
            result_code, reason = capture_unavailable_from_trade(trade)
        if loaded["contracts"] is not None and loaded["result"] != RESULT_PROVIDER_FAILURE:
            underlying = _optional_float((result or {}).get("price"))
            candidates, annotated, annotated_reason, selected = research_candidates(
                loaded["contracts"],
                option_type=option_type,
                underlying_price=underlying,
                as_of=as_of,
                expiration=loaded["expiration"],
            )
            if loaded["result"] == RESULT_CAPTURED:
                result_code = annotated
                reason = annotated_reason
        record = build_capture_record(
            opportunity_id=opportunity_id,
            capture_reason=CAPTURE_TRADE_ENTERED,
            result=result_code,
            symbol=ticker,
            direction=((result or {}).get("trade_plan") or {}).get("direction") or (result or {}).get("bias"),
            rejection_reason=reason,
            candidates=candidates,
            selected_option_symbol=selected,
            underlying_price=(result or {}).get("price"),
            underlying_timestamp=now,
            requested_at=loaded["requested_at"],
            provider_responded_at=loaded["responded_at"],
            trade_entered_at_value=trade_entered_at(result),
            scan_cycle_id=scan_cycle_id,
            authoritative_trade_id=opportunity_id,
            authoritative_event_id=(result or {}).get("_authoritative_event_id"),
            metadata={
                "expiration": loaded["expiration"],
                "observation_relation": loaded["observation_relation"],
                "payload_identity": loaded["payload_identity"],
                "market_data_source": "PRODUCTION_CAPTURE",
                "provider_request_occurred": loaded["provider_request_occurred"],
            },
            now=now,
        )
        stored = repository.record_capture(record)
        LOGGER.info(json.dumps({
            "event": "translation_research_capture_succeeded",
            "capture_reason": CAPTURE_TRADE_ENTERED,
            "opportunity_id": opportunity_id,
            "capture_result": result_code,
            "candidate_count": record["candidate_count"],
            "research_version": RESEARCH_VERSION,
        }, sort_keys=True))
        return stored
    except Exception:
        LOGGER.exception(json.dumps({
            "event": "translation_research_capture_failed",
            "capture_reason": CAPTURE_TRADE_ENTERED,
            "opportunity_id": str((result or {}).get("_authoritative_entry_id") or ""),
            "research_version": RESEARCH_VERSION,
        }, sort_keys=True))
        return None


def record_production_fill_capture(
    repository, result, trade, decision, provider, *, now=None, scan_cycle_id=None,
):
    """Persist fill-time evidence from the production capture/decision. Never raises."""
    try:
        if repository is None or not translation_research_enabled():
            return None
        opportunity_id = str((result or {}).get("_authoritative_entry_id") or "").strip()
        if not opportunity_id:
            return None
        existing = repository.get_capture(opportunity_id, CAPTURE_PRODUCTION_FILL)
        fill = getattr(decision, "paper_fill_price", None) if decision is not None else None
        if existing:
            if existing.get("production_fill") is None and fill is not None:
                repository.enrich_fill(
                    opportunity_id,
                    production_fill=fill,
                    production_realistic_entry=fill,
                    paper_trade_id=getattr(trade, "trade_id", None),
                    now=now,
                )
            LOGGER.info(json.dumps({
                "event": "translation_research_duplicate_ignored",
                "capture_reason": CAPTURE_PRODUCTION_FILL,
                "opportunity_id": opportunity_id,
                "research_version": RESEARCH_VERSION,
            }, sort_keys=True))
            return repository.get_capture(opportunity_id, CAPTURE_PRODUCTION_FILL)
        ticker = str((result or {}).get("symbol") or getattr(trade, "ticker", "") or "").upper()
        option_type = option_type_for(result) or getattr(trade, "option_type", None)
        as_of = (now or datetime.now(timezone.utc)).date()
        loaded = production_chain_observation(provider, ticker)
        observed_contracts = loaded["contracts"]
        expiration = loaded["expiration"]
        requested_at = loaded["requested_at"]
        responded_at = loaded["responded_at"]
        candidates = None
        selected = getattr(trade, "option_symbol", None)
        result_code = loaded["result"]
        reason = loaded["rejection_reason"]
        if result_code == RESULT_NOT_REQUESTED_BY_PRODUCTION and trade is not None:
            result_code, reason = capture_unavailable_from_trade(trade)
        if observed_contracts is not None and loaded["result"] != RESULT_PROVIDER_FAILURE:
            candidates, annotated, annotated_reason, selector_choice = research_candidates(
                observed_contracts,
                option_type=option_type,
                underlying_price=_optional_float((result or {}).get("price")),
                as_of=as_of,
                expiration=expiration,
            )
            selected = selector_choice or selected
            if loaded["result"] == RESULT_CAPTURED:
                result_code = annotated
                reason = annotated_reason
        if decision is not None and not getattr(decision, "eligible", False):
            reason = reason or getattr(decision, "reason", None)
        production_symbol = getattr(trade, "option_symbol", None)
        for row in candidates or []:
            row["is_production_selected"] = int(
                bool(production_symbol) and row.get("option_symbol") == production_symbol
            )
        record = build_capture_record(
            opportunity_id=opportunity_id,
            capture_reason=CAPTURE_PRODUCTION_FILL,
            result=result_code,
            symbol=ticker,
            direction=getattr(trade, "direction", None) or ((result or {}).get("trade_plan") or {}).get("direction"),
            rejection_reason=reason if result_code != RESULT_CAPTURED or (
                decision is not None and not getattr(decision, "eligible", True)
            ) else None,
            candidates=candidates,
            selected_option_symbol=selected,
            production_option_symbol=production_symbol,
            production_fill=fill if decision is not None and getattr(decision, "eligible", False) else None,
            production_realistic_entry=fill,
            underlying_price=(result or {}).get("price") or getattr(trade, "underlying_entry_price", None),
            underlying_timestamp=now,
            requested_at=requested_at,
            provider_responded_at=responded_at,
            trade_entered_at_value=trade_entered_at(result),
            scan_cycle_id=scan_cycle_id,
            paper_trade_id=getattr(trade, "trade_id", None),
            authoritative_trade_id=opportunity_id,
            authoritative_event_id=(result or {}).get("_authoritative_event_id"),
            metadata={
                "production_eligible": getattr(decision, "eligible", None),
                "production_reason": getattr(decision, "reason", None),
                "trade_status": getattr(trade, "status", None),
                "observation_relation": loaded["observation_relation"],
                "payload_identity": loaded["payload_identity"],
                "market_data_source": "PRODUCTION_CAPTURE",
                "provider_request_occurred": loaded["provider_request_occurred"],
            },
            now=now,
        )
        if decision is not None and not getattr(decision, "eligible", False) and record["rejection_reason"] is None:
            record["rejection_reason"] = getattr(decision, "reason", None)
        stored = repository.record_capture(record)
        LOGGER.info(json.dumps({
            "event": "translation_research_capture_succeeded",
            "capture_reason": CAPTURE_PRODUCTION_FILL,
            "opportunity_id": opportunity_id,
            "capture_result": result_code,
            "candidate_count": record["candidate_count"],
            "research_version": RESEARCH_VERSION,
        }, sort_keys=True))
        return stored
    except Exception:
        LOGGER.exception(json.dumps({
            "event": "translation_research_capture_failed",
            "capture_reason": CAPTURE_PRODUCTION_FILL,
            "opportunity_id": str((result or {}).get("_authoritative_entry_id") or ""),
            "research_version": RESEARCH_VERSION,
        }, sort_keys=True))
        return None


def record_open_position_marks(
    repository, positions, quote_observer, *, now=None, scan_cycle_id=None, opportunity_lookup=None,
):
    """Persist one mark per OPEN paper position from the existing refresh quotes."""
    try:
        if repository is None or not translation_research_enabled():
            return 0
        now = now or datetime.now(timezone.utc)
        persisted = 0
        lookup = opportunity_lookup or {}
        quotes = getattr(quote_observer, "quotes", {}) if quote_observer is not None else {}
        for position in positions or []:
            if getattr(position, "status", None) != "OPEN":
                continue
            option_symbol = getattr(position, "option_symbol", None)
            raw = quotes.get(option_symbol) if option_symbol else None
            quote, error = (None, None)
            if isinstance(raw, tuple) and len(raw) == 2:
                quote, error = raw
            elif isinstance(raw, dict):
                quote = raw
            opportunity_id = lookup.get(getattr(position, "trade_id", None))
            record = build_mark_record(
                paper_trade_id=position.trade_id,
                opportunity_id=opportunity_id,
                symbol=getattr(position, "ticker", None),
                option_symbol=option_symbol,
                recorded_at=now,
                scan_cycle_id=scan_cycle_id,
                quote=quote if isinstance(quote, dict) else None,
                quote_error=error,
                requested_at=(getattr(quote_observer, "requested_at", {}) or {}).get(option_symbol),
                responded_at=(getattr(quote_observer, "responded_at", {}) or {}).get(option_symbol),
                position=position,
            )
            repository.record_mark(record)
            persisted += 1
        LOGGER.info(json.dumps({
            "event": "translation_research_marks_persisted",
            "marks_persisted": persisted,
            "research_version": RESEARCH_VERSION,
        }, sort_keys=True))
        return persisted
    except Exception:
        LOGGER.exception(json.dumps({
            "event": "translation_research_mark_failed",
            "research_version": RESEARCH_VERSION,
        }, sort_keys=True))
        return 0


def _candidate_row(raw, *, option_type, as_of, expiration=None):
    greeks = raw.get("greeks") if isinstance(raw.get("greeks"), dict) else {}
    bid = _optional_float(raw.get("bid"))
    ask = _optional_float(raw.get("ask"))
    mid = (bid + ask) / 2 if bid is not None and ask is not None else None
    strike = _optional_float(raw.get("strike"))
    symbol = raw.get("symbol") or raw.get("option_symbol")
    exp = raw.get("expiration_date") or raw.get("expiration") or expiration
    passed, rejection = _selector_eligibility(raw, option_type=option_type)
    delta = _optional_float(raw.get("delta", greeks.get("delta")))
    spread = None
    if bid is not None and ask is not None and mid not in (None, 0):
        spread = (ask - bid) / mid * 100
    return {
        "option_symbol": str(symbol) if symbol else None,
        "expiration": str(exp) if exp else None,
        "strike": strike,
        "option_type": option_type,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "bid_size": _optional_float(raw.get("bidsize", raw.get("bid_size"))),
        "ask_size": _optional_float(raw.get("asksize", raw.get("ask_size"))),
        "volume": _optional_int(raw.get("volume")),
        "open_interest": _optional_int(raw.get("open_interest")),
        "delta": delta,
        "implied_volatility": _optional_float(
            raw.get("implied_volatility", greeks.get("mid_iv", greeks.get("smv_vol")))
        ),
        "gamma": _optional_float(raw.get("gamma", greeks.get("gamma"))),
        "theta": _optional_float(raw.get("theta", greeks.get("theta"))),
        "dte": _dte(exp, as_of),
        "quote_timestamp": str(
            raw.get("trade_date") or greeks.get("updated_at") or raw.get("updated_at") or ""
        ) or None,
        "passed_selector_eligibility": int(passed),
        "rejection_reason": rejection,
        "selector_key_json": json.dumps({
            "delta_distance": abs(abs(delta) - 0.50) if delta is not None else None,
            "spread_percent": spread,
            "open_interest": _optional_int(raw.get("open_interest")),
            "volume": _optional_int(raw.get("volume")),
            "strike": strike,
            "option_symbol": str(symbol) if symbol else None,
        }, sort_keys=True),
        "is_selector_choice": 0,
        "is_production_selected": 0,
    }


def _selector_eligibility(raw, *, option_type):
    if str(raw.get("option_type") or "").lower() != str(option_type or "").lower():
        return False, "OPTION_TYPE_MISMATCH"
    if not (raw.get("symbol") or raw.get("option_symbol")):
        return False, "MISSING_OPTION_SYMBOL"
    if _optional_float(raw.get("strike")) is None:
        return False, "MISSING_STRIKE"
    ask = _optional_float(raw.get("ask"))
    if ask is None or ask <= 0:
        return False, "MISSING_ASK"
    bid = _optional_float(raw.get("bid"))
    if bid is not None and bid > ask:
        return False, "INVERTED_QUOTE"
    return True, None


def _selector_sort_key(row, underlying_price):
    delta = row.get("delta")
    spread = None
    try:
        payload = json.loads(row.get("selector_key_json") or "{}")
        spread = payload.get("spread_percent")
    except json.JSONDecodeError:
        spread = None
    delta_key = abs(abs(delta) - 0.50) if delta is not None else math.inf
    strike_distance = (
        abs((row.get("strike") or 0) - underlying_price)
        if underlying_price is not None and row.get("strike") is not None and delta is None
        else 0.0
    )
    return (
        0 if row.get("passed_selector_eligibility") else 1,
        delta_key if delta is not None else strike_distance,
        spread if spread is not None else math.inf,
        -(row.get("open_interest") or 0),
        -(row.get("volume") or 0),
        row.get("strike") if row.get("strike") is not None else math.inf,
        row.get("option_symbol") or "",
    )


def _dte(expiration, as_of):
    try:
        exp = date.fromisoformat(str(expiration))
    except (TypeError, ValueError):
        return None
    as_of = as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of))
    return (exp - as_of).days


def _optional_float(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_int(value):
    number = _optional_float(value)
    return int(number) if number is not None else None


def _safe_reason(value):
    text = str(value or "Option-chain data unavailable.")
    lowered = text.lower()
    if any(token in lowered for token in ("token", "authorization", "password", "secret", "postgres://")):
        return "Option-chain credentials unavailable."
    return text[:240]
