"""
daily_sales_service.py

Callable service wrapper around the daily sales report pipeline.
Invoked by report_job_worker.py — does NOT depend on argparse.

When parameters include delivery_method == 'table', the full section
row data is included in the return dict so the job result page can
render it inline. For email runs the sections key is omitted to avoid
bloating the Supabase result column on every automated run.
"""

import os
import logging
from datetime import datetime
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
from shopify_client import ShopifyClient


def _bucket_to_dict(info: dict) -> dict:
    """
    Serialize a product bucket into a clean JSON-safe dict
    for storage in the Supabase result column.
    """
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

    Called by execute_daily_sales() in report_job_worker.py, which passes
    the full job parameters dict through.

    parameters keys used here:
        delivery_method : 'email' | 'table'   (default: 'email')
        formats         : ['pdf', 'csv']       (default: ['pdf', 'csv'])

    When delivery_method == 'table', the full sections payload is included
    in the return value for dashboard rendering. Otherwise only metadata
    (filenames, row counts, email status) is returned.
    """
    parameters         = parameters or {}
    delivery_method    = parameters.get("delivery_method", "email")
    formats            = parameters.get("formats", ["pdf", "csv"])
    include_table_data = delivery_method == "table"

    start_date = start_et.date()
    end_date   = end_et.date()

    filename     = (
        f"daily_sales_report_"
        f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"
    )
    pdf_filename = (
        f"daily_sales_report_"
        f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.pdf"
    )
    pdf_path = os.path.join(os.getcwd(), pdf_filename)

    report_title = f"Daily Sales Report — {start_et.strftime('%B %d, %Y')}"
    window_text  = (
        f"{start_et.strftime('%b %d %Y %I:%M %p ET')} → "
        f"{end_et.strftime('%b %d %Y %I:%M %p ET')}"
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
            filename,
            start_et,
            end_et,
            dry_run=False,
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

        subject   = f"Daily Sales Report — {start_et.strftime('%B %d, %Y')}"
        html_body = (
            "<p>Your daily sales report is attached.</p>"
            f"<p><strong>{filename}</strong></p>"
        )
        attachments = prepare_mailtrap_attachments(attachment_paths)
        send_mailtrap_email(subject, html_body, attachments)
        email_sent = True
        logging.info("[service] Email sent via Mailtrap.")

    # ── Result payload ────────────────────────────────────────────────────────
    result: Dict = {
        "report_id":       "daily_sales",
        "window_start":    start_et.isoformat(),
        "window_end":      end_et.isoformat(),
        "csv_filename":    filename if csv_written else None,
        "pdf_filename":    pdf_filename if pdf_written else None,
        "email_sent":      email_sent,
        "delivery_method": delivery_method,
        "formats":         formats,
        "row_counts":      row_counts,
    }

    # Only embed full row data for table-delivery runs.
    # Automated email runs stay lean in Supabase.
    if include_table_data:
        result["sections"] = {
            section_key: sorted(
                [_bucket_to_dict(v) for v in buckets.values()],
                key=lambda x: sort_title_key(x["title"]),
            )
            for section_key, buckets in sections_raw.items()
        }

    return result