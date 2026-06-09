/**
 * Unit tests for CLI WebSocket response collection.
 *
 * These run a local in-process WebSocket server. They verify that the CLI only
 * persists embeds for the active chat and waits for async skill completion
 * frames that arrive after the assistant text response.
 */

import { after, before, describe, it } from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { createRequire } from "node:module";

import { OpenMatesWsClient } from "../src/ws.ts";

const require = createRequire(import.meta.url);
const { WebSocketServer } = require("ws");

describe("OpenMatesWsClient.collectAiResponse", () => {
  let server: InstanceType<typeof WebSocketServer>;
  let apiUrl: string;

  before(async () => {
    server = new WebSocketServer({ port: 0 });
    await once(server, "listening");
    const address = server.address();
    assert.ok(address && typeof address === "object");
    apiUrl = `http://127.0.0.1:${address.port}`;
  });

  after(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  it("ignores unrelated embeds and waits for delayed async embed completion", async () => {
    const chatId = "chat-active";
    const userMessageId = "user-message-1";
    const asyncEmbedId = "embed-async";

    server.once("connection", (socket) => {
      setTimeout(() => {
      socket.send(
        JSON.stringify({
          type: "send_embed_data",
          payload: {
            embed_id: "embed-other-chat",
            chat_id: "chat-other",
            message_id: "message-other",
            status: "finished",
            type: "app_skill_use",
            content: "app_id: web\nskill_id: search\nstatus: finished",
          },
        }),
      );

      socket.send(
        JSON.stringify({
          type: "send_embed_data",
          payload: {
            embed_id: asyncEmbedId,
            chat_id: chatId,
            message_id: "assistant-message-1",
            status: "processing",
            type: "app_skill_use",
            content: "app_id: images\nskill_id: generate\nstatus: processing",
          },
        }),
      );

      socket.send(
        JSON.stringify({
          type: "ai_message_update",
          payload: {
            user_message_id: userMessageId,
            message_id: "assistant-message-1",
            chat_id: chatId,
            is_final_chunk: true,
            full_content_so_far: `\`\`\`json\n{"type":"app_skill_use","embed_id":"${asyncEmbedId}","app_id":"images","skill_id":"generate"}\n\`\`\`\n\nThe image will appear soon.`,
          },
        }),
      );
      }, 5);

      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "post_processing_metadata",
            payload: {
              chat_id: chatId,
              follow_up_request_suggestions: ["Try another style"],
            },
          }),
        );
      }, 15);

      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "send_embed_data",
            payload: {
              embed_id: asyncEmbedId,
              chat_id: chatId,
              message_id: "assistant-message-1",
              status: "finished",
              type: "app_skill_use",
              content: "app_id: images\nskill_id: generate\nstatus: finished\nfiles: {}",
            },
          }),
        );
      }, 60);
    });

    const client = new OpenMatesWsClient({
      apiUrl,
      sessionId: "session-1",
      wsToken: "token",
      refreshToken: null,
    });
    await client.open();

    try {
      const response = await client.collectAiResponse(userMessageId, chatId, {
        timeoutMs: 25,
        asyncEmbedWaitMs: 1_000,
      });

      assert.deepEqual(
        response.embeds.map((embed) => embed.embed_id),
        [asyncEmbedId],
      );
      assert.equal(response.embeds[0]?.status, "finished");
      assert.deepEqual(response.followUpSuggestions, ["Try another style"]);
    } finally {
      client.close();
    }
  });

  it("accepts matching-chat AI completion when server user message id differs", async () => {
    const chatId = "chat-active-mismatch";
    const userMessageId = "cli-user-message";

    server.once("connection", (socket) => {
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "ai_message_update",
            payload: {
              user_message_id: "server-side-user-message",
              message_id: "assistant-message-2",
              chat_id: chatId,
              is_final_chunk: true,
              full_content_so_far: "Here are the listings I found.",
              category: "general_knowledge",
              model_name: "Gemini 3 Flash",
            },
          }),
        );
      }, 5);
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "post_processing_metadata",
            payload: {
              chat_id: chatId,
              follow_up_request_suggestions: ["Show cheaper options"],
            },
          }),
        );
      }, 10);
    });

    const client = new OpenMatesWsClient({
      apiUrl,
      sessionId: "session-2",
      wsToken: "token",
      refreshToken: null,
    });
    await client.open();

    try {
      const response = await client.collectAiResponse(userMessageId, chatId, {
        timeoutMs: 1_000,
      });

      assert.equal(response.messageId, "assistant-message-2");
      assert.equal(response.content, "Here are the listings I found.");
      assert.equal(response.category, "general_knowledge");
    } finally {
      client.close();
    }
  });

  it("collects completed assistant messages from chat_message_added fallback", async () => {
    const chatId = "chat-fallback";
    const userMessageId = "cli-user-message-fallback";

    server.once("connection", (socket) => {
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "chat_message_added",
            payload: {
              chat_id: chatId,
              message: {
                message_id: "assistant-message-3",
                chat_id: chatId,
                role: "assistant",
                status: "completed",
                content: "I found current furnished apartments in Berlin.",
                category: "general_knowledge",
                model_name: "Gemini 3 Flash",
              },
              versions: { messages_v: 2 },
              last_edited_overall_timestamp: 1780877511,
            },
          }),
        );
      }, 5);
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "post_processing_metadata",
            payload: {
              chat_id: chatId,
              follow_up_request_suggestions: ["Show cheaper apartments"],
            },
          }),
        );
      }, 10);
    });

    const client = new OpenMatesWsClient({
      apiUrl,
      sessionId: "session-3",
      wsToken: "token",
      refreshToken: null,
    });
    await client.open();

    try {
      const response = await client.collectAiResponse(userMessageId, chatId, {
        timeoutMs: 1_000,
      });

      assert.equal(response.messageId, "assistant-message-3");
      assert.equal(
        response.content,
        "I found current furnished apartments in Berlin.",
      );
      assert.equal(response.category, "general_knowledge");
      assert.equal(response.modelName, "Gemini 3 Flash");
      assert.deepEqual(response.followUpSuggestions, ["Show cheaper apartments"]);
    } finally {
      client.close();
    }
  });

  it("surfaces sub-chat lifecycle frames without resolving the parent response early", async () => {
    const chatId = "chat-sub-chat-parent";
    const userMessageId = "user-message-sub-chat-parent";
    const receivedEvents: Array<{ type: string; payload: Record<string, unknown> }> = [];

    server.once("connection", (socket) => {
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "spawn_sub_chats",
            payload: {
              chat_id: chatId,
              sub_chats: [
                {
                  id: "child-chat-1",
                  user_message_id: "child-user-message-1",
                  prompt: "Research the surface explanation.",
                },
              ],
            },
          }),
        );
        socket.send(
          JSON.stringify({
            type: "sub_chat_progress",
            payload: {
              chat_id: chatId,
              task_id: "task-parent",
              status: "running",
              total: 1,
              completed: 0,
            },
          }),
        );
        socket.send(
          JSON.stringify({
            type: "sub_chat_confirmation_required",
            payload: {
              chat_id: chatId,
              task_id: "task-confirm",
              sub_chats: [
                {
                  id: "child-chat-2",
                  user_message_id: "child-user-message-2",
                  prompt: "Research the counterargument.",
                },
              ],
              max_auto_sub_chats: 3,
              max_direct_sub_chats: 10,
              existing_sub_chats: 0,
              remaining_sub_chats: 10,
            },
          }),
        );
      }, 5);

      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "ai_message_update",
            payload: {
              user_message_id: userMessageId,
              message_id: "assistant-message-sub-chat-parent",
              chat_id: chatId,
              is_final_chunk: true,
              full_content_so_far: "## Short Answer\n\nThe child findings are synthesized here.",
            },
          }),
        );
      }, 40);
    });

    const client = new OpenMatesWsClient({
      apiUrl,
      sessionId: "session-sub-chat-events",
      wsToken: "token",
      refreshToken: null,
    });
    await client.open();

    try {
      const response = await client.collectAiResponse(userMessageId, chatId, {
        timeoutMs: 1_000,
        onSubChatEvent: (event) => receivedEvents.push(event),
      });

      assert.equal(
        response.content,
        "## Short Answer\n\nThe child findings are synthesized here.",
      );
      assert.deepEqual(
        receivedEvents.map((event) => event.type),
        ["spawn_sub_chats", "sub_chat_progress", "sub_chat_confirmation_required"],
      );
      assert.equal(receivedEvents[0]?.payload.chat_id, chatId);
    } finally {
      client.close();
    }
  });
});
