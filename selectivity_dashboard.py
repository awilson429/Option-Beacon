"""Read-only Developer Tools presentation for shadow selectivity analytics."""

from __future__ import annotations

import math

import pandas as pd

from selectivity_analysis import analyze_selectivity, feature_bins


def render_selectivity_analysis(st, repository):
    st.markdown("### Selectivity Analysis · Shadow Only")
    st.caption(
        "Descriptive analysis of immutable entry snapshots. It cannot change production entries, ranking, or exits."
    )
    if repository is None:
        st.warning("Authoritative intelligence storage is unavailable.")
        return None
    history_limit = st.selectbox(
        "Selectivity history limit", (100, 500, 1000, 5000), index=1,
        key="selectivity_history_limit",
    )
    if not st.checkbox("Load Selectivity analytics", value=False, key="load_selectivity_analytics"):
        st.caption("Query-on-demand: no historical intelligence rows are loaded while this analysis is idle.")
        return None
    report = analyze_selectivity(
        repository.list_intelligence_snapshots(limit=history_limit),
        repository.list_intelligence_outcomes(limit=history_limit),
    )
    overview = report["overview"]
    columns = st.columns(5)
    columns[0].metric("Completed Trades", overview["trade_count"])
    columns[1].metric("Baseline Win Rate", _percent(overview["win_rate"]))
    columns[2].metric("Baseline Avg Return", _percent(overview["average_return"], signed=True))
    columns[3].metric("Eligible Analysis", len(report["rows"]))
    columns[4].metric("Sample Confidence", report["sample_confidence"])
    if overview["trade_count"] < 20:
        st.warning("Exploratory only: fewer than 20 completed trades are available.")
    else:
        st.info(
            f"Chronological validation: {report['training_count']} older training trades · "
            f"{report['validation_count']} newer validation trades."
        )

    st.markdown("#### Tier Comparison · Newer Validation Trades")
    tier_rows = [{
        "Tier": row["tier"], "Trades": row["trade_count"],
        "% Retained": _percent(row["percent_retained"]),
        "Win Rate": _percent(row["win_rate"]),
        "Avg Return": _percent(row["average_return"], signed=True),
        "Expectancy": _percent(row["expectancy"], signed=True),
        "Avg MFE": _percent(row["average_mfe"], signed=True),
        "Avg MAE": _percent(row["average_mae"], signed=True),
        "Trade Reduction": _percent(row["trade_reduction"]),
        "Win-rate Lift": _points(row["win_rate_lift"]),
    } for row in report["tiers"]]
    st.dataframe(pd.DataFrame(tier_rows), use_container_width=True, hide_index=True)

    effects = report["model"]["factor_effects"]
    positive = sorted(
        ((name, values) for name, values in effects.items() if values["effect"] > 0),
        key=lambda item: item[1]["effect"], reverse=True,
    )
    negative = sorted(
        ((name, values) for name, values in effects.items() if values["effect"] < 0),
        key=lambda item: item[1]["effect"],
    )
    factor_columns = st.columns(2)
    with factor_columns[0]:
        st.markdown("#### Top Positive Factors")
        _factor_table(st, positive)
    with factor_columns[1]:
        st.markdown("#### Top Negative Factors")
        _factor_table(st, negative)

    st.markdown("#### Entry vs Exit Diagnosis")
    diagnosis_rows = [
        {"Classification": name, "Trades": count}
        for name, count in sorted(report["diagnoses"].items())
    ]
    st.dataframe(pd.DataFrame(diagnosis_rows), use_container_width=True, hide_index=True)

    with st.expander("Feature bins and trade review", expanded=False):
        st.caption("Bins below five trades are explicitly marked unreliable.")
        st.dataframe(
            pd.DataFrame(feature_bins(report["rows"], "rule_score", (0, 80, 85, 90, 95, 101))),
            use_container_width=True, hide_index=True,
        )
        review = [{
            "Time": row["entry_timestamp"], "Symbol": row["symbol"],
            "Setup": row["setup"], "Direction": row["direction"],
            "Rule Score": row["rule_score"], "Quality Score": row["selectivity_score"],
            "Tier": row["selectivity_tier"], "Market Regime": row["market_regime"],
            "Sector Alignment": row["sector_alignment"],
            "Realized Return": row["realized_return"], "MFE": row["mfe"],
            "MAE": row["mae"], "Exit Reason": row["exit_reason"],
            "Diagnosis": row["diagnosis"],
        } for row in report["rows"]]
        st.dataframe(pd.DataFrame(review), use_container_width=True, hide_index=True)
    return report


def _factor_table(st, factors):
    if not factors:
        st.caption("Insufficient repeated entry features.")
        return
    st.dataframe(pd.DataFrame([{
        "Factor": name, "Observed Return Difference": _percent(values["effect"], signed=True),
        "Sample": values["sample_size"],
    } for name, values in factors[:5]]), use_container_width=True, hide_index=True)


def _percent(value, signed=False):
    if value is None: return "—"
    if math.isinf(value): return "∞"
    return f"{value:+.2f}%" if signed else f"{value:.1f}%"


def _points(value):
    return f"{value:+.1f} pts" if value is not None else "—"
