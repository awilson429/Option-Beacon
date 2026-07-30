# OptionBeacon 2.0 Opportunity State Machine

## Scope

This is the proposed opportunity lifecycle for research and shadow evaluation.
It is not connected to the existing production lifecycle.

Every transition is caused by an immutable event with opportunity id, event
time, received time, prior state, next state, playbook/version, reason codes,
input snapshot id, and idempotency key.

## States

| State | Required conditions / entry | Exit conditions | User explanation | Logging | Actionable |
|---|---|---|---|---|---|
| `NO_SETUP` | No playbook formation passes | Formation appears | “No defined setup is present.” | Evaluation summary; missing data | No |
| `DEVELOPING` | Formation exists but prerequisites/structure are incomplete | Prerequisites pass, formation fails, or thesis invalidates | “A setup is forming but is incomplete.” | Formation evidence and missing requirements | No |
| `WATCHING` | Prerequisites pass; confirmation or timing gate is pending | Confirmation, expiry, late condition, or invalidation | “Conditions are worth monitoring; do not enter yet.” | Required confirmation and expiry | No |
| `READY` | Confirmation, evidence, location, timing, risk, and freshness gates pass | Entry, late condition, weakening, expiry, or invalidation | “The planned entry is currently valid.” | Frozen ready snapshot and plan version | Yes |
| `ACTIVE` | A tracked paper entry event occurs from READY | Weakening, targets, stop, invalidation, or closure | “The planned trade has entered.” | Entry price/time and immutable plan | Yes, manage only |
| `LATE` | Entry was not taken and maximum-entry or age rule is exceeded | New formation cycle, invalidation, or closure | “The thesis may remain valid, but the planned entry has passed.” | Late threshold and observed price | No |
| `WEAKENING` | Active thesis loses required non-terminal evidence without hitting stop/invalidation | Evidence recovers, target, stop, invalidation, or closure | “The trade is active, but supporting evidence has weakened.” | Changed families and management reason | Yes, manage only |
| `INVALIDATED` | Thesis invalidation condition is met before or after entry | Closure only | “The original thesis is no longer valid.” | Exact invalidation fact and precedence | No new entry |
| `TARGET_1_REACHED` | Active price reaches Target 1 | Target 2, stop/trailing exit, invalidation, or closure | “The first objective was reached.” | Target level/time and plan version | Yes, manage only |
| `TARGET_2_REACHED` | Active/Target 1 price reaches Target 2 | Stop/trailing exit, invalidation, or closure | “The second objective was reached.” | Target level/time and plan version | Yes, manage only |
| `STOPPED` | Active trade reaches the governing stop | Closure | “The planned risk limit was reached.” | Stop level, observed/exit price and time | No |
| `CLOSED` | Terminal close event, including never-entered expiry | None | “Tracking is complete.” | Exit reason, outcome, final metrics | No |

`TARGET_1_REACHED` and `TARGET_2_REACHED` record milestones. A plan with a
third target records a target event while remaining in `TARGET_2_REACHED`, then
closes according to policy; a future schema may add a third milestone state.

## Allowed transitions

```text
NO_SETUP -> DEVELOPING
DEVELOPING -> NO_SETUP | WATCHING | INVALIDATED | CLOSED
WATCHING -> DEVELOPING | READY | LATE | INVALIDATED | CLOSED
READY -> WATCHING | ACTIVE | LATE | WEAKENING | INVALIDATED | CLOSED
LATE -> DEVELOPING | INVALIDATED | CLOSED
ACTIVE -> WEAKENING | INVALIDATED | TARGET_1_REACHED | TARGET_2_REACHED | STOPPED | CLOSED
WEAKENING -> ACTIVE | INVALIDATED | TARGET_1_REACHED | TARGET_2_REACHED | STOPPED | CLOSED
TARGET_1_REACHED -> WEAKENING | INVALIDATED | TARGET_2_REACHED | STOPPED | CLOSED
TARGET_2_REACHED -> WEAKENING | INVALIDATED | STOPPED | CLOSED
INVALIDATED -> CLOSED
STOPPED -> CLOSED
CLOSED -> (none)
```

A later formation for the same symbol receives a new opportunity identity; it
does not reopen a terminal opportunity.

## Transition precedence

When one market update satisfies several conditions:

1. Closed-state immutability
2. Data integrity failure (hold state; emit health event)
3. Stop or explicit thesis invalidation
4. Highest target reached
5. Entry
6. Late/expiry
7. Weakening/recovery
8. Formation progression

Stop versus target behavior must use the documented market sampling policy.
With bar-only data where both occur in one bar and sequence is unknown, use a
conservative ambiguous-bar outcome or lower-timeframe data; never assume the
favorable event happened first.

## Guards

- `READY -> ACTIVE` requires an explicit qualifying entry event, not merely an
  evaluation timestamp.
- Only a never-entered opportunity can transition to `LATE`.
- Target and stop states require a prior ACTIVE state.
- Entry cannot occur after invalidation, late expiry, stop, or closure.
- Terminal states cannot return to formation or active states.
- A duplicate event id is a no-op.
- Out-of-order events are rejected or replayed chronologically; they cannot
  silently mutate the current snapshot.
- Missing/stale required data cannot advance actionability.

## Required data by transition class

- **Formation:** playbook/version, feature snapshot, context, direction.
- **Ready:** fresh price, entry zone, maximum entry, stop, targets,
  invalidation, evidence result, risk/reward, event-risk state.
- **Entry:** sampled price, time, quote quality, plan id.
- **Management:** current price, entry, stop/targets, features and thesis health.
- **Terminal:** reason, time, observed/exit price if entered, final MFE/MAE and
  hold time where applicable.

## Logging and reconstruction

The event log is append-only. A derived snapshot may be rewritten atomically
for fast reads, but it must be reconstructable from events. Each state change
records the policy versions and source snapshot hashes. Evaluation events that
do not change state are sampled or deduplicated to control volume while
preserving reasons for important conflicts and data outages.

## Entry-state vocabulary

The user-facing entry state is derived from lifecycle:

- early: DEVELOPING or WATCHING;
- ready: READY;
- active: ACTIVE or target/weakening states;
- late: LATE;
- invalid: INVALIDATED, STOPPED, or CLOSED as context requires.
