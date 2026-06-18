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
WORKER_ID="${BACKTEST_WORKER_ID:-${WORKER_ID:-backtest_worker_$(hostname)}}"
POLL_INTERVAL_VALUE="${BACKTEST_POLL_INTERVAL:-${POLL_INTERVAL:-}}"
ARGS=""
if [ -n "$MONGO_URI" ]; then ARGS="$ARGS --mongo-uri $MONGO_URI"; fi
if [ -n "$BACKTEST_DB_NAME" ]; then ARGS="$ARGS --db-name $BACKTEST_DB_NAME"; fi
if [ -n "$WORKER_ID" ]; then ARGS="$ARGS --worker-id $WORKER_ID"; fi
if [ -n "$POLL_INTERVAL_VALUE" ]; then ARGS="$ARGS --poll-interval $POLL_INTERVAL_VALUE"; fi
if [ -n "$LOG_LEVEL" ]; then ARGS="$ARGS --log-level $LOG_LEVEL"; fi

echo "Starting backtest worker..."

# Optionally start the screening scheduler in the background
if [ "${ENABLE_SCREENING:-true}" = "true" ]; then
    echo "Starting screening scheduler (mode=${SCREENING_MODE:-conservative})..."
    python /app/screening_scheduler.py &
    SCREENING_PID=$!
    echo "Screening scheduler PID: $SCREENING_PID"
fi

exec python backtest_worker.py $ARGS

