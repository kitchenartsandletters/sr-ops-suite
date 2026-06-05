# Shopify API Version Maintenance Protocol

## Overview

Shopify releases a new stable API version quarterly (January, April, July, October) and retires versions after approximately 12 months. Staying current prevents silent failures like the June 3, 2026 report outage. This document defines how KAL maintains API version hygiene across all services.

---

## Version Lifecycle

Shopify's release and retirement schedule:

| Version    | Released     | Retirement (approx.) |
|------------|--------------|----------------------|
| 2025-01    | Jan 2025     | Jan 2026             |
| 2025-04    | Apr 2025     | Apr 2026             |
| 2025-07    | Jul 2025     | Jul 2026             |
| 2025-10    | Oct 2025     | Oct 2026             |
| 2026-01    | Jan 2026     | Jan 2027             |
| 2026-04    | Apr 2026     | Apr 2027             |

**Current version in use:** `2025-10`
**Next required update:** before October 2026
**Source of truth:** https://shopify.dev/docs/api/usage/versioning

Shopify sends deprecation emails to the app contact address when a version approaches retirement. Ensure the Shopify app contact email is monitored.

---

## Where the Version Is Used

### Environment Variables (Railway)

| Service            | Variable              | Current Value |
|--------------------|-----------------------|---------------|
| sr-ops-suite worker | `SHOPIFY_API_VERSION` | `2025-10`     |
| admin-dashboard backend | `SHOPIFY_API_VERSION` | `2025-10` (verify) |

Both services construct their Shopify API URL from this env var. Updating the env var and redeploying is sufficient for most version bumps.

### Code References

All Shopify API calls route through `ShopifyClient` in `scripts/shopify_client.py` (or `scripts/lop_unfulfilled_report.py` for the LOP report). The URL is constructed once at init:

```python
self.base_url = f"https://{base_domain}/admin/api/{api_version}/graphql.json"
```

The one exception is the Shopify GraphQL proxy in `admin-dashboard/backend/app/routes.py` which has a hardcoded version string:

```python
f"https://{os.getenv('SHOP_URL')}/admin/api/2023-10/graphql.json"
```

**This is a known issue.** This route still uses `2023-10` which has been retired. It should be updated to read from an env var. See Hardcoded Versions below.

---

## Update Procedure

Run this procedure once per quarter, or immediately when a Shopify deprecation email arrives.

### Step 1 — Check the current stable version

Go to https://shopify.dev/docs/api/usage/versioning and confirm the latest stable release. Do not use release candidate (`-rc`) versions in production.

### Step 2 — Review the changelog for breaking changes

Go to https://shopify.dev/changelog and filter by the new version. Check for:
- Removed or renamed fields in queries used by our scripts
- Changed response shapes (especially `pageInfo`, `edges`, `node` patterns)
- Deprecated mutations or query arguments
- Changes to `financial_status`, `processedAt`, `totalInventory`, `inventoryLevels`, or `committed` quantities — all of which are used in our reports

Key queries to verify against the changelog:
- `orders` with `processedAt`, `sourceName`, `channel`, `lineItems`, `variant`, `product`
- `product` with `totalInventory`, `priceRangeV2`, `collections`, `variants`, `inventoryItem`, `inventoryLevels`, `quantities`
- `draftOrders` with `completedAt`, `order`
- `products` with `status`, `onlineStoreUrl`, `collections`, `variants`, `inventoryItem`

### Step 3 — Test in staging (or dry-run)

Run `daily_sales_report.py --dry-run` and `weekly_maintenance_report.py` locally with the new version set:

```bash
SHOPIFY_API_VERSION=2026-01 python scripts/daily_sales_report.py --dry-run
```

Watch for GraphQL errors indicating field removals or shape changes.

### Step 4 — Update env vars in Railway

Update `SHOPIFY_API_VERSION` on:
- sr-ops-suite worker service
- admin-dashboard backend service (if used there)
- sr-ops-suite cron service (if it makes direct Shopify calls)

### Step 5 — Fix hardcoded versions

Update the hardcoded version in `admin-dashboard/backend/app/routes.py`:

```python
# Change:
f"https://{os.getenv('SHOP_URL')}/admin/api/2023-10/graphql.json"

# To:
api_version = os.getenv("SHOPIFY_API_VERSION", "2025-10")
f"https://{os.getenv('SHOP_URL')}/admin/api/{api_version}/graphql.json"
```

### Step 6 — Redeploy and monitor

Deploy both services. Watch worker logs for the startup validation message:

```
[shopify] API connection validated: https://castironbooks.myshopify.com/admin/api/2026-01/graphql.json
```

Monitor the next two automated report runs to confirm successful email delivery.

### Step 7 — Update this document

Update the "Current version in use" and "Next required update" fields above.

---

## Hardcoded Versions — Known Issues

| File | Location | Current Value | Action |
|------|----------|---------------|--------|
| `admin-dashboard/backend/app/routes.py` | Shopify GraphQL proxy route | `2023-10` | Replace with env var read |

Any new code that constructs a Shopify API URL must read from `os.getenv("SHOPIFY_API_VERSION")` and never hardcode a version string.

---

## Failure Mode Reference

| Symptom | Likely Cause |
|---------|--------------|
| `Shopify GraphQL error: Not Found` | API version sunset or invalid `SHOP_URL` |
| `Shopify GraphQL error: {"errors": [...]}` | Field removed or renamed in new version |
| Report runs but data looks wrong | Response shape changed silently |
| 401 or authentication error | `SHOPIFY_ACCESS_TOKEN` rotated or app uninstalled |

The startup validation call (`client.validate_connection()`) will surface "Not Found" immediately with a clear error message naming the env var, rather than failing silently mid-report.

---

## Calendar Reminders

Set a recurring calendar reminder for the first week of each month in January, April, July, and October:

> **Shopify API version check due.** Review https://shopify.dev/docs/api/usage/versioning and update `SHOPIFY_API_VERSION` env vars if a new stable version is available. Retire the old version before its sunset date.

---

## Quarterly Checklist

- [ ] Check current stable version at shopify.dev
- [ ] Review changelog for breaking changes affecting our queries
- [ ] Run dry-run test locally with new version
- [ ] Update `SHOPIFY_API_VERSION` env var on all Railway services
- [ ] Fix any hardcoded version strings found in code review
- [ ] Redeploy and monitor two report runs
- [ ] Update "Current version in use" in this document
- [ ] Update `INFRASTRUCTURE.md` if service topology changed
