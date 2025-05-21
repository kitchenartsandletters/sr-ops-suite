// src/index.js

// Load environment variables
require('dotenv').config();

const express = require('express');
const bodyParser = require('body-parser');
const { App, ExpressReceiver } = require('@slack/bolt');
const { Pool } = require('pg');
const db = new Pool({ connectionString: process.env.SR_DATABASE_URL });

// After existing requires
const formatEDT = () => {
  const now = new Date().toLocaleString('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  });
  // Convert "MM/DD/YYYY, HH:MM" to "MMDDYYYY_HHMM"
  const [datePart, timePart] = now.split(', ');
  const filenameDate = datePart.replace(/\//g, '');
  const filenameTime = timePart.replace(/:/g, '');
  return `${filenameDate}_${filenameTime}`;
};

// Import the Shopify orders webhook handler
const ordersWebhookApp = require('./webhooks/orders');

// Slack Events API receiver
const slackReceiver = new ExpressReceiver({
  signingSecret: process.env.SR_SLACK_SIGNING_SECRET,
  endpoints: '/slack/events',
  disableBodyParser: true
});

// Slack Bolt App
const slackApp = new App({
  token: process.env.SR_SLACK_BOT_TOKEN,
  receiver: slackReceiver
});


const app = express();

// Quick‐list export for grouped backorders
app.get('/export/backorders-list.csv', async (req, res) => {
  try {
    const { rows } = await db.query(`
      SELECT
        product_barcode AS isbn,
        product_title AS title,
        MIN(order_date)::date AS oldest,
        MAX(order_date)::date AS newest,
        SUM(ordered_qty) AS total_open_qty,
        product_vendor AS vendor
      FROM order_line_backorders
      WHERE status = 'open'
        AND override_flag = FALSE
        AND initial_available < 0
      GROUP BY product_barcode, product_title, product_vendor
      ORDER BY total_open_qty DESC
    `);
    res.setHeader('Content-Type', 'text/csv');
    const ts = formatEDT();
    res.setHeader(
      'Content-Disposition',
      `attachment; filename="backorders-list_${ts}.csv"`
    );
    let csv = 'ISBN,Title,Oldest,Newest,OpenQty,Vendor\n';
    // Helper to format dates as MM/DD/YYYY
    const formatDate = dateStr => {
      if (!dateStr) return '';
      const d = new Date(dateStr);
      return `${String(d.getMonth()+1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}/${d.getFullYear()}`;
    };
    for (const r of rows) {
      csv += `${r.isbn},"${r.title}",${formatDate(r.oldest)},${formatDate(r.newest)},${r.total_open_qty},"${r.vendor}"\n`;
    }
    res.send(csv);
  } catch (err) {
    console.error('Error generating quick-list CSV:', err);
    res.status(500).send('Internal Server Error');
  }
});

// Redirect non-.csv export to .csv endpoint
app.get('/export/backorders-list', (req, res) => {
  res.redirect(301, '/export/backorders-list.csv');
});


// Full backorders export
app.get('/export/backorders.csv', async (req, res) => {
  try {
    const { rows } = await db.query(`
      SELECT
        order_id,
        shopify_order_id,
        product_barcode AS isbn,
        product_title AS title,
        order_date::date,
        eta_date::date,
        initial_backordered AS open_qty,
        product_vendor AS vendor
      FROM order_line_backorders
      WHERE status = 'open'
        AND override_flag = FALSE
        AND initial_available < 0
      ORDER BY order_date ASC
    `);
    res.setHeader('Content-Type', 'text/csv');
    const ts = formatEDT();
    res.setHeader(
      'Content-Disposition',
      `attachment; filename="backorders_${ts}.csv"`
    );
    let csv = 'OrderID,ShopifyOrderID,ISBN,Title,OrderDate,ETA,OpenQty,Vendor\n';
    for (const r of rows) {
      csv += `${r.order_id},${r.shopify_order_id},${r.isbn},"${r.title}",${r.order_date},${r.eta_date || ''},${r.open_qty},"${r.vendor}"\n`;
    }
    res.send(csv);
  } catch (err) {
    console.error('Error generating full backorders CSV:', err);
    res.status(500).send('Internal Server Error');
  }
});

// Mount the Shopify orders/create webhook at the correct path
app.use('/webhooks/orders', ordersWebhookApp);

// Slack Events endpoint with raw-body parsing for JSON and URL-encoded payloads (1mb limit)
app.post(
  '/slack/events',
  bodyParser.raw({
    type: ['application/json', 'application/x-www-form-urlencoded'],
    limit: '1mb'
  }),
  slackReceiver.router
);

// Now apply JSON/urlencoded for other routes
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));

// Mount Slack command and event handlers
require('./slack/app')(slackApp);

// Start server
const PORT = process.env.PORT || 3001;
app.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});
