# Neon Public Network Transfer Audit

## Scope and evidence

Neon billing showed approximately 1,086 GB of public transfer versus 0.02 GB-month
of storage. This audit therefore preserves all telemetry and history and targets
database result sets returned to Railway/Streamlit. No provider, scanner, entry,
exit, risk, BROAD, MIRROR, or intraday behavior changes are included.

## Ranked read paths

| Severity | Path / function | Tables and query shape | Bound before | Filtering / aggregation | Rerun behavior |
|---|---|---|---|---|---|
| HIGH | `app.render_paper_trading_page` | `mirror_execution_marks SELECT * ORDER BY observed_at` | None | Entire table transferred; Python grouped | Every Paper Trading rerun, even collapsed |
| HIGH | `winner_dna_dashboard.render_winner_dna` | full MIRROR trades/marks, intelligence snapshots/outcomes, PAPER journal/trades | 5,000 except marks/trades unlimited | Exact joins and aggregation in Python | Every Developer Tools rerun, even collapsed |
| HIGH | `selectivity_dashboard.render_selectivity_analysis` | snapshot/outcome JSON rows | 5,000 | Analysis in Python | Every Developer Tools rerun |
| HIGH | Paper Trading comparison/funnel | full-width journal and authoritative event rows | 5,000 | Session filtering/grouping in Python | Every Paper Trading rerun |
| MEDIUM | Trade Desk comparison/activity | authoritative events, PAPER journal/captures, MIRROR trades | 200–5,000 | Mostly Python joins | Every Trade Desk rerun |
| MEDIUM | `MirrorExecutionRepository.rows` | `SELECT *` MIRROR trades, no limit | None | Caller filtering | Worker cycle and multiple UI pages |
| MEDIUM | `PaperExecutionRepository.records` | all contract JSON, no limit | None | Python deserialization | PAPER/Trade Desk reruns and worker handoff |
| MEDIUM | `run_mirror_pnl_attribution` CLI | `SELECT *` from configured audit tables | None | Offline Python audit | Manual only, not Streamlit |
| MEDIUM | authoritative worker handoff | up to 5,000 full events | 5,000 | Event-type filtering in Python | Worker cycles |
| LOW | scanner health/runtime/locks | single-row `SELECT *` by ID or latest + `LIMIT 1` | 1 | SQL | Frequent, negligible width |
| LOW | intraday signal/trade getters | ID/status predicates; UI lists have limits | one/bounded | SQL | Worker/UI |
| LOW | funnel latest-cycle/symbol reads | latest cycle `LIMIT 1`, symbols by cycle ID | one cycle | SQL | UI reruns |

Other repository reads were reviewed. Point lookups using primary keys, schema
introspection, counts, lock ownership, and `SELECT 1` diagnostics return negligible
payloads. Legacy local SQLite storage reads do not contribute Neon public egress.

## Implemented fixes

### MIRROR marks

The unbounded raw-mark read was replaced in Paper Trading and Winner DNA with
`mark_summaries(trade_ids, observed_after=None)`. PostgreSQL now receives an exact,
parameterized `IN` predicate and returns one row per relevant MIRROR trade using
`COUNT`, `MAX`, `MIN`, and `GROUP BY`. An optional `observed_at >= ?` bound supports
session-scoped callers. Telemetry writes and raw `marks(trade_id)` access for tests
or deliberate trade drilldown remain unchanged.

Transfer impact is **ESTIMATED >99% for this query** when each trade has hundreds
or thousands of marks: result cardinality changes from marks to trades. Exact byte
reduction is **UNKNOWN** until production diagnostics measure row sizes.

### Winner DNA

Winner DNA is now explicitly query-on-demand. Its default history limit is 500,
with 100/1,000/5,000 options. After loading bounded snapshots, it extracts exact
opportunity IDs and requests:

- projected MIRROR analytics columns with `WHERE opportunity_id IN (...) LIMIT ?`;
- one SQL-aggregated mark summary per opened trade;
- projected BROAD decision columns through an exact joined-ID query.

The previous full PAPER capture/journal and raw mark downloads were removed.
Collapsed/idle Developer Tools reruns return zero Winner DNA historical rows.

### Selectivity and Paper Trading

Selectivity is query-on-demand and defaults to 500 snapshot/outcome rows. Paper
Trading has a 100/500/1,000/5,000 history selector with 500 as the default instead
of an unconditional 5,000. Intelligence repository queries now project only ID,
JSON, schema version, and timestamp columns rather than `SELECT *`.

No time-based cache was added. Query-on-demand avoids historical reads entirely
while idle and cannot make live state stale. Live scanner health, positions, and
runtime state remain uncached.

## Diagnostics

Set `OPTIONBEACON_QUERY_EGRESS_DIAGNOSTICS=true` temporarily to emit structured
`database_read_result` events for multi-row repository reads. Events contain only
a query fingerprint, operation, row count, approximate result bytes, and duration.
Parameters, URLs, credentials, and result payloads are never logged. The feature
defaults off to avoid production log noise.

## Remaining transfer risks

- Trade Desk still reconstructs comparisons from bounded raw events and trades.
- Worker authoritative handoff reads up to 5,000 events and filters event types in Python.
- Manual `run_mirror_pnl_attribution` remains intentionally full-history.
- MIRROR trade ledgers and PAPER capture ledgers remain unbounded in several legacy callers.

These paths should be ranked with measured `database_read_result` bytes before
further refactoring because they share production worker semantics.

## Measuring Neon improvement

Enable diagnostics for a bounded observation window, record hourly approximate
bytes by query fingerprint, deploy, and compare the same Railway traffic period.
In Neon, compare hourly public network transfer before and after deployment using
equivalent market hours and Streamlit usage. Keep scanner cadence and traffic
constant. No Neon API key belongs in source; dashboard/API exports can be joined
offline by hour.
