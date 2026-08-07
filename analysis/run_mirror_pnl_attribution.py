"""CLI for a production-safe, transaction-read-only MIRROR attribution audit."""

from __future__ import annotations

import argparse
import json
import os
import tomllib
from datetime import datetime
from pathlib import Path

from psycopg2 import connect
from psycopg2.extras import RealDictCursor

from analysis.mirror_pnl_attribution import EASTERN, build_session_audit


TABLES = {
    "authoritative_events": "authoritative_trade_events",
    "opportunities": "opportunities",
    "mirror_rows": "mirror_execution_trades",
    "mirror_marks": "mirror_execution_marks",
    "paper_trades": "paper_execution_trades",
    "paper_journal": "paper_execution_journal",
}


def database_url():
    configured = os.getenv("DATABASE_URL", "").strip()
    if configured:
        return configured
    secrets_path = Path(".streamlit/secrets.toml")
    if secrets_path.exists():
        return str(tomllib.loads(secrets_path.read_text(encoding="utf-8")).get("DATABASE_URL") or "").strip()
    return ""


def read_rows(url):
    """Read complete source ledgers inside a database-enforced read-only transaction."""
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    connection = connect(
        url, cursor_factory=RealDictCursor, sslmode="require",
        options="-c default_transaction_read_only=on",
    )
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            result = {}
            missing = []
            for key, table in TABLES.items():
                cursor.execute("SELECT to_regclass(%s) AS table_name", (f"public.{table}",))
                if cursor.fetchone()["table_name"] is None:
                    result[key] = []
                    missing.append(table)
                    continue
                cursor.execute(f'SELECT * FROM "{table}"')
                result[key] = [dict(row) for row in cursor.fetchall()]
            result["missing_tables"] = missing
            connection.rollback()
            return result
    finally:
        connection.close()


def table_inventory(url):
    """Return non-system table names without reading table contents."""
    connection = connect(
        url, cursor_factory=RealDictCursor, sslmode="require",
        options="-c default_transaction_read_only=on",
    )
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_schema,table_name FROM information_schema.tables "
                "WHERE table_type='BASE TABLE' AND table_schema NOT IN "
                "('pg_catalog','information_schema') ORDER BY table_schema,table_name"
            )
            rows = [dict(row) for row in cursor.fetchall()]
            connection.rollback()
            return rows
    finally:
        connection.close()


def authoritative_source_summary(url):
    """Return freshness metadata only; never returns trade payloads."""
    connection = connect(
        url, cursor_factory=RealDictCursor, sslmode="require",
        options="-c default_transaction_read_only=on",
    )
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT MAX(event_timestamp) AS latest_event_timestamp,"
                "COUNT(*) AS event_count FROM authoritative_trade_events"
            )
            row = dict(cursor.fetchone())
            connection.rollback()
            return row
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-date", help="Eastern session date (YYYY-MM-DD)")
    parser.add_argument("--list-tables", action="store_true")
    parser.add_argument("--source-summary", action="store_true")
    args = parser.parse_args()
    if args.list_tables:
        print(json.dumps(table_inventory(database_url()), indent=2))
        return
    if args.source_summary:
        print(json.dumps(authoritative_source_summary(database_url()), indent=2, default=str))
        return
    session_date = (
        datetime.fromisoformat(args.session_date).date()
        if args.session_date else datetime.now(EASTERN).date()
    )
    rows = read_rows(database_url())
    audit = build_session_audit(
        rows["authoritative_events"], rows["opportunities"], rows["mirror_rows"],
        rows["paper_trades"], rows["paper_journal"], session_date=session_date,
        mirror_marks=rows["mirror_marks"],
    )
    audit["source_status"] = {
        "database_transaction": "READ_ONLY",
        "missing_tables": rows["missing_tables"],
        "production_data_verified": not rows["missing_tables"],
    }
    print(json.dumps(audit, indent=2, default=str))


if __name__ == "__main__":
    main()
