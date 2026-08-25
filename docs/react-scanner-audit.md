# React Scanner migration audit

Date: 2026-08-24
Branch: `web/react-scanner`

## Scope and conclusion

The React Scanner must be a read-only projection of existing worker persistence. It must not load the legacy `latest_results.json`, invoke `generate_signal`, contact Yahoo Finance/Finnhub/Tradier, or reproduce eligibility logic in TypeScript. The durable sources that can safely support the page are `scanner_health`, `opportunities`, `authoritative_trade_events`, and `capital_decisions`. Values that only exist in a process-local scan result or legacy file snapshot must remain explicitly unavailable.

## 1. Scanner entry points

- `optionbeacon.worker.run:main` is the production recurring worker entry point. It validates `OPTIONBEACON_SCAN_SECONDS` (default 300 seconds, bounded to 30–3600), creates one durable repository, and repeatedly invokes `run_scan_once` with failure backoff.
- `optionbeacon.worker.scan_once:run_scan_once` is the production single-cycle entry point.
- `optionbeacon_live:generate_signal` is the per-symbol market-data/scoring pipeline used by the worker. It calculates indicators and scores, enriches the trade plan and option liquidity, timestamps the result, and writes legacy/local observations.
- `scheduled_scan:main` is a legacy scheduled entry point that scans only while the market is open and writes local snapshot/history files. It is not the production read model for the React API.
- Streamlit also reads `optionbeacon_snapshot.load_latest_results`; this may fall back to a remote GitHub snapshot. The new FastAPI endpoint must not inherit that network behavior.

## 2. Worker and scan lifecycle

The production cycle acquires a lease in `scanner_locks`, starts a row in `scanner_health`, loads the configured universe plus symbols with open authoritative trades, scans serially, records bounded progress, persists eligible opportunity lifecycle changes, writes the legacy snapshot, runs the authoritative-entry funnel, hands accepted entries to paper/capital simulation, runs isolated MIRROR/control experiments, and finalizes health as `AVAILABLE`, `PARTIAL`, `UNAVAILABLE`, or `ERROR`.

`scanner_health` records start/completion/success/error times, symbol counts, result/failure counts, progress, code version, market-data state, and active owner. `trade_state_service.scanner_health_state` is the canonical interpretation of `SCANNING`, `CURRENT`, `STALE`, `ERROR`, or `WAITING`; an apparently scanning row is only active when its owner/lease/progress are still valid.

The recurring worker waits the configured interval after a cycle. Therefore an expected next scan can only be derived as `last_completed_at + configured interval`; it is not a persisted scheduler commitment. The API should label the interval as configured/expected and may return no next time while actively scanning or when no completion exists.

## 3. SPY and QQQ scan path

`SPY` and `QQQ` are the first two `DEFAULT_ETF_SYMBOLS` in `finnhub_universe.py`. They travel through the same universe, data, scoring, persistence, and worker lifecycle as every other symbol; there is no separate React-safe scanner implementation. Open-trade symbols are appended to the universe to preserve lifecycle updates. The Scanner UI can spotlight SPY and QQQ by filtering the canonical persisted opportunity stream without changing the scan universe or strategy.

## 4. Signal and opportunity models

- A transient scanner result contains the richest current read: price, bullish/bearish scores, confidence, signal/setup stage, timing, reasons, indicator values, trade plan, option liquidity, timestamps, and provider-derived context.
- `signal_history.scanner_result_to_trade_outcome` converts only eligible directional results with a usable trade plan into a deterministic candidate. Invalid, extended, non-directional, and no-entry results are intentionally not canonical opportunities.
- `opportunities` is the durable opportunity record: symbol, direction, playbook, signal timestamp, state, confidence, entry/stop/three targets, evidence JSON, metadata JSON, and source version.
- The authoritative lifecycle is embedded as `metadata.trade_outcome` and mirrored by `authoritative_trades` / `authoritative_trade_events` for entered and closed events.
- `intelligence_setup_snapshots` and `opportunity_context` are additive research/analysis records. They are not needed for the minimum operational Scanner contract and must not be treated as strategy authority.

## 5. Persistence inventory

### Scanner observations

- Durable operational state: `scanner_health` and `scanner_locks`.
- Durable eligible setup snapshots: `opportunities`, plus intelligence/context tables.
- Legacy/display snapshots: `latest_results.json`, `signal_history.jsonl`, and related local/remote history files. These contain richer per-symbol reads but are not a reliable database-backed API source.
- Scalp research has its own `scalp_research_observations` table and remains isolated SHADOW research for the Options Desk.

### Accepted/rejected signals and opportunities

- An eligible setup becomes an `opportunities` row in state `CANDIDATE`; later authoritative lifecycle transitions are persisted in the embedded outcome and trade/event tables.
- Non-eligible transient scanner reads are not canonically persisted as rejected opportunities. The Scanner must not invent them from absence.
- The authoritative funnel emits durable trade events for meaningful accepted lifecycle transitions. Broad paper-execution acceptance/rejection also exists in `paper_execution_journal`, but the minimum Scanner lane read can use the normalized capital decisions described below.

### OB/BROAD decisions

`capital_decisions` is the canonical independent lane-decision ledger. It stores lane, opportunity ID, symbol, direction, decision state, reason code, explanation, proposed contract/quantity/capital/risk, drawdown state, timestamp, and optional hypothetical outcome. `paper_execution.run_paper_execution` records both BROAD and OB decisions for each handed-off authoritative entry. A BROAD failure can result in a truthful OB `INDEPENDENT_OPTION_LIFECYCLE_UNAVAILABLE` rejection; the API must preserve, not reinterpret, that reason.

### Provider and data status

The worker persists only the aggregate `scanner_health.market_data_state` and symbol result/failure counts. The provider-cycle name/request/cache/rate-limit summary is logged but not persisted. The API therefore cannot truthfully report a live provider connection or per-symbol provider error; it should return `not_queried` for the API/provider relationship and use persisted market-data state/freshness separately.

## 6. Existing Streamlit presentation

`app.py` renders:

- a grouped two-column scanner from transient `latest_results`;
- freshness and service-configuration health cards;
- top bullish/bearish opportunity cards;
- a “Today’s Best Trade” view with an intentional no-qualifying-setup state and a derived developing setup;
- paper, capital, MIRROR, filtered, and forensic views in separate advanced sections.

Streamlit presentation helpers such as `ui_polish.scanner_summary` derive labels including `ENTERABLE`, `WAIT`, and `EXTENDED` from transient timing fields. Those labels are display logic, not durable lane decisions. React should use persisted opportunity state and persisted capital decisions instead of porting this derivation.

## 7. Existing FastAPI support

- `OptionBeaconReadService` already provides read-only database access, market-calendar state, system health, SPY/QQQ option-desk projections, active/recent trades, and capital accounts/decisions.
- `ReadOnlyTradeRepository` suppresses schema DDL and opens PostgreSQL transactions with `SET TRANSACTION READ ONLY`, then rolls back.
- `/api/system/status` already exposes market, database, coarse freshness, worker, and provider-not-queried status.
- `/api/trade-desk`, `/api/trades/*`, and `/api/capital*` contain reusable projections but do not assemble per-opportunity lane decisions or normalized scanner activity.

The minimum addition is one aggregate `GET /api/scanner` endpoint with explicit Pydantic models. It can reuse the same repository reads and market-calendar logic while returning section-level status so one optional read failure does not make the entire workstation unusable.

## 8. Missing fields for a useful Scanner page

The current durable model does not canonically retain every scan of SPY/QQQ. Specifically missing are:

- current non-actionable SPY/QQQ price and signal when no eligible opportunity exists;
- bullish and bearish component scores;
- most raw indicator/context values from the latest candle;
- transient rejection reasons for results that never became opportunities;
- a persisted provider-cycle summary/name/status;
- an exact scheduled next-run timestamp;
- an explicit per-opportunity data-quality/freshness classification.

For this phase, the API will return nullable fields and explicit `unavailable`/`stale` states. Persisting a canonical per-symbol scan observation is the appropriate later backend improvement; reading legacy files or calling providers in the API would create split authority.

## 9. Authority map

| Information | Authority | API treatment |
| --- | --- | --- |
| Market open/closed | NYSE calendar at request time | Derived session state, labeled as such |
| Worker/scan health | `scanner_health` interpreted by `scanner_health_state` | Authoritative operational status |
| Expected interval/next scan | worker configuration plus last completion | Derived expectation, nullable |
| SPY/QQQ current eligible setup | newest persisted `opportunities` row | Authoritative persisted state |
| Entry/stop/targets/confidence | persisted opportunity columns | Expose directly, nullable |
| Last persisted underlying / rule score | latest matching authoritative trade event | Expose with freshness context, nullable; never call it a live quote |
| Score | persisted opportunity confidence or explicit metadata score only | Never synthesize from other fields |
| Contract | persisted opportunity metadata or latest matching capital decision | Expose when present |
| OB/BROAD disposition | newest matching `capital_decisions` row per lane | Authoritative lane decision |
| Recent activity | normalized opportunities, capital decisions, and trade events | Derived ordering/labels over durable records |
| Fresh/stale/unavailable | timestamp age plus scan health | Derived display classification |
| Provider connection | not persisted and API makes no provider call | `not_queried` / unavailable |
| Transient indicator values and rejected reads | legacy/in-memory only | Null/unavailable |

## 10. MIRROR inventory and boundary

MIRROR and MIRROR V2 are invoked after the authoritative/paper handoff in `run_scan_once` and persist separate experiment/runtime/disposition data. Streamlit contains extensive MIRROR experiment and forensic panels. The existing React Trade Desk maps MIRROR/control trades to a demoted `RESEARCH_CONTROL` role.

The Scanner aggregate will expose only `research_control_role: RESEARCH_CONTROL_ONLY` as a boundary statement. MIRROR will not appear in the OB/BROAD lane array, will not receive capital metrics, and will not be presented as an actionable or live lane. No MIRROR strategy, execution, persistence, or Streamlit code should change in this phase.

## Implementation guardrails from this audit

1. Keep the endpoint strictly read-only and provider-free.
2. Use `scanner_health_state` instead of inventing a second health interpretation.
3. Use `opportunities` as the persisted SPY/QQQ and current-opportunity source.
4. Join lane decisions by exact `opportunity_id`; never fuzzy-match symbols/times.
5. Return exactly OB and BROAD as capital lanes.
6. Preserve nulls and explicit unavailable states for noncanonical values.
7. Isolate optional section read failures in the response.
8. Leave all worker, strategy, execution, provider, MIRROR, and Streamlit behavior unchanged.
