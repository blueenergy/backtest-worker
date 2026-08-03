#!/usr/bin/env python3
"""
Backtest Worker Service

Polls pending backtest tasks from MongoDB, executes them with quant-strategies,
and writes results back. Supports atomic claim, lease fencing, and graceful drain.
"""

import argparse
import json
import logging
import math
import os
import signal
import statistics
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

try:
    from simple_backtest_runner import SimpleBacktestRunner
except ModuleNotFoundError:
    from worker.simple_backtest_runner import SimpleBacktestRunner

try:
    from worker.task_store import HeartbeatTicker, MongoBacktestTaskStore
except ModuleNotFoundError:
    from task_store import HeartbeatTicker, MongoBacktestTaskStore

from quant_strategies.strategies import STRATEGY_MAP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)

HEALTH_FILE = Path(os.getenv("BACKTEST_HEALTH_FILE", "/tmp/backtest_worker_healthy"))


def _normalize_task_date(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return text[:10].replace("-", "")


def _validate_task_dates(start_date: str, end_date: str) -> None:
    if len(start_date) != 8 or not start_date.isdigit():
        raise ValueError(f"Invalid or missing start_date: {start_date or '<empty>'}")
    if len(end_date) != 8 or not end_date.isdigit():
        raise ValueError(f"Invalid or missing end_date: {end_date or '<empty>'}")


def _mask_mongo_uri(uri: str) -> str:
    """Mask credentials before logging a MongoDB URI.

    Anything unrecognised is redacted rather than passed through: this runs on
    the startup log path, so it must neither leak a password nor raise.
    """
    if not uri:
        return ""
    if not isinstance(uri, str):
        return "***"
    for scheme in ("mongodb+srv", "mongodb"):
        prefix = f"{scheme}://"
        if uri.startswith(prefix):
            rest = uri[len(prefix) :]
            break
    else:
        return "***"
    if "@" not in rest:
        return uri
    _, host_and_path = rest.rsplit("@", 1)
    return f"{scheme}://***:***@{host_and_path}"


def touch_health_file() -> None:
    try:
        HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        HEALTH_FILE.touch()
    except OSError as exc:
        log.warning("Could not update health file %s: %s", HEALTH_FILE, exc)


class BacktestWorkerService:
    """Service that polls for backtest tasks and executes them."""

    def __init__(
        self,
        worker_id: Optional[str] = None,
        poll_interval: int = 5,
        access_token: Optional[str] = None,
        worker_token: Optional[str] = None,
        api_base: Optional[str] = None,
        mongo_uri: Optional[str] = None,
        db_name: Optional[str] = None,
        task_store: Optional[MongoBacktestTaskStore] = None,
    ):
        self.api_base = (api_base or "").rstrip("/")
        self.worker_id = worker_id or f"worker_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.poll_interval = poll_interval
        self.worker_token = worker_token or access_token
        self.running = False
        self.draining = False
        self.task_store = task_store or MongoBacktestTaskStore(mongo_uri=mongo_uri, db_name=db_name)
        self.runner = SimpleBacktestRunner()
        self._active_task: Optional[Dict[str, Any]] = None
        self._reap_interval = max(30, int(os.getenv("BACKTEST_REAP_INTERVAL_SECONDS", "60")))
        self._last_reap_at = 0.0

        log.info("Initialized BacktestWorkerService: %s", self.worker_id)

    def startup(self) -> None:
        self.task_store.ensure_indexes()
        reclaimed = self.task_store.requeue_own_orphans(self.worker_id)
        if reclaimed:
            log.info("Requeued %d orphaned tasks for restarted worker %s", reclaimed, self.worker_id)
        self.task_store.record_worker_status(
            self.worker_id,
            "idle",
            {"current_task_id": None, "last_message": "worker started"},
        )
        touch_health_file()

    def poll_tasks(self) -> Optional[Dict[str, Any]]:
        if self.draining:
            return None
        try:
            task = self.task_store.claim_task(self.worker_id)
            if task:
                log.info("Claimed task: %s", task.get("task_id"))
            return task
        except Exception as exc:
            log.error("Error claiming task: %s", exc)
            return None

    def execute_backtest(self, task: Dict[str, Any]) -> Dict[str, Any]:
        task_id = task["task_id"]
        symbol = task["symbol"]
        asset_type = (task.get("asset_type") or "stock").lower()
        strategy_key = task["strategy_key"]
        start_date = _normalize_task_date(task.get("start_date"))
        end_date = _normalize_task_date(task.get("end_date"))
        strategy_params = task.get("strategy_params", {})
        preset_name = task.get("preset")
        initial_cash = task.get("initial_cash", 1000000)

        log.info("Executing backtest for %s (%s, %s to %s)", symbol, asset_type, start_date, end_date)
        log.info("Strategy: %s, Params: %s", strategy_key, strategy_params)
        log.info("Preset: %s", preset_name)
        log.info("Initial cash: %s", initial_cash)

        _validate_task_dates(start_date, end_date)
        if strategy_key not in STRATEGY_MAP:
            raise ValueError(
                f"Unknown strategy: {strategy_key}. Available: {list(STRATEGY_MAP.keys())}"
            )

        strategy_class = STRATEGY_MAP[strategy_key]
        log.info("Using strategy class: %s", strategy_class.__name__)
        raw_results = self.runner.run_backtest(
            symbol=symbol,
            strategy_class=strategy_class,
            strategy_params=strategy_params,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            preset_name=preset_name,
            asset_type=asset_type,
        )
        results = self._format_results(raw_results)
        log.info("Backtest completed for %s", task_id)
        return results

    def _format_results(self, raw_results: Dict[str, Any]) -> Dict[str, Any]:
        metrics = raw_results.get("metrics", {})
        log.info(
            "Results: Return=%.2f%%, MaxDD=%.2f%%, WinRate=%.2f%%, Trades=%s",
            metrics.get("total_return", 0),
            metrics.get("max_drawdown", 0),
            metrics.get("win_rate", 0),
            metrics.get("total_trades", 0),
        )
        return raw_results

    def report_success(self, task_id: str, lease_token: str, results: Dict[str, Any]) -> bool:
        return self.task_store.report_success(task_id, self.worker_id, lease_token, results)

    def report_failure(self, task_id: str, lease_token: str, error_message: str) -> bool:
        return self.task_store.report_failure(task_id, self.worker_id, lease_token, error_message)

    def release_active_task(self, message: str) -> bool:
        task = self._active_task
        if not task:
            return False
        released = self.task_store.release_task(
            task["task_id"],
            self.worker_id,
            task["lease_token"],
            message,
        )
        if released:
            log.info("Released task %s: %s", task["task_id"], message)
        self._active_task = None
        return released

    def process_task(self, task: Dict[str, Any]) -> bool:
        task_id = task["task_id"]
        lease_token = task.get("lease_token")
        if not lease_token:
            log.error("Task %s missing lease_token after claim", task_id)
            return False

        self._active_task = task
        ticker = HeartbeatTicker(self.task_store, task_id, self.worker_id, lease_token).start()
        self.task_store.record_worker_status(
            self.worker_id,
            "running",
            {"current_task_id": task_id, "last_message": "executing backtest"},
        )

        try:
            if self.draining:
                self.release_active_task("requeued during drain")
                return False

            results = self.execute_backtest(task)
            if self.draining:
                self.release_active_task("requeued after execution during drain")
                return False
            return self.report_success(task_id, lease_token, results)
        except Exception as exc:
            error_msg = f"Backtest execution failed: {exc}"
            log.error("Error processing task %s: %s", task_id, error_msg, exc_info=True)
            if self.draining:
                self.release_active_task(f"requeued after failure during drain: {exc}")
                return False
            self.report_failure(task_id, lease_token, error_msg)
            return False
        finally:
            ticker.stop()
            self._active_task = None
            self.task_store.record_worker_status(
                self.worker_id,
                "draining" if self.draining else "idle",
                {"current_task_id": None, "last_message": "task finished"},
            )
            touch_health_file()

    def maybe_reap_expired(self) -> None:
        now = time.monotonic()
        if now - self._last_reap_at < self._reap_interval:
            return
        self._last_reap_at = now
        self.task_store.reset_expired_jobs()

    def run(self) -> None:
        self.running = True
        self.startup()
        log.info("Starting backtest worker: %s", self.worker_id)
        log.info("MongoDB: %s/%s", _mask_mongo_uri(self.task_store.mongo_uri), self.task_store.db_name)
        log.info("Poll interval: %ss", self.poll_interval)

        while self.running:
            try:
                touch_health_file()
                self.maybe_reap_expired()
                # process_task already released any in-flight task once drain
                # started, so reaching the top of the loop means we are done.
                if self.draining:
                    log.info("Drain finished; worker %s leaving claim loop", self.worker_id)
                    self.running = False
                    break

                task = self.poll_tasks()
                if task:
                    self.process_task(task)
                else:
                    self.task_store.record_worker_status(
                        self.worker_id,
                        "idle",
                        {"current_task_id": None, "last_message": "no pending task"},
                    )
                    time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                log.info("Received interrupt signal, shutting down...")
                self.running = False
            except Exception as exc:
                log.error("Unexpected error in main loop: %s", exc, exc_info=True)
                time.sleep(self.poll_interval)

        self.release_active_task("requeued on worker shutdown")
        self.task_store.record_worker_status(
            self.worker_id,
            "stopped",
            {"current_task_id": None, "last_message": "worker stopped"},
        )
        log.info("Backtest worker stopped")

    def stop(self, draining: bool = False) -> None:
        if draining:
            self.draining = True
            log.info("Worker %s entering drain mode", self.worker_id)
            self.task_store.record_worker_status(
                self.worker_id,
                "draining",
                {"current_task_id": self._active_task and self._active_task.get("task_id"), "last_message": "draining"},
            )
        else:
            self.running = False


def load_config(config_path: str) -> Dict[str, Any]:
    try:
        with open(config_path, "r") as handle:
            config = json.load(handle)
        log.info("Loaded configuration from %s", config_path)
        return config
    except FileNotFoundError:
        log.error("Config file not found: %s", config_path)
        log.info("Please copy config.example.json to config.json and fill in your values")
        sys.exit(1)
    except json.JSONDecodeError as exc:
        log.error("Invalid JSON in config file: %s", exc)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest Worker Service")
    parser.add_argument("--config", help="Path to config.json file")
    parser.add_argument("--api-base", help="Deprecated; tasks are read directly from MongoDB")
    parser.add_argument("--mongo-uri", help="MongoDB connection URI")
    parser.add_argument("--db-name", help="MongoDB database for backtest tasks/results")
    parser.add_argument("--worker-id", help="Unique identifier for this worker")
    parser.add_argument("--poll-interval", type=float, help="Seconds between poll attempts")
    parser.add_argument("--token", help="Deprecated")
    parser.add_argument("--worker-token", help="Deprecated")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level",
    )
    parser.add_argument("--test", action="store_true", help="Verify config and Mongo connectivity")
    args = parser.parse_args()

    config: Dict[str, Any] = {}
    if args.config:
        config = load_config(args.config)
    elif Path("config.json").exists():
        log.info("Found config.json in current directory")
        config = load_config("config.json")

    mongo_uri = args.mongo_uri or os.getenv("MONGO_URI") or config.get("mongo_uri")
    db_name = (
        args.db_name
        or os.getenv("BACKTEST_DB_NAME")
        or os.getenv("DB_NAME")
        or config.get("db_name")
        or config.get("backtest_db_name")
        or "finance"
    )
    worker_id = args.worker_id or config.get("worker_id")
    poll_interval = args.poll_interval or config.get("poll_interval", 5.0)
    worker_token = args.worker_token or args.token or config.get("worker_token") or config.get("api_token")
    log_level = args.log_level or config.get("log_level", "INFO")
    logging.getLogger().setLevel(getattr(logging, log_level))

    if worker_token:
        log.warning("worker_token is deprecated and ignored; backtest tasks are read from MongoDB")

    worker = BacktestWorkerService(
        api_base=args.api_base or config.get("api_base_url"),
        worker_id=worker_id,
        poll_interval=poll_interval,
        worker_token=worker_token,
        mongo_uri=mongo_uri,
        db_name=db_name,
    )

    if args.test:
        log.info("Running in TEST mode")
        worker.task_store.db.command("ping")
        pending = worker.task_store.pending_count()
        log.info("MongoDB OK; pending tasks=%s", pending)
        sys.exit(0)

    def signal_handler(signum, _frame) -> None:
        log.info("Received signal %s", signum)
        if signum == signal.SIGTERM:
            worker.stop(draining=True)
        else:
            worker.stop(draining=False)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        worker.run()
    except Exception as exc:
        log.error("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
