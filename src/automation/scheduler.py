"""Standalone scheduler for automated analysis runs.

Usage:
    python -m src.automation.scheduler            # Start weekly scheduler (blocks)
    python -m src.automation.scheduler --run-now   # Run once immediately, then exit
"""

import argparse
import sys
import time
from datetime import datetime

from src.config import SCHEDULE_DAY_OF_WEEK, SCHEDULE_HOUR, SCHEDULE_MINUTE
from src.data.models import AlertRecord, AlertSeverity, AlertType
from src.db.operations import init_db, save_alert
from src.utils.logger import get_logger

logger = get_logger("automation.scheduler")


def scheduled_run(db_path: str | None = None) -> None:
    """Execute the full analysis pipeline: orchestrate → risk → earnings → alerts → notify."""
    from src.agents.runner import run_all_orchestrated, run_risk
    from src.automation.alerts import detect_and_fire_alerts
    from src.automation.earnings import refresh_earnings_calendar
    from src.automation.notifier import notify

    kwargs = {"db_path": db_path} if db_path else {}
    start = time.monotonic()
    logger.info("Scheduled run starting...")

    try:
        init_db(**({} if db_path is None else {"db_path": db_path}))

        # Step 1: Run orchestrated analysis for all tickers
        logger.info("Step 1/4: Running orchestrated analysis for all tickers...")
        try:
            run_all_orchestrated(save=True)
        except SystemExit as e:
            if e.code != 0:
                logger.warning(f"Orchestrated analysis exited with code {e.code}, continuing...")

        # Step 2: Run portfolio risk assessment
        logger.info("Step 2/4: Running portfolio risk assessment...")
        try:
            run_risk(save=True)
        except SystemExit as e:
            if e.code != 0:
                logger.warning(f"Risk analysis exited with code {e.code}, continuing...")

        # Step 3: Refresh earnings calendar
        logger.info("Step 3/4: Refreshing earnings calendar...")
        refresh_earnings_calendar(**kwargs)

        # Step 4: Detect and fire alerts
        logger.info("Step 4/4: Detecting alerts...")
        alerts = detect_and_fire_alerts(**kwargs)

        duration = time.monotonic() - start

        # Save run-completed alert
        run_alert = AlertRecord(
            alert_type=AlertType.RUN_COMPLETED,
            severity=AlertSeverity.INFO,
            title="Scheduled analysis run completed",
            detail=f"Full pipeline completed in {duration:.0f}s. {len(alerts)} alert(s) generated.",
        )
        save_alert(run_alert, **kwargs)
        alerts.append(run_alert)

        # Notify
        notify(alerts)
        logger.info(f"Scheduled run completed in {duration:.0f}s")

    except Exception as e:
        duration = time.monotonic() - start
        logger.error(f"Scheduled run failed after {duration:.0f}s: {e}")

        # Save run-failed alert
        fail_alert = AlertRecord(
            alert_type=AlertType.RUN_FAILED,
            severity=AlertSeverity.CRITICAL,
            title="Scheduled analysis run failed",
            detail=f"Pipeline failed after {duration:.0f}s: {e}",
        )
        try:
            save_alert(fail_alert, **kwargs)
            notify([fail_alert])
        except Exception:
            logger.error("Failed to save/notify run failure alert")


def start_scheduler() -> None:
    """Configure and start the blocking scheduler with weekly cron trigger."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BlockingScheduler()
    trigger = CronTrigger(
        day_of_week=SCHEDULE_DAY_OF_WEEK,
        hour=SCHEDULE_HOUR,
        minute=SCHEDULE_MINUTE,
    )
    scheduler.add_job(
        scheduled_run,
        trigger,
        id="weekly_analysis",
        name="Weekly Analysis Run",
    )

    next_run = trigger.get_next_fire_time(None, datetime.now())
    logger.info(
        f"Scheduler started. Next run: {next_run} "
        f"(every {SCHEDULE_DAY_OF_WEEK} at {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d})"
    )
    print(f"Scheduler running. Next analysis: {next_run}")
    print("Press Ctrl+C to stop.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by user")
        print("\nScheduler stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Investment Agent — Automated Scheduler")
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run the analysis pipeline once immediately, then exit",
    )
    args = parser.parse_args()

    if args.run_now:
        print("Running analysis pipeline now...")
        scheduled_run()
        print("Done.")
    else:
        start_scheduler()


if __name__ == "__main__":
    main()
