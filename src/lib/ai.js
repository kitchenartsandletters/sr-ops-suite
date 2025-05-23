const { Configuration, OpenAIApi } = require("openai");

const configuration = new Configuration({
  apiKey: process.env.OPENAI_API_KEY
});

const openai = new OpenAIApi(configuration);

async function callGPT(prompt) {
  const response = await openai.createChatCompletion({
    model: "gpt-4",
    messages: [
      { role: "system", content: "You are a sharp AI operations assistant." },
      { role: "user", content: prompt }
    ]
  });

  return response.data.choices[0].message.content.trim();
}

module.exports = { callGPT };
