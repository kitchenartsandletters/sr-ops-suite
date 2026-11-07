#!/usr/bin/env python3
"""
eu_pid_audit.py

READ-ONLY audit of variant barcodes for the EU product identifier (PID)
requirement in effect from 2026-11-01. Nothing is written to Shopify.

For every variant in the catalog it reads the full `barcodes` set (with types)
and sorts findings into categories:

  retype_isbn          Untyped ("Custom") barcode that is a valid ISBN-10/13.
                       Whole catalog, regardless of market. Safe to retype to ISBN.
  isbn_needs_cleanup   Valid ISBN only after stripping hyphens/spaces. Retyping
                       would also change the stored value (and what the
                       storefront reads as the barcode), so review first.
  isbn_bad_checksum    Looks like an ISBN (978/979 13-digit, or 10-char) but the
                       check digit fails. Review: typo, or really a custom code.
  gtin_candidate       Untyped barcode that passes a UPC-12 or non-ISBN EAN-13
                       checksum (e.g. merchandise). Review; may belong as UPC/EAN.
  intl_no_barcode      In scope for international sale, no barcode at all.
                       Needs: "no standardized identifier" + an NS-PID barcode.
  intl_custom_only     In scope, has barcodes but none is a standardized ID.
                       Needs: "no standardized identifier" checkbox (admin).
  intl_many_barcodes   Variant has more barcodes than one page returned; its
                       full set was fetched separately. Informational.

"In scope" = product ACTIVE, published in the International market (checked via
publishedInContext for --country, default DE), and sellable (in stock or
inventoryPolicy CONTINUE).

Note: the "has no standardized identifier" declaration is not readable through
the barcode API, so intl_* rows may include products already declared in admin.

Run from the repo root:
    python scripts/eu_pid_audit.py
    python scripts/eu_pid_audit.py --country FR --page-size 25
"""

import sys
import csv
import time
import logging
import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Match the repo's import convention: scripts/ on sys.path, .env at repo root.
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from shopify_client import ShopifyClient, get_token_manager  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

BARCODES_PER_PAGE = 5  # nearly every book has 1; extras fetched on demand

VARIANTS_QUERY = """
query EuPidAudit($first: Int!, $after: String, $country: CountryCode!) {
  productVariants(first: $first, after: $after, sortKey: ID) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        title
        sku
        inventoryPolicy
        inventoryQuantity
        barcodes(first: %d) {
          pageInfo { hasNextPage }
          edges { node { type value } }
        }
        product {
          id
          title
          status
          publishedInContext(context: { country: $country })
        }
      }
    }
  }
}
""" % BARCODES_PER_PAGE

VARIANT_BARCODES_QUERY = """
query VariantBarcodes($id: ID!) {
  productVariant(id: $id) {
    barcodes(first: 20) {
      edges { node { type value } }
    }
  }
}
"""


# ------------------------ Identifier validation ------------------------ #

def clean(value: str) -> str:
    return value.replace("-", "").replace(" ", "").strip().upper()


def is_isbn13(v: str) -> bool:
    if len(v) != 13 or not v.isdigit() or v[:3] not in ("978", "979"):
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(v))
    return total % 10 == 0


def is_isbn10(v: str) -> bool:
    if len(v) != 10 or not v[:9].isdigit() or not (v[9].isdigit() or v[9] == "X"):
        return False
    digits = [int(c) for c in v[:9]] + [10 if v[9] == "X" else int(v[9])]
    return sum((10 - i) * d for i, d in enumerate(digits)) % 11 == 0


def is_isbn(v: str) -> bool:
    return is_isbn13(v) or is_isbn10(v)


def looks_like_isbn(v: str) -> bool:
    """Shape of an ISBN, ignoring the check digit."""
    if len(v) == 13 and v.isdigit() and v[:3] in ("978", "979"):
        return True
    return len(v) == 10 and v[:9].isdigit() and (v[9].isdigit() or v[9] == "X")


def is_gtin_checksum(v: str) -> bool:
    """UPC-12 / EAN-13 mod-10 check (weights 3,1 from the right)."""
    if len(v) not in (12, 13) or not v.isdigit():
        return False
    body, check = v[:-1], int(v[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


STANDARD_TYPES = {"ISBN", "EAN", "UPC", "GTIN"}


def classify_barcode(raw: str, btype):
    """Category for one barcode, or None if nothing to do."""
    if btype is not None:
        return None  # already typed; Shopify validated it on write
    if is_isbn(raw):
        return "retype_isbn"
    c = clean(raw)
    if c != raw and is_isbn(c):
        return "isbn_needs_cleanup"
    if looks_like_isbn(c):
        return "isbn_bad_checksum"
    if is_gtin_checksum(c):
        return "gtin_candidate"
    return None


def has_standard_id(barcodes) -> bool:
    """True if any barcode is (or will become, after retype) a standardized ID."""
    for b in barcodes:
        if b["type"] in STANDARD_TYPES:
            return True
        if b["type"] is None and is_isbn(clean(b["value"])):
            return True
    return False


# ------------------------ Shopify access ------------------------ #

def gql(client, query, variables, max_attempts=8):
    """client.graphql with backoff on THROTTLED (the client raises on it)."""
    for attempt in range(1, max_attempts + 1):
        try:
            return client.graphql(query, variables)
        except RuntimeError as e:
            if "THROTTLED" not in str(e) or attempt == max_attempts:
                raise
            wait = min(2 ** attempt, 30)
            logging.warning("Throttled; sleeping %ss (attempt %d)", wait, attempt)
            time.sleep(wait)


def fetch_all_barcodes(client, variant_id):
    data = gql(client, VARIANT_BARCODES_QUERY, {"id": variant_id})
    return [e["node"] for e in data["productVariant"]["barcodes"]["edges"]]


def iter_variants(client, country, page_size):
    after = None
    page = 0
    while True:
        data = gql(client, VARIANTS_QUERY,
                   {"first": page_size, "after": after, "country": country})
        conn = data["productVariants"]
        page += 1
        for edge in conn["edges"]:
            yield edge["node"]
        if page % 20 == 0:
            logging.info("…%d pages read", page)
        if not conn["pageInfo"]["hasNextPage"]:
            return
        after = conn["pageInfo"]["endCursor"]
        time.sleep(0.25)  # stay gentle on the cost bucket


# ------------------------ Audit ------------------------ #

def in_scope(v) -> bool:
    p = v["product"]
    if p["status"] != "ACTIVE" or not p["publishedInContext"]:
        return False
    return v["inventoryPolicy"] == "CONTINUE" or (v["inventoryQuantity"] or 0) > 0


def gid_num(gid: str) -> str:
    return gid.rsplit("/", 1)[-1]


def audit(client, country, page_size, admin_base):
    rows = []
    seen = 0
    for v in iter_variants(client, country, page_size):
        seen += 1
        p = v["product"]
        barcodes = [e["node"] for e in v["barcodes"]["edges"]]
        many = v["barcodes"]["pageInfo"]["hasNextPage"]
        if many:
            barcodes = fetch_all_barcodes(client, v["id"])

        scope = in_scope(v)
        base = {
            "in_scope": "yes" if scope else "no",
            "product_status": p["status"],
            "published_intl": "yes" if p["publishedInContext"] else "no",
            "title": p["title"],
            "variant": v["title"],
            "sku_author": v["sku"] or "",
            "inventory_policy": v["inventoryPolicy"],
            "inventory_qty": v["inventoryQuantity"],
            "barcode_count": len(barcodes),
            "product_id": gid_num(p["id"]),
            "variant_id": gid_num(v["id"]),
            "admin_url": f"{admin_base}/products/{gid_num(p['id'])}/variants/{gid_num(v['id'])}",
        }

        for pos, b in enumerate(barcodes, start=1):
            cat = classify_barcode(b["value"], b["type"])
            if cat:
                rows.append({**base, "category": cat, "barcode_position": pos,
                             "barcode_value": b["value"], "barcode_type": b["type"] or "",
                             "cleaned_value": clean(b["value"])})

        if scope:
            if not barcodes:
                rows.append({**base, "category": "intl_no_barcode"})
            elif not has_standard_id(barcodes):
                rows.append({**base, "category": "intl_custom_only",
                             "barcode_value": " | ".join(b["value"] for b in barcodes)})
            if many:
                rows.append({**base, "category": "intl_many_barcodes"})

    return rows, seen


COLUMNS = [
    "category", "in_scope", "title", "variant", "sku_author",
    "barcode_position", "barcode_value", "barcode_type", "cleaned_value",
    "barcode_count", "product_status", "published_intl",
    "inventory_policy", "inventory_qty", "product_id", "variant_id", "admin_url",
]

CATEGORY_ORDER = [
    "retype_isbn", "isbn_needs_cleanup", "isbn_bad_checksum", "gtin_candidate",
    "intl_no_barcode", "intl_custom_only", "intl_many_barcodes",
]


def write_csv(path, rows):
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    rows.sort(key=lambda r: (order.get(r["category"], 99), r["title"].lower()))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def parse_args():
    ap = argparse.ArgumentParser(description="Read-only EU PID barcode audit.")
    ap.add_argument("--country", default="DE",
                    help="EU country code used to test International-market publication (default DE).")
    ap.add_argument("--page-size", type=int, default=50,
                    help="Variants per page (default 50; lower if throttled often).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Run the audit but don't write the CSV.")
    return ap.parse_args()


def main():
    args = parse_args()
    client = ShopifyClient()
    client.validate_connection()

    store = get_token_manager().domain.split(".myshopify.com")[0]
    admin_base = f"https://admin.shopify.com/store/{store}"

    logging.info("🇪🇺 EU PID audit (read-only), market check country=%s", args.country)
    rows, seen = audit(client, args.country.upper(), args.page_size, admin_base)

    counts = Counter(r["category"] for r in rows)
    logging.info("Variants scanned: %d", seen)
    for cat in CATEGORY_ORDER:
        logging.info("  %-20s %d", cat, counts.get(cat, 0))

    if args.dry_run:
        logging.info("Dry run — no CSV written.")
        return

    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    date_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")
    path = out_dir / f"eu_pid_audit_{date_str}.csv"
    write_csv(path, rows)
    logging.info("✅ CSV written: %s", path)


if __name__ == "__main__":
    main()
