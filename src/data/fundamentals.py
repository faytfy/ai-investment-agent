"""yfinance fundamentals data fetcher."""

import time
from datetime import datetime
from typing import Optional

import yfinance as yf

from src.config import DB_PATH, WATCHLIST
from src.data.models import FundamentalsSnapshot
from src.db.operations import upsert_fundamentals
from src.utils.logger import get_logger, log_fetch

logger = get_logger("fundamentals")

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2


def fetch_fundamentals(ticker: str) -> Optional[FundamentalsSnapshot]:
    """Fetch fundamental data from yfinance for a single ticker.

    Pulls from yf.Ticker.info, which aggregates financials, ratios,
    analyst targets, and market data. Fields that aren't available
    for a given ticker are left as None.

    Returns FundamentalsSnapshot or None on permanent failure.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with log_fetch(logger, ticker, "fundamentals") as ctx:
                stock = yf.Ticker(ticker)
                info = stock.info

                if not info or info.get("regularMarketPrice") is None:
                    logger.warning(f"No fundamental data returned for {ticker}")
                    return None

                snapshot = _parse_fundamentals(ticker, info)
                ctx["records"] = 1
                return snapshot

        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed for {ticker}: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"All {MAX_RETRIES} attempts failed for {ticker}: {e}")
                return None

    return None


def update_all_fundamentals(db_path: Optional[str] = None) -> dict:
    """Fetch and store fundamentals for all watchlist tickers.

    Returns a summary dict with successes and failures.
    """
    db = db_path or DB_PATH

    results = {"successes": [], "failures": []}

    for ticker in WATCHLIST:
        try:
            snapshot = fetch_fundamentals(ticker)
            if snapshot is None:
                results["failures"].append({"ticker": ticker, "reason": "fetch returned None"})
                continue

            upsert_fundamentals(snapshot, db_path=db)
            results["successes"].append({"ticker": ticker, "has_financials": snapshot.has_financials})
            logger.info(f"[{len(results['successes'])}/{len(WATCHLIST)}] {ticker}: fundamentals stored")

        except Exception as e:
            logger.error(f"Unexpected error for {ticker}: {e}")
            results["failures"].append({"ticker": ticker, "reason": str(e)})

    logger.info(
        f"Fundamentals update complete: {len(results['successes'])} succeeded, "
        f"{len(results['failures'])} failed"
    )
    return results


def _parse_fundamentals(ticker: str, info: dict) -> FundamentalsSnapshot:
    """Parse yfinance info dict into a validated FundamentalsSnapshot.

    Uses .get() for every field since yfinance returns different fields
    for different tickers.
    """
    return FundamentalsSnapshot(
        ticker=ticker,
        fetched_at=datetime.now(),
        # Income statement
        revenue=_safe_float(info.get("totalRevenue")),
        revenue_growth_yoy=_safe_float(info.get("revenueGrowth")),
        net_income=_safe_float(info.get("netIncomeToCommon")),
        gross_margin=_safe_float(info.get("grossMargins")),
        operating_margin=_safe_float(info.get("operatingMargins")),
        net_margin=_safe_float(info.get("profitMargins")),
        # Balance sheet
        total_debt=_safe_float(info.get("totalDebt")),
        total_cash=_safe_float(info.get("totalCash")),
        debt_to_equity=_safe_float(info.get("debtToEquity")),
        # Cash flow
        free_cash_flow=_safe_float(info.get("freeCashflow")),
        capital_expenditure=_safe_float(info.get("capitalExpenditures")),
        # Valuation ratios
        pe_ratio=_safe_float(info.get("trailingPE")),
        forward_pe=_safe_float(info.get("forwardPE")),
        ps_ratio=_safe_float(info.get("priceToSalesTrailing12Months")),
        pb_ratio=_safe_float(info.get("priceToBook")),
        peg_ratio=_safe_float(info.get("pegRatio")),
        ev_to_ebitda=_safe_float(info.get("enterpriseToEbitda")),
        # Market data
        market_cap=_safe_float(info.get("marketCap")),
        enterprise_value=_safe_float(info.get("enterpriseValue")),
        beta=_safe_float(info.get("beta")),
        fifty_two_week_high=_safe_float(info.get("fiftyTwoWeekHigh")),
        fifty_two_week_low=_safe_float(info.get("fiftyTwoWeekLow")),
        # Analyst data
        analyst_target_mean=_safe_float(info.get("targetMeanPrice")),
        analyst_target_median=_safe_float(info.get("targetMedianPrice")),
        analyst_target_high=_safe_float(info.get("targetHighPrice")),
        analyst_target_low=_safe_float(info.get("targetLowPrice")),
        analyst_count=_safe_int(info.get("numberOfAnalystOpinions")),
        recommendation=info.get("recommendationKey"),
    )


def _safe_float(value) -> Optional[float]:
    """Safely convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        result = float(value)
        if result != result:  # NaN check
            return None
        return result
    except (ValueError, TypeError):
        return None


def _safe_int(value) -> Optional[int]:
    """Safely convert a value to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
