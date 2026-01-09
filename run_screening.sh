#!/usr/bin/env bash
# Integrated Stock Screening Script
#
# Usage:
#   ./run_screening.sh [mode] [limit]
#
# Modes:
#   conservative : Run high win-rate focus presets (default)
#   standard     : Run balanced approach presets
#   aggressive   : Run more opportunities presets
#   all          : Run all of the above
#
# Limit:
#   Optional. Number of symbols to process (for fast testing).
#
# Examples:
#   ./run_screening.sh conservative
#   ./run_screening.sh conservative 50
#   ./run_screening.sh all 10

set -e

cd "$(dirname "$0")"

MODE=${1:-"conservative"}
LIMIT=${2:-0}

echo "============================================="
echo "Stock Screening System"
echo "Mode:  ${MODE}"
if [ "${LIMIT}" -gt 0 ]; then
    echo "Limit: ${LIMIT} symbols (TEST MODE)"
fi
echo "============================================="
echo ""

# Configuration
MIN_WIN_RATE=0.50
MIN_TRADES=3
MIN_RETURN=0.03

# Smart backtest window:
# - First run or weekend: Use 360 days for comprehensive analysis
# - Daily incremental: Use 60 days for quick updates
DAY_OF_WEEK=$(date +%u)  # 1=Monday, 7=Sunday
if [ "$DAY_OF_WEEK" -ge 6 ]; then
    DAYS_BACK=360  # Weekend: Full scan
    echo "📅 Weekend mode: Using 360-day backtest window"
else
    DAYS_BACK=60   # Weekday: Quick update
    echo "⚡ Daily mode: Using 60-day backtest window"
fi

# Allow manual override via environment variable
if [ -n "$SCREENING_DAYS_BACK" ]; then
    DAYS_BACK=$SCREENING_DAYS_BACK
    echo "🔧 Manual override: Using ${DAYS_BACK}-day window"
fi

run_task() {
    local strat=$1
    # Use standard names for presets: turtle_conservative, yang_conservative, dragon_conservative
    # Wait, checking actual preset names in code...
    # Turtle: turtle_conservative, turtle_standard, turtle_aggressive
    # Single Yang: yang_conservative, yang_default, yang_aggressive
    # Hidden Dragon: dragon_conservative, dragon_default, dragon_aggressive
    
    local preset=$2
    local label=$3
    
    echo "--- Screening: ${strat} (${label}) ---"
    python daily_full_market_screening.py \
        --strategy-key ${strat} \
        --preset ${preset} \
        --days-back ${DAYS_BACK} \
        --initial-cash 1000000 \
        --min-win-rate ${MIN_WIN_RATE} \
        --min-trades ${MIN_TRADES} \
        --min-return ${MIN_RETURN} \
        --limit-symbols ${LIMIT} \
        --log-level INFO
    echo ""
}

run_conservative() {
    run_task "turtle" "turtle_conservative" "Conservative"
    run_task "single_yang" "yang_conservative" "Conservative"
    run_task "hidden_dragon" "dragon_conservative" "Conservative"
}

run_standard() {
    run_task "turtle" "turtle_standard" "Standard"
    run_task "single_yang" "yang_default" "Standard"
    run_task "hidden_dragon" "dragon_default" "Standard"
}

run_aggressive() {
    run_task "turtle" "turtle_aggressive" "Aggressive"
    run_task "single_yang" "yang_aggressive" "Aggressive"
    run_task "hidden_dragon" "dragon_aggressive" "Aggressive"
}

case ${MODE} in
    "conservative")
        run_conservative
        ;;
    "standard")
        run_standard
        ;;
    "aggressive")
        run_aggressive
        ;;
    "all")
        run_conservative
        run_standard
        run_aggressive
        ;;
    *)
        echo "Error: Unknown mode '${MODE}'"
        echo "Available modes: conservative, standard, aggressive, all"
        exit 1
        ;;
esac

echo "=============================================="
echo "✅ Screening Complete (Mode: ${MODE})"
echo "=============================================="
echo ""
echo "Results saved to MongoDB with preset tags."
echo "Check frontend 'Strategy Stock Pool' tab to compare results."
