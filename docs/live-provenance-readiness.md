# Live Provenance Collection and Research Readiness

## Verified live path

| Stage | Implementation | Persisted evidence | Identity / parent |
|---|---|---|---|
| Worker cycle | `optionbeacon.worker.scan_once.run_scan_once` | `provenance_scan_cycles` | SHA-256 of scanner ID, run number, and UTC start |
| Market observation | `signal_generator` then `decision_provenance.build_observation` | `provenance_observations` | observation ID → scan cycle; symbol is independently bounded to SPY/QQQ |
| Qualification or rejection | existing `scanner_result_decision` projection | qualification state, reason code, explanation, scores | stored on the observation before candidate processing |
| Candidate/opportunity | `trade_state_service.process_scanner_result` / `sync_trade_outcome` | `opportunities`, `authoritative_trades`, events | opportunity ID; observation is linked only when the real opportunity exists |
| Entry-funnel diagnostics | `authoritative_entry_funnel.record_authoritative_entry_funnel` | funnel cycle/symbol tables | scanner/run/start-derived cycle ID and symbol |
| OB/BROAD decision | `CapitalRepository.record_decision` | `capital_decisions`, `provenance_decision_trade_links` | decision → exact observation and opportunity, lane OB or BROAD |
| Contract/execution | paper execution followed by `CapitalRepository.sync_paper_positions` | `paper_execution_*`, `capital_positions` | lane-prefixed position ID → decision/opportunity |
| Management | `CapitalRepository._record_management_snapshot` | `trade_management_snapshots` | exact trade, opportunity, lane, timestamp, fingerprint |
| Outcome | authoritative lifecycle and closed capital position | authoritative outcome / `capital_positions.realistic_pnl` | exact opportunity/trade/lane |
| Retrospective outcome | `CapitalRepository.record_hypothetical_outcome` | non-TAKE `capital_decisions` only | exact decision ID; unavailable otherwise |
| Completion | worker success/error paths call `_finish_provenance_cycle` | genuine completion/status/provider state | original scan-cycle ID |
| Validation/readiness | `analysis.provenance_validation` | none (read-only) | ET date session containing exact cycles |

Observations are written for SPY and QQQ immediately after the live generator returns and before `process_scanner_result`. Therefore no-setup, rejected, session-blocked, data-unsafe, and qualified states survive even when no opportunity, contract, or execution is produced. No-candidate is represented by the observation and its reason; missing later links remain absent rather than inferred.

## Lifecycle and integrity findings

The research session key is the Eastern market date; each restart-safe worker cycle has a separate deterministic identity. A restart creates a new cycle and cannot overwrite an earlier one. A process killed before a genuine finish leaves `completed_at` null and `cycle_status=SCANNING`; readiness labels it incomplete and never invents completion. All timestamps are stored as UTC and grouped into sessions in `America/New_York`.

Database uniqueness already prevents duplicate primary identities. Collection hardening now also rejects conflicting immutable fields when an idempotent cycle, observation, or decision ID already exists. Repeated rapid SPY/QQQ scans remain isolated by cycle ID, observation ID, and symbol. Provenance persistence failures mark the cycle degraded when its cycle row exists; a failure before the cycle row itself is durable can only be recovered from worker logs and is a remaining operational limitation.

The validator previously looked up linked OB/BROAD trade IDs only in `authoritative_trades`; live links use lane-owned `capital_positions`. Readiness now resolves both, preventing false orphan findings.

## Counterfactual evidence

Existing retrospective support is intentionally narrow: a non-TAKE capital decision may later receive `hypothetical_realistic_pnl` and `hypothetical_outcome`. The update cannot modify TAKE decisions and cannot participate in scanning, qualification, ranking, or execution. Readiness reports available, unavailable, and coverage counts. A decision without both fields remains `UNAVAILABLE_COUNTERFACTUAL_OUTCOME`. Scanner-level rejected/no-setup observations without an opportunity do not currently have a canonical forward-mark model, so no outcome is fabricated.

## Research readiness

`GET /api/provenance/readiness` and `python -m analysis.provenance_validation --readiness` reuse the canonical validator per Eastern session. They distinguish no data, incomplete data, integrity failure, healthy-but-insufficient collection, collecting, and research ready.

A session is individually eligible only when it has genuine completed cycles, at least 95% expected SPY/QQQ observation coverage, healthy validator status, and no degraded cycle or critical identity issue. Collection-level readiness requires at least 20 eligible complete sessions. Progress at 20, 40, and 60 sessions is evidence coverage—not a statistical guarantee and never a reason to tune strategy automatically.

Storage reporting measures bounded serialized evidence bytes for the selected session and projects 20, 40, 60, 250, and 1,000 sessions. Normal design expectation remains roughly 78 cycles and 156 observations per day. Uniqueness and immutable collision checks prevent accidental duplicate growth; no retention deletes research evidence.

## React / Next.js cutover

| Question | Answer | Blocker |
|---|---|---|
| Live scanner state without Streamlit? | Yes, via FastAPI scanner/system endpoints. | NONE |
| Signal/history without Streamlit? | Yes, via scanner, active-trades, recent-activity, and journal endpoints. | NONE |
| Provenance validation without Streamlit? | Yes, `/api/provenance/validation`. | NONE |
| Provenance readiness without Streamlit? | Yes, `/api/provenance/readiness`. | NONE |
| Does a backend worker require Streamlit? | No. Scanner/paper/capital workers own persistence independently. | NONE |
| Does Streamlit own unreproducible core state? | Some legacy presentation/session controls remain UI-local, but canonical trading evidence is persisted. | MINOR |
| What remains before React is primary? | Operational deployment, authentication/access policy if required, remaining reports/settings parity, production monitoring, and a controlled cutover/runbook. | MODERATE |

No React component reads Streamlit session state, Python files, Neon directly, or market providers directly. FastAPI is the boundary. Streamlit can be retired only after operational and remaining-page parity is accepted; it is not removed by this task.

## Diagnostics

```powershell
python -m analysis.provenance_validation --readiness --lookback-days 365
python -m analysis.provenance_validation --readiness --date 2026-08-26 --json-output readiness.json
```

Both commands and both provenance endpoints are read-only. Synthetic tests use isolated temporary databases and never write to production storage.
