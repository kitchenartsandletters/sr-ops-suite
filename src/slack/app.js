// src/slack/app.js
require('dotenv').config();
const { App, ExpressReceiver } = require('@slack/bolt');

console.log('BOT TOKEN:', process.env.SR_SLACK_BOT_TOKEN ? '✅ loaded' : '❌ missing');

// Create a receiver for Slack events
const receiver = new ExpressReceiver({
  signingSecret: process.env.SR_SLACK_SIGNING_SECRET,
  endpoints: '/slack/events'
});

// Initialize Bolt App with the receiver
const app = new App({
  token: process.env.SR_SLACK_BOT_TOKEN,
  receiver
});

// Example slash command
app.command('/sr-backorders', async ({ ack, respond }) => {
  await ack();
  await respond('Here are your backorders...');
});

// Update ETA command
app.command('/sr-update-eta', async ({ ack, body, respond }) => {
  await ack();
  // body.text contains arguments, e.g. "<order_id> YYYY-MM-DD"
  await respond(`Updating ETA for backorder: ${body.text}`);
});

// Fulfill Backorder command
app.command('/sr-fulfill-backorder', async ({ ack, body, respond }) => {
  await ack();
  // body.text contains order identifier
  await respond(`Marking backorder as fulfilled: ${body.text}`);
});

// Create a hold request
app.command('/sr-hold-create', async ({ ack, body, respond }) => {
    await ack();
    // body.text contains order identifier
    await respond(`Creating hold request for: ${body.text}`);
});

// List hold requests
app.command('/sr-holds', async ({ ack, body, respond }) => {
    await ack();
    // body.text contains order identifier
    await respond(`Listing hold requests for: ${body.text}`);
});

// Start the app
(async () => {
  const port = process.env.PORT || 3001;
  await app.start(port);
  console.log(`⚡️ Slack Bolt app running on port ${port}`);
})();