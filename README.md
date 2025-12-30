# SR Ops Suite — Reporting & Operations Toolkit

Admin Dashboard–driven Shipping & Receiving operations toolkit for **Kitchen Arts & Letters (KAL)**.

This repository contains a set of **authoritative operational reporting scripts** built on Shopify’s Admin GraphQL API.  
All reports are business‑calendar aware, inventory‑correct, and designed to support real‑world bookstore operations.

---

## 1. Core Design Principles

- **Business‑defined time windows** (not calendar days)
- **GraphQL‑only** (REST + FulfillmentOrders deprecated)
- **CSV is canonical**; PDF is presentation
- **Committed inventory is the sole source of truth** for unfulfilled quantities
- Explicit avoidance of inference, heuristics, or legacy Shopify abstractions
- All logic is auditable against Shopify Admin UI

---

## 2. Reporting Modules (Authoritative Map)

| Module | File | Purpose |
|------|------|--------|
| Daily Sales Report | `daily_sales_report.py` | Business‑day sales & inventory posture |
| Daily Sales PDF | `daily_sales_pdf.py` | Printable presentation layer |
| Weekly Maintenance | `weekly_maintenance_report.py` | Inventory & catalog hygiene audits |
| LOP Unfulfilled Orders | `lop_unfulfilled_report.py` | Order‑level fulfillment execution since last LOP |

Each module has a **single responsibility**. Logic does not overlap.

---

## 3. Business Calendar (Shared Foundation)

**File:** `business_calendar.py`

This module defines the *true operating calendar* for KAL.

### Rules
- Regular open days: **Monday–Saturday**
- Sundays closed **except special December Sundays**
- Annual holiday closures are explicitly defined
- Returns **date boundaries only** (no time logic)

### Key Functions
- `is_business_day(d)`
- `find_last_open_day(today)`
- `get_reporting_window(today) → (start_date, end_date)`

### Time Expansion
All scripts expand dates into timestamps using:

```
Start: 10:00 AM ET on start_date
End:   9:59:59 AM ET on end_date
```

This ensures operational alignment with KAL’s daily workflow.

---

## 4. Daily Sales Report (Canonical Specification)

**File:** `daily_sales_report.py`

### Purpose
Generate a **daily, business‑accurate sales report** grouped by product and inventory posture.

### Reporting Window
On any valid business day run, the report covers:

```
Start: 10:00 AM ET on the last open business day
End:   9:59:59 AM ET on the day of the report
```

Closed days (weekends, holidays) are automatically included.

### Inventory Buckets
Products are categorized into:

1. **Main Sales** — inventory > 0
2. **Backorders** — inventory < 0
3. **Out of Stock** — inventory == 0
4. **Preorders** — products in the “Preorder” collection (inventory‑agnostic)

### CSV Columns (Canonical)
- Title (article‑stripped, unicode‑normalized)
- Author (derived from SKU)
- Vendor
- ISBN (barcode)
- Price
- Collections
- On‑Hand Inventory
- Incoming Inventory
- Online Sold
- POS Sold
- Attributes (Signed, Bookplate, etc.)
- Notes

### Non‑Goals
- Not an order‑level fulfillment audit
- Not a reconciliation tool
- Not dependent on FulfillmentOrders

---

## 5. Daily Sales PDF

**File:** `daily_sales_pdf.py`

The PDF mirrors CSV content with enhanced readability:

- Clean, Shopify‑style tables
- Unicode‑safe rendering (DejaVuSans)
- Wrapped titles/authors
- Secondary gray rows for metadata
- Page headers with:
  - Report name
  - Report date
  - Reporting window
  - Pagination

PDFs are **presentation only**. CSV remains canonical.

---

## 6. Weekly Maintenance Report (Unified Inventory Model)

**File:** `weekly_maintenance_report.py`

### Canonical Rule

> **Unfulfilled Quantity = Shopify Committed Inventory**

Derived exclusively from:

```
InventoryLevel.quantities(names: ["committed"])
```

### Why FulfillmentOrders Are Deprecated

| Method | Issues | Status |
|------|-------|-------|
| FulfillmentOrders | Partial fulfillment drift, merges/splits, legacy artifacts | ❌ Deprecated |
| Committed Inventory | Internal Shopify source of truth | ✅ Canonical |

### Reports Generated

1. **Negative inventory, no unfulfilled orders**
2. **Published products with no collections**
3. **Out‑of‑stock or negative inventory with unfulfilled orders (non‑Preorder)**

All logic matches Shopify Admin inventory math exactly.

---

## 7. LOP Unfulfilled Orders Report

**File:** `lop_unfulfilled_report.py`

### Purpose
Identify **orders requiring shipping execution** since the most recent order tagged `LOP`.

### How It Works
1. Locate most recent order tagged `LOP`
2. Fetch all subsequent orders
3. Post‑filter strictly by `createdAt` timestamp
4. Exclude fulfilled, digital, or pickup‑only orders
5. Output order‑level CSV for shipping action

This script is **operational**, not analytical.

---

## OP Titles (Out-of-Print) — Explicit Fulfillment Exclusion

### Definition

**OP = Out-of-Print**, identified by titles prefixed with:

```
OP:
```

This prefix is the **single source of truth** for OP classification.  
OP is a **catalog state**, not an inventory state.

---

### Core Invariant

> **OP (Out-of-Print) titles can never be oversold by definition.**

Because OP titles represent finite, already-owned stock:
- They are never replenished
- They are never sold beyond physical availability
- They are typically surfaced for archival or special-request sales

---

### Operational Consequences

OP titles **never participate in**:
- Preorder detection
- Backorder detection
- Inventory-driven exception logic
- Incomplete Orders classification
- Mixed-availability allocation logic

Even if:
- Inventory is low
- Quantity > 1
- The order contains other problematic (non-OP) items

OP titles are **always considered fulfillable** within their known constraints.

---

### Relationship to Incomplete Orders

**Incomplete Orders** are strictly operational exceptions.

An order is considered *Incomplete* only when **non-OP** line items:
- Are Preorders, or
- Are Backorders, or
- Are otherwise unavailable due to inventory state

> **Any line item whose title begins with `OP:` is categorically excluded from Incomplete Orders logic.**

OP items:
- Never cause an order to appear in the Incomplete Orders section
- Never appear in the OP / Incomplete Orders spin-off section
- Never contribute to fulfillment risk classification

---

### Reporting Behavior

**ORDER VIEW**
- OP items appear as normal line items
- They may display quantity, notes, and attributes
- They do **not** affect availability classification

**OP / Incomplete Orders Section**
- OP items never appear
- OP items never trigger inclusion
- This section reflects **operational risk only**, not catalog intent

---

### Summary

- OP = Out-of-Print
- Identified by the `OP:` prefix
- OP titles are never oversold
- OP titles are excluded from:
  - Preorder logic
  - Backorder logic
  - Incomplete Orders detection
- Incomplete Orders reflect **inventory and preorder risk only**
- OP is a **deliberate catalog classification**, not an operational exception

---

## 8. Output & Delivery

### Files
- CSVs written to project root or `output/`
- PDFs generated alongside CSVs

### Email Delivery
If **not** run with `--dry-run`, reports are emailed via Mailtrap.

Required environment variables:

```
MAILTRAP_API_TOKEN
EMAIL_SENDER
EMAIL_RECIPIENTS
```

During development, `--dry-run` prevents email sending.

---

## 9. Future Development (Non‑Binding)

Planned (not yet implemented):

- PDF companion for LOP Unfulfilled Report
- Aggregate vs Order View enhancements
- Admin Dashboard notifications and controls
- Admin UI triggers
- Persistent storage (Supabase)

These are **roadmap items**, not part of current guarantees.

---

## 10. Summary

This repository provides:

- Accurate, calendar‑aware reporting
- Inventory‑correct logic aligned with Shopify Admin
- Clean CSV + PDF outputs
- Clear separation of concerns
- A stable foundation for future operational tooling

**This README is the single authoritative reference.**
