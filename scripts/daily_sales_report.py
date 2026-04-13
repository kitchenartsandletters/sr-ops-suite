#!/usr/bin/env python3
"""
Daily Sales Report (previous calendar day, sales grouped by product)

This script:
- Connects to Shopify Admin GraphQL using env SHOP_URL + SHOPIFY_ACCESS_TOKEN
- Normalizes UTC → ET timestamps for correct previous day's 00:00–23:59 ET window
- Pulls all orders processed in the business-defined 10:00 AM ET → 9:59:59 AM ET window
- Aggregates quantity sold per product
- Fetches collection list + barcode + inventory per product
- Writes a CSV and PDF
- Supports: --dry-run
"""

import os
import csv
import logging
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import base64
import requests

from daily_sales_pdf import generate_daily_sales_pdf
from dotenv import load_dotenv

from lop_unfulfilled_report import ShopifyClient
from business_calendar import get_reporting_window, is_business_day


# Hardcoded blacklist of product IDs
BLACKLISTED_PRODUCT_IDS = {
    "gid://shopify/Product/5238890889349",
    "gid://shopify/Product/6544636477573",
    "gid://shopify/Product/5238923001989",
    "gid://shopify/Product/6604620202117",
    "gid://shopify/Product/6589468967045",
    "gid://shopify/Product/6830824489093",
    "gid://shopify/Product/6621878386821",
    "gid://shopify/Product/6621879304325",
    "gid://shopify/Product/6621878812805",
    "gid://shopify/Product/6621879533701",
    "gid://shopify/Product/6621879042181",
}


# -----------------------------
# MAILTRAP EMAIL DELIVERY
# -----------------------------

def validate_env_for_mailtrap():
    required = ["MAILTRAP_API_TOKEN", "EMAIL_SENDER", "EMAIL_RECIPIENTS"]
    missing = [var for var in required if not os.getenv(var)]
    if missing:
        raise EnvironmentError(
            f"Missing Mailtrap environment variables: {', '.join(missing)}"
        )


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
            "type": "text/csv" if fp.lower().endswith(".csv") else "application/pdf",
            "disposition": "attachment",
        })
    return attachments


def send_mailtrap_email(subject, html_body, attachments=None, recipients=None):
    validate_env_for_mailtrap()
    url = "https://send.api.mailtrap.io/api/send"
    token = os.getenv("MAILTRAP_API_TOKEN")
    sender = os.getenv("EMAIL_SENDER")
    recipient_list = os.getenv("EMAIL_RECIPIENTS", "")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    if recipients:
          to_addresses = [{"email": r} for r in recipients if r.strip()]
    else:
           to_addresses = [{"email": r.strip()} for r in recipient_list.split(",") if r.strip()]

    payload = {
        "from": {"email": sender, "name": "Daily Sales Report"},
        "to": to_addresses,
        "subject": subject,
        "html": html_body,
    }

    if attachments:
        payload["attachments"] = attachments

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        logging.error(f"Mailtrap error {response.status_code}: {response.text}")
        raise RuntimeError("Mailtrap email failed.")

    logging.info("📧 Daily sales report email sent successfully.")


# -----------------------------
# CLI
# -----------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate Daily Sales Report (business-defined rolling window)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without writing CSV/PDF or sending email.",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Override window start date (ET) in YYYY-MM-DD. Start time will be 10:00 AM ET on this date.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Override window end date (ET) in YYYY-MM-DD. End time will be 9:59:59 AM ET on this date.",
    )
    return parser.parse_args()


# -----------------------------
# GraphQL Queries
# -----------------------------

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
        sourceName
        channel {
          handle
        }
        lineItems(first: 100) {
          edges {
            node {
              quantity
              title
              customAttributes {
                key
                value
              }
              variant {
                id
                sku
                barcode
                product {
                  id
                  title
                  totalInventory
                }
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

PRODUCT_DETAILS_QUERY = """
query ProductDetails($id: ID!) {
  product(id: $id) {
    id
    title
    vendor
    totalInventory
    priceRangeV2 {
      minVariantPrice {
        amount
        currencyCode
      }
    }
    collections(first: 5) {
      edges {
        node {
          title
        }
      }
    }
    variants(first: 50) {
      edges {
        node {
          id
          inventoryItem {
            id
            inventoryLevels(first: 5) {
              edges {
                node {
                  quantities(names: ["incoming"]) {
                    name
                    quantity
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


# -----------------------------
# Data Fetching
# -----------------------------

def fetch_24h_orders(client: ShopifyClient, start_et: datetime, end_et: datetime):
    start_str = start_et.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
    end_str = end_et.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")

    q_filter = (
        f'financial_status:paid '
        f'-financial_status:refunded '
        f'processed_at:>="{start_str}" '
        f'processed_at:<="{end_str}"'
    )

    records = []
    after = None

    while True:
        variables = {
            "first": 100,
            "after": after,
            "query": q_filter,
        }

        data = client.graphql(ORDERS_24H_QUERY, variables)
        if not data:
            break

        edges = data["orders"]["edges"]

        for edge in edges:
            node = edge["node"]
            p_at = node.get("processedAt")
            if not p_at:
                continue

            try:
                dt = datetime.fromisoformat(p_at.replace("Z", "+00:00"))
            except Exception:
                logging.warning(f"Could not parse processedAt timestamp: {p_at}")
                continue

            dt_et = dt.astimezone(start_et.tzinfo)

            if start_et <= dt_et <= end_et:
                records.append(node)
            else:
                logging.warning(
                    f"⚠️ Drift detected: Shopify returned order {node.get('name')} "
                    f"processedAt={dt_et} outside strict window "
                    f"{start_et} → {end_et}"
                )

        if not data["orders"]["pageInfo"]["hasNextPage"]:
            break

        after = edges[-1]["cursor"]

    logging.info("Fetched %d strictly-windowed orders.", len(records))
    return records


def extract_product_ids(orders) -> set[str]:
    product_ids: set[str] = set()
    for order in orders:
        for edge in order.get("lineItems", {}).get("edges", []):
            item = edge.get("node") or {}
            variant = item.get("variant")
            if not variant:
                continue
            product = variant.get("product") or {}
            pid = product.get("id")
            if pid:
                product_ids.add(pid)
    return product_ids


def fetch_product_details(client: ShopifyClient, product_ids: set[str]) -> dict:
    details: dict[str, dict] = {}

    for pid in sorted(product_ids):
        variables = {"id": pid}
        data = client.graphql(PRODUCT_DETAILS_QUERY, variables)
        product = (data or {}).get("product")
        if not product:
            continue

        title = product.get("title") or ""
        total_inv = product.get("totalInventory")
        collections = [
            edge["node"]["title"]
            for edge in product.get("collections", {}).get("edges", [])
        ]

        price = None
        pr = product.get("priceRangeV2") or {}
        minp = pr.get("minVariantPrice") or {}
        amount = minp.get("amount")
        if amount is not None:
            price = amount

        incoming_total = 0
        for v_edge in product.get("variants", {}).get("edges", []):
            v_node = v_edge.get("node") or {}
            inv_item = v_node.get("inventoryItem") or {}
            for lvl_edge in inv_item.get("inventoryLevels", {}).get("edges", []):
                lvl_node = lvl_edge.get("node") or {}
                for q in lvl_node.get("quantities") or []:
                    if q.get("name") == "incoming":
                        qty_val = q.get("quantity") or 0
                        incoming_total += qty_val

        details[pid] = {
            "title": title,
            "vendor": product.get("vendor") or "",
            "available": total_inv,
            "collections": collections,
            "incoming": incoming_total,
            "price": price,
        }

    logging.info("Enriched %d products with collections + incoming inventory.", len(details))
    return details


# -----------------------------
# Aggregation
# -----------------------------

def aggregate_products(orders, product_details: dict, exclusion_ids: set | None = None):
    main_sales = {}
    preorder_sales = {}
    backorder_sales = {}
    oos_sales = {}
 
    # When called from daily_sales_service.py, exclusion_ids comes from the DB.
    # When called from the CLI (main()), exclusion_ids is None — fall back to
    # the hardcoded BLACKLISTED_PRODUCT_IDS for backwards compatibility.
    effective_exclusions = exclusion_ids if exclusion_ids is not None else BLACKLISTED_PRODUCT_IDS
 
    for order in orders:
        li_edges = order["lineItems"]["edges"]
 
        for edge in li_edges:
            item = edge["node"]
            variant = item.get("variant")
            if variant is None:
                continue
 
            attrs = {a["key"]: a["value"] for a in item.get("customAttributes", [])}
 
            product = variant["product"]
            pid = product["id"]
            base_title = product["title"]

            # ── TEMPORARY DEBUG ───────────────────────────────────────────────
            TARGET_IDS = {"6621879304325", "6621878386821"}
            if any(t in pid for t in TARGET_IDS):
                logging.info(f"[DEBUG] Found target: pid={pid}")
                logging.info(f"[DEBUG]   in effective_exclusions: {pid in effective_exclusions}")
                logging.info(f"[DEBUG]   variant={variant}")
                pdetail = product_details.get(pid, {})
                logging.info(f"[DEBUG]   pdetail={pdetail}")
                logging.info(f"[DEBUG]   title from pdetail={pdetail.get('title', product['title'])}")
                logging.info(f"[DEBUG]   collections={pdetail.get('collections', [])}")
            # ── END DEBUG ─────────────────────────────────────────────────────
 
            pdetail = product_details.get(pid, {})
            title = pdetail.get("title", base_title)
            collections = pdetail.get("collections", [])
            available = pdetail.get("available", product.get("totalInventory"))
            incoming = pdetail.get("incoming", 0)
            price = pdetail.get("price")
            vendor = pdetail.get("vendor", "")
 
            is_preorder = "Preorder" in collections
 
            if pid in effective_exclusions or "cookbook club" in title.lower():
                continue
 
            label_parts = []
            if attrs.get("_signed") == "true":
                label_parts.append("Signed")
            if attrs.get("_bookplate") == "true":
                label_parts.append("Bookplate")
            attr_label = ", ".join(label_parts)
 
            sku = variant.get("sku")
            barcode = variant.get("barcode")
 
            source = order.get("sourceName", "")
            handle = (order.get("channel") or {}).get("handle", "")
            is_online = (source == "web") or (handle == "online_store")
            quantity_target = "ol_sold" if is_online else "pos_sold"
 
            if is_preorder:
                target = preorder_sales
            else:
                if available is not None:
                    if available < 0:
                        target = backorder_sales
                    elif available == 0:
                        target = oos_sales
                    else:
                        target = main_sales
                else:
                    target = main_sales
 
            if pid not in target:
                target[pid] = {
                    "title": title,
                    "vendor": vendor,
                    "author": sku or "",
                    "collections": collections,
                    "isbn": barcode or "NO BARCODE",
                    "available": available,
                    "incoming": incoming,
                    "price": price,
                    "ol_sold": 0,
                    "pos_sold": 0,
                    "attributes": attr_label,
                }
            else:
                bucket = target[pid]
                bucket["available"] = available
                bucket["incoming"] = incoming
                bucket["collections"] = collections
                bucket["title"] = title
                bucket["price"] = price
                bucket["vendor"] = vendor
                if sku:
                    bucket["author"] = sku
                if barcode:
                    bucket["isbn"] = barcode
 
            target[pid][quantity_target] += item["quantity"]
 
    return main_sales, backorder_sales, oos_sales, preorder_sales


# -----------------------------
# Output Helpers
# -----------------------------

def sort_title_key(title: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", title)
    lowered = normalized.lower()

    for article in ("the ", "a ", "an "):
        if lowered.startswith(article):
            return lowered[len(article):]

    return lowered


def write_csv(data: tuple, filename: str, start_et: datetime, end_et: datetime, dry_run: bool):
    main_sales, backorder_sales, oos_sales, preorder_sales = data

    if dry_run:
        logging.info("Dry run: would write %s", filename)
        return filename

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        writer.writerow(["Report Date", datetime.now(start_et.tzinfo).strftime("%Y-%m-%d %H:%M %Z")])
        writer.writerow([
            f"Window: {start_et.strftime('%b %d %Y %I:%M %p ET')} → "
            f"{end_et.strftime('%b %d %Y %I:%M %p ET')}"
        ])
        writer.writerow([])

        header = [
            "Product",
            "Author",
            "Vendor",
            "ISBN",
            "Price",
            "Collection",
            "On Hand",
            "Incoming Inv",
            "Attributes",
            "Notes",
        ]

        writer.writerow(header)
        for _, info in sorted(main_sales.items(), key=lambda x: sort_title_key(x[1]["title"])):
            writer.writerow([
                info["title"],
                info["author"],
                info.get("vendor", ""),
                info["isbn"],
                info.get("price", ""),
                ", ".join(info["collections"]),
                info["available"],
                info.get("incoming", 0),
                info["attributes"],
                "",
            ])

        if backorder_sales:
            writer.writerow([])
            writer.writerow(["BACKORDERS"])
            writer.writerow([])
            writer.writerow(header)
            for _, info in sorted(backorder_sales.items(), key=lambda x: sort_title_key(x[1]["title"])):
                writer.writerow([
                    info["title"],
                    info["author"],
                    info.get("vendor", ""),
                    info["isbn"],
                    info.get("price", ""),
                    ", ".join(info["collections"]),
                    info["available"],
                    info.get("incoming", 0),
                    info["attributes"],
                    "",
                ])

        if oos_sales:
            writer.writerow([])
            writer.writerow(["OUT OF STOCK"])
            writer.writerow([])
            writer.writerow(header)
            for _, info in sorted(oos_sales.items(), key=lambda x: sort_title_key(x[1]["title"])):
                writer.writerow([
                    info["title"],
                    info["author"],
                    info.get("vendor", ""),
                    info["isbn"],
                    info.get("price", ""),
                    ", ".join(info["collections"]),
                    info["available"],
                    info.get("incoming", 0),
                    info["attributes"],
                    "",
                ])

        if preorder_sales:
            writer.writerow([])
            writer.writerow(["PREORDER SALES"])
            writer.writerow([])
            writer.writerow(header)
            for _, info in sorted(preorder_sales.items(), key=lambda x: sort_title_key(x[1]["title"])):
                writer.writerow([
                    info["title"],
                    info["author"],
                    info.get("vendor", ""),
                    info["isbn"],
                    info.get("price", ""),
                    ", ".join(info["collections"]),
                    info["available"],
                    info.get("incoming", 0),
                    info["attributes"],
                    "",
                ])

    logging.info("CSV written: %s", filename)
    return filename


# -----------------------------
# Main
# -----------------------------

def main():
    load_dotenv()
    args = parse_args()
    client = ShopifyClient()

    tz_et = ZoneInfo("America/New_York")
    today_et = datetime.now(tz_et)

    def _parse_ymd(s: str):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            raise ValueError(f"Invalid date '{s}'. Expected YYYY-MM-DD.")

    if args.start_date or args.end_date:
        start_date = _parse_ymd(args.start_date) if args.start_date else None
        end_date = _parse_ymd(args.end_date) if args.end_date else None

        if start_date is None:
            start_date, _ = get_reporting_window(today_et.date())
        if end_date is None:
            end_date = today_et.date()

        if end_date < start_date:
            raise ValueError(f"end-date {end_date} cannot be before start-date {start_date}")

        start_et = datetime(start_date.year, start_date.month, start_date.day, 10, 0, 0).replace(tzinfo=tz_et)
        end_et = datetime(end_date.year, end_date.month, end_date.day, 9, 59, 59).replace(tzinfo=tz_et)

    else:
        if not is_business_day(today_et.date()):
            logging.info(f"Today ({today_et.date()}) is not a business day — skipping report.")
            return

        start_date, _ = get_reporting_window(today_et.date())
        end_date = today_et.date()

        start_et = datetime(start_date.year, start_date.month, start_date.day, 10, 0, 0).replace(tzinfo=tz_et)
        end_et = datetime(end_date.year, end_date.month, end_date.day, 9, 59, 59).replace(tzinfo=tz_et)

    logging.info(f"Reporting window start ET: {start_et}")
    logging.info(f"Reporting window end ET: {end_et}")
    logging.info(f"UTC window: {start_et.astimezone(ZoneInfo('UTC'))} → {end_et.astimezone(ZoneInfo('UTC'))}")

    if args.start_date or args.end_date:
        logging.info(f"Using override date range: {start_date} → {end_date} (ET dates)")

    now_et = today_et

    orders = fetch_24h_orders(client, start_et, end_et)

    product_ids = extract_product_ids(orders)
    product_details = fetch_product_details(client, product_ids)

    main_sales, backorder_sales, oos_sales, preorder_sales = aggregate_products(
        orders,
        product_details,
    )

    filename = f"daily_sales_report_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"
    pdf_filename = f"daily_sales_report_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.pdf"

    if not args.dry_run:
        write_csv(
            (main_sales, backorder_sales, oos_sales, preorder_sales),
            filename,
            start_et,
            end_et,
            args.dry_run,
        )
    else:
        logging.info("Dry run: would write %s", filename)

    pdf_path = os.path.join(os.getcwd(), pdf_filename)

    if not args.dry_run:
        sections = {
            "main": list(main_sales.values()),
            "backorders": list(backorder_sales.values()),
            "out_of_stock": list(oos_sales.values()),
            "preorders": list(preorder_sales.values()),
        }

        report_title = f"Daily Sales Report — {now_et.strftime('%B %d, %Y')}"
        window_text = (
            f"{start_et.strftime('%b %d %Y %I:%M %p ET')} → "
            f"{end_et.strftime('%b %d %Y %I:%M %p ET')}"
        )

        generate_daily_sales_pdf(
            sections,
            pdf_path,
            report_title,
            window_text,
        )

    if not args.dry_run:
        filepath = os.path.join(os.getcwd(), filename)

        subject = f"Daily Sales Report — {now_et.strftime('%B %d, %Y')}"
        html_body = (
            "<p>Your daily sales report is attached.</p>"
            f"<p><strong>{filename}</strong></p>"
        )

        attachments = prepare_mailtrap_attachments([filepath, pdf_path])
        send_mailtrap_email(subject, html_body, attachments)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()