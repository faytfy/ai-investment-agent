"""Tests for the Risk Manager agent.

Tests cover:
- PortfolioRiskReport model validation (valid, boundary, edge cases)
- Portfolio metrics computation (sector exposure, correlation, signal distribution)
- Context building (full, partial, empty)
- DB round-trips (save + load risk report)
- E2E with real API (skipped without key)
"""

import json
import os
import sqlite3
import tempfile
from datetime import date

import pytest

from src.config import WATCHLIST
from src.data.models import (
    PortfolioRiskReport,
    RiskLevel,
    Signal,
    SynthesisReport,
)
from src.db.operations import get_reports, init_db, save_report


# ============================================================
# Helpers
# ============================================================


def _make_synthesis(
    ticker: str = "TSM",
    signal: Signal = Signal.BULLISH,
    confidence: float = 0.8,
    recommendation: str = "BUY — strong fundamentals",
) -> SynthesisReport:
    """Create a minimal valid SynthesisReport for testing."""
    return SynthesisReport(
        ticker=ticker,
        overall_signal=signal,
        overall_confidence=confidence,
        analyst_agreement="3/3 bullish",
        bull_case_summary="Strong growth outlook",
        bear_case_summary="Valuation stretched",
        recommendation=recommendation,
        key_watch_items=["Earnings next quarter"],
        analyst_reports_used=["fundamental_analyst", "sentiment_analyst", "supply_chain_analyst"],
    )


def _make_risk_report(**overrides) -> PortfolioRiskReport:
    """Create a minimal valid PortfolioRiskReport for testing."""
    defaults = {
        "overall_risk_level": RiskLevel.MODERATE,
        "risk_summary": "Portfolio has moderate concentration in semiconductor sector.",
        "sector_exposure": {"Semiconductor": 0.44, "Power/Energy": 0.33, "Other": 0.23},
        "concentration_warnings": ["Semiconductor at 44% — above 30% threshold"],
        "correlation_flags": ["TSM + ASML (Semiconductor)"],
        "position_sizing": {
            "TSM": {"max_allocation": 0.12, "reason": "High conviction but geopolitical risk"},
        },
        "recommendations": ["Consider trimming semiconductor exposure"],
        "portfolio_signals": [
            {"ticker": "TSM", "signal": "bullish", "confidence": 0.8, "recommendation": "BUY"},
        ],
        "tickers_analyzed": ["TSM"],
    }
    defaults.update(overrides)
    return PortfolioRiskReport(**defaults)


# ============================================================
# Model validation tests
# ============================================================


class TestPortfolioRiskReportModel:
    """Tests for the PortfolioRiskReport Pydantic model."""

    def test_valid_report(self):
        report = _make_risk_report()
        assert report.overall_risk_level == RiskLevel.MODERATE
        assert report.risk_summary == "Portfolio has moderate concentration in semiconductor sector."
        assert len(report.recommendations) == 1
        assert report.tickers_analyzed == ["TSM"]

    def test_all_risk_levels(self):
        for level in RiskLevel:
            report = _make_risk_report(overall_risk_level=level)
            assert report.overall_risk_level == level

    def test_empty_risk_summary_rejected(self):
        with pytest.raises(ValueError, match="Risk summary cannot be empty"):
            _make_risk_report(risk_summary="")

    def test_whitespace_risk_summary_rejected(self):
        with pytest.raises(ValueError, match="Risk summary cannot be empty"):
            _make_risk_report(risk_summary="   ")

    def test_empty_recommendations_rejected(self):
        with pytest.raises(ValueError, match="Must provide at least one recommendation"):
            _make_risk_report(recommendations=[])

    def test_sector_exposure_valid_range(self):
        report = _make_risk_report(sector_exposure={"Semiconductor": 0.0, "Power": 1.0})
        assert report.sector_exposure["Semiconductor"] == 0.0
        assert report.sector_exposure["Power"] == 1.0

    def test_sector_exposure_negative_rejected(self):
        with pytest.raises(ValueError, match="Sector weight must be 0-1"):
            _make_risk_report(sector_exposure={"Semiconductor": -0.1})

    def test_sector_exposure_over_one_rejected(self):
        with pytest.raises(ValueError, match="Sector weight must be 0-1"):
            _make_risk_report(sector_exposure={"Semiconductor": 1.5})

    def test_empty_optional_lists_ok(self):
        report = _make_risk_report(
            concentration_warnings=[],
            correlation_flags=[],
        )
        assert report.concentration_warnings == []
        assert report.correlation_flags == []

    def test_default_report_date_is_today(self):
        report = _make_risk_report()
        assert report.report_date == date.today()

    def test_invalid_risk_level_rejected(self):
        with pytest.raises(ValueError):
            _make_risk_report(overall_risk_level="critical")

    def test_position_sizing_structure(self):
        report = _make_risk_report(
            position_sizing={
                "TSM": {"max_allocation": 0.12, "reason": "Geopolitical risk"},
                "AVGO": {"max_allocation": 0.15, "reason": "High conviction"},
            }
        )
        assert len(report.position_sizing) == 2
        assert report.position_sizing["TSM"]["max_allocation"] == 0.12


# ============================================================
# Portfolio metrics computation tests
# ============================================================


class TestComputePortfolioMetrics:
    """Tests for compute_portfolio_metrics()."""

    def test_full_watchlist_sector_exposure(self):
        from src.agents.risk_manager import compute_portfolio_metrics

        reports = [_make_synthesis(ticker=t) for t in WATCHLIST]
        metrics = compute_portfolio_metrics(reports)

        # Should have sector exposure summing to ~1.0
        total = sum(metrics["sector_exposure"].values())
        assert abs(total - 1.0) < 0.01

        # Semiconductor should be the largest sector (TSM, AVGO, ASML)
        assert "Semiconductor" in metrics["sector_exposure"]

    def test_equal_weight_calculation(self):
        from src.agents.risk_manager import compute_portfolio_metrics

        reports = [_make_synthesis(ticker=t) for t in WATCHLIST]
        metrics = compute_portfolio_metrics(reports)

        expected_weight = 1.0 / len(WATCHLIST)
        assert abs(metrics["equal_weight"] - expected_weight) < 0.001

    def test_signal_distribution(self):
        from src.agents.risk_manager import compute_portfolio_metrics

        reports = [
            _make_synthesis("TSM", signal=Signal.BULLISH),
            _make_synthesis("AVGO", signal=Signal.BULLISH),
            _make_synthesis("GEV", signal=Signal.NEUTRAL),
        ]
        metrics = compute_portfolio_metrics(reports)

        assert metrics["signal_distribution"]["bullish"] == 2
        assert metrics["signal_distribution"]["neutral"] == 1

    def test_same_layer_pairs_detected(self):
        from src.agents.risk_manager import compute_portfolio_metrics

        reports = [_make_synthesis(ticker=t) for t in WATCHLIST]
        metrics = compute_portfolio_metrics(reports)

        # Power/Energy has 3 stocks (GEV, ETN, CEG) → 3 pairs
        power_pairs = [p for p in metrics["same_layer_pairs"] if p[2] == "Power/Energy"]
        assert len(power_pairs) == 3  # GEV+ETN, GEV+CEG, ETN+CEG

    def test_coverage_full(self):
        from src.agents.risk_manager import compute_portfolio_metrics

        reports = [_make_synthesis(ticker=t) for t in WATCHLIST]
        metrics = compute_portfolio_metrics(reports)
        assert metrics["coverage"] == 1.0

    def test_coverage_partial(self):
        from src.agents.risk_manager import compute_portfolio_metrics

        reports = [_make_synthesis("TSM")]
        metrics = compute_portfolio_metrics(reports)
        assert metrics["coverage"] == 1.0 / len(WATCHLIST)

    def test_coverage_empty(self):
        from src.agents.risk_manager import compute_portfolio_metrics

        metrics = compute_portfolio_metrics([])
        assert metrics["coverage"] == 0.0

    def test_missing_tickers_tracked(self):
        from src.agents.risk_manager import compute_portfolio_metrics

        reports = [_make_synthesis("TSM"), _make_synthesis("AVGO")]
        metrics = compute_portfolio_metrics(reports)

        assert "TSM" not in metrics["tickers_missing"]
        assert "AVGO" not in metrics["tickers_missing"]
        # All other watchlist tickers should be in missing
        assert len(metrics["tickers_missing"]) == len(WATCHLIST) - 2

    def test_signal_distribution_all_same(self):
        from src.agents.risk_manager import compute_portfolio_metrics

        reports = [
            _make_synthesis("TSM", signal=Signal.BULLISH),
            _make_synthesis("AVGO", signal=Signal.BULLISH),
            _make_synthesis("GEV", signal=Signal.BULLISH),
        ]
        metrics = compute_portfolio_metrics(reports)
        assert metrics["signal_distribution"] == {"bullish": 3}
        assert "bearish" not in metrics["signal_distribution"]

    def test_custom_watchlist(self):
        from src.agents.risk_manager import compute_portfolio_metrics

        custom = {
            "AAA": {"name": "A Corp", "layer": "Power/Grid", "tier": 1},
            "BBB": {"name": "B Corp", "layer": "Power/Grid", "tier": 1},
        }
        reports = [_make_synthesis("AAA"), _make_synthesis("BBB")]
        metrics = compute_portfolio_metrics(reports, watchlist=custom)

        assert metrics["sector_exposure"]["Power/Energy"] == 1.0
        assert metrics["equal_weight"] == 0.5
        assert len(metrics["same_layer_pairs"]) == 1


# ============================================================
# Context building tests
# ============================================================


class TestBuildRiskContext:
    """Tests for build_risk_context()."""

    def test_full_context(self):
        from src.agents.risk_manager import build_risk_context, compute_portfolio_metrics

        reports = [
            _make_synthesis("TSM", signal=Signal.BULLISH),
            _make_synthesis("GEV", signal=Signal.NEUTRAL),
        ]
        metrics = compute_portfolio_metrics(reports)
        context = build_risk_context(reports, metrics)

        assert "Portfolio Risk Assessment Data" in context
        assert "TSM" in context
        assert "GEV" in context
        assert "Sector Exposure" in context
        assert "Signal Distribution" in context

    def test_empty_reports(self):
        from src.agents.risk_manager import build_risk_context, compute_portfolio_metrics

        metrics = compute_portfolio_metrics([])
        context = build_risk_context([], metrics)

        assert "0 of" in context
        assert "0%" in context

    def test_thesis_change_flagged(self):
        from src.agents.risk_manager import build_risk_context, compute_portfolio_metrics

        report = _make_synthesis("TSM")
        report = report.model_copy(update={"thesis_changed_since_last": True})
        reports = [report]
        metrics = compute_portfolio_metrics(reports)
        context = build_risk_context(reports, metrics)

        assert "THESIS CHANGE DETECTED" in context

    def test_disagreements_included(self):
        from src.agents.risk_manager import build_risk_context, compute_portfolio_metrics

        report = _make_synthesis("TSM")
        report = report.model_copy(
            update={"disagreement_flags": ["Sentiment vs fundamentals on Taiwan risk"]}
        )
        reports = [report]
        metrics = compute_portfolio_metrics(reports)
        context = build_risk_context(reports, metrics)

        assert "Taiwan risk" in context

    def test_missing_tickers_shown(self):
        from src.agents.risk_manager import build_risk_context, compute_portfolio_metrics

        reports = [_make_synthesis("TSM")]
        metrics = compute_portfolio_metrics(reports)
        context = build_risk_context(reports, metrics)

        assert "Missing reports" in context


# ============================================================
# Tool schema tests
# ============================================================


class TestRiskToolSchema:
    """Tests for the RISK_TOOL schema."""

    def test_schema_has_required_fields(self):
        from src.agents.risk_manager import RISK_TOOL

        required = RISK_TOOL["input_schema"]["required"]
        assert "overall_risk_level" in required
        assert "risk_summary" in required
        assert "sector_exposure" in required
        assert "recommendations" in required

    def test_risk_level_enum_matches_model(self):
        from src.agents.risk_manager import RISK_TOOL

        schema_enum = RISK_TOOL["input_schema"]["properties"]["overall_risk_level"]["enum"]
        model_values = [level.value for level in RiskLevel]
        assert sorted(schema_enum) == sorted(model_values)


# ============================================================
# DB round-trip tests
# ============================================================


class TestRiskManagerDB:
    """Tests for saving and loading risk reports."""

    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        init_db(self.db_path)

    def teardown_method(self):
        os.unlink(self.db_path)

    def _ensure_portfolio(self):
        """Seed a PORTFOLIO row in stocks table for FK compliance."""
        from src.agents.risk_manager import _ensure_portfolio_stock
        _ensure_portfolio_stock(self.db_path)

    def test_save_and_load_risk_report(self):
        self._ensure_portfolio()
        report = _make_risk_report()
        save_report(
            ticker="PORTFOLIO",
            agent_name="risk_manager",
            report_date=report.report_date,
            report=report.model_dump(mode="json"),
            signal="neutral",
            confidence=0.0,
            db_path=self.db_path,
        )

        rows = get_reports("PORTFOLIO", agent_name="risk_manager", db_path=self.db_path)
        assert len(rows) == 1

        loaded = PortfolioRiskReport(**rows[0]["report"])
        assert loaded.overall_risk_level == RiskLevel.MODERATE
        assert loaded.risk_summary == report.risk_summary
        assert loaded.tickers_analyzed == ["TSM"]

    def test_multiple_risk_reports_stored(self):
        self._ensure_portfolio()
        for level in [RiskLevel.LOW, RiskLevel.HIGH]:
            report = _make_risk_report(overall_risk_level=level)
            save_report(
                ticker="PORTFOLIO",
                agent_name="risk_manager",
                report_date=report.report_date,
                report=report.model_dump(mode="json"),
                signal="neutral",
                confidence=0.0,
                db_path=self.db_path,
            )

        rows = get_reports("PORTFOLIO", agent_name="risk_manager", limit=10, db_path=self.db_path)
        assert len(rows) == 2
        levels = {PortfolioRiskReport(**r["report"]).overall_risk_level for r in rows}
        assert RiskLevel.LOW in levels
        assert RiskLevel.HIGH in levels

    def test_load_all_synthesis_reports_empty_db(self):
        from src.agents.risk_manager import _load_all_synthesis_reports
        reports = _load_all_synthesis_reports(db_path=self.db_path)
        assert reports == []

    def test_load_all_synthesis_reports_with_data(self):
        from src.agents.risk_manager import _load_all_synthesis_reports

        # Save a synthesis report for TSM
        synth = _make_synthesis("TSM")
        save_report(
            ticker="TSM",
            agent_name="research_synthesizer",
            report_date=synth.report_date,
            report=synth.model_dump(mode="json"),
            signal=synth.overall_signal.value,
            confidence=synth.overall_confidence,
            db_path=self.db_path,
        )

        reports = _load_all_synthesis_reports(db_path=self.db_path)
        assert len(reports) == 1
        assert reports[0].ticker == "TSM"

    def test_load_all_synthesis_reports_skips_invalid(self):
        from src.agents.risk_manager import _load_all_synthesis_reports

        # Save a malformed report for TSM
        save_report(
            ticker="TSM",
            agent_name="research_synthesizer",
            report_date=date.today(),
            report={"invalid": "data"},
            signal="bullish",
            confidence=0.5,
            db_path=self.db_path,
        )

        reports = _load_all_synthesis_reports(db_path=self.db_path)
        assert len(reports) == 0

    def test_analyze_portfolio_no_reports_raises(self):
        from src.agents.risk_manager import analyze_portfolio

        with pytest.raises(ValueError, match="No synthesis reports found"):
            analyze_portfolio(save=False, db_path=self.db_path)

    def test_synthesis_report_round_trip_for_risk_input(self):
        """Verify synthesis reports can be saved and loaded as risk manager input."""
        synth = _make_synthesis("TSM")
        save_report(
            ticker="TSM",
            agent_name="research_synthesizer",
            report_date=synth.report_date,
            report=synth.model_dump(mode="json"),
            signal=synth.overall_signal.value,
            confidence=synth.overall_confidence,
            db_path=self.db_path,
        )

        rows = get_reports("TSM", agent_name="research_synthesizer", db_path=self.db_path)
        assert len(rows) == 1
        loaded = SynthesisReport(**rows[0]["report"])
        assert loaded.ticker == "TSM"
        assert loaded.overall_signal == Signal.BULLISH


# ============================================================
# E2E test (skipped without API key)
# ============================================================


@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping E2E risk manager test",
)
class TestE2ERiskManager:
    """End-to-end test with real Claude API."""

    def test_risk_assessment_with_mock_reports(self):
        from src.agents.risk_manager import run_risk_manager

        reports = [
            _make_synthesis("TSM", Signal.BULLISH, 0.85),
            _make_synthesis("AVGO", Signal.BULLISH, 0.75),
            _make_synthesis("GEV", Signal.NEUTRAL, 0.60),
            _make_synthesis("CEG", Signal.BEARISH, 0.55),
        ]

        result = run_risk_manager(reports, save=False)

        assert isinstance(result, PortfolioRiskReport)
        assert result.overall_risk_level in list(RiskLevel)
        assert len(result.risk_summary) > 10
        assert len(result.recommendations) >= 1
        assert len(result.tickers_analyzed) == 4
