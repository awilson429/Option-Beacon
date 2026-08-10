# Neon egress phase 2 audit

## Production evidence and ranking

Railway production logs on 2026-08-10 had query-egress diagnostics enabled. Ranking uses
`call_count * average_result_bytes`. Parameters, payloads, credentials, and SQL text are not logged.

| Rank | Fingerprint / old read | Caller and frequency | Production bytes / rows | Root cause and disposition |
|---:|---|---|---:|---|
| 1 | `b0572097fe58` | `process_scanner_result -> list_trade_outcomes -> list_opportunities`, once per each of ~74 symbols | 5,332,487 B / 5,000 each | Full, JSON-heavy history reconstructed per symbol. Fixed: one projected active snapshot per worker cycle and in-memory reuse. |
| 2 | `b0572097fe58` | `authoritative_trade_state`, every Streamlit rerun | 5,332,487 B / 5,000 | Wide `SELECT *`. Fixed at repository layer to ID plus lifecycle payload; historical UI still receives the same decoded records. |
| 3 | `b0572097fe58` | Trade Desk activity enrichment, every Trade Desk rerun | 5,332,487 B / 5,000 | Only six scalar fields for displayed event IDs were required. Fixed with exact-ID projection. |
| 4 | `5382bf9bff9a` | MIRROR CONTROL `rows()`, observed five times in one cycle | 109,277 B / 76 each | Full ledger repeatedly used for IDs, active positions, counts, and comparison. Fixed with projected ID/open/comparison queries and SQL counts. |
| 5 | `45fc6b780281` | entry/exit event summaries across PAPER, CONTROL and V2 | ~54–58 KB / 118 each; observed six calls | Identical event history reloaded by adjacent lanes. Fixed: one entry and one exit read shared per cycle. |
| 6 | `ad533262aeac` | PAPER `load()`, twice during position refresh and again in helpers | workload-dependent | Full historical position JSON filtered in Python. Fixed worker path to server-filtered OPEN/current-session rows and one in-memory refresh. |
| 7 | PAPER journal full-history query | Trade Desk, 5,000 rows each rerun | workload-dependent; JSON-heavy | Only open-position and selected-session decisions are required. Fixed with exact trade/source IDs and explicit projections. |
| 8 | `40363b1b771e` | PAPER captures, Trade Desk and Paper Trading | workload-dependent | Immutable capture JSON was loaded globally. Fixed Trade Desk to exact open/session IDs; Paper Trading is bounded to the selected history window. |
| 9 | `70a4c2252cac` and V2 full-ledger reads | V2 worker dispositions, open management, and comparison | currently small, unbounded growth | Fixed before growth: projected IDs/open rows and only missing/OPEN comparisons are refreshed. |
| 10 | `48e2c75441e2` | intraday worker `list_signals(limit=10000)` every cycle | workload-dependent | Historical signals downloaded to close active opportunities. Fixed with a two-column active-state predicate. |

Other bounded fingerprints seen in the sampled production window included `f6acae48ac12`
(9,440 B / 118 rows), `cea77ba85ed2` (roughly 0.35 KB / 19 rows), and zero-row
`2980a11c3cee`/`70a4c2252cac`. These were not material beside the top query.

The sampled log window contained 32 calls to `b0572097fe58`, transferring 170,639,584 bytes while
the scanner advanced through consecutive symbols. At 74 symbols, the same pattern is approximately
394.6 MB per cycle. At a five-minute cadence it is approximately 4.74 GB/hour or 113.7 GB/day.
This single defect is sufficient to explain terabyte-scale monthly public transfer.

After this change the hot path is one active-only `SELECT id,metadata_json` per cycle. Until a
post-deployment fingerprint is observed, the new result is conservatively budgeted below 250 KB,
for estimated savings above 394 MB per cycle and above 99.9% on this path.

## Read-path inventory

| Surface | Repository reads | Bounds/aggregation and execution |
|---|---|---|
| App bootstrap / Trade Desk | projected outcome payloads; latest health/lock; exact activity opportunities; 200 projected events; exact session events; full PAPER account positions; exact capture/journal provenance; CONTROL rows/runtime | Every rerun. Live state is not cached. Extended 500/1,000/5,000 event history now requires explicit opt-in. Session predicates execute in SQL before transfer. |
| Paper Trading | PAPER positions, bounded journal/captures/events; CONTROL rows and mark summaries; V2 rows/comparisons; runtime rows | Only when that destination renders. Default history reduced to 100. Marks remain server-aggregated per exact trade ID. |
| SPY/QQQ page | bounded signals/trades, runtime state, SQL performance aggregation | Page-only; live-sensitive and uncached. |
| Opportunities | scanner snapshot/file state; authoritative state already loaded at app bootstrap | No extra historical Neon analytics query. |
| History | projected authoritative outcome payloads already loaded; legacy journal/file reads | Page-only. Historical record set is unchanged. |
| After Hours | no Neon-specific historical query; Finnhub calls are unrelated to Neon egress | Page-only/provider cached by existing app behavior. |
| Developer Tools | health/runtime plus query-on-demand Winner DNA, selectivity, and Option Translation Autopsy | Analytics are genuinely deferred behind checkbox/button controls; collapsed state alone is not relied on. |
| Winner DNA | bounded snapshot/outcome projections; exact MIRROR rows and mark summaries; exact BROAD decisions | Explicit load, default 500. Server predicates and exact IDs. |
| Selectivity | bounded intelligence snapshots/outcomes | Explicit load, default 500. |
| Option Translation Autopsy | date-bounded snapshot/outcomes; exact MIRROR rows; bounded raw marks | Explicit button only. Raw telemetry is never a default UI read. |
| BROAD effectiveness | uses the already-loaded bounded Paper Trading data and mark summaries | No independent raw-mark download. |
| Authoritative worker | one active projected outcome snapshot; open/current state; shared projected events; SQL funnel counts | Every cycle. No per-symbol history read remains. |
| PAPER worker | server-filtered OPEN/current-session positions; projected disposition IDs; shared entry events | Every cycle. Historical closed positions are not reconstructed. |
| MIRROR CONTROL worker | projected disposition IDs; active rows; shared entries/exits; SQL counts | Every cycle. Full history remains available only to UI/explicit analytics. |
| MIRROR V2 worker | projected disposition IDs/open rows; pending comparisons; exact CONTROL projection; shared entries/exits | Every cycle when enabled. No raw marks are read. |
| Intraday worker | OPEN trades and active signal-state projection; runtime row | Every cycle. Former 10,000-row signal read removed. |
| Health/reliability | latest scanner health and one exact lock | Every relevant rerun/cycle; single-row live data, uncached. |
| Migration/CLI | exact import identity checks; explicitly invoked analytics may read bounded/raw history | Not scheduled. Remains operator-triggered and outside normal idle cost. |

## Budgets and caching decisions

- Normal Streamlit rerun target: below 250 KB; warn operationally above 500 KB.
- Idle research: zero historical analytics reads until explicit action.
- Authoritative/BROAD cycle: only active/current-session state, one shared event snapshot, and SQL counts.
- Intraday cycle: OPEN trades plus active signal states only.
- Research: explicit trigger, bounded row controls, and query-egress logging.

No TTL cache was added to live positions, marks, scanner health, runtime state, or locks. Historical
analytics were already action-gated; caching those results would add state complexity without
addressing the observed worker defect. In-render reuse and SQL predicates provide deterministic
freshness with greater savings.

## Railway follow-up query

After deployment, search Option-Beacon deploy logs for `database_read_result`. Export or count by
`query_fingerprint`, then calculate `count * average(approx_result_bytes)`. Confirm the old
`b0572097fe58` fingerprint is absent from per-symbol timing intervals and that no replacement query
exceeds 500 KB on a normal cycle. Search the SPY/QQQ service separately using the same event filter.

No schema, data, strategy, provider, contract, fill, exit, sizing, or capital change is part of this work.
