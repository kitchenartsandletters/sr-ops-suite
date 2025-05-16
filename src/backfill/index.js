  /**
   * backfill/index.js
   *
   * One‑off script to seed existing backorders into the database.
   */
  require('dotenv').config();

  // Throttle and retry helpers
  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  async function retryWithBackoff(fn, retries = 3, delay = 500) {
    try {
      return await fn();
    } catch (err) {
      // Retry on 429 Too Many Requests
      if (retries > 0 && err.response && err.response.statusCode === 429) {
        await sleep(delay);
        return retryWithBackoff(fn, retries - 1, delay * 2);
      }
      throw err;
    }
  }

  // Sanity check for Shopify credentials
  if (!process.env.SR_SHOPIFY_SHOP || !process.env.SR_SHOPIFY_ACCESS_TOKEN) {
    console.error('🔴 Missing Shopify credentials: SR_SHOPIFY_SHOP or SR_SHOPIFY_ACCESS_TOKEN');
    process.exit(1);
  }
  const Shopify = require('shopify-api-node');
  const { Pool } = require('pg');
const db = new Pool({
  connectionString: process.env.SR_DATABASE_URL,
  ssl: {
    rejectUnauthorized: false
  }
});

  // Initialize Shopify client
  const shopify = new Shopify({
    shopName:   process.env.SR_SHOPIFY_SHOP,
    accessToken: process.env.SR_SHOPIFY_ACCESS_TOKEN
  });

  // Helper to snapshot backorder state into order_line_backorders
  async function processOrder(order) {
    const snapshotTs = new Date().toISOString();
    for (const item of order.line_items) {
      const orderId = order.id.toString();
      const lineItemId = item.id.toString();
      const variantId = item.variant_id;
      const orderedQty = item.quantity;

      // Fetch inventory_item_id
      const variant = await retryWithBackoff(() => shopify.productVariant.get(variantId));
      const inventoryItemId = variant.inventory_item_id;

      // Fetch current available inventory
      const levels = await retryWithBackoff(() =>
        shopify.inventoryLevel.list({
          inventory_item_ids: inventoryItemId.toString()
        })
      );
      const initialAvailable = levels.reduce((sum, lvl) => sum + (lvl.available || 0), 0);

      // Calculate initial backordered quantity
      const initialBackordered = Math.max(0, orderedQty - initialAvailable);

      // Upsert into order_line_backorders
      await db.query(
        `INSERT INTO order_line_backorders
          (order_id, line_item_id, variant_id, ordered_qty, initial_available, initial_backordered, snapshot_ts, status)
         VALUES ($1, $2, $3, $4, $5, $6, $7, 'open')
         ON CONFLICT (order_id, line_item_id) DO UPDATE SET
           initial_available   = EXCLUDED.initial_available,
           initial_backordered = EXCLUDED.initial_backordered,
           snapshot_ts         = EXCLUDED.snapshot_ts,
           status              = 'open';`,
        [orderId, lineItemId, variantId, orderedQty, initialAvailable, initialBackordered, snapshotTs]
      );
      console.log(`Backfilled snapshot for Order ${orderId}, Item ${lineItemId}: backordered=${initialBackordered}, available=${initialAvailable}`);
      await sleep(300);
    }
  }

  // Main backfill function
  async function backfillBackorders() {
    let params = {
      status: 'open',
      limit: 250,
      created_at_min: process.env.SR_BACKFILL_START_DATE
    };

    do {
      const orders = await shopify.order.list(params);
      for (const order of orders) {
        await processOrder(order);
        await sleep(1000);
      }
      params = orders.nextPageParameters;
    } while (params);

    console.log('Backfill complete.');
    process.exit(0);
  }

  // Test Shopify connection
  (async () => {
    try {
      const shopInfo = await shopify.shop.get();
      console.log(`✅ Connected to Shopify store: ${shopInfo.name}`);
    } catch (err) {
      console.error('🔴 Shopify connection failed:', err);
      process.exit(1);
    }

    // Continue with backfill
    try {
      await backfillBackorders();
    } catch (err) {
      console.error('Backfill error:', err);
      process.exit(1);
    }
  })();