I’ve loaded and displayed the current open issues. Here’s a proposed roadmap in three phases:

⸻

Phase 1: Core Stability & Data Accuracy
	1.	KIT-106: Auto-tag Preorders via Webhook
	•	Ensure newly placed preorders (identified via isPreorder) get tagged so they don’t surface in backorder dashboards.
	2.	KIT-110: Webhook Order Updates (Fulfill/Cancel)
	•	Complete the Shopify webhook handling in orders.js to close orders on orders/fulfilled and orders/cancelled.
	3.	KIT-109: “Close” Button Workflow Polishing
	•	Triage any edge‐case failures in the Close > Action Choice > Confirm flow—retry on payload size, ack errors, etc.

⸻

Phase 2: UX Enhancements & New Features
	1.	KIT-108: Export CSV on Dashboard View
	•	Add /export/backorders.csv and “Export CSV” button directly in the detailed dashboard.
	2.	KIT-111: Railway Cost Optimization
	•	Audit your Railway deployment (dyno sizes, logs retention) to reduce costs.
	3.	Add “Notes” Feature (Order & ISBN)
	•	Scoped notes per line item and per SKU, with add/edit/delete flows.

⸻

Phase 3: Documentation & Testing
	1.	Comprehensive Test Coverage
	•	Expand Jest + supertest tests for new webhook routes and Slack interactions.
	2.	Finalize README & In-Slack Help
	•	Update /sr-help modal and “View Help Docs” content with all new commands and flows.
	3.	Team Onboarding & Rollout
	•	Share changelog in #sr-backorders; run an end-to-end demo with Matt and team.

⸻

Let me know if you’d like to reorder priorities, merge any items, or dive deeper into specific tasks! ￼