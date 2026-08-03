# Live Trade Activity

Live Trade Activity is a read-only visual projection of OptionBeacon's
authoritative opportunity and trade lifecycle. It does not create, enter,
close, or score trades.

## Source of truth

Lifecycle transitions continue through `process_scanner_result` and
`sync_trade_outcome`. After the authoritative opportunity/trade row is written,
an immutable event is appended to `authoritative_trade_events`. Every event has
a deterministic deduplication key derived from trade ID, event type, timestamp,
and material marker. Reprocessing a scanner result or restarting the worker
therefore cannot duplicate either a trade or its material event.

The stream includes WATCH creation/update, entry-ready, entered, position
updates, targets, stops, exit signals, closed trades, EOD exits, maximum-hold
exits, and invalidations. Existing scorecards and journals continue to read the
same authoritative trade outcomes.

## Trade Desk behavior

- A new entry or closure remains prominent for five minutes based on its
  persisted event timestamp.
- A trade that enters and closes between page views remains visible in Live
  Activity, Recently Closed, and the scorecard.
- Active positions are explicitly labeled ACTIVE and include entered time with
  seconds, age, entry/current values, return, stop, target, and coach state.
- Live Activity shows up to 20 meaningful events newest first. ENTRY and EXIT
  use explicit labels in addition to semantic color treatment.
- Recently Closed shows today's latest 10 authoritative trades. Full history
  remains available through Opened Alerts and Journal.

The normal application rerun remains at 60 seconds. A Streamlit fragment polls
only `authoritative_trade_events` every 10 seconds. It does not invoke
`scan_symbols`, provider requests, or the worker, so scanner cadence and market
data load are unchanged. Active-price freshness remains bounded by the
authoritative worker cadence.

## Production verification

1. Deploy the branch and confirm startup creates
   `authoritative_trade_events` and its timestamp index in Neon.
2. Open Trade Desk and verify Live Activity loads without provider requests or
   duplicate trade rows.
3. Allow a qualified watch to appear; confirm WATCH and READY events show an ET
   timestamp including seconds.
4. Trigger an entry in the normal authoritative lifecycle. Confirm NEW ENTRY,
   ACTIVE position status, and ENTER on the tape. Reload the page and confirm
   the notification remains until five minutes after the persisted entry time.
5. Allow one target/stop closure. Confirm the winner/loser card, EXIT tape row,
   Recently Closed row, journal entry, and scorecard all share the same trade ID
   and count exactly one trade.
6. Verify a rapid entry/exit by waiting to open or refresh Trade Desk until
   after closure; both events and the closed result must still be visible.
7. Exercise an EOD exit and confirm the neutral `EOD EXIT` label and unchanged
   EOD lifecycle result.
8. Restart the worker and reload the page. Confirm prior events remain and no
   duplicates are added.
9. Observe logs/provider metrics for several 10-second fragment refreshes and
   confirm no scanner or market-data request cadence increase.
