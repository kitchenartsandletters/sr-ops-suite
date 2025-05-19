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
  // Helper to generate EDT timestamp for filenames
  function formatEDT() {
    const now = new Date().toLocaleString('en-US', {
      timeZone: 'America/New_York',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });
    const [datePart, timePart] = now.split(', ');
    const filenameDate = datePart.replace(/\//g, '');
    const filenameTime = timePart.replace(/:/g, '');
    return `${filenameDate}_${filenameTime}`;
  }
  const client = slackApp.client;
  // Debug: log configured export URL base
  console.log('SR_APP_URL:', process.env.SR_APP_URL);

  // CSV export endpoint (handles with or without trailing slash)
  slackApp.receiver.app.get(['/export/backorders-list', '/export/backorders-list/'], async (req, res) => {
    console.log('CSV export endpoint hit:', req.method, req.path);
    try {
      const result = await db.query(`
        SELECT
          product_barcode   AS isbn,
          product_title     AS title,
          MIN(order_date)::date AS oldest,
          MAX(order_date)::date AS newest,
          SUM(ordered_qty)  AS total_open_qty,
          product_vendor    AS vendor
        FROM order_line_backorders
        WHERE status = 'open'
          AND override_flag = FALSE
          AND initial_available < 0
        GROUP BY product_barcode, product_title, product_vendor
        ORDER BY total_open_qty DESC
      `);
      const rows = result.rows;
      const header = 'ISBN,Title,Oldest,Newest,Total Open Qty,Vendor';
      const lines = rows.map(r => [
        r.isbn,
        `"${r.title.replace(/"/g, '""')}"`,
        r.oldest,
        r.newest,
        r.total_open_qty,
        r.vendor || ''
      ].join(','));
      const csv = [header, ...lines].join('\n');
      res.setHeader('Content-Type', 'text/csv');
      res.setHeader('Content-Disposition', 'attachment; filename="backorders.csv"');
      res.send(csv);
    } catch (err) {
      console.error('Error generating CSV:', err);
      res.status(500).send('Internal Server Error');
    }
  });

  // Health check endpoint
  slackApp.receiver.app.get('/healthz', (req, res) => {
    res.status(200).send('OK');
  });
  // Debug: dump registered routes and log all incoming requests
  if (slackApp.receiver.app && slackApp.receiver.app._router) {
    const routes = slackApp.receiver.app._router.stack
      .filter(r => r.route && r.route.path)
      .map(r => `${Object.keys(r.route.methods).join(',').toUpperCase()} ${r.route.path}`);
    console.log('Registered routes:', routes);
    // Debug: log all incoming requests
    slackApp.receiver.app.use((req, res, next) => {
      console.log('Incoming request:', req.method, req.originalUrl);
      next();
    });
  } else {
    console.warn('Express app router not available for route dumping.');
  }

  // When a user opens the App Home, publish their dashboard
  slackApp.event('app_home_opened', async ({ event, client }) => {
    // background view publish
    (async () => {
      try {
        if (!event.view?.private_metadata) {
          await publishBackordersHomeView(event.user, client, 1, 'age');
        }
      } catch (err) {
        console.error('Error publishing App Home view:', err);
      }
    })();
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
      return { blocks: null, totalPages: 1, total, rows: [] };
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
      case 'title':
        // Sort alphabetically by product title
        orderClause = 'product_title ASC';
        break;
      case 'qty':
        orderClause = 'initial_backordered DESC';
        break;
      default:
        orderClause = 'initial_backordered DESC, initial_available ASC';
    }

    const dataRes = await db.query(`
      SELECT
        order_id,
        shopify_order_id,
        order_date,
        product_title,
        product_sku,
        product_barcode,
        product_vendor,
        product_pub_date,
        eta_date,
        ordered_qty,
        initial_available,
        initial_backordered,
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
    const lastRefreshed = new Date().toLocaleString('en-US', {
      timeZone: 'America/New_York',
      dateStyle: 'short',
      timeStyle: 'short'
    });
    const blocks = [
      { type: 'header', text: { type: 'plain_text', text: '📦 Backorders Dashboard' } },
      { type: 'context', elements: [{ type: 'mrkdwn', text: `*Last refreshed:* ${lastRefreshed}` }] },
      { type: 'divider' },
      { type: 'section', text: { type: 'mrkdwn', text: `*Current Backorders* (Page ${page} of ${totalPages})${sortLabel}` } },
      {
        type: 'actions',
        elements: [
          {
            type: 'button',
            text: { type: 'plain_text', text: 'Sort by Title' },
            action_id: 'backorders_sort_title',
            value: `${page}|title`
          }
        ]
      },
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
      blocks.push(
        {
          type: 'section',
          fields: [
            { type: 'mrkdwn', text: `*Order:* <https://${process.env.SR_SHOPIFY_SHOP.replace(/"/g, '')}/admin/orders/${row.shopify_order_id}|${row.order_id}>` },
            { type: 'mrkdwn', text: `*Date:*  \`${new Date(row.order_date).toLocaleDateString()}\`` },
            { type: 'mrkdwn', text: `*Status*  \`${statusText}\`` },
            { type: 'mrkdwn', text: `*Title*  \`${row.product_title}\`` },
            { type: 'mrkdwn', text: `*ISBN:*  \`${row.product_barcode || 'Unknown'}\`` },
            { type: 'mrkdwn', text: `*Vendor:*  \`${row.product_vendor || 'Unknown'}\`` },
            { type: 'mrkdwn', text: `*Open Qty:*  \`${row.ordered_qty}\`` },
            // Conditionally include ETA field
            ...(row.eta_date
              ? [{ type: 'mrkdwn', text: `*ETA:*  \`${new Date(row.eta_date).toLocaleDateString()}\`` }]
              : [])
          ]
        },
        {
          type: 'actions',
          elements: [
            {
              type: 'button',
              text: { type: 'plain_text', text: 'Mark Fulfilled' },
              style: 'primary',
              action_id: 'mark_fulfilled',
              value: `${row.order_id}|${row.line_item_id}`
            },
            {
              type: 'button',
              text: { type: 'plain_text', text: 'Update ETA' },
              action_id: 'update_eta',
              value: `${row.order_id}|${row.line_item_id}`
            },
            // Conditionally include Clear ETA button when an ETA is set
            ...(row.eta_date ? [{
              type: 'button',
              text: { type: 'plain_text', text: 'Clear ETA' },
              style: 'danger',
              action_id: 'clear_eta',
              value: `${row.order_id}|${row.line_item_id}`
            }] : [])
          ]
        },
        { type: 'divider' }
      );
    }
    blocks.push({
      type: 'actions',
      elements: [
        {
          type: 'button',
          text: { type: 'plain_text', text: '◀ Previous' },
          action_id: 'backorders_prev',
          value: `${page}|${sortKey || ''}`,
          style: 'primary'
        },
        {
          type: 'button',
          text: { type: 'plain_text', text: 'Next ▶' },
          action_id: 'backorders_next',
          value: `${page}|${sortKey || ''}`,
          style: 'primary'
        }
      ]
    });
    return { blocks, totalPages, total, rows };
  }

  // Backorders report (paginated)
  slackApp.command('/sr-back', async ({ ack, body, client, context }) => {
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
    console.log('Using paginated /sr-back, page:', page, 'sortKey:', sortKey);
    // Always publish backorders to the user's App Home
    await client.chat.postEphemeral({
      channel: body.channel_id,
      user: body.user_id,
      text: `Publishing backorders to your App Home…`
    });
    await publishBackordersHomeView(body.user_id, client, page, sortKey);
    return;
    // (old unreachable code below kept for reference)
    /*
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
    */
  });

  // Navigate to previous page
  slackApp.action('backorders_prev', async ({ ack, body, client }) => {
    await ack();
    const [rawPage, rawSort] = body.actions[0].value.split('|');
    const currentPage = parseInt(rawPage, 10);
    const sortKey = rawSort || null;
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
    const [rawPage, rawSort] = body.actions[0].value.split('|');
    const currentPage = parseInt(rawPage, 10);
    const sortKey = rawSort || null;

    try {
      // Determine target page
      let targetPage = currentPage + 1;
      // Fetch totalPages from a preliminary call
      const { totalPages } = await buildBackordersBlocks(targetPage, sortKey);
      if (targetPage > totalPages) {
        targetPage = totalPages;
      }

      // Home Tab pagination?
      if (body.container?.type === 'view') {
        await publishBackordersHomeView(body.user.id, client, targetPage, sortKey);
        return;
      }

      // Build blocks for the capped page
      const { blocks } = await buildBackordersBlocks(targetPage, sortKey);
      const channel = body.channel?.id || body.channel_id;
      const ts = body.message?.ts || body.container?.message_ts;
      await client.chat.update({
        channel,
        ts,
        text: `Current Backorders (Page ${targetPage} of ${totalPages})`,
        blocks
      });
    } catch (error) {
      console.error('Error paginating backorders (next):', error);
    }
  });

  // Sort by Title
  slackApp.action('backorders_sort_title', async ({ ack, body, client }) => {
    await ack();
    const [page] = body.actions[0].value.split('|');
    await publishBackordersHomeView(body.user.id, client, parseInt(page, 10), 'title');
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
      if (body.container?.type === 'view') {
        // Button clicked in App Home: republish the Home view
        await publishBackordersHomeView(body.user.id, client);
      } else {
        // Button clicked in a chat message: update the message
        const channel = body.channel.id;
        const ts = body.message.ts;
        await client.chat.update({
          channel,
          ts,
          text: `Current Backorders (Page ${currentPage} of ${totalPages})`,
          blocks
        });
      }
    } catch (err) {
      console.error('Error handling Mark Fulfilled:', err);
    }
  });

  // Handle "Update ETA" button clicks (open modal)
  slackApp.action('update_eta', async ({ ack, body, client }) => {
    await ack();
    const triggerId = body.trigger_id;
    const [orderId, lineItemId] = body.actions[0].value.split('|');
    await client.views.open({
      trigger_id: triggerId,
      view: {
        type: 'modal',
        callback_id: 'update_eta_submit',
        private_metadata: `${orderId}|${lineItemId}`,
        title: { type: 'plain_text', text: 'Set ETA' },
        submit: { type: 'plain_text', text: 'Save' },
        close: { type: 'plain_text', text: 'Cancel' },
        blocks: [
          {
            type: 'input',
            block_id: 'eta_input',
            label: { type: 'plain_text', text: 'ETA date' },
            element: {
              type: 'datepicker',
              action_id: 'eta_action'
            }
          }
        ]
      }
    });
  });

  // Handle "Clear ETA" button clicks
  slackApp.action('clear_eta', async ({ ack, body, client }) => {
    await ack();
    const [orderId, lineItemId] = body.actions[0].value.split('|');
    try {
      // Clear the eta_date for this row
      await db.query(
        `UPDATE order_line_backorders
           SET eta_date = NULL
         WHERE order_id = $1
           AND line_item_id = $2`,
        [orderId, lineItemId]
      );
      // Refresh Home view for user
      await publishBackordersHomeView(body.user.id, client);
    } catch (err) {
      console.error('Error clearing ETA date:', err);
    }
  });

  // Handle ETA modal submission
  slackApp.view('update_eta_submit', async ({ ack, body, client }) => {
    await ack();
    const metadata = body.view.private_metadata;
    const [orderId, lineItemId] = metadata.split('|');
    const etaDate = body.view.state.values.eta_input.eta_action.selected_date;
    try {
      await db.query(
        `UPDATE order_line_backorders SET eta_date = $1 WHERE order_id = $2 AND line_item_id = $3`,
        [etaDate, orderId, lineItemId]
      );
      // Refresh Home view for user
      await publishBackordersHomeView(body.user.id, client);
    } catch (err) {
      console.error('Error saving ETA date:', err);
    }
  });

  // Other commands can be added here...

  /**
   * Fetches paginated backorders (by page/sort) and publishes to the user's App Home.
   */
  async function publishBackordersHomeView(userId, client, page = 1, sortKey = 'age') {
    // Build blocks for the requested page and sortKey
    const { blocks, rows } = await buildBackordersBlocks(page, sortKey);
    console.log('Paged backorders rows:', JSON.stringify(rows, null, 2));
    // Publish the view (add docs button at top)
    await client.views.publish({
      user_id: userId,
      view: {
        type: 'home',
        private_metadata: JSON.stringify({ page, sortKey }),
        blocks: [
          // add docs button at top
          {
            type: 'actions',
            elements: [
              {
                type: 'button',
                text: { type: 'plain_text', text: 'View Docs' },
                action_id: 'open_docs'
              }
            ]
          },
          ...(blocks ?? [])
        ]
      }
    });
  }

  // Handle "View Docs" button click to show README in App Home
  slackApp.action('open_docs', async ({ ack, body, client }) => {
    await ack();
    // Build help blocks (simple indexed list)
    const helpBlocks = [
      { type: 'header', text: { type: 'plain_text', text: 'sr-ops-suite Help' } },
      { type: 'section', text: { type: 'mrkdwn', text:
        '*Slash Commands (alphabetical):*\n' +
        '• `/sr-back` – Detailed, paginated backorders\n' +
        '• `/sr-back-list` – Quick one-line-per-SKU summary\n' +
        '• `/sr-fulfill-item` – Fulfill a specific ISBN on an order\n' +
        '• `/sr-fulfill-order` – Fulfill all items on an order\n' +
        '• `/sr-help` – Show this help modal\n' +
        '• `/sr-override` – Override backorder for an order line item\n' +
        '• `/sr-undo` – Undo a manual fulfillment\n' +
        '• `/sr-update-eta` – Update ETA for a backorder item\n' +
        '• `/sr-fulfilled-list` – List recently fulfilled items'
      } }
    ];
    // Publish docs view
    await client.views.publish({
      user_id: body.user.id,
      view: {
        type: 'home',
        private_metadata: JSON.stringify({ page: 1, sortKey: null }),
        blocks: helpBlocks
      }
    });
  });
  // Build aggregated blocks: one row per ISBN
  async function buildAggregatedBlocks() {
    const res = await db.query(`
      SELECT
        product_barcode   AS barcode,
        product_title     AS title,
        product_vendor    AS vendor,
        MIN(order_date)::date AS oldest,
        MAX(order_date)::date AS newest,
        SUM(ordered_qty)  AS total_open_qty
      FROM order_line_backorders
      WHERE status = 'open'
        AND override_flag = FALSE
        AND initial_available < 0
      GROUP BY product_barcode, product_title, product_vendor
      ORDER BY total_open_qty DESC
    `);
    const rows = res.rows;
    const count = rows.length;
    const lastRefreshed = new Date().toLocaleString('en-US', {
      timeZone: 'America/New_York',
      dateStyle: 'short',
      timeStyle: 'short'
    });
    const blocks = [
      { type: 'header', text: { type: 'plain_text', text: '📦 Backorders Summary' } },
      {
        type: 'context',
        elements: [
          { type: 'mrkdwn', text: `*${count} SKUs backordered* • Last refreshed: ${lastRefreshed}` }
        ]
      },
      { type: 'divider' },
      {
        type: 'actions',
        elements: [
          {
            type: 'button',
            text: { type: 'plain_text', text: 'Export CSV' },
            url: `${process.env.SR_APP_URL}/export/backorders-list.csv`,
            action_id: 'download_csv'
          }
        ]
      },
      { type: 'divider' }
    ];
    for (const r of rows) {
      blocks.push({
        type: 'section',
        fields: [
          { type: 'mrkdwn', text: `*ISBN:*\n\`${r.barcode || 'N/A'}\`` },
          { type: 'mrkdwn', text: `*Title:*\n\`${r.title}\`` },
          { type: 'mrkdwn', text: `*Oldest:*\n\`${new Date(r.oldest).toLocaleDateString()}\`` },
          { type: 'mrkdwn', text: `*Newest:*\n\`${new Date(r.newest).toLocaleDateString()}\`` },
          { type: 'mrkdwn', text: `*Qty:*\n\`${r.total_open_qty}\`` },
          { type: 'mrkdwn', text: `*Vendor:*\n\`${r.vendor || 'N/A'}\`` }
        ]
      });
      blocks.push({ type: 'divider' });
    }
    return blocks;
  }

  // Publish aggregated blocks to the App Home
  async function publishAggregatedHomeView(userId, client) {
    const blocks = await buildAggregatedBlocks();
    await client.views.publish({
      user_id: userId,
      view: {
        type: 'home',
        private_metadata: 'aggregated',
        blocks
      }
    });
  }

  // Aggregated backorders summary to App Home
  slackApp.command('/sr-back-list', async ({ ack, command, client }) => {
    await ack();
    // Fire-and-forget background processing
    (async () => {
      try {
        // Notify user
        await client.chat.postEphemeral({
          channel: command.channel_id,
          user: command.user_id,
          text: 'Publishing aggregated backorders summary to your App Home...',
        });
        // Publish summary
        await publishAggregatedHomeView(command.user_id, client);
      } catch (err) {
        console.error('Error handling /sr-back-list in background:', err);
      }
    })();
  });

  /**
   * Marks all line items on a given order as fulfilled.
   * Usage: /sr-fulfill-order <orderId>
   */
  slackApp.command('/sr-fulfill-order', async ({ ack, body, respond }) => {
    await ack();
    const orderId = body.text.trim();
    // Normalize human-friendly order number to include leading '#'
    const normalizedOrderId = orderId.startsWith('#') ? orderId : `#${orderId}`;
    if (!orderId) {
      return await respond('Usage: /sr-fulfill-order <orderId>');
    }
    try {
      const result = await db.query(
        `UPDATE order_line_backorders
           SET status = 'closed',
               override_flag = TRUE,
               override_reason = 'Manually marked fulfilled',
               override_ts = NOW()
         WHERE order_id = $1`,
        [normalizedOrderId]
      );
      await respond(`✅ Fulfilled order ${normalizedOrderId}. Rows affected: ${result.rowCount}`);
    } catch (err) {
      console.error('Error fulfilling order:', err);
      await respond('❌ Failed to fulfill order.');
    }
  });

  /**
   * Marks a specific ISBN on a given order as fulfilled.
   * Usage: /sr-fulfill-item <orderId> <ISBN>
   */
  slackApp.command('/sr-fulfill-item', async ({ ack, body, respond }) => {
    await ack();
    const parts = body.text.trim().split(/\s+/);
    const [orderId, barcode] = parts;
    // Normalize human-friendly order number to include leading '#'
    const normalizedOrderId = orderId && orderId.startsWith('#') ? orderId : `#${orderId}`;
    if (!orderId || !barcode) {
      return await respond('Usage: /sr-fulfill-item <orderId> <ISBN>');
    }
    try {
      const result = await db.query(
        `UPDATE order_line_backorders
           SET status = 'closed',
               override_flag = TRUE,
               override_reason = 'Manually marked fulfilled',
               override_ts = NOW()
         WHERE order_id = $1
           AND product_barcode = $2`,
        [normalizedOrderId, barcode]
      );
      await respond(`✅ Fulfilled ISBN ${barcode} on order ${normalizedOrderId}. Rows affected: ${result.rowCount}`);
    } catch (err) {
      console.error('Error fulfilling item:', err);
      await respond('❌ Failed to fulfill item.');
    }
  });
  // Quick help modal via slash command
  slackApp.command('/sr-help', async ({ ack, body, client }) => {
    await ack();
    // Build modal blocks
    const commands = [
      { cmd: '/sr-back', desc: 'Detailed, paginated backorders' },
      { cmd: '/sr-back-list', desc: 'Quick one-line-per-SKU summary' },
      { cmd: '/sr-fulfill-item', desc: 'Fulfill a specific ISBN on an order' },
      { cmd: '/sr-fulfill-order', desc: 'Fulfill all items on an order' },
      { cmd: '/sr-override', desc: 'Override backorder for an order line item' },
      { cmd: '/sr-undo', desc: 'Undo a manual fulfillment' },
      { cmd: '/sr-update-eta', desc: 'Update ETA for a backorder item' },
      { cmd: '/sr-fulfilled-list', desc: 'List recently fulfilled items' }
    ];
    commands.sort((a, b) => a.cmd.localeCompare(b.cmd));
    const lines = commands.map(c => `• \`${c.cmd}\` – ${c.desc}`).join('\n');
    await client.views.open({
      trigger_id: body.trigger_id,
      view: {
        type: 'modal',
        title: { type: 'plain_text', text: 'sr-ops-suite Help' },
        close: { type: 'plain_text', text: 'Close' },
        blocks: [
          { type: 'section', text: { type: 'mrkdwn', text: '*Slash Commands (alphabetical):*' } },
          { type: 'section', text: { type: 'mrkdwn', text: lines } }
        ]
      }
    });
  });
};