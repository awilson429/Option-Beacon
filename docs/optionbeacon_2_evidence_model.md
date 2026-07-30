# OptionBeacon 2.0 Evidence Model

## Recommendation

Use a **gated, family-based hybrid model**:

1. Playbook prerequisites and safety gates decide whether evaluation may
   continue.
2. Each independent evidence family produces one directional verdict and a
   reliability level.
3. A conflict policy determines whether evidence is coherent, mixed, or
   contradictory.
4. The system returns an evidence grade and broad confidence band.
5. Historical paper outcomes later calibrate the band; they do not rewrite the
   current evidence.

This is preferable to another additive 100-point score. Multiple indicators
inside one family explain that family, but cannot each award independent
points. Confidence is a bounded expression of evidence completeness and
historical calibration, not a promise of success.

## Output contract

An `EvidenceResult` should contain:

- direction and playbook;
- as-of timestamp and component versions;
- hard-gate results;
- one `FamilyVerdict` per family;
- supporting, conflicting, neutral, missing, and stale families;
- grade: `A`, `B`, `C`, `D`, or `INSUFFICIENT`;
- confidence band: `HIGH`, `MODERATE`, `LOW`, or `UNAVAILABLE`;
- calibrated probability only after adequate out-of-sample evidence;
- reason codes, deterministic summary, and known limitations.

Family verdicts use `SUPPORTS`, `CONFLICTS`, `NEUTRAL`, `UNKNOWN`, or
`NOT_APPLICABLE`, plus `HIGH`, `MEDIUM`, or `LOW` reliability.

## Grade policy

- **A:** all hard gates pass; strong support from several independent required
  families; no critical conflict; data is fresh and substantially complete.
- **B:** gates pass; net independent support is clear; conflicts are
  explainable and non-critical.
- **C:** gates pass but support is mixed, incomplete, or weak. Monitoring only
  unless a playbook explicitly allows it.
- **D:** critical conflict, poor location/timing, or unfavorable risk. Not
  actionable.
- **INSUFFICIENT:** required evidence is missing, stale, or unreliable.

Grades are ordinal, not arithmetic probabilities.

## Evidence families

### 1. Market environment

- **Purpose:** Determine whether broad conditions support the proposed
  direction and playbook.
- **Candidate inputs:** SPY/QQQ trend and agreement, opening behavior, realized
  volatility, sector proxies, session phase.
- **Sources:** Existing Yahoo OHLCV; existing scanner outputs for SPY/QQQ and
  sector ETFs; future VIX/breadth feeds.
- **Point-in-time:** Completed bars only; source and session timestamp required.
- **States:** supportive, adverse, rotational/mixed, volatility shock, unknown.
- **Direction:** Continuation prefers alignment; reversal playbooks may require
  an adverse extreme followed by confirmation.
- **Confidence contribution:** One family verdict regardless of the number of
  benchmark indicators.
- **Conflicts:** SPY/QQQ disagreement, shock volatility, or broad market moving
  against a continuation.
- **Missing data:** `UNKNOWN`; may block regime-dependent playbooks.
- **Limitations:** ETF proxies are not true breadth or internals.

### 2. Trend

- **Purpose:** Describe higher- and intraday directional persistence.
- **Inputs:** Slopes, moving-average ordering, swing sequence, distance from
  reference trend, multi-timeframe alignment.
- **Sources:** Existing OHLCV.
- **Point-in-time:** Windows end at the evaluation clock; incomplete
  higher-timeframe bars are not final.
- **States:** bullish, bearish, flat, transitioning, overextended, unknown.
- **Direction:** Alignment supports continuation; countertrend requires a
  reversal-specific playbook.
- **Contribution:** One verdict; MA and swing measures are corroborators.
- **Conflicts:** Higher timeframe opposes an unconfirmed intraday move.
- **Missing:** Reduce reliability or block higher-timeframe playbooks.
- **Limitations:** Trend measures lag and are correlated.

### 3. Structure

- **Purpose:** Identify meaningful price organization.
- **Inputs:** Swing highs/lows, consolidation, break/retest, opening range,
  prior-day range, support/resistance.
- **Sources:** Existing OHLCV.
- **Point-in-time:** Pivots must use only bars confirmed by the cutoff.
- **States:** continuation, compression, breakout, failed break, reversal,
  disorganized.
- **Direction:** Playbook-specific.
- **Contribution:** Often a required family for setup formation.
- **Conflicts:** Price violates the structural thesis or has no clean level.
- **Missing:** No setup rather than inferred structure.
- **Limitations:** Pivot sensitivity and noisy low-timeframe bars.

### 4. Momentum

- **Purpose:** Measure directional rate and persistence, not participation.
- **Inputs:** Returns over bounded windows, impulse versus pullback, oscillator
  state, acceleration/deceleration.
- **Sources:** Existing OHLCV.
- **Point-in-time:** Completed bars and fixed windows.
- **States:** strengthening, steady, fading, divergent, exhausted, unknown.
- **Direction:** Strength supports continuation; controlled divergence can
  support a reversal only with structure confirmation.
- **Contribution:** One family verdict; correlated oscillators do not stack.
- **Conflicts:** Momentum fades before confirmation or is already exhausted.
- **Missing:** Lower reliability.
- **Limitations:** Highly correlated with trend and price location.

### 5. Participation

- **Purpose:** Determine whether activity validates the move.
- **Inputs:** Relative volume, breakout volume, volume trend, range expansion,
  future breadth.
- **Sources:** Existing Yahoo volume; future internals provider.
- **Point-in-time:** Compare elapsed session volume with like-for-like periods.
- **States:** confirming, normal, weak, climactic, unknown.
- **Direction:** Direction-neutral quality evidence interpreted by playbook.
- **Contribution:** One verdict, separate from momentum.
- **Conflicts:** Low participation on a required expansion.
- **Missing:** Some playbooks become WATCHING, not READY.
- **Limitations:** Consolidated-feed coverage and intraday seasonality.

### 6. Relative strength

- **Purpose:** Compare a symbol with SPY/QQQ and its sector.
- **Inputs:** Excess return, ratio trend, behavior during benchmark pullbacks,
  sector-relative movement.
- **Sources:** Existing OHLCV and sector mapping.
- **Point-in-time:** Synchronized timestamps and equal windows.
- **States:** outperforming, underperforming, neutral, diverging, unknown.
- **Direction:** Outperformance supports bullish trades; underperformance
  supports bearish trades.
- **Contribution:** One independent verdict.
- **Conflicts:** Proposed direction relies entirely on market movement while
  the symbol lags.
- **Missing:** Neutral/unknown, never assumed aligned.
- **Limitations:** Sector mappings and sparse synchronized bars.

### 7. Location

- **Purpose:** Judge where price is relative to decision and risk levels.
- **Inputs:** VWAP, prior high/low, overnight range, support/resistance, range
  percentile, distance to invalidation.
- **Sources:** Existing OHLCV; premarket levels require extended-hours data.
- **Point-in-time:** Session-aware VWAP and levels known at evaluation time.
- **States:** favorable, neutral, crowded, late/extended, invalid.
- **Direction:** Playbook-specific.
- **Contribution:** Hard gate for invalid/late entries.
- **Conflicts:** Poor location can override otherwise supportive evidence.
- **Missing:** Do not invent levels; reduce actionability.
- **Limitations:** Level selection can be sensitive to timeframe.

### 8. Timing

- **Purpose:** Determine whether the setup is forming, confirmed, late, or
  stale.
- **Inputs:** Session phase, confirmation event, bars since event, distance from
  entry, setup age.
- **Sources:** Existing timestamps and OHLCV.
- **Point-in-time:** Exchange calendar and event timestamps required.
- **States:** early, watching, ready, late, expired, unknown.
- **Direction:** Symmetric.
- **Contribution:** Hard actionability gate.
- **Conflicts:** Evidence can be strong while timing is late; state becomes
  LATE, not READY.
- **Missing:** Non-actionable.
- **Limitations:** Bar granularity limits exact crossing time.

### 9. Risk/reward

- **Purpose:** Verify that a coherent plan exists.
- **Inputs:** Entry zone, maximum entry, structural stop, targets, slippage
  allowance, reward-to-risk.
- **Sources:** Existing trade-plan inputs.
- **Point-in-time:** Uses levels available at plan creation.
- **States:** acceptable, marginal, unfavorable, undefined.
- **Direction:** Symmetric.
- **Contribution:** Hard gate, not bonus points.
- **Conflicts:** No valid stop or reachable target blocks action.
- **Missing:** Not actionable.
- **Limitations:** Underlying levels do not guarantee option fill or return.

### 10. Event risk

- **Purpose:** Identify scheduled uncertainty that can invalidate normal
  assumptions.
- **Inputs:** Economic releases, Fed events, earnings, dividends, halts.
- **Sources:** Finnhub may provide some company data, but no reliable integrated
  calendar currently exists; new provider likely required.
- **Point-in-time:** Publication time, event time, revisions, and timezone.
- **States:** clear, approaching, active, recently released, unknown.
- **Direction:** Usually a risk gate, not directional support.
- **Contribution:** Can cap grade or block entry.
- **Conflicts:** Imminent high-impact event overrides technical coherence.
- **Missing:** `UNKNOWN`, visibly disclosed; configurable conservative gate.
- **Limitations:** Coverage, revisions, and licensing.

### 11. Options context

- **Purpose:** Assess contract liquidity and volatility context after the
  underlying thesis exists.
- **Inputs:** Bid/ask, spread, open interest, volume, IV, delta, expiration,
  future skew/term structure.
- **Sources:** Existing Tradier chain and quote paths.
- **Point-in-time:** Chain snapshot timestamp and exact contract.
- **States:** liquid, acceptable, poor, unavailable; IV low/normal/high only
  after a defensible baseline.
- **Direction:** Does not create the underlying direction.
- **Contribution:** Contract/implementation gate, not duplicated thesis points.
- **Conflicts:** Untradeable spread or missing contract blocks paper contract
  capture while preserving the underlying opportunity.
- **Missing:** Underlying analysis remains; option execution context unavailable.
- **Limitations:** Entitlements, delayed fields, and incomplete historical IV.

### 12. Sentiment

- **Purpose:** Provide optional contextual risk, not an unverified directional
  trigger.
- **Inputs:** News classification, future social/analyst sentiment, catalyst
  polarity.
- **Sources:** Existing Finnhub general news; structured sentiment requires new
  capability/provider.
- **Point-in-time:** Published and received timestamps; no revised future label.
- **States:** positive, negative, mixed, high-uncertainty, unavailable.
- **Direction:** Secondary context only in MVP.
- **Contribution:** No MVP grade contribution.
- **Conflicts:** Material breaking news can block or flag a technical setup.
- **Missing:** No penalty except visible absence.
- **Limitations:** NLP error, duplication, source bias, and licensing.

## Conflict and correlation rules

- Trend indicators vote inside Trend, not separately in the final result.
- Price/VWAP distance belongs to Location; VWAP reclaim structure belongs to
  Structure. The same observation cannot independently strengthen both unless
  each interpretation is explicitly recorded and final weighting is capped.
- Relative volume belongs to Participation, not Momentum.
- Sector and benchmark alignment contribute through Market Environment and
  Relative Strength under distinct definitions; duplicate raw returns are
  deduplicated.
- Location, Timing, Risk/Reward, stale data, and event risk can be hard gates.
- A critical conflict cannot be averaged away by several weak supports.

## Approach comparison

| Approach | Strength | Weakness | Decision |
|---|---|---|---|
| Weighted additive evidence | Simple ranking | Double-counting and false precision | Do not use as the primary decision |
| Confidence bands | Honest uncertainty | Needs a decision structure beneath it | Use as an output |
| Calibrated probability | Empirically meaningful | Requires large clean out-of-sample cohorts | Add later |
| Gated playbooks | Interpretable and setup-specific | More definitions and tests | Use as the foundation |
| Hybrid | Gates plus grades and later calibration | Governance is more complex | Recommended |

## Calibration policy

Initially, confidence bands are deterministic policy outputs. After minimum
sample gates, compare each playbook/version/grade with out-of-sample win rate,
expectancy, target/stop rates, MFE/MAE, and calibration error. Publish sample
size and interval uncertainty. Never reuse evaluation outcomes to tune and
claim performance on the same cohort.
