#!/usr/bin/env python3
"""
Backtest Worker Service

This service polls for pending backtest tasks from the server,
executes them using quant-strategies, and reports results back.

Usage:
    # Use config file (recommended)
    python backtest_worker.py --config config.json
    
    # Use command line arguments
    python backtest_worker.py --worker-id WORKER_ID --token TOKEN
"""

import sys
import time
import json
import argparse
import logging
import signal
import statistics
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import requests

from worker.simple_backtest_runner import SimpleBacktestRunner
from strategies import STRATEGY_MAP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


class BacktestWorkerService:
    """Service that polls for backtest tasks and executes them."""
    
    def __init__(
        self,
        api_base: str = "http://localhost:3001/api",
        worker_id: Optional[str] = None,
        poll_interval: int = 5,
        access_token: Optional[str] = None
    ):
        """
        Initialize the backtest worker service.
        
        Args:
            api_base: Base URL of the API server
            worker_id: Unique identifier for this worker
            poll_interval: Seconds to wait between polling
            access_token: Authentication token for API requests
        """
        self.api_base = api_base.rstrip('/')
        self.worker_id = worker_id or f"worker_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.poll_interval = poll_interval
        self.access_token = access_token
        self.running = False
        
        # Create runner instance
        self.runner = SimpleBacktestRunner()
        
        log.info(f"Initialized BacktestWorkerService: {self.worker_id}")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for API requests."""
        headers = {'Content-Type': 'application/json'}
        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        return headers
    
    def poll_tasks(self) -> Optional[Dict[str, Any]]:
        """
        Poll for pending backtest tasks.
        
        Returns:
            Task data if available, None otherwise
        """
        try:
            response = requests.get(
                f"{self.api_base}/backtest/tasks/pending/poll",
                headers=self._get_headers(),
                params={'worker_id': self.worker_id},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Handle both list and dict responses
                if isinstance(data, list):
                    if data:  # Non-empty list, return first task
                        task = data[0]
                        log.info(f"Found pending task: {task.get('task_id')}")
                        return task
                    return None
                elif isinstance(data, dict) and data:  # Non-empty dict
                    log.info(f"Found pending task: {data.get('task_id')}")
                    return data
                else:
                    return None
                    
            elif response.status_code == 204:
                # No tasks available
                return None
            else:
                log.error(f"Poll failed: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
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
            response = requests.post(
                f"{self.api_base}/backtest/tasks/{task_id}/claim",
                headers=self._get_headers(),
                params={'worker_id': self.worker_id},  # Send as query parameter
                timeout=10
            )
            
            if response.status_code == 200:
                log.info(f"Successfully claimed task: {task_id}")
                return True
            else:
                log.warning(f"Failed to claim task {task_id}: {response.status_code}")
                if response.status_code == 422:
                    log.error(f"Validation error: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
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
        strategy_key = task['strategy_key']
        start_date = task['start_date']
        end_date = task['end_date']
        strategy_params = task.get('strategy_params', {})
        initial_cash = task.get('initial_cash', 1000000)
        
        log.info(f"Executing backtest for {symbol} ({start_date} to {end_date})")
        log.info(f"Strategy: {strategy_key}, Params: {strategy_params}")
        log.info(f"Initial cash: {initial_cash}")
        
        try:
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
                initial_cash=initial_cash
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
        initial_cash = raw_results['initial_cash']
        final_value = raw_results['final_value']
        equity_curve = raw_results['equity_curve']
        trades = raw_results['trades']
        
        # Calculate total return
        total_return = (final_value - initial_cash) / initial_cash if initial_cash > 0 else 0
        
        # Calculate max drawdown
        max_drawdown = 0.0
        if equity_curve:
            peak = equity_curve[0]['value']
            for point in equity_curve:
                value = point['value']
                if value > peak:
                    peak = value
                drawdown = (value - peak) / peak
                if drawdown < max_drawdown:
                    max_drawdown = drawdown
        
        # Calculate win rate
        win_rate = 0.0
        total_trades = len(trades)
        if total_trades > 0:
            # Assume trades are dicts with 'pnl' key, or lists [entry_price, exit_price]
            winning_trades = 0
            for trade in trades:
                if isinstance(trade, dict) and trade.get('pnl', 0) > 0:
                    winning_trades += 1
                elif isinstance(trade, (list, tuple)) and len(trade) >= 2:
                    # [entry_price, exit_price]
                    if trade[1] > trade[0]:
                        winning_trades += 1
            win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # Calculate Sharpe ratio (simplified)
        sharpe_ratio = None
        if equity_curve and len(equity_curve) > 1:
            returns = []
            for i in range(1, len(equity_curve)):
                curr = equity_curve[i]['value']
                prev = equity_curve[i-1]['value']
                ret = (curr - prev) / prev if prev > 0 else 0
                returns.append(ret)
            
            if len(returns) > 1:
                mean_return = statistics.mean(returns)
                std_return = statistics.stdev(returns)
                sharpe_ratio = (mean_return / std_return * (252 ** 0.5)) if std_return > 0 else 0
        
        # Profit/loss ratio
        profit_loss_ratio = None
        winning_pnl = 0
        losing_pnl = 0
        for trade in trades:
            if isinstance(trade, dict) and 'pnl' in trade:
                pnl = trade['pnl']
                if pnl > 0:
                    winning_pnl += pnl
                else:
                    losing_pnl += abs(pnl)
        
        if losing_pnl > 0:
            profit_loss_ratio = winning_pnl / losing_pnl
        
        # Format results
        results = {
            'metrics': {
                'total_return': round(total_return, 4),
                'max_drawdown': round(max_drawdown, 4),
                'win_rate': round(win_rate, 4),
                'sharpe_ratio': round(sharpe_ratio, 2) if sharpe_ratio is not None else None,
                'total_trades': total_trades,
                'profit_loss_ratio': round(profit_loss_ratio, 2) if profit_loss_ratio is not None else None,
                'final_value': round(final_value, 2),
                'total_profit': round(final_value - initial_cash, 2)
            },
            'equity_curve': equity_curve,
            'trades': trades,
            'strategy_name': raw_results.get('strategy_name', 'Unknown')
        }
        
        log.info(f"Results: Return={total_return:.2%}, MaxDD={max_drawdown:.2%}, "
                f"WinRate={win_rate:.2%}, Trades={total_trades}")
        
        return results
    
    def report_success(self, task_id: str, results: Dict[str, Any]) -> bool:
        """
        Report successful backtest results to server.
        
        Args:
            task_id: ID of the completed task
            results: Backtest results
            
        Returns:
            True if reported successfully, False otherwise
        """
        try:
            response = requests.post(
                f"{self.api_base}/backtest/tasks/{task_id}/report",
                headers=self._get_headers(),
                json={
                    'worker_id': self.worker_id,
                    'status': 'completed',
                    'result_data': results
                },
                timeout=30
            )
            
            if response.status_code == 200:
                log.info(f"Successfully reported results for {task_id}")
                return True
            else:
                log.error(f"Failed to report results for {task_id}: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            log.error(f"Error reporting results for {task_id}: {e}")
            return False
    
    def report_failure(self, task_id: str, error_message: str) -> bool:
        """
        Report failed backtest to server.
        
        Args:
            task_id: ID of the failed task
            error_message: Error description
            
        Returns:
            True if reported successfully, False otherwise
        """
        try:
            response = requests.post(
                f"{self.api_base}/backtest/tasks/{task_id}/fail",
                headers=self._get_headers(),
                json={
                    'worker_id': self.worker_id,
                    'error_message': error_message
                },
                timeout=10
            )
            
            if response.status_code == 200:
                log.info(f"Successfully reported failure for {task_id}")
                return True
            else:
                log.error(f"Failed to report failure for {task_id}: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
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
        log.info(f"API Base: {self.api_base}")
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
  
  # Use only command line arguments (not recommended)
  python backtest_worker.py --api-base http://localhost:3001/api --token YOUR_TOKEN
        """
    )
    parser.add_argument(
        '--config',
        help='Path to config.json file (recommended)'
    )
    parser.add_argument(
        '--api-base',
        help='Base URL of the API server (overrides config)'
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
        help='Access token for API authentication (overrides config)'
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
    api_base = args.api_base or config.get('api_base_url', 'http://localhost:3001/api')
    worker_id = args.worker_id or config.get('worker_id')
    poll_interval = args.poll_interval or config.get('poll_interval', 5.0)
    access_token = args.token or config.get('api_token')
    log_level = args.log_level or config.get('log_level', 'INFO')
    
    # Update log level
    logging.getLogger().setLevel(getattr(logging, log_level))
    
    # Validate required parameters
    if not access_token:
        log.error("Access token is required!")
        log.info("Please provide token via --token argument or in config.json")
        log.info("Get your token from: User Profile -> API Token Management")
        sys.exit(1)
    
    # Create worker service
    worker = BacktestWorkerService(
        api_base=api_base,
        worker_id=worker_id,
        poll_interval=poll_interval,
        access_token=access_token
    )
    
    # Test mode: verify configuration and connection, then exit
    if args.test:
        log.info("=" * 60)
        log.info("Running in TEST mode - will verify config and exit")
        log.info("=" * 60)
        log.info(f"API Base: {api_base}")
        log.info(f"Worker ID: {worker_id or '(auto-generated)'}")
        log.info(f"Poll Interval: {poll_interval}s")
        log.info(f"Token: {'*' * 20}...{access_token[-10:] if len(access_token) > 10 else '***'}")
        log.info("")
        
        # Test API connection
        log.info("Testing API connection...")
        try:
            response = requests.get(
                f"{api_base}/backtest/tasks/pending/poll",
                headers={'Authorization': f'Bearer {access_token}'},
                timeout=10
            )
            log.info(f"Received response: {response.status_code}")
            
            if response.status_code == 200:
                log.info("✅ API connection successful!")
                task = response.json()
                # API returns a list or single object
                if isinstance(task, list):
                    if task:  # Non-empty list
                        log.info(f"✅ Found {len(task)} pending task(s)")
                        log.info(f"   First task: {task[0].get('task_id')}")
                    else:
                        log.info("✅ No pending tasks (this is OK)")
                elif isinstance(task, dict):
                    if task:  # Non-empty dict
                        log.info(f"✅ Found pending task: {task.get('task_id')}")
                    else:
                        log.info("✅ No pending tasks (this is OK)")
                else:
                    log.info("✅ No pending tasks (this is OK)")
            elif response.status_code == 403:
                log.error("❌ Authentication failed - invalid token")
                log.info("Please check your api_token in config.json")
                sys.exit(1)
            else:
                log.warning(f"⚠️  Unexpected response: {response.status_code}")
                log.info(f"Response: {response.text}")
        except requests.exceptions.ConnectionError as e:
            log.error(f"❌ Cannot connect to API server: {e}")
            log.info(f"Please check if server is running at: {api_base}")
            sys.exit(1)
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
