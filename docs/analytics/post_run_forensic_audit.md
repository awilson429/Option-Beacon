# OptionBeacon Post-Run Forensic Audit

## Production result (2026-08-13)

The read-only production query was run for the explicit inclusive Eastern-date
window `2026-01-01` through `2026-08-13`.

Classification: **INSUFFICIENT / INCOMPLETE DATA**.

| Persisted source | Records |
| --- | ---: |
| Intelligence setup snapshots | 10 |
| Intelligence outcome labels | 1 |
| MIRROR execution trades | 0 (table absent) |
| MIRROR execution marks | 0 (table absent) |
| BROAD/PAPER trades joined to these identities | 0 |
| BROAD/PAPER decisions joined to these identities | 0 |

The snapshots cover an earliest/latest persisted timestamp of
`2026-07-30T14:00:00Z`. Nine snapshots lack outcomes. No complete session has
reliable authoritative plus MIRROR execution data, so the eligible translation
sample is `N=0`.

Consequently:

- Authoritative performance is insufficient (`N=1` completed outcome).
- MIRROR performance, translation matrix, MFE/MAE, option economics, entry
  latency, contract selection, BROAD selectivity, Winner DNA comparisons, and
  counterfactual validation are insufficient (`N=0`).
- There is no supported biggest observed leak and no defensible “what is
  working” subset.
- No behavior change or strategy experiment is recommended until the connected
  production database contains complete authoritative outcomes and the MIRROR
  trade/mark ledgers.

These are facts about the database available to the audit process, not findings
inferred from fixtures. Fixtures are used only for deterministic validation of
the analytics code.

## Running the report

```powershell
python -m analysis.run_post_run_forensic_audit --start 2026-01-01 --end 2026-08-13
```

Both dates are Eastern trading dates and the end is inclusive. The reader:

- uses a database-enforced read-only transaction;
- converts ET boundaries to a half-open UTC interval;
- applies explicit time and identity predicates before limits;
- projects named columns rather than full-width rows;
- joins only exact opportunity/trade identities;
- rolls back and closes the connection;
- makes no provider calls and does not reconstruct historical Greeks or IV;
- has no dependency on the Trade Desk history dropdown.

## Report contents

The JSON report includes integrity and coverage, the explicit session window,
authoritative and MIRROR performance, the exclusive translation matrix,
AUTH-WIN/MIRROR-LOSS detail, timing and contract groups, MFE/MAE and giveback,
capital economics, BROAD selectivity, Winner DNA, session/symbol/direction/setup/
regime groups, mark-ordered exit counterfactuals, explainable entry filters,
chronological validation, ranked failure modes, the biggest observed leak,
working subsets, next experiments, and missing fields worth persisting.

Every missing measurement remains unavailable rather than becoming zero.
Historical exit simulations are labeled `HISTORICAL COUNTERFACTUAL - NOT
PRODUCTION PERFORMANCE` and use only observed marks in timestamp order.

## Schema and production behavior

Schema impact: **none**.

Trading behavior impact: **none**. No scanner, score, threshold, setup,
authoritative lifecycle, BROAD/MIRROR participation, contract, sizing, risk,
exit, worker, provider, or UI behavior is modified.

Query/egress impact: on-demand CLI only; projected reads bounded by explicit
sessions, exact identities, `--trade-limit` (default 10,000), and `--mark-limit`
(default 250,000). No query is connected to normal scanner or dashboard cadence.

## Data to begin persisting

- Underlying price at the exact MIRROR fill timestamp.
- Historical option Greeks and IV at entry (never reconstructed later).
- Provider quote timestamp and component latency (signal, selection, quote,
  persistence/fill).
- Clearly flagged post-close option marks if post-close opportunity-cost research
  is desired.
