
  /**
   * backfill/index.js
   *
   * One‑off script to seed existing backorders into the database.
   */
  require('dotenv').config();
  // Sanity check for Shopify credentials
  if (!process.env.SR_SHOPIFY_SHOP || !process.env.SR_SHOPIFY_ACCESS_TOKEN) {
    console.error('🔴 Missing Shopify credentials: SR_SHOPIFY_SHOP or SR_SHOPIFY_ACCESS_TOKEN');
    process.exit(1);
  }
  const Shopify = require('shopify-api-node');
  const { upsertBackorder } = require('../db/backorders');

  // Initialize Shopify client
  const shopify = new Shopify({
    shopName:   process.env.SR_SHOPIFY_SHOP,
    accessToken: process.env.SR_SHOPIFY_ACCESS_TOKEN
  });

  // Helper to determine backordered quantity
  async function processOrder(order) {
    for (const item of order.line_items) {
      const orderedQty = item.quantity;
      const fulfillable = item.fulfillableQuantity;
      if (fulfillable < orderedQty) {
        const backorderedQty = orderedQty - fulfillable;
        await upsertBackorder({
          order_id: order.id.toString(),
          line_item_id: item.id.toString(),
          qty: backorderedQty,
          inventory_after: fulfillable - backorderedQty,
          status: 'open'
        });
        console.log(`Backfilled backorder for Order ${order.id}, Item ${item.id}: ${backorderedQty}`);
      }
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