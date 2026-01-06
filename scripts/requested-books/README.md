# Requested Books — Exploratory Scripts (Phase 0)

This directory contains **read-only, local-only exploratory scripts** used to inspect and understand the existing Slack channel `#requested-books`.

These scripts are intentionally **non-automated**, **non-destructive**, and **not part of any production workflow**. Their sole purpose is to extract raw data and surface observable patterns so that we can design a reliable state model, staff-facing conventions, and future automation with confidence.

---

## Scope & Philosophy

**What these scripts do:**
- Read historical Slack data from the `#requested-books` channel
- Export raw messages, threads, replies, and emoji reactions
- Produce inspection-friendly CSVs and summaries
- Help identify existing (implicit) patterns in how requests are tracked

**What these scripts explicitly do NOT do:**
- Post messages to Slack
- Modify Slack data
- Infer or assign request state
- Write to a database
- Trigger downstream automations
- Enforce staff behavior

If a script appears to *interpret* data beyond counting or grouping, it does not belong in Phase 0.

---

## Directory Structure

```
scripts/requested-books/
├── 00_export_channel_raw.js     # Full raw export of Slack channel + threads
├── 01_inspect_patterns.js       # Pattern analysis (emoji usage, replies, age)
├── output/
│   ├── raw/
│   │   └── requested_books_raw.json
│   └── analysis/
│       ├── emoji_usage.csv
│       ├── reply_patterns.csv
│       └── threads_summary.csv
└── README.md
```

---

## Phase 0 Workflow

### Step 1 — Export Raw Slack Data
Run the raw export script to capture the current state of the channel.

Output:
- A single JSON file containing:
  - Top-level request messages
  - Thread replies
  - Emoji reactions
  - Timestamps and user IDs

No normalization or interpretation occurs at this stage.

---

### Step 2 — Inspect Patterns
Run the inspection script against the raw export to answer questions such as:
- How often are emojis used?
- Which emojis appear most frequently?
- Are updates posted as replies or top-level messages?
- How many requests have no replies?
- How old are open-looking requests?

Outputs are CSVs suitable for manual review.

---

## Inputs & Configuration

These scripts rely on:
- A valid Slack Bot/User token in the environment
- Read access to the `#requested-books` channel

All configuration should be handled via environment variables or constants in the script files. Hardcoding credentials is not permitted.

---

## Relationship to the Main Codebase

- These scripts are **not imported** by `src/slack/`
- They do **not** share runtime with the Slack Bolt app
- They serve as **ground truth input** for:
  - `docs/requested-books/state-machine.md`
  - `docs/requested-books/staff-guide.md`
  - Future Slack assistive automation

Once Phase 0 is complete, these scripts may be archived but should be retained for historical reference.

---

## Guardrails

- Treat exported data as sensitive (contains customer contact info)
- Do not commit raw exports to version control
- Do not modify Slack messages based on findings from these scripts
- When in doubt, prefer *understanding* over *automation*

---

## Next Phases (Context Only)

- **Phase 1:** Formal state machine + staff-facing conventions
- **Phase 2:** Assistive Slack notifications + CSV reporting
- **Phase 3:** Optional persistence and analytics

These phases are documented separately and are out of scope for this directory.
