"""Tests for dashboard data_loader functions."""

import json
import os
import sqlite3
import tempfile
from datetime import date
from unittest.mock import patch

import pytest

from src.db.operations import init_db, save_report, get_connection
from src.dashboard.data_loader import (
    load_portfolio_summary,
    load_ticker_detail,
    load_risk_report,
    load_signal_history,
    load_all_signal_history,
    get_signal_color,
    get_risk_color,
    ANALYST_AGENTS,
    SYNTHESIZER_AGENT,
    RISK_AGENT,
)


@pytest.fixture
def db_path():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(db_path=path)
    yield path
    os.unlink(path)


def _save_synthesis(ticker: str, signal: str, confidence: float, db_path: str,
                    report_date: date = None, **extra):
    """Helper to save a synthesis report."""
    report = {
        "ticker": ticker,
        "overall_signal": signal,
        "overall_confidence": confidence,
        "analyst_agreement": extra.get("analyst_agreement", "3/3 bullish"),
        "disagreement_flags": extra.get("disagreement_flags", []),
        "bull_case_summary": extra.get("bull_case_summary", "Strong growth"),
        "bear_case_summary": extra.get("bear_case_summary", "Valuation risk"),
        "recommendation": extra.get("recommendation", "HOLD — thesis intact"),
        "thesis_changed_since_last": extra.get("thesis_changed_since_last", False),
        "key_watch_items": extra.get("key_watch_items", ["Next earnings"]),
        "analyst_reports_used": extra.get("analyst_reports_used", []),
    }
    save_report(
        ticker=ticker,
        agent_name=SYNTHESIZER_AGENT,
        report_date=report_date or date.today(),
        report=report,
        signal=signal if signal in ("bullish", "bearish", "neutral") else "neutral",
        confidence=confidence,
        db_path=db_path,
    )


def _save_analyst_report(ticker: str, agent: str, signal: str, confidence: float, db_path: str):
    """Helper to save an analyst report."""
    report = {
        "ticker": ticker,
        "agent": agent,
        "signal": signal,
        "confidence": confidence,
        "thesis": f"Test thesis for {ticker}",
        "key_metrics": {"pe_ratio": 25.0, "revenue_growth": 0.35},
        "bull_case": "Strong fundamentals",
        "bear_case": "Market risks",
        "risks": ["Risk 1", "Risk 2"],
        "evidence": ["Evidence 1"],
    }
    save_report(
        ticker=ticker,
        agent_name=agent,
        report_date=date.today(),
        report=report,
        signal=signal,
        confidence=confidence,
        db_path=db_path,
    )


def _save_risk_report(db_path: str, **extra):
    """Helper to save a risk report. Creates PORTFOLIO stock entry if needed."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO stocks (ticker, name, layer, tier, watch_only) "
            "VALUES ('PORTFOLIO', 'Portfolio', 'Portfolio', 0, 1)"
        )
        conn.commit()
    finally:
        conn.close()

    report = {
        "overall_risk_level": extra.get("overall_risk_level", "moderate"),
        "risk_summary": extra.get("risk_summary", "Portfolio risk is moderate"),
        "sector_exposure": extra.get("sector_exposure", {"Semiconductor": 0.4, "Power": 0.3}),
        "concentration_warnings": extra.get("concentration_warnings", ["Heavy semi exposure"]),
        "correlation_flags": extra.get("correlation_flags", []),
        "position_sizing": extra.get("position_sizing", {"TSM": {"max_allocation": 0.15, "reason": "Geo risk"}}),
        "recommendations": extra.get("recommendations", ["Diversify power exposure"]),
        "tickers_analyzed": extra.get("tickers_analyzed", ["TSM", "AVGO"]),
    }
    save_report(
        ticker="PORTFOLIO",
        agent_name=RISK_AGENT,
        report_date=date.today(),
        report=report,
        signal="neutral",
        confidence=0.0,
        db_path=db_path,
    )


# ============================================================
# load_portfolio_summary tests
# ============================================================


class TestLoadPortfolioSummary:

    def test_empty_db_returns_all_tickers_with_none_signals(self, db_path):
        summaries = load_portfolio_summary(db_path=db_path)
        assert len(summaries) > 0
        for s in summaries:
            assert s["signal"] is None
            assert s["confidence"] is None
            assert s["recommendation"] is None

    def test_with_synthesis_report(self, db_path):
        _save_synthesis("TSM", "bullish", 0.85, db_path, recommendation="BUY — strong growth")
        summaries = load_portfolio_summary(db_path=db_path)
        tsm = next(s for s in summaries if s["ticker"] == "TSM")
        assert tsm["signal"] == "bullish"
        assert tsm["confidence"] == 0.85
        assert tsm["recommendation"] == "BUY — strong growth"
        assert tsm["report_date"] is not None

    def test_partial_reports_some_tickers_have_data(self, db_path):
        _save_synthesis("TSM", "bullish", 0.8, db_path)
        _save_synthesis("AVGO", "bearish", 0.6, db_path)
        summaries = load_portfolio_summary(db_path=db_path)
        tsm = next(s for s in summaries if s["ticker"] == "TSM")
        avgo = next(s for s in summaries if s["ticker"] == "AVGO")
        asml = next(s for s in summaries if s["ticker"] == "ASML")
        assert tsm["signal"] == "bullish"
        assert avgo["signal"] == "bearish"
        assert asml["signal"] is None

    def test_includes_watch_only_tickers(self, db_path):
        summaries = load_portfolio_summary(db_path=db_path)
        tickers = [s["ticker"] for s in summaries]
        assert "NVDA" in tickers
        assert "PLTR" in tickers

    def test_ticker_metadata_correct(self, db_path):
        summaries = load_portfolio_summary(db_path=db_path)
        tsm = next(s for s in summaries if s["ticker"] == "TSM")
        assert tsm["name"] == "Taiwan Semiconductor"
        assert tsm["layer"] == "Foundry/Packaging"
        assert tsm["tier"] == 1

    def test_latest_report_used(self, db_path):
        """Verify that the most recent report (by date) is returned."""
        report_old = {
            "ticker": "TSM", "overall_signal": "bearish", "overall_confidence": 0.4,
            "analyst_agreement": "1/3 bearish", "disagreement_flags": [],
            "bull_case_summary": "x", "bear_case_summary": "x",
            "recommendation": "SELL", "thesis_changed_since_last": False,
            "key_watch_items": ["x"], "analyst_reports_used": [],
        }
        report_new = {
            "ticker": "TSM", "overall_signal": "bullish", "overall_confidence": 0.9,
            "analyst_agreement": "3/3 bullish", "disagreement_flags": [],
            "bull_case_summary": "x", "bear_case_summary": "x",
            "recommendation": "BUY", "thesis_changed_since_last": False,
            "key_watch_items": ["x"], "analyst_reports_used": [],
        }
        save_report("TSM", SYNTHESIZER_AGENT, date(2026, 4, 1), report_old, "bearish", 0.4, db_path)
        save_report("TSM", SYNTHESIZER_AGENT, date(2026, 4, 8), report_new, "bullish", 0.9, db_path)
        summaries = load_portfolio_summary(db_path=db_path)
        tsm = next(s for s in summaries if s["ticker"] == "TSM")
        assert tsm["signal"] == "bullish"
        assert tsm["confidence"] == 0.9


# ============================================================
# load_ticker_detail tests
# ============================================================


class TestLoadTickerDetail:

    def test_empty_db_returns_skeleton(self, db_path):
        detail = load_ticker_detail("TSM", db_path=db_path)
        assert detail["ticker"] == "TSM"
        assert detail["name"] == "Taiwan Semiconductor"
        assert detail["synthesis"] is None
        assert detail["analysts"] == []

    def test_with_synthesis(self, db_path):
        _save_synthesis(
            "TSM", "bullish", 0.85, db_path,
            bull_case_summary="CoWoS monopoly",
            bear_case_summary="Taiwan risk",
            key_watch_items=["Q1 earnings"],
        )
        detail = load_ticker_detail("TSM", db_path=db_path)
        assert detail["synthesis"] is not None
        assert detail["synthesis"]["overall_signal"] == "bullish"
        assert detail["synthesis"]["overall_confidence"] == 0.85
        assert detail["synthesis"]["bull_case_summary"] == "CoWoS monopoly"
        assert detail["synthesis"]["bear_case_summary"] == "Taiwan risk"
        assert "Q1 earnings" in detail["synthesis"]["key_watch_items"]

    def test_with_analyst_reports(self, db_path):
        for agent in ANALYST_AGENTS:
            _save_analyst_report("TSM", agent, "bullish", 0.8, db_path)
        detail = load_ticker_detail("TSM", db_path=db_path)
        assert len(detail["analysts"]) == 3
        agents_found = {a["agent"] for a in detail["analysts"]}
        assert agents_found == set(ANALYST_AGENTS)

    def test_analyst_report_fields(self, db_path):
        _save_analyst_report("TSM", "fundamental_analyst", "bullish", 0.9, db_path)
        detail = load_ticker_detail("TSM", db_path=db_path)
        analyst = detail["analysts"][0]
        assert analyst["signal"] == "bullish"
        assert analyst["confidence"] == 0.9
        assert analyst["thesis"] == "Test thesis for TSM"
        assert analyst["key_metrics"]["pe_ratio"] == 25.0
        assert analyst["bull_case"] == "Strong fundamentals"
        assert "Risk 1" in analyst["risks"]

    def test_unknown_ticker_returns_fallback(self, db_path):
        detail = load_ticker_detail("UNKNOWN", db_path=db_path)
        assert detail["ticker"] == "UNKNOWN"
        assert detail["name"] == "UNKNOWN"
        assert detail["layer"] == "Unknown"

    def test_partial_analysts(self, db_path):
        _save_analyst_report("TSM", "fundamental_analyst", "bullish", 0.8, db_path)
        detail = load_ticker_detail("TSM", db_path=db_path)
        assert len(detail["analysts"]) == 1
        assert detail["analysts"][0]["agent"] == "fundamental_analyst"

    def test_empty_db_price_is_none(self, db_path):
        detail = load_ticker_detail("TSM", db_path=db_path)
        assert detail["price"] is None

    def test_with_price_data(self, db_path):
        from src.data.models import PriceBar, PriceHistory
        from src.db.operations import upsert_prices

        bars = [
            PriceBar(date=date(2026, 4, i), open=100.0 + i, high=105.0 + i,
                     low=95.0 + i, close=102.0 + i, volume=1000000)
            for i in range(1, 6)
        ]
        history = PriceHistory(ticker="TSM", bars=bars)
        upsert_prices("TSM", history, db_path=db_path)

        detail = load_ticker_detail("TSM", db_path=db_path)
        assert detail["price"] is not None
        assert detail["price"]["latest_close"] == 107.0  # 102 + 5
        assert detail["price"]["high_52w"] == 110.0  # 105 + 5
        assert detail["price"]["low_52w"] == 96.0  # 95 + 1


# ============================================================
# load_risk_report tests
# ============================================================


class TestLoadRiskReport:

    def test_no_risk_report_returns_none(self, db_path):
        result = load_risk_report(db_path=db_path)
        assert result is None

    def test_with_risk_report(self, db_path):
        _save_risk_report(db_path, overall_risk_level="elevated",
                          risk_summary="High semiconductor concentration")
        result = load_risk_report(db_path=db_path)
        assert result is not None
        assert result["overall_risk_level"] == "elevated"
        assert result["risk_summary"] == "High semiconductor concentration"
        assert "Semiconductor" in result["sector_exposure"]
        assert result["sector_exposure"]["Semiconductor"] == 0.4

    def test_position_sizing_loaded(self, db_path):
        _save_risk_report(db_path, position_sizing={
            "TSM": {"max_allocation": 0.15, "reason": "Geo risk cap"},
            "AVGO": {"max_allocation": 0.12, "reason": "Concentration limit"},
        })
        result = load_risk_report(db_path=db_path)
        assert "TSM" in result["position_sizing"]
        assert result["position_sizing"]["TSM"]["max_allocation"] == 0.15

    def test_warnings_and_flags(self, db_path):
        _save_risk_report(
            db_path,
            concentration_warnings=["Semi at 40%", "Power at 30%"],
            correlation_flags=["CEG-GEV correlated"],
        )
        result = load_risk_report(db_path=db_path)
        assert len(result["concentration_warnings"]) == 2
        assert "CEG-GEV correlated" in result["correlation_flags"]

    def test_recommendations_loaded(self, db_path):
        _save_risk_report(db_path, recommendations=["Reduce semi exposure", "Add diversification"])
        result = load_risk_report(db_path=db_path)
        assert len(result["recommendations"]) == 2


# ============================================================
# load_signal_history tests
# ============================================================


class TestLoadSignalHistory:

    def test_empty_db_returns_empty_list(self, db_path):
        result = load_signal_history("TSM", db_path=db_path)
        assert result == []

    def test_single_report(self, db_path):
        _save_synthesis("TSM", "bullish", 0.85, db_path, report_date=date(2026, 4, 1))
        result = load_signal_history("TSM", db_path=db_path)
        assert len(result) == 1
        assert result[0]["signal"] == "bullish"
        assert result[0]["confidence"] == 0.85
        assert result[0]["date"] == "2026-04-01"

    def test_multiple_reports_chronological_order(self, db_path):
        _save_synthesis("TSM", "bearish", 0.4, db_path, report_date=date(2026, 4, 1))
        _save_synthesis("TSM", "neutral", 0.5, db_path, report_date=date(2026, 4, 4))
        _save_synthesis("TSM", "bullish", 0.85, db_path, report_date=date(2026, 4, 8))
        result = load_signal_history("TSM", db_path=db_path)
        assert len(result) == 3
        # Should be chronological (oldest first)
        assert result[0]["signal"] == "bearish"
        assert result[1]["signal"] == "neutral"
        assert result[2]["signal"] == "bullish"

    def test_limit_respected(self, db_path):
        for i in range(5):
            _save_synthesis("TSM", "bullish", 0.8, db_path, report_date=date(2026, 4, i + 1))
        result = load_signal_history("TSM", limit=3, db_path=db_path)
        assert len(result) == 3

    def test_only_returns_requested_ticker(self, db_path):
        _save_synthesis("TSM", "bullish", 0.85, db_path, report_date=date(2026, 4, 1))
        _save_synthesis("AVGO", "bearish", 0.6, db_path, report_date=date(2026, 4, 1))
        result = load_signal_history("TSM", db_path=db_path)
        assert len(result) == 1
        assert result[0]["signal"] == "bullish"

    def test_signal_change_detection(self, db_path):
        """History can be used to detect signal changes."""
        _save_synthesis("TSM", "bearish", 0.4, db_path, report_date=date(2026, 4, 1))
        _save_synthesis("TSM", "bullish", 0.8, db_path, report_date=date(2026, 4, 8))
        result = load_signal_history("TSM", db_path=db_path)
        assert result[0]["signal"] != result[1]["signal"]


# ============================================================
# load_all_signal_history tests
# ============================================================


class TestLoadAllSignalHistory:

    def test_empty_db_returns_empty_list(self, db_path):
        result = load_all_signal_history(db_path=db_path)
        assert result == []

    def test_multiple_tickers(self, db_path):
        _save_synthesis("TSM", "bullish", 0.85, db_path, report_date=date(2026, 4, 1))
        _save_synthesis("AVGO", "bearish", 0.6, db_path, report_date=date(2026, 4, 2))
        result = load_all_signal_history(db_path=db_path)
        assert len(result) == 2
        tickers = {r["ticker"] for r in result}
        assert tickers == {"TSM", "AVGO"}

    def test_sorted_by_date(self, db_path):
        _save_synthesis("AVGO", "bearish", 0.6, db_path, report_date=date(2026, 4, 5))
        _save_synthesis("TSM", "bullish", 0.85, db_path, report_date=date(2026, 4, 1))
        result = load_all_signal_history(db_path=db_path)
        assert result[0]["ticker"] == "TSM"  # earlier date
        assert result[1]["ticker"] == "AVGO"

    def test_includes_ticker_field(self, db_path):
        _save_synthesis("TSM", "bullish", 0.85, db_path, report_date=date(2026, 4, 1))
        result = load_all_signal_history(db_path=db_path)
        assert "ticker" in result[0]
        assert result[0]["ticker"] == "TSM"

    def test_limit_per_ticker(self, db_path):
        for i in range(5):
            _save_synthesis("TSM", "bullish", 0.8, db_path, report_date=date(2026, 4, i + 1))
        result = load_all_signal_history(limit_per_ticker=2, db_path=db_path)
        tsm_entries = [r for r in result if r["ticker"] == "TSM"]
        assert len(tsm_entries) == 2


# ============================================================
# Corrupted data tests
# ============================================================


class TestCorruptedData:

    def test_corrupted_synthesis_json_raises(self, db_path):
        """Corrupted JSON in DB propagates as JSONDecodeError from get_reports."""
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO analysis_reports (ticker, agent_name, date, report_json, signal, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("TSM", SYNTHESIZER_AGENT, "2026-04-08", "not valid json{{{", "neutral", 0.5),
            )
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(json.JSONDecodeError):
            load_portfolio_summary(db_path=db_path)

    def test_missing_fields_in_report_json(self, db_path):
        """Report JSON exists but is missing expected fields."""
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO analysis_reports (ticker, agent_name, date, report_json, signal, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("TSM", SYNTHESIZER_AGENT, "2026-04-08", '{"foo": "bar"}', "neutral", 0.5),
            )
            conn.commit()
        finally:
            conn.close()

        summaries = load_portfolio_summary(db_path=db_path)
        tsm = next(s for s in summaries if s["ticker"] == "TSM")
        assert tsm["signal"] is None
        assert tsm["confidence"] is None
        assert tsm["recommendation"] is None

    def test_corrupted_analyst_report_skipped(self, db_path):
        """Corrupted analyst report JSON in DB should not crash ticker detail."""
        _save_analyst_report("TSM", "fundamental_analyst", "bullish", 0.8, db_path)
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO analysis_reports (ticker, agent_name, date, report_json, signal, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("TSM", "sentiment_analyst", "2026-04-08", '{}', "neutral", 0.5),
            )
            conn.commit()
        finally:
            conn.close()

        detail = load_ticker_detail("TSM", db_path=db_path)
        assert len(detail["analysts"]) == 2

    def test_corrupted_risk_report_returns_none(self, db_path):
        """Risk report with missing fields still loads without crash."""
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO stocks (ticker, name, layer, tier, watch_only) "
                "VALUES ('PORTFOLIO', 'Portfolio', 'Portfolio', 0, 1)"
            )
            conn.execute(
                "INSERT INTO analysis_reports (ticker, agent_name, date, report_json, signal, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("PORTFOLIO", RISK_AGENT, "2026-04-08", '{"unexpected": true}', "neutral", 0.0),
            )
            conn.commit()
        finally:
            conn.close()

        result = load_risk_report(db_path=db_path)
        assert result is not None
        assert result["sector_exposure"] == {}
        assert result["recommendations"] == []

    def test_corrupted_signal_history_entry_skipped(self, db_path):
        """Signal history entries with bad data are skipped gracefully."""
        # Save a valid report
        _save_synthesis("TSM", "bullish", 0.85, db_path, report_date=date(2026, 4, 1))
        # Insert a report with valid JSON but that will trigger TypeError in .get()
        conn = get_connection(db_path)
        try:
            # report_json is a JSON array instead of object — .get() on list raises AttributeError
            conn.execute(
                "INSERT INTO analysis_reports (ticker, agent_name, date, report_json, signal, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("TSM", SYNTHESIZER_AGENT, "2026-04-05", '[1, 2, 3]', "neutral", 0.5),
            )
            conn.commit()
        finally:
            conn.close()

        # load_signal_history should skip the corrupted entry
        result = load_signal_history("TSM", db_path=db_path)
        assert len(result) == 1
        assert result[0]["signal"] == "bullish"


# ============================================================
# Color helper tests
# ============================================================


class TestColorHelpers:

    def test_signal_colors(self):
        assert get_signal_color("bullish") == "green"
        assert get_signal_color("bearish") == "red"
        assert get_signal_color("neutral") == "orange"
        assert get_signal_color(None) == "gray"
        assert get_signal_color("unknown") == "gray"

    def test_risk_colors(self):
        assert get_risk_color("low") == "green"
        assert get_risk_color("moderate") == "blue"
        assert get_risk_color("elevated") == "orange"
        assert get_risk_color("high") == "red"
        assert get_risk_color(None) == "gray"
        assert get_risk_color("unknown") == "gray"

    def test_case_insensitive(self):
        assert get_signal_color("BULLISH") == "green"
        assert get_risk_color("HIGH") == "red"


# ============================================================
# Action button subprocess tests
# ============================================================


class TestPriceLoadingEdgeCases:

    def test_price_load_exception_returns_none(self, db_path):
        """If price loading raises, detail['price'] remains None."""
        with patch("src.dashboard.data_loader.get_prices", side_effect=Exception("DB error")):
            detail = load_ticker_detail("TSM", db_path=db_path)
            assert detail["price"] is None

    def test_signal_history_chronological_with_limit(self, db_path):
        """When limit is less than available reports, returns the most recent N in chronological order."""
        _save_synthesis("TSM", "bearish", 0.3, db_path, report_date=date(2026, 4, 1))
        _save_synthesis("TSM", "neutral", 0.5, db_path, report_date=date(2026, 4, 4))
        _save_synthesis("TSM", "bullish", 0.8, db_path, report_date=date(2026, 4, 8))
        # Limit to 2 — should get the 2 most recent (newest from DB), reversed to chronological
        result = load_signal_history("TSM", limit=2, db_path=db_path)
        assert len(result) == 2
        assert result[0]["date"] <= result[1]["date"]  # chronological order
