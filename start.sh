#!/bin/bash
# Backtest Worker Startup Script

CONFIG_FILE=${1:-"config.json"}

cd "$(dirname "$0")/worker"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Config file not found: $CONFIG_FILE"
    echo ""
    echo "Please create config file:"
    echo "  cp config.example.json config.json"
    echo "  vim config.json  # Fill in your api_token"
    exit 1
fi

echo "========================================="
echo "Starting Backtest Worker"
echo "========================================="
echo "Config: $CONFIG_FILE"
echo "========================================="

python backtest_worker.py --config "$CONFIG_FILE"
