# Report Job Worker (Async)

This service polls Supabase (`reports.report_jobs`) for queued report jobs,
claims them atomically via RPC, executes the corresponding report service,
and updates job status and result metadata.

## Environment Variables Required

- SUPABASE_URL
- SUPABASE_KEY
- SHOP_URL
- SHOPIFY_ACCESS_TOKEN
- SHOPIFY_API_VERSION
- MAILTRAP_API_TOKEN
- EMAIL_SENDER
- EMAIL_RECIPIENTS

## Behavior

- Poll interval controlled by REPORT_WORKER_POLL_INTERVAL (default: 5 seconds)
- Executes registered report executors (currently: daily_sales)
- Designed to run as a dedicated Railway worker service