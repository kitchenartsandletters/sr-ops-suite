const { getSystemStatus } = require("../lib/utils");
const { callGPT } = require("../lib/ai");

module.exports = async ({ command, ack, respond }) => {
  await ack(); // respond to Slack immediately

  // Defer heavy logic to avoid blocking
  setTimeout(async () => {
    try {
      const status = await getSystemStatus();

      const gptResponse = await callGPT(`
You are an operations orchestrator assistant. Analyze the following system status and provide:
1. A concise summary
2. 1–2 recommended next actions
3. Bullet points, under 150 words

System Status:
${JSON.stringify(status, null, 2)}
      `);

      await respond({
        text: "*🧠 Weekly Orchestrator Summary*",
        blocks: [
          {
            type: "section",
            text: { type: "mrkdwn", text: `*System Status Summary:*\n${gptResponse}` }
          },
          {
            type: "actions",
            elements: [
              {
                type: "button",
                text: { type: "plain_text", text: "Retry KIT-84" },
                action_id: "retry_kit_84"
              },
              {
                type: "button",
                text: { type: "plain_text", text: "View Logs" },
                url: "https://github.com/your-org/your-repo/actions"
              }
            ]
          }
        ]
      });
    } catch (err) {
      console.error("Error in /orchestrator (deferred):", err);
      await respond({ text: "❌ Failed to retrieve system status or generate summary." });
    }
  }, 0); // defer execution
};
