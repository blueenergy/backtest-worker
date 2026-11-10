#!/usr/bin/env python3
"""期货双均线回测（研究脚本，不接生产回测链路）。

数据：``quant_data.fut_daily``（Tushare 主力连续日线，不复权）。
策略：复用 ``quant-strategies`` 的 ``SmaCrossStrategy`` 信号规则
（金叉做多 / 死叉平多 + ATR chandelier 止损 + ATR 风险仓位），只把执行层
换成期货口径：

* 1 手 = 1 个合约单位（不是 A 股 100 股）
* 仓位同时受风险预算与保证金上限约束
* ``--allow-short`` 时死叉反手做空、金叉反手做多
* 手续费支持「成交金额比例 + 每手固定」两种口径，无印花税

为什么不能直接用 SimpleBacktestRunner：
* 它按 ``volume_price + adj_factor`` 取股票数据，期货在 ``fut_daily``
* ``AShareBroker`` 用 10% 默认涨跌幅算涨跌停，会把 RB 的正常波动误判成板
* ``AShareCommission`` 是印花税 / 最低 5 元口径

主力连续换月：
``fut_daily`` 的 ``RB.SHF`` 是主连拼接。实测换月日绝对收益均值 2.94%，
非换月 0.96%；直接回测会被换月跳空触发假信号。默认 ``--roll-mode
back_adjust`` 按换月日收盘比回填历史价格（标准后复权拼接）；``--roll-mode
none`` 保留原始主连，仅用于对照。

用法（镜像更新后，容器内）::

    docker exec apps-backtest-worker-1 python3 \
        /app/scripts/futures_sma_backtest.py \
        --symbol RB.SHF --start 20100101 --end 20261109 \
        --fast 10 --slow 30 --allow-short

    # 参数网格 + JSON
    ... --fast 5,10,20 --slow 20,30,60 --json-out /tmp/rb_sma.json

本地有依赖时也可直接::

    python3 scripts/futures_sma_backtest.py --symbol RB.SHF --fast 10 --slow 30

注意：合约乘数/保证金/费率是研究默认值，会随交易所和期货公司调整；实盘前
必须按当期合约表核对。tick 由库内收盘价的最小变动反推。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import backtrader as bt
import numpy as np
import pandas as pd

try:
    from quant_strategies.strategies.sma import SmaCrossStrategy
except ImportError:  # 本地未装 quant-strategies 时，从 monorepo 相对路径兜底
    _ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_ROOT / "quant-strategies"))
    from quant_strategies.strategies.sma import SmaCrossStrategy


# --------------------------------------------------------------------------- specs
@dataclass(frozen=True)
class ContractSpec:
    name: str
    mult: float          # 合约乘数（每点/每吨/每桶对应的元数）
    tick: float          # 最小变动价位（由库内收盘价最小变动反推）
    margin: float        # 保证金比例（研究默认）
    fee_rate: float = 0.0    # 单边手续费，按成交金额（含乘数）比例
    fee_per_lot: float = 0.0  # 单边手续费，每手固定元数


# 与 quant-data-engine/constants/fut_codes.py 的白名单一致。
# 保证金/费率是研究默认值，不是交易所权威数据。
CONTRACT_SPECS: Dict[str, ContractSpec] = {
    "IF.CFX": ContractSpec("沪深300股指", 300, 0.2, 0.12, fee_rate=0.000023),
    "IH.CFX": ContractSpec("上证50股指", 200, 0.2, 0.12, fee_rate=0.000023),
    "IC.CFX": ContractSpec("中证500股指", 200, 0.2, 0.12, fee_rate=0.000023),
    "IM.CFX": ContractSpec("中证1000股指", 100, 0.2, 0.12, fee_rate=0.000023),
    "AU.SHF": ContractSpec("黄金", 1000, 0.01, 0.10, fee_per_lot=10.0),
    "CU.SHF": ContractSpec("沪铜", 5, 10.0, 0.10, fee_rate=0.00005),
    "AL.SHF": ContractSpec("沪铝", 5, 5.0, 0.10, fee_per_lot=3.0),
    "RB.SHF": ContractSpec("螺纹钢", 10, 1.0, 0.10, fee_rate=0.0001),
    "I.DCE": ContractSpec("铁矿石", 100, 0.5, 0.12, fee_rate=0.0001),
    "J.DCE": ContractSpec("焦炭", 100, 0.5, 0.12, fee_rate=0.0001),
    "JM.DCE": ContractSpec("焦煤", 60, 0.5, 0.12, fee_rate=0.0001),
    "M.DCE": ContractSpec("豆粕", 10, 1.0, 0.10, fee_per_lot=1.5),
    "SC.INE": ContractSpec("原油", 1000, 0.1, 0.12, fee_per_lot=20.0),
    "CF.ZCE": ContractSpec("棉花", 5, 5.0, 0.10, fee_per_lot=4.3),
    "TA.ZCE": ContractSpec("PTA", 5, 2.0, 0.10, fee_per_lot=3.0),
    "LC.GFE": ContractSpec("碳酸锂", 1, 20.0, 0.12, fee_rate=0.0001),
}


# ----------------------------------------------------------------------- commission
class FuturesCommission(bt.CommInfoBase):
    """期货手续费 + 按名义价值计算的保证金。"""

    params = (
        ("stocklike", False),
        ("commtype", bt.CommInfoBase.COMM_PERC),
        ("percabs", True),
        ("commission", 0.0),
        ("mult", 1.0),
        ("margin_pct", 0.10),
        ("fee_per_lot", 0.0),
    )

    def _getcommission(self, size, price, pseudoexec):  # noqa: ARG002
        return abs(size) * (
            price * self.p.mult * self.p.commission + self.p.fee_per_lot
        )

    def get_margin(self, price):
        return price * self.p.mult * self.p.margin_pct


# ------------------------------------------------------------------------ strategy
class FuturesSmaCross(SmaCrossStrategy):
    """``SmaCrossStrategy`` 的期货执行版。

    信号规则与股票版一致（SMA 金叉/死叉 + chandelier 止损 + ATR 风险仓位）；
    差异只在执行层：合约手数、乘数、保证金，以及可选的做空反手。
    """

    params = (
        ("allow_short", False),
        ("mult", 10.0),
        ("margin_pct", 0.10),
        ("risk_per_trade", 0.01),
        ("atr_stop_mult", 2.5),
        ("max_hold_bars", 0),
    )

    def __init__(self):
        super().__init__()
        self.equity_curve: List[float] = []
        self.exposure_bars = 0
        self._last_pos = 0
        self._high_since_entry = 0.0
        self._low_since_entry = 0.0
        self._entry_bar = -1

    # -- sizing ------------------------------------------------------------
    def validate_lot_size(self, qty: int) -> int:
        return max(0, int(qty))

    def _contracts_for_risk(self, price: float) -> int:
        atr = float(self._risk_atr[0] or 0.0)
        stop_distance = atr * float(getattr(self.p, "atr_stop_mult", 2.5))
        if stop_distance <= 0 or price <= 0:
            return 0
        risk_budget = self.broker.getvalue() * float(
            getattr(self.p, "risk_per_trade", 0.01)
        )
        by_risk = int(risk_budget / (stop_distance * self.p.mult))
        margin_per_lot = price * self.p.mult * self.p.margin_pct
        by_margin = (
            int(self.broker.getcash() * 0.95 / margin_per_lot)
            if margin_per_lot > 0
            else 0
        )
        return max(0, min(by_risk, by_margin))

    # -- risk --------------------------------------------------------------
    def _sync_position_state(self) -> None:
        pos = int(self.position.size)
        if pos == self._last_pos:
            return
        self._last_pos = pos
        if pos:
            price = float(self.position.price)
            self._high_since_entry = price
            self._low_since_entry = price
            self._entry_bar = len(self)
        else:
            self._high_since_entry = 0.0
            self._low_since_entry = 0.0
            self._entry_bar = -1

    def _risk_exit(self, price: float, pos: int) -> bool:
        atr = float(self._risk_atr[0] or 0.0)
        if atr <= 0:
            return False
        stop_mult = float(getattr(self.p, "atr_stop_mult", 2.5))
        if pos > 0:
            self._high_since_entry = max(self._high_since_entry, price)
            if price <= self._high_since_entry - stop_mult * atr:
                return True
        else:
            self._low_since_entry = min(self._low_since_entry, price)
            if price >= self._low_since_entry + stop_mult * atr:
                return True

        max_hold = int(getattr(self.p, "max_hold_bars", 0))
        if max_hold > 0 and self._entry_bar >= 0:
            if len(self) - self._entry_bar >= max_hold:
                return True
        return False

    # -- main loop ---------------------------------------------------------
    def next(self):
        price = float(self.data.close[0])
        self._sync_position_state()
        pos = self._last_pos

        fast = float(self.sma_fast[0])
        slow = float(self.sma_slow[0])
        prev_fast = float(self.sma_fast[-1])
        prev_slow = float(self.sma_slow[-1])
        cross_up = fast > slow and prev_fast <= prev_slow
        cross_down = fast < slow and prev_fast >= prev_slow

        if pos == 0:
            if cross_up:
                size = self._contracts_for_risk(price)
                if size:
                    self.buy(size=size)
                    self.log(f"BUY {size} lots @ {price:.2f} (golden cross)")
            elif cross_down and self.p.allow_short:
                size = self._contracts_for_risk(price)
                if size:
                    self.sell(size=size)
                    self.log(f"SELL {size} lots @ {price:.2f} (death cross)")
        elif pos > 0:
            if self._risk_exit(price, pos):
                self.close()
                self.log(f"CLOSE long @ {price:.2f} (risk exit)")
            elif cross_down:
                self.close()
                self.log(f"CLOSE long @ {price:.2f} (death cross)")
                if self.p.allow_short:
                    size = self._contracts_for_risk(price)
                    if size:
                        self.sell(size=size)
        else:
            if self._risk_exit(price, pos):
                self.close()
                self.log(f"CLOSE short @ {price:.2f} (risk exit)")
            elif cross_up:
                self.close()
                self.log(f"CLOSE short @ {price:.2f} (golden cross)")
                size = self._contracts_for_risk(price)
                if size:
                    self.buy(size=size)

        if pos:
            self.exposure_bars += 1
        # BackBroker 每根 bar 会按收盘价做期货盯市现金调整，getvalue() 即 MTM 权益
        self.equity_curve.append(float(self.broker.getvalue()))


# ---------------------------------------------------------------------------- data
def get_db(args: argparse.Namespace):
    """优先走 data-access-lib（DATA_DB_NAME=quant_data），否则直连 Mongo。"""
    try:
        from stock_data_access.mongo_context import get_db as _get_db

        return _get_db()
    except Exception:
        from pymongo import MongoClient

        uri = args.mongo_uri or os.environ.get("MONGO_URI", "mongodb://localhost:27017")
        name = args.data_db or os.environ.get("DATA_DB_NAME", "quant_data")
        return MongoClient(uri)[name]


def load_futures_frame(db, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    docs = list(
        db["fut_daily"].find(
            {
                "ts_code": symbol,
                "trade_date": {"$gte": start_date, "$lte": end_date},
            },
            {
                "_id": 0,
                "trade_date": 1,
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "vol": 1,
                "contract": 1,
            },
        ).sort("trade_date", 1)
    )
    if not docs:
        raise SystemExit(
            f"fut_daily 没有 {symbol} 在 {start_date}-{end_date} 的数据；"
            "检查 DATA_DB_NAME 是否指向 quant_data。"
        )

    frame = pd.DataFrame(docs)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d")
    frame = frame.set_index("trade_date").sort_index()
    for col in ("open", "high", "low", "close", "vol"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close"])
    frame["volume"] = frame["vol"].fillna(0.0)
    return frame


def count_rolls(frame: pd.DataFrame) -> int:
    if "contract" not in frame.columns:
        return 0
    contracts = frame["contract"].fillna("").astype(str)
    changed = contracts.ne(contracts.shift(1)).to_numpy(copy=True)
    if len(changed):
        changed[0] = False
    return int(changed.sum())


def back_adjust_rolls(frame: pd.DataFrame) -> pd.DataFrame:
    """按换月日收盘比回填历史价格（最新一段保持原始价位）。

    主连换月跳空是拼接伪影，不是可交易收益。后复权后最新价格仍是真实价位，
    早期价格只用于收益/信号，不参与当前名义价值计算。
    """
    out = frame.copy()
    if "contract" not in out.columns:
        return out

    contracts = out["contract"].fillna("").astype(str)
    changed = contracts.ne(contracts.shift(1)).to_numpy(copy=True)
    if len(changed):
        changed[0] = False

    factors = np.ones(len(out), dtype=float)
    closes = out["close"].astype(float).to_numpy()
    for i in np.flatnonzero(changed):
        prev_close = closes[i - 1]
        cur_close = closes[i]
        if prev_close > 0 and cur_close > 0:
            factors[:i] *= cur_close / prev_close

    for col in ("open", "high", "low", "close"):
        out[col] = out[col].astype(float) * factors
    return out


# ------------------------------------------------------------------------- summary
def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def summarize(
    strat: FuturesSmaCross,
    frame: pd.DataFrame,
    initial_cash: float,
    fast: int,
    slow: int,
    allow_short: bool,
) -> Dict[str, Any]:
    ta = strat.analyzers.ta.get_analysis()
    total = int(_safe_float(ta.get("total", {}).get("closed", 0)))
    won = int(_safe_float(ta.get("won", {}).get("total", 0)))
    lost = int(_safe_float(ta.get("lost", {}).get("total", 0)))
    avg_win = _safe_float(ta.get("won", {}).get("pnl", {}).get("average", 0.0))
    avg_loss = _safe_float(ta.get("lost", {}).get("pnl", {}).get("average", 0.0))
    gross_win = _safe_float(ta.get("won", {}).get("pnl", {}).get("total", 0.0))
    gross_loss = abs(_safe_float(ta.get("lost", {}).get("pnl", {}).get("total", 0.0)))

    equity = pd.Series(strat.equity_curve, dtype=float)
    if equity.empty:
        raise SystemExit("策略没有产生权益曲线（数据可能不足）")
    final_value = float(equity.iloc[-1])
    total_return = final_value / initial_cash - 1.0
    peak = equity.cummax()
    max_drawdown = float((equity / peak - 1.0).min())
    bars = len(frame)
    cagr = (
        (final_value / initial_cash) ** (252.0 / bars) - 1.0
        if final_value > 0 and bars > 0
        else float("nan")
    )
    exposure = strat.exposure_bars / len(equity) if len(equity) else 0.0

    return {
        "fast": fast,
        "slow": slow,
        "allow_short": allow_short,
        "trades": total,
        "won": won,
        "lost": lost,
        "win_rate": (won / total) if total else 0.0,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_drawdown,
        "exposure": exposure,
        "final_value": final_value,
    }


def run_one(
    frame: pd.DataFrame,
    spec: ContractSpec,
    fast: int,
    slow: int,
    cash: float,
    allow_short: bool,
    slip_ticks: float,
    risk_per_trade: float = 0.01,
    atr_stop_mult: float = 2.5,
    max_hold_bars: int = 0,
) -> Tuple[Dict[str, Any], str]:
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(
        FuturesSmaCross,
        fast_period=fast,
        slow_period=slow,
        allow_short=allow_short,
        mult=spec.mult,
        margin_pct=spec.margin,
        risk_per_trade=risk_per_trade,
        atr_stop_mult=atr_stop_mult,
        max_hold_bars=max_hold_bars,
    )
    cerebro.broker.setcash(cash)
    cerebro.broker.addcommissioninfo(
        FuturesCommission(
            commission=spec.fee_rate,
            mult=spec.mult,
            margin_pct=spec.margin,
            fee_per_lot=spec.fee_per_lot,
        )
    )
    if slip_ticks > 0:
        cerebro.broker.set_slippage_fixed(
            slip_ticks * spec.tick,
            slip_open=True,
            slip_limit=True,
            slip_match=True,
            slip_out=False,
        )
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="ta")

    log_buffer = io.StringIO()
    with contextlib.redirect_stdout(log_buffer):
        strat = cerebro.run()[0]

    return summarize(strat, frame, cash, fast, slow, allow_short), log_buffer.getvalue()


# ----------------------------------------------------------------------------- cli
def _parse_int_list(value: str) -> List[int]:
    items = [item.strip() for item in str(value).split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("需要至少一个整数")
    return [int(item) for item in items]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="期货双均线回测（研究脚本）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  --symbol RB.SHF --start 20100101 --end 20261109 --fast 10 --slow 30\n"
            "  --symbol RB.SHF --fast 5,10,20 --slow 20,30,60 --allow-short\n"
        ),
    )
    parser.add_argument("--symbol", help="期货 ts_code，例如 RB.SHF")
    parser.add_argument("--start", default="20100101", help="开始日期 YYYYMMDD")
    parser.add_argument("--end", default="20991231", help="结束日期 YYYYMMDD")
    parser.add_argument("--fast", default="10", help="快线周期，可逗号分隔多个")
    parser.add_argument("--slow", default="30", help="慢线周期，可逗号分隔多个")
    parser.add_argument("--cash", type=float, default=1_000_000.0, help="初始资金")
    parser.add_argument("--allow-short", action="store_true", help="允许反手做空")
    parser.add_argument(
        "--roll-mode",
        choices=("back_adjust", "none"),
        default="back_adjust",
        help="主力连续换月处理：后复权拼接或保留原始跳空",
    )
    parser.add_argument("--slip-ticks", type=float, default=1.0, help="单边滑点，单位 tick")
    parser.add_argument(
        "--risk-per-trade",
        type=float,
        default=0.01,
        help="单笔风险预算（权益比例）；乘数大的品种可调大到 0.03-0.05",
    )
    parser.add_argument("--atr-stop-mult", type=float, default=2.5, help="ATR 止损倍数")
    parser.add_argument("--max-hold-bars", type=int, default=0, help="最长持仓 bar 数，0=不限")
    parser.add_argument("--margin", type=float, default=None, help="覆盖保证金比例")
    parser.add_argument("--fee-rate", type=float, default=None, help="覆盖按金额手续费率")
    parser.add_argument("--fee-per-lot", type=float, default=None, help="覆盖每手固定手续费")
    parser.add_argument("--mult", type=float, default=None, help="自定义品种的合约乘数")
    parser.add_argument("--tick", type=float, default=None, help="自定义品种的最小变动价位")
    parser.add_argument("--mongo-uri", default=None, help="直连 Mongo 时使用")
    parser.add_argument("--data-db", default=None, help="直连 Mongo 时的数据库名")
    parser.add_argument("--json-out", default=None, help="结果写入 JSON 文件")
    parser.add_argument("--list-specs", action="store_true", help="列出内置合约规格后退出")
    parser.add_argument("--verbose", action="store_true", help="打印策略逐笔日志")
    return parser


def resolve_spec(args: argparse.Namespace) -> ContractSpec:
    symbol = args.symbol.strip().upper()
    base = CONTRACT_SPECS.get(symbol)
    if base is None:
        if args.mult is None or args.margin is None or args.tick is None:
            raise SystemExit(
                f"{symbol} 不在内置规格表；自定义品种需要 --mult --margin --tick。\n"
                "内置品种：" + ", ".join(sorted(CONTRACT_SPECS))
            )
        base = ContractSpec("自定义", args.mult, args.tick, args.margin)
    return ContractSpec(
        name=base.name,
        mult=args.mult if args.mult is not None else base.mult,
        tick=args.tick if args.tick is not None else base.tick,
        margin=args.margin if args.margin is not None else base.margin,
        fee_rate=args.fee_rate if args.fee_rate is not None else base.fee_rate,
        fee_per_lot=(
            args.fee_per_lot if args.fee_per_lot is not None else base.fee_per_lot
        ),
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_specs:
        print(f"{'ts_code':<10}{'name':<12}{'mult':>8}{'tick':>8}{'margin':>9}"
              f"{'fee_rate':>10}{'fee_lot':>9}")
        for code, spec in sorted(CONTRACT_SPECS.items()):
            print(f"{code:<10}{spec.name:<12}{spec.mult:>8g}{spec.tick:>8g}"
                  f"{spec.margin:>9.0%}{spec.fee_rate:>10g}{spec.fee_per_lot:>9g}")
        return 0

    if not args.symbol:
        parser.error("--symbol is required（或使用 --list-specs）")

    symbol = args.symbol.strip().upper()
    spec = resolve_spec(args)
    fasts = _parse_int_list(args.fast)
    slows = _parse_int_list(args.slow)
    combos = [(fast, slow) for fast in fasts for slow in slows if fast < slow]
    if not combos:
        raise SystemExit("没有有效的 fast < slow 组合")

    db = get_db(args)
    frame = load_futures_frame(db, symbol, args.start, args.end)

    rolls = count_rolls(frame)
    original = frame.copy()
    if args.roll_mode == "back_adjust":
        frame = back_adjust_rolls(frame)

    min_bars = max(slow for _, slow in combos) + 20
    if len(frame) < min_bars:
        raise SystemExit(
            f"数据只有 {len(frame)} 根，慢线最大 {max(slow for _, slow in combos)}，"
            f"至少需要 {min_bars} 根"
        )

    print(
        f"{symbol} {spec.name}  bars={len(frame)}  "
        f"{frame.index[0].date()} → {frame.index[-1].date()}  rolls={rolls}  "
        f"roll_mode={args.roll_mode}"
    )
    print(
        f"spec: mult={spec.mult:g} tick={spec.tick:g} margin={spec.margin:.0%} "
        f"fee_rate={spec.fee_rate:g} fee_per_lot={spec.fee_per_lot:g} "
        f"cash={args.cash:,.0f} slip={args.slip_ticks:g}tick "
        f"risk={args.risk_per_trade:.1%} "
        f"mode={'long-short' if args.allow_short else 'long-only'}"
    )
    buy_hold = float(original["close"].iloc[-1] / original["close"].iloc[0] - 1.0)
    print(f"raw main-continuous buy&hold: {buy_hold:.1%}（仅参考，含换月跳空）\n")

    header = (
        f"{'fast':>5}{'slow':>6}{'trades':>7}{'win%':>7}{'avg_win':>11}"
        f"{'avg_loss':>11}{'PF':>7}{'total%':>9}{'CAGR%':>8}{'MDD%':>8}{'expo%':>7}"
    )
    print(header)
    print("-" * len(header))

    runs: List[Dict[str, Any]] = []
    zero_trade = False
    for fast, slow in combos:
        result, log_text = run_one(
            frame=frame,
            spec=spec,
            fast=fast,
            slow=slow,
            cash=args.cash,
            allow_short=args.allow_short,
            slip_ticks=args.slip_ticks,
            risk_per_trade=args.risk_per_trade,
            atr_stop_mult=args.atr_stop_mult,
            max_hold_bars=args.max_hold_bars,
        )
        runs.append(result)
        if result["trades"] == 0:
            zero_trade = True
        pf = result["profit_factor"]
        pf_text = "inf" if not math.isfinite(pf) else f"{pf:.2f}"
        print(
            f"{fast:>5}{slow:>6}{result['trades']:>7}{result['win_rate'] * 100:>7.1f}"
            f"{result['avg_win']:>11.0f}{result['avg_loss']:>11.0f}{pf_text:>7}"
            f"{result['total_return'] * 100:>9.1f}{result['cagr'] * 100:>8.1f}"
            f"{result['max_drawdown'] * 100:>8.1f}{result['exposure'] * 100:>7.1f}"
        )
        if args.verbose:
            print(log_text)

    if not runs:
        raise SystemExit("没有产生任何结果")

    if zero_trade:
        print(
            "\n提示：有组合 0 笔成交。合约乘数较大时 1% 风险预算可能不足 1 手，"
            "试试 --risk-per-trade 0.03~0.05。"
        )

    if args.json_out:
        payload = {
            "symbol": symbol,
            "name": spec.name,
            "start": args.start,
            "end": args.end,
            "bars": len(frame),
            "rolls": rolls,
            "roll_mode": args.roll_mode,
            "spec": asdict(spec),
            "cash": args.cash,
            "allow_short": args.allow_short,
            "raw_buy_hold": buy_hold,
            "risk_per_trade": args.risk_per_trade,
            "atr_stop_mult": args.atr_stop_mult,
            "max_hold_bars": args.max_hold_bars,
            "slip_ticks": args.slip_ticks,
            "runs": [{k: _jsonable(v) for k, v in run.items()} for run in runs],
        }
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print(f"\nJSON -> {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
