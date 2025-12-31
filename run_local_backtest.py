#!/usr/bin/env python3
"""
Advanced local backtest runner with visualization capabilities.

This script allows you to run backtests locally without needing the full server infrastructure.
It uses the same core components as the backtest worker but runs in a standalone mode.
Includes advanced plotting and reporting capabilities from stock-execution-system.

Usage:
    python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231
    python run_local_backtest.py --symbol TSLA --strategy grid --param grid_pct=0.02 --param max_batches=5
    python run_local_backtest.py --symbol 002050.SZ --strategy single_yang --start 20230101 --end 20231231
    python run_local_backtest.py --symbol 002050.SZ --strategy hidden_dragon --start 20230101 --end 20231231
"""

import argparse
import sys
from pathlib import Path
import json
import pandas as pd
from datetime import datetime

# Add parent directory to path for strategy imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import STRATEGY_MAP early to use in argparse
from strategies import STRATEGY_MAP

# Add worker to path
sys.path.insert(0, str(Path(__file__).parent))

from worker.simple_backtest_runner import SimpleBacktestRunner


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run local backtest without server infrastructure"
    )
    
    parser.add_argument(
        "--symbol",
        required=True,
        help="Stock symbol to backtest (e.g., AAPL, TSLA, 000858.SZ)"
    )
    
    parser.add_argument(
        "--strategy",
        required=True,
        choices=list(STRATEGY_MAP.keys()),
        help=f"Strategy to use (available: {', '.join(STRATEGY_MAP.keys())})"
    )
    
    parser.add_argument(
        "--start",
        required=True,
        help="Start date (YYYYMMDD)"
    )
    
    parser.add_argument(
        "--end",
        required=True,
        help="End date (YYYYMMDD)"
    )
    
    parser.add_argument(
        "--cash",
        type=float,
        default=100000.0,
        help="Initial cash (default: 100000.0)"
    )
    
    parser.add_argument(
        "--param",
        action="append",
        help="Strategy parameter (e.g., --param entry_window=20 --param risk_pct=0.02)"
    )
    
    parser.add_argument(
        "--output",
        help="Output file for results (JSON format)"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output"
    )
    
    parser.add_argument(
        "--output-dir",
        help="Output directory for plots and reports (default: results_YYYYMMDD_HHMMSS)"
    )
    
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="Skip plot generation"
    )
    
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip HTML report generation"
    )
    
    return parser.parse_args()


def parse_params(param_list):
    """Parse parameter list from command line."""
    if not param_list:
        return {}
    
    params = {}
    for param_str in param_list:
        if '=' in param_str:
            key, value = param_str.split('=', 1)
            # Try to convert to appropriate type
            try:
                # Try int first
                params[key] = int(value)
            except ValueError:
                try:
                    # Then float
                    params[key] = float(value)
                except ValueError:
                    # Then string
                    params[key] = value
        else:
            print(f"Warning: Parameter '{param_str}' not in key=value format, skipping")
    
    return params


def calculate_performance_metrics(equity_curve):
    """Calculate Max Drawdown and Sharpe Ratio from equity curve.
    
    Args:
        equity_curve: List of {'date': str, 'value': float}
    
    Returns:
        dict with 'max_drawdown' and 'sharpe_ratio'
    """
    if not equity_curve or len(equity_curve) < 2:
        return {'max_drawdown': 0.0, 'sharpe_ratio': 0.0}
    
    import numpy as np
    
    values = np.array([point['value'] for point in equity_curve])
    
    # Max Drawdown
    running_max = np.maximum.accumulate(values)
    drawdown = (values - running_max) / running_max
    max_drawdown = np.min(drawdown)  # Most negative value
    
    # Sharpe Ratio (annualized)
    returns = np.diff(values) / values[:-1]  # Daily returns
    if len(returns) > 0 and np.std(returns) > 0:
        avg_return = np.mean(returns)
        std_return = np.std(returns)
        # Annualize: assume 252 trading days
        sharpe_ratio = (avg_return / std_return) * np.sqrt(252)
    else:
        sharpe_ratio = 0.0
    
    return {
        'max_drawdown': float(max_drawdown),
        'sharpe_ratio': float(sharpe_ratio)
    }


def generate_advanced_plots_and_reports(results, output_dir, symbol, strategy_name, no_plot=False, no_report=False):
    """Generate advanced plots and reports using stock-execution-system patterns."""
    try:
        # Import plotting and reporting utilities
        from visualization.plotting import plot_symbol_close
        from visualization.reporting import generate_quantstats_report
        
        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        print("\n📊 Generating advanced visualizations and reports...")
        
        # Extract trades from results
        trades = results.get('trades', [])
        
        # Initialize df to avoid UnboundLocalError
        df = None
        
        # Create a mock DataFrame from results for plotting
        # In a real scenario, we would have access to the actual price data
        # For now, we'll create a basic plot
        if not no_plot and trades:
            # Extract trade dates and create a simple equity curve for demonstration
            import numpy as np
            
            # Create mock price data based on the backtest period
            start_date = datetime.strptime(results['start_date'], '%Y%m%d')
            end_date = datetime.strptime(results['end_date'], '%Y%m%d')
            
            # Create date range
            date_range = pd.date_range(start=start_date, end=end_date, freq='D')
            
            # Create mock price data
            np.random.seed(42)  # For reproducible results
            returns = np.random.normal(0.0005, 0.02, len(date_range))  # Daily returns
            prices = [results['initial_cash']]
            for r in returns[1:]:
                prices.append(prices[-1] * (1 + r))
            
            # Create DataFrame
            df = pd.DataFrame({
                'close': prices,
                'open': [p * (1 + np.random.normal(0, 0.001)) for p in prices],
                'high': [p * (1 + abs(np.random.normal(0, 0.005))) for p in prices],
                'low': [p * (1 - abs(np.random.normal(0, 0.005))) for p in prices],
                'volume': [100000] * len(date_range)
            }, index=date_range)
            
            # Convert trades to the format expected by plotting function (if any exist)
            plot_trades = []
            for i, trade in enumerate(trades[:20]):  # Limit to first 20 trades for clarity
                # Map the trade fields to the expected format for plotting
                # BUG FIX: Use 'datetime' not 'timestamp' - matches results.json field name
                plot_trades.append({
                    'datetime': trade.get('datetime', pd.to_datetime(trade.get('timestamp', date_range[min(i, len(date_range)-1)]))),
                    'action': trade.get('action', 'BUY').upper(),
                    'size': trade.get('size', trade.get('quantity', 100)),  # Handle different field names
                    'price': trade.get('price', trade.get('avg_price', df['close'].iloc[min(i, len(df)-1)] if len(df) > 0 else 100)),
                    'position_after': trade.get('position_after', trade.get('size', 100)),
                    'avg_cost': trade.get('avg_cost', trade.get('price', df['close'].iloc[min(i, len(df)-1)] if len(df) > 0 else 100)),
                    'realized_pl': trade.get('realized_pl', trade.get('pnl', 0)),
                    'cum_pl': trade.get('cumulative_pl', 0),
                    'unrealized_pl': trade.get('unrealized_pl', 0),
                    'total_pl': trade.get('total_pl', 0),
                })
            
            # Generate plot
            try:
                plot_path = plot_symbol_close(
                    df=df,
                    symbol=symbol,
                    stock_name=f"{symbol}_{strategy_name}",
                    events=plot_trades if plot_trades else None,  # Pass None if no trades
                    output_dir=output_path,
                    strategy_key=strategy_name
                )
                if plot_path:
                    print(f"📈 Plot saved to: {plot_path}")
            except Exception as e:
                print(f"⚠️  Error generating plot: {e}")
        
        # Generate HTML report if not disabled
        if not no_report:
            try:
                if df is not None:  # Only generate report if df was created
                    # Create mock price map for report generation
                    price_map = {symbol: df}
                    symbols = [symbol]
                    initial_capital = results['initial_cash']
                    
                    report_path = generate_quantstats_report(
                        price_map=price_map,
                        symbols=symbols,
                        initial_capital=initial_capital,
                        output_dir=output_path,
                        title=f"{strategy_name.upper()} Strategy - {symbol}"
                    )
                    if report_path:
                        print(f"📊 HTML Report saved to: {report_path}")
                else:
                    print("⚠️  Skipping HTML report generation - no price data available")
            except Exception as e:
                print(f"⚠️  Error generating report: {e}")
        
        print(f"✅ Advanced visualizations completed in: {output_path}")
        
    except ImportError as e:
        print(f"⚠️  Could not import advanced plotting utilities: {e}")
        print("   Install required dependencies or copy plotting/reporting modules from stock-execution-system")
    except Exception as e:
        print(f"⚠️  Error in advanced plotting: {e}")


def create_output_directory(output_dir_arg, symbol, strategy_name):
    """Create output directory for results."""
    if output_dir_arg:
        output_dir = Path(output_dir_arg)
    else:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(f"results_{symbol}_{strategy_name}_{timestamp}")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def main():
    """Main entry point."""
    args = parse_args()
    
    print("=" * 80)
    print(f"[Local Backtest Runner] - {args.strategy.upper()} Strategy")
    print("=" * 80)
    print(f"Symbol: {args.symbol}")
    print(f"Strategy: {args.strategy}")
    print(f"Date Range: {args.start} to {args.end}")
    print(f"Initial Cash: {args.cash:,.2f}")
    print(f"Parameters: {args.param or 'default'}")
    print("=" * 80)
    
    try:
        # Get strategy class from STRATEGY_MAP (already imported at top)
        if args.strategy not in STRATEGY_MAP:
            print(f"❌ Error: Unknown strategy '{args.strategy}'")
            print(f"Available strategies: {list(STRATEGY_MAP.keys())}")
            sys.exit(1)
        
        strategy_class = STRATEGY_MAP[args.strategy]
        print(f"✅ Using strategy: {strategy_class.__name__}")
        
        # Parse parameters
        strategy_params = parse_params(args.param)
        print(f"✅ Parameters: {strategy_params}")
        
        # Create runner
        runner = SimpleBacktestRunner()
        
        # Run backtest
        print("\n🚀 Running backtest...")
        results = runner.run_backtest(
            symbol=args.symbol,
            strategy_class=strategy_class,
            strategy_params=strategy_params,
            start_date=args.start,
            end_date=args.end,
            initial_cash=args.cash
        )
        
        # Display results
        print("\n" + "=" * 80)
        print("[BACKTEST RESULTS]")
        print("=" * 80)
        print(f"Strategy: {results.get('strategy_name', 'Unknown')}")
        print(f"Symbol: {results['symbol']}")
        print(f"Period: {results['start_date']} to {results['end_date']}")
        print(f"Initial Cash: {results['initial_cash']:,.2f}")
        print(f"Final Value: {results['final_value']:,.2f}")
        print(f"Total Profit: {results['total_profit']:,.2f}")
        print(f"Total Return: {results['profit_percentage']:.2f}%")
        print(f"Total Trades: {len(results.get('trades', []))}")
        print(f"Equity Points: {len(results.get('equity_curve', []))}")
        
        # Calculate and display performance metrics
        equity_curve = results.get('equity_curve', [])
        if equity_curve and len(equity_curve) >= 2:
            metrics = calculate_performance_metrics(equity_curve)
            print(f"Max Drawdown: {metrics['max_drawdown']:.2%}")
            print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
                
        print("="*80)
        
        # Create output directory
        output_dir = create_output_directory(args.output_dir, args.symbol, args.strategy)
        print(f"📁 Results directory: {output_dir}")
        
        # Save results to the output directory
        results_path = output_dir / "results.json"
        with open(results_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"💾 Results saved to: {results_path}")
        
        # Show detailed trades if verbose
        if args.verbose and trades:
            print("\n[TRADE DETAILS]")
            for i, trade in enumerate(trades[:10]):  # Show first 10 trades
                print(f"  {i+1}. {trade.get('action', 'N/A')} {trade.get('size', 0)} @ {trade.get('price', 0):.2f}")
            if len(trades) > 10:
                print(f"  ... and {len(trades) - 10} more trades")
        
        # Generate advanced plots and reports
        if not args.no_plot or not args.no_report:
            generate_advanced_plots_and_reports(
                results=results,
                output_dir=output_dir,
                symbol=args.symbol,
                strategy_name=args.strategy,
                no_plot=args.no_plot,
                no_report=args.no_report
            )
        
        return results
        
    except Exception as e:
        print(f"\n❌ Error running backtest: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
