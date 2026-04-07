"""General Analyst Agent — Single Agent MVP.

Reads price, fundamentals, filings, and news from the DB,
calls Claude API, and produces a structured AnalysisReport.

Now delegates to the shared base module for context building and API calls.
"""

from pathlib import Path
from typing import Optional

from src.agents.base import (  # noqa: F401 — re-exports for backward compat
    build_standard_context,
    format_fundamentals_section,
    format_filings_section,
    format_news_section,
    format_price_section,
    get_stock_context,
    run_agent,
    REPORT_TOOL,
)
from src.data.models import AnalysisReport
from src.utils.logger import get_logger

logger = get_logger("analyst")

AGENT_NAME = "general_analyst"
PROMPT_PATH = Path(__file__).parent / "prompts" / "analyst.md"

# Re-export for backward compatibility with tests
_get_system_prompt = lambda: PROMPT_PATH.read_text()
_get_stock_context = get_stock_context
_format_price_section = format_price_section
_format_fundamentals_section = format_fundamentals_section
_format_filings_section = format_filings_section
_format_news_section = format_news_section
build_context = build_standard_context


def analyze_ticker(ticker: str, save: bool = True, db_path: Optional[str] = None) -> AnalysisReport:
    """Run the general analyst agent on a single ticker.

    Args:
        ticker: Stock ticker symbol
        save: Whether to save the report to the database
        db_path: Optional database path (for testing)

    Returns:
        AnalysisReport with the agent's analysis
    """
    return run_agent(
        ticker=ticker,
        agent_name=AGENT_NAME,
        prompt_path=PROMPT_PATH,
        context_builder=build_standard_context,
        save=save,
        db_path=db_path,
    )
