# Backtest Worker Visualization Setup

This document explains how to set up advanced visualization and reporting features for the local backtest runner.

## Overview

The local backtest runner now includes advanced visualization capabilities from the stock-execution-system, including:

- 📊 Equity curve plots with trade markers
- 📋 Trade execution tables
- 📊 HTML performance reports using quantstats
- 📈 Portfolio visualization vs individual stocks

## Setup

The visualization modules have been automatically set up using the `setup_visualization.py` script, which:

1. Copies plotting and reporting modules from stock-execution-system
2. Creates a local visualization package
3. Updates the local backtest runner to use local modules

## Usage

Once set up, you can use all the advanced visualization features:

```bash
# Run with default visualization (plots and HTML reports)
python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231

# Custom output directory
python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231 --output-dir my_backtest_results

# Skip plot generation
python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231 --no-plot

# Skip HTML report generation
python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231 --no-report
```

## Dependencies

The visualization features require additional dependencies:

- matplotlib
- pandas
- quantstats
- seaborn
- scipy
- yfinance

These were installed when you ran the setup script.

## Files Created

The setup creates the following files:

- `visualization/plotting.py` - Plotting utilities from stock-execution-system
- `visualization/reporting.py` - Reporting utilities from stock-execution-system
- `visualization/__init__.py` - Package initialization file
- Updated `run_local_backtest.py` - Modified to use local visualization modules

## Output Structure

When running backtests with visualization enabled, the following files are created in the output directory:

```
output_directory/
├── results.json                 # Raw backtest results
├── backtrader_plot_*.png       # Equity curve plot with trade markers
├── trades_*.csv                # Trade execution table
└── quantstats_report.html      # Comprehensive HTML performance report
```

## Re-running Setup

If you need to re-run the setup (e.g., to update visualization modules), use:

```bash
python setup_visualization.py
```

## Troubleshooting

If you encounter issues with visualization:

1. **Import errors**: Make sure all dependencies are installed:
   ```bash
   pip install matplotlib pandas quantstats seaborn scipy yfinance
   ```

2. **Missing modules**: Re-run the setup script:
   ```bash
   python setup_visualization.py
   ```

3. **Plotting errors**: Try running with `--no-plot` to skip plot generation

4. **Report errors**: Try running with `--no-report` to skip HTML report generation