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
        
        try:
            # 1. Load data using data-access-lib
            log.info(f"Loading price data for {symbol}...")
            df = self.data_loader.fetch_frame([symbol], start_date, end_date)
            
            if df is None or df.empty:
                raise ValueError(f"No data found for {symbol} ({start_date}-{end_date})")
            
            log.info(f"Loaded {len(df)} bars")
            
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
            
            # 3. Add strategy
            safe_params = strategy_params or {}
            
            # If preset_name is provided, use preset parameters
            if preset_name:
                try:
                    from quant_strategies.strategy_params.factory import create_strategy_with_params
                    strategy_class, preset_params = create_strategy_with_params(preset_name)
                    # Override preset params with any explicit params
                    preset_params.update(safe_params)
                    safe_params = preset_params
                except ImportError:
                    print(f"[WARNING] Could not load preset '{preset_name}', using default parameters")
            
            safe_params['worker_mode'] = 'backtest'
            cerebro.addstrategy(strategy_class, **safe_params)
            
            # 4. Add analyzers to capture trade and performance data
            cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="tradeanalyzer")
            cerebro.addanalyzer(bt.analyzers.Transactions, _name="transactions")
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
            
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
            
            log.info(f"Backtest completed. Final value: {results['final_value']:,.2f}")
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
    
    def _collect_results(self, cerebro, strategy, symbol, start_date, end_date, initial_cash) -> Dict[str, Any]:
        """Collect backtest results from Backtrader."""
        final_value = cerebro.broker.getvalue()
        profit = final_value - initial_cash
        profit_pct = (profit / initial_cash * 100) if initial_cash > 0 else 0
        
        # Extract trade data prioritizing strategy's own logging
        # (which only records actual executed trades, not all broker transactions)
        trades = []
        
        # First, try to get trades from strategy's own logging (only actual trades)
        strategy_trades = getattr(strategy, 'trades_log', [])
        if strategy_trades:
            trades = strategy_trades
        else:
            # Fallback to analyzers only if strategy logging is not available
            if hasattr(strategy, 'analyzers'):
                transactions = strategy.analyzers.getbyname('transactions')
                ta = strategy.analyzers.getbyname('tradeanalyzer')
                
                # Only use Transactions analyzer if we don't have strategy trades
                # Note: Transactions analyzer includes ALL broker transactions, not just trades
                if transactions:
                    transactions_data = transactions.get_analysis()
                    if transactions_data:
                        trades = self._format_trades_from_transactions(transactions_data)
                # Fallback to trade analyzer if no transactions
                elif ta:
                    ta_dict = self._get_trade_analyzer_dict(ta)
                    trades = self._format_trades_from_analyzer(ta_dict)
        
        # Get equity curve from broker's value history
        equity_history = getattr(strategy, 'equity_history', [])
        equity_curve = []
        if equity_history:
            for date, value in equity_history:
                equity_curve.append({
                    'date': date.strftime('%Y%m%d') if hasattr(date, 'strftime') else str(date),
                    'value': float(value)
                })
        
        results = {
            'symbol': symbol,
            'start_date': start_date,
            'end_date': end_date,
            'initial_cash': float(initial_cash),
            'final_value': float(final_value),
            'total_profit': float(profit),
            'profit_percentage': float(profit_pct),
            'trades': trades,
            'equity_curve': equity_curve,
            'strategy_name': strategy.__class__.__name__,
        }
        
        return results
    
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
