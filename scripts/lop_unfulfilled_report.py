#!/usr/bin/env python3
"""
LOP Unfulfilled Orders Report

- Uses Shopify Admin GraphQL API (SHOP_URL, SHOPIFY_ACCESS_TOKEN, optional SHOPIFY_API_VERSION)
- Finds the most recent order tagged "LOP"
- From that order's createdAt → now, collects all orders that:
    - are UNFULFILLED or PARTIALLY_FULFILLED
    - require shipping
- Outputs a CSV with:
    Section A: Detailed rows: Order #, Product, SKU, QTY, Notes
    Section B: Summary rows: Product, SKU, Total QTY Needed
"""

import os
import sys
import csv
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
import argparse

from dotenv import load_dotenv
from pathlib import Path

# Ensure .env is loaded from the project root (one level above /scripts)
env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(env_path)

def parse_args():
    parser = argparse.ArgumentParser(description="Generate an unfulfilled LOP report.")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing CSV output.")
    return parser.parse_args()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class ShopifyClient:
    def __init__(self) -> None:
        shop_url = os.getenv("SHOP_URL")
        access_token = os.getenv("SHOPIFY_ACCESS_TOKEN")
        api_version = os.getenv("SHOPIFY_API_VERSION", "2025-01")

        if not shop_url or not access_token:
            raise RuntimeError(
                "SHOP_URL and SHOPIFY_ACCESS_TOKEN must be set in environment variables."
            )

        # Normalize shop_url; allow either bare domain or full https://
        if shop_url.startswith("http://") or shop_url.startswith("https://"):
            base_domain = shop_url.split("://", 1)[1].rstrip("/")
        else:
            base_domain = shop_url.rstrip("/")

        self.base_url = f"https://{base_domain}/admin/api/{api_version}/graphql.json"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-Shopify-Access-Token": access_token,
                "Content-Type": "application/json",
            }
        )

    def graphql(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"query": query, "variables": variables or {}}
        resp = self.session.post(self.base_url, json=payload, timeout=30)
        try:
            data = resp.json()
        except ValueError:
            logging.error("Non-JSON response from Shopify: %s", resp.text[:500])
            resp.raise_for_status()
            raise

        if resp.status_code != 200 or "errors" in data:
            logging.error("GraphQL error: status=%s errors=%s", resp.status_code, data.get("errors"))
            raise RuntimeError(f"Shopify GraphQL error: {data.get('errors')}")

        return data["data"]


# ------------------------ GraphQL Queries ------------------------ #

FIND_LOP_ORDER_QUERY = """
query FindMostRecentLopOrder($first: Int!, $after: String) {
  orders(
    first: $first
    after: $after
    sortKey: CREATED_AT
    reverse: true
  ) {
    edges {
      cursor
      node {
        id
        name
        createdAt
        tags
      }
    }
    pageInfo {
      hasNextPage
    }
  }
}
"""

ORDERS_SINCE_QUERY = """
query OrdersSinceLop(
  $first: Int!
  $after: String
  $query: String!
) {
  orders(
    first: $first
    after: $after
    sortKey: CREATED_AT
    reverse: false
    query: $query
  ) {
    edges {
      cursor
      node {
        id
        name
        createdAt
        cancelReason
        cancelledAt
        displayFulfillmentStatus
        requiresShipping
        note
        channel {
          handle
        }
        lineItems(first: 100) {
          edges {
            node {
              title
              quantity
              variant {
                sku
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

LINE_ITEMS_PAGINATION_QUERY = """
query OrderLineItemsMore($id: ID!, $first: Int!, $after: String) {
  order(id: $id) {
    lineItems(first: $first, after: $after) {
      edges {
        cursor
        node {
          title
          quantity
          variant {
            sku
          }
        }
      }
      pageInfo {
        hasNextPage
      }
    }
  }
}
"""


# ------------------------ Core Logic ------------------------ #

def find_most_recent_lop_order(client: ShopifyClient) -> Dict[str, Any]:
    """
    Page through orders newest → oldest until we find a tag "LOP".
    Returns the order node dict.
    Raises RuntimeError if none found.
    """
    logging.info("Searching for most recent order tagged 'LOP'...")
    after = None
    page_size = 50

    while True:
        data = client.graphql(
            FIND_LOP_ORDER_QUERY,
            {"first": page_size, "after": after},
        )

        orders = data["orders"]
        for edge in orders["edges"]:
            node = edge["node"]
            tags = node.get("tags", [])
            if "LOP" in tags:
                logging.info(
                    "Found LOP order: %s (createdAt=%s)",
                    node["name"],
                    node["createdAt"],
                )
                return node

        if not orders["pageInfo"]["hasNextPage"]:
            break

        # Move to the next page
        after = orders["edges"][-1]["cursor"]

    raise RuntimeError("No order with tag 'LOP' was found.")


def parse_iso_date(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def collect_line_items_with_pagination(client: ShopifyClient, order_node: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Ensure we have all line items for an order (in case > 100).
    Returns a list of {title, quantity, sku}.
    """
    line_items = []

    li_conn = order_node["lineItems"]
    for edge in li_conn["edges"]:
        li_node = edge["node"]
        line_items.append(
            {
                "title": li_node["title"],
                "quantity": li_node["quantity"],
                "sku": (li_node["variant"]["sku"] if li_node["variant"] else None),
            }
        )

    if not li_conn["pageInfo"]["hasNextPage"]:
        return line_items

    # Paginate further if needed
    order_id = order_node["id"]
    after = li_conn["edges"][-1]["cursor"]
    page_size = 100

    while True:
        data = client.graphql(
            LINE_ITEMS_PAGINATION_QUERY,
            {"id": order_id, "first": page_size, "after": after},
        )
        li_conn = data["order"]["lineItems"]
        for edge in li_conn["edges"]:
            li_node = edge["node"]
            line_items.append(
                {
                    "title": li_node["title"],
                    "quantity": li_node["quantity"],
                    "sku": (li_node["variant"]["sku"] if li_node["variant"] else None),
                }
            )

        if not li_conn["pageInfo"]["hasNextPage"]:
            break

        after = li_conn["edges"][-1]["cursor"]

    return line_items


def fetch_orders_since_lop(
    client: ShopifyClient,
    lop_created_at: str,
) -> List[Dict[str, Any]]:
    """
    Fetch all orders created at or after the LOP order's createdAt.
    We'll filter in Python for:
      - displayFulfillmentStatus in {UNFULFILLED, PARTIALLY_FULFILLED}
      - requiresShipping == True
      - not canceled
    """
    # Shopify order search query string; we use created_at lower bound, exclude canceled and refunded.
    # Example: created_at:>=2025-01-01T00:00:00Z AND -status:cancelled AND -financial_status:refunded
    query_str = f"created_at:>={lop_created_at} AND -status:cancelled AND -financial_status:refunded"

    logging.info("Fetching orders since LOP (createdAt >= %s)...", lop_created_at)

    after = None
    page_size = 50
    collected: List[Dict[str, Any]] = []

    while True:
        data = client.graphql(
            ORDERS_SINCE_QUERY,
            {"first": page_size, "after": after, "query": query_str},
        )
        orders_conn = data["orders"]
        for edge in orders_conn["edges"]:
            node = edge["node"]
            collected.append(node)

        if not orders_conn["pageInfo"]["hasNextPage"]:
            break

        after = orders_conn["edges"][-1]["cursor"]

    logging.info("Fetched %d orders created from LOP onward.", len(collected))
    return collected


def filter_orders_requiring_shipping(orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Keep only orders that:
      - requireShipping == True
      - displayFulfillmentStatus in {"UNFULFILLED", "PARTIALLY_FULFILLED"}
      - not canceled
    """
    qualifying = []
    for o in orders:
        if o.get("cancelledAt"):
            continue

        if not o.get("requiresShipping", False):
            continue

        status = o.get("displayFulfillmentStatus")
        if status not in ("UNFULFILLED", "PARTIALLY_FULFILLED"):
            continue

        qualifying.append(o)

    logging.info("Filtered to %d orders requiring shipping and not fulfilled.", len(qualifying))
    return qualifying


def build_csv_rows(client: ShopifyClient, orders: List[Dict[str, Any]]) -> Tuple[List[List[Any]], List[List[Any]]]:
    """
    Returns:
      - detail_rows for Section A
      - summary_rows for Section B
    Each detail row: [Order #, Product, SKU, QTY, Notes]
    """
    detail_rows: List[List[Any]] = []
    summary_agg: Dict[Tuple[str, str], int] = {}

    for order in orders:
        order_name = order.get("name")
        note = order.get("note") or ""
        line_items = collect_line_items_with_pagination(client, order)

        for li in line_items:
            product_title = li["title"]
            qty = li["quantity"]
            sku = li.get("sku") or ""

            detail_rows.append(
                [order_name, product_title, sku, qty, note]
            )

            key = (product_title, sku)
            summary_agg[key] = summary_agg.get(key, 0) + qty

    # Build summary rows sorted by product title then SKU
    summary_rows: List[List[Any]] = []
    for (product_title, sku), total_qty in sorted(summary_agg.items(), key=lambda x: (x[0][0], x[0][1])):
        summary_rows.append([product_title, sku, total_qty])

    return detail_rows, summary_rows


def write_report_csv(
    detail_rows: List[List[Any]],
    summary_rows: List[List[Any]],
    output_path: str,
) -> None:
    """
    Write a CSV with two sections:
      Section A: headers + detail rows
      (blank line)
      Section B: headers + summary rows
    """
    logging.info("Writing CSV report to %s", output_path)
    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Section A header
        writer.writerow(["Order #", "Product", "SKU", "QTY", "Notes"])
        for row in detail_rows:
            writer.writerow(row)

        # Blank separator row
        writer.writerow([])

        # Section B header
        writer.writerow(["Product", "SKU", "Total QTY Needed"])
        for row in summary_rows:
            writer.writerow(row)


def main() -> None:
    args = parse_args()
    try:
        client = ShopifyClient()
    except RuntimeError as e:
        logging.error(str(e))
        sys.exit(1)

    # 1) Find most recent LOP order
    lop_order = find_most_recent_lop_order(client)
    lop_created_at = lop_order["createdAt"]

    # 2) Fetch orders since LOP createdAt
    orders_since = fetch_orders_since_lop(client, lop_created_at)

    # 3) Filter for orders requiring shipping and unfulfilled/partially fulfilled
    qualifying_orders = filter_orders_requiring_shipping(orders_since)

    if not qualifying_orders:
        logging.info("No qualifying unfulfilled shipping orders found since LOP.")
        return

    # 4) Build CSV rows
    detail_rows, summary_rows = build_csv_rows(client, qualifying_orders)

    if args.dry_run:
        logging.info("Dry run enabled — skipping CSV write.")
        return

    # 5) Write CSV
    today_str = datetime.utcnow().strftime("%Y%m%d")
    output_path = f"lop_unfulfilled_orders_report_{today_str}.csv"
    write_report_csv(detail_rows, summary_rows, output_path)

    logging.info("Report generation complete.")


if __name__ == "__main__":
    main()