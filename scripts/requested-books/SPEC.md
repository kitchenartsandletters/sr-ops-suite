Exploratory Script Specification

Requested Books — Phase 0

Purpose

The exploratory scripts are designed to capture and expose ground-truth behavior in the Slack channel #requested-books without interpretation or enforcement.

Their output will be used to:
	•	Identify implicit staff patterns
	•	Determine viable status signals (emoji, replies, phrasing)
	•	Inform the design of a formal state machine
	•	Shape staff-facing conventions and future automation

These scripts do not attempt to answer the question “what is the state of a request.”
They only answer: “What is present in Slack today?”

⸻

Script 00 — Raw Channel Export

Name

00_export_channel_raw.js

Classification
	•	Phase 0
	•	Read-only
	•	Local execution only

⸻

Inputs
	1.	Slack authentication
	•	Slack Bot token or User token provided via environment variable
	•	Token must have read access to #requested-books
	2.	Channel identifier
	•	Channel name (#requested-books) or channel ID
	•	Channel resolution may be handled internally but is not persisted
	3.	Optional parameters
	•	Start date (timestamp)
	•	End date (timestamp)
	•	Pagination limit override (for testing)

All inputs must be explicit and discoverable. No hidden defaults.

⸻

Slack API Usage

The script is permitted to use the following Slack Web API methods:
	1.	conversations.history
	•	Fetch top-level messages from the channel
	•	Include:
	•	ts
	•	user
	•	text
	•	subtype
	•	thread_ts
	•	reply_count
	•	reactions (if present)
	2.	conversations.replies
	•	Fetch all replies for messages where thread_ts exists
	•	Include:
	•	Reply messages
	•	Reply reactions
	•	Timestamps and user IDs
	3.	Emoji reactions
	•	Reaction data should be captured as provided by Slack
	•	No normalization or interpretation at this stage

No other Slack endpoints are permitted in Phase 0.

⸻

Data Model (Raw Export)

The output must preserve Slack’s native structure while grouping data in a way that is easy to inspect.

Each thread is the primary unit of output.

Top-level structure

{
  "channel": "requested-books",
  "exported_at": "<ISO timestamp>",
  "thread_count": <number>,
  "threads": [ ... ]
}


⸻

Thread object

{
  "thread_ts": "<string>",
  "parent": {
    "ts": "<string>",
    "user": "<user_id>",
    "text": "<raw text>",
    "subtype": "<string | null>",
    "reactions": [ ... ]
  },
  "replies": [
    {
      "ts": "<string>",
      "user": "<user_id>",
      "text": "<raw text>",
      "reactions": [ ... ]
    }
  ]
}

Notes:
	•	No attempt is made to classify a message as a “request” or “update”
	•	Messages without replies are still represented as threads
	•	Threads with malformed or missing data are preserved as-is

⸻

Output
	•	A single JSON file written to:

scripts/requested-books/output/raw/requested_books_raw.json


	•	The file must be:
	•	Deterministic
	•	Human-readable (pretty-printed)
	•	Safe to re-run (overwrite allowed locally)

⸻

Non-Goals (Explicit)

This script must not:
	•	Infer request state
	•	Guess whether a request is open or closed
	•	Parse book titles or customer names
	•	Interpret emoji meaning
	•	Filter out “irrelevant” messages
	•	Deduplicate messages
	•	Write to a database
	•	Post anything to Slack

If a future phase needs this behavior, it must live elsewhere.

⸻

Script 01 — Pattern Inspection

Name

01_inspect_patterns.js

Classification
	•	Phase 0
	•	Derived analysis only
	•	Input: raw export JSON

⸻

Purpose

This script transforms the raw export into observable metrics that help humans answer design questions.

It does not decide meaning — it only surfaces frequency and structure.

⸻

Inputs
	•	Path to requested_books_raw.json

⸻

Outputs

The script produces one or more CSV files under:

scripts/requested-books/output/analysis/

Expected outputs include (subject to revision):
	1.	Emoji usage
	•	Emoji name
	•	Count
	•	Appears on parent vs reply
	•	Appears alone vs with text
	2.	Reply patterns
	•	Number of replies per thread
	•	Threads with zero replies
	•	Threads with multiple replies by different users
	3.	Temporal patterns
	•	Time between parent message and first reply
	•	Age of threads with no replies
	4.	Free-text indicators
	•	Frequency of words like “notified”, “arrived”, “picked up”, etc.
	•	Case-insensitive, non-interpretive

⸻

Non-Goals

This script must not:
	•	Assign state
	•	Decide correctness
	•	Recommend actions
	•	Mutate the raw export
	•	Filter or hide data

Its outputs are inputs to human judgment, not conclusions.

⸻

Relationship to Later Phases

The results of these scripts directly inform:
	•	docs/requested-books/state-machine.md
	•	docs/requested-books/staff-guide.md
	•	Signal selection (emoji, reply conventions)
	•	Automation safety checks

No later-phase code may contradict observed findings without explicit justification.

⸻

Success Criteria for Phase 0

Phase 0 is complete when:
	•	The full channel history can be inspected offline
	•	Emoji and reply usage patterns are clearly understood
	•	We can confidently define:
	•	A minimal signal set
	•	A conservative state machine
	•	Staff conventions that match reality

Only then should automation be considered.

⸻

Exploratory Script Specification

Requested Books — Phase 0

Script 01: Pattern Inspection

⸻

Purpose

01_inspect_patterns.js analyzes the raw Slack export produced by 00_export_channel_raw.js and emits inspection-friendly summaries that help humans answer questions about:
	•	How requests are actually tracked today
	•	What implicit signals already exist (emoji, replies, wording)
	•	Where ambiguity and inconsistency occur
	•	What conventions are realistic to formalize

This script does not infer state, does not label correctness, and does not recommend actions.

Its output exists solely to inform:
	•	State machine design
	•	Staff-facing conventions
	•	Automation guardrails

⸻

Inputs

Required
	•	Path to requested_books_raw.json

Expected default location:

scripts/requested-books/output/raw/requested_books_raw.json

The script must fail fast if:
	•	The file does not exist
	•	The JSON cannot be parsed
	•	The top-level structure is malformed

⸻

Output Location

All outputs must be written to:

scripts/requested-books/output/analysis/

Files are derived artifacts and may be regenerated freely.

⸻

Output Files (Initial Set)

The script should generate the following CSVs. Column definitions are intentionally explicit to avoid interpretation creep.

⸻

1️⃣ threads_summary.csv

One row per thread

Purpose:
	•	Establish scale
	•	Identify “quiet” vs active threads
	•	Support age and reply-count analysis

Columns
	•	thread_ts
	•	parent_ts
	•	parent_user
	•	parent_text_length (character count only)
	•	reply_count
	•	has_replies (boolean)
	•	parent_has_reactions (boolean)
	•	reply_has_reactions (boolean)
	•	first_reply_ts (null if none)
	•	last_reply_ts (null if none)
	•	thread_age_days (relative to export time)

Notes:
	•	No semantic analysis of text
	•	Length is allowed; content meaning is not

⸻

2️⃣ emoji_usage.csv

One row per emoji occurrence

Purpose:
	•	Identify which emojis are actually used
	•	Determine whether emojis appear on parents, replies, or both
	•	Support later signal selection

Columns
	•	emoji_name
	•	location (parent | reply)
	•	thread_ts
	•	message_ts
	•	message_user

Notes:
	•	Each emoji occurrence is a row
	•	No attempt to interpret emoji meaning
	•	Skin tone variants, if present, are preserved as-is

⸻

3️⃣ reply_patterns.csv

One row per thread

Purpose:
	•	Understand reply behavior
	•	Identify whether replies are conversational or transactional

Columns
	•	thread_ts
	•	reply_count
	•	unique_reply_users
	•	single_responder (boolean)
	•	multiple_responders (boolean)
	•	contains_numeric_dates (boolean; regex only)
	•	contains_keywords (boolean; see below)

⸻

4️⃣ keyword_frequency.csv

One row per keyword

Purpose:
	•	Surface commonly used operational language
	•	Compare words vs emojis as signals

Keyword set (initial, fixed list)
	•	notified
	•	arrived
	•	ordered
	•	picked up
	•	cancelled
	•	ready

Matching rules:
	•	Case-insensitive
	•	Substring match
	•	No stemming
	•	No inference

Columns
	•	keyword
	•	occurrence_count
	•	threads_with_keyword

⸻

Allowed Analysis Techniques

The script may:
	•	Count
	•	Group
	•	Sort
	•	Regex-match
	•	Compute time deltas
	•	Compute booleans from presence/absence

The script may not:
	•	Assign state labels
	•	Decide request completion
	•	Guess intent
	•	Collapse threads
	•	Modify raw data
	•	Exclude “irrelevant” messages

If a derived metric feels interpretive, it does not belong here.

⸻

Execution Model
	•	Local execution only
	•	No Slack API calls
	•	Deterministic output
	•	Safe to re-run repeatedly

Example invocation:

node scripts/requested-books/01_inspect_patterns.js


⸻

Relationship to Later Phases

The outputs of this script directly inform:
	•	docs/requested-books/state-machine.md
	•	docs/requested-books/staff-guide.md
	•	Emoji selection and enforcement feasibility
	•	Whether replies or reactions are more reliable signals
	•	Where automation should not be trusted

No later-phase system should contradict findings here without explicit documentation.

⸻

Success Criteria for Script 01

This script is considered successful when you can confidently answer:
	•	Do people use emojis at all?
	•	Which emojis are actually used?
	•	Are updates consistently posted as replies?
	•	How often are requests never replied to?
	•	Are words like “notified” more common than emojis?
	•	Is there enough structure to formalize without heavy enforcement?

Once those answers are clear, Phase 0 is complete.

⸻

Out of Scope (Explicit)
	•	State machine implementation
	•	Staff instructions
	•	Slack notifications
	•	Webhooks
	•	Databases
	•	PDFs
	•	Dashboards

Those come after understanding.

⸻