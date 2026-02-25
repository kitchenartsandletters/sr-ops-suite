#!/usr/bin/env python3
"""
Async Report Job Worker

Polls Supabase (reports.report_jobs) for queued jobs,
claims them atomically via RPC,
executes report services,
updates status + result metadata.

Intended to run as a dedicated Railway worker service.
"""

import os
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from services.supabase_client import supabase

# Import report executors
from services.daily_sales_service import run_daily_sales_report
from scripts.business_calendar import get_reporting_window, is_business_day


# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

POLL_INTERVAL_SECONDS = int(os.getenv("REPORT_WORKER_POLL_INTERVAL", "5"))

load_dotenv()


# ─────────────────────────────────────────────────────────────
# Report Dispatcher
# ─────────────────────────────────────────────────────────────

def execute_daily_sales(parameters: dict):
    """
    Dispatch wrapper for daily sales report.
    Computes ET window using business_calendar for exact CLI parity.
    """

    tz_et = ZoneInfo("America/New_York")

    start_date_str = parameters.get("start_date")
    end_date_str = parameters.get("end_date")

    # If explicit date range passed (manual run)
    if start_date_str and end_date_str:
        start_date = datetime.fromisoformat(start_date_str).date()
        end_date = datetime.fromisoformat(end_date_str).date()
    else:
        # Default CLI behavior: previous business window
        today_et = datetime.now(tz_et)

        if not is_business_day(today_et.date()):
            logging.info(
                f"[worker] {today_et.date()} is not a business day — skipping daily_sales job."
            )
            return {"skipped": True, "reason": "non_business_day"}

        start_date, _ = get_reporting_window(today_et.date())
        end_date = today_et.date()

    start_et = datetime(
        start_date.year, start_date.month, start_date.day,
        10, 0, 0, tzinfo=tz_et
    )

    end_et = datetime(
        end_date.year, end_date.month, end_date.day,
        9, 59, 59, tzinfo=tz_et
    )

    logging.info(
        f"[worker] Daily sales ET window: "
        f"{start_et.isoformat()} → {end_et.isoformat()}"
    )

    result = run_daily_sales_report(
        start_et=start_et,
        end_et=end_et,
        write_csv=True,
        write_pdf=True,
        send_email=True,
    )

    return result


REPORT_EXECUTORS = {
    "daily_sales": execute_daily_sales,
    # Future:
    # "weekly_maintenance": execute_weekly_maintenance,
    # "lop_unfulfilled": execute_lop_unfulfilled,
}


# ─────────────────────────────────────────────────────────────
# Job Lifecycle Helpers
# ─────────────────────────────────────────────────────────────

def claim_next_job():
    """
    Atomically claim the next queued job via RPC.
    """
    resp = supabase.rpc("reports.reports_claim_next_job").execute()

    if resp.data:
        return resp.data[0]

    return None


def update_job(job_id: str, *, status: str, result=None, error=None):
    payload = {
        "status": status,
    }

    now_utc = datetime.now(timezone.utc).isoformat()

    if status == "running":
        payload["started_at"] = now_utc

    if status in ("success", "failed", "cancelled"):
        payload["completed_at"] = now_utc

    if result is not None:
        payload["result"] = result

    if error is not None:
        payload["error"] = error

    supabase.schema("reports") \
        .table("report_jobs") \
        .update(payload) \
        .eq("id", job_id) \
        .execute()


# ─────────────────────────────────────────────────────────────
# Worker Loop
# ─────────────────────────────────────────────────────────────

async def process_job(job: dict):
    job_id = job["id"]
    report_id = job["report_id"]
    parameters = job.get("parameters") or {}

    logging.info(f"[worker] Processing job {job_id} ({report_id})")

    try:
        update_job(job_id, status="running")

        executor = REPORT_EXECUTORS.get(report_id)
        if not executor:
            raise ValueError(f"No executor registered for report_id='{report_id}'")

        if asyncio.iscoroutinefunction(executor):
            result = await executor(parameters)
        else:
            result = executor(parameters)

        update_job(job_id, status="success", result=result)

        logging.info(f"[worker] Job {job_id} completed successfully.")

    except Exception as e:
        logging.exception(f"[worker] Job {job_id} failed.")
        update_job(job_id, status="failed", error=str(e))


async def worker_loop():
    logging.info("🚀 Report Job Worker started.")

    while True:
        try:
            job = claim_next_job()

            if job:
                await process_job(job)
            else:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

        except Exception:
            logging.exception("[worker] Unexpected error in worker loop.")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


# ─────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(worker_loop())