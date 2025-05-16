

// src/utils/verify-shopify-webhook.js
const crypto = require('crypto');

/**
 * Middleware to verify Shopify webhooks
 * @param {string} secret - Your Shopify webhook shared secret
 */
function verifyShopifyWebhook(secret) {
  return (req, res, next) => {
    try {
      const hmacHeader = req.get('X-Shopify-Hmac-Sha256');
      if (!hmacHeader) {
        return res.status(401).send('Missing HMAC header');
      }

      // req.body is a Buffer because bodyParser.raw was used
      const body = req.body.toString('utf8');

      // Compute HMAC using the shared secret
      const generatedHmac = crypto
        .createHmac('sha256', secret)
        .update(body, 'utf8')
        .digest('base64');

      // Use timingSafeEqual to avoid timing attacks
      const bufferReceived = Buffer.from(hmacHeader, 'base64');
      const bufferGenerated = Buffer.from(generatedHmac, 'base64');

      if (
        bufferReceived.length !== bufferGenerated.length ||
        !crypto.timingSafeEqual(bufferReceived, bufferGenerated)
      ) {
        return res.status(401).send('HMAC validation failed');
      }

      // HMAC is valid, continue to handler
      next();
    } catch (err) {
      console.error('Error verifying Shopify webhook:', err);
      res.status(500).send('Webhook verification error');
    }
  };
}

module.exports = { verifyShopifyWebhook };