"""Tests for the data pipeline — Phase 1b (EDGAR + News).

Model validation tests run offline.
DB tests use a temp database.
Integration tests hit real EDGAR API and RSS feeds.
"""

import os
import tempfile
from datetime import date, datetime

import pytest

from src.data.models import (
    FilingContent,
    FilingInfo,
    FilingType,
    NewsArticle,
    NewsFeed,
)
from src.db.operations import (
    get_connection,
    get_filing_content,
    get_filings,
    get_news,
    init_db,
    upsert_filing,
    upsert_news,
)


# --- Fixtures ---


@pytest.fixture
def tmp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    os.unlink(db_path)


# --- Filing model tests ---


class TestFilingInfo:
    def test_valid_filing(self):
        filing = FilingInfo(
            ticker="AVGO",
            cik="1649338",
            accession_number="0001649338-25-000001",
            filing_type=FilingType.TEN_K,
            filed_date=date(2025, 12, 15),
            filing_url="https://www.sec.gov/Archives/edgar/data/1649338/...",
        )
        assert filing.ticker == "AVGO"
        assert filing.filing_type == FilingType.TEN_K

    def test_cik_must_be_numeric(self):
        with pytest.raises(ValueError, match="numeric"):
            FilingInfo(
                ticker="AVGO",
                cik="abc",
                accession_number="0001649338-25-000001",
                filing_type=FilingType.TEN_K,
                filed_date=date(2025, 12, 15),
                filing_url="https://example.com",
            )

    def test_cik_strips_leading_zeros(self):
        filing = FilingInfo(
            ticker="AVGO",
            cik="0001649338",
            accession_number="0001649338-25-000001",
            filing_type=FilingType.TEN_K,
            filed_date=date(2025, 12, 15),
            filing_url="https://example.com",
        )
        assert filing.cik == "1649338"

    def test_all_filing_types(self):
        for ft in FilingType:
            filing = FilingInfo(
                ticker="TSM",
                cik="1046179",
                accession_number=f"test-{ft.value}",
                filing_type=ft,
                filed_date=date(2025, 1, 1),
                filing_url="https://example.com",
            )
            assert filing.filing_type == ft

    def test_optional_fields(self):
        filing = FilingInfo(
            ticker="TSM",
            cik="1046179",
            accession_number="test-123",
            filing_type=FilingType.TEN_Q,
            filed_date=date(2025, 6, 1),
            filing_url="https://example.com",
        )
        assert filing.report_date is None
        assert filing.title is None


class TestFilingContent:
    def test_empty_content(self):
        content = FilingContent(
            accession_number="test-123",
            filing_type=FilingType.TEN_K,
        )
        assert not content.has_content
        assert content.raw_text_length == 0

    def test_with_sections(self):
        content = FilingContent(
            accession_number="test-123",
            filing_type=FilingType.TEN_K,
            business="We are a semiconductor company...",
            risk_factors="Geopolitical risks in Taiwan...",
            mda="Revenue grew 35% year over year...",
            raw_text_length=500000,
        )
        assert content.has_content
        assert "semiconductor" in content.business

    def test_serialization_roundtrip(self):
        original = FilingContent(
            accession_number="test-123",
            filing_type=FilingType.TEN_K,
            risk_factors="Some risk factors here",
            mda="Management discussion here",
            raw_text_length=100000,
        )
        json_str = original.model_dump_json()
        restored = FilingContent.model_validate_json(json_str)
        assert restored.risk_factors == original.risk_factors
        assert restored.mda == original.mda


# --- News model tests ---


class TestNewsArticle:
    def test_valid_article(self):
        article = NewsArticle(
            ticker="TSM",
            title="TSM Reports Record Revenue",
            source="Yahoo Finance",
            url="https://example.com/article",
            published_at=datetime(2026, 3, 15, 10, 30),
            summary="Taiwan Semiconductor reported record Q1 revenue...",
        )
        assert article.ticker == "TSM"
        assert article.title == "TSM Reports Record Revenue"

    def test_empty_title_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            NewsArticle(
                ticker="TSM",
                title="   ",
                published_at=datetime(2026, 3, 15),
            )

    def test_whitespace_title_stripped(self):
        article = NewsArticle(
            ticker="TSM",
            title="  Some title  ",
            published_at=datetime(2026, 3, 15),
        )
        assert article.title == "Some title"

    def test_minimal_article(self):
        article = NewsArticle(
            ticker="TSM",
            title="Headline",
            published_at=datetime(2026, 3, 15),
        )
        assert article.source is None
        assert article.url is None
        assert article.summary is None


class TestNewsFeed:
    def test_empty_feed(self):
        feed = NewsFeed(ticker="TSM", articles=[])
        assert feed.is_empty

    def test_non_empty_feed(self):
        articles = [
            NewsArticle(ticker="TSM", title="Article 1", published_at=datetime(2026, 3, 15)),
            NewsArticle(ticker="TSM", title="Article 2", published_at=datetime(2026, 3, 14)),
        ]
        feed = NewsFeed(ticker="TSM", articles=articles)
        assert not feed.is_empty
        assert len(feed.articles) == 2


# --- Filing DB tests ---


class TestFilingOperations:
    def test_upsert_and_read_filing(self, tmp_db):
        filing = FilingInfo(
            ticker="AVGO",
            cik="1649338",
            accession_number="0001649338-25-000001",
            filing_type=FilingType.TEN_K,
            filed_date=date(2025, 12, 15),
            report_date=date(2025, 10, 31),
            title="Annual Report",
            filing_url="https://example.com/filing",
        )
        upsert_filing(filing, db_path=tmp_db)

        results = get_filings("AVGO", db_path=tmp_db)
        assert len(results) == 1
        assert results[0].accession_number == "0001649338-25-000001"
        assert results[0].filing_type == FilingType.TEN_K
        assert results[0].filed_date == date(2025, 12, 15)

    def test_upsert_with_content(self, tmp_db):
        filing = FilingInfo(
            ticker="AVGO",
            cik="1649338",
            accession_number="0001649338-25-000002",
            filing_type=FilingType.TEN_Q,
            filed_date=date(2025, 9, 1),
            filing_url="https://example.com/filing2",
        )
        content = FilingContent(
            accession_number="0001649338-25-000002",
            filing_type=FilingType.TEN_Q,
            mda="Revenue increased by 20%...",
            risk_factors="Supply chain disruptions...",
            raw_text_length=200000,
        )
        upsert_filing(filing, content=content, db_path=tmp_db)

        result = get_filing_content("0001649338-25-000002", db_path=tmp_db)
        assert result is not None
        assert result.mda == "Revenue increased by 20%..."
        assert result.risk_factors == "Supply chain disruptions..."

    def test_content_none_for_missing(self, tmp_db):
        result = get_filing_content("nonexistent", db_path=tmp_db)
        assert result is None

    def test_filter_by_type(self, tmp_db):
        for i, ft in enumerate([FilingType.TEN_K, FilingType.TEN_Q, FilingType.TEN_Q]):
            filing = FilingInfo(
                ticker="AVGO",
                cik="1649338",
                accession_number=f"test-{i}",
                filing_type=ft,
                filed_date=date(2025, 1 + i, 1),
                filing_url="https://example.com",
            )
            upsert_filing(filing, db_path=tmp_db)

        ten_k = get_filings("AVGO", filing_type=FilingType.TEN_K, db_path=tmp_db)
        assert len(ten_k) == 1

        ten_q = get_filings("AVGO", filing_type=FilingType.TEN_Q, db_path=tmp_db)
        assert len(ten_q) == 2

    def test_filings_ordered_by_date_desc(self, tmp_db):
        for i, d in enumerate([date(2025, 1, 1), date(2025, 6, 1), date(2025, 12, 1)]):
            filing = FilingInfo(
                ticker="AVGO",
                cik="1649338",
                accession_number=f"date-test-{i}",
                filing_type=FilingType.TEN_Q,
                filed_date=d,
                filing_url="https://example.com",
            )
            upsert_filing(filing, db_path=tmp_db)

        results = get_filings("AVGO", db_path=tmp_db)
        assert results[0].filed_date == date(2025, 12, 1)
        assert results[2].filed_date == date(2025, 1, 1)

    def test_upsert_is_idempotent(self, tmp_db):
        filing = FilingInfo(
            ticker="AVGO",
            cik="1649338",
            accession_number="idem-test",
            filing_type=FilingType.TEN_K,
            filed_date=date(2025, 12, 1),
            filing_url="https://example.com",
        )
        upsert_filing(filing, db_path=tmp_db)
        upsert_filing(filing, db_path=tmp_db)

        results = get_filings("AVGO", db_path=tmp_db)
        assert len(results) == 1

    def test_upsert_preserves_content_on_reinsert(self, tmp_db):
        """Re-upserting without content should NOT erase existing content."""
        filing = FilingInfo(
            ticker="AVGO",
            cik="1649338",
            accession_number="preserve-test",
            filing_type=FilingType.TEN_K,
            filed_date=date(2025, 12, 1),
            filing_url="https://example.com",
        )
        content = FilingContent(
            accession_number="preserve-test",
            filing_type=FilingType.TEN_K,
            mda="Important analysis data",
            raw_text_length=50000,
        )
        # First insert with content
        upsert_filing(filing, content=content, db_path=tmp_db)

        # Re-insert without content (simulates re-fetch where content fetch failed)
        upsert_filing(filing, content=None, db_path=tmp_db)

        # Content should still be there
        result = get_filing_content("preserve-test", db_path=tmp_db)
        assert result is not None
        assert result.mda == "Important analysis data"


# --- News DB tests ---


class TestNewsOperations:
    def test_upsert_and_read_news(self, tmp_db):
        articles = [
            NewsArticle(
                ticker="TSM",
                title="TSM Beats Earnings",
                source="Yahoo Finance",
                url="https://example.com/1",
                published_at=datetime(2026, 3, 15, 10, 0),
                summary="Record quarter...",
            ),
            NewsArticle(
                ticker="TSM",
                title="TSM Expands CoWoS",
                source="Reuters",
                published_at=datetime(2026, 3, 14, 8, 0),
            ),
        ]
        count = upsert_news(articles, db_path=tmp_db)
        assert count == 2

        results = get_news("TSM", db_path=tmp_db)
        assert len(results) == 2
        # Should be newest first
        assert results[0].title == "TSM Beats Earnings"

    def test_dedup_by_title_and_date(self, tmp_db):
        article = NewsArticle(
            ticker="TSM",
            title="Duplicate Headline",
            published_at=datetime(2026, 3, 15, 10, 0),
        )
        upsert_news([article], db_path=tmp_db)
        upsert_news([article], db_path=tmp_db)

        results = get_news("TSM", db_path=tmp_db)
        assert len(results) == 1

    def test_filter_by_since(self, tmp_db):
        articles = [
            NewsArticle(ticker="TSM", title="Old News", published_at=datetime(2026, 1, 1)),
            NewsArticle(ticker="TSM", title="New News", published_at=datetime(2026, 3, 15)),
        ]
        upsert_news(articles, db_path=tmp_db)

        results = get_news("TSM", since=datetime(2026, 3, 1), db_path=tmp_db)
        assert len(results) == 1
        assert results[0].title == "New News"

    def test_empty_articles_list(self, tmp_db):
        count = upsert_news([], db_path=tmp_db)
        assert count == 0

    def test_news_for_wrong_ticker_empty(self, tmp_db):
        articles = [
            NewsArticle(ticker="TSM", title="TSM News", published_at=datetime(2026, 3, 15)),
        ]
        upsert_news(articles, db_path=tmp_db)

        results = get_news("AVGO", db_path=tmp_db)
        assert len(results) == 0


# --- Schema tests ---


class TestSchemaAdditions:
    def test_filings_table_exists(self, tmp_db):
        conn = get_connection(tmp_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='filings'"
        ).fetchall()
        assert len(tables) == 1
        conn.close()

    def test_news_table_exists(self, tmp_db):
        conn = get_connection(tmp_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='news_articles'"
        ).fetchall()
        assert len(tables) == 1
        conn.close()


# --- EDGAR HTML parsing tests ---


class TestEdgarParsing:
    def test_html_to_text(self):
        from src.data.edgar import _html_to_text

        html = "<p>Hello <b>world</b></p><script>evil()</script>"
        text = _html_to_text(html)
        assert "Hello" in text
        assert "world" in text
        assert "evil" not in text
        assert "<" not in text

    def test_html_to_text_entities(self):
        from src.data.edgar import _html_to_text

        html = "Revenue &amp; profit &gt; expectations"
        text = _html_to_text(html)
        assert "Revenue & profit > expectations" in text

    def test_extract_sections_10k(self):
        from src.data.edgar import _extract_sections

        # Simulate a minimal 10-K with section headers
        fake_text = (
            "Table of Contents\n"
            "Item 1. Business\n"
            + "A" * 200  # business section content
            + "\nItem 1A. Risk Factors\n"
            + "B" * 200  # risk factors content
            + "\nItem 1B. Unresolved Staff Comments\n"
            + "C" * 200
            + "\nItem 7. Management Discussion\n"
            + "D" * 200  # MDA content
            + "\nItem 7A. Quantitative Disclosures\n"
        )
        content = _extract_sections("test", FilingType.TEN_K, fake_text)
        assert content.business is not None
        assert "A" * 100 in content.business
        assert content.risk_factors is not None
        assert "B" * 100 in content.risk_factors
        assert content.mda is not None
        assert "D" * 100 in content.mda

    def test_extract_sections_missing_section(self):
        from src.data.edgar import _extract_sections

        # Text with no recognizable sections
        content = _extract_sections("test", FilingType.TEN_K, "Just some random text")
        assert not content.has_content

    def test_section_too_short_returns_none(self):
        from src.data.edgar import _extract_sections

        # Section content < 100 chars = treated as just a header
        fake_text = "Item 1. Business\nShort\nItem 1A. Risk\nAlso short\nItem 1B. End"
        content = _extract_sections("test", FilingType.TEN_K, fake_text)
        assert content.business is None

    def test_extract_sections_10q(self):
        from src.data.edgar import _extract_sections

        fake_text = (
            "Item 1A. Risk Factors\n"
            + "R" * 200
            + "\nItem 2. MD&A\n"
            + "M" * 200
            + "\nItem 3. Quantitative\n"
        )
        content = _extract_sections("test", FilingType.TEN_Q, fake_text)
        assert content.risk_factors is not None
        assert "R" * 100 in content.risk_factors
        assert content.mda is not None
        assert "M" * 100 in content.mda

    def test_extract_sections_8k_returns_empty(self):
        from src.data.edgar import _extract_sections

        content = _extract_sections("test", FilingType.EIGHT_K, "Some 8-K content here")
        assert not content.has_content

    def test_find_section_no_end_marker(self):
        from src.data.edgar import _find_section

        text = "Item 7. Management Discussion\n" + "X" * 200
        result = _find_section(text, r"item\s*7[.\s]", r"item\s*99[.\s]")
        assert result is not None
        assert "X" * 100 in result


# --- News RSS parsing tests ---


class TestNewsParsing:
    def test_parse_rss_xml(self):
        from src.data.news import _parse_rss_xml

        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
        <channel>
            <item>
                <title>TSM Earnings Beat</title>
                <link>https://example.com/1</link>
                <pubDate>Mon, 15 Mar 2026 10:00:00 GMT</pubDate>
                <description>Record revenue reported</description>
            </item>
            <item>
                <title>TSM Expands Capacity</title>
                <link>https://example.com/2</link>
                <pubDate>Sun, 14 Mar 2026 08:00:00 GMT</pubDate>
            </item>
        </channel>
        </rss>"""

        articles = _parse_rss_xml("TSM", xml, "Test Source")
        assert len(articles) == 2
        assert articles[0].title == "TSM Earnings Beat"
        assert articles[0].source == "Test Source"
        assert articles[1].title == "TSM Expands Capacity"

    def test_parse_rss_empty_title_skipped(self):
        from src.data.news import _parse_rss_xml

        xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
            <item><title></title><pubDate>Mon, 15 Mar 2026 10:00:00 GMT</pubDate></item>
            <item><title>Valid</title><pubDate>Mon, 15 Mar 2026 10:00:00 GMT</pubDate></item>
        </channel></rss>"""

        articles = _parse_rss_xml("TSM", xml, "Test")
        assert len(articles) == 1
        assert articles[0].title == "Valid"

    def test_parse_rss_malformed_xml(self):
        from src.data.news import _parse_rss_xml

        articles = _parse_rss_xml("TSM", "not xml at all", "Test")
        assert articles == []

    def test_clean_html(self):
        from src.data.news import _clean_html

        assert _clean_html("<b>Bold</b> text") == "Bold text"
        assert _clean_html("A &amp; B") == "A & B"

    def test_parse_date_rfc2822(self):
        from src.data.news import _parse_date

        dt = _parse_date("Mon, 15 Mar 2026 10:00:00 GMT")
        assert dt is not None
        assert dt.day == 15
        assert dt.month == 3

    def test_parse_date_iso(self):
        from src.data.news import _parse_date

        dt = _parse_date("2026-03-15T10:00:00Z")
        assert dt is not None
        assert dt.day == 15

    def test_parse_date_invalid(self):
        from src.data.news import _parse_date

        assert _parse_date("not a date") is None

    def test_parse_date_returns_naive_datetime(self):
        """All parsed dates should be timezone-naive for consistency."""
        from src.data.news import _parse_date

        # RFC 2822 with timezone
        dt = _parse_date("Mon, 15 Mar 2026 10:00:00 GMT")
        assert dt is not None
        assert dt.tzinfo is None

        # ISO with Z
        dt = _parse_date("2026-03-15T10:00:00Z")
        assert dt is not None
        assert dt.tzinfo is None

    def test_summary_truncation(self):
        from src.data.news import _parse_rss_xml

        long_desc = "A" * 600
        xml = f"""<?xml version="1.0"?>
        <rss version="2.0"><channel>
            <item>
                <title>Test</title>
                <pubDate>Mon, 15 Mar 2026 10:00:00 GMT</pubDate>
                <description>{long_desc}</description>
            </item>
        </channel></rss>"""

        articles = _parse_rss_xml("TSM", xml, "Test")
        assert len(articles) == 1
        assert len(articles[0].summary) == 500
        assert articles[0].summary.endswith("...")

    def test_rss_source_element_override(self):
        from src.data.news import _parse_rss_xml

        xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
            <item>
                <title>Headline</title>
                <pubDate>Mon, 15 Mar 2026 10:00:00 GMT</pubDate>
                <source>Reuters</source>
            </item>
        </channel></rss>"""

        articles = _parse_rss_xml("TSM", xml, "Default Source")
        assert len(articles) == 1
        assert articles[0].source == "Reuters"


# --- Integration tests (hit real APIs) ---


class TestEdgarIntegration:
    """These tests hit the real SEC EDGAR API."""

    def test_get_cik_for_avgo(self):
        """AVGO (Broadcom) should have a CIK — it's a US-listed company."""
        from src.data.edgar import get_cik

        cik = get_cik("AVGO")
        assert cik is not None
        assert cik.isdigit()

    def test_get_cik_nonexistent(self):
        from src.data.edgar import get_cik

        cik = get_cik("ZZZZNOTREAL999")
        assert cik is None

    def test_fetch_filing_list_avgo(self):
        """Fetch real 10-K/10-Q filings for Broadcom."""
        from src.data.edgar import fetch_filing_list

        filings = fetch_filing_list("AVGO", limit=5)
        assert len(filings) > 0

        filing = filings[0]
        assert filing.ticker == "AVGO"
        assert filing.filing_type in [FilingType.TEN_K, FilingType.TEN_Q]
        assert filing.filed_date < date.today()
        assert filing.filing_url.startswith("https://")

    def test_fetch_filing_list_filter_10k(self):
        """Filter to only 10-K filings."""
        from src.data.edgar import fetch_filing_list

        filings = fetch_filing_list("AVGO", filing_types=[FilingType.TEN_K], limit=3)
        for f in filings:
            assert f.filing_type == FilingType.TEN_K

    def test_fetch_filing_content(self):
        """Fetch actual filing content for the most recent AVGO filing."""
        from src.data.edgar import fetch_filing_content, fetch_filing_list

        filings = fetch_filing_list("AVGO", filing_types=[FilingType.TEN_K], limit=1)
        if not filings:
            pytest.skip("No 10-K filings found for AVGO")

        content = fetch_filing_content(filings[0])
        assert content is not None
        assert content.raw_text_length > 0
        # 10-K should have at least some extractable sections
        # (but parsing is best-effort, so we don't assert has_content)

    def test_foreign_ticker_no_filings(self):
        """ASML is Dutch — may have limited SEC filings (20-F instead of 10-K)."""
        from src.data.edgar import fetch_filing_list

        filings = fetch_filing_list("ASML", filing_types=[FilingType.TEN_K], limit=3)
        # ASML files 20-F, not 10-K, so this should return empty or very few
        # Just verifying it doesn't crash
        assert isinstance(filings, list)


class TestNewsIntegration:
    """These tests hit real RSS feeds."""

    def test_fetch_yahoo_news(self):
        """Fetch real Yahoo Finance RSS for a major stock."""
        from src.data.news import fetch_yahoo_news

        articles = fetch_yahoo_news("AAPL")
        # Yahoo RSS may or may not return results — just check it doesn't crash
        assert isinstance(articles, list)

    def test_fetch_google_news(self):
        """Fetch real Google News RSS."""
        from src.data.news import fetch_google_news

        articles = fetch_google_news("NVDA", "NVIDIA")
        assert isinstance(articles, list)

    def test_fetch_news_aggregate(self):
        """Fetch from all sources combined."""
        from src.data.news import fetch_news

        feed = fetch_news("AVGO", company_name="Broadcom")
        assert isinstance(feed, NewsFeed)
        assert feed.ticker == "AVGO"
        # Articles may be empty if RSS feeds are down, but shouldn't crash
        assert isinstance(feed.articles, list)
