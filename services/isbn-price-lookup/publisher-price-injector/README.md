# Publisher Price Injector

**Project ID:** `publisher-price-injector`  
**Source Repo:** `kitchenartsandletters/sr-ops-suite`  
**Root Directory:** `/services/isbn-price-lookup`  
**Backend (Railway):** `https://isbn-price-lookup-production.up.railway.app`  
**Apps Script ID:** `1BFD8GqtWoXUf8t052cYl7RhZxpvAzK__aPw3CpWIfXEbDqouLsMtFSTG`

---

## Overview

Publisher Price Injector is a Google Sheets **Internal Marketplace Add-on** that fills a `List Price` column by looking up ISBNs against Shopify product barcodes. It is designed for publisher returns workflows where pricing data must be injected into spreadsheets originating outside Shopify.

The add-on provides a **single-click, non-technical workflow** while maintaining strict security, versioning, and rollback guarantees.

---

## User Experience

After installation:

1. Open any Google Sheet
2. Ensure the sheet contains headers:
   - `ISBN`
   - `List Price`
3. Navigate to:

```
Extensions → Publisher Price Injector → Inject Shopify List Prices
```

4. The add-on:
   - Collects ISBNs from rows where `List Price` is empty
   - Queries the backend service
   - Writes prices into the corresponding cells
   - Writes `NOT FOUND` when no match exists

A toast notification confirms completion.

---

## Architecture

### Components

1. **Google Sheets Add-on (Apps Script)**
   - Reads spreadsheet data
   - Batches ISBNs
   - Calls backend API
   - Writes results to the sheet

2. **Backend Service (Railway)**
   - Endpoint: `/isbn/prices`
   - Auth: `X-ISBN-PRICE-SECRET`
   - Queries Shopify Admin API (GraphQL)
   - Matches ISBN → `product.barcode`
   - Returns scalar pricing data

3. **Shopify Admin API**
   - Accessed using existing environment variables:
     - `SHOP_URL`
     - `SHOPIFY_ACCESS_TOKEN`
     - `SHOPIFY_API_VERSION`

---

## Security Model Shift

This project required transitioning from a **container-bound Apps Script** (implicit trust) to a **Workspace Marketplace Add-on**, which operates under a **zero-trust distribution model**.

Marketplace Add-ons require:
- Explicit OAuth identity binding
- Versioned deployments
- Manifest-enforced security
- Store listing metadata

---

## Key Failure Modes and Resolutions

### 1. AuthMode Deadlock (Help-only State)

Marketplace Add-ons initially load in `AuthMode.NONE`, restricting access to authenticated services and UI construction.

**Resolution**
- Implemented `onInstall(e)` calling `onOpen(e)`
- Used `createAddonMenu()` (Sheets Add-on hook)
- Kept menu construction minimal to allow Google to attach the menu before OAuth is granted

---

### 2. Manifest Enforcement for Outbound Requests

Once linked to a user-managed GCP project, outbound network calls are subject to runtime security enforcement.

**Resolution**
- Added the Railway production URL to the Apps Script manifest allowlist
- Enabled `UrlFetchApp` to communicate with the backend

---

### 3. Marketplace SDK ↔ Script Version Sync

Code changes in the Apps Script editor do not affect installed users until a **new numbered deployment** is created and referenced by the Marketplace SDK.

**Resolution**
- Established a strict deployment pipeline:
  1. Update code or manifest
  2. Create a new Add-on deployment (numbered)
  3. Update Marketplace SDK to point to that version

---

### 4. Store Listing and Internal Visibility

Internal Marketplace apps remain invisible until all required listing metadata and assets are present.

**Resolution**
- Completed Store Listing with required icons, banner, screenshot, and URLs
- Published as **Internal**, making the app discoverable under “My domain apps”

---

### 5. OAuth Identity Binding (`401: deleted_client`)

Deleting the OAuth client in GCP breaks the Apps Script identity binding.

**Resolution**
- Migrated to a fresh GCP project
- Re-linked the Apps Script project via project number
- Generated a clean OAuth client consistent with Internal consent settings

---

## Technical Summary Table

| Problem | Symptom | Root Cause | Resolution |
|------|------|------|------|
| Invisible menu | Help-only | AuthMode.NONE | `onInstall` + `createAddonMenu` |
| Network blocked | Fetch failure | Runtime policy | Manifest allowlist |
| Changes not live | Old behavior | Version mismatch | New deployment + SDK update |
| App not discoverable | Missing listing | Incomplete metadata | Store listing completion |
| 401 Unauthorized | Auth blocked | Orphaned OAuth client | Fresh GCP project |

---

## Non-Technical User Guide

### Requirements
- Google Workspace account in the approved domain
- Add-on installed (or admin-installed)
- Sheet headers:
  - `ISBN`
  - `List Price`

### Usage
1. Open the spreadsheet
2. Verify headers
3. Run:
   ```
   Extensions → Publisher Price Injector → Inject Shopify List Prices
   ```
4. Review results

### Interpreting `NOT FOUND`
- ISBN missing or malformed
- No matching Shopify barcode
- Product exists but barcode is absent

---

## SOP: Updating Publisher Price Injector

### A. Backend-only Changes (Railway)

If modifying pricing logic **without** changing:
- Endpoint URL
- Request/response shape
- Auth header name

**Action**
- Deploy to Railway

**Result**
- Changes take effect immediately
- No Apps Script or Marketplace changes required

---

### B. Add-on Changes (Apps Script)

If changing:
- Menu items
- Sheet write behavior
- Headers
- External URLs
- OAuth scopes or manifest

**Steps**
1. Edit `Code.gs` or `appsscript.json`
2. Create a **new Add-on deployment**
3. Record the new version number
4. Update Marketplace SDK → Sheets add-on version
5. Save

---

### C. Verification and Rollback

- **Verify:** Run the add-on in a fresh Sheet (allow 5–10 min cache)
- **Rollback:** Point Marketplace SDK back to the previous version and save

---

## Maintenance Cheat Sheet

| Change Type | New Deployment | SDK Version Update |
|---|---|---|
| Menu/UI change | Yes | Yes |
| New external URL | Yes | Yes |
| Backend logic only | No | No |
| Shared secret rotation | Script Properties | No |
| New OAuth scope | Yes | Yes (re-auth required) |

---

## Safety Constraints

- Do not change the Script ID without planning a new Marketplace listing
- Never point Marketplace to `HEAD`
- Avoid deleting OAuth clients in GCP
- Always allowlist new outbound URLs

---

## Locations

- **Repository:** `kitchenartsandletters/sr-ops-suite`
- **Service Path:** `/services/isbn-price-lookup`
- **Marketplace App:** Publisher Price Injector (Internal)

---

## Appendix: Internal vs Public Marketplace Apps

### Internal Apps
- Domain-only distribution
- Metadata + assets still required
- Minimal documentation acceptable
- No external review

### Public Apps
- Subject to Google review
- Stronger privacy language required
- Branding and documentation expected
- Verification delays should be planned

---

End of README.