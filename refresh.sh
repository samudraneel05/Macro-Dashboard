#!/usr/bin/env bash
# =============================================================================
# refresh.sh — one-command data refresh (macOS / Linux)
# =============================================================================
# Re-runs the full ETL pipeline to refresh output/dashboard.db and the CSVs.
# After this completes, open Power BI Desktop and click "Refresh" — the
# Python script source will read the updated dashboard.db.
#
# Usage:
#   ./refresh.sh                  # full refresh using today as end date
#   ./refresh.sh --start-date 2020-01-01
#   ./refresh.sh --start-date 2020-01-01 --end-date 2025-12-31
#
# Requirements:
#   - Python 3.9+ with the project's .venv (auto-activated below) or a
#     virtualenv where pandas/numpy/requests/yfinance/matplotlib are
#     installed.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate the project venv if it exists, otherwise fall back to PATH python.
if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

echo "================================================================"
echo "  Refreshing Global Macro Dashboard data"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================================"

python main.py "$@"

echo
echo "================================================================"
echo "  Refresh complete."
echo "  Cached data: $SCRIPT_DIR/output/dashboard.db"
echo
echo "  Next step:"
echo "    1. Open your .pbix in Power BI Desktop (Windows)."
echo "    2. Click Home > Refresh (uses the cached dashboard.db)."
echo
echo "  For a live pull inside Power BI without running this script,"
echo "  set the Windows env var POWERBI_FRESH=1 then click Refresh."
echo "================================================================"
