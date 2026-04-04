"""CLI runner for the analyst agent.

Usage:
    python -m src.agents.runner TSM          # Analyze one ticker
    python -m src.agents.runner --all        # Analyze all active watchlist tickers
    python -m src.agents.runner TSM --no-save  # Analyze without saving to DB
"""

import argparse
import json
import sys
import time

from src.config import WATCHLIST
from src.agents.analyst import analyze_ticker
from src.db.operations import init_db
from src.utils.logger import get_logger

logger = get_logger("runner")


def run_single(ticker: str, save: bool = True) -> None:
    """Analyze a single ticker and print the report."""
    ticker = ticker.upper()
    start = time.monotonic()

    try:
        report = analyze_ticker(ticker, save=save)
    except Exception as e:
        logger.error(f"Failed to analyze {ticker}: {e}")
        sys.exit(1)

    duration = time.monotonic() - start

    # Pretty-print the report
    print("\n" + "=" * 60)
    print(f"  {report.ticker} — {report.signal.value.upper()} "
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


def run_all(save: bool = True) -> None:
    """Analyze all active watchlist tickers."""
    tickers = list(WATCHLIST.keys())
    total = len(tickers)

    logger.info(f"Analyzing {total} tickers: {', '.join(tickers)}")

    results = []
    for i, ticker in enumerate(tickers, 1):
        print(f"\n[{i}/{total}] Analyzing {ticker}...")
        try:
            report = analyze_ticker(ticker, save=save)
            results.append(report)
            print(f"  -> {report.signal.value.upper()} ({report.confidence:.0%})")
        except Exception as e:
            logger.error(f"  -> FAILED: {e}")
            continue

    # Summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    for r in results:
        print(f"  {r.ticker:>5} | {r.signal.value:>8} | {r.confidence:.0%} | {r.thesis[:60]}...")
    print(f"\n{len(results)}/{total} completed successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the analyst agent")
    parser.add_argument("ticker", nargs="?", help="Ticker to analyze (or --all)")
    parser.add_argument("--all", action="store_true", help="Analyze all watchlist tickers")
    parser.add_argument("--no-save", action="store_true", help="Don't save report to database")

    args = parser.parse_args()

    if not args.ticker and not args.all:
        parser.print_help()
        sys.exit(1)

    # Ensure DB is initialized
    init_db()

    save = not args.no_save

    if args.all:
        run_all(save=save)
    else:
        run_single(args.ticker, save=save)


if __name__ == "__main__":
    main()
