import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo


DB_FILE = "optionbeacon_trades.db"


POSITION_COLUMNS = {
    "current_premium": "REAL",
    "peak_premium": "REAL",
    "partial_1_taken": "INTEGER DEFAULT 0",
    "partial_2_taken": "INTEGER DEFAULT 0",
}

RECOMMENDATION_COLUMNS = {
    "current_profit_percent": "REAL",
    "peak_profit_percent": "REAL",
    "profit_giveback_percent": "REAL",
}


def eastern_timestamp():
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %I:%M:%S %p ET")


def connect(db_file=DB_FILE):
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_position_columns(connection):
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(positions)").fetchall()
    }

    for column, column_type in POSITION_COLUMNS.items():
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE positions ADD COLUMN {column} {column_type}")


def ensure_recommendation_columns(connection):
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(recommendations)").fetchall()
    }

    for column, column_type in RECOMMENDATION_COLUMNS.items():
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE recommendations ADD COLUMN {column} {column_type}")


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
                current_premium REAL,
                peak_premium REAL,
                exit_premium REAL,
                contracts INTEGER,
                entry_underlying_price REAL,
                current_stop REAL,
                target_1 REAL,
                target_2 REAL,
                target_3 REAL,
                partial_1_taken INTEGER DEFAULT 0,
                partial_2_taken INTEGER DEFAULT 0,
                original_plan_json TEXT NOT NULL,
                entry_notes TEXT,
                exit_notes TEXT
            )
            """
        )
        ensure_position_columns(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                exit_score INTEGER NOT NULL,
                exit_label TEXT NOT NULL,
                coach_action TEXT NOT NULL,
                coach_next_step TEXT NOT NULL,
                current_profit_percent REAL,
                peak_profit_percent REAL,
                profit_giveback_percent REAL,
                reasons_json TEXT NOT NULL,
                FOREIGN KEY(position_id) REFERENCES positions(id)
            )
            """
        )
        ensure_recommendation_columns(connection)


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
                current_premium,
                peak_premium,
                contracts,
                entry_underlying_price,
                current_stop,
                target_1,
                target_2,
                target_3,
                original_plan_json,
                entry_notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                entry_premium,
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


def load_closed_positions(db_file=DB_FILE):
    return load_positions(status="CLOSED", db_file=db_file)


def close_position(position_id, exit_premium=None, exit_notes="", db_file=DB_FILE):
    initialize_trade_db(db_file)
    position = load_position(position_id, db_file=db_file)
    peak_premium = position.get("peak_premium") if position else None
    current_premium = exit_premium
    if current_premium is None and position:
        current_premium = position.get("current_premium")

    if exit_premium and (not peak_premium or exit_premium > peak_premium):
        peak_premium = exit_premium

    with connect(db_file) as connection:
        connection.execute(
            """
            UPDATE positions
            SET status = ?,
                closed_at = ?,
                current_premium = ?,
                peak_premium = ?,
                exit_premium = ?,
                exit_notes = ?
            WHERE id = ?
            """,
            (
                "CLOSED",
                eastern_timestamp(),
                current_premium,
                peak_premium,
                exit_premium,
                exit_notes,
                position_id,
            ),
        )


def load_position(position_id, db_file=DB_FILE):
    initialize_trade_db(db_file)
    with connect(db_file) as connection:
        row = connection.execute(
            "SELECT * FROM positions WHERE id = ?",
            (position_id,),
        ).fetchone()

    return dict(row) if row else None


def update_position_premium(position_id, current_premium, db_file=DB_FILE):
    initialize_trade_db(db_file)
    position = load_position(position_id, db_file=db_file)
    if not position:
        return None

    current_premium = float(current_premium)
    previous_peak = position.get("peak_premium") or position.get("entry_premium") or 0
    peak_premium = max(float(previous_peak or 0), current_premium)

    with connect(db_file) as connection:
        connection.execute(
            """
            UPDATE positions
            SET current_premium = ?, peak_premium = ?
            WHERE id = ?
            """,
            (current_premium, peak_premium, position_id),
        )

    return load_position(position_id, db_file=db_file)


def latest_recommendation(position_id, db_file=DB_FILE):
    initialize_trade_db(db_file)
    with connect(db_file) as connection:
        row = connection.execute(
            """
            SELECT * FROM recommendations
            WHERE position_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (position_id,),
        ).fetchone()

    return dict(row) if row else None


def record_recommendation(position_id, recommendation, db_file=DB_FILE):
    initialize_trade_db(db_file)
    previous = latest_recommendation(position_id, db_file=db_file)

    if previous:
        same_score = int(previous["exit_score"]) == int(recommendation["exit_score"])
        same_action = previous["coach_action"] == recommendation["coach_action"]
        if same_score and same_action:
            return previous["id"]

    with connect(db_file) as connection:
        cursor = connection.execute(
            """
            INSERT INTO recommendations (
                position_id,
                timestamp,
                exit_score,
                exit_label,
                coach_action,
                coach_next_step,
                current_profit_percent,
                peak_profit_percent,
                profit_giveback_percent,
                reasons_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position_id,
                eastern_timestamp(),
                int(recommendation["exit_score"]),
                recommendation["exit_label"],
                recommendation["coach_action"],
                recommendation["coach_next_step"],
                recommendation.get("current_profit_percent"),
                recommendation.get("peak_profit_percent"),
                recommendation.get("profit_giveback_percent"),
                json.dumps(recommendation.get("exit_reasons", []), sort_keys=True),
            ),
        )
        return cursor.lastrowid


def load_recommendations(position_id=None, db_file=DB_FILE):
    initialize_trade_db(db_file)
    query = "SELECT * FROM recommendations"
    params = []

    if position_id:
        query += " WHERE position_id = ?"
        params.append(position_id)

    query += " ORDER BY timestamp DESC, id DESC"

    with connect(db_file) as connection:
        rows = connection.execute(query, params).fetchall()

    return [dict(row) for row in rows]
