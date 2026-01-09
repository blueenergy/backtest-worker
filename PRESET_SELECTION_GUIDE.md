# Strategy Preset Selection Guide

## Overview

The stock screening system now supports **parameter presets** for each strategy, allowing you to run different risk profiles and compare results.

## Preset Types

All strategies now support three standard presets:

| Preset | Chinese | Description | Stock Count | Win Rate | Use Case |
|--------|---------|-------------|-------------|----------|----------|
| `conservative` | 保守 | Strict parameters, fewer but high-quality signals | Low | High | Risk-averse, high win-rate focus |
| `default/standard` | 标准 | Balanced parameters | Medium | Medium | General use |
| `aggressive` | 激进 | Loose parameters, more opportunities | High | Lower | High-frequency trading, more chances |

## Running Screening with Presets

### Command Line

```bash
cd backtest-worker

# Run single preset
python daily_full_market_screening.py \
    --strategy-key turtle \
    --preset turtle_conservative \
    --days-back 360 \
    --min-win-rate 0.50 \
    --min-trades 3

# Available presets:
# Turtle: turtle_conservative, turtle_standard, turtle_aggressive
# Single Yang: yang_conservative, yang_default, yang_aggressive
# Hidden Dragon: dragon_conservative, dragon_default, dragon_aggressive
```

### Convenient Script

```bash
# Run conservative presets (high win-rate focus) - Default
./run_screening.sh conservative

# Run balanced approach presets
./run_screening.sh standard

# Run aggressive presets
./run_screening.sh aggressive

# Run ALL presets for comparison (runs all 9 tasks)
./run_screening.sh all
```

## Frontend Usage

After running screening:

1. **Open Frontend** → "Strategy Stock Pool" tab
2. **Select Strategy**: e.g., "海龟交易" (Turtle)
3. **Select Preset**: Use "参数风格" dropdown
   - **保守（高胜率）**: Fewer stocks, higher quality
   - **标准**: Balanced approach
   - **激进（高频交易）**: More stocks, more opportunities
4. **Select Date**: Choose screening date
5. **Compare Results**: Switch between presets to see differences
6. **View Charts**: Click any stock to see K-line with buy/sell markers (360-day window)

## Trade History Visualization

When viewing K-line charts from strategy stock pool:

- **Green "B" markers**: Buy signals (pin icon at bottom)
- **Red "S" markers**: Sell signals (circle icon at top)
- **Complete trade cycle**: See entry and exit points
- **Validate strategy**: Check if buy/sell timing is reasonable

This helps you understand:
- Strategy buy/sell logic
- Whether entries lead to profits
- If exits are timely
- Stop-loss effectiveness

## Database Storage

Each screening result is stored with:
- `strategy`: Strategy name (e.g., "turtle")
- `preset`: Preset name (e.g., "turtle_conservative")
- `date`: Screening date (YYYYMMDD)
- `symbol`: Stock symbol
- `hist_win_rate`, `hist_return`, etc.: Historical metrics

The combination of `(date, strategy, preset, symbol)` forms a unique record.

**Two collections**:
1. `strategy_stock_pool`: Today's buy signals (for selection list)
2. `strategy_trade_history`: Complete trade history (buy + sell, for charts)

## Example Workflow

```bash
# Step 1: Run screening with all presets for full comparison
cd backtest-worker
./run_screening.sh all

# Step 2: Check frontend
# - Strategy Stock Pool → Turtle → Conservative: See 30-50 stocks
# - Strategy Stock Pool → Turtle → Aggressive: See 80-120 stocks

# Step 3: Click any stock to view chart
# - K-line shows complete buy/sell history
# - Green B = Buy points
# - Red S = Sell points
# - Evaluate strategy effectiveness visually (360-day historical window)

# Step 4: Compare and decide
# - Which preset has higher win-rate?
# - Which preset matches your risk tolerance?
# - Do aggressive signals include all conservative signals?

# Step 5: Make trading decision
# - Use conservative for actual trading (fewer, safer bets)
# - Use aggressive for watchlist (more opportunities to monitor)
```

## API Endpoints

Backend exposes four endpoints:

1. **GET /api/strategy-pool/presets?strategy={strategy_key}**
   - Returns available presets for a strategy
   - Example: `["turtle_conservative", "turtle_standard", "turtle_aggressive"]`

2. **GET /api/strategy-pool/dates?strategy={strategy_key}&preset={preset_name}**
   - Returns available dates for given strategy and preset
   - Preset is optional (returns all dates if omitted)

3. **GET /api/strategy-pool/stocks?date={date}&strategy={strategy_key}&preset={preset_name}**
   - Returns stocks for given date, strategy, and preset
   - Preset is optional (returns all presets if omitted)

4. **GET /api/strategy-pool/trade-history?symbol={symbol}&strategy={strategy}&preset={preset}**
   - Returns complete trade history (buy + sell) for a stock
   - Used for K-line chart visualization

## Preset Parameters

### Turtle Strategy

| Parameter | Conservative | Standard | Aggressive |
|-----------|-------------|----------|------------|
| entry_window | 20 days | 55 days | 70 days |
| Description | Tighter breakout = stronger signal | Classic Turtle | Longer window = more trends |

### Single Yang Strategy

| Parameter | Conservative | Default | Aggressive |
|-----------|-------------|---------|------------|
| big_yang_rate | 7% | 5% | 4% |
| vol_expand_rate | 2.0x | 1.5x | 1.3x |
| Description | Strict pattern | Standard | Loose pattern |

### Hidden Dragon Strategy

| Parameter | Conservative | Default | Aggressive |
|-----------|-------------|---------|------------|
| max_callback_days | 5 days | 20 days | 10 days |
| entry_ma_period | 10 days | 60 days | 20 days |
| Description | Quick pullback | Standard | Medium pullback |

## Best Practices

1. **Run Multiple Presets**: Always run both conservative and aggressive to see the full spectrum
2. **Track Performance**: Monitor win-rates of each preset over 2-4 weeks
3. **Adjust Based on Market**: Bear market → use conservative; Bull market → can use aggressive
4. **Combine with Historical Filters**: Use `--min-win-rate 0.50` to further filter results
5. **Portfolio Allocation**: 
   - 70% capital on conservative signals
   - 30% capital on aggressive signals (for diversification)
6. **Use Charts for Validation**:
   - Click stocks to see historical buy/sell points
   - Verify strategy logic makes sense
   - Check if past trades were profitable

## Troubleshooting

**Q: Preset dropdown is empty in frontend**
- A: Run screening with `--preset` parameter first
- The frontend only shows presets that exist in database

**Q: Same stocks appear in both conservative and aggressive**
- A: This is expected! Conservative is a subset of aggressive
- Stocks appearing in conservative are the "best of the best"

**Q: Can I run without preset?**
- A: Yes, omit `--preset` to use default parameters
- Will be stored as preset="default" in database

**Q: K-line chart shows no buy/sell markers**
- A: Trade history is only available for stocks screened with strategy info
- Click stocks from "Strategy Stock Pool" tab, not "Watchlist"
- Make sure you ran screening recently (data expires)

**Q: How to interpret buy/sell markers?**
- Green B (bottom): Strategy detected buy signal at this price
- Red S (top): Strategy detected sell signal at this price
- Check if price rose after buy, and if sell captured profit
- Multiple B-S cycles show strategy's complete behavior
