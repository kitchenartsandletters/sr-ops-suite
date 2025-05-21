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
    await ack();
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
  slackApp.event('app_home_opened', async ({ ack, event, client }) => {
    await ack();
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
      { type: 'header', text: { type: 'plain_text', text: '📦 Backorders - Order View' } },
      { type: 'context', elements: [{ type: 'mrkdwn', text: `*Last refreshed:* ${lastRefreshed}` }] },
      { type: 'divider' },
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
              text: { type: 'plain_text', text: 'Close' },
              style: 'primary',
              action_id: 'mark_fulfilled',
              value: `${row.order_id}|${row.line_item_id}|${page}|${sortKey || ''}`
            },
            {
              type: 'button',
              text: { type: 'plain_text', text: 'Update ETA' },
              action_id: 'update_eta',
              value: `${row.order_id}|${row.line_item_id}|${page}|${sortKey || ''}`
            },
            ...(row.eta_date ? [{
              type: 'button',
              text: { type: 'plain_text', text: 'Clear ETA' },
              style: 'danger',
              action_id: 'clear_eta',
              value: `${row.order_id}|${row.line_item_id}|${page}|${sortKey || ''}`
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


  // Override backorder status (supports both orderId/lineItemId and ISBN forms)
  slackApp.command('/sr-override', async ({ ack, body, respond }) => {
    await ack();
    const parts = body.text.trim().split(/\s+/);
    try {
      // Bulk override by ISBN: /sr-override <isbn> <reason>
      if (parts.length === 2 && /^\d{13}$/.test(parts[0])) {
        const [isbn, reason] = parts;
        const result = await db.query(
          `UPDATE order_line_backorders
             SET override_flag   = TRUE,
                 override_reason = $1,
                 override_ts     = NOW()
           WHERE product_barcode = $2
             AND status           = 'open'
             AND override_flag    = FALSE`,
          [reason, isbn]
        );
        return await respond(`✅ Bulk override applied to ISBN ${isbn}. Rows affected: ${result.rowCount}${reason ? ` (${reason})` : ''}`);
      }

      // Single-line override: /sr-override <orderId> <lineItemId> <action> <reason>
      if (parts.length < 3) {
        return await respond('Usage: `/sr-override <orderNumber> <lineItemId> <clear|set> [reason]` or `/sr-override <ISBN> <reason>`');
      }
      const [orderId, lineItemId, action, ...reasonParts] = parts;
      const overrideFlag = action === 'clear';
      const overrideReason = reasonParts.join(' ') || null;
      await db.query(
        `UPDATE order_line_backorders
           SET override_flag   = $1,
               override_reason = $2,
               override_ts     = NOW()
         WHERE order_id      = $3
           AND line_item_id  = $4`,
        [overrideFlag, overrideReason, orderId, lineItemId]
      );
      const verb = overrideFlag ? 'cleared' : 'set';
      return await respond(`✅ Override ${verb} for Order ${orderId}, Item ${lineItemId}${overrideReason ? `: ${overrideReason}` : ''}`);
    } catch (err) {
      console.error('Error overriding backorder:', err);
      return await respond('❌ Unable to apply override.');
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

  // Handle "Mark Fulfilled" button clicks by opening a confirm modal
  
// 1) Open action-choice modal for “Close”
slackApp.action('mark_fulfilled', async ({ ack, body, client }) => {
  await ack();
  const [orderId, lineItemId, page, sortKey] = body.actions[0].value.split('|');
  await client.views.open({
    trigger_id: body.trigger_id,
    view: {
      type: 'modal',
      callback_id: 'close_action_choice',
      private_metadata: body.actions[0].value,
      title: { type: 'plain_text', text: 'Close Backorder' },
      submit: { type: 'plain_text', text: 'Save' },
      close: { type: 'plain_text', text: 'Cancel' },
      blocks: [
        {
          type: 'input',
          block_id: 'close_action',
          label: { type: 'plain_text', text: 'Choose action' },
          element: {
            type: 'radio_buttons',
            action_id: 'action_choice',
            options: [
              { text: { type: 'plain_text', text: 'Mark Fulfilled' }, value: 'fulfilled' },
              { text: { type: 'plain_text', text: 'Cancel/Refund' }, value: 'cancel_refund' }
            ]
          }
        }
      ]
    }
  });
});

// 2) Handle action-choice submit and show confirm modal
slackApp.view('close_action_choice', async ({ ack, body, client }) => {
  await ack();
  const metadata = body.view.private_metadata; // e.g., "123|456|1|age"
  const selected = body.view.state.values.close_action.action_choice.selected_option.value;
  await client.views.open({
    trigger_id: body.trigger_id,
    view: {
      type: 'modal',
      callback_id: 'confirm_close',
      private_metadata: `${metadata}|${selected}`,
      title: { type: 'plain_text', text: 'Confirm Close' },
      submit: { type: 'plain_text', text: 'Confirm' },
      close: { type: 'plain_text', text: 'Cancel' },
      blocks: [
        {
          type: 'section',
          text: {
            type: 'mrkdwn',
            text: `Are you sure you want to *${selected === 'fulfilled' ? 'mark this backorder fulfilled' : 'cancel/refund this backorder'}*?`
          }
        }
      ]
    }
  });
});

// 3) Final confirmation: update DB and refresh view
slackApp.view('confirm_close', async ({ ack, body, client }) => {
  await ack();
  const parts = body.view.private_metadata.split('|');
  // If aggregated flow:
if (parts[0] === 'agg') {
  const isbn = parts[1];
  const action = parts[4];
  const reasonText = action === 'fulfilled'
    ? 'Manually marked fulfilled'
    : 'Manually marked cancel/refund';
  await db.query(
    `UPDATE order_line_backorders
       SET status         = 'closed',
           override_flag  = TRUE,
           override_reason = $1,
           override_ts     = NOW()
     WHERE product_barcode = $2
       AND status           = 'open'`,
    [reasonText, isbn]
  );
  await publishAggregatedHomeView(body.user.id, client);
  return;
}

  // Detailed flow:
  const [orderId, lineItemId, rawPage, rawSort, action] = parts;
  const page = parseInt(rawPage, 10) || 1;
  const sortKey = rawSort || 'age';
  const reasonText = action === 'fulfilled'
    ? 'Manually marked fulfilled'
    : 'Manually marked cancel/refund';
  await db.query(
    `UPDATE order_line_backorders
       SET status = 'closed',
           override_flag = TRUE,
           override_reason = $1,
           override_ts = NOW()
     WHERE order_id = $2
       AND line_item_id = $3`,
    [reasonText, orderId, lineItemId]
  );
  await publishBackordersHomeView(body.user.id, client, page, sortKey);
});

  // Confirm Mark Fulfilled submit handler
  slackApp.view('confirm_mark_fulfilled', async ({ ack, body, client }) => {
    await ack();
    const [orderId, lineItemId, rawPage, rawSort] = body.view.private_metadata.split('|');
    const page = parseInt(rawPage, 10) || 1;
    const sortKey = rawSort || 'age';
    try {
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
      // Refresh view
      await publishBackordersHomeView(body.user.id, client, page, sortKey);
    } catch (err) {
      console.error('Error confirming Mark Fulfilled:', err);
    }
  });

  // Handle "Update ETA" button clicks (open modal)
  slackApp.action('update_eta', async ({ ack, body, client }) => {
    await ack();
    const triggerId = body.trigger_id;
    const [orderId, lineItemId, rawPage, rawSort] = body.actions[0].value.split('|');
    const page = parseInt(rawPage, 10) || 1;
    const sortKey = rawSort || 'age';
    await client.views.open({
      trigger_id: triggerId,
      view: {
        type: 'modal',
        callback_id: 'update_eta_submit',
        private_metadata: `${orderId}|${lineItemId}|${page}|${sortKey}`,
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

  // Handle "Clear ETA" button clicks by opening confirmation modal
  slackApp.action('clear_eta', async ({ ack, body, client }) => {
    await ack();
    const [orderId, lineItemId, rawPage, rawSort] = body.actions[0].value.split('|');
    await client.views.open({
      trigger_id: body.trigger_id,
      view: {
        type: 'modal',
        callback_id: 'confirm_clear_eta',
        private_metadata: body.actions[0].value,
        title: { type: 'plain_text', text: 'Confirm Clear ETA' },
        submit: { type: 'plain_text', text: 'Confirm' },
        close: { type: 'plain_text', text: 'Cancel' },
        blocks: [
          {
            type: 'section',
            text: {
              type: 'mrkdwn',
              text: `Are you sure you want to clear the ETA for Order *${orderId}*, Item *${lineItemId}*?`
            }
          }
        ]
      }
    });
  });

  // Confirm Clear ETA submit handler
  slackApp.view('confirm_clear_eta', async ({ ack, body, client }) => {
    await ack();
    const [orderId, lineItemId, rawPage, rawSort] = body.view.private_metadata.split('|');
    const page = parseInt(rawPage, 10) || 1;
    const sortKey = rawSort || 'age';
    try {
      await db.query(
        `UPDATE order_line_backorders
           SET eta_date = NULL
         WHERE order_id = $1
           AND line_item_id = $2`,
        [orderId, lineItemId]
      );
      await publishBackordersHomeView(body.user.id, client, page, sortKey);
    } catch (err) {
      console.error('Error confirming Clear ETA:', err);
    }
  });

  // Handle ETA modal submission (now only opens confirmation modal)
  slackApp.view('update_eta_submit', async ({ ack, body, client }) => {
    await ack();
    const metadata = body.view.private_metadata;
    const [prefix, id, rawPage, rawSort] = metadata.split('|');
    const etaDate = body.view.state.values.eta_input.eta_action.selected_date || body.view.state.values.eta_input.eta_action.value;
    // Open confirmation modal
    await client.views.open({
      trigger_id: body.trigger_id,
      view: {
        type: 'modal',
        callback_id: 'confirm_update_eta',
        private_metadata: `${metadata}|${etaDate}`,
        title: { type: 'plain_text', text: 'Confirm ETA Update' },
        submit: { type: 'plain_text', text: 'Confirm' },
        close: { type: 'plain_text', text: 'Cancel' },
        blocks: [
          {
            type: 'section',
            text: {
              type: 'mrkdwn',
              text: prefix === 'agg'
                ? `Are you sure you want to set the ETA for all backorders of ISBN *${id}* to *${etaDate}*?`
                : `Are you sure you want to set the ETA for Order *${prefix}*, Item *${id}* to *${etaDate}*?`
            }
          }
        ]
      }
    });
  });

  // Confirm Update ETA submit handler
  slackApp.view('confirm_update_eta', async ({ ack, body, client }) => {
    await ack();
    const metadata = body.view.private_metadata;
    const parts = metadata.split('|');
    const isAgg = parts[0] === 'agg';
    let page = 1, sortKey = 'age';
    try {
      if (isAgg) {
        const isbn = parts[1];
        const etaDate = parts[2];
        // Perform aggregated update
        const result = await db.query(
          `UPDATE order_line_backorders
             SET eta_date = $1
           WHERE product_barcode = $2
             AND status = 'open'
             AND override_flag = FALSE`,
          [etaDate, isbn]
        );
        await client.chat.postEphemeral({
          channel: body.user.id,
          user: body.user.id,
          text: `✅ Set ETA (${etaDate}) for ISBN ${isbn} on ${result.rowCount} backorders.`
        });
        await publishAggregatedHomeView(body.user.id, client);
      } else {
        const [orderId, lineItemId, rawPage, rawSort, etaDate] = parts;
        page = parseInt(rawPage, 10) || 1;
        sortKey = rawSort || 'age';
        // Perform per-line update
        await db.query(
          `UPDATE order_line_backorders
             SET eta_date = $1
           WHERE order_id = $2
             AND line_item_id = $3`,
          [etaDate, orderId, lineItemId]
        );
        await publishBackordersHomeView(body.user.id, client, page, sortKey);
      }
    } catch (err) {
      console.error('Error confirming Update ETA:', err);
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
    // Publish the view (with new top actions)
    await client.views.publish({
      user_id: userId,
      view: {
        type: 'home',
        private_metadata: JSON.stringify({ page, sortKey }),
        blocks: [
          {
            type: 'actions',
            elements: [
              {
                type: 'button',
                text: { type: 'plain_text', text: 'Refresh' },
                action_id: 'home_refresh',
                value: 'dashboard'
              },
              {
                type: 'button',
                text: { type: 'plain_text', text: 'ISBN View' },
                action_id: 'home_toggle',
                value: 'summary'
              },
              {
                type: 'button',
                text: { type: 'plain_text', text: 'Sort by Title' },
                action_id: 'backorders_sort_title',
                value: `${page}|title`
              },
              {
                type: 'button',
                text: { type: 'plain_text', text: 'View Help Docs' },
                action_id: 'open_docs'
              }
            ]
          },
          ...(blocks ?? [])
        ]
      }
    });
  }

  // Refresh current dashboard view
  slackApp.action('home_refresh', async ({ ack, body, client }) => {
    await ack();
    let metadata;
    try {
      metadata = JSON.parse(body.view.private_metadata);
    } catch {
      metadata = {};
    }
    if (metadata.view === 'summary') {
      await publishAggregatedHomeView(body.user.id, client, metadata.sortKey);
    } else {
      const page = metadata.page || 1;
      const sortKey = metadata.sortKey || 'age';
      await publishBackordersHomeView(body.user.id, client, page, sortKey);
    }
  });

  // Handle "View Docs" button click to show README in a modal
  slackApp.action('open_docs', async ({ ack, body, client }) => {
    await ack();
    // Build modal blocks with full command examples and help
    const modalBlocks = [
      { type: 'header', text: { type: 'plain_text', text: 'sr-ops-suite', emoji: true } },
      { type: 'section', text: { type: 'mrkdwn', text: '*sr-ops-suite* is a suite of Slack applications for shipping and receiving workflows. The `sr` prefix stands for Shipping & Receiving. Tools in the suite will help communicate about backorders, preorders, daily inventory tracking, order collection and exports—all without leaving Slack.' } },
      { type: 'divider' },
      { type: 'section', text: { type: 'mrkdwn', text: '*What It Does*' } },
      { type: 'section', text: { type: 'mrkdwn', text:
          '- *Backorders - Order View* (`#sr-backorders` channel): A dedicated Slack channel for team-wide backorder discussions and notifications.\n' +
          '- *Display Current Backorders* (`/sr-back`): Display and refresh a detailed, paginated view of current backorders by line item.\n' +
          '- *Update ETA* (`/sr-update-eta [orderNumber] [isbn] [YYYY-MM-DD]` and `/sr-update-eta [isbn] [YYYY-MM-DD]`): Update the estimated arrival date for a backordered item.\n' +
          '  _Examples:_ `/sr-update-eta 60166 9780316580915 2025-06-01`  `/sr-update-eta 9780316580915 2025-06-01`\n' +
          '- *Fulfill ISBN* (`/sr-fulfill-isbn`): Mark all open backorders for a given ISBN as fulfilled.\n' +
          '- *Override Backorder* (`/sr-override [orderNumber] [lineItemId] [action] [reason]`): Manually override a backorder entry’s status.\n' +
          '  _Example:_ `/sr-override 60166 13059031040133 clear preorder`\n' +
          '- *Fulfilled List* (`/sr-fulfilled-list`): List the last 10 items manually marked fulfilled.\n' +
          '  _Example:_ `/sr-fulfilled-list`\n' +
          '- *Undo Fulfillment* (`/sr-undo [overrideNumber]`): Undo a specific manually marked fulfillment (use after `/sr-fulfilled-list`).\n' +
          '  _Example:_ `/sr-undo 3`\n' +
          '- *Quick Backorder Summary* (`/sr-back-list`): Generates a one-line-per-SKU summary of backorders with total quantities per product in App Home, including Export CSV.\n' +
          '  _Example:_ `/sr-back-list`\n' +
          '- *Fulfill Orders* (`/sr-fulfill-order [orderNumber]`): Handle bulk order fulfillment by order number.\n' +
          '  _Example:_ `/sr-fulfill-order 60166`\n' +
          '- *Fulfill Items* (`/sr-fulfill-item [orderNumber] [isbn]`): Fulfill a specific ISBN on a given order.\n' +
          '  _Example:_ `/sr-fulfill-item 60166 9780316580915`\n' +
          '- *Export CSV* (button in App Home): Download the full backorders list as a CSV file.\n' +
          '- *Help Modal* (`/sr-help`): Open a help modal listing all available commands with examples.\n' +
          '  _Example:_ `/sr-help`'
      } },
      { type: 'divider' },
      { type: 'section', text: { type: 'mrkdwn', text: '*Installing in Slack*' } },
      { type: 'section', text: { type: 'mrkdwn', text:
          '1) Desktop: App Directory → Add apps → search `sr-ops-suite` → Add to Slack\n' +
          '2) Mobile: Apps (•••) → search `sr-ops-suite` → install'
      } },
      { type: 'divider' },
      { type: 'section', text: { type: 'mrkdwn', text: '*Using Slash Commands*' } },
      { type: 'section', text: { type: 'mrkdwn', text:
          '`/sr-back [sortKey]` — Detailed, paginated backorders in App Home. (_e.g._ `/sr-back`, `/sr-back sort:title`)\n' +
          '`/sr-back-list` — Quick one-line-per-SKU summary in App Home with CSV export. (_e.g._ `/sr-back-list`)\n' +
          '`/sr-fulfilled-list` — List last 10 fulfilled backorders. (_e.g._ `/sr-fulfilled-list`)\n' +
          '`/sr-fulfill-order [orderNumber]` — Fulfill all items in an order. (_e.g._ `/sr-fulfill-order 60166`)\n' +
          '`/sr-fulfill-item [orderNumber] [isbn]` — Fulfill specific ISBN on an order. (_e.g._ `/sr-fulfill-item 60166 9780316580915`)\n' +
          '`/sr-fulfill-isbn [isbn]` — Fulfill all backorders for an ISBN. (_e.g._ `/sr-fulfill-isbn 9780316580915`)\n' +
          '`/sr-update-eta [orderNumber] [isbn] [YYYY-MM-DD]` — Update ETA for a specific order and ISBN. (_e.g._ `/sr-update-eta 60166 9780316580915 2025-06-01`)\n' +
          '`/sr-update-eta [isbn] [YYYY-MM-DD]` — Update ETA across all backorders of an ISBN. (_e.g._ `/sr-update-eta 9780316580915 2025-06-01`)\n' +
          '`/sr-override [orderNumber] [lineItemId] [action] [reason]` — Override backorder entry. (_e.g._ `/sr-override 60166 13059031040133 clear preorder`)\n' +
          '`/sr-undo [overrideNumber]` — Undo a manual fulfillment (use after `/sr-fulfilled-list`). (_e.g._ `/sr-undo 3`)\n' +
          '`/sr-help` — Open this help modal with examples. (_e.g._ `/sr-help`)'
      } },
      { type: 'divider' },
      { type: 'section', text: { type: 'mrkdwn', text: '*How App Home Works*' } },
      { type: 'section', text: { type: 'mrkdwn', text:
          'App Home is your persistent dashboard under Apps → sr-ops-suite.\n' +
          'Run `/sr-back` or `/sr-back-list` to refresh detailed or summary views.\n' +
          'Other commands display ephemeral messages in the channel or DM.'
      } },
      { type: 'divider' },
      { type: 'section', text: { type: 'mrkdwn', text: '*Views*' } },
      { type: 'section', text: { type: 'mrkdwn', text:
          '1) Detailed View (`/sr-back`): pagination, sorting, and per-line actions (Sort by Title, Mark Fulfilled, Update ETA, Clear ETA).\n' +
          '2) Quick Summary (`/sr-back-list`): one line per SKU with actions (Sort by Title, Export CSV, View Help Docs, Mark Fulfilled, Update ETA, Clear ETA).'
      } },
      { type: 'divider' },
      { type: 'section', text: { type: 'mrkdwn', text: '*Ephemeral vs. Visible Blocks*' } },
      { type: 'section', text: { type: 'mrkdwn', text:
          '- Ephemeral: visible only to you; used for confirmations and notices.\n' +
          '- Visible: persist in channels or App Home; used for dashboards.'
      } },
      { type: 'divider' }
    ];
    await client.views.open({
      trigger_id: body.trigger_id,
      view: {
        type: 'modal',
        title: { type: 'plain_text', text: 'sr-ops-suite Help' },
        close: { type: 'plain_text', text: 'Close' },
        blocks: modalBlocks
      }
    });
  });

  // The 'back_to_dashboard' handler is no longer used and has been removed.
  // Build aggregated blocks: one row per ISBN, with sorting
  async function buildAggregatedBlocks(sortKey = 'qty') {
    const orderClause = sortKey === 'title'
      ? 'product_title ASC'
      : 'SUM(ordered_qty) DESC';
    const res = await db.query(`
      SELECT
        product_barcode   AS barcode,
        product_title     AS title,
        product_vendor    AS vendor,
        MIN(order_date)::date AS oldest,
        MAX(order_date)::date AS newest,
        MIN(eta_date)::date AS eta_date,
        SUM(ordered_qty)  AS total_open_qty
      FROM order_line_backorders
      WHERE status = 'open'
        AND override_flag = FALSE
        AND initial_available < 0
      GROUP BY product_barcode, product_title, product_vendor
      ORDER BY ${orderClause}
    `);
    const rows = res.rows;
    const count = rows.length;
    const lastRefreshed = new Date().toLocaleString('en-US', {
      timeZone: 'America/New_York',
      dateStyle: 'short',
      timeStyle: 'short'
    });
    const blocks = [
      { type: 'header', text: { type: 'plain_text', text: '📦 Backorders - ISBN View' } },
      {
        type: 'context',
        elements: [
          { type: 'mrkdwn', text: `*${count} SKUs backordered* • Last refreshed: ${lastRefreshed}` }
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
          { type: 'mrkdwn', text: `*Vendor:*\n\`${r.vendor || 'N/A'}\`` },
          // Only include ETA field if r.eta_date is truthy
          ...(r.eta_date
            ? [{ type: 'mrkdwn', text: `*ETA:*\n\`${new Date(r.eta_date).toLocaleDateString()}\`` }]
            : [])
        ]
      });
      // Only insert aggregated actions block if r.barcode is truthy
      if (r.barcode) {
        const actions = [
          {
            type: 'button',
            text: { type: 'plain_text', text: 'Close' },
            style: 'primary',
            action_id: 'agg_mark_fulfilled',
            value: r.barcode
          },
          {
            type: 'button',
            text: { type: 'plain_text', text: 'Update ETA' },
            action_id: 'agg_update_eta',
            value: r.barcode
          }
        ];
        if (r.eta_date) {
          actions.push({
            type: 'button',
            text: { type: 'plain_text', text: 'Clear ETA' },
            style: 'danger',
            action_id: 'agg_clear_eta',
            value: r.barcode
          });
        }
        blocks.splice(blocks.length, 0, { type: 'actions', elements: actions });
      }
      blocks.push({ type: 'divider' });
    }
    return blocks;
  }
  /**
   * Update ETA via slash command.
   * Usage: /sr-update-eta <orderId> <isbn> <YYYY-MM-DD>
   *    or: /sr-update-eta <isbn> <YYYY-MM-DD>
   */
  slackApp.command('/sr-update-eta', async ({ ack, body, respond }) => {
    await ack();
    const parts = body.text.trim().split(/\s+/);
    let orderId, isbn, etaDate;
    if (parts.length === 3) {
      [orderId, isbn, etaDate] = parts;
      orderId = orderId.startsWith('#') ? orderId : `#${orderId}`;
    } else if (parts.length === 2) {
      [isbn, etaDate] = parts;
    } else {
      return await respond('Usage: `/sr-update-eta <orderId> <isbn> <YYYY-MM-DD>` or `/sr-update-eta <isbn> <YYYY-MM-DD>`');
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(etaDate)) {
      return await respond('Date must be in `YYYY-MM-DD` format.');
    }
    // Build query
    let sql = `
      UPDATE order_line_backorders
         SET eta_date = $1
       WHERE product_barcode = $2
         AND status = 'open'
         AND override_flag = FALSE
    `;
    const params = [etaDate, isbn];
    if (orderId) {
      sql += ' AND order_id = $3';
      params.push(orderId);
    }
    try {
      const result = await db.query(sql, params);
      await respond(`✅ Updated ETA (${etaDate}) for ${result.rowCount} row(s).`);
    } catch (err) {
      console.error('Error updating ETA via slash:', err);
      await respond('❌ Failed to update ETA. Check your inputs.');
    }
  });


  // Publish aggregated blocks to the App Home
  async function publishAggregatedHomeView(userId, client, sortKey = 'qty') {
    const blocks = await buildAggregatedBlocks(sortKey);
    await client.views.publish({
      user_id: userId,
      view: {
        type: 'home',
        private_metadata: JSON.stringify({ view: 'summary' }),
        blocks: [
          {
            type: 'actions',
            elements: [
              {
                type: 'button',
                text: { type: 'plain_text', text: 'Refresh' },
                action_id: 'home_refresh',
                value: 'summary'
              },
              {
                type: 'button',
                text: { type: 'plain_text', text: 'Order View' },
                action_id: 'home_toggle',
                value: 'dashboard'
              },
              {
                type: 'button',
                text: { type: 'plain_text', text: 'Sort by Title' },
                action_id: 'agg_sort_title',
                value: 'title'
              },
              {
                type: 'button',
                text: { type: 'plain_text', text: 'Export CSV' },
                url: `${process.env.SR_APP_URL}/export/backorders-list.csv`,
                action_id: 'download_csv'
              },
              {
                type: 'button',
                text: { type: 'plain_text', text: 'View Help Docs' },
                action_id: 'open_docs'
              }
            ]
          },
          ...blocks
        ]
      }
    });
  }

  // Aggregated backorders ISBN view to App Home
  slackApp.command('/sr-back-list', async ({ ack, command, client }) => {
    await ack();
    // Fire-and-forget background processing
    (async () => {
      try {
        // Notify user
        await client.chat.postEphemeral({
          channel: command.channel_id,
          user: command.user_id,
          text: 'Publishing aggregated backorders by ISBN to your App Home...',
        });
        // Publish summary (default sortKey)
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
      { cmd: '/sr-back', desc: 'Refresh detailed backorders order view', example: '/sr-back' },
      { cmd: '/sr-back sort:title', desc: 'Sort detailed view by title', example: '/sr-back sort:title' },
      { cmd: '/sr-back-list', desc: 'Refresh quick SKU summary', example: '/sr-back-list' },
      { cmd: '/sr-fulfilled-list', desc: 'List last 10 fulfilled backorders', example: '/sr-fulfilled-list' },
      { cmd: '/sr-fulfill-order', desc: 'Fulfill all items on an order', example: '/sr-fulfill-order 60641' },
      { cmd: '/sr-fulfill-item', desc: 'Fulfill specific ISBN on an order', example: '/sr-fulfill-item 60641 9780316580915' },
      { cmd: '/sr-fulfill-isbn', desc: 'Fulfill all backorders for an ISBN', example: '/sr-fulfill-isbn 9780316580915' },
      { cmd: '/sr-update-eta', desc: 'Update ETA for an order+ISBN', example: '/sr-update-eta 60166 9780316580915 2025-06-15' },
      { cmd: '/sr-update-eta', desc: 'Update ETA for all backorders of an ISBN', example: '/sr-update-eta 9780316580915 2025-06-15' },
      { cmd: '/sr-override', desc: 'Override backorder entry (clear or set)', example: '/sr-override 57294 13059031040133 clear preorder' },
      { cmd: '/sr-undo', desc: 'Undo a manual fulfillment (use after `/sr-fulfilled-list` to get its number)', example: '/sr-undo 1' },
    ];
    commands.sort((a, b) => a.cmd.localeCompare(b.cmd));
    const lines = commands.map(c => `• \`${c.cmd}\` – ${c.desc} (_Example: \`${c.example}\`_)`).join('\n');
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

  // Aggregated Update ETA
  slackApp.action('agg_update_eta', async ({ ack, body, client }) => {
    await ack();
    const isbn = body.actions[0].value;
    await client.views.open({
      trigger_id: body.trigger_id,
      view: {
        type: 'modal',
        callback_id: 'update_eta_submit',
        private_metadata: `agg|${isbn}`,
        title: { type: 'plain_text', text: 'Set ETA for SKU' },
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

  // Aggregated Clear ETA
  slackApp.action('agg_clear_eta', async ({ ack, body, client }) => {
    await ack();
    const isbn = body.actions[0].value;
    try {
      const result = await db.query(
        `UPDATE order_line_backorders
           SET eta_date = NULL
         WHERE product_barcode = $1
           AND status = 'open'
           AND override_flag = FALSE`,
        [isbn]
      );
      // Notify user and refresh summary
      await client.chat.postEphemeral({
        channel: body.channel.id,
        user: body.user.id,
        text: `✅ Cleared ETA for ${result.rowCount} row(s) of ISBN ${isbn}.`
      });
      await publishAggregatedHomeView(body.user.id, client);
    } catch (err) {
      console.error('Error clearing aggregated ETA:', err);
    }
  });

  // Aggregated Mark Fulfilled
// Aggregated “Close” button opens action-choice modal
slackApp.action('agg_mark_fulfilled', async ({ ack, body, client }) => {
  await ack();
  const isbn = body.actions[0].value;
  await client.views.open({
    trigger_id: body.trigger_id,
    view: {
      type: 'modal',
      callback_id: 'close_action_choice',
      private_metadata: `agg|${isbn}`,
      title: { type: 'plain_text', text: 'Close Backorder SKU' },
      submit: { type: 'plain_text', text: 'Save' },
      close: { type: 'plain_text', text: 'Cancel' },
      blocks: [
        {
          type: 'input',
          block_id: 'close_action',
          label: { type: 'plain_text', text: 'Choose action' },
          element: {
            type: 'radio_buttons',
            action_id: 'action_choice',
            options: [
              { text: { type: 'plain_text', text: 'Mark Fulfilled' }, value: 'fulfilled' },
              { text: { type: 'plain_text', text: 'Cancel/Refund' }, value: 'cancel_refund' }
            ]
          }
        }
      ]
    }
  });
});
  // Aggregated Sort by Title
  slackApp.action('agg_sort_title', async ({ ack, body, client }) => {
    await ack();
    await publishAggregatedHomeView(body.user.id, client, 'title');
  });

  // Updated home_toggle handler to switch between dashboard and summary
  slackApp.action('home_toggle', async ({ ack, body, client }) => {
    await ack();
    const target = body.actions[0].value;
    // Safely parse private_metadata JSON (fallback if not JSON)
    let metadata;
    try {
      metadata = JSON.parse(body.view.private_metadata);
    } catch {
      metadata = {};
    }
    if (target === 'dashboard') {
      const page = metadata.page || 1;
      const sortKey = metadata.sortKey || 'age';
      await publishBackordersHomeView(body.user.id, client, page, sortKey);
    } else if (target === 'summary') {
      await publishAggregatedHomeView(body.user.id, client);
    }
  });
};