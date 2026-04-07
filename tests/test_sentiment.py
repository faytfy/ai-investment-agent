"""Tests for the sentiment analyst agent — news metrics, context building, and E2E."""

import os
import tempfile
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from src.agents.sentiment import _compute_news_metrics, build_sentiment_context
from src.data.models import (
    AnalysisReport,
    FundamentalsSnapshot,
    NewsArticle,
    PriceBar,
    PriceHistory,
    Signal,
)
from src.db.operations import (
    get_reports,
    init_db,
    save_report,
    upsert_fundamentals,
    upsert_news,
    upsert_prices,
)


# ============================================================
# Helpers
# ============================================================


def _make_articles(ticker: str, count: int, days_ago_start: int = 0) -> list[NewsArticle]:
    """Create a list of news articles spread over time."""
    now = datetime.now()
    return [
        NewsArticle(
            ticker=ticker,
            title=f"Article {i} about {ticker}",
            source=f"Source{i % 3}",  # 3 unique sources
            published_at=now - timedelta(days=days_ago_start + i),
            summary=f"Summary of article {i}.",
        )
        for i in range(count)
    ]


def _make_price_bars(count: int = 25) -> list[PriceBar]:
    """Create price bars for testing."""
    return [
        PriceBar(
            date=date(2026, 3, 1) + timedelta(days=i),
            open=170.0 + i * 0.5,
            high=175.0 + i * 0.5,
            low=165.0 + i * 0.5,
            close=172.0 + i * 0.5,
            volume=5_000_000,
        )
        for i in range(count)
        if (date(2026, 3, 1) + timedelta(days=i)).weekday() < 5
    ]


# ============================================================
# News metrics computation tests
# ============================================================


class TestNewsMetrics:
    """Test _compute_news_metrics produces correct sentiment signals."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)
            yield tmp.name

    def test_no_articles(self, db_path):
        result = _compute_news_metrics("TSM", db_path=db_path)
        assert "Total articles (30 days): 0" in result
        assert "NONE" in result

    def test_recent_surge(self, db_path):
        """Many articles in last 7 days = surging."""
        articles = _make_articles("TSM", count=10, days_ago_start=0)
        upsert_news(articles, db_path=db_path)
        result = _compute_news_metrics("TSM", db_path=db_path)
        assert "SURGING" in result

    def test_moderate_volume(self, db_path):
        """Some articles in last 7 days but majority older."""
        old_articles = _make_articles("TSM", count=8, days_ago_start=10)
        recent_articles = _make_articles("TSM", count=2, days_ago_start=0)
        # Use different titles to avoid dedup
        for i, a in enumerate(recent_articles):
            a.title = f"Recent article {i}"
        upsert_news(old_articles + recent_articles, db_path=db_path)
        result = _compute_news_metrics("TSM", db_path=db_path)
        assert "Total articles (30 days):" in result

    def test_quiet_period(self, db_path):
        """All articles older than 7 days = quiet."""
        articles = _make_articles("TSM", count=5, days_ago_start=10)
        upsert_news(articles, db_path=db_path)
        result = _compute_news_metrics("TSM", db_path=db_path)
        assert "QUIET" in result

    def test_source_diversity(self, db_path):
        articles = _make_articles("TSM", count=6, days_ago_start=0)
        upsert_news(articles, db_path=db_path)
        result = _compute_news_metrics("TSM", db_path=db_path)
        assert "Unique sources:" in result

    def test_most_recent_article_age(self, db_path):
        articles = _make_articles("TSM", count=3, days_ago_start=2)
        upsert_news(articles, db_path=db_path)
        result = _compute_news_metrics("TSM", db_path=db_path)
        assert "Most recent article:" in result
        assert "day(s) ago" in result


# ============================================================
# Context building tests
# ============================================================


class TestSentimentContext:
    """Test that sentiment context includes enrichment sections."""

    def test_context_includes_news_metrics_with_data(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)

            bars = _make_price_bars()
            upsert_prices("TSM", PriceHistory(ticker="TSM", bars=bars), db_path=tmp.name)

            articles = _make_articles("TSM", count=5, days_ago_start=0)
            upsert_news(articles, db_path=tmp.name)

            context = build_sentiment_context("TSM", db_path=tmp.name)

            assert "# Analysis Data for TSM" in context
            assert "## News Sentiment Metrics" in context
            assert "Total articles (30 days):" in context

    def test_context_includes_price_momentum(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)

            bars = _make_price_bars(count=25)
            upsert_prices("TSM", PriceHistory(ticker="TSM", bars=bars), db_path=tmp.name)

            context = build_sentiment_context("TSM", db_path=tmp.name)

            assert "## Price Momentum" in context
            assert "5-day momentum:" in context

    def test_context_without_news(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)

            context = build_sentiment_context("TSM", db_path=tmp.name)

            assert "# Analysis Data for TSM" in context
            assert "## News Sentiment Metrics" in context
            assert "Total articles (30 days): 0" in context

    def test_context_without_price_data(self):
        """No price bars means no momentum section."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)

            context = build_sentiment_context("TSM", db_path=tmp.name)

            assert "## Price Momentum" not in context

    def test_context_with_exactly_5_bars(self):
        """Exactly 5 bars — should show 5-day momentum but not 20-day."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)

            bars = [
                PriceBar(
                    date=date(2026, 3, i + 3),  # Mon-Fri
                    open=170.0, high=175.0, low=165.0,
                    close=172.0 + i, volume=5_000_000,
                )
                for i in range(5)
            ]
            upsert_prices("TSM", PriceHistory(ticker="TSM", bars=bars), db_path=tmp.name)

            context = build_sentiment_context("TSM", db_path=tmp.name)

            assert "5-day momentum:" in context
            assert "20-day momentum:" not in context

    def test_context_with_fewer_than_5_bars(self):
        """Fewer than 5 bars — no momentum section at all."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)

            bars = [
                PriceBar(
                    date=date(2026, 3, i + 3),
                    open=170.0, high=175.0, low=165.0,
                    close=172.0, volume=5_000_000,
                )
                for i in range(3)
            ]
            upsert_prices("TSM", PriceHistory(ticker="TSM", bars=bars), db_path=tmp.name)

            context = build_sentiment_context("TSM", db_path=tmp.name)

            assert "## Price Momentum" not in context


# ============================================================
# Report model tests
# ============================================================


class TestSentimentReportModel:
    """Test that sentiment analyst reports have correct agent name."""

    def test_agent_name(self):
        report = AnalysisReport(
            ticker="TSM",
            agent="sentiment_analyst",
            signal="bullish",
            confidence=0.70,
            thesis="Positive news sentiment driven by record revenue reports.",
            bull_case="Continued positive coverage drives sentiment.",
            bear_case="Narrative reversal on geopolitical concerns.",
            risks=["Narrative fatigue"],
            evidence=["5 positive articles in 7 days"],
        )
        assert report.agent == "sentiment_analyst"

    def test_sentiment_report_serialization(self):
        report = AnalysisReport(
            ticker="TSM",
            agent="sentiment_analyst",
            signal="neutral",
            confidence=0.55,
            thesis="Mixed sentiment signals.",
            key_metrics={"news_article_count": 8.0, "sentiment_direction": 0.0},
            bull_case="Positive earnings coverage.",
            bear_case="Geopolitical concerns weighing.",
            risks=["Narrative shift risk", "Crowded trade"],
            evidence=["Reuters reported record Q4", "Taiwan tensions in headlines"],
        )
        json_str = report.model_dump_json()
        restored = AnalysisReport.model_validate_json(json_str)
        assert restored.agent == "sentiment_analyst"
        assert restored.key_metrics["news_article_count"] == 8.0


# ============================================================
# DB round-trip tests
# ============================================================


class TestSentimentReportDB:
    """Test saving/retrieving sentiment analyst reports."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)
            yield tmp.name

    def test_save_and_retrieve_sentiment_report(self, db_path):
        report = AnalysisReport(
            ticker="TSM",
            agent="sentiment_analyst",
            signal="bullish",
            confidence=0.72,
            thesis="Strong positive sentiment.",
            bull_case="News flow positive.",
            bear_case="Narrative reversal.",
            risks=["Hype exhaustion"],
            evidence=["Record coverage"],
        )

        save_report(
            ticker=report.ticker,
            agent_name=report.agent,
            report_date=report.report_date,
            report=report.model_dump(mode="json"),
            signal=report.signal.value,
            confidence=report.confidence,
            db_path=db_path,
        )

        reports = get_reports("TSM", db_path=db_path)
        assert len(reports) == 1
        assert reports[0]["report"]["agent"] == "sentiment_analyst"
        assert reports[0]["signal"] == "bullish"

    def test_multiple_agents_coexist(self, db_path):
        """Sentiment + fundamental reports coexist for same ticker."""
        for agent_name in ["fundamental_analyst", "sentiment_analyst"]:
            save_report(
                ticker="TSM",
                agent_name=agent_name,
                report_date=date.today(),
                report={"ticker": "TSM", "agent": agent_name, "signal": "bullish"},
                signal="bullish",
                confidence=0.75,
                db_path=db_path,
            )

        reports = get_reports("TSM", db_path=db_path)
        assert len(reports) == 2
        agents = {r["report"]["agent"] for r in reports}
        assert "fundamental_analyst" in agents
        assert "sentiment_analyst" in agents


# ============================================================
# E2E test — requires ANTHROPIC_API_KEY
# ============================================================


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping E2E test",
)
class TestE2ESentimentAnalysis:
    """End-to-end: seed DB, run sentiment analyst, validate report."""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_db(tmp.name)
            yield tmp.name

    def test_sentiment_analyze_ticker(self, db_path):
        bars = _make_price_bars(count=25)
        upsert_prices("TSM", PriceHistory(ticker="TSM", bars=bars), db_path=db_path)

        fundamentals = FundamentalsSnapshot(
            ticker="TSM",
            revenue=70_000_000_000,
            revenue_growth_yoy=0.35,
            gross_margin=0.57,
            market_cap=800_000_000_000,
        )
        upsert_fundamentals(fundamentals, db_path=db_path)

        articles = [
            NewsArticle(
                ticker="TSM",
                title="TSMC Reports Record Q4 Revenue on AI Demand",
                source="Reuters",
                published_at=datetime.now() - timedelta(days=1),
                summary="Record quarterly revenue driven by AI chip demand.",
            ),
            NewsArticle(
                ticker="TSM",
                title="TSMC Expands CoWoS Packaging Capacity for 2027",
                source="Bloomberg",
                published_at=datetime.now() - timedelta(days=3),
                summary="Advanced packaging expansion announced.",
            ),
        ]
        upsert_news(articles, db_path=db_path)

        from src.agents.sentiment import analyze_ticker

        report = analyze_ticker("TSM", save=False, db_path=db_path)

        assert report.ticker == "TSM"
        assert report.agent == "sentiment_analyst"
        assert report.signal in [Signal.BULLISH, Signal.BEARISH, Signal.NEUTRAL]
        assert 0.0 <= report.confidence <= 1.0
        assert len(report.thesis) > 10
        assert len(report.risks) >= 1
        assert len(report.evidence) >= 1
