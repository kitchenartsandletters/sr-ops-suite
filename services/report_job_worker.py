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
from supabase import create_client

# Import report executors
from services.daily_sales_service import run_daily_sales_report


# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

POLL_INTERVAL_SECONDS = int(os.getenv("REPORT_WORKER_POLL_INTERVAL", "5"))

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY environment variables.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ─────────────────────────────────────────────────────────────
# Report Dispatcher
# ─────────────────────────────────────────────────────────────

async def execute_daily_sales(parameters: dict):
    """
    Dispatch wrapper for daily sales report.
    Supports optional start_date / end_date overrides.
    """

    start_date = parameters.get("start_date")
    end_date = parameters.get("end_date")

    result = await run_daily_sales_report(
        start_date=start_date,
        end_date=end_date,
        generate_pdf=True,
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
    resp = supabase.rpc("reports_claim_next_job").execute()

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

        result = await executor(parameters)

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