// src/slack/app.js
require('dotenv').config();
const { Pool } = require('pg');
const { WebClient } = require('@slack/web-api');
const db = new Pool({ connectionString: process.env.SR_DATABASE_URL });

const PAGE_SIZE = 10;

/**
 * Registers Slack command and event handlers on the given Bolt App instance.
 * @param {import('@slack/bolt').App} slackApp
 */
module.exports = function registerSlackCommands(slackApp) {
  const client = slackApp.client;

  // When a user opens the App Home, publish their dashboard
  slackApp.event('app_home_opened', async ({ event, client }) => {
    try {
      await publishBackordersHomeView(event.user, client);
    } catch (err) {
      console.error('Error publishing App Home view:', err);
    }
  });

  // Helper to build paginated backorders blocks
  async function buildBackordersBlocks(page, sortKey = null) {
    // Get total count
    const countRes = await db.query(`
      SELECT COUNT(*) AS total
        FROM order_line_backorders
       WHERE status = 'open'
         AND override_flag = FALSE
         AND initial_available < 0
    `);
    const total = parseInt(countRes.rows[0].total, 10);
    if (total === 0) {
      return { blocks: null, totalPages: 1, total };
    }
    const offset = (page - 1) * PAGE_SIZE;

    // Determine ORDER BY clause based on sortKey
    let orderClause;
    switch (sortKey) {
      case 'age':
        orderClause = `
          FLOOR(
            EXTRACT(EPOCH FROM (
              NOW() - GREATEST(
                COALESCE(product_pub_date::timestamp, order_date),
                order_date
              )
            )) / 86400
          ) DESC
        `;
        break;
      case 'vendor':
        orderClause = 'product_vendor ASC';
        break;
      case 'qty':
        orderClause = 'initial_backordered DESC';
        break;
      default:
        orderClause = 'initial_backordered DESC, initial_available ASC';
    }

    const dataRes = await db.query(`
      SELECT
        order_id, order_date, product_title, product_sku,
        product_barcode, product_vendor, product_pub_date,
        ordered_qty, initial_available, initial_backordered,
        line_item_id
      FROM order_line_backorders
      WHERE status = 'open'
        AND override_flag = FALSE
        AND initial_available < 0
      ORDER BY ${orderClause}
      LIMIT $1 OFFSET $2
    `, [PAGE_SIZE, offset]);
    const rows = dataRes.rows;
    const totalPages = Math.ceil(total / PAGE_SIZE);

    const sortLabel = sortKey ? ` • sorted by ${sortKey}` : '';
    const blocks = [
      { type: 'section', text: { type: 'mrkdwn', text: `*Current Backorders* (Page ${page} of ${totalPages})${sortLabel}` } },
      { type: 'divider' }
    ];
    for (const row of rows) {
      // determine status: unreleased preorder vs open backorder
      const now = Date.now();
      let statusText;
      if (row.product_pub_date) {
        const pubTs = new Date(row.product_pub_date).getTime();
        if (pubTs > now) {
          // still a preorder not yet released
          const daysUntil = Math.ceil((pubTs - now) / (1000*60*60*24));
          statusText = `Releases in ${daysUntil} day${daysUntil !== 1 ? 's' : ''}`;
        } else {
          // released; calculate days since the later of release date or order date
          const orderTs = new Date(row.order_date).getTime();
          const startTs = Math.max(pubTs, orderTs);
          const daysOpen = Math.floor((now - startTs) / (1000*60*60*24));
          statusText = `${daysOpen} day${daysOpen !== 1 ? 's' : ''} open`;
        }
      } else {
        // no pub_date (non-preorder), treat as normal backorder
        const daysOpen = Math.floor((now - new Date(row.order_date).getTime()) / (1000*60*60*24));
        statusText = `${daysOpen} day${daysOpen !== 1 ? 's' : ''} open`;
      }
      blocks.push({
        type: 'section',
        fields: [
          { type: 'mrkdwn', text: `*Order:* \`\`${row.order_id}\`\`` },
          { type: 'mrkdwn', text: `*Date*  \n${new Date(row.order_date).toLocaleDateString()}` },
          { type: 'mrkdwn', text: `*Status*  \n${statusText}` },
          { type: 'mrkdwn', text: `*Title*  \n${row.product_title}` },
          { type: 'mrkdwn', text: `*Vendor*  \n${row.product_vendor || 'Unknown'}` },
          { type: 'mrkdwn', text: `*On Hand*  \n${row.initial_available}` },
          { type: 'mrkdwn', text: `*Backordered*  \n${row.initial_backordered}` }
        ],
        accessory: {
          type: 'button',
          text: { type: 'plain_text', text: 'Mark Fulfilled' },
          style: 'primary',
          value: `${row.order_id}|${row.line_item_id}`,
          action_id: 'mark_fulfilled'
        }
      });
    }
    blocks.push({ type: 'divider' });
    blocks.push({
      type: 'actions',
      elements: [
        {
          type: 'button',
          text: { type: 'plain_text', text: '◀ Previous' },
          action_id: 'backorders_prev',
          value: String(page),
          style: 'primary'
        },
        {
          type: 'button',
          text: { type: 'plain_text', text: 'Next ▶' },
          action_id: 'backorders_next',
          value: String(page),
          style: 'primary'
        }
      ]
    });
    return { blocks, totalPages, total };
  }

  // Backorders report (paginated)
  slackApp.command('/sr-backorders', async ({ ack, body }) => {
    await ack();
    // Parse page number and optional sort flag
    const parts = body.text.trim().split(/\s+/);
    let page = 1, sortKey = null;
    for (const p of parts) {
      if (/^\d+$/.test(p)) {
        page = Math.max(1, parseInt(p, 10));
      } else if (p.startsWith('sort:')) {
        sortKey = p.split(':')[1];
      }
    }
    console.log('Using paginated /sr-backorders, page:', page, 'sortKey:', sortKey);
    try {
      const { blocks, total } = await buildBackordersBlocks(page, sortKey);
      if (!blocks) {
        return await client.chat.postMessage({
          channel: body.channel_id,
          text: '✅ No open backorders at the moment!'
        });
      }
      console.log('Slash response_url:', body.response_url);
      console.log('Debug: blocks count =', blocks.length);
      console.log('Sample block JSON:', JSON.stringify(blocks[2], null, 2));
      console.dir(blocks.slice(0, 3), { depth: 2 });
      // Post as a regular message so we can update it later
      await client.chat.postMessage({
        channel: body.channel_id,
        text: `Current Backorders (Page ${page} of ${Math.ceil(total / PAGE_SIZE)})`,
        metadata: {
          event_type: 'sr_backorders',
          event_payload: { sortKey }
        },
        blocks
      });
    } catch (error) {
      console.error('Error fetching backorders:', error);
      await client.chat.postMessage({
        channel: body.channel_id,
        text: '❌ Sorry, I was unable to load backorders.'
      });
    }
  });

  // Navigate to previous page
  slackApp.action('backorders_prev', async ({ ack, body, client }) => {
    await ack();
    const currentPage = parseInt(body.actions[0].value, 10);
    const metadata = body.message?.metadata?.event_payload || {};
    const sortKey = metadata.sortKey || null;
    const prevPage = currentPage - 1;
    const page = prevPage >= 1 ? prevPage : 1;
    try {
      // Home Tab pagination?
      if (body.container?.type === 'view') {
        // user opening Home
        await publishBackordersHomeView(body.user.id, client, page, sortKey);
        return;
      }
      const { blocks } = await buildBackordersBlocks(page, sortKey);
      // Safely get channel and message timestamp
      const channel = body.channel?.id || body.channel_id;
      const ts = body.message?.ts || body.container?.message_ts;
      await client.chat.update({
        channel,
        ts,
        text: `Current Backorders (Page ${page})`,
        blocks
      });
    } catch (error) {
      console.error('Error paginating backorders (prev):', error);
    }
  });

  // Navigate to next page
  slackApp.action('backorders_next', async ({ ack, body, client }) => {
    await ack();
    const currentPage = parseInt(body.actions[0].value, 10);
    const metadata = body.message?.metadata?.event_payload || {};
    const sortKey = metadata.sortKey || null;
    const nextPage = currentPage + 1;
    try {
      // Home Tab pagination?
      if (body.container?.type === 'view') {
        await publishBackordersHomeView(body.user.id, client, nextPage, sortKey);
        return;
      }
      const { blocks, totalPages } = await buildBackordersBlocks(nextPage, sortKey);
      const page = nextPage > totalPages ? totalPages : nextPage;
      const { blocks: blocksFinal } = await buildBackordersBlocks(page, sortKey);
      // Safely get channel and message timestamp
      const channel = body.channel?.id || body.channel_id;
      const ts = body.message?.ts || body.container?.message_ts;
      await client.chat.update({
        channel,
        ts,
        text: `Current Backorders (Page ${page})`,
        blocks: blocksFinal
      });
    } catch (error) {
      console.error('Error paginating backorders (next):', error);
    }
  });

  // Override backorder status
  slackApp.command('/sr-override', async ({ ack, body, respond }) => {
    await ack();
    const parts = body.text.trim().split(/\s+/);
    const [orderId, lineItemId, action, ...reasonParts] = parts;
    const overrideFlag = action === 'clear';
    const overrideReason = reasonParts.join(' ') || null;
    try {
      await db.query(
        `UPDATE order_line_backorders
           SET override_flag = $1,
               override_reason = $2,
               override_ts = NOW()
         WHERE order_id = $3
           AND line_item_id = $4`,
        [overrideFlag, overrideReason, orderId, lineItemId]
      );
      const verb = overrideFlag ? 'cleared' : 'set';
      await respond({
        text: `Override ${verb} for Order ${orderId}, Item ${lineItemId}${overrideReason ? `: ${overrideReason}` : ''}`
      });
    } catch (err) {
      console.error('Error overriding backorder:', err);
      await respond('❌ Unable to apply override.');
    }
  });

  // Bulk override backorders by ISBN
  slackApp.command('/sr-fulfill-isbn', async ({ ack, body, respond }) => {
    await ack();
    const parts = body.text.trim().split(/\s+/);
    const [isbn, ...reasonParts] = parts;
    const overrideReason = reasonParts.join(' ') || null;

    try {
      const result = await db.query(
        `UPDATE order_line_backorders
           SET override_flag   = TRUE,
               override_reason = $1,
               override_ts     = NOW()
         WHERE product_barcode = $2
           AND status           = 'open'
           AND override_flag    = FALSE`,
        [overrideReason, isbn]
      );
      await respond(`✅ Bulk override applied to ISBN ${isbn}. Rows affected: ${result.rowCount}${overrideReason ? ` (${overrideReason})` : ''}`);
    } catch (err) {
      console.error('Error in bulk override by ISBN:', err);
      await respond('❌ Failed to bulk override backorders by ISBN.');
    }
  });

  /**
   * List the last 10 manually fulfilled backorders for easy undo.
   * Usage: /sr-fulfilled-list
   */
  slackApp.command('/sr-fulfilled-list', async ({ ack, body, respond }) => {
    await ack();
    try {
      const res = await db.query(`
        SELECT order_id, line_item_id, product_title, product_barcode, override_ts
          FROM order_line_backorders
         WHERE status = 'closed'
           AND override_flag = TRUE
           AND override_reason = 'Manually marked fulfilled'
         ORDER BY override_ts DESC
         LIMIT 10
      `);
      const rows = res.rows;
      if (rows.length === 0) {
        return await respond('No recently fulfilled backorders found.');
      }
      // Build numbered list
      const lines = rows.map((r, i) =>
        `*${i+1}.* Order ${r.order_id} – ${r.product_title} – ISBN ${r.product_barcode}`
      );
      lines.unshift('*Recently Fulfilled Backorders:*');
      lines.push('\n_To undo:_ `/sr-undo <number> [reason]`');
      await respond(lines.join('\n'));
    } catch (err) {
      console.error('Error listing fulfilled backorders:', err);
      await respond('❌ Failed to list fulfilled backorders.');
    }
  });

  /**
   * Undo a manual fulfillment by index in the last 10 list.
   * Usage: /sr-undo <index> [reason]
   */
  slackApp.command('/sr-undo', async ({ ack, body, respond }) => {
    await ack();
    const parts = body.text.trim().split(/\s+/);
    const index = parseInt(parts[0], 10);
    const reason = parts.slice(1).join(' ') || 'Undone via /sr-undo';
    if (isNaN(index) || index < 1 || index > 10) {
      return await respond('Please provide a valid item number between 1 and 10.');
    }
    try {
      // Re-fetch the same last 10
      const res = await db.query(`
        SELECT order_id, line_item_id
          FROM order_line_backorders
         WHERE status = 'closed'
           AND override_flag = TRUE
           AND override_reason = 'Manually marked fulfilled'
         ORDER BY override_ts DESC
         LIMIT 10
      `);
      const row = res.rows[index - 1];
      if (!row) {
        return await respond('Could not find an entry to undo at that number.');
      }
      // Perform the undo update
      await db.query(
        `UPDATE order_line_backorders
           SET status = 'open',
               override_flag = FALSE,
               override_reason = $1,
               override_ts = NOW()
         WHERE order_id = $2
           AND line_item_id = $3`,
        [reason, row.order_id, row.line_item_id]
      );
      await respond(`✅ Undo applied to Order ${row.order_id}/${row.line_item_id}. Reason: ${reason}`);
    } catch (err) {
      console.error('Error undoing fulfillment:', err);
      await respond('❌ Failed to undo fulfillment.');
    }
  });

  // Handle "Mark Fulfilled" button clicks
  slackApp.action('mark_fulfilled', async ({ ack, body, client }) => {
    await ack();
    try {
      const [orderId, lineItemId] = body.actions[0].value.split('|');
      // Update the backorder status to closed
      await db.query(
        `UPDATE order_line_backorders
           SET status = 'closed',
               override_flag = TRUE,
               override_reason = 'Manually marked fulfilled',
               override_ts = NOW()
         WHERE order_id = $1
           AND line_item_id = $2`,
        [orderId, lineItemId]
      );
      // Rebuild the current page to reflect the removal
      const currentPage = parseInt(body.actions[0].block_id || body.actions[0].valuePage, 10) || 1;
      const { blocks, totalPages } = await buildBackordersBlocks(currentPage);
      const channel = body.channel?.id || body.channel_id;
      const ts = body.message?.ts || body.container?.message_ts;
      await client.chat.update({
        channel,
        ts,
        text: `Current Backorders (Page ${currentPage} of ${totalPages})`,
        blocks
      });
    } catch (err) {
      console.error('Error handling Mark Fulfilled:', err);
    }
  });

  // Other commands can be added here...

  /**
   * Fetches paginated backorders (by page/sort) and publishes to the user's App Home.
   */
  async function publishBackordersHomeView(userId, client, page = 1, sortKey = 'age') {
    // Build blocks for the requested page and sortKey
    const { blocks } = await buildBackordersBlocks(page, sortKey);
    // Prepend a header
    const header = {
      type: 'header',
      text: { type: 'plain_text', text: '📦 Backorders Dashboard' }
    };
    // Publish the view
    await client.views.publish({
      user_id: userId,
      view: {
        type: 'home',
        blocks: [header, { type: 'divider' }, ...(blocks ?? [])]
      }
    });
  }
};
