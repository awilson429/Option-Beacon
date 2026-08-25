# React Active Trades audit

Date: 2026-08-24
Branch: `web/react-active-trades`

## Scope and invariant

This audit covers the read path needed for a first-class React Active Trades page. The React application remains presentation-only, FastAPI remains a read-only boundary, and the existing Python workers and repositories remain authoritative for lifecycle, execution, marks, risk, management, and provider access.

## Persisted sources

1. **Authoritative open trades.** `TradeRepository.list_open_trades()` reads `authoritative_trades` rows whose status is `OPEN`. Each row has an exact trade ID and opportunity ID, entry/open timestamps, underlying entry and last price, stop, up to three targets, lifecycle status, and JSON metadata. `opportunities` supplies symbol, direction, playbook/setup, signal timestamp, entry/stop/targets, evidence, and metadata.
2. **Existing active-trade repository methods.** `list_open_trades()`, `list_recent_trades()`, `get_trade()`, `open_trade()`, `update_trade()`, and `close_trade()` own the authoritative lifecycle. The FastAPI adapter currently enriches open rows only with symbol, direction, and setup from the exact opportunity ID.
3. **Paper-execution lifecycle.** `paper_execution_trades` captures the selected option contract and source signal; `paper_execution_positions` persists the option position, underlying entry/latest underlying, option entry/current mark, quantity, unrealized P&L/return, excursions, timestamps, and status. `CapitalRepository.sync_paper_positions()` projects accepted lane decisions into `capital_positions` separately for OB and BROAD.
4. **Lane-capital projection.** `capital_positions` is the canonical display source for exact lane ownership, contract, realistic option entry, current option premium, quantity, committed capital, initial dollar risk, unrealized P&L, stop, targets, open/mark timestamps, and status. `capital_decisions` persists proposed account-risk percentage and provides an exact `(lane, opportunity_id)` join. Only OB and BROAD are deployable simulated-capital lanes.
5. **Live-trade / Trade Coach state.** The Streamlit-era `trade_storage.positions` and `trade_storage.recommendations` tables persist manually managed positions and coach recommendations. They use a local/manual numeric position ID and do not persist a canonical authoritative trade ID or opportunity ID. Joining them to `authoritative_trades` or `capital_positions` by symbol, timestamp, or contract would be ambiguous, so this read API must not do that.
6. **Exit Score.** Exit Score, canonical label/action, suggested stop, and recommendation timestamp exist in the legacy recommendations table. They are not canonically attributable to the active authoritative/capital records. They may be returned only when the exact active trade metadata already persists those values; otherwise the API must return `null` with management data status `unavailable`.
7. **Marks and premiums.** `paper_execution_positions` stores the richer raw mark projection; `capital_positions.current_premium`, `unrealized_pnl`, and `last_mark_at` are the canonical lane-specific presentation values. The active API can classify a persisted mark with the same 15-minute freshness window already used by FastAPI system/scanner projections. No provider call is required.
8. **Stops and targets.** `authoritative_trades` stores `stop_price` and `target_1` through `target_3`. `capital_positions` stores lane stop and JSON targets, although current capital synchronization can persist an empty target list. The read projection can use an exact opportunity join to the authoritative plan when the lane projection does not contain those values.
9. **Time in trade.** The existing FastAPI capital projection calculates elapsed seconds as the difference between the current read time (or close time) and persisted `opened_at`. The Active Trades projection can reuse the same calculation; this is read-time presentation and does not alter lifecycle state.
10. **Contract identity.** Exact option symbol, option type, strike, expiration, DTE, and quantity are available in `paper_execution_positions`; `capital_positions` persists all except option type. Option type can be sourced only from exact persisted metadata or conservatively normalized from the authoritative direction when it is explicitly CALL/PUT. The API must not parse or guess an OCC contract.
11. **OB/BROAD attribution.** `capital_positions.lane` is exact and canonical. An authoritative lifecycle row with no matching capital projection is the OptionBeacon authoritative position and is presented as OB. A capital position is included only when its lane is exactly OB or BROAD. The read layer does not infer BROAD from symbols or timing.
12. **MIRROR/control state.** MIRROR has separate research/control persistence and paper comparison paths. It is not a deployable capital lane. MIRROR/control rows are excluded from the primary Active Trades response and are neither deleted nor rewritten.
13. **Streamlit presentation.** `paper_trading_page.open_paper_position_rows()` and the Trade Desk sections in `app.py` display open paper contracts, entry/current premium, P&L, return, time, and risk/account context. Other Streamlit sections compute and render Trade Coach output. Those functions remain unchanged; React will consume the persisted projection instead of importing Streamlit or executing its logic.
14. **Existing FastAPI endpoint.** `GET /api/trades/active` currently returns the base `TradeResponse` list from `authoritative_trades`, enriched by opportunity identity. It is the correct endpoint to enrich additively. It is read-only and uses no providers.

## Additive projection design

The enriched endpoint should keep every existing base field and add flat, nullable operational fields for lane identity, contract, entry, current mark/P&L, plan, risk, freshness, and management. It should:

- project each open OB/BROAD `capital_positions` row as a first-class lane position;
- exact-join its opportunity and authoritative lifecycle rows;
- suppress the duplicate authoritative OB row when an OB capital position already represents it;
- retain an unmatched authoritative open trade as an OB authoritative row;
- exact-join the latest persisted TAKE decision for account-risk percentage;
- never include MIRROR/control positions in the primary list;
- return localized `unavailable`/`stale` status instead of failing because an optional mark or management field is absent.

## Canonical gaps

The following requested fields are not consistently or canonically persisted for exact active-trade identity today:

- maximum-hold / timeout;
- breakeven state;
- current risk after management changes;
- Exit Score and canonical recommendation for the authoritative/capital trade identity;
- Trade Coach status;
- thesis status;
- momentum state;
- VWAP/EMA structure state;
- target-progress state;
- stop-management state;
- last management update;
- DTE on current `capital_positions` rows (the schema exists but synchronization currently writes `null`);
- option type as a dedicated `capital_positions` column;
- lane targets when the capital synchronizer stores an empty list.

The API will expose nullable fields for these gaps and may pass through exact values already present in persisted authoritative/capital metadata. It will not calculate, threshold, or reconstruct management recommendations. A future worker/persistence change should introduce a canonical management snapshot keyed by lane, trade ID, and opportunity ID before React displays richer coaching state.
