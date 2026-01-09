#!/bin/bash
# Test backtest worker functionality

cd "$(dirname "$0")"

CONFIG_FILE=${1:-"config.json"}

if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Config file not found: $CONFIG_FILE"
    echo "Using config.example.json for testing..."
    CONFIG_FILE="config.example.json"
fi

echo "========================================="
echo "Testing Backtest Worker Configuration"
echo "========================================="
echo "Config: $CONFIG_FILE"
echo ""

# Run configuration test
python worker/backtest_worker.py --config "$CONFIG_FILE" --test

echo ""
echo "========================================="
echo "Running Unit Tests"
echo "========================================="

# Run unit tests
python -m pytest test_backtest_worker.py -v

echo ""
echo "========================================="
echo "Running Local Backtest Tests"
echo "========================================="

# Run local backtest tests
python test_backtest_locally.py