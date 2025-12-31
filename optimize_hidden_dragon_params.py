#!/usr/bin/env python3
"""Hidden Dragon Low Suction Strategy Parameter Optimization.

This script runs parameter optimization to find the best parameter combination
for the Hidden Dragon Low Suction trading strategy.

Usage:
    python optimize_hidden_dragon_params.py --symbol 002050.SZ --start 20230101 --end 20251226
"""

import argparse
import sys
from pathlib import Path

import backtrader as bt
import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies import HiddenDragonLowSuction
from stock_data_access import StockPriceDataAccess


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Optimize Hidden Dragon Low Suction Strategy Parameters')
    
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
    """Run parameter optimization for Hidden Dragon Low Suction strategy.
    
    Args:
        symbol: Stock symbol
        start_date: Start date (YYYYMMDD)
        end_date: End date (YYYYMMDD)
        initial_cash: Initial capital
    
    Returns:
        List of optimization results
    """
    print("=" * 80)
    print("[Hidden Dragon Low Suction Strategy Parameter Optimization]")
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
    
    # Prepare data feed
    df_bt = df.copy()
    if df_bt.index.name == 'trade_date':
        df_bt.index.name = None
    
    data_feed = bt.feeds.PandasData(
        dataname=df_bt,
        datetime=None,
        open='open',
        high='high',
        low='low',
        close='close',
        volume='volume',
        openinterest=-1
    )
    
    # Define parameter ranges to optimize
    min_boom_days_list = [1, 2]                   # Consecutive limit-up days
    entry_ma_periods = [10, 20, 60]               # Entry MA period
    max_callback_days_list = [10, 20, 30]         # Max callback observation days
    volume_shrink_pcts = [0.6, 0.8]               # Volume contraction threshold
    
    print("\n🔍 Optimization Parameters:")
    print(f"  min_boom_days: {min_boom_days_list}")
    print(f"  entry_ma_period: {entry_ma_periods}")
    print(f"  max_callback_days: {max_callback_days_list}")
    print(f"  volume_shrink_pct: {volume_shrink_pcts}")
    total_combinations = len(min_boom_days_list) * len(entry_ma_periods) * len(max_callback_days_list) * len(volume_shrink_pcts)
    print(f"  Total combinations: {total_combinations}")
    
    print("\n🚀 Running optimization...")
    print("-" * 80)
    
    # Manual optimization loop
    results = []
    count = 0
    
    for min_boom_days in min_boom_days_list:
        for entry_ma_period in entry_ma_periods:
            for max_callback_days in max_callback_days_list:
                for volume_shrink_pct in volume_shrink_pcts:
                    count += 1
                    
                    # Create fresh Cerebro for each combination
                    cerebro = bt.Cerebro()
                    cerebro.adddata(data_feed)
                    cerebro.broker.setcash(initial_cash)
                    cerebro.broker.setcommission(commission=0.0001)
                    
                    # Add strategy with specific parameters
                    cerebro.addstrategy(
                        HiddenDragonLowSuction,
                        min_boom_days=min_boom_days,
                        entry_ma_period=entry_ma_period,
                        exit_ma_period=entry_ma_period,  # Use same MA for exit
                        max_callback_days=max_callback_days,
                        volume_shrink_pct=volume_shrink_pct,
                        limit_up_rate=0.095,  # Fixed
                        stop_loss_rate=0.05,  # Fixed
                        position_pct=0.3,  # Fixed
                        ma_proximity_pct=0.01,  # Fixed
                        trailing_stop_pct=0.05,  # Fixed
                        worker_mode='backtest',
                        debug=False
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
                        
                        total_trades = trades_analyzer.get('total', {}).get('total', 0)
                        won_trades = trades_analyzer.get('won', {}).get('total', 0)
                        win_rate = (won_trades / total_trades * 100) if total_trades > 0 else 0
                        
                        result = {
                            'min_boom_days': min_boom_days,
                            'entry_ma_period': entry_ma_period,
                            'max_callback_days': max_callback_days,
                            'volume_shrink_pct': volume_shrink_pct,
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
                              f"boom={min_boom_days}, ma={entry_ma_period}, "
                              f"callback={max_callback_days}, vol={volume_shrink_pct:.0%} | "
                              f"Return={profit_pct:+.2f}% | "
                              f"DD={max_drawdown:.2f}% | "
                              f"Sharpe={sharpe_ratio:.2f} | "
                              f"Trades={total_trades}")
                        
                    except Exception as e:
                        print(f"[{count}/{total_combinations}] ❌ Error: {e}")
                        continue
    
    return results


def display_best_results(results):
    """Display top performing parameter combinations."""
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
        print(f"{i}. min_boom_days={result['min_boom_days']}, "
              f"entry_ma_period={result['entry_ma_period']}, "
              f"max_callback_days={result['max_callback_days']}, "
              f"volume_shrink_pct={result['volume_shrink_pct']:.0%}")
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
        print(f"{i}. min_boom_days={result['min_boom_days']}, "
              f"entry_ma_period={result['entry_ma_period']}, "
              f"max_callback_days={result['max_callback_days']}, "
              f"volume_shrink_pct={result['volume_shrink_pct']:.0%}")
        print(f"   Return: {result['profit_pct']:+.2f}% | "
              f"Sharpe: {result['sharpe_ratio']:.2f} | "
              f"Trades: {result['total_trades']}")
    
    # Sort by minimum drawdown
    sorted_by_drawdown = sorted(results, key=lambda x: abs(x['max_drawdown']))
    
    print("\n🛡️  Top 3 by Lowest Drawdown:")
    print("-" * 80)
    for i, result in enumerate(sorted_by_drawdown[:3], 1):
        print(f"{i}. min_boom_days={result['min_boom_days']}, "
              f"entry_ma_period={result['entry_ma_period']}, "
              f"max_callback_days={result['max_callback_days']}, "
              f"volume_shrink_pct={result['volume_shrink_pct']:.0%}")
        print(f"   Return: {result['profit_pct']:+.2f}% | "
              f"Drawdown: {result['max_drawdown']:.2f}%")
    
    # Sort by trade count
    sorted_by_trades = sorted(results, key=lambda x: x['total_trades'], reverse=True)
    
    print("\n📈 Top 3 by Most Trades:")
    print("-" * 80)
    for i, result in enumerate(sorted_by_trades[:3], 1):
        print(f"{i}. min_boom_days={result['min_boom_days']}, "
              f"entry_ma_period={result['entry_ma_period']}, "
              f"max_callback_days={result['max_callback_days']}, "
              f"volume_shrink_pct={result['volume_shrink_pct']:.0%}")
        print(f"   Trades: {result['total_trades']} (Win: {result['win_rate']:.1f}%) | "
              f"Return: {result['profit_pct']:+.2f}%")
    
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
