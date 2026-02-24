#!/bin/sh

echo "Starting Report Job Worker..."

cd /app

# Optional: small startup delay if needed for DB readiness
# sleep 3

python services/report_job_worker.py