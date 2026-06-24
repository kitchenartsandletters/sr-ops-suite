#!/bin/sh

echo "Enqueuing NYFS daily sales report job..."
export PYTHONPATH=/app
python /app/cron/daily_sales_nyfs/enqueue_job.py
echo "Done."
