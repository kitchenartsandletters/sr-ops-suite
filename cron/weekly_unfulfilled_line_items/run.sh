#!/usr/bin/env bash

set -e

echo "🚀 Weekly Unfulfilled Line Items Cron Worker starting..."

# Default behavior:
# - Use full sweep (capped safely inside script)
# - SLA threshold 30 days (default)
# - Output to /app/output

python scripts/weekly_unfulfilled_line_items_report.py \
    --full-sweep \
    --sla-days 30

echo "✅ Weekly Unfulfilled Line Items Cron Worker finished."