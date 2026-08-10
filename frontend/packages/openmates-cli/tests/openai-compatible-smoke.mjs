#!/usr/bin/env node
// frontend/packages/openmates-cli/tests/openai-compatible-smoke.mjs
//
// Live smoke test for OpenMates' OpenAI-compatible API from Node.js.
// It checks the official OpenAI JS SDK plus the Vercel AI SDK
// `@ai-sdk/openai-compatible` provider. Requires
// OPENMATES_TEST_ACCOUNT_API_KEY and optional OPENMATES_OPENAI_COMPAT_MODEL.

const DEFAULT_BASE_URL = 'https://api.dev.openmates.org/v1';
const DEFAULT_ORIGIN = 'https://app.dev.openmates.org';

function requireEnv(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required environment variable: ${name}`);
  return value;
}

function argValue(name, fallback) {
  const index = process.argv.indexOf(name);
  if (index !== -1 && process.argv[index + 1]) return process.argv[index + 1];
  return fallback;
}

async function importOrExplain(moduleName, installHint) {
  try {
    return await import(moduleName);
  } catch (error) {
    throw new Error(`${installHint}\nOriginal import error for ${moduleName}: ${error.message}`);
  }
}

async function main() {
  const apiKey = requireEnv('OPENMATES_TEST_ACCOUNT_API_KEY');
  const baseURL = argValue('--base-url', process.env.OPENMATES_OPENAI_COMPAT_BASE_URL ?? DEFAULT_BASE_URL);
  const origin = argValue('--origin', process.env.OPENMATES_OPENAI_COMPAT_ORIGIN ?? DEFAULT_ORIGIN);

  const { default: OpenAI } = await importOrExplain(
    'openai',
    'Install the official OpenAI JS SDK before running this smoke test: pnpm add -D openai',
  );
  const openai = new OpenAI({ apiKey, baseURL, defaultHeaders: { Origin: origin } });

  const models = await openai.models.list();
  const model = argValue('--model', process.env.OPENMATES_OPENAI_COMPAT_MODEL ?? models.data?.[0]?.id);
  if (!model) throw new Error('/v1/models returned no models');
  console.log(`[openai-compat-js] model=${model}`);

  const retrieved = await openai.models.retrieve(model);
  if (retrieved.id !== model) throw new Error(`Unexpected retrieve result: ${retrieved.id}`);

  const textResponse = await openai.chat.completions.create({
    model,
    messages: [{ role: 'user', content: 'Reply with exactly: OK' }],
    temperature: 0,
  });
  const text = textResponse.choices[0]?.message?.content ?? '';
  if (!text.trim()) throw new Error('Official OpenAI JS chat completion returned empty content');
  console.log(`[openai-compat-js] openai-js=${JSON.stringify(text.slice(0, 80))}`);

  const tools = [
    {
      type: 'function',
      function: {
        name: 'get_weather',
        description: 'Get weather for a city.',
        parameters: {
          type: 'object',
          properties: { city: { type: 'string' } },
          required: ['city'],
        },
      },
    },
  ];
  const toolResponse = await openai.chat.completions.create({
    model,
    messages: [{ role: 'user', content: 'What is the weather in Berlin?' }],
    tools,
    tool_choice: { type: 'function', function: { name: 'get_weather' } },
  });
  const toolCall = toolResponse.choices[0]?.message?.tool_calls?.[0];
  if (!toolCall || toolCall.function?.name !== 'get_weather') {
    throw new Error('Official OpenAI JS forced function tool call returned no get_weather tool_call');
  }
  console.log(`[openai-compat-js] tool_call=${toolCall.id}:${toolCall.function.name}`);

  const [{ createOpenAICompatible }, { generateText, streamText }] = await Promise.all([
    importOrExplain(
      '@ai-sdk/openai-compatible',
      'Install the Vercel OpenAI-compatible provider before running this smoke test: pnpm add -D @ai-sdk/openai-compatible ai',
    ),
    importOrExplain('ai', 'Install the Vercel AI SDK before running this smoke test: pnpm add -D ai'),
  ]);
  const provider = createOpenAICompatible({
    name: 'openmates',
    apiKey,
    baseURL,
    headers: { Origin: origin },
    includeUsage: true,
  });
  const aiSdkResult = await generateText({
    model: provider.chatModel(model),
    prompt: 'Reply with exactly: OK',
    temperature: 0,
  });
  if (!aiSdkResult.text.trim()) throw new Error('Vercel AI SDK generateText returned empty content');
  console.log(`[openai-compat-js] ai-sdk=${JSON.stringify(aiSdkResult.text.slice(0, 80))}`);

  const streamResult = streamText({
    model: provider.chatModel(model),
    prompt: 'Reply with one short word.',
    temperature: 0,
  });
  let streamed = '';
  for await (const textPart of streamResult.textStream) streamed += textPart;
  if (!streamed.trim()) throw new Error('Vercel AI SDK streamText returned empty content');
  console.log(`[openai-compat-js] ai-sdk-stream=${JSON.stringify(streamed.slice(0, 80))}`);
  console.log('[openai-compat-js] JS SDK smoke passed');
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
