# Trade Data Recovery and Legacy Import

## Safety principles

- Never delete or rewrite legacy history during migration.
- Import is dry-run by default.
- Imported opportunities retain original outcome timestamps and source
  metadata.
- Database identities and an import ledger make retries idempotent.
- Back up the target database before applying a large import.

## Supported legacy sources

The importer accepts:

- `signal_history.jsonl` in the existing `TradeOutcome` schema;
- CSV files with recognizable Symbol/Ticker, Direction, timestamp, entry,
  stop, target, and outcome columns.

Malformed rows are counted and skipped. Unsupported files are reported invalid.

## Dry run

```bash
python -m optionbeacon.worker.import_legacy signal_history.jsonl
```

Multiple files:

```bash
python -m optionbeacon.worker.import_legacy \
  signal_history.jsonl optionbeacon_trade_journal.csv
```

The JSON report contains imported, skipped, invalid, and duplicate counts.
Dry-run does not modify the source or repository.

## Apply

After reviewing the dry-run:

```bash
python -m optionbeacon.worker.import_legacy \
  signal_history.jsonl --apply
```

For a local test repository:

```bash
python -m optionbeacon.worker.import_legacy \
  signal_history.jsonl --sqlite-path recovery-test.db --apply
```

Production uses `DATABASE_URL`; never place the URL on a shared command line or
in source control.

## After deployment

If the dashboard reports unavailable or empty data:

1. Do not assume there are no trades.
2. Check storage and scanner states.
3. Verify `DATABASE_URL` points to the expected database.
4. Query open trades and scanner health read-only.
5. Restart/retry the worker, not the Streamlit filesystem.
6. Import legacy data only after a dry-run and backup.

## Rollback

Application rollback:

1. redeploy the previous application commit;
2. stop the new worker schedule if it is incompatible;
3. retain the PostgreSQL tables and legacy files;
4. do not drop or truncate schema;
5. restore reads only after validating version compatibility.

Because new tables are additive, an application rollback does not require data
deletion.

## Durability boundaries

PostgreSQL data survives application redeploys subject to the database
provider's retention/backups. SQLite and JSONL/CSV files inside Streamlit
Community Cloud do not provide that guarantee. Repository backups, retention,
and point-in-time recovery are configured with the PostgreSQL provider.
