"""SQLite storage for ETF identities and immutable decision evidence."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 1


class Database:
    """Own the small local database used by the V1 workflow.

    Market data is deliberately not stored here. It remains an external input so
    a selected data source can be replaced without changing decision history.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """Open, commit and explicitly close a SQLite connection."""
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS etf_identity (
                    exchange TEXT NOT NULL CHECK (exchange IN ('SSE', 'SZSE')),
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    tracking_target TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    passive_tracking INTEGER NOT NULL CHECK (passive_tracking IN (0, 1)),
                    listing_date TEXT,
                    source_name TEXT NOT NULL,
                    source_url TEXT,
                    source_as_of TEXT NOT NULL,
                    source_record_id TEXT,
                    imported_at TEXT NOT NULL,
                    PRIMARY KEY (exchange, code)
                );

                CREATE TABLE IF NOT EXISTS decision_event (
                    event_id TEXT PRIMARY KEY,
                    subject_type TEXT NOT NULL CHECK (subject_type IN ('ETF', 'DIRECTION', 'STRATEGY')),
                    subject_key TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    rule_version TEXT,
                    evidence_json TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_decision_subject
                ON decision_event(subject_type, subject_key, created_at);

                CREATE TABLE IF NOT EXISTS rule_set (
                    version TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    rules_json TEXT NOT NULL,
                    registered_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS market_daily (
                    exchange TEXT NOT NULL CHECK (exchange IN ('SSE', 'SZSE')),
                    code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL,
                    amount REAL,
                    adjustment TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_url TEXT,
                    source_as_of TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    PRIMARY KEY (exchange, code, trade_date, adjustment)
                );

                CREATE INDEX IF NOT EXISTS idx_market_daily_series
                ON market_daily(exchange, code, adjustment, trade_date);

                CREATE TABLE IF NOT EXISTS investment_plan (
                    direction_key TEXT PRIMARY KEY,
                    exchange TEXT NOT NULL,
                    code TEXT NOT NULL,
                    strategy TEXT NOT NULL CHECK (strategy IN ('DCA', 'DCA_GRID', 'OBSERVE')),
                    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'OBSERVE', 'STOP_ADDING')),
                    base_amount REAL,
                    frequency TEXT,
                    next_execution_date TEXT,
                    cash_reserve REAL NOT NULL DEFAULT 0,
                    rule_version TEXT,
                    note TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(exchange, code) REFERENCES etf_identity(exchange, code)
                );

                CREATE TABLE IF NOT EXISTS holding (
                    account TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    code TEXT NOT NULL,
                    quantity REAL NOT NULL CHECK (quantity >= 0),
                    average_cost REAL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(account, exchange, code),
                    FOREIGN KEY(exchange, code) REFERENCES etf_identity(exchange, code)
                );

                CREATE TABLE IF NOT EXISTS execution_record (
                    execution_id TEXT PRIMARY KEY,
                    plan_direction_key TEXT,
                    account TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    code TEXT NOT NULL,
                    executed_date TEXT NOT NULL,
                    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
                    quantity REAL,
                    amount REAL,
                    price REAL,
                    note TEXT,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY(plan_direction_key) REFERENCES investment_plan(direction_key)
                );
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
