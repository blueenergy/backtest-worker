# Backtest Worker Testing Suite

This directory contains comprehensive tests for the backtest-worker system.

## Test Files

### `test_backtest_worker.py`
Core unit tests for individual components:
- SimpleBacktestRunner functionality
- Configuration loading
- API interaction methods
- Result formatting
- Error handling
- Strategy execution

### `test_integration.py`
Integration tests for complete workflows:
- End-to-end backtest flow
- Real strategy integration (Turtle, Grid)
- Authentication headers
- Result formatting edge cases
- Task processing workflows

### `test_backtest_locally.py`
Local functionality tests:
- Strategy imports and availability
- Runner initialization
- Backtest execution with real strategies
- Data access testing

## Running Tests

### All Tests
```bash
./test.sh
```

### Individual Test Files
```bash
# Unit tests
python test_backtest_worker.py

# Integration tests  
python test_integration.py

# Local functionality tests
python test_backtest_locally.py
```

### Using pytest (if available)
```bash
python -m pytest test_backtest_worker.py -v
```

## Test Coverage

The test suite covers:

### Core Components
- [x] SimpleBacktestRunner initialization and methods
- [x] Data feed creation
- [x] Result collection and formatting
- [x] Configuration loading

### API Integration
- [x] Task polling (success and failure cases)
- [x] Task claiming
- [x] Result reporting (success/failure)
- [x] Authentication headers
- [x] Network error handling

### Strategy Execution
- [x] Turtle strategy integration
- [x] Grid strategy integration
- [x] Unknown strategy handling
- [x] Parameter validation

### Edge Cases
- [x] Empty data handling
- [x] Single data point scenarios
- [x] Zero trade scenarios
- [x] Network timeout/error scenarios
- [x] Invalid configuration handling

## Architecture Patterns

Tests follow the patterns from stock-execution-system:
- Mock external dependencies (MongoDB, API calls)
- Test both success and failure paths
- Verify data structure integrity
- Test error handling and recovery
- Validate authentication flows

## Dependencies

Tests require:
- Python 3.8+
- pytest (optional, for pytest runner)
- All dependencies from requirements.txt
- Access to quant-strategies package