"""
Scheduler — runs the tracker automatically on a schedule.
Uses APScheduler to poll Facebook every POLL_INTERVAL_SECONDS.

Run: python scheduler.py
"""
import os
import time
from dotenv import load_dotenv
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler

from src.tracker import run_tracker

load_dotenv()

INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", 300))


def main():
    scheduler = BlockingScheduler()
    scheduler.add_job(run_tracker, "interval", seconds=INTERVAL, id="tracker")
    logger.info(f"Scheduler started — polling every {INTERVAL}s")

    # Run immediately on start
    run_tracker()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
