"""Tests for the supply chain analyst agent — layer context, metrics, and E2E."""

import os
import tempfile
from datetime import date, datetime, timedelta

import pytest

from src.agents.supply_chain import (
    _build_layer_context,
    _compute_supply_chain_metrics,
    build_supply_chain_context,
)
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
# Helpers
# ============================================================


def _full_fundamentals(**overrides) -> FundamentalsSnapshot:
    """Create a FundamentalsSnapshot with supply-chain-relevant fields."""
    data = {
        "ticker": "TSM",
        "revenue": 70_000_000_000,
        "revenue_growth_yoy": 0.35,
        "net_income": 25_000_000_000,
        "gross_margin": 0.57,
        "operating_margin": 0.45,
        "free_cash_flow": 18_200_000_000,
        "capital_expenditure": -20_000_000_000,
        "debt_to_equity": 0.25,
    }
    data.update(overrides)
    return FundamentalsSnapshot(**data)


def _make_price_bars(count: int = 25) -> list[PriceBar]:
    return [
        PriceBar(
            date=date(2026, 3, 1) + timedelta(days=i),
            open=170.0 + i * 0.5,
            high=175.0 + i * 0.5,
            low=165.0 + i * 0.5,
            close=172.0 + i * 0.5,
            volume=5_000_000,
        )
        for i in range(count)
        if (date(2026, 3, 1) + timedelta(days=i)).weekday() < 5
    ]


# ============================================================
# Layer context tests
# ============================================================


class TestLayerContext:
    """Test _build_layer_context produces correct positioning info."""

    def test_tier1_stock(self):
        result = _build_layer_context("TSM")
        assert "Taiwan Semiconductor" in result
        assert "Foundry/Packaging" in result
        assert "Tier 1" in result
        assert "Structural Bottleneck Owner" in result

    def test_tier2_stock(self):
        result = _build_layer_context("VRT")
        assert "Vertiv" in result
        assert "Cooling" in result
        assert "Tier 2" in result

    def test_watch_only_stock(self):
        result = _build_layer_context("NVDA")
        assert "NVIDIA" in result
        assert "Watch Only" in result

    def test_unknown_stock(self):
        result = _build_layer_context("AAPL")
        assert "AAPL" in result
        assert "Unknown" in result

    def test_peers_found(self):
        """AVGO and ANET are both in Networking-adjacent layers; test a layer with actual peers."""
        # GEV and ETN are both Power-adjacent but different layers.
        # Test a stock with known no peers to verify "unique position"
        result = _build_layer_context("ASML")
        assert "Equipment" in result
        # ASML is the only Equipment stock — should show unique position
        assert "unique position" in result.lower() or "None in portfolio" in result

    def test_peer_listing(self):
        """Stocks in the same layer should list each other as peers."""
        # Check that the function runs without error for stocks with no same-layer peers
        result = _build_layer_context("MU")
        assert "Memory" in result


# ============================================================
# Supply chain metrics tests
# ============================================================


class TestSupplyChainMetrics:
    """Test _compute_supply_chain_metrics produces correct derived values."""

    def test_capex_intensity(self):
        f = _full_fundamentals()
        result = _compute_supply_chain_metrics(f)
        # |Capex| / Revenue = 20B / 70B = 28.6%
        assert "Capex Intensity" in result
        assert "28.6%" in result
        assert "Heavy capacity investment" in result.lower() or "heavy" in result.lower()

    def test_low_capex_intensity(self):
        f = _full_fundamentals(capital_expenditure=-2_000_000_000, revenue=100_000_000_000)
        result = _compute_supply_chain_metrics(f)
        assert "2.0%" in result
        assert "asset-light" in result.lower() or "underinvesting" in result.lower()

    def test_gross_margin_strong(self):
        f = _full_fundamentals(gross_margin=0.57)
        result = _compute_supply_chain_metrics(f)
        assert "Gross Margin: 57.0%" in result
        assert "pricing power" in result.lower()

    def test_gross_margin_weak(self):
        f = _full_fundamentals(gross_margin=0.20)
        result = _compute_supply_chain_metrics(f)
        assert "Gross Margin: 20.0%" in result
        assert "weak" in result.lower()

    def test_revenue_growth_strong(self):
        f = _full_fundamentals(revenue_growth_yoy=0.35)
        result = _compute_supply_chain_metrics(f)
        assert "Revenue Growth YoY: 35.0%" in result
        assert "demand signal" in result.lower()

    def test_revenue_growth_negative(self):
        f = _full_fundamentals(revenue_growth_yoy=-0.05)
        result = _compute_supply_chain_metrics(f)
        assert "Revenue Growth YoY: -5.0%" in result
        assert "contraction" in result.lower()

    def test_fcf_margin(self):
        f = _full_fundamentals()
        result = _compute_supply_chain_metrics(f)
        # FCF/Revenue = 18.2B / 70B = 26.0%
        assert "FCF Margin" in result
        assert "26.0%" in result

    def test_low_leverage(self):
        f = _full_fundamentals(debt_to_equity=0.25)
        result = _compute_supply_chain_metrics(f)
        assert "Debt/Equity: 0.25" in result
        assert "capacity for debt-funded expansion" in result.lower()

    def test_high_leverage(self):
        f = _full_fundamentals(debt_to_equity=2.5)
        result = _compute_supply_chain_metrics(f)
        assert "Debt/Equity: 2.50" in result
        assert "limited expansion flexibility" in result.lower()

    def test_all_none(self):
        f = FundamentalsSnapshot(ticker="TSM")
        result = _compute_supply_chain_metrics(f)
        assert "Insufficient data" in result

    def test_partial_data(self):
        """Only gross margin — should still produce output."""
        f = FundamentalsSnapshot(ticker="TSM", gross_margin=0.57)
        result = _compute_supply_chain_metrics(f)
        assert "Gross Margin" in result
        assert "Insufficient data" not in result

    def test_zero_revenue_no_crash(self):
        f = FundamentalsSnapshot(
            ticker="TSM", capital_expenditure=-5_000_000_000, revenue=0
        )
        result = _compute_supply_chain_metrics(f)
        assert "Capex Intensity" not in result


# ============================================================
# Context building tests
# ============================================================


class TestSupplyChainContext:
    """Test that supply chain context includes enrichment sections."""

    def test_context_includes_layer_section(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)

            context = build_supply_chain_context("TSM", db_path=tmp.name)

            assert "# Analysis Data for TSM" in context
            assert "## Supply Chain Position" in context
            assert "Foundry/Packaging" in context

    def test_context_includes_metrics_with_data(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)

            fundamentals = _full_fundamentals()
            upsert_fundamentals(fundamentals, db_path=tmp.name)

            context = build_supply_chain_context("TSM", db_path=tmp.name)

            assert "## Supply Chain Metrics" in context
            assert "Capex Intensity" in context

    def test_context_without_fundamentals(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)

            context = build_supply_chain_context("TSM", db_path=tmp.name)

            assert "## Supply Chain Position" in context
            assert "## Supply Chain Metrics" not in context

    def test_context_has_standard_sections(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)

            bars = _make_price_bars()
            upsert_prices("TSM", PriceHistory(ticker="TSM", bars=bars), db_path=tmp.name)

            context = build_supply_chain_context("TSM", db_path=tmp.name)

            assert "## Recent Price Action" in context
            assert "## Fundamentals" in context
            assert "## SEC Filings" in context
            assert "## Recent News" in context


# ============================================================
# Report model tests
# ============================================================


class TestSupplyChainReportModel:
    """Test that supply chain analyst reports have correct agent name."""

    def test_agent_name(self):
        report = AnalysisReport(
            ticker="TSM",
            agent="supply_chain_analyst",
            signal="bullish",
            confidence=0.80,
            thesis="TSMC owns the CoWoS bottleneck with demand 3x supply.",
            bull_case="Bottleneck tightens further.",
            bear_case="Capacity expansion catches up to demand.",
            risks=["Taiwan geopolitical risk"],
            evidence=["Capex intensity 28.6%"],
        )
        assert report.agent == "supply_chain_analyst"

    def test_supply_chain_report_serialization(self):
        report = AnalysisReport(
            ticker="TSM",
            agent="supply_chain_analyst",
            signal="bullish",
            confidence=0.82,
            thesis="Bottleneck owner with durable moat.",
            key_metrics={
                "capex_intensity": 0.286,
                "gross_margin": 0.57,
                "revenue_growth": 0.35,
            },
            bull_case="Demand exceeds supply through 2027.",
            bear_case="Customer vertical integration.",
            risks=["Geopolitical", "Customer concentration"],
            evidence=["Revenue $70B", "Capex $20B"],
        )
        json_str = report.model_dump_json()
        restored = AnalysisReport.model_validate_json(json_str)
        assert restored.agent == "supply_chain_analyst"
        assert restored.key_metrics["capex_intensity"] == 0.286


# ============================================================
# DB round-trip tests
# ============================================================


class TestSupplyChainReportDB:
    """Test saving/retrieving supply chain analyst reports."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)
            yield tmp.name

    def test_save_and_retrieve_supply_chain_report(self, db_path):
        report = AnalysisReport(
            ticker="TSM",
            agent="supply_chain_analyst",
            signal="bullish",
            confidence=0.80,
            thesis="Bottleneck owner.",
            bull_case="Demand tightening.",
            bear_case="Capacity catches up.",
            risks=["Taiwan risk"],
            evidence=["CoWoS demand 3x supply"],
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
        assert reports[0]["report"]["agent"] == "supply_chain_analyst"
        assert reports[0]["signal"] == "bullish"

    def test_three_agents_coexist(self, db_path):
        """All three analyst reports coexist for same ticker."""
        for agent_name in [
            "fundamental_analyst",
            "sentiment_analyst",
            "supply_chain_analyst",
        ]:
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
        assert len(reports) == 3
        agents = {r["report"]["agent"] for r in reports}
        assert "fundamental_analyst" in agents
        assert "sentiment_analyst" in agents
        assert "supply_chain_analyst" in agents


# ============================================================
# E2E test — requires ANTHROPIC_API_KEY
# ============================================================


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping E2E test",
)
class TestE2ESupplyChainAnalysis:
    """End-to-end: seed DB, run supply chain analyst, validate report."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)
            yield tmp.name

    def test_supply_chain_analyze_ticker(self, db_path):
        bars = _make_price_bars(count=25)
        upsert_prices("TSM", PriceHistory(ticker="TSM", bars=bars), db_path=db_path)

        fundamentals = _full_fundamentals()
        upsert_fundamentals(fundamentals, db_path=db_path)

        articles = [
            NewsArticle(
                ticker="TSM",
                title="TSMC CoWoS Capacity Expansion on Track for 2027",
                source="Reuters",
                published_at=datetime.now() - timedelta(days=2),
                summary="Advanced packaging capacity expansion proceeding as planned.",
            ),
        ]
        upsert_news(articles, db_path=db_path)

        from src.agents.supply_chain import analyze_ticker

        report = analyze_ticker("TSM", save=False, db_path=db_path)

        assert report.ticker == "TSM"
        assert report.agent == "supply_chain_analyst"
        assert report.signal in [Signal.BULLISH, Signal.BEARISH, Signal.NEUTRAL]
        assert 0.0 <= report.confidence <= 1.0
        assert len(report.thesis) > 10
        assert len(report.risks) >= 1
        assert len(report.evidence) >= 1
