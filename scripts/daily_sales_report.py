#!/usr/bin/env python3
"""
Daily Sales Report (previous calendar day, sales grouped by product)

This script:
- Connects to Shopify Admin GraphQL using env SHOP_URL + SHOPIFY_ACCESS_TOKEN
- Normalizes UTC → ET timestamps for correct previous day's 00:00–23:59 ET window
- Pulls all orders processed in last previous day's 00:00–23:59 ET window (paid, not refunded)
- Aggregates quantity sold per product
- Fetches collection list + barcode + inventory per product
- Writes a CSV:
    First row: Report Date | <ET datetime>
    Then columns:
      Product, Author, Collection, ISBN, Available, Quantity Sold, Notes
- Supports: --dry-run
"""

import os
import csv
import logging
import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import base64
import requests
from pathlib import Path

from dotenv import load_dotenv

from lop_unfulfilled_report import ShopifyClient
from business_calendar import get_reporting_window


# Hardcoded blacklist of product IDs
BLACKLISTED_PRODUCT_IDS = {
    "gid://shopify/Product/5238890889349",
    "gid://shopify/Product/6544636477573",
    "gid://shopify/Product/5238923001989",
    "gid://shopify/Product/6604620202117",
    "gid://shopify/Product/6589468967045",
}

""" MAILTRAP EMAIL DELIVERY """

def validate_env_for_mailtrap():
    required = ["MAILTRAP_API_TOKEN", "EMAIL_SENDER", "EMAIL_RECIPIENTS"]
    missing = [var for var in required if not os.getenv(var)]
    if missing:
        raise EnvironmentError(f"Missing Mailtrap environment variables: {', '.join(missing)}")

def prepare_mailtrap_attachments(filepaths):
    attachments = []
    for fp in filepaths:
        if not os.path.exists(fp):
            logging.warning(f"Attachment missing: {fp}")
            continue
        with open(fp, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        attachments.append({
            "filename": os.path.basename(fp),
            "content": encoded,
            "type": "text/csv",
            "disposition": "attachment",
        })
    return attachments

def send_mailtrap_email(subject, html_body, attachments=None):
    validate_env_for_mailtrap()
    url = "https://send.api.mailtrap.io/api/send"
    token = os.getenv("MAILTRAP_API_TOKEN")
    sender = os.getenv("EMAIL_SENDER")
    recipient_list = os.getenv("EMAIL_RECIPIENTS", "")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    to_addresses = [
        {"email": r.strip()}
        for r in recipient_list.split(",")
        if r.strip()
    ]

    payload = {
        "from": {"email": sender, "name": "Daily Sales Report"},
        "to": to_addresses,
        "subject": subject,
        "html": html_body
    }

    if attachments:
        payload["attachments"] = attachments

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        logging.error(f"Mailtrap error {response.status_code}: {response.text}")
        raise RuntimeError("Mailtrap email failed.")
    else:
        logging.info("📧 Daily sales report email sent successfully.")

def parse_args():
    parser = argparse.ArgumentParser(description="Generate Daily Sales Report (24h rolling window).")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing CSV output.")
    return parser.parse_args()


ORDERS_24H_QUERY = """
query Orders24h($first: Int!, $after: String, $query: String!) {
  orders(
    first: $first
    after: $after
    sortKey: PROCESSED_AT
    reverse: false
    query: $query
  ) {
    edges {
      cursor
      node {
        id
        name
        processedAt
        displayFinancialStatus
        sourceName
        channel {
          handle
        }
        lineItems(first: 100) {
          edges {
            node {
              quantity
              title
              variant {
                id
                sku
                barcode
                product {
                  id
                  title
                  totalInventory
                  collections(first: 20) {
                    edges {
                      node {
                        title
                      }
                    }
                  }
                }
              }
              customAttributes {
                key
                value
              }
            }
          }
        }
      }
    }
    pageInfo {
      hasNextPage
    }
  }
}
"""


def fetch_24h_orders(client: ShopifyClient, start_et: datetime, end_et: datetime):
    q_filter = (
        f"financial_status:paid "
        f"-financial_status:refunded "
        f"processed_at:>={start_et.isoformat()} "
        f"processed_at:<={end_et.isoformat()}"
    )

    records = []
    after = None

    while True:
        variables = {
            "first": 100,
            "after": after,
            "query": q_filter
        }

        data = client.graphql(ORDERS_24H_QUERY, variables)
        if not data:
            break

        edges = data["orders"]["edges"]
        for edge in edges:
            records.append(edge["node"])

        if not data["orders"]["pageInfo"]["hasNextPage"]:
            break

        after = edges[-1]["cursor"]

    logging.info("Fetched %d orders in last 24h window.", len(records))
    return records


def aggregate_products(orders):
    signed_bp_sales = {}
    main_sales = {}
    preorder_sales = {}

    for order in orders:
        li_edges = order["lineItems"]["edges"]
        for edge in li_edges:
            item = edge["node"]
            variant = item.get("variant")
            if variant is None:
                continue

            attrs = {a["key"]: a["value"] for a in item.get("customAttributes", [])}
            is_signed = attrs.get("_signed") == "true"
            is_bookplate = attrs.get("_bookplate") == "true"

            product = variant["product"]
            pid = product["id"]
            title = product["title"]

            is_preorder = any(c["node"]["title"] == "Preorder" for c in product["collections"]["edges"])

            # Blacklist by Product ID or Title prefix
            if pid in BLACKLISTED_PRODUCT_IDS or title.startswith("Cookbook Club:"):
                continue

            attr_label = ", ".join([
                lbl for lbl in (
                    "Signed" if is_signed else None,
                    "Bookplate" if is_bookplate else None
                ) if lbl
            ])

            title = product["title"]
            sku = variant.get("sku")
            barcode = variant.get("barcode")
            total_inv = product.get("totalInventory")

            collections = [
                c["node"]["title"]
                for c in product["collections"]["edges"]
            ]

            # Determine target bucket
            if is_preorder:
                target = preorder_sales
            elif is_signed or is_bookplate:
                target = signed_bp_sales
            else:
                target = main_sales

            bucket = target.setdefault(pid, {
                "title": title,
                "author": sku or "",
                "collections": collections,
                "isbn": barcode or "NO BARCODE",
                "available": total_inv,
                "ol_sold": 0,
                "pos_sold": 0,
                "attributes": attr_label,
            })

            # Robust OL/POS classification using both sourceName and channel.handle
            source = order.get("sourceName", "")
            handle = (order.get("channel") or {}).get("handle", "")

            is_online = (source == "web") or (handle == "online_store")
            is_pos = (source == "pos") or (handle == "pos")

            if is_online:
                bucket["ol_sold"] += item["quantity"]
            else:
                bucket["pos_sold"] += item["quantity"]

    return main_sales, preorder_sales, signed_bp_sales


def write_csv(data: tuple, report_datetime_et: datetime, dry_run: bool):
    main_sales, preorder_sales, signed_bp_sales = data
    filename = f"daily_sales_report_{report_datetime_et.strftime('%Y%m%d_%H%M')}.csv"

    if dry_run:
        logging.info("Dry run: would write %s", filename)
        return filename

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        writer.writerow(["Report Date", report_datetime_et.strftime("%Y-%m-%d %H:%M %Z")])
        writer.writerow([])

        writer.writerow([
            "Product",
            "Author",
            "Collection",
            "ISBN",
            "Available",
            "OL Sales",
            "POS Sales",
            "Attributes",
            "Notes"
        ])

        for pid, info in main_sales.items():
            writer.writerow([
                info["title"],
                info["author"],
                ", ".join(info["collections"]),
                info["isbn"],
                info["available"],
                info["ol_sold"],
                info["pos_sold"],
                info.get("attributes", ""),
                ""
            ])

        if preorder_sales:
            writer.writerow([])
            writer.writerow(["PREORDER SALES"])
            writer.writerow([])

            for pid, info in preorder_sales.items():
                writer.writerow([
                    info["title"],
                    info["author"],
                    ", ".join(info["collections"]),
                    info["isbn"],
                    info["available"],
                    info["ol_sold"],
                    info["pos_sold"],
                    info.get("attributes", ""),
                    ""
                ])

        if signed_bp_sales:
            writer.writerow([])
            writer.writerow(["SIGNED & BOOKPLATE SALES"])
            writer.writerow([])

            for pid, info in signed_bp_sales.items():
                writer.writerow([
                    info["title"],
                    info["author"],
                    ", ".join(info["collections"]),
                    info["isbn"],
                    info["available"],
                    info["ol_sold"],
                    info["pos_sold"],
                    info.get("attributes", ""),
                    ""
                ])

    logging.info("CSV written: %s", filename)
    return filename


def main():
    load_dotenv()

    args = parse_args()

    client = ShopifyClient()

    tz_et = ZoneInfo("America/New_York")
    today_et = datetime.now(tz_et)

    start_date, end_date = get_reporting_window(today_et.date())

    start_et = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=tz_et)
    end_et = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=tz_et)

    now_et = today_et

    orders = fetch_24h_orders(client, start_et, end_et)
    main_sales, preorder_sales, signed_bp_sales = aggregate_products(orders)
    write_csv((main_sales, preorder_sales, signed_bp_sales), now_et, args.dry_run)

    # === MAILTRAP EMAIL DELIVERY ===
    if not args.dry_run:
        filename = f"daily_sales_report_{now_et.strftime('%Y%m%d_%H%M')}.csv"
        filepath = os.path.join(os.getcwd(), filename)

        subject = f"📊 Daily Sales Report — {now_et.strftime('%B %d, %Y')}"
        html_body = (
            "<p>Your daily sales report is attached.</p>"
            f"<p><strong>{filename}</strong></p>"
        )

        attachments = prepare_mailtrap_attachments([filepath])
        send_mailtrap_email(subject, html_body, attachments)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
