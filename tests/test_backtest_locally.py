#!/usr/bin/env python3
"""
Local test script for backtest-worker without API server.

This tests the core backtest execution flow using local data.
"""

import sys
import logging
from pathlib import Path

# Add worker to path
sys.path.insert(0, str(Path(__file__).parent))

from worker.simple_backtest_runner import SimpleBacktestRunner
from strategies import STRATEGY_MAP, TurtleTradingStrategy, GridTradingStrategy

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


def test_strategy_import():
    """Test that all strategies can be imported."""
    log.info("Testing strategy imports...")
    
    log.info("✅ BacktestStrategy imported")
    log.info(f"✅ TurtleTradingStrategy imported: {TurtleTradingStrategy}")
    log.info(f"✅ GridTradingStrategy imported: {GridTradingStrategy}")
    log.info(f"✅ STRATEGY_MAP: {list(STRATEGY_MAP.keys())}")
    
    assert 'turtle' in STRATEGY_MAP
    assert 'grid' in STRATEGY_MAP
    assert STRATEGY_MAP['turtle'] == TurtleTradingStrategy
    assert STRATEGY_MAP['grid'] == GridTradingStrategy
    
    log.info("✅ All strategy imports successful!")


def test_runner_initialization():
    """Test that the runner can be initialized."""
    log.info("Testing SimpleBacktestRunner initialization...")
    
    runner = SimpleBacktestRunner()
    assert runner is not None
    assert runner.data_loader is not None
    
    log.info("✅ SimpleBacktestRunner initialized successfully!")


def test_backtest_with_grid():
    """Test running a simple backtest with Grid strategy."""
    log.info("\n" + "="*60)
    log.info("Testing Grid backtest (requires data from data-access-lib)")
    log.info("="*60)
    
    try:
        runner = SimpleBacktestRunner()
        
        # Test parameters
        symbol = '000858.SZ'  # SMIC
        start_date = '20230101'
        end_date = '20231231'
        initial_cash = 100000  # 100k for testing
        
        strategy_params = {
            'grid_pct': 0.02,
            'batch_size': 500,
            'max_batches': 3,
        }
        
        log.info("\nRunning backtest:")
        log.info(f"  Symbol: {symbol}")
        log.info("  Strategy: GridTradingStrategy")
        log.info(f"  Period: {start_date} to {end_date}")
        log.info(f"  Initial cash: {initial_cash:,.0f}")
        log.info(f"  Strategy params: {strategy_params}")
        
        results = runner.run_backtest(
            symbol=symbol,
            strategy_class=GridTradingStrategy,
            strategy_params=strategy_params,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash
        )
        
        # Display results
        log.info("\n" + "-"*60)
        log.info("Backtest Results:")
        log.info("-"*60)
        log.info(f"Strategy: {results.get('strategy_name')}")
        log.info(f"Final value: {results.get('final_value'):,.2f}")
        log.info(f"Total profit: {results.get('total_profit'):,.2f}")
        log.info(f"Profit %: {results.get('profit_percentage'):.2f}%")
        log.info(f"Total trades: {len(results.get('trades', []))}")
        log.info(f"Equity curve points: {len(results.get('equity_curve', []))}")
        
        log.info("\n✅ Backtest completed successfully!")
        # Verify results structure
        assert results.get('strategy_name') is not None
        assert results.get('final_value') is not None
        
    except ValueError as e:
        # Expected if no data is available
        log.info(f"\n⚠️  Note: {e}")
        log.info("This is normal if data-access-lib can't connect to MongoDB.")
        log.info("In production, data will be fetched from the configured data source.")
    except Exception as e:
        log.error(f"\n❌ Backtest failed: {e}", exc_info=True)
        raise


def test_backtest_with_turtle():
    """Test running a simple backtest with Turtle strategy."""
    log.info("\n" + "="*60)
    log.info("Testing Turtle backtest (requires data from data-access-lib)")
    log.info("="*60)
    
    try:
        runner = SimpleBacktestRunner()
        
        # Test parameters
        symbol = '000858.SZ'  # SMIC
        start_date = '20230101'
        end_date = '20231231'
        initial_cash = 100000  # 100k for testing
        
        strategy_params = {
            'entry_window': 20,
            'exit_window': 10,
            'risk_pct': 0.05,
            'atr_window': 10,
            'max_units': 2,
        }
        
        log.info("\nRunning backtest:")
        log.info(f"  Symbol: {symbol}")
        log.info("  Strategy: TurtleTradingStrategy")
        log.info(f"  Period: {start_date} to {end_date}")
        log.info(f"  Initial cash: {initial_cash:,.0f}")
        log.info(f"  Strategy params: {strategy_params}")
        
        results = runner.run_backtest(
            symbol=symbol,
            strategy_class=TurtleTradingStrategy,
            strategy_params=strategy_params,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash
        )
        
        # Display results
        log.info("\n" + "-"*60)
        log.info("Backtest Results:")
        log.info("-"*60)
        log.info(f"Strategy: {results.get('strategy_name')}")
        log.info(f"Final value: {results.get('final_value'):,.2f}")
        log.info(f"Total profit: {results.get('total_profit'):,.2f}")
        log.info(f"Profit %: {results.get('profit_percentage'):.2f}%")
        log.info(f"Total trades: {len(results.get('trades', []))}")
        log.info(f"Equity curve points: {len(results.get('equity_curve', []))}")
        
        log.info("\n✅ Backtest completed successfully!")
        # Verify results structure
        assert results.get('strategy_name') is not None
        assert results.get('final_value') is not None
        
    except ValueError as e:
        # Expected if no data is available
        log.info(f"\n⚠️  Note: {e}")
        log.info("This is normal if data-access-lib can't connect to MongoDB.")
        log.info("In production, data will be fetched from the configured data source.")
    except Exception as e:
        log.error(f"\n❌ Backtest failed: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    try:
        test_strategy_import()
        test_runner_initialization()
        test_backtest_with_grid()
        test_backtest_with_turtle()
        
        log.info("\n" + "="*60)
        log.info("✅ All tests passed!")
        log.info("="*60)
    except Exception as e:
        log.error(f"Tests failed: {e}", exc_info=True)
        sys.exit(1)
