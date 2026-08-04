#!/usr/bin/env python3
"""Unit tests for SimpleBacktestRunner."""

import unittest
from unittest.mock import Mock, patch

from worker.simple_backtest_runner import SimpleBacktestRunner


class TestSimpleBacktestRunner(unittest.TestCase):
    """Test cases for SimpleBacktestRunner."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.runner = SimpleBacktestRunner()
        
    def test_run_backtest_basic(self):
        """Test basic backtest execution against mocked bars."""
        import pandas as pd
        from quant_strategies.strategies import STRATEGY_MAP

        # Grid needs 50+ bars to pass the runner's pre-flight length check.
        n_bars = 120
        dates = pd.date_range(start='2023-01-01', periods=n_bars, freq='D')
        mock_df = pd.DataFrame(
            {
                'open': [100 + i for i in range(n_bars)],
                'high': [105 + i for i in range(n_bars)],
                'low': [95 + i for i in range(n_bars)],
                'close': [104 + i for i in range(n_bars)],
                'volume': [1000 + i * 100 for i in range(n_bars)],
            },
            index=dates,
        )

        # setUp already built the runner, so patching the module attribute
        # would come too late; swap the loader on the instance instead.
        mock_df = mock_df.copy()
        mock_df["pre_close"] = mock_df["close"].shift(1).fillna(mock_df["close"])
        mock_df["adj_factor"] = 1.0
        mock_df.attrs = {
            "adj_degraded": False,
            "adj_coverage": 1.0,
            "adj_bfilled": False,
        }
        self.runner.adj_loader = Mock()
        self.runner.adj_loader.load_adjusted_ohlc.return_value = mock_df

        results = self.runner.run_backtest(
            symbol='TEST.SZ',
            strategy_class=STRATEGY_MAP['grid'],
            start_date='20230101',
            end_date='20230430',
            initial_cash=100000,
        )

        self.assertIn('metrics', results)
        self.assertIn('trades', results)
        self.assertIn('equity_curve', results)
        self.runner.adj_loader.load_adjusted_ohlc.assert_called_once()
    
    def test_create_data_feed(self):
        """Test data feed creation."""
        import pandas as pd
        
        # Create sample data
        df = pd.DataFrame({
            'open': [100, 101, 102],
            'high': [105, 106, 107],
            'low': [95, 96, 97],
            'close': [104, 105, 106],
            'volume': [1000, 1100, 1200]
        })
        df.index = pd.to_datetime(['2023-01-01', '2023-01-02', '2023-01-03'])
        
        # Test data feed creation
        data_feed = self.runner._create_data_feed(df, 'TEST.SZ')
        
        # Verify data feed properties
        self.assertEqual(data_feed.symbol, 'TEST.SZ')
        self.assertEqual(data_feed._name, 'TEST.SZ')

    @patch('stock_data_access.mongo_context.get_db')
    def test_fetch_etf_frame(self, mock_get_db):
        """Test ETF daily bars are loaded from etf_daily."""
        class FakeCursor(list):
            def sort(self, *_args, **_kwargs):
                return self

        class FakeCollection:
            def find(self, query, projection):
                self.query = query
                self.projection = projection
                return FakeCursor([
                    {
                        "ts_code": "510300.SH",
                        "trade_date": "20240102",
                        "open": 3.5,
                        "high": 3.6,
                        "low": 3.4,
                        "close": 3.55,
                        "vol": 100000,
                    }
                ])

        fake_etf_daily = FakeCollection()
        mock_get_db.return_value = {"etf_daily": fake_etf_daily}

        df = self.runner._fetch_etf_frame("510300.SH", "20240101", "20240131")

        self.assertFalse(df.empty)
        self.assertEqual(list(df.columns), ["open", "high", "low", "close", "volume"])
        self.assertEqual(df.iloc[0]["volume"], 100000)
        self.assertEqual(fake_etf_daily.query["ts_code"], "510300.SH")
    
    def test_collect_results(self):
        """Test results collection."""
        # Create mock cerebro and strategy
        mock_cerebro = Mock()
        mock_cerebro.broker = Mock()
        mock_cerebro.broker.getvalue.return_value = 110000.0
        
        mock_strategy = Mock()
        mock_strategy.trades_log = [
            {
                "action": "BUY",
                "size": 900,
                "price": 100.0,
                "position_after": 900,
                "avg_cost": 100.0,
            }
        ]
        mock_strategy.analyzers = Mock()
        mock_strategy.analyzers.getbyname.return_value = None
        mock_strategy.__class__ = Mock()
        mock_strategy.__class__.__name__ = 'MockStrategy'
        mock_strategy.equity_history = []
        
        # Test results collection
        results = self.runner._collect_results(
            mock_cerebro, 
            mock_strategy, 
            'TEST.SZ', 
            '20230101', 
            '20230103', 
            100000.0
        )
        
        # Verify results structure
        self.assertIn('metrics', results)
        self.assertIn('trades', results)
        self.assertIn('equity_curve', results)
        self.assertEqual(results['metrics']['invested_cash'], 90000.0)
        self.assertAlmostEqual(results['metrics']['invested_return'], 10000.0 / 90000.0)
        self.assertEqual(results['metrics']['capital_utilization'], 0.9)

    def test_sanitize_params_drops_invalid_ai_combo_keys(self):
        class FakeStrategy:
            params = (
                ("entry_ma_period", 60),
                ("ma_proximity_pct", 0.01),
            )

        raw = {
            "entry_ma_period": 20,
            "entry_ma_period + ma_proximity_pct": 0.03,
            "ma_proximity_pct": 0.02,
        }
        sanitized = self.runner._sanitize_params(FakeStrategy, raw)
        self.assertEqual(
            sanitized,
            {"entry_ma_period": 20, "ma_proximity_pct": 0.02},
        )

    def test_sanitize_params_drops_batch_metadata_and_reads_backtrader_params(self):
        try:
            from backtest_worker import STRATEGY_MAP
        except ImportError:
            from worker.backtest_worker import STRATEGY_MAP

        cls = STRATEGY_MAP.get("hidden_dragon")
        self.assertTrue(self.runner._strategy_param_names(cls))

        raw = {
            "universe_value": "csi1000",
            "universe_type": "index",
            "entry_ma_period": 20,
        }
        sanitized = self.runner._sanitize_params(cls, raw)
        self.assertEqual(sanitized, {"entry_ma_period": 20})

    def test_etf_default_target_position_survives_turtle_sanitization(self):
        class FakeTurtleStrategy:
            params = (
                ("entry_window", 55),
                ("target_position_pct", 0.0),
            )

        sanitized = self.runner._sanitize_params(
            FakeTurtleStrategy,
            {"target_position_pct": 0.95},
        )
        self.assertEqual(sanitized, {"target_position_pct": 0.95})

    def test_estimate_required_bars_single_yang_uses_ma120(self):
        """use_min_ma_exit builds MA120; short windows must not pass the pre-check."""
        from quant_strategies.strategies import STRATEGY_MAP
        from quant_strategies.strategy_params import get_preset

        cls = STRATEGY_MAP["single_yang"]
        # Strategy default alone (no explicit params)
        self.assertEqual(self.runner._estimate_required_bars(cls, None), 120)
        # Screening preset dataclass
        yang = get_preset("yang_conservative")
        self.assertEqual(self.runner._estimate_required_bars(cls, yang), 120)
        self.assertEqual(self.runner._estimate_required_bars(cls, yang.to_dict()), 120)
        # Explicit disable falls back to exit_ma_period
        self.assertEqual(
            self.runner._estimate_required_bars(
                cls, {"use_min_ma_exit": False, "exit_ma_period": 10}
            ),
            10,
        )

    @patch.object(SimpleBacktestRunner, "_fetch_price_frame")
    def test_single_yang_short_history_raises_valueerror_not_indexerror(self, mock_fetch):
        """~80 bars used to IndexError inside Backtrader SMA; must fail cleanly."""
        import pandas as pd
        from quant_strategies.strategies import STRATEGY_MAP
        from quant_strategies.strategy_params import get_preset

        n = 80
        idx = pd.bdate_range("2026-04-01", periods=n)
        mock_fetch.return_value = pd.DataFrame(
            {
                "open": [10.0] * n,
                "high": [10.5] * n,
                "low": [9.5] * n,
                "close": [10.2] * n,
                "volume": [1_000_000] * n,
            },
            index=idx,
        )

        with self.assertRaises(ValueError) as ctx:
            self.runner.run_backtest(
                symbol="000001.SZ",
                strategy_class=STRATEGY_MAP["single_yang"],
                strategy_params=get_preset("yang_conservative"),
                start_date="20260401",
                end_date="20260731",
                initial_cash=1_000_000,
            )
        self.assertIn("need at least 120 bars", str(ctx.exception))
        self.assertIn("got 80", str(ctx.exception))

    def test_adj_degraded_raises(self):
        import pandas as pd
        from quant_strategies.strategies import STRATEGY_MAP

        dates = pd.date_range(start='2023-01-01', periods=60, freq='D')
        mock_df = pd.DataFrame(
            {
                'open': [100] * 60,
                'high': [101] * 60,
                'low': [99] * 60,
                'close': [100] * 60,
                'volume': [1000] * 60,
            },
            index=dates,
        )
        mock_df.attrs = {
            "adj_degraded": True,
            "adj_coverage": 0.0,
            "adj_bfilled": False,
        }
        self.runner.adj_loader = Mock()
        self.runner.adj_loader.load_adjusted_ohlc.return_value = mock_df

        with self.assertRaises(ValueError) as ctx:
            self.runner.run_backtest(
                symbol='TEST.SZ',
                strategy_class=STRATEGY_MAP['grid'],
                start_date='20230101',
                end_date='20230301',
                initial_cash=100000,
            )
        self.assertIn("adj_degraded", str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
