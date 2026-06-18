#!/usr/bin/env python3
"""
Backtest Worker Service

This service polls pending backtest tasks from MongoDB, executes them
using quant-strategies, and writes results back to MongoDB.

Usage:
    # Use config file (recommended)
    python backtest_worker.py --config config.json
    
    # Use command line arguments
    python backtest_worker.py --worker-id WORKER_ID
"""

import sys
import time
import json
import argparse
import logging
import signal
import statistics
import os
import math
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Dict, Any
from pymongo import MongoClient

# Add parent directory to path for strategy imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

try:
    from simple_backtest_runner import SimpleBacktestRunner
except ModuleNotFoundError:
    from worker.simple_backtest_runner import SimpleBacktestRunner
from quant_strategies.strategies import STRATEGY_MAP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


def _normalize_task_date(value: Any) -> str:
    """Return YYYYMMDD for task dates, or empty string when missing."""
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


def _clean_for_mongo(value: Any) -> Any:
    """Normalize worker result values before writing them to MongoDB."""
    if value is None or isinstance(value, (str, bool, datetime, date)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int):
        if -(2 ** 63) <= value <= (2 ** 63 - 1):
            return value
        return str(value)
    if isinstance(value, dict):
        return {str(k): _clean_for_mongo(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_for_mongo(v) for v in value]
    if hasattr(value, "item"):
        try:
            return _clean_for_mongo(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


class MongoBacktestTaskStore:
    """MongoDB-backed task queue for backtest workers."""

    def __init__(
        self,
        mongo_uri: Optional[str] = None,
        db_name: Optional[str] = None,
        db: Any = None,
    ):
        self.mongo_uri = mongo_uri or os.getenv("MONGO_URI", "mongodb://localhost:27017")
        self.db_name = db_name or os.getenv("BACKTEST_DB_NAME") or os.getenv("DB_NAME") or "finance"
        self._client = None if db is not None else MongoClient(self.mongo_uri)
        self.db = db or self._client[self.db_name]
        self.backtest_tasks = self.db["backtest_tasks"]
        self.backtest_results = self.db["backtest_results"]

    def poll_task(self) -> Optional[Dict[str, Any]]:
        """Return the oldest valid pending task without claiming it."""
        cursor = (
            self.backtest_tasks
            .find({
                "status": "pending",
                "start_date": {"$nin": ["", None]},
                "end_date": {"$nin": ["", None]},
            })
            .sort("created_at", 1)
            .limit(1)
        )
        task = next(iter(cursor), None)
        if not task:
            return None
        return {
            "task_id": task["task_id"],
            "user_id": str(task.get("user_id", "")),
            "symbol": task["symbol"],
            "asset_type": (task.get("asset_type") or "stock").lower(),
            "strategy_key": task["strategy_key"],
            "preset": task.get("preset"),
            "strategy_params": task.get("strategy_params", {}),
            "start_date": task["start_date"],
            "end_date": task["end_date"],
            "initial_cash": task.get("initial_cash", 1000000.0),
            "created_at": task.get("created_at"),
        }

    def claim_task(self, task_id: str, worker_id: str) -> bool:
        result = self.backtest_tasks.update_one(
            {"task_id": task_id, "status": "pending"},
            {
                "$set": {
                    "status": "claimed",
                    "worker_id": worker_id,
                    "started_at": datetime.now(),
                }
            },
        )
        return result.modified_count > 0

    def report_success(self, task_id: str, results: Dict[str, Any]) -> bool:
        task = self.backtest_tasks.find_one({"task_id": task_id})
        if not task:
            log.error(f"Backtest task not found: {task_id}")
            return False
        if task.get("status") not in ["claimed", "running"]:
            log.error(f"Cannot report results for task {task_id} in status: {task.get('status')}")
            return False

        result_doc = _clean_for_mongo({
            "task_id": task_id,
            "user_id": task.get("user_id"),
            "symbol": task.get("symbol"),
            "asset_type": (task.get("asset_type") or "stock").lower(),
            "strategy_key": task.get("strategy_key"),
            "preset": task.get("preset"),
            "strategy_params": task.get("strategy_params", {}),
            "batch_id": task.get("batch_id"),
            "metrics": results.get("metrics", {}),
            "trades": results.get("trades", []),
            "equity_curve": results.get("equity_curve", []),
            "created_at": datetime.now(),
        })

        try:
            self.backtest_results.update_one(
                {"task_id": task_id},
                {"$set": result_doc},
                upsert=True,
            )
            self.backtest_tasks.update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        "status": "completed",
                        "completed_at": datetime.now(),
                    }
                },
            )
            return True
        except Exception as exc:
            log.error(f"Failed to persist backtest result for {task_id}: {exc}", exc_info=True)
            self.backtest_tasks.update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        "status": "failed",
                        "error_message": f"Failed to persist backtest result: {exc}",
                        "completed_at": datetime.now(),
                    }
                },
            )
            return False

    def report_failure(self, task_id: str, error_message: str) -> bool:
        result = self.backtest_tasks.update_one(
            {"task_id": task_id},
            {
                "$set": {
                    "status": "failed",
                    "error_message": error_message or "Backtest failed",
                    "completed_at": datetime.now(),
                }
            },
        )
        return result.modified_count > 0


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
        """
        Initialize the backtest worker service.
        
        Args:
            worker_id: Unique identifier for this worker
            poll_interval: Seconds to wait between polling
            mongo_uri: MongoDB connection URI
            db_name: MongoDB database containing backtest_tasks/results
        """
        self.api_base = (api_base or "").rstrip("/")
        self.worker_id = worker_id or f"worker_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.poll_interval = poll_interval
        # Deprecated API auth args are accepted only for old configs/callers.
        self.worker_token = worker_token or access_token
        self.running = False
        self.task_store = task_store or MongoBacktestTaskStore(mongo_uri=mongo_uri, db_name=db_name)
        
        # Create runner instance
        self.runner = SimpleBacktestRunner()
        
        log.info(f"Initialized BacktestWorkerService: {self.worker_id}")
    
    def poll_tasks(self) -> Optional[Dict[str, Any]]:
        """
        Poll for pending backtest tasks from MongoDB.
        
        Returns:
            Task data if available, None otherwise
        """
        try:
            task = self.task_store.poll_task()
            if task:
                log.info(f"Found pending task: {task.get('task_id')}")
            return task
        except Exception as e:
            log.error(f"Error polling tasks: {e}")
            return None
    
    def claim_task(self, task_id: str) -> bool:
        """
        Claim a backtest task.
        
        Args:
            task_id: ID of the task to claim
            
        Returns:
            True if claimed successfully, False otherwise
        """
        try:
            if self.task_store.claim_task(task_id, self.worker_id):
                log.info(f"Successfully claimed task: {task_id}")
                return True
            log.warning(f"Failed to claim task {task_id}: already claimed or not pending")
            return False
        except Exception as e:
            log.error(f"Error claiming task {task_id}: {e}")
            return False
    
    def execute_backtest(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a backtest task using quant-strategies.
        
        Args:
            task: Task data including symbol, strategy, dates, params
            
        Returns:
            Backtest results including metrics, trades, and equity curve
        """
        task_id = task['task_id']
        symbol = task['symbol']
        asset_type = (task.get('asset_type') or 'stock').lower()
        strategy_key = task['strategy_key']
        start_date = _normalize_task_date(task.get('start_date'))
        end_date = _normalize_task_date(task.get('end_date'))
        strategy_params = task.get('strategy_params', {})
        preset_name = task.get('preset')
        initial_cash = task.get('initial_cash', 1000000)
        
        log.info(f"Executing backtest for {symbol} ({asset_type}, {start_date} to {end_date})")
        log.info(f"Strategy: {strategy_key}, Params: {strategy_params}")
        log.info(f"Preset: {preset_name}")
        log.info(f"Initial cash: {initial_cash}")
        
        try:
            _validate_task_dates(start_date, end_date)

            # Get strategy class from STRATEGY_MAP
            if strategy_key not in STRATEGY_MAP:
                raise ValueError(f"Unknown strategy: {strategy_key}. Available: {list(STRATEGY_MAP.keys())}")
            
            strategy_class = STRATEGY_MAP[strategy_key]
            log.info(f"Using strategy class: {strategy_class.__name__}")
            
            # Run backtest using SimpleBacktestRunner
            log.info("Starting backtest execution...")
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
            log.info("Backtest execution completed")
            
            # Format results with metrics
            results = self._format_results(raw_results)
            
            log.info(f"Backtest completed for {task_id}")
            return results
            
        except Exception as e:
            log.error(f"Error executing backtest {task_id}: {e}", exc_info=True)
            raise
    
    def _format_results(self, raw_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format backtest results with metrics.
        
        Args:
            raw_results: Raw results from SimpleBacktestRunner
            
        Returns:
            Formatted results dict with metrics
        """
        # SimpleBacktestRunner already returns API-compatible format:
        # {'metrics': {...}, 'trades': [...], 'equity_curve': [...]}
        
        # Extract metrics for logging
        metrics = raw_results.get('metrics', {})
        total_return = metrics.get('total_return', 0)
        max_drawdown = metrics.get('max_drawdown', 0)
        win_rate = metrics.get('win_rate', 0)
        total_trades = metrics.get('total_trades', 0)
        
        log.info(f"Results: Return={total_return:.2f}%, MaxDD={max_drawdown:.2f}%, "
                f"WinRate={win_rate:.2f}%, Trades={total_trades}")
        
        return raw_results
    
    def report_success(self, task_id: str, results: Dict[str, Any]) -> bool:
        """
        Report successful backtest results to MongoDB.
        
        Args:
            task_id: ID of the completed task
            results: Backtest results in API format (metrics, trades, equity_curve)
            
        Returns:
            True if reported successfully, False otherwise
        """
        try:
            if self.task_store.report_success(task_id, results):
                log.info(f"Successfully reported results for {task_id}")
                return True
            log.error(f"Failed to report results for {task_id}")
            return False
        except Exception as e:
            log.error(f"Error reporting results for {task_id}: {e}")
            return False
    
    def report_failure(self, task_id: str, error_message: str) -> bool:
        """
        Report failed backtest to MongoDB.
        
        Args:
            task_id: ID of the failed task
            error_message: Error description
            
        Returns:
            True if reported successfully, False otherwise
        """
        try:
            if self.task_store.report_failure(task_id, error_message):
                log.info(f"Successfully reported failure for {task_id}")
                return True
            log.error(f"Failed to report failure for {task_id}: task not found")
            return False
        except Exception as e:
            log.error(f"Error reporting failure for {task_id}: {e}")
            return False
    
    def process_task(self, task: Dict[str, Any]) -> bool:
        """
        Process a single backtest task.
        
        Args:
            task: Task data
            
        Returns:
            True if processed successfully, False otherwise
        """
        task_id = task['task_id']
        
        try:
            # Claim the task
            if not self.claim_task(task_id):
                log.warning(f"Could not claim task {task_id}, skipping")
                return False
            
            # Execute backtest
            results = self.execute_backtest(task)
            
            # Report success
            return self.report_success(task_id, results)
            
        except Exception as e:
            error_msg = f"Backtest execution failed: {str(e)}"
            log.error(f"Error processing task {task_id}: {error_msg}", exc_info=True)
            
            # Report failure
            self.report_failure(task_id, error_msg)
            return False
    
    def run(self):
        """Main worker loop."""
        self.running = True
        log.info(f"Starting backtest worker: {self.worker_id}")
        log.info(f"MongoDB: {self.task_store.mongo_uri}/{self.task_store.db_name}")
        log.info(f"Poll Interval: {self.poll_interval}s")
        
        while self.running:
            try:
                # Poll for pending tasks
                task = self.poll_tasks()
                
                if task:
                    # Process the task
                    self.process_task(task)
                else:
                    # No tasks available, wait before polling again
                    time.sleep(self.poll_interval)
                    
            except KeyboardInterrupt:
                log.info("Received interrupt signal, shutting down...")
                self.running = False
            except Exception as e:
                log.error(f"Unexpected error in main loop: {e}", exc_info=True)
                time.sleep(self.poll_interval)
        
        log.info("Backtest worker stopped")
    
    def stop(self):
        """Stop the worker."""
        self.running = False


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load configuration from JSON file.
    
    Args:
        config_path: Path to config.json file
        
    Returns:
        Configuration dictionary
    """
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        log.info(f"Loaded configuration from {config_path}")
        return config
    except FileNotFoundError:
        log.error(f"Config file not found: {config_path}")
        log.info("Please copy config.example.json to config.json and fill in your values")
        sys.exit(1)
    except json.JSONDecodeError as e:
        log.error(f"Invalid JSON in config file: {e}")
        sys.exit(1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Backtest Worker Service',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use config file (recommended)
  python backtest_worker.py --config config.json
  
  # Override with command line arguments
  python backtest_worker.py --config config.json --worker-id my_worker
  
  # Use only command line arguments
  python backtest_worker.py --mongo-uri mongodb://localhost:27017 --db-name finance
        """
    )
    parser.add_argument(
        '--config',
        help='Path to config.json file (recommended)'
    )
    parser.add_argument(
        '--api-base',
        help='Deprecated; tasks are read directly from MongoDB'
    )
    parser.add_argument(
        '--mongo-uri',
        help='MongoDB connection URI (overrides MONGO_URI/config)'
    )
    parser.add_argument(
        '--db-name',
        help='MongoDB database for backtest tasks/results (overrides BACKTEST_DB_NAME/DB_NAME/config)'
    )
    parser.add_argument(
        '--worker-id',
        help='Unique identifier for this worker (overrides config)'
    )
    parser.add_argument(
        '--poll-interval',
        type=float,
        help='Seconds to wait between polling for tasks (overrides config)'
    )
    parser.add_argument(
        '--token',
        help='Deprecated; API task polling is no longer used'
    )
    parser.add_argument(
        '--worker-token',
        help='Deprecated; API task polling is no longer used'
    )
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Log level (overrides config)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test configuration and connection, then exit'
    )
    
    args = parser.parse_args()
    
    # Load config from file if specified
    config = {}
    if args.config:
        config = load_config(args.config)
    elif Path('config.json').exists():
        log.info("Found config.json in current directory")
        config = load_config('config.json')
    
    # Command line arguments override config file
    api_base = args.api_base or config.get('api_base_url')
    mongo_uri = args.mongo_uri or os.getenv("MONGO_URI") or config.get("mongo_uri")
    db_name = (
        args.db_name
        or os.getenv("BACKTEST_DB_NAME")
        or os.getenv("DB_NAME")
        or config.get("db_name")
        or config.get("backtest_db_name")
        or "finance"
    )
    worker_id = args.worker_id or config.get('worker_id')
    poll_interval = args.poll_interval or config.get('poll_interval', 5.0)
    worker_token = (
        args.worker_token
        or args.token
        or config.get('worker_token')
        or config.get('api_token')
    )
    log_level = args.log_level or config.get('log_level', 'INFO')
    
    # Update log level
    logging.getLogger().setLevel(getattr(logging, log_level))
    if worker_token:
        log.warning("worker_token is deprecated and ignored; backtest tasks are read from MongoDB")
    
    # Create worker service
    worker = BacktestWorkerService(
        api_base=api_base,
        worker_id=worker_id,
        poll_interval=poll_interval,
        worker_token=worker_token,
        mongo_uri=mongo_uri,
        db_name=db_name,
    )
    
    # Test mode: verify configuration and connection, then exit
    if args.test:
        log.info("=" * 60)
        log.info("Running in TEST mode - will verify config and exit")
        log.info("=" * 60)
        log.info(f"Mongo URI: {worker.task_store.mongo_uri}")
        log.info(f"Backtest DB: {worker.task_store.db_name}")
        log.info(f"Worker ID: {worker_id or '(auto-generated)'}")
        log.info(f"Poll Interval: {poll_interval}s")
        log.info("")
        
        log.info("Testing MongoDB connection...")
        try:
            worker.task_store.db.command("ping")
            task = worker.poll_tasks()
            log.info("✅ MongoDB connection successful!")
            if task:
                log.info(f"✅ Found pending task: {task.get('task_id')}")
            else:
                log.info("✅ No pending tasks (this is OK)")
        except Exception as e:
            log.error(f"❌ Test failed: {e}", exc_info=True)
            sys.exit(1)
        
        log.info("")
        log.info("=" * 60)
        log.info("✅ Configuration test passed!")
        log.info("=" * 60)
        log.info("To run the worker normally, use: ./start.sh")
        sys.exit(0)
    
    # Handle shutdown signals
    def signal_handler(signum, frame):
        log.info(f"Received signal {signum}, stopping worker...")
        worker.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run worker
    try:
        worker.run()
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
