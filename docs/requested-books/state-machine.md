Requested Books — State Machine (Phase 1)

Purpose

This document defines the Phase 1 state machine for tracking customer book requests submitted via the Slack channel #requested-books.

The goal of this state machine is to:
	•	Reflect actual staff behavior, not idealized workflows
	•	Avoid false certainty or inferred outcomes
	•	Provide a stable foundation for:
	•	Staff-facing conventions
	•	Assistive automation
	•	Reliable reporting

This is not a fulfillment engine.
It is a truthful classification system over Slack activity.

⸻

Design Principles
	1.	Slack is the system of record
State is derived from visible Slack activity only.
	2.	Silence is not meaning
A lack of replies does not imply action or inaction.
	3.	Explicit beats inferred
A state is only assigned when there is a clear signal.
	4.	Minimal but extensible
Phase 1 introduces the smallest viable set of states that can be trusted.

⸻

Conceptual Workflow (Real World)

This is how requests actually move through the business:

Requested
→ Ordered
→ Arrived
→ Customer Notified
→ Picked Up / Fulfilled

Not all of these stages are currently expressed consistently in Slack.
The state machine below only encodes what can be reliably detected.

⸻

Phase 1 State Definitions

REQUESTED

Definition
A customer request has been posted to #requested-books.

Derivation Rules
	•	Top-level Slack message
	•	reply_count == 0

Interpretation
	•	A request exists
	•	No visible staff interaction yet

Notes
	•	This state does not imply that the request has been ignored
	•	It only reflects the absence of a reply

⸻

ACKNOWLEDGED

Definition
A staff member has replied to the request, but no specific action has been explicitly declaredDOM for keyword.

Derivation Rules
	•	reply_count > 0
	•	No explicit action keywords detected

Interpretation
	•	The request has been seen and touched by a human
	•	No assumptions are made about ordering, arrival, or notification

Why this state exists
	•	Prevents over-claiming progress
	•	Separates “seen” from “acted upon”

⸻

ORDERED

Definition
A staff reply explicitly states that the book has been ordered.

Derivation Rules
	•	A reply contains one of the following (case-insensitive):
	•	ordered
	•	on order
	•	placed order
	•	backordered (optional inclusion)

Interpretation
	•	An order has been placed with a supplier
	•	Inventory has not necessarily arrived

Important
	•	This state is never inferred
	•	Absence of this keyword means the system does not assume ordering

⸻

NOTIFIED

Definition
A staff reply explicitly states that the customer has been notified.

Derivation Rules
	•	A reply contains the keyword:
	•	notified (case-insensitive)

Interpretation
	•	The customer has been contacted
	•	The request is now waiting on customer action (pickup, confirmation, etc.)

Notes
	•	This is the most common and reliable signal observed in historical data
	•	NOTIFIED is not a terminal state

⸻

FULFILLED

Definition
The request has been completed (e.g. picked up, shipped, resolved).

Derivation Rules (Phase 1)
	•	Explicit only
	•	A staff reply contains one of:
	•	fulfilled
	•	picked up
	•	completed

OR (if adopted by staff convention):
	•	A checkmark reaction (✅) is added to the parent message

Interpretation
	•	The request lifecycle is complete
	•	No further action required

Why this is manual in Phase 1
	•	Historical data shows fulfillment is rarely marked
	•	Auto-closing would introduce false positives
	•	Staff clarity is prioritized over automation

If it is not marked, it is not closed.

⸻

CANCELLED

Definition
The request has been explicitly cancelled.

Derivation Rules
	•	A reply contains:
	•	cancelled or canceled

Interpretation
	•	The request should not be pursued further

Notes
	•	Rare but unambiguous
	•	Safe to classify automatically when present

⸻

UNKNOWN

Definition
A request with no replies that has aged beyond a defined threshold.

Derivation Rules
	•	reply_count == 0
	•	Thread age exceeds configurable threshold (e.g. 180 days)

Interpretation
	•	The true outcome is unknowable from Slack
	•	The system refuses to guess

Purpose
	•	Prevents inflating “open requests”
	•	Avoids retroactive closure of historical data

⸻

State Transition Diagram (Phase 1)

REQUESTED
├─(any reply)────────────▶ ACKNOWLEDGED
│                           ├─("ordered")────▶ ORDERED
│                           ├─("notified")───▶ NOTIFIED
│                           ├─("cancelled")──▶ CANCELLED
│                           └─(explicit)─────▶ FULFILLED
└─(stale, no reply)──────▶ UNKNOWN


⸻

Automatic vs Explicit Transitions

Automatic (Structural)
	•	REQUESTED → ACKNOWLEDGED
	•	REQUESTED → UNKNOWN

Explicit (Human-Declared)
	•	→ ORDERED
	•	→ NOTIFIED
	•	→ FULFILLED
	•	→ CANCELLED

No other transitions are permitted in Phase 1.

⸻

What Phase 1 Explicitly Does NOT Do
	•	Infer ordering from silence
	•	Infer fulfillment from inventory changes
	•	Infer completion from notification
	•	Use emoji alone as authoritative signals
	•	Retroactively “fix” historical threads

These are deliberate exclusions.

⸻

Phase 2 Preview (Non-Binding)

Future phases may introduce:
	•	Inventory webhook → ORDERED / ARRIVED assistive prompts
	•	Staff prompts for unclosed NOTIFIED requests
	•	Optional persistence layer
	•	Stronger fulfillment conventions

None of these are assumed here.

⸻

Contract Summary

This state machine is:
	•	Honest
	•	Evidence-based
	•	Slack-native
	•	Safe to automate around, not over

It is the authoritative interpretation layer for requested books in Phase 1.