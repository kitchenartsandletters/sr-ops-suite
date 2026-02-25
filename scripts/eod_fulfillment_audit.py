#!/usr/bin/env python3
"""
EOD Fulfillment Audit Report

Finds open orders that:
  - are UNFULFILLED or PARTIALLY_FULFILLED
  - require shipping
  - are NOT cancelled
  - are FULLY SHIPPABLE right now:
        * not in Preorder collection
        * inventory >= 0
        * inventory >= committed qty

Outputs:
  - eod_fulfillment_audit_YYYYMMDD.csv

Intended as an end-of-day oversight tool.
"""

import os
import csv
import logging
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Dict, Any, List

from dotenv import load_dotenv

# Reuse your existing Shopify client + helpers
from lop_unfulfilled_report import ShopifyClient
from weekly_maintenance_report import (
    fetch_all_products,
    build_product_to_committed_qty,
    product_collections_titles,
)

# -----------------------------
# GraphQL: Open Orders Query
# -----------------------------

OPEN_ORDERS_QUERY = """
query OpenOrders($first: Int!, $after: String) {
  orders(
    first: $first,
    after: $after,
    sortKey: CREATED_AT,
    reverse: false,
    query: "status:open"
  ) {
    edges {
      cursor
      node {
        id
        name
        createdAt
        displayFulfillmentStatus
        requiresShipping
        cancelledAt
        note
        lineItems(first: 100) {
          edges {
            node {
              title
              quantity
              variant {
                sku
                product {
                  id
                }
              }
            }
          }
          pageInfo {
            hasNextPage
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
# Helpers
# -----------------------------

def in_preorder_collection(product_node: Dict[str, Any]) -> bool:
    for title in product_collections_titles(product_node):
        if title == "Preorder":
            return True
    return False


def is_order_candidate(order_node: Dict[str, Any]) -> bool:
    """
    Filter to open, shipping-required, unfulfilled orders.
    """
    if order_node.get("cancelledAt"):
        return False

    if not order_node.get("requiresShipping"):
        return False

    status = order_node.get("displayFulfillmentStatus")
    if status not in ("UNFULFILLED", "PARTIALLY_FULFILLED"):
        return False

    return True


def fetch_open_orders(client: ShopifyClient) -> List[Dict[str, Any]]:
    """
    Fetch all open orders via pagination.
    """
    logging.info("📦 Fetching open orders...")
    orders = []
    after = None
    page = 1

    while True:
        logging.info(f"Fetching open orders page {page}...")
        data = client.graphql(
            OPEN_ORDERS_QUERY,
            {"first": 50, "after": after},
        )

        conn = data["orders"]
        for edge in conn["edges"]:
            orders.append(edge["node"])

        if not conn["pageInfo"]["hasNextPage"]:
            break

        after = conn["edges"][-1]["cursor"]
        page += 1

    logging.info("Loaded %d open orders", len(orders))
    return orders


def order_is_fully_shippable(
    order_node: Dict[str, Any],
    products: Dict[str, Dict[str, Any]],
    prod_to_committed_qty: Dict[str, int],
) -> bool:
    """
    Determines whether ALL line items are shippable.
    """

    for edge in order_node["lineItems"]["edges"]:
        li = edge["node"]
        variant = li.get("variant")

        if not variant or not variant.get("product"):
            return False

        product_id = variant["product"]["id"]
        product = products.get(product_id)

        if not product:
            logging.warning("Missing product for ID %s", product_id)
            return False

        total_inventory = product.get("totalInventory")
        committed_qty = prod_to_committed_qty.get(product_id, 0)

        if total_inventory is None:
            return False

        # Rule 1: Not preorder
        if in_preorder_collection(product):
            return False

        # Rule 2: No negative inventory
        if total_inventory < 0:
            return False

        # Rule 3: Must cover committed
        if total_inventory < committed_qty:
            return False

    return True


# -----------------------------
# CSV Writer
# -----------------------------

CSV_HEADER = [
    "Order #",
    "Created At",
    "Fulfillment Status",
    "Line Count",
    "Note",
]


def write_csv(filename: Path, rows: List[Dict[str, Any]]):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for r in rows:
            writer.writerow([
                r["order_name"],
                r["created_at"],
                r["status"],
                r["line_count"],
                r["note"],
            ])
    logging.info("CSV written: %s", filename)


# -----------------------------
# Main
# -----------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="EOD fulfillment audit.")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing CSV.")
    return parser.parse_args()


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    args = parse_args()

    logging.info("🔍 Starting EOD Fulfillment Audit...")

    client = ShopifyClient()

    # 1. Load products + committed map (reuse weekly logic)
    products = fetch_all_products(client)
    prod_to_committed_qty = build_product_to_committed_qty(products)

    # 2. Fetch open orders
    open_orders = fetch_open_orders(client)

    # 3. Filter to candidate orders
    candidate_orders = [o for o in open_orders if is_order_candidate(o)]
    logging.info("Candidate open orders: %d", len(candidate_orders))

    # 4. Identify fully shippable orders
    shippable_orders = []

    for order in candidate_orders:
        if order_is_fully_shippable(order, products, prod_to_committed_qty):
            shippable_orders.append({
                "order_name": order["name"],
                "created_at": order["createdAt"],
                "status": order["displayFulfillmentStatus"],
                "line_count": len(order["lineItems"]["edges"]),
                "note": order.get("note") or "",
            })

    logging.info("🚨 Fully shippable but unfulfilled orders: %d", len(shippable_orders))

    if args.dry_run:
        logging.info("Dry run — no CSV written.")
        return

    # 5. Write output
    today_et = datetime.now(ZoneInfo("America/New_York"))
    date_str = today_et.strftime("%Y%m%d")

    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)

    filename = out_dir / f"eod_fulfillment_audit_{date_str}.csv"
    write_csv(filename, shippable_orders)

    logging.info("✅ EOD Fulfillment Audit complete.")


if __name__ == "__main__":
    main()