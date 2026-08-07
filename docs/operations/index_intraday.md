# INDEX INTRADAY experimental lane

INDEX INTRADAY is an additive, paper-only SPY/QQQ strategy. It does not import or
change the authoritative 74-symbol scoring, candidate lifecycle, BROAD PAPER, or
MIRROR execution paths. Railway is the sole writer; Streamlit reads the four
`intraday_*` tables only.

V1 detects three explainable families: VWAP reclaim/rejection, a 09:30–09:45 ET
opening-range break, and EMA 9/21 trend continuation confirmed on deterministic
5-minute bars. Three-minute bars are supported by the same session-aligned
1-minute aggregation helper but are not currently a rule input. Regime and session
bucket are persisted as analytics dimensions. SPY/QQQ agreement adds six confidence
points; disagreement removes four and never blocks a setup.

The durable lifecycle is OBSERVING → SETUP_DETECTED → ARMED → TRIGGERED →
PAPER_OPENED → MANAGED → CLOSED. One five-minute-bucketed opportunity ID follows
the signal throughout. Every selected 0DTE and 1DTE contract produces one Mirror
and one Managed one-contract shadow. Contract identity is immutable. Selection
prefers absolute delta 0.45–0.60 around 0.525, then near-the-money distance,
spread, volume, and open interest. Quotes wider than 35% or otherwise invalid are
rejected.

Both variants use `INTRADAY_CONSERVATIVE_QUARTER_SPREAD_V1`: entry is one quarter
of the half-spread above midpoint and exit one quarter below midpoint. Mirror exits
with the underlying lifecycle. Managed defaults are experimental: -20% hard stop,
+15% protection, +25% trailing activation, 10 percentage-point giveback, 45-minute
maximum hold, and 15:55 ET forced exit.

Run the lane as an independent worker with:

```text
python -m optionbeacon.worker.intraday --interval-seconds 60
```

Do not replace Railway's broad-worker start command. A separate service is needed.
One cycle uses two Finnhub candle calls plus up to six Tradier calls when both
symbols qualify. Start at 60 seconds and measure 429s/latency before considering
30 seconds. No production scheduling change is included.

Each cycle uses the dedicated `index-intraday-paper` lease and deterministically:

1. reloads every durable open Intraday Mirror and Managed position;
2. loads SPY and QQQ minute bars;
3. refreshes immutable option contracts and manages/closes each position independently;
4. evaluates SPY and QQQ for new setups and triggered entries;
5. persists `intraday_runtime_state`; and
6. releases the lease.

Mirror marks and excursions are refreshed every cycle. It closes on an opposing
underlying context or the 15:55 ET safety exit. Managed positions apply the exact
persisted experimental configuration. Missing/unusable quotes never manufacture a
mark or close; the trade remains open with `QUOTE_UNAVAILABLE` and is retried.

Operational events are `intraday_cycle_started`, `intraday_symbol_evaluated`,
`intraday_setup_detected`, `intraday_setup_armed`, `intraday_triggered`,
`intraday_paper_opened`, `intraday_position_updated`,
`intraday_profit_protection_armed`, `intraday_trailing_activated`,
`intraday_trade_closed`, `intraday_cycle_completed`, and
`intraday_cycle_failed`. Quote failures emit `intraday_position_update_failed`.

Replay is deterministic for underlying bars through `detect_candidate`; historical
option execution is intentionally not claimed because historical quote snapshots
are unavailable. Never synthesize historical option fills.
