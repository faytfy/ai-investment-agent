"""Research Synthesizer Agent — unified investment memo from analyst reports.

Reads individual analyst reports (fundamental, sentiment, supply chain)
and produces a single SynthesisReport with a unified recommendation.
Uses Claude Opus for harder reasoning (weighing conflicting signals).
"""

import json
from pathlib import Path
from typing import Optional

import anthropic

from src.config import ANTHROPIC_API_KEY, SYNTHESIZER_MODEL
from src.data.models import AnalysisReport, Signal, SynthesisReport
from src.db.operations import get_reports, save_report
from src.utils.logger import get_logger

logger = get_logger("synthesizer")

AGENT_NAME = "research_synthesizer"
PROMPT_PATH = Path(__file__).parent / "prompts" / "synthesizer.md"

# Tool schema for structured synthesis output via Claude tool_use
SYNTHESIS_TOOL = {
    "name": "submit_synthesis_report",
    "description": "Submit a unified investment synthesis memo combining all analyst reports.",
    "input_schema": {
        "type": "object",
        "properties": {
            "overall_signal": {
                "type": "string",
                "enum": ["bullish", "bearish", "neutral"],
                "description": "Unified investment signal",
            },
            "overall_confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Confidence in the unified signal (0.0 to 1.0)",
            },
            "analyst_agreement": {
                "type": "string",
                "description": "Summary of analyst agreement, e.g. '2/3 bullish, 1/3 neutral'",
            },
            "disagreement_flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific points where analysts disagree",
            },
            "bull_case_summary": {
                "type": "string",
                "description": "Unified bull case combining strongest arguments from all analysts",
            },
            "bear_case_summary": {
                "type": "string",
                "description": "Unified bear case combining strongest arguments from all analysts",
            },
            "recommendation": {
                "type": "string",
                "description": "Clear actionable recommendation, e.g. 'HOLD — thesis intact, no action needed'",
            },
            "thesis_changed_since_last": {
                "type": "boolean",
                "description": "Whether any analyst flagged a thesis change",
            },
            "key_watch_items": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Upcoming events or data points that could change the thesis (at least 1)",
            },
        },
        "required": [
            "overall_signal",
            "overall_confidence",
            "analyst_agreement",
            "disagreement_flags",
            "bull_case_summary",
            "bear_case_summary",
            "recommendation",
            "thesis_changed_since_last",
            "key_watch_items",
        ],
    },
}


def build_synthesis_context(
    ticker: str,
    analyst_reports: list[AnalysisReport],
) -> str:
    """Build the context for the synthesizer from analyst reports.

    Args:
        ticker: Stock ticker symbol
        analyst_reports: List of AnalysisReport objects from different analysts

    Returns:
        Formatted text context for the synthesizer prompt
    """
    if not analyst_reports:
        return f"# Synthesis Data for {ticker}\n\nNo analyst reports available."

    sections = [
        f"# Synthesis Data for {ticker}",
        f"Number of analyst reports: {len(analyst_reports)}",
        "",
    ]

    for report in analyst_reports:
        sections.append(f"## {report.agent} Report")
        sections.append(f"Signal: {report.signal.value} (confidence: {report.confidence:.0%})")
        sections.append(f"Thesis: {report.thesis}")
        sections.append("")
        sections.append(f"Bull Case: {report.bull_case}")
        sections.append(f"Bear Case: {report.bear_case}")
        sections.append("")

        if report.key_metrics:
            sections.append("Key Metrics:")
            for k, v in report.key_metrics.items():
                sections.append(f"  {k}: {v}")
            sections.append("")

        sections.append("Risks:")
        for r in report.risks:
            sections.append(f"  - {r}")
        sections.append("")

        sections.append("Evidence:")
        for e in report.evidence:
            sections.append(f"  - {e}")
        sections.append("")

        if report.thesis_change:
            sections.append(f"*** THESIS CHANGE: {report.thesis_change_reason} ***")
            sections.append("")

        sections.append("---")
        sections.append("")

    return "\n".join(sections)


def _load_analyst_reports_from_db(
    ticker: str, db_path: Optional[str] = None
) -> list[AnalysisReport]:
    """Load the most recent report from each analyst agent for a ticker."""
    agent_names = ["fundamental_analyst", "sentiment_analyst", "supply_chain_analyst"]
    reports = []

    kwargs = {"db_path": db_path} if db_path else {}

    for agent_name in agent_names:
        rows = get_reports(ticker, agent_name=agent_name, limit=1, **kwargs)
        if rows:
            try:
                report = AnalysisReport(**rows[0]["report"])
                reports.append(report)
                logger.info(f"Loaded {agent_name} report for {ticker}: {report.signal.value}")
            except Exception as e:
                logger.warning(f"Failed to parse {agent_name} report for {ticker}: {e}")

    return reports


def run_synthesizer(
    ticker: str,
    analyst_reports: list[AnalysisReport],
    save: bool = True,
    db_path: Optional[str] = None,
) -> SynthesisReport:
    """Run the synthesizer on a set of analyst reports.

    Args:
        ticker: Stock ticker symbol
        analyst_reports: List of AnalysisReport objects to synthesize
        save: Whether to save the synthesis report to the database
        db_path: Optional database path (for testing)

    Returns:
        SynthesisReport with unified recommendation
    """
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set. Add it to your .env file.")

    if not analyst_reports:
        raise ValueError(f"No analyst reports to synthesize for {ticker}")

    logger.info(
        f"[{AGENT_NAME}] Synthesizing {len(analyst_reports)} reports for {ticker}..."
    )

    # Build context from analyst reports
    context = build_synthesis_context(ticker, analyst_reports)

    # Load system prompt
    system_prompt = PROMPT_PATH.read_text()

    # Call Claude Opus for synthesis (harder reasoning task)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=SYNTHESIZER_MODEL,
        max_tokens=4096,
        system=system_prompt,
        tools=[SYNTHESIS_TOOL],
        tool_choice={"type": "tool", "name": "submit_synthesis_report"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Synthesize the following analyst reports for {ticker} and submit "
                    f"your unified investment memo using the submit_synthesis_report tool."
                    f"\n\n{context}"
                ),
            }
        ],
    )

    # Extract the tool call result
    tool_use_block = None
    for block in response.content:
        if block.type == "tool_use":
            tool_use_block = block
            break

    if tool_use_block is None:
        raise RuntimeError(
            f"Claude did not return a tool_use block. Response: {response.content}"
        )

    # Build the SynthesisReport from Claude's tool output
    report_data = tool_use_block.input
    try:
        synthesis = SynthesisReport(
            ticker=ticker,
            overall_signal=Signal(report_data["overall_signal"]),
            overall_confidence=report_data["overall_confidence"],
            analyst_agreement=report_data["analyst_agreement"],
            disagreement_flags=report_data.get("disagreement_flags", []),
            bull_case_summary=report_data["bull_case_summary"],
            bear_case_summary=report_data["bear_case_summary"],
            recommendation=report_data["recommendation"],
            thesis_changed_since_last=report_data.get("thesis_changed_since_last", False),
            key_watch_items=report_data["key_watch_items"],
            analyst_reports_used=[r.agent for r in analyst_reports],
        )
    except (KeyError, ValueError) as e:
        logger.error(f"Claude returned invalid synthesis data: {e}")
        logger.error(f"Raw tool output: {report_data}")
        raise RuntimeError(f"Failed to parse synthesis report for {ticker}: {e}") from e

    logger.info(
        f"[{AGENT_NAME}] Synthesis complete for {ticker}: {synthesis.overall_signal.value} "
        f"(confidence: {synthesis.overall_confidence:.2f})"
    )

    # Save to database (reuse analysis_reports table with agent=research_synthesizer)
    if save:
        save_kwargs = {"db_path": db_path} if db_path else {}
        save_report(
            ticker=ticker,
            agent_name=AGENT_NAME,
            report_date=synthesis.report_date,
            report=synthesis.model_dump(mode="json"),
            signal=synthesis.overall_signal.value,
            confidence=synthesis.overall_confidence,
            **save_kwargs,
        )
        logger.info(f"[{AGENT_NAME}] Synthesis report saved to database for {ticker}")

    return synthesis


def analyze_ticker(
    ticker: str, save: bool = True, db_path: Optional[str] = None
) -> SynthesisReport:
    """Run the synthesizer by loading analyst reports from the DB.

    This is the entry point used by the runner when running the synthesizer
    standalone (not via the orchestrator).
    """
    reports = _load_analyst_reports_from_db(ticker, db_path)
    if not reports:
        raise ValueError(
            f"No analyst reports found in DB for {ticker}. "
            f"Run the analyst agents first (fundamental, sentiment, supply_chain)."
        )
    logger.info(f"Loaded {len(reports)} analyst reports from DB for {ticker}")
    return run_synthesizer(ticker, analyst_reports=reports, save=save, db_path=db_path)
