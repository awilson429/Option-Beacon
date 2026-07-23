import json
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo


DB_FILE = "optionbeacon_trades.db"


POSITION_COLUMNS = {
    "current_premium": "REAL",
    "peak_premium": "REAL",
    "partial_1_taken": "INTEGER DEFAULT 0",
    "partial_2_taken": "INTEGER DEFAULT 0",
    "outcome_tag": "TEXT",
    "lessons_learned": "TEXT",
    "setup_grade": "TEXT",
    "management_grade": "TEXT",
    "rule_following_score": "INTEGER",
}

RECOMMENDATION_COLUMNS = {
    "current_profit_percent": "REAL",
    "peak_profit_percent": "REAL",
    "profit_giveback_percent": "REAL",
    "suggested_stop": "REAL",
    "suggested_stop_reason": "TEXT",
}


def eastern_timestamp():
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %I:%M:%S %p ET")


def database_url():
    value = os.getenv("DATABASE_URL")
    if value:
        return value

    try:
        import streamlit as st

        return st.secrets.get("DATABASE_URL", "")
    except Exception:
        return ""


def using_postgres(db_file=DB_FILE):
    return db_file == DB_FILE and bool(database_url())


def connect(db_file=DB_FILE):
    if using_postgres(db_file):
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
        except ImportError as exc:
            raise RuntimeError(
                "DATABASE_URL is configured, but psycopg2-binary is not installed."
            ) from exc

        url = database_url()
        kwargs = {"cursor_factory": RealDictCursor}
        if "sslmode=" not in url:
            kwargs["sslmode"] = "require"

        return psycopg2.connect(url, **kwargs)

    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    return connection


def is_postgres_connection(connection):
    return connection.__class__.__module__.startswith("psycopg2")


def normalize_sql(connection, sql):
    if is_postgres_connection(connection):
        return sql.replace("?", "%s")
    return sql


def fetchall(connection, sql, params=()):
    cursor = connection.cursor()
    cursor.execute(normalize_sql(connection, sql), params)
    rows = cursor.fetchall()
    cursor.close()

    return [dict(row) for row in rows]


def fetchone(connection, sql, params=()):
    cursor = connection.cursor()
    cursor.execute(normalize_sql(connection, sql), params)
    row = cursor.fetchone()
    cursor.close()

    return dict(row) if row else None


def execute(connection, sql, params=()):
    cursor = connection.cursor()
    cursor.execute(normalize_sql(connection, sql), params)
    return cursor


def ensure_position_columns(connection):
    if is_postgres_connection(connection):
        existing_columns = {
            row["column_name"]
            for row in fetchall(
                connection,
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'positions'
                """,
            )
        }
    else:
        existing_columns = {
            row["name"]
            for row in fetchall(connection, "PRAGMA table_info(positions)")
        }

    for column, column_type in POSITION_COLUMNS.items():
        if column not in existing_columns:
            execute(connection, f"ALTER TABLE positions ADD COLUMN {column} {column_type}")


def ensure_recommendation_columns(connection):
    if is_postgres_connection(connection):
        existing_columns = {
            row["column_name"]
            for row in fetchall(
                connection,
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'recommendations'
                """,
            )
        }
    else:
        existing_columns = {
            row["name"]
            for row in fetchall(connection, "PRAGMA table_info(recommendations)")
        }

    for column, column_type in RECOMMENDATION_COLUMNS.items():
        if column not in existing_columns:
            execute(connection, f"ALTER TABLE recommendations ADD COLUMN {column} {column_type}")


def initialize_trade_db(db_file=DB_FILE):
    with connect(db_file) as connection:
        position_id_type = "SERIAL PRIMARY KEY" if is_postgres_connection(connection) else "INTEGER PRIMARY KEY AUTOINCREMENT"
        recommendation_id_type = position_id_type
        execute(
            connection,
            """
            CREATE TABLE IF NOT EXISTS positions (
                id {position_id_type},
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
                exit_notes TEXT,
                outcome_tag TEXT,
                lessons_learned TEXT,
                setup_grade TEXT,
                management_grade TEXT,
                rule_following_score INTEGER
            )
            """.format(position_id_type=position_id_type),
        )
        ensure_position_columns(connection)
        execute(
            connection,
            """
            CREATE TABLE IF NOT EXISTS recommendations (
                id {recommendation_id_type},
                position_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                exit_score INTEGER NOT NULL,
                exit_label TEXT NOT NULL,
                coach_action TEXT NOT NULL,
                coach_next_step TEXT NOT NULL,
                current_profit_percent REAL,
                peak_profit_percent REAL,
                profit_giveback_percent REAL,
                suggested_stop REAL,
                suggested_stop_reason TEXT,
                reasons_json TEXT NOT NULL,
                FOREIGN KEY(position_id) REFERENCES positions(id)
            )
            """.format(recommendation_id_type=recommendation_id_type),
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
        returning = " RETURNING id" if is_postgres_connection(connection) else ""
        cursor = execute(
            connection,
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
            """ + returning,
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
        if is_postgres_connection(connection):
            row = cursor.fetchone()
            cursor.close()
            return row["id"]

        lastrowid = cursor.lastrowid
        cursor.close()
        return lastrowid


def load_positions(status=None, db_file=DB_FILE):
    initialize_trade_db(db_file)
    query = "SELECT * FROM positions"
    params = []

    if status:
        query += " WHERE status = ?"
        params.append(status)

    query += " ORDER BY entered_at DESC, id DESC"

    with connect(db_file) as connection:
        rows = fetchall(connection, query, params)

    return rows


def load_open_positions(db_file=DB_FILE):
    return load_positions(status="OPEN", db_file=db_file)


def load_closed_positions(db_file=DB_FILE):
    return load_positions(status="CLOSED", db_file=db_file)


def close_position(
    position_id,
    exit_premium=None,
    exit_notes="",
    outcome_tag="Unreviewed",
    lessons_learned="",
    setup_grade="Unreviewed",
    management_grade="Unreviewed",
    rule_following_score=None,
    db_file=DB_FILE,
):
    initialize_trade_db(db_file)
    position = load_position(position_id, db_file=db_file)
    peak_premium = position.get("peak_premium") if position else None
    current_premium = exit_premium
    if current_premium is None and position:
        current_premium = position.get("current_premium")

    if exit_premium and (not peak_premium or exit_premium > peak_premium):
        peak_premium = exit_premium

    with connect(db_file) as connection:
        execute(
            connection,
            """
            UPDATE positions
            SET status = ?,
                closed_at = ?,
                current_premium = ?,
                peak_premium = ?,
                exit_premium = ?,
                exit_notes = ?,
                outcome_tag = ?,
                lessons_learned = ?,
                setup_grade = ?,
                management_grade = ?,
                rule_following_score = ?
            WHERE id = ?
            """,
            (
                "CLOSED",
                eastern_timestamp(),
                current_premium,
                peak_premium,
                exit_premium,
                exit_notes,
                outcome_tag,
                lessons_learned,
                setup_grade,
                management_grade,
                rule_following_score,
                position_id,
            ),
        )


def load_position(position_id, db_file=DB_FILE):
    initialize_trade_db(db_file)
    with connect(db_file) as connection:
        return fetchone(
            connection,
            "SELECT * FROM positions WHERE id = ?",
            (position_id,),
        )


def update_position_premium(position_id, current_premium, db_file=DB_FILE):
    initialize_trade_db(db_file)
    position = load_position(position_id, db_file=db_file)
    if not position:
        return None

    current_premium = float(current_premium)
    previous_peak = position.get("peak_premium") or position.get("entry_premium") or 0
    peak_premium = max(float(previous_peak or 0), current_premium)

    with connect(db_file) as connection:
        execute(
            connection,
            """
            UPDATE positions
            SET current_premium = ?, peak_premium = ?
            WHERE id = ?
            """,
            (current_premium, peak_premium, position_id),
        )

    return load_position(position_id, db_file=db_file)


def update_position_stop(position_id, current_stop, db_file=DB_FILE):
    initialize_trade_db(db_file)
    with connect(db_file) as connection:
        execute(
            connection,
            """
            UPDATE positions
            SET current_stop = ?
            WHERE id = ?
            """,
            (float(current_stop), position_id),
        )

    return load_position(position_id, db_file=db_file)


def mark_partial_profit(position_id, partial_level, taken=True, db_file=DB_FILE):
    initialize_trade_db(db_file)
    if partial_level not in (1, 2):
        raise ValueError("partial_level must be 1 or 2")

    column = f"partial_{partial_level}_taken"
    with connect(db_file) as connection:
        execute(
            connection,
            f"""
            UPDATE positions
            SET {column} = ?
            WHERE id = ?
            """,
            (1 if taken else 0, position_id),
        )

    return load_position(position_id, db_file=db_file)


def latest_recommendation(position_id, db_file=DB_FILE):
    initialize_trade_db(db_file)
    with connect(db_file) as connection:
        return fetchone(
            connection,
            """
            SELECT * FROM recommendations
            WHERE position_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (position_id,),
        )


def record_recommendation(position_id, recommendation, db_file=DB_FILE):
    initialize_trade_db(db_file)
    previous = latest_recommendation(position_id, db_file=db_file)

    if previous:
        same_score = int(previous["exit_score"]) == int(recommendation["exit_score"])
        same_action = previous["coach_action"] == recommendation["coach_action"]
        same_stop = previous.get("suggested_stop") == recommendation.get("suggested_stop")
        if same_score and same_action and same_stop:
            return previous["id"]

    with connect(db_file) as connection:
        returning = " RETURNING id" if is_postgres_connection(connection) else ""
        cursor = execute(
            connection,
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
                suggested_stop,
                suggested_stop_reason,
                reasons_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """ + returning,
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
                recommendation.get("suggested_stop"),
                recommendation.get("suggested_stop_reason"),
                json.dumps(recommendation.get("exit_reasons", []), sort_keys=True),
            ),
        )
        if is_postgres_connection(connection):
            row = cursor.fetchone()
            cursor.close()
            return row["id"]

        lastrowid = cursor.lastrowid
        cursor.close()
        return lastrowid


def load_recommendations(position_id=None, db_file=DB_FILE):
    initialize_trade_db(db_file)
    query = "SELECT * FROM recommendations"
    params = []

    if position_id:
        query += " WHERE position_id = ?"
        params.append(position_id)

    query += " ORDER BY timestamp DESC, id DESC"

    with connect(db_file) as connection:
        rows = fetchall(connection, query, params)

    return rows
