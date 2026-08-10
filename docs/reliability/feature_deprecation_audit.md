# OptionBeacon feature deprecation audit

This audit is conservative. Historical rows, migration paths, production workers, and calculation
modules were not deleted. Classification is based on current imports, navigation, write paths, and
table ownership on `origin/main` at the start of the MIRROR V2 work.

## Navigation and feature classification

| Surface | Purpose and dependencies | Classification | Cost observation |
|---|---|---|---|
| Trade Desk | Primary operational state, reconciliation, positions, activity, and journal | KEEP | Core Neon reads; operationally necessary |
| SPY / QQQ | Separate intraday worker state and strategy ledger | KEEP | Distinct execution lane and tables |
| Opportunities | Ranked current candidates and full scanner | KEEP, possibly Trade Desk subsection later | Scanner snapshot work; no duplicate provider call beyond cached UI scan |
| Paper Trading | BROAD, MIRROR CONTROL, V2 shadow, and exact comparison | KEEP | Required experiment operations; bounded SQL reads |
| After Hours | Earnings/news and next-session focus | CONSOLIDATE under Opportunities/Research later | Unique Finnhub requests; hiding alone does not save cost if rendered elsewhere |
| History | Signal outcomes, coach history, and legacy journal inspection | KEEP; rename Trades & History later | Historical data access is unique |
| Tools | Scanner health only | CONSOLIDATE into Developer Tools / Advanced Diagnostics | Removes one top-level destination; material compute savings only if diagnostics become lazy |
| Developer Tools | Provider verification, scanner/funnel diagnostics, and research analytics | CONSOLIDATE into Strategy Lab plus Advanced Diagnostics | Currently performs many research queries on every page render |

The current app already co-locates Winner DNA, Option Translation Autopsy, selectivity analytics,
and the authoritative funnel inside Developer Tools. Their calculation modules remain separate and
should stay that way. The next UI phase should split that single long render into lazy subsections:

- Strategy Lab: MIRROR CONTROL vs V2, Winner DNA, BROAD effectiveness, Option Translation Autopsy,
  and selectivity.
- Advanced Diagnostics: scanner, funnel, provider, repository/build, reliability, and egress health.

The Paper Trading history row selector and the Trade Desk 200/500/1000/5000 event-history selector
are diagnostic data-volume controls, not primary trading decisions. Move them into an Advanced Data
Window expander. Session reconciliation is independently queried, so this does not weaken financial
session accuracy.

## PAPER profiles

- `BROAD`: actively creatable through `PAPER_SIMULATION_PROFILE=BROAD`; KEEP.
- `SAFE`: actively creatable and still the code default; KEEP as an execution compatibility mode,
  but hide from routine production UI when the persisted worker profile is BROAD.
- `LEGACY_UNLABELED`: not creatable as a configured execution profile. It is a read-time label for
  pre-profile journal history; HIDE from normal operations but preserve in History/Advanced.
- Labels such as `LEGACY PAPER` and `UNKNOWN PROVENANCE`: reconciliation-only historical categories,
  not execution modes; preserve for auditability.

Changing the default from SAFE or deleting SAFE is not safe in this phase because environment
fallback behavior and tests explicitly depend on it.

## Code-path classification

KEEP: worker entry points, authoritative repository/state services, PAPER execution, MIRROR CONTROL,
intraday execution, provider adapters, migration/import compatibility, trade reconciliation, and all
analytics calculation modules.

CONSOLIDATE at the UI level: Winner DNA, BROAD effectiveness, Option Translation Autopsy, selectivity,
and MIRROR comparison under Strategy Lab; diagnostics under Advanced Diagnostics. Internal modules
should remain separate.

HIDE/DEPRECATE from primary navigation: Tools as a separate destination, incident-specific funnel and
repository diagnostics, raw event-window controls, and legacy PAPER profile rows. No worker imports
these UI render paths.

SAFE-TO-REMOVE candidates after a dedicated proof PR: none identified with enough evidence for
immediate deletion. Several large legacy Trade Desk render functions in `app.py` appear superseded,
but tests and internal fallbacks still reference presentation helpers around them. They are Phase 2
candidates only.

UNKNOWN: filesystem JSON ledgers and `positions`/`recommendations` SQL tables in `trade_storage.py`.
They are still imported by app trade-journal functions and may carry user-managed history. Preserve
until production usage and row counts are measured. Experiment-generation scripts and committed
analysis artifacts are offline tools, not runtime dead code.

## Application-owned table inventory

| Tables | Classification |
|---|---|
| `opportunities`, `authoritative_trades`, `authoritative_trade_events` | ACTIVE WRITE / ACTIVE READ |
| `scanner_health`, `scanner_locks` | ACTIVE WRITE / ACTIVE READ |
| `intelligence_setup_snapshots`, `intelligence_outcome_labels`, `intelligence_shadow_events` | ACTIVE WRITE / ACTIVE READ analytics |
| `paper_execution_positions`, `paper_execution_trades`, `paper_execution_journal`, `paper_execution_runtime_state` | ACTIVE WRITE / ACTIVE READ |
| `mirror_execution_trades`, `mirror_execution_journal`, `mirror_execution_runtime_state`, `mirror_execution_marks` | ACTIVE WRITE / ACTIVE READ |
| `mirror_v2_shadow_trades`, `mirror_v2_shadow_marks`, `mirror_v2_shadow_runtime_state`, `mirror_v2_shadow_comparisons` | ACTIVE WRITE / ACTIVE READ when V2 enabled |
| `intraday_signals`, `intraday_paper_trades`, `intraday_paper_journal`, `intraday_runtime_state` | ACTIVE WRITE / ACTIVE READ by SPY/QQQ service |
| `authoritative_entry_funnel_cycles`, `authoritative_entry_funnel_symbols` | ACTIVE WRITE diagnostics / ACTIVE READ |
| `legacy_imports` | HISTORICAL READ ONLY except explicit import operations |
| `positions`, `recommendations` | UNKNOWN; legacy/user journal compatibility, do not drop |

All schema creation is additive and idempotent. No table is an evidence-backed drop candidate today.

## Cost and Phase 2

Merely hiding navigation reduces clutter but not Railway worker or provider cost. The meaningful
savings would come from lazy-loading Strategy Lab/Advanced sections: fewer broad analytics queries,
raw-event transfers, dataframe construction, and Streamlit rerun work. Moving After Hours without
changing when it fetches data produces no provider savings. Removing test/offline modules produces
maintenance savings only.

Phase 2 should: introduce a seven-destination grouped information architecture; lazy-load research
and diagnostics; move history-limit controls into Advanced; measure production table/query usage;
then remove proven-unreferenced legacy Trade Desk renderers and file-ledger compatibility in separate,
reversible changes.

Target structure:

- Operations: Trade Desk, Opportunities, SPY / QQQ, Paper Trading.
- Research: Strategy Lab.
- History: Trades & History, Legacy PAPER inspection.
- Advanced: Diagnostics and provider/scanner/repository health.
