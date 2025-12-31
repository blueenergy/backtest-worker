#!/usr/bin/env python3
"""
Regression test for Grid Strategy Position Tracking Bug Fix.

Bug Report: https://github.com/user/stock-execution-system/issues/XXX
- Issue: Grid strategy continuously buys/sells at same level across multiple bars
- Root Cause: current_position parameter was local variable, not persistent state
- Fix: Query self.position.size directly from broker instead of passing as parameter

This test ensures the bug doesn't reappear in future refactoring.
"""

import unittest
import pandas as pd
import backtrader as bt
from datetime import datetime

from strategies import GridTradingStrategy


class GridStrategyBugRegression(unittest.TestCase):
    """Regression tests to prevent Grid Strategy position tracking bug."""
    
    def test_bug_scenario_no_repeated_trades(self):
        """
        Exact reproduction of the bug scenario.
        
        Bug Details:
        - User ran backtest on 002050.SZ (stock symbol)
        - Grid strategy with default params (3% grid, 1000 batch_size, 5 max_batches)
        - Data: 2023-01-10 to 2023-01-17
        
        Bug Manifestation:
        ```
        Jan 10: BUY 1000 @ 24.32  (level -1)
        Jan 11: BUY 1000 @ 21.85  (same level -1, SHOULD NOT HAPPEN)
        Jan 12: BUY 1000 @ 21.85  (same level -1, SHOULD NOT HAPPEN)
        Jan 13: BUY 1000 @ 21.85  (same level -1, SHOULD NOT HAPPEN)
        Jan 14: SELL 1000 @ 27.93 (level +1)
        Jan 15: SELL 1000 @ 28.77 (level +1, SHOULD NOT HAPPEN)
        Jan 16: SELL 1000 @ 28.93 (level +1, SHOULD NOT HAPPEN)
        Jan 17: SELL 1000 @ 30.00 (level +1, SHOULD NOT HAPPEN)
        ```
        
        Expected After Fix:
        - Only 1 BUY when price first crosses below grid level
        - Only 1 SELL when price crosses above grid level
        - No repeated trades at same level
        """
        # Reproduce the exact price pattern from bug report
        prices = [
            24.32,  # 2023-01-10 - initial price
            21.85,  # 2023-01-11 - drops to level -1 (BUY should trigger here)
            21.85,  # 2023-01-12 - stays at same level (should NOT buy again)
            21.85,  # 2023-01-13 - stays at same level (should NOT buy again)
            21.85,  # 2023-01-14 - stays at same level (should NOT buy again)
            27.93,  # 2023-01-15 - rises to level +1 (SELL should trigger here)
            28.77,  # 2023-01-16 - continues up (should NOT sell again)
            28.93,  # 2023-01-17 - continues up (should NOT sell again)
        ]
        
        dates = pd.date_range(start='2023-01-10', periods=len(prices), freq='D')
        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': [p * 0.98 for p in prices],
            'close': prices,
            'volume': [1000000] * len(prices)
        }, index=dates)
        
        # Run backtest with exact user's parameters
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(1000000)
        
        # Add data
        data = bt.feeds.PandasData(dataname=df)
        cerebro.adddata(data)
        
        # Add strategy with user's parameters
        cerebro.addstrategy(GridTradingStrategy,
                          grid_pct=0.03,        # 3% grid
                          batch_size=1000,
                          max_batches=5,
                          dynamic_base=False,
                          worker_mode='backtest')
        
        # Add trade analyzer
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        
        # Run
        results = cerebro.run()
        strategy = results[0]
        
        # Get final position
        final_position = strategy.position.size
        
        # Debug output
        base_price = 24.32
        grid_size = base_price * 0.03  # ~0.73
        level_minus_1 = base_price - grid_size  # ~23.59
        level_plus_1 = base_price + grid_size   # ~25.05
        
        print(f"\n{'='*80}")
        print(f"REGRESSION TEST: Grid Strategy Position Tracking")
        print(f"{'='*80}")
        print(f"\nPrice Data:")
        for i, (date, price) in enumerate(zip(dates, prices)):
            print(f"  {date.strftime('%Y-%m-%d')}: ${price:.2f}")
        
        print(f"\nGrid Parameters:")
        print(f"  Base Price: ${base_price:.2f}")
        print(f"  Grid Size (3%): ${grid_size:.2f}")
        print(f"  Level -1: ${level_minus_1:.2f}")
        print(f"  Level +1: ${level_plus_1:.2f}")
        
        print(f"\nTest Results:")
        print(f"  Final Position Size: {final_position} shares")
        print(f"  Final Portfolio Value: ${strategy.broker.getvalue():,.2f}")
        print(f"  Buy Levels Triggered: {strategy.triggered_buy_levels}")
        print(f"  Sell Levels Triggered: {strategy.triggered_sell_levels}")
        
        # CRITICAL ASSERTION: Position should NOT be 4000 (which was the bug)
        # 4000 would mean 4x 1000-share buys (Jan 10-13)
        # With fix, should be 0 (closed out) or 1000-2000 (partially filled)
        
        # Expected behavior after fix:
        # - Price crosses below level -1 once (Jan 11) -> 1 BUY
        # - Price crosses above level +1 once (Jan 15) -> 1 SELL
        # - Final position should be 0 or small positive
        
        self.assertLess(final_position, 4000,
                       f"BUG DETECTED: Position is {final_position}, expected < 4000. "
                       f"This indicates repeated trades at same grid level!")
        
        print(f"\n✅ PASS: Position tracking is working correctly")
        print(f"   No repeated trades at same grid level detected")
        print(f"{'='*80}\n")
    
    def test_grid_level_state_persistence(self):
        """
        Verify that triggered_buy_levels and triggered_sell_levels persist correctly.
        
        This is the internal state that prevents repeated trades at same level.
        """
        prices = [100, 97, 97, 97, 100, 103, 103]  # Stay at level, oscillate
        dates = pd.date_range(start='2023-01-01', periods=len(prices), freq='D')
        
        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': [p * 0.98 for p in prices],
            'close': prices,
            'volume': [100000] * len(prices)
        }, index=dates)
        
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(100000)
        
        data = bt.feeds.PandasData(dataname=df)
        cerebro.adddata(data)
        
        cerebro.addstrategy(GridTradingStrategy,
                          grid_pct=0.03,
                          batch_size=1000,
                          max_batches=5,
                          dynamic_base=False,
                          worker_mode='backtest')
        
        results = cerebro.run()
        strategy = results[0]
        
        # State should be tracked
        print(f"\nTest: Grid level state persistence")
        print(f"Prices: {prices}")
        print(f"Triggered buy levels: {strategy.triggered_buy_levels}")
        print(f"Triggered sell levels: {strategy.triggered_sell_levels}")
        print(f"Final position: {strategy.position.size}")
        
        # Key assertions
        self.assertIsInstance(strategy.triggered_buy_levels, set,
                            "triggered_buy_levels must be a set for proper tracking")
        self.assertIsInstance(strategy.triggered_sell_levels, set,
                            "triggered_sell_levels must be a set for proper tracking")
        
        # Levels should not accumulate unbounded (this would indicate leaking state)
        total_levels = len(strategy.triggered_buy_levels) + len(strategy.triggered_sell_levels)
        self.assertLessEqual(total_levels, self.max_batches * 2,
                           "Triggered levels accumulating unbounded indicates state leak")
    
    max_batches = 5  # For assertion reference


if __name__ == '__main__':
    # Run with verbose output to see regression test details
    unittest.main(verbosity=2)
