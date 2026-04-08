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

---

## Session 5 — Phase 3a: Fundamental Analyst Agent

### Status: COMPLETE

### Built
- `src/agents/base.py` — Extracted shared agent logic: context building (price, fundamentals, filings, news formatting), `REPORT_TOOL` schema, `run_agent()` generic pipeline, `build_standard_context_with_data()` (returns text + raw data to avoid double-fetch)
- `src/agents/fundamental.py` — Fundamental analyst agent: `_compute_derived_metrics()` (FCF yield, earnings yield, forward earnings yield, implied earnings growth, net debt, capex intensity, FCF conversion, 52-week range position, analyst upside, PEG assessment, EV/FCF), `build_fundamental_context()` (standard context + derived metrics section), `analyze_ticker()` entry point
- `src/agents/prompts/fundamental.md` — Fundamentals-first system prompt: 6-section analysis framework (Growth, Profitability, Cash Flow, Valuation, Competitive Position, Filing Insights), confidence calibration guidance, explicit fundamentals > sentiment directive
- `src/agents/analyst.py` — Refactored to delegate to `base.py`, re-exports for backward compat with existing tests, added `db_path` parameter for interface consistency
- `src/agents/runner.py` — Added `--agent` flag with `AGENT_REGISTRY` for dynamic import; supports `general` (default) and `fundamental`
- `tests/test_fundamental.py` — 28 tests: derived metrics (20 including edge cases), context building (3), model validation (2), DB round-trips (2), E2E (1, skipped without key)

### Key Decisions
- **`base.py` extraction** — Shared pipeline (`run_agent`) takes `agent_name`, `prompt_path`, and `context_builder` callable. Each specialized agent only needs to define its prompt and optionally a custom context builder.
- **`build_standard_context_with_data()`** — Returns `(text, price_history, fundamentals)` tuple so fundamental agent can access raw data for derived metric computation without re-querying DB.
- **Derived metrics enrichment** — Fundamental agent appends computed ratios (FCF yield, earnings yield, capex intensity, etc.) as a separate "Derived Financial Metrics" section. Gives the LLM richer data without modifying the shared context builder.
- **Consistent `analyze_ticker` interface** — Both `analyst.py` and `fundamental.py` accept `(ticker, save, db_path)` for interface symmetry.

### Bugs Found & Fixed During Review
1. **Double data fetch** — `build_fundamental_context` was calling `build_standard_context` (which fetches from DB) then fetching fundamentals+prices again for derived metrics. Fixed by introducing `build_standard_context_with_data()` that returns raw data alongside text.
2. **Unused imports in `fundamental.py`** — `format_fundamentals_section`, `format_price_section`, `get_stock_context`, `PriceBar` imported but unused. Cleaned up.
3. **`analyst.py` missing `db_path`** — General analyst's `analyze_ticker` lacked `db_path` parameter, breaking interface symmetry with fundamental analyst. Added for consistency.
4. **Weak test assertion** — `test_partial_data_graceful` had `assert X or len(result) > 0` which could never fail. Replaced with specific assertion.

### Deviations
- None — on track with roadmap

### Open Blockers
- None

### Testing Note
- 141 total tests pass (all sessions), 2 E2E skipped without API key
- Code reviewer flagged `key_metrics: dict[str, Optional[float]]` type may reject string values from Claude. Not fixed this session — the existing general analyst has worked fine with this constraint. Will revisit if it causes real failures.

### Next Session (Session 6 — Phase 3b)
**Scope:** Sentiment + Supply Chain Agents
- Build `src/agents/sentiment.py` — Sentiment analyst focused on news, filing tone, market sentiment
- Build `src/agents/supply_chain.py` — Supply chain analyst focused on bottleneck positioning, demand visibility, competitive moat
- Prompts for each at `src/agents/prompts/sentiment.md` and `src/agents/prompts/supply_chain.md`
- Register both in `runner.py`'s `AGENT_REGISTRY`
- Tests for both

**Files to read at session start:** `CLAUDE.md`, `PROGRESS.md`, `DESIGN.md` (sections 4, 7), `src/agents/base.py`, `src/agents/fundamental.py`, `src/agents/runner.py`, `src/data/models.py`

---

## Session 6 — Phase 3b: Sentiment + Supply Chain Agents

### Status: COMPLETE

### Built
- `src/agents/sentiment.py` — Sentiment analyst agent: `_compute_news_metrics()` (volume, recency distribution, source diversity, volume interpretation), `build_sentiment_context()` (standard context + price momentum + news metrics), `analyze_ticker()` entry point
- `src/agents/prompts/sentiment.md` — Sentiment-first system prompt: 5-section analysis framework (News Flow, Filing Language & Management Tone, Market Narrative & Positioning, Sentiment Inflection Detection, Risk Sentiment), confidence calibration, sentiment != fundamentals directive
- `src/agents/supply_chain.py` — Supply chain analyst agent: `_build_layer_context()` (tier, layer, peer identification from WATCHLIST), `_compute_supply_chain_metrics()` (capex intensity, gross margin as pricing power proxy, revenue growth as demand signal, FCF margin, leverage capacity), `build_supply_chain_context()` (standard context + layer position + supply chain metrics), `analyze_ticker()` entry point
- `src/agents/prompts/supply_chain.md` — Supply chain positioning system prompt: 6-section analysis framework (Bottleneck Assessment, Demand Visibility, Competitive Moat Durability, Capex & Capacity Analysis, Supply Chain Risk Factors, Cross-Layer Dependencies), AI supply chain layer map, position > price directive
- `src/agents/runner.py` — Added `sentiment` and `supply_chain` to `AGENT_REGISTRY`
- `tests/test_sentiment.py` — 17 tests: news metrics (6), context building (6 including boundary cases for 5/3 price bars), report model (2), DB round-trips (2), E2E (1, skipped without key)
- `tests/test_supply_chain.py` — 25 tests: layer context (6), supply chain metrics (12 including edge cases), context building (4), report model (2), DB round-trips (2), E2E (1, skipped without key)

### Key Decisions
- **Sentiment context enrichment** — News volume metrics (30d/7d/3d counts), recency, source diversity, and volume interpretation labels (SURGING/MODERATE/QUIET/NONE) give the LLM structured sentiment signals beyond raw article text.
- **Supply chain layer context** — Injects portfolio tier, layer position, and same-layer peer names directly into context. LLM can compare the stock's position relative to peers without needing separate data.
- **Supply chain metrics with interpretive labels** — Capex intensity, gross margin, revenue growth, and leverage each include threshold-based labels (e.g., "Heavy capacity investment", "Strong pricing power"). Guides the LLM's interpretation without prescribing conclusions.
- **Price momentum in sentiment context** — 5d/20d momentum added as a cross-reference for the sentiment agent. Lets it flag sentiment-price divergences.
- **Same `run_agent()` pipeline** — Both new agents plug into the existing shared pipeline. No changes to `base.py` or `models.py` needed.

### Bugs Found & Fixed During Review
1. **No bugs in source code** — Code reviewer confirmed all context builder signatures match `Callable[[str, Optional[str]], str]`, all guards against IndexError/division-by-zero are in place.
2. **Added boundary tests** — Test reviewer flagged missing coverage for exactly 5 price bars and fewer than 5 bars in sentiment momentum. Added `test_context_with_exactly_5_bars` and `test_context_with_fewer_than_5_bars` — both pass, confirming guards work.

### Review Notes (not fixed, acceptable)
- Hardcoded tier labels in `supply_chain.py` — consistent with existing pattern, not worth extracting to config at this stage
- Prompt path existence not validated at import time — same as fundamental agent; `run_agent()` will raise clear FileNotFoundError if path is wrong

### Deviations
- None — on track with roadmap

### Open Blockers
- None

### Testing Note
- 183 total tests pass (all sessions), 4 E2E skipped without API key
- All 3 analyst agents (fundamental, sentiment, supply chain) now follow the same pattern and share the same pipeline

### Next Session (Session 7 — Phase 3c)
**Scope:** Synthesizer + LangGraph Orchestration
- Build `src/agents/synthesizer.py` — Research Synthesizer that reads all 3 analyst reports and produces unified memo
- Build `src/orchestrator/graph.py` — LangGraph wiring to run analysts in parallel, then synthesize
- New Pydantic model for unified synthesis report (per DESIGN.md Section 4.2)
- Tests for synthesizer + orchestration

**Files to read at session start:** `CLAUDE.md`, `PROGRESS.md`, `DESIGN.md` (sections 4, 7), `src/agents/base.py`, `src/agents/runner.py`, `src/data/models.py`, `src/agents/fundamental.py` (pattern reference)

---

## Session 7 — Phase 3c: Synthesizer + LangGraph Orchestration

### Status: COMPLETE

### Built
- `src/data/models.py` — Added `SynthesisReport` Pydantic model: overall_signal, overall_confidence, analyst_agreement, disagreement_flags, bull/bear case summaries, recommendation, thesis_changed_since_last, key_watch_items, analyst_reports_used
- `src/agents/synthesizer.py` — Research Synthesizer agent: `SYNTHESIS_TOOL` schema, `build_synthesis_context()` (formats analyst reports for Claude), `_load_analyst_reports_from_db()` (loads latest report per analyst), `run_synthesizer()` (Claude Opus API call), `analyze_ticker()` (standalone entry point)
- `src/agents/prompts/synthesizer.md` — Synthesizer system prompt: 5-section analysis framework (Signal Synthesis, Bull Case, Bear Case, Recommendation, Key Watch Items), confidence calibration, fundamentals > sentiment weighting directive
- `src/orchestrator/graph.py` — LangGraph StateGraph: `OrchestratorState` (Pydantic model with `Annotated[list, operator.add]` reducers), 3 analyst nodes running in parallel via fan-out edges, synthesizer fan-in node, `build_graph()` compiler, `orchestrate()` entry point
- `src/agents/runner.py` — Added `synthesizer` to `AGENT_REGISTRY`, added `--orchestrate` flag with `run_orchestrated()` (single ticker) and `run_all_orchestrated()` (all tickers)
- `tests/test_synthesizer.py` — 33 tests: model validation (11 including boundary), context building (8), DB round-trips (5 including corrupted JSON), tool schema (2), orchestrator (7 including partial failure, full failure, synthesizer failure), E2E (1, skipped without key)

### Key Decisions
- **Claude Opus for synthesizer** — Per DESIGN.md Section 4.4: harder reasoning task (weighing conflicting signals) warrants the stronger model. Config: `SYNTHESIZER_MODEL = "claude-opus-4-6"`
- **Separate SYNTHESIS_TOOL schema** — Different from analyst REPORT_TOOL. Synthesizer output has different fields (analyst_agreement, disagreement_flags, recommendation text, etc.)
- **`analyst_reports_used` is computed, not from Claude** — Populated from input reports, not in tool schema. Gives downstream consumers a way to detect degraded synthesis (1-2 of 3 analysts).
- **Graceful degradation** — Orchestrator proceeds with 1-2 analyst reports if one fails. Synthesizer prompt handles partial data. Zero reports → no synthesis attempted.
- **Reuse `analysis_reports` table** — Synthesis reports saved with `agent_name="research_synthesizer"`, same table as analyst reports. No schema migration needed.
- **LangGraph StateGraph with Pydantic** — `OrchestratorState` uses `Annotated[list, operator.add]` for accumulating analyst reports from parallel nodes.

### Bugs Found & Fixed During Review
1. **`key_watch_items` validator vs tool schema mismatch** — Pydantic model required non-empty list, but tool schema didn't enforce it. Claude could return empty array → validation failure. Fixed by adding `minItems: 1` to tool schema.
2. **Fragile state reconstruction from LangGraph** — `OrchestratorState(**result)` could fail if LangGraph adds internal keys. Fixed by filtering to known fields before construction.

### Review Notes (not fixed, acceptable)
- `analyst_reports_used` not in tool schema — by design, computed from input reports
- Synthesizer runs with partial data (1-2 of 3 analysts) — acceptable, field `analyst_reports_used` documents coverage
- Prompt path not validated at import time — same pattern as all other agents
- No timeout on individual analyst nodes — LangGraph doesn't natively support per-node timeouts; API call timeout is the effective bound

### Deviations
- None — on track with roadmap

### Open Blockers
- None

### Testing Note
- 216 total tests pass (all sessions), 5 E2E skipped without API key
- All 4 agents (fundamental, sentiment, supply chain, synthesizer) + orchestrator tested
- Orchestrator tests use mocked API calls to verify graph wiring and state management

### Next Session (Session 8 — Phase 4)
**Scope:** Risk Manager
- Build `src/agents/risk_manager.py` — Portfolio-level risk analysis agent
- Produces portfolio risk report per DESIGN.md Section 4.2 (sector exposure, concentration warnings, correlation flags, position sizing)
- Reads all latest synthesis reports across the watchlist
- Tests for risk manager

**Files to read at session start:** `CLAUDE.md`, `PROGRESS.md`, `DESIGN.md` (sections 4, 7), `src/agents/synthesizer.py`, `src/orchestrator/graph.py`, `src/data/models.py`, `src/config.py`

---

## Session 8 — Phase 4: Risk Manager

### Status: COMPLETE

### Built
- `src/data/models.py` — Added `RiskLevel` enum and `PortfolioRiskReport` Pydantic model: overall_risk_level, risk_summary, sector_exposure (validated 0-1), concentration_warnings, correlation_flags, position_sizing, recommendations (non-empty), portfolio_signals, tickers_analyzed
- `src/agents/risk_manager.py` — Risk manager agent: `LAYER_GROUPS` (maps stock layers to sector groups), `RISK_TOOL` schema, `_ensure_portfolio_stock()` (FK compliance for PORTFOLIO ticker), `_load_all_synthesis_reports()` (loads latest synthesis per watchlist ticker), `compute_portfolio_metrics()` (sector exposure, signal distribution, same-layer pairs, coverage tracking), `build_risk_context()` (formats reports + metrics for Claude), `run_risk_manager()` (Claude Sonnet API call), `analyze_portfolio()` (entry point)
- `src/agents/prompts/risk_manager.md` — Risk manager system prompt: 5-section framework (Sector/Layer Exposure, Concentration Risk, Correlation Assessment, Position Sizing, Portfolio-Level Risk Actions), risk level calibration
- `src/agents/runner.py` — Added `risk_manager` to `AGENT_REGISTRY`, added `--risk` CLI flag with `run_risk()` (pretty-prints sector exposure, warnings, correlations, position sizing, recommendations)
- `tests/test_risk_manager.py` — 36 tests: model validation (12), portfolio metrics (10 including all-same-signal), context building (5), tool schema (2), DB round-trips (7 including load/skip-invalid/no-reports-error), E2E (1, skipped without key)

### Key Decisions
- **Claude Sonnet for risk manager** — Per DESIGN.md Section 4.4: rule-based + analytical task, doesn't need Opus
- **"neutral" signal in DB** — The `analysis_reports` table has a CHECK constraint limiting signal to bullish/bearish/neutral. Risk reports store their actual risk level in the JSON report; the signal column uses "neutral" as a placeholder
- **Synthetic PORTFOLIO stock entry** — FK constraint on `analysis_reports.ticker` requires a matching `stocks` row. `_ensure_portfolio_stock()` inserts an idempotent watch-only PORTFOLIO row
- **LAYER_GROUPS mapping** — Maps individual stock layers (e.g., "Foundry/Packaging", "Equipment (EUV)") to sector groups (e.g., "Semiconductor") for exposure calculation. This is the portfolio-level abstraction layer
- **Equal-weight assumption** — Sector exposure computed assuming equal allocation across active positions. Actual portfolio weights would require position data (future enhancement)
- **portfolio_signals and tickers_analyzed computed in Python** — Not from Claude's tool output. Gives deterministic data from input reports

### Bugs Found & Fixed During Review
1. **DB CHECK constraint on signal column** — `save_report()` with signal="moderate" (risk level) violates `CHECK (signal IN ('bullish', 'bearish', 'neutral'))`. Fixed by using "neutral" as placeholder signal for risk reports.
2. **DB FOREIGN KEY on ticker** — `save_report(ticker="PORTFOLIO")` violates FK to `stocks(ticker)` since PORTFOLIO doesn't exist. Fixed by adding `_ensure_portfolio_stock()` that creates a synthetic row.
3. **Test ordering assumption** — `test_multiple_risk_reports_latest_first` assumed insertion order = retrieval order for same-date reports. Fixed by testing both reports exist rather than ordering.

### Review Notes (not fixed, acceptable)
- No try-except on `client.messages.create()` — same pattern as all other agents; API errors propagate to runner which calls sys.exit(1)
- `position_sizing` inner dict not validated in Pydantic — Claude's tool schema already constrains max_allocation to [0, 0.15] and requires both keys; duplicating in Pydantic would be redundant
- `portfolio_signals` / `tickers_analyzed` not cross-validated — both computed from the same input list, so they can't diverge

### Deviations
- None — on track with roadmap

### Open Blockers
- None

### Testing Note
- 252 total tests pass (all sessions), 6 E2E skipped without API key
- All 5 agents (fundamental, sentiment, supply chain, synthesizer, risk manager) + orchestrator tested

### Next Session (Session 9 — Phase 5a)
**Scope:** Dashboard: Layout
- Build `src/dashboard/app.py` — Streamlit dashboard
- Portfolio overview page: signal summary table, sector exposure chart
- Stock cards: per-ticker view with latest signals, key metrics, recommendations
- Read from DB (latest reports, synthesis, risk assessment)

**Files to read at session start:** `CLAUDE.md`, `PROGRESS.md`, `DESIGN.md` (sections 4, 7, 9), `src/data/models.py`, `src/db/operations.py`, `src/config.py`

---

## Session 9 — Phase 5a: Dashboard Layout

### Status: COMPLETE

### Built
- `src/dashboard/data_loader.py` — Data loading helpers for Streamlit: `load_portfolio_summary()` (latest synthesis per ticker), `load_ticker_detail()` (synthesis + analysts + price for one ticker), `load_risk_report()` (latest portfolio risk), `get_signal_color()`, `get_risk_color()` color mappers
- `src/dashboard/app.py` — Streamlit dashboard with two views:
  - **Portfolio Overview:** signal summary table (active + watch-only), signal distribution metrics (bullish/neutral/bearish counts), risk report card (risk level, summary, sector exposure bar chart, concentration warnings, correlation flags, position sizing table, recommendations)
  - **Stock Detail:** price metrics (latest close, 52W high/low, range position), synthesis signal card (signal, confidence, agreement), recommendation, bull/bear case columns, thesis change alert, disagreement flags, watch items, analyst report expanders (each with thesis, bull/bear, risks, key metrics)
- `tests/test_dashboard.py` — 26 tests: portfolio summary (6), ticker detail (8 including price data), risk report (5), corrupted data handling (4), color helpers (3)

### Key Decisions
- **Read-only dashboard** — No writes to DB from the dashboard. All data loaded via `get_reports()` and `get_prices()` from `operations.py`
- **Data loader as separate module** — `data_loader.py` handles DB → display-ready dict conversion. Keeps `app.py` focused on layout. Testable independently without Streamlit.
- **Dict-based return types** — Data loader returns plain dicts (not Pydantic models) since the data comes from `report_json` blobs. Avoids double-validation overhead.
- **Graceful degradation** — Empty DB shows "No data" messages with CLI commands to populate. Missing reports for some tickers show partial data. Missing fields in JSON use `.get()` defaults.
- **No caching yet** — Deferred to Session 10 when interactivity adds frequent reruns. Current page loads are fast (single DB read per view, ~11 tickers).

### Bugs Found & Fixed During Review
1. **Unused imports in data_loader.py** — `json`, `AnalysisReport`, `Signal`, `SynthesisReport`, `PortfolioRiskReport`, `RiskLevel`, `get_connection`, `get_stocks`, `init_db` imported but unused. Cleaned up.
2. **Variable `f` shadowing built-in** — `for f in risk["correlation_flags"]` in app.py. Renamed to `flag`.
3. **Dead `signal_badge`/`risk_badge` helpers** — Defined in app.py but never called. Removed.
4. **Test: corrupted JSON test was a no-op** — Original test caught `JSONDecodeError` and passed silently. Rewritten to use `pytest.raises(json.JSONDecodeError)` to assert the specific behavior.
5. **Test: latest-report test accepted any answer** — Both reports had same date, assertion accepted either signal. Fixed by using different dates to make ordering deterministic.

### Review Notes (not fixed, acceptable)
- `get_reports()` returns raw string signals, not `Signal` enum — consistent with existing pattern, validation happens at write time
- No `@st.cache_data` — deferred to Session 10 when interactive widgets make caching worthwhile
- `init_db()` runs on every Streamlit rerender — idempotent, negligible cost

### Deviations
- None — on track with roadmap

### Open Blockers
- None

### Testing Note
- 278 total tests pass (all sessions), 6 E2E skipped without API key
- 26 new dashboard tests covering data loader functions, edge cases, corrupted data

### Next Session (Session 10 — Phase 5b)
**Scope:** Dashboard: Interactivity
- Add `@st.cache_data` for performance on repeated reruns
- Signal history / trend view (show signal changes over time)
- Action buttons (trigger analysis run from dashboard)
- Drill-downs and filtering
- Refresh button to reload data

**Files to read at session start:** `CLAUDE.md`, `PROGRESS.md`, `DESIGN.md` (sections 4, 7, 9), `src/dashboard/app.py`, `src/dashboard/data_loader.py`, `src/db/operations.py`

---

## Session 10 — Phase 5b: Dashboard Interactivity

### Status: COMPLETE

### Built
- `src/dashboard/data_loader.py` — Added `@st.cache_data(ttl=300)` to all loader functions, added `load_signal_history()` (per-ticker signal history, chronological order) and `load_all_signal_history()` (cross-portfolio signal history)
- `src/dashboard/app.py` — Full interactivity overhaul:
  - **Caching:** All data loaders cached with 5-min TTL
  - **Refresh button:** Sidebar button clears `st.cache_data` and reruns
  - **Filters:** Sidebar signal filter (bullish/neutral/bearish/no data) and tier filter (Tier 1/Tier 2/Watch Only) on Portfolio Overview
  - **Signal history (Portfolio):** Line chart of confidence over time across all tickers, plus signal change log table
  - **Signal trend (Stock Detail):** Per-ticker signal timeline table + confidence trend chart
  - **Action buttons:** "Run Full Analysis" and "Run Risk Analysis" on Portfolio Overview, "Run Analysis for {ticker}" on Stock Detail — all via `subprocess.run()` with spinner, output capture, and error display
- `tests/test_dashboard.py` — 40 tests (up from 26): added signal history tests (6), all-signal history tests (5), corrupted signal history test (1), price exception test (1), chronological ordering with limit test (1)

### Key Decisions
- **`@st.cache_data(ttl=300)`** — 5-minute TTL balances freshness with performance. Refresh button provides manual override.
- **Subprocess for action buttons** — `subprocess.run()` with list args (no shell=True), 600s timeout, captured output. Args are hardcoded from WATCHLIST, not user input.
- **Signal distribution uses unfiltered data** — Metric counts (bullish/neutral/bearish) always show the full portfolio, not filtered subset, so users can see the overall picture while filtering the table.
- **`load_all_signal_history` delegates to `load_signal_history`** — Reuses the per-ticker function to avoid duplicating logic. Both cached independently.

### Bugs Found & Fixed During Review
1. **Analyst signal None crash** — `analyst['signal'].upper()` in expander title would crash if signal was None. Fixed by adding None guard with fallback to "—".
2. **Unused `get_signal_color` import** — Imported in app.py but never used. Removed.
3. **`AttributeError` not caught in signal history** — Corrupted report with JSON array (instead of object) raised `AttributeError` on `.get()`. Added to exception tuple.

### Review Notes (not fixed, acceptable)
- `get_risk_color` defined in data_loader.py but not currently used in app.py — kept for potential future use (e.g., colored badges)
- Signal distribution metrics show unfiltered counts by design — matches the "at a glance" purpose
- No integration test for subprocess execution — would require mocking the full agent pipeline

### Deviations
- None — on track with roadmap

### Open Blockers
- None

### Testing Note
- 292 total tests pass (all sessions), 6 E2E skipped without API key
- 40 dashboard tests covering data loaders, signal history, corrupted data, edge cases

### Next Session (Session 11 — Phase 6)
**Scope:** Automation & Alerts
- Build scheduler (APScheduler) for automated weekly analysis runs
- Thesis-change alerts (detect when synthesis signal flips)
- Earnings calendar integration
- Notification mechanism (e.g., email or log-based alerts)

**Files to read at session start:** `CLAUDE.md`, `PROGRESS.md`, `DESIGN.md` (sections 4, 7, 10), `src/agents/runner.py`, `src/data/models.py`, `src/dashboard/data_loader.py`

---

## Session 11 — Phase 6: Automation & Alerts

### Status: COMPLETE

### Built
- `src/data/models.py` — Added `AlertType` enum (signal_change, thesis_change, earnings_approaching, run_completed, run_failed), `AlertSeverity` enum (info, warning, critical), `AlertRecord` model (ticker, type, severity, title, detail, created_at, acknowledged), `EarningsEvent` model (ticker, earnings_date, estimate_eps)
- `src/db/schema.py` — Added `alerts` table (with date index) and `earnings_calendar` table (with unique ticker+date index)
- `src/db/operations.py` — Added `save_alert()`, `get_alerts()` (with unacknowledged filter), `alert_exists_today()` (dedup check), `upsert_earnings()`, `get_upcoming_earnings()` (date-windowed query)
- `src/config.py` — Added scheduler config (day, hour, minute), `EARNINGS_ALERT_DAYS`, `ALERT_LOG_PATH`, SMTP settings (all env-driven, email disabled by default)
- `src/automation/__init__.py` — Package init
- `src/automation/__main__.py` — Entry point for `python -m src.automation`
- `src/automation/earnings.py` — `_fetch_earnings_date()` (yfinance .calendar with dict/DataFrame format handling), `refresh_earnings_calendar()` (all tickers with 0.5s throttle)
- `src/automation/alerts.py` — `detect_signal_changes()` (compares latest 2 synthesis reports per ticker, CRITICAL for bearish flips), `detect_thesis_changes()` (reads thesis_changed_since_last flag), `detect_earnings_alerts()` (upcoming earnings within alert window), `detect_and_fire_alerts()` (coordinator with same-day dedup)
- `src/automation/notifier.py` — `notify()` dispatches to structured log file (always on) + optional SMTP email (off by default). Email failure never crashes the caller.
- `src/automation/scheduler.py` — `scheduled_run()` (orchestrate → risk → earnings → alerts → notify), `start_scheduler()` (BlockingScheduler with CronTrigger), CLI with `--run-now` flag
- `src/dashboard/data_loader.py` — Added `load_alerts()` and `load_earnings_calendar()` (both cached)
- `src/dashboard/app.py` — Added Recent Alerts section, Upcoming Earnings section, schedule status in sidebar (schedule display + last run timestamp)
- `tests/test_automation.py` — 38 tests: models (6), alert DB ops (5), earnings DB ops (4), signal change detection (5), thesis change detection (3), earnings alerts (2), dedup (1), earnings fetcher (5), notifier (4), scheduler pipeline (3)

### Key Decisions
- **Standalone scheduler process** — Runs separately from Streamlit, communicates via shared SQLite DB. `python -m src.automation.scheduler` blocks with APScheduler; `--run-now` runs once and exits.
- **Direct function calls** — Scheduler calls `run_all_orchestrated()` and `run_risk()` directly (Python imports, not subprocess). Catches `SystemExit` since runner functions call `sys.exit(1)` on failure.
- **Alert dedup via `alert_exists_today()`** — Same (ticker, alert_type, title) within the same day prevents duplicate alerts on re-runs.
- **Severity escalation** — Signal changes involving bearish = CRITICAL. Neutral transitions = WARNING. Thesis changes = WARNING. Earnings/run status = INFO.
- **Email off by default** — `SMTP_ENABLED=false`. Alert log file is the primary notification channel for a solo user.
- **All config env-driven** — Schedule timing, alert window, SMTP settings all configurable via environment variables without code changes.

### Bugs Found & Fixed During Review
1. **`sys.exit(1)` kills scheduler** — `run_risk()` and `run_all_orchestrated()` in `runner.py` call `sys.exit(1)` on failure, which is `SystemExit` (not `Exception`). Scheduler's `try/except Exception` wouldn't catch it. Fixed by wrapping both calls in `try/except SystemExit`.
2. **Operator precedence ambiguity** — `if cal is None or cal.empty if hasattr(cal, "empty") else not cal` parsed correctly but was unreadable. Added explicit parentheses.
3. **Tests depended on real WATCHLIST config** — Alert detection tests relied on "TSM" being in the actual config. Mocked `WATCHLIST` and `WATCH_ONLY` in all detection tests for isolation.
4. **No earnings fetcher tests** — `earnings.py` had zero coverage. Added 5 tests with mocked yfinance.

### Review Notes (not fixed, acceptable)
- `start_scheduler()` not directly tested — APScheduler internals are their responsibility; we test the `scheduled_run()` pipeline
- SMTP only supports port 587 (STARTTLS) — port 465 (implicit SSL) would need `SMTP_SSL()`. Acceptable for an opt-in feature.
- `run_all_orchestrated` and `run_risk` don't accept `db_path` — they always use global `DB_PATH`. Scheduler's `db_path` parameter only affects earnings/alerts. Acceptable; would need runner refactor to change.

### Deviations
- None — on track with roadmap

### Open Blockers
- None

### Testing Note
- 330 total tests pass (all sessions), 6 E2E skipped without API key
- 38 new automation tests covering models, DB ops, detection logic, dedup, earnings fetcher, notifier, scheduler pipeline

### Next Session (Session 12 — Integration & Polish)
**Scope:** End-to-end testing, edge cases, README
- Full pipeline E2E test (fetch data → orchestrate → risk → alerts → dashboard)
- Edge case hardening across all modules
- README with setup instructions, usage examples, architecture diagram
- Any polish or cleanup from previous sessions

**Files to read at session start:** `CLAUDE.md`, `PROGRESS.md`, `DESIGN.md`, all `src/` modules for integration review
