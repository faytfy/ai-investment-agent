"""Structured logging for the AI Investment Agent."""

import logging
import sys
import time
from contextlib import contextmanager
from typing import Generator

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger for the given module name."""
    logger = logging.getLogger(f"investment.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


@contextmanager
def log_fetch(logger: logging.Logger, ticker: str, source: str) -> Generator[dict, None, None]:
    """Context manager that logs fetch operations with timing and record counts.

    Usage:
        with log_fetch(logger, "TSM", "yfinance_prices") as ctx:
            data = fetch_something()
            ctx["records"] = len(data)
    """
    ctx: dict = {"records": 0}
    start = time.monotonic()
    logger.info(f"Fetching {source} for {ticker}...")
    try:
        yield ctx
        duration = time.monotonic() - start
        logger.info(
            f"Fetched {source} for {ticker}: "
            f"{ctx['records']} records in {duration:.1f}s"
        )
    except Exception as e:
        duration = time.monotonic() - start
        logger.error(
            f"Failed {source} for {ticker} after {duration:.1f}s: {e}"
        )
        raise
