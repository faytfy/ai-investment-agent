"""Fundamental Analyst Agent — deep financial analysis.

Focuses on valuation, margins, cash flow, and growth sustainability.
Produces structured AnalysisReport with agent="fundamental_analyst".
"""

from pathlib import Path
from typing import Optional

from src.agents.base import (
    build_standard_context_with_data,
    run_agent,
)
from src.data.models import AnalysisReport, FundamentalsSnapshot
from src.utils.logger import get_logger

logger = get_logger("fundamental_analyst")

AGENT_NAME = "fundamental_analyst"
PROMPT_PATH = Path(__file__).parent / "prompts" / "fundamental.md"


def _compute_derived_metrics(f: FundamentalsSnapshot, current_price: Optional[float] = None) -> str:
    """Compute derived financial ratios not directly available from yfinance.

    These give the LLM richer data to work with for valuation analysis.
    """
    lines = []

    # FCF Yield = FCF / Market Cap
    if f.free_cash_flow is not None and f.market_cap is not None and f.market_cap > 0:
        fcf_yield = f.free_cash_flow / f.market_cap
        lines.append(f"FCF Yield: {fcf_yield:.2%}")

    # Earnings Yield = 1 / P/E (inverse of P/E, comparable to bond yields)
    if f.pe_ratio is not None and f.pe_ratio > 0:
        earnings_yield = 1.0 / f.pe_ratio
        lines.append(f"Earnings Yield: {earnings_yield:.2%}")

    # Forward Earnings Yield
    if f.forward_pe is not None and f.forward_pe > 0:
        fwd_earnings_yield = 1.0 / f.forward_pe
        lines.append(f"Forward Earnings Yield: {fwd_earnings_yield:.2%}")

    # P/E to Forward P/E spread (earnings growth implied by market)
    if f.pe_ratio is not None and f.forward_pe is not None and f.forward_pe > 0:
        pe_compression = (f.pe_ratio / f.forward_pe - 1) * 100
        lines.append(f"Implied Earnings Growth (trailing→forward): {pe_compression:+.1f}%")

    # Net Debt = Total Debt - Total Cash
    if f.total_debt is not None and f.total_cash is not None:
        net_debt = f.total_debt - f.total_cash
        lines.append(f"Net Debt: ${net_debt:,.0f}")
        if f.free_cash_flow is not None and f.free_cash_flow > 0:
            debt_to_fcf = net_debt / f.free_cash_flow
            lines.append(f"Net Debt / FCF: {debt_to_fcf:.1f}x")

    # Capex Intensity = Capex / Revenue
    if f.capital_expenditure is not None and f.revenue is not None and f.revenue > 0:
        capex_intensity = abs(f.capital_expenditure) / f.revenue
        lines.append(f"Capex Intensity (Capex/Revenue): {capex_intensity:.1%}")

    # FCF Conversion = FCF / Net Income
    if f.free_cash_flow is not None and f.net_income is not None and f.net_income > 0:
        fcf_conversion = f.free_cash_flow / f.net_income
        lines.append(f"FCF Conversion (FCF/Net Income): {fcf_conversion:.1%}")

    # Price vs 52-week range positioning
    if (
        current_price is not None
        and f.fifty_two_week_high is not None
        and f.fifty_two_week_low is not None
        and f.fifty_two_week_high > f.fifty_two_week_low
    ):
        range_position = (current_price - f.fifty_two_week_low) / (
            f.fifty_two_week_high - f.fifty_two_week_low
        )
        lines.append(f"52-Week Range Position: {range_position:.0%} (0%=low, 100%=high)")

    # Analyst upside/downside
    if f.analyst_target_mean is not None and current_price is not None and current_price > 0:
        upside = (f.analyst_target_mean / current_price - 1) * 100
        lines.append(f"Analyst Target Upside/Downside: {upside:+.1f}%")

    # PEG assessment
    if f.peg_ratio is not None:
        lines.append(f"PEG Ratio: {f.peg_ratio:.2f}")
        if f.peg_ratio < 1.0:
            lines.append("  -> PEG < 1.0: growth may be underpriced")
        elif f.peg_ratio > 2.0:
            lines.append("  -> PEG > 2.0: growth may be overpriced")

    # Enterprise Value / FCF
    if f.enterprise_value is not None and f.free_cash_flow is not None and f.free_cash_flow > 0:
        ev_to_fcf = f.enterprise_value / f.free_cash_flow
        lines.append(f"EV/FCF: {ev_to_fcf:.1f}")

    return "\n".join(lines) if lines else "Insufficient data to compute derived metrics."


def build_fundamental_context(ticker: str, db_path: Optional[str] = None) -> str:
    """Build an enriched context for fundamental analysis.

    Starts with the standard context and adds a derived metrics section
    computed from the raw fundamentals data. Uses build_standard_context_with_data
    to avoid double-fetching from DB.
    """
    base_context, price_history, fundamentals = build_standard_context_with_data(ticker, db_path)

    # Get current price for derived metrics
    current_price = None
    if price_history and price_history.bars:
        current_price = price_history.bars[-1].close

    # Compute derived metrics
    derived_section = ""
    if fundamentals is not None:
        derived = _compute_derived_metrics(fundamentals, current_price)
        derived_section = f"\n\n## Derived Financial Metrics\n{derived}"

    return base_context + derived_section


def analyze_ticker(ticker: str, save: bool = True, db_path: Optional[str] = None) -> AnalysisReport:
    """Run the fundamental analyst agent on a single ticker.

    Args:
        ticker: Stock ticker symbol
        save: Whether to save the report to the database
        db_path: Optional database path (for testing)

    Returns:
        AnalysisReport with agent="fundamental_analyst"
    """
    return run_agent(
        ticker=ticker,
        agent_name=AGENT_NAME,
        prompt_path=PROMPT_PATH,
        context_builder=build_fundamental_context,
        save=save,
        db_path=db_path,
    )
