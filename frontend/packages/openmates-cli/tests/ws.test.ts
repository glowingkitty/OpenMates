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

import { OpenMatesWsClient, WebSocketProtocolError } from "../src/ws.ts";

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
            type: "task_event",
            payload: {
              event_id: "task-event-1",
              chat_id: chatId,
              task_id: "TASK-123",
              short_id: "TASK-123",
              event_type: "created",
              title: "Book flights",
              status: "todo",
              created_at: 1780000000,
              task_update_job_id: "task-update-job-1",
            },
          }),
        );
        socket.send(
          JSON.stringify({
            type: "task_update_jobs_available",
            payload: {
              chat_id: chatId,
              jobs: [
                {
                  job_id: "task-update-job-1",
                  task_id: "TASK-123",
                  chat_id: chatId,
                  revision: 1,
                  task_key_version: 1,
                  expires_at: 1780000900,
                },
              ],
            },
          }),
        );
        socket.send(
          JSON.stringify({
            type: "task_update_jobs_available",
            payload: {
              chat_id: chatId,
              jobs: [
                {
                  job_id: "task-update-job-2",
                  task_id: "TASK-456",
                  chat_id: chatId,
                  revision: 1,
                  task_key_version: 1,
                  expires_at: 1780000901,
                },
              ],
            },
          }),
        );
        socket.send(
          JSON.stringify({
            type: "post_processing_metadata",
            payload: {
              chat_id: chatId,
              follow_up_request_suggestions: ["Try another style"],
              task_proposals: [
                {
                  title: "Book flights",
                  description: "Compare morning flights first.",
                  status: "todo",
                  assignee_type: "ai",
                },
              ],
              task_update_proposals: [
                {
                  task_id: "task-existing",
                  status: "done",
                },
              ],
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
      assert.deepEqual(response.taskProposals, [
        {
          title: "Book flights",
          description: "Compare morning flights first.",
          status: "todo",
          assignee_type: "ai",
        },
      ]);
      assert.deepEqual(response.taskUpdateProposals, [
        {
          task_id: "task-existing",
          status: "done",
        },
      ]);
      assert.deepEqual(response.taskEvents, [
        {
          event_id: "task-event-1",
          chat_id: chatId,
          task_id: "TASK-123",
          short_id: "TASK-123",
          event_type: "created",
          title: "Book flights",
          status: "todo",
          created_at: 1780000000,
          task_update_job_id: "task-update-job-1",
        },
      ]);
      assert.deepEqual(response.pendingTaskUpdateJobs, [
        {
          job_id: "task-update-job-1",
          task_id: "TASK-123",
          chat_id: chatId,
          revision: 1,
          task_key_version: 1,
          expires_at: 1780000900,
        },
        {
          job_id: "task-update-job-2",
          task_id: "TASK-456",
          chat_id: chatId,
          revision: 1,
          task_key_version: 1,
          expires_at: 1780000901,
        },
      ]);
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
              recovery_job_id: "11111111-1111-4111-8111-111111111111",
              recovery_protocol_version: 1,
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
      assert.equal(response.recoveryJobId, "11111111-1111-4111-8111-111111111111");
    } finally {
      client.close();
    }
  });

  it("rejects client_update_required with concise CLI update guidance", async () => {
    server.once("connection", (socket) => {
      setTimeout(() => socket.send(JSON.stringify({
        type: "error",
        payload: {
          code: "client_update_required",
          message: "Please update OpenMates before sending another saved chat message.",
        },
      })), 5);
    });

    const client = new OpenMatesWsClient({
      apiUrl,
      sessionId: "session-update-required",
      wsToken: "token",
      refreshToken: null,
    });
    await client.open();

    try {
      await assert.rejects(
        client.collectAiResponse("user-message", "chat-update-required", { timeoutMs: 1_000 }),
        (error) => error instanceof WebSocketProtocolError
          && error.code === "client_update_required"
          && /OpenMates CLI update required/.test(error.message),
      );
    } finally {
      client.close();
    }
  });

  it("ignores preflight errors scoped to a different saved-chat turn", async () => {
    const chatId = "chat-ignore-stale-preflight";
    const userMessageId = "user-message-ignore-stale-preflight";

    server.once("connection", (socket) => {
      setTimeout(() => {
        socket.send(JSON.stringify({
          type: "error",
          payload: {
            code: "durable_preflight_conflict",
            message: "Encrypted chat preflight was rejected.",
            turn_id: "turn-stale",
          },
        }));
        socket.send(JSON.stringify({
          type: "ai_message_update",
          payload: {
            user_message_id: userMessageId,
            message_id: "assistant-ignore-stale-preflight",
            chat_id: chatId,
            is_final_chunk: true,
            full_content_so_far: "The active turn completed.",
          },
        }));
        socket.send(JSON.stringify({
          type: "recovery_jobs_available",
          payload: {
            jobs: [
              {
                job_id: "recovery-job-current",
                chat_id: chatId,
                turn_id: "turn-current",
                assistant_message_id: "assistant-ignore-stale-preflight",
                chat_key_version: 1,
              },
            ],
          },
        }));
      }, 5);
      setTimeout(() => {
        socket.send(JSON.stringify({
          type: "post_processing_metadata",
          payload: { chat_id: chatId },
        }));
      }, 10);
    });

    const client = new OpenMatesWsClient({
      apiUrl,
      sessionId: "session-ignore-stale-preflight",
      wsToken: "token",
      refreshToken: null,
    });
    await client.open();

    try {
      const response = await client.collectAiResponse(userMessageId, chatId, {
        timeoutMs: 1_000,
        recoveryTurnId: "turn-current",
      });

      assert.equal(response.content, "The active turn completed.");
    } finally {
      client.close();
    }
  });

  it("rejects preflight errors scoped to the active saved-chat turn", async () => {
    server.once("connection", (socket) => {
      setTimeout(() => socket.send(JSON.stringify({
        type: "error",
        payload: {
          code: "durable_preflight_conflict",
          message: "Encrypted chat preflight was rejected.",
          turn_id: "turn-current",
        },
      })), 5);
    });

    const client = new OpenMatesWsClient({
      apiUrl,
      sessionId: "session-active-preflight-error",
      wsToken: "token",
      refreshToken: null,
    });
    await client.open();

    try {
      await assert.rejects(
        client.collectAiResponse("user-message", "chat-active-preflight-error", {
          timeoutMs: 1_000,
          recoveryTurnId: "turn-current",
        }),
        (error) => error instanceof WebSocketProtocolError
          && error.code === "durable_preflight_conflict"
          && /Encrypted chat preflight was rejected/.test(error.message),
      );
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

  it("buffers reconnect-advertised task update jobs before response collection starts", async () => {
    const chatId = "chat-reconnect-jobs";
    const userMessageId = "user-message-reconnect";

    server.once("connection", (socket) => {
      socket.send(
        JSON.stringify({
          type: "task_update_jobs_available",
          payload: {
            jobs: [
              {
                job_id: "task-update-job-reconnect",
                task_id: "TASK-789",
                chat_id: "chat-source",
                revision: 4,
                task_key_version: 1,
                expires_at: 1780000999,
              },
            ],
          },
        }),
      );
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "ai_message_update",
            payload: {
              user_message_id: userMessageId,
              message_id: "assistant-reconnect",
              chat_id: chatId,
              is_final_chunk: true,
              full_content_so_far: "Recovered pending task jobs.",
            },
          }),
        );
      }, 15);
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "post_processing_metadata",
            payload: { chat_id: chatId },
          }),
        );
      }, 20);
    });

    const client = new OpenMatesWsClient({
      apiUrl,
      sessionId: "session-reconnect-jobs",
      wsToken: "token",
      refreshToken: null,
    });
    await client.open();
    await new Promise((resolve) => setTimeout(resolve, 5));

    try {
      const response = await client.collectAiResponse(userMessageId, chatId, {
        timeoutMs: 1_000,
      });

      assert.deepEqual(response.pendingTaskUpdateJobs, [
        {
          job_id: "task-update-job-reconnect",
          task_id: "TASK-789",
          chat_id: "chat-source",
          revision: 4,
          task_key_version: 1,
          expires_at: 1780000999,
        },
      ]);
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
        socket.send(
          JSON.stringify({
            type: "awaiting_sub_chats_completion",
            payload: {
              chat_id: chatId,
              task_id: "task-parent",
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
              message_id: "assistant-message-sub-chat-status",
              chat_id: chatId,
              is_final_chunk: true,
              full_content_so_far:
                "I've started the sub-chats and will continue once they finish.\n---\n*Warning: child findings are still running.*",
            },
          }),
        );
      }, 40);

      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "ai_background_response_completed",
            payload: {
              user_message_id: "server-side-continuation-message",
              message_id: "assistant-message-sub-chat-parent",
              chat_id: chatId,
              full_content: "## Short Answer\n\nThe child findings are synthesized here.",
            },
          }),
        );
      }, 80);

      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "post_processing_metadata",
            payload: {
              chat_id: chatId,
              follow_up_request_suggestions: ["Show the child evidence"],
            },
          }),
        );
      }, 90);
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
        [
          "spawn_sub_chats",
          "sub_chat_progress",
          "sub_chat_confirmation_required",
          "awaiting_sub_chats_completion",
        ],
      );
      assert.equal(receivedEvents[0]?.payload.chat_id, chatId);
      assert.equal(
        (receivedEvents[0]?.payload.sub_chats as Array<unknown> | undefined)?.length,
        1,
      );
    } finally {
      client.close();
    }
  });

  it("resolves awaiting_user_input for child chat events routed through the active parent", async () => {
    const chatId = "parent-waiting-chat";
    const childChatId = "child-waiting-chat";
    const userMessageId = "user-message-waiting";
    const receivedEvents: Array<{ type: string; payload: Record<string, unknown> }> = [];

    server.once("connection", (socket) => {
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "awaiting_user_input",
            payload: {
              chat_id: childChatId,
              parent_id: chatId,
              task_id: "task-waiting",
              message_id: "assistant-question-message",
              question: "Which source should the child chat inspect next?",
            },
          }),
        );
      }, 5);
    });

    const client = new OpenMatesWsClient({
      apiUrl,
      sessionId: "session-awaiting-input",
      wsToken: "token",
      refreshToken: null,
    });
    await client.open();

    try {
      const response = await client.collectAiResponse(userMessageId, chatId, {
        timeoutMs: 1_000,
        onSubChatEvent: (event) => receivedEvents.push(event),
      });

      assert.equal(response.status, "waiting_for_user");
      assert.equal(response.messageId, "assistant-question-message");
      assert.equal(receivedEvents[0]?.type, "awaiting_user_input");
      assert.equal(receivedEvents[0]?.payload.chat_id, childChatId);
      assert.equal(receivedEvents[0]?.payload.parent_id, chatId);
    } finally {
      client.close();
    }
  });

  it("resolves saved-chat collection from a matching recovery job", async () => {
    const chatId = "chat-recovery-available";
    const userMessageId = "user-message-recovery";
    const turnId = "turn-current";

    server.once("connection", (socket) => {
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "recovery_jobs_available",
            payload: {
              jobs: [
                {
                  job_id: "recovery-job-stale",
                  chat_id: chatId,
                  turn_id: "turn-stale",
                  assistant_message_id: "assistant-message-stale",
                  chat_key_version: 1,
                },
                {
                  job_id: "recovery-job-current",
                  chat_id: chatId,
                  turn_id: turnId,
                  assistant_message_id: "assistant-message-current",
                  chat_key_version: 1,
                },
              ],
            },
          }),
        );
        socket.send(
          JSON.stringify({
            type: "post_processing_metadata",
            payload: { chat_id: chatId },
          }),
        );
      }, 5);
    });

    const client = new OpenMatesWsClient({
      apiUrl,
      sessionId: "session-recovery-available",
      wsToken: "token",
      refreshToken: null,
    });
    await client.open();

    try {
      const response = await client.collectAiResponse(userMessageId, chatId, {
        timeoutMs: 1_000,
        recoveryTurnId: turnId,
      });

      assert.equal(response.status, "completed");
      assert.equal(response.recoveryJobId, "recovery-job-current");
      assert.equal(response.messageId, "assistant-message-current");
      assert.equal(response.content, "");
    } finally {
      client.close();
    }
  });

  it("waits for a matching recovery job after assistant and post-processing frames", async () => {
    const chatId = "chat-recovery-late";
    const userMessageId = "user-message-recovery-late";
    const turnId = "turn-late-recovery";

    server.once("connection", (socket) => {
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "ai_message_update",
            payload: {
              user_message_id: userMessageId,
              message_id: "assistant-late-recovery-stream",
              chat_id: chatId,
              is_final_chunk: true,
              full_content_so_far: "Task changes are done.",
            },
          }),
        );
      }, 5);
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "post_processing_metadata",
            payload: { chat_id: chatId },
          }),
        );
      }, 10);
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "recovery_jobs_available",
            payload: {
              jobs: [
                {
                  job_id: "recovery-job-late",
                  chat_id: chatId,
                  turn_id: turnId,
                  assistant_message_id: "assistant-late-recovery",
                  chat_key_version: 1,
                },
              ],
            },
          }),
        );
      }, 30);
    });

    const client = new OpenMatesWsClient({
      apiUrl,
      sessionId: "session-late-recovery",
      wsToken: "token",
      refreshToken: null,
    });
    await client.open();

    try {
      const response = await client.collectAiResponse(userMessageId, chatId, {
        timeoutMs: 1_000,
        recoveryTurnId: turnId,
      });

      assert.equal(response.status, "completed");
      assert.equal(response.recoveryJobId, "recovery-job-late");
      assert.equal(response.messageId, "assistant-late-recovery");
      assert.equal(response.content, "Task changes are done.");
    } finally {
      client.close();
    }
  });

  it("resolves saved-chat recovery before optional post-processing metadata", async () => {
    const chatId = "chat-recovery-before-post-processing";
    const userMessageId = "user-message-recovery-before-post-processing";
    const turnId = "turn-before-post-processing";

    server.once("connection", (socket) => {
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "ai_message_update",
            payload: {
              user_message_id: userMessageId,
              message_id: "assistant-before-post-processing-stream",
              chat_id: chatId,
              is_final_chunk: true,
              full_content_so_far: "Application preview is ready.",
            },
          }),
        );
      }, 5);
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "recovery_jobs_available",
            payload: {
              jobs: [
                {
                  job_id: "recovery-job-before-post-processing",
                  chat_id: chatId,
                  turn_id: turnId,
                  assistant_message_id: "assistant-before-post-processing",
                  chat_key_version: 1,
                },
              ],
            },
          }),
        );
      }, 20);
      setTimeout(() => {
        socket.send(
          JSON.stringify({
            type: "post_processing_metadata",
            payload: { chat_id: chatId, follow_up_suggestions: ["Too late"] },
          }),
        );
      }, 250);
    });

    const client = new OpenMatesWsClient({
      apiUrl,
      sessionId: "session-recovery-before-post-processing",
      wsToken: "token",
      refreshToken: null,
    });
    await client.open();

    try {
      const startedAt = Date.now();
      const response = await client.collectAiResponse(userMessageId, chatId, {
        timeoutMs: 1_000,
        recoveryTurnId: turnId,
      });

      assert.equal(response.status, "completed");
      assert.equal(response.recoveryJobId, "recovery-job-before-post-processing");
      assert.equal(response.messageId, "assistant-before-post-processing");
      assert.equal(response.content, "Application preview is ready.");
      assert.ok(Date.now() - startedAt < 200, "saved-chat recovery should not wait for post-processing");
    } finally {
      client.close();
    }
  });

  it("waitForMessage ignores scoped errors that miss the predicate", async () => {
    server.once("connection", (socket) => {
      setTimeout(() => {
        socket.send(JSON.stringify({
          type: "error",
          payload: {
            code: "durable_preflight_conflict",
            message: "Encrypted chat preflight was rejected.",
            turn_id: "turn-stale",
          },
        }));
        socket.send(JSON.stringify({
          type: "chat_turn_preflight_ack",
          payload: {
            preflight_id: "preflight-current",
            state: "COMMITTED",
            turn_id: "turn-current",
          },
        }));
      }, 5);
    });

    const client = new OpenMatesWsClient({
      apiUrl,
      sessionId: "session-wait-stale-error",
      wsToken: "token",
      refreshToken: null,
    });
    await client.open();

    try {
      const response = await client.waitForMessage(
        "chat_turn_preflight_ack",
        (payload) => (payload as Record<string, unknown>).turn_id === "turn-current",
        1_000,
      );

      assert.equal((response.payload as Record<string, unknown>).preflight_id, "preflight-current");
    } finally {
      client.close();
    }
  });

  it("waitForMessage rejects scoped errors that match the predicate", async () => {
    server.once("connection", (socket) => {
      setTimeout(() => socket.send(JSON.stringify({
        type: "error",
        payload: {
          code: "durable_preflight_conflict",
          message: "Encrypted chat preflight was rejected.",
          turn_id: "turn-current",
        },
      })), 5);
    });

    const client = new OpenMatesWsClient({
      apiUrl,
      sessionId: "session-wait-active-error",
      wsToken: "token",
      refreshToken: null,
    });
    await client.open();

    try {
      await assert.rejects(
        client.waitForMessage(
          "chat_turn_preflight_ack",
          (payload) => (payload as Record<string, unknown>).turn_id === "turn-current",
          1_000,
        ),
        (error) => error instanceof WebSocketProtocolError
          && error.code === "durable_preflight_conflict"
          && /Encrypted chat preflight was rejected/.test(error.message),
      );
    } finally {
      client.close();
    }
  });
});
