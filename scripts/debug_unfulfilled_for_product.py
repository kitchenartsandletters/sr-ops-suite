#!/usr/bin/env python3
"""
Single‑Order & Single‑Product Inspector
--------------------------------------

This script pulls ONE order and inspects ONE product inside that order.

Usage:
    python scripts/debug_unfulfilled_for_product.py \
        gid://shopify/Order/5678470889605 \
        gid://shopify/Product/5238828302469
"""

import sys
import json
from lop_unfulfilled_report import ShopifyClient


# ------------------------------
# GraphQL Query for Single Order
# ------------------------------
ORDER_QUERY = """
query GetOrder($id: ID!) {
  order(id: $id) {
    id
    name
    createdAt
    displayFinancialStatus
    displayFulfillmentStatus

    lineItems(first: 50) {
      nodes {
        id
        quantity
        name
        sku
        product {
          id
          title
        }
        variant { id title }
      }
    }

    fulfillmentOrders(first: 50) {
      nodes {
        id
        status
        requestStatus

        lineItems(first: 50) {
          nodes {
            id
            totalQuantity
            remainingQuantity
            lineItem {
              id
              product { id title }
            }
          }
        }
      }
    }
  }
}
"""


def extract_numeric(gid: str) -> str:
    """Extract the numeric ID from a Shopify GID."""
    if gid.startswith("gid://shopify/"):
        return gid.split("/")[-1]
    return gid


# ------------------------------------------------
# MAIN INSPECTOR — ONLY FOR ONE ORDER + ONE PRODUCT
# ------------------------------------------------
def inspect(order_gid: str, product_gid: str):
    client = ShopifyClient()

    print(f"\n=== INSPECTING ORDER ===\n{order_gid}\n")
    data = client.graphql(ORDER_QUERY, {"id": order_gid})

    order = data.get("order")
    if not order:
        print("❌ Order not found.")
        return

    # Basic order-level metadata
    print("Order Info:")
    print(f"  Name: {order.get('name')}")
    print(f"  Financial Status: {order.get('displayFinancialStatus')}")
    print(f"  Fulfillment Status: {order.get('displayFulfillmentStatus')}")
    print(f"  Canceled At: {order.get('canceledAt')}")
    print()

    numeric_pid = extract_numeric(product_gid)

    # -----------------------------------------
    # LINE ITEMS — Locate the product in the order
    # -----------------------------------------
    print("Line Items:")
    li_nodes = order["lineItems"]["nodes"]
    li_for_product = []

    for li in li_nodes:
        prod = li.get("product")
        pid = prod["id"].split("/")[-1] if prod else None

        is_match = pid == numeric_pid

        print(f"- {li['name']}  qty={li['quantity']}  (product_id={pid})  MATCH={is_match}")

        if is_match:
            li_for_product.append(li)

    if not li_for_product:
        print("\n❌ Product does NOT appear in this order.")
    else:
        print("\n✅ Product appears in this order.")

    print("\n------------------------------------------")
    print("FULFILLMENT ORDERS — Checking remaining qty")
    print("------------------------------------------\n")

    fo_nodes = order["fulfillmentOrders"]["nodes"]
    total_remaining = 0

    for fo in fo_nodes:
        print(f"FO {fo['id']}: status={fo['status']}  requestStatus={fo.get('requestStatus')}")
        for item in fo["lineItems"]["nodes"]:

            # Attempt to identify the product inside the FO LI
            li = item.get("lineItem")
            pid = None
            if li and li.get("product"):
                pid = li["product"]["id"].split("/")[-1]

            if pid == numeric_pid:
                rm = item.get("remainingQuantity")
                tq = item.get("totalQuantity")
                print(f"  → MATCH lineItem {item['id']} total={tq} remaining={rm}")
                if rm is not None:
                    total_remaining += rm
            else:
                print(f"    lineItem {item['id']} (product={pid})")

        print()

    print("======================================")
    print(" UNFULFILLED SUMMARY FOR PRODUCT")
    print("======================================")
    print(f"Product ID: {product_gid}")
    print(f"Order ID:   {order_gid}")
    print(f"Total Remaining (FO-based): {total_remaining}")
    print("======================================\n")

    if total_remaining > 0:
        print("✅ This order SHOULD contribute to Unfulfilled Qty.")
    else:
        print("❌ This order contributes 0 unfulfilled quantity.")
    print()


# ----------------------
# CLI ENTRY
# ----------------------
if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage:")
        print("  python scripts/debug_unfulfilled_for_product.py <order_gid> <product_gid>")
        sys.exit(1)

    order_gid = sys.argv[1]
    product_gid = sys.argv[2]

    inspect(order_gid, product_gid)
