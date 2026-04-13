#!/usr/bin/env python3
"""
cron/daily_sales/enqueue_job.py

Inserts a queued daily_sales job into reports.report_jobs.
The report_job_worker picks it up, checks for schedule overrides,
and executes via daily_sales_service.py.
"""

import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ── Time gate ─────────────────────────────────────────────────────────────────
# Only enqueue between 9:50 AM and 10:15 AM ET.
# Blocks accidental runs triggered by Railway deploys or container restarts.

now_et    = datetime.now(ZoneInfo("America/New_York"))
hour_et   = now_et.hour
minute_et = now_et.minute

in_window = (hour_et == 9 and minute_et >= 50) or (hour_et == 10 and minute_et <= 15)

if not in_window:
    logging.info(
        f"Outside enqueue window — current ET time is {now_et.strftime('%H:%M')}. "
        f"Expected 09:50–10:15 ET. Skipping."
    )
    sys.exit(0)

# ── Enqueue ───────────────────────────────────────────────────────────────────

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
                "parameters": {"is_automated": True},
            })
            .execute()
        )

        if not resp.data:
            logging.error("Insert returned no data — job may not have been created.")
            sys.exit(1)

        job = resp.data[0]
        logging.info(
            f"✅ Daily sales job enqueued: id={job['id']} status={job['status']}"
        )

    except Exception as e:
        logging.exception(f"Failed to enqueue daily sales job: {e}")
        sys.exit(1)


if __name__ == "__main__":
    enqueue()