Status: Proposal (Feedback Requested)

This guide is a proposed set of conventions for how we track customer book requests in the #requested-books Slack channel.

Nothing here is automated yet. The goal of this draft is to:
- Make our current workflow clearer and more consistent
- Identify gaps or edge cases before introducing automation
- Gather feedback from staff on what works, what doesn’t, and what’s missing

Please read this as a working proposal. Questions, suggestions, and pushback are encouraged before anything is finalized.

This proposal intentionally focuses on manual practice first. These conventions must prove workable in day-to-day use before any automation is introduced. If the system cannot be followed manually, it should not be automated.

How feedback will be gathered

This proposal is intentionally being shared before anything is finalized or automated. Feedback will be gathered through day-to-day use of the #requested-books channel, informal discussion, and direct comments from staff about what feels clear, unclear, or impractical. The goal is to identify friction, edge cases, and missing steps while the system is still manual, so adjustments can be made before any automation is introduced.

---

Requested Books — Staff Guide

How to Track Customer Requests in Slack

This guide explains how to use the #requested-books Slack channel so that customer requests don’t get lost, duplicated, or accidentally re-worked.

You do not need to learn a new system.
You only need to be clear and consistent when updating a request.

⸻

What the #requested-books channel is (and is not)

This channel is a shared log of customer book requests that exist outside of Shopify orders and must be tracked manually in Slack until they are fulfilled or cancelled.

It is used to:
	•	Record visible status updates
	•	Serve as a shared reference point for follow-ups

The channel is not:
	•	A place for ideas or general recommendations
	•	A system for order management or customer service tickets
	•	A repository for hard-to-source, out-of-print, or special-effort titles -> there are dedicated channels for these book types
	•	A place where silence means “done”
	•	A system that automatically knows what happened

⸻

Core Rule: Replies Are the Record

Our future automated system will only read what is recorded in Slack. If it isn’t written in the thread, the system will not know it happened.

⸻

The lifecycle of a request (simple version)

Every request moves through these stages:
	1.	Requested – Customer asked for a book
	2.	Acknowledged – A staff member replied
	3.	Ordered – The book was ordered
	4.	Notified – The customer was contacted
	5.	Fulfilled – The request is complete
	6.	Cancelled – The request will not be fulfilled

You do not need to add a reply for every conceptual stage, but when a meaningful action happens, it must be recorded.

All requests must be closed via "Fulfilled" or "Cancelled"

⸻

How to Build and Update a Request (aka Replies Are Everything    )

Requests in this channel are **built over time**. Each reply adds information and transforms the request into a complete, self-contained record.

Important rules:
- **Always reply in the original thread.** Do not post updates as new messages.
- **Replies are additive.** Each reply should describe *what just happened*.
- **Do not overwrite history.** Do not edit the original message to reflect updates.
- **Assume someone else will read this later.** The full story must live in the thread.

This is the only way a request can remain complete, readable, and trustworthy.


Examples: Good vs Bad Requests

Below are anonymized examples based on real requests. These show how a request should (and should not) be shaped over time.

Ideal Example 1: Clear, self-contained, fully progressed request

Alice  
Dec 23, 2025 at 11:05 AM  
Lugma for Livia  
917-402-1548

    Replies in thread:
    Edna  
    Dec 23 at 2:41 PM  
    Ordered (next RDH order)

    Edna  
    Jan 9 at 12:16 PM  
    Notified 1/9

    Edna  
    Jan 14 at 5:02 PM  
    Picked up

Why this is the ideal:
- The original request includes the book title, customer name, and contact info.
- The reply is added as a **reply**, not a new message.
- “Notified," "Ordered," and "Picked up" are explicit and dated.
- Anyone reading the thread understands the current state immediately.

Good Example 2: Multiple steps, still clear

Alex  
Jan 4, 2026 at 2:41 PM  
Campania for Mike 
jordanm@example.com

    Replies in thread:
    Sam  
    Jan 5 at 10:12 AM  
    Ordered (next RDH order)

    Sam  
    Jan 11 at 3:47 PM  
    Fulfilled 1/11

Why this is good:
- Each action is recorded as it happens.
- Ordering and fulfillment are clearly distinguished.
- Even though a "Notified" reply was not added, the request was clearly closed by "Fulfilled."
- The request can be picked up by any staff member without additional context.

Bad Example 1: Ambiguous reply, unclear outcome

Julia  
Dec 23, 2025 at 11:06 AM  
The Philosopher Fish for Bruce  
646-352-3120

    Replies in thread:
    Laurie  
    Jan 3 at 5:55 PM  
    Called customer on 1/3, had to leave a voice message

Why this is a problem:
- The reply is verbose without finality.
- It’s unclear whether the customer was successfully notified.
- It’s unclear what the next action to take should be and when it should be taken.
- Does not use a recognized status keyword.
- Another staff member would not know what to do next.

Bad Example 2: Replies outside the thread (fragmented record), off-topic

Marcus  
Jan 10, 2026 at 9:18 AM  
Breaking Breads for Elena. She would also like to preorder a copy of Noma Guide to Building Flavor for in-store pickup.
elena@example.com

Why this is a problem:
- The reply is not in the original thread.
- The request is now split across messages.
- The system (and other staff) cannot reliably see the full history.
- The request includes two separate books
- The request includes a preorder for an active title and isn't clear if the customer simply wants to be notified or if this needs to be promoted to an actual order

⸻

Status Definitions:

1. Requested

What this looks like
	•	A message is posted in #requested-books
	•	No replies yet

Example:
Breaking Breads for Elena  
elena@example.com

What it means
	•	A customer has asked for a book
	•	No visible staff action yet

What you should do
	•	Nothing yet — this is just the starting point

⸻

2. Acknowledged

What this looks like
	•	Any reply to the request

Examples
	•	“Checking availability”
	•	“Looking into this”
	•	“Will follow up”
    •	“Added to cart (acknowledgement only)”

What it means
	•	Someone has seen and touched the request
	•	It does not mean the book was ordered

Why this matters
	•	It tells others the request hasn’t been forgotten

Important:
    •	The system will view any reply at this stage as "acknowledgement" but clarity and brevity should be exercised
⸻

3. Ordered (important!)

What this looks like
	•	A reply that explicitly says the book was ordered

Recommended wording
	•	Ordered
	•	On order
	•	Added to next RDH order
    •	Stocky PO# 1740

What it means
	•	The book has been ordered
	•	It has not necessarily arrived yet

Important
	•	If you don’t say “ordered," "order," or "PO" the system will not assume it was ordered
	•	Silence ≠ ordered

⸻

4. Notified (very important)

What this looks like
	•	A reply that includes the word “notified”

Recommended wording
	•	Notified 3/12
	•	Customer notified
	•	Notified via email

What it means
	•	The customer has been contacted
	•	The request is now waiting on the customer

Important clarification
	•	Notified does NOT mean fulfilled
	•	Many requests stop here until pickup or follow-up

⸻

5. Fulfilled (this must be explicit)

What this looks like
	•	A reply clearly stating completion

Recommended wording
	•	Fulfilled
	•	Picked up
	•	Completed

(Optionally: add a ✅ checkmark to the original message - visually helpful but not crucial)

What it means
	•	The request is done
	•	No further action needed

Critical rule

If fulfillment is not marked, the system will treat the request as still open.

This prevents requests from being accidentally reopened or re-worked.

⸻

6. Cancelled

What this looks like
	•	A reply saying:
	•	Cancelled
	•	Customer cancelled

What it means
	•	The request should not be pursued further

⸻

What NOT to do (very important)

Please avoid the following:
	•	 Do not rely on emojis alone to close a request
	•	 Do not assume others know a book was ordered
	•	 Do not leave a request silent after physical fulfillment
	•	 Do not edit the original request to update status

Why?
Because replies are how the system and other staff see progress.

⸻

Why this matters

Being explicit helps (will help):
    •	Find and search for orders
	•	Prevent missed follow-ups
	•	Make handoffs between staff clear
	•	Ensure customers aren’t contacted multiple times
    •	Surface fulfillment needs immediately

This is about clarity, not extra work.

⸻

Quick reference (TL;DR)

When something happens, add a reply:

Situation	                    What to reply
You’ve looked at it	            Any reply
You placed an order	            Ordered ...
You contacted the customer	    Notified
Customer picked up / done	    Fulfilled
Request won’t proceed	        Cancelled


⸻

Final reminder

Slack is the record.

If it’s not written in the thread, the system does not know it happened.