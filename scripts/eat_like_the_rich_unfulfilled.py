#!/usr/bin/env python3
"""
Eat (Like) the Rich — Unfulfilled Order Breakdown

Counts UNFULFILLED demand for one title and buckets it three ways:

  1. SINGLE COPY      — order contains this book only, 1 unfulfilled copy
  2. MULTIPLE COPIES  — order contains this book only, 2+ unfulfilled copies
                        (broken out by copies-per-order)
  3. COMBINED         — order contains this book plus other unfulfilled items

Only counts orders that are open, not cancelled, and whose fulfillment status
is UNFULFILLED or PARTIALLY_FULFILLED. Within those, only line items with
unfulfilledQuantity > 0 count — so a partially shipped order where this title
already went out is correctly ignored.

Auth is handled by scripts/shopify_client.py (client credentials grant).

Usage:
    python scripts/eat_like_the_rich_unfulfilled.py
    python scripts/eat_like_the_rich_unfulfilled.py --list-orders
    python scripts/eat_like_the_rich_unfulfilled.py --csv out/eltr_unfulfilled.csv
    python scripts/eat_like_the_rich_unfulfilled.py --require-shipping
"""

import sys
import csv
import argparse
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

from shopify_client import ShopifyClient, ShopifyAuthError


# ------------------------------------------------------------------ #
# Target title
# ------------------------------------------------------------------ #

PRODUCT_ID = "7251975274629"
PRODUCT_GID = f"gid://shopify/Product/{PRODUCT_ID}"
ISBN = "9780593837320"
TITLE_LABEL = "Eat (Like) the Rich"


env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# ------------------------------------------------------------------ #
# GraphQL
# ------------------------------------------------------------------ #

OPEN_ORDERS_QUERY = """
query OpenOrders($first: Int!, $after: String, $query: String!) {
  orders(first: $first, after: $after, sortKey: CREATED_AT, reverse: false, query: $query) {
    edges {
      cursor
      node {
        id
        name
        createdAt
        displayFulfillmentStatus
        requiresShipping
        cancelledAt
        lineItems(first: 100) {
          edges {
            node {
              id
              title
              quantity
              unfulfilledQuantity
              variant {
                barcode
                product { id title }
              }
            }
          }
          pageInfo { hasNextPage }
        }
      }
    }
    pageInfo { hasNextPage }
  }
}
"""

LINE_ITEMS_PAGE_QUERY = """
query OrderLineItems($id: ID!, $first: Int!, $after: String) {
  order(id: $id) {
    lineItems(first: $first, after: $after) {
      edges {
        cursor
        node {
          id
          title
          quantity
          unfulfilledQuantity
          variant {
            barcode
            product { id title }
          }
        }
      }
      pageInfo { hasNextPage }
    }
  }
}
"""


# ------------------------------------------------------------------ #
# Fetch
# ------------------------------------------------------------------ #

def fetch_open_orders(client: ShopifyClient) -> List[Dict[str, Any]]:
    """Page through all open, non-cancelled orders."""
    query_str = "status:open AND -status:cancelled"
    after = None
    collected: List[Dict[str, Any]] = []

    while True:
        data = client.graphql(
            OPEN_ORDERS_QUERY,
            {"first": 50, "after": after, "query": query_str},
        )
        conn = data["orders"]
        edges = conn["edges"]
        collected.extend(e["node"] for e in edges)

        if not conn["pageInfo"]["hasNextPage"] or not edges:
            break
        after = edges[-1]["cursor"]

    logging.info("Fetched %d open orders.", len(collected))
    return collected


def all_line_items(client: ShopifyClient, order: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return every line item on the order, paginating past the first 100 if needed."""
    edges = order["lineItems"]["edges"]
    items = [e["node"] for e in edges]

    if not order["lineItems"]["pageInfo"]["hasNextPage"]:
        return items

    after = edges[-1].get("cursor")
    while True:
        data = client.graphql(
            LINE_ITEMS_PAGE_QUERY,
            {"id": order["id"], "first": 100, "after": after},
        )
        conn = data["order"]["lineItems"]
        page_edges = conn["edges"]
        items.extend(e["node"] for e in page_edges)

        if not conn["pageInfo"]["hasNextPage"] or not page_edges:
            break
        after = page_edges[-1]["cursor"]

    return items


# ------------------------------------------------------------------ #
# Matching + classification
# ------------------------------------------------------------------ #

def is_target(line_item: Dict[str, Any]) -> bool:
    """Match on product ID first; fall back to variant barcode (ISBN)."""
    variant = line_item.get("variant") or {}
    product = variant.get("product") or {}
    pid = product.get("id") or ""

    if pid == PRODUCT_GID or pid.rsplit("/", 1)[-1] == PRODUCT_ID:
        return True

    barcode = (variant.get("barcode") or "").strip()
    return bool(barcode) and barcode == ISBN


def unfulfilled_qty(line_item: Dict[str, Any]) -> int:
    q = line_item.get("unfulfilledQuantity")
    if q is None:
        q = line_item.get("quantity") or 0
    return int(q)


def is_candidate(order: Dict[str, Any], require_shipping: bool) -> bool:
    if order.get("cancelledAt"):
        return False
    if order.get("displayFulfillmentStatus") not in ("UNFULFILLED", "PARTIALLY_FULFILLED"):
        return False
    if require_shipping and not order.get("requiresShipping"):
        return False
    return True


def classify(client: ShopifyClient, orders: List[Dict[str, Any]], require_shipping: bool):
    """
    Returns:
      single_copy -> list of order records
      multi_copy  -> {copies: [order records]}
      combined    -> list of order records (this title + other unfulfilled items)
    """
    single_copy: List[Dict[str, Any]] = []
    multi_copy: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    combined: List[Dict[str, Any]] = []

    for order in orders:
        if not is_candidate(order, require_shipping):
            continue

        items = all_line_items(client, order)

        target_qty = 0
        other_titles: List[str] = []
        other_qty = 0

        for li in items:
            qty = unfulfilled_qty(li)
            if qty <= 0:
                continue
            if is_target(li):
                target_qty += qty
            else:
                other_titles.append(li.get("title") or "(untitled)")
                other_qty += qty

        if target_qty <= 0:
            continue

        record = {
            "order": order.get("name"),
            "created_at": order.get("createdAt"),
            "status": order.get("displayFulfillmentStatus"),
            "copies": target_qty,
            "other_item_count": len(other_titles),
            "other_unit_count": other_qty,
            "other_titles": other_titles,
        }

        if other_titles:
            combined.append(record)
        elif target_qty == 1:
            single_copy.append(record)
        else:
            multi_copy[target_qty].append(record)

    return single_copy, multi_copy, combined


# ------------------------------------------------------------------ #
# Output
# ------------------------------------------------------------------ #

def print_report(single_copy, multi_copy, combined, list_orders: bool) -> None:
    single_orders = len(single_copy)
    single_units = single_orders

    multi_orders = sum(len(v) for v in multi_copy.values())
    multi_units = sum(copies * len(v) for copies, v in multi_copy.items())

    combined_orders = len(combined)
    combined_units = sum(r["copies"] for r in combined)

    bar = "=" * 62

    print()
    print(bar)
    print(f" UNFULFILLED ORDERS — {TITLE_LABEL}")
    print(f" Product {PRODUCT_ID} · ISBN {ISBN}")
    print(bar)

    print("\n1. SINGLE COPY (this title only, 1 copy)")
    print(f"   Orders: {single_orders}")
    if list_orders and single_copy:
        for r in sorted(single_copy, key=lambda x: x["created_at"]):
            print(f"     {r['order']}  {r['created_at'][:10]}")

    print("\n2. MULTIPLE COPIES (this title only, 2+ copies)")
    if not multi_copy:
        print("   Orders: 0")
    else:
        print(f"   Orders: {multi_orders}   Copies: {multi_units}")
        print()
        print("   Copies/order   Orders   Copies")
        print("   ------------   ------   ------")
        for copies in sorted(multi_copy):
            n = len(multi_copy[copies])
            print(f"   {copies:>12}   {n:>6}   {copies * n:>6}")
            if list_orders:
                for r in sorted(multi_copy[copies], key=lambda x: x["created_at"]):
                    print(f"       {r['order']}  {r['created_at'][:10]}")

    print("\n3. COMBINED WITH OTHER TITLES")
    print(f"   Orders: {combined_orders}   Copies of this title: {combined_units}")
    if list_orders and combined:
        print()
        for r in sorted(combined, key=lambda x: x["created_at"]):
            others = ", ".join(r["other_titles"][:3])
            if len(r["other_titles"]) > 3:
                others += f", +{len(r['other_titles']) - 3} more"
            print(f"     {r['order']}  {r['created_at'][:10]}  "
                  f"copies={r['copies']}  with: {others}")

    print("\n" + "-" * 62)
    print(f" TOTAL unfulfilled orders containing this title: "
          f"{single_orders + multi_orders + combined_orders}")
    print(f" TOTAL unfulfilled copies of this title:         "
          f"{single_units + multi_units + combined_units}")
    print("-" * 62 + "\n")


def write_csv(single_copy, multi_copy, combined, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([f"UNFULFILLED — {TITLE_LABEL} — product {PRODUCT_ID} — ISBN {ISBN}"])
        w.writerow([])
        w.writerow(["Bucket", "Order #", "Created", "Fulfillment Status",
                    "Copies", "Other Titles In Order"])

        for r in sorted(single_copy, key=lambda x: x["created_at"]):
            w.writerow(["Single copy", r["order"], r["created_at"], r["status"], r["copies"], ""])

        for copies in sorted(multi_copy):
            for r in sorted(multi_copy[copies], key=lambda x: x["created_at"]):
                w.writerow([f"Multi copy ({copies})", r["order"], r["created_at"],
                            r["status"], r["copies"], ""])

        for r in sorted(combined, key=lambda x: x["created_at"]):
            w.writerow(["Combined", r["order"], r["created_at"], r["status"],
                        r["copies"], "; ".join(r["other_titles"])])

    logging.info("Wrote CSV to %s", path)


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

def parse_args():
    p = argparse.ArgumentParser(
        description=f"Unfulfilled order breakdown for {TITLE_LABEL}."
    )
    p.add_argument("--list-orders", action="store_true",
                   help="Print individual order numbers in each bucket.")
    p.add_argument("--csv", metavar="PATH", default=None,
                   help="Also write results to a CSV at PATH.")
    p.add_argument("--require-shipping", action="store_true",
                   help="Exclude pickup-only / digital orders (requiresShipping=false).")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    try:
        client = ShopifyClient()
        client.validate_connection()
    except ShopifyAuthError as e:
        logging.error("Auth failed: %s", e)
        sys.exit(1)
    except RuntimeError as e:
        logging.error(str(e))
        sys.exit(1)

    orders = fetch_open_orders(client)
    single_copy, multi_copy, combined = classify(client, orders, args.require_shipping)

    print_report(single_copy, multi_copy, combined, args.list_orders)

    if args.csv:
        write_csv(single_copy, multi_copy, combined, args.csv)


if __name__ == "__main__":
    main()