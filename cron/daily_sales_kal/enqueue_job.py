#!/usr/bin/env python3
"""
cron/daily_sales_kal/enqueue_job.py

Enqueues a daily_sales_kal job for 1435 Lexington.

SCHEDULING (Railway cron is UTC; the store opens at 10:00 AM *Eastern*):
    Set the service's cron to:   0 14,15 * * 1-6
    Both hours fire every day. Exactly ONE of them lands inside the ET gate below:
        EDT (Mar-Nov):  14:00Z = 10:00 ET  -> passes,   15:00Z = 11:00 ET -> exits quietly
        EST (Nov-Mar):  14:00Z = 09:00 ET  -> exits quietly, 15:00Z = 10:00 ET -> passes
    A single fixed UTC hour silently breaks twice a year (it broke on 2026-11-02).

The gate exists to stop deploys/restarts from enqueuing spurious reports. The
dedupe check below means that even a restart *inside* the window cannot enqueue twice.

Every path that ends WITHOUT a job being enqueued is either:
  - an expected, logged no-op (outside the gate, or a job already exists), or
  - a failure that sends an alert email and exits non-zero.
"""

import logging
import os
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

REPORT_ID      = "daily_sales_kal"
ET             = ZoneInfo("America/New_York")
GATE_START_MIN = 9 * 60 + 50     # 09:50 ET
GATE_END_MIN   = 10 * 60 + 30    # 10:30 ET  (was 10:15; Railway cron start jitter has been up to ~5 min)


def _send_enqueue_alert(error: str):
    """Best-effort alert. Never raises."""
    try:
        import requests as req
        token          = os.getenv("MAILTRAP_API_TOKEN")
        sender         = os.getenv("EMAIL_SENDER")
        recipients_raw = os.getenv("EMAIL_RECIPIENTS", "")
        if not token or not sender or not recipients_raw:
            logging.error("Cannot send enqueue alert — Mailtrap env vars missing.")
            return
        to_addresses = [{"email": r.strip()} for r in recipients_raw.split(",") if r.strip()]
        req.post(
            "https://send.api.mailtrap.io/api/send",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "from":    {"email": sender, "name": "KAL Report Worker"},
                "to":      to_addresses,
                "subject": "⚠️ KAL daily sales report failed to enqueue",
                "text": (
                    f"The KAL daily sales report cron failed to insert a job.\n\n"
                    f"Error: {error}\n\n"
                    f"The report will NOT run today unless you run it manually.\n"
                    f"https://admin.kitchenartsandletters.com/reports\n"
                ),
            },
            timeout=15,
        )
    except Exception as e:
        logging.error(f"Enqueue alert itself failed: {e}")


# ── Time gate ─────────────────────────────────────────────────────────────────
now_et  = datetime.now(ET)
now_utc = now_et.astimezone(timezone.utc)
now_min = now_et.hour * 60 + now_et.minute

if not (GATE_START_MIN <= now_min <= GATE_END_MIN):
    logging.warning(
        f"Outside enqueue window — now {now_et.strftime('%H:%M %Z')} "
        f"({now_utc.strftime('%H:%M')}Z). Window is 09:50–10:30 ET. Exiting WITHOUT enqueuing. "
        f"This is expected for one of the two daily cron firings (14:00Z / 15:00Z); "
        f"it is a problem only if NEITHER firing enqueues."
    )
    sys.exit(0)

# ── Enqueue ───────────────────────────────────────────────────────────────────

try:
    from services.supabase_client import supabase
except Exception as e:                       # was ImportError only, and exited without alerting
    logging.error(f"Failed to import supabase client: {e}")
    _send_enqueue_alert(f"Could not import supabase client: {e}")
    sys.exit(1)


def _already_enqueued_today() -> bool:
    """
    True if an automated job for this report already exists since 09:30 ET today.
    Fails OPEN: if the check itself errors we enqueue anyway — a duplicate report
    is better than a missing one.
    """
    try:
        since = now_et.replace(hour=9, minute=30, second=0, microsecond=0).astimezone(timezone.utc)
        resp = (
            supabase
            .schema("reports")
            .table("report_jobs")
            .select("id")
            .eq("report_id", REPORT_ID)
            .filter("parameters->>is_automated", "eq", "true")
            .gte("created_at", since.strftime("%Y-%m-%dT%H:%M:%SZ"))
            .limit(1)
            .execute()
        )
        return bool(resp.data)
    except Exception as e:
        logging.warning(f"Duplicate check failed ({e}); proceeding to enqueue.")
        return False


def enqueue():
    if _already_enqueued_today():
        logging.warning(
            f"An automated {REPORT_ID} job already exists for {now_et.date()} — "
            f"not enqueuing a duplicate."
        )
        return

    max_attempts = 3
    last_error   = "unknown error"
    for attempt in range(1, max_attempts + 1):
        try:
            resp = (
                supabase
                .schema("reports")
                .table("report_jobs")
                .insert({
                    "report_id":  REPORT_ID,
                    "status":     "queued",
                    "parameters": {
                        "is_automated":   True,
                        "scheduled_date": now_et.date().isoformat(),
                    },
                })
                .execute()
            )
            if not resp.data:
                raise RuntimeError("Insert returned no data.")
            job = resp.data[0]
            logging.info(f"✅ KAL daily sales job enqueued: id={job['id']}")
            return
        except Exception as e:
            last_error = str(e)
            logging.warning(f"Attempt {attempt}/{max_attempts} failed: {e}")
            if attempt < max_attempts:
                time.sleep(10)

    logging.error(f"All {max_attempts} attempts failed: {last_error}")
    _send_enqueue_alert(last_error)
    sys.exit(1)


if __name__ == "__main__":
    enqueue()
