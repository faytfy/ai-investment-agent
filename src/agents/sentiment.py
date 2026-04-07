"""Sentiment Analyst Agent — news flow, filing tone, and narrative analysis.

Focuses on news sentiment, filing language shifts, and market narrative
to detect sentiment inflection points. Produces structured AnalysisReport
with agent="sentiment_analyst".
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.agents.base import (
    build_standard_context_with_data,
    format_news_section,
    run_agent,
)
from src.data.models import AnalysisReport, NewsArticle
from src.db.operations import get_news
from src.utils.logger import get_logger

logger = get_logger("sentiment_analyst")

AGENT_NAME = "sentiment_analyst"
PROMPT_PATH = Path(__file__).parent / "prompts" / "sentiment.md"


def _compute_news_metrics(
    ticker: str, db_path: Optional[str] = None
) -> str:
    """Compute sentiment-relevant metrics from available news data.

    Analyzes news volume, recency distribution, and source diversity
    to give the LLM richer sentiment context.
    """
    kwargs = {"db_path": db_path} if db_path else {}
    now = datetime.now()

    # Get articles from broader window for volume comparison
    articles_30d = get_news(ticker, limit=50, since=now - timedelta(days=30), **kwargs)
    articles_7d = [a for a in articles_30d if a.published_at >= now - timedelta(days=7)]
    articles_3d = [a for a in articles_30d if a.published_at >= now - timedelta(days=3)]

    lines = []

    # Volume metrics
    lines.append(f"Total articles (30 days): {len(articles_30d)}")
    lines.append(f"Articles (last 7 days): {len(articles_7d)}")
    lines.append(f"Articles (last 3 days): {len(articles_3d)}")

    # Volume interpretation
    if len(articles_30d) == 0:
        lines.append("News volume: NONE — no recent coverage detected")
    elif len(articles_7d) > len(articles_30d) * 0.5:
        lines.append("News volume: SURGING — majority of 30-day articles in last 7 days")
    elif len(articles_7d) > 0:
        lines.append("News volume: MODERATE — some recent activity")
    else:
        lines.append("News volume: QUIET — no articles in last 7 days")

    # Recency
    if articles_30d:
        most_recent = max(a.published_at for a in articles_30d)
        days_since = (now - most_recent).days
        lines.append(f"Most recent article: {days_since} day(s) ago")

    # Source diversity
    sources = {a.source for a in articles_30d if a.source}
    if sources:
        lines.append(f"Unique sources: {len(sources)} ({', '.join(sorted(sources)[:5])})")

    return "\n".join(lines)


def build_sentiment_context(ticker: str, db_path: Optional[str] = None) -> str:
    """Build an enriched context for sentiment analysis.

    Starts with the standard context and adds a news metrics section
    with volume, recency, and source diversity analysis.
    """
    base_context, price_history, fundamentals = build_standard_context_with_data(
        ticker, db_path
    )

    # Add price momentum summary for sentiment cross-reference
    momentum_section = ""
    if price_history and price_history.bars and len(price_history.bars) >= 5:
        closes = [b.close for b in price_history.bars]
        current = closes[-1]
        pct_5d = (current / closes[-5] - 1) * 100
        pct_20d = (current / closes[-20] - 1) * 100 if len(closes) >= 20 else None

        momentum_lines = [f"Current price: ${current:.2f}"]
        momentum_lines.append(f"5-day momentum: {pct_5d:+.1f}%")
        if pct_20d is not None:
            momentum_lines.append(f"20-day momentum: {pct_20d:+.1f}%")
        momentum_section = "\n\n## Price Momentum (for sentiment cross-reference)\n" + "\n".join(
            momentum_lines
        )

    # News volume and recency metrics
    news_metrics = _compute_news_metrics(ticker, db_path)
    news_metrics_section = f"\n\n## News Sentiment Metrics\n{news_metrics}"

    return base_context + momentum_section + news_metrics_section


def analyze_ticker(
    ticker: str, save: bool = True, db_path: Optional[str] = None
) -> AnalysisReport:
    """Run the sentiment analyst agent on a single ticker.

    Args:
        ticker: Stock ticker symbol
        save: Whether to save the report to the database
        db_path: Optional database path (for testing)

    Returns:
        AnalysisReport with agent="sentiment_analyst"
    """
    return run_agent(
        ticker=ticker,
        agent_name=AGENT_NAME,
        prompt_path=PROMPT_PATH,
        context_builder=build_sentiment_context,
        save=save,
        db_path=db_path,
    )
