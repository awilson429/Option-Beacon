# Restore OptionBeacon after total computer loss

Assumption: the original PC is dead, GitHub may be unavailable, the original
database may be unavailable, and only the Samsung T5 plus a new Windows PC are
available. The backup never contains plaintext credentials.

## 1. Locate and validate the snapshot

1. Connect the Samsung T5.
2. Open `OptionBeacon_Backup\LATEST\CURRENT_SNAPSHOT.txt`.
3. Open that named directory under `OptionBeacon_Backup\SNAPSHOTS`.
4. Read `manifests\BACKUP_SUMMARY.txt` and
   `manifests\backup_manifest.json`.
5. Prefer a `BACKUP SUCCESSFUL` or `BACKUP SUCCESSFUL WITH WARNINGS` snapshot.
   A partial snapshot may still contain valid Git/local data, but its database
   section explains what is missing.

## 2. Install prerequisites

Install on the new Windows PC:

- Git for Windows.
- Python 3.12 (including the `py` launcher and pip).
- Node.js 24 and Corepack/pnpm 11.19.0.
- PostgreSQL client tools containing `pg_dump`, `pg_restore`, and `psql`.
- A code editor and, optionally, Railway/GitHub CLIs.
- The approved password manager and the tool needed to decrypt any `.age`,
  `.gpg`, or `.pgp` secret archive.

Verify versions in PowerShell:

```powershell
git --version
py -3.12 --version
node --version
pnpm --version
pg_restore --version
```

## 3. Recover Git without GitHub

Copy the selected snapshot to the new PC. Then run:

```powershell
git bundle verify .\git\Option-Beacon-complete.bundle
git clone .\git\Option-Beacon-complete.bundle C:\OptionBeacon\Option-Beacon
Set-Location C:\OptionBeacon\Option-Beacon
git branch --all
git tag --list
git log -5 --oneline --decorate
```

Switch to the branch recorded in `backup_manifest.json` if the clone did not
select it automatically:

```powershell
git switch <recorded-branch>
git rev-parse HEAD
```

The resulting HEAD must match the manifest before continuing.

If a new GitHub repository must be created later, add it as a remote and upload
all offline history:

```powershell
git remote add recovered-origin <new-repository-url>
git push recovered-origin --all
git push recovered-origin --tags
```

Do not overwrite an existing remote until its ownership and contents are
verified.

## 4. Restore uncommitted and local files

The snapshot's `repository\` directory contains the tracked working-tree state
at backup time. Compare it with the bundle clone before overlaying it:

```powershell
robocopy <snapshot>\repository C:\OptionBeacon\Option-Beacon /E /L
```

Remove `/L` only after reviewing the preview. The same changes are also
represented by `git\working-tree.patch` and `git\staged.patch` when applicable.
After overlaying, inspect:

```powershell
git status --short
git diff --check
```

Selected untracked/research/runtime files are under `exports\`. Copy only the
artifacts needed for the recovered environment. Review
`manifests\untracked_included.json` and `untracked_excluded.json`.

## 5. Create a new PostgreSQL/Neon database

Create a new empty PostgreSQL-compatible database in Neon or another approved
provider. Record its connection string in the password manager. Do not put it
in Git, documentation, chat, or screenshots.

Set it only for the current recovery PowerShell session:

```powershell
$env:DATABASE_URL = '<new managed PostgreSQL connection string>'
```

Use the provider's direct/unpooled endpoint for restore if its pooled endpoint
does not support administrative restore operations.

## 6. Restore the database

Confirm the snapshot contains a non-empty
`database\optionbeacon-postgresql.dump` and that its manifest verification is
successful. Inspect it, then restore:

```powershell
pg_restore --list <snapshot>\database\optionbeacon-postgresql.dump
pg_restore --no-owner --no-acl --exit-on-error `
  --dbname "$env:DATABASE_URL" `
  <snapshot>\database\optionbeacon-postgresql.dump
```

For a brand-new empty database, do not add `--clean`. If retrying after a failed
partial restore, create another empty database instead of guessing which
objects to delete.

Verify connectivity without printing the URL:

```powershell
psql "$env:DATABASE_URL" -c "select current_database(), now();"
```

If the dump is absent, database history cannot be reconstructed from Git. The
application can initialize a new empty schema, but that is not data recovery.

## 7. Restore or recreate credentials

Open `manifests\secret_inventory.json`. Recover required values from the
password manager/provider consoles or decrypt the explicitly protected archive.
Never copy the archive's decryption key onto the same SSD.

Create `.streamlit\secrets.toml` or process/deployment environment variables as
appropriate. At minimum review:

- `DATABASE_URL`
- `TRADIER_ACCESS_TOKEN`
- `FINNHUB_API_KEY`
- `TRADIER_API_BASE_URL`
- `OPTIONBEACON_CORS_ORIGINS`
- `NEXT_PUBLIC_OPTIONBEACON_API_URL`
- Railway/GitHub deployment secrets

The inventory lists optional paper, research, worker, and OB/BROAD capital
overrides. Omit overrides to use committed defaults.

## 8. Configure Python

From the recovered repository:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
```

Do not restore an old `.venv`; recreate it.

## 9. Start FastAPI and Streamlit

Open separate PowerShell windows with the virtual environment active.

FastAPI:

```powershell
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Legacy/current Streamlit UI while it remains in the repository:

```powershell
streamlit run app.py
```

Confirm FastAPI health/status endpoints respond before starting workers.

## 10. Configure and start React/Next.js

```powershell
Set-Location frontend
Copy-Item .env.example .env.local
```

Set `NEXT_PUBLIC_OPTIONBEACON_API_URL=http://localhost:8000`, then:

```powershell
pnpm install --frozen-lockfile
pnpm test
pnpm lint
pnpm build
pnpm dev
```

Open `http://localhost:3000/` and `http://localhost:3000/options`.

## 11. Start workers only after safety checks

On the first recovered boot, explicitly prevent brokerage execution:

```powershell
$env:OPTIONBEACON_EXECUTION_MODE = 'PAPER'
$env:OPTIONBEACON_TRADING_ENABLED = 'false'
```

Then start only the needed worker processes:

```powershell
python -m optionbeacon.worker.run
python -m optionbeacon.worker.intraday --interval-seconds 60
```

Do not run two copies of the same worker against the recovered database.

## 12. End-to-end verification

1. Run `python -m optionbeacon.worker.healthcheck`.
2. Confirm the database status is durable/connected.
3. Confirm scanner health and the latest successful cycle are current.
4. Confirm the React Trade Desk loads persisted session/account state.
5. Confirm SPY and QQQ Options pages load persisted strategy/scalp state.
6. Confirm expected historical trades/events exist in PostgreSQL.
7. Confirm new PAPER events persist and survive a service restart.
8. Confirm MIRROR/scalp remain research-only.
9. Confirm `OPTIONBEACON_TRADING_ENABLED` remains false.
10. Recreate Railway, hosting, and GitHub Actions variables from the inventory.

Only after this checklist passes is the system operationally recovered. This
procedure does not authorize live brokerage execution.
