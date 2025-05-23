const { getSystemStatus } = require("../lib/utils");
const { callGPT } = require("../lib/ai");

module.exports = async ({ command, ack, respond }) => {
  try {
    await ack();
    await respond({ text: "✅ /orchestrator command received." });
  } catch (err) {
    console.error("⚠️ Error handling /orchestrator:", err);
  }
};
