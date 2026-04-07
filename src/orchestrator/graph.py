"""LangGraph orchestration — runs analyst agents in parallel, then synthesizes.

Graph structure:
    START → [fundamental, sentiment, supply_chain] (parallel) → synthesize → END

Each analyst node produces an AnalysisReport. The synthesizer node reads all
reports and produces a SynthesisReport.
"""

import operator
from typing import Annotated, Optional

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.data.models import AnalysisReport, SynthesisReport
from src.utils.logger import get_logger

logger = get_logger("orchestrator")


# ============================================================
# Graph State
# ============================================================


class OrchestratorState(BaseModel):
    """State passed through the LangGraph orchestration graph."""

    ticker: str
    save: bool = True
    db_path: Optional[str] = None

    # Analyst reports accumulate via the reducer (operator.add)
    analyst_reports: Annotated[list[AnalysisReport], operator.add] = Field(
        default_factory=list
    )
    analyst_errors: Annotated[list[str], operator.add] = Field(default_factory=list)

    # Final synthesis
    synthesis: Optional[SynthesisReport] = None


# ============================================================
# Node functions
# ============================================================


def _run_analyst_node(
    state: OrchestratorState, agent_module: str, agent_fn: str = "analyze_ticker"
) -> dict:
    """Run a single analyst agent and return the report as a state update."""
    import importlib

    module = importlib.import_module(agent_module)
    analyze_fn = getattr(module, agent_fn)

    try:
        report = analyze_fn(
            ticker=state.ticker, save=state.save, db_path=state.db_path
        )
        logger.info(f"[{agent_module}] Completed: {report.signal.value} ({report.confidence:.0%})")
        return {"analyst_reports": [report]}
    except Exception as e:
        error_msg = f"{agent_module} failed for {state.ticker}: {e}"
        logger.error(error_msg)
        return {"analyst_errors": [error_msg]}


def run_fundamental(state: OrchestratorState) -> dict:
    """Run the fundamental analyst."""
    return _run_analyst_node(state, "src.agents.fundamental")


def run_sentiment(state: OrchestratorState) -> dict:
    """Run the sentiment analyst."""
    return _run_analyst_node(state, "src.agents.sentiment")


def run_supply_chain(state: OrchestratorState) -> dict:
    """Run the supply chain analyst."""
    return _run_analyst_node(state, "src.agents.supply_chain")


def run_synthesizer(state: OrchestratorState) -> dict:
    """Run the research synthesizer on collected analyst reports."""
    from src.agents.synthesizer import run_synthesizer as _run_synthesizer

    if not state.analyst_reports:
        error_msg = f"No analyst reports available for {state.ticker} — all analysts failed"
        logger.error(error_msg)
        return {"analyst_errors": [error_msg]}

    if state.analyst_errors:
        logger.warning(
            f"Proceeding with {len(state.analyst_reports)} of 3 reports. "
            f"Errors: {state.analyst_errors}"
        )

    try:
        synthesis = _run_synthesizer(
            ticker=state.ticker,
            analyst_reports=state.analyst_reports,
            save=state.save,
            db_path=state.db_path,
        )
        return {"synthesis": synthesis}
    except Exception as e:
        error_msg = f"Synthesizer failed for {state.ticker}: {e}"
        logger.error(error_msg)
        return {"analyst_errors": [error_msg]}


# ============================================================
# Graph construction
# ============================================================


def build_graph() -> StateGraph:
    """Build the orchestration graph.

    Returns a compiled LangGraph StateGraph ready for invocation.
    """
    graph = StateGraph(OrchestratorState)

    # Add nodes
    graph.add_node("fundamental", run_fundamental)
    graph.add_node("sentiment", run_sentiment)
    graph.add_node("supply_chain", run_supply_chain)
    graph.add_node("synthesize", run_synthesizer)

    # Fan-out: START → all 3 analysts in parallel
    graph.add_edge(START, "fundamental")
    graph.add_edge(START, "sentiment")
    graph.add_edge(START, "supply_chain")

    # Fan-in: all 3 analysts → synthesize
    graph.add_edge("fundamental", "synthesize")
    graph.add_edge("sentiment", "synthesize")
    graph.add_edge("supply_chain", "synthesize")

    # Synthesize → END
    graph.add_edge("synthesize", END)

    return graph.compile()


def orchestrate(
    ticker: str, save: bool = True, db_path: Optional[str] = None
) -> OrchestratorState:
    """Run the full analysis pipeline for a single ticker.

    Runs all 3 analysts in parallel, then synthesizes their reports.

    Args:
        ticker: Stock ticker symbol
        save: Whether to save reports to the database
        db_path: Optional database path (for testing)

    Returns:
        OrchestratorState with analyst_reports and synthesis
    """
    ticker = ticker.upper()
    logger.info(f"Starting orchestrated analysis for {ticker}")

    graph = build_graph()

    initial_state = OrchestratorState(
        ticker=ticker,
        save=save,
        db_path=db_path,
    )

    result = graph.invoke(initial_state)

    # LangGraph returns a dict; convert back to OrchestratorState
    if isinstance(result, dict):
        known_fields = set(OrchestratorState.model_fields.keys())
        filtered = {k: v for k, v in result.items() if k in known_fields}
        final_state = OrchestratorState(**filtered)
    else:
        final_state = result

    logger.info(
        f"Orchestration complete for {ticker}: "
        f"{len(final_state.analyst_reports)} reports, "
        f"{len(final_state.analyst_errors)} errors"
    )

    if final_state.synthesis:
        logger.info(
            f"Synthesis: {final_state.synthesis.overall_signal.value} "
            f"({final_state.synthesis.overall_confidence:.0%})"
        )

    return final_state
