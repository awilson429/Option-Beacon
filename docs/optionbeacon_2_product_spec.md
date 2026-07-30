# OptionBeacon 2.0 Product Specification

## Mission

OptionBeacon 2.0 is an explainable, AI-assisted intraday trade-analysis
platform. It helps a trader understand the market environment, recognize
directional opportunities, evaluate supporting and conflicting evidence,
construct a complete risk-defined plan, and review what happened. It is
advisory and paper-first; it does not execute live orders.

“AI-assisted” describes the analyst-like experience: structured synthesis,
clear explanations, historical context, and disciplined monitoring. The MVP
decision engine remains deterministic and interpretable. Generative AI is not
required to produce recommendations.

## Product promises

For every displayed opportunity, the system should answer:

1. What is the current market environment?
2. Is there a directional opportunity?
3. Which playbook describes it?
4. What independent evidence supports it?
5. What evidence conflicts with it?
6. Is the entry developing, ready, late, or invalid?
7. What are entry, stop, targets, and expected duration?
8. What breaks the thesis?
9. How have comparable point-in-time setups behaved?
10. What should be monitored after entry, and why?

The system must distinguish facts, deterministic interpretations, historical
statistics, and unavailable data. It must not manufacture certainty.

## Users and jobs

The primary user is a self-directed intraday options trader who needs an
underlying-price thesis before selecting a contract. The core jobs are:

- prepare for the session without assembling several dashboards;
- focus attention on a small number of explainable opportunities;
- avoid early, late, or invalid entries;
- follow a predeclared plan rather than react emotionally;
- evaluate thesis quality separately from execution quality;
- build research evidence from paper outcomes.

## Experience model

### Pre-market: Morning Brief

The brief is an as-of snapshot, not a prediction. It contains:

- overnight SPY and QQQ direction, range, gap, and prior-close relationship;
- expected volatility using available realized-volatility proxies, with VIX
  included only when a reliable feed is implemented;
- prior day, overnight, premarket, VWAP, and opening-range levels where data is
  available;
- scheduled economic and company events, explicitly marked unavailable until
  a reliable calendar is integrated;
- bullish, bearish, and balanced scenarios;
- evidence required to confirm each scenario;
- invalidation conditions and data freshness.

### During the session: Live Trade Desk

The market header presents SPY/QQQ regime, directional bias, breadth/sector
proxies, volatility state, data freshness, and conflicts.

Each opportunity card contains:

- symbol, direction, playbook, lifecycle state, evidence grade, and confidence
  band;
- price relative to VWAP and key levels;
- higher-timeframe and market alignment;
- supporting evidence by family;
- conflicting, missing, and stale evidence;
- entry state and late-entry warning;
- entry zone, maximum entry, stop, targets, risk/reward, and invalidation;
- historical analog sample, match level, expectancy, and limitations;
- a concise deterministic thesis and “what would change this view.”

Only READY and ACTIVE are actionable in the proposed lifecycle. WATCHING is a
monitoring instruction, not an entry recommendation.

### After entry: Active Trade Management

For each paper-tracked position:

- original and current plan version;
- entry, current underlying price, stop, targets, and elapsed time;
- direction-aware return and current R multiple;
- MFE and MAE;
- target and risk progress;
- thesis health: intact, weakening, or invalidated;
- momentum/participation status;
- deterministic management event and reason;
- quote/data availability and last update time.

Management changes are event records. The original thesis and plan remain
available for review.

### After exit: Post-Trade Review

The review separates model quality from trader execution:

- original context, playbook, evidence, thesis, plan, and versions;
- entry quality: early, planned, chased, or missed;
- thesis quality: correct, partially correct, or incorrect;
- exit quality relative to plan, MFE, and MAE;
- realized outcome and failure category;
- rule adherence and management events;
- analog expectations versus observed outcome;
- structured lesson tags for later research.

## Information hierarchy

1. State and actionability
2. Direction, entry, stop, targets, and invalidation
3. Evidence grade and conflicts
4. Market context and playbook rationale
5. Historical analogs
6. Detailed feature values and audit metadata

Unavailable or insufficient values display as unavailable, not zero. Every
screen exposes an as-of time and data-health summary.

## Explanation contract

Every conclusion must carry:

- `value`: the conclusion;
- `reason_codes`: stable machine-readable causes;
- `summary`: deterministic plain language;
- `supporting_evidence`;
- `conflicting_evidence`;
- `missing_evidence`;
- `as_of`, `source_versions`, and `strategy_version`.

Explanations describe why a rule reached a result. They must never retrofit a
story after the result.

## Product boundaries

The MVP does not:

- execute, route, or recommend live brokerage orders;
- promise returns or present confidence as certainty;
- depend on premium news, sentiment, unusual-options, breadth, or calendar
  feeds;
- silently substitute delayed data for live data;
- change the stable production scanner;
- activate a playbook without research and promotion gates.

## Success measures

Product quality is assessed through:

- data completeness and freshness;
- deterministic replay parity;
- opportunity funnel counts and lifecycle integrity;
- calibration by confidence band and evidence grade;
- expectancy, MFE/MAE, stop/target distribution, and time exit by playbook;
- false-ready and late-entry rates;
- explanation completeness and conflict visibility;
- paper-trader rule adherence;
- operational error isolation.

Success is not measured by maximizing the number of signals.

## Related documents

- [MVP](optionbeacon_2_mvp.md)
- [Architecture](optionbeacon_2_architecture.md)
- [Evidence model](optionbeacon_2_evidence_model.md)
- [Playbooks](optionbeacon_2_playbooks.md)
- [State machine](optionbeacon_2_state_machine.md)
- [Data capability map](optionbeacon_2_data_capability_map.md)
- [Roadmap](../ROADMAP.md)
