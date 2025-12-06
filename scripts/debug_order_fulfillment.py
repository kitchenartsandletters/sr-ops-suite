#!/usr/bin/env python3
import os
from dotenv import load_dotenv
from lop_unfulfilled_report import ShopifyClient

load_dotenv()

DEBUG_QUERY = """
query DebugOrder($name: String!) {
  orders(first: 1, query: $name) {
    edges {
      node {
        id
        name
        displayFinancialStatus
        displayFulfillmentStatus
        cancelledAt

        lineItems(first: 50) {
          edges {
            node {
              title
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

        fulfillments {
          id
          status
          createdAt
          fulfillmentLineItems(first: 50) {
            nodes {
              id
              quantity
              lineItem {
                title
                quantity
              }
            }
          }
        }

        fulfillmentOrders(first: 20) {
          nodes {
            id
            status
            lineItems(first: 50) {
              nodes {
                id
                totalQuantity
                remainingQuantity
                lineItem {
                  title
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
"""

def inspect_order(order_name: str):
    client = ShopifyClient()
    variables = {"name": order_name}
    data = client.graphql(DEBUG_QUERY, variables)
    print("\n==============================")
    print(f"ORDER {order_name}")
    print("==============================")

    try:
        order = data["orders"]["edges"][0]["node"]
    except:
        print("⚠️  Order not found via GraphQL")
        return

    print("\n--- BASIC INFO ---")
    print("ID:", order["id"])
    print("Financial:", order.get("displayFinancialStatus"))
    print("Fulfillment:", order.get("displayFulfillmentStatus"))
    print("Canceled:", order["cancelledAt"])

    print("\n--- LINE ITEMS ---")
    for e in order["lineItems"]["edges"]:
        li = e["node"]
        print(f"• {li['title']}  qty={li['quantity']}")

    print("\n--- FULFILLMENTS (legacy) ---")
    fulfillments_list = order.get("fulfillments") or []
    for f in fulfillments_list:
        print(" Fulfillment:", f.get("status"), "created:", f.get("createdAt"))
        fli_conn = f.get("fulfillmentLineItems") or {}
        for fli in fli_conn.get("nodes", []):
            line = fli.get("lineItem") or {}
            print("   -", line.get("title"), "qty=", fli.get("quantity"))

    print("\n--- FULFILLMENT ORDERS (FOs) ---")
    fo_conn = order.get("fulfillmentOrders") or {}
    for fo in fo_conn.get("nodes", []):
        print(" FO Status:", fo.get("status"))
        li_conn = fo.get("lineItems") or {}
        for ln in li_conn.get("nodes", []):
            li_line = ln.get("lineItem") or {}
            print(
                f"   • {li_line.get('title')}  "
                f"total={ln.get('totalQuantity')}  "
                f"remaining={ln.get('remainingQuantity')}"
            )


if __name__ == "__main__":
    orders = ["69396", "68178", "58744", "50111"]
    for o in orders:
        inspect_order(o)