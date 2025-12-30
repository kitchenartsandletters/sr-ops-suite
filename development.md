# sr-ops-suite — Development Notes

This document locks in design, scope, and sequencing decisions for ongoing operational reporting tools.

---

## LOP Unfulfilled Report — Canonical Design

The `lop_unfulfilled_report` is evolving into a first-class operational report, parallel to `daily_sales_report`.

It serves **three distinct operational audiences**, each with a dedicated view.

---

## 1. ORDER VIEW (Picker / Ops-Facing)

**Purpose:**  
Show exactly what needs to be picked, packed, or investigated right now.

**Characteristics:**
- One row per **order × line item**
- Preserves order context (order number, notes)
- Highlights operational complexity

**Planned Enhancements:**
- Highlight rows when:
  - Quantity > 1
  - Notes are present
  - Mixed availability exists
- Add an **Attributes** column to the right of Notes:
  - Signed
  - Bookplate
  - Preorder OR Backorder (mutually exclusive)

Attributes should be derived using the same logic as `daily_sales_report`.  
**Has Notes** is NOT an attribute and is intentionally excluded.

---

### Preorder vs Backorder — Mutually Exclusive Classification

---
A product line item can be **either** a Preorder **or** a Backorder — never both.

• **Preorder**
  - Determined strictly by catalog state
  - Product belongs to a collection whose name contains "Preorder"
  - Inventory levels are ignored

• **Backorder**
  - Determined strictly by inventory state
  - Product inventory is ≤ 0
  - Product is *not* in a Preorder collection

This mirrors the logic used in `daily_sales_report` and is the canonical classification rule.
---

---

## 2. TOTAL QUANTITY VIEW (Procurement-Facing)

**Purpose:**  
Provide a pure, article-agnostic view of total quantities required, regardless of orders.

**Structural Rules:**
- Appears *after* ORDER VIEW
- Preceded by a header row:

  ```
  TOTAL QUANTITY VIEW
  ```

**Column Schema (Locked):**

| Column | Name |
|------|------|
| A | QTY |
| B | Product |
| C | Author |

Notes:
- Rename **SKU → Author** everywhere
- Move quantity to column A for visual priority

**Sorting Rules (Locked):**
1. QTY descending
2. Product title, article-agnostic  
   (ignore leading “The”, “A”, “An”; Unicode-normalized)

---

## 3. AGGREGATE / EXCEPTIONS VIEW (Manager-Facing)

**Purpose:**  
Surface orders that cannot be wholly fulfilled and require decisions.

---
**Out-of-Print (OP) titles**
- Are identified by titles prefixed with "OP:"
- Represent a catalog state, not an inventory state
- Are never oversold by definition
- Can never cause an order to appear in INCOMPLETE ORDERS
- Must always be excluded from Preorder, Backorder, and Incomplete Orders logic
---

**Planned Structure:**
```
INCOMPLETE ORDERS
Order # | Product | Author | QTY | REASON
```

**REASON Examples:**
- Backorder
- Preorder
- Mixed availability
- Requires decision

This view should be separate from ORDER VIEW.

---

## CSV vs PDF Responsibilities

### CSV (Canonical Source)
- Contains all logic, classification, and aggregation
- Drives all downstream outputs
- Must remain deterministic and auditable
- Attributes column is canonical and must be populated before any PDF work begins.

### PDF (Presentation Layer)
- Consumes structured CSV-equivalent data
- Adds visual emphasis only
- Must never re-derive business logic

---

## Classification Architecture (Future-Proofing)

Introduce a shared helper:

```python
def classify_line_item(...):
    return {
        "is_preorder": bool,
        "is_backorder": bool,
        "is_signed": bool,
        "availability": "available | partial | blocked",
        ...
    }
```

This helper should be reused by:
- `lop_unfulfilled_report`
- `daily_sales_report`
- Future dashboards and services

---

## Explicitly Deferred (Do NOT Implement Yet)

The following are intentionally postponed:

- FulfillmentOrder (FO)–based logic
- Inventory allocation math (splitting quantities)
- Row-splitting in PDFs
- Over-optimization of fulfillment states

Sequencing matters. These come later.

---

## Current Priority Order

1. CSV Phase 1–2  
   - ORDER VIEW header
   - TOTAL QUANTITY VIEW with locked schema + sorting
2. CSV Phase 3  
   - Attributes column
3. PDF builder scaffold (`lop_unfulfilled_pdf.py`)
4. Aggregate / Incomplete Orders view
5. Allocation-aware quantity splitting (future phase)

---

**Status:**  
This document represents a locked design agreement as of December 2025.
