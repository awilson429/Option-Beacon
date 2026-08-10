"""On-demand, read-only Developer Tools UI for option translation attribution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from mirror_execution import MirrorExecutionRepository
from option_translation_autopsy import analyze_option_translation


def render_option_translation_autopsy(st, repository):
    with st.expander("OPTION TRANSLATION AUTOPSY", expanded=False):
        st.caption("Forensic persisted-data analysis only · exact identity joins · no provider calls or trading changes")
        if repository is None:
            st.warning("Authoritative persistence is unavailable.")
            return None
        lookback = st.selectbox("Autopsy lookback", (7, 30, 90), index=1, key="option_autopsy_lookback_days")
        row_limit = st.selectbox("Autopsy trade limit", (100, 500, 1000), index=1, key="option_autopsy_limit")
        if not st.button("Run Option Translation Autopsy", key="run_option_translation_autopsy"):
            st.caption("Heavy marks and analytics queries run only after this action.")
            return None
        start_at = datetime.now(timezone.utc) - timedelta(days=int(lookback))
        snapshots = repository.list_intelligence_snapshots(limit=row_limit, start_at=start_at)
        outcomes = repository.list_intelligence_outcomes(limit=row_limit, start_at=start_at)
        opportunity_ids = ({str((row.get("snapshot") or row).get("opportunity_id")) for row in snapshots
                            if (row.get("snapshot") or row).get("opportunity_id")} |
                           {str((row.get("outcome") or row).get("opportunity_id")) for row in outcomes
                            if (row.get("outcome") or row).get("opportunity_id")})
        try:
            mirror_repository = MirrorExecutionRepository(repository, initialize=False)
            mirrors = mirror_repository.analytics_rows(opportunity_ids, limit=row_limit)
            marks = mirror_repository.analytics_marks(
                (row.get("mirror_trade_id") for row in mirrors), observed_after=start_at,
                limit=max(1000, int(row_limit) * 100),
            )
        except Exception as error:
            st.warning(f"Persisted MIRROR analytics data is unavailable: {type(error).__name__}")
            mirrors, marks = [], []
        report = analyze_option_translation(snapshots, outcomes, mirrors, marks)
        sample = report["sample"]
        if sample["preliminary"]:
            st.warning(f'PRELIMINARY: only {sample["eligible"]} eligible trades; at least 20 are required for validation labels.')
        if sample["concentration_warning"]:
            st.warning("Concentration: one symbol exceeds 30% of eligible trades.")
        st.caption(f'Eligible {sample["eligible"]} · excluded {sample["excluded"]} · sessions {sample["sessions"]} · symbols {sample["symbols"]} · CALL/PUT {sample["call_count"]}/{sample["put_count"]}')
        _table(st, "A. Translation Scorecard", report["outcome_matrix"])
        _table(st, "B. AUTH WIN / MIRROR LOSS", [_autopsy_row(row) for row in report["auth_win_mirror_loss"]])
        _table(st, "C. Entry Timing", [report["entry_timing"]] + [_timing_row(row) for row in report["rows"]])
        _table(st, "D. Exit Efficiency", report["exit_efficiency"])
        _table(st, "E. Underlying Magnitude", report["magnitude"])
        _table(st, "F. Spread / Fill Friction", report["spread"])
        _table(st, "G. Contract Characteristics", report["dte"] + report["moneyness"] + report["contract"])
        _table(st, "H. Capital Efficiency", [report["capital"]] + report["capital_comparisons"])
        _table(st, "I. Entry Feature Attribution", report["feature_attribution"])
        _table(st, "J. Selective MIRROR What-If", report["selective_what_if"])
        _table(st, "K. Exit What-If", report["exit_what_if"])
        _table(st, "L. Data Coverage", [{"Metric": key, "Value": value} for key, value in report["coverage"].items()] +
               [{"Metric": f"Excluded: {key}", "Value": value} for key, value in report["excluded"].items()])
        st.caption("Timing snapshots use the nearest persisted mark within ±45 seconds; missing points remain unavailable and are never interpolated. Delta and IV are not reconstructed.")
        return report


def _table(st, title, rows):
    st.markdown(f"#### {title}")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _autopsy_row(row):
    keys = ("opportunity_id", "symbol", "direction", "setup", "auth_entry", "auth_exit", "auth_return",
            "contract", "expiration", "strike", "option_type", "dte", "entry_bid", "entry_ask", "entry_mid",
            "entry_fill", "spread_dollars", "spread_percent", "debit", "exit_fill", "mirror_return", "mirror_pnl",
            "mfe", "mae", "peak_return", "peak_pnl", "time_to_peak_minutes", "peak_to_exit_minutes", "giveback",
            "ever_profitable", "profitable_then_loser", "hold_minutes", "exit_reason", "telemetry_coverage",
            "failure_mode", "causal_confidence")
    return {key: row.get(key) for key in keys}


def _timing_row(row):
    return {"opportunity_id": row["opportunity_id"], "outcome": row["outcome"],
            **{f"+{minute}m": row.get(f"return_{minute}m") for minute in (1, 2, 3, 5, 10, 15, 30)}}
