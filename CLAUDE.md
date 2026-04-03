# AI Investment Agent — Session Instructions

## Current State
- **Phase:** 1a — Data Pipeline: Price & Fundamentals (COMPLETE)
- **Session:** 2 of 12
- **Next Session:** 3 — Phase 1b (Data: SEC EDGAR + News)

## Session Opening Protocol

Every new session, do this in order:

1. Read this file (`CLAUDE.md`)
2. Read `PROGRESS.md` — what happened last session, what's next
3. Read `DESIGN.md` — architecture reference (sections relevant to current phase)
4. Read only the source files relevant to this session's scope
5. Confirm the plan with the user before writing code
6. Run the plan through the **Plan Review Checklist** (below) before coding starts

## Plan Review Checklist

Every session plan must address these five areas. If an area isn't relevant, mark it N/A.

### 1. Data Flow
- What goes **in** to this session's code? (upstream inputs)
- What comes **out**? (downstream consumers)
- Are the interfaces typed with Pydantic models?

### 2. Failure Modes
- What external dependencies can fail? (APIs, files, DB)
- What happens when they do? (retry, skip, error?)
- Can one failure cascade and break everything?

### 3. Validation
- Where does untrusted data enter? (user input, API responses)
- What validation exists at that boundary?
- What does invalid data look like, and where does it go?

### 4. Testing Strategy
- What are the contract tests? (does the interface match?)
- What are the round-trip tests? (write → read → compare)
- What are the edge cases? (empty data, missing fields, stale data)

### 5. Performance
- Any loops over network calls? (batch or parallelize)
- Any unbounded data? (need pagination or limits)
- Anything that blocks the user waiting? (need progress feedback)

## Post-Coding Review Protocol

After coding and tests pass, spawn two review agents in parallel:

1. **Code Reviewer** (senior engineer) — reads all session files together. Checks:
   - Do interfaces align across files?
   - Type mismatches or contract violations?
   - Missing error handling at boundaries?
   - Anything that'll break downstream consumers in future sessions?

2. **Test Reviewer** (QA engineer) — reads tests against source. Checks:
   - Are edge cases covered?
   - Untested code paths?
   - Do assertions verify meaningful behavior, not just "doesn't crash"?

Then: fix anything flagged → re-run tests → proceed to session close.

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
