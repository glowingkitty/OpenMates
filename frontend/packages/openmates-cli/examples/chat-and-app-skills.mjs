#!/usr/bin/env node
/*
 * OpenMates npm SDK example: chats and app skills.
 *
 * Run after building the package:
 *   OPENMATES_API_KEY=sk-api-... node examples/chat-and-app-skills.mjs
 *
 * This uses real API requests. It lists encrypted account chats, loads the first
 * chat when available, and runs a deterministic math app skill.
 */

import { OpenMates } from "../dist/index.js";

const client = new OpenMates({
  apiKey: process.env.OPENMATES_API_KEY,
  apiUrl: process.env.OPENMATES_API_URL,
});

const chats = await client.chats.list({ limit: 10 });
const firstChat = chats[0]?.id ? await client.chats.load(String(chats[0].id)) : null;
const calculation = await client.apps.math.calculate({
  title: "SDK example calculation",
  expression: "2 + 2",
});

console.log(JSON.stringify({
  chats: chats.map((chat) => ({
    id: chat.id,
    title: chat.title ?? null,
    category: chat.category ?? null,
  })),
  loadedChat: firstChat
    ? {
        id: firstChat.chat?.id ?? null,
        messageCount: Array.isArray(firstChat.messages) ? firstChat.messages.length : 0,
        embedCount: Array.isArray(firstChat.embeds) ? firstChat.embeds.length : 0,
      }
    : null,
  calculation,
}, null, 2));
