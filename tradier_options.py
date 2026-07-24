import json
import os
from datetime import date, datetime
from functools import lru_cache
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://api.tradier.com/v1"
TOKEN_ENV_NAME = "TRADIER_ACCESS_TOKEN"
BASE_URL_ENV_NAME = "TRADIER_API_BASE_URL"


@lru_cache(maxsize=8)
def _secret_value(name):
    value = os.getenv(name)
    if value:
        return value

    try:
        import streamlit as st

        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass

    return ""


def tradier_configured():
    return bool(_secret_value(TOKEN_ENV_NAME))


def _headers():
    return {
        "Authorization": f"Bearer {_secret_value(TOKEN_ENV_NAME)}",
        "Accept": "application/json",
    }


def _get_json(path, params=None, timeout=8):
    token = _secret_value(TOKEN_ENV_NAME)
    if not token:
        return None, "TRADIER_ACCESS_TOKEN is not configured."

    base_url = _secret_value(BASE_URL_ENV_NAME) or DEFAULT_BASE_URL
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    if params:
        url = f"{url}?{urlencode(params)}"

    request = Request(url, headers=_headers())
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), ""
    except Exception as exc:
        return None, f"Tradier request failed: {exc}"


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


@lru_cache(maxsize=256)
def option_expirations(symbol):
    payload, error = _get_json(
        "/markets/options/expirations",
        {"symbol": symbol, "includeAllRoots": "true", "strikes": "false"},
    )
    if error:
        return [], error

    expirations = _as_list((payload or {}).get("expirations", {}).get("date"))
    return [expiration for expiration in expirations if expiration], ""


def _days_to_expiration(expiration):
    try:
        expiration_date = datetime.strptime(expiration, "%Y-%m-%d").date()
        return (expiration_date - date.today()).days
    except (TypeError, ValueError):
        return 999


def _preferred_expiration(expirations, min_dte=0, max_dte=14):
    dated = sorted((expiration, _days_to_expiration(expiration)) for expiration in expirations)
    for expiration, dte in dated:
        if min_dte <= dte <= max_dte:
            return expiration, dte
    for expiration, dte in dated:
        if dte >= 0:
            return expiration, dte
    return None, None


@lru_cache(maxsize=512)
def option_chain(symbol, expiration):
    payload, error = _get_json(
        "/markets/options/chains",
        {"symbol": symbol, "expiration": expiration, "greeks": "true"},
    )
    if error:
        return [], error

    options = _as_list((payload or {}).get("options", {}).get("option"))
    return options, ""


def _number(value, default=0):
    try:
        if value in [None, ""]:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _option_side(direction):
    if direction == "Bullish":
        return "call"
    if direction == "Bearish":
        return "put"
    return ""


def _midpoint(bid, ask, last):
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    return last


def _contract_score(contract, underlying_price):
    bid = _number(contract.get("bid"))
    ask = _number(contract.get("ask"))
    last = _number(contract.get("last"))
    volume = _number(contract.get("volume"))
    open_interest = _number(contract.get("open_interest"))
    strike = _number(contract.get("strike"))
    midpoint = _midpoint(bid, ask, last)
    spread = ask - bid if ask and bid else 0
    spread_pct = spread / midpoint if midpoint else 1
    distance_pct = abs(strike - underlying_price) / underlying_price if underlying_price else 1

    score = 0
    if open_interest >= 5000:
        score += 25
    elif open_interest >= 1000:
        score += 20
    elif open_interest >= 250:
        score += 12
    elif open_interest > 0:
        score += 6

    if volume >= 1000:
        score += 25
    elif volume >= 250:
        score += 18
    elif volume >= 50:
        score += 10
    elif volume > 0:
        score += 4

    if spread_pct <= 0.05:
        score += 25
    elif spread_pct <= 0.10:
        score += 18
    elif spread_pct <= 0.18:
        score += 10
    elif spread_pct <= 0.30:
        score += 4

    if distance_pct <= 0.015:
        score += 20
    elif distance_pct <= 0.035:
        score += 14
    elif distance_pct <= 0.06:
        score += 8

    if bid > 0 and ask > 0:
        score += 5

    return min(score, 100), spread_pct


def _contract_payload(contract, score, spread_pct, dte):
    bid = _number(contract.get("bid"))
    ask = _number(contract.get("ask"))
    volume = int(_number(contract.get("volume")))
    open_interest = int(_number(contract.get("open_interest")))
    strike = _number(contract.get("strike"))
    symbol = contract.get("symbol") or contract.get("option_symbol") or ""

    if score >= 80:
        label = "Strong"
    elif score >= 60:
        label = "Acceptable"
    elif score >= 40:
        label = "Thin"
    else:
        label = "Weak"

    return {
        "available": True,
        "score": score,
        "label": label,
        "contract": symbol,
        "expiration": contract.get("expiration_date") or contract.get("expiration"),
        "dte": dte,
        "option_type": contract.get("option_type"),
        "strike": round(strike, 2),
        "bid": round(bid, 2),
        "ask": round(ask, 2),
        "spread_pct": round(spread_pct * 100, 1),
        "volume": volume,
        "open_interest": open_interest,
        "detail": (
            f"{label} options liquidity: {volume:,} volume, {open_interest:,} open interest, "
            f"{round(spread_pct * 100, 1)}% spread."
        ),
    }


def option_liquidity_for_setup(result):
    symbol = result.get("symbol")
    direction = result.get("bias")
    signal = result.get("signal")
    price = _number(result.get("price"))
    side = _option_side(direction)

    if signal not in ["BULLISH SETUP", "BEARISH SETUP", "BUY CALL", "BUY PUT"]:
        return {"available": False, "score": 0, "label": "Not checked", "detail": "Option chain is checked only for active setups."}

    if not symbol or not side or not price:
        return {"available": False, "score": 0, "label": "Unavailable", "detail": "No directional option setup is active."}

    expirations, error = option_expirations(symbol)
    if error:
        return {"available": False, "score": 0, "label": "Unavailable", "detail": error}

    expiration, dte = _preferred_expiration(expirations)
    if not expiration:
        return {"available": False, "score": 0, "label": "Unavailable", "detail": "No Tradier option expirations returned."}

    contracts, error = option_chain(symbol, expiration)
    if error:
        return {"available": False, "score": 0, "label": "Unavailable", "detail": error}

    same_side = [
        contract for contract in contracts
        if str(contract.get("option_type", "")).lower() == side
    ]
    if not same_side:
        return {"available": False, "score": 0, "label": "Unavailable", "detail": f"No {side} contracts returned for {expiration}."}

    scored = []
    for contract in same_side:
        score, spread_pct = _contract_score(contract, price)
        scored.append((score, spread_pct, contract))

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_spread, best_contract = scored[0]
    return _contract_payload(best_contract, best_score, best_spread, dte)


def enrich_with_option_liquidity(result):
    if not result:
        return result

    enriched = dict(result)
    enriched["option_liquidity"] = option_liquidity_for_setup(enriched)
    return enriched
