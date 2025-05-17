// src/slack/app.js
require('dotenv').config();
const { Pool } = require('pg');
const db = new Pool({ connectionString: process.env.SR_DATABASE_URL });

/**
 * Registers Slack command and event handlers on the given Bolt App instance.
 * @param {import('@slack/bolt').App} slackApp
 */
module.exports = function registerSlackCommands(slackApp) {
  // Backorders report
  slackApp.command('/sr-backorders', async ({ ack, respond }) => {
    await ack();
    try {
      const result = await db.query(`
        SELECT 
          order_id,
          product_title,
          product_sku,
          product_barcode,
          ordered_qty,
          initial_available,
          initial_backordered
        FROM order_line_backorders
        WHERE status = 'open'
          AND override_flag = FALSE
          AND initial_available < 0
        ORDER BY initial_backordered DESC, initial_available ASC
        LIMIT 50
      `);
      const rows = result.rows;
      // Only show up to MAX_DISPLAY entries to avoid Slack block limits
      const MAX_DISPLAY = 25;
      const displayRows = rows.slice(0, MAX_DISPLAY);
      if (rows.length === 0) {
        return respond('✅ No open backorders at the moment!');
      }
      const blocks = [
        { type: 'section', text: { type: 'mrkdwn', text: '*Current Backorders*' } },
        { type: 'divider' }
      ];
      for (const row of displayRows) {
        blocks.push({
          type: 'section',
          text: {
            type: 'mrkdwn',
            text: `*Order:* ${row.order_id} • *Title:* ${row.product_title} • *Author:* ${row.product_sku}\n• *ISBN:* ${row.product_barcode} • Ordered: ${row.ordered_qty}\n• Available: ${row.initial_available}\n• Backordered: ${row.initial_backordered}`
          }
        });
      }
      if (rows.length > MAX_DISPLAY) {
        blocks.push({
          type: 'context',
          elements: [
            { type: 'mrkdwn', text: `Showing ${MAX_DISPLAY} of ${rows.length} backorders. Narrow your query or use pagination.` }
          ]
        });
      }
      await respond({ blocks });
    } catch (error) {
      console.error('Error fetching backorders:', error);
      await respond('❌ Sorry, I was unable to load backorders.');
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

  // Other commands can be added here...
};
