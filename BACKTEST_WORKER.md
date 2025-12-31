## Local Backtesting (Standalone Mode)

You can run backtests locally without the full server infrastructure using the standalone runner:

```bash
# Basic usage
python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231

# With custom parameters
python run_local_backtest.py --symbol TSLA --strategy grid --start 20230101 --end 20231231 --param grid_pct=0.02 --param max_batches=5

# Single Yang Not Broken Strategy (单阳不破)
python run_local_backtest.py --symbol 002050.SZ --strategy single_yang --start 20230101 --end 20231231 --param big_yang_rate=0.05 --param max_consolidate_days=8

# Hidden Dragon Low Suction Strategy (潜龙低吸)
python run_local_backtest.py --symbol 002050.SZ --strategy hidden_dragon --start 20230101 --end 20231231 --param min_boom_days=1 --param entry_ma_period=60

# With custom cash amount
python run_local_backtest.py --symbol MSFT --strategy turtle --start 20230101 --end 20231231 --cash 50000

# Save results to specific directory with visualizations
python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231 --output-dir my_backtest_results

# Skip plot generation
python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231 --no-plot

# Skip HTML report generation
python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231 --no-report

# Show detailed output
python run_local_backtest.py --symbol AAPL --strategy turtle --start 20230101 --end 20231231 --verbose
```

### Local Runner Options

| Option | Description | Default |
|--------|-------------|---------|  
| `--symbol` | Stock symbol to backtest | Required |
| `--strategy` | Strategy to use (turtle, grid, single_yang, hidden_dragon) | Required |
| `--start` | Start date (YYYYMMDD) | Required |
| `--end` | End date (YYYYMMDD) | Required |
| `--cash` | Initial cash amount | `100000.0` |
| `--param` | Strategy parameter (can be used multiple times) | None |
| `--output-dir` | Output directory for results, plots and reports | `results_{symbol}_{strategy}_{timestamp}` |
| `--no-plot` | Skip plot generation | False |
| `--no-report` | Skip HTML report generation | False |
| `--verbose` | Show detailed output | False |

### Advanced Features

The local backtest runner now includes advanced visualization and reporting capabilities from the stock-execution-system:

- **📈 Plot Generation**: Creates detailed equity curve plots with trade markers
- **📊 HTML Reports**: Generates comprehensive performance reports using quantstats
- **📋 Trade Tables**: Shows detailed trade execution tables
- **📈 Portfolio Visualization**: Shows portfolio equity curves vs individual stocks

### Available Strategies

- `turtle`: Turtle Trading Strategy (trend following with ATR-based position sizing)
- `grid`: Grid Trading Strategy (mean reversion with grid levels)
- `single_yang`: Single Yang Not Broken Strategy (单阳不破 - breakout after consolidation)
- `hidden_dragon`: Hidden Dragon Low Suction Strategy (潜龙低吸 - limit-up pullback entry)

### Strategy Parameters

**Turtle Strategy:**
- `entry_window`: Entry breakout window (default: 55)
- `exit_window`: Exit breakout window (default: 10)
- `risk_pct`: Risk per trade as percentage of capital (default: 0.03)
- `atr_window`: ATR calculation window (default: 20)
- `max_units`: Maximum position units (default: 4)

**Grid Strategy:**
- `grid_pct`: Grid interval as percentage (default: 0.03)
- `batch_size`: Shares per batch (default: 1000)
- `max_batches`: Maximum concurrent positions (default: 5)

**Single Yang Not Broken Strategy (单阳不破):**
- `big_yang_rate`: Big yang candle threshold (default: 0.05, i.e., 5% gain)
- `vol_expand_rate`: Volume expansion multiplier (default: 1.5x)
- `max_consolidate_days`: Maximum consolidation days (default: 8)
- `breakout_vol_rate`: Breakout volume multiplier (default: 1.2x)
- `position_pct`: Position size as percentage (default: 0.3)
- `stop_loss_mode`: Stop loss mode - 'yang_low' or 'pct' (default: 'yang_low')
- `stop_loss_pct`: Fixed stop loss percentage (default: 0.05)
- `take_profit_pct`: Take profit percentage (default: 0.15, 0=disabled)
- `trailing_stop_pct`: Trailing stop percentage (default: 0, disabled)
- `exit_ma_period`: MA period for exit signal (default: 20, 0=disabled)

**Hidden Dragon Low Suction Strategy (潜龙低吸):**
- `limit_up_rate`: Limit-up threshold (default: 0.095, i.e., ~10%)
- `min_boom_days`: Minimum consecutive limit-up days (default: 1)
- `max_callback_days`: Maximum pullback observation days (default: 20)
- `stop_loss_rate`: Stop loss percentage (default: 0.05)
- `position_pct`: Position size as percentage (default: 0.3)
- `volume_shrink_pct`: Volume contraction threshold (default: 0.6)
- `ma_proximity_pct`: MA proximity threshold (default: 0.01, i.e., 1%)
- `entry_ma_period`: Entry MA period (default: 60)
- `exit_ma_period`: Exit MA period (default: 60)
- `take_profit_pct`: Take profit percentage (default: 0, disabled)
- `trailing_stop_pct`: Trailing stop percentage (default: 0.05)

## Parameter Optimization

The backtest-worker includes parameter optimization scripts for each strategy to find optimal parameter combinations:

### Grid Strategy Optimization

```bash
python optimize_grid_params.py --symbol 002050.SZ --start 20230101 --end 20251226 --cash 100000
```

**Optimizes:**
- `grid_pct`: Grid interval (2%, 3%, 4%, 5%)
- `max_batches`: Maximum positions (3, 5, 7)
- Total: 12 combinations

### Turtle Strategy Optimization

```bash
python optimize_turtle_params.py --symbol 002050.SZ --start 20230101 --end 20251226 --cash 100000
```

**Optimizes:**
- `entry_window`: Entry breakout window (20, 55)
- `exit_window`: Exit breakout window (10, 20)
- `risk_pct`: Risk per trade (1%, 2%, 3%)
- `max_units`: Maximum units (2, 4)
- Total: 24 combinations

### Single Yang Not Broken Strategy Optimization

```bash
python optimize_single_yang_params.py --symbol 002050.SZ --start 20230101 --end 20251226 --cash 100000
```

**Optimizes:**
- `big_yang_rate`: Big yang threshold (3%, 5%, 7%)
- `max_consolidate_days`: Consolidation period (5, 8, 10)
- `stop_loss_mode`: Stop loss mode ('yang_low', 'pct')
- `take_profit_pct`: Take profit (0%, 10%, 15%)
- Total: 54 combinations

### Hidden Dragon Low Suction Strategy Optimization

```bash
python optimize_hidden_dragon_params.py --symbol 002050.SZ --start 20230101 --end 20251226 --cash 100000
```

**Optimizes:**
- `min_boom_days`: Consecutive limit-up days (1, 2)
- `entry_ma_period`: Entry MA period (10, 20, 60)
- `max_callback_days`: Max callback days (10, 20, 30)
- `volume_shrink_pct`: Volume contraction (60%, 80%)
- Total: 36 combinations

### Optimization Output

All optimization scripts provide:
- **🏆 Top 3 by Total Return**: Highest profit percentage
- **📊 Top 3 by Sharpe Ratio**: Best risk-adjusted returns
- **🛡️ Top 3 by Lowest Drawdown**: Minimum risk
- **📈 Top 3 by Most Trades**: Most active combinations (Turtle/Single Yang/Hidden Dragon only)

## Command Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--config` | Path to config.json file | None |
| `--worker-id` | Worker unique identifier | `worker_YYYYMMDD_HHMMSS` |
| `--poll-interval` | Polling interval (seconds) | `5` |
| `--api-base` | API server address | `http://localhost:3001/api` |
| `--token` | Authentication token (optional) | None |
| `--log-level` | Logging level | `INFO` |
| `--test` | Test configuration and exit | False |

## Workflow

```
1. Worker starts
2. Polls server for pending tasks
3. Claims task (atomic operation)
4. Executes backtest using quant-strategies
5. Collects results (metrics, trades, equity curve)
6. Reports results to server
7. Repeat step 2
```

## Remote Deployment

### Method 1: Direct deployment

```bash
# On remote machine
git clone <repo>
cd backtest-worker
./start.sh remote_worker_01
```

### Method 2: Using deployment script

```bash
# Modify deploy_remote.sh to use backtest-worker
# Update paths and configurations as needed
```

### Method 3: Background execution

```bash
# Using nohup
nohup ./start.sh worker_bg > backtest_worker.log 2>&1 &

# Using screen
screen -S backtest
./start.sh
# Ctrl+A D to detach

# Using systemd (Linux)
# Create /etc/systemd/system/backtest-worker.service
```

## Multiple Worker Deployment

Multiple workers can run simultaneously for parallel backtesting:

```bash
# Multiple workers locally
./start.sh worker_01 &
./start.sh worker_02 &
./start.sh worker_03 &

# Or on different machines
# Machine A
./start.sh worker_a

# Machine B  
./start.sh worker_b
```

## Logging and Monitoring

### Log Storage Locations

The backtest worker stores logs in multiple locations:

1. **Console Output**: Real-time logging to stdout/stderr when running in foreground
   - Format: `YYYY-MM-DD HH:MM:SS - LOGGER_NAME - LEVEL - MESSAGE`
   - Example: `2025-12-29 23:30:00 - worker.backtest_worker - INFO - Starting backtest worker: worker_001`

2. **Background Process Logs**: When using nohup or similar, logs are stored in:
   - Default: `backtest_worker.log` (when using `nohup ./start.sh > backtest_worker.log 2>&1 &`)
   - Custom: Any file specified when starting the process

3. **Application Logs**: The worker uses Python's logging module which can be configured in:
   - Configuration file: `config.json` (log_level parameter)
   - Environment: `LOG_LEVEL` environment variable

### Log Content

Worker outputs detailed logging information:

```
2025-12-29 23:30:00 - INFO - Starting backtest worker: worker_001
2025-12-29 23:30:05 - INFO - Found pending task: bt_20251229_120000_AAPL
2025-12-29 23:30:05 - INFO - Successfully claimed task: bt_20251229_120000_AAPL
2025-12-29 23:30:15 - INFO - Loading price data for AAPL...
2025-12-29 23:30:16 - INFO - Loaded 252 bars
2025-12-29 23:30:16 - INFO - Running backtest...
2025-12-29 23:30:25 - INFO - Backtest completed
2025-12-29 23:30:25 - INFO - Results: Return=15.00%, MaxDD=-8.00%, WinRate=60.00%, Trades=45
```

### Log Levels

- **DEBUG**: Detailed information for troubleshooting
- **INFO**: General operational information
- **WARNING**: Potential issues that don't stop execution
- **ERROR**: Errors that may affect functionality

## Stopping Worker

- **Ctrl+C** - Graceful shutdown
- **kill <pid>** - Send SIGTERM signal
- Worker completes current task before exiting

## Dependencies

- Python 3.8+
- requests
- backtrader
- quant-strategies (strategy library)
- data-access-lib (data provider)
- Access to quantFinance API server
- matplotlib (for visualization)
- quantstats (for HTML reports)

## Troubleshooting

### Issue: Cannot connect to API server

```bash
# Check network connectivity
curl http://localhost:3001/api/backtest/tasks/pending/poll

# Check firewall settings
# Ensure port 3001 is accessible
```

### Issue: Authentication failure

```bash
# Use token parameter
python worker/backtest_worker.py --token YOUR_ACCESS_TOKEN
```

### Issue: Missing dependencies

```bash
# Install dependencies
pip install -r requirements.txt

# Install visualization dependencies
pip install matplotlib pandas quantstats seaborn scipy

# Check if quant-strategies is available
pip install -e ../quant-strategies  # or install from package
```

## Performance Tuning

- **poll_interval**: Increase interval when few tasks (e.g., 10-30 seconds)
- **Multiple workers**: Parallel processing of backtest tasks
- **Resource limits**: Single worker typically uses 1 CPU + 500MB memory

## Security Recommendations

1. **Don't expose API publicly** - Use VPN or SSH tunnel
2. **Use authentication tokens** - Avoid unauthorized access
3. **Limit worker permissions** - Run with dedicated user
4. **Monitor logs** - Detect unusual behavior promptly

## Related Documents

- [config.example.json](./config.example.json) - Configuration template
- [quantFinance API](../quantFinance/routers/backtest.py) - Backtest API documentation
- [quant-strategies](../quant-strategies/) - Strategy library documentation