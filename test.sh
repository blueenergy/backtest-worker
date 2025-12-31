#!/bin/bash
# Test backtest worker connectivity

cd "$(dirname "$0")/worker"

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

python backtest_worker.py --config "$CONFIG_FILE" --test
