# OptionBeacon React/FastAPI whole-product audit

**Audit date:** 2026-08-25

**Baseline:** merged `main` at `6861bf6`

**Audit branch:** `audit/react-whole-product`

**Scope:** evidence-only review; no runtime, strategy, execution, persistence, provider, risk, or Streamlit behavior changed

## Executive conclusion

OptionBeacon now has a coherent five-workspace React read surface over a well-separated, read-only FastAPI boundary. The product can explain current persisted participation, SPY/QQQ setups, scanner health and eligible opportunities, exact OB/BROAD active positions, and canonical completed-trade history without executing strategy or provider work in a web request. Exact `(trade_id, lane)` management joins, independent OB/BROAD capital ledgers, explicit unavailable states, and demotion of MIRROR/control are strong foundations.

The migration is not functionally complete as an entire operating product. React is sufficient as the default **monitoring and review interface**, but not as the only interface for a complete operating day. It has no alert center, pre-market readiness view, incident/data-health workflow, manual intervention workflow, or research/diagnostic replacement. Streamlit still owns the legacy saved-trade controls (manual premium updates, stop application, partial flags, and close/outcome capture), the distinct intraday SPY/QQQ workspace, paper/MIRROR experiment operations, research analyses, and advanced diagnostics. Whether the manual tracker is needed on a given day depends on whether the user relies exclusively on the worker-owned capital positions or also manages those legacy saved positions.

The largest product weakness is not visual inconsistency; it is the absence of an explicit end-to-end workflow that links scanner observation → opportunity → lane decision → exact position → management → outcome and makes failures actionable. The largest trading-system weakness is incomplete canonical evidence: non-eligible scan observations and their rejection/progression context are lost, while OB/BROAD management snapshots record state only at safe position synchronization boundaries and often cannot contain canonically evaluated Trade Coach/Exit Score conclusions. This prevents a complete explanation of why an opportunity was ignored and, for many trades, why the system stayed in or exited.

The single highest-value next engineering task is a **canonical decision-provenance ledger** for SPY/QQQ that records bounded, decision-relevant scanner observations and connects them by stable identities to eligible opportunities, OB/BROAD decisions, positions, management snapshots, and outcomes. It must be observational and must not alter scoring, eligibility, execution, or exits. That task improves correctness, scanner usefulness, Journal learning, forensic reconstruction, and readiness evidence at once.

React may become the default URL now for routine monitoring, but Streamlit must remain available as an explicitly labeled Research / Operations console until the daily-operation blockers in this audit are either migrated or deliberately retired. Controlled real-money testing is **not ready**: the repository deliberately has no brokerage execution, current lane evidence is below documented validation thresholds, the option lifecycle is still coupled to BROAD, authentication/remote API controls are absent, automated alerting is incomplete, and disaster recovery has not been proven by a restore drill.

## 1. Baseline and system boundary

The audit began by fast-forwarding `main` to `6861bf6` and confirming these merged systems:

- FastAPI read boundary under `api/`, with explicit Pydantic response models and a read-only repository transaction;
- React routes `/`, `/options`, `/scanner`, `/active-trades`, and `/journal`;
- independent simulated-capital state and decision ledgers for OB and BROAD;
- canonical `trade_management_snapshots` with exact identity, material-state deduplication, latest/batch/history reads, and Active Trades / Journal projections;
- the existing Python worker, strategy, execution, risk, provider, research, and Streamlit systems unchanged.

The intended authority split is sound:

| Layer | Responsibility | Boundary assessment |
| --- | --- | --- |
| React / Next.js | Presentation, filters, local selection, request refresh | Correctly read-only; no strategy/provider execution |
| FastAPI | Typed read models and status semantics | Correctly read-only; some projections repeat broad in-memory aggregation |
| Python services/workers | Strategy, scan, execution, management, allocation, risk | Correct authority owner |
| Repositories/PostgreSQL | Durable opportunity, trade, event, capital, execution, snapshot truth | Strong identity model; incomplete observation coverage |
| Streamlit | Legacy production UI, research, diagnostics, manual saved-position tools | Still active; must be separated from the primary-product narrative |

The repository README still describes only the Phase 2 Trade Desk and Options Desk and says Streamlit is the production UI. That migration copy is stale relative to the five merged routes and should be corrected in a later documentation-only task.

## 2. Product architecture map

### React route and data matrix

| Route | Purpose / primary user question | FastAPI reads | Python authority | Polling | Loading / empty / error / stale behavior |
| --- | --- | --- | --- | --- | --- |
| `/` Trade Desk | Session command center: “What is participating, how is today going, and is the system healthy?” | `/api/trade-desk`, `/api/trades/active`, `/api/trades/recent?limit=12`, `/api/system/status` | `OptionBeaconReadService.trade_desk_home`, active capital/authoritative trades, recent authoritative events, lane capital state/decisions, scanner health | 10s home; 5s active; 15s recent; 15s system | Section skeletons; intentional no-active/activity states; failures isolated per section; no page-level stale banner, only system status values |
| `/options` Options Desk | “What are the current persisted SPY/QQQ plans and what does isolated scalp research show?” | Per symbol `/api/options-desk/{symbol}`, `/api/scalp/{symbol}`, `/api/scalp/{symbol}/performance`; `/api/scalp/compare` | Persisted `opportunities`; isolated `scalp_research_observations`; Python analytics | 10s strategy; 5s scalp; 60s performance/compare | Per-instrument skeletons and request isolation; unavailable values remain unavailable; research lifecycle has empty/insufficient evidence states; freshness is mostly timestamps/status rather than one canonical page snapshot |
| `/scanner` Scanner | “What did the persisted worker see in SPY/QQQ, which opportunities exist, and what did each capital lane decide?” | `/api/scanner` | `scanner_health`/`scanner_locks`, `opportunities`, `capital_decisions`, authoritative event summaries | 15s | Page skeleton; intentional no-qualifying-setup; section-level partial/error semantics; prominent stale warning; provider status truthfully `not_queried` |
| `/active-trades` Active Trades | “What exact OB/BROAD positions are open, at what risk/plan/mark, and what is their latest management state?” | `/api/trades/active`, `/api/system/status` | `capital_positions`, authoritative trades, opportunities, capital decisions, paper marks, latest exact management snapshot | 5s positions; 15s system | Position skeletons; intentional empty; page section failure isolated from system; mark-level stale/unavailable callouts; last-mark timestamp |
| `/journal` Journal | “What happened in completed OB/BROAD trades, and what canonical management history exists?” | `/api/trades/history?...`; on selection `/api/trades/{trade_id}/management?lane=...` | lane-owned `capital_positions` joined to opportunities, authoritative trades, paper execution records, exact management summaries/history | 45s history; selected timeline on demand/focus disabled | Summary/history skeletons; filtered empty; retry state; missing legacy/canonical fields explicitly listed; timeline independently errors/unavailable; no stale classification for historical data |

All five pages also mount `AppShell`, which polls `/api/system/status` every 15 seconds. SWR deduplicates equal keys within a mounted tree, but each route is a separate page lifecycle.

### Responsibilities duplicated across pages

1. Trade Desk and Active Trades both show open positions, P&L, lanes, and system status. The home version is a summary but does not link to the detailed position.
2. Trade Desk and Scanner both show recent activity and OB/BROAD capital decisions.
3. Options Desk and Scanner both describe current SPY/QQQ direction/setup state, but with different contracts and freshness semantics.
4. Trade Desk, Active Trades, Scanner, and the shell each display health/freshness concepts using different timestamps and scopes.
5. Trade Desk and Journal both show session/historical P&L, while Journal uses realistic lane capital P&L and Trade Desk mixes recent authoritative records with active projections. The scopes are labeled but remain easy to conflate.

The duplication is acceptable only if each summary becomes a navigable handoff. Today it often repeats information without offering a direct transition.

### Important responsibilities with no React home

- pre-market readiness checklist: worker lease, last successful scan, provider-cycle quality, database recency, risk entry locks, and configuration mode;
- alerts/incidents: stale worker, DB unavailable, provider failure, position mark failure, rejected/failed execution, risk-state transition, recovery status;
- exact opportunity-to-position-to-journal navigation and identity search;
- manual operations and acknowledgements, if they are intended to remain part of the product;
- research experiment operations, diagnostics, backups/restore status, and configuration inspection;
- an explicit session close/reconciliation view.

### Architecture verdict

The five-workspace architecture makes sense as one trading product: Home → Options/Scanner → Active Trades → Journal is a credible lifecycle. It currently behaves more like five strong read models than one guided workflow. Keep the routes; improve transitions and canonical context before considering route consolidation.

## 3. Full-session workflow

| Session stage | Expected React destination | Needed information | Present / authoritative? | Duplication and transition finding |
| --- | --- | --- | --- | --- |
| Before market | Trade Desk, then Scanner | previous worker success, next expected run, DB/provider/data status, lane risk locks, available cash, scheduled mode | Partial. DB/worker/freshness and accounts exist; provider is intentionally not queried; risk locks require separate unused API; no checklist | No direct Data Health page. Shell can label market closed but cannot distinguish ready-for-open from merely reachable |
| Market open | Trade Desk | session open, fresh worker, capital availability, incidents | Partial and mostly authoritative | Market open is calendar-derived; no transition/alert acknowledgement or “first fresh cycle complete” gate |
| Scanning | Scanner | active lease/progress, last cycle, symbols/failures, SPY/QQQ current observations | Health is authoritative; current SPY/QQQ only if an eligible opportunity persists | Scanner has the best operational state, but non-eligible observations disappear and provider detail is unavailable |
| Opportunity | Scanner / Options Desk | setup, progression, score/confidence, plan, freshness, data quality | Partial. Eligible opportunity plan is persisted; transient components/progression/rejections are not | Two pages show setup state; no canonical deep link or stable opportunity detail route |
| Capital decision | Scanner, summarized on Trade Desk | independent OB/BROAD TAKE/REJECT, reason, size/risk/capital, contract | Yes for handed-off eligible opportunities | Strong ledger. No link from a decision to its later exact position or its rejected hypothetical outcome |
| Entry | Active Trades | exact lane position, contract, fill, intended plan, execution quality | Mostly yes for capital positions; fallback authoritative trades have less contract/mark data | No notification/event transition; Trade Desk summary is not linked to the position card |
| Active management | Active Trades | mark age, P&L/risk, stop/targets, progression, thesis/momentum, coach/exit state/reason | Partial. Exact latest snapshots are safe; OB/BROAD coach/Exit Score may be null because they are not canonically evaluated at that boundary | Read-only is appropriate for automated execution. No incident/action path when data or management is unavailable |
| Exit | Active Trades → Journal | exit event/reason/fill, realized result, final management context | Available after durable closure, with explicit missing fields | No toast/alert or direct “review closed trade” handoff; 45s Journal poll can lag a just-closed position |
| Journal/review | Journal | exact outcome, lane economics, plan, timeline, MFE/MAE, attribution, comparisons | Strong per-trade basics; weak analytical learning views | Filters stop at lane/symbol/result/date. No grouped setup/time/direction/exit analysis or opportunity provenance view |

### Dead ends and missing transitions

- No setup/opportunity detail has a stable React URL.
- No Scanner card links to a capital decision, Active Trade, or Journal row by identity.
- No Active Trade links back to its opportunity or forward to its completed Journal record.
- No Trade Desk summary card links to the detailed workspace.
- A stale/failed state tells the user what is unavailable but not where to diagnose it.
- “Soon” navigation items imply a roadmap but provide no current operational alternative.
- Session close has no explicit reconciliation or “all positions closed / risk reset / worker state” confirmation.

### Can one operate without Streamlit?

**No, not for the full repository-defined workflow.** React can monitor the automated worker/capital path and review completed canonical trades. Streamlit remains required for the legacy saved-trade workflow (manual mark, stop, partial, close/outcome operations), the distinct intraday SPY/QQQ workspace, paper/MIRROR experiment operations, and operational/research diagnostics. If “daily operation” is narrowly defined as watching an entirely automated worker with no manual interventions, React is adequate for normal-state monitoring but still lacks actionable incident diagnostics and alerts.

## 4. Information architecture and UX findings

### Severity-ranked findings

| Severity | Finding | Evidence / impact |
| --- | --- | --- |
| **CRITICAL** | None found in the read-only UI itself | The audit found no fuzzy OB/BROAD identity join, provider call in the API, strategy reconstruction in React, or route-level data cross-contamination |
| **HIGH** | Freshness is not a product-wide contract | `/options` requests seven independently timed resources; Home uses four; shell, Scanner, active marks, and Journal use different clocks/thresholds. A user can see mutually current-looking values from different snapshots |
| **HIGH** | Scanner cannot show “nothing qualified” with the reason the current SPY/QQQ read failed to qualify | Non-eligible observations, component scores, transient rejection reasons, and progression are not canonically persisted. Empty is truthful but low-information |
| **HIGH** | Active management cannot always explain stay/exit decisions | OB/BROAD snapshot integration has exact identity but does not run/fabricate Trade Coach or Exit Score; those fields can remain null |
| **HIGH** | No actionable incident/data-health workspace | Stale and error states are visible, but no React page provides provider/worker/funnel/repository diagnostics or alert history |
| **HIGH** | React has no explicit workflow transitions | Repeated summaries are not deep links; opportunity, lane decision, position, management, and outcome identities are not navigable as one chain |
| **MEDIUM** | P&L scopes are easy to conflate | Home session values, active unrealized values, authoritative recent results, capital realistic P&L, and Journal lane economics have different bases; labels do not always name the basis |
| **MEDIUM** | Lane terminology varies | `OB`, `AUTHORITATIVE`, “Authoritative lane”; `BROAD`, `PAPER`, “Paper participation lane”; `MIRROR / CONTROL RESEARCH`, `RESEARCH_CONTROL`, `CONTROL_RESEARCH`, `SHADOW` all appear |
| **MEDIUM** | Timestamp conventions vary | Shared formatter shows ET time only; Journal shows full date/time/timezone; Scanner uses a compact timestamp; “as of,” “last mark,” “observed,” and “last success” have different meanings |
| **MEDIUM** | The shell can imply certainty during status loading/failure | AppShell’s market display defaults to `CLOSED` when system state is absent, rather than “unavailable/connecting” |
| **MEDIUM** | Mobile drawer lacks modal behavior | At 390×844 focus remained on the obscured “Open navigation” button after opening; body overflow remained `visible`. There is no demonstrated focus trap or background scroll lock |
| **MEDIUM** | Journal client requests `limit=200` without pagination controls | API supports offset/limit, but the UI exposes neither paging nor result-window messaging beyond total count |
| **LOW** | Migration scaffolding is user-visible | Every shell footer says “React migration · Journal,” and disabled “Soon” areas occupy a large share of desktop navigation |
| **LOW** | Journal has the wrong browser document title | Browser QA loaded `/journal` with `OptionBeacon · Trade Desk` while its visible H1 was Journal; the other four routes had route-specific titles |
| **LOW** | Error components and copy differ by page | Journal defines its own `ErrorState`; other pages use shared `SectionError`. Retry containment is good but visual/copy semantics vary |
| **LOW** | Information density is high at 1100px | No overflow was detected, but Options Desk and multi-column summaries become visually compressed before the mobile breakpoint |

### Visual audit

The live app was inspected at all required sizes across every route.

| Viewport | Result |
| --- | --- |
| 1440×1000 | Stable desktop rail, consistent surfaces and typography; all five routes loaded; no horizontal overflow |
| 1100×900 | Desktop rail remains; cards collapse without document overflow; Options and dense metric sections are compressed but usable |
| 390×844 | Mobile header/drawer pattern appears on every route; cards and Journal mobile history stack correctly; no document overflow; drawer focus/scroll issues noted above |

The pages feel like **one coherent application with five separately evolved content implementations**. The shell, palette, card surfaces, typography, metric primitive, badges, loading shimmer, and empty-state voice are consistent. Page-specific error components, timestamp helpers, dense layouts, freshness vocabulary, and duplicated trade representations expose their separate development histories.

Loading, empty, and error behavior is generally strong: data is not fabricated, one failed endpoint normally does not erase unrelated sections, and stale marks do not hide persisted plans. Visual screenshots were used during QA but were not added to the repository because the measurements and findings are reproducible and no image was needed as a durable artifact.

## 5. React component architecture

### Existing good shared primitives

- `AppShell` owns navigation and top-level status.
- `Metric`, `StatusBadge`, `EmptyState`, and `SectionError` provide a recognizable system.
- `InstrumentPanel`, `ScalpLifecycle`, and `ComparisonTable` appropriately decompose Options Desk.
- Fetching is centralized in `use-options-data.ts`; endpoint construction and HTTP errors live in `lib/api.ts`.

### Consolidation opportunities

| Duplication | Current examples | Recommendation (later) |
| --- | --- | --- |
| Page header + refresh action | all five desk components | Shared `WorkspaceHeader` with optional freshness/as-of slot |
| Loading cards/skeleton grids | each page defines its own | Shared skeleton primitives by density, while retaining page composition |
| Error state | shared `SectionError` vs Journal `ErrorState` and timeline inline errors | One shared section/page/inline error family with consistent availability language |
| Timestamp/duration | `format.timestamp`, Scanner `compactTimestamp`, Journal `fullTimestamp`, Active `duration` | Shared semantic timestamp component accepting purpose: observed, mark, decision, captured, historical |
| P&L/return styling | Journal `pnlClass`, Active inline comparisons, Home formatting | Shared `PnLValue` with explicit basis and null behavior |
| Lane presentation | badges plus page-specific copy | Canonical lane vocabulary/presentation map: lane ID, role, capital mode, research boundary |
| Trade card/identity | Home summary, Active position, Scanner opportunity, Journal rows/detail | Shared identity header and deep-link contract, not one monolithic card |
| Freshness logic | Scanner page, Active aggregate, shell system, Options timestamps | API-provided resource freshness envelope plus shared presentation |

### Business logic in React

Most React calculations are safe display derivations: sums, formatting, duration, progress-bar percentages, and choosing positive/negative classes. Three areas should eventually move into typed API fields to prevent divergent truth:

1. Active Trades aggregates capital, initial risk, P&L, and aggregate freshness in the browser.
2. Some plan progress/position presentation is derived from raw values in `active-trades-desk.tsx`.
3. Pages map low-level lane/status strings to roles and wording independently.

These are not strategy changes, but totals and classifications shown as authoritative should be computed once by Python and include completeness denominators. A sum of known values can otherwise look like a complete total when one row is null.

## 6. FastAPI contract audit

### Consumed endpoint inventory

- Trade Desk: `GET /api/trade-desk`, `/api/trades/active`, `/api/trades/recent`, `/api/system/status`
- Options Desk: `GET /api/options-desk/{symbol}`, `/api/scalp/{symbol}`, `/api/scalp/{symbol}/performance`, `/api/scalp/compare`
- Scanner: `GET /api/scanner`
- Active Trades: `GET /api/trades/active`, `/api/system/status`
- Journal: `GET /api/trades/history`, `/api/trades/{trade_id}/management`

Unconsumed but available endpoints include `/api/health`, `/api/market/{symbol}`, aggregate `/api/options-desk`, `/api/capital`, `/api/capital/compare`, `/api/capital/decisions/recent`, `/api/capital/{lane}`, and `/api/risk/status`. They are not necessarily dead; some are useful external/readiness contracts, but ownership and intended consumers should be documented.

### Strengths

- Explicit Pydantic response models and parameter validation.
- FastAPI imports do not import Streamlit.
- API repository disables schema DDL and uses read-only PostgreSQL transactions.
- Nulls are generally preserved rather than zero-filled.
- Scanner sections can degrade independently.
- Active management joins by exact `(trade_id, lane)`; MIRROR/control cannot enter OB/BROAD arrays.
- The API does not query market providers and reports provider state as `not_queried`.

### Contract inconsistencies and gaps

1. There is no common response envelope (`as_of`, `source_updated_at`, `freshness`, `data_status`, `partial_fields`, `request_id`) across endpoints. Some responses are bare arrays.
2. `fresh`, `stale`, `unavailable`, `persisted`, `partial`, `error`, `healthy`, `degraded`, and lifecycle states are mixed across different fields without a shared taxonomy.
3. Timestamps serialize consistently as ISO datetimes through Pydantic, but their semantics differ and are not always named precisely enough.
4. `/trades/history` uses limit/offset and filters; `/trades/recent` only has bounded limit; management history has limit and optional lane but no cursor. Frontend pagination is absent.
5. Management lane is optional at the API. The React caller supplies it, but a remote caller can request only `trade_id`; exact trade identity should remain globally unique or lane should become required for the lane-owned domain.
6. `/trade-desk` calls other broad projection methods, which repeat repository reads. Options Desk separately calls per-symbol strategy and research endpoints, producing no shared snapshot time.
7. Journal aggregation filters and paginates after loading broad source sets into Python.
8. Active totals are reconstructed in React without completeness metadata.
9. Calendar-derived market status is request-time truth, while worker freshness is persisted truth; the envelope does not make that distinction uniform.

Recommended later contract direction: a lightweight, versioned `ResourceState` envelope for every operational response with `request_as_of`, authoritative `source_as_of`, `freshness_state`, `freshness_age_seconds`, `data_status`, and `missing/partial` detail. Do not wrap immutable history rows merely for visual uniformity; use the envelope at the collection level.

## 7. Freshness and live experience

### Current cadence

| Cadence | Data |
| --- | --- |
| 5 seconds | scalp state per symbol; Active Trades positions |
| 10 seconds | SPY/QQQ persisted strategy state; Trade Desk home |
| 15 seconds | system status in AppShell; recent Trade Desk trades; Scanner aggregate |
| 45 seconds | Journal history |
| 60 seconds | scalp performance per symbol; SPY/QQQ comparison |
| On demand | selected trade management history; manual refresh buttons |

SWR uses `revalidateOnFocus: true`, no automatic error retry, and `keepPreviousData: true`; management history disables focus revalidation.

### Risks

- A single Options page can issue seven independent resource reads plus shell status, each with different source times.
- Home asks for active/recent/system separately even though `/trade-desk` already performs some overlapping reads.
- Repeated wide repository reads amplify polling cost despite a very small number of symbols/trades today.
- `keepPreviousData` improves continuity but needs an obvious “refreshing/last successful” state when a subsequent request fails.
- Fifteen-minute backend freshness thresholds are too coarse to communicate a five-second active-position expectation.
- Just-closed positions can disappear from Active Trades before Journal’s next 45-second refresh, creating a temporary dead zone.

### Technology comparison

| Approach | Fit | Finding |
| --- | --- | --- |
| Existing independent polling | Simple, resilient | Acceptable at current scale but semantically uncoordinated and query-heavy |
| Coordinated polling | Best next step | Use a product snapshot ID/as-of, tiered cadences, request deduplication, and a single operational summary read |
| Server-sent events | Later, targeted | Useful for alerts/lifecycle transitions once durable events and reconnection semantics are defined |
| WebSockets | Not justified | No bidirectional trading control or sub-second quote stream exists in React; adds operational complexity without current value |

Recommendation: retain HTTP/SWR, define three tiers—5s position/critical state, 15s scanner/system, 45–60s history/research—and add canonical `source_as_of`/snapshot identity. Provide one coordinated operational endpoint for shell + session + alerts rather than turning every resource into a socket stream.

## 8. Scanner data completeness

### Transient knowledge not canonically persisted for every SPY/QQQ scan

- a non-actionable current result when no opportunity is eligible;
- bullish and bearish component/rule scores and the rule contributions;
- current indicator values and limited context used at decision time;
- the specific eligibility/rejection reason before an opportunity exists;
- setup stage/progression (forming, trigger-ready, extended, invalidated) across observations;
- provider-cycle/source/cache/rate-limit quality by symbol;
- option-liquidity observations when no capital decision is created;
- exact code/config version associated with every non-eligible observation.

### Persistence value classification

| Priority | Persist | Why |
| --- | --- | --- |
| **TRADING-VALUE HIGH** | one bounded decision observation per SPY/QQQ cycle: symbol, observed time, price, direction/none, component scores, eligibility state, normalized rejection reason, setup stage, confidence, data-quality state, code/config version | Explains missed/rejected opportunities, denominators, selectivity, progression, and false inactivity |
| **TRADING-VALUE HIGH** | exact linkage from observation → opportunity (if any) → OB/BROAD decision IDs | Creates the learning and forensic chain without changing eligibility |
| **TRADING-VALUE HIGH** | the decision inputs actually consumed by eligibility/risk logic, recorded as known-at-time values | Supports reproducibility and prevents hindsight reconstruction |
| **TRADING-VALUE HIGH** | normalized per-symbol data failure/staleness reason | Distinguishes “no setup” from “could not evaluate” |
| **NICE TO HAVE** | every raw indicator/candle/provider response | Large/noisy; raw market data may be recoverable elsewhere and can create retention/licensing burden |
| **NICE TO HAVE** | full provider request/cache telemetry per symbol in the product DB | Operationally useful, but aggregate incidents/metrics belong in observability tooling unless they changed a decision |
| **NICE TO HAVE** | every intermediate display label from Streamlit | Labels are derived presentation, not canonical trading truth |

Use retention and material-change rules. Persisting every raw scan field forever would create noise; persist the inputs and result needed to reproduce the decision.

## 9. Trade-management snapshot completeness

### What is strong now

- Exact snapshot identity requires `trade_id`, `opportunity_id`, and lane; operational lookup is exact `(trade_id, lane)`.
- Snapshot rows carry lane role, symbol/contract context, marks/P&L where available, plan/risk values, coach/exit/thesis/momentum fields where available, source/version, missing data, payload, and a material fingerprint.
- Repeated refresh-only changes reuse the latest row; material lifecycle/plan/risk/management changes append history.
- Latest single/batch reads and chronological history exist.
- Snapshot write failures are isolated and cannot change execution.
- Active Trades admits only OB/BROAD; control research remains separately identified.

### Remaining gaps

1. The safe OB/BROAD integration point is capital-position synchronization. It records what is available there but does not canonically evaluate Trade Coach or Exit Score, so those conclusions can be absent.
2. A snapshot’s `management_reason` may describe the current persisted state but is not a universal causal event explaining each stay/exit decision.
3. Stop movement can be reconstructed only when material snapshots capture every mutation source; there is no first-class `previous_stop`, `new_stop`, actor, and reason event contract.
4. Target progression values exist, but explicit target-hit/partial-fill events and their execution effects are not uniformly canonical across domains.
5. Thesis and momentum fields are nullable and their input evidence/version may not be captured at the exact evaluation boundary.
6. The final execution exit reason and the final advisory management conclusion can be separate facts; Journal shows both but cannot always prove their causal relationship.
7. Legacy numeric Streamlit positions/recommendations lack exact lane/trade identity and correctly remain unjoined.

### Can the system answer “Why did OptionBeacon stay in or exit this exact trade?”

**Partially.** It can identify the exact lane-owned trade, show chronological material state, stop/targets, and any persisted exit/coach/thesis/momentum conclusions. It cannot guarantee that every management evaluation—especially “stay” decisions—or the inputs behind it were captured for OB/BROAD. It must not infer missing explanations from current data.

Minimum addition: at the existing evaluation boundary, persist a canonical `management_evaluation` event keyed by exact `(trade_id, opportunity_id, lane)` with evaluation timestamp, action (`HOLD`, `TIGHTEN`, `PARTIAL`, `EXIT`, `NO_EVALUATION`), reason code/explanation, inputs-as-known, stop/target before/after, Trade Coach state/version, Exit Score/components/version when actually evaluated, thesis/momentum state, freshness, and the resulting lifecycle/event ID. This should feed (or coexist with) material snapshots and remain observational.

## 10. Journal and learning loop

| Learning question | Classification | Evidence / missing piece |
| --- | --- | --- |
| Which setup types win/lose most? | **PARTIALLY AVAILABLE** | Strategy/setup exists per row, but UI/API supplies no grouped analysis; legacy/missing setup completeness must be quantified |
| OB vs BROAD performance? | **AVAILABLE NOW** | Independent lane summary and rows use realistic capital P&L; MIRROR excluded |
| SPY vs QQQ performance? | **PARTIALLY AVAILABLE** | Symbol filter and rows exist; no side-by-side aggregate |
| Calls vs puts? | **PARTIALLY AVAILABLE** | Direction/option type exist when captured; no grouped metrics and missingness remains |
| Time-of-day performance? | **PARTIALLY AVAILABLE** | Entry/exit timestamps exist; no ET session-bucket aggregation |
| Hold-time performance? | **PARTIALLY AVAILABLE** | Hold duration and overall average exist; no bucket/outcome view |
| Exit reason performance? | **PARTIALLY AVAILABLE** | Exit reason is nullable; filter/group metrics absent |
| Stop-out patterns? | **PARTIALLY AVAILABLE** | Initial/current stops and exit reason may exist; exact stop-hit and movement events are incomplete |
| Target-hit patterns? | **NOT CAPTURED** as a reliable cross-lane analytic | Targets exist, but canonical target-hit/partial sequence is not uniform |
| Confidence/score performance? | **PARTIALLY AVAILABLE** | Opportunity confidence/source evidence may exist upstream, but Journal contract does not expose stable decision-time score/components |
| Intended vs actual entry slippage? | **PARTIALLY AVAILABLE** | Theoretical/realistic values are persisted in capital/execution domains, but Journal exposes option entry rather than a normalized intended/fill/slippage set |
| Maximum favorable excursion? | **PARTIALLY AVAILABLE** | Execution MFE fields are projected when present; Journal detail does not display/group them and coverage may be incomplete |
| Maximum adverse excursion? | **PARTIALLY AVAILABLE** | Same as MFE |

The smallest useful learning addition is not a new dashboard first. Add canonical decision-time setup/score/regime fields, intended quote/fill/slippage fields, normalized exit/target/stop event codes, complete MFE/MAE coverage, and a data-completeness bitmap to the exact trade outcome projection. Then add server-side grouped analytics with sample counts and missingness. Without denominators, attractive subgroup statistics are unsafe.

## 11. Real-money readiness

| Dimension | Rating | Evidence and blocker |
| --- | --- | --- |
| Data | **PARTIAL** | Worker health, leases, durable DB, stale classifications, and provider failure handling exist. Per-symbol provider/data-quality causality and non-eligible observations are incomplete; some thresholds are coarse |
| Strategy | **NOT READY** | Framework correctly requires 100 trades/30 sessions for `PAPER_VALIDATED` and 250/60 for `LIVE_CANDIDATE`; current displayed states are developing/early and regime count is deliberately unavailable |
| Execution | **PARTIAL** | Conservative spread-adjusted simulated fills, fees, liquidity gates, and realistic P&L exist. No brokerage execution; quote lifecycle is coupled to BROAD, exits retain historical assumptions, and fill model is not validated against live fills |
| Risk | **PARTIAL** | Independent lane capital, risk-based sizing, max open risk/positions/daily loss, drawdown reduce/halt states, and no forced oversize contract are strong. Controls are simulated; no broker reconciliation or authenticated kill-switch operation exists |
| Operations | **PARTIAL** | Durable leases/health, recurring restart policy, failure isolation, and logs exist. React lacks alert history/escalation; API health is coarse; provider/DB incidents still require diagnostics/log inspection |
| Recovery | **PARTIAL** | One-click SSD tooling, Git bundle, DB dump verification, manifest, and restore instructions exist. PostgreSQL client availability, portable secrets, hosted secrets, and a periodic isolated restore drill remain human gaps |
| Observability | **PARTIAL** | Exact trades/events/capital/management and strong tests enable substantial reconstruction. Missing scan denominators and incomplete management evaluations prevent a complete “what and why” chain |

### Controlled-real-money blockers

1. Reach documented `PAPER_VALIDATED` evidence with regime and execution completeness; do not bypass readiness labels.
2. Remove the lane-neutral quote-lifecycle gap before comparing or funding OB independently.
3. Add authenticated, auditable operational controls and broker/order-state reconciliation in a separate future scope.
4. Define kill switch, max-loss enforcement, alert/escalation, and human incident runbook against actual broker state.
5. Validate fill/slippage assumptions with controlled tiny-size evidence.
6. Protect the remote API/UI with authentication and network controls.
7. Complete and rehearse disaster recovery.

## 12. Streamlit dependency

### Top-level and functional classification

| Streamlit surface/function family | Classification | React status / remaining need |
| --- | --- | --- |
| Trade Desk operational summaries, active authoritative rows, recent closes | **REPLACED BY REACT** for read-only monitoring | React Home/Active/Journal are clearer canonical views |
| Saved Trade Tracker manual premium update, apply suggested stop, partial flags, mark closed/outcome | **STILL REQUIRED FOR DAILY OPERATION** if legacy saved positions are used | No React write controls; identity is legacy numeric and cannot be merged safely |
| `SPY / QQQ` intraday workspace (`render_intraday_page`) | **STILL REQUIRED FOR DAILY OPERATION** for that distinct intraday strategy | React Options Desk is not a migration of the intraday execution domain |
| Opportunities/top setups/full scanner/transient guide | **PARTIALLY REPLACED; STILL REQUIRED** for richer transient inspection | React Scanner is durable and safer but intentionally omits noncanonical transient state |
| Paper Trading / BROAD / MIRROR / V2 comparison and experiment operations | **RESEARCH ONLY** (with operational experiment monitoring) | Not a deployable React lane workspace |
| Strategy Lab: Winner DNA, option translation autopsy, selectivity, contextual research, forensics | **RESEARCH ONLY** | Keep lazy/on-demand; do not put in primary trading path yet |
| Advanced scanner/funnel/provider/repository/build diagnostics | **ADMIN/DEVELOPER TOOL** | Exact blocker for React-only incident response; should remain separate from primary UI |
| Legacy History/coach timeline/signal outcomes/file journals | **UNKNOWN / RESEARCH ARCHIVE** | Preserve until production usage and row counts prove safe retirement |
| Superseded legacy Trade Desk render variants | **SAFE TO REMOVE LATER**, only after reference/production proof | Tests/fallbacks still reference helpers; no deletion justified in this audit |
| After-hours earnings/headline briefing | **RESEARCH ONLY** | Unique provider work; not needed for the core canonical operating loop |

React can become the default interface now only with clear links to “Research / Operations (Streamlit)” and no claim that all functions migrated. Exact blockers to React-only operation are the intraday domain, legacy manual saved-position actions, experiment operations, advanced diagnostics, and richer transient scanner inspection.

## 13. Dead and legacy inventory

| Candidate | Classification | Rationale |
| --- | --- | --- |
| Python worker, strategy, repository, capital, paper execution, MIRROR, intraday, provider modules | **STILL ACTIVE** | Runtime or research authority; not UI migration debris |
| FastAPI capital/risk/health/market endpoints not consumed by current React | **UNKNOWN / STILL ACTIVE** | Valid contracts with tests and likely external/future operational use; instrument before removal |
| `latest_results.json`, signal-history files, local SQLite/JSON journals | **UNKNOWN / RESEARCH ARCHIVE** | Some are import/recovery/display sources and may contain unique evidence |
| `positions` / `recommendations` legacy tables | **UNKNOWN** | Streamlit manual tracker still reads/writes them; not canonically attributable |
| legacy Trade Desk render variants in `app.py` | **SAFE TO REMOVE LATER** after a dedicated reference/production proof task | Large and likely superseded, but presentation tests/fallbacks remain |
| MIRROR/MIRROR V2 dashboards and tables | **RESEARCH ARCHIVE / STILL ACTIVE** depending experiment enablement | Never present as deployable capital; retain evidence |
| React shared/page components | **STILL ACTIVE** | All listed components are imported by current routes; no evidence-backed unused component found |
| “React migration · Journal” shell footer and disabled Soon navigation | **SAFE TO REMOVE LATER** | Temporary migration scaffolding, not functional authority |
| old README Phase 2 wording | **SAFE TO UPDATE LATER** | Documentation lag, not runtime code |

No table or calculation module is an evidence-backed immediate deletion candidate. Measure imports, production row counts, scheduled entry points, and log use before removal.

## 14. Security and production boundary

### Positive controls

- Provider and database credentials remain server-side; frontend receives only `NEXT_PUBLIC_OPTIONBEACON_API_URL`.
- The API performs read-only DB transactions, no schema initialization, no writes, and no provider calls.
- CORS allowlist is environment-controlled, defaults to localhost, strips wildcard, permits only GET, and restricts headers.
- Response models constrain payload shape; symbol/lane/filter inputs are validated.
- Existing backup tooling excludes secrets and private-key formats by default.

### Must fix before public/remote deployment

| Severity | Finding | Required boundary |
| --- | --- | --- |
| **P0** | No authentication or authorization protects portfolio/trade/system data | Put UI/API behind identity-aware access; enforce authorization server-side, not only in Next navigation |
| **P0** | CORS is not access control | Restrict network ingress/API origin and authenticate requests; a non-browser client ignores CORS |
| **P1** | FastAPI OpenAPI/docs are enabled by default | Disable or authenticate docs in the public environment, or explicitly accept the exposure after review |
| **P1** | Operational payloads expose detailed positions, contracts, P&L, risk, worker health, and error text | Define a private payload classification and redact/suppress internal errors from public responses |
| **P1** | No request identity, rate limiting, or audit trail at API boundary | Add gateway/app rate limits and access logs with secret-safe request correlation |
| **P1** | Deployment topology is incomplete in repository configuration | `railway.toml` starts the worker, not the FastAPI/Next services; document and test separate service definitions, TLS, health checks, and environment ownership |
| **P2** | Security headers/CSP are not demonstrated | Set at hosting/reverse proxy or Next; verify clickjacking, MIME, referrer, and CSP policy |

No penetration testing was performed. No secret was printed or inspected. Logging code should continue structured redaction; production verification should test representative provider/DB failures without exposing credentials or full connection strings.

## 15. Performance and scale

### Current scale

Current traffic and cardinality are small enough that the app is responsive. The material inefficiencies are architectural, not browser rendering bottlenecks:

- Trade Desk calls four endpoints and its home projection itself invokes active, recent, capital, and decision reads.
- Options Desk polls seven independent endpoint resources.
- Active and Journal build large lookup dictionaries from broad source lists.
- Scanner reads up to 200 opportunities/decisions and 100 events then normalizes/sorts in Python.
- Journal requests up to 10,000 opportunities/recent trades, all capital positions, all paper execution rows/positions, and management summaries before filtering/paginating in Python.
- Active Trades reads up to 10,000 capital decisions to find latest TAKE decisions.

These are tolerable now and should not trigger speculative caching that could hide live state.

### At 10× data

| Risk | Expected impact | Direction |
| --- | --- | --- |
| Journal in-memory joins/filter/aggregation | latency, DB egress, API memory, 45s repeated cost | SQL-filter source rows first; indexed joins/materialized read model; aggregate with counts/missingness in DB/service |
| Offset pagination | increasingly expensive/deforming under concurrent inserts | keyset/cursor pagination by exit timestamp + exact ID |
| Active 10k decision scan | repeated sort/transfer | indexed latest decision lookup for exact lane/opportunity identities |
| Snapshot table growth | history scans/storage increase | retain append-only truth; verify composite indexes, monitor growth, consider partition/retention only after evidence |
| Poll amplification | multiplied DB reads across tabs/users | coordinated operational endpoint, SWR dedup, server cache only for immutable/slow history |
| Scanner normalization | broad reads and Python sorting | bounded indexed queries by supported symbol/time and prejoined event summaries |
| Large Journal payload | 200 dense rows plus missing fields | real pagination, summary separate from page window, details on demand |

No significant unnecessary React rerender problem was identified relative to database/query costs. Optimize read models and query shape before memoizing small components.

## 16. Test coverage audit

The merged baseline has a substantial Python suite and five focused React test files (27 tests) covering loading, empty, error isolation, stale Scanner/Active states, lane identity, P&L treatment, filters, and exact management history. API tests cover read-only/CORS/OpenAPI, unavailable behavior, Scanner no-provider/no-write boundaries, OB/BROAD/MIRROR isolation, multiple lanes on the same symbol, stale marks, malformed Journal records, management deduplication, and chronological exact history. Browser QA covered every route and the required viewports in this audit.

High-value missing or underrepresented product tests:

1. Cross-page contract consistency for the same exact opportunity/trade/lane and source timestamp.
2. A full lifecycle browser/API test: opportunity → decisions → active → management change → close → Journal.
3. Coordinated behavior when a trade closes between Active’s 5s poll and Journal’s 45s poll.
4. Market calendar transitions at open, early close, close, holiday, and DST boundaries across shell/pages.
5. Worker state transitions `SCANNING` → `CURRENT` → `STALE`/`ERROR`, including lease owner expiry, in browser-level copy.
6. DB outage and recovery after stale SWR data exists; current content must be labeled retained/stale, not silently current.
7. Provider partial failures that result in no opportunity versus genuine no-setup results.
8. Many simultaneous positions, same symbol/contract across OB and BROAD, and multiple opportunities per symbol at responsive sizes.
9. Journal 10× pagination, concurrent inserts, missing source rows, and deterministic summary/page semantics.
10. Accessibility: drawer/modal focus trap, Escape/return focus, background scroll lock, keyboard row activation, labels, and contrast.
11. API authentication/authorization, ingress, rate limits, and security headers before remote deployment.
12. Backup restore drill in a clean environment, not only backup creation/manifest tests.
13. Schema migration compatibility against a production-like PostgreSQL snapshot and snapshot-table growth/query plans.
14. Alert delivery/escalation and incident acknowledgement once that product surface exists.

## 17. Product scorecard

| Dimension | Score | Evidence |
| --- | ---: | --- |
| Product coherence | **6/10** | Clear lifecycle routes and one shell; missing transitions, alerts, readiness, and diagnostic handoffs |
| React UI completeness | **6/10** | Excellent canonical read surfaces; no intraday migration, legacy operations, diagnostics, or research replacement |
| API architecture | **7/10** | Strong typed/read-only/provider-free boundary; inconsistent envelopes and repeated broad projections |
| Data integrity | **8/10** | Exact identities, explicit nulls, durable capital/events, control isolation; legacy and observation gaps remain |
| Scanner observability | **6/10** | Strong durable worker/opportunity/decision view; non-eligible observations and data-quality causality missing |
| Trade-management observability | **7/10** | Exact append-only material snapshots and history; incomplete evaluation/causal capture for OB/BROAD |
| Journal/learning capability | **5/10** | Strong exact row/detail foundation; limited grouped analytics, denominators, setup/score/slippage/event completeness |
| Risk controls | **7/10** | Independent lane sizing/exposure/daily loss/drawdown states; simulated only and no broker reconciliation |
| Operational resilience | **6/10** | leases, restarts, durable DB, failure isolation, backup tooling; weak alerts, remote topology, and restore proof |
| Real-money readiness | **3/10** | Intentionally no brokerage; evidence thresholds unmet, auth/ops/recovery/execution validation incomplete |

## 18. Prioritized roadmap

### P0 — must fix before remote/public or controlled-money use

| Rank | Problem and evidence | Proposed solution | Value | Risk | Scope |
| ---: | --- | --- | --- | --- | --- |
| 1 | Missing canonical observation/decision chain prevents explaining no-trade and many management decisions | Add bounded canonical SPY/QQQ decision observations and exact links through opportunity, lane decision, position, management evaluation, and outcome; no logic changes | Highest correctness, research, forensic, and readiness value | Schema/cardinality and accidental coupling; require observational tests | **LARGE** |
| 2 | No authenticated remote boundary; CORS alone does not protect sensitive trading data | Identity-aware UI/API auth, network ingress policy, authorization tests, rate limits, private docs | Required for any remote/public or real-money surface | Misconfiguration can block operations or leak data | **LARGE** |
| 3 | Real-money evidence thresholds and execution validation are unmet | Keep simulation; collect complete regime/execution evidence until documented `PAPER_VALIDATED`, then validate tiny-size fills in a separately authorized phase | Prevents premature capital deployment | Time/sample risk; avoid tuning during collection | **LARGE** |
| 4 | Incident response depends on logs/Streamlit and has no alert escalation | Define durable critical events and alert/runbook path for stale worker, DB/provider failure, mark failure, risk halt, execution/reconciliation failure | Protects operations and response time | Alert noise/false confidence | **MEDIUM** |
| 5 | Recovery is documented but not proven end-to-end | Install/configure DB tools, secure credential recovery, schedule isolated restore drill with RTO/RPO evidence | Reduces catastrophic loss risk | Handling production-like data/secrets | **MEDIUM** |

### P1 — high value

| Rank | Problem and evidence | Proposed solution | Value | Risk | Scope |
| ---: | --- | --- | --- | --- | --- |
| 1 | Independent polling produces inconsistent snapshots and repeated reads | Shared freshness envelope, coordinated cadence, operational summary endpoint, source snapshot/as-of IDs | User trust, lower load, simpler error semantics | Cache/staleness mistakes | **MEDIUM** |
| 2 | OB/BROAD management cannot always explain stay/exit | Persist exact management evaluations and actual inputs/results at existing evaluation boundaries | Causal Journal and forensic review | Must not duplicate or alter management logic | **MEDIUM** |
| 3 | Journal cannot answer core subgroup questions reliably | Add minimum outcome fields/completeness, then server-side grouped analytics with sample sizes | Direct strategy-learning value | Multiple-comparison/hindsight misuse | **LARGE** |
| 4 | React lacks identity-based lifecycle navigation | Stable opportunity/trade URLs and links Home/Scanner/Active/Journal | Makes five pages one product | Routing/API lookup complexity | **MEDIUM** |
| 5 | Journal query path will not scale | SQL-side filtered read model, indexed joins, summary query, cursor pagination | Predictable performance at 10× | Query/migration correctness | **LARGE** |
| 6 | React-only incident handling is impossible | Private Data Health/Alerts read workspace fed by durable events; keep admin actions outside until authorized | Reduces Streamlit dependency | Can become noisy/overbroad | **MEDIUM** |

### P2 — useful

| Recommendation | Problem / evidence | Value | Risk | Scope |
| --- | --- | --- | --- | --- |
| Canonical terminology and formatting contract | Lane/freshness/time/P&L/unavailable vocabulary varies | Comprehension and maintenance | Low | **SMALL** |
| Shared UI primitives for workspace header/error/timestamp/P&L/identity | Repeated implementations | Consistency and test reduction | Over-generalization | **MEDIUM** |
| Pre-market and session-close checklists | No explicit readiness/reconciliation transition | Operational clarity | False assurance if incomplete | **MEDIUM** |
| Active summary totals from API with completeness | Browser sums known rows | Prevents partial totals looking complete | Contract change | **SMALL** |
| Explicit Streamlit Research/Operations link and ownership copy | Users cannot tell what remains there | Honest migration/default workflow | Low | **SMALL** |
| README/deployment documentation refresh | Phase 2 copy and worker-only Railway config are incomplete | Safer onboarding/operations | Low | **SMALL** |

### P3 — polish / optional

- fix mobile drawer focus trap, Escape/return focus, and scroll lock;
- replace migration footer and reconsider disabled “Soon” navigation;
- tune 1100px information density;
- align skeleton shapes and error copy;
- add saved views/export only after canonical Journal analytics exist;
- consider SSE for durable critical events only after alerts and event semantics exist.

### Top 5 next tasks, exact order

1. **Canonical SPY/QQQ decision-provenance ledger and identity chain** (observation → opportunity → OB/BROAD decision → trade → management → outcome).
2. **Authenticated private production boundary** for React/FastAPI, including ingress, authorization, rate limits, and private API docs.
3. **Canonical management-evaluation persistence** at actual OB/BROAD evaluation boundaries, without evaluating anything in the API.
4. **Durable operational alerts + Data Health read workspace and incident runbook**.
5. **Scalable Journal learning read model** with complete decision/outcome fields, sample/missingness counts, grouped analytics, and cursor pagination.

The first task is highest value because it supplies evidence needed by Scanner, management, Journal, observability, tests, and readiness. Authentication is independently mandatory before remote exposure and should proceed in parallel only if engineering capacity allows; it does not replace the evidence task.

## 19. Final answers

1. **Is the React migration functionally complete?** No. The five core read workspaces are complete, but the complete repository-defined operating/research/admin workflow is not.
2. **Should React become the default OptionBeacon interface?** Yes for routine monitoring and review, with an explicit Research / Operations link to Streamlit and no claim that Streamlit is retired.
3. **What still requires Streamlit?** Intraday SPY/QQQ, legacy saved-position write controls, richer transient scanner inspection, paper/MIRROR experiment operations, research analyses, and advanced diagnostics.
4. **Single biggest product weakness?** The five pages do not form a linked, actionable lifecycle with identity-based transitions and incident resolution.
5. **Single biggest trading-system weakness?** Missing canonical decision evidence for non-eligible scans and incomplete causal management evaluations.
6. **Single highest-value next engineering task?** The bounded canonical SPY/QQQ decision-provenance ledger and exact lifecycle identity chain.
7. **What should not be worked on yet?** Brokerage execution, WebSockets, cosmetic redesign, broad route consolidation, ML/optimization, automatic strategy tuning, or legacy deletion. First obtain complete evidence, secure the boundary, and satisfy paper-readiness thresholds.
8. **How close is OptionBeacon to controlled real-money testing?** The foundations are meaningful but the system is not close enough to authorize it. It is a strong simulation/research system with partial operational controls, not a broker-integrated, authenticated, recovery-tested execution product. Treat the current readiness as roughly **3/10** and require all P0 gates before even a separately designed tiny-capital pilot.

## Audit-only confirmation

This branch changes only this Markdown audit. It does not change OB/BROAD strategy behavior, entry/exit logic, Exit Score, Trade Coach, stops/targets, position sizing, provider calls, execution, persistence, FastAPI behavior, React runtime behavior, or Streamlit behavior.
