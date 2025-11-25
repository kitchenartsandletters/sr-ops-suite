const { Pool } = require("pg");
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


const { callGPT } = require('../lib/ai');
const { logAgentAction } = require('../lib/utils');

module.exports = async ({ command, ack, respond }) => {
  await ack();

  setTimeout(async () => {
    try {
      const status = await getBackorderStatus();

      const gptResponse = await callGPT(`
You are a logistics assistant summarizing open backorders.

Backorder items:
${JSON.stringify(status.backorders, null, 2)}

Summarize:
1. Key titles or ISBNs with high open quantities or long aging
2. Any trends by vendor or missing ETA
3. Suggestions in plain language, max 150 words
      `);

      await logAgentAction({
        source: "gpt",
        action_type: "suggestion",
        action_detail: {
          summary: gptResponse,
          input_count: status.backorders?.length || 0
        },
        user_id: command.user_id,
        result: "suggested"
      });

      await respond({
        text: "*📦 Backorder Summary*",
        blocks: [
          {
            type: "section",
            text: {
              type: "mrkdwn",
              text: gptResponse
            }
          }
        ]
      });
    } catch (err) {
      console.error("Error in /orchestrator flow:", err);
      await respond({ text: "❌ Could not generate summary." });
    }
  }, 0);
};
