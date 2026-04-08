"""End-to-end integration tests for the full pipeline.

Tests the complete data flow: seed DB → save reports → alert detection → dashboard loaders.
All external APIs (Claude, yfinance) are mocked — tests only verify internal wiring.
"""

import json
import os
import tempfile
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from src.data.models import (
    AlertRecord,
    AlertSeverity,
    AlertType,
    AnalysisReport,
    FundamentalsSnapshot,
    PortfolioRiskReport,
    PriceBar,
    PriceHistory,
    RiskLevel,
    Signal,
    SynthesisReport,
)
from src.db.operations import (
    get_alerts,
    get_prices,
    get_reports,
    get_upcoming_earnings,
    init_db,
    save_alert,
    save_report,
    upsert_earnings,
    upsert_fundamentals,
    upsert_prices,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def db_path():
    """Create a fresh temporary database for each test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(db_path=path)
    yield path
    os.unlink(path)


def _make_price_history(ticker: str, days: int = 30) -> PriceHistory:
    """Generate synthetic price bars."""
    bars = []
    base_price = 100.0
    for i in range(days):
        d = date.today() - timedelta(days=days - i)
        price = base_price + i * 0.5
        bars.append(PriceBar(
            date=d,
            open=price,
            high=price + 2.0,
            low=price - 1.0,
            close=price + 1.0,
            volume=1000000 + i * 10000,
        ))
    return PriceHistory(ticker=ticker, bars=bars)


def _make_fundamentals(ticker: str) -> FundamentalsSnapshot:
    """Generate a synthetic fundamentals snapshot."""
    return FundamentalsSnapshot(
        ticker=ticker,
        revenue=1e10,
        revenue_growth_yoy=0.15,
        net_income=2e9,
        gross_margin=0.55,
        operating_margin=0.35,
        net_margin=0.20,
        pe_ratio=25.0,
        forward_pe=20.0,
        market_cap=200e9,
        beta=1.1,
    )


def _make_analyst_report(ticker: str, agent: str, signal: Signal) -> AnalysisReport:
    """Generate a synthetic analyst report."""
    return AnalysisReport(
        ticker=ticker,
        agent=agent,
        signal=signal,
        confidence=0.75,
        thesis=f"{ticker} looks {signal.value} based on fundamentals",
        bull_case=f"Strong growth trajectory for {ticker}",
        bear_case=f"Valuation risk for {ticker}",
        risks=[f"Competition risk for {ticker}"],
        evidence=[f"Revenue growth exceeds expectations for {ticker}"],
        key_metrics={"pe_ratio": 25.0, "revenue_growth": 0.15},
    )


def _make_synthesis_report(ticker: str, signal: Signal) -> SynthesisReport:
    """Generate a synthetic synthesis report."""
    return SynthesisReport(
        ticker=ticker,
        overall_signal=signal,
        overall_confidence=0.80,
        analyst_agreement="3/3 bullish",
        bull_case_summary=f"All analysts agree {ticker} has strong fundamentals",
        bear_case_summary=f"Valuation stretched for {ticker}",
        recommendation=f"BUY — strong consensus on {ticker}",
        key_watch_items=[f"Monitor {ticker} earnings next quarter"],
        analyst_reports_used=["fundamental_analyst", "sentiment_analyst", "supply_chain_analyst"],
    )


def _make_risk_report(tickers: list[str]) -> PortfolioRiskReport:
    """Generate a synthetic risk report."""
    return PortfolioRiskReport(
        overall_risk_level=RiskLevel.MODERATE,
        risk_summary="Portfolio is moderately concentrated in semiconductor supply chain",
        sector_exposure={"Semiconductor": 0.6, "Power": 0.3, "Networking": 0.1},
        concentration_warnings=["Heavy semiconductor exposure (60%)"],
        correlation_flags=["TSM-ASML correlation > 0.8"],
        position_sizing={t: {"max_allocation": 0.12, "reason": "Standard sizing"} for t in tickers},
        recommendations=["Consider adding non-tech exposure for diversification"],
        tickers_analyzed=tickers,
        portfolio_signals=[
            {"ticker": t, "signal": "bullish", "confidence": 0.8, "recommendation": "BUY"}
            for t in tickers
        ],
    )


# ============================================================
# Full Pipeline Integration Tests
# ============================================================


class TestFullPipeline:
    """Test the complete data flow from DB seeding through dashboard reads."""

    def test_price_fundamentals_round_trip(self, db_path):
        """Seed prices and fundamentals → read back and verify."""
        ticker = "TSM"
        prices = _make_price_history(ticker, days=30)
        fundies = _make_fundamentals(ticker)

        upsert_prices(ticker, prices, db_path=db_path)
        upsert_fundamentals(fundies, db_path=db_path)

        # Read back prices
        read_prices = get_prices(ticker, db_path=db_path)
        assert not read_prices.is_empty
        assert len(read_prices.bars) == 30
        assert read_prices.bars[-1].close == prices.bars[-1].close

        # Read back fundamentals
        from src.db.operations import get_latest_fundamentals
        read_fundies = get_latest_fundamentals(ticker, db_path=db_path)
        assert read_fundies is not None
        assert read_fundies.revenue == 1e10
        assert read_fundies.revenue_growth_yoy == 0.15

    def test_analyst_reports_round_trip(self, db_path):
        """Save analyst reports → read back via get_reports."""
        ticker = "TSM"
        agents = ["fundamental_analyst", "sentiment_analyst", "supply_chain_analyst"]

        for agent in agents:
            report = _make_analyst_report(ticker, agent, Signal.BULLISH)
            save_report(
                ticker=ticker,
                agent_name=agent,
                report_date=report.report_date,
                report=report.model_dump(mode="json"),
                signal=report.signal.value,
                confidence=report.confidence,
                db_path=db_path,
            )

        # Read back
        for agent in agents:
            reports = get_reports(ticker, agent_name=agent, limit=1, db_path=db_path)
            assert len(reports) == 1
            assert reports[0]["signal"] == "bullish"
            assert reports[0]["report"]["agent"] == agent

    def test_synthesis_report_round_trip(self, db_path):
        """Save synthesis report → read back and verify all fields."""
        ticker = "TSM"
        synth = _make_synthesis_report(ticker, Signal.BULLISH)

        save_report(
            ticker=ticker,
            agent_name="research_synthesizer",
            report_date=synth.report_date,
            report=synth.model_dump(mode="json"),
            signal=synth.overall_signal.value,
            confidence=synth.overall_confidence,
            db_path=db_path,
        )

        reports = get_reports(ticker, agent_name="research_synthesizer", limit=1, db_path=db_path)
        assert len(reports) == 1
        data = reports[0]["report"]
        assert data["overall_signal"] == "bullish"
        assert data["overall_confidence"] == 0.80
        assert data["recommendation"] == f"BUY — strong consensus on {ticker}"
        assert data["thesis_changed_since_last"] is False

    def test_risk_report_round_trip(self, db_path):
        """Save risk report → read back as PORTFOLIO ticker."""
        tickers = ["TSM", "AVGO"]
        risk = _make_risk_report(tickers)

        # Ensure PORTFOLIO stock exists
        from src.db.operations import get_connection
        conn = get_connection(db_path)
        conn.execute(
            "INSERT OR IGNORE INTO stocks (ticker, name, layer, tier, watch_only) "
            "VALUES ('PORTFOLIO', 'Portfolio', 'portfolio', 0, 0)"
        )
        conn.commit()
        conn.close()

        save_report(
            ticker="PORTFOLIO",
            agent_name="risk_manager",
            report_date=risk.report_date,
            report=risk.model_dump(mode="json"),
            signal="neutral",
            confidence=0.0,
            db_path=db_path,
        )

        reports = get_reports("PORTFOLIO", agent_name="risk_manager", limit=1, db_path=db_path)
        assert len(reports) == 1
        data = reports[0]["report"]
        assert data["overall_risk_level"] == "moderate"
        assert "TSM" in data["tickers_analyzed"]

    def test_full_pipeline_data_flow(self, db_path):
        """Complete pipeline: prices → analysts → synthesis → risk → alerts → dashboard loaders."""
        ticker = "TSM"

        # Step 1: Seed prices
        prices = _make_price_history(ticker, days=30)
        upsert_prices(ticker, prices, db_path=db_path)

        # Step 2: Seed fundamentals
        fundies = _make_fundamentals(ticker)
        upsert_fundamentals(fundies, db_path=db_path)

        # Step 3: Save analyst reports
        for agent in ["fundamental_analyst", "sentiment_analyst", "supply_chain_analyst"]:
            report = _make_analyst_report(ticker, agent, Signal.BULLISH)
            save_report(
                ticker=ticker,
                agent_name=agent,
                report_date=report.report_date,
                report=report.model_dump(mode="json"),
                signal=report.signal.value,
                confidence=report.confidence,
                db_path=db_path,
            )

        # Step 4: Save synthesis report
        synth = _make_synthesis_report(ticker, Signal.BULLISH)
        save_report(
            ticker=ticker,
            agent_name="research_synthesizer",
            report_date=synth.report_date,
            report=synth.model_dump(mode="json"),
            signal=synth.overall_signal.value,
            confidence=synth.overall_confidence,
            db_path=db_path,
        )

        # Step 5: Save risk report
        risk = _make_risk_report([ticker])
        from src.db.operations import get_connection
        conn = get_connection(db_path)
        conn.execute(
            "INSERT OR IGNORE INTO stocks (ticker, name, layer, tier, watch_only) "
            "VALUES ('PORTFOLIO', 'Portfolio', 'portfolio', 0, 0)"
        )
        conn.commit()
        conn.close()

        save_report(
            ticker="PORTFOLIO",
            agent_name="risk_manager",
            report_date=risk.report_date,
            report=risk.model_dump(mode="json"),
            signal="neutral",
            confidence=0.0,
            db_path=db_path,
        )

        # Step 6: Save an alert
        alert = AlertRecord(
            ticker=ticker,
            alert_type=AlertType.SIGNAL_CHANGE,
            severity=AlertSeverity.WARNING,
            title="TSM signal changed from neutral to bullish",
            detail="Fundamental and sentiment analysts now agree on bullish outlook",
        )
        save_alert(alert, db_path=db_path)

        # Step 7: Save earnings event
        upsert_earnings(
            ticker=ticker,
            earnings_date=date.today() + timedelta(days=5),
            db_path=db_path,
        )

        # Step 8: Verify dashboard loaders read everything correctly
        # (Bypass Streamlit caching for test)
        from src.dashboard.data_loader import (
            load_alerts,
            load_earnings_calendar,
            load_portfolio_summary,
            load_risk_report,
            load_signal_history,
            load_ticker_detail,
        )

        # Portfolio summary
        summary = load_portfolio_summary.__wrapped__(db_path=db_path)
        tsm_row = next(s for s in summary if s["ticker"] == "TSM")
        assert tsm_row["signal"] == "bullish"
        assert tsm_row["confidence"] == 0.80

        # Ticker detail
        detail = load_ticker_detail.__wrapped__(ticker, db_path=db_path)
        assert detail["synthesis"] is not None
        assert detail["synthesis"]["overall_signal"] == "bullish"
        assert len(detail["analysts"]) == 3
        assert detail["price"] is not None
        assert detail["price"]["latest_close"] == prices.bars[-1].close

        # Risk report
        risk_data = load_risk_report.__wrapped__(db_path=db_path)
        assert risk_data is not None
        assert risk_data["overall_risk_level"] == "moderate"

        # Signal history
        history = load_signal_history.__wrapped__(ticker, db_path=db_path)
        assert len(history) == 1
        assert history[0]["signal"] == "bullish"

        # Alerts
        alerts = load_alerts.__wrapped__(db_path=db_path)
        assert len(alerts) >= 1
        signal_alerts = [a for a in alerts if a["alert_type"] == "signal_change"]
        assert len(signal_alerts) == 1

        # Earnings calendar
        earnings = load_earnings_calendar.__wrapped__(db_path=db_path)
        assert len(earnings) >= 1
        assert any(e["ticker"] == "TSM" for e in earnings)


# ============================================================
# Signal Change Detection Integration
# ============================================================


class TestSignalChangeDetection:
    """Test alert detection logic with real DB data."""

    def test_signal_flip_detected(self, db_path):
        """When synthesis signal changes between reports, an alert fires."""
        ticker = "TSM"

        # Save two synthesis reports with different signals
        old_synth = _make_synthesis_report(ticker, Signal.NEUTRAL)
        old_synth.report_date = date.today() - timedelta(days=7)
        save_report(
            ticker=ticker,
            agent_name="research_synthesizer",
            report_date=old_synth.report_date,
            report=old_synth.model_dump(mode="json"),
            signal=old_synth.overall_signal.value,
            confidence=old_synth.overall_confidence,
            db_path=db_path,
        )

        new_synth = _make_synthesis_report(ticker, Signal.BULLISH)
        save_report(
            ticker=ticker,
            agent_name="research_synthesizer",
            report_date=new_synth.report_date,
            report=new_synth.model_dump(mode="json"),
            signal=new_synth.overall_signal.value,
            confidence=new_synth.overall_confidence,
            db_path=db_path,
        )

        # Run signal change detection
        from src.automation.alerts import detect_signal_changes
        with patch("src.automation.alerts.WATCHLIST", {ticker: {"name": "TSM", "layer": "Foundry", "tier": 1}}), \
             patch("src.automation.alerts.WATCH_ONLY", {}):
            alerts = detect_signal_changes(db_path=db_path)

        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.SIGNAL_CHANGE
        assert "neutral" in alerts[0].detail.lower()
        assert "bullish" in alerts[0].detail.lower()

    def test_no_alert_when_signal_unchanged(self, db_path):
        """No alert fires when consecutive reports have the same signal."""
        ticker = "TSM"

        for i in range(2):
            synth = _make_synthesis_report(ticker, Signal.BULLISH)
            synth.report_date = date.today() - timedelta(days=7 - i * 7)
            save_report(
                ticker=ticker,
                agent_name="research_synthesizer",
                report_date=synth.report_date,
                report=synth.model_dump(mode="json"),
                signal=synth.overall_signal.value,
                confidence=synth.overall_confidence,
                db_path=db_path,
            )

        from src.automation.alerts import detect_signal_changes
        with patch("src.automation.alerts.WATCHLIST", {ticker: {"name": "TSM", "layer": "Foundry", "tier": 1}}), \
             patch("src.automation.alerts.WATCH_ONLY", {}):
            alerts = detect_signal_changes(db_path=db_path)

        assert len(alerts) == 0

    def test_earnings_alert_fires_within_window(self, db_path):
        """Earnings within the alert window trigger an alert."""
        ticker = "TSM"
        upsert_earnings(
            ticker=ticker,
            earnings_date=date.today() + timedelta(days=3),
            db_path=db_path,
        )

        from src.automation.alerts import detect_earnings_alerts
        with patch("src.automation.alerts.WATCHLIST", {ticker: {"name": "TSM", "layer": "Foundry", "tier": 1}}), \
             patch("src.automation.alerts.WATCH_ONLY", {}):
            alerts = detect_earnings_alerts(db_path=db_path)

        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.EARNINGS_APPROACHING


# ============================================================
# Empty Database Edge Cases
# ============================================================


class TestEmptyDatabase:
    """Verify graceful handling when the database has no reports."""

    def test_dashboard_loaders_with_empty_db(self, db_path):
        """All dashboard loaders return sensible defaults on empty DB."""
        from src.dashboard.data_loader import (
            load_alerts,
            load_earnings_calendar,
            load_portfolio_summary,
            load_risk_report,
            load_signal_history,
            load_ticker_detail,
        )

        # Portfolio summary — all tickers present with null signals
        summary = load_portfolio_summary.__wrapped__(db_path=db_path)
        assert len(summary) > 0
        for row in summary:
            assert row["signal"] is None
            assert row["confidence"] is None

        # Ticker detail — synthesis is None, no analysts, no price
        detail = load_ticker_detail.__wrapped__("TSM", db_path=db_path)
        assert detail["synthesis"] is None
        assert detail["analysts"] == []
        assert detail["price"] is None

        # Risk report — None
        risk = load_risk_report.__wrapped__(db_path=db_path)
        assert risk is None

        # Signal history — empty
        history = load_signal_history.__wrapped__("TSM", db_path=db_path)
        assert history == []

        # Alerts — empty
        alerts = load_alerts.__wrapped__(db_path=db_path)
        assert alerts == []

        # Earnings — empty
        earnings = load_earnings_calendar.__wrapped__(db_path=db_path)
        assert earnings == []

    def test_alert_detection_with_empty_db(self, db_path):
        """Alert detection produces no alerts on empty DB."""
        from src.automation.alerts import detect_and_fire_alerts

        with patch("src.automation.alerts.WATCHLIST", {"TSM": {"name": "TSM", "layer": "Foundry", "tier": 1}}), \
             patch("src.automation.alerts.WATCH_ONLY", {}):
            alerts = detect_and_fire_alerts(db_path=db_path)

        assert alerts == []

    def test_scheduler_handles_empty_db(self, db_path):
        """Scheduler pipeline completes even with no prior data."""
        from src.automation.scheduler import scheduled_run

        with patch("src.agents.runner.run_all_orchestrated") as mock_orch, \
             patch("src.agents.runner.run_risk", side_effect=ValueError("No synthesis reports")), \
             patch("src.automation.earnings.refresh_earnings_calendar"), \
             patch("src.automation.alerts.detect_and_fire_alerts", return_value=[]), \
             patch("src.automation.notifier.notify"):

            # Should not crash — risk failure is caught
            scheduled_run(db_path=db_path)
            mock_orch.assert_called_once()

        # Should still save a run_completed alert
        alerts = get_alerts(limit=10, db_path=db_path)
        completed = [a for a in alerts if a["alert_type"] == "run_completed"]
        assert len(completed) == 1


# ============================================================
# Cross-Module Data Consistency
# ============================================================


class TestDataConsistency:
    """Verify that data models serialize/deserialize consistently across modules."""

    def test_synthesis_report_model_dump_matches_db_read(self, db_path):
        """SynthesisReport.model_dump() → save_report() → get_reports() → fields match."""
        ticker = "AVGO"
        synth = _make_synthesis_report(ticker, Signal.BEARISH)

        dumped = synth.model_dump(mode="json")
        save_report(
            ticker=ticker,
            agent_name="research_synthesizer",
            report_date=synth.report_date,
            report=dumped,
            signal=synth.overall_signal.value,
            confidence=synth.overall_confidence,
            db_path=db_path,
        )

        reports = get_reports(ticker, agent_name="research_synthesizer", limit=1, db_path=db_path)
        read_back = reports[0]["report"]

        # All key fields should round-trip exactly
        assert read_back["overall_signal"] == "bearish"
        assert read_back["overall_confidence"] == synth.overall_confidence
        assert read_back["analyst_agreement"] == synth.analyst_agreement
        assert read_back["bull_case_summary"] == synth.bull_case_summary
        assert read_back["bear_case_summary"] == synth.bear_case_summary
        assert read_back["recommendation"] == synth.recommendation
        assert read_back["thesis_changed_since_last"] == synth.thesis_changed_since_last
        assert read_back["key_watch_items"] == synth.key_watch_items

    def test_analyst_report_model_dump_matches_db_read(self, db_path):
        """AnalysisReport.model_dump() round-trips through the DB."""
        ticker = "ASML"
        report = _make_analyst_report(ticker, "fundamental_analyst", Signal.NEUTRAL)

        dumped = report.model_dump(mode="json")
        save_report(
            ticker=ticker,
            agent_name="fundamental_analyst",
            report_date=report.report_date,
            report=dumped,
            signal=report.signal.value,
            confidence=report.confidence,
            db_path=db_path,
        )

        reports = get_reports(ticker, agent_name="fundamental_analyst", limit=1, db_path=db_path)
        read_back = reports[0]["report"]

        assert read_back["signal"] == "neutral"
        assert read_back["confidence"] == report.confidence
        assert read_back["thesis"] == report.thesis
        assert read_back["key_metrics"]["pe_ratio"] == 25.0

    def test_risk_report_model_dump_matches_db_read(self, db_path):
        """PortfolioRiskReport.model_dump() round-trips through the DB."""
        tickers = ["TSM", "AVGO", "ASML"]
        risk = _make_risk_report(tickers)

        from src.db.operations import get_connection
        conn = get_connection(db_path)
        conn.execute(
            "INSERT OR IGNORE INTO stocks (ticker, name, layer, tier, watch_only) "
            "VALUES ('PORTFOLIO', 'Portfolio', 'portfolio', 0, 0)"
        )
        conn.commit()
        conn.close()

        dumped = risk.model_dump(mode="json")
        save_report(
            ticker="PORTFOLIO",
            agent_name="risk_manager",
            report_date=risk.report_date,
            report=dumped,
            signal="neutral",
            confidence=0.0,
            db_path=db_path,
        )

        reports = get_reports("PORTFOLIO", agent_name="risk_manager", limit=1, db_path=db_path)
        read_back = reports[0]["report"]

        assert read_back["overall_risk_level"] == "moderate"
        assert set(read_back["tickers_analyzed"]) == set(tickers)
        assert read_back["sector_exposure"]["Semiconductor"] == 0.6
        assert len(read_back["recommendations"]) == 1

    def test_alert_record_round_trip(self, db_path):
        """AlertRecord → save_alert() → get_alerts() → fields match."""
        alert = AlertRecord(
            ticker="MU",
            alert_type=AlertType.THESIS_CHANGE,
            severity=AlertSeverity.CRITICAL,
            title="MU thesis changed",
            detail="HBM demand revised downward",
        )
        save_alert(alert, db_path=db_path)

        alerts = get_alerts(limit=10, db_path=db_path)
        assert len(alerts) == 1
        a = alerts[0]
        assert a["ticker"] == "MU"
        assert a["alert_type"] == "thesis_change"
        assert a["severity"] == "critical"
        assert a["title"] == "MU thesis changed"
        assert a["detail"] == "HBM demand revised downward"

    def test_load_all_signal_history_across_tickers(self, db_path):
        """load_all_signal_history returns sorted cross-ticker signal history."""
        from src.dashboard.data_loader import load_all_signal_history

        # Save synthesis reports for two tickers on different dates
        for ticker, day_offset in [("TSM", 7), ("AVGO", 3)]:
            synth = _make_synthesis_report(ticker, Signal.BULLISH)
            synth.report_date = date.today() - timedelta(days=day_offset)
            save_report(
                ticker=ticker,
                agent_name="research_synthesizer",
                report_date=synth.report_date,
                report=synth.model_dump(mode="json"),
                signal=synth.overall_signal.value,
                confidence=synth.overall_confidence,
                db_path=db_path,
            )

        history = load_all_signal_history.__wrapped__(db_path=db_path)
        assert len(history) == 2
        # Should be sorted by date ascending (TSM first since it's older)
        assert history[0]["ticker"] == "TSM"
        assert history[1]["ticker"] == "AVGO"
        assert history[0]["date"] <= history[1]["date"]

    def test_ticker_detail_unknown_ticker(self, db_path):
        """load_ticker_detail returns defaults for a ticker not in the watchlist."""
        from src.dashboard.data_loader import load_ticker_detail

        detail = load_ticker_detail.__wrapped__("AAPL", db_path=db_path)
        assert detail["ticker"] == "AAPL"
        assert detail["name"] == "AAPL"
        assert detail["layer"] == "Unknown"
        assert detail["synthesis"] is None
        assert detail["analysts"] == []

    def test_scheduler_tracks_step_failures(self, db_path):
        """Scheduler alert includes which steps failed."""
        from src.automation.scheduler import scheduled_run

        with patch("src.agents.runner.run_all_orchestrated", side_effect=Exception("API down")), \
             patch("src.agents.runner.run_risk", side_effect=ValueError("No reports")), \
             patch("src.automation.earnings.refresh_earnings_calendar"), \
             patch("src.automation.alerts.detect_and_fire_alerts", return_value=[]), \
             patch("src.automation.notifier.notify"):

            scheduled_run(db_path=db_path)

        alerts = get_alerts(limit=10, db_path=db_path)
        completed = [a for a in alerts if a["alert_type"] == "run_completed"]
        assert len(completed) == 1
        assert "with errors" in completed[0]["title"]
        assert "orchestration" in completed[0]["detail"]
        assert "risk" in completed[0]["detail"]
        assert completed[0]["severity"] == "warning"
