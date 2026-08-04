"""A-share commission model for Backtrader backtests.

Models bilateral broker commission (with minimum per order), sell-side stamp
duty, and optional transfer fee.  Uses ``percabs=True`` so rate params are
literal fractions (e.g. 0.0001 = 万分之一).
"""
from backtrader import CommInfoBase


class AShareCommission(CommInfoBase):
    """China A-share stock commission scheme."""

    params = (
        ("stocklike", True),
        ("commtype", CommInfoBase.COMM_PERC),
        ("percabs", True),
        ("commission", 0.0001),  # bilateral broker fee (万分之一)
        ("stamp_tax", 0.0005),  # sell-side stamp duty (0.05%)
        ("transfer_fee", 0.00001),  # bilateral transfer fee (0.001%)
        ("min_commission", 5.0),  # minimum CNY per order
    )

    def _getcommission(self, size, price, pseudoexec):  # noqa: ARG002
        if size == 0 or price <= 0:
            return 0.0

        notional = abs(size) * price
        commission = notional * self.p.commission
        transfer = notional * self.p.transfer_fee
        stamp = notional * self.p.stamp_tax if size < 0 else 0.0
        total = commission + transfer + stamp
        return max(total, self.p.min_commission)


__all__ = ["AShareCommission"]
