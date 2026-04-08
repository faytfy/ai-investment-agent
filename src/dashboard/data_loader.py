"""Data loading helpers for the Streamlit dashboard.

Reads from SQLite DB and returns display-ready data structures.
All functions are read-only — no writes to DB.
"""

from typing import Optional

import streamlit as st

from src.config import WATCHLIST, WATCH_ONLY
from src.db.operations import get_alerts as db_get_alerts, get_reports, get_prices, get_upcoming_earnings
from src.utils.logger import get_logger

logger = get_logger("dashboard.data_loader")

# Agent names that produce per-ticker analyst reports
ANALYST_AGENTS = ["fundamental_analyst", "sentiment_analyst", "supply_chain_analyst"]
SYNTHESIZER_AGENT = "research_synthesizer"
RISK_AGENT = "risk_manager"


@st.cache_data(ttl=300)
def load_portfolio_summary(db_path: Optional[str] = None) -> list[dict]:
    """Load latest synthesis report for each watchlist ticker.

    Returns a list of dicts, one per ticker, with:
        ticker, name, layer, tier, signal, confidence, recommendation, report_date
    Tickers with no synthesis report are included with signal=None.
    """
    kwargs = {"db_path": db_path} if db_path else {}
    summaries = []

    all_tickers = {**WATCHLIST, **WATCH_ONLY}

    for ticker, info in all_tickers.items():
        row = {
            "ticker": ticker,
            "name": info["name"],
            "layer": info["layer"],
            "tier": info.get("tier", 0),
            "signal": None,
            "confidence": None,
            "recommendation": None,
            "report_date": None,
        }

        reports = get_reports(ticker, agent_name=SYNTHESIZER_AGENT, limit=1, **kwargs)
        if reports:
            report_data = reports[0]["report"]
            try:
                row["signal"] = report_data.get("overall_signal")
                row["confidence"] = report_data.get("overall_confidence")
                row["recommendation"] = report_data.get("recommendation")
                row["report_date"] = reports[0]["date"]
            except (KeyError, TypeError):
                logger.warning(f"Corrupted synthesis report for {ticker}, skipping")

        summaries.append(row)

    return summaries


@st.cache_data(ttl=300)
def load_ticker_detail(ticker: str, db_path: Optional[str] = None) -> dict:
    """Load detailed data for a single ticker.

    Returns a dict with:
        ticker, name, layer, tier,
        synthesis: dict or None (latest synthesis report fields),
        analysts: list[dict] (latest report from each analyst agent),
        price: dict or None (latest close, 52w high/low from price history)
    """
    kwargs = {"db_path": db_path} if db_path else {}
    all_tickers = {**WATCHLIST, **WATCH_ONLY}
    info = all_tickers.get(ticker, {"name": ticker, "layer": "Unknown", "tier": 0})

    detail = {
        "ticker": ticker,
        "name": info["name"],
        "layer": info["layer"],
        "tier": info.get("tier", 0),
        "synthesis": None,
        "analysts": [],
        "price": None,
    }

    # Load latest synthesis
    synth_reports = get_reports(ticker, agent_name=SYNTHESIZER_AGENT, limit=1, **kwargs)
    if synth_reports:
        try:
            report_data = synth_reports[0]["report"]
            detail["synthesis"] = {
                "overall_signal": report_data.get("overall_signal"),
                "overall_confidence": report_data.get("overall_confidence"),
                "analyst_agreement": report_data.get("analyst_agreement"),
                "disagreement_flags": report_data.get("disagreement_flags", []),
                "bull_case_summary": report_data.get("bull_case_summary"),
                "bear_case_summary": report_data.get("bear_case_summary"),
                "recommendation": report_data.get("recommendation"),
                "thesis_changed_since_last": report_data.get("thesis_changed_since_last", False),
                "key_watch_items": report_data.get("key_watch_items", []),
                "report_date": synth_reports[0]["date"],
            }
        except (KeyError, TypeError):
            logger.warning(f"Corrupted synthesis report for {ticker}")

    # Load latest report from each analyst
    for agent in ANALYST_AGENTS:
        agent_reports = get_reports(ticker, agent_name=agent, limit=1, **kwargs)
        if agent_reports:
            try:
                r = agent_reports[0]
                detail["analysts"].append({
                    "agent": agent,
                    "signal": r["signal"],
                    "confidence": r["confidence"],
                    "report_date": r["date"],
                    "thesis": r["report"].get("thesis"),
                    "key_metrics": r["report"].get("key_metrics", {}),
                    "bull_case": r["report"].get("bull_case"),
                    "bear_case": r["report"].get("bear_case"),
                    "risks": r["report"].get("risks", []),
                })
            except (KeyError, TypeError):
                logger.warning(f"Corrupted {agent} report for {ticker}")

    # Load latest price data (last 5 bars for sparkline / current price)
    try:
        price_history = get_prices(ticker, **kwargs)
        if not price_history.is_empty:
            bars = price_history.bars
            latest = bars[-1]
            high_52w = max(b.high for b in bars[-252:]) if len(bars) >= 1 else None
            low_52w = min(b.low for b in bars[-252:]) if len(bars) >= 1 else None
            detail["price"] = {
                "latest_close": latest.close,
                "latest_date": latest.date.isoformat(),
                "high_52w": high_52w,
                "low_52w": low_52w,
            }
    except Exception as e:
        logger.warning(f"Failed to load prices for {ticker}: {e}")

    return detail


@st.cache_data(ttl=300)
def load_risk_report(db_path: Optional[str] = None) -> Optional[dict]:
    """Load the latest portfolio risk report.

    Returns a dict with all PortfolioRiskReport fields, or None if no report exists.
    """
    kwargs = {"db_path": db_path} if db_path else {}

    reports = get_reports("PORTFOLIO", agent_name=RISK_AGENT, limit=1, **kwargs)
    if not reports:
        return None

    try:
        report_data = reports[0]["report"]
        return {
            "overall_risk_level": report_data.get("overall_risk_level", "moderate"),
            "risk_summary": report_data.get("risk_summary", ""),
            "sector_exposure": report_data.get("sector_exposure", {}),
            "concentration_warnings": report_data.get("concentration_warnings", []),
            "correlation_flags": report_data.get("correlation_flags", []),
            "position_sizing": report_data.get("position_sizing", {}),
            "recommendations": report_data.get("recommendations", []),
            "tickers_analyzed": report_data.get("tickers_analyzed", []),
            "report_date": reports[0]["date"],
        }
    except (KeyError, TypeError):
        logger.warning("Corrupted risk report, skipping")
        return None


def get_signal_color(signal: Optional[str]) -> str:
    """Map a signal string to a display color."""
    if signal is None:
        return "gray"
    colors = {
        "bullish": "green",
        "bearish": "red",
        "neutral": "orange",
    }
    return colors.get(signal.lower(), "gray")


def get_risk_color(risk_level: Optional[str]) -> str:
    """Map a risk level string to a display color."""
    if risk_level is None:
        return "gray"
    colors = {
        "low": "green",
        "moderate": "blue",
        "elevated": "orange",
        "high": "red",
    }
    return colors.get(risk_level.lower(), "gray")


@st.cache_data(ttl=300)
def load_signal_history(ticker: str, limit: int = 20, db_path: Optional[str] = None) -> list[dict]:
    """Load synthesis signal history for a single ticker.

    Returns a list of dicts sorted by date ascending:
        {date, signal, confidence}
    """
    kwargs = {"db_path": db_path} if db_path else {}
    reports = get_reports(ticker, agent_name=SYNTHESIZER_AGENT, limit=limit, **kwargs)
    history = []
    for r in reports:
        try:
            history.append({
                "date": r["date"],
                "signal": r["report"].get("overall_signal"),
                "confidence": r["report"].get("overall_confidence"),
            })
        except (KeyError, TypeError, AttributeError):
            logger.warning(f"Corrupted signal history entry for {ticker}, skipping")
    # get_reports returns newest first; reverse for chronological order
    history.reverse()
    return history


@st.cache_data(ttl=300)
def load_all_signal_history(limit_per_ticker: int = 10, db_path: Optional[str] = None) -> list[dict]:
    """Load recent signal history across all watchlist tickers.

    Returns a list of dicts:
        {ticker, date, signal, confidence}
    Sorted by date ascending.
    """
    all_tickers = {**WATCHLIST, **WATCH_ONLY}
    all_history = []
    for ticker in all_tickers:
        for entry in load_signal_history(ticker, limit=limit_per_ticker, db_path=db_path):
            all_history.append({"ticker": ticker, **entry})
    all_history.sort(key=lambda x: x["date"])
    return all_history


@st.cache_data(ttl=300)
def load_alerts(limit: int = 20, db_path: Optional[str] = None) -> list[dict]:
    """Load recent alerts, newest first."""
    kwargs = {"db_path": db_path} if db_path else {}
    return db_get_alerts(limit=limit, **kwargs)


@st.cache_data(ttl=300)
def load_earnings_calendar(db_path: Optional[str] = None) -> list[dict]:
    """Load upcoming earnings events."""
    kwargs = {"db_path": db_path} if db_path else {}
    return get_upcoming_earnings(within_days=30, **kwargs)
