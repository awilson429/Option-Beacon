"""Compact, explicitly requested Developer Tools view for QQQ forward research."""
from datetime import datetime, timezone
from collections import Counter
from statistics import median

from intraday_execution import IntradayRepository
from qqq_forward_research import compare_first_two

RESULT_KEY="qqq_forward_experiment_result"


def mark_coverage(rows, marks):
    counts={row["source_trade_id"]:0 for row in rows}
    for mark in marks:
        if mark.get("trade_id") in counts: counts[mark["trade_id"]]+=1
    values=list(counts.values())
    ordered=sorted(marks,key=lambda row:(str(row.get("observed_at")),str(row.get("trade_id"))))
    return {"eligible_positions":len(rows),"eligible_open_qqq_positions":sum(not row.get("closed_at") for row in rows),
        "positions_with_1_or_more_marks":sum(v>=1 for v in values),
        "positions_with_5_or_more_marks":sum(v>=5 for v in values),
        "average_marks_per_trade":sum(values)/len(values) if values else None,
        "median_marks_per_trade":median(values) if values else None,
        "marks_per_session":dict(Counter(str(mark.get("eastern_session")) for mark in marks)),
        "missing_mark_trades":[identity for identity,count in counts.items() if not count],
        "earliest_mark":ordered[0].get("observed_at") if ordered else None,
        "latest_mark":ordered[-1].get("observed_at") if ordered else None,
        "by_variant":{variant:sum(mark.get("variant")==variant for mark in marks) for variant in ("INTRADAY_MIRROR","INTRADAY_MANAGED")}}


def render_qqq_forward_research(st, repository, *, now=None):
    with st.expander("QQQ FORWARD EXPERIMENT",expanded=False):
        st.caption("Research only · baseline trading remains unchanged · current Eastern session excluded")
        clicked=st.button("Load QQQ Forward Experiment",key="load_qqq_forward_experiment")
        result=st.session_state.get(RESULT_KEY)
        if clicked and repository:
            try:
                snapshot=IntradayRepository(repository,initialize=False).qqq_research_snapshot()
                experiment=snapshot.get("experiment")
                if experiment:
                    comparison=compare_first_two(snapshot["rows"],experiment_start_timestamp=experiment["experiment_start_timestamp"],now=now or datetime.now(timezone.utc))
                    result={"comparison":comparison,"mark_coverage":mark_coverage(snapshot["rows"],snapshot["marks"]),"experiment":experiment}
                else: result={"status":"NOT_STARTED","reason":"Experiment begins with the first post-deployment QQQ baseline trade."}
                st.session_state[RESULT_KEY]=result
            except Exception: st.error("QQQ research analytics are temporarily unavailable; trading is unaffected."); return None
        if result:
            st.json(result)
        return result
