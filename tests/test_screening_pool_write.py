"""Unit tests for Plan B: all BUY signals written to pool with qualified flag.

No real Mongo is touched: the data loader, backtest runner, and collections
are all faked, so these run under `pytest -m "not integration"` in CI.
"""

from argparse import Namespace
from types import SimpleNamespace

import daily_full_market_screening as d

END_DATE = "20260612"


class FakeCollection:
    def __init__(self):
        self.upserts = []  # [(filter, $set-doc), ...]
        self.indexes = []

    def update_one(self, filt, update, upsert=False):
        assert upsert is True
        self.upserts.append((filt, update["$set"]))

    def create_index(self, keys, **kwargs):  # noqa: D102
        self.indexes.append(keys)


class FakeLoader:
    def __init__(self, symbols):
        self.symbols = symbols
        self.info_coll = SimpleNamespace(distinct=lambda field: sorted(self.symbols))

    def fetch_names(self, symbols):
        return {s: "name_" + s for s in symbols}


class FakeRunner:
    def __init__(self, results_by_symbol, errors_by_symbol=None):
        self.results = results_by_symbol
        self.errors = errors_by_symbol or {}

    def run_backtest(self, **kwargs):
        sym = kwargs["symbol"]
        if sym in self.errors:
            raise self.errors[sym]
        return self.results[sym]


def make_args(**overrides):
    base = dict(
        strategy_key="hidden_dragon",
        preset=None,
        days_back=180,
        initial_cash=1_000_000,
        limit_symbols=0,
        universe_index="",
        dry_run=False,
        sync_all=False,
        log_level="INFO",
        min_win_rate=0.50,
        min_trades=3,
        min_return=0.03,
    )
    base.update(overrides)
    return Namespace(**base)


def make_trade(dt, action, price=10.0, pnl=0.0):
    return {
        "datetime": dt,
        "action": action,
        "price": price,
        "quantity": 100,
        "pnl": pnl,
        "cumulative_pnl": pnl,
    }


def make_results(trades, metrics=None):
    return {
        "trades": trades,
        "metrics": metrics
        or {
            "win_rate": 0.6,
            "total_trades": 5,
            "total_return": 0.08,
            "sharpe_ratio": 1.2,
            "max_drawdown": 0.15,
        },
    }


def run_screening(monkeypatch, args, results, errors=None):
    pool_coll = FakeCollection()
    hist_coll = FakeCollection()
    db = {"strategy_stock_pool": pool_coll, "strategy_trade_history": hist_coll}

    monkeypatch.setattr(d, "_parse_args", lambda: args)
    monkeypatch.setattr(d, "_get_date_range", lambda days: ("20260101", END_DATE))
    monkeypatch.setattr(d, "_get_results_db", lambda: db)
    monkeypatch.setattr(d, "get_data_db", lambda *a, **k: None)
    monkeypatch.setattr(
        d,
        "StockPriceDataAccess",
        lambda *a, **k: FakeLoader(list(results.keys())),
    )
    monkeypatch.setattr(
        d, "SimpleBacktestRunner", lambda: FakeRunner(results, errors)
    )
    monkeypatch.setattr("quant_strategies.strategy_params.get_preset", lambda name: None)

    d.main()
    return pool_coll, hist_coll


# ---------------------------------------------------------------------------
# Write behavior
# ---------------------------------------------------------------------------


def test_qualified_buy_writes_pool_and_history(monkeypatch):
    results = {"000001.SZ": make_results([make_trade(f"{END_DATE} 10:00:00", "buy")])}
    pool, hist = run_screening(monkeypatch, make_args(), results)

    assert len(pool.upserts) == 1
    pool_filter, pool_doc = pool.upserts[0]
    assert pool_filter == {
        "date": END_DATE,
        "strategy": "hidden_dragon",
        "preset": "default",
        "symbol": "000001.SZ",
    }
    assert pool_doc["qualified"] is True
    assert pool_doc["action"] == "BUY"

    assert len(hist.upserts) == 1
    assert hist.upserts[0][1]["qualified"] is True


def test_insufficient_trades_buy_still_writes_pool_with_qualified_false(monkeypatch):
    metrics = {"win_rate": 1.0, "total_trades": 1, "total_return": 0.5}
    results = {"000002.SZ": make_results([make_trade(f"{END_DATE} 11:00:00", "buy")], metrics)}
    pool, hist = run_screening(monkeypatch, make_args(), results)

    assert len(pool.upserts) == 1
    assert pool.upserts[0][1]["qualified"] is False
    assert hist.upserts[0][1]["qualified"] is False


def test_low_win_rate_marks_not_qualified(monkeypatch):
    metrics = {"win_rate": 0.2, "total_trades": 5, "total_return": 0.5}
    results = {"000003.SZ": make_results([make_trade(f"{END_DATE} 11:00:00", "buy")], metrics)}
    pool, _ = run_screening(monkeypatch, make_args(), results)

    assert pool.upserts[0][1]["qualified"] is False


def test_low_return_marks_not_qualified(monkeypatch):
    metrics = {"win_rate": 0.8, "total_trades": 5, "total_return": 0.01}
    results = {"000004.SZ": make_results([make_trade(f"{END_DATE} 11:00:00", "buy")], metrics)}
    pool, _ = run_screening(monkeypatch, make_args(), results)

    assert pool.upserts[0][1]["qualified"] is False


def test_sell_only_writes_history_not_pool(monkeypatch):
    results = {"000005.SZ": make_results([make_trade("20260601 11:00:00", "sell")])}
    pool, hist = run_screening(monkeypatch, make_args(), results)

    assert pool.upserts == []
    assert len(hist.upserts) == 1
    assert hist.upserts[0][1]["action"] == "SELL"


def test_no_trades_writes_nothing(monkeypatch):
    results = {"000006.SZ": make_results([])}
    pool, hist = run_screening(monkeypatch, make_args(), results)

    assert pool.upserts == []
    assert hist.upserts == []


def test_dry_run_writes_nothing(monkeypatch):
    results = {"000007.SZ": make_results([make_trade(f"{END_DATE} 10:00:00", "buy")])}
    pool, hist = run_screening(monkeypatch, make_args(dry_run=True), results)

    assert pool.upserts == []
    assert hist.upserts == []


# ---------------------------------------------------------------------------
# Counters and summary log
# ---------------------------------------------------------------------------


def test_candidates_count_only_end_date_buys(monkeypatch, caplog):
    qualified = {
        "000010.SZ": make_results([make_trade(f"{END_DATE} 10:00:00", "buy")])
    }
    not_qualified = {
        "000011.SZ": make_results(
            [make_trade(f"{END_DATE} 10:00:00", "buy")],
            {"win_rate": 0.1, "total_trades": 1, "total_return": 0.5},
        )
    }
    historical_buy = {
        "000012.SZ": make_results([make_trade("20260301 10:00:00", "buy")])
    }
    results = {**qualified, **not_qualified, **historical_buy}
    pool, _ = run_screening(monkeypatch, make_args(), results)

    # All three BUYs written (historical included), but only two are end-date.
    assert len(pool.upserts) == 3

    with caplog.at_level("INFO", logger="daily_full_market_screening"):
        run_screening(monkeypatch, make_args(), results)
    summary = [r.message for r in caplog.records if r.message.startswith("Screening done")]
    assert summary, "summary log missing"
    assert "candidates=2" in summary[-1]
    assert "qualified=1" in summary[-1]
    assert "not_qualified=1" in summary[-1]


def test_upsert_keys_are_stable_across_runs(monkeypatch):
    results = {"000013.SZ": make_results([make_trade(f"{END_DATE} 10:00:00", "buy")])}
    pool1, hist1 = run_screening(monkeypatch, make_args(), results)
    pool2, hist2 = run_screening(monkeypatch, make_args(), results)

    assert [f for f, _ in pool1.upserts] == [f for f, _ in pool2.upserts]
    assert [f for f, _ in hist1.upserts] == [f for f, _ in hist2.upserts]


def test_not_qualified_log_lists_reasons(monkeypatch, caplog):
    results = {
        "000014.SZ": make_results(
            [make_trade(f"{END_DATE} 10:00:00", "buy")],
            {"win_rate": 0.1, "total_trades": 1, "total_return": 0.5},
        )
    }
    with caplog.at_level("INFO", logger="daily_full_market_screening"):
        run_screening(monkeypatch, make_args(), results)
    not_qualified = [r.message for r in caplog.records if r.message.startswith("[NOT_QUALIFIED]")]
    assert not_qualified
    assert "trades=1<3" in not_qualified[0]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_no_data_valueerror_counts_skipped(monkeypatch, caplog):
    results = {"000015.SZ": make_results([])}
    errors = {"000015.SZ": ValueError("No data found")}
    pool, hist = run_screening(monkeypatch, make_args(), results, errors)

    assert pool.upserts == [] and hist.upserts == []
    with caplog.at_level("INFO", logger="daily_full_market_screening"):
        run_screening(monkeypatch, make_args(), results, errors)
    summary = [r.message for r in caplog.records if r.message.startswith("Screening done")]
    assert "skipped_no_data=1" in summary[-1]
    assert "errors=0" in summary[-1]


def test_unexpected_exception_counts_error(monkeypatch, caplog):
    results = {"000016.SZ": make_results([])}
    errors = {"000016.SZ": RuntimeError("boom")}
    pool, hist = run_screening(monkeypatch, make_args(), results, errors)

    assert pool.upserts == [] and hist.upserts == []
    with caplog.at_level("INFO", logger="daily_full_market_screening"):
        run_screening(monkeypatch, make_args(), results, errors)
    summary = [r.message for r in caplog.records if r.message.startswith("Screening done")]
    assert "errors=1" in summary[-1]


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------


def test_ensure_indexes_created(monkeypatch):
    results = {"000017.SZ": make_results([make_trade(f"{END_DATE} 10:00:00", "buy")])}
    pool, hist = run_screening(monkeypatch, make_args(), results)

    assert pool.indexes == [[("date", 1), ("strategy", 1), ("preset", 1)], [("preset", 1), ("date", -1)]]
    assert hist.indexes == [[("symbol", 1), ("strategy", 1), ("preset", 1), ("datetime", 1)]]


# ---------------------------------------------------------------------------
# Arg defaults must match production thresholds
# ---------------------------------------------------------------------------


def test_arg_defaults_match_production_thresholds(monkeypatch):
    for name in ("SCREENING_MIN_WIN_RATE", "SCREENING_MIN_TRADES", "SCREENING_MIN_RETURN"):
        monkeypatch.delenv(name, raising=False)

    # d._parse_args is monkeypatched away in run_screening; call the real
    # parser here by invoking the module function directly.
    monkeypatch.setattr("sys.argv", ["prog"])
    args = d._parse_args()
    assert args.min_win_rate == 0.50
    assert args.min_trades == 3
    assert args.min_return == 0.03
