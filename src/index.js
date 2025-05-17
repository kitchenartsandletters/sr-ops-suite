// src/index.js

// Load environment variables
require('dotenv').config();

const express = require('express');
const bodyParser = require('body-parser');
const { App, ExpressReceiver } = require('@slack/bolt');

// Import the Shopify orders webhook handler
const ordersWebhookApp = require('./webhooks/orders');

// Slack Events API receiver
const slackReceiver = new ExpressReceiver({
  signingSecret: process.env.SR_SLACK_SIGNING_SECRET,
  endpoints: '/slack/events'
});

// Slack Bolt App
const slackApp = new App({
  token: process.env.SR_SLACK_BOT_TOKEN,
  receiver: slackReceiver
});

const app = express();

// Mount the Shopify orders/create webhook at the correct path
app.use('/webhooks/orders', ordersWebhookApp);

// Mount Slack Events handler
app.use(slackReceiver.router);

// For all other routes (e.g., Slack commands), you can parse JSON bodies
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));

// Mount Slack command and event handlers
require('./slack/app')(slackApp);

// Start server
const PORT = process.env.PORT || 3001;
app.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});
