# sr-ops-suite

**sr-ops-suite** is a suite of Slack applications for shipping and receiving workflows. The “sr” prefix stands for **Shipping & Receiving**. Tools in the suite will help communicate about backorders, preorders, daily inventory tracking, order collection and exports—all without leaving Slack.

---

## What It Does

- **Backorders Dashboard** (`#sr-backorders` channel):  
  A dedicated Slack channel for team-wide backorder discussions and notifications.
  
- **Display Current Backorders in a Detailed View** (`/sr-back`):
  Display and refresh a detailed, paginated view of current backorders by line item.

- **Update ETA** (`/sr-update-eta`):  
  Update the estimated arrival date for a backordered item.

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

> **Note:** Although slash commands can be run in any channel or DM, the `#sr-backorders` Slack channel is intended for team-wide communication and notifications. Other commands (e.g. `/sr-fulfill-order`) may be run in any channel or DM as needed.

---

## Installing in Slack

1. **Desktop**  
   - Go to your Slack workspace’s App Directory.
   - Select [+] Add apps  
   - Search for **sr-ops-suite** or find "Sr-Ops-Suite" in the Apps list
   - Select the App and click **Add to Slack**.

2. **Mobile**  
   - Open Slack mobile app.  
   - Tap **Apps** (•••), search for **sr-ops-suite**, and install.

---

## Using Slash Commands

Type commands anywhere the app is invited. Don’t include brackets—just replace placeholders:

- **`/sr-back [sortKey]`**  
  Detailed, paginated backorders in App Home  
  _Example:_ `/sr-back` or `/sr-back sort:title`
  _Accepted Clauses:_ `sort:title`, `sort:age`, `sort:vendor`

- **`/sr-update-eta [orderId] [isbn] [date]`**  
  Update a backorder’s ETA for a specific order and ISBN  
  _Example:_ `/sr-update-eta 60166 9780316580915 06/01/2025`

- **`/sr-fulfill-isbn [isbn]`**  
  Fulfill all backorders for a given ISBN  
  _Example:_ `/sr-fulfill-isbn 9780316580915`

- **`/sr-override [orderId] [lineItemId] [action] [reason]`**  
  Override a backorder’s entry (e.g. a preorder is listed as backordered) 
  _Example:_ `/sr-override 60166 13059031040133 clear preorder`
  _Example:_ `/sr-override 60166 13059031040133 restore preorder`

- **`/sr-fulfilled-list`**  
  List the last 10 items manually marked fulfilled. Used to feed /sr-undo or reference recent actions.  
  _Example:_ `/sr-fulfilled-list`

- **`/sr-undo [overrideId]`**  
  Undo a specific manually marked fulfilled entry. Used in conjuction with /sr-fulfilled-list.  
  _Example:_ run `/sr-fulfilled-list` a generated number list is populated then to undo: /sr-undo <number> [reason]

- **`/sr-back-list`**  
  Quick, one-line-per-SKU summary in App Home. Includes Export CSV capability.
  _Example:_ `/sr-back-list`

- **`/sr-fulfill-order [orderId]`**  
  Handle bulk order fulfillment. Marks fulfilled all open items in a specific order.
  _Example:_ `/sr-fulfill-order 60166`

- **`/sr-fulfill-item [orderId] [isbn]`**  
  Fulfill a specific ISBN on an order. Marks fulfilled all items with entered ISBN in a specific order.
  _Example:_ `/sr-fulfill-item 60166 9780316580915`


## How App Home Works

- **App Home** is your persistent dashboard under **Apps → sr-ops-suite**.  
- Run `/sr-back` or `/sr-back-list` to refresh the detailed or quick summary dashboard.
- **Other slash commands** (e.g. `/sr-update-eta`, `/sr-override`, `/sr-fulfill-order`, etc.) display **ephemeral messages** directly in the channel or DM where they are invoked.

---

## Detailed vs. Quick Views

1. **Detailed View** (`/sr-back`)  
   - Shows each backorder line item with order details.  
   - Supports pagination and sorting.
   - Includes **Sort by Title**, **Mark Fulfilled**, **Update ETA**, and **Clear ETA** buttons
   - Accepts sorting tokens: `sort:title`, `sort:age`, and `sort:vender`

2. **Quick Summary** (`/sr-back-list`)  
   - One line per SKU:  
     `ISBN • Title • Oldest • Newest • Qty • Vendor`  
   - Includes an **Export CSV** button.

---

## Ephemeral vs. Visible Blocks

- **Ephemeral blocks**: visible only to you; used for confirmations and notices.  
- **Visible blocks**: appear in channels or App Home and persist; used for dashboards.

---
