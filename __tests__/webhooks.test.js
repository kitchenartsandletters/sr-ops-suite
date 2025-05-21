const request = require('supertest');
const crypto  = require('crypto');
const app     = require('../src/index');  // your exported Express app

// Ensure the webhook secret is set for HMAC generation
process.env.SR_SHOPIFY_WEBHOOK_SECRET = 'testsecret';
const secret  = process.env.SR_SHOPIFY_WEBHOOK_SECRET;

// Helper to generate a valid HMAC header
function generateHmac(body) {
  return crypto
    .createHmac('sha256', secret)
    .update(body)
    .digest('base64');
}

describe('Shopify /webhooks/shopify endpoint', () => {
  const payload = JSON.stringify({
    id: 123,
    line_items: [
      { id: 111, sku: '9780316580915' }
    ]
  });

  it('responds 200 for valid HMAC', async () => {
    const hmac = generateHmac(payload);
    await request(app)
      .post('/webhooks/shopify')
      .set('X-Shopify-Topic', 'orders/fulfilled')
      .set('X-Shopify-Hmac-Sha256', hmac)
      .set('Content-Type', 'application/json')
      .send(payload)
      .expect(200);
  });

  it('responds 401 for invalid HMAC', async () => {
    await request(app)
      .post('/webhooks/shopify')
      .set('X-Shopify-Topic', 'orders/fulfilled')
      .set('X-Shopify-Hmac-Sha256', 'bad-hmac')
      .set('Content-Type', 'application/json')
      .send(payload)
      .expect(401);
  });
});