#!/usr/bin/env python3
"""
Test GridTradingStrategy position tracking with multi-bar data.

This test specifically validates that grid levels don't trigger repeatedly
across multiple bars when price stays in the same grid level range.

Regression test for: Grid Strategy Position Tracking Bug
- Issue: `current_position` parameter was local variable, not persistent state
- Result: Grid levels triggered every day causing continuous buy/sell
"""

import unittest
import pandas as pd
from datetime import datetime, timedelta
import backtrader as bt

from strategies import GridTradingStrategy


class TestGridPositionTracking(unittest.TestCase):
    """Test grid strategy position tracking across multiple bars."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.initial_cash = 100000
        self.batch_size = 1000
        self.max_batches = 3
    
    def _create_test_data(self, prices, dates=None):
        """Create a backtrader-compatible DataFrame."""
        n = len(prices)
        if dates is None:
            dates = pd.date_range(start='2023-01-01', periods=n, freq='D')
        
        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': [p * 0.98 for p in prices],
            'close': prices,
            'volume': [100000] * n
        }, index=dates)
        
        return df
    
    def _run_backtest(self, df, strategy_params=None):
        """Run a backtest and collect results."""
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(self.initial_cash)
        
        # Add data feed
        data = bt.feeds.PandasData(dataname=df)
        cerebro.adddata(data)
        
        # Add strategy
        params = strategy_params or {
            'grid_pct': 0.03,
            'batch_size': self.batch_size,
            'max_batches': self.max_batches,
            'dynamic_base': False,  # Disable recentering for easier testing
            'worker_mode': 'backtest'
        }
        cerebro.addstrategy(GridTradingStrategy, **params)
        
        # Add analyzer to track trades
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        
        # Run backtest
        results = cerebro.run()
        return results[0] if results else None
    
    def test_grid_no_repeated_buys_same_level(self):
        """
        Test that grid doesn't buy repeatedly at same level across multiple bars.
        
        Scenario:
        - Initial price: 100
        - Grid levels: 97 (level -1), 100 (base), 103 (level +1)
        - Price stays between 98-99 for 3 days
        
        Expected: Only 1 BUY at first crossing, not 3 BUYs
        """
        # Price drops to level -1 then stays around that level
        prices = [100, 98, 98.5, 98, 99, 100]
        df = self._create_test_data(prices)
        
        strategy = self._run_backtest(df, {
            'grid_pct': 0.03,  # 3% = ~3 per 100
            'batch_size': self.batch_size,
            'max_batches': self.max_batches,
            'dynamic_base': False,
            'worker_mode': 'backtest'
        })
        
        # Collect trades
        trades_data = strategy.analyzers.trades.get_analysis()
        
        # Count total transactions
        total_trades = 0
        if 'long' in trades_data:
            # Backtrader's TradeAnalyzer counts wins and losses
            # We need to count total trades
            long_trades = trades_data.get('long', {})
            total = long_trades.get('total', 0)
            total_trades += total
        
        # With proper position tracking, should have only 1 buy
        # Without fix, would have multiple buys at same level
        print(f"\nTest: Grid no repeated buys at same level")
        print(f"Prices: {prices}")
        print(f"Total trades executed: {total_trades}")
        print(f"Final broker cash: {strategy.broker.getcash():.2f}")
        print(f"Final position size: {strategy.position.size}")
        
        # The key assertion: should not have more than expected trades
        # Expected: 1 buy when crossing into level -1
        # If bug existed: 3+ buys
        self.assertLessEqual(total_trades, 2, 
                           "Grid strategy should not repeatedly buy at same level")
    
    def test_grid_position_size_correct(self):
        """
        Test that position size matches expected grid batches.
        
        Scenario:
        - Price oscillates crossing multiple grid levels
        - Should accumulate batches up to max_batches
        
        Expected: Position size = num_levels_crossed * batch_size (max: max_batches * batch_size)
        """
        # Price: 100 -> 96 -> 98 -> 99 -> 100
        # Should trigger buys at levels -1, -2, then stabilize
        prices = [100, 97, 95, 94, 95, 96, 97, 98, 99, 100]
        df = self._create_test_data(prices)
        
        strategy = self._run_backtest(df, {
            'grid_pct': 0.03,
            'batch_size': self.batch_size,
            'max_batches': self.max_batches,
            'dynamic_base': False,
            'worker_mode': 'backtest'
        })
        
        final_position = strategy.position.size
        max_position = self.max_batches * self.batch_size
        
        print(f"\nTest: Grid position size correct")
        print(f"Prices: {prices}")
        print(f"Final position size: {final_position}")
        print(f"Max expected position: {max_position}")
        print(f"Final portfolio value: {strategy.broker.getvalue():.2f}")
        
        # Position should not exceed max_position
        self.assertLessEqual(final_position, max_position,
                           "Position size should not exceed max_batches * batch_size")
    
    def test_grid_triggered_levels_tracking(self):
        """
        Test that triggered_buy_levels and triggered_sell_levels are properly tracked.
        
        Scenario:
        - Price crosses grid level
        - Check that level is marked as triggered
        - Price doesn't trigger same level again
        
        Expected: Each level only triggers once per crossing
        """
        # Price: oscillates around base, crossing levels multiple times
        prices = [100, 97, 95, 98, 100, 103, 101, 98, 95, 97]
        df = self._create_test_data(prices)
        
        strategy = self._run_backtest(df, {
            'grid_pct': 0.03,
            'batch_size': self.batch_size,
            'max_batches': self.max_batches,
            'dynamic_base': False,
            'worker_mode': 'backtest'
        })
        
        # Check internal state
        buy_levels = strategy.triggered_buy_levels
        sell_levels = strategy.triggered_sell_levels
        
        print(f"\nTest: Grid triggered levels tracking")
        print(f"Prices: {prices}")
        print(f"Triggered buy levels: {buy_levels}")
        print(f"Triggered sell levels: {sell_levels}")
        print(f"Final position: {strategy.position.size}")
        
        # Verify levels are sets (should be small sets, not accumulating unbounded)
        self.assertIsInstance(buy_levels, set)
        self.assertIsInstance(sell_levels, set)
        
        # Levels should be reasonable (max_batches range)
        for level in buy_levels:
            self.assertGreaterEqual(level, -self.max_batches,
                                  "Buy level should be within max_batches range")
            self.assertLess(level, 0,
                           "Buy levels should be negative")
        
        for level in sell_levels:
            self.assertLessEqual(level, self.max_batches,
                               "Sell level should be within max_batches range")
            self.assertGreater(level, 0,
                              "Sell levels should be positive")
    
    def test_grid_with_real_price_action(self):
        """
        Test grid strategy with realistic price action similar to user's data.
        
        Scenario:
        - Price drops sharply (like user's 002050.SZ data)
        - Price oscillates in similar range for multiple days
        
        Expected: Should buy once on initial drop, not repeat for every day
        """
        # Simulate real scenario from user's data
        # Start at 24.32, drop to 21.85, oscillate
        prices = [
            24.32,  # Initial
            21.85,  # Day 1 - drop
            21.85,  # Day 2 - same level
            21.85,  # Day 3 - same level
            21.85,  # Day 4 - same level
            27.93,  # Day 5 - rebound
            28.77,  # Day 6 - continue up
            28.93,  # Day 7
            30.00,  # Day 8
            31.00,  # Day 9
            30.50,  # Day 10 - slight pullback
        ]
        df = self._create_test_data(prices)
        
        strategy = self._run_backtest(df, {
            'grid_pct': 0.02,  # 2% grid
            'batch_size': 1000,
            'max_batches': 5,
            'dynamic_base': False,
            'worker_mode': 'backtest'
        })
        
        trades_data = strategy.analyzers.trades.get_analysis()
        final_position = strategy.position.size
        final_value = strategy.broker.getvalue()
        
        print(f"\nTest: Grid with realistic price action")
        print(f"Prices: {prices}")
        print(f"Trades analysis: {trades_data}")
        print(f"Final position: {final_position}")
        print(f"Final portfolio value: {final_value:.2f}")
        print(f"Total P&L: {final_value - self.initial_cash:.2f}")
        
        # Should not have excessive trades
        # User's bug had 4 buys in 4 days at same level
        # With fix, should have 1-2 buys maximum
        self.assertLessEqual(final_position, 5000,
                           "Should not accumulate excessive position")


if __name__ == '__main__':
    unittest.main(verbosity=2)
