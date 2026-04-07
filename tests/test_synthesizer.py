"""Tests for the synthesizer agent, SynthesisReport model, and LangGraph orchestrator."""

import json
import os
import tempfile
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.data.models import (
    AnalysisReport,
    Signal,
    SynthesisReport,
)
from src.agents.synthesizer import (
    SYNTHESIS_TOOL,
    build_synthesis_context,
    _load_analyst_reports_from_db,
    run_synthesizer,
)
from src.db.operations import (
    get_reports,
    init_db,
    save_report,
)


# ============================================================
# Helpers
# ============================================================


def _make_report(
    agent: str = "fundamental_analyst",
    signal: str = "bullish",
    confidence: float = 0.75,
    **overrides,
) -> AnalysisReport:
    """Create a test AnalysisReport."""
    data = {
        "ticker": "TSM",
        "agent": agent,
        "signal": Signal(signal),
        "confidence": confidence,
        "thesis": f"Test thesis from {agent}",
        "key_metrics": {"pe_ratio": 22.4},
        "bull_case": f"Bull case from {agent}",
        "bear_case": f"Bear case from {agent}",
        "risks": [f"Risk from {agent}"],
        "evidence": [f"Evidence from {agent}"],
        "thesis_change": False,
        "thesis_change_reason": None,
    }
    data.update(overrides)
    return AnalysisReport(**data)


def _three_reports() -> list[AnalysisReport]:
    """Create a standard set of 3 analyst reports."""
    return [
        _make_report("fundamental_analyst", "bullish", 0.80),
        _make_report("sentiment_analyst", "neutral", 0.55),
        _make_report("supply_chain_analyst", "bullish", 0.70),
    ]


# ============================================================
# SynthesisReport Model Tests
# ============================================================


class TestSynthesisReportModel:
    """Test SynthesisReport Pydantic model validation."""

    def test_valid_synthesis(self):
        report = SynthesisReport(
            ticker="TSM",
            overall_signal=Signal.BULLISH,
            overall_confidence=0.78,
            analyst_agreement="2/3 bullish, 1/3 neutral",
            disagreement_flags=["Sentiment notes negative news cycle"],
            bull_case_summary="Strong fundamentals and supply chain position",
            bear_case_summary="Geopolitical risks remain",
            recommendation="HOLD — thesis intact",
            thesis_changed_since_last=False,
            key_watch_items=["Q1 2026 earnings on April 17"],
            analyst_reports_used=["fundamental_analyst", "sentiment_analyst", "supply_chain_analyst"],
        )
        assert report.overall_signal == Signal.BULLISH
        assert report.overall_confidence == 0.78
        assert len(report.analyst_reports_used) == 3

    def test_confidence_bounds(self):
        with pytest.raises(ValueError):
            SynthesisReport(
                ticker="TSM",
                overall_signal=Signal.BULLISH,
                overall_confidence=1.5,
                analyst_agreement="3/3 bullish",
                bull_case_summary="Bull",
                bear_case_summary="Bear",
                recommendation="BUY",
                key_watch_items=["Earnings"],
            )

    def test_confidence_lower_bound(self):
        with pytest.raises(ValueError):
            SynthesisReport(
                ticker="TSM",
                overall_signal=Signal.BULLISH,
                overall_confidence=-0.1,
                analyst_agreement="3/3 bullish",
                bull_case_summary="Bull",
                bear_case_summary="Bear",
                recommendation="BUY",
                key_watch_items=["Earnings"],
            )

    def test_empty_text_fields_rejected(self):
        with pytest.raises(ValueError):
            SynthesisReport(
                ticker="TSM",
                overall_signal=Signal.BULLISH,
                overall_confidence=0.70,
                analyst_agreement="",
                bull_case_summary="Bull",
                bear_case_summary="Bear",
                recommendation="BUY",
                key_watch_items=["Earnings"],
            )

    def test_empty_recommendation_rejected(self):
        with pytest.raises(ValueError):
            SynthesisReport(
                ticker="TSM",
                overall_signal=Signal.BULLISH,
                overall_confidence=0.70,
                analyst_agreement="3/3 bullish",
                bull_case_summary="Bull",
                bear_case_summary="Bear",
                recommendation="  ",
                key_watch_items=["Earnings"],
            )

    def test_empty_watch_items_rejected(self):
        with pytest.raises(ValueError):
            SynthesisReport(
                ticker="TSM",
                overall_signal=Signal.BULLISH,
                overall_confidence=0.70,
                analyst_agreement="3/3 bullish",
                bull_case_summary="Bull",
                bear_case_summary="Bear",
                recommendation="BUY",
                key_watch_items=[],
            )

    def test_default_values(self):
        report = SynthesisReport(
            ticker="TSM",
            overall_signal=Signal.NEUTRAL,
            overall_confidence=0.50,
            analyst_agreement="Mixed",
            bull_case_summary="Bull",
            bear_case_summary="Bear",
            recommendation="HOLD",
            key_watch_items=["Something"],
        )
        assert report.thesis_changed_since_last is False
        assert report.disagreement_flags == []
        assert report.analyst_reports_used == []
        assert report.report_date == date.today()

    def test_all_signals(self):
        for signal in Signal:
            report = SynthesisReport(
                ticker="TSM",
                overall_signal=signal,
                overall_confidence=0.50,
                analyst_agreement="test",
                bull_case_summary="Bull",
                bear_case_summary="Bear",
                recommendation="HOLD",
                key_watch_items=["Item"],
            )
            assert report.overall_signal == signal

    def test_confidence_boundary_zero(self):
        report = SynthesisReport(
            ticker="TSM",
            overall_signal=Signal.BEARISH,
            overall_confidence=0.0,
            analyst_agreement="0/3 confident",
            bull_case_summary="Bull",
            bear_case_summary="Bear",
            recommendation="HOLD",
            key_watch_items=["Wait for data"],
        )
        assert report.overall_confidence == 0.0

    def test_confidence_boundary_one(self):
        report = SynthesisReport(
            ticker="TSM",
            overall_signal=Signal.BULLISH,
            overall_confidence=1.0,
            analyst_agreement="3/3 bullish",
            bull_case_summary="Bull",
            bear_case_summary="Bear",
            recommendation="BUY",
            key_watch_items=["Monitor"],
        )
        assert report.overall_confidence == 1.0

    def test_model_dump_json(self):
        report = SynthesisReport(
            ticker="TSM",
            overall_signal=Signal.BULLISH,
            overall_confidence=0.78,
            analyst_agreement="2/3 bullish",
            bull_case_summary="Bull",
            bear_case_summary="Bear",
            recommendation="BUY",
            key_watch_items=["Earnings"],
        )
        dumped = report.model_dump(mode="json")
        assert dumped["overall_signal"] == "bullish"
        assert isinstance(dumped["report_date"], str)


# ============================================================
# Context Building Tests
# ============================================================


class TestSynthesisContext:
    """Test build_synthesis_context."""

    def test_context_with_three_reports(self):
        reports = _three_reports()
        context = build_synthesis_context("TSM", reports)
        assert "# Synthesis Data for TSM" in context
        assert "Number of analyst reports: 3" in context
        assert "fundamental_analyst Report" in context
        assert "sentiment_analyst Report" in context
        assert "supply_chain_analyst Report" in context

    def test_context_includes_signals(self):
        reports = _three_reports()
        context = build_synthesis_context("TSM", reports)
        assert "bullish" in context
        assert "neutral" in context
        assert "80%" in context
        assert "55%" in context

    def test_context_includes_thesis(self):
        reports = _three_reports()
        context = build_synthesis_context("TSM", reports)
        assert "Test thesis from fundamental_analyst" in context

    def test_context_includes_metrics(self):
        reports = _three_reports()
        context = build_synthesis_context("TSM", reports)
        assert "pe_ratio" in context

    def test_context_includes_risks_and_evidence(self):
        reports = _three_reports()
        context = build_synthesis_context("TSM", reports)
        assert "Risk from fundamental_analyst" in context
        assert "Evidence from sentiment_analyst" in context

    def test_context_with_thesis_change(self):
        reports = [
            _make_report("fundamental_analyst", thesis_change=True,
                         thesis_change_reason="Revenue miss signals slowdown"),
        ]
        context = build_synthesis_context("TSM", reports)
        assert "THESIS CHANGE" in context
        assert "Revenue miss signals slowdown" in context

    def test_context_with_no_reports(self):
        context = build_synthesis_context("TSM", [])
        assert "No analyst reports available" in context

    def test_context_with_one_report(self):
        reports = [_make_report("fundamental_analyst")]
        context = build_synthesis_context("TSM", reports)
        assert "Number of analyst reports: 1" in context
        assert "fundamental_analyst Report" in context


# ============================================================
# DB Round-Trip Tests
# ============================================================


class TestSynthesisDBRoundTrip:
    """Test saving and loading synthesis reports via the DB."""

    def test_save_and_load_synthesis(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_db(db_path)

            synthesis = SynthesisReport(
                ticker="TSM",
                overall_signal=Signal.BULLISH,
                overall_confidence=0.78,
                analyst_agreement="2/3 bullish",
                bull_case_summary="Strong position",
                bear_case_summary="Geo risk",
                recommendation="HOLD",
                key_watch_items=["Earnings April 17"],
                analyst_reports_used=["fundamental_analyst", "sentiment_analyst"],
            )

            save_report(
                ticker="TSM",
                agent_name="research_synthesizer",
                report_date=synthesis.report_date,
                report=synthesis.model_dump(mode="json"),
                signal=synthesis.overall_signal.value,
                confidence=synthesis.overall_confidence,
                db_path=db_path,
            )

            rows = get_reports("TSM", agent_name="research_synthesizer", db_path=db_path)
            assert len(rows) == 1
            assert rows[0]["signal"] == "bullish"
            assert rows[0]["confidence"] == 0.78

            # Verify the JSON round-trips
            loaded = SynthesisReport(**rows[0]["report"])
            assert loaded.ticker == "TSM"
            assert loaded.overall_signal == Signal.BULLISH
            assert loaded.recommendation == "HOLD"

    def test_load_analyst_reports_from_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_db(db_path)

            # Save analyst reports
            for report in _three_reports():
                save_report(
                    ticker="TSM",
                    agent_name=report.agent,
                    report_date=report.report_date,
                    report=report.model_dump(mode="json"),
                    signal=report.signal.value,
                    confidence=report.confidence,
                    db_path=db_path,
                )

            loaded = _load_analyst_reports_from_db("TSM", db_path=db_path)
            assert len(loaded) == 3
            agents = {r.agent for r in loaded}
            assert agents == {"fundamental_analyst", "sentiment_analyst", "supply_chain_analyst"}

    def test_load_partial_reports(self):
        """When only some analyst reports exist in DB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_db(db_path)

            # Only save fundamental report
            report = _make_report("fundamental_analyst")
            save_report(
                ticker="TSM",
                agent_name=report.agent,
                report_date=report.report_date,
                report=report.model_dump(mode="json"),
                signal=report.signal.value,
                confidence=report.confidence,
                db_path=db_path,
            )

            loaded = _load_analyst_reports_from_db("TSM", db_path=db_path)
            assert len(loaded) == 1
            assert loaded[0].agent == "fundamental_analyst"

    def test_load_no_reports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_db(db_path)

            loaded = _load_analyst_reports_from_db("TSM", db_path=db_path)
            assert len(loaded) == 0

    def test_load_corrupted_report_skipped(self):
        """Corrupted JSON in DB is silently skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            init_db(db_path)

            # Save a valid report
            report = _make_report("fundamental_analyst")
            save_report(
                ticker="TSM",
                agent_name=report.agent,
                report_date=report.report_date,
                report=report.model_dump(mode="json"),
                signal=report.signal.value,
                confidence=report.confidence,
                db_path=db_path,
            )

            # Save a corrupted report (missing required fields)
            save_report(
                ticker="TSM",
                agent_name="sentiment_analyst",
                report_date=date.today(),
                report={"ticker": "TSM", "garbage": True},
                signal="bullish",
                confidence=0.5,
                db_path=db_path,
            )

            loaded = _load_analyst_reports_from_db("TSM", db_path=db_path)
            # Only the valid report should load
            assert len(loaded) == 1
            assert loaded[0].agent == "fundamental_analyst"


# ============================================================
# Synthesis Tool Schema Tests
# ============================================================


class TestSynthesisToolSchema:
    """Verify the tool schema matches what we expect."""

    def test_tool_name(self):
        assert SYNTHESIS_TOOL["name"] == "submit_synthesis_report"

    def test_required_fields(self):
        required = SYNTHESIS_TOOL["input_schema"]["required"]
        expected = [
            "overall_signal", "overall_confidence", "analyst_agreement",
            "disagreement_flags", "bull_case_summary", "bear_case_summary",
            "recommendation", "thesis_changed_since_last", "key_watch_items",
        ]
        assert set(required) == set(expected)


# ============================================================
# Orchestrator Tests
# ============================================================


class TestOrchestratorGraph:
    """Test LangGraph orchestrator wiring and state management."""

    def test_graph_builds(self):
        """Graph compiles without errors."""
        from src.orchestrator.graph import build_graph
        graph = build_graph()
        assert graph is not None

    def test_orchestrator_state_defaults(self):
        from src.orchestrator.graph import OrchestratorState
        state = OrchestratorState(ticker="TSM")
        assert state.ticker == "TSM"
        assert state.save is True
        assert state.db_path is None
        assert state.analyst_reports == []
        assert state.analyst_errors == []
        assert state.synthesis is None

    def test_orchestrator_state_report_accumulation(self):
        """Verify the Annotated[list, operator.add] reducer works."""
        from src.orchestrator.graph import OrchestratorState
        # Simulate what LangGraph does: merge dicts with add reducer
        reports = _three_reports()
        state = OrchestratorState(ticker="TSM", analyst_reports=reports)
        assert len(state.analyst_reports) == 3

    @patch("src.agents.fundamental.analyze_ticker")
    @patch("src.agents.sentiment.analyze_ticker")
    @patch("src.agents.supply_chain.analyze_ticker")
    @patch("src.agents.synthesizer.run_synthesizer")
    def test_orchestrate_full_pipeline(
        self, mock_synth, mock_sc, mock_sent, mock_fund
    ):
        """Full pipeline with mocked API calls."""
        from src.orchestrator.graph import orchestrate

        # Setup mocks
        reports = _three_reports()
        mock_fund.return_value = reports[0]
        mock_sent.return_value = reports[1]
        mock_sc.return_value = reports[2]

        synthesis = SynthesisReport(
            ticker="TSM",
            overall_signal=Signal.BULLISH,
            overall_confidence=0.75,
            analyst_agreement="2/3 bullish, 1/3 neutral",
            bull_case_summary="Strong",
            bear_case_summary="Risks",
            recommendation="HOLD",
            key_watch_items=["Earnings"],
            analyst_reports_used=["fundamental_analyst", "sentiment_analyst", "supply_chain_analyst"],
        )
        mock_synth.return_value = synthesis

        result = orchestrate("TSM", save=False)

        assert len(result.analyst_reports) == 3
        assert result.synthesis is not None
        assert result.synthesis.overall_signal == Signal.BULLISH
        assert len(result.analyst_errors) == 0

    @patch("src.agents.fundamental.analyze_ticker")
    @patch("src.agents.sentiment.analyze_ticker")
    @patch("src.agents.supply_chain.analyze_ticker")
    @patch("src.agents.synthesizer.run_synthesizer")
    def test_orchestrate_partial_failure(
        self, mock_synth, mock_sc, mock_sent, mock_fund
    ):
        """Pipeline continues when one analyst fails."""
        from src.orchestrator.graph import orchestrate

        reports = _three_reports()
        mock_fund.return_value = reports[0]
        mock_sent.side_effect = RuntimeError("API timeout")
        mock_sc.return_value = reports[2]

        synthesis = SynthesisReport(
            ticker="TSM",
            overall_signal=Signal.BULLISH,
            overall_confidence=0.60,
            analyst_agreement="2/2 bullish (sentiment unavailable)",
            bull_case_summary="Strong",
            bear_case_summary="Risks",
            recommendation="HOLD with caution",
            key_watch_items=["Re-run sentiment"],
            analyst_reports_used=["fundamental_analyst", "supply_chain_analyst"],
        )
        mock_synth.return_value = synthesis

        result = orchestrate("TSM", save=False)

        assert len(result.analyst_reports) == 2
        assert len(result.analyst_errors) == 1
        assert "API timeout" in result.analyst_errors[0]
        assert result.synthesis is not None

    @patch("src.agents.fundamental.analyze_ticker")
    @patch("src.agents.sentiment.analyze_ticker")
    @patch("src.agents.supply_chain.analyze_ticker")
    def test_orchestrate_all_analysts_fail(
        self, mock_sc, mock_sent, mock_fund
    ):
        """When all analysts fail, no synthesis is produced."""
        from src.orchestrator.graph import orchestrate

        mock_fund.side_effect = RuntimeError("fail 1")
        mock_sent.side_effect = RuntimeError("fail 2")
        mock_sc.side_effect = RuntimeError("fail 3")

        result = orchestrate("TSM", save=False)

        assert len(result.analyst_reports) == 0
        assert len(result.analyst_errors) >= 3
        assert result.synthesis is None

    @patch("src.agents.fundamental.analyze_ticker")
    @patch("src.agents.sentiment.analyze_ticker")
    @patch("src.agents.supply_chain.analyze_ticker")
    @patch("src.agents.synthesizer.run_synthesizer")
    def test_orchestrate_synthesizer_failure(
        self, mock_synth, mock_sc, mock_sent, mock_fund
    ):
        """When analysts succeed but synthesizer fails, reports are kept."""
        from src.orchestrator.graph import orchestrate

        reports = _three_reports()
        mock_fund.return_value = reports[0]
        mock_sent.return_value = reports[1]
        mock_sc.return_value = reports[2]
        mock_synth.side_effect = RuntimeError("Claude API error")

        result = orchestrate("TSM", save=False)

        assert len(result.analyst_reports) == 3
        assert result.synthesis is None
        assert any("Claude API error" in e for e in result.analyst_errors)


# ============================================================
# E2E Test (requires ANTHROPIC_API_KEY)
# ============================================================


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping E2E test",
)
class TestE2ESynthesis:
    """End-to-end test: run synthesizer with real API call."""

    def test_synthesize_from_reports(self):
        """Synthesize 3 mock reports with real Claude API call."""
        reports = _three_reports()
        synthesis = run_synthesizer("TSM", analyst_reports=reports, save=False)

        assert isinstance(synthesis, SynthesisReport)
        assert synthesis.ticker == "TSM"
        assert synthesis.overall_signal in list(Signal)
        assert 0.0 <= synthesis.overall_confidence <= 1.0
        assert len(synthesis.analyst_agreement) > 0
        assert len(synthesis.bull_case_summary) > 0
        assert len(synthesis.bear_case_summary) > 0
        assert len(synthesis.recommendation) > 0
        assert len(synthesis.key_watch_items) >= 1
