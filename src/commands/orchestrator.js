const { WebClient } = require("@slack/web-api");
const { getSystemStatus, triggerWorkflow } = require("../lib/utils");
const { callGPT } = require("../lib/ai");

module.exports = async ({ command, ack, respond }) => {
  await ack();

  // Fetch system status (from Supabase, GitHub, Railway, etc.)
  const status = await getSystemStatus();

  // Ask GPT to summarize status and suggest next actions
  const gptResponse = await callGPT(`
You are an operations orchestrator assistant. Analyze the following system status and provide:
1. A concise summary
2. 1–2 recommended next actions
3. Bullet points, under 150 words

System Status:
${JSON.stringify(status, null, 2)}
  `);

  // Construct Slack message with interactive buttons
  await respond({
    text: "*🧠 Weekly Orchestrator Summary*",
    blocks: [
      {
        type: "section",
        text: { type: "mrkdwn", text: `*System Status Summary:*
${gptResponse}` }
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
};
