Phase 2: Assistive Slack Request System (Concept)

Purpose

Introduce assistive automation that supports staff without replacing judgment, assuming intent, or silently changing request state.

Automation must reflect explicit human actions, not infer outcomes.

⸻

Guiding Principles
	•	Slack remains the system of record
	•	Automation is read-only by default
	•	No automatic state changes without explicit signals
	•	Automation should surface, not decide

⸻

What Phase 2 Can Do (Safely)

1. Passive Classification
	•	Parse threads using the Phase 1 state machine
	•	Classify requests as:
	•	Requested
	•	Acknowledged
	•	Ordered
	•	Notified
	•	Fulfilled
	•	Cancelled
	•	Unknown (stale)

No changes are written back to Slack.

⸻

2. Visibility & Reporting
	•	Generate CSV / summary views:
	•	Open requests
	•	Notified but not fulfilled
	•	Stale requests
	•	Surface summaries in Slack (read-only messages)

⸻

3. Assistive Prompts (Optional, gated)
Examples:
	•	“This request was notified 30 days ago and is still open.”
	•	“Inventory arrived that matches an open request — review?”

These prompts:
	•	Do not change state
	•	Do not message customers
	•	Do not assume fulfillment

They simply nudge humans.

⸻

What Phase 2 Will Explicitly NOT Do
	•	Auto-close requests
	•	Auto-mark fulfillment
	•	Infer ordering from inventory
	•	Message customers
	•	Replace staff judgment

⸻

Prerequisite for Phase 2

Phase 2 should not begin until:
	•	Staff consistently reply in-thread
	•	Status keywords are used reliably
	•	Fulfillment is explicitly marked in practice

If Phase 1 cannot be sustained manually, Phase 2 should not proceed.

⸻

Long-Term Possibilities (Out of Scope for Now)
	•	Inventory → request matching
	•	Customer notification tooling
	•	Persistent database
	•	UI dashboards

These are intentionally deferred.

⸻

Summary

Phase 2 is about clarity, visibility, and support — not automation for its own sake.
The system succeeds only if it faithfully reflects what staff already do well.

⸻
