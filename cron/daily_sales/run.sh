#!/bin/sh

echo "Enqueuing daily sales report job..."
export PYTHONPATH=/app
python /app/cron/daily_sales/enqueue_job.py
echo "Done."