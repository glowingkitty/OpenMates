/**
 * CLI example continuation unit contracts.
 *
 * Continuing a public example must preserve the example transcript as AI
 * context rather than sending only a lightweight source marker.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { buildAnonymousExampleHistoryPayload, buildExampleContinuationHistory } from "../src/tuiExampleContinuation.ts";
import type { ExampleChatConversation } from "../src/exampleChats.ts";

function conversation(): ExampleChatConversation {
  return {
    chat: {
      id: "example-svelte",
      shortId: "example-svelte",
      slug: "svelte-runes-docs",
      title: "Svelte Runes Docs",
      summary: "Find Svelte 5 documentation",
      updatedAt: null,
      category: "software_development",
      mateName: null,
      source: "example",
    },
    messages: [
      {
        id: "u1",
        chatId: "example-svelte",
        role: "user",
        content: "Find docs for $state and $derived",
        senderName: "User",
        category: null,
        modelName: null,
        createdAt: 1,
        embedIds: [],
      },
      {
        id: "a1",
        chatId: "example-svelte",
        role: "assistant",
        content: "Here are the official docs and a component example.",
        senderName: null,
        category: "software_development",
        modelName: "test-model",
        createdAt: 2,
        embedIds: [],
      },
    ],
    followUpSuggestions: [],
  };
}

describe("CLI example continuation history", () => {
  it("preserves full public example conversation turns", () => {
    const history = buildExampleContinuationHistory(conversation());
    assert.deepEqual(history.map((message) => message.content), [
      "Find docs for $state and $derived",
      "Here are the official docs and a component example.",
    ]);
    assert.equal(history[0]?.message_id, "u1");
    assert.equal(history[0]?.chat_id, "example-svelte");
  });

  it("builds anonymous-safe history payload fields", () => {
    const payload = buildAnonymousExampleHistoryPayload(conversation());
    assert.deepEqual(Object.keys(payload[0] ?? {}).sort(), ["content", "created_at", "role", "sender_name"]);
    assert.equal(payload[0]?.role, "user");
    assert.equal(payload[1]?.role, "assistant");
  });
});
