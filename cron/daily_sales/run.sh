#!/bin/sh

echo "Enqueuing daily sales report job..."
python /app/cron/daily_sales/enqueue_job.py
echo "Done."