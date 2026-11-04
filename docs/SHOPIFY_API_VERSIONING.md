# Shopify API Version Maintenance Protocol

## Overview

Shopify releases a new stable Admin API version every quarter (January, April, July, October). Each version is supported for at least 12 months, then stops being accessible. A version past its end of access can keep "working" while Shopify serves a different version behind it, so a stale version degrades silently rather than failing loudly.

Incident history:
- **2026-06-03** — report failed on a transient Shopify "Not Found"; led to `validate_connection()` and retries.
- **2026-10-16 → 2026-11-04** — the worker kept requesting `2025-10` for 19 days after its end of access. Reports still ran; nothing flagged it. Led to the served-version check below.

**Current version in use:** `2026-10` (set 2026-11-04, verified against a known report window)
**Accessible until:** 2027-10-16 15:00 UTC
**Bump by:** July 2027 (move to `2027-07`), and never later than 2027-10-16
**Source of truth:** https://shopify.dev/docs/api/usage/versioning

---

## Version Lifecycle (from Shopify's versioning page, Nov 2026)

| Version | Released     | Accessible until         | Status (Nov 2026)  |
|---------|--------------|--------------------------|--------------------|
| 2025-07 | Jul 1, 2025  | Jul 16, 2026 15:00 UTC   | Unsupported        |
| 2025-10 | Oct 1, 2025  | Oct 16, 2026 15:00 UTC   | Unsupported        |
| 2026-01 | Jan 1, 2026  | Jan 16, 2027 15:00 UTC   | Stable             |
| 2026-04 | Apr 1, 2026  | Apr 16, 2027 15:00 UTC   | Stable             |
| 2026-07 | Jul 1, 2026  | Jul 16, 2027 15:00 UTC   | Stable             |
| 2026-10 | Oct 1, 2026  | Oct 16, 2027 15:00 UTC   | Latest stable      |
| 2027-01 | Jan 1, 2027  | Jan 16, 2028 15:00 UTC   | Release candidate  |

Never run a release candidate in production.

---

## Where the Version Is Used

**sr-ops-suite — one setting.** Every Shopify call goes through `ShopifyClient` in `scripts/shopify_client.py` (`lop_unfulfilled_report.py` re-imports it). The URL is built from:

| Where | Setting | Value |
|-------|---------|-------|
| Railway: **report worker** service | `SHOPIFY_API_VERSION` | `2026-10` |
| `scripts/shopify_client.py` | `DEFAULT_API_VERSION` (fallback if the env var is unset) | `2026-10` |

Keep these two equal. The cron/enqueue services do not call Shopify and need no version.

**admin-dashboard backend — none.** It no longer calls Shopify. The Shopify proxy (and the old hardcoded `2023-10`) moved to **request-service** (`api.kitchenartsandletters.com`). Any `SHOPIFY_API_VERSION` left on the dashboard service is dead and can be deleted.

**request-service — owns its own Shopify calls.** Not covered by this document; check its version separately on the same schedule.

---

## How We Detect Drift

On every job, `ShopifyClient.validate_connection()` records the `X-Shopify-API-Version` response header (the version Shopify actually served) and logs one of:

```
[shopify] Served API version: 2026-10                     <- healthy
[shopify] Requested API version X but Shopify served Y.   <- WARNING: X is past end of life, bump now
[shopify] Served API version not reported by Shopify.     <- header absent; check manually
```

---

## Update Procedure

Run once per year at minimum (or when Shopify emails about a deprecation). Shopify sends these to the app's contact address — keep it monitored.

1. **Pick the target.** Latest *stable* version on the versioning page.
2. **Check our fields against it.** Open the target version's reference pages for `Order` and `Product` and confirm every field we query still exists (deprecated is OK; removed is not):
   - `orders`: `processedAt`, `sourceName`, `channel { handle }`, `retailLocation { id }`, `lineItems { quantity title customAttributes variant { id sku barcode product { id title totalInventory } } }`, `pageInfo`
   - `product`: `title`, `vendor`, `totalInventory`, `priceRangeV2.minVariantPrice`, `collections`, `variants.inventoryItem.inventoryLevels { location { id } quantities(names: ["available","incoming"]) }`
3. **Set the env var** on the report worker and update `DEFAULT_API_VERSION` to match. Railway redeploys the worker.
4. **Verify with a known window.** Re-run a recent day in table mode (no email) and compare `result.row_counts` to the automated job for the same window. The total must match exactly; the split between sections can shift only if inventory moved since.
   ```sql
   INSERT INTO reports.report_jobs (report_id, status, parameters)
   VALUES ('daily_sales_kal','queued',
     '{"start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD","delivery_method":"table","formats":["pdf","csv"],"test":"API bump"}');
   ```
5. **Check the worker log** for `[shopify] Served API version: <target>`.
6. **Update this document** (current version, accessible-until, bump-by, lifecycle table).

### Deprecation watch list

| Field | Status | Plan |
|-------|--------|------|
| `Order.physicalLocation` | Deprecated | Replaced by `Order.retailLocation` (2026-11-04) |
| `Order.channel` | Deprecated, still present in 2026-10 | Used only as a secondary online-sale signal next to `sourceName`. Re-check at the 2027 bump; replace or drop before it is removed. |

Any new code that builds a Shopify URL must go through `ShopifyClient`; never hardcode a version string.

---

## Failure Mode Reference

| Symptom | Likely cause |
|---------|--------------|
| `WARNING Requested API version X but Shopify served Y` | X is past end of life — bump now |
| `Shopify GraphQL error: Not Found` | Version unavailable or wrong `SHOP_URL` |
| `Shopify GraphQL error: [... field ... doesn't exist ...]` | A field we query was removed in this version |
| Report runs but data looks wrong | Response shape changed; compare against a known window (step 4) |
| `Shopify token request failed: status=400/401` | `SHOPIFY_CLIENT_ID` / `SHOPIFY_CLIENT_SECRET` wrong or rotated, or the app was uninstalled (`SHOPIFY_ACCESS_TOKEN` is retired and unused) |

Job failures email `EMAIL_RECIPIENTS`; a missing daily job is caught by the worker's missed-run watchdog at 10:30 ET.

---

## Calendar Reminders

- **July 2027:** bump to `2027-07` (procedure above).
- **Each January, April, July, October:** 5-minute check of the versioning page for anything we use that is deprecated.
