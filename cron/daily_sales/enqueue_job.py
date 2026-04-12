#!/usr/bin/env python3
"""
cron/daily_sales/enqueue_job.py

Inserts a queued daily_sales job into reports.report_jobs.
The report_job_worker picks it up, checks for schedule overrides,
and executes via daily_sales_service.py.

Replaces the direct script invocation in run.sh.
"""

import logging
import sys
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

try:
    from services.supabase_client import supabase
except ImportError as e:
    logging.error(f"Failed to import supabase client: {e}")
    sys.exit(1)


def enqueue():
    try:
        resp = (
            supabase
            .schema("reports")
            .table("report_jobs")
            .insert({
                "report_id":  "daily_sales",
                "status":     "queued",
                "parameters": {},  # worker fills in scheduled_date + is_manual=False
            })
            .execute()
        )

        if not resp.data:
            logging.error("Insert returned no data — job may not have been created.")
            sys.exit(1)

        job = resp.data[0]
        logging.info(f"✅ Daily sales job enqueued: id={job['id']} status={job['status']}")

    except Exception as e:
        logging.exception(f"Failed to enqueue daily sales job: {e}")
        sys.exit(1)


if __name__ == "__main__":
    enqueue()