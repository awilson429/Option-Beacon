# OptionBeacon recovery checklist

- [ ] Connect Samsung T5 and read `LATEST\CURRENT_SNAPSHOT.txt`.
- [ ] Confirm the selected manifest says successful or understand every warning.
- [ ] Install Git, Python 3.12, Node 24, pnpm 11.19, and PostgreSQL client tools.
- [ ] Run `git bundle verify` on `Option-Beacon-complete.bundle`.
- [ ] Clone the bundle and match branch/HEAD to `backup_manifest.json`.
- [ ] Review/overlay the tracked `repository\` snapshot.
- [ ] Review working-tree/staged patches and selected `exports\` artifacts.
- [ ] Create a new empty PostgreSQL/Neon database.
- [ ] Set the new `DATABASE_URL` without printing or committing it.
- [ ] Run `pg_restore --list`, then restore the custom dump with `pg_restore`.
- [ ] Recover Tradier, Finnhub, database, hosting, Railway, and GitHub secrets.
- [ ] Recreate `.streamlit\secrets.toml`/environment values; never commit them.
- [ ] Create a new Python virtual environment and install `requirements.txt`.
- [ ] Run the Python test suite.
- [ ] Configure `frontend\.env.local` and run pnpm install/test/lint/build.
- [ ] Start FastAPI on port 8000 and Next.js on port 3000.
- [ ] Start Streamlit only if the legacy/current UI is required.
- [ ] Force `OPTIONBEACON_EXECUTION_MODE=PAPER`.
- [ ] Force `OPTIONBEACON_TRADING_ENABLED=false`.
- [ ] Start exactly one primary worker and, if required, one intraday worker.
- [ ] Run worker healthcheck and confirm durable database persistence.
- [ ] Verify Trade Desk plus SPY and QQQ Options pages.
- [ ] Confirm historical rows and new PAPER rows survive restart.
- [ ] Confirm no brokerage execution is enabled.
- [ ] Store a written restore-drill result separately from the SSD.

Full procedure: `RESTORE_OPTIONBEACON.md`.
