#!/usr/bin/env python3
"""Unit tests for backtest-worker components.

This tests the core functionality of the backtest worker system:
- SimpleBacktestRunner functionality
- BacktestWorkerService MongoDB task interactions
- Configuration loading
- Error handling
"""

import sys
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import pandas as pd
import backtrader as bt

# Add worker to path
sys.path.insert(0, str(Path(__file__).parent))

from worker.simple_backtest_runner import SimpleBacktestRunner
from worker.backtest_worker import BacktestWorkerService, load_config


def test_simple_runner_initialization():
    """Test that SimpleBacktestRunner can be initialized."""
    runner = SimpleBacktestRunner()
    assert runner is not None
    assert runner.data_loader is not None
    print("✅ SimpleBacktestRunner initialized successfully")


def test_runner_create_data_feed():
    """Test that _create_data_feed works correctly."""
    runner = SimpleBacktestRunner()
    
    # Create test data
    dates = pd.date_range(start='2023-01-01', periods=10, freq='D')
    df = pd.DataFrame({
        'open': [100 + i for i in range(10)],
        'high': [101 + i for i in range(10)],
        'low': [99 + i for i in range(10)],
        'close': [100.5 + i for i in range(10)],
        'volume': [1000] * 10
    }, index=dates)
    
    # Test data feed creation
    feed = runner._create_data_feed(df, 'TEST')
    assert feed is not None
    print("✅ Data feed created successfully")


def test_runner_collect_results():
    """Test that _collect_results works correctly."""
    runner = SimpleBacktestRunner()
    
    # Create a mock cerebro and strategy
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(100000.0)
    
    # Mock strategy with required attributes
    class MockStrategy:
        def __init__(self):
            self.trades_log = [
                {'pnl': 100, 'datetime': '2023-01-01'},
                {'pnl': -50, 'datetime': '2023-01-02'}
            ]
            self.equity_history = [
                (pd.Timestamp('2023-01-01'), 100000.0),
                (pd.Timestamp('2023-01-02'), 100050.0)
            ]
            self.__class__.__name__ = 'MockStrategy'
    
    mock_strategy = MockStrategy()
    
    # Test result collection
    results = runner._collect_results(
        cerebro, 
        mock_strategy, 
        'TEST', 
        '20230101', 
        '20230102', 
        100000.0
    )
    
    assert 'symbol' in results
    assert 'final_value' in results
    assert results['symbol'] == 'TEST'
    print("✅ Results collected successfully")


def test_config_loading():
    """Test configuration loading functionality."""
    # Create a temporary config file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        config_data = {
            "mongo_uri": "mongodb://test-mongo:27017",
            "db_name": "finance_test",
            "worker_id": "test_worker_01",
            "poll_interval": 10,
            "log_level": "DEBUG"
        }
        json.dump(config_data, f)
        config_path = f.name
    
    try:
        # Test config loading
        config = load_config(config_path)
        assert config['mongo_uri'] == "mongodb://test-mongo:27017"
        assert config['db_name'] == "finance_test"
        assert config['worker_id'] == "test_worker_01"
        assert config['poll_interval'] == 10
        assert config['log_level'] == "DEBUG"
        print("✅ Configuration loaded successfully")
    finally:
        # Clean up
        os.unlink(config_path)


def test_worker_poll_tasks():
    """Test that worker can poll for tasks."""
    task_store = Mock()
    task_store.poll_task.return_value = {
        'task_id': 'test_task_001',
        'symbol': 'AAPL',
        'strategy_key': 'turtle',
        'start_date': '20230101',
        'end_date': '20231231'
    }
    
    worker = BacktestWorkerService(
        worker_id="test_worker",
        task_store=task_store
    )
    
    task = worker.poll_tasks()
    assert task is not None
    assert task['task_id'] == 'test_task_001'
    task_store.poll_task.assert_called_once()
    print("✅ Task polling works correctly")


def test_worker_poll_no_tasks():
    """Test that worker handles no tasks correctly."""
    task_store = Mock()
    task_store.poll_task.return_value = None
    
    worker = BacktestWorkerService(
        worker_id="test_worker",
        task_store=task_store
    )
    
    task = worker.poll_tasks()
    assert task is None
    print("✅ No tasks handling works correctly")


def test_worker_claim_task():
    """Test that worker can claim tasks."""
    task_store = Mock()
    task_store.claim_task.return_value = True
    
    worker = BacktestWorkerService(
        worker_id="test_worker",
        task_store=task_store
    )
    
    success = worker.claim_task('test_task_001')
    assert success is True
    task_store.claim_task.assert_called_once_with('test_task_001', 'test_worker')
    print("✅ Task claiming works correctly")


def test_worker_report_success():
    """Test that worker can report successful results."""
    task_store = Mock()
    task_store.report_success.return_value = True
    
    worker = BacktestWorkerService(
        worker_id="test_worker",
        task_store=task_store
    )
    
    results = {
        'metrics': {'total_return': 0.15, 'max_drawdown': -0.08},
        'equity_curve': [],
        'trades': []
    }
    
    success = worker.report_success('test_task_001', results)
    assert success is True
    task_store.report_success.assert_called_once_with('test_task_001', results)
    print("✅ Success reporting works correctly")


def test_worker_report_failure():
    """Test that worker can report failures."""
    task_store = Mock()
    task_store.report_failure.return_value = True
    
    worker = BacktestWorkerService(
        worker_id="test_worker",
        task_store=task_store
    )
    
    success = worker.report_failure('test_task_001', 'Test error message')
    assert success is True
    task_store.report_failure.assert_called_once_with('test_task_001', 'Test error message')
    print("✅ Failure reporting works correctly")


def test_worker_format_results():
    """Test that worker correctly formats results with metrics."""
    worker = BacktestWorkerService(
        api_base="http://test-server:3001/api",
        worker_id="test_worker",
        access_token="test_token"
    )
    
    # Create sample raw results
    raw_results = {
        'symbol': 'TEST',
        'start_date': '20230101',
        'end_date': '20231231',
        'initial_cash': 100000.0,
        'final_value': 115000.0,
        'total_profit': 15000.0,
        'profit_percentage': 0.15,
        'trades': [
            {'pnl': 1000, 'datetime': '2023-06-01', 'price': 100, 'size': 100},
            {'pnl': -200, 'datetime': '2023-06-02', 'price': 99, 'size': 50}
        ],
        'equity_curve': [
            {'date': '20230601', 'value': 101000.0},
            {'date': '20230602', 'value': 100800.0},
            {'date': '20231231', 'value': 115000.0}
        ],
        'strategy_name': 'TestStrategy'
    }
    
    formatted_results = worker._format_results(raw_results)
    
    assert 'metrics' in formatted_results
    assert 'equity_curve' in formatted_results
    assert 'trades' in formatted_results
    assert 'total_return' in formatted_results['metrics']
    assert 'max_drawdown' in formatted_results['metrics']
    assert 'win_rate' in formatted_results['metrics']
    
    print("✅ Results formatting works correctly")


def test_worker_execute_backtest():
    """Test that worker can execute a backtest task."""
    # Create a mock task
    task = {
        'task_id': 'test_task_001',
        'symbol': 'TEST',
        'strategy_key': 'turtle',  # This should be in STRATEGY_MAP
        'start_date': '20230101',
        'end_date': '20230105',
        'strategy_params': {
            'entry_window': 20,
            'exit_window': 10,
            'risk_pct': 0.02
        },
        'initial_cash': 100000.0
    }
    
    worker = BacktestWorkerService(
        api_base="http://test-server:3001/api",
        worker_id="test_worker",
        access_token="test_token"
    )
    
    # Mock the runner to avoid actual data fetching
    with patch.object(worker.runner, 'run_backtest') as mock_run_backtest:
        mock_run_backtest.return_value = {
            'symbol': 'TEST',
            'start_date': '20230101',
            'end_date': '20230105',
            'initial_cash': 100000.0,
            'final_value': 100500.0,
            'total_profit': 500.0,
            'profit_percentage': 0.005,
            'trades': [],
            'equity_curve': [],
            'strategy_name': 'TurtleTradingStrategy'
        }
        
        results = worker.execute_backtest(task)
        
        assert 'metrics' in results
        assert 'equity_curve' in results
        assert results['strategy_name'] == 'TurtleTradingStrategy'
        print("✅ Backtest execution works correctly")


def test_worker_process_task_success():
    """Test that worker can process a complete task successfully."""
    task = {
        'task_id': 'test_task_001',
        'symbol': 'TEST',
        'strategy_key': 'turtle',
        'start_date': '20230101',
        'end_date': '20230105',
        'strategy_params': {
            'entry_window': 20,
            'exit_window': 10,
            'risk_pct': 0.02
        },
        'initial_cash': 100000.0
    }
    
    worker = BacktestWorkerService(
        api_base="http://test-server:3001/api",
        worker_id="test_worker",
        access_token="test_token"
    )
    
    # Mock all the necessary methods
    with patch.object(worker, 'claim_task', return_value=True), \
         patch.object(worker, 'execute_backtest') as mock_execute, \
         patch.object(worker, 'report_success', return_value=True):
        
        mock_execute.return_value = {
            'metrics': {'total_return': 0.005},
            'equity_curve': [],
            'trades': []
        }
        
        success = worker.process_task(task)
        assert success is True
        print("✅ Task processing works correctly")


def test_worker_process_task_failure():
    """Test that worker handles task processing failures correctly."""
    task = {
        'task_id': 'test_task_001',
        'symbol': 'TEST',
        'strategy_key': 'turtle',
        'start_date': '20230101',
        'end_date': '20230105',
        'strategy_params': {},
        'initial_cash': 100000.0
    }
    
    worker = BacktestWorkerService(
        api_base="http://test-server:3001/api",
        worker_id="test_worker",
        access_token="test_token"
    )
    
    # Mock failure in execution
    with patch.object(worker, 'claim_task', return_value=True), \
         patch.object(worker, 'execute_backtest', side_effect=Exception("Test error")), \
         patch.object(worker, 'report_failure', return_value=True):
        
        success = worker.process_task(task)
        assert success is False
        print("✅ Task failure handling works correctly")


def test_worker_execute_unknown_strategy():
    """Test that worker handles unknown strategies correctly."""
    task = {
        'task_id': 'test_task_001',
        'symbol': 'TEST',
        'strategy_key': 'unknown_strategy',  # This doesn't exist
        'start_date': '20230101',
        'end_date': '20230105',
        'strategy_params': {},
        'initial_cash': 100000.0
    }
    
    worker = BacktestWorkerService(
        api_base="http://test-server:3001/api",
        worker_id="test_worker",
        access_token="test_token"
    )
    
    try:
        worker.execute_backtest(task)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown strategy" in str(e)
        print("✅ Unknown strategy handling works correctly")


def test_worker_format_results_with_empty_data():
    """Test that worker handles empty data correctly."""
    worker = BacktestWorkerService(
        api_base="http://test-server:3001/api",
        worker_id="test_worker",
        access_token="test_token"
    )
    
    raw_results = {
        'symbol': 'TEST',
        'start_date': '20230101',
        'end_date': '20230105',
        'initial_cash': 100000.0,
        'final_value': 100000.0,
        'total_profit': 0.0,
        'profit_percentage': 0.0,
        'trades': [],
        'equity_curve': [],
        'strategy_name': 'TestStrategy'
    }
    
    results = worker._format_results(raw_results)
    
    assert 'metrics' in results
    assert results['metrics']['win_rate'] == 0.0
    assert results['metrics']['total_return'] == 0.0
    print("✅ Empty data handling works correctly")


if __name__ == '__main__':
    print("Running backtest-worker unit tests...")
    print("=" * 50)
    
    try:
        test_simple_runner_initialization()
        test_runner_create_data_feed()
        test_runner_collect_results()
        test_config_loading()
        test_worker_poll_tasks()
        test_worker_poll_no_tasks()
        test_worker_claim_task()
        test_worker_report_success()
        test_worker_report_failure()
        test_worker_format_results()
        test_worker_execute_backtest()
        test_worker_process_task_success()
        test_worker_process_task_failure()
        test_worker_execute_unknown_strategy()
        test_worker_format_results_with_empty_data()
        
        print("=" * 50)
        print("✅ All tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)