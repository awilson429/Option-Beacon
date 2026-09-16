"""Append-only RESEARCH persistence for the translation flight recorder.

Tables are created additively with CREATE TABLE IF NOT EXISTS. They never rewrite
authoritative trading rows. THE FLIGHT RECORDER DOES NOT MAKE TRADING DECISIONS.
"""

from __future__ import annotations

import hashlib
import json
import logging

from translation_research import CAPTURE_PRODUCTION_FILL, RESEARCH_VERSION


LOGGER = logging.getLogger(__name__)


class TranslationResearchRepository:
    def __init__(self, repository, *, initialize=True):
        self.repository = repository
        if initialize:
            self.initialize()

    def initialize(self):
        with self.repository.connection() as connection:
            for ddl in (
                """CREATE TABLE IF NOT EXISTS translation_research_captures (
                    capture_id TEXT PRIMARY KEY,
                    research_version TEXT NOT NULL,
                    lane_role TEXT NOT NULL,
                    capture_reason TEXT NOT NULL,
                    opportunity_id TEXT NOT NULL,
                    authoritative_trade_id TEXT,
                    authoritative_event_id TEXT,
                    scan_cycle_id TEXT,
                    paper_trade_id TEXT,
                    symbol TEXT NOT NULL,
                    direction TEXT,
                    capture_result TEXT NOT NULL,
                    rejection_reason TEXT,
                    candidate_count INTEGER,
                    eligible_candidate_count INTEGER,
                    selected_option_symbol TEXT,
                    production_option_symbol TEXT,
                    production_fill REAL,
                    production_realistic_entry REAL,
                    underlying_price REAL,
                    underlying_timestamp TEXT,
                    requested_at TEXT NOT NULL,
                    provider_responded_at TEXT,
                    persisted_at TEXT NOT NULL,
                    trade_entered_at TEXT,
                    elapsed_from_trade_entered_seconds REAL,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(research_version, opportunity_id, capture_reason)
                )""",
                """CREATE TABLE IF NOT EXISTS translation_research_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    capture_id TEXT NOT NULL,
                    opportunity_id TEXT NOT NULL,
                    research_version TEXT NOT NULL,
                    option_symbol TEXT,
                    expiration TEXT,
                    strike REAL,
                    option_type TEXT,
                    bid REAL,
                    ask REAL,
                    mid REAL,
                    bid_size REAL,
                    ask_size REAL,
                    volume INTEGER,
                    open_interest INTEGER,
                    delta REAL,
                    implied_volatility REAL,
                    gamma REAL,
                    theta REAL,
                    dte INTEGER,
                    quote_timestamp TEXT,
                    passed_selector_eligibility INTEGER,
                    rejection_reason TEXT,
                    selector_rank INTEGER,
                    selector_key_json TEXT,
                    is_selector_choice INTEGER NOT NULL,
                    is_production_selected INTEGER NOT NULL,
                    UNIQUE(capture_id, option_symbol)
                )""",
                """CREATE TABLE IF NOT EXISTS translation_research_marks (
                    mark_id TEXT PRIMARY KEY,
                    research_version TEXT NOT NULL,
                    lane_role TEXT NOT NULL,
                    opportunity_id TEXT,
                    paper_trade_id TEXT NOT NULL,
                    scan_cycle_id TEXT,
                    symbol TEXT,
                    option_symbol TEXT,
                    recorded_at TEXT NOT NULL,
                    bid REAL,
                    ask REAL,
                    mid REAL,
                    last REAL,
                    quote_timestamp TEXT,
                    provider_timestamp TEXT,
                    quote_age_seconds REAL,
                    volume INTEGER,
                    open_interest INTEGER,
                    delta REAL,
                    implied_volatility REAL,
                    gamma REAL,
                    theta REAL,
                    underlying_price REAL,
                    underlying_timestamp TEXT,
                    entry_price REAL,
                    current_return_pct REAL,
                    trade_status TEXT,
                    lifecycle_state TEXT,
                    management_state_json TEXT NOT NULL,
                    UNIQUE(research_version, paper_trade_id, recorded_at)
                )""",
                "CREATE INDEX IF NOT EXISTS idx_translation_research_captures_opportunity "
                "ON translation_research_captures(opportunity_id, capture_reason)",
                "CREATE INDEX IF NOT EXISTS idx_translation_research_captures_persisted "
                "ON translation_research_captures(persisted_at)",
                "CREATE INDEX IF NOT EXISTS idx_translation_research_candidates_opportunity "
                "ON translation_research_candidates(opportunity_id)",
                "CREATE INDEX IF NOT EXISTS idx_translation_research_candidates_symbol "
                "ON translation_research_candidates(option_symbol)",
                "CREATE INDEX IF NOT EXISTS idx_translation_research_marks_opportunity "
                "ON translation_research_marks(opportunity_id, recorded_at)",
                "CREATE INDEX IF NOT EXISTS idx_translation_research_marks_trade "
                "ON translation_research_marks(paper_trade_id, recorded_at)",
            ):
                self.repository._execute(connection, ddl).close()

    def get_capture(self, opportunity_id, capture_reason, *, research_version=RESEARCH_VERSION):
        with self.repository.connection() as connection:
            return self.repository._fetchone(
                connection,
                """SELECT * FROM translation_research_captures
                   WHERE research_version=? AND opportunity_id=? AND capture_reason=?""",
                (research_version, opportunity_id, capture_reason),
            )

    def record_capture(self, record):
        existing = self.get_capture(record["opportunity_id"], record["capture_reason"])
        if existing:
            if record.get("candidates") and not self.candidates(existing["capture_id"]):
                with self.repository.connection() as connection:
                    for candidate in record.get("candidates") or []:
                        self._insert_candidate(connection, {**record, "capture_id": existing["capture_id"]}, candidate)
            return existing
        values = (
            record["capture_id"], record["research_version"], record["lane_role"],
            record["capture_reason"], record["opportunity_id"], record.get("authoritative_trade_id"),
            record.get("authoritative_event_id"), record.get("scan_cycle_id"),
            record.get("paper_trade_id"), record["symbol"], record.get("direction"),
            record["capture_result"], record.get("rejection_reason"),
            record.get("candidate_count"), record.get("eligible_candidate_count"),
            record.get("selected_option_symbol"), record.get("production_option_symbol"),
            record.get("production_fill"), record.get("production_realistic_entry"),
            record.get("underlying_price"), record.get("underlying_timestamp"),
            record["requested_at"], record.get("provider_responded_at"), record["persisted_at"],
            record.get("trade_entered_at"), record.get("elapsed_from_trade_entered_seconds"),
            record.get("metadata_json") or "{}",
        )
        with self.repository.connection() as connection:
            self.repository._execute(
                connection,
                """INSERT INTO translation_research_captures (
                    capture_id, research_version, lane_role, capture_reason, opportunity_id,
                    authoritative_trade_id, authoritative_event_id, scan_cycle_id, paper_trade_id,
                    symbol, direction, capture_result, rejection_reason, candidate_count,
                    eligible_candidate_count, selected_option_symbol, production_option_symbol,
                    production_fill, production_realistic_entry, underlying_price,
                    underlying_timestamp, requested_at, provider_responded_at, persisted_at,
                    trade_entered_at, elapsed_from_trade_entered_seconds, metadata_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(research_version, opportunity_id, capture_reason) DO NOTHING""",
                values,
            ).close()
            for candidate in record.get("candidates") or []:
                self._insert_candidate(connection, record, candidate)
        return self.get_capture(record["opportunity_id"], record["capture_reason"])

    def enrich_fill(self, opportunity_id, *, production_fill, production_realistic_entry,
                    paper_trade_id, now=None):
        with self.repository.connection() as connection:
            self.repository._execute(
                connection,
                """UPDATE translation_research_captures
                   SET production_fill=?, production_realistic_entry=?, paper_trade_id=?
                   WHERE research_version=? AND opportunity_id=? AND capture_reason=?
                     AND production_fill IS NULL""",
                (
                    production_fill, production_realistic_entry, paper_trade_id,
                    RESEARCH_VERSION, opportunity_id, CAPTURE_PRODUCTION_FILL,
                ),
            ).close()
        return self.get_capture(opportunity_id, CAPTURE_PRODUCTION_FILL)

    def record_mark(self, record):
        values = (
            record["mark_id"], record["research_version"], record["lane_role"],
            record.get("opportunity_id"), record["paper_trade_id"], record.get("scan_cycle_id"),
            record.get("symbol"), record.get("option_symbol"), record["recorded_at"],
            record.get("bid"), record.get("ask"), record.get("mid"), record.get("last"),
            record.get("quote_timestamp"), record.get("provider_timestamp"),
            record.get("quote_age_seconds"), record.get("volume"), record.get("open_interest"),
            record.get("delta"), record.get("implied_volatility"), record.get("gamma"),
            record.get("theta"), record.get("underlying_price"), record.get("underlying_timestamp"),
            record.get("entry_price"), record.get("current_return_pct"),
            record.get("trade_status"), record.get("lifecycle_state"),
            record.get("management_state_json") or "{}",
        )
        with self.repository.connection() as connection:
            self.repository._execute(
                connection,
                """INSERT INTO translation_research_marks (
                    mark_id, research_version, lane_role, opportunity_id, paper_trade_id,
                    scan_cycle_id, symbol, option_symbol, recorded_at, bid, ask, mid, last,
                    quote_timestamp, provider_timestamp, quote_age_seconds, volume, open_interest,
                    delta, implied_volatility, gamma, theta, underlying_price, underlying_timestamp,
                    entry_price, current_return_pct, trade_status, lifecycle_state,
                    management_state_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(research_version, paper_trade_id, recorded_at) DO NOTHING""",
                values,
            ).close()
        return self.get_mark(record["paper_trade_id"], record["recorded_at"])

    def get_mark(self, paper_trade_id, recorded_at, *, research_version=RESEARCH_VERSION):
        with self.repository.connection() as connection:
            return self.repository._fetchone(
                connection,
                """SELECT * FROM translation_research_marks
                   WHERE research_version=? AND paper_trade_id=? AND recorded_at=?""",
                (research_version, paper_trade_id, recorded_at),
            )

    def captures(
        self, *, opportunity_id=None, capture_reason=None, research_version=RESEARCH_VERSION,
        option_symbol=None, session_date=None, limit=500,
    ):
        clauses = ["research_version=?"]
        params = [research_version]
        if opportunity_id:
            clauses.append("opportunity_id=?")
            params.append(opportunity_id)
        if capture_reason:
            clauses.append("capture_reason=?")
            params.append(capture_reason)
        if option_symbol:
            clauses.append("(selected_option_symbol=? OR production_option_symbol=?)")
            params.extend([option_symbol, option_symbol])
        if session_date:
            clauses.append("persisted_at LIKE ?")
            params.append(f"{session_date}%")
        query = (
            "SELECT * FROM translation_research_captures WHERE "
            + " AND ".join(clauses)
            + " ORDER BY persisted_at, capture_reason LIMIT ?"
        )
        params.append(int(limit))
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, query, tuple(params))

    def candidates(self, capture_id):
        with self.repository.connection() as connection:
            return self.repository._fetchall(
                connection,
                """SELECT * FROM translation_research_candidates
                   WHERE capture_id=? ORDER BY selector_rank, option_symbol""",
                (capture_id,),
            )

    def candidates_for_opportunity(self, opportunity_id, *, research_version=RESEARCH_VERSION):
        with self.repository.connection() as connection:
            return self.repository._fetchall(
                connection,
                """SELECT * FROM translation_research_candidates
                   WHERE opportunity_id=? AND research_version=?
                   ORDER BY capture_id, selector_rank""",
                (opportunity_id, research_version),
            )

    def marks(
        self, *, opportunity_id=None, paper_trade_id=None, option_symbol=None,
        research_version=RESEARCH_VERSION, limit=5000,
    ):
        clauses = ["research_version=?"]
        params = [research_version]
        if opportunity_id:
            clauses.append("opportunity_id=?")
            params.append(opportunity_id)
        if paper_trade_id:
            clauses.append("paper_trade_id=?")
            params.append(paper_trade_id)
        if option_symbol:
            clauses.append("option_symbol=?")
            params.append(option_symbol)
        query = (
            "SELECT * FROM translation_research_marks WHERE "
            + " AND ".join(clauses)
            + " ORDER BY recorded_at LIMIT ?"
        )
        params.append(int(limit))
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, query, tuple(params))

    def opportunity_ids_for_paper_trades(self, trade_ids):
        identities = [str(value) for value in trade_ids or [] if value]
        if not identities:
            return {}
        placeholders = ",".join("?" * len(identities))
        with self.repository.connection() as connection:
            rows = self.repository._fetchall(
                connection,
                f"""SELECT trade_id, source_signal_id, opportunity_id
                    FROM paper_execution_trades WHERE trade_id IN ({placeholders})""",
                tuple(identities),
            )
        return {
            row["trade_id"]: row.get("opportunity_id") or row.get("source_signal_id")
            for row in rows
        }

    def _insert_candidate(self, connection, capture, candidate):
        option_symbol = candidate.get("option_symbol")
        identity = f"{capture['capture_id']}|{option_symbol or hashlib.sha256(json.dumps(candidate, sort_keys=True, default=str).encode()).hexdigest()[:16]}"
        candidate_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        values = (
            candidate_id, capture["capture_id"], capture["opportunity_id"],
            capture["research_version"], option_symbol, candidate.get("expiration"),
            candidate.get("strike"), candidate.get("option_type"), candidate.get("bid"),
            candidate.get("ask"), candidate.get("mid"), candidate.get("bid_size"),
            candidate.get("ask_size"), candidate.get("volume"), candidate.get("open_interest"),
            candidate.get("delta"), candidate.get("implied_volatility"), candidate.get("gamma"),
            candidate.get("theta"), candidate.get("dte"), candidate.get("quote_timestamp"),
            candidate.get("passed_selector_eligibility"), candidate.get("rejection_reason"),
            candidate.get("selector_rank"), candidate.get("selector_key_json"),
            int(candidate.get("is_selector_choice") or 0),
            int(candidate.get("is_production_selected") or 0),
        )
        self.repository._execute(
            connection,
            """INSERT INTO translation_research_candidates (
                candidate_id, capture_id, opportunity_id, research_version, option_symbol,
                expiration, strike, option_type, bid, ask, mid, bid_size, ask_size, volume,
                open_interest, delta, implied_volatility, gamma, theta, dte, quote_timestamp,
                passed_selector_eligibility, rejection_reason, selector_rank, selector_key_json,
                is_selector_choice, is_production_selected
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(capture_id, option_symbol) DO NOTHING""",
            values,
        ).close()
