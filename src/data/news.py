"""News/RSS feed fetcher.

Fetches financial news for watchlist tickers via RSS feeds.
Sources: Yahoo Finance RSS, Google News RSS.

No API keys needed — RSS is free and unlimited.
Sentiment scoring is NOT done here — that's the Sentiment Agent's job (Session 6).
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Optional

import requests

from src.config import DB_PATH, WATCHLIST
from src.data.models import NewsArticle, NewsFeed
from src.db.operations import upsert_news
from src.utils.logger import get_logger, log_fetch

logger = get_logger("news")

MAX_RETRIES = 2
RETRY_BACKOFF_BASE = 2
REQUEST_TIMEOUT = 15

# RSS feed URL templates — {ticker} and {query} are substituted
YAHOO_FINANCE_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}+stock&hl=en-US&gl=US&ceid=US:en"


def _headers() -> dict:
    return {
        "User-Agent": "AIInvestmentAgent/1.0 (research tool)",
        "Accept": "application/rss+xml, application/xml, text/xml",
    }


# --- RSS Feed Parsing ---


def fetch_yahoo_news(ticker: str) -> list[NewsArticle]:
    """Fetch news from Yahoo Finance RSS for a ticker."""
    url = YAHOO_FINANCE_RSS.format(ticker=ticker)
    return _fetch_rss(ticker, url, "Yahoo Finance")


def fetch_google_news(ticker: str, company_name: str = "") -> list[NewsArticle]:
    """Fetch news from Google News RSS for a ticker.

    Uses ticker + company name for better search results.
    """
    query = f"{ticker}"
    if company_name:
        query = f"{ticker}+{company_name.replace(' ', '+')}"
    url = GOOGLE_NEWS_RSS.format(query=query)
    return _fetch_rss(ticker, url, "Google News")


def _fetch_rss(ticker: str, url: str, source_name: str) -> list[NewsArticle]:
    """Fetch and parse an RSS feed into NewsArticle objects."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()

            articles = _parse_rss_xml(ticker, resp.text, source_name)
            logger.info(f"Fetched {len(articles)} articles from {source_name} for {ticker}")
            return articles

        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.warning(f"Attempt {attempt}/{MAX_RETRIES} {source_name} failed for {ticker}: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                logger.warning(f"{source_name} RSS failed for {ticker}: {e}")
                return []

    return []


def _parse_rss_xml(ticker: str, xml_text: str, source_name: str) -> list[NewsArticle]:
    """Parse RSS XML into NewsArticle objects."""
    articles = []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning(f"Failed to parse RSS XML from {source_name}: {e}")
        return []

    # Standard RSS 2.0 structure: rss > channel > item
    channel = root.find("channel")
    if channel is None:
        # Try Atom-style feed
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
        if not items:
            items = root.findall(".//item")
    else:
        items = channel.findall("item")

    for item in items:
        try:
            article = _parse_rss_item(ticker, item, source_name)
            if article:
                articles.append(article)
        except Exception as e:
            logger.debug(f"Skipped malformed RSS item: {e}")

    return articles


def _parse_rss_item(ticker: str, item: ET.Element, source_name: str) -> Optional[NewsArticle]:
    """Parse a single RSS item into a NewsArticle."""
    # Try standard RSS fields
    title_el = item.find("title")
    if title_el is None or not title_el.text:
        return None

    title = _clean_html(title_el.text.strip())
    if not title:
        return None

    # Published date
    pub_date = None
    for date_tag in ["pubDate", "published", "dc:date", "updated"]:
        date_el = item.find(date_tag)
        if date_el is not None and date_el.text:
            pub_date = _parse_date(date_el.text.strip())
            if pub_date:
                break

    if pub_date is None:
        pub_date = datetime.now()  # fallback to now if no date

    # URL
    link_el = item.find("link")
    url = None
    if link_el is not None:
        url = link_el.text.strip() if link_el.text else link_el.get("href")

    # Summary/description
    desc_el = item.find("description")
    summary = None
    if desc_el is not None and desc_el.text:
        summary = _clean_html(desc_el.text.strip())
        if summary and len(summary) > 500:
            summary = summary[:497] + "..."

    # Source attribution
    source_el = item.find("source")
    source = source_name
    if source_el is not None and source_el.text:
        source = source_el.text.strip()

    return NewsArticle(
        ticker=ticker,
        title=title,
        source=source,
        url=url,
        published_at=pub_date,
        summary=summary,
    )


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse various date formats from RSS feeds.

    Always returns a naive (tz-unaware) datetime for consistency.
    All timestamps are stored as-is without timezone conversion.
    """
    result = None

    # Try RFC 2822 (standard RSS)
    try:
        result = parsedate_to_datetime(date_str)
    except (ValueError, TypeError):
        pass

    # Try ISO 8601
    if result is None:
        try:
            result = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    # Try common formats
    if result is None:
        for fmt in ["%a, %d %b %Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
            try:
                result = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue

    # Strip timezone info to keep all datetimes naive and consistent
    if result is not None and result.tzinfo is not None:
        result = result.replace(tzinfo=None)

    return result


def _clean_html(text: str) -> str:
    """Remove HTML tags and clean up text."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# --- Aggregate Fetcher ---


def fetch_news(ticker: str, company_name: str = "") -> NewsFeed:
    """Fetch news from all RSS sources for a ticker.

    Combines Yahoo Finance and Google News, deduplicates by title.
    """
    with log_fetch(logger, ticker, "news") as ctx:
        all_articles: list[NewsArticle] = []

        # Fetch from each source
        yahoo = fetch_yahoo_news(ticker)
        all_articles.extend(yahoo)

        google = fetch_google_news(ticker, company_name)
        all_articles.extend(google)

        # Deduplicate by normalized title
        seen_titles: set[str] = set()
        unique: list[NewsArticle] = []
        for article in all_articles:
            normalized = article.title.lower().strip()
            if normalized not in seen_titles:
                seen_titles.add(normalized)
                unique.append(article)

        # Sort by date, newest first
        unique.sort(key=lambda a: a.published_at, reverse=True)

        ctx["records"] = len(unique)
        return NewsFeed(ticker=ticker, articles=unique)


# --- Batch Operations ---


def update_all_news(db_path: Optional[str] = None) -> dict:
    """Fetch and store news for all watchlist tickers.

    Returns a summary dict with successes, failures, and total articles.
    """
    db = db_path or DB_PATH

    results = {"successes": [], "failures": [], "total_articles": 0}

    for ticker, info in WATCHLIST.items():
        try:
            feed = fetch_news(ticker, company_name=info["name"])

            if not feed.is_empty:
                upsert_news(feed.articles, db_path=db)
                results["total_articles"] += len(feed.articles)

            results["successes"].append({"ticker": ticker, "articles": len(feed.articles)})
            logger.info(f"[{len(results['successes'])}/{len(WATCHLIST)}] {ticker}: {len(feed.articles)} articles")

        except Exception as e:
            logger.error(f"Unexpected error for {ticker}: {e}")
            results["failures"].append({"ticker": ticker, "reason": str(e)})

    logger.info(
        f"News update complete: {len(results['successes'])} succeeded, "
        f"{len(results['failures'])} failed, {results['total_articles']} total articles"
    )
    return results
