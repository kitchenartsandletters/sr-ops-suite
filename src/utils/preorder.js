// src/utils/preorder.js
require('dotenv').config();
const fetch = require('node-fetch');

// GraphQL endpoint and headers
const SHOP = process.env.SR_SHOPIFY_SHOP;
const TOKEN = process.env.SR_SHOPIFY_ACCESS_TOKEN;
const GRAPHQL_URL = `https://${SHOP}/admin/api/2025-01/graphql.json`;
const HEADERS = {
  "Content-Type": "application/json",
  "X-Shopify-Access-Token": TOKEN
};

async function isPreorder(productId) {
  if (!productId) return false;
  const gid = `gid://shopify/Product/${productId}`;
  const query = `
    query productPreorderStatus($id: ID!) {
      product(id: $id) {
        tags
        collections(first: 1, query: "handle:pre-order") {
          edges { node { id } }
        }
        metafields(namespace: "custom", first: 1, keys: ["pub_date"]) {
          edges { node { value } }
        }
      }
    }
  `;
  const res = await fetch(GRAPHQL_URL, {
    method: 'POST',
    headers: HEADERS,
    body: JSON.stringify({ query, variables: { id: gid } })
  });
  if (!res.ok) return false;
  const { data } = await res.json();
  if (!data || !data.product) return false;

  const { tags = '', collections, metafields } = data.product;
  const tagList = tags.split(',').map(t => t.trim().toLowerCase());
  const hasTag = tagList.includes('preorder');
  const inCollection = (collections.edges || []).length > 0;

  // Parse pub_date value if present
  let futurePub = false;
  const mfEdge = (metafields.edges || [])[0];
  if (mfEdge && mfEdge.node && mfEdge.node.value) {
    const [m, d, y] = mfEdge.node.value.split('-').map(Number);
    const pubDate = new Date(y, m - 1, d);
    futurePub = pubDate > new Date();
  }

  // At least two of three must be true
  return [hasTag, inCollection, futurePub].filter(Boolean).length >= 2;
}

module.exports = { isPreorder };
