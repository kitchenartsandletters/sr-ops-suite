# Shopify API Version Maintenance Protocol

## Overview

Shopify releases a new stable Admin API version every quarter (January, April, July, October). Each version is supported for at least 12 months, then stops being accessible. A version past its end of access can keep "working" while Shopify serves a different version behind it, so a stale version degrades silently rather than failing loudly.

Incident history:
- **2026-06-03** — report failed on a transient Shopify "Not Found"; led to `validate_connection()` and retries.
- **2026-10-16 → 2026-11-04** — the worker kept requesting `2025-10` for 19 days after its end of access. Reports still ran; nothing flagged it. Led to the served-version check below.

**This document covers the whole estate.** The procedure and drift detection below are written for sr-ops-suite, which is where they were built; the [inventory](#org-wide-inventory) is the list of every service that pins a version, because the 2026-10 incident happened in the one place nobody was watching and there are four more places like it.

**sr-ops-suite version in use:** `2026-10` (set 2026-11-04, verified against a known report window)
**Accessible until:** 2027-10-16 15:00 UTC
**Bump by:** July 2027 (move to `2027-07`), and never later than 2027-10-16
**Earliest cliff anywhere:** `2026-04` on campaign-service and supply-chain-service, 2027-04-16 15:00 UTC
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

## Org-wide inventory

Every service that mints its own Admin API token and therefore pins its own version. Each row was read from the repo named, not inferred from another service's notes.

| Service | Where the version is set | Version | Accessible until | Drift detection |
|---------|--------------------------|---------|------------------|-----------------|
| sr-ops-suite (report worker) | Railway `SHOPIFY_API_VERSION`; `scripts/shopify_client.py` `DEFAULT_API_VERSION` | `2026-10` | 2027-10-16 | `validate_connection()`, logs served version |
| preorder-service | `shopify_version.py` `DEFAULT_SHOPIFY_API_VERSION`, env override | `2026-07` | 2027-07-16 | `scripts/smoke_shopify_api_version.py` (manual, pre-bump) |
| request-service | `backend/app/shopify_version.py`, env override | `2026-07` | 2027-07-16 | none |
| campaign-service | `app/config.py` `SHOPIFY_API_VERSION` default, env override | `2026-04` | 2027-04-16 | none |
| supply-chain-service | `app/clients/shopify_token.py`, `SHOPIFY_API_VERSION` env (default in `.env.example`) | `2026-04` | 2027-04-16 | none |

Only sr-ops-suite notices drift on its own. Everywhere else, this table and the quarterly check are the detection.

**The 2026-04 pair is a coupled bump.** campaign-service and supply-chain-service move to `2026-10` together, and only after checking `InventoryItem.variants` usage in supply-chain-service — the reason they are pinned back is recorded in `campaign-service/app/config.py`, so change that comment if the reason changes.

**Not checked, and worth confirming once:** webhook-gateway, backorder-service, edelweiss-service, damaged-books-service. The gateway verifies HMACs and forwards rather than querying the Admin API, so it may legitimately pin nothing; the others are unknown. Add a row or a note either way so the next person does not re-derive this.

**admin-dashboard backend — none.** It no longer calls Shopify. The Shopify proxy (and the old hardcoded `2023-10`) moved to **request-service** (`api.kitchenartsandletters.com`). Any `SHOPIFY_API_VERSION` left on the dashboard service is dead and can be deleted.

---

## Where the Version Is Used (sr-ops-suite)

**One setting.** Every Shopify call goes through `ShopifyClient` in `scripts/shopify_client.py` (`lop_unfulfilled_report.py` re-imports it). The URL is built from:

| Where | Setting | Value |
|-------|---------|-------|
| Railway: **report worker** service | `SHOPIFY_API_VERSION` | `2026-10` |
| `scripts/shopify_client.py` | `DEFAULT_API_VERSION` (fallback if the env var is unset) | `2026-10` |

Keep these two equal. The cron/enqueue services do not call Shopify and need no version.

---

## How We Detect Drift

On every job, `ShopifyClient.validate_connection()` records the `X-Shopify-API-Version` response header (the version Shopify actually served) and logs one of:

```
[shopify] Served API version: 2026-10                     <- healthy
[shopify] Requested API version X but Shopify served Y.   <- WARNING: X is past end of life, bump now
[shopify] Served API version not reported by Shopify.     <- header absent; check manually
```

This runs in sr-ops-suite only. The other services in the inventory have no equivalent, so a version past end of access there degrades exactly the way `2025-10` did — silently, with everything still appearing to work. Worth porting the served-version check into the shared Shopify client in each service; until then the quarterly walk is the only guard.

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
6. **Update this document** (current version, accessible-until, bump-by, lifecycle table, and the inventory row).

Steps 1, 2 and 6 apply to any service in the inventory. Steps 3 to 5 are sr-ops-suite's; each other service verifies its own way, and preorder-service has `scripts/smoke_shopify_api_version.py` for exactly this.

### Deprecation watch list

| Field | Status | Plan |
|-------|--------|------|
| `Order.physicalLocation` | Deprecated | Replaced by `Order.retailLocation` (2026-11-04) |
| `Order.channel` | Deprecated, still present in 2026-10 | Used only as a secondary online-sale signal next to `sourceName`. Re-check at the 2027 bump; replace or drop before it is removed. |
| `OrderCreateOrderInput.customerId` | Deprecated | Replaced by `customer { toAssociate { id } }` in campaign-service (2026-11-17). Grep for `customerId` before the next bump. |

Any new code that builds a Shopify URL must go through `ShopifyClient`; never hardcode a version string.

---

## Failure Mode Reference

| Symptom | Likely cause |
|---------|--------------|
| `WARNING Requested API version X but Shopify served Y` | X is past end of life — bump now |
| `Shopify GraphQL error: Not Found` | Version unavailable or wrong `SHOP_URL` |
| `Shopify GraphQL error: [... field ... doesn't exist ...]` | A field we query was removed in this version |
| `Field X is not defined by type Y` on a mutation input | The field never existed on that input, or was removed. Check the input object's reference page before assuming a version problem |
| Report runs but data looks wrong | Response shape changed; compare against a known window (step 4) |
| `Shopify token request failed: status=400/401` | `SHOPIFY_CLIENT_ID` / `SHOPIFY_CLIENT_SECRET` wrong or rotated, or the app was uninstalled (`SHOPIFY_ACCESS_TOKEN` is retired and unused) |

Job failures email `EMAIL_RECIPIENTS`; a missing daily job is caught by the worker's missed-run watchdog at 10:30 ET.

---

## Calendar Reminders

- **April 2027:** campaign-service and supply-chain-service lose access to `2026-04` on 2027-04-16. Bump the pair together (see the inventory note) well before then.
- **July 2027:** preorder-service and request-service lose `2026-07` on 2027-07-16; sr-ops-suite bumps to `2027-07`.
- **Each January, April, July, October:** 5-minute check of the versioning page for anything we use that is deprecated, **and walk the inventory table** — confirm each row still matches what the service actually sends, and that nothing new calls Shopify without a row.
