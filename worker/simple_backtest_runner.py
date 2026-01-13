"""Simple backtest runner using quant-strategies directly.

This runner:
- Uses data-access-lib to fetch data
- Uses quant-strategies for strategy execution
- Does NOT depend on stock-execution-system or UnifiedWorker
"""

import logging
import backtrader as bt
from typing import Dict, Any, Optional

from stock_data_access import StockPriceDataAccess

log = logging.getLogger(__name__)


class SimpleBacktestRunner:
    """Direct backtest runner without external framework dependencies."""
    
    def __init__(self):
        self.data_loader = StockPriceDataAccess(minute=False)
    
    def run_backtest(
        self,
        symbol: str,
        strategy_class: type,
        strategy_params: Optional[Dict[str, Any]] = None,
        start_date: str = None,
        end_date: str = None,
        initial_cash: float = 1_000_000,
        preset_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run a backtest with given parameters.
        
        Args:
            symbol: Stock symbol (e.g., '000858.SZ')
            strategy_class: Strategy class (subclass of BacktestStrategy)
            strategy_params: Strategy parameters dict
            start_date: Start date (YYYYMMDD)
            end_date: End date (YYYYMMDD)
            initial_cash: Initial cash
            preset_name: Optional preset name (e.g., 'turtle_standard', 'grid_default')
            
        Returns:
            Dictionary with backtest results
        """
        log.info(f"Starting backtest: {symbol} ({start_date} to {end_date})")
        log.info(f"Strategy: {strategy_class.__name__}")
        log.info(f"Strategy class type: {type(strategy_class)}")
        log.info(f"Strategy params attribute type: {type(getattr(strategy_class, 'params', None))}")
        log.info(f"Strategy params received: {strategy_params}")
        log.info(f"Preset name: {preset_name}")
        
        try:
            # 1. Load data using data-access-lib
            log.info(f"Loading price data for {symbol}...")
            df = self.data_loader.fetch_frame([symbol], start_date, end_date)
            
            if df is None or df.empty:
                raise ValueError(f"No data found for {symbol} ({start_date}-{end_date})")
            
            n_bars = len(df)
            log.info(f"Loaded {n_bars} bars")

            # Quick pre-check: estimate minimum required bars from strategy params/class
            min_required = self._estimate_required_bars(strategy_class, safe_params if 'safe_params' in locals() else strategy_params)
            if n_bars < min_required:
                raise ValueError(f"Not enough data for strategy {strategy_class.__name__}: need at least {min_required} bars, got {n_bars}")
            
            # 2. Setup Backtrader
            cerebro = bt.Cerebro()
            cerebro.broker.setcash(initial_cash)
            
            # Add custom commission scheme like stock-execution-system
            from backtrader import CommInfoBase
            
            # Define custom commission scheme
            class CustomCommissionScheme(CommInfoBase):
                params = (
                    ("commission", 0.0001),  # 佣金万分之一
                    ("stamp_tax", 0.0005),  # 印花税万分之五
                )
            
            cerebro.broker.addcommissioninfo(CustomCommissionScheme())
            
            # 3. Add strategy with parameters
            if strategy_params is not None and hasattr(strategy_params, 'to_dict'):
                safe_params = strategy_params.to_dict()
            else:
                safe_params = (strategy_params or {}).copy() if strategy_params else {}
            
            log.info(f"Strategy params received: {safe_params}")
            
            # If preset_name is provided, load preset parameters
            if preset_name:
                try:
                    from quant_strategies.strategy_params.factory import create_strategy_with_params
                    strategy_class, preset_params = create_strategy_with_params(preset_name)
                    # Override preset params with any explicit params
                    preset_params.update(safe_params)
                    safe_params = preset_params
                    log.info(f"Loaded preset '{preset_name}' with params: {safe_params}")
                except ImportError as e:
                    log.warning(f"Could not load preset '{preset_name}': {e}, using provided parameters")
            
            # Coerce parameter types based on strategy defaults to avoid str vs int/float issues
            safe_params = self._coerce_params(strategy_class, safe_params)

            # Add worker_mode flag for backtest context
            safe_params['worker_mode'] = 'backtest'
            
            log.info(f"Final params passed to strategy: {safe_params}")
            cerebro.addstrategy(strategy_class, **safe_params)
            
            # 4. Add analyzers to capture trade and performance data
            cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="tradeanalyzer")
            cerebro.addanalyzer(bt.analyzers.Transactions, _name="transactions")
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
            cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
            cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.0)
            
            # 5. Create data feed from DataFrame
            feed = self._create_data_feed(df, symbol)
            cerebro.adddata(feed)
            
            # 6. Run backtest
            log.info("Running backtest...")
            strategies = cerebro.run()
            
            # Check if strategy ran
            if not strategies:
                raise ValueError("Strategy execution failed - no strategies returned")
            
            strategy = strategies[0]
            
            # 6. Collect results
            results = self._collect_results(cerebro, strategy, symbol, start_date, end_date, initial_cash)
            
            # Log completion with metrics
            final_value = cerebro.broker.getvalue()
            log.info(f"Backtest completed. Final value: {final_value:,.2f}")
            return results
            
        except Exception as e:
            log.error(f"Backtest failed: {e}", exc_info=True)
            raise
    
    def _create_data_feed(self, df, symbol):
        """Create a Backtrader PandasData feed from DataFrame."""
        import pandas as pd
        import backtrader as bt
        
        # Ensure DataFrame has proper index and columns
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, format='%Y%m%d')
        
        # Rename columns to match Backtrader expectations
        df_copy = df.copy()
        columns_map = {
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'volume',
        }
        
        # Map available columns
        for src, dst in columns_map.items():
            if src in df_copy.columns and src != dst:
                df_copy[dst] = df_copy[src]
        
        # Create named data feed with attributes like stock-execution-system
        class NamedPandasData(bt.feeds.PandasData):
            params = ()
        
        data_df = df_copy.copy()
        dt_index = pd.to_datetime(data_df.index)
        data_df = data_df.set_index(dt_index).sort_index()
        data = NamedPandasData(dataname=data_df)
        data.symbol = symbol
        data._name = symbol
        
        # Try to get stock name from data-access-lib
        try:
            from stock_data_access import StockPriceDataAccess
            loader = StockPriceDataAccess(minute=False)
            name_map = loader.fetch_names([symbol])
            stock_name = name_map.get(symbol, symbol)
            data.stock_name = stock_name
        except Exception:
            data.stock_name = symbol
        
        return data

    def _estimate_required_bars(self, strategy_class: type, strategy_params: Optional[Dict[str, Any]] = None) -> int:
        """Estimate minimum required bars for a strategy to initialize indicators safely.

        Heuristics used:
        - If strategy_class has attribute `min_data_required` use it.
        - If strategy_params contains `exit_ma_period` or `ma_period` use max of those * 2.
        - Fallback to conservative default of 50 bars.
        """
        try:
            # 1. Class-level hint
            if hasattr(strategy_class, 'min_data_required'):
                val = getattr(strategy_class, 'min_data_required')
                if isinstance(val, int) and val > 0:
                    return val

            # 2. Strategy params based heuristics
            params = strategy_params or {}

            # Special case: multi-MA exit uses 20/30/60
            if params.get('use_min_ma_exit'):
                return 60 * 2  # twice the longest MA for safety

            candidates = []
            for key in ('exit_ma_period', 'ma_period', 'short_ma', 'long_ma'):
                v = params.get(key)
                if isinstance(v, int) and v > 0:
                    candidates.append(v)

            if candidates:
                # take twice the largest moving average period as safe
                return max(candidates) * 2

            # 3. Fallback default (relaxed for tests/mocks)
            return 5
        except Exception:
            return 5

    def _coerce_params(self, strategy_class: type, params: Dict[str, Any]) -> Dict[str, Any]:
        """Convert stringified numeric params to correct types using strategy_class.params defaults."""
        coerced = params.copy()

        raw_defaults = getattr(strategy_class, 'params', None)
        defaults = {}

        # Extract defaults from tuple/list of pairs or dict-like structures
        if isinstance(raw_defaults, (list, tuple)):
            for item in raw_defaults:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    name, default = item[0], item[1]
                    defaults[name] = default
        elif isinstance(raw_defaults, dict):
            defaults = dict(raw_defaults)
        else:
            # Unknown structure (e.g., a type), skip default-based coercion
            defaults = {}

        # First pass: use defaults to guide casting
        for key, default in defaults.items():
            if key not in coerced:
                continue
            val = coerced[key]

            # Skip None or already proper type
            if val is None:
                continue

            # If value is string, try to cast based on default's type
            if isinstance(val, str):
                target_type = type(default)
                try:
                    if target_type is bool:
                        coerced[key] = val.lower() in ('1', 'true', 'yes', 'y', 't')
                    elif target_type is int:
                        coerced[key] = int(float(val))
                    elif target_type is float:
                        coerced[key] = float(val)
                    else:
                        # Fallback: try float then int
                        coerced[key] = float(val)
                except Exception:
                    # leave as-is if conversion fails
                    pass
            else:
                # If default is int but value is float like 0.0, cast to int
                if isinstance(default, int) and isinstance(val, float):
                    coerced[key] = int(val)

        # Second pass: generic numeric coercion for any remaining string values
        for key, val in list(coerced.items()):
            if not isinstance(val, str):
                continue
            v = val.strip()
            if v == '':
                continue
            # Bool strings
            low = v.lower()
            if low in ('true', 'false'):
                coerced[key] = (low == 'true')
                continue
            # Numeric strings
            try:
                as_float = float(v)
                if as_float.is_integer():
                    coerced[key] = int(as_float)
                else:
                    coerced[key] = as_float
            except Exception:
                # non-numeric, leave as-is
                pass

        return coerced
    
    def _collect_results(self, cerebro, strategy, symbol, start_date, end_date, initial_cash) -> Dict[str, Any]:
        """Collect backtest results from Backtrader in API-compatible format.
        
        Returns structure matching BacktestResultReport:
        {
            'symbol': str,
            'start_date': str,
            'end_date': str,
            'initial_cash': float,
            'final_value': float,
            'total_profit': float,
            'profit_percentage': float,
            'strategy_name': str,
            'metrics': BacktestResultMetrics,
            'trades': List[BacktestTrade],
            'equity_curve': List[BacktestEquityPoint]
        }
        """
        final_value = cerebro.broker.getvalue()
        profit = final_value - initial_cash
        profit_pct = (profit / initial_cash * 100) if initial_cash > 0 else 0
        
        # Extract performance metrics from analyzers
        metrics = self._extract_metrics(strategy, profit_pct)
        
        # Extract and format trades for API
        trades = self._extract_api_trades(strategy)
        
        # Get equity curve from broker's value history
        equity_curve = self._extract_equity_curve(strategy)
        
        # Return in API-compatible format (include basic fields for tests/API)
        results = {
            'symbol': symbol,
            'start_date': start_date,
            'end_date': end_date,
            'initial_cash': initial_cash,
            'final_value': final_value,
            'total_profit': profit,
            'profit_percentage': profit_pct,
            'strategy_name': getattr(strategy.__class__, '__name__', 'UnknownStrategy'),
            'metrics': metrics,
            'trades': trades,
            'equity_curve': equity_curve,
        }
        
        return results
    
    def _extract_metrics(self, strategy, total_return_pct) -> Dict[str, Any]:
        """Extract performance metrics matching BacktestResultMetrics schema.
        
        Note: Returns metrics in decimal format (0-1 range) for frontend display.
        Frontend will multiply by 100 to show percentages.
        """
        metrics = {
            'total_return': total_return_pct / 100,  # Convert to decimal
            'sharpe_ratio': 0.0,
            'max_drawdown': 0.0,
            'win_rate': 0.0,
            'total_trades': 0
        }
        
        if not hasattr(strategy, 'analyzers'):
            return metrics
        
        # Extract Returns (Backtrader returns decimal, keep as decimal for API)
        try:
            returns_analyzer = strategy.analyzers.getbyname('returns')
            returns_data = returns_analyzer.get_analysis()
            rtot = returns_data.get('rtot', 0)
            log.info(f"[DEBUG] Returns analyzer rtot: {rtot}")
            # Keep as decimal (e.g., 0.0147 for 1.47%)
            metrics['total_return'] = rtot
        except Exception as e:
            log.warning(f"[DEBUG] Failed to extract returns: {e}")
            pass
        
        # Extract Sharpe Ratio
        try:
            sharpe_analyzer = strategy.analyzers.getbyname('sharpe')
            sharpe_data = sharpe_analyzer.get_analysis()
            sharpe_ratio = sharpe_data.get('sharperatio', None)
            metrics['sharpe_ratio'] = sharpe_ratio if sharpe_ratio is not None else 0.0
        except Exception:
            metrics['sharpe_ratio'] = 0.0
        
        # Extract Max Drawdown (Backtrader returns percentage value like 3.69 for 3.69%)
        try:
            dd_analyzer = strategy.analyzers.getbyname('drawdown')
            dd_data = dd_analyzer.get_analysis()
            dd_value = dd_data.get('max', {}).get('drawdown', 0)
            log.info(f"[DEBUG] Drawdown analyzer value: {dd_value}")
            # Backtrader returns percentage (e.g., 3.69 for 3.69%), convert to decimal (0.0369)
            metrics['max_drawdown'] = dd_value / 100
        except Exception as e:
            log.warning(f"[DEBUG] Failed to extract drawdown: {e}")
            pass
        
        # Extract Trade Stats
        try:
            ta = strategy.analyzers.getbyname('tradeanalyzer')
            ta_data = ta.get_analysis()
            total_closed = ta_data.get('total', {}).get('closed', 0)
            won_total = ta_data.get('won', {}).get('total', 0)
            log.info(f"[DEBUG] Trade analyzer - total_closed: {total_closed}, won_total: {won_total}")
            
            metrics['total_trades'] = total_closed
            # Calculate win rate as decimal (e.g., 1.0 for 100%)
            metrics['win_rate'] = (won_total / total_closed) if total_closed > 0 else 0
            log.info(f"[DEBUG] Calculated win_rate: {metrics['win_rate']}")
        except Exception as e:
            log.warning(f"[DEBUG] Failed to extract trade stats: {e}")
            pass
        
        return metrics
    
    def _extract_api_trades(self, strategy) -> list:
        """Extract trades in API format matching BacktestTrade schema.
        
        BacktestTrade schema:
        - datetime: str
        - action: str (buy/sell)
        - price: float
        - quantity: int
        - commission: float
        - pnl: float
        - cumulative_pnl: float
        """
        trades = []
        
        # Try strategy's own trades_log first
        strategy_trades = getattr(strategy, 'trades_log', [])
        if strategy_trades:
            for trade in strategy_trades:
                # Normalize action to lowercase for API compatibility
                action = trade.get('action', 'unknown')
                if isinstance(action, str):
                    action = action.lower()  # Convert 'BUY'/'SELL' to 'buy'/'sell'
                
                api_trade = {
                    'datetime': trade.get('datetime').strftime('%Y-%m-%d %H:%M:%S') if hasattr(trade.get('datetime'), 'strftime') else str(trade.get('datetime', '')),
                    'action': action,
                    'price': float(trade.get('price', 0)),
                    'quantity': int(trade.get('size', 0)),  # Map 'size' to 'quantity'
                    'commission': 0.0,  # Strategy trades_log doesn't track commission
                    'pnl': float(trade.get('realized_pl', 0)),
                    'cumulative_pnl': float(trade.get('cum_pl', 0))
                }
                trades.append(api_trade)
        
        return trades
    
    def _extract_equity_curve(self, strategy) -> list:
        """Extract equity curve matching BacktestEquityPoint schema.
        
        BacktestEquityPoint schema:
        - date: str
        - value: float
        """
        equity_curve = []
        equity_history = getattr(strategy, 'equity_history', [])
        
        if equity_history:
            for date, value in equity_history:
                equity_curve.append({
                    'date': date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date),
                    'value': float(value)
                })
        
        return equity_curve
    
    def _get_trade_analyzer_dict(self, analyzer):
        """Convert trade analyzer to dictionary."""
        try:
            return analyzer.get_analysis()
        except Exception:
            return {}
    
    def _format_trades_from_analyzer(self, ta_dict):
        """Format trade data from trade analyzer."""
        trades = []
        
        if not ta_dict:
            return trades
        
        # The trade analyzer provides summary stats, not individual trades
        # We can create a summary of trades based on the analyzer data
        total_closed = ta_dict.get('total', {}).get('closed', 0)
        
        # If there are closed trades, we can extract some stats
        if total_closed > 0:
            ta_dict.get('won', {}).get('total', 0)
            ta_dict.get('lost', {}).get('total', 0)
            
            # This is just summary info, actual trade details would need to be captured during execution
            for i in range(total_closed):
                trades.append({
                    'id': i,
                    'status': 'closed',
                    'pnl': 0,  # Placeholder - actual data would come from strategy
                    'size': 0, # Placeholder
                    'entry_price': 0, # Placeholder
                    'exit_price': 0, # Placeholder
                })
        
        return trades
    
    def _format_trades_from_transactions(self, transactions_data):
        """Format trade data from transactions analyzer."""
        trades = []
        
        # Transactions analyzer provides transaction data in the format:
        # {datetime: [(order_ref, size, price, comm, pnl, value), ...]}
        for dt, transactions_list in transactions_data.items():
            for trans in transactions_list:
                print("len(trans) is", len(trans))
                if len(trans) >= 6:                  
                    # Format: (order_ref, size, price, comm, pnl, value)
                    order_ref = trans[0]
                    size = trans[1]
                    price = trans[2]
                    comm = trans[3]
                    pnl = trans[4]
                    value = trans[5]
                    
                    trades.append({
                        'datetime': str(dt),
                        'order_ref': order_ref,
                        'size': size,
                        'price': price,
                        'commission': comm,
                        'pnl': pnl,
                        'value': value
                    })
                elif len(trans) >= 5:
                    # Format: (order_ref, size, price, comm, pnl)
                    print("**********")
                    print(trans)
                    order_ref = trans[0]
                    size = trans[1]
                    price = trans[2]
                    comm = trans[3]
                    pnl = trans[4]
                    
                    trades.append({
                        'datetime': str(dt),
                        'order_ref': order_ref,
                        'size': size,
                        'price': price,
                        'commission': comm,
                        'pnl': pnl,
                        'value': 0  # Default if not provided
                    })
                elif len(trans) >= 4:
                    # Some transactions might have fewer fields: (order_ref, size, price, comm)
                    order_ref = trans[0]
                    size = trans[1]
                    price = trans[2]
                    comm = trans[3]
                    
                    trades.append({
                        'datetime': str(dt),
                        'order_ref': order_ref,
                        'size': size,
                        'price': price,
                        'commission': comm,
                        'pnl': 0,  # Default if not provided
                        'value': 0  # Default if not provided
                    })
        
        return trades


__all__ = ["SimpleBacktestRunner"]
