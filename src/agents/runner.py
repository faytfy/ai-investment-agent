"""CLI runner for analyst agents.

Usage:
    python -m src.agents.runner TSM                        # General analyst, one ticker
    python -m src.agents.runner TSM --agent fundamental    # Fundamental analyst
    python -m src.agents.runner --all                      # All tickers, general analyst
    python -m src.agents.runner --all --agent fundamental  # All tickers, fundamental analyst
    python -m src.agents.runner TSM --no-save              # Analyze without saving to DB
"""

import argparse
import sys
import time

from src.config import WATCHLIST
from src.db.operations import init_db
from src.utils.logger import get_logger

logger = get_logger("runner")

AGENT_REGISTRY = {
    "general": ("src.agents.analyst", "analyze_ticker"),
    "fundamental": ("src.agents.fundamental", "analyze_ticker"),
    "sentiment": ("src.agents.sentiment", "analyze_ticker"),
    "supply_chain": ("src.agents.supply_chain", "analyze_ticker"),
    "synthesizer": ("src.agents.synthesizer", "analyze_ticker"),
}


def _get_analyze_fn(agent_name: str):
    """Dynamically import the analyze_ticker function for the given agent."""
    if agent_name not in AGENT_REGISTRY:
        logger.error(f"Unknown agent: {agent_name}. Available: {list(AGENT_REGISTRY.keys())}")
        sys.exit(1)

    module_path, fn_name = AGENT_REGISTRY[agent_name]
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, fn_name)


def run_single(ticker: str, agent: str = "general", save: bool = True) -> None:
    """Analyze a single ticker and print the report."""
    ticker = ticker.upper()
    analyze_ticker = _get_analyze_fn(agent)
    start = time.monotonic()

    try:
        report = analyze_ticker(ticker, save=save)
    except Exception as e:
        logger.error(f"Failed to analyze {ticker}: {e}")
        sys.exit(1)

    duration = time.monotonic() - start

    print("\n" + "=" * 60)
    print(f"  [{report.agent}] {report.ticker} — {report.signal.value.upper()} "
          f"(confidence: {report.confidence:.0%})")
    print("=" * 60)
    print(f"\nThesis: {report.thesis}")
    print(f"\nBull Case: {report.bull_case}")
    print(f"\nBear Case: {report.bear_case}")
    print(f"\nRisks:")
    for r in report.risks:
        print(f"  - {r}")
    print(f"\nEvidence:")
    for e in report.evidence:
        print(f"  - {e}")
    if report.key_metrics:
        print(f"\nKey Metrics:")
        for k, v in report.key_metrics.items():
            print(f"  {k}: {v}")
    if report.thesis_change:
        print(f"\n*** THESIS CHANGE: {report.thesis_change_reason} ***")
    print(f"\nCompleted in {duration:.1f}s")
    if save:
        print("Report saved to database.")


def run_orchestrated(ticker: str, save: bool = True) -> None:
    """Run the full orchestrated pipeline: 3 analysts in parallel → synthesizer."""
    from src.orchestrator.graph import orchestrate

    ticker = ticker.upper()
    print(f"\nRunning orchestrated analysis for {ticker}...")
    print("(3 analysts in parallel → synthesis)\n")

    start = time.monotonic()

    try:
        state = orchestrate(ticker, save=save)
    except Exception as e:
        logger.error(f"Orchestration failed for {ticker}: {e}")
        sys.exit(1)

    duration = time.monotonic() - start

    # Print individual analyst results
    for report in state.analyst_reports:
        print(f"  [{report.agent}] {report.signal.value.upper()} ({report.confidence:.0%})")

    if state.analyst_errors:
        print(f"\n  Errors:")
        for err in state.analyst_errors:
            print(f"    - {err}")

    # Print synthesis
    if state.synthesis:
        s = state.synthesis
        print("\n" + "=" * 60)
        print(f"  SYNTHESIS: {ticker} — {s.overall_signal.value.upper()} "
              f"(confidence: {s.overall_confidence:.0%})")
        print("=" * 60)
        print(f"\nAgreement: {s.analyst_agreement}")
        if s.disagreement_flags:
            print(f"\nDisagreements:")
            for d in s.disagreement_flags:
                print(f"  - {d}")
        print(f"\nBull Case: {s.bull_case_summary}")
        print(f"\nBear Case: {s.bear_case_summary}")
        print(f"\nRecommendation: {s.recommendation}")
        if s.key_watch_items:
            print(f"\nWatch Items:")
            for item in s.key_watch_items:
                print(f"  - {item}")
        if s.thesis_changed_since_last:
            print(f"\n*** THESIS CHANGE DETECTED ***")
    else:
        print("\n  Synthesis not produced (check errors above)")

    print(f"\nCompleted in {duration:.1f}s")
    if save:
        print("All reports saved to database.")


def run_all_orchestrated(save: bool = True) -> None:
    """Run orchestrated analysis for all watchlist tickers."""
    from src.orchestrator.graph import orchestrate

    tickers = list(WATCHLIST.keys())
    total = len(tickers)

    logger.info(f"Orchestrating analysis for {total} tickers: {', '.join(tickers)}")

    results = []
    for i, ticker in enumerate(tickers, 1):
        print(f"\n[{i}/{total}] Orchestrating {ticker}...")
        try:
            state = orchestrate(ticker, save=save)
            if state.synthesis:
                results.append(state.synthesis)
                print(f"  -> {state.synthesis.overall_signal.value.upper()} "
                      f"({state.synthesis.overall_confidence:.0%})")
            else:
                print(f"  -> No synthesis produced")
        except Exception as e:
            logger.error(f"  -> FAILED: {e}")
            continue

    print("\n" + "=" * 60)
    print(f"  ORCHESTRATED SUMMARY")
    print("=" * 60)
    for s in results:
        print(f"  {s.ticker:>5} | {s.overall_signal.value:>8} | "
              f"{s.overall_confidence:.0%} | {s.recommendation[:50]}...")
    print(f"\n{len(results)}/{total} completed successfully.")


def run_all(agent: str = "general", save: bool = True) -> None:
    """Analyze all active watchlist tickers."""
    tickers = list(WATCHLIST.keys())
    total = len(tickers)
    analyze_ticker = _get_analyze_fn(agent)

    logger.info(f"[{agent}] Analyzing {total} tickers: {', '.join(tickers)}")

    results = []
    for i, ticker in enumerate(tickers, 1):
        print(f"\n[{i}/{total}] Analyzing {ticker} ({agent})...")
        try:
            report = analyze_ticker(ticker, save=save)
            results.append(report)
            print(f"  -> {report.signal.value.upper()} ({report.confidence:.0%})")
        except Exception as e:
            logger.error(f"  -> FAILED: {e}")
            continue

    print("\n" + "=" * 60)
    print(f"  SUMMARY ({agent})")
    print("=" * 60)
    for r in results:
        print(f"  {r.ticker:>5} | {r.signal.value:>8} | {r.confidence:.0%} | {r.thesis[:60]}...")
    print(f"\n{len(results)}/{total} completed successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run analyst agents")
    parser.add_argument("ticker", nargs="?", help="Ticker to analyze (or --all)")
    parser.add_argument("--all", action="store_true", help="Analyze all watchlist tickers")
    parser.add_argument("--agent", default="general",
                        choices=list(AGENT_REGISTRY.keys()),
                        help="Which analyst agent to run (default: general)")
    parser.add_argument("--no-save", action="store_true", help="Don't save report to database")
    parser.add_argument("--orchestrate", action="store_true",
                        help="Run full pipeline: 3 analysts in parallel → synthesizer")

    args = parser.parse_args()

    if not args.ticker and not args.all:
        parser.print_help()
        sys.exit(1)

    init_db()

    save = not args.no_save

    if args.orchestrate:
        if args.all:
            run_all_orchestrated(save=save)
        elif args.ticker:
            run_orchestrated(args.ticker, save=save)
        else:
            parser.print_help()
            sys.exit(1)
    elif args.all:
        run_all(agent=args.agent, save=save)
    else:
        run_single(args.ticker, agent=args.agent, save=save)


if __name__ == "__main__":
    main()
