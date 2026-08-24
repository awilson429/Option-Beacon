from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContractRules:
    allowed_dte: tuple[int, ...] = (0, 1)
    min_delta: float = .40
    max_delta: float = .65
    max_spread_pct: float = 20.0
    min_volume: int = 10
    min_open_interest: int = 50


def filter_contracts(quotes, direction, rules=ContractRules()):
    kind = "call" if str(getattr(direction, "value", direction)).upper() == "CALL" else "put"
    accepted, rejected = [], []
    for quote in quotes:
        row = dict(quote); bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
        mid = (bid+ask)/2 if bid and ask else 0; spread_pct = (ask-bid)/mid*100 if mid else None
        reasons=[]
        if str(row.get("option_type") or "").lower() != kind: reasons.append("wrong_option_type")
        if row.get("dte") not in rules.allowed_dte: reasons.append("dte_outside_research_universe")
        if row.get("delta") is None or not rules.min_delta <= abs(float(row["delta"])) <= rules.max_delta: reasons.append("delta_outside_range")
        if spread_pct is None or spread_pct > rules.max_spread_pct: reasons.append("spread_too_wide")
        if int(row.get("volume") or 0) < rules.min_volume: reasons.append("low_volume")
        if int(row.get("open_interest") or 0) < rules.min_open_interest: reasons.append("low_open_interest")
        row.update(mid=mid or None, spread_pct=spread_pct, term="0DTE" if row.get("dte")==0 else "1DTE" if row.get("dte")==1 else "OTHER")
        (rejected if reasons else accepted).append({**row, "rejection_reasons": reasons})
    return accepted, rejected


@dataclass(frozen=True)
class ExecutionConfig:
    entry_slippage: float = .02
    exit_slippage: float = .02
    fee_per_contract: float = .65


def simulate_execution(quote, exit_quote, *, quantity=1, config=ExecutionConfig()):
    entry_mid=(float(quote["bid"])+float(quote["ask"]))/2; exit_mid=(float(exit_quote["bid"])+float(exit_quote["ask"]))/2
    entry_fill=float(quote["ask"])+config.entry_slippage; exit_fill=max(0,float(exit_quote["bid"])-config.exit_slippage)
    fees=2*quantity*config.fee_per_contract
    return {"ideal_entry":entry_mid,"ideal_exit":exit_mid,"entry_fill":entry_fill,"exit_fill":exit_fill,"slippage":((entry_fill-entry_mid)+(exit_mid-exit_fill))*100*quantity,
            "fees":fees,"ideal_pnl":(exit_mid-entry_mid)*100*quantity,"realistic_pnl":(exit_fill-entry_fill)*100*quantity-fees}
