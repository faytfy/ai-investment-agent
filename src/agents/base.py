"""Shared agent logic — context building and API call pattern.

Extracted from analyst.py so that specialized agents (fundamental, sentiment,
supply chain) can reuse the same data gathering and structured output pipeline.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import anthropic

from src.config import ANALYST_MODEL, ANTHROPIC_API_KEY, WATCHLIST, WATCH_ONLY
from src.data.models import (
    AnalysisReport,
    FundamentalsSnapshot,
    NewsArticle,
    PriceBar,
    Signal,
)
from src.db.operations import (
    get_filings,
    get_filing_content,
    get_latest_fundamentals,
    get_news,
    get_prices,
    save_report,
)
from src.utils.logger import get_logger

logger = get_logger("agent_base")

# Tool schema for structured output via Claude tool_use
REPORT_TOOL = {
    "name": "submit_analysis_report",
    "description": "Submit a structured investment analysis report for a stock.",
    "input_schema": {
        "type": "object",
        "properties": {
            "signal": {
                "type": "string",
                "enum": ["bullish", "bearish", "neutral"],
                "description": "Investment signal: bullish, bearish, or neutral",
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Confidence in the signal (0.0 to 1.0)",
            },
            "thesis": {
                "type": "string",
                "description": "One-paragraph investment thesis summary",
            },
            "key_metrics": {
                "type": "object",
                "description": "Key financial metrics with their values (use null for unavailable)",
            },
            "bull_case": {
                "type": "string",
                "description": "Best realistic scenario (1-2 paragraphs)",
            },
            "bear_case": {
                "type": "string",
                "description": "Worst realistic scenario (1-2 paragraphs)",
            },
            "risks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific, actionable risks (at least 2-3)",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific data points supporting the signal (at least 2-3)",
            },
            "thesis_change": {
                "type": "boolean",
                "description": "Whether the fundamental thesis has changed",
            },
            "thesis_change_reason": {
                "type": ["string", "null"],
                "description": "Reason for thesis change (null if no change)",
            },
        },
        "required": [
            "signal",
            "confidence",
            "thesis",
            "key_metrics",
            "bull_case",
            "bear_case",
            "risks",
            "evidence",
            "thesis_change",
            "thesis_change_reason",
        ],
    },
}


# ============================================================
# Stock context helpers
# ============================================================


def get_stock_context(ticker: str) -> dict:
    """Look up the stock's role in the watchlist."""
    info = WATCHLIST.get(ticker) or WATCH_ONLY.get(ticker)
    if info:
        return {"name": info["name"], "layer": info["layer"]}
    return {"name": ticker, "layer": "Unknown"}


# ============================================================
# Data formatting functions
# ============================================================


def format_price_section(bars: list[PriceBar]) -> str:
    """Format recent price data into a readable text section."""
    if not bars:
        return "No price data available."

    lines = ["Date       | Close   | Volume"]
    lines.append("-" * 40)
    for bar in bars[-30:]:  # Last 30 trading days
        lines.append(f"{bar.date} | ${bar.close:>8.2f} | {bar.volume:>12,}")

    # Summary stats
    closes = [b.close for b in bars[-30:]]
    current = closes[-1]
    high = max(closes)
    low = min(closes)
    avg = sum(closes) / len(closes)

    if len(bars) >= 5:
        pct_5d = (closes[-1] / closes[-5] - 1) * 100
    else:
        pct_5d = 0.0

    if len(bars) >= 20:
        pct_20d = (closes[-1] / closes[-20] - 1) * 100
    else:
        pct_20d = 0.0

    lines.append("")
    lines.append(f"Current: ${current:.2f}")
    lines.append(f"30-day range: ${low:.2f} - ${high:.2f}")
    lines.append(f"30-day average: ${avg:.2f}")
    lines.append(f"5-day change: {pct_5d:+.1f}%")
    lines.append(f"20-day change: {pct_20d:+.1f}%")

    return "\n".join(lines)


def format_fundamentals_section(f: Optional[FundamentalsSnapshot]) -> str:
    """Format fundamentals into a readable text section."""
    if f is None:
        return "No fundamentals data available."

    lines = []

    if f.revenue is not None:
        lines.append(f"Revenue: ${f.revenue:,.0f}")
    if f.revenue_growth_yoy is not None:
        lines.append(f"Revenue Growth YoY: {f.revenue_growth_yoy:.1%}")
    if f.net_income is not None:
        lines.append(f"Net Income: ${f.net_income:,.0f}")
    if f.gross_margin is not None:
        lines.append(f"Gross Margin: {f.gross_margin:.1%}")
    if f.operating_margin is not None:
        lines.append(f"Operating Margin: {f.operating_margin:.1%}")
    if f.net_margin is not None:
        lines.append(f"Net Margin: {f.net_margin:.1%}")
    if f.free_cash_flow is not None:
        lines.append(f"Free Cash Flow: ${f.free_cash_flow:,.0f}")
    if f.pe_ratio is not None:
        lines.append(f"P/E Ratio: {f.pe_ratio:.1f}")
    if f.forward_pe is not None:
        lines.append(f"Forward P/E: {f.forward_pe:.1f}")
    if f.ps_ratio is not None:
        lines.append(f"P/S Ratio: {f.ps_ratio:.1f}")
    if f.ev_to_ebitda is not None:
        lines.append(f"EV/EBITDA: {f.ev_to_ebitda:.1f}")
    if f.market_cap is not None:
        lines.append(f"Market Cap: ${f.market_cap:,.0f}")
    if f.beta is not None:
        lines.append(f"Beta: {f.beta:.2f}")
    if f.fifty_two_week_high is not None:
        lines.append(f"52-Week High: ${f.fifty_two_week_high:.2f}")
    if f.fifty_two_week_low is not None:
        lines.append(f"52-Week Low: ${f.fifty_two_week_low:.2f}")
    if f.debt_to_equity is not None:
        lines.append(f"Debt/Equity: {f.debt_to_equity:.2f}")

    # Analyst data
    if f.has_analyst_data:
        lines.append("")
        lines.append("--- Analyst Consensus ---")
        if f.analyst_target_mean is not None:
            lines.append(f"Target Mean: ${f.analyst_target_mean:.2f}")
        if f.analyst_target_median is not None:
            lines.append(f"Target Median: ${f.analyst_target_median:.2f}")
        if f.analyst_target_low is not None and f.analyst_target_high is not None:
            lines.append(f"Target Range: ${f.analyst_target_low:.2f} - ${f.analyst_target_high:.2f}")
        if f.analyst_count is not None:
            lines.append(f"Analyst Count: {f.analyst_count}")
        if f.recommendation is not None:
            lines.append(f"Recommendation: {f.recommendation}")

    return "\n".join(lines) if lines else "No fundamentals data available."


def format_filings_section(ticker: str, db_path: Optional[str] = None) -> str:
    """Format recent SEC filings into a readable text section."""
    kwargs = {"db_path": db_path} if db_path else {}
    filings = get_filings(ticker, limit=5, **kwargs)
    if not filings:
        return "No SEC filings available."

    lines = []
    for f in filings:
        lines.append(f"--- {f.filing_type.value} filed {f.filed_date} ---")
        if f.title:
            lines.append(f"Title: {f.title}")

        content = get_filing_content(f.accession_number, **kwargs)
        if content and content.has_content:
            if content.mda:
                mda_text = content.mda[:2000]
                if len(content.mda) > 2000:
                    mda_text += "... [truncated]"
                lines.append(f"MD&A: {mda_text}")
            if content.risk_factors:
                risk_text = content.risk_factors[:1000]
                if len(content.risk_factors) > 1000:
                    risk_text += "... [truncated]"
                lines.append(f"Risk Factors: {risk_text}")
        lines.append("")

    return "\n".join(lines) if lines else "No SEC filings available."


def format_news_section(ticker: str, db_path: Optional[str] = None) -> str:
    """Format recent news articles into a readable text section."""
    since = datetime.now() - timedelta(days=30)
    kwargs = {"db_path": db_path} if db_path else {}
    articles = get_news(ticker, limit=20, since=since, **kwargs)
    if not articles:
        return "No recent news available."

    lines = []
    for a in articles:
        lines.append(f"[{a.published_at.strftime('%Y-%m-%d')}] {a.title}")
        if a.source:
            lines.append(f"  Source: {a.source}")
        if a.summary:
            lines.append(f"  {a.summary[:200]}")
        lines.append("")

    return "\n".join(lines)


# ============================================================
# Standard context builder
# ============================================================


def build_standard_context_with_data(
    ticker: str, db_path: Optional[str] = None
) -> tuple[str, "PriceHistory", Optional[FundamentalsSnapshot]]:
    """Assemble all available data for a ticker into text context + raw data.

    Returns a tuple of (context_text, price_history, fundamentals) so that
    specialized agents can access the raw data without re-fetching from DB.
    """
    from src.data.models import PriceHistory  # avoid circular at module level

    stock = get_stock_context(ticker)

    kwargs = {"db_path": db_path} if db_path else {}
    price_history = get_prices(ticker, **kwargs)
    fundamentals = get_latest_fundamentals(ticker, **kwargs)

    sections = [
        f"# Analysis Data for {ticker} ({stock['name']})",
        f"Layer: {stock['layer']}",
        f"Date: {date.today().isoformat()}",
        "",
        "## Recent Price Action",
        format_price_section(price_history.bars),
        "",
        "## Fundamentals",
        format_fundamentals_section(fundamentals),
        "",
        "## SEC Filings",
        format_filings_section(ticker, db_path),
        "",
        "## Recent News",
        format_news_section(ticker, db_path),
    ]

    return "\n".join(sections), price_history, fundamentals


def build_standard_context(ticker: str, db_path: Optional[str] = None) -> str:
    """Assemble all available data for a ticker into a single text context.

    This is the default context builder used by the general analyst.
    """
    text, _, _ = build_standard_context_with_data(ticker, db_path)
    return text


# ============================================================
# Generic agent runner
# ============================================================


def run_agent(
    ticker: str,
    agent_name: str,
    prompt_path: Path,
    context_builder: Callable[[str, Optional[str]], str],
    save: bool = True,
    db_path: Optional[str] = None,
) -> AnalysisReport:
    """Run an analyst agent on a single ticker.

    This is the shared execution pipeline:
    1. Build context using the provided context_builder
    2. Load system prompt from prompt_path
    3. Call Claude API with tool_use for structured output
    4. Validate and return AnalysisReport

    Args:
        ticker: Stock ticker symbol
        agent_name: Name of the agent (e.g., "general_analyst", "fundamental_analyst")
        prompt_path: Path to the agent's system prompt markdown file
        context_builder: Function(ticker, db_path) -> context string
        save: Whether to save the report to the database
        db_path: Optional database path (for testing)
    """
    if not ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. Add it to your .env file."
        )

    logger.info(f"[{agent_name}] Analyzing {ticker}...")

    # Build the data context
    context = context_builder(ticker, db_path)

    # Load system prompt
    system_prompt = prompt_path.read_text()

    # Call Claude API with tool_use for structured output
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=ANALYST_MODEL,
        max_tokens=4096,
        system=system_prompt,
        tools=[REPORT_TOOL],
        tool_choice={"type": "tool", "name": "submit_analysis_report"},
        messages=[
            {
                "role": "user",
                "content": f"Analyze this stock and submit your report using the submit_analysis_report tool.\n\n{context}",
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

    # Build the AnalysisReport from Claude's tool output
    report_data = tool_use_block.input
    try:
        report = AnalysisReport(
            ticker=ticker,
            agent=agent_name,
            signal=Signal(report_data["signal"]),
            confidence=report_data["confidence"],
            thesis=report_data["thesis"],
            key_metrics=report_data.get("key_metrics", {}),
            bull_case=report_data["bull_case"],
            bear_case=report_data["bear_case"],
            risks=report_data["risks"],
            evidence=report_data["evidence"],
            thesis_change=report_data.get("thesis_change", False),
            thesis_change_reason=report_data.get("thesis_change_reason"),
        )
    except (KeyError, ValueError) as e:
        logger.error(f"Claude returned invalid report data: {e}")
        logger.error(f"Raw tool output: {report_data}")
        raise RuntimeError(f"Failed to parse {agent_name} report for {ticker}: {e}") from e

    logger.info(
        f"[{agent_name}] Analysis complete for {ticker}: {report.signal.value} "
        f"(confidence: {report.confidence:.2f})"
    )

    # Save to database
    if save:
        save_kwargs = {"db_path": db_path} if db_path else {}
        save_report(
            ticker=ticker,
            agent_name=report.agent,
            report_date=report.report_date,
            report=report.model_dump(mode="json"),
            signal=report.signal.value,
            confidence=report.confidence,
            **save_kwargs,
        )
        logger.info(f"[{agent_name}] Report saved to database for {ticker}")

    return report
