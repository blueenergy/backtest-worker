#!/usr/bin/env python3
"""
Screening scheduler: runs daily_full_market_screening.py on a schedule.

Singleton role (BACKTEST_ROLE=screening). Uses a Mongo distributed lock so only
one screening scheduler runs across replicas.
"""

import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

from pymongo import MongoClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - screening_scheduler - %(levelname)s - %(message)s",
)
log = logging.getLogger("screening_scheduler")

SCREENING_MODE = os.environ.get("SCREENING_MODE", "conservative")
SCREENING_STRATEGIES = os.environ.get("SCREENING_STRATEGIES", "")
MANUAL_DAYS_BACK = os.environ.get("SCREENING_DAYS_BACK", "")
SCREENING_UNIVERSE_INDEX = os.environ.get("SCREENING_UNIVERSE_INDEX", "").strip()
MANUAL_RUN_AT = os.environ.get("SCREENING_RUN_AT", "")
HOLDER_ID = os.environ.get("BACKTEST_WORKER_ID", f"screening_{os.getenv('HOSTNAME', 'local')}")
LOCK_TTL_SECONDS = max(300, int(os.environ.get("SCREENING_LOCK_TTL_SECONDS", "7200")))

PRESETS = {
    "conservative": [
        ("turtle", "turtle_conservative"),
        ("single_yang", "yang_conservative"),
        ("hidden_dragon", "dragon_conservative"),
    ],
    "standard": [
        ("turtle", "turtle_standard"),
        ("single_yang", "yang_default"),
        ("hidden_dragon", "dragon_default"),
    ],
    "aggressive": [
        ("turtle", "turtle_aggressive"),
        ("single_yang", "yang_aggressive"),
        ("hidden_dragon", "dragon_aggressive"),
    ],
}

_shutdown_requested = False
_active_child: Optional[subprocess.Popen] = None
_lock_client: Optional[MongoClient] = None
_lock_db = None


def _mongo_db():
    global _lock_client, _lock_db
    if _lock_db is None:
        mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
        db_name = os.environ.get("BACKTEST_DB_NAME") or os.environ.get("DB_NAME") or "finance"
        _lock_client = MongoClient(mongo_uri)
        _lock_db = _lock_client[db_name]
    return _lock_db


def acquire_screening_lock() -> bool:
    from worker.task_store import MongoBacktestTaskStore

    store = MongoBacktestTaskStore(db=_mongo_db())
    store.ensure_indexes()
    acquired = store.acquire_screening_lock(HOLDER_ID, ttl_seconds=LOCK_TTL_SECONDS)
    if not acquired:
        log.warning("Another screening scheduler holds the lock; skipping run")
    return acquired


def release_screening_lock() -> None:
    from worker.task_store import MongoBacktestTaskStore

    store = MongoBacktestTaskStore(db=_mongo_db())
    store.release_screening_lock(HOLDER_ID)


def get_tasks():
    mode = SCREENING_MODE
    if mode == "all":
        tasks = []
        for values in PRESETS.values():
            tasks.extend(values)
        return tasks

    tasks = []
    seen = set()
    for item in mode.split(","):
        item = item.strip()
        for pair in PRESETS.get(item, []):
            if pair not in seen:
                seen.add(pair)
                tasks.append(pair)
    tasks = tasks or PRESETS["conservative"]

    if SCREENING_STRATEGIES:
        allowed = {s.strip() for s in SCREENING_STRATEGIES.split(",")}
        tasks = [(sk, preset) for sk, preset in tasks if sk in allowed]
    return tasks


def get_schedule():
    if MANUAL_RUN_AT:
        hour, minute = MANUAL_RUN_AT.split(":")
        run_hour, run_minute = int(hour), int(minute)
    else:
        now = datetime.now()
        if now.weekday() >= 5:
            run_hour, run_minute = 8, 0
        else:
            run_hour, run_minute = 18, 30

    if MANUAL_DAYS_BACK:
        days_back = int(MANUAL_DAYS_BACK)
    else:
        now = datetime.now()
        days_back = 360 if now.weekday() >= 5 else 250
    return run_hour, run_minute, days_back


def run_screening(days_back: int) -> None:
    global _active_child
    if not acquire_screening_lock():
        return

    tasks = get_tasks()
    log.info(
        "Starting screening | mode=%s days_back=%d universe_index=%s tasks=%d holder=%s",
        SCREENING_MODE,
        days_back,
        SCREENING_UNIVERSE_INDEX or "all",
        len(tasks),
        HOLDER_ID,
    )

    try:
        for strategy_key, preset in tasks:
            if _shutdown_requested:
                log.info("Shutdown requested; stopping screening loop")
                break
            log.info("Running: strategy=%s preset=%s", strategy_key, preset)
            cmd = [
                sys.executable,
                "daily_full_market_screening.py",
                "--strategy-key",
                strategy_key,
                "--preset",
                preset,
                "--days-back",
                str(days_back),
                "--initial-cash",
                "1000000",
                "--min-win-rate",
                "0.50",
                "--min-trades",
                "3",
                "--min-return",
                "0.03",
                "--log-level",
                "INFO",
            ]
            if SCREENING_UNIVERSE_INDEX:
                cmd.extend(["--universe-index", SCREENING_UNIVERSE_INDEX])

            _active_child = subprocess.Popen(
                cmd,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
            return_code = _active_child.wait()
            _active_child = None
            if return_code != 0:
                log.error(
                    "Screening task failed: strategy=%s preset=%s returncode=%d",
                    strategy_key,
                    preset,
                    return_code,
                )
            else:
                log.info("Screening task done: strategy=%s preset=%s", strategy_key, preset)
        log.info("All screening tasks complete for today.")
    finally:
        release_screening_lock()


def _terminate_active_child() -> None:
    global _active_child
    if _active_child is None or _active_child.poll() is not None:
        return
    log.info("Terminating active screening subprocess pid=%s", _active_child.pid)
    _active_child.terminate()
    try:
        _active_child.wait(timeout=30)
    except subprocess.TimeoutExpired:
        log.warning("Screening subprocess did not exit; killing pid=%s", _active_child.pid)
        _active_child.kill()
        _active_child.wait(timeout=10)
    _active_child = None


def _handle_signal(signum, _frame) -> None:
    global _shutdown_requested
    log.info("Received signal %s; requesting shutdown", signum)
    _shutdown_requested = True
    _terminate_active_child()
    release_screening_lock()
    if signum == signal.SIGTERM:
        sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log.info("Screening scheduler started | mode=%s holder=%s", SCREENING_MODE, HOLDER_ID)
    already_ran_today = ""

    while not _shutdown_requested:
        run_hour, run_minute, days_back = get_schedule()
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        if now.hour == run_hour and now.minute == run_minute and already_ran_today != today_str:
            already_ran_today = today_str
            run_screening(days_back)
        time.sleep(30)

    log.info("Screening scheduler stopped")


if __name__ == "__main__":
    main()
