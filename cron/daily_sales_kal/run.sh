#!/bin/sh

echo "Enqueuing KAL daily sales report job..."
export PYTHONPATH=/app
python /app/cron/daily_sales_kal/enqueue_job.py
echo "Done."
