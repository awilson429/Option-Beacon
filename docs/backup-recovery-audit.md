# OptionBeacon backup and recovery audit

Audit date: 2026-08-24. This inventory intentionally contains credential names
and locations, never credential values.

## Recovery boundary

OptionBeacon cannot be reconstructed from one source alone. A complete recovery
requires:

1. Git history plus the current working tree.
2. Important ignored and untracked local artifacts.
3. A PostgreSQL custom-format dump of the durable production database.
4. Recreated credentials from a password manager or separately encrypted,
   portable secret archive.
5. The runtime/package manifests and deployment configuration committed here.

The backup tooling is infrastructure only. It does not change OB, BROAD,
MIRROR, scalp research, providers, workers, APIs, or user interfaces.

## Source repository and Git

- The repository is a normal Git working tree with GitHub configured as a
  remote. The remote URL is metadata, not a substitute for an offline backup.
- Recovery requires commits, all branches, tags, remotes, HEAD, current branch,
  working-tree status, uncommitted patches, and selected untracked files.
- `git bundle create ... --all` is the offline authoritative history backup.
  The bundle is verified with `git bundle verify` before a snapshot can be
  promoted.
- A separate tracked working-tree copy preserves modified tracked content that
  is not represented by the bundle.
- Untracked recovery/research files are copied separately and inventoried.

## Python and application runtime

- GitHub Actions explicitly uses Python 3.12. The audited machine runs Python
  3.12.13. Use Python 3.12 for recovery.
- `.devcontainer/devcontainer.json` still references a Python 3.11 base image;
  treat that as legacy development configuration rather than the recovery
  authority.
- `requirements.txt` defines the runtime dependencies: yfinance, pandas,
  Streamlit 1.60.0, streamlit-autorefresh, pandas-market-calendars,
  psycopg2-binary 2.x, FastAPI, Uvicorn, and HTTPX.
- Most Python dependencies are range/unpinned. The requirements file is the
  install authority, but a future lock/constraints file would improve exact
  reproducibility.
- Streamlit starts with `streamlit run app.py`.
- FastAPI starts with `python -m uvicorn api.main:app --port 8000`.
- The primary worker starts with `python -m optionbeacon.worker.run`.
- The intraday worker starts with
  `python -m optionbeacon.worker.intraday --interval-seconds 60`.

## React/Next.js frontend

- `frontend/package.json` and `frontend/pnpm-lock.yaml` are sufficient to
  reinstall dependencies; `node_modules` and `.next` are disposable.
- Audited versions are Next.js 16.3.2, React/React DOM 19.2.8, and pnpm 11.19.0.
- The package manifest does not declare a Node engines range. The audited
  machine uses Node 24.19.0; use Node 24 unless a later project manifest says
  otherwise.
- The API base is configured with `NEXT_PUBLIC_OPTIONBEACON_API_URL`.
- Development: `pnpm install --frozen-lockfile`, then `pnpm dev`.
- Production verification: `pnpm test`, `pnpm lint`, and `pnpm build`.

## Persistence and PostgreSQL

- Durable production persistence is selected through `DATABASE_URL` and
  psycopg2. The same code can use local SQLite when durable storage is not
  required.
- The locally configured value points to a managed PostgreSQL service. The
  backup does not expose its vendor, hostname, username, or password.
- `TradeRepository.initialize()` creates and additively evolves canonical
  opportunity, trade, event, scanner-health/lock, context, intelligence, and
  paper-execution tables.
- Separate additive repositories initialize MIRROR, MIRROR v2, scalp research,
  intratrade telemetry, and OB/BROAD capital-readiness tables.
- Capital readiness adds `lane_capital_state`, `capital_decisions`,
  `capital_positions`, `capital_risk_events`, `capital_equity_history`, and
  `capital_daily_state`.
- `optionbeacon/migrations/paper_execution_to_postgres.py` imports legacy local
  paper-execution state. Initialization/migrations are useful for an empty
  database, but they cannot reconstruct production history; the dump is
  required.
- Use `pg_dump --format=custom --no-owner --no-acl` for backup and `pg_restore`
  for verification/restoration. At audit time `pg_dump`, `pg_restore`, and
  `psql` are not installed on this Windows machine, so an actual required
  database backup would correctly report `BACKUP PARTIAL`.

## Providers, research, and deployment

- Tradier uses `TRADIER_ACCESS_TOKEN` and optional `TRADIER_API_BASE_URL`.
- Finnhub uses `FINNHUB_API_KEY`; universe sizing/symbol overrides use
  `OPTION_BEACON_TOP_MOVER_COUNT`, `OPTION_BEACON_ATTENTION_COUNT`, and
  `OPTION_BEACON_SYMBOLS`.
- Scalp, MIRROR, contextual research, experiment logs, forensic audits, and
  local exports are code/configuration or artifacts; no live brokerage order
  path is introduced by recovery tooling.
- `railway.toml` starts the primary worker. `railway.intraday.toml` starts the
  minute intraday worker. Railway environment values must be recreated in the
  deployment platform.
- `.github/workflows/scheduled-scan.yml` is manual maintenance infrastructure.
  It uses GitHub Actions secret names and publishes selected scanner data to a
  `scanner-data` branch. GitHub-hosted secret values cannot be recovered from
  Git or this backup and must be recreated.

## Environment-variable inventory

The generated `secret_inventory.json` is the machine-readable authority. Key
classes are:

- Required production secret: `DATABASE_URL`.
- Required provider secret for option data: `TRADIER_ACCESS_TOKEN`.
- Optional provider secret: `FINNHUB_API_KEY`.
- Frontend/deployment configuration: `NEXT_PUBLIC_OPTIONBEACON_API_URL`,
  `OPTIONBEACON_CORS_ORIGINS`, and `TRADIER_API_BASE_URL`.
- Storage/worker configuration: `OPTIONBEACON_ENVIRONMENT`,
  `OPTIONBEACON_REQUIRE_DURABLE_STORAGE`, `OPTIONBEACON_SCAN_SECONDS`,
  `OPTIONBEACON_SCANNER_ID`, and database diagnostic toggles.
- Paper execution configuration: `OPTIONBEACON_EXECUTION_MODE`,
  `OPTIONBEACON_TRADING_ENABLED`, allowed symbols, entry windows, position and
  daily limits, stop/target/hold settings, liquidity settings, and fill model.
- Research configuration: MIRROR and MIRROR-v2 flags/start dates, ranking and
  filter flags, universe configuration, and EOD timing.
- Capital readiness configuration: every documented setting supports both
  `OB_` and `BROAD_` prefixes, including starting capital, per-trade/open risk,
  positions, daily loss, drawdown thresholds, reduced-risk multiplier,
  liquidity/freshness, fees, and entry/exit slippage.
- Railway-provided deployment identifiers are runtime metadata, not portable
  secrets.

## Secret locations and handling

- A live ignored `.streamlit/secrets.toml` exists locally. Its keys are
  inventoried, but the file is never copied in plaintext.
- Ignored `.env` and frontend local-env files receive the same treatment.
- Windows DPAPI is not used because machine/user-bound encryption is unsuitable
  when the original PC is dead.
- The optional `ProtectedSecretsSource` accepts only an explicitly supplied
  `.age`, `.gpg`, or `.pgp` portable encrypted archive. Encryption/decryption
  keys must be stored separately from the SSD.
- Without that archive, recovery must use a password manager and provider
  account recovery. The backup reports a warning rather than claiming secret
  values were protected.

## Local artifacts

Important current local artifacts include signal and experiment JSONL files,
trade-plan journals, SQLite databases, provider caches, backtest/threshold CSVs,
forensic JSON exports, and diagnostic/reference screenshots. These are small
enough to preserve and may contain research evidence unavailable in Git or the
production database.

Default inclusion permits `.json`, `.jsonl`, `.csv`, `.db`, `.sqlite`,
`.sqlite3`, `.html`, `.png`, `.jpg`, `.jpeg`, `.md`, `.txt`, and `.log` files.
The manifest records every included/excluded candidate and size.

Default exclusions are `.git`, virtual environments, `node_modules`, `.next`,
Python caches, test temporary directories, `.analysis-cache`, dependency
caches, secret/config files, private-key formats, unsupported binary types, and
artifacts larger than the configured limit. No exclusion silently discards
Git modifications: tracked working-tree files are copied independently.

## Recovery gaps requiring human action

1. Install PostgreSQL client tools and configure `PgDumpPath`, or add them to
   PATH, before relying on the SSD for database disaster recovery.
2. Create and separately test a portable encrypted credential archive, or
   confirm the password manager contains all required provider/database data.
3. Recreate GitHub Actions/Railway/hosting secrets after a catastrophe.
4. Periodically perform a restore drill to a new PostgreSQL database and a
   temporary Windows directory. A verified backup is not a substitute for a
   tested restore.
