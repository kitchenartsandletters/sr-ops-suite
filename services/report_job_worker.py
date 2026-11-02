#!/usr/bin/env python3
"""
Async Report Job Worker

Polls Supabase (reports.report_jobs) for queued jobs,
claims them atomically via RPC,
executes report services,
updates status + result metadata.

Also runs a missing-run watchdog (see check_expected_runs): on business days it
asserts that the automated job actually EXISTS by a deadline, and emails if not.
That check is independent of the enqueuer, Railway cron, and DST, so it catches
every "nothing was enqueued" failure mode rather than just the ones we've seen.

Intended to run as a dedicated Railway worker service.
"""

import os
import time
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from services.supabase_client import supabase

# Import report executors
from services.daily_sales_service import run_daily_sales_report
from scripts.business_calendar import (
    get_reporting_window,
    is_business_day,
    get_open_time,
    get_close_time,
    LOCATION_KAL,
    LOCATION_NYFS,
)


# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

POLL_INTERVAL_SECONDS = int(os.getenv("REPORT_WORKER_POLL_INTERVAL", "5"))
KAL_LOCATION_ID  = os.getenv("KAL_LOCATION_ID",  "gid://shopify/Location/40052293765")
NYFS_LOCATION_ID = os.getenv("NYFS_LOCATION_ID", "gid://shopify/Location/67668738181")

# Automated jobs that MUST exist on business days, and the ET time by which they must.
# (report_id, calendar location, deadline hour ET, deadline minute ET)
# NYFS is intentionally absent: the pop-up closed in Sept 2026 and its cron is disabled.
# If it returns, add ("daily_sales_nyfs", LOCATION_NYFS, 12, 30) — and fix its enqueue gate
# the same way as KAL's (cron/daily_sales_nyfs/enqueue_job.py has the identical DST flaw).
EXPECTED_AUTOMATED_RUNS = [
    ("daily_sales_kal", LOCATION_KAL, 10, 30),
]
WATCHDOG_INTERVAL_SECONDS = 60
WATCHDOG_STOP_HOUR_ET     = 18    # don't raise missed-run alerts in the evening (e.g. after a late restart)

load_dotenv()

_missing_run_alerted: set = set()   # {(report_id, 'YYYY-MM-DD')}  once per day per process


# ─────────────────────────────────────────────────────────────
# Utility Functions
# ─────────────────────────────────────────────────────────────

def _send_alert_email(subject: str, text: str) -> bool:
    """
    Best-effort plain-text alert to EMAIL_RECIPIENTS via Mailtrap.
    Never raises. Returns True if Mailtrap accepted it.
    """
    try:
        import requests as req
        token          = os.getenv("MAILTRAP_API_TOKEN")
        sender         = os.getenv("EMAIL_SENDER")
        recipients_raw = os.getenv("EMAIL_RECIPIENTS", "")
        if not token or not sender or not recipients_raw:
            logging.warning("[worker] Cannot send alert — Mailtrap env vars missing.")
            return False

        to_addresses = [{"email": r.strip()} for r in recipients_raw.split(",") if r.strip()]
        resp = req.post(
            "https://send.api.mailtrap.io/api/send",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "from":    {"email": sender, "name": "KAL Report Worker"},
                "to":      to_addresses,
                "subject": subject,
                "text":    text,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            return True
        logging.warning(f"[worker] Alert send failed: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        logging.warning(f"[worker] Could not send alert: {e}")
        return False


def send_failure_alert(job_id: str, report_id: str, error: str):
    """Alert for a job that was claimed and then failed."""
    ok = _send_alert_email(
        f"⚠️ Report job failed: {report_id}",
        (
            f"A report job failed and requires attention.\n\n"
            f"Job ID:    {job_id}\n"
            f"Report:    {report_id}\n"
            f"Error:     {error}\n\n"
            f"Check the admin dashboard for details:\n"
            f"https://admin.kitchenartsandletters.com/reports\n"
        ),
    )
    if ok:
        logging.info(f"[worker] Failure alert sent for job {job_id}.")


def check_expected_runs(now_et: datetime | None = None):
    """
    Missing-run watchdog. For each expected automated report: on a business day,
    after its deadline, if NO job row for that report exists since 09:30 ET today,
    send one alert email.

    Notes:
      - Any job created since 09:30 ET satisfies the check, including a manual run
        or a failed job (failed jobs already alert on their own).
      - Once per report per day per process. A worker restart later the same day
        can re-alert once.
      - A failure of the check itself is logged and retried next tick; it never
        marks the day as alerted.
    """
    tz_et  = ZoneInfo("America/New_York")
    now_et = now_et or datetime.now(tz_et)
    today  = now_et.date()

    for report_id, cal_loc, hh, mm in EXPECTED_AUTOMATED_RUNS:
        key = (report_id, today.isoformat())
        if key in _missing_run_alerted:
            continue

        deadline = now_et.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now_et < deadline or now_et.hour >= WATCHDOG_STOP_HOUR_ET:
            continue

        try:
            if not is_business_day(today, cal_loc):
                continue

            since = now_et.replace(hour=9, minute=30, second=0, microsecond=0).astimezone(timezone.utc)
            resp = (
                supabase
                .schema("reports")
                .table("report_jobs")
                .select("id")
                .eq("report_id", report_id)
                .gte("created_at", since.strftime("%Y-%m-%dT%H:%M:%SZ"))
                .limit(1)
                .execute()
            )
            if resp.data:
                continue

            _missing_run_alerted.add(key)
            logging.error(
                f"[watchdog] No {report_id} job exists for {today} as of "
                f"{now_et.strftime('%H:%M %Z')} (deadline {hh:02d}:{mm:02d} ET). Alerting."
            )
            _send_alert_email(
                f"🚨 Daily report did NOT run: {report_id} ({today})",
                (
                    f"{report_id} is expected on business days, and no job exists for {today} "
                    f"as of {now_et.strftime('%H:%M %Z')} (expected by {hh:02d}:{mm:02d} ET).\n\n"
                    f"Nothing was enqueued. Likely causes: the Railway cron for the enqueue service "
                    f"did not fire, fired outside the enqueue time gate, or the container crashed "
                    f"before inserting a job. Check that service's deploy logs around 14:00Z / 15:00Z.\n\n"
                    f"To get today's report now, run it from the dashboard:\n"
                    f"https://admin.kitchenartsandletters.com/reports\n"
                ),
            )
        except Exception:
            logging.exception(f"[watchdog] Check for {report_id} failed; will retry next tick.")


# ─────────────────────────────────────────────────────────────
# Report Dispatcher
# ─────────────────────────────────────────────────────────────

def _execute_daily_sales_for_location(parameters: dict, location_id: str, cal_location: str):
    """
    Shared executor logic for both KAL and NYFS daily sales reports.
    cal_location: 'kal' or 'nyfs' — used for business calendar lookups.
    location_id:  Shopify location GID — used for order and inventory filtering.
    """
    tz_et    = ZoneInfo("America/New_York")
    today_et = datetime.now(tz_et)

    start_date_str = parameters.get("start_date")
    end_date_str   = parameters.get("end_date")

    open_h,  open_m  = get_open_time(cal_location)
    close_h, close_m = get_close_time(cal_location)

    if start_date_str and end_date_str:
        start_date = datetime.fromisoformat(start_date_str).date()
        end_date   = datetime.fromisoformat(end_date_str).date()
        parameters = {**parameters, "is_manual": True}

    else:
        if not is_business_day(today_et.date(), cal_location):
            logging.info(
                f"[worker] {today_et.date()} is not a business day for {cal_location} — skipping."
            )
            return {"skipped": True, "reason": "non_business_day", "location": cal_location}

        start_date, _ = get_reporting_window(today_et.date(), cal_location)
        end_date      = today_et.date()
        parameters    = {
            **parameters,
            "scheduled_date": today_et.date().isoformat(),
            "is_manual": False,
        }

    # tzinfo=ZoneInfo resolves the correct EDT/EST offset for each date, so a merged
    # window that crosses a DST transition has -04:00 on one end and -05:00 on the other.
    start_et = datetime(
        start_date.year, start_date.month, start_date.day,
        open_h, open_m, 0, tzinfo=tz_et
    )
    end_et = datetime(
        end_date.year, end_date.month, end_date.day,
        close_h, close_m, 59, tzinfo=tz_et
    )

    logging.info(
        f"[worker] {cal_location.upper()} daily sales ET window: "
        f"{start_et.isoformat()} → {end_et.isoformat()}"
    )

    return run_daily_sales_report(
        start_et=start_et,
        end_et=end_et,
        write_csv_file=True,
        write_pdf=True,
        send_email=True,
        parameters={
            **parameters,
            "location_id":     location_id,
            "cal_location":    cal_location,
        },
    )


def execute_daily_sales_kal(parameters: dict):
    return _execute_daily_sales_for_location(
        parameters,
        location_id=KAL_LOCATION_ID,
        cal_location=LOCATION_KAL,
    )


def execute_daily_sales_nyfs(parameters: dict):
    return _execute_daily_sales_for_location(
        parameters,
        location_id=NYFS_LOCATION_ID,
        cal_location=LOCATION_NYFS,
    )


REPORT_EXECUTORS = {
    "daily_sales_kal":  execute_daily_sales_kal,
    "daily_sales_nyfs": execute_daily_sales_nyfs,
}


# ─────────────────────────────────────────────────────────────
# Job Lifecycle Helpers
# ─────────────────────────────────────────────────────────────

def claim_next_job():
    resp = supabase.rpc("reports_claim_next_job").execute()

    data = resp.data

    # No job returned
    if not data:
        return None

    # If function returns a single object
    if isinstance(data, dict):
        return data

    # If function returns list
    if isinstance(data, list) and len(data) > 0:
        return data[0]

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
        send_failure_alert(job_id, report_id, str(e))


async def worker_loop():
    logging.info("🚀 Report Job Worker started.")
    logging.info(
        "[watchdog] Expecting automated runs: "
        + ", ".join(f"{r} by {h:02d}:{m:02d} ET" for r, _, h, m in EXPECTED_AUTOMATED_RUNS)
    )
    last_watchdog = 0.0

    while True:
        try:
            now = time.monotonic()
            if now - last_watchdog >= WATCHDOG_INTERVAL_SECONDS:
                last_watchdog = now
                check_expected_runs()          # never raises; logs its own errors

            job = claim_next_job()

            # No job returned (None, empty dict, etc.)
            if not job or not isinstance(job, dict) or not job.get("id"):
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            logging.info(
                f"[worker] Processing job {job.get('id')} ({job.get('report_id')})"
            )

            await process_job(job)

        except Exception:
            logging.exception("[worker] Unexpected error in worker loop.")
            await asyncio.sleep(5)


# ─────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(worker_loop())
