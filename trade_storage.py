import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo


DB_FILE = "optionbeacon_trades.db"


def eastern_timestamp():
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %I:%M:%S %p ET")


def connect(db_file=DB_FILE):
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_trade_db(db_file=DB_FILE):
    with connect(db_file) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                entered_at TEXT NOT NULL,
                closed_at TEXT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                option_type TEXT NOT NULL,
                strike REAL,
                expiration TEXT,
                entry_premium REAL,
                exit_premium REAL,
                contracts INTEGER,
                entry_underlying_price REAL,
                current_stop REAL,
                target_1 REAL,
                target_2 REAL,
                target_3 REAL,
                original_plan_json TEXT NOT NULL,
                entry_notes TEXT,
                exit_notes TEXT
            )
            """
        )


def create_position(
    *,
    symbol,
    direction,
    option_type,
    strike,
    expiration,
    entry_premium,
    contracts,
    entry_underlying_price,
    current_stop,
    target_1,
    target_2,
    target_3,
    original_plan,
    entry_notes="",
    db_file=DB_FILE,
):
    initialize_trade_db(db_file)
    with connect(db_file) as connection:
        cursor = connection.execute(
            """
            INSERT INTO positions (
                status,
                entered_at,
                symbol,
                direction,
                option_type,
                strike,
                expiration,
                entry_premium,
                contracts,
                entry_underlying_price,
                current_stop,
                target_1,
                target_2,
                target_3,
                original_plan_json,
                entry_notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "OPEN",
                eastern_timestamp(),
                symbol,
                direction,
                option_type,
                strike,
                expiration,
                entry_premium,
                contracts,
                entry_underlying_price,
                current_stop,
                target_1,
                target_2,
                target_3,
                json.dumps(original_plan or {}, sort_keys=True),
                entry_notes,
            ),
        )
        return cursor.lastrowid


def load_positions(status=None, db_file=DB_FILE):
    initialize_trade_db(db_file)
    query = "SELECT * FROM positions"
    params = []

    if status:
        query += " WHERE status = ?"
        params.append(status)

    query += " ORDER BY entered_at DESC, id DESC"

    with connect(db_file) as connection:
        rows = connection.execute(query, params).fetchall()

    return [dict(row) for row in rows]


def load_open_positions(db_file=DB_FILE):
    return load_positions(status="OPEN", db_file=db_file)


def close_position(position_id, exit_premium=None, exit_notes="", db_file=DB_FILE):
    initialize_trade_db(db_file)
    with connect(db_file) as connection:
        connection.execute(
            """
            UPDATE positions
            SET status = ?, closed_at = ?, exit_premium = ?, exit_notes = ?
            WHERE id = ?
            """,
            ("CLOSED", eastern_timestamp(), exit_premium, exit_notes, position_id),
        )
