# Daily Sales Report Cron Worker

This Railway Worker executes the `weekly_maintenance_report.py` script on a schedule.

## Deployment

1. Push your repo to GitHub.
2. In Railway, create a new service:
   - "Deploy from GitHub repo"
   - Point it to this repo
   - Select the directory: cron/daily_sales
3. Railway will automatically build using the Dockerfile.
4. Add env vars:
   - SHOP_URL
   - SHOPIFY_ACCESS_TOKEN
   - SHOPIFY_API_VERSION
5. Enable Cron
   Example: `0 6 * * *` (6am UTC)

## Logs
View real-time logs in Railway → weekly-maintenance-worker → Logs.