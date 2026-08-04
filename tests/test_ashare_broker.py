#!/usr/bin/env python3
"""Unit tests for A-share limit broker helpers."""
import unittest

import pandas as pd

from worker.ashare_broker import annotate_limit_flags, _limit_pct


class TestAShareBroker(unittest.TestCase):
    def test_limit_pct_main_board(self):
        self.assertEqual(_limit_pct("600519.SH"), 0.10)

    def test_limit_pct_chinext(self):
        self.assertEqual(_limit_pct("300750.SZ"), 0.20)

    def test_annotate_limit_flags(self):
        df = pd.DataFrame(
            {
                "pre_close": [10.0, 10.0, 10.0],
                "close": [11.0, 10.0, 9.0],
                "open": [10.0, 10.0, 10.0],
                "high": [11.0, 10.0, 9.0],
                "low": [10.0, 10.0, 9.0],
                "volume": [100, 100, 100],
            },
            index=pd.date_range("2024-01-01", periods=3, freq="B"),
        )
        out = annotate_limit_flags(df, "600519.SH")
        self.assertTrue(bool(out["limit_up"].iloc[0]))
        self.assertTrue(bool(out["limit_down"].iloc[2]))


if __name__ == "__main__":
    unittest.main()
