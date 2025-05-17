// src/utils/preorder.js
require('dotenv').config();
const Shopify = require('shopify-api-node');

// Initialize Shopify client
const client = new Shopify({
  shopName:    process.env.SR_SHOPIFY_SHOP,
  accessToken: process.env.SR_SHOPIFY_ACCESS_TOKEN
});

/**
 * Determines if a product is actively preorderable.
 * Checks for a 'preorder' tag and a future publication date metafield.
 * @param {number|string} productId - The Shopify product ID
 * @returns {Promise<boolean>} True if the product is an active preorder
 */
async function isPreorder(productId) {
  // Bail immediately if no valid productId
  if (!productId || (typeof productId !== 'string' && typeof productId !== 'number')) {
    return false;
  }
  try {
    // Fetch product data
    const product = await client.product.get(productId);
    // Normalize tags: Shopify returns a comma-separated string
    const tagsString = product.tags || '';
    const tags = tagsString.split(',').map(t => t.trim()).filter(Boolean);
    const hasPreorderTag = tags.includes('preorder');

    // Fetch publication date metafield
    let pubDate;
    const mfList = await client.metafield.list({
      metafield: { owner_resource: 'product', owner_id: productId },
      namespace: 'global',
      key: 'pub_date'
    });
    if (Array.isArray(mfList) && mfList.length && mfList[0].value) {
      pubDate = new Date(mfList[0].value);
    }

    // Fallback date from tags (MM-DD-YYYY)
    if (!pubDate) {
      const fallbackTag = tags.find(t => /^\d{2}-\d{2}-\d{4}$/.test(t));
      if (fallbackTag) {
        const [m, d, y] = fallbackTag.split('-').map(Number);
        pubDate = new Date(y, m - 1, d);
      }
    }

    // If tagged and pubDate is in the future in ET, it's a preorder
    if (hasPreorderTag && pubDate) {
      const nowET = new Date().toLocaleString('en-US', { timeZone: 'America/New_York' });
      if (new Date(nowET) < pubDate) {
        return true;
      }
    }

    return false;
  } catch (err) {
    console.error(`isPreorder error for product ${productId}:`, err);
    return false;
  }
}

module.exports = { isPreorder };
