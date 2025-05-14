const { Client } = require('pg');
const client = new Client({ connectionString: process.env.SR_DATABASE_URL });
client.connect();
module.exports = client;