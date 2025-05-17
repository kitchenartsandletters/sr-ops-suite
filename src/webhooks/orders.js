require('dotenv').config();
const express = require('express');
const bodyParser = require('body-parser');
const { verifyShopifyWebhook } = require('../utils/verify-shopify-webhook');
const { isPreorder } = require('../utils/preorder');
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
      const orderDate = order.created_at;  // ISO timestamp when the order was placed
      const snapshotTs = new Date().toISOString();

      for (const item of order.line_items) {
        // Determine if this is a preorder; skip if so, but guard against errors
        let skipPreorder = false;
        try {
          skipPreorder = await isPreorder(item.product_id);
        } catch (err) {
          console.error(`isPreorder error for product ${item.product_id}:`, err);
          // On error, treat as non-preorder to ensure processing continues
          skipPreorder = false;
        }
        if (skipPreorder) {
          console.log(`Skipping preorder item for Order ${order.name}, Product ${item.product_id}`);
          continue;
        }
        const { id: line_item_id, variant_id, quantity: ordered_qty } = item;

        const productTitle = item.title;
        const productSku   = item.sku || item.barcode || null;

        // Fetch inventory_item_id via variant
        const variant = await shopify.productVariant.get(variant_id);
        const inventoryItemId = variant.inventory_item_id;

        // Fetch product to get vendor code
        let productVendor = null;
        try {
          const product = await shopify.product.get(variant.product_id);
          productVendor = product.vendor || null;
        } catch (err) {
          console.error(`Error fetching product ${variant.product_id} for vendor:`, err);
        }

        // Use the variant’s barcode for productBarcode
        const productBarcode = variant.barcode || null;

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
            (order_id, line_item_id, order_date, variant_id, ordered_qty, initial_available,
             initial_backordered, snapshot_ts, status, product_title, product_sku, product_barcode,
             product_vendor)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'open',$9,$10,$11,$12)
           ON CONFLICT (order_id, line_item_id) DO UPDATE SET
             initial_available   = EXCLUDED.initial_available,
             initial_backordered = EXCLUDED.initial_backordered,
             snapshot_ts         = EXCLUDED.snapshot_ts,
             status              = 'open',
             order_date          = EXCLUDED.order_date,
             product_title       = EXCLUDED.product_title,
             product_sku         = EXCLUDED.product_sku,
             product_barcode     = EXCLUDED.product_barcode,
             product_vendor      = EXCLUDED.product_vendor;`,
          [
            order.name,
            line_item_id,
            orderDate,
            variant_id,
            ordered_qty,
            initial_available,
            initial_backordered,
            snapshotTs,
            productTitle,
            productSku,
            productBarcode,
            productVendor
          ]
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