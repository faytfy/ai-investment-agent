"""Risk Manager Agent — portfolio-level risk analysis.

Reads the latest synthesis reports for all watchlist tickers and produces
a single PortfolioRiskReport with sector exposure, concentration warnings,
correlation flags, and position sizing recommendations.
Uses Claude Sonnet (rule-based + analytical, per DESIGN.md Section 4.4).
"""

import json
from collections import Counter
from pathlib import Path
from typing import Optional

import anthropic

from src.config import ANALYST_MODEL, ANTHROPIC_API_KEY, WATCHLIST
from src.data.models import (
    PortfolioRiskReport,
    RiskLevel,
    Signal,
    SynthesisReport,
)
from src.db.operations import get_connection, get_reports, save_report
from src.utils.logger import get_logger

logger = get_logger("risk_manager")

AGENT_NAME = "risk_manager"
PROMPT_PATH = Path(__file__).parent / "prompts" / "risk_manager.md"

# Layer groupings for sector exposure calculation
LAYER_GROUPS = {
    "Foundry/Packaging": "Semiconductor",
    "Equipment (EUV)": "Semiconductor",
    "Custom ASIC + Networking": "Semiconductor",
    "Memory (HBM)": "Memory",
    "Networking": "Networking",
    "Power/Grid": "Power/Energy",
    "Power/Transformers": "Power/Energy",
    "Nuclear Power": "Power/Energy",
    "Cooling": "Infrastructure",
    "GPU": "Semiconductor",
    "AI Software": "Software",
}

# Tool schema for structured risk report output via Claude tool_use
RISK_TOOL = {
    "name": "submit_risk_report",
    "description": "Submit a portfolio-level risk assessment report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "overall_risk_level": {
                "type": "string",
                "enum": ["low", "moderate", "elevated", "high"],
                "description": "Overall portfolio risk level",
            },
            "risk_summary": {
                "type": "string",
                "description": "2-4 sentence summary of the portfolio's risk posture",
            },
            "sector_exposure": {
                "type": "object",
                "additionalProperties": {"type": "number"},
                "description": "Sector/layer → weight (0.0 to 1.0), must sum to ~1.0",
            },
            "concentration_warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific concentration risk warnings",
            },
            "correlation_flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Pairs or clusters of correlated positions",
            },
            "position_sizing": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "max_allocation": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 0.15,
                        },
                        "reason": {"type": "string"},
                    },
                    "required": ["max_allocation", "reason"],
                },
                "description": "Ticker → {max_allocation, reason} for position sizing",
            },
            "recommendations": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "2-5 actionable risk management recommendations",
            },
        },
        "required": [
            "overall_risk_level",
            "risk_summary",
            "sector_exposure",
            "concentration_warnings",
            "correlation_flags",
            "position_sizing",
            "recommendations",
        ],
    },
}


def _ensure_portfolio_stock(db_path: Optional[str] = None) -> None:
    """Ensure a synthetic PORTFOLIO entry exists in the stocks table.

    The analysis_reports table has a FK to stocks(ticker). Since the risk
    manager saves with ticker='PORTFOLIO', we need this row to exist.
    """
    kwargs = {"db_path": db_path} if db_path else {}
    conn = get_connection(**kwargs)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO stocks (ticker, name, layer, tier, watch_only) "
            "VALUES ('PORTFOLIO', 'Portfolio Risk', 'Portfolio', 0, 1)",
        )
        conn.commit()
    finally:
        conn.close()


def _load_all_synthesis_reports(
    db_path: Optional[str] = None,
) -> list[SynthesisReport]:
    """Load the latest synthesis report for each watchlist ticker."""
    reports = []
    kwargs = {"db_path": db_path} if db_path else {}

    for ticker in WATCHLIST:
        rows = get_reports(ticker, agent_name="research_synthesizer", limit=1, **kwargs)
        if rows:
            try:
                report = SynthesisReport(**rows[0]["report"])
                reports.append(report)
                logger.info(
                    f"Loaded synthesis for {ticker}: "
                    f"{report.overall_signal.value} ({report.overall_confidence:.0%})"
                )
            except Exception as e:
                logger.warning(f"Failed to parse synthesis report for {ticker}: {e}")

    return reports


def compute_portfolio_metrics(
    reports: list[SynthesisReport],
    watchlist: Optional[dict] = None,
) -> dict:
    """Compute portfolio-level metrics from synthesis reports.

    Returns a dict with:
        - sector_exposure: {sector: weight}
        - signal_distribution: {signal: count}
        - layer_map: {ticker: layer}
        - same_layer_pairs: [(ticker1, ticker2, layer)]
        - equal_weight: per-stock weight assuming equal allocation
        - coverage: fraction of watchlist with reports
    """
    if watchlist is None:
        watchlist = WATCHLIST

    tickers_with_reports = {r.ticker for r in reports}
    active_tickers = list(watchlist.keys())
    n_active = len(active_tickers)

    # Equal weight per position
    equal_weight = 1.0 / n_active if n_active > 0 else 0.0

    # Map each ticker to its sector group
    layer_map = {}
    sector_counts: Counter = Counter()
    for ticker in active_tickers:
        info = watchlist.get(ticker, {})
        layer = info.get("layer", "Unknown")
        sector = LAYER_GROUPS.get(layer, "Other")
        layer_map[ticker] = {"layer": layer, "sector": sector}
        sector_counts[sector] += 1

    # Sector exposure as fraction of total positions
    sector_exposure = {
        sector: count * equal_weight
        for sector, count in sector_counts.items()
    }

    # Signal distribution from reports
    signal_distribution: Counter = Counter()
    for r in reports:
        signal_distribution[r.overall_signal.value] += 1

    # Same-layer pairs (correlation proxy)
    same_layer_pairs = []
    for i, t1 in enumerate(active_tickers):
        for t2 in active_tickers[i + 1 :]:
            s1 = layer_map[t1]["sector"]
            s2 = layer_map[t2]["sector"]
            if s1 == s2:
                same_layer_pairs.append((t1, t2, s1))

    coverage = len(tickers_with_reports) / n_active if n_active > 0 else 0.0

    return {
        "sector_exposure": sector_exposure,
        "signal_distribution": dict(signal_distribution),
        "layer_map": layer_map,
        "same_layer_pairs": same_layer_pairs,
        "equal_weight": equal_weight,
        "coverage": coverage,
        "n_active": n_active,
        "tickers_with_reports": sorted(tickers_with_reports),
        "tickers_missing": sorted(set(active_tickers) - tickers_with_reports),
    }


def build_risk_context(
    reports: list[SynthesisReport],
    metrics: dict,
) -> str:
    """Build the context for the risk manager from synthesis reports + metrics."""
    sections = [
        "# Portfolio Risk Assessment Data",
        "",
        f"Active positions: {metrics['n_active']}",
        f"Reports available: {len(reports)} of {metrics['n_active']} "
        f"({metrics['coverage']:.0%} coverage)",
    ]

    if metrics["tickers_missing"]:
        sections.append(
            f"Missing reports: {', '.join(metrics['tickers_missing'])}"
        )

    # Sector exposure
    sections.append("")
    sections.append("## Computed Sector Exposure (equal-weight)")
    for sector, weight in sorted(
        metrics["sector_exposure"].items(), key=lambda x: -x[1]
    ):
        flag = " ⚠️ >30%" if weight > 0.30 else ""
        sections.append(f"  {sector}: {weight:.1%}{flag}")

    # Signal distribution
    sections.append("")
    sections.append("## Signal Distribution")
    for signal, count in sorted(metrics["signal_distribution"].items()):
        sections.append(f"  {signal}: {count}")

    # Same-layer pairs
    if metrics["same_layer_pairs"]:
        sections.append("")
        sections.append("## Same-Sector Pairs (correlation proxy)")
        for t1, t2, sector in metrics["same_layer_pairs"]:
            sections.append(f"  {t1} + {t2} ({sector})")

    # Per-stock layer map
    sections.append("")
    sections.append("## Stock → Layer Mapping")
    for ticker, info in sorted(metrics["layer_map"].items()):
        sections.append(f"  {ticker}: {info['layer']} → {info['sector']}")

    # Individual synthesis summaries
    sections.append("")
    sections.append("## Synthesis Reports")
    sections.append("")

    for report in reports:
        sections.append(f"### {report.ticker}")
        sections.append(
            f"Signal: {report.overall_signal.value} "
            f"(confidence: {report.overall_confidence:.0%})"
        )
        sections.append(f"Agreement: {report.analyst_agreement}")
        sections.append(f"Recommendation: {report.recommendation}")
        sections.append(f"Bull: {report.bull_case_summary}")
        sections.append(f"Bear: {report.bear_case_summary}")

        if report.disagreement_flags:
            sections.append("Disagreements:")
            for d in report.disagreement_flags:
                sections.append(f"  - {d}")

        if report.thesis_changed_since_last:
            sections.append("*** THESIS CHANGE DETECTED ***")

        if report.key_watch_items:
            sections.append("Watch items:")
            for item in report.key_watch_items:
                sections.append(f"  - {item}")

        sections.append("")
        sections.append("---")
        sections.append("")

    return "\n".join(sections)


def run_risk_manager(
    reports: list[SynthesisReport],
    save: bool = True,
    db_path: Optional[str] = None,
) -> PortfolioRiskReport:
    """Run the risk manager on synthesis reports.

    Args:
        reports: List of SynthesisReport objects (one per ticker)
        save: Whether to save the risk report to the database
        db_path: Optional database path (for testing)

    Returns:
        PortfolioRiskReport with portfolio-level risk assessment
    """
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set. Add it to your .env file.")

    if not reports:
        raise ValueError("No synthesis reports to assess — run orchestration first")

    logger.info(
        f"[{AGENT_NAME}] Assessing portfolio risk across {len(reports)} tickers..."
    )

    # Compute portfolio metrics
    metrics = compute_portfolio_metrics(reports)

    # Build context
    context = build_risk_context(reports, metrics)

    # Load system prompt
    system_prompt = PROMPT_PATH.read_text()

    # Call Claude Sonnet (rule-based + analytical per DESIGN.md 4.4)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=ANALYST_MODEL,
        max_tokens=4096,
        system=system_prompt,
        tools=[RISK_TOOL],
        tool_choice={"type": "tool", "name": "submit_risk_report"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Assess the portfolio-level risk for the following {len(reports)} "
                    f"stocks and submit your risk report using the submit_risk_report tool."
                    f"\n\n{context}"
                ),
            }
        ],
    )

    # Extract tool call result
    tool_use_block = None
    for block in response.content:
        if block.type == "tool_use":
            tool_use_block = block
            break

    if tool_use_block is None:
        raise RuntimeError(
            f"Claude did not return a tool_use block. Response: {response.content}"
        )

    # Build the PortfolioRiskReport from Claude's tool output
    report_data = tool_use_block.input
    try:
        risk_report = PortfolioRiskReport(
            overall_risk_level=RiskLevel(report_data["overall_risk_level"]),
            risk_summary=report_data["risk_summary"],
            sector_exposure=report_data.get("sector_exposure", {}),
            concentration_warnings=report_data.get("concentration_warnings", []),
            correlation_flags=report_data.get("correlation_flags", []),
            position_sizing=report_data.get("position_sizing", {}),
            recommendations=report_data["recommendations"],
            portfolio_signals=[
                {
                    "ticker": r.ticker,
                    "signal": r.overall_signal.value,
                    "confidence": r.overall_confidence,
                    "recommendation": r.recommendation,
                }
                for r in reports
            ],
            tickers_analyzed=[r.ticker for r in reports],
        )
    except (KeyError, ValueError) as e:
        logger.error(f"Claude returned invalid risk data: {e}")
        logger.error(f"Raw tool output: {report_data}")
        raise RuntimeError(f"Failed to parse risk report: {e}") from e

    logger.info(
        f"[{AGENT_NAME}] Risk assessment complete: "
        f"{risk_report.overall_risk_level.value} risk"
    )

    # Save to database (reuse analysis_reports table with agent=risk_manager)
    # Use "neutral" as signal since the DB CHECK constraint only allows
    # bullish/bearish/neutral. The actual risk level is in the JSON report.
    if save:
        save_kwargs = {"db_path": db_path} if db_path else {}
        _ensure_portfolio_stock(db_path)
        save_report(
            ticker="PORTFOLIO",
            agent_name=AGENT_NAME,
            report_date=risk_report.report_date,
            report=risk_report.model_dump(mode="json"),
            signal="neutral",
            confidence=0.0,
            **save_kwargs,
        )
        logger.info(f"[{AGENT_NAME}] Risk report saved to database")

    return risk_report


def analyze_portfolio(
    save: bool = True, db_path: Optional[str] = None
) -> PortfolioRiskReport:
    """Run the risk manager by loading synthesis reports from the DB.

    This is the main entry point for the risk manager.
    """
    reports = _load_all_synthesis_reports(db_path)
    if not reports:
        raise ValueError(
            "No synthesis reports found in DB. "
            "Run orchestration first (python -m src.agents.runner --all --orchestrate)."
        )
    logger.info(f"Loaded {len(reports)} synthesis reports for risk assessment")
    return run_risk_manager(reports, save=save, db_path=db_path)
