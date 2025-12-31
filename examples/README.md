# Backtest Worker Examples

This directory contains examples for using the backtest worker system.

## Local Backtesting

### `local_backtest_example.py`
Demonstrates how to run backtests locally without server infrastructure:
- Turtle strategy backtest
- Grid strategy backtest  
- Logging strategy backtest
- Custom parameter usage
- Direct code integration examples

Run with:
```bash
python examples/local_backtest_example.py
```

## Standalone Runner

For simple local backtesting, use the standalone runner:

```bash
# Basic usage
python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231

# With custom parameters
python run_local_backtest.py --symbol TSLA --strategy grid --start 20230101 --end 20231231 --param grid_pct=0.02 --param max_batches=5

# Save results to file
python run_local_backtest.py --symbol MSFT --strategy turtle --start 20230101 --end 20231231 --output results.json
```

See the main documentation for complete usage details.