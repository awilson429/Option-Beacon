# SPY/QQQ scalp and Options Desk audit

## Authoritative existing paths

| Concern | Current implementation | Finding |
|---|---|---|
| SPY/QQQ signal calculation | `intraday_strategy.py`, `optionbeacon_strategy.py`, `optionbeacon_signal.py` | The index-intraday detector is already parameterized for SPY and QQQ. The production OptionBeacon scanner remains separate and is not changed here. |
| Bias, score, trigger, stops, targets | `optionbeacon_strategy.py`, `optionbeacon_signal.py`, `trade_plan_engine.py`, `setup_stages.py` | Existing behavior is authoritative and remains untouched. Persisted opportunity/evidence data is the API source. |
| Contract selection | `tradier_options.py`, `option_trade_engine.py`, `intraday_execution.py` | Production selection and execution are not reused by scalp research. Research filtering is a pure function over supplied quotes. |
| Exit Score / Trade Coach | `exit_scoring.py`, `live_trade_coach.py`, `trade_plan_lifecycle.py` | Production management is unchanged. Scalp exits are isolated and may record existing exit state only as context. |
| Persistence | `trade_repository.py`, `paper_execution_repository.py`, `trade_storage.py` | Existing records are not altered. Scalp records use an explicit `SCALP_RESEARCH` strategy attribution and additive tables. |
| Regime and context | `market_regime.py`, `market_intelligence.py`, `opportunity_context.py` | Persisted regime/evidence is exposed read-only; cross-index agreement remains context, never a gate. |
| Confirmations / snapshots | `intelligence_capture.py`, `optionbeacon_snapshot.py`, `signal_history.py` | The API reads persisted snapshots. It does not call providers or write observations. |
| SPY/QQQ Streamlit desk | `app.py`, `featured_setup_card.py`, `trade_desk_compact.py` | Streamlit remains operational and unchanged. |
| QQQ command card | `qqq_command_card.py` | The rich model is QQQ-hard-coded in its queries, labels, contract helper names, FIRST_TWO experiment, and QQQ-only research metrics. Its generic fields overlap with the persisted API service, but its HTML/session presentation must not become a React dependency. |

## QQQ-only versus reusable

QQQ currently has the rich command-card session pulse, FIRST_TWO experiment, DNA/mark coverage, and QQQ-specific SQLite queries. Generic concepts include current price, direction, setup/trigger, contract identity, quote/spread, context quality, freshness, session outcome, and lifecycle state. The FastAPI aggregation exposes those generic persisted concepts independently by symbol. QQQ-only experiments remain clearly QQQ-only instead of being copied into SPY.

SPY and QQQ API reads are filtered independently. Cross-index state is descriptive context only. Missing values remain unavailable rather than being copied from the peer symbol.

## Live React update recommendation

Workers should continue persisting authoritative snapshots and scalp observations. FastAPI should serve inexpensive cached current-state projections (roughly 2–5 seconds during market hours) and separately cached performance aggregates (30–60 seconds). A later SSE channel can publish invalidation keys or version/timestamp events; React can then refetch only the affected symbol. Provider calls, signal calculation, and writes must stay outside request handlers.
