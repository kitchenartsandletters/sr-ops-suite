SR Ops Suite — Reporting Modules

Daily Sales Report · Business-Day Calendar · PDF/CSV Output · Weekly Maintenance Roadmap

⸻

1. Overview

This directory contains operational reporting utilities used by Kitchen Arts & Letters to generate automated sales intelligence, inventory oversight, and fulfillment-related audits.
The tooling is designed to:
	•	Pull accurate sales data using Shopify’s Admin GraphQL API
	•	Generate both CSV and clean, printer-ready PDF reports
	•	Respect KAL’s real-world business-day calendar (open/closed days, holiday closures, special December Sundays)
	•	Avoid duplicate or stale reporting
	•	Provide a foundation for weekly maintenance and exception-based reporting

⸻

2. Daily Sales Report

File: daily_sales_report.py

Purpose: Generate a daily sales report covering the correct business-defined time window, separated into meaningful inventory buckets, and delivered via email.

⸻

2.1 Business-Defined Reporting Window

Daily reporting follows KAL’s operational window, not the calendar day.

Reporting Window Logic

Every run at 10:00 AM ET will generate a report covering:

Start: 10:00 AM ET the previous business day
End:   9:59:59 AM ET on the day of the report

This window automatically extends across closed days using logic defined in business_calendar.py.

Examples
	•	Regular Tuesday run → covers Mon 10:00 AM → Tue 9:59 AM
	•	Monday run after weekend → covers Sat 10:00 AM → Mon 9:59 AM
	•	Dec 27 run (after 12/25–12/26 closures)
→ covers Dec 24 10:00 AM → Dec 27 9:59 AM

The daily report never runs on closed business days (holidays, Sundays except special open Sundays). It only runs when the bookstore is “open,” and retroactively includes all closed days automatically.

⸻

3. Report Structure

The CSV and PDF both contain four sections:
	1.	Main Sales
	2.	Backorders (inventory < 0)
	3.	Out of Stock (inventory == 0)
	4.	Preorders (products in the “Preorder” collection, inventory-agnostic)

Each product row includes:
	•	Title (article-stripped and unicode-normalized for sorting)
	•	Author (derived from SKU)
	•	Collections
	•	ISBN
	•	Inventory (available on hand)
	•	Online sales (OL Sales)
	•	POS sales (POS Sales)
	•	Attributes (Signed, Bookplate, etc.)

⸻

4. PDF Generation

File: daily_sales_pdf.py

The PDF format includes:
	•	A clean Shopify-style table layout
	•	Automatic unicode handling via DejaVuSans.ttf
	•	Wrapping for long text (title, author)
	•	“Collections:” rendered on its own indented row
	•	Smaller font for collection rows
	•	Page headers that include:
	•	Report Name
	•	Report Date
	•	Reporting Window
	•	Pagination

The PDF mirrors the CSV sections but provides a more readable, at-a-glance layout for internal distribution and printing.

⸻

5. Business Calendar

File: business_calendar.py

Defines the true KAL operating calendar, separate from Shopify’s.

Includes:
	•	Static holiday closure definition for the current year
	•	Special open Sundays in December
	•	Function is_business_day(d) to determine store-open dates
	•	Function find_last_open_day(today)
	•	Function get_reporting_window(today) returning:
	•	(start_date, end_date) date objects
	•	Daily report expands continuous window across closed days

The daily report script applies the 10:00 AM window boundaries on top of the calendar dates returned by this module.

⸻

6. Email Delivery

Daily reports are emailed via Mailtrap API and include:
	•	CSV file
	•	PDF file
	•	Subject line with the report date
	•	HTML summary in email body

Environment variables required:

MAILTRAP_API_TOKEN
EMAIL_SENDER
EMAIL_RECIPIENTS


⸻

7. Weekly Maintenance Roadmap

The next major module to implement will be a weekly maintenance reporting suite, created as:

weekly_maintenance_report.py

This script will run once per week (cron-driven) and identify operational gaps that require staff action.

Initial Report Set (Approved)

1. Products with negative inventory but no unfulfilled orders
These indicate:
	•	Mis-picks
	•	Receiving errors
	•	Catalog discrepancy
	•	Inventory drift

2. Products published to Online Store but not in any collection
These items are “floating” — navigational blind spots that customers cannot browse to.

3. Products with inventory ≤ 0 AND attached to unfulfilled orders but not in the Preorder collection
This is the highest-value maintenance report:
	•	True fulfillment risks
	•	Items oversold but not flagged as preorders
	•	Prevents customer disappointment and misfire handling

Design Notes
	•	Will reuse the existing ShopifyClient
	•	Will generate CSV (and optional PDF) in the same output style
	•	Will be cron-scheduled but also callable by Admin UI (future phase)
	•	Report functions will be modular to enable on-demand targeted runs later

⸻

8. Summary

Together, these scripts provide:
	•	Accurate daily sales visibility
	•	Reliable business-calendar awareness
	•	Clean internal reporting (CSV + PDF)
	•	Automated delivery via email
	•	A foundation for robust weekly maintenance audits
	•	Future extensibility for Admin UI, Slack alerts, webhook integrations, and bundle/multicomponent logic