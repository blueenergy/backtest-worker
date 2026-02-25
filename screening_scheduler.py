#!/usr/bin/env python3
"""
Screening scheduler: runs daily_full_market_screening.py on a schedule.

Schedule logic (matches screening.sh):
  - Weekday (Mon-Fri): run once at 18:30 CST using 60-day window
  - Weekend (Sat-Sun): run once at 08:00 CST using 360-day window

Environment variables (all optional):
  SCREENING_MODE       : conservative | standard | aggressive | all (default: conservative)
  SCREENING_DAYS_BACK  : override the auto window (e.g. 360)
  SCREENING_RUN_AT     : HH:MM in local time to trigger (default: auto by weekday)
  TZ                   : should be set to Asia/Shanghai in docker-compose
"""

import os
import subprocess
import sys
import time
import logging
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - screening_scheduler - %(levelname)s - %(message)s",
)
log = logging.getLogger("screening_scheduler")

SCREENING_MODE = os.environ.get("SCREENING_MODE", "conservative")
MANUAL_DAYS_BACK = os.environ.get("SCREENING_DAYS_BACK", "")
MANUAL_RUN_AT = os.environ.get("SCREENING_RUN_AT", "")  # e.g. "18:30"

PRESETS = {
    "conservative": [
        ("turtle",       "turtle_conservative"),
        ("single_yang",  "yang_conservative"),
        ("hidden_dragon","dragon_conservative"),
    ],
    "standard": [
        ("turtle",       "turtle_standard"),
        ("single_yang",  "yang_default"),
        ("hidden_dragon","dragon_default"),
    ],
    "aggressive": [
        ("turtle",       "turtle_aggressive"),
        ("single_yang",  "yang_aggressive"),
        ("hidden_dragon","dragon_aggressive"),
    ],
}

def get_tasks():
    """Return list of (strategy_key, preset) tuples based on SCREENING_MODE."""
    mode = SCREENING_MODE
    if mode == "all":
        tasks = []
        for v in PRESETS.values():
            tasks.extend(v)
        return tasks
    return PRESETS.get(mode, PRESETS["conservative"])


def get_schedule():
    """Return (run_hour, run_minute, days_back) for today."""
    if MANUAL_RUN_AT:
        h, m = MANUAL_RUN_AT.split(":")
        run_hour, run_minute = int(h), int(m)
    else:
        now = datetime.now()
        if now.weekday() >= 5:  # weekend
            run_hour, run_minute = 8, 0
        else:
            run_hour, run_minute = 18, 30

    if MANUAL_DAYS_BACK:
        days_back = int(MANUAL_DAYS_BACK)
    else:
        now = datetime.now()
        days_back = 360 if now.weekday() >= 5 else 60

    return run_hour, run_minute, days_back


def run_screening(days_back: int):
    """Run all configured screening presets sequentially."""
    tasks = get_tasks()
    log.info("Starting screening | mode=%s days_back=%d tasks=%d", SCREENING_MODE, days_back, len(tasks))

    for strategy_key, preset in tasks:
        log.info("Running: strategy=%s preset=%s", strategy_key, preset)
        result = subprocess.run(
            [
                sys.executable,
                "daily_full_market_screening.py",
                "--strategy-key", strategy_key,
                "--preset", preset,
                "--days-back", str(days_back),
                "--initial-cash", "1000000",
                "--min-win-rate", "0.50",
                "--min-trades", "3",
                "--min-return", "0.03",
                "--log-level", "INFO",
            ],
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        if result.returncode != 0:
            log.error("Screening task failed: strategy=%s preset=%s returncode=%d",
                      strategy_key, preset, result.returncode)
        else:
            log.info("Screening task done: strategy=%s preset=%s", strategy_key, preset)

    log.info("All screening tasks complete for today.")


def next_run_time(run_hour: int, run_minute: int) -> datetime:
    """Return the next datetime when screening should run."""
    now = datetime.now()
    target = now.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def main():
    log.info("Screening scheduler started | mode=%s", SCREENING_MODE)
    already_ran_today: str = ""  # date string YYYY-MM-DD

    while True:
        run_hour, run_minute, days_back = get_schedule()
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        # Check if it's time to run
        if (now.hour == run_hour and now.minute == run_minute
                and already_ran_today != today_str):
            already_ran_today = today_str
            run_screening(days_back)

        # Sleep until next minute check
        time.sleep(30)


if __name__ == "__main__":
    main()
