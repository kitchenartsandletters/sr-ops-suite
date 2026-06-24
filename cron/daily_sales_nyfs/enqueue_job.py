#!/usr/bin/env python3
"""
cron/daily_sales_nyfs/enqueue_job.py

Enqueues a daily_sales_nyfs job for 111 Broadway.
Runs at 12:00 PM ET via Railway cron (0 16 * * 2-0 UTC).
Broadway is open Tue–Sun so cron fires Tue–Sun (2-7 in cron = Tue–Sun).
"""

import logging
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ── Time gate ─────────────────────────────────────────────────────────────────
now_et    = datetime.now(ZoneInfo("America/New_York"))
hour_et   = now_et.hour
minute_et = now_et.minute

in_window = (hour_et == 11 and minute_et >= 50) or (hour_et == 12 and minute_et <= 15)

if not in_window:
    logging.info(
        f"Outside enqueue window — current ET time is {now_et.strftime('%H:%M')}. "
        f"Expected 11:50–12:15 ET. Skipping."
    )
    sys.exit(0)

# ── Enqueue ───────────────────────────────────────────────────────────────────

try:
    from services.supabase_client import supabase
except ImportError as e:
    logging.error(f"Failed to import supabase client: {e}")
    sys.exit(1)


def _send_enqueue_alert(error: str):
    try:
        import requests as req
        token          = os.getenv("MAILTRAP_API_TOKEN")
        sender         = os.getenv("EMAIL_SENDER")
        recipients_raw = os.getenv("NYFS_EMAIL_RECIPIENTS", "") or os.getenv("EMAIL_RECIPIENTS", "")
        if not token or not sender or not recipients_raw:
            return
        to_addresses = [{"email": r.strip()} for r in recipients_raw.split(",") if r.strip()]
        req.post(
            "https://send.api.mailtrap.io/api/send",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "from":    {"email": sender, "name": "KAL Report Worker"},
                "to":      to_addresses,
                "subject": "⚠️ NYFS daily sales report failed to enqueue",
                "text": (
                    f"The NYFS (111 Broadway) daily sales report cron failed to insert a job.\n\n"
                    f"Error: {error}\n\n"
                    f"The report will NOT run today. Manual intervention required.\n"
                    f"https://admin.kitchenartsandletters.com/reports\n"
                ),
            },
            timeout=15,
        )
    except Exception:
        pass


def enqueue():
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            resp = (
                supabase
                .schema("reports")
                .table("report_jobs")
                .insert({
                    "report_id":  "daily_sales_nyfs",
                    "status":     "queued",
                    "parameters": {"is_automated": True},
                })
                .execute()
            )
            if not resp.data:
                logging.error("Insert returned no data.")
                sys.exit(1)
            job = resp.data[0]
            logging.info(f"✅ NYFS daily sales job enqueued: id={job['id']}")
            return
        except Exception as e:
            logging.warning(f"Attempt {attempt}/{max_attempts} failed: {e}")
            if attempt < max_attempts:
                time.sleep(10)
            else:
                logging.error(f"All {max_attempts} attempts failed.")
                _send_enqueue_alert(str(e))
                sys.exit(1)


if __name__ == "__main__":
    enqueue()