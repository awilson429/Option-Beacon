# Canonical live snapshot API

`GET /api/live/snapshot` is the versioned, read-only bootstrap contract for the React migration. It returns the latest already-persisted OptionBeacon state immediately; it does not wait for a scan or make state current.

## Source of truth and safety

The Python worker and repositories remain authoritative. The snapshot composes existing read projections only:

| Snapshot section | Authoritative source |
| --- | --- |
| `market` | Persisted scanner timestamps/health plus the configured NYSE session calendar |
| `symbols.SPY`, `symbols.QQQ` | Latest canonical provenance observation already attached by the scanner projection and persisted opportunity state |
| `scanner` | Persisted scan health, provenance cycle, and processed-symbol coverage |
| `decisions` | Persisted OB/BROAD lane decisions attached to bounded current opportunities |
| `active_trades` | Existing active-trade projection, including persisted management snapshots and marks where available |
| `recent_trades` | Most recent 20 authoritative stored trades |
| `system` | Existing database, worker, freshness, coverage, and provenance-health projections |
| `provenance` | Canonical observation availability/count metadata |

The request does not initiate a scan, call a market-data provider, evaluate indicators or strategy, score candidates, create or close trades, or write persistence. `provider_status` remains `not_queried` by design.

## Contract

The top-level `schema_version` is `"1"`. It versions the HTTP snapshot contract only and has no relationship to strategy, scoring, or execution versions. `snapshot_id` is a deterministic digest of persisted cycle, observation, decision, active-position, and recent-trade identities/timestamps; repeated reads of unchanged authoritative state retain the same ID even though `generated_at` advances.

The response contains:

- `generated_at` and aggregate `data_status`.
- Market session date/state, latest authoritative data timestamp, and freshness.
- Explicit SPY and QQQ objects, even when no observation exists.
- Scanner cycle identity/completion, bounded processed-symbol coverage, and health.
- At most 20 current OB/BROAD decisions.
- Current active trades and at most 20 recent completed/authoritative trades.
- Database/worker health, per-symbol coverage, provenance status, and stale/missing labels.

## Null and unavailable semantics

Missing values remain `null`; they are never converted to numeric zero. Each symbol and health section carries an explicit status. Valid `0` values remain `0`.

The serialization boundary converts `datetime`, `date`, `Decimal`, pandas timestamp-compatible values, NumPy-style scalar values, and enums to strict JSON. `NaN`, positive infinity, and negative infinity become `null`, preventing invalid JSON numeric output.

## React diagnostics

The temporary internal page is `/diagnostics/live-snapshot`. It polls the snapshot every 15 seconds through the shared typed client and displays connection state, SPY/QQQ coverage, the latest scanner cycle, decisions, active/recent trade counts, and stale/missing health. It is a contract-validation view, not the production trading terminal.

The client contract is `LiveSnapshot` in `frontend/src/lib/types.ts`; `api.liveSnapshot()` and `useLiveSnapshot()` are the direct client and SWR hook.

## Performance shape

The snapshot reuses four bounded service projections: scanner, active trades, 20 recent trades, and system status. It does not load an unbounded trade history. The scanner projection currently performs its established bounded opportunity, decision, event, health, and canonical-observation reads. A future optimization should introduce a repository-level snapshot/read transaction only after production timing identifies a need; duplicating query logic here would risk semantic drift.
