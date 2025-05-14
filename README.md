# SR Ops Suite

Slack-driven Shipping & Receiving operations toolkit.

## Setup

1. Copy `.env.example` to `.env` and fill in credentials.
2. Install dependencies:
   ```bash
   npm install
3. npm run backfill
4. Start the Slack bot:
   npm start

### 4. Scripts

1. **Backfill:** `scripts/backfill.sh` wraps `npm run backfill`.
2. **Cron Jobs:** Use system crontab or GitHub Actions to run `npm run job:aging`, etc.

### 5. Directory & File Stubs

- **`src/backfill/index.js`**
  ```js
  require('dotenv').config();
  console.log('Backfill script stub');