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

BACKTEST_ROLE="${BACKTEST_ROLE:-worker}"
if [ "${ENABLE_SCREENING:-false}" = "true" ] && [ "$BACKTEST_ROLE" = "worker" ]; then
    echo "WARN: ENABLE_SCREENING=true is deprecated; run a separate screening container (BACKTEST_ROLE=screening)."
fi

WORKER_ID="${BACKTEST_WORKER_ID:-${WORKER_ID:-backtest_worker_$(hostname)}}"
POLL_INTERVAL_VALUE="${BACKTEST_POLL_INTERVAL:-${POLL_INTERVAL:-}}"
ARGS=""
if [ -n "$MONGO_URI" ]; then ARGS="$ARGS --mongo-uri $MONGO_URI"; fi
if [ -n "$BACKTEST_DB_NAME" ]; then ARGS="$ARGS --db-name $BACKTEST_DB_NAME"; fi
if [ -n "$WORKER_ID" ]; then ARGS="$ARGS --worker-id $WORKER_ID"; fi
if [ -n "$POLL_INTERVAL_VALUE" ]; then ARGS="$ARGS --poll-interval $POLL_INTERVAL_VALUE"; fi
if [ -n "$LOG_LEVEL" ]; then ARGS="$ARGS --log-level $LOG_LEVEL"; fi

case "$BACKTEST_ROLE" in
  screening)
    echo "Starting screening scheduler (BACKTEST_ROLE=screening, mode=${SCREENING_MODE:-conservative})..."
    exec python /app/screening_scheduler.py
    ;;
  worker)
    echo "Starting backtest queue worker (BACKTEST_ROLE=worker, worker_id=$WORKER_ID)..."
    exec python backtest_worker.py $ARGS
    ;;
  *)
    echo "ERROR: unknown BACKTEST_ROLE=$BACKTEST_ROLE (expected worker or screening)" >&2
    exit 1
    ;;
esac
