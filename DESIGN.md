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

---

## 11. Multi-Agent Research — Reference Projects

These projects informed our architecture. Documented here so future sessions can reference the design rationale.

### 11.1 Key Open-Source Projects

| Project | Stars | Architecture | Key Takeaway |
|---|---|---|---|
| **virattt/ai-hedge-fund** | 49.9k | 18 agents: 12 investor personas (Buffett, Munger, Cathie Wood, Burry, Damodaran, Lynch, etc.) + 4 analytical agents + Risk Manager + Portfolio Manager. Built with LangGraph + FastAPI + TypeScript frontend. | Diversity of investment philosophy baked in via persona agents. Creates natural bull/bear debate without explicit debate mechanism. |
| **TradingAgents** (arxiv.org/abs/2412.20138) | Academic | Mirrors real trading firm: Analyst Team (parallel) → Research Team → Trader → Risk Mgmt → Fund Manager. Built with LangGraph. | **Structured reports between agents, not chat.** This preserves information fidelity — our primary design influence. Demonstrated superior Sharpe ratio and lower max drawdown. |
| **FinRobot** (AI4Finance Foundation) | — | 3-agent Chain-of-Thought: Data-CoT → Concept-CoT → Thesis-CoT. | Simplest effective pattern for equity research. Our single-agent MVP (Phase 2) will resemble this before we decompose. |
| **AutoHedge** (Swarm Corporation) | — | Enterprise swarm intelligence. Continuous analysis, thesis generation/validation, risk sizing, live execution on Solana. | Too complex for our use case, but shows where full automation leads. |
| **FinRL** | — | Reinforcement learning for portfolio optimization. Not LLM-based. | Complementary approach — could add RL-based position sizing in a future phase. |

### 11.2 Communication Patterns (Research Summary)

| Pattern | How It Works | When to Use |
|---|---|---|
| **Sequential Pipeline** | A → B → C → D | Simple tasks, clear dependencies |
| **Hierarchical** | Boss delegates to specialists | Portfolio management structure |
| **Debate/Consensus** | Agents argue, then vote | Surfaces disagreements, reduces bias; expensive |
| **Parallel + Synthesize** | Analysts run concurrently, synthesizer merges | **Our choice** — speed + information richness |

**Research finding:** Voting protocols improve reasoning tasks by 13.2%. Deliberation improves knowledge tasks by 2.8%. For investment analysis, parallel + synthesize with structured reports is the sweet spot.

### 11.3 Single-Agent vs Multi-Agent (Quantified)

| Dimension | Single Agent | Multi-Agent |
|---|---|---|
| Complex task success rate | 2.9% | 42.7% |
| Financial reconciliation accuracy | 60% | 92.1% |
| Response speed | 30-50% faster | Slower (coordination overhead) |
| API cost | Lower | 30-50% higher |

**Our approach:** Start single (Phase 2), decompose into multi-agent (Phase 3) once data pipeline is proven. Per Microsoft's recommendation.

### 11.4 Frameworks Evaluated

| Framework | Verdict | Why |
|---|---|---|
| **LangGraph** | **Selected** | Used by both ai-hedge-fund and TradingAgents. Graph-based orchestration fits our parallel→sequential flow. Most proven for finance. |
| CrewAI | Rejected | Easier to prototype but less flexible for complex orchestration. |
| AutoGen (Microsoft) | Rejected | Better for conversational agent collaboration; we want structured reports, not dialogue. |
| MetaGPT | Rejected | Designed for software-company workflows, not investment analysis. |

### 11.5 Regulatory Context

- No AI-specific SEC regulations yet, but existing anti-fraud rules (Section 206 Advisers Act) apply
- SEC actively pursuing "AI washing" — firms claiming AI they don't have
- 2026 SEC examination priorities: verify actual AI usage matches representations
- **Human-in-the-loop** (our model) is what regulators expect
- For personal use with disclaimers: no registration needed
- All referenced open-source projects include "not financial advice" disclaimers

### 11.6 Data Layer Projects

| Project | Purpose |
|---|---|
| **OpenBB** (github.com/OpenBB-finance/OpenBB) | Open-source financial data platform; could replace yfinance if we need more structured data |
| **Alpha Vantage MCP Server** (mcp.alphavantage.co) | MCP integration for LLM-native data access; potential future integration |

---

## 12. Data Budget — Full Tradeoff Analysis

For position trading on fundamentals, **data freshness matters less than data depth.** A 15-minute delay on price is irrelevant when your holding period is months.

| Data Need | Free Option | Premium Option | When to Upgrade |
|---|---|---|---|
| **Price data** | Yahoo Finance (yfinance) — no strict rate limit | Polygon.io (~$30/mo) — real-time, full history, after-hours | **Not needed** — free is sufficient for position trading |
| **Fundamentals** | SEC EDGAR (raw XML/HTML filing) | Financial Modeling Prep (~$20/mo) — pre-parsed, standardized ratios, analyst estimates | **First upgrade** — saves enormous parsing effort for clean quarterly data |
| **News & sentiment** | RSS feeds, free news APIs (limited) | Benzinga Pro (~$100/mo), NewsAPI (~$50/mo) — real-time firehose, pre-scored sentiment | When agent needs to react to news within hours, not days |
| **Analyst ratings** | Sporadic via Yahoo Finance | Koyfin (~$30/mo), Seeking Alpha (~$20/mo) — consensus estimates, price targets, revision history | Useful for position trading — analyst revision momentum is a real signal |
| **Earnings transcripts** | SEC filings (delayed) | Earnings call APIs (~$30-50/mo) — same-day parsed transcripts, NLP-ready | When agent should analyze management tone and guidance language |
| **Alternative data** | GitHub stars, job postings (free scraping) | Supply chain tracking, satellite data, patent filings | Skip entirely — hedge fund territory, overkill for our strategy |

**Recommended upgrade path:**
1. Start 100% free (Phase 1-4)
2. First paid: Financial Modeling Prep (~$20/mo) — clean fundamentals
3. Second paid: Analyst estimates + earnings transcripts (~$40-50/mo) — highest signal for fundamental position trading
4. Skip: Real-time tick data, options flow, alternative data

---

## 13. Context Window Management

Phases were split across 12 sessions to ensure each fits within a single conversation context window without degradation.

| Original Phase | Sessions | Why Split |
|---|---|---|
| Phase 0 (Design) | 1 session | Small — project scaffold and docs |
| Phase 1 (Data Pipeline) | **2 sessions** | 3 data sources (yfinance, EDGAR, news) + DB schema + models — too many files for one session |
| Phase 2 (Single Agent) | 1 session | One agent + prompts + report format |
| Phase 3 (Multi-Agent) | **3 sessions** | 3 analyst agents + synthesizer + LangGraph orchestration — largest phase, most complex |
| Phase 4 (Risk Manager) | 1 session | One agent + portfolio math |
| Phase 5 (Dashboard) | **2 sessions** | Layout + interactivity are distinct concerns; Streamlit code gets verbose |
| Phase 6 (Automation) | 1 session | Small — scheduler + alerts |
| Integration | 1 session | Testing + polish + README |

**Rule:** Each session should create/modify no more than ~6-8 source files to stay within comfortable context limits.
