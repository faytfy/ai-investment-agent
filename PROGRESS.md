# Progress Log

## Session 1 — Phase 0: Design & Setup (2026-04-02)

### Completed
- Created GitHub repo: `faytfy/ai-investment-agent`
- Wrote `DESIGN.md` — full architecture document covering:
  - Investment profile (fundamental, position trading, 8-10 stocks)
  - Watchlist (9 active + 2 watch-only)
  - Multi-agent architecture (3 analysts → synthesizer → risk manager → dashboard)
  - Structured report format (JSON schemas for each agent)
  - Tech stack (Python, LangGraph, Claude API, yfinance, SQLite, Streamlit)
  - 12-session phased roadmap
  - Session opening/closing protocol
- Wrote `CLAUDE.md` — session start instructions
- Wrote `PROGRESS.md` — this file
- Set up project structure (`src/`, `tests/`, `data/`)
- Created `requirements.txt` with all dependencies
- Created `.env.example` with API key template
- Created `.gitignore`
- Created `src/config.py` with watchlist, model settings, constants
- Completed AI supply chain research → `AI_Supply_Chain_Investment_Report.md`
- Completed multi-agent architecture research (findings in DESIGN.md)

### Not Completed
- Nothing deferred — Phase 0 is complete

### Blockers
- None

### Open Decisions
- None — all Phase 0 decisions are locked in

### Next Session (Session 2 — Phase 1a)
**Scope:** Data Pipeline — Price & Fundamentals

Build:
1. `src/db/schema.py` — SQLite schema (stocks, prices, fundamentals, analysis_reports)
2. `src/db/operations.py` — DB read/write operations
3. `src/data/models.py` — Pydantic data models
4. `src/data/price.py` — yfinance integration (historical prices, current quotes)
5. `src/data/fundamentals.py` — yfinance fundamentals (financials, ratios, analyst targets)
6. `tests/test_data.py` — tests for data pipeline

**Files to read at session start:** `CLAUDE.md`, `PROGRESS.md`, `DESIGN.md` (sections 4-5), `src/config.py`

### Deviations from Original Plan
- None — on track

---

## Session 2 — Phase 1a: Data Pipeline (Price & Fundamentals)

### Status: COMPLETE

### Built
- `src/utils/logger.py` — structured logging with timed fetch context manager
- `src/data/models.py` — Pydantic models (StockInfo, PriceBar, PriceHistory, FundamentalsSnapshot) with validators
- `src/db/schema.py` — SQLite schema (stocks, prices, fundamentals, analysis_reports)
- `src/db/operations.py` — full CRUD: init_db, upsert/get prices, upsert/get fundamentals, save/get reports
- `src/data/price.py` — yfinance price fetcher with retry, per-ticker isolation, validation
- `src/data/fundamentals.py` — yfinance fundamentals fetcher with retry, per-ticker isolation
- `tests/test_data.py` — 36 tests (model validation, DB round-trips, edge cases, yfinance integration)

### Key Decisions
- JSON blob for fundamentals in DB (yfinance fields vary by ticker)
- tier=0 for watch-only stocks (allows StockInfo to represent all stocks)
- All functions return Pydantic models at boundaries, not raw dicts
- Integration tests hit real yfinance (no mocks)

### Deviations
- Added `src/utils/` directory (not in original DESIGN.md structure) for logger
- Post-coding review process caught 3 critical bugs (tier mismatch, watch-only filter logic, redundant imports) — all fixed before commit

### Open Blockers
- None

### Next Session (Session 3 — Phase 1b)
**Scope:** Data Pipeline — SEC EDGAR + News
- `src/data/edgar.py` — SEC EDGAR filing parser
- `src/data/news.py` — News/RSS integration
- Tests for both

**Files to read at session start:** `CLAUDE.md`, `PROGRESS.md`, `DESIGN.md` (sections 4-6), `src/data/models.py`, `src/config.py`

---

## Session 3 — Phase 1b: Data Pipeline (SEC EDGAR + News)

### Status: COMPLETE

### Built
- `src/data/models.py` — Added `FilingType` enum, `FilingInfo`, `FilingContent`, `NewsArticle`, `NewsFeed` Pydantic models
- `src/db/schema.py` — Added `filings` table (with accession_number unique constraint, content_json) and `news_articles` table (with dedup index on ticker+title+published_at)
- `src/db/operations.py` — Added `upsert_filing`, `get_filings`, `get_filing_content`, `upsert_news`, `get_news` operations
- `src/data/edgar.py` — SEC EDGAR fetcher: CIK lookup (cached), filing list from submissions API, filing content extraction (HTML→text, section parsing for Items 1/1A/7)
- `src/data/news.py` — RSS news fetcher: Yahoo Finance + Google News RSS, date parsing, HTML cleaning, deduplication
- `tests/test_edgar_news.py` — 55 tests (model validation, DB round-trips, HTML parsing, RSS parsing, section extraction, integration tests against real EDGAR + RSS)

### Key Decisions
- Filing content stored as JSON blob (same pattern as fundamentals)
- Section extraction uses regex on plain text (best-effort; some filings have non-standard formatting)
- All news dates normalized to naive datetimes (no timezone mixing)
- `upsert_filing` preserves existing content when re-upserting without content (prevents data loss on failed re-fetch)
- CIK cache loaded once per process with retry storm prevention
- RSS-only for news (free, no API keys needed); sentiment scoring deferred to Sentiment Agent (Session 6)

### Bugs Found & Fixed During Review
1. `upsert_news` count bug — was using cumulative `conn.total_changes` instead of per-row `cursor.rowcount`
2. Timezone mixing — `parsedate_to_datetime` returns tz-aware, `datetime.now()` is naive; fixed by stripping tzinfo
3. Content data loss — `INSERT OR REPLACE` would overwrite existing content_json with NULL; fixed with check-then-update logic
4. CIK retry storm — empty cache caused repeated full-download attempts; fixed with `_cik_cache_loaded` flag

### Deviations
- None — on track with roadmap

### Open Blockers
- None

### Testing Debt
- **No E2E tests yet.** Unit + integration tests cover individual functions and DB round-trips, but the batch orchestrators (`update_all_filings`, `update_all_news`, `update_all_prices`) have no coverage. When the single agent MVP ties the full pipeline together (Session 4+), add E2E tests that run: fetch data → store in DB → agent reads from DB → produces report. This is the right time because E2E tests need a downstream consumer to be meaningful.

### Next Session (Session 4 — Phase 2)
**Scope:** Single Agent MVP
- Build a single Claude agent that reads price, fundamentals, and filing data
- Produces structured buy/sell/hold reports (JSON)
- Agent system prompt + report format
- Tests for agent output validation
- **E2E test:** Full pipeline for 1 ticker (fetch → store → agent reads → report) — addresses testing debt from Sessions 2-3

**Files to read at session start:** `CLAUDE.md`, `PROGRESS.md`, `DESIGN.md` (sections 4, 7), `src/data/models.py`, `src/config.py`, `src/db/operations.py`

---

## Session 4 — Phase 2: Single Agent MVP

### Status: COMPLETE

### Built
- `src/data/models.py` — Added `Signal` enum, `AnalysisReport` Pydantic model with field validation (signal, confidence bounds, non-empty text/list validators)
- `src/agents/prompts/analyst.md` — System prompt for the general analyst (analysis framework, output rules, guidelines)
- `src/agents/analyst.py` — Full agent logic: data gathering from DB, context assembly (price/fundamentals/filings/news), Claude API call with tool_use for structured output, report validation and saving
- `src/agents/runner.py` — CLI runner (`python -m src.agents.runner TSM` or `--all`) with pretty-print output and summary table
- `tests/test_agent.py` — 22 tests: model validation (13), context building (6), DB round-trips (2), E2E with real API (1, skipped without key)

### Key Decisions
- **Tool_use for structured output** — Forces Claude to return JSON matching our schema, instead of hoping for valid JSON in free-form text
- **Anthropic SDK directly** (not LangGraph) — Single agent, one API call; LangGraph orchestration deferred to Phase 3c
- **Context assembled in Python** — All data pre-fetched from DB and formatted as text, not live tool calls during analysis
- **`report_date` field name** — Renamed from `date` to avoid Pydantic clash with the `date` type import
- **db_path threading** — All data fetchers accept optional db_path for testability

### Bugs Found & Fixed During Review
1. **db_path not threaded to filings/news** — `build_context()` only passed db_path to prices/fundamentals, not filings/news; fixed by threading kwargs through all formatters
2. **No error handling on malformed Claude response** — Direct dict access to tool output would crash on missing keys; wrapped in try/except with logging
3. **`date` field name clash** — Pydantic errored because `date: date` shadowed the type import; renamed to `report_date`

### Deviations
- None — on track with roadmap

### Open Blockers
- None

### Testing Note
- E2E test (`TestE2EAnalysis`) is in place but skipped without `ANTHROPIC_API_KEY` in environment. To run: `ANTHROPIC_API_KEY=sk-... python -m pytest tests/test_agent.py -k "E2E" -v`
- Batch orchestrator E2E tests (testing debt from Sessions 2-3) still deferred — the E2E test here covers the agent path but not the data fetch → store → agent pipeline. Best addressed when the full multi-agent pipeline exists (Session 7).

### Next Session (Session 5 — Phase 3a)
**Scope:** Fundamental Analyst Agent
- Refactor `general_analyst` into a dedicated `fundamental_analyst` with deeper financial analysis
- Standalone agent with structured report matching DESIGN.md Section 4.2
- Prompt tuned for financial ratios, DCF, valuation comparisons
- Tests for fundamental-specific analysis quality

**Files to read at session start:** `CLAUDE.md`, `PROGRESS.md`, `DESIGN.md` (sections 4, 7), `src/agents/analyst.py`, `src/agents/prompts/analyst.md`, `src/data/models.py`
