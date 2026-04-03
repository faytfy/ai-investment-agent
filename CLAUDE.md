# AI Investment Agent — Session Instructions

## Current State
- **Phase:** 0 — Design & Setup (COMPLETE)
- **Session:** 1 of 12
- **Next Session:** 2 — Phase 1a (Data Pipeline: Price & Fundamentals)

## Session Opening Protocol

Every new session, do this in order:

1. Read this file (`CLAUDE.md`)
2. Read `PROGRESS.md` — what happened last session, what's next
3. Read `DESIGN.md` — architecture reference (sections relevant to current phase)
4. Read only the source files relevant to this session's scope
5. Confirm the plan with the user before writing code

## Session Closing Protocol

Before ending every session:

1. **Update `PROGRESS.md`** — what completed, what didn't, blockers, next steps, deviations
2. **Update this file (`CLAUDE.md`)** — bump phase/session number, update next session scope
3. **Run tests / verify** — confirm code runs without errors, note known issues
4. **Checkpoint with user** — "Here's what we did, here's what's next — anything to adjust?"
5. **Git commit & push** — clear commit message summarizing the session

## Key Files

| File | Purpose |
|---|---|
| `DESIGN.md` | Architecture, tech stack, agent design, full roadmap |
| `PROGRESS.md` | Living handoff document — session-by-session log |
| `AI_Supply_Chain_Investment_Report.md` | Market research on AI supply chain |
| `src/` | All source code |
| `data/` | SQLite database (gitignored) |
| `tests/` | Test files |

## Phase Map (for reference)

| Session | Phase | Scope |
|---|---|---|
| 1 | 0 | Design & Setup |
| 2 | 1a | Data: Price & Fundamentals (yfinance, SQLite) |
| 3 | 1b | Data: SEC EDGAR + News |
| 4 | 2 | Single Agent MVP |
| 5 | 3a | Fundamental Analyst Agent |
| 6 | 3b | Sentiment + Supply Chain Agents |
| 7 | 3c | Synthesizer + LangGraph Orchestration |
| 8 | 4 | Risk Manager |
| 9 | 5a | Dashboard: Layout |
| 10 | 5b | Dashboard: Interactivity |
| 11 | 6 | Automation & Alerts |
| 12 | — | Integration, Polish, README |

## Working Rules

- Never auto-trade — agent recommends, user decides
- Structured JSON reports between agents, not free-form chat
- Start free-tier data sources; document upgrade path
- Don't add features beyond what the current phase requires
- Test before committing
