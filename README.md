# SR Ops Suite

Slack-driven Shipping & Receiving operations toolkit.

---

# Weekly Maintenance Report — Inventory & Order Hygiene  
### *(Unified Committed-Inventory Edition — December 2025)*

The Weekly Maintenance Report generates three automated CSVs that surface inventory and catalog risks.  
As of December 2025, the report uses a **single, canonical source of truth** for determining unfulfilled orders:

---

# 🧭 **Unfulfilled Quantity = Shopify Admin “Committed” Inventory**  
### (No FulfillmentOrders API; no inference; no approximation — direct committed counts only)

---

## ⭐ Why we switched to committed inventory

Shopify’s **committed inventory** represents units that:

- Have been sold (an order exists)
- Have not been fulfilled  
- Are reserved against available stock  
- Directly influence whether a title is oversold or backordered  

Shopify defines *committed* as the quantity of inventory tied to an **unfulfilled line item**.  
This is **exactly** the number shown in the Shopify Admin inventory UI.

Because Shopify’s FulfillmentOrders can be:

- partially fulfilled,
- misaligned with historical fulfillment behavior,
- merged/split by Shopify internally,
- or contain legacy fulfillment remnants,

they cannot be considered a reliable primary source of truth.

The committed inventory quantity, however, is **the one consistent, authoritative state** maintained internally by Shopify and exposed via **InventoryLevel.quantities(names: ["committed"])**.

---

# 🧱 **How the Script Works Now (Unified System)**

### 1. Load all active products  
Using the GraphQL Admin API:

- Up to 20 variants per product  
- For each variant → fetch:
  - `inventoryItem`
  - `inventoryLevels(first: 10)`
  - `quantities(names: ["committed"])`

### 2. Build a product → unfulfilled_qty map  
```
prod_to_unfulfilled_qty[product_id] = sum_of_all_committed_quantities
```

This includes all locations, all variants.

### 3. Use this map for all three reports  
Every maintenance report relies on:

- `p.totalInventory` (Shopify’s aggregated availability across all locations)
- `prod_to_unfulfilled_qty[pid]` (committed, i.e., open orders)

No fulfillment-order logic remains in the script.

---

# 📦 **Report Definitions (Post-Migration)**

## **Report 1 — Negative inventory, no unfulfilled orders**
A product appears here when:

- `totalInventory < 0`  
- `committed == 0`  
- Not blacklisted  

Indicates a *possible manual adjustment* or *past mismatch* that has not corrected itself via orders.

---

## **Report 2 — Published but not in any collections**
Unchanged logic — looks for:

- Product is ACTIVE + Online Store URL exists  
- No collections attached  
- Not blacklisted  

---

## **Report 3 — Out-of-stock/negative inventory with unfulfilled orders (non-Preorder)**  
A product appears here when:

- `committed > 0`  
- `totalInventory <= 0`  
- Not in the “Preorder” collection  
- Not blacklisted  

### Status classification:
| Condition | Backorder Status |
|----------|------------------|
| `totalInventory < 0 and committed > 0` | `backorder` |
| `totalInventory == 0 and committed > 0` | `pending_fulfillment` |
| Else | `""` (not included) |

This aligns exactly with Shopify Admin behavior.

---

# 🔍 Debugging / Verification

### To verify results for a single product:

1. Open Shopify Admin → Product → Inventory  
2. Check:
   - **Available**
   - **Committed**
   - **On-hand**
3. Confirm `committed` matches:
   - `Unfulfilled Qty` in the CSV  
4. Confirm `available + committed` matches Shopify’s total inventory math:
   - If `totalInventory = -3`, Shopify Admin will show:
     - Available = -3  
     - Committed = 3  

These states are now directly reflected in our report.

---

# 🧪 Why this system is more reliable than FO-based logic

| Method | Problems | Current Status |
|--------|----------|-----------------|
| **FulfillmentOrders (FOs)** | Slow, inconsistent, partial cancellations, legacy behavior, Shopify merges/splits FOs silently | ❌ Deprecated from our logic |
| **Committed Inventory (InventoryLevel.quantities)** | True internal Shopify source of unfulfilled units | ✅ Canonical system |

This eliminates:
- Partial fulfillment detection issues  
- Orders where the FO does not align with historical fulfillment  
- Race conditions  
- Missing updates from cancelled-but-partially-fulfilled sequences  
- Shopify internally creating new FOs that the API does not surface predictably  

---

# 🧬 Environment Requirements

- `read_inventory` scope required for committed quantities  
- `read_products` required  
- **GraphQL only** — REST inventory endpoints no longer recommended  

---

# 📂 Output Files

Generated into `output/`:

- `weekly_negative_no_orders_YYYYMMDD.csv`
- `weekly_published_no_collections_YYYYMMDD.csv`
- `weekly_oos_unfulfilled_not_preorder_YYYYMMDD.csv`

---

# 📨 Email Delivery

If not run with `--dry-run`, all three CSVs are emailed via Mailtrap using:

```
MAILTRAP_API_TOKEN  
EMAIL_SENDER  
EMAIL_RECIPIENTS  
```

---

# 🛠 Future-Proofing Notes

This architecture is stable because:

- Shopify’s inventory states system is mature and not subject to FO churn.
- Inventory quantities are central to their internal accounting system.
- This will remain consistent across API versions.

If Shopify updates inventory states, this approach will still work.

---