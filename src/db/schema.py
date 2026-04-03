"""SQLite database schema for the AI Investment Agent."""

import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stocks (
    ticker TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    layer TEXT NOT NULL,
    tier INTEGER NOT NULL CHECK (tier IN (0, 1, 2)),
    watch_only INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL NOT NULL CHECK (open > 0),
    high REAL NOT NULL CHECK (high > 0),
    low REAL NOT NULL CHECK (low > 0),
    close REAL NOT NULL CHECK (close > 0),
    volume INTEGER NOT NULL CHECK (volume >= 0),
    adj_close REAL,
    PRIMARY KEY (ticker, date),
    FOREIGN KEY (ticker) REFERENCES stocks(ticker)
);

CREATE TABLE IF NOT EXISTS fundamentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    data_json TEXT NOT NULL,
    FOREIGN KEY (ticker) REFERENCES stocks(ticker)
);

CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker_date
    ON fundamentals(ticker, fetched_at DESC);

CREATE TABLE IF NOT EXISTS analysis_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    date TEXT NOT NULL,
    report_json TEXT NOT NULL,
    signal TEXT CHECK (signal IN ('bullish', 'bearish', 'neutral')),
    confidence REAL CHECK (confidence >= 0 AND confidence <= 1),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticker) REFERENCES stocks(ticker)
);

CREATE INDEX IF NOT EXISTS idx_reports_ticker_agent
    ON analysis_reports(ticker, agent_name, date DESC);
"""


def create_tables(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist."""
    conn.executescript(SCHEMA_SQL)
