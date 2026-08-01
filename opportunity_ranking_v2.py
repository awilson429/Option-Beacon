"""Explainable Opportunity Ranking V2, disabled unless explicitly enabled."""

from __future__ import annotations

import os


RANKING_V2_FLAG = "OPTIONBEACON_OPPORTUNITY_RANKING_V2"


def ranking_v2_enabled(value=None):
    raw = os.getenv(RANKING_V2_FLAG, "false") if value is None else value
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def rank_opportunities_v2(opportunities, *, enabled=None):
    if not ranking_v2_enabled(enabled):
        return {"enabled": False, "production_ranking_preserved": True, "results": []}
    scored = []
    for item in opportunities:
        score = float(item.get("rule_score") or item.get("confidence") or 0)
        strengths, weaknesses = [], []
        for key, points, positive in (("regime_alignment", 8, "ALIGNED"), ("sector_alignment", 6, "ALIGNED"), ("data_quality", 5, "COMPLETE")):
            value = str(item.get(key) or "UNKNOWN").upper()
            if positive in value: score += points; strengths.append(f"{key.upper()}_{value}")
            elif value == "UNKNOWN": weaknesses.append(f"{key.upper()}_UNKNOWN")
            else: score -= points; weaknesses.append(f"{key.upper()}_{value}")
        rr = item.get("risk_reward")
        if rr is not None and float(rr) >= 2: score += 5; strengths.append("RISK_REWARD_AT_LEAST_2")
        action = str(item.get("status") or "WATCH").upper()
        scored.append({"opportunity_id": item.get("opportunity_id"), "ranking_score": round(score, 3),
                       "actionability_state": action, "top_strengths": strengths[:3], "top_weaknesses": weaknesses[:3],
                       "regime_alignment": item.get("regime_alignment", "UNKNOWN"), "sector_alignment": item.get("sector_alignment", "UNKNOWN"),
                       "historical_context": item.get("historical_context"), "data_quality_status": item.get("data_quality", "UNKNOWN")})
    scored.sort(key=lambda row: (-row["ranking_score"], str(row["opportunity_id"])))
    for rank, row in enumerate(scored, 1): row["overall_rank"] = rank
    return {"enabled": True, "production_ranking_preserved": False, "results": scored}


def side_by_side_ranking(production_ids, opportunities, *, enabled=None):
    shadow = rank_opportunities_v2(opportunities, enabled=enabled)
    return {"production_order": list(production_ids), "ranking_v2": shadow, "affects_production": False}
