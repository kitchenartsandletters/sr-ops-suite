// src/db/backorders.js
/**
 * upsertBackorder: Inserts or updates a backorder record in the database.
 */
const client = require('./client');

async function upsertBackorder({ order_id, line_item_id, qty, inventory_after, status }) {
  const query = `
    INSERT INTO backorders (order_id, line_item_id, qty, inventory_after, status)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (order_id, line_item_id)
    DO UPDATE SET 
      qty = EXCLUDED.qty,
      inventory_after = EXCLUDED.inventory_after,
      status = EXCLUDED.status;
  `;
  await client.query(query, [order_id, line_item_id, qty, inventory_after, status]);
}

module.exports = { upsertBackorder };
