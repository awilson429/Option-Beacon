# React/FastAPI migration foundation audit

Audit date: 2026-09-13

## Current architecture

OptionBeacon already implements the intended separation in committed code:

```text
market-data providers
  -> Python scanners, strategy engines, and lifecycle workers
  -> canonical repositories / PostgreSQL (with legacy local stores)
  -> read-only FastAPI service
  -> React + TypeScript frontend
```

`app.py` remains the primary legacy Streamlit entry point and must remain available as the behavioral reference during migration. `scheduled_scan.py`, `scheduled_trade_coach.py`, and modules under `optionbeacon/worker/` are non-UI execution entry points. `.github/workflows/scheduled-scan.yml` is the scheduled scanner workflow.

The React application in `frontend/` has advanced beyond the original Vite proof-of-connection shell. It is now a Next.js React/TypeScript application with route-level workspaces and Vitest tests. Replacing it with Vite would remove completed migration work, so the existing React framework is retained. It continues to consume FastAPI only and does not evaluate trading decisions in the browser.

## Responsibility inventory

### Trading and business logic (retain unchanged)

- Signal/scoring/strategy: `optionbeacon_signal.py`, `optionbeacon_strategy.py`, `intraday_strategy.py`, `entry_timing.py`, `exit_scoring.py`, `setup_stages.py`, `opportunity_ranking_v2.py`, and `authoritative_entry_funnel.py`.
- Scanner and live lifecycle: `optionbeacon_live.py`, `scheduled_scan.py`, `live_trade_activity.py`, `optionbeacon/worker/scan_once.py`, `optionbeacon/worker/run.py`, `optionbeacon/worker/intraday.py`, and `intraday_execution.py`.
- Trade lifecycle and management: `trade_management.py`, `trade_state_service.py`, `trade_plan_engine.py`, `trade_plan_lifecycle.py`, `paper_execution.py`, `mirror_execution.py`, `option_trade_engine.py`, and `option_position_tracker.py`.
- Provenance and validation: `decision_provenance.py`, `trade_evidence.py`, `authoritative_entry_funnel.py`, `analysis/provenance_validation.py`, `post_run_forensic_audit.py`, and `whole_app_audit.py`.
- Analytics and research: the modules under `analysis/` plus root modules ending in `_analytics.py`, `_analysis.py`, `_audit.py`, `_experiment.py`, `winner_dna.py`, `signal_outcomes.py`, and `trade_replay.py`.

These modules should remain authoritative. API handlers must project their persisted outputs rather than reimplement thresholds, indicators, selection, entries, exits, validation, or lifecycle decisions.

### Persistence and storage (retain behind services)

- Canonical repositories: `trade_repository.py`, `paper_execution_repository.py`, `capital_repository.py`, and `trade_storage.py`.
- Supporting durable stores: `signal_history.py`, `trade_plan_journal.py`, `trade_journal.py`, `intelligence_capture.py`, and `legacy_trade_import.py`.
- Configuration/migration: `dashboard_storage_config.py`, `optionbeacon/migrations/`, and worker database diagnostics.
- Local SQLite/JSON/CSV artifacts remain legacy/development inputs. Production API reads are configured through `DATABASE_URL` and do not read Streamlit secrets.

### UI-only code

- Streamlit composition: `app.py`, modules named `*_dashboard.py` or `*_page.py`, `trade_desk_compact.py`, `trade_desk_comparison.py`, `trade_plan_ui.py`, `featured_setup_card.py`, `qqq_command_card.py`, `workspace_ui.py`, `ui_navigation.py`, `ui_modern_style.py`, `ui_polish.py`, and `ui/`.
- React presentation and browser state: `frontend/src/app/`, `frontend/src/components/`, `frontend/src/hooks/`, and `frontend/src/lib/`.

Several Streamlit dashboard/page modules mix presentation with orchestration and DataFrame shaping. They should not be imported by FastAPI. Reusable calculations should be reached through existing non-UI services or thin adapters.

### Streamlit application state coupling

`st.session_state` is concentrated in `app.py` and UI modules including `ui_navigation.py`, `workspace_ui.py`, `paper_trading_page.py`, `intraday_page.py`, `trade_plan_ui.py`, `trade_desk_compact.py`, and dashboard/card modules. It tracks navigation, refresh controls, cached scan/display results, selected symbols/tabs, preview modes, and transient form state.

Navigation and form state belong in React. Scanner, trade, lifecycle, provenance, and execution state must come from canonical persistence/worker snapshots, not be moved from Streamlit session state into FastAPI process memory.

### Existing API, worker, and asynchronous boundaries

- `api/main.py` creates the FastAPI application, applies explicit-origin CORS, and starts one process-local live-snapshot identity watcher for SSE.
- `api/routes/` exposes health, system, market, scanner, trade desk, options desk, trades, capital, provenance, the canonical live snapshot, and read-only live events.
- `api/services.py` is the read-only projection/service boundary and uses read-only database transactions.
- `api/live_events.py` fans out committed `snapshot_id` changes. It does not run strategy logic or write trade state.
- `optionbeacon/worker/run.py` owns the long-running scan/persistence loop; `lock_lease.py` uses a background heartbeat thread for lease ownership.
- SSE publishes process-local `snapshot.changed` / `resync.required` envelopes. Replay is not durable; REST `GET /api/live/snapshot` remains the resynchronization source. See `docs/live-events-api.md`.

## UI-shaped return values requiring care

The highest-coupling functions are Streamlit render functions and helpers that return pandas `DataFrame`, `Styler`, chart-ready dictionaries, preformatted labels, HTML/CSS, or emoji/status strings. Common locations are `app.py`, dashboard modules, `trade_desk_view_models.py`, `trade_desk_compact.py`, `trade_desk_comparison.py`, `workspace_ui.py`, and analytics dashboards.

API schemas should expose typed domain values, explicit unavailable/null states, timestamps, identifiers, and provenance fields. Formatting, color, layout, and humanized labels belong in React. Existing API schemas under `api/schemas/` already establish this adapter pattern and should be extended additively.

## What remains unchanged

- All scanner, strategy, scoring, entry/exit, provenance, validation, execution, and persistence behavior.
- The worker as the owner of provider access, decision execution, and writes.
- Existing repository implementations and stored records.
- Streamlit startup and UI code during the migration.

## Migration risks

1. Streamlit session state can conceal process-local state that is not durable. Each migrated panel must identify its authoritative persisted source before parity is claimed.
2. Importing dashboard modules from FastAPI can trigger Streamlit side effects and couple API startup to UI dependencies.
3. Running scans or provider calls in request handlers can duplicate work, mutate state, increase market-data usage, and diverge from the worker's authoritative decisions.
4. pandas/numpy values, datetimes, NaN, and UI-formatted strings require explicit schema normalization.
5. Local SQLite/JSON/CSV and production PostgreSQL can yield different freshness or completeness; the API must label source and unavailable state rather than infer data.
6. Live transport can reorder, duplicate, or drop messages. Events need stable IDs, timestamps, reconnect behavior, and a REST snapshot fallback.
7. CORS is an allow-list for local direct-to-FastAPI development. Production browsers use same-origin Next.js `/api`; FastAPI must stay private. Wildcards are rejected.
8. The current frontend is Next.js, not Vite. Framework conversion is a separate product decision and should not be bundled into an API-boundary task.

## Recommended structure

The current structure should be retained and evolved without duplicating the engine:

```text
api/
  main.py                 # application factory and middleware
  dependencies.py         # service dependency construction
  routes/                 # thin REST handlers
  schemas/                # typed wire contracts
  services.py             # read-only projection/adapters
  websocket/              # future live transport, when justified
frontend/
  src/app/                # React routes
  src/components/         # presentation
  src/hooks/              # polling/live subscription state
  src/lib/                # API client and wire types
optionbeacon/worker/       # authoritative background execution
analysis/                  # offline/read-only analytics
tests/                     # engine, repository, API contract tests
```

As `api/services.py` grows, split it by bounded domain (`scanner`, `trades`, `capital`, `provenance`) while keeping repositories and strategy modules in their current locations.

## Local development

From the repository root:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn api.main:app --reload --port 8000
```

In another terminal:

```powershell
Set-Location frontend
Copy-Item .env.example .env.local
pnpm install
pnpm dev
```

Open `http://localhost:3000`. The frontend reads the API URL from `NEXT_PUBLIC_OPTIONBEACON_API_URL` in development and defaults to the local FastAPI service. Production uses same-origin `/api` through Next.js; see `docs/react-fastapi-railway-pilot.md`.

Run the retained Streamlit reference from the repository root:

```powershell
python -m streamlit run app.py
```

## Recommended next live-transport work

Keep REST snapshots canonical. A later durable outbox could add granular `decision.committed` / `trade.*` events with true replay. Until then, `snapshot.changed` plus `resync.required` is the honest contract; do not invent event types from frontend diffs.
