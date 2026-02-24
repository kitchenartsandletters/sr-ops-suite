#!/bin/sh

echo "Starting Report Job Worker..."

export PYTHONPATH=/app
python -m services.report_job_worker