const OpenAI = require("openai");

const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY
});

console.log("✅ OPENAI_API_KEY exists?", !!process.env.OPENAI_API_KEY);

async function callGPT(prompt) {
  const response = await openai.chat.completions.create({
    model: "gpt-4",
    messages: [
      { role: "system", content: "You are a sharp AI operations assistant." },
      { role: "user", content: prompt }
    ]
  });

  return response.choices[0].message.content.trim();
}

module.exports = { callGPT };
