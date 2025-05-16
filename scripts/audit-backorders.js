// scripts/audit-backorders.js
require('dotenv').config();
const Shopify = require('shopify-api-node');

// Throttling and retry helpers
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
async function retryWithBackoff(fn, retries = 3, delay = 500) {
  try {
    return await fn();
  } catch (err) {
    if (retries > 0 && err.response && err.response.statusCode === 429) {
      await sleep(delay);
      return retryWithBackoff(fn, retries - 1, delay * 2);
    }
    throw err;
  }
}

// Cache results of isPreorder to avoid repeat API calls
const preorderCache = new Map();

const client = new Shopify({
  shopName:    process.env.SR_SHOPIFY_SHOP,
  accessToken: process.env.SR_SHOPIFY_ACCESS_TOKEN,
});

// Helper to determine if a product is actively preorderable
async function isPreorder(productId) {
  try {
    if (!productId) return false;
    // Fetch product data (tags and metafields)
    const product = await retryWithBackoff(() => client.product.get(productId));
    if (!product || typeof product !== 'object') return false;

    // Normalize tags: Shopify returns a comma-separated string
    const tagsString = product.tags || '';
    const tags = tagsString.split(',').map(t => t.trim()).filter(Boolean);

    const hasPreorderTag = tags.includes('preorder');

    // Fetch pre-order metafield if exists
    let pubDate;
    const mfList = await retryWithBackoff(() =>
      client.metafield.list({
        metafield: { owner_resource: 'product', owner_id: productId },
        namespace: 'global',
        key: 'pub_date'
      })
    );
    if (Array.isArray(mfList) && mfList.length && mfList[0].value) {
      pubDate = new Date(mfList[0].value);
    }

    // Fallback tag date
    const fallbackTag = tags.find(t => /^\d{2}-\d{2}-\d{4}$/.test(t));
    if (!pubDate && fallbackTag) {
      const [m, d, y] = fallbackTag.split('-').map(Number);
      pubDate = new Date(y, m - 1, d);
    }

    if (hasPreorderTag && pubDate) {
      const today = new Date().toLocaleString('en-US', { timeZone: 'America/New_York' });
      if (new Date(today) < pubDate) {
        return true;
      }
    }
    return false;
  } catch (err) {
    console.error(`isPreorder error for product ${productId}:`, err);
    return false;
  }
}

async function fetchInventoryItemId(variantId) {
  const variant = await retryWithBackoff(() => client.productVariant.get(variantId));
  return variant.inventory_item_id;
}

async function fetchInventoryLevel(inventoryItemId) {
  try {
    // Pass inventory_item_ids as a string
    const levels = await retryWithBackoff(() =>
      client.inventoryLevel.list({
        inventory_item_ids: inventoryItemId.toString()
        // if you ever include location_ids, do:
        // location_ids: locationIds.join(',')
      })
    );
    console.debug(`Inventory levels for item ${inventoryItemId}:`, levels);
    const totalAvailable = levels.reduce((sum, lvl) => sum + (lvl.available || 0), 0);
    return totalAvailable;
  } catch (err) {
    console.error(
      `Error fetching inventory for item ${inventoryItemId}:`,
      err.response?.body ?? err
    );
    return null;
  }
}

(async () => {
  const thirtyDaysAgo = new Date();
  thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
  const createdAtMin = thirtyDaysAgo.toISOString();

  // Paginate through all orders in the last 30 days
  let params = { limit: 250, status: 'any', created_at_min: createdAtMin };
  const rows = [];
  do {
    const orders = await client.order.list(params);
    for (const order of orders) {
      for (const item of order.line_items) {
        const { quantity, fulfillable_quantity, variant_id } = item;
        const fulfillableQuantity = fulfillable_quantity;
        if (fulfillableQuantity <= 0) continue;  // only open items
        const inventoryItemId = await fetchInventoryItemId(variant_id);
        const available = await fetchInventoryLevel(inventoryItemId);
        const backorderedQty = Math.max(0, quantity - fulfillableQuantity);
        const nowOversold = available < 0;
        const trulyBackordered = fulfillableQuantity > 0 && (backorderedQty > 0 || nowOversold);
        if (!trulyBackordered) continue;
        // Only now check for preorder status, using cache
        const pid = item.product_id;
        let isPre = false;
        if (pid) {
          if (preorderCache.has(pid)) {
            isPre = preorderCache.get(pid);
          } else {
            try {
              isPre = await isPreorder(pid);
            } catch {
              isPre = false;
            }
            preorderCache.set(pid, isPre);
          }
        }
        if (isPre) continue;
        // Candidate confirmed as backorder
        rows.push({
          order: order.name,
          title: item.title,
          ordered: quantity,
          fulfillableQuantity,
          available,
          backorderedQty
        });
        await sleep(300);
      }
      await sleep(500);
    }
    params = orders.nextPageParameters;
  } while (params);

  console.table(rows);
})();