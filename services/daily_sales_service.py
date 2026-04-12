"""
daily_sales_service.py

Callable service wrapper around the daily sales report pipeline.
Invoked by report_job_worker.py — does NOT depend on argparse.

Schedule override behaviour:
  Before computing the reporting window from business_calendar, the service
  checks reports.report_schedule_overrides for a row matching today's run date.
  If found and not yet consumed, that window is used instead and the row is
  marked used_at = now().

Email subject/body:
  - Automated run, standard window:
      Subject: "Daily Sales Report — Monday, April 13, 2026"
  - Automated run, admin-overridden window:
      Subject: "Daily Sales Report — Apr 10–13, 2026 (Extended Window)"
      Body:    notes the extended coverage + label if set
  - On-demand manual run with custom date range:
      Subject: "Daily Sales Report — Apr 10–13, 2026 (On-Demand)"
      Body:    notes manually triggered with custom range
"""

import os
import logging
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
from typing import Dict

from scripts.daily_sales_report import (
    fetch_24h_orders,
    extract_product_ids,
    fetch_product_details,
    aggregate_products,
    write_csv,
    sort_title_key,
    prepare_mailtrap_attachments,
    send_mailtrap_email,
)
from scripts.daily_sales_pdf import generate_daily_sales_pdf
from scripts.business_calendar import get_reporting_window
from shopify_client import ShopifyClient
from services.supabase_client import supabase


def _bucket_to_dict(info: dict) -> dict:
    return {
        "title":       info.get("title", ""),
        "author":      info.get("author", ""),
        "vendor":      info.get("vendor", ""),
        "isbn":        info.get("isbn", ""),
        "price":       info.get("price", ""),
        "collections": info.get("collections", []),
        "available":   info.get("available"),
        "incoming":    info.get("incoming", 0),
        "ol_sold":     info.get("ol_sold", 0),
        "pos_sold":    info.get("pos_sold", 0),
        "attributes":  info.get("attributes", ""),
    }


def _fmt_date_range_short(start: date, end: date) -> str:
    """Format a date range compactly: 'Apr 10–13, 2026' or 'Apr 10 – May 2, 2026'."""
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%b %-d')}–{end.strftime('%-d, %Y')}"
    if start.year == end.year:
        return f"{start.strftime('%b %-d')} – {end.strftime('%b %-d, %Y')}"
    return f"{start.strftime('%b %-d, %Y')} – {end.strftime('%b %-d, %Y')}"


def _check_schedule_override(report_id: str, run_date: date) -> dict | None:
    """
    Look up an unconsumed schedule override for this report_id + run_date.
    Returns the row dict if found, None otherwise.
    """
    try:
        resp = (
            supabase
            .schema("reports")
            .table("report_schedule_overrides")
            .select("id, start_date, end_date, label")
            .eq("report_id", report_id)
            .eq("scheduled_date", run_date.isoformat())
            .is_("used_at", "null")
            .limit(1)
            .execute()
        )
        data = resp.data or []
        return data[0] if data else None
    except Exception as e:
        logging.warning(f"[service] Failed to check schedule override: {e}")
        return None


def _mark_override_used(override_id: str) -> None:
    """Mark a schedule override as consumed so it isn't applied again."""
    try:
        supabase \
            .schema("reports") \
            .table("report_schedule_overrides") \
            .update({"used_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", override_id) \
            .execute()
    except Exception as e:
        logging.warning(f"[service] Failed to mark override {override_id} as used: {e}")


def run_daily_sales_report(
    start_et: datetime,
    end_et: datetime,
    *,
    write_csv_file: bool = True,
    write_pdf: bool = True,
    send_email: bool = True,
    parameters: dict | None = None,
) -> Dict:
    """
    Execute the daily sales report pipeline and return structured metadata.

    parameters keys:
        delivery_method  : 'email' | 'table'   (default: 'email')
        formats          : ['pdf', 'csv']       (default: ['pdf', 'csv'])
        start_date       : 'YYYY-MM-DD'         override from on-demand run
        end_date         : 'YYYY-MM-DD'         override from on-demand run
        scheduled_date   : 'YYYY-MM-DD'         set by worker for automated runs
        is_manual        : bool                 True when triggered on-demand
    """
    parameters      = parameters or {}
    delivery_method = parameters.get("delivery_method", "email")
    formats         = parameters.get("formats", ["pdf", "csv"])
    is_manual       = bool(parameters.get("is_manual", False))
    include_table_data = delivery_method == "table"

    tz_et = ZoneInfo("America/New_York")

    # ── Determine effective window ────────────────────────────────────────────
    # Priority: 1) explicit manual date range, 2) schedule override, 3) business calendar

    run_type        = "automated"   # 'automated' | 'override' | 'on_demand'
    override_label  = None

    if is_manual and parameters.get("start_date") and parameters.get("end_date"):
        # On-demand run with explicit date range from the dashboard
        run_type = "on_demand"
        # Use the passed-in start_et / end_et (already set by worker from params)

    else:
        # Automated run — check for admin schedule override first
        run_date = start_et.date()
        scheduled_date_str = parameters.get("scheduled_date")
        if scheduled_date_str:
            run_date = date.fromisoformat(scheduled_date_str)

        schedule_override = _check_schedule_override("daily_sales", run_date)

        if schedule_override:
            # Admin has set a custom window for this run date
            run_type       = "override"
            override_label = schedule_override.get("label")
            ov_start       = date.fromisoformat(schedule_override["start_date"])
            ov_end         = date.fromisoformat(schedule_override["end_date"])
            start_et = datetime(ov_start.year, ov_start.month, ov_start.day, 10, 0, 0, tzinfo=tz_et)
            end_et   = datetime(ov_end.year,   ov_end.month,   ov_end.day,   9, 59, 59, tzinfo=tz_et)
            _mark_override_used(schedule_override["id"])
            logging.info(f"[service] Using schedule override: {ov_start} → {ov_end}")
        else:
            # Standard automated window from business calendar
            run_type = "automated"
            logging.info(f"[service] Using standard business calendar window.")

    start_date = start_et.date()
    end_date   = end_et.date()

    filename     = f"daily_sales_report_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"
    pdf_filename = f"daily_sales_report_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.pdf"
    pdf_path     = os.path.join(os.getcwd(), pdf_filename)

    window_text  = (
        f"{start_et.strftime('%b %d %Y %I:%M %p ET')} → "
        f"{end_et.strftime('%b %d %Y %I:%M %p ET')}"
    )

    # ── Subject + body copy based on run type ─────────────────────────────────
    date_range_short = _fmt_date_range_short(start_date, end_date)

    if run_type == "on_demand":
        report_title = f"Daily Sales Report — {date_range_short} (On-Demand)"
        subject      = f"Daily Sales Report — {date_range_short} (On-Demand)"
        html_body    = (
            f"<p>This is an <strong>on-demand</strong> daily sales report covering "
            f"<strong>{date_range_short}</strong>.</p>"
            f"<p>Window: {window_text}</p>"
            f"<p><strong>{filename}</strong></p>"
        )
    elif run_type == "override":
        report_title = f"Daily Sales Report — {date_range_short} (Extended Window)"
        subject      = f"Daily Sales Report — {date_range_short} (Extended Window)"
        label_note   = f" — {override_label}" if override_label else ""
        html_body    = (
            f"<p>This daily sales report covers an <strong>extended window</strong>"
            f"{label_note}: <strong>{date_range_short}</strong>.</p>"
            f"<p>Window: {window_text}</p>"
            f"<p><strong>{filename}</strong></p>"
        )
    else:
        # Standard automated run
        report_title = f"Daily Sales Report — {start_et.strftime('%B %d, %Y')}"
        subject      = f"Daily Sales Report — {start_et.strftime('%B %d, %Y')}"
        html_body    = (
            f"<p>Your daily sales report is attached.</p>"
            f"<p><strong>{filename}</strong></p>"
        )

    # ── Fetch + aggregate ─────────────────────────────────────────────────────
    client = ShopifyClient()

    orders          = fetch_24h_orders(client, start_et, end_et)
    product_ids     = extract_product_ids(orders)
    product_details = fetch_product_details(client, product_ids)

    main_sales, backorder_sales, oos_sales, preorder_sales = aggregate_products(
        orders, product_details
    )

    sections_raw = {
        "main":         main_sales,
        "backorders":   backorder_sales,
        "out_of_stock": oos_sales,
        "preorders":    preorder_sales,
    }
    row_counts = {k: len(v) for k, v in sections_raw.items()}

    # ── CSV ───────────────────────────────────────────────────────────────────
    csv_written = False
    if write_csv_file and "csv" in formats:
        write_csv(
            (main_sales, backorder_sales, oos_sales, preorder_sales),
            filename, start_et, end_et, dry_run=False,
        )
        csv_written = True
        logging.info(f"[service] CSV written: {filename}")

    # ── PDF ───────────────────────────────────────────────────────────────────
    pdf_written = False
    if write_pdf and "pdf" in formats:
        sections_for_pdf = {k: list(v.values()) for k, v in sections_raw.items()}
        generate_daily_sales_pdf(sections_for_pdf, pdf_path, report_title, window_text)
        pdf_written = True
        logging.info(f"[service] PDF written: {pdf_filename}")

    # ── Email ─────────────────────────────────────────────────────────────────
    email_sent = False
    if send_email and delivery_method == "email":
        attachment_paths = []
        if csv_written:
            attachment_paths.append(os.path.join(os.getcwd(), filename))
        if pdf_written:
            attachment_paths.append(pdf_path)
        attachments = prepare_mailtrap_attachments(attachment_paths)
        send_mailtrap_email(subject, html_body, attachments)
        email_sent = True
        logging.info(f"[service] Email sent: {subject}")

    # ── Result payload ────────────────────────────────────────────────────────
    result: Dict = {
        "report_id":       "daily_sales",
        "run_type":        run_type,
        "window_start":    start_et.isoformat(),
        "window_end":      end_et.isoformat(),
        "csv_filename":    filename if csv_written else None,
        "pdf_filename":    pdf_filename if pdf_written else None,
        "email_sent":      email_sent,
        "delivery_method": delivery_method,
        "formats":         formats,
        "row_counts":      row_counts,
    }

    if include_table_data:
        result["sections"] = {
            section_key: sorted(
                [_bucket_to_dict(v) for v in buckets.values()],
                key=lambda x: sort_title_key(x["title"]),
            )
            for section_key, buckets in sections_raw.items()
        }

    return result