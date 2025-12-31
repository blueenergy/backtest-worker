#!/usr/bin/env python3
"""Turtle Strategy Parameter Optimization.

This script runs parameter optimization to find the best parameter combination
for the Turtle trading strategy.

Usage:
    python optimize_turtle_params.py --symbol 002050.SZ --start 20230101 --end 20251226
"""

import argparse
import sys
from pathlib import Path

import backtrader as bt
import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies import TurtleTradingStrategy
from stock_data_access import StockPriceDataAccess


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Optimize Turtle Strategy Parameters')
    
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
    """Run parameter optimization for Turtle strategy.
    
    Args:
        symbol: Stock symbol
        start_date: Start date (YYYYMMDD)
        end_date: End date (YYYYMMDD)
        initial_cash: Initial capital
    
    Returns:
        List of optimization results
    """
    print("=" * 80)
    print("[Turtle Strategy Parameter Optimization]")
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
    
    # Define parameter ranges to optimize
    entry_windows = [20, 55]              # Classic Turtle uses 20/55
    exit_windows = [10, 20]               # Exit breakout window
    risk_pcts = [0.01, 0.02, 0.03]        # Risk per trade: 1%, 2%, 3%
    max_units_list = [2, 4]               # Maximum pyramid units
    
    print("\n🔍 Optimization Parameters:")
    print(f"  entry_window: {entry_windows}")
    print(f"  exit_window: {exit_windows}")
    print(f"  risk_pct: {risk_pcts}")
    print(f"  max_units: {max_units_list}")
    total_combinations = len(entry_windows) * len(exit_windows) * len(risk_pcts) * len(max_units_list)
    print(f"  Total combinations: {total_combinations}")
    
    print("\n🚀 Running optimization...")
    print("-" * 80)
    
    # Manual optimization loop to avoid multiprocessing issues
    results = []
    count = 0
    
    for entry_window in entry_windows:
        for exit_window in exit_windows:
            for risk_pct in risk_pcts:
                for max_units in max_units_list:
                    count += 1
                    
                    # Create fresh Cerebro for each combination
                    cerebro = bt.Cerebro()
                    
                    # Add data
                    cerebro.adddata(data_feed)
                    
                    # Set cash and commission
                    cerebro.broker.setcash(initial_cash)
                    cerebro.broker.setcommission(commission=0.0001)  # 万分之一佣金
                    
                    # Add strategy with specific parameters
                    cerebro.addstrategy(
                        TurtleTradingStrategy,
                        entry_window=entry_window,
                        exit_window=exit_window,
                        risk_pct=risk_pct,
                        max_units=max_units,
                        atr_window=20,  # Fixed ATR window
                        trailing_stop_mult=2,  # Fixed 2N trailing stop
                        exit_mode='trailing',  # Fixed exit mode
                        worker_mode='backtest'
                    )
                    
                    # Add analyzers
                    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
                    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
                    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
                    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
                    
                    # Run backtest
                    try:
                        strategies = cerebro.run()
                        strategy = strategies[0]
                        
                        # Get parameters
                        params = strategy.params
                        
                        # Get final portfolio value
                        final_value = strategy.broker.getvalue()
                        profit = final_value - initial_cash
                        profit_pct = (profit / initial_cash) * 100
                        
                        # Get analyzer results
                        returns_analyzer = strategy.analyzers.returns.get_analysis()
                        drawdown_analyzer = strategy.analyzers.drawdown.get_analysis()
                        sharpe_analyzer = strategy.analyzers.sharpe.get_analysis()
                        trades_analyzer = strategy.analyzers.trades.get_analysis()
                        
                        total_return = returns_analyzer.get('rtot', 0) * 100
                        max_drawdown = drawdown_analyzer.get('max', {}).get('drawdown', 0)
                        sharpe_ratio = sharpe_analyzer.get('sharperatio', None)
                        sharpe_ratio = sharpe_ratio if sharpe_ratio is not None else 0.0
                        
                        # Get trade statistics
                        total_trades = trades_analyzer.get('total', {}).get('total', 0)
                        won_trades = trades_analyzer.get('won', {}).get('total', 0)
                        win_rate = (won_trades / total_trades * 100) if total_trades > 0 else 0
                        
                        result = {
                            'entry_window': entry_window,
                            'exit_window': exit_window,
                            'risk_pct': risk_pct,
                            'max_units': max_units,
                            'final_value': final_value,
                            'profit': profit,
                            'profit_pct': profit_pct,
                            'total_return': total_return,
                            'max_drawdown': max_drawdown,
                            'sharpe_ratio': sharpe_ratio,
                            'total_trades': total_trades,
                            'win_rate': win_rate
                        }
                        results.append(result)
                        
                        print(f"[{count}/{total_combinations}] "
                              f"entry={entry_window}, exit={exit_window}, "
                              f"risk={risk_pct:.1%}, units={max_units} | "
                              f"Return={profit_pct:+.2f}% | "
                              f"DD={max_drawdown:.2f}% | "
                              f"Sharpe={sharpe_ratio:.2f} | "
                              f"Trades={total_trades}")
                        
                    except Exception as e:
                        print(f"[{count}/{total_combinations}] ❌ Error: {e}")
                        continue
    
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
        print(f"{i}. entry_window={result['entry_window']}, "
              f"exit_window={result['exit_window']}, "
              f"risk_pct={result['risk_pct']:.1%}, "
              f"max_units={result['max_units']}")
        print(f"   Return: {result['profit_pct']:+.2f}% | "
              f"Drawdown: {result['max_drawdown']:.2f}% | "
              f"Sharpe: {result['sharpe_ratio']:.2f} | "
              f"Trades: {result['total_trades']} (Win: {result['win_rate']:.1f}%)")
        print(f"   Final Value: ${result['final_value']:,.2f}")
    
    # Sort by Sharpe ratio
    sorted_by_sharpe = sorted(results, key=lambda x: x['sharpe_ratio'], reverse=True)
    
    print("\n📊 Top 3 by Sharpe Ratio:")
    print("-" * 80)
    for i, result in enumerate(sorted_by_sharpe[:3], 1):
        print(f"{i}. entry_window={result['entry_window']}, "
              f"exit_window={result['exit_window']}, "
              f"risk_pct={result['risk_pct']:.1%}, "
              f"max_units={result['max_units']}")
        print(f"   Return: {result['profit_pct']:+.2f}% | "
              f"Drawdown: {result['max_drawdown']:.2f}% | "
              f"Sharpe: {result['sharpe_ratio']:.2f} | "
              f"Trades: {result['total_trades']}")
    
    # Sort by minimum drawdown (closest to 0)
    sorted_by_drawdown = sorted(results, key=lambda x: abs(x['max_drawdown']))
    
    print("\n🛡️  Top 3 by Lowest Drawdown:")
    print("-" * 80)
    for i, result in enumerate(sorted_by_drawdown[:3], 1):
        print(f"{i}. entry_window={result['entry_window']}, "
              f"exit_window={result['exit_window']}, "
              f"risk_pct={result['risk_pct']:.1%}, "
              f"max_units={result['max_units']}")
        print(f"   Return: {result['profit_pct']:+.2f}% | "
              f"Drawdown: {result['max_drawdown']:.2f}% | "
              f"Sharpe: {result['sharpe_ratio']:.2f}")
    
    # Sort by trade count (more trades = more opportunities)
    sorted_by_trades = sorted(results, key=lambda x: x['total_trades'], reverse=True)
    
    print("\n📈 Top 3 by Most Trades:")
    print("-" * 80)
    for i, result in enumerate(sorted_by_trades[:3], 1):
        print(f"{i}. entry_window={result['entry_window']}, "
              f"exit_window={result['exit_window']}, "
              f"risk_pct={result['risk_pct']:.1%}, "
              f"max_units={result['max_units']}")
        print(f"   Trades: {result['total_trades']} (Win: {result['win_rate']:.1f}%) | "
              f"Return: {result['profit_pct']:+.2f}% | "
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
