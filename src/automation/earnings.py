"""Earnings calendar fetcher using yfinance.

Retrieves upcoming earnings dates for all watchlist tickers and stores them in the DB.
"""

import time
from datetime import date
from typing import Optional

import yfinance as yf

from src.config import WATCH_ONLY, WATCHLIST
from src.db.operations import upsert_earnings
from src.utils.logger import get_logger

logger = get_logger("automation.earnings")


def _fetch_earnings_date(ticker: str) -> Optional[date]:
    """Fetch the next earnings date for a single ticker via yfinance.

    Returns None if earnings date is unavailable or in the past.
    """
    try:
        stock = yf.Ticker(ticker)
        cal = stock.calendar
        if cal is None or (cal.empty if hasattr(cal, "empty") else not cal):
            return None

        # yfinance .calendar returns a dict or DataFrame depending on version
        if isinstance(cal, dict):
            earnings_date = cal.get("Earnings Date")
            if isinstance(earnings_date, list) and earnings_date:
                earnings_date = earnings_date[0]
        else:
            # DataFrame format
            if "Earnings Date" in cal.index:
                earnings_date = cal.loc["Earnings Date"].iloc[0]
            elif "Earnings Date" in cal.columns:
                earnings_date = cal["Earnings Date"].iloc[0]
            else:
                return None

        if earnings_date is None:
            return None

        # Convert to date object
        if hasattr(earnings_date, "date"):
            earnings_date = earnings_date.date()
        elif isinstance(earnings_date, str):
            earnings_date = date.fromisoformat(earnings_date)

        return earnings_date
    except Exception as e:
        logger.warning(f"Failed to fetch earnings date for {ticker}: {e}")
        return None


def refresh_earnings_calendar(db_path: Optional[str] = None) -> dict[str, Optional[date]]:
    """Fetch and store upcoming earnings dates for all watchlist tickers.

    Returns a dict of {ticker: earnings_date_or_none}.
    """
    kwargs = {"db_path": db_path} if db_path else {}
    all_tickers = {**WATCHLIST, **WATCH_ONLY}
    results: dict[str, Optional[date]] = {}

    for ticker in all_tickers:
        earnings_date = _fetch_earnings_date(ticker)
        results[ticker] = earnings_date

        if earnings_date is not None:
            upsert_earnings(ticker, earnings_date, **kwargs)
            logger.info(f"{ticker}: next earnings {earnings_date}")
        else:
            logger.debug(f"{ticker}: no earnings date available")

        time.sleep(0.5)  # be polite to yfinance

    fetched = sum(1 for d in results.values() if d is not None)
    logger.info(f"Earnings calendar refreshed: {fetched}/{len(all_tickers)} dates found")
    return results
