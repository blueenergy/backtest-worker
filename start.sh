#!/bin/bash
# Backtest Worker Startup Script

CONFIG_FILE=${1:-"config.json"}

# Get the project root directory
PROJECT_ROOT="$(realpath "$(dirname "$0")")"
echo "Project root: $PROJECT_ROOT"
# Change to worker directory
cd "$PROJECT_ROOT/worker"

# Convert config path to absolute path from project root
if [[ "$CONFIG_FILE" != /* ]]; then
    # Relative path - resolve from project root
    CONFIG_FILE="$PROJECT_ROOT/$CONFIG_FILE"
fi
echo "Config file: $CONFIG_FILE"
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
