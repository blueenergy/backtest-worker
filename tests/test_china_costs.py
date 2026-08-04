#!/usr/bin/env python3
"""Unit tests for A-share commission model."""
import unittest

from worker.china_costs import AShareCommission


class TestAShareCommission(unittest.TestCase):
    def test_buy_applies_min_commission(self):
        comm = AShareCommission()
        # tiny notional -> min 5 CNY
        fee = comm.getcommission(size=100, price=1.0)
        self.assertEqual(fee, 5.0)

    def test_sell_includes_stamp_tax(self):
        comm = AShareCommission()
        buy_fee = comm.getcommission(size=1000, price=10.0)
        sell_fee = comm.getcommission(size=-1000, price=10.0)
        self.assertGreater(sell_fee, buy_fee)

    def test_percabs_rate_is_literal_fraction(self):
        comm = AShareCommission()
        # 10000 shares @ 10 = 100k notional; commission 0.01% = 10 + transfer
        fee = comm.getcommission(size=10000, price=10.0)
        self.assertGreater(fee, 10.0)
        self.assertLess(fee, 15.0)


if __name__ == "__main__":
    unittest.main()
