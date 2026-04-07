"""Tests for the fundamental analyst agent — derived metrics, context building, and E2E."""

import os
import tempfile
from datetime import date, datetime
from unittest.mock import patch

import pytest

from src.agents.fundamental import _compute_derived_metrics, build_fundamental_context
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
# Helper
# ============================================================


def _full_fundamentals(**overrides) -> FundamentalsSnapshot:
    """Create a FundamentalsSnapshot with all fields populated."""
    data = {
        "ticker": "TSM",
        "revenue": 70_000_000_000,
        "revenue_growth_yoy": 0.35,
        "net_income": 25_000_000_000,
        "gross_margin": 0.57,
        "operating_margin": 0.45,
        "net_margin": 0.357,
        "total_debt": 30_000_000_000,
        "total_cash": 50_000_000_000,
        "debt_to_equity": 0.25,
        "free_cash_flow": 18_200_000_000,
        "capital_expenditure": -20_000_000_000,
        "pe_ratio": 22.4,
        "forward_pe": 18.5,
        "ps_ratio": 11.4,
        "peg_ratio": 0.8,
        "ev_to_ebitda": 15.2,
        "market_cap": 800_000_000_000,
        "enterprise_value": 780_000_000_000,
        "beta": 1.15,
        "fifty_two_week_high": 200.0,
        "fifty_two_week_low": 120.0,
        "analyst_target_mean": 195.0,
        "analyst_target_median": 192.0,
        "analyst_target_high": 220.0,
        "analyst_target_low": 160.0,
        "analyst_count": 35,
        "recommendation": "buy",
    }
    data.update(overrides)
    return FundamentalsSnapshot(**data)


# ============================================================
# Derived metrics computation tests
# ============================================================


class TestDerivedMetrics:
    """Test _compute_derived_metrics produces correct computed ratios."""

    def test_fcf_yield(self):
        f = _full_fundamentals()
        result = _compute_derived_metrics(f)
        # FCF yield = 18.2B / 800B = 2.275%
        assert "FCF Yield: 2.27%" in result

    def test_earnings_yield(self):
        f = _full_fundamentals()
        result = _compute_derived_metrics(f)
        # Earnings yield = 1/22.4 = 4.46%
        assert "Earnings Yield: 4.46%" in result

    def test_forward_earnings_yield(self):
        f = _full_fundamentals()
        result = _compute_derived_metrics(f)
        assert "Forward Earnings Yield: 5.41%" in result

    def test_implied_earnings_growth(self):
        f = _full_fundamentals()
        result = _compute_derived_metrics(f)
        assert "Implied Earnings Growth" in result
        assert "+21.1%" in result

    def test_net_debt_values(self):
        f = _full_fundamentals()
        result = _compute_derived_metrics(f)
        # Net debt = 30B - 50B = -20B (net cash)
        assert "Net Debt: $-20,000,000,000" in result
        # Net Debt / FCF = -20B / 18.2B = -1.1x
        assert "Net Debt / FCF: -1.1x" in result

    def test_capex_intensity(self):
        f = _full_fundamentals()
        result = _compute_derived_metrics(f)
        assert "Capex Intensity" in result
        assert "28.6%" in result

    def test_fcf_conversion(self):
        f = _full_fundamentals()
        result = _compute_derived_metrics(f)
        assert "FCF Conversion" in result
        assert "72.8%" in result

    def test_52_week_range_position(self):
        f = _full_fundamentals()
        result = _compute_derived_metrics(f, current_price=172.0)
        assert "52-Week Range Position: 65%" in result

    def test_analyst_upside(self):
        f = _full_fundamentals()
        result = _compute_derived_metrics(f, current_price=172.0)
        assert "Analyst Target Upside/Downside: +13.4%" in result

    def test_peg_assessment_underpriced(self):
        f = _full_fundamentals(peg_ratio=0.8)
        result = _compute_derived_metrics(f)
        assert "PEG Ratio: 0.80" in result
        assert "underpriced" in result

    def test_peg_assessment_overpriced(self):
        f = _full_fundamentals(peg_ratio=2.5)
        result = _compute_derived_metrics(f)
        assert "PEG Ratio: 2.50" in result
        assert "overpriced" in result

    def test_peg_assessment_fair_value(self):
        """PEG between 1.0 and 2.0 should not have underpriced/overpriced label."""
        f = _full_fundamentals(peg_ratio=1.5)
        result = _compute_derived_metrics(f)
        assert "PEG Ratio: 1.50" in result
        assert "underpriced" not in result
        assert "overpriced" not in result

    def test_ev_to_fcf(self):
        f = _full_fundamentals()
        result = _compute_derived_metrics(f)
        assert "EV/FCF: 42.9" in result

    def test_all_none_fundamentals(self):
        f = FundamentalsSnapshot(ticker="TSM")
        result = _compute_derived_metrics(f)
        assert "Insufficient data" in result

    def test_partial_data_only_revenue_and_market_cap(self):
        """Only revenue and market cap — no derived metric conditions are met."""
        f = FundamentalsSnapshot(ticker="TSM", revenue=70_000_000_000, market_cap=800_000_000_000)
        result = _compute_derived_metrics(f)
        assert "Insufficient data" in result

    def test_zero_market_cap_no_crash(self):
        f = FundamentalsSnapshot(
            ticker="TSM", free_cash_flow=18_200_000_000, market_cap=0
        )
        result = _compute_derived_metrics(f)
        assert "FCF Yield:" not in result

    def test_negative_net_income_no_fcf_conversion(self):
        f = FundamentalsSnapshot(
            ticker="TSM", free_cash_flow=5_000_000_000, net_income=-1_000_000_000
        )
        result = _compute_derived_metrics(f)
        assert "FCF Conversion" not in result

    def test_zero_pe_ratio_no_earnings_yield(self):
        """pe_ratio=0 should not produce Earnings Yield (would be division by zero)."""
        f = FundamentalsSnapshot(ticker="TSM", pe_ratio=None)  # pe_ratio validator converts 0 to None
        result = _compute_derived_metrics(f)
        assert "Earnings Yield:" not in result

    def test_negative_fcf_still_shows_fcf_yield(self):
        """Negative FCF with positive market cap should show negative FCF Yield."""
        f = FundamentalsSnapshot(
            ticker="TSM", free_cash_flow=-5_000_000_000, market_cap=100_000_000_000
        )
        result = _compute_derived_metrics(f)
        assert "FCF Yield: -5.00%" in result

    def test_52_week_high_equals_low_no_crash(self):
        """When high == low, should skip range position (no division by zero)."""
        f = FundamentalsSnapshot(
            ticker="TSM", fifty_two_week_high=150.0, fifty_two_week_low=150.0
        )
        result = _compute_derived_metrics(f, current_price=150.0)
        assert "52-Week Range Position" not in result

    def test_current_price_zero_no_analyst_upside(self):
        """current_price=0 should not produce analyst upside (division by zero)."""
        f = FundamentalsSnapshot(ticker="TSM", analyst_target_mean=195.0)
        result = _compute_derived_metrics(f, current_price=0.0)
        assert "Analyst Target Upside" not in result


# ============================================================
# Context building tests
# ============================================================


class TestFundamentalContext:
    """Test that fundamental context includes derived metrics section."""

    def test_context_includes_derived_section_with_data(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)

            bars = [
                PriceBar(
                    date=date(2026, 3, i + 1),
                    open=170.0, high=175.0, low=165.0,
                    close=172.0, volume=5_000_000,
                )
                for i in range(5)
            ]
            upsert_prices("TSM", PriceHistory(ticker="TSM", bars=bars), db_path=tmp.name)

            fundamentals = FundamentalsSnapshot(
                ticker="TSM",
                revenue=70_000_000_000,
                net_income=25_000_000_000,
                free_cash_flow=18_200_000_000,
                market_cap=800_000_000_000,
                pe_ratio=22.4,
                forward_pe=18.5,
                fifty_two_week_high=200.0,
                fifty_two_week_low=120.0,
                analyst_target_mean=195.0,
            )
            upsert_fundamentals(fundamentals, db_path=tmp.name)

            context = build_fundamental_context("TSM", db_path=tmp.name)

            # Standard sections
            assert "# Analysis Data for TSM" in context
            assert "## Recent Price Action" in context
            assert "## Fundamentals" in context

            # Derived section
            assert "## Derived Financial Metrics" in context
            assert "FCF Yield:" in context
            assert "Earnings Yield:" in context

            # Price-dependent derived metrics (current_price from DB bars)
            assert "52-Week Range Position:" in context
            assert "Analyst Target Upside/Downside:" in context

    def test_context_without_fundamentals(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)

            context = build_fundamental_context("TSM", db_path=tmp.name)

            assert "# Analysis Data for TSM" in context
            assert "## Derived Financial Metrics" not in context

    def test_context_with_minimal_fundamentals(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)

            fundamentals = FundamentalsSnapshot(ticker="TSM", revenue=70_000_000_000)
            upsert_fundamentals(fundamentals, db_path=tmp.name)

            context = build_fundamental_context("TSM", db_path=tmp.name)

            assert "## Derived Financial Metrics" in context


# ============================================================
# Report model tests (agent name)
# ============================================================


class TestFundamentalReportModel:
    """Test that fundamental analyst reports have the correct agent name."""

    def test_agent_name(self):
        report = AnalysisReport(
            ticker="TSM",
            agent="fundamental_analyst",
            signal="bullish",
            confidence=0.75,
            thesis="Strong fundamentals driven by AI demand.",
            bull_case="Revenue growth accelerates.",
            bear_case="Margin compression from capex.",
            risks=["Geopolitical risk"],
            evidence=["35% YoY revenue growth"],
        )
        assert report.agent == "fundamental_analyst"

    def test_fundamental_report_serialization(self):
        report = AnalysisReport(
            ticker="TSM",
            agent="fundamental_analyst",
            signal="bullish",
            confidence=0.82,
            thesis="Strong fundamentals.",
            key_metrics={
                "revenue_growth_yoy": 0.35,
                "gross_margin": 0.57,
                "fcf_yield": 0.0228,
                "earnings_yield": 0.0446,
            },
            bull_case="AI demand continues.",
            bear_case="Valuation compressed.",
            risks=["Taiwan tensions", "Customer concentration"],
            evidence=["Revenue $70B", "FCF $18.2B"],
        )
        json_str = report.model_dump_json()
        restored = AnalysisReport.model_validate_json(json_str)
        assert restored.agent == "fundamental_analyst"
        assert restored.key_metrics["fcf_yield"] == 0.0228


# ============================================================
# DB round-trip for fundamental reports
# ============================================================


class TestFundamentalReportDB:
    """Test saving/retrieving fundamental analyst reports."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)
            yield tmp.name

    def test_save_and_retrieve_fundamental_report(self, db_path):
        report = AnalysisReport(
            ticker="TSM",
            agent="fundamental_analyst",
            signal="bullish",
            confidence=0.82,
            thesis="Strong fundamentals.",
            bull_case="Revenue growth.",
            bear_case="Margin risk.",
            risks=["Geopolitical"],
            evidence=["35% growth"],
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
        assert reports[0]["report"]["agent"] == "fundamental_analyst"
        assert reports[0]["signal"] == "bullish"
        assert reports[0]["confidence"] == 0.82

    def test_multiple_agents_same_ticker(self, db_path):
        """Both general and fundamental reports coexist for the same ticker."""
        for agent_name in ["general_analyst", "fundamental_analyst"]:
            save_report(
                ticker="TSM",
                agent_name=agent_name,
                report_date=date.today(),
                report={"ticker": "TSM", "agent": agent_name, "signal": "bullish"},
                signal="bullish",
                confidence=0.75,
                db_path=db_path,
            )

        reports = get_reports("TSM", db_path=db_path)
        assert len(reports) == 2
        agents = {r["report"]["agent"] for r in reports}
        assert "general_analyst" in agents
        assert "fundamental_analyst" in agents


# ============================================================
# E2E test — requires ANTHROPIC_API_KEY
# ============================================================


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping E2E test",
)
class TestE2EFundamentalAnalysis:
    """End-to-end: seed DB, run fundamental analyst, validate report."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)
            yield tmp.name

    def test_fundamental_analyze_ticker(self, db_path):
        """Seed data, run fundamental analyst, validate output."""
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
            if date(2026, 3, i + 1).weekday() < 5
        ]
        upsert_prices("TSM", PriceHistory(ticker="TSM", bars=bars), db_path=db_path)

        fundamentals = FundamentalsSnapshot(
            ticker="TSM",
            revenue=70_000_000_000,
            revenue_growth_yoy=0.35,
            gross_margin=0.57,
            operating_margin=0.45,
            net_margin=0.357,
            net_income=25_000_000_000,
            pe_ratio=22.4,
            forward_pe=18.5,
            market_cap=800_000_000_000,
            enterprise_value=780_000_000_000,
            free_cash_flow=18_200_000_000,
            capital_expenditure=-20_000_000_000,
            total_debt=30_000_000_000,
            total_cash=50_000_000_000,
            debt_to_equity=0.25,
            analyst_target_mean=195.0,
            analyst_count=35,
        )
        upsert_fundamentals(fundamentals, db_path=db_path)

        articles = [
            NewsArticle(
                ticker="TSM",
                title="TSMC Reports Record Q4 Revenue",
                source="Reuters",
                published_at=datetime(2026, 3, 15),
                summary="Record quarterly revenue driven by AI chip demand.",
            ),
        ]
        upsert_news(articles, db_path=db_path)

        from src.agents.fundamental import analyze_ticker

        report = analyze_ticker("TSM", save=False, db_path=db_path)

        assert report.ticker == "TSM"
        assert report.agent == "fundamental_analyst"
        assert report.signal in [Signal.BULLISH, Signal.BEARISH, Signal.NEUTRAL]
        assert 0.0 <= report.confidence <= 1.0
        assert len(report.thesis) > 10
        assert len(report.bull_case) > 10
        assert len(report.bear_case) > 10
        assert len(report.risks) >= 1
        assert len(report.evidence) >= 1
        _ = report.model_dump_json()
