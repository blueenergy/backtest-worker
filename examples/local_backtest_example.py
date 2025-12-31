#!/usr/bin/env python3
"""
Examples of running local backtests using the SimpleBacktestRunner directly.

This demonstrates different ways to run backtests locally without server infrastructure.
"""

import sys
from pathlib import Path
import pandas as pd

# Add worker to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from worker.simple_backtest_runner import SimpleBacktestRunner


def example_turtle_backtest():
    """Example: Run Turtle strategy backtest."""
    print("=" * 60)
    print("Turtle Strategy Backtest Example")
    print("=" * 60)
    
    SimpleBacktestRunner()
    
    # For local testing, we'll use mock data
    # In real usage, this would fetch from data-access-lib
    import numpy as np
    dates = pd.date_range(start='2023-01-01', periods=252, freq='D')  # ~1 year of daily data
    np.random.seed(42)
    returns = np.random.normal(0.001, 0.02, len(dates))
    prices = [100.0]
    for r in returns[1:]:
        prices.append(prices[-1] * (1 + r))
    
    sample_data = pd.DataFrame({
        'open': [p * (1 + np.random.normal(0, 0.001)) for p in prices],
        'high': [p * (1 + abs(np.random.normal(0, 0.005))) for p in prices],
        'low': [p * (1 - abs(np.random.normal(0, 0.005))) for p in prices],
        'close': prices,
        'volume': [100000] * len(dates)
    }, index=dates)
    
    # In real usage, you would use:
    # results = runner.run_backtest(
    #     symbol='AAPL',
    #     strategy_class=TurtleTradingStrategy,
    #     strategy_params={'entry_window': 20, 'exit_window': 10, 'risk_pct': 0.02},
    #     start_date='20230101',
    #     end_date='20231231',
    #     initial_cash=100000.0
    # )
    
    # For this example, we'll show the structure with mock data
    print("Runner initialized successfully")
    print(f"Available data points: {len(sample_data)}")
    print("Sample data preview:")
    print(sample_data.head())
    print("\nTo run with real data, use the command line tool:")
    print("python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231")


def example_grid_backtest():
    """Example: Run Grid strategy backtest."""
    print("\n" + "=" * 60)
    print("Grid Strategy Backtest Example")
    print("=" * 60)
    
    SimpleBacktestRunner()
    
    print("Runner initialized successfully")
    print("Grid strategy parameters typically include:")
    print("- grid_pct: Percentage interval for grid levels (e.g., 0.02 for 2%)")
    print("- batch_size: Number of shares per grid trade")
    print("- max_batches: Maximum number of grid positions")
    print("\nExample command:")
    print("python run_local_backtest.py --symbol TSLA --strategy grid --start 20230101 --end 20231231 --param grid_pct=0.02 --param max_batches=5")


def example_logging_strategy():
    """Example: Note about logging strategy."""
    print("\n" + "=" * 60)
    print("Note about Logging Strategy")
    print("=" * 60)
    
    print("The 'logging' strategy is not currently available in the STRATEGY_MAP.")
    print("Available strategies are:")
    print("- turtle: Turtle Trading Strategy")
    print("- grid: Grid Trading Strategy")
    print("\nExample command:")
    print("python run_local_backtest.py --symbol MSFT --strategy turtle --start 20230101 --end 20231231")


def example_custom_parameters():
    """Example: Using custom strategy parameters."""
    print("\n" + "=" * 60)
    print("Custom Parameters Example")
    print("=" * 60)
    
    print("You can pass custom parameters to strategies:")
    print("\nTurtle Strategy parameters:")
    print("- entry_window: Entry breakout window (default: 55)")
    print("- exit_window: Exit breakout window (default: 10)")
    print("- risk_pct: Risk per trade as percentage of capital (default: 0.03)")
    print("- atr_window: ATR calculation window (default: 20)")
    print("- max_units: Maximum position units (default: 4)")
    
    print("\nGrid Strategy parameters:")
    print("- grid_pct: Grid interval as percentage (default: 0.03)")
    print("- batch_size: Shares per batch (default: 1000)")
    print("- max_batches: Maximum concurrent positions (default: 5)")
    
    print("\nExample with multiple parameters:")
    print("python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231 --param entry_window=20 --param risk_pct=0.02 --param max_units=3")


def example_advanced_visualization():
    """Example: Using advanced visualization features."""
    print("\n" + "=" * 60)
    print("Advanced Visualization Features")
    print("=" * 60)
    
    print("The enhanced local backtester now includes advanced visualization:")
    print("\n📊 Plot Generation:")
    print("- Equity curve plots with trade markers")
    print("- Trade execution tables")
    print("- Portfolio visualization vs individual stocks")
    
    print("\n📊 HTML Reports:")
    print("- Comprehensive performance reports using quantstats")
    print("- Risk metrics, drawdown analysis, and more")
    
    print("\n📁 Output Options:")
    print("- Custom output directories")
    print("- Skip plot generation if not needed")
    print("- Skip HTML reports if not needed")
    
    print("\nExample with visualization:")
    print("python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231 --output-dir my_backtest_results")
    
    print("\nSkip plot generation:")
    print("python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231 --no-plot")
    
    print("\nSkip HTML report:")
    print("python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231 --no-report")


def example_direct_usage():
    """Example: Using SimpleBacktestRunner directly in code."""
    print("\n" + "=" * 60)
    print("Direct Usage in Code Example")
    print("=" * 60)
    
    
    SimpleBacktestRunner()
    
    print("Example of direct usage in Python code:")
    print("""
from worker.simple_backtest_runner import SimpleBacktestRunner
from strategies import TurtleTradingStrategy

runner = SimpleBacktestRunner()

# Run backtest directly
results = runner.run_backtest(
    symbol='AAPL',
    strategy_class=TurtleTradingStrategy,
    strategy_params={
        'entry_window': 20,
        'exit_window': 10,
        'risk_pct': 0.02
    },
    start_date='20230101',
    end_date='20231231',
    initial_cash=100000.0
)

print(f"Final value: {results['final_value']}")
print(f"Total return: {results['profit_percentage']:.2%}")
    """)


if __name__ == "__main__":
    print("Local Backtest Examples")
    print("This shows different ways to run backtests locally without server infrastructure")
    
    example_turtle_backtest()
    example_grid_backtest()
    example_logging_strategy()
    example_custom_parameters()
    example_advanced_visualization()
    example_direct_usage()
    
    print("\n" + "=" * 60)
    print("For actual backtesting, use:")
    print("python run_local_backtest.py --help")
    print("=" * 60)