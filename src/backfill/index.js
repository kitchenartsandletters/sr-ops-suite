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
      const orderId = order.name;
      const orderDate = order.created_at; // ISO timestamp string
      const lineItemId = item.id.toString();
      const variantId = item.variant_id;
      // Skip if no valid variantId
      if (!variantId) {
        console.warn(`Skipping line item ${lineItemId} in order ${orderId} due to missing variantId`);
        continue;
      }
      const orderedQty = item.quantity;

      const productTitle = item.title;
      const productSku   = item.sku || item.barcode || null;
      // const productBarcode = item.barcode || null;

      // Fetch inventory_item_id
      let variant;
      try {
        variant = await retryWithBackoff(() => shopify.productVariant.get(variantId));
      } catch (err) {
        console.error(`Error fetching variant ${variantId} for order ${orderId}:`, err);
        continue;
      }
      // Fetch product to get vendor code
      let productVendor = null;
      try {
        const product = await retryWithBackoff(() => shopify.product.get(variant.product_id));
        productVendor = product.vendor || null;
        console.log(`Fetched vendor for product ${variant.product_id} in order ${orderId}:`, productVendor);
      } catch (err) {
        console.error(`Error fetching product ${variant.product_id} for vendor on order ${orderId}:`, err);
      }
      const inventoryItemId = variant.inventory_item_id;
      // Use the variant’s barcode for the product barcode
      const productBarcode = variant.barcode || null;

      // Fetch current available inventory
      let levels;
      try {
        levels = await retryWithBackoff(() =>
          shopify.inventoryLevel.list({
            inventory_item_ids: inventoryItemId.toString()
          })
        );
      } catch (err) {
        console.error(`Error fetching inventory for item ${lineItemId} (variant ${variantId}):`, err);
        continue;
      }
      const initialAvailable = levels.reduce((sum, lvl) => sum + (lvl.available || 0), 0);

      // Calculate initial backordered quantity
      const initialBackordered = Math.max(0, orderedQty - initialAvailable);

      // Upsert into order_line_backorders
      await db.query(
        `
        INSERT INTO order_line_backorders (
          order_id,
          line_item_id,
          order_date,
          variant_id,
          ordered_qty,
          initial_available,
          initial_backordered,
          snapshot_ts,
          status,
          product_title,
          product_sku,
          product_barcode
          ,product_vendor
        ) VALUES (
          $1, $2, $3, $4, $5, $6, $7, $8, 'open', $9, $10, $11
          ,$12
        )
        ON CONFLICT (order_id, line_item_id) DO UPDATE SET
          initial_available   = EXCLUDED.initial_available,
          initial_backordered = EXCLUDED.initial_backordered,
          snapshot_ts         = EXCLUDED.snapshot_ts,
          status              = 'open',
          order_date          = EXCLUDED.order_date,
          product_title       = EXCLUDED.product_title,
          product_sku         = EXCLUDED.product_sku,
          product_barcode     = EXCLUDED.product_barcode
          ,product_vendor      = EXCLUDED.product_vendor;
        `,
        [
          orderId,
          lineItemId,
          orderDate,
          variantId,
          orderedQty,
          initialAvailable,
          initialBackordered,
          snapshotTs,
          productTitle,
          productSku,
          productBarcode
          ,productVendor
        ]
      );
      console.log(`Backfilled snapshot for Order ${orderId}, Item ${lineItemId}: backordered=${initialBackordered}, available=${initialAvailable}`);
      await sleep(300);
    }
  }

  // Main backfill function
  async function backfillBackorders() {
   // Step 1: Fetch all orders within the date range
   let allOrders = [];
   let params = {
     status: 'open',
     limit: 250,
     created_at_min: process.env.SR_BACKFILL_START_DATE
   };
   do {
     const orders = await shopify.order.list(params);
     allOrders = allOrders.concat(orders);
     params = orders.nextPageParameters;
   } while (params);

   // Process all orders without preorder filtering
   for (const order of allOrders) {
     await processOrder(order);
     await sleep(1000);
   }

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