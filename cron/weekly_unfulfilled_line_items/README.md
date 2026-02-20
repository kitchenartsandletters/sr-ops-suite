# Weekly Unfulfilled Line Items Cron Worker

This Railway Worker executes the `weekly_unfulfilled_line_items_report.py` script on a schedule.

## Purpose

Generates and emails the Weekly Unfulfilled Line Items report:

- Only unfulfilled line items
- Canonical committed-inventory model
- Age (days) + heatmap column
- Excludes Preorder collection
- Applies blacklist rules

Output:
- weekly_unfulfilled_line_items_YYYYMMDD_HHMMSS.csv

No PDF companion.
No product summary report.

---

## Deployment

1. Push repo to GitHub.
2. In Railway, create a new service:
   - "Deploy from GitHub repo"
   - Select directory: `cron/weekly_unfulfilled_line_items`
3. Railway builds using the Dockerfile.
4. Add required environment variables:

Required Shopify:
- SHOP_URL
- SHOPIFY_ACCESS_TOKEN
- SHOPIFY_API_VERSION

Required Mailtrap:
- MAILTRAP_API_TOKEN
- EMAIL_SENDER
- EMAIL_RECIPIENTS

---

## Recommended Cron Schedule

Example: Every Friday 10:00 AM ET

UTC equivalent: