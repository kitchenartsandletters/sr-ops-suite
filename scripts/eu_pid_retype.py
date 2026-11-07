#!/usr/bin/env python3
"""
eu_pid_retype.py

Types untyped ("Custom") ISBN barcodes as ISBN for the EU product identifier
requirement. DRY RUN BY DEFAULT: nothing is written unless you pass --apply.

Actions (whole catalog, any status or market):
  retype   Untyped barcode that is already a valid ISBN. Value unchanged,
           type set to ISBN. Always on.
  restore  Untyped 9-digit barcode that becomes a valid ISBN-10 with a leading
           0 restored (e.g. 312198604 -> 0312198604). Value CHANGES.
           Only with --include-restore.
  cleanup  Untyped barcode that is a valid ISBN once hyphens/spaces are removed
           (and a lowercase x uppercased). Value CHANGES.
           Only with --include-restore.
  gtin     Untyped 12-digit barcode with a valid check digit -> UPC, or 13-digit
           -> EAN. Value unchanged. Skips GS1 restricted/in-store prefixes
           (UPC 2/4/5; EAN 02, 04, 2xx, 98x, 99x) and 12-digit 978/979 values,
           which are usually truncated ISBNs. Only with --include-gtin.

Safety:
  * Each variant's FULL barcode set is resent in its original order (Shopify
    replaces the whole set on write). Only the targeted entries change, so the
    first barcode, which the legacy `barcode` field and the storefront read,
    stays in position 1.
  * Just before each write batch, the current barcodes are re-read; any variant
    whose barcodes changed since the scan is skipped (status=stale).
  * Every write is logged with before/after JSON, which serves as an undo record.
  * Re-running is safe: already-typed barcodes are not touched, so an
    interrupted run resumes by just running again.

Run from the repo root:
    python scripts/eu_pid_retype.py                          # dry run, writes plan CSV
    python scripts/eu_pid_retype.py --include-restore        # dry run incl. value fixes
    python scripts/eu_pid_retype.py --apply --limit 10       # pilot: first 10 products
    python scripts/eu_pid_retype.py --apply --include-restore
    python scripts/eu_pid_retype.py --include-gtin                 # dry run: UPC/EAN typing
Requires the app to have the write_products scope for --apply.
"""

import sys
import csv
import json
import logging
import argparse
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Reuses the audit's path/env setup, validators, client helpers and paging.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eu_pid_audit import (  # noqa: E402
    ROOT, ShopifyClient,
    clean, is_isbn, is_isbn10, gql, iter_variants, fetch_all_barcodes, gid_num,
)

MIN_API_VERSION = "2026-10"  # first version with ProductVariant.barcodes

CURRENT_BARCODES_QUERY = """
query CurrentBarcodes($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on ProductVariant {
      id
      barcodes(first: 20) { edges { node { type value } } }
    }
  }
}
"""


# ------------------------ Planning ------------------------ #

def gtin_check(v: str) -> bool:
    """Mod-10 check digit used by UPC-A and EAN-13 (weights 3,1 from the right)."""
    body, check = v[:-1], int(v[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def gtin_type(v: str):
    """'UPC' or 'EAN' for a globally standardized code, else None."""
    if not v.isdigit() or len(v) not in (12, 13) or not gtin_check(v):
        return None
    if len(v) == 12:
        if v[0] in "245" or v[:3] in ("978", "979"):
            return None  # restricted / in-store / coupon, or truncated ISBN
        return "UPC"
    if v[:2] in ("02", "04", "98", "99") or v[0] == "2":
        return None  # restricted / in-store / coupon / refund
    if v[:3] in ("978", "979"):
        return None  # ISBN range; handled as ISBN
    return "EAN"


def plan_barcodes(barcodes, include_restore, include_gtin=False):
    """Return (new_barcodes, actions). new_barcodes keeps order and length."""
    new, actions = [], []
    for b in barcodes:
        btype, value = b["type"], b["value"]
        nb = {"type": btype, "value": value}
        if btype is None:
            if is_isbn(value):
                nb = {"type": "ISBN", "value": value}
                actions.append("retype")
            elif include_restore:
                c = clean(value)
                if c != value and is_isbn(c):
                    nb = {"type": "ISBN", "value": c}
                    actions.append("cleanup")
                elif len(value) == 9 and value.isdigit() and is_isbn10("0" + value):
                    nb = {"type": "ISBN", "value": "0" + value}
                    actions.append("restore")
            if include_gtin and nb["type"] is None:
                gt = gtin_type(value)
                if gt:
                    nb = {"type": gt, "value": value}
                    actions.append("gtin")
        new.append(nb)
    return new, actions


def to_input(barcodes):
    """BarcodeInput list; omit type when untyped so Shopify stores as entered."""
    out = []
    for b in barcodes:
        item = {"value": b["value"]}
        if b["type"] is not None:
            item["type"] = b["type"]
        out.append(item)
    return out


def scan(client, include_restore, page_size, include_gtin=False):
    """Live scan; returns OrderedDict product_id -> list of variant plans."""
    plans = OrderedDict()
    seen = 0
    for v in iter_variants(client, "DE", page_size):  # country unused here
        seen += 1
        barcodes = [e["node"] for e in v["barcodes"]["edges"]]
        if v["barcodes"]["pageInfo"]["hasNextPage"]:
            barcodes = fetch_all_barcodes(client, v["id"])
        new, actions = plan_barcodes(barcodes, include_restore, include_gtin)
        if not actions:
            continue
        plans.setdefault(v["product"]["id"], []).append({
            "product_id": v["product"]["id"],
            "variant_id": v["id"],
            "title": v["product"]["title"],
            "status": v["product"]["status"],
            "actions": actions,
            "before": barcodes,
            "after": new,
        })
    return plans, seen


# ------------------------ Writing ------------------------ #

def build_batch_mutation(items):
    decls, parts, variables = [], [], {}
    for i, (pid, vplans) in enumerate(items):
        decls.append(f"$p{i}: ID!, $v{i}: [ProductVariantsBulkInput!]!")
        parts.append(
            f"m{i}: productVariantsBulkUpdate(productId: $p{i}, variants: $v{i}) {{\n"
            f"  productVariants {{ id barcodes(first: 20) {{ edges {{ node {{ type value }} }} }} }}\n"
            f"  userErrors {{ field message code }}\n"
            f"}}"
        )
        variables[f"p{i}"] = pid
        variables[f"v{i}"] = [
            {"id": vp["variant_id"], "barcodes": to_input(vp["after"])} for vp in vplans
        ]
    query = "mutation RetypeBatch(" + ", ".join(decls) + ") {\n" + "\n".join(parts) + "\n}"
    return query, variables


def current_barcodes(client, variant_ids):
    data = gql(client, CURRENT_BARCODES_QUERY, {"ids": variant_ids})
    out = {}
    for n in data["nodes"]:
        if n:
            out[n["id"]] = [e["node"] for e in n["barcodes"]["edges"]]
    return out


def norm(barcodes):
    return [(b["type"], b["value"]) for b in barcodes]


def apply_batch(client, items, log):
    # 1. Staleness check against live data.
    vids = [vp["variant_id"] for _, vps in items for vp in vps]
    live = current_barcodes(client, vids)
    fresh = []
    for pid, vps in items:
        keep = []
        for vp in vps:
            if norm(live.get(vp["variant_id"], [])) != norm(vp["before"]):
                log(vp, "stale", "barcodes changed since scan; skipped")
            else:
                keep.append(vp)
        if keep:
            fresh.append((pid, keep))
    if not fresh:
        return

    # 2. One aliased request for the batch.
    query, variables = build_batch_mutation(fresh)
    data = gql(client, query, variables)

    # 3. Per-product results, verified against intent.
    for i, (pid, vps) in enumerate(fresh):
        res = data[f"m{i}"]
        errors = res.get("userErrors") or []
        if errors:
            msg = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in errors)
            for vp in vps:
                log(vp, "error", msg)
            continue
        returned = {
            pv["id"]: [e["node"] for e in pv["barcodes"]["edges"]]
            for pv in (res.get("productVariants") or [])
        }
        for vp in vps:
            got = returned.get(vp["variant_id"])
            if got is not None and norm(got) == norm(vp["after"]):
                log(vp, "ok", "")
            else:
                log(vp, "mismatch", f"returned {json.dumps(got)}")


# ------------------------ CSV ------------------------ #

LOG_COLUMNS = [
    "timestamp", "result", "actions", "title", "product_status",
    "before", "after", "message", "product_id", "variant_id",
]


class CsvLog:
    def __init__(self, path):
        self.path = path
        self.counts = Counter()
        self.f = open(path, "w", newline="", encoding="utf-8")
        self.w = csv.DictWriter(self.f, fieldnames=LOG_COLUMNS)
        self.w.writeheader()

    def __call__(self, vp, result, message):
        self.counts[result] += 1
        self.w.writerow({
            "timestamp": datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds"),
            "result": result,
            "actions": "+".join(vp["actions"]),
            "title": vp["title"],
            "product_status": vp["status"],
            "before": json.dumps(vp["before"]),
            "after": json.dumps(vp["after"]),
            "message": message,
            "product_id": gid_num(vp["product_id"]),
            "variant_id": gid_num(vp["variant_id"]),
        })
        self.f.flush()  # survive interruption

    def close(self):
        self.f.close()


# ------------------------ Main ------------------------ #

def parse_args():
    ap = argparse.ArgumentParser(description="Type untyped ISBN barcodes as ISBN (dry run by default).")
    ap.add_argument("--apply", action="store_true", help="Actually write to Shopify.")
    ap.add_argument("--include-restore", action="store_true",
                    help="Also restore lost leading zeros on ISBN-10s and strip hyphens/spaces (changes values).")
    ap.add_argument("--include-gtin", action="store_true",
                    help="Also type valid UPC-12 codes as UPC and EAN-13 codes as EAN (values unchanged).")
    ap.add_argument("--only", default="",
                    help="Comma-separated actions to include, e.g. restore,cleanup (pilot a specific action).")
    ap.add_argument("--limit", type=int, default=0,
                    help="Only process the first N products (pilot run).")
    ap.add_argument("--batch", type=int, default=10,
                    help="Products per write request (default 10).")
    ap.add_argument("--page-size", type=int, default=50, help="Variants per scan page.")
    ap.add_argument("--yes", action="store_true", help="Skip the confirmation prompt with --apply.")
    return ap.parse_args()


def main():
    args = parse_args()
    client = ShopifyClient()
    client.validate_connection()
    served = client.served_api_version or client.api_version
    if served < MIN_API_VERSION:
        sys.exit(f"❌ Needs Admin API {MIN_API_VERSION}+, but {served} is in use. Check SHOPIFY_API_VERSION.")

    mode = "APPLY" if args.apply else "DRY RUN"
    extras = [x for x, on in (("restore/cleanup", args.include_restore), ("gtin", args.include_gtin)) if on]
    logging.info("🔤 EU PID retype — %s%s", mode, f" (+{', '.join(extras)})" if extras else "")
    logging.info("Scanning catalog…")
    plans, seen = scan(client, args.include_restore, args.page_size, args.include_gtin)

    items = list(plans.items())
    if args.only:
        wanted = {a.strip() for a in args.only.split(",")}
        items = [(pid, [vp for vp in vps if set(vp["actions"]) & wanted]) for pid, vps in items]
        items = [(pid, vps) for pid, vps in items if vps]
    if args.limit:
        items = items[: args.limit]
    vcount = sum(len(v) for _, v in items)
    action_counts = Counter(a for _, vps in items for vp in vps for a in vp["actions"])
    logging.info("Variants scanned: %d | products to change: %d | variants: %d",
                 seen, len(items), vcount)
    for a in ("retype", "restore", "cleanup", "gtin"):
        logging.info("  %-8s %d", a, action_counts.get(a, 0))

    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d_%H%M%S")

    if not args.apply:
        log = CsvLog(out_dir / f"eu_pid_retype_plan_{stamp}.csv")
        for _, vps in items:
            for vp in vps:
                log(vp, "planned", "")
        log.close()
        logging.info("Dry run — nothing written to Shopify. Plan: %s", log.path)
        return

    if not items:
        logging.info("Nothing to do.")
        return
    if not args.yes:
        reply = input(f"Write barcode changes to {len(items)} products ({vcount} variants)? Type YES: ")
        if reply.strip() != "YES":
            sys.exit("Aborted.")

    log = CsvLog(out_dir / f"eu_pid_retype_log_{stamp}.csv")
    try:
        for start in range(0, len(items), args.batch):
            apply_batch(client, items[start:start + args.batch], log)
            done = min(start + args.batch, len(items))
            if done % (args.batch * 20) == 0 or done == len(items):
                logging.info("…%d/%d products | %s", done, len(items), dict(log.counts))
    except KeyboardInterrupt:
        logging.warning("Interrupted. Re-run to continue; finished variants are skipped automatically.")
    finally:
        log.close()
        logging.info("Results: %s", dict(log.counts))
        logging.info("Log (before/after, usable for undo): %s", log.path)


if __name__ == "__main__":
    main()
