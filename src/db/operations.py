"""Database read/write operations for the AI Investment Agent."""

import json
import sqlite3
from datetime import date, datetime
from typing import Optional

import pandas as pd

from src.config import DB_PATH, WATCH_ONLY, WATCHLIST
from src.data.models import FundamentalsSnapshot, PriceBar, PriceHistory, StockInfo
from src.db.schema import create_tables
from src.utils.logger import get_logger

logger = get_logger("db")


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Get a database connection with row factory enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """Create tables and seed the stocks table from the watchlist."""
    conn = get_connection(db_path)
    try:
        create_tables(conn)
        _seed_stocks(conn)
        conn.commit()
        logger.info("Database initialized successfully")
    finally:
        conn.close()


def _seed_stocks(conn: sqlite3.Connection) -> None:
    """Insert watchlist stocks if they don't already exist."""
    for ticker, info in WATCHLIST.items():
        conn.execute(
            "INSERT OR IGNORE INTO stocks (ticker, name, layer, tier, watch_only) "
            "VALUES (?, ?, ?, ?, 0)",
            (ticker, info["name"], info["layer"], info["tier"]),
        )
    for ticker, info in WATCH_ONLY.items():
        conn.execute(
            "INSERT OR IGNORE INTO stocks (ticker, name, layer, tier, watch_only) "
            "VALUES (?, ?, ?, ?, 1)",
            (ticker, info["name"], info["layer"], 0),
        )


def get_stocks(db_path: str = DB_PATH, include_watch_only: bool = False) -> list[StockInfo]:
    """Get all active stocks from the database."""
    conn = get_connection(db_path)
    try:
        query = "SELECT ticker, name, layer, tier FROM stocks WHERE watch_only = 0"
        if include_watch_only:
            query = "SELECT ticker, name, layer, tier FROM stocks"
        rows = conn.execute(query).fetchall()
        return [StockInfo(ticker=r["ticker"], name=r["name"], layer=r["layer"], tier=r["tier"]) for r in rows]
    finally:
        conn.close()


# --- Price operations ---


def upsert_prices(ticker: str, history: PriceHistory, db_path: str = DB_PATH) -> int:
    """Bulk upsert price bars for a ticker. Returns number of rows written."""
    if history.is_empty:
        return 0

    conn = get_connection(db_path)
    try:
        rows = [
            (ticker, bar.date.isoformat(), bar.open, bar.high, bar.low,
             bar.close, bar.volume, bar.adj_close)
            for bar in history.bars
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO prices "
            "(ticker, date, open, high, low, close, volume, adj_close) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        count = len(rows)
        logger.info(f"Upserted {count} price rows for {ticker}")
        return count
    finally:
        conn.close()


def get_prices(
    ticker: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
    db_path: str = DB_PATH,
) -> PriceHistory:
    """Read price history for a ticker, optionally filtered by date range."""
    conn = get_connection(db_path)
    try:
        query = "SELECT date, open, high, low, close, volume, adj_close FROM prices WHERE ticker = ?"
        params: list = [ticker]

        if start:
            query += " AND date >= ?"
            params.append(start.isoformat())
        if end:
            query += " AND date <= ?"
            params.append(end.isoformat())

        query += " ORDER BY date ASC"
        rows = conn.execute(query, params).fetchall()

        bars = [
            PriceBar(
                date=date.fromisoformat(r["date"]),
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
                adj_close=r["adj_close"],
            )
            for r in rows
        ]
        return PriceHistory(ticker=ticker, bars=bars)
    finally:
        conn.close()


def get_prices_df(
    ticker: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
    db_path: str = DB_PATH,
) -> pd.DataFrame:
    """Read price history as a pandas DataFrame (convenience for analysis)."""
    history = get_prices(ticker, start, end, db_path)
    if history.is_empty:
        return pd.DataFrame()
    return pd.DataFrame([bar.model_dump() for bar in history.bars]).set_index("date")


# --- Fundamentals operations ---


def upsert_fundamentals(snapshot: FundamentalsSnapshot, db_path: str = DB_PATH) -> None:
    """Store a fundamentals snapshot as JSON."""
    conn = get_connection(db_path)
    try:
        data_json = snapshot.model_dump_json()
        conn.execute(
            "INSERT INTO fundamentals (ticker, fetched_at, data_json) VALUES (?, ?, ?)",
            (snapshot.ticker, snapshot.fetched_at.isoformat(), data_json),
        )
        conn.commit()
        logger.info(f"Stored fundamentals snapshot for {snapshot.ticker}")
    finally:
        conn.close()


def get_latest_fundamentals(ticker: str, db_path: str = DB_PATH) -> Optional[FundamentalsSnapshot]:
    """Get the most recent fundamentals snapshot for a ticker."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT data_json FROM fundamentals WHERE ticker = ? ORDER BY fetched_at DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        if row is None:
            return None
        return FundamentalsSnapshot.model_validate_json(row["data_json"])
    finally:
        conn.close()


# --- Analysis report operations (for future sessions) ---


def save_report(
    ticker: str,
    agent_name: str,
    report_date: date,
    report: dict,
    signal: str,
    confidence: float,
    db_path: str = DB_PATH,
) -> None:
    """Save an analysis report."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO analysis_reports "
            "(ticker, agent_name, date, report_json, signal, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ticker, agent_name, report_date.isoformat(), json.dumps(report), signal, confidence),
        )
        conn.commit()
        logger.info(f"Saved {agent_name} report for {ticker}: {signal} ({confidence:.2f})")
    finally:
        conn.close()


def get_reports(
    ticker: str,
    agent_name: Optional[str] = None,
    limit: int = 10,
    db_path: str = DB_PATH,
) -> list[dict]:
    """Get recent analysis reports for a ticker."""
    conn = get_connection(db_path)
    try:
        query = "SELECT agent_name, date, report_json, signal, confidence FROM analysis_reports WHERE ticker = ?"
        params: list = [ticker]

        if agent_name:
            query += " AND agent_name = ?"
            params.append(agent_name)

        query += " ORDER BY date DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [
            {
                "agent_name": r["agent_name"],
                "date": r["date"],
                "report": json.loads(r["report_json"]),
                "signal": r["signal"],
                "confidence": r["confidence"],
            }
            for r in rows
        ]
    finally:
        conn.close()
