# AI Investment Agent — Design Document

**Project:** Autonomous AI Supply Chain Investment Analysis Agent
**Owner:** Fay
**Created:** 2026-04-02
**Status:** Phase 0 — Design & Setup

---

## 1. Overview

A multi-agent system that analyzes AI supply chain stocks and produces structured buy/sell/hold recommendations. The system is designed for **fundamental-driven position trading** (months-long holds, occasional swing trades) on a focused portfolio of 8-10 stocks.

**Key principle:** Agent recommends, human decides.

---

## 2. Investment Profile

| Parameter | Value |
|---|---|
| Strategy | Fundamental-driven, long positions |
| Horizon | Position trading (months), occasional swing (weeks) |
| Portfolio size | 8-10 focused AI supply chain stocks |
| Automation | Agent recommends with evidence; user makes final decision |
| Data budget | Free tier to start; upgrade path documented |
| Risk tolerance | Moderate — no leverage, no options |

---

## 3. Watchlist

### Tier 1 — Structural Bottleneck Owners (highest conviction)

| Ticker | Layer | Thesis |
|---|---|---|
| TSM | Foundry/Packaging | Irreplaceable. CoWoS packaging monopoly, demand 3x supply through 2026+ |
| AVGO | Custom ASIC + Networking | Dual engine: designs ASICs for Google/Meta/OpenAI + networking silicon |
| ASML | Equipment | EUV lithography monopoly. No alternative on Earth |
| GEV | Power/Grid | $2B+ DC orders, 3x growth. Grid infrastructure backbone |
| ETN | Power/Transformers | 11-year backlog. Transformer shortage = massive pricing power |

### Tier 2 — Strong Moat + Demand Visibility

| Ticker | Layer | Thesis |
|---|---|---|
| VRT | Cooling | Liquid cooling revenue doubling. 40% CAGR through 2028 |
| MU | Memory (HBM) | Only U.S.-based HBM producer. $8B run-rate. Strategic asset |
| CEG | Nuclear Power | Largest U.S. nuclear fleet. 20-year hyperscaler contracts |
| ANET | Networking | AI networking revenue doubling. Surpassed Cisco |

### Watch Only (not yet buy)

| Ticker | Layer | Notes |
|---|---|---|
| NVDA | GPU | Dominant but priced for perfection; best on dips |
| PLTR | AI Software | 112x P/S is dangerous for position trading |

---

## 4. Architecture

### 4.1 System Overview

```
  ┌─────────────── DATA LAYER (free APIs) ────────────────┐
  │  Yahoo Finance  |  SEC EDGAR  |  News RSS/APIs        │
  └────────┬──────────────┬──────────────┬────────────────┘
           │              │              │
    Fundamental      Sentiment      Supply Chain
     Analyst          Analyst         Analyst
   (financials,    (news, earnings  (bottlenecks,
    ratios, DCF)    call tone)      capex, tariffs)
           │              │              │
           └──────────┬───┘──────────────┘
                      │
              Research Synthesizer
            (bull vs bear case,
             agreement/disagreement,
             thesis-change detection)
                      │
                Risk Manager
             (position sizing,
              correlation, exposure,
              sector concentration)
                      │
            ┌─────────────────┐
            │   DASHBOARD     │
            │  Portfolio view  │
            │  Stock cards     │
            │  Alerts          │
            │  Action buttons  │
            └─────────────────┘
```

### 4.2 Agent Design

Each analyst agent produces a **structured report** (not free-form chat):

```json
{
  "ticker": "TSM",
  "agent": "fundamental_analyst",
  "date": "2026-04-02",
  "signal": "bullish",
  "confidence": 0.82,
  "thesis": "CoWoS capacity expansion on track...",
  "key_metrics": {
    "revenue_growth_yoy": 0.35,
    "gross_margin": 0.57,
    "pe_ratio": 22.4,
    "free_cash_flow": 18200000000
  },
  "bull_case": "...",
  "bear_case": "...",
  "risks": ["Taiwan geopolitical risk", "..."],
  "evidence": ["Q4 2025 earnings beat by 12%", "..."],
  "thesis_change": false,
  "thesis_change_reason": null
}
```

The Research Synthesizer reads all analyst reports and produces a **unified memo**:

```json
{
  "ticker": "TSM",
  "date": "2026-04-02",
  "overall_signal": "bullish",
  "overall_confidence": 0.78,
  "analyst_agreement": "2/3 bullish, 1/3 neutral",
  "disagreement_flags": ["Sentiment analyst notes negative news cycle on Taiwan tensions"],
  "bull_case_summary": "...",
  "bear_case_summary": "...",
  "recommendation": "HOLD — thesis intact, no action needed",
  "thesis_changed_since_last": false,
  "key_watch_items": ["Q1 2026 earnings on April 17"]
}
```

The Risk Manager operates at **portfolio level**:

```json
{
  "date": "2026-04-02",
  "portfolio_signals": [...],
  "sector_exposure": {
    "semiconductor": 0.35,
    "power_energy": 0.30,
    "infrastructure": 0.20,
    "memory": 0.15
  },
  "concentration_warnings": ["Power/energy at 30% — consider if adding GEV"],
  "correlation_flags": ["CEG and VST have 0.85 correlation — effectively same bet"],
  "position_sizing": {
    "TSM": {"max_allocation": 0.15, "reason": "High conviction but geopolitical risk cap"}
  }
}
```

### 4.3 Communication Pattern

**Parallel + Synthesize with Structured Reports**
- Analysts run in parallel (speed)
- Each produces a structured JSON report (information preservation)
- Synthesizer reads all reports sequentially (coherence)
- Risk Manager checks portfolio-level constraints (safety)

### 4.4 LLM Strategy

| Agent | Model | Rationale |
|---|---|---|
| Fundamental Analyst | Claude Sonnet | Cost-effective, sufficient for financial analysis |
| Sentiment Analyst | Claude Sonnet | Cost-effective for news/sentiment processing |
| Supply Chain Analyst | Claude Sonnet | Cost-effective for industry analysis |
| Research Synthesizer | Claude Opus | Harder reasoning task — weighing conflicting signals |
| Risk Manager | Claude Sonnet | Rule-based + analytical, doesn't need Opus |

---

## 5. Tech Stack

| Component | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Finance + AI ecosystem depth |
| Agent Framework | LangGraph | Proven in top finance projects; graph-based orchestration |
| LLM | Anthropic Claude API | User preference; Sonnet for analysts, Opus for synthesizer |
| Price/Fundamentals | yfinance | Free, sufficient for position trading |
| SEC Filings | SEC EDGAR API | Free, authoritative |
| News | RSS feeds + free news APIs | Free tier start |
| Database | SQLite (→ PostgreSQL later) | Simple start, clean upgrade path |
| Dashboard | Streamlit | Fast MVP; rich enough for the use case |
| Scheduler | APScheduler | Weekly automated analysis runs |
| Config | python-dotenv + .env | API keys, model settings |

---

## 6. Data Sources — Free Tier

| Source | Data | Rate Limits | Notes |
|---|---|---|---|
| yfinance | Price, volume, basic financials, analyst targets | Unofficial, no strict limit | Good enough for position trading |
| SEC EDGAR | 10-K, 10-Q, 8-K filings | 10 requests/sec | Raw XML/HTML, needs parsing |
| Alpha Vantage (free) | Technicals, news sentiment | 25 requests/day | Supplement, not primary |
| RSS feeds | Financial news | Unlimited | Reuters, Bloomberg RSS, Yahoo Finance |
| FRED | Macro data (rates, GDP) | 120 requests/min | Fed economic data |

### Upgrade Path (when ready)

| Upgrade | Cost | What You Get | When to Upgrade |
|---|---|---|---|
| Financial Modeling Prep | ~$20/mo | Pre-parsed financials, standardized ratios | When tired of parsing EDGAR XML |
| NewsAPI | ~$50/mo | Structured news firehose, faster sentiment | When news latency matters |
| Seeking Alpha | ~$20/mo | Analyst estimates, consensus, price targets | When you want revision momentum signals |

---

## 7. Phased Roadmap

| Session | Phase | Scope | Key Deliverables |
|---|---|---|---|
| 1 | 0 | Design & Setup | DESIGN.md, CLAUDE.md, PROGRESS.md, project structure, deps |
| 2 | 1a | Data: Price & Fundamentals | yfinance integration, SQLite schema, data models |
| 3 | 1b | Data: SEC EDGAR + News | EDGAR parser, news/sentiment pipeline |
| 4 | 2 | Single Agent MVP | One Claude agent, structured buy/sell/hold reports |
| 5 | 3a | Fundamental Analyst Agent | Standalone agent with structured report output |
| 6 | 3b | Sentiment + Supply Chain Agents | Two more specialist agents |
| 7 | 3c | Synthesizer + Orchestration | Research Synthesizer, LangGraph wiring |
| 8 | 4 | Risk Manager | Portfolio-level risk analysis |
| 9 | 5a | Dashboard: Layout | Streamlit UI, portfolio overview, stock cards |
| 10 | 5b | Dashboard: Interactivity | Action buttons, drill-downs, signal history |
| 11 | 6 | Automation & Alerts | Scheduler, thesis-change alerts, earnings calendar |
| 12 | — | Integration & Polish | End-to-end testing, edge cases, README |

---

## 8. Session Protocol

### Session Closing (every session)

1. **Update PROGRESS.md** — what completed, what didn't, blockers, next steps
2. **Update CLAUDE.md** — current phase, file reading order for next session
3. **Run tests / verify** — confirm code runs, note known issues
4. **Checkpoint with user** — summarize, ask for feedback or corrections
5. **Git commit & push** — clear commit message summarizing the session

### Session Opening (every new conversation)

1. Read `CLAUDE.md` → where we are
2. Read `PROGRESS.md` → what happened last, what's next
3. Read `DESIGN.md` → architecture reference
4. Read only files relevant to this session's scope
5. Confirm plan with user before writing code

---

## 9. Project Structure

```
ai-investment-agent/
├── CLAUDE.md                    # Session start instructions
├── PROGRESS.md                  # Living handoff document
├── DESIGN.md                    # This file — architecture & decisions
├── AI_Supply_Chain_Investment_Report.md  # Market research
├── .env.example                 # API key template
├── .gitignore
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── config.py                # Settings, API keys, constants
│   ├── data/
│   │   ├── __init__.py
│   │   ├── price.py             # yfinance integration
│   │   ├── fundamentals.py      # Financial data fetching
│   │   ├── edgar.py             # SEC EDGAR parsing
│   │   ├── news.py              # News/RSS integration
│   │   └── models.py            # Data models / schemas
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── fundamental.py       # Fundamental Analyst agent
│   │   ├── sentiment.py         # Sentiment Analyst agent
│   │   ├── supply_chain.py      # Supply Chain Analyst agent
│   │   ├── synthesizer.py       # Research Synthesizer agent
│   │   ├── risk_manager.py      # Risk Manager agent
│   │   └── prompts/             # Agent system prompts
│   │       ├── fundamental.md
│   │       ├── sentiment.md
│   │       ├── supply_chain.md
│   │       ├── synthesizer.md
│   │       └── risk_manager.md
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   └── graph.py             # LangGraph orchestration
│   ├── dashboard/
│   │   ├── __init__.py
│   │   └── app.py               # Streamlit dashboard
│   └── db/
│       ├── __init__.py
│       ├── schema.py            # SQLite schema
│       └── operations.py        # DB read/write operations
├── data/
│   └── investment.db            # SQLite database (gitignored)
└── tests/
    ├── __init__.py
    ├── test_data.py
    ├── test_agents.py
    └── test_orchestrator.py
```

---

## 10. Key Design Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|---|---|---|---|
| Structured reports over chat | JSON reports | Free-form agent dialogue | TradingAgents research: preserves information fidelity |
| Parallel analysts | 3 concurrent | Sequential pipeline | Speed; analysts are independent |
| Separate synthesizer | Dedicated agent | Analyst self-synthesis | Different cognitive task; keeps analysts focused |
| Opus for synthesizer only | Mixed model | All Opus or all Sonnet | Cost optimization; synthesis is the hardest reasoning task |
| Streamlit for dashboard | Streamlit | Next.js, Gradio | Fast MVP; Python-native; rich enough for the use case |
| SQLite to start | SQLite | PostgreSQL from day 1 | Simplicity; no server to manage; migrate later if needed |
| No auto-trading | Human decides | Full automation | Risk management; regulatory simplicity; user preference |
