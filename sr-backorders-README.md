# sr-ops-suite

**sr-ops-suite** is a suite of Slack applications for shipping and receiving workflows. The “sr” prefix stands for **Shipping & Receiving**. Tools in the suite will help communicate about backorders, preorders, daily inventory tracking, order collection and exports—all without leaving Slack.

---

## What It Does

- **Backorders Dashboard** (`#sr-backorders` channel):  
  A dedicated Slack channel for team-wide backorder discussions and notifications. Use the `/sr-back` slash command to refresh a detailed, paginated view of current backorders by line item.

- **Update ETA** (`/sr-update-eta`):  
  Update the estimated arrival date for a backordered item.

- **Fulfill ISBN** (`/sr-fulfill-isbn`):  
  Mark all open backorders for a given ISBN as fulfilled.

- **Override Backorder** (`/sr-override`):  
  Manually override a backorder entry’s status or quantities.

- **Fulfilled List** (`/sr-fulfilled-list`):  
  List the last 10 items manually marked fulfilled.

- **Undo Fulfillment** (`/sr-undo`):  
  Undo a specific manually marked fulfilled entry.

- **Quick Backorder Summary** (`/sr-back-list`):  
  Generates a one-line-per-SKU summary of backorders with total quantities per product in App Home.

- **Fulfill Orders** (`/sr-fulfill-order`):  
  Handle bulk order fulfillment by order ID.

- **Fulfill Items** (`/sr-fulfill-item`):  
  Fulfill a specific ISBN on a given order.

- **Export CSV** (`Export CSV` button in App Home):  
  Download the full backorders list as a CSV file.

---

## Installing in Slack

1. **Desktop**  
   - Go to your Slack workspace’s App Directory.  
   - Search for **sr-ops-suite** and click **Add to Slack**.

2. **Mobile**  
   - Open Slack mobile app.  
   - Tap **Apps** (•••), search for **sr-ops-suite**, and install.

---

> **Note:** Although slash commands can be run in any channel or DM, the `/sr-backorders` command is intended for team-wide communication and notifications and is typically used in the dedicated `#sr-backorders` Slack channel. Other commands (e.g. `/sr-fulfill-order`) may be run in any channel or DM as needed.

## Using Slash Commands

Type commands anywhere the app is invited. Don’t include brackets—just replace placeholders:

- **`/sr-back [page] [sortKey]`**  
  Detailed, paginated backorders in App Home  
  _Example:_ `/sr-back` or `/sr-back 2 title`

- **`/sr-update-eta [orderId] [isbn] [date]`**  
  Update a backorder’s ETA for a specific order and ISBN  
  _Example:_ `/sr-update-eta 60166 9780316580915 06/01/2025`

- **`/sr-fulfill-isbn [isbn]`**  
  Fulfill all backorders for a given ISBN  
  _Example:_ `/sr-fulfill-isbn 9780316580915`

- **`/sr-override [orderId] [isbn] [qty]`**  
  Override a backorder’s quantity  
  _Example:_ `/sr-override 60166 9780316580915 5`

- **`/sr-fulfilled-list`**  
  List the last 10 items manually marked fulfilled  
  _Example:_ `/sr-fulfilled-list`

- **`/sr-undo [overrideId]`**  
  Undo a specific manually marked fulfilled entry  
  _Example:_ `/sr-undo 12345`

- **`/sr-back-list`**  
  Quick, one-line-per-SKU summary in App Home  
  _Example:_ `/sr-back-list`

- **`/sr-fulfill-order [orderId]`**  
  Handle bulk order fulfillment  
  _Example:_ `/sr-fulfill-order 60166`

- **`/sr-fulfill-item [orderId] [isbn]`**  
  Fulfill a specific ISBN on an order  
  _Example:_ `/sr-fulfill-item 60166 9780316580915`


## How App Home Works

- **Slash commands** trigger updates in **App Home**.  
- **App Home** is your persistent dashboard under **Apps → sr-ops-suite**.  
- Run `/sr-backorders` or `/sr-backorders-summary` to refresh the Home view.

---

## Detailed vs. Quick Views

1. **Detailed View** (`/sr-backorders`)  
   - Shows each backorder line item with order details.  
   - Supports pagination and sorting.

2. **Quick Summary** (`/sr-backorders-summary`)  
   - One line per SKU:  
     `ISBN • Title • Oldest • Newest • Qty • Vendor`  
   - Includes an **Export CSV** button.

---

## Ephemeral vs. Visible Blocks

- **Ephemeral blocks**: visible only to you; used for confirmations and notices.  
- **Visible blocks**: appear in channels or App Home and persist; used for dashboards.

---

## Keeping the README Accessible

- **Project repo**: `README.md` at the root will render in GitHub/GitLab.  
- **Editor sidebar**: use a Markdown sidebar plugin in VS Code.  
- **Confluence/Notion**: paste Markdown into a shared page.  
- **Slack Shortcut**: create a global shortcut to open or DM this README link.
