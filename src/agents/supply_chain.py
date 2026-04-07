"""Supply Chain Analyst Agent — bottleneck positioning and demand visibility.

Focuses on competitive positioning, moat durability, capex cycles, and
supply chain risk factors. Produces structured AnalysisReport with
agent="supply_chain_analyst".
"""

from pathlib import Path
from typing import Optional

from src.agents.base import (
    build_standard_context_with_data,
    get_stock_context,
    run_agent,
)
from src.config import WATCHLIST, WATCH_ONLY
from src.data.models import AnalysisReport, FundamentalsSnapshot
from src.utils.logger import get_logger

logger = get_logger("supply_chain_analyst")

AGENT_NAME = "supply_chain_analyst"
PROMPT_PATH = Path(__file__).parent / "prompts" / "supply_chain.md"


def _build_layer_context(ticker: str) -> str:
    """Build supply chain layer context from the watchlist configuration.

    Provides the LLM with information about where this stock sits in the
    AI supply chain and who its layer peers are.
    """
    stock = get_stock_context(ticker)
    layer = stock["layer"]

    lines = [f"Company: {stock['name']} ({ticker})", f"Supply Chain Layer: {layer}"]

    # Find tier
    if ticker in WATCHLIST:
        tier = WATCHLIST[ticker]["tier"]
        tier_label = "Tier 1 — Structural Bottleneck Owner" if tier == 1 else "Tier 2 — Strong Moat + Demand Visibility"
        lines.append(f"Portfolio Tier: {tier_label}")
    elif ticker in WATCH_ONLY:
        lines.append(f"Portfolio Tier: Watch Only — {WATCH_ONLY[ticker].get('note', 'monitoring')}")

    # Find layer peers (other stocks in the same or adjacent layers)
    all_stocks = {**WATCHLIST, **WATCH_ONLY}
    peers = []
    for t, info in all_stocks.items():
        if t != ticker and info["layer"] == layer:
            peers.append(f"{t} ({info['name']})")

    if peers:
        lines.append(f"Same-layer peers: {', '.join(peers)}")
    else:
        lines.append("Same-layer peers: None in portfolio (unique position)")

    return "\n".join(lines)


def _compute_supply_chain_metrics(f: FundamentalsSnapshot) -> str:
    """Compute supply-chain-relevant derived metrics from fundamentals.

    Focuses on capex, capacity investment, and pricing power indicators.
    """
    lines = []

    # Capex intensity = |Capex| / Revenue
    if f.capital_expenditure is not None and f.revenue is not None and f.revenue > 0:
        capex_intensity = abs(f.capital_expenditure) / f.revenue
        lines.append(f"Capex Intensity (Capex/Revenue): {capex_intensity:.1%}")
        if capex_intensity > 0.20:
            lines.append("  -> High capex intensity: heavy capacity investment")
        elif capex_intensity < 0.05:
            lines.append("  -> Low capex intensity: asset-light or underinvesting")

    # Gross margin as pricing power proxy
    if f.gross_margin is not None:
        lines.append(f"Gross Margin: {f.gross_margin:.1%}")
        if f.gross_margin > 0.50:
            lines.append("  -> Strong pricing power (>50% gross margin)")
        elif f.gross_margin < 0.25:
            lines.append("  -> Weak pricing power (<25% gross margin)")

    # Revenue growth as demand indicator
    if f.revenue_growth_yoy is not None:
        lines.append(f"Revenue Growth YoY: {f.revenue_growth_yoy:.1%}")
        if f.revenue_growth_yoy > 0.20:
            lines.append("  -> Strong demand signal (>20% growth)")
        elif f.revenue_growth_yoy < 0:
            lines.append("  -> Demand contraction (negative growth)")

    # Operating margin as operational leverage indicator
    if f.operating_margin is not None:
        lines.append(f"Operating Margin: {f.operating_margin:.1%}")

    # FCF generation capacity
    if f.free_cash_flow is not None and f.revenue is not None and f.revenue > 0:
        fcf_margin = f.free_cash_flow / f.revenue
        lines.append(f"FCF Margin (FCF/Revenue): {fcf_margin:.1%}")

    # Debt capacity for expansion
    if f.debt_to_equity is not None:
        lines.append(f"Debt/Equity: {f.debt_to_equity:.2f}")
        if f.debt_to_equity < 0.5:
            lines.append("  -> Low leverage: capacity for debt-funded expansion")
        elif f.debt_to_equity > 2.0:
            lines.append("  -> High leverage: limited expansion flexibility")

    return "\n".join(lines) if lines else "Insufficient data for supply chain metrics."


def build_supply_chain_context(ticker: str, db_path: Optional[str] = None) -> str:
    """Build an enriched context for supply chain analysis.

    Starts with the standard context and adds supply chain layer positioning,
    peer context, and capex/pricing power metrics.
    """
    base_context, price_history, fundamentals = build_standard_context_with_data(
        ticker, db_path
    )

    # Supply chain layer and peer context
    layer_context = _build_layer_context(ticker)
    layer_section = f"\n\n## Supply Chain Position\n{layer_context}"

    # Supply chain derived metrics
    metrics_section = ""
    if fundamentals is not None:
        metrics = _compute_supply_chain_metrics(fundamentals)
        metrics_section = f"\n\n## Supply Chain Metrics\n{metrics}"

    return base_context + layer_section + metrics_section


def analyze_ticker(
    ticker: str, save: bool = True, db_path: Optional[str] = None
) -> AnalysisReport:
    """Run the supply chain analyst agent on a single ticker.

    Args:
        ticker: Stock ticker symbol
        save: Whether to save the report to the database
        db_path: Optional database path (for testing)

    Returns:
        AnalysisReport with agent="supply_chain_analyst"
    """
    return run_agent(
        ticker=ticker,
        agent_name=AGENT_NAME,
        prompt_path=PROMPT_PATH,
        context_builder=build_supply_chain_context,
        save=save,
        db_path=db_path,
    )
