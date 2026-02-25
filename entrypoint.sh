#!/bin/bash
set -e

# Install local editable packages if mounted
if [ -d "/deps/data-access-lib" ]; then
    echo "Installing data-access-lib..."
    pip install --no-cache-dir -q -e /deps/data-access-lib
fi

if [ -d "/deps/quant-strategies" ]; then
    echo "Installing quant-strategies..."
    pip install --no-cache-dir -q -e /deps/quant-strategies
fi

# Build args from environment variables
WORKER_ID="${WORKER_ID:-backtest_worker_$(hostname)}"
ARGS=""
if [ -n "$API_BASE_URL" ]; then ARGS="$ARGS --api-base $API_BASE_URL"; fi
if [ -n "$WORKER_ID" ];    then ARGS="$ARGS --worker-id $WORKER_ID"; fi
if [ -n "$API_TOKEN" ];    then ARGS="$ARGS --token $API_TOKEN"; fi
if [ -n "$POLL_INTERVAL" ]; then ARGS="$ARGS --poll-interval $POLL_INTERVAL"; fi
if [ -n "$LOG_LEVEL" ];    then ARGS="$ARGS --log-level $LOG_LEVEL"; fi

echo "Starting backtest worker..."
exec python backtest_worker.py $ARGS
