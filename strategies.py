"""Compatibility shim for tests and scripts expecting `strategies` at project root.

Re-exports strategy classes and STRATEGY_MAP from quant_strategies.strategies.
"""
from quant_strategies.strategies import *  # noqa: F401,F403
