import os
import sys

import pytest

# Ensure project root is on sys.path for absolute imports in tests
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def stub_symbol_name_lookup(request, monkeypatch):
    """Keep _create_data_feed from reaching MongoDB for a display name.

    The lookup is cosmetic and its failure is swallowed, so without a reachable
    MongoDB every data feed silently burns a 30s server-selection timeout.
    """
    if 'integration' in request.keywords:
        return

    from worker.simple_backtest_runner import SimpleBacktestRunner

    monkeypatch.setattr(
        SimpleBacktestRunner,
        '_fetch_symbol_name',
        lambda self, symbol, asset_type='stock': symbol,
    )
