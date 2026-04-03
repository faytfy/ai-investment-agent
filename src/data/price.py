"""yfinance price data fetcher."""

import time
from datetime import datetime
from typing import Optional

import yfinance as yf

from src.config import DB_PATH, WATCHLIST
from src.data.models import PriceBar, PriceHistory
from src.db.operations import upsert_prices
from src.utils.logger import get_logger, log_fetch

logger = get_logger("price")

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds


def fetch_price_history(ticker: str, period: str = "2y") -> Optional[PriceHistory]:
    """Fetch historical price data from yfinance.

    Args:
        ticker: Stock symbol (e.g., "TSM")
        period: yfinance period string (e.g., "2y", "1y", "6mo")

    Returns:
        PriceHistory with validated bars, or None on permanent failure.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with log_fetch(logger, ticker, "price_history") as ctx:
                stock = yf.Ticker(ticker)
                df = stock.history(period=period, auto_adjust=False)

                if df.empty:
                    logger.warning(f"No price data returned for {ticker}")
                    return PriceHistory(ticker=ticker, bars=[], period=period)

                bars = _dataframe_to_bars(df, ticker)
                ctx["records"] = len(bars)
                return PriceHistory(ticker=ticker, bars=bars, period=period)

        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed for {ticker}: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"All {MAX_RETRIES} attempts failed for {ticker}: {e}")
                return None

    return None


def fetch_current_quote(ticker: str) -> Optional[dict]:
    """Fetch the current quote for a ticker.

    Returns a dict with price, change, volume, or None on failure.
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            "ticker": ticker,
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "previous_close": info.get("previousClose"),
            "change_percent": info.get("regularMarketChangePercent"),
            "volume": info.get("regularMarketVolume"),
            "market_cap": info.get("marketCap"),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Failed to fetch quote for {ticker}: {e}")
        return None


def update_all_prices(period: str = "2y", db_path: Optional[str] = None) -> dict:
    """Fetch and store prices for all watchlist tickers.

    Returns a summary dict with successes, failures, and total records.
    """
    db = db_path or DB_PATH

    results = {"successes": [], "failures": [], "total_records": 0}

    for ticker in WATCHLIST:
        try:
            history = fetch_price_history(ticker, period)
            if history is None:
                results["failures"].append({"ticker": ticker, "reason": "fetch returned None"})
                continue

            if not history.is_empty:
                count = upsert_prices(ticker, history, db_path=db)
                results["total_records"] += count

            results["successes"].append({"ticker": ticker, "records": len(history.bars)})
            logger.info(f"[{len(results['successes'])}/{len(WATCHLIST)}] {ticker}: {len(history.bars)} bars")

        except Exception as e:
            logger.error(f"Unexpected error for {ticker}: {e}")
            results["failures"].append({"ticker": ticker, "reason": str(e)})

    logger.info(
        f"Price update complete: {len(results['successes'])} succeeded, "
        f"{len(results['failures'])} failed, {results['total_records']} total records"
    )
    return results


def _dataframe_to_bars(df, ticker: str) -> list[PriceBar]:
    """Convert a yfinance DataFrame to validated PriceBar list.

    Rows that fail validation are logged and skipped.
    """
    bars = []
    skipped = 0

    for idx, row in df.iterrows():
        try:
            bar = PriceBar(
                date=idx.date() if hasattr(idx, "date") else idx,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=int(row["Volume"]),
                adj_close=float(row["Adj Close"]) if "Adj Close" in row and row["Adj Close"] is not None else None,
            )
            bars.append(bar)
        except (ValueError, KeyError) as e:
            skipped += 1
            if skipped <= 3:
                logger.warning(f"Skipped invalid price row for {ticker} at {idx}: {e}")

    if skipped > 3:
        logger.warning(f"Skipped {skipped} total invalid rows for {ticker}")

    return bars
