const { Pool } = require('pg');
const db = new Pool({ connectionString: process.env.SR_DATABASE_URL });

async function getBackorderStatus() {
  try {
    const result = await db.query(`
      SELECT
        product_barcode,
        product_title,
        product_vendor,
        ordered_qty,
        initial_backordered,
        order_date,
        product_pub_date,
        eta_date
      FROM order_line_backorders
      WHERE status = 'open'
        AND override_flag = FALSE
        AND initial_available < 0
      ORDER BY order_date ASC
      LIMIT 50
    `);

    const formatted = result.rows.map(row => {
      const daysOpen = Math.floor((Date.now() - new Date(row.order_date).getTime()) / (1000 * 60 * 60 * 24));
      return {
        title: row.product_title,
        isbn: row.product_barcode,
        vendor: row.product_vendor,
        qty: row.ordered_qty,
        backordered: row.initial_backordered,
        eta: row.eta_date,
        pub_date: row.product_pub_date,
        days_open: daysOpen
      };
    });

    return { backorders: formatted, timestamp: new Date().toISOString() };
  } catch (err) {
    console.error("Error fetching backorder status:", err);
    return { error: "Could not fetch backorder data." };
  }
}

async function triggerWorkflow(workflowId) {
  // Placeholder: Use GitHub Actions API or Railway API
  return { success: true, triggered: workflowId };
}

async function logAgentAction({
  source,
  action_type,
  action_detail,
  user_id = null,
  result = null,
  correlation_id = null,
  notes = null
}) {
  try {
    await db.query(`
      INSERT INTO agent_action_log (
        timestamp, source, action_type, action_detail, user_id, result, correlation_id, notes
      ) VALUES (
        NOW(), $1, $2, $3, $4, $5, $6, $7
      )
    `, [source, action_type, action_detail, user_id, result, correlation_id, notes]);
  } catch (err) {
    console.error("⚠️ Failed to log agent action:", err);
  }
}

module.exports = { getBackorderStatus, triggerWorkflow, logAgentAction };
