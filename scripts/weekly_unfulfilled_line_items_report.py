#!/usr/bin/env python3
"""
Weekly Unfulfilled Line Items (Age / Order Date Companion Report)

Goal:
- Add ORDER DATE context to the committed-inventory model without relying on FulfillmentOrders logic.
- Show ONLY unfulfilled line items (no fulfilled items from mixed-status orders).
- Keep canonical "unfulfilled qty" = committed inventory (InventoryLevel.quantities["committed"]).

Stages (aligned to your plan):
- Stage 0: default sweep = last 60 days (extendable to full sweep later)
- Stage 1: strict UTC window in query + strict post-filtering + drift logging
- Stage 2: line-item view contains ONLY unfulfilled line items (unfulfilledQuantity > 0)
- Stage 3: Option A (lean output; no extra fulfilled noise)
- Stage 4: stable risk logic aligned with committed model

Outputs:
1) LINE ITEM VIEW CSV (only unfulfilled line items)
2) PRODUCT SUMMARY CSV (risk-focused: inventory <= 0, committed > 0, NOT in Preorder collection)
"""

import os
import csv
import logging
import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

# Reuse your existing ShopifyClient (same as your other scripts)
from lop_unfulfilled_report import ShopifyClient


# ──────────────────────────────────────────────────────────────────────────────
# Args
# ──────────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Weekly unfulfilled line items report (committed-inventory canonical).")
    p.add_argument("--days", type=int, default=180, help="Lookback window in days (default: 180).")
    p.add_argument("--since", type=str, default=None, help="Override start time (UTC) ISO8601, e.g. 2025-12-01T00:00:00Z.")
    p.add_argument("--until", type=str, default=None, help="Override end time (UTC) ISO8601, e.g. 2025-12-08T00:00:00Z.")
    p.add_argument("--output-dir", type=str, default="output", help="Output directory (default: output/).")
    p.add_argument("--dry-run", action="store_true", help="Run without writing CSVs.")
    p.add_argument("--page-size", type=int, default=100, help="Orders page size (default: 100).")
    p.add_argument("--line-items-first", type=int, default=100, help="Line items per order (default: 100).")
    p.add_argument("--max-orders", type=int, default=None, help="Optional safety cap on total orders processed.")
    p.add_argument("--full-sweep", action="store_true", help="Bypass day window and fetch all available history (capped safely).")
    p.add_argument("--cap-days", type=int, default=365, help="Maximum lookback cap in days when using full sweep (default: 365).")
    p.add_argument("--sla-days", type=int, default=30, help="SLA threshold in days for aging flag (default: 30).")
    return p.parse_args()


# ──────────────────────────────────────────────────────────────────────────────
# GraphQL queries
# ──────────────────────────────────────────────────────────────────────────────

# NOTE:
# - We query orders in a UTC time window using processed_at.
# - We use fulfillment_status:unfulfilled to narrow to orders with any unfulfilled items.
# - We still post-filter line items to ONLY unfulfilledQuantity > 0.
ORDERS_QUERY = """
query Orders($first: Int!, $after: String, $query: String!, $lineItemsFirst: Int!) {
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
        displayFulfillmentStatus
        displayFinancialStatus
        lineItems(first: $lineItemsFirst) {
          nodes {
            id
            title
            sku
            vendor
            quantity
            unfulfilledQuantity
            fulfillmentStatus
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
                vendor
                totalInventory
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

# We fetch product details + committed inventory per product, using nodes(ids: ...) in batches
# to minimize query count. We keep it small: title/vendor/totalInventory/collections + variants
# → inventoryLevels quantities(committed).
PRODUCTS_BY_ID_QUERY = """
query ProductsById($ids: [ID!]!) {
  nodes(ids: $ids) {
    __typename
    ... on Product {
      id
      title
      vendor
      totalInventory
      collections(first: 10) {
        nodes { title }
      }
      variants(first: 50) {
        nodes {
          id
          inventoryItem {
            id
            inventoryLevels(first: 10) {
              nodes {
                id
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
}
"""


# ──────────────────────────────────────────────────────────────────────────────
# Data models
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class UnfulfilledLineRow:
    order_id: str
    order_name: str
    processed_at_utc: datetime

    product_id: str
    product_title: str
    product_vendor: str

    variant_id: Optional[str]
    isbn: str
    author: str  # derived from SKU (consistent with your other reports)

    qty_ordered: int
    qty_unfulfilled: int

    notes: str
    attributes: str  # e.g. Signed, Bookplate, Preorder, Backorder (derived downstream)

@dataclass
class ProductSnapshot:
    product_id: str
    title: str
    vendor: str
    total_inventory: Optional[int]
    collections: List[str]
    committed: int  # canonical unfulfilled
    is_preorder: bool


# ──────────────────────────────────────────────────────────────────────────────
# Helpers: time parsing + query building
# ──────────────────────────────────────────────────────────────────────────────

def parse_utc_iso8601(s: str) -> datetime:
    """
    Parse '2025-12-01T00:00:00Z' into aware UTC datetime.
    """
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

# ──────────────────────────────────────────────────────────────────────────────
# ET display helper
# ──────────────────────────────────────────────────────────────────────────────
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")

def utc_to_et_str(dt: datetime) -> str:
    return dt.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S")

def utc_window_from_args(days: int, since: Optional[str], until: Optional[str], full_sweep: bool = False, cap_days: int = 365) -> Tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)

    if since:
        start = parse_utc_iso8601(since)
    elif full_sweep:
        # full sweep uses capped rolling window
        start = now - timedelta(days=cap_days)
    else:
        start = now - timedelta(days=days)

    if until:
        end = parse_utc_iso8601(until)
    else:
        end = now

    if end < start:
        start, end = end, start

    return start, end

def build_orders_query_filter(start_utc: datetime, end_utc: datetime) -> str:
    """
    Keep the server-side filter strict and stable.
    We still post-filter any stragglers by processedAt.
    """
    # Shopify search uses processed_at in ISO8601. We pass UTC timestamps.
    # fulfillment_status:unfulfilled narrows to orders with any unfulfilled items.
    return (
        f"financial_status:paid "
        f"-financial_status:refunded "
        f"fulfillment_status:unfulfilled "
        f"processed_at:>={start_utc.isoformat()} "
        f"processed_at:<={end_utc.isoformat()}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Fetch: orders (pagination) and extract ONLY unfulfilled line items
# ──────────────────────────────────────────────────────────────────────────────

def fetch_unfulfilled_line_items(
    client: ShopifyClient,
    start_utc: datetime,
    end_utc: datetime,
    page_size: int,
    line_items_first: int,
    max_orders: Optional[int] = None,
) -> Tuple[List[UnfulfilledLineRow], List[str]]:
    """
    Returns:
      - rows: ONLY line items where unfulfilledQuantity > 0 AND processedAt within [start_utc, end_utc]
      - product_ids: unique product ids referenced by those line items
    """
    q_filter = build_orders_query_filter(start_utc, end_utc)

    rows: List[UnfulfilledLineRow] = []
    product_ids: set[str] = set()

    after = None
    total_orders_seen = 0
    total_orders_in_window = 0
    total_line_items_kept = 0
    drift_rejected_out_of_window = 0

    while True:
        variables = {
            "first": page_size,
            "after": after,
            "query": q_filter,
            "lineItemsFirst": line_items_first,
        }

        data = client.graphql(ORDERS_QUERY, variables)
        if not data:
            break

        edges = data["orders"]["edges"]
        if not edges:
            break

        for edge in edges:
            node = edge["node"]
            total_orders_seen += 1
            if max_orders and total_orders_seen > max_orders:
                logging.warning("Max orders cap reached (%s). Stopping early.", max_orders)
                return rows, sorted(product_ids)

            processed_at = parse_utc_iso8601(node["processedAt"]).astimezone(timezone.utc)

            # STRICT post-filter (non-negotiable)
            if processed_at < start_utc or processed_at > end_utc:
                drift_rejected_out_of_window += 1
                continue

            total_orders_in_window += 1

            for li in node.get("lineItems", {}).get("nodes", []) or []:
                unfulfilled_qty = li.get("unfulfilledQuantity") or 0
                if unfulfilled_qty <= 0:
                    continue  # Stage 2: exclude fulfilled line items

                variant = li.get("variant") or {}
                product = (variant.get("product") or {})
                # Skip Preorder products (align with weekly_maintenance_report logic)
                # Preorder detection will be enforced later using product snapshots,
                # but we prevent obvious noise early.
                # (Final authoritative filter happens after snapshot join.)

                pid = product.get("id")
                if not pid:
                    continue

                # Notes: keep raw notes; attributes logic is derived later
                notes = ""
                ca = li.get("customAttributes") or []
                if ca:
                    # preserve a small, readable notes string (not inference)
                    # (If you later want "Notes" to come from actual note fields, swap here.)
                    notes = "; ".join([f"{x.get('key')}={x.get('value')}" for x in ca if x.get("key")])

                row = UnfulfilledLineRow(
                    order_id=node["id"],
                    order_name=node.get("name") or "",
                    processed_at_utc=processed_at,

                    product_id=pid,
                    product_title=product.get("title") or li.get("title") or "",
                    product_vendor=product.get("vendor") or li.get("vendor") or "",

                    variant_id=variant.get("id"),
                    isbn=(variant.get("barcode") or "").strip() or "NO BARCODE",
                    author=(variant.get("sku") or li.get("sku") or "").strip(),

                    qty_ordered=int(li.get("quantity") or 0),
                    qty_unfulfilled=int(unfulfilled_qty),

                    notes=notes,
                    attributes="",  # filled later (Phase)
                )

                rows.append(row)
                product_ids.add(pid)
                total_line_items_kept += 1

        if not data["orders"]["pageInfo"]["hasNextPage"]:
            break

        after = edges[-1]["cursor"]

    logging.info("Orders seen (server filtered): %d", total_orders_seen)
    logging.info("Orders accepted (strict UTC post-filter): %d", total_orders_in_window)
    logging.info("Orders rejected (out of window drift): %d", drift_rejected_out_of_window)
    logging.info("Unfulfilled line items kept: %d", total_line_items_kept)

    return rows, sorted(product_ids)


# ──────────────────────────────────────────────────────────────────────────────
# Fetch: product snapshots + committed quantities (canonical)
# ──────────────────────────────────────────────────────────────────────────────

def chunked(xs: List[str], n: int) -> List[List[str]]:
    return [xs[i:i+n] for i in range(0, len(xs), n)]

def build_product_snapshots(
    client: ShopifyClient,
    product_ids: List[str],
    cache: Optional[Dict[str, ProductSnapshot]] = None,
    batch_size: int = 25,
) -> Dict[str, ProductSnapshot]:
    """
    Fetch product snapshots in batches using nodes(ids: ...).
    Computes committed by summing all committed quantities across variants+locations.
    """
    cache = cache or {}
    needed = [pid for pid in product_ids if pid not in cache]

    for batch in chunked(needed, batch_size):
        data = client.graphql(PRODUCTS_BY_ID_QUERY, {"ids": batch})
        nodes = (data or {}).get("nodes") or []

        for node in nodes:
            if not node or node.get("__typename") != "Product":
                continue

            pid = node["id"]
            title = node.get("title") or ""
            vendor = node.get("vendor") or ""
            total_inv = node.get("totalInventory")

            collections = [c.get("title") for c in (node.get("collections", {}).get("nodes") or []) if c.get("title")]
            is_preorder = any("Preorder" in (c or "") for c in collections)  # matches your daily_sales_report convention

            committed_total = 0
            for v in (node.get("variants", {}).get("nodes") or []):
                inv_item = (v.get("inventoryItem") or {})
                for lvl in (inv_item.get("inventoryLevels", {}).get("nodes") or []):
                    for q in (lvl.get("quantities") or []):
                        if q.get("name") == "committed":
                            committed_total += int(q.get("quantity") or 0)

            cache[pid] = ProductSnapshot(
                product_id=pid,
                title=title,
                vendor=vendor,
                total_inventory=total_inv,
                collections=collections,
                committed=committed_total,
                is_preorder=is_preorder,
            )

    logging.info("Product snapshots cached: %d", len(cache))
    return cache


# ──────────────────────────────────────────────────────────────────────────────
# Risk logic (committed model) + attributes derivation (no FO inference)
# ──────────────────────────────────────────────────────────────────────────────

def derive_attributes_for_line(
    row: UnfulfilledLineRow,
    product: ProductSnapshot,
) -> str:
    """
    Canonical status for this report:
      - We only include line items where qty_unfulfilled > 0.
      - Preorder products are filtered out elsewhere.
      - If inventory is negative -> backorder
      - Otherwise -> pending_fulfillment
    """
    if product.is_preorder:
        return ""

    # Defensive: if total inventory is missing, don't label.
    if product.total_inventory is None:
        return ""

    if product.total_inventory < 0:
        return "backorder"

    return "pending_fulfillment"

def is_risk_product(product: ProductSnapshot) -> bool:
    """
    Canonical committed model:
    - committed > 0 (unfulfilled exists)
    - totalInventory <= 0 (cannot fulfill cleanly from available)
    - not preorder (preorders are handled elsewhere)
    """
    if product.is_preorder:
        return False
    if (product.total_inventory is None):
        return False
    if product.committed <= 0:
        return False
    return product.total_inventory <= 0


# ──────────────────────────────────────────────────────────────────────────────
# Join logic
# ──────────────────────────────────────────────────────────────────────────────

def attach_attributes_and_vendor(
    rows: List[UnfulfilledLineRow],
    products: Dict[str, ProductSnapshot],
) -> List[UnfulfilledLineRow]:
    out: List[UnfulfilledLineRow] = []
    for r in rows:
        p = products.get(r.product_id)
        if not p:
            continue

        # Exclude Preorder products entirely
        if p.is_preorder:
            continue

        r.product_title = p.title or r.product_title
        r.product_vendor = p.vendor or r.product_vendor
        r.attributes = derive_attributes_for_line(r, p)

        out.append(r)
    return out

def compute_product_age_summary(
    rows: List[UnfulfilledLineRow],
    products: Dict[str, ProductSnapshot],
) -> List[Dict[str, Any]]:
    """
    Product summary rows (risk-focused):
    - Includes earliest/latest unfulfilled order date (from line-item view),
      but inclusion is decided by committed model (ProductSnapshot).
    """
    # index line items by product
    by_pid: Dict[str, List[UnfulfilledLineRow]] = {}
    for r in rows:
        by_pid.setdefault(r.product_id, []).append(r)

    summaries: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    for pid, plist in by_pid.items():
        p = products.get(pid)
        if not p:
            continue
        if not is_risk_product(p):
            continue

        earliest = min(x.processed_at_utc for x in plist)
        latest = max(x.processed_at_utc for x in plist)
        age_days = (now - earliest).days

        if age_days <= 7:
            age_bucket = "0-7"
        elif age_days <= 14:
            age_bucket = "8-14"
        elif age_days <= 30:
            age_bucket = "15-30"
        elif age_days <= 60:
            age_bucket = "31-60"
        else:
            age_bucket = "60+"

        # Heatmap intensity (visual cue column)
        if age_days <= 7:
            heatmap = "🟢"
        elif age_days <= 14:
            heatmap = "🟡"
        elif age_days <= 30:
            heatmap = "🟠"
        else:
            heatmap = "🔴"

        sla_breach = age_days >= getattr(__import__("__main__"), "SLA_THRESHOLD_DAYS", 30)

        summaries.append({
            "product_id": pid,
            "title": p.title,
            "vendor": p.vendor,
            "collections": ", ".join(p.collections),
            "total_inventory": p.total_inventory,
            "committed": p.committed,
            "earliest_order_utc": earliest.isoformat(),
            "latest_order_utc": latest.isoformat(),
            "age_days": age_days,
            "age_bucket": age_bucket,
            "heatmap": heatmap,
            "sla_breach": "YES" if sla_breach else ""
        })

    # Sort: oldest first (largest age)
    summaries.sort(key=lambda x: x["age_days"], reverse=True)
    return summaries


# ──────────────────────────────────────────────────────────────────────────────
# CSV writing
# ──────────────────────────────────────────────────────────────────────────────

def write_line_item_csv(rows: List[UnfulfilledLineRow], path: Path, start_utc: datetime, end_utc: datetime, dry_run: bool):
    if dry_run:
        logging.info("Dry run: would write %s", path)
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["REPORT", "UNFULFILLED LINE ITEM VIEW"])
        w.writerow(["WINDOW_ET", f"{utc_to_et_str(start_utc)} → {utc_to_et_str(end_utc)}"])
        w.writerow(["GENERATED_ET", utc_to_et_str(datetime.now(timezone.utc))])
        w.writerow([])

        header = [
            "Order",
            "Processed At",
            "Product",
            "Author",
            "Vendor",
            "ISBN",
            "QTY Ordered",
            "QTY Unfulfilled",
            "Status",
            "Age (days)",
            "Heatmap",
        ]
        w.writerow(header)

        # Keep readable, deterministic sort: processedAt asc then order then product
        rows_sorted = sorted(rows, key=lambda r: (r.processed_at_utc, r.order_name, r.product_title))

        now_utc = datetime.now(timezone.utc)

        for r in rows_sorted:
            processed_et = r.processed_at_utc.astimezone(ET)
            formatted_dt = processed_et.strftime("%Y-%m-%d %I:%M %p")

            age_days = (now_utc - r.processed_at_utc).days

            if age_days <= 7:
                heatmap = "🟢"
            elif age_days <= 14:
                heatmap = "🟡"
            elif age_days <= 30:
                heatmap = "🟠"
            else:
                heatmap = "🔴"

            w.writerow([
                r.order_name,
                formatted_dt,
                r.product_title,
                r.author,
                r.product_vendor,
                r.isbn,
                r.qty_ordered,
                r.qty_unfulfilled,
                r.attributes,
                age_days,
                heatmap,
            ])

    logging.info("Wrote line item CSV: %s", path)

def write_product_summary_csv(rows: List[Dict[str, Any]], path: Path, start_utc: datetime, end_utc: datetime, dry_run: bool):
    if dry_run:
        logging.info("Dry run: would write %s", path)
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["REPORT", "UNFULFILLED RISK PRODUCTS (COMMITTED MODEL)"])
        w.writerow(["WINDOW_UTC", f"{start_utc.isoformat()} → {end_utc.isoformat()}"])
        w.writerow(["GENERATED_UTC", datetime.now(timezone.utc).isoformat()])
        w.writerow([])

        header = [
            "Product",
            "Vendor",
            "Collections",
            "Total Inventory",
            "Committed (Canonical)",
            "Earliest Unfulfilled Order (UTC)",
            "Earliest Unfulfilled Order (ET)",
            "Latest Unfulfilled Order (UTC)",
            "Latest Unfulfilled Order (ET)",
            "Age (days)",
            "Age Bucket",
            "Heatmap",
            "SLA Breach"
        ]
        w.writerow(header)

        for r in rows:
            earliest_utc = parse_utc_iso8601(r["earliest_order_utc"])
            latest_utc = parse_utc_iso8601(r["latest_order_utc"])

            w.writerow([
                r["title"],
                r["vendor"],
                r["collections"],
                r["total_inventory"],
                r["committed"],
                r["earliest_order_utc"],
                utc_to_et_str(earliest_utc),
                r["latest_order_utc"],
                utc_to_et_str(latest_utc),
                r["age_days"],
                r["age_bucket"],
                r.get("heatmap", ""),
                r.get("sla_breach", "")
            ])

    logging.info("Wrote product summary CSV: %s", path)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    load_dotenv()
    args = parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    global SLA_THRESHOLD_DAYS
    SLA_THRESHOLD_DAYS = args.sla_days

    start_utc, end_utc = utc_window_from_args(
        args.days,
        args.since,
        args.until,
        full_sweep=args.full_sweep,
        cap_days=args.cap_days,
    )

    window_days = (end_utc - start_utc).days
    logging.info("Effective window length (days): %d", window_days)
    if window_days > 365:
        logging.warning("Large sweep window detected (>365 days). Ensure rate limits are acceptable.")

    logging.info("Strict UTC window start: %s", start_utc.isoformat())
    logging.info("Strict UTC window end:   %s", end_utc.isoformat())

    client = ShopifyClient()

    # 1) Fetch unfulfilled line items only (Stage 2)
    rows, product_ids = fetch_unfulfilled_line_items(
        client=client,
        start_utc=start_utc,
        end_utc=end_utc,
        page_size=args.page_size,
        line_items_first=args.line_items_first,
        max_orders=args.max_orders,
    )

    if not rows:
        logging.info("No unfulfilled line items found in window.")
        return

    # 2) Fetch product snapshots (title/vendor/inventory/collections + committed)
    product_cache: Dict[str, ProductSnapshot] = {}
    product_cache = build_product_snapshots(client, product_ids, cache=product_cache, batch_size=25)

    # 3) Attach stable attributes + vendor/title preference (no inference drift)
    rows = attach_attributes_and_vendor(rows, product_cache)

    # 4) Build risk-focused product summary (committed model decides inclusion)
    summary_rows = compute_product_age_summary(rows, product_cache)

    # 5) Write CSVs
    outdir = Path(args.output_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    line_csv = outdir / f"weekly_unfulfilled_line_items_{stamp}.csv"
    prod_csv = outdir / f"weekly_unfulfilled_risk_products_{stamp}.csv"

    write_line_item_csv(rows, line_csv, start_utc, end_utc, args.dry_run)
    write_product_summary_csv(summary_rows, prod_csv, start_utc, end_utc, args.dry_run)

    if args.dry_run:
        logging.info("Dry run complete.")
    else:
        logging.info("Done.")

if __name__ == "__main__":
    main()