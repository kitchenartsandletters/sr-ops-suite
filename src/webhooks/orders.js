require('dotenv').config();
const express = require('express');
const bodyParser = require('body-parser');
const { verifyShopifyWebhook } = require('../utils/verify-shopify-webhook');
const Shopify = require('shopify-api-node');
const { Pool } = require('pg');

// Initialize router
const router = express.Router();
// Use raw body parser for webhook verification
router.use(bodyParser.raw({ type: 'application/json' }));

// Initialize Shopify client
const shopify = new Shopify({
  shopName:    process.env.SR_SHOPIFY_SHOP,
  accessToken: process.env.SR_SHOPIFY_ACCESS_TOKEN
});

// Initialize Postgres pool
const db = new Pool({ connectionString: process.env.SR_DATABASE_URL });

// Webhook handler for new orders
router.post(
  '/',
  verifyShopifyWebhook(process.env.SR_SHOPIFY_SECRET),
  async (req, res) => {
    try {
      const order = JSON.parse(req.body.toString());
      const snapshotTs = new Date().toISOString();

      for (const item of order.line_items) {
        const { id: line_item_id, variant_id, quantity: ordered_qty } = item;

        // Fetch inventory_item_id via variant
        const variant = await shopify.productVariant.get(variant_id);
        const inventoryItemId = variant.inventory_item_id;

        // Fetch current available inventory
        const levels = await shopify.inventoryLevel.list({
          inventory_item_ids: inventoryItemId.toString()
        });
        const initial_available = levels.reduce((sum, lvl) => sum + (lvl.available || 0), 0);

        // Calculate initial backordered quantity
        const initial_backordered = Math.max(0, ordered_qty - initial_available);

        // Upsert into order_line_backorders
        await db.query(
          `INSERT INTO order_line_backorders
            (order_id, line_item_id, variant_id, ordered_qty, initial_available, initial_backordered, snapshot_ts, status)
           VALUES ($1,$2,$3,$4,$5,$6,$7,'open')
           ON CONFLICT (order_id, line_item_id) DO UPDATE SET
             initial_available   = EXCLUDED.initial_available,
             initial_backordered = EXCLUDED.initial_backordered,
             snapshot_ts         = EXCLUDED.snapshot_ts,
             status              = 'open';`,
          [order.name, line_item_id, variant_id, ordered_qty, initial_available, initial_backordered, snapshotTs]
        );
      }

      res.status(200).send('OK');
    } catch (err) {
      console.error('Webhook processing error:', err);
      res.status(500).send('Error');
    }
  }
);

module.exports = router;