# OptionBeacon 2.0 Implementation Checklist

## Current Goal

Build OptionBeacon into a trade planning and management system, not just a scanner.

## Phase 1

- [x] Add setup stages.
- [x] Add entry timing classifications.
- [x] Add complete trade plan fields.
- [x] Add maximum-entry and do-not-chase logic.
- [x] Add "What should I do next?" guidance to scanner cards.
- [x] Add manual trade entry.
- [x] Add active position tracking.
- [x] Add basic exit score.
- [x] Add trade journal storage.

## Phase 2

- [x] Add peak-profit tracking.
- [x] Add partial-profit logic.
- [x] Add breakeven recommendation.
- [x] Add trailing-stop/profit-giveback recommendation.
- [x] Add timeline of recommendation changes.
- [x] Add alert rules for trade-coach changes.
- [x] Add manual buttons for marking partial profits taken.
- [x] Add suggested stop updates after profit milestones.
- [x] Add compact active-trade summary.
- [x] Add closed-trade outcome tags and lessons learned fields.
- [x] Add journal review stats by outcome tag and common lesson patterns.
- [x] Add trade review dashboard by setup, management, and discipline.
- [x] Add optional structured review fields for setup, management, and rule-following.
- [x] Add review filters for ticker, direction, outcome, and date range.
- [x] Add export buttons for filtered review dashboard, outcome review, and lesson patterns.
- [x] Add review trend snapshots over time.

## Phase 2 Summary

Phase 2 turned OptionBeacon from a signal-only scanner into a paper-trade management system. The app can now track open trades, monitor premium progress, recommend partial profits, suggest breakeven/trailing stops, log trade-coach changes, and review closed trades by outcome, setup quality, management quality, rule discipline, and lessons learned.

## Phase 3 Candidates

- [ ] Add scheduled active-trade coaching outside the Streamlit session.
- [ ] Add trade-coach SMS alerts from scheduled scans, not only app refreshes.
- [ ] Add option-chain contract tracking so current premiums can update automatically.
- [ ] Add portfolio-level risk controls and max open exposure rules.
- [ ] Add broker/import-ready trade journal CSV support.
- [ ] Add win-rate and expectancy review by ticker, setup grade, and management grade.
- [ ] Add chart snapshots or entry/exit screenshots for closed trades.
- [ ] Add a clean multi-page Streamlit layout for Scanner, Active Trades, Journal, and Settings.

## Resume Here

Next implementation step: choose the first Phase 3 priority and start a focused implementation slice.
