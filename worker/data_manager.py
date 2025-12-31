"""
Data Manager - Worker 内部的数据获取策略

Worker 自己决定从哪里获取数据，对外部透明
"""

import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
import json

from stock_data_access import StockPriceDataAccess

log = logging.getLogger(__name__)


class DataSource:
    """数据源基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        return self.config.get("enabled", False)
    
    def get_bars(self, symbol: str, start_date: str, end_date: str) -> List[Dict]:
        """获取K线数据"""
        raise NotImplementedError


class StockAccessSource(DataSource):
    """基于 data-access-lib 的股票数据源
    
    通过 StockPriceDataAccess 统一访问价格数据，避免在 worker 内部直接操作 MongoDB。
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        minute = bool(config.get("minute", False))
        self.loader = StockPriceDataAccess(minute=minute)
    
    def is_available(self) -> bool:
        # 只要 loader 创建成功就认为可用，具体异常在 get_bars 里处理
        return True
    
    def get_bars(self, symbol: str, start_date: str, end_date: str) -> List[Dict]:
        """使用 StockPriceDataAccess 获取指定区间的 OHLCV 数据"""
        try:
            df = self.loader.fetch_frame([symbol], start_date, end_date)
        except Exception as e:
            log.warning(f"StockAccessSource.fetch_frame failed for {symbol}: {e}")
            return []
        
        if df is None or getattr(df, "empty", True):
            return []
        
        # 确保按时间排序
        try:
            df = df.sort_index()
        except Exception:
            pass
        
        bars: List[Dict[str, Any]] = []
        for ts, row in df.iterrows():
            try:
                bars.append({
                    "date": ts.strftime("%Y%m%d"),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0.0)),
                })
            except Exception:
                # 某行数据不完整时跳过
                continue
        
        return bars


class DataManager:
    """数据管理器 - 自动选择最佳数据源"""
    
    def __init__(self, config_path: str = 'config.json'):
        self.config = self._load_config(config_path)
        self.cache_dir = Path(self.config.get('data_strategy', {}).get('cache_dir', './cache'))
        self.cache_dir.mkdir(exist_ok=True, parents=True)
        
        # 延迟加载数据源（按需导入）
        self.sources = {}
        self._init_sources()
    
    def _load_config(self, config_path: str) -> Dict:
        """加载配置文件"""
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            log.warning(f"Config file {config_path} not found, using defaults")
            return self._default_config()
    
    def _default_config(self) -> Dict:
        """默认配置"""
        return {
            "data_strategy": {
                "use_cache": True,
                "cache_dir": "./cache",
                "source_priority": ["cache", "stock_access"],
            },
            "data_sources": {
                "stock_access": {
                    "enabled": True,
                    "minute": False,
                },
            },
        }
    
    def _init_sources(self):
        """初始化数据源（延迟加载）"""
        data_sources_config = self.config.get("data_sources", {})
        
        # 基于 data-access-lib 的股票价格数据源
        stock_cfg = data_sources_config.get("stock_access", {})
        if stock_cfg.get("enabled"):
            try:
                self.sources["stock_access"] = StockAccessSource(stock_cfg)
                log.info("StockAccess data source initialized (via stock-data-access lib)")
            except Exception as e:
                log.warning(f"Failed to initialize StockAccessSource: {e}")
    
    def get_bars(self, symbol: str, start_date: str, end_date: str) -> List[Dict]:
        """
        获取K线数据 - 自动选择最佳数据源
        
        Args:
            symbol: 股票代码（如 000858.SZ）
            start_date: 开始日期（YYYYMMDD）
            end_date: 结束日期（YYYYMMDD）
            
        Returns:
            K线数据列表
        """
        # 1. 尝试缓存
        if self.config.get('data_strategy', {}).get('use_cache', True):
            cached_data = self._try_cache(symbol, start_date, end_date)
            if cached_data:
                log.info(f"Data loaded from cache: {symbol}")
                return cached_data
        
        # 2. 按优先级尝试各数据源
        source_priority = self.config.get("data_strategy", {}).get(
            "source_priority",
            ["stock_access"],
        )
        
        for source_name in source_priority:
            if source_name == 'cache':
                continue  # Already tried
            
            source = self.sources.get(source_name)
            if not source:
                log.debug(f"Data source {source_name} not configured")
                continue
            
            if not source.is_available():
                log.debug(f"Data source {source_name} not available")
                continue
            
            try:
                log.info(f"Trying data source: {source_name}")
                data = source.get_bars(symbol, start_date, end_date)
                
                if data:
                    log.info(f"Data loaded from {source_name}: {len(data)} bars")
                    # 缓存数据
                    self._cache_data(symbol, start_date, end_date, data)
                    return data
                else:
                    log.warning(f"No data returned from {source_name}")
                    
            except Exception as e:
                log.warning(f"Failed to get data from {source_name}: {e}")
                continue
        
        raise ValueError(f"No data source available for {symbol} ({start_date} - {end_date})")
    
    def _try_cache(self, symbol: str, start_date: str, end_date: str) -> Optional[List[Dict]]:
        """尝试从缓存读取数据"""
        cache_file = self._get_cache_path(symbol, start_date, end_date)
        
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                log.warning(f"Failed to read cache: {e}")
        
        return None
    
    def _cache_data(self, symbol: str, start_date: str, end_date: str, data: List[Dict]):
        """缓存数据到本地"""
        try:
            cache_file = self._get_cache_path(symbol, start_date, end_date)
            cache_file.parent.mkdir(exist_ok=True, parents=True)
            
            with open(cache_file, 'w') as f:
                json.dump(data, f)
            
            log.info(f"Data cached to {cache_file}")
        except Exception as e:
            log.warning(f"Failed to cache data: {e}")
    
    def _get_cache_path(self, symbol: str, start_date: str, end_date: str) -> Path:
        """生成缓存文件路径"""
        return self.cache_dir / f"{symbol}_{start_date}_{end_date}.json"
