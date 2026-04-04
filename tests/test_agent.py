"""Tests for the analyst agent — model validation, context building, and E2E."""

import os
import tempfile
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.data.models import (
    AnalysisReport,
    FundamentalsSnapshot,
    NewsArticle,
    PriceBar,
    PriceHistory,
    Signal,
)
from src.db.operations import (
    get_reports,
    init_db,
    save_report,
    upsert_fundamentals,
    upsert_news,
    upsert_prices,
)


# ============================================================
# AnalysisReport model validation tests
# ============================================================


class TestAnalysisReportModel:
    """Test the AnalysisReport Pydantic model."""

    def _valid_report_data(self, **overrides) -> dict:
        """Base valid report data."""
        data = {
            "ticker": "TSM",
            "agent": "general_analyst",
            "signal": "bullish",
            "confidence": 0.75,
            "thesis": "Strong fundamentals and growing demand.",
            "key_metrics": {"pe_ratio": 22.4, "revenue_growth_yoy": 0.35},
            "bull_case": "Revenue growth accelerates on AI demand.",
            "bear_case": "Geopolitical risk in Taiwan escalates.",
            "risks": ["Taiwan tensions", "Customer concentration"],
            "evidence": ["Q4 revenue beat by 12%", "CoWoS capacity doubling"],
            "thesis_change": False,
            "thesis_change_reason": None,
        }
        data.update(overrides)
        return data

    def test_valid_report(self):
        report = AnalysisReport(**self._valid_report_data())
        assert report.ticker == "TSM"
        assert report.signal == Signal.BULLISH
        assert report.confidence == 0.75

    def test_all_signals(self):
        for signal in ["bullish", "bearish", "neutral"]:
            report = AnalysisReport(**self._valid_report_data(signal=signal))
            assert report.signal.value == signal

    def test_invalid_signal_rejected(self):
        with pytest.raises(ValueError):
            AnalysisReport(**self._valid_report_data(signal="strong_buy"))

    def test_confidence_bounds(self):
        AnalysisReport(**self._valid_report_data(confidence=0.0))
        AnalysisReport(**self._valid_report_data(confidence=1.0))

        with pytest.raises(ValueError):
            AnalysisReport(**self._valid_report_data(confidence=-0.1))
        with pytest.raises(ValueError):
            AnalysisReport(**self._valid_report_data(confidence=1.1))

    def test_empty_thesis_rejected(self):
        with pytest.raises(ValueError):
            AnalysisReport(**self._valid_report_data(thesis=""))

    def test_empty_bull_case_rejected(self):
        with pytest.raises(ValueError):
            AnalysisReport(**self._valid_report_data(bull_case="  "))

    def test_empty_bear_case_rejected(self):
        with pytest.raises(ValueError):
            AnalysisReport(**self._valid_report_data(bear_case=""))

    def test_empty_risks_rejected(self):
        with pytest.raises(ValueError):
            AnalysisReport(**self._valid_report_data(risks=[]))

    def test_empty_evidence_rejected(self):
        with pytest.raises(ValueError):
            AnalysisReport(**self._valid_report_data(evidence=[]))

    def test_thesis_change_with_reason(self):
        report = AnalysisReport(
            **self._valid_report_data(
                thesis_change=True,
                thesis_change_reason="Revenue growth decelerated below 10%",
            )
        )
        assert report.thesis_change is True
        assert report.thesis_change_reason is not None

    def test_default_date_is_today(self):
        report = AnalysisReport(**self._valid_report_data())
        assert report.report_date == date.today()

    def test_serialization_roundtrip(self):
        report = AnalysisReport(**self._valid_report_data())
        json_str = report.model_dump_json()
        restored = AnalysisReport.model_validate_json(json_str)
        assert restored.ticker == report.ticker
        assert restored.signal == report.signal
        assert restored.confidence == report.confidence

    def test_key_metrics_with_nulls(self):
        report = AnalysisReport(
            **self._valid_report_data(
                key_metrics={"pe_ratio": 22.4, "forward_pe": None}
            )
        )
        assert report.key_metrics["pe_ratio"] == 22.4
        assert report.key_metrics["forward_pe"] is None


# ============================================================
# Context building tests
# ============================================================


class TestContextBuilding:
    """Test that context assembly produces correct output."""

    def test_format_price_section_empty(self):
        from src.agents.analyst import _format_price_section

        result = _format_price_section([])
        assert "No price data" in result

    def test_format_price_section_with_data(self):
        from src.agents.analyst import _format_price_section

        bars = [
            PriceBar(
                date=date(2026, 3, i + 1),
                open=100.0 + i,
                high=105.0 + i,
                low=95.0 + i,
                close=102.0 + i,
                volume=1000000 + i * 100,
            )
            for i in range(10)
        ]
        result = _format_price_section(bars)
        assert "Current:" in result
        assert "30-day range:" in result
        assert "$102.00" in result  # First close

    def test_format_price_section_single_bar(self):
        from src.agents.analyst import _format_price_section

        bars = [
            PriceBar(
                date=date(2026, 3, 1),
                open=100.0, high=105.0, low=95.0,
                close=102.0, volume=1000000,
            )
        ]
        result = _format_price_section(bars)
        assert "Current: $102.00" in result
        assert "5-day change: +0.0%" in result  # Fallback when < 5 bars

    def test_format_fundamentals_section_none(self):
        from src.agents.analyst import _format_fundamentals_section

        result = _format_fundamentals_section(None)
        assert "No fundamentals" in result

    def test_format_fundamentals_section_with_data(self):
        from src.agents.analyst import _format_fundamentals_section

        f = FundamentalsSnapshot(
            ticker="TSM",
            revenue=50_000_000_000,
            pe_ratio=22.4,
            gross_margin=0.57,
            analyst_target_mean=180.0,
            analyst_count=30,
        )
        result = _format_fundamentals_section(f)
        assert "Revenue:" in result
        assert "P/E Ratio: 22.4" in result
        assert "Gross Margin:" in result
        assert "Analyst Consensus" in result
        assert "Target Mean:" in result

    def test_build_context_includes_all_sections(self):
        """Verify context string has all expected sections."""
        from src.agents.analyst import build_context

        # Use a temp DB with no data — build_context should still produce all sections
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)
            context = build_context("TSM", db_path=tmp.name)

            assert "# Analysis Data for TSM" in context
            assert "Taiwan Semiconductor" in context
            assert "## Recent Price Action" in context
            assert "## Fundamentals" in context
            assert "## SEC Filings" in context
            assert "## Recent News" in context

    def test_build_context_with_data(self):
        """Verify context includes actual data when seeded."""
        from src.agents.analyst import build_context

        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)
            # Seed price data
            bars = [
                PriceBar(
                    date=date(2026, 3, i + 1),
                    open=170.0, high=175.0, low=165.0,
                    close=172.0 + i, volume=5_000_000,
                )
                for i in range(5)
            ]
            upsert_prices("TSM", PriceHistory(ticker="TSM", bars=bars), db_path=tmp.name)

            context = build_context("TSM", db_path=tmp.name)
            assert "$172.00" in context  # First close price appears


# ============================================================
# DB round-trip for reports
# ============================================================


class TestReportDBRoundTrip:
    """Test saving and retrieving reports from the database."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)
            yield tmp.name

    def test_save_and_retrieve_report(self, db_path):
        report = AnalysisReport(
            ticker="TSM",
            signal="bullish",
            confidence=0.8,
            thesis="Strong demand outlook.",
            bull_case="AI capex cycle continues.",
            bear_case="Geopolitical risk.",
            risks=["Taiwan tensions"],
            evidence=["Revenue beat expectations"],
        )

        save_report(
            ticker=report.ticker,
            agent_name=report.agent,
            report_date=report.report_date,
            report=report.model_dump(mode="json"),
            signal=report.signal.value,
            confidence=report.confidence,
            db_path=db_path,
        )

        reports = get_reports("TSM", db_path=db_path)
        assert len(reports) == 1
        assert reports[0]["signal"] == "bullish"
        assert reports[0]["confidence"] == 0.8
        assert reports[0]["report"]["ticker"] == "TSM"

    def test_multiple_reports_ordered_by_date(self, db_path):
        for i, signal in enumerate(["bullish", "neutral", "bearish"]):
            save_report(
                ticker="TSM",
                agent_name="general_analyst",
                report_date=date(2026, 4, i + 1),
                report={"ticker": "TSM", "signal": signal},
                signal=signal,
                confidence=0.7,
                db_path=db_path,
            )

        reports = get_reports("TSM", db_path=db_path)
        assert len(reports) == 3
        # Most recent first
        assert reports[0]["signal"] == "bearish"
        assert reports[2]["signal"] == "bullish"


# ============================================================
# E2E test — requires ANTHROPIC_API_KEY
# ============================================================


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping E2E test",
)
class TestE2EAnalysis:
    """End-to-end test: seed DB with real data, run agent, validate report."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)
            yield tmp.name

    def test_analyze_ticker_with_seeded_data(self, db_path):
        """Seed a ticker with minimal data, run the agent, validate the output."""
        # Seed some price data
        bars = [
            PriceBar(
                date=date(2026, 3, i + 1),
                open=170.0 + i,
                high=175.0 + i,
                low=165.0 + i,
                close=172.0 + i,
                volume=5_000_000,
            )
            for i in range(20)
            if date(2026, 3, i + 1).weekday() < 5  # skip weekends
        ]
        upsert_prices("TSM", PriceHistory(ticker="TSM", bars=bars), db_path=db_path)

        # Seed fundamentals
        fundamentals = FundamentalsSnapshot(
            ticker="TSM",
            revenue=70_000_000_000,
            revenue_growth_yoy=0.35,
            gross_margin=0.57,
            operating_margin=0.45,
            pe_ratio=22.4,
            forward_pe=18.5,
            market_cap=800_000_000_000,
            free_cash_flow=18_200_000_000,
            analyst_target_mean=195.0,
            analyst_count=35,
        )
        upsert_fundamentals(fundamentals, db_path=db_path)

        # Seed a news article
        articles = [
            NewsArticle(
                ticker="TSM",
                title="TSMC Reports Record Q4 Revenue on AI Chip Demand",
                source="Reuters",
                published_at=datetime(2026, 3, 15),
                summary="TSMC reported record quarterly revenue driven by strong AI chip demand.",
            ),
        ]
        upsert_news(articles, db_path=db_path)

        # Run the agent with mocked DB path
        with patch("src.agents.analyst.get_prices") as mock_prices, \
             patch("src.agents.analyst.get_latest_fundamentals") as mock_fund, \
             patch("src.agents.analyst.get_filings") as mock_filings, \
             patch("src.agents.analyst.get_news") as mock_news:

            mock_prices.return_value = PriceHistory(ticker="TSM", bars=bars)
            mock_fund.return_value = fundamentals
            mock_filings.return_value = []
            mock_news.return_value = articles

            report = analyze_ticker("TSM", save=False)

        # Validate the report
        assert report.ticker == "TSM"
        assert report.signal in [Signal.BULLISH, Signal.BEARISH, Signal.NEUTRAL]
        assert 0.0 <= report.confidence <= 1.0
        assert len(report.thesis) > 10
        assert len(report.bull_case) > 10
        assert len(report.bear_case) > 10
        assert len(report.risks) >= 1
        assert len(report.evidence) >= 1

        # Verify it's a valid Pydantic model (no validation errors)
        _ = report.model_dump_json()
