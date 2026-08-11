"""Read-only Developer Tools presentation for Winner DNA analytics."""

from __future__ import annotations

import pandas as pd

from mirror_execution import MirrorExecutionRepository
from paper_execution_repository import PaperExecutionRepository
from winner_dna import analyze_winner_dna


def render_winner_dna(st, repository):
    with st.expander("WINNER DNA / ENTRY ATTRIBUTION", expanded=False):
        st.caption("Research-only attribution from immutable entry snapshots · no provider calls · no production tuning")
        if repository is None:
            st.warning("Authoritative intelligence storage is unavailable.")
            return None
        history_limit = st.selectbox(
            "Winner DNA history limit", (100, 500, 1000, 5000), index=1,
            key="winner_dna_history_limit",
        )
        if not st.button("Load Winner DNA analytics", key="load_winner_dna"):
            st.caption("Analytics are query-on-demand to avoid transferring historical rows on unrelated reruns.")
            return None
        snapshots = repository.list_intelligence_snapshots(limit=history_limit)
        outcomes = repository.list_intelligence_outcomes(limit=history_limit)
        opportunity_ids = {
            str((wrapped.get("snapshot") or wrapped).get("opportunity_id"))
            for wrapped in snapshots if (wrapped.get("snapshot") or wrapped).get("opportunity_id")
        }
        mirrors, marks, journal = [], [], []
        try:
            mirror_repository = MirrorExecutionRepository(repository, initialize=False)
            mirrors = mirror_repository.analytics_rows(opportunity_ids, limit=history_limit)
            marks = mirror_repository.mark_summaries(
                row.get("mirror_trade_id") for row in mirrors if row.get("opened_at")
            )
        except Exception:
            pass
        try:
            paper_repository = PaperExecutionRepository(repository, initialize=False)
            journal = paper_repository.analytics_decisions(opportunity_ids, limit=history_limit)
        except Exception:
            pass
        report = analyze_winner_dna(
            snapshots, outcomes,
            mirror_rows=mirrors, mirror_marks=marks,
            broad_journal=journal, broad_captures=(),
        )
        coverage = report["coverage"]
        st.markdown("#### Data Coverage")
        st.dataframe(pd.DataFrame([{"Feature": name, "Coverage %": value,
                                    "Status": report["feature_status"].get(name, "PERSISTED / JOINED")}
                                   for name, value in sorted(coverage.items())]),
                     use_container_width=True, hide_index=True)
        large = report["thresholds"]["large_winner_positive_75th_percentile"]
        st.caption(
            f'Flat/noise: ±{report["thresholds"]["flat_noise_absolute_pct"]:.2f}% · '
            f'Large winner: upper quartile of positive returns ({large:.3f}% in this sample)'
            if large is not None else "No positive outcomes are available for a large-winner threshold."
        )
        insight_rows = [value for value in (
            ({"Insight": "Strongest supported factor", "Value": f'{report["insights"]["strongest_factor"]["feature"]} · {report["insights"]["strongest_factor"]["bin"]}',
              "N": report["insights"]["strongest_factor"]["n"]} if report["insights"]["strongest_factor"] else None),
            ({"Insight": "Weakest supported factor", "Value": f'{report["insights"]["weakest_factor"]["feature"]} · {report["insights"]["weakest_factor"]["bin"]}',
              "N": report["insights"]["weakest_factor"]["n"]} if report["insights"]["weakest_factor"] else None),
            ({"Insight": "Weakest supported session", "Value": report["insights"]["weakest_session"]["group"],
              "N": report["insights"]["weakest_session"]["n"]} if report["insights"]["weakest_session"] else None),
        ) if value]
        if insight_rows:
            st.markdown("#### Supported Insights")
            st.dataframe(pd.DataFrame(insight_rows), use_container_width=True, hide_index=True)

        st.markdown("#### A. Outcome Distribution")
        st.dataframe(pd.DataFrame(_summary_rows(report["outcome_distribution"])), use_container_width=True, hide_index=True)
        st.markdown("#### B. Large Winner DNA")
        dna = [{"Outcome": group["group"], "N": group["n"],
                "Avg Confidence": _avg(group["rows"], "confidence"),
                "Median Confidence": _median(group["rows"], "confidence"),
                "Avg Volume Ratio": _avg(group["rows"], "relative_volume"),
                "Median Volume Ratio": _median(group["rows"], "relative_volume"),
                "Avg VWAP Distance": _avg(group["rows"], "vwap_distance"),
                "Avg RSI": _avg(group["rows"], "rsi"),
                "Morning %": _rate(group["rows"], lambda row: row.get("session_bucket") == "MORNING")}
               for group in report["large_winner_dna"]]
        st.dataframe(pd.DataFrame(dna), use_container_width=True, hide_index=True)

        st.markdown("#### C. Feature Effects")
        st.dataframe(pd.DataFrame([{"Feature": row["feature"], "Bin": row["bin"],
                                   **_summary_row(row)} for row in report["feature_effects"]]),
                     use_container_width=True, hide_index=True)
        st.markdown("#### D. Auth Win / MIRROR Loss")
        st.dataframe(pd.DataFrame([{"Group": row["group"], **_summary_row(row),
                                   "Avg Confidence": row["average_confidence"],
                                   "Avg Volume Ratio": row["average_volume_ratio"],
                                   "Avg ATR": row["average_atr"], "Avg Hold Minutes": row["average_hold_minutes"],
                                   "Avg MIRROR Spread %": row["average_mirror_spread_percent"],
                                   "Avg MIRROR DTE": row["average_mirror_dte"]}
                                  for row in report["option_translation"]]), use_container_width=True, hide_index=True)

        st.markdown("#### E. Multi-Factor Patterns")
        st.dataframe(pd.DataFrame([{"Pattern": row["pattern"], "N": row["n"],
                                   "Train N": row["train_n"], "Train Expectancy": row["train"]["expectancy"],
                                   "Validation N": row["validation_n"], "Validation Expectancy": row["validation"]["expectancy"],
                                   "Sessions": row["sessions"], "Symbols": row["symbols"],
                                   "CALL / PUT": f'{row["call_count"]} / {row["put_count"]}',
                                   "Stability": row["stability"]} for row in report["patterns"]]),
                     use_container_width=True, hide_index=True)

        st.markdown("#### F. Session / Regime")
        st.dataframe(pd.DataFrame(_summary_rows(report["session_effects"])), use_container_width=True, hide_index=True)
        st.dataframe(pd.DataFrame(_summary_rows(report["regime_effects"])), use_container_width=True, hide_index=True)
        st.markdown("#### G. Symbol Dependence")
        if report["symbol_concentration_warning"]:
            st.warning(f'One symbol represents {report["symbol_concentration"]:.1f}% of eligible trades; apparent effects may not generalize.')
        st.dataframe(pd.DataFrame(_summary_rows(report["symbol_effects"])), use_container_width=True, hide_index=True)
        st.dataframe(pd.DataFrame(_summary_rows(report["sector_effects"])), use_container_width=True, hide_index=True)
        st.dataframe(pd.DataFrame(_summary_rows(report["direction_effects"])), use_container_width=True, hide_index=True)
        return report


def _summary_row(row):
    return {"N": row["n"], "Win Rate %": row["win_rate"],
            "Avg Auth Return %": row["average_return"], "Median Auth Return %": row["median_return"],
            "Expectancy": row["expectancy"], "Profit Factor": row["profit_factor"],
            "Large Winner Rate %": row.get("large_winner_rate"),
            "MIRROR Win Rate %": row.get("mirror_win_rate"), "MIRROR Net P&L": row.get("mirror_net_pnl"),
            "Avg Debit": row.get("average_debit"), "Peak Capital": row.get("peak_capital")}


def _summary_rows(groups):
    return [{"Group": row["group"], **_summary_row(row)} for row in groups]


def _avg(rows, key):
    values = [row.get(key) for row in rows if row.get(key) is not None]
    return sum(values) / len(values) if values else None


def _median(rows, key):
    values = sorted(row.get(key) for row in rows if row.get(key) is not None)
    if not values:
        return None
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def _rate(rows, predicate):
    return sum(predicate(row) for row in rows) / len(rows) * 100 if rows else None
