/**
 * Requested Books — Phase 0
 * Script 00: Raw Channel Export
 *
 * Read-only, local-only export of the #requested-books Slack channel.
 * Exports top-level messages, thread replies, and emoji reactions
 * with zero interpretation or state inference.
 */

import fs from "fs";
import path from "path";
import process from "process";
import fetch from "node-fetch";

const SLACK_BOT_TOKEN = process.env.SLACK_BOT_TOKEN;
const CHANNEL_NAME = "requested-books";
const SLACK_API_BASE = "https://slack.com/api";

if (!SLACK_BOT_TOKEN) {
  console.error("Missing SLACK_BOT_TOKEN environment variable.");
  process.exit(1);
}

const OUTPUT_DIR = path.resolve(
  "scripts/requested-books/output/raw"
);
const OUTPUT_FILE = path.join(
  OUTPUT_DIR,
  "requested_books_raw.json"
);

/**
 * Generic Slack GET helper (query params only).
 */
async function slackGet(endpoint, params = {}) {
  const url = new URL(`${SLACK_API_BASE}/${endpoint}`);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      url.searchParams.append(key, value);
    }
  });

  const res = await fetch(url.toString(), {
    headers: {
      Authorization: `Bearer ${SLACK_BOT_TOKEN}`,
    },
  });

  const data = await res.json();

  if (!data.ok) {
    throw new Error(
      `Slack API error (${endpoint}): ${data.error}`
    );
  }

  return data;
}

/**
 * Resolve public channel ID by name.
 */
async function resolveChannelId(channelName) {
  let cursor;

  do {
    const res = await slackGet("conversations.list", {
      types: "public_channel",
      limit: 200,
      cursor,
    });

    const channel = res.channels.find(
      (c) => c.name === channelName
    );
    if (channel) return channel.id;

    cursor = res.response_metadata?.next_cursor;
  } while (cursor);

  throw new Error(
    `Channel #${channelName} not found or not accessible.`
  );
}

/**
 * Fetch full channel history.
 */
async function fetchChannelHistory(channelId) {
  let cursor;
  const messages = [];

  do {
    const res = await slackGet("conversations.history", {
      channel: channelId,
      limit: 200,
      cursor,
    });

    messages.push(...res.messages);
    cursor = res.response_metadata?.next_cursor;
  } while (cursor);

  return messages;
}

/**
 * Fetch replies for a thread (parent + replies).
 */
async function fetchThreadReplies(channelId, threadTs) {
  const res = await slackGet("conversations.replies", {
    channel: channelId,
    ts: threadTs,
  });

  return res.messages;
}

/**
 * Simple sleep helper for throttling Slack API calls.
 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Main execution
 */
async function run() {
  console.log("Resolving channel ID...");
  const channelId = await resolveChannelId(CHANNEL_NAME);

  console.log("Fetching channel history...");
  const history = await fetchChannelHistory(channelId);

  const threads = [];

  for (const message of history) {
    const threadTs = message.thread_ts || message.ts;
    let replies = [];

    if (message.reply_count && message.reply_count > 0) {
      try {
        // Throttle to avoid Slack rate limits
        await sleep(350);

        const replyMessages = await fetchThreadReplies(
          channelId,
          threadTs
        );

        replies = replyMessages.filter(
          (m) => m.ts !== message.ts
        );
      } catch (err) {
        console.warn(
          `Failed to fetch replies for thread ${threadTs}: ${err.message}`
        );
      }
    }

    threads.push({
      thread_ts: threadTs,
      parent: {
        ts: message.ts,
        user: message.user,
        text: message.text,
        subtype: message.subtype || null,
        reactions: message.reactions || [],
      },
      replies: replies.map((r) => ({
        ts: r.ts,
        user: r.user,
        text: r.text,
        reactions: r.reactions || [],
      })),
    });
  }

  const output = {
    channel: CHANNEL_NAME,
    exported_at: new Date().toISOString(),
    thread_count: threads.length,
    threads,
  };

  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  fs.writeFileSync(
    OUTPUT_FILE,
    JSON.stringify(output, null, 2),
    "utf-8"
  );

  console.log(
    `Export complete. Wrote ${threads.length} threads to:`
  );
  console.log(OUTPUT_FILE);
}

run().catch((err) => {
  console.error("Export failed:", err);
  process.exit(1);
});
