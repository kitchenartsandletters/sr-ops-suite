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

Note: "unfulfilled orders" for this report are derived from InventoryLevel committed quantities (the same numbers used by Shopify Admin), not fulfillment orders.
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

# Fetch ALL products (filtered via GraphQL argument, lighter pages)
PRODUCTS_QUERY = """
query WeeklyProducts($first: Int!, $after: String, $query: String) {
  products(first: $first, after: $after, query: $query) {
    edges {
      cursor
      node {
        id
        title
        totalInventory
        status
        onlineStoreUrl
        productType
        variants(first: 20) {
          edges {
            node {
              sku
              barcode
              inventoryItem {
                inventoryLevels(first: 10) {
                  edges {
                    node {
                      location {
                        name
                      }
                      quantities(names: ["committed"]) {
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
        collections(first: 10) {
          edges {
            node {
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


# -----------------------------
# Data fetch helpers
# -----------------------------

def fetch_all_products(client: ShopifyClient):
    """Fetch all ACTIVE products via GraphQL in reasonably sized pages.

    Notes:
      - Uses first=100 to keep per-query cost manageable.
      - Filters to status:active to avoid archived catalog noise.
      - Catches RuntimeError from ShopifyClient.graphql to avoid hard crashes
        if Shopify returns a transient 500; partial results are still returned
        and logged.
    """
    products = {}
    after = None

    page = 1
    while True:
        logging.info(f"[weekly] Fetching products page {page}...")
        variables = {
            "first": 100,
            "after": after,
            "query": "status:active",
        }
        try:
            data = client.graphql(PRODUCTS_QUERY, variables)
        except RuntimeError as e:
            logging.error("[weekly] Shopify GraphQL error on products page %d: %s", page, e)
            # Return what we have so far instead of crashing the whole script
            break

        if not data or "products" not in data:
            logging.warning("[weekly] No product data returned on page %d", page)
            break

        edges = data["products"].get("edges", [])
        for edge in edges:
            node = edge.get("node") or {}
            pid = node.get("id")
            if not pid:
                continue
            products[pid] = node

        page_info = data["products"].get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break

        if edges:
            after = edges[-1]["cursor"]
        else:
            logging.warning("[weekly] No edges on page %d despite hasNextPage=true; stopping.", page)
            break

        page += 1

    logging.info("[weekly] Loaded %d products (status:active)", len(products))
    return products



# New committed-qty mapping helper
def build_product_to_committed_qty(products):
    """
    Returns dict: { product_id: total_committed_qty } using InventoryLevels.

    We sum 'committed' quantities across all variants and locations for each product.
    This becomes our unified definition of "unfulfilled" customer obligations.
    """
    mapping = {}
    for pid, p in products.items():
        total_committed = 0
        variants_conn = (p.get("variants") or {}).get("edges", [])  # variants(first: 20)
        for v_edge in variants_conn:
            v_node = v_edge.get("node") or {}
            inv_item = (v_node.get("inventoryItem") or {})
            levels_conn = (inv_item.get("inventoryLevels") or {}).get("edges", [])
            for lvl_edge in levels_conn:
                lvl_node = lvl_edge.get("node") or {}
                quantities = lvl_node.get("quantities") or []
                for q in quantities:
                    # We requested names=["committed"], but be defensive.
                    if (q.get("name") or "").lower() == "committed":
                        qty = q.get("quantity") or 0
                        if isinstance(qty, (int, float)):
                            total_committed += qty
        if total_committed > 0:
            mapping[pid] = total_committed
    logging.info("[weekly] Built committed-qty map for %d products", len(mapping))
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
            if total_inv < 0:
                status = "backorder"
            elif total_inv == 0 and unfulfilled_qty > 0:
                status = "pending_fulfillment"
            else:
                status = ""
            rows.append({
                "product_id": pid,
                "title": p.get("title", ""),
                "author_or_sku": (v or {}).get("sku", ""),
                "barcode": (v or {}).get("barcode", ""),
                "inventory": total_inv,
                "collections": ", ".join(collections) if collections else "",
                "unfulfilled_qty": unfulfilled_qty,
                "backorder_status": status,
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
    "Status"
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
                r.get("backorder_status", ""),
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
    prod_to_unfulfilled_qty = build_product_to_committed_qty(products)

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