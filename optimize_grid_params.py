#!/usr/bin/env python3
"""Grid Strategy Parameter Optimization using Backtrader's optstrategy.

This script runs parameter optimization to find the best grid_pct and max_batches
combination for the grid trading strategy.

Usage:
    python optimize_grid_params.py --symbol 002050.SZ --start 20250101 --end 20251226
"""

import argparse
import sys
from pathlib import Path

import backtrader as bt
import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies import GridTradingStrategy
from stock_data_access import StockPriceDataAccess


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Optimize Grid Strategy Parameters')
    
    parser.add_argument(
        '--symbol',
        type=str,
        required=True,
        help='Stock symbol (e.g., 002050.SZ)'
    )
    
    parser.add_argument(
        '--start',
        type=str,
        required=True,
        help='Start date (YYYYMMDD)'
    )
    
    parser.add_argument(
        '--end',
        type=str,
        required=True,
        help='End date (YYYYMMDD)'
    )
    
    parser.add_argument(
        '--cash',
        type=float,
        default=100000,
        help='Initial cash (default: 100000)'
    )
    
    return parser.parse_args()


def run_optimization(symbol, start_date, end_date, initial_cash=100000):
    """Run parameter optimization for grid strategy.
    
    Args:
        symbol: Stock symbol
        start_date: Start date (YYYYMMDD)
        end_date: End date (YYYYMMDD)
        initial_cash: Initial capital
    
    Returns:
        List of optimization results
    """
    print("=" * 80)
    print("[Grid Strategy Parameter Optimization]")
    print("=" * 80)
    print(f"Symbol: {symbol}")
    print(f"Date Range: {start_date} to {end_date}")
    print(f"Initial Cash: {initial_cash:,.2f}")
    print("=" * 80)
    
    # Load data
    print("\n📊 Loading data from database...")
    data_access = StockPriceDataAccess(minute=False)
    df = data_access.fetch_frame([symbol], start_date, end_date)
    
    if df is None or df.empty:
        print(f"❌ No data found for {symbol} in date range {start_date} to {end_date}")
        return []
    
    print(f"✅ Loaded {len(df)} bars")
    
    # Create Cerebro engine (maxcpus=None forces single-process mode for optimization)
    cerebro = bt.Cerebro(optreturn=False, maxcpus=None)
    
    # Prepare data feed (ensure proper datetime index)
    df_bt = df.copy()
    if df_bt.index.name == 'trade_date':
        df_bt.index.name = None  # Backtrader expects unnamed datetime index
    
    # Add data feed with explicit datetime column mapping
    data_feed = bt.feeds.PandasData(
        dataname=df_bt,
        datetime=None,  # Use index as datetime
        open='open',
        high='high',
        low='low',
        close='close',
        volume='volume',
        openinterest=-1  # No open interest data
    )
    cerebro.adddata(data_feed)
    
    # Set initial cash
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=0.0)  # No commission for optimization
    
    # Define parameter ranges to optimize
    grid_pcts = [0.02, 0.03, 0.04, 0.05]      # Grid interval: 2%, 3%, 4%, 5%
    max_batches_list = [3, 5, 7]              # Grid levels: 3, 5, 7
    
    print("\n🔍 Optimization Parameters:")
    print(f"  grid_pct: {grid_pcts}")
    print(f"  max_batches: {max_batches_list}")
    print(f"  Total combinations: {len(grid_pcts) * len(max_batches_list)}")
    
    print("\n🚀 Running optimization...")
    print("-" * 80)
    
    # Manual optimization loop instead of optstrategy to avoid multiprocessing issues
    results = []
    for grid_pct in grid_pcts:
        for max_batches in max_batches_list:
            # Create fresh Cerebro for each combination
            cerebro = bt.Cerebro()
            
            # Add data
            cerebro.adddata(data_feed)
            
            # Set cash and commission
            cerebro.broker.setcash(initial_cash)
            cerebro.broker.setcommission(commission=0.0)
            
            # Add strategy with specific parameters
            cerebro.addstrategy(
                GridTradingStrategy,
                grid_pct=grid_pct,
                max_batches=max_batches,
                dynamic_base=False,
                worker_mode='backtest'
            )
            
            # Add analyzers
            cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
            cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
            
            # Run backtest
            strategies = cerebro.run()
            strategy = strategies[0]
            # Get parameters
            grid_pct = strategy.params.grid_pct
            max_batches = strategy.params.max_batches
            
            # Get final portfolio value
            final_value = strategy.broker.getvalue()
            profit = final_value - initial_cash
            profit_pct = (profit / initial_cash) * 100
            
            # Get analyzer results
            returns_analyzer = strategy.analyzers.returns.get_analysis()
            drawdown_analyzer = strategy.analyzers.drawdown.get_analysis()
            sharpe_analyzer = strategy.analyzers.sharpe.get_analysis()
            
            total_return = returns_analyzer.get('rtot', 0) * 100
            max_drawdown = drawdown_analyzer.get('max', {}).get('drawdown', 0)
            sharpe_ratio = sharpe_analyzer.get('sharperatio', None)
            # Handle None sharpe ratio
            sharpe_ratio = sharpe_ratio if sharpe_ratio is not None else 0.0
            
            result = {
                'grid_pct': grid_pct,
                'max_batches': max_batches,
                'final_value': final_value,
                'profit': profit,
                'profit_pct': profit_pct,
                'total_return': total_return,
                'max_drawdown': max_drawdown,
                'sharpe_ratio': sharpe_ratio
            }
            results.append(result)
            
            print(f"grid_pct={grid_pct:.2%}, max_batches={max_batches} | "
                  f"Return={profit_pct:+.2f}% | "
                  f"Drawdown={max_drawdown:.2f}% | "
                  f"Sharpe={sharpe_ratio:.2f}")
    
    return results


def display_best_results(results):
    """Display top performing parameter combinations.
    
    Args:
        results: List of optimization results
    """
    if not results:
        print("\n❌ No results to display")
        return
    
    print("\n" + "=" * 80)
    print("[TOP PARAMETER COMBINATIONS]")
    print("=" * 80)
    
    # Sort by profit percentage
    sorted_by_profit = sorted(results, key=lambda x: x['profit_pct'], reverse=True)
    
    print("\n🏆 Top 3 by Total Return:")
    print("-" * 80)
    for i, result in enumerate(sorted_by_profit[:3], 1):
        print(f"{i}. grid_pct={result['grid_pct']:.2%}, max_batches={result['max_batches']}")
        print(f"   Return: {result['profit_pct']:+.2f}% | "
              f"Drawdown: {result['max_drawdown']:.2f}% | "
              f"Sharpe: {result['sharpe_ratio']:.2f}")
        print(f"   Final Value: ${result['final_value']:,.2f}")
    
    # Sort by Sharpe ratio
    sorted_by_sharpe = sorted(results, key=lambda x: x['sharpe_ratio'], reverse=True)
    
    print("\n📊 Top 3 by Sharpe Ratio:")
    print("-" * 80)
    for i, result in enumerate(sorted_by_sharpe[:3], 1):
        print(f"{i}. grid_pct={result['grid_pct']:.2%}, max_batches={result['max_batches']}")
        print(f"   Return: {result['profit_pct']:+.2f}% | "
              f"Drawdown: {result['max_drawdown']:.2f}% | "
              f"Sharpe: {result['sharpe_ratio']:.2f}")
    
    # Sort by minimum drawdown (closest to 0)
    sorted_by_drawdown = sorted(results, key=lambda x: abs(x['max_drawdown']))
    
    print("\n🛡️  Top 3 by Lowest Drawdown:")
    print("-" * 80)
    for i, result in enumerate(sorted_by_drawdown[:3], 1):
        print(f"{i}. grid_pct={result['grid_pct']:.2%}, max_batches={result['max_batches']}")
        print(f"   Return: {result['profit_pct']:+.2f}% | "
              f"Drawdown: {result['max_drawdown']:.2f}% | "
              f"Sharpe: {result['sharpe_ratio']:.2f}")
    
    print("=" * 80)


def main():
    """Main entry point."""
    args = parse_args()
    
    try:
        results = run_optimization(
            symbol=args.symbol,
            start_date=args.start,
            end_date=args.end,
            initial_cash=args.cash
        )
        
        display_best_results(results)
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error during optimization: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
