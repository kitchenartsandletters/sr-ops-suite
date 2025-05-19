# sr-ops-suite

*sr-ops-suite* is a suite of Slack applications for shipping and receiving workflows. The “sr” prefix stands for Shipping & Receiving. Tools in the suite will help communicate about backorders, preorders, daily inventory tracking, order collection and exports—all without leaving Slack.

---

## What It Does

- **Backorders Dashboard** (`#sr-backorders` channel):  
  A dedicated Slack channel for team-wide backorder discussions and notifications.

- **Display Current Backorders** (`/sr-back`):  
  Display and refresh a detailed, paginated view of current backorders by line item.

- **Update ETA** (`/sr-update-eta`):  
  Update the estimated arrival date for a backordered item, accepting `YYYY-MM-DD` format.

- **Fulfill ISBN** (`/sr-fulfill-isbn`):  
  Mark all open backorders for a given ISBN as fulfilled.

- **Override Backorder** (`/sr-override`):  
  Manually override a backorder entry’s status.

- **Fulfilled List** (`/sr-fulfilled-list`):  
  List the last 10 items manually marked fulfilled.

- **Undo Fulfillment** (`/sr-undo`):  
  Undo a specific manually marked fulfilled entry.

- **Quick Backorder Summary** (`/sr-back-list`):  
  Generates a one-line-per-SKU summary of backorders with total quantities per product in App Home. CSV downloadable.

- **Fulfill Orders** (`/sr-fulfill-order`):  
  Handle bulk order fulfillment by order number.

- **Fulfill Items** (`/sr-fulfill-item`):  
  Fulfill a specific ISBN on a given order.

- **Export CSV** (`Export CSV` button in App Home):  
  Download the full backorders list as a CSV file.

> *Note:* Although slash commands can be run in any channel or DM, the `#sr-backorders` Slack channel is intended for team-wide communication and notifications. Other commands (e.g. `/sr-fulfill-order` or `/sr-update-eta`) may be run in any channel or DM as needed.

---

## Installing in Slack

1. **Desktop**  
   - Go to your Slack workspace’s App Directory.  
   - Click **Add apps**.  
   - Search for *sr-ops-suite* and click **Add to Slack**.

2. **Mobile**  
   - Open Slack mobile app.  
   - Tap **Apps** (•••), search for *sr-ops-suite*, and install.

---

## Using Slash Commands

Type commands anywhere the app is invited. Don’t include brackets—just replace placeholders:

- **`/sr-back [sortKey]`**  
  Detailed, paginated backorders in App Home.  
  _Example:_ `/sr-back` or `/sr-back sort:title`  
  _Accepted Clauses:_ `sort:title`, `sort:age`, `sort:vendor`

- **`/sr-back-list`**  
  Quick one-line-per-SKU summary in App Home. Includes CSV export.  
  _Example:_ `/sr-back-list`

- **`/sr-fulfilled-list`**  
  List the last 10 items manually marked fulfilled. Used with `/sr-undo`.  
  _Example:_ `/sr-fulfilled-list`

- **`/sr-fulfill-item [orderNumber] [isbn]`**  
  Fulfill a specific ISBN on an order.  
  _Example:_ `/sr-fulfill-item 60166 9780316580915`

- **`/sr-fulfill-order [orderNumber]`**  
  Fulfill all items in a given order.  
  _Example:_ `/sr-fulfill-order 60166`

- **`/sr-fulfill-isbn [isbn]`**  
  Fulfill all backorders for a given ISBN.  
  _Example:_ `/sr-fulfill-isbn 9780316580915`

- **`/sr-override [orderNumber] [lineItemId] [action] [reason]`**  
  Override a backorder entry’s status or quantities.  
  _Example:_ `/sr-override 57294 13059031040133 clear preorder`

- **`/sr-undo [overrideId]`**  
  Undo a specific manually marked fulfillment.  
  _Example:_ `/sr-undo 12345`

- **`/sr-update-eta [orderNumber] [isbn] [YYYY-MM-DD]`**  
  Update ETA for a backorder item (strict ISO date).  
  _Example:_ `/sr-update-eta 60166 9780316580915 2025-06-01`
  _Example:_ `/sr-update-eta 9780316580915 2025-06-01`

- **`/sr-help`**  
  Open a searchable help modal listing all commands with examples.  

---

## How App Home Works

- **App Home** is your persistent dashboard under **Apps → sr-ops-suite**.  
- Run `/sr-back` or `/sr-back-list` to refresh the detailed or quick summary dashboard.  
- **Other slash commands** display ephemeral messages directly in the invoking channel or DM.

---

## Detailed vs. Quick Views

1. **Detailed View** (`/sr-back`)  
   - Shows backorder line-item details with pagination and sorting.  
   - Includes buttons: Sort by Title, Mark Fulfilled, Update ETA, Clear ETA.

2. **Quick Summary** (`/sr-back-list`)  
   - One line per SKU: ISBN • Title • Oldest • Newest • Qty • Vendor • ETA  
   - Includes buttons: Sort by Title, Export CSV, View Help Docs  
   - Per-row actions: Mark Fulfilled, Update ETA, Clear ETA (if ETA present).

---

## Ephemeral vs. Visible Blocks

- **Ephemeral blocks**: visible only to you; used for confirmations and notices.  
- **Visible blocks**: appear in channels or App Home and persist; used for dashboards.

---
