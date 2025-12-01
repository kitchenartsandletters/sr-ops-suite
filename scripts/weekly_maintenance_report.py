#!/usr/bin/env python3
"""
Weekly Maintenance Report

Generates three targeted maintenance reports:

1) Products with negative inventory but no open/unfulfilled orders
2) Products published to the Online Store but not in any collection
3) Products at 0 or less inventory with unfulfilled orders and NOT in the Preorder collection

Output:
  - weekly_negative_no_orders_YYYYMMDD.csv
  - weekly_published_no_collections_YYYYMMDD.csv
  - weekly_oos_unfulfilled_not_preorder_YYYYMMDD.csv

Runs independently of the business calendar logic; intended for a weekly cron at 10:00 AM ET on Fridays.
"""

# Hardcoded blacklist rules (titles, IDs, SKUs, etc.)
BLACKLISTED_TITLE_PREFIXES = [
    "Cookbook Club",
]

import os
import csv
import logging
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import base64
import requests
from pathlib import Path

from dotenv import load_dotenv

from lop_unfulfilled_report import ShopifyClient

# -----------------------------
# Mailtrap helpers (light copy)
# -----------------------------

def validate_env_for_mailtrap():
    required = ["MAILTRAP_API_TOKEN", "EMAIL_SENDER", "EMAIL_RECIPIENTS"]
    missing = [var for var in required if not os.getenv(var)]
    if missing:
        raise EnvironmentError(f"Missing Mailtrap environment variables: {', '.join(missing)}")


def prepare_mailtrap_attachments(filepaths):
    attachments = []
    for fp in filepaths:
        if not os.path.exists(fp):
            logging.warning(f"[weekly] Attachment missing: {fp}")
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
        "from": {"email": sender, "name": "Weekly Maintenance Report"},
        "to": to_addresses,
        "subject": subject,
        "html": html_body,
    }

    if attachments:
        payload["attachments"] = attachments

    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code != 200:
        logging.error(f"[weekly] Mailtrap error {resp.status_code}: {resp.text}")
        raise RuntimeError("Weekly maintenance email failed.")
    logging.info("📧 Weekly maintenance report email sent successfully.")


# -----------------------------
# GraphQL Queries
# -----------------------------

# Fetch ALL products (we’ll filter client-side for inventory, collections, etc.)
PRODUCTS_QUERY = """
query WeeklyProducts($first: Int!, $after: String) {
  products(first: $first, after: $after) {
    edges {
      cursor
      node {
        id
        title
        totalInventory
        status
        onlineStoreUrl
        productType
        variants(first: 50) {
          edges {
            node {
              id
              sku
              barcode
            }
          }
        }
        collections(first: 50) {
          edges {
            node {
              id
              title
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

# All unfulfilled orders (no date filter; weekly maintenance about current risk)
UNFULFILLED_ORDERS_QUERY = """
query WeeklyUnfulfilledOrders($first: Int!, $after: String) {
  orders(
    first: $first
    after: $after
    query: "fulfillment_status:unfulfilled financial_status:paid -financial_status:refunded"
    sortKey: PROCESSED_AT
    reverse: false
  ) {
    edges {
      cursor
      node {
        id
        name
        lineItems(first: 100) {
          edges {
            node {
              quantity
              variant {
                id
                product {
                  id
                  title
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


# -----------------------------
# Data fetch helpers
# -----------------------------

def fetch_all_products(client: ShopifyClient):
    products = {}
    after = None

    page = 1
    while True:
        logging.info(f"[weekly] Fetching products page {page}...")
        variables = {"first": 100, "after": after}
        data = client.graphql(PRODUCTS_QUERY, variables)
        if not data:
            break

        edges = data["products"]["edges"]
        for edge in edges:
            node = edge["node"]
            pid = node["id"]
            products[pid] = node

        if not data["products"]["pageInfo"]["hasNextPage"]:
            break
        after = edges[-1]["cursor"]
        page += 1

    logging.info("[weekly] Loaded %d products", len(products))
    return products


def fetch_unfulfilled_orders(client: ShopifyClient):
    orders = []
    after = None

    page = 1
    while True:
        logging.info(f"[weekly] Fetching unfulfilled orders page {page}...")
        variables = {"first": 50, "after": after}
        data = client.graphql(UNFULFILLED_ORDERS_QUERY, variables)
        if not data:
            break

        edges = data["orders"]["edges"]
        for edge in edges:
            orders.append(edge["node"])

        if not data["orders"]["pageInfo"]["hasNextPage"]:
            break
        after = edges[-1]["cursor"]
        page += 1

    logging.info("[weekly] Loaded %d unfulfilled orders", len(orders))
    return orders


def build_product_to_unfulfilled_qty(orders):
    """
    Returns dict: { product_id: total_unfulfilled_qty }
    """
    mapping = {}
    for order in orders:
        for edge in order["lineItems"]["edges"]:
            item = edge["node"]
            variant = item.get("variant")
            if not variant:
                continue
            product = variant.get("product")
            if not product:
                continue
            pid = product["id"]
            mapping[pid] = mapping.get(pid, 0) + item["quantity"]
    return mapping


def product_collections_titles(product_node):
    return [
        c["node"]["title"]
        for c in product_node.get("collections", {}).get("edges", [])
    ]


def product_primary_variant(product_node):
    """
    Just grab the first variant for display (title/SKU/ISBN proxies).
    """
    edges = product_node.get("variants", {}).get("edges", [])
    if edges:
        return edges[0]["node"]
    return None


def is_blacklisted(product_node):
    """
    Returns True if product title matches any blacklist rule.
    """
    title = (product_node.get("title") or "").strip()
    lowered = title.lower()

    for prefix in BLACKLISTED_TITLE_PREFIXES:
        if lowered.startswith(prefix.lower()):
            return True

    return False


# -----------------------------
# Report 1:
# Products with negative inventory but no unfulfilled orders
# -----------------------------

def report_negative_no_orders(products, prod_to_unfulfilled_qty):
    rows = []
    for pid, p in products.items():
        if is_blacklisted(p):
            continue
        total_inv = p.get("totalInventory")
        if total_inv is None:
            continue

        if total_inv < 0 and prod_to_unfulfilled_qty.get(pid, 0) == 0:
            v = product_primary_variant(p)
            collections = product_collections_titles(p)

            rows.append({
                "product_id": pid,
                "title": p.get("title", ""),
                "author_or_sku": (v or {}).get("sku", ""),
                "barcode": (v or {}).get("barcode", ""),
                "inventory": total_inv,
                "collections": ", ".join(collections) if collections else "",
                "unfulfilled_qty": 0,
            })

    logging.info("[weekly] Report 1: %d rows (negative inventory, no unfulfilled orders)", len(rows))
    return rows


# -----------------------------
# Report 2:
# Products published to Online Store but NOT in any collection
# -----------------------------

def is_published_to_online_store(p):
    # Heuristic: active + onlineStoreUrl exists
    status = p.get("status")
    online_url = p.get("onlineStoreUrl")
    return status == "ACTIVE" and bool(online_url)


def report_published_no_collections(products):
    rows = []
    for pid, p in products.items():
        if is_blacklisted(p):
            continue
        if not is_published_to_online_store(p):
            continue

        collections_edges = p.get("collections", {}).get("edges", [])
        if collections_edges:
            continue  # has at least one collection

        v = product_primary_variant(p)
        rows.append({
            "product_id": pid,
            "title": p.get("title", ""),
            "author_or_sku": (v or {}).get("sku", ""),
            "barcode": (v or {}).get("barcode", ""),
            "inventory": p.get("totalInventory"),
            "collections": "",
            "unfulfilled_qty": 0,
        })

    logging.info("[weekly] Report 2: %d rows (published, no collections)", len(rows))
    return rows


# -----------------------------
# Report 3:
# Products at 0 or less inventory, with unfulfilled orders,
# and NOT in the Preorder collection
# -----------------------------

def in_preorder_collection(p):
    for title in product_collections_titles(p):
        if title == "Preorder":
            return True
    return False


def report_oos_unfulfilled_not_preorder(products, prod_to_unfulfilled_qty):
    rows = []
    for pid, unfulfilled_qty in prod_to_unfulfilled_qty.items():
        p = products.get(pid)
        if not p:
            continue
        if is_blacklisted(p):
            continue

        total_inv = p.get("totalInventory")
        if total_inv is None:
            continue

        if total_inv <= 0 and not in_preorder_collection(p):
            v = product_primary_variant(p)
            collections = product_collections_titles(p)
            rows.append({
                "product_id": pid,
                "title": p.get("title", ""),
                "author_or_sku": (v or {}).get("sku", ""),
                "barcode": (v or {}).get("barcode", ""),
                "inventory": total_inv,
                "collections": ", ".join(collections) if collections else "",
                "unfulfilled_qty": unfulfilled_qty,
            })

    logging.info("[weekly] Report 3: %d rows (<=0 inventory, unfulfilled, not preorder)", len(rows))
    return rows


# -----------------------------
# CSV helpers
# -----------------------------

CSV_HEADER = [
    "Product ID",
    "Title",
    "Author/SKU",
    "ISBN/Barcode",
    "Inventory",
    "Unfulfilled Qty",
    "Collections",
]


def write_csv(filename, rows):
    if not rows:
        logging.info("[weekly] No rows for %s — CSV will still be created (header only).", filename)
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for r in rows:
            writer.writerow([
                r.get("product_id", ""),
                r.get("title", ""),
                r.get("author_or_sku", ""),
                r.get("barcode", ""),
                r.get("inventory", ""),
                r.get("unfulfilled_qty", ""),
                r.get("collections", ""),
            ])
    logging.info("[weekly] CSV written: %s", filename)


# -----------------------------
# Main runner
# -----------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Weekly maintenance report (inventory & order hygiene).")
    parser.add_argument("--dry-run", action="store_true", help="Run without sending email.")
    return parser.parse_args()


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    logging.info("🔧 Weekly Maintenance Report started...")

    args = parse_args()

    client = ShopifyClient()

    # 1. Load core data
    products = fetch_all_products(client)
    unfulfilled_orders = fetch_unfulfilled_orders(client)
    prod_to_unfulfilled_qty = build_product_to_unfulfilled_qty(unfulfilled_orders)

    # 2. Build reports
    logging.info("📦 Building Report 1: Negative inventory, no unfulfilled orders...")
    negative_no_orders = report_negative_no_orders(products, prod_to_unfulfilled_qty)

    logging.info("🧭 Building Report 2: Published to Online Store but not in any collection...")
    published_no_collections = report_published_no_collections(products)

    logging.info("🚨 Building Report 3: OOS/negative + unfulfilled and *not* in Preorder...")
    oos_unfulfilled_not_preorder = report_oos_unfulfilled_not_preorder(products, prod_to_unfulfilled_qty)

    # 3. Write CSVs
    today_et = datetime.now(ZoneInfo("America/New_York"))
    date_str = today_et.strftime("%Y%m%d")

    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)

    fn_neg = out_dir / f"weekly_negative_no_orders_{date_str}.csv"
    fn_pub = out_dir / f"weekly_published_no_collections_{date_str}.csv"
    fn_oos = out_dir / f"weekly_oos_unfulfilled_not_preorder_{date_str}.csv"

    logging.info("📝 Writing CSV 1 (negative inventory, no unfulfilled orders)...")
    write_csv(fn_neg, negative_no_orders)

    logging.info("📝 Writing CSV 2 (published, no collections)...")
    write_csv(fn_pub, published_no_collections)

    logging.info("📝 Writing CSV 3 (OOS/negative + unfulfilled, not Preorder)...")
    write_csv(fn_oos, oos_unfulfilled_not_preorder)

    if args.dry_run:
        logging.info("[weekly] Dry run — skipping email send.")
        return

    # 4. Email everything

    logging.info("📡 Preparing email with 3 CSV attachments...")
    attachments = prepare_mailtrap_attachments([
        str(fn_neg),
        str(fn_pub),
        str(fn_oos),
    ])

    subject = f"🧹 Weekly Maintenance Report — {today_et.strftime('%B %d, %Y')}"
    html_body = """
    <p>Attached are the weekly maintenance reports for inventory and order hygiene:</p>
    <ul>
      <li>Negative inventory with no unfulfilled orders</li>
      <li>Published to Online Store but in no collections</li>
      <li>Out-of-stock/negative with unfulfilled orders and not in Preorder collection</li>
    </ul>
    """

    logging.info("📨 Sending weekly maintenance email...")
    send_mailtrap_email(subject, html_body, attachments)


if __name__ == "__main__":
    main()