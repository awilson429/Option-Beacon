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
                reasons_json TEXT NOT NULL,
                FOREIGN KEY(position_id) REFERENCES positions(id)
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


def load_closed_positions(db_file=DB_FILE):
    return load_positions(status="CLOSED", db_file=db_file)


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
                reasons_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position_id,
                eastern_timestamp(),
                int(recommendation["exit_score"]),
                recommendation["exit_label"],
                recommendation["coach_action"],
                recommendation["coach_next_step"],
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
