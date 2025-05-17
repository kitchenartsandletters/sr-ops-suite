// src/slack/app.js
require('dotenv').config();
const { Pool } = require('pg');
const db = new Pool({ connectionString: process.env.SR_DATABASE_URL });

const PAGE_SIZE = 10;

/**
 * Registers Slack command and event handlers on the given Bolt App instance.
 * @param {import('@slack/bolt').App} slackApp
 */
module.exports = function registerSlackCommands(slackApp) {
  // Helper to build paginated backorders blocks
  async function buildBackordersBlocks(page) {
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
    const dataRes = await db.query(`
      SELECT
        order_id,
        product_title,
        product_sku,
        product_barcode,
        ordered_qty,
        initial_available,
        initial_backordered,
        line_item_id
      FROM order_line_backorders
      WHERE status = 'open'
        AND override_flag = FALSE
        AND initial_available < 0
      ORDER BY initial_backordered DESC, initial_available ASC
      LIMIT $1 OFFSET $2
    `, [PAGE_SIZE, offset]);
    const rows = dataRes.rows;
    const totalPages = Math.ceil(total / PAGE_SIZE);

    const blocks = [
      { type: 'section', text: { type: 'mrkdwn', text: `*Current Backorders* (Page ${page} of ${totalPages})` } },
      { type: 'divider' }
    ];
    for (const row of rows) {
      blocks.push({
        type: 'section',
        fields: [
          { type: 'mrkdwn', text: `*Order*  \n${row.order_id}` },
          { type: 'mrkdwn', text: `*Title*  \n${row.product_title}` },
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
          style: 'primary',
          disabled: page <= 1
        },
        {
          type: 'button',
          text: { type: 'plain_text', text: 'Next ▶' },
          action_id: 'backorders_next',
          value: String(page),
          style: 'primary',
          disabled: page >= totalPages
        }
      ]
    });
    return { blocks, totalPages, total };
  }

  // Backorders report (paginated)
  slackApp.command('/sr-backorders', async ({ ack, respond, body }) => {
    await ack();
    console.log('Using paginated /sr-backorders, page:', Math.max(1, parseInt(body.text.trim(), 10) || 1));
    const page = Math.max(1, parseInt(body.text.trim(), 10) || 1);
    try {
      const { blocks, total } = await buildBackordersBlocks(page);
      if (!blocks) {
        return respond('✅ No open backorders at the moment!');
      }
      console.log('Slash response_url:', body.response_url);
      console.log('Debug: blocks count =', blocks.length);
      console.dir(blocks.slice(0, 3), { depth: 2 });
      await respond({
        text: `Current Backorders (Page ${page} of ${Math.ceil(total / PAGE_SIZE)})`,
        blocks
      });
    } catch (error) {
      console.error('Error fetching backorders:', error);
      await respond('❌ Sorry, I was unable to load backorders.');
    }
  });

  // Navigate to previous page
  slackApp.action('backorders_prev', async ({ ack, body, client }) => {
    await ack();
    const currentPage = parseInt(body.actions[0].value, 10);
    const prevPage = currentPage - 1;
    const page = prevPage >= 1 ? prevPage : 1;
    try {
      const { blocks } = await buildBackordersBlocks(page);
      await client.chat.update({
        channel: body.channel.id,
        ts: body.message.ts,
        text: `Current Backorders (Page ${page - 1})`,
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
    const nextPage = currentPage + 1;
    try {
      const { blocks, totalPages } = await buildBackordersBlocks(nextPage);
      // If user tried to go past last page, just stay at last
      const page = nextPage > totalPages ? totalPages : nextPage;
      const { blocks: blocksFinal } = await buildBackordersBlocks(page);
      await client.chat.update({
        channel: body.channel.id,
        ts: body.message.ts,
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

  // Other commands can be added here...
};
