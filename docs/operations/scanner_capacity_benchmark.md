# Scanner Capacity Benchmark

OptionBeacon records one `scanner_capacity_metrics` row and one concise
`scanner_capacity_summary` log event for every completed scan. The feature is
observational: without benchmark environment variables, symbol selection,
scoring, ranking, persistence, and trade lifecycle behavior are unchanged.

## Measurements and health bands

Each row captures the configured, attempted, successful, failed, and skipped
symbol counts; requests, cache hits, retries, 429s and provider warnings;
duration and utilization; per-symbol average/p50/p95/maximum time; repository
write time; WATCH, WAIT, OPEN, actionable and total opportunities; overlap,
schedule delay, partial status, and opportunity density. Detailed symbol timing
is stored in metadata only when
`OPTIONBEACON_VERBOSE_CAPACITY_DIAGNOSTICS=true` (default: false).

Utilization is `scan duration / configured interval * 100`. HEALTHY is below
50% with no provider degradation; CAUTION is 50–75% or has emerging provider
failures; SATURATED is 75–100% or materially degraded; OVERLOADED is 100% or
more, overlaps, or severe persistent provider failure. The existing scanner
lock prevents conflicting scans; a rejected invocation is recorded as an
overlap with its intended start and schedule delay.

Opportunity density is visible opportunities divided by successfully processed
symbols. A low density may make a larger universe poor value; a high density
dominated by WATCH/WAIT rows may create a dashboard usability bottleneck even
when worker timing is healthy.

## Testing universe sizes

Set `OPTIONBEACON_BENCHMARK_SYMBOL_LIMIT` to `8`, `15`, `25`, `40`, `60`, or
`100`, then restart the worker. The scanner takes the first N symbols in the
existing ordered universe and logs the included list. Unset the variable to
restore the normal production universe. Never change the base production
universe merely to run this benchmark.

Observe at least 10 scans per size (20 is preferred across varying market
conditions). Developer Tools shows the current scan, recent aggregate, and
universe comparison. A recommendation appears only after at least 10 scans for
a size; it selects the largest observed size whose p95 remains under 60 seconds,
success is at least 90%, and aggregate health is HEALTHY or CAUTION.

## Diagnosing the bottleneck

- Provider: rising 429 percentage, retries, failures, or partial scans.
- Worker: high per-symbol times and utilization without provider errors.
- Database: repository-write time grows disproportionately.
- UI/usability: opportunity density and WATCH/WAIT volume grow faster than
  actionable opportunities.

Monday procedure: begin with `8`, restart, and observe 10–20 scans. Repeat in
order for `15`, `25`, `40`, and `60`, restarting after each environment change.
Do not proceed upward when p95 reaches the interval, overlaps occur, provider
failure persists, or dashboard volume is operationally excessive. Export or
capture the Developer Tools comparison after each cohort, then unset the limit
and restart to return to unchanged production selection.
