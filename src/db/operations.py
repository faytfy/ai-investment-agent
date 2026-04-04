"""Database read/write operations for the AI Investment Agent."""

import json
import sqlite3
from datetime import date, datetime
from typing import Optional

import pandas as pd

from src.config import DB_PATH, WATCH_ONLY, WATCHLIST
from src.data.models import (
    FundamentalsSnapshot,
    FilingContent,
    FilingInfo,
    FilingType,
    NewsArticle,
    NewsFeed,
    PriceBar,
    PriceHistory,
    StockInfo,
)
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


# --- Filing operations ---


def upsert_filing(
    filing: FilingInfo,
    content: Optional[FilingContent] = None,
    db_path: str = DB_PATH,
) -> None:
    """Store a filing's metadata and optional parsed content.

    If the filing already exists (by accession_number) and content is None,
    the existing content_json is preserved (not overwritten with NULL).
    """
    conn = get_connection(db_path)
    try:
        content_json = content.model_dump_json() if content else None

        # Check if filing already exists
        existing = conn.execute(
            "SELECT content_json FROM filings WHERE accession_number = ?",
            (filing.accession_number,),
        ).fetchone()

        if existing:
            # Update metadata; only overwrite content if new content is provided
            if content_json:
                conn.execute(
                    "UPDATE filings SET ticker=?, cik=?, filing_type=?, filed_date=?, "
                    "report_date=?, title=?, filing_url=?, content_json=? "
                    "WHERE accession_number=?",
                    (
                        filing.ticker, filing.cik, filing.filing_type.value,
                        filing.filed_date.isoformat(),
                        filing.report_date.isoformat() if filing.report_date else None,
                        filing.title, filing.filing_url, content_json,
                        filing.accession_number,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE filings SET ticker=?, cik=?, filing_type=?, filed_date=?, "
                    "report_date=?, title=?, filing_url=? "
                    "WHERE accession_number=?",
                    (
                        filing.ticker, filing.cik, filing.filing_type.value,
                        filing.filed_date.isoformat(),
                        filing.report_date.isoformat() if filing.report_date else None,
                        filing.title, filing.filing_url,
                        filing.accession_number,
                    ),
                )
        else:
            conn.execute(
                "INSERT INTO filings "
                "(ticker, cik, accession_number, filing_type, filed_date, "
                "report_date, title, filing_url, content_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    filing.ticker, filing.cik, filing.accession_number,
                    filing.filing_type.value, filing.filed_date.isoformat(),
                    filing.report_date.isoformat() if filing.report_date else None,
                    filing.title, filing.filing_url, content_json,
                ),
            )
        conn.commit()
        logger.info(f"Stored filing {filing.filing_type.value} for {filing.ticker} ({filing.accession_number})")
    finally:
        conn.close()


def get_filings(
    ticker: str,
    filing_type: Optional[FilingType] = None,
    limit: int = 10,
    db_path: str = DB_PATH,
) -> list[FilingInfo]:
    """Get recent filings for a ticker, optionally filtered by type."""
    conn = get_connection(db_path)
    try:
        query = "SELECT ticker, cik, accession_number, filing_type, filed_date, report_date, title, filing_url FROM filings WHERE ticker = ?"
        params: list = [ticker]

        if filing_type:
            query += " AND filing_type = ?"
            params.append(filing_type.value)

        query += " ORDER BY filed_date DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [
            FilingInfo(
                ticker=r["ticker"],
                cik=r["cik"],
                accession_number=r["accession_number"],
                filing_type=FilingType(r["filing_type"]),
                filed_date=date.fromisoformat(r["filed_date"]),
                report_date=date.fromisoformat(r["report_date"]) if r["report_date"] else None,
                title=r["title"],
                filing_url=r["filing_url"],
            )
            for r in rows
        ]
    finally:
        conn.close()


def get_filing_content(accession_number: str, db_path: str = DB_PATH) -> Optional[FilingContent]:
    """Get the parsed content for a specific filing."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT content_json FROM filings WHERE accession_number = ?",
            (accession_number,),
        ).fetchone()
        if row is None or row["content_json"] is None:
            return None
        return FilingContent.model_validate_json(row["content_json"])
    finally:
        conn.close()


# --- News operations ---


def upsert_news(articles: list[NewsArticle], db_path: str = DB_PATH) -> int:
    """Store news articles, deduplicating by (ticker, title, published_at). Returns count stored."""
    if not articles:
        return 0

    conn = get_connection(db_path)
    try:
        count = 0
        for article in articles:
            try:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO news_articles "
                    "(ticker, title, source, url, published_at, summary) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        article.ticker,
                        article.title,
                        article.source,
                        article.url,
                        article.published_at.isoformat(),
                        article.summary,
                    ),
                )
                if cursor.rowcount > 0:
                    count += 1
            except sqlite3.IntegrityError:
                pass  # duplicate, skip
        conn.commit()
        logger.info(f"Stored {count} news articles")
        return count
    finally:
        conn.close()


def get_news(
    ticker: str,
    limit: int = 50,
    since: Optional[datetime] = None,
    db_path: str = DB_PATH,
) -> list[NewsArticle]:
    """Get recent news articles for a ticker."""
    conn = get_connection(db_path)
    try:
        query = "SELECT ticker, title, source, url, published_at, summary FROM news_articles WHERE ticker = ?"
        params: list = [ticker]

        if since:
            query += " AND published_at >= ?"
            params.append(since.isoformat())

        query += " ORDER BY published_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [
            NewsArticle(
                ticker=r["ticker"],
                title=r["title"],
                source=r["source"],
                url=r["url"],
                published_at=datetime.fromisoformat(r["published_at"]),
                summary=r["summary"],
            )
            for r in rows
        ]
    finally:
        conn.close()


# --- Analysis report operations (for future sessions) ---


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
