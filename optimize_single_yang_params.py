#!/usr/bin/env python3
"""Single Yang Not Broken Strategy Parameter Optimization.

This script runs parameter optimization to find the best parameter combination
for the Single Yang Not Broken trading strategy.

Usage:
    python optimize_single_yang_params.py --symbol 002050.SZ --start 20230101 --end 20251226
"""

import argparse
import sys
from pathlib import Path

import backtrader as bt
import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies import SingleYangNotBroken
from stock_data_access import StockPriceDataAccess


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Optimize Single Yang Not Broken Strategy Parameters')
    
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
    """Run parameter optimization for Single Yang Not Broken strategy.
    
    Args:
        symbol: Stock symbol
        start_date: Start date (YYYYMMDD)
        end_date: End date (YYYYMMDD)
        initial_cash: Initial capital
    
    Returns:
        List of optimization results
    """
    print("=" * 80)
    print("[Single Yang Not Broken Strategy Parameter Optimization]")
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
    big_yang_rates = [0.03, 0.05, 0.07]          # Big yang threshold: 3%, 5%, 7%
    max_consolidate_days_list = [5, 8, 10]       # Consolidation period
    stop_loss_modes = ['yang_low', 'pct']         # Stop loss mode
    take_profit_pcts = [0, 0.10, 0.15]           # Take profit: 0%, 10%, 15%
    
    print("\n🔍 Optimization Parameters:")
    print(f"  big_yang_rate: {big_yang_rates}")
    print(f"  max_consolidate_days: {max_consolidate_days_list}")
    print(f"  stop_loss_mode: {stop_loss_modes}")
    print(f"  take_profit_pct: {take_profit_pcts}")
    total_combinations = len(big_yang_rates) * len(max_consolidate_days_list) * len(stop_loss_modes) * len(take_profit_pcts)
    print(f"  Total combinations: {total_combinations}")
    
    print("\n🚀 Running optimization...")
    print("-" * 80)
    
    # Manual optimization loop
    results = []
    count = 0
    
    for big_yang_rate in big_yang_rates:
        for max_consolidate_days in max_consolidate_days_list:
            for stop_loss_mode in stop_loss_modes:
                for take_profit_pct in take_profit_pcts:
                    count += 1
                    
                    # Create fresh Cerebro for each combination
                    cerebro = bt.Cerebro()
                    cerebro.adddata(data_feed)
                    cerebro.broker.setcash(initial_cash)
                    cerebro.broker.setcommission(commission=0.0001)
                    
                    # Add strategy with specific parameters
                    cerebro.addstrategy(
                        SingleYangNotBroken,
                        big_yang_rate=big_yang_rate,
                        max_consolidate_days=max_consolidate_days,
                        stop_loss_mode=stop_loss_mode,
                        take_profit_pct=take_profit_pct,
                        vol_expand_rate=1.5,  # Fixed
                        breakout_vol_rate=1.2,  # Fixed
                        position_pct=0.3,  # Fixed
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
                            'big_yang_rate': big_yang_rate,
                            'max_consolidate_days': max_consolidate_days,
                            'stop_loss_mode': stop_loss_mode,
                            'take_profit_pct': take_profit_pct,
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
                              f"yang={big_yang_rate:.1%}, days={max_consolidate_days}, "
                              f"stop={stop_loss_mode}, tp={take_profit_pct:.0%} | "
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
        print(f"{i}. big_yang_rate={result['big_yang_rate']:.1%}, "
              f"max_consolidate_days={result['max_consolidate_days']}, "
              f"stop_loss_mode={result['stop_loss_mode']}, "
              f"take_profit_pct={result['take_profit_pct']:.0%}")
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
        print(f"{i}. big_yang_rate={result['big_yang_rate']:.1%}, "
              f"max_consolidate_days={result['max_consolidate_days']}, "
              f"stop_loss_mode={result['stop_loss_mode']}, "
              f"take_profit_pct={result['take_profit_pct']:.0%}")
        print(f"   Return: {result['profit_pct']:+.2f}% | "
              f"Sharpe: {result['sharpe_ratio']:.2f} | "
              f"Trades: {result['total_trades']}")
    
    # Sort by minimum drawdown
    sorted_by_drawdown = sorted(results, key=lambda x: abs(x['max_drawdown']))
    
    print("\n🛡️  Top 3 by Lowest Drawdown:")
    print("-" * 80)
    for i, result in enumerate(sorted_by_drawdown[:3], 1):
        print(f"{i}. big_yang_rate={result['big_yang_rate']:.1%}, "
              f"max_consolidate_days={result['max_consolidate_days']}, "
              f"stop_loss_mode={result['stop_loss_mode']}, "
              f"take_profit_pct={result['take_profit_pct']:.0%}")
        print(f"   Return: {result['profit_pct']:+.2f}% | "
              f"Drawdown: {result['max_drawdown']:.2f}%")
    
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
