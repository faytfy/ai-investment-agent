"""SEC EDGAR filing fetcher.

Uses the EDGAR API to look up company filings (10-K, 10-Q, 8-K)
and extract key sections for analysis.

Rate limit: 10 requests/sec — we add 0.15s delay between requests.
User-Agent header required per SEC policy.
"""

import re
import time
from datetime import date, datetime
from html import unescape
from typing import Optional

import requests

from src.config import DB_PATH, SEC_EDGAR_BASE_URL, SEC_EDGAR_USER_AGENT, WATCHLIST
from src.data.models import FilingContent, FilingInfo, FilingType
from src.db.operations import upsert_filing
from src.utils.logger import get_logger, log_fetch

logger = get_logger("edgar")

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2
REQUEST_DELAY = 0.15  # seconds between requests (stay under 10/sec)
MAX_SECTION_CHARS = 50_000  # cap extracted section text

# EDGAR API endpoints
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FILING_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}"

# Cache ticker → CIK mapping (loaded once per process)
_cik_cache: dict[str, str] = {}
_cik_cache_loaded: bool = False


def _headers() -> dict:
    return {"User-Agent": SEC_EDGAR_USER_AGENT, "Accept": "application/json"}


def _rate_limit():
    time.sleep(REQUEST_DELAY)


# --- CIK Lookup ---


def get_cik(ticker: str) -> Optional[str]:
    """Look up CIK number for a ticker symbol.

    Uses SEC's company_tickers.json which maps all tickers to CIK numbers.
    Results are cached in-memory for the process lifetime.
    """
    global _cik_cache_loaded

    if not _cik_cache_loaded:
        _load_cik_mapping()
        _cik_cache_loaded = True

    return _cik_cache.get(ticker)


def _load_cik_mapping() -> None:
    """Load the full ticker → CIK mapping from SEC."""
    global _cik_cache
    try:
        _rate_limit()
        resp = requests.get(COMPANY_TICKERS_URL, headers=_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for entry in data.values():
            t = entry.get("ticker", "").upper()
            cik = str(entry.get("cik_str", ""))
            if t and cik:
                _cik_cache[t] = cik

        logger.info(f"Loaded {len(_cik_cache)} ticker→CIK mappings from SEC")
    except Exception as e:
        logger.error(f"Failed to load CIK mapping: {e}")


# --- Filing List ---


def fetch_filing_list(
    ticker: str,
    filing_types: Optional[list[FilingType]] = None,
    limit: int = 10,
) -> list[FilingInfo]:
    """Fetch recent filings for a ticker from EDGAR.

    Args:
        ticker: Stock symbol
        filing_types: Filter to these types (default: 10-K and 10-Q)
        limit: Max filings to return

    Returns:
        List of FilingInfo, newest first. Empty list on failure.
    """
    if filing_types is None:
        filing_types = [FilingType.TEN_K, FilingType.TEN_Q]

    type_values = {ft.value for ft in filing_types}

    cik = get_cik(ticker)
    if cik is None:
        logger.warning(f"No CIK found for {ticker} — may not be SEC-registered")
        return []

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with log_fetch(logger, ticker, "edgar_filings") as ctx:
                _rate_limit()
                # Pad CIK to 10 digits for the submissions URL
                cik_padded = cik.zfill(10)
                url = SUBMISSIONS_URL.format(cik=cik_padded)
                resp = requests.get(url, headers=_headers(), timeout=15)
                resp.raise_for_status()
                data = resp.json()

                filings = _parse_submissions(ticker, cik, data, type_values, limit)
                ctx["records"] = len(filings)
                return filings

        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed for {ticker}: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"All {MAX_RETRIES} attempts failed for {ticker} filings: {e}")
                return []

    return []


def _parse_submissions(
    ticker: str,
    cik: str,
    data: dict,
    type_values: set[str],
    limit: int,
) -> list[FilingInfo]:
    """Parse the EDGAR submissions JSON into FilingInfo objects."""
    recent = data.get("filings", {}).get("recent", {})
    if not recent:
        return []

    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    report_dates = recent.get("reportDate", [])
    descriptions = recent.get("primaryDocDescription", [])

    filings = []
    for i in range(len(forms)):
        if forms[i] not in type_values:
            continue

        accession = accessions[i] if i < len(accessions) else ""
        accession_no_dashes = accession.replace("-", "")
        primary_doc = primary_docs[i] if i < len(primary_docs) else ""

        filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_doc}"

        report_date_str = report_dates[i] if i < len(report_dates) else None
        report_dt = None
        if report_date_str:
            try:
                report_dt = date.fromisoformat(report_date_str)
            except ValueError:
                pass

        try:
            filing = FilingInfo(
                ticker=ticker,
                cik=cik,
                accession_number=accession,
                filing_type=FilingType(forms[i]),
                filed_date=date.fromisoformat(dates[i]),
                report_date=report_dt,
                title=descriptions[i] if i < len(descriptions) else None,
                filing_url=filing_url,
            )
            filings.append(filing)
        except (ValueError, KeyError) as e:
            logger.warning(f"Skipped malformed filing for {ticker}: {e}")

        if len(filings) >= limit:
            break

    return filings


# --- Filing Content Extraction ---


def fetch_filing_content(filing: FilingInfo) -> Optional[FilingContent]:
    """Fetch and parse the content of a filing.

    Downloads the filing HTML/text and extracts key sections:
    - Business (Item 1, 10-K only)
    - Risk Factors (Item 1A)
    - MD&A (Item 7 for 10-K, Item 2 for 10-Q)

    Returns FilingContent or None on failure.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with log_fetch(logger, filing.ticker, f"edgar_content_{filing.filing_type.value}") as ctx:
                _rate_limit()
                resp = requests.get(filing.filing_url, headers=_headers(), timeout=30)
                resp.raise_for_status()

                raw_text = _html_to_text(resp.text)
                ctx["records"] = 1

                content = _extract_sections(
                    filing.accession_number,
                    filing.filing_type,
                    raw_text,
                )
                return content

        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.warning(f"Attempt {attempt}/{MAX_RETRIES} content fetch failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"All {MAX_RETRIES} attempts failed for content {filing.accession_number}: {e}")
                return None

    return None


def _html_to_text(html: str) -> str:
    """Convert HTML to plain text, preserving basic structure."""
    # Remove script and style blocks
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Replace block elements with newlines
    text = re.sub(r"<(?:br|p|div|tr|li|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Remove remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode HTML entities
    text = unescape(text)
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_sections(
    accession_number: str,
    filing_type: FilingType,
    text: str,
) -> FilingContent:
    """Extract key sections from filing plain text.

    Uses regex patterns to find section headers in 10-K/10-Q filings.
    Falls back gracefully — missing sections are None, not errors.
    """
    content = FilingContent(
        accession_number=accession_number,
        filing_type=filing_type,
        raw_text_length=len(text),
    )

    if filing_type == FilingType.TEN_K:
        content.business = _find_section(text, r"item\s*1[.\s]", r"item\s*1a[.\s]")
        content.risk_factors = _find_section(text, r"item\s*1a[.\s]", r"item\s*1b[.\s]")
        content.mda = _find_section(text, r"item\s*7[.\s]", r"item\s*7a[.\s]")
    elif filing_type == FilingType.TEN_Q:
        content.risk_factors = _find_section(text, r"item\s*1a[.\s]", r"item\s*2[.\s]")
        content.mda = _find_section(text, r"item\s*2[.\s]", r"item\s*3[.\s]")

    return content


def _find_section(text: str, start_pattern: str, end_pattern: str) -> Optional[str]:
    """Extract text between two section header patterns.

    Returns the text between the start and end patterns, capped at MAX_SECTION_CHARS.
    Returns None if the section can't be found.
    """
    start_match = None
    # Find the LAST occurrence of the start pattern (often repeated in TOC)
    for m in re.finditer(start_pattern, text, re.IGNORECASE):
        start_match = m

    if start_match is None:
        return None

    search_start = start_match.end()
    end_match = re.search(end_pattern, text[search_start:], re.IGNORECASE)

    if end_match:
        section = text[search_start : search_start + end_match.start()]
    else:
        # No end marker — take up to MAX_SECTION_CHARS from the start
        section = text[search_start : search_start + MAX_SECTION_CHARS]

    section = section.strip()
    if len(section) < 100:
        return None  # Too short to be a real section (probably just a header)

    return section[:MAX_SECTION_CHARS]


# --- Batch Operations ---


def update_all_filings(
    filing_types: Optional[list[FilingType]] = None,
    limit_per_ticker: int = 5,
    fetch_content: bool = True,
    db_path: Optional[str] = None,
) -> dict:
    """Fetch and store filings for all watchlist tickers.

    Args:
        filing_types: Which filing types to fetch (default: 10-K, 10-Q)
        limit_per_ticker: Max filings per ticker
        fetch_content: Whether to also download and parse filing content
        db_path: Database path override

    Returns summary dict.
    """
    db = db_path or DB_PATH

    results = {"successes": [], "failures": [], "total_filings": 0, "content_fetched": 0}

    for ticker in WATCHLIST:
        try:
            filings = fetch_filing_list(ticker, filing_types, limit=limit_per_ticker)
            if not filings:
                results["failures"].append({"ticker": ticker, "reason": "no filings found"})
                continue

            for filing in filings:
                content = None
                if fetch_content:
                    content = fetch_filing_content(filing)
                    if content and content.has_content:
                        results["content_fetched"] += 1

                upsert_filing(filing, content, db_path=db)
                results["total_filings"] += 1

            results["successes"].append({"ticker": ticker, "filings": len(filings)})
            logger.info(f"[{len(results['successes'])}/{len(WATCHLIST)}] {ticker}: {len(filings)} filings")

        except Exception as e:
            logger.error(f"Unexpected error for {ticker}: {e}")
            results["failures"].append({"ticker": ticker, "reason": str(e)})

    logger.info(
        f"Filing update complete: {len(results['successes'])} succeeded, "
        f"{len(results['failures'])} failed, {results['total_filings']} filings, "
        f"{results['content_fetched']} with content"
    )
    return results
