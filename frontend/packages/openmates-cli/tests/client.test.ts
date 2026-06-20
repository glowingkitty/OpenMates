/**
 * Unit tests for OpenMatesClient session target selection.
 *
 * Purpose: prevent persisted pair-login sessions from appearing logged out when
 * the CLI is run without OPENMATES_API_URL.
 * Security: uses a temporary HOME and fake legacy session data; no real CLI
 * session, cookies, master keys, or account identifiers are read.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/client.test.ts
 */

import { describe, it, beforeEach, after } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";

const originalHome = process.env.HOME;
const originalApiUrl = process.env.OPENMATES_API_URL;
const tempHome = mkdtempSync(join(tmpdir(), "openmates-cli-client-"));
const stateDir = join(tempHome, ".openmates");
const sessionPath = join(stateDir, "session.json");
const serverConfigPath = join(stateDir, "server.json");
const sessionApiUrl = "https://api.dev.openmates.org";

process.env.HOME = tempHome;
delete process.env.OPENMATES_API_URL;

mkdirSync(stateDir, { recursive: true, mode: 0o700 });

function writeLegacySession(apiUrl = sessionApiUrl): void {
  writeFileSync(
    sessionPath,
    JSON.stringify(
      {
        apiUrl,
        sessionId: "test-session-id",
        wsToken: "test-ws-token",
        cookies: { auth_refresh_token: "test-refresh-token" },
        masterKeyExportedB64: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        hashedEmail: "test-hashed-email",
        userEmailSalt: "test-email-salt",
        createdAt: 1710000000000,
        authorizerDeviceName: "Test Browser",
        autoLogoutMinutes: null,
      },
      null,
      2,
    ),
    { mode: 0o600 },
  );
}

writeLegacySession();

const require = createRequire(import.meta.url);
const { WebSocketServer } = require("ws");

const {
  OpenMatesClient,
  MEMORY_TYPE_REGISTRY,
  buildAppSettingsMemoryRequestSystemMessage,
  buildAppSettingsMemoryResponseSystemMessage,
  buildConnectedAccountDirectoryPayload,
  buildSubChatConfirmationPayload,
  buildSubChatEncryptedMetadataPayloads,
  buildTurnTokenRefsRequestPayload,
  getClientMessagesVersionForSync,
} = await import("../src/client.ts");
const { decryptBytesWithAesGcm, decryptWithAesGcmCombined, encryptBytesWithAesGcm } = await import("../src/crypto.ts");

after(() => {
  if (originalHome === undefined) {
    delete process.env.HOME;
  } else {
    process.env.HOME = originalHome;
  }
  if (originalApiUrl === undefined) {
    delete process.env.OPENMATES_API_URL;
  } else {
    process.env.OPENMATES_API_URL = originalApiUrl;
  }
  rmSync(tempHome, { recursive: true, force: true });
});

describe("OpenMatesClient session API URL", () => {
  beforeEach(() => {
    writeLegacySession();
    rmSync(serverConfigPath, { force: true });
  });

  it("uses the persisted session API URL when no override is set", () => {
    const client = OpenMatesClient.load();
    assert.strictEqual(client.apiUrl, sessionApiUrl);
  });

  it("keeps explicit API URL overrides higher priority than the persisted session", () => {
    const client = OpenMatesClient.load({ apiUrl: "http://127.0.0.1:8000" });
    assert.strictEqual(client.apiUrl, "http://127.0.0.1:8000");
  });

  it("uses installed self-host server API when no override or session exists", () => {
    rmSync(sessionPath, { force: true });
    writeFileSync(serverConfigPath, `${JSON.stringify({
      installPath: "/tmp/openmates-self-host",
      installedAt: Date.now(),
      composeProfile: "core",
      installMode: "image",
      apiUrl: "http://localhost:8000",
      appUrl: "http://localhost:5173",
    })}\n`);

    const client = OpenMatesClient.load();
    assert.strictEqual(client.apiUrl, "http://localhost:8000");
  });

  it("persists rotated auth cookies and ws tokens after whoami", async () => {
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/auth/session");
      response.writeHead(200, {
        "content-type": "application/json",
        "set-cookie": "auth_refresh_token=rotated-refresh-token; Path=/; HttpOnly",
      });
      response.end(
        JSON.stringify({
          success: true,
          ws_token: "rotated-ws-token",
          user: { id: "test-user-id" },
        }),
      );
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const user = await client.whoAmI();
      assert.deepEqual(user, { id: "test-user-id" });

      const saved = JSON.parse(readFileSync(sessionPath, "utf-8"));
      assert.strictEqual(saved.wsToken, "rotated-ws-token");
      assert.strictEqual(saved.cookies.auth_refresh_token, "rotated-refresh-token");
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("includes session_id when refreshing the WebSocket token", async () => {
    let requestBody = "";
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/auth/session");
      request.setEncoding("utf8");
      request.on("data", (chunk) => {
        requestBody += chunk;
      });
      request.on("end", () => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await (client as unknown as { refreshWsToken(): Promise<void> }).refreshWsToken();

      assert.deepEqual(JSON.parse(requestBody), { session_id: "test-session-id" });
      const saved = JSON.parse(readFileSync(sessionPath, "utf-8"));
      assert.strictEqual(saved.wsToken, "fresh-ws-token");
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("persists pending AI responses during CLI sync", async () => {
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    const wsServer = new WebSocketServer({ server });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    const chatKey = new Uint8Array(32).fill(7);
    const masterKey = new Uint8Array(32);
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, masterKey);
    let completedPayload: Record<string, any> | null = null;

    wsServer.once("connection", (socket: any) => {
      socket.on("message", (raw: Buffer) => {
        const frame = JSON.parse(raw.toString());
        if (frame.type === "phased_sync_request") {
          socket.send(JSON.stringify({
            type: "pending_ai_response",
            payload: {
              chat_id: "chat-1",
              message_id: "assistant-1",
              content: "Completed while the first client was gone.",
              fired_at: 1780000000,
              category: "general_knowledge",
              model_name: "Gemini 3 Flash",
            },
          }));
          socket.send(JSON.stringify({
            type: "phase_2_last_20_chats_ready",
            payload: {
              total_chat_count: 1,
              chats: [{
                chat_details: {
                  id: "chat-1",
                  encrypted_chat_key: encryptedChatKey,
                  messages_v: 1,
                  title_v: 0,
                  draft_v: 0,
                  last_edited_overall_timestamp: 1779999999,
                },
              }],
            },
          }));
          socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
        }
        if (frame.type === "ai_response_completed") {
          completedPayload = frame.payload;
          socket.send(JSON.stringify({
            type: "ai_response_storage_confirmed",
            payload: { message_id: "assistant-1" },
          }));
        }
      });
    });

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const cache = await client.ensureSynced(true);

      assert.ok(completedPayload);
      assert.equal(completedPayload.chat_id, "chat-1");
      assert.equal(completedPayload.message.message_id, "assistant-1");
      assert.equal(completedPayload.versions.messages_v, 2);
      assert.equal(
        await decryptWithAesGcmCombined(completedPayload.message.encrypted_content, chatKey),
        "Completed while the first client was gone.",
      );
      assert.equal(cache.chats[0]?.messages.length, 1);
      const cachedMessage = JSON.parse(cache.chats[0]?.messages[0] as string);
      assert.equal(cachedMessage.message_id, "assistant-1");
      assert.equal(
        await decryptWithAesGcmCombined(cachedMessage.encrypted_content, chatKey),
        "Completed while the first client was gone.",
      );
    } finally {
      await new Promise<void>((resolve) => wsServer.close(() => resolve()));
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});

describe("memory type registry", () => {
  it("covers all production memory types needed by CLI memory commands", () => {
    assert.deepEqual(Object.keys(MEMORY_TYPE_REGISTRY).sort(), [
      "ai/communication_style",
      "ai/learning_preferences",
      "books/currently_reading",
      "books/favorite_books",
      "books/to_read_list",
      "code/coding_setup",
      "code/preferred_tech",
      "code/projects",
      "code/want_to_learn",
      "docs/writing_style",
      "events/saved_events",
      "health/appointments",
      "health/medical_history",
      "home/saved_listings",
      "images/preferred_styles",
      "mail/writing_styles",
      "reminder/saved_item_reminder_defaults",
      "study/learning_goals",
      "travel/preferred_activities",
      "travel/preferred_airlines",
      "travel/preferred_transport_methods",
      "travel/saved_connections",
      "travel/saved_stays",
      "travel/trips",
      "tv/to_watch_list",
      "tv/watched_movies",
      "tv/watched_tv_shows",
      "videos/to_watch_list",
      "web/bookmarks",
      "web/read_later",
    ]);
  });
});

describe("connected account payload builders", () => {
  it("rejects token or plaintext identity fields in the chat-visible directory", () => {
    assert.throws(
      () => buildConnectedAccountDirectoryPayload([
        {
          connected_account_id: "acct-1",
          app_id: "calendar",
          account_ref: "work",
          label: "Work",
          capabilities: ["read"],
          provider_email: "person@example.com",
        } as never,
      ]),
      /forbidden field: provider_email/,
    );
  });

  it("builds token-broker requests without putting refresh tokens in chat payloads", () => {
    const request = buildTurnTokenRefsRequestPayload({
      chatId: "chat-1",
      messageId: "msg-1",
      refs: [
        {
          connected_account_id: "acct-1",
          app_id: "calendar",
          allowed_actions: ["read"],
          refresh_token_envelope: { refresh_token: "refresh-secret" },
          action_scope: { calendar_id: "primary" },
        },
      ],
    });
    const directory = buildConnectedAccountDirectoryPayload([
      {
        connected_account_id: "acct-1",
        app_id: "calendar",
        account_ref: "work",
        label: "Work",
        capabilities: ["read"],
      },
    ]);

    assert.equal(request.refs[0]?.refresh_token_envelope.refresh_token, "refresh-secret");
    assert.equal(JSON.stringify(directory).includes("refresh-secret"), false);
  });

  it("posts connected-account cancel requests without token refs", async () => {
    let requestBody = "";
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/connected-accounts/actions/action-1/cancel");
      request.setEncoding("utf8");
      request.on("data", (chunk) => {
        requestBody += chunk;
      });
      request.on("end", () => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ action_id: "action-1", status: "cancelled", receipt: {} }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const result = await client.cancelConnectedAccountAction({
        actionId: "action-1",
        chatId: "chat-1",
        messageId: "message-1",
      });

      assert.deepEqual(JSON.parse(requestBody), { chat_id: "chat-1", message_id: "message-1" });
      assert.equal(JSON.stringify(requestBody).includes("refresh"), false);
      assert.deepEqual(result, { action_id: "action-1", status: "cancelled", receipt: {} });
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("posts connected-account undo requests with only the opaque turn token ref", async () => {
    let requestBody = "";
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/connected-accounts/actions/action-1/undo");
      request.setEncoding("utf8");
      request.on("data", (chunk) => {
        requestBody += chunk;
      });
      request.on("end", () => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(
          JSON.stringify({
            action_id: "action-1",
            status: "undone",
            undo_type: "delete_created_event",
            events: [],
            receipt: {},
          }),
        );
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const result = await client.undoConnectedAccountAction({
        actionId: "action-1",
        chatId: "chat-1",
        messageId: "message-1",
        turnTokenRef: "turn-ref-1",
      });

      assert.deepEqual(JSON.parse(requestBody), {
        chat_id: "chat-1",
        message_id: "message-1",
        turn_token_ref: "turn-ref-1",
      });
      assert.equal(JSON.stringify(requestBody).includes("refresh"), false);
      assert.deepEqual(result, {
        action_id: "action-1",
        status: "undone",
        undo_type: "delete_created_event",
        events: [],
        receipt: {},
      });
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});

describe("memory request system messages", () => {
  it("builds the request artifact without approving memory content", () => {
    const message = buildAppSettingsMemoryRequestSystemMessage({
      userMessageId: "user-message-id",
      requestId: "request-id",
      requestedKeys: ["books-currently_reading"],
      createdAt: 1780000000,
    });

    assert.equal(message.message_id, "request-id");
    assert.equal(message.role, "system");
    assert.equal(message.created_at, 1780000000);
    assert.equal(message.user_message_id, "user-message-id");

    const payload = JSON.parse(message.content);
    assert.equal(payload.type, "app_settings_memories_request");
    assert.equal(payload.user_message_id, "user-message-id");
    assert.equal(payload.request_id, "request-id");
    assert.deepEqual(payload.requested_keys, ["books-currently_reading"]);
    assert.deepEqual(payload.categories, [
      { appId: "books", itemType: "currently_reading", entryCount: 0 },
    ]);
    assert.notEqual(payload.type, "app_settings_memories_response");
    assert.equal(payload.action, undefined);
  });

  it("builds an included response artifact only for explicit approval", () => {
    const message = buildAppSettingsMemoryResponseSystemMessage({
      userMessageId: "user-message-id",
      messageId: "response-id",
      action: "included",
      categories: [{ appId: "books", itemType: "currently_reading", entryCount: 2 }],
      createdAt: 1780000001,
    });

    assert.equal(message.message_id, "response-id");
    assert.equal(message.role, "system");
    assert.equal(message.created_at, 1780000001);
    assert.equal(message.user_message_id, "user-message-id");

    const payload = JSON.parse(message.content);
    assert.equal(payload.type, "app_settings_memories_response");
    assert.equal(payload.user_message_id, "user-message-id");
    assert.equal(payload.action, "included");
    assert.deepEqual(payload.categories, [
      { appId: "books", itemType: "currently_reading", entryCount: 2 },
    ]);
  });
});

describe("CLI chat PII redaction payloads", () => {
  it("sends redacted user content and encrypted PII mappings", async () => {
    const captured: {
      messagePayload?: Record<string, unknown>;
      metadataPayload?: Record<string, unknown>;
    } = {};
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
        return;
      }
      if (
        request.method === "GET" &&
        request.url === "/v1/settings/export-account-data?include_usage=false&include_invoices=false"
      ) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ data: { app_settings_memories: [] } }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          if (frame.type === "chat_message_added") {
            captured.messagePayload = frame.payload;
            const message = frame.payload.message as Record<string, unknown>;
            ws.send(JSON.stringify({
              type: "chat_message_confirmed",
              payload: {
                chat_id: frame.payload.chat_id,
                message_id: message.message_id,
              },
            }));
          }
          if (frame.type === "encrypted_chat_metadata") {
            captured.metadataPayload = frame.payload;
            setTimeout(() => {
              ws.send(JSON.stringify({
                type: "ai_background_response_completed",
                payload: {
                  chat_id: frame.payload.chat_id,
                  user_message_id: frame.payload.message_id,
                  message_id: "assistant-message-id",
                  full_content: "ok",
                  category: "general_knowledge",
                  model_name: "test-model",
                },
              }));
              ws.send(JSON.stringify({
                type: "post_processing_metadata",
                payload: { chat_id: frame.payload.chat_id },
              }));
            }, 10);
          }
          if (frame.type === "ai_response_completed") {
            const message = frame.payload.message as Record<string, unknown>;
            ws.send(JSON.stringify({
              type: "ai_response_storage_confirmed",
              payload: { message_id: message.message_id },
            }));
          }
        });
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.sendMessage({
        message: "Email [EMAIL_1_com] or call [PHONE_1_567].",
        piiMappings: [
          { placeholder: "[EMAIL_1_com]", original: "sarah@example.com", type: "EMAIL" },
          { placeholder: "[PHONE_1_567]", original: "+1 (555) 123-4567", type: "PHONE" },
        ],
      });

      const userMessage = captured.messagePayload?.message as Record<string, unknown> | undefined;
      assert.equal(userMessage?.content, "Email [EMAIL_1_com] or call [PHONE_1_567].");
      assert.equal(JSON.stringify(captured.messagePayload).includes("sarah@example.com"), false);
      assert.equal(JSON.stringify(captured.messagePayload).includes("+1 (555) 123-4567"), false);

      assert.equal(typeof captured.metadataPayload?.encrypted_pii_mappings, "string");
      const masterKey = Buffer.alloc(32);
      const encryptedChatKey = String(captured.metadataPayload?.encrypted_chat_key);
      const chatKey = await decryptBytesWithAesGcm(encryptedChatKey, masterKey);
      assert.ok(chatKey);
      const mappingsJson = await decryptWithAesGcmCombined(
        String(captured.metadataPayload?.encrypted_pii_mappings),
        chatKey,
      );
      assert.deepEqual(JSON.parse(mappingsJson ?? "[]"), [
        { placeholder: "[EMAIL_1_com]", original: "sarah@example.com", type: "EMAIL" },
        { placeholder: "[PHONE_1_567]", original: "+1 (555) 123-4567", type: "PHONE" },
      ]);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});

describe("CLI incognito chat payloads", () => {
  it("can include known Learning Mode context without changing incognito state", async () => {
    const captured: { messagePayload?: Record<string, unknown> } = {};
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          if (frame.type !== "chat_message_added") return;

          captured.messagePayload = frame.payload;
          const message = frame.payload.message as Record<string, unknown>;
          ws.send(JSON.stringify({
            type: "chat_message_confirmed",
            payload: {
              chat_id: frame.payload.chat_id,
              message_id: message.message_id,
            },
          }));
          ws.send(JSON.stringify({
            type: "ai_background_response_completed",
            payload: {
              chat_id: frame.payload.chat_id,
              user_message_id: message.message_id,
              message_id: "assistant-message-id",
              full_content: "ok",
              category: "general_knowledge",
              model_name: "test-model",
            },
          }));
          ws.send(JSON.stringify({
            type: "post_processing_metadata",
            payload: { chat_id: frame.payload.chat_id },
          }));
        });
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.sendMessage({
        message: "Explain slowly",
        incognito: true,
        learningMode: { enabled: true, ageGroup: "16_18" },
        precollectResponse: true,
      });

      assert.equal(captured.messagePayload?.is_incognito, true);
      assert.deepEqual(captured.messagePayload?.learning_mode, {
        enabled: true,
        age_group: "16_18",
      });
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("sends current message history with incognito messages", async () => {
    const captured: { messagePayload?: Record<string, unknown> } = {};
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          if (frame.type !== "chat_message_added") return;

          captured.messagePayload = frame.payload;
          const message = frame.payload.message as Record<string, unknown>;
          ws.send(JSON.stringify({
            type: "chat_message_confirmed",
            payload: {
              chat_id: frame.payload.chat_id,
              message_id: message.message_id,
            },
          }));
          ws.send(JSON.stringify({
            type: "ai_background_response_completed",
            payload: {
              chat_id: frame.payload.chat_id,
              user_message_id: message.message_id,
              message_id: "assistant-message-id",
              full_content: "ok",
              category: "general_knowledge",
              model_name: "test-model",
            },
          }));
          ws.send(JSON.stringify({
            type: "post_processing_metadata",
            payload: { chat_id: frame.payload.chat_id },
          }));
        });
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.sendMessage({
        message: "Benchmark prompt",
        incognito: true,
        precollectResponse: true,
      });

      assert.equal(captured.messagePayload?.is_incognito, true);
      const message = captured.messagePayload?.message as Record<string, unknown> | undefined;
      const history = captured.messagePayload?.message_history as Record<string, unknown>[] | undefined;
      assert.equal(Array.isArray(history), true);
      assert.equal(history?.length, 1);
      assert.equal(history?.[0]?.message_id, message?.message_id);
      assert.equal(history?.[0]?.chat_id, captured.messagePayload?.chat_id);
      assert.equal(history?.[0]?.role, "user");
      assert.equal(history?.[0]?.sender_name, "User");
      assert.equal(history?.[0]?.content, "Benchmark prompt");
      assert.equal(typeof history?.[0]?.created_at, "number");
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("prepends provided benchmark history before the current incognito message", async () => {
    const captured: { messagePayload?: Record<string, unknown> } = {};
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token" }));
        return;
      }
      response.writeHead(404);
      response.end();
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          if (frame.type !== "chat_message_added") return;
          captured.messagePayload = frame.payload;
          const message = frame.payload.message as Record<string, unknown>;
          ws.send(JSON.stringify({
            type: "chat_message_confirmed",
            payload: { chat_id: frame.payload.chat_id, message_id: message.message_id },
          }));
          ws.send(JSON.stringify({
            type: "ai_background_response_completed",
            payload: {
              chat_id: frame.payload.chat_id,
              user_message_id: message.message_id,
              message_id: "assistant-message-id",
              full_content: "ok",
            },
          }));
          ws.send(JSON.stringify({ type: "post_processing_metadata", payload: { chat_id: frame.payload.chat_id } }));
        });
      });
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.sendMessage({
        message: "Follow-up prompt",
        incognito: true,
        messageHistory: [
          { message_id: "history-1", role: "user", sender_name: "User", content: "Earlier user", created_at: 100 },
          { message_id: "history-2", role: "assistant", sender_name: "Assistant", content: "Earlier assistant", created_at: 101 },
        ],
        precollectResponse: true,
      });

      const history = captured.messagePayload?.message_history as Record<string, unknown>[] | undefined;
      assert.equal(history?.length, 3);
      assert.equal(history?.[0]?.message_id, "history-1");
      assert.equal(history?.[1]?.message_id, "history-2");
      assert.equal(history?.[2]?.content, "Follow-up prompt");
      assert.equal(history?.[0]?.chat_id, captured.messagePayload?.chat_id);
      assert.equal(history?.[1]?.chat_id, captured.messagePayload?.chat_id);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});

describe("sub-chat encryption helpers", () => {
  it("encrypts child first-message metadata with the parent chat key", async () => {
    const parentKey = new Uint8Array(32).fill(7);
    const encryptedChatKey = "wrapped-parent-key";
    const payloads = await buildSubChatEncryptedMetadataPayloads({
      parentChatId: "parent-chat-id",
      parentChatKey: parentKey,
      encryptedParentChatKey: encryptedChatKey,
      createdAt: 1780000000,
      subChats: [
        {
          id: "child-chat-id",
          user_message_id: "child-user-message-id",
          prompt: "Research the counterargument.",
        },
      ],
    });

    assert.equal(payloads.length, 1);
    const payload = payloads[0];
    assert.equal(payload.chat_id, "child-chat-id");
    assert.equal(payload.parent_id, "parent-chat-id");
    assert.equal(payload.is_sub_chat, true);
    assert.equal(payload.message_id, "child-user-message-id");
    assert.equal(payload.encrypted_chat_key, encryptedChatKey);
    assert.equal(payload.versions.messages_v, 1);
    assert.equal(payload.versions.title_v, 0);

    assert.equal(
      await decryptWithAesGcmCombined(payload.encrypted_content, parentKey),
      "Research the counterargument.",
    );
    assert.equal(
      await decryptWithAesGcmCombined(payload.encrypted_sender_name, parentKey),
      "User",
    );
    assert.equal(
      await decryptWithAesGcmCombined(payload.encrypted_title, parentKey),
      "Research the counterargument.",
    );
  });

  it("builds approval and cancellation payloads only from explicit decisions", () => {
    assert.deepEqual(
      buildSubChatConfirmationPayload({
        chatId: "parent-chat-id",
        taskId: "task-id",
        approved: true,
        approveCount: 2,
      }),
      {
        chat_id: "parent-chat-id",
        task_id: "task-id",
        action: "approve",
        approve_count: 2,
      },
    );

    assert.deepEqual(
      buildSubChatConfirmationPayload({
        chatId: "parent-chat-id",
        taskId: "task-id",
        approved: false,
      }),
      {
        chat_id: "parent-chat-id",
        task_id: "task-id",
        action: "cancel",
        approve_count: null,
      },
    );
  });
});

describe("sync delta request helpers", () => {
  it("forces a message refresh when cached metadata has no local messages", () => {
    assert.equal(
      getClientMessagesVersionForSync({
        details: { id: "child-chat-id", messages_v: 2 },
        messages: [],
      }),
      0,
    );
  });

  it("keeps the cached messages version when local messages are present", () => {
    assert.equal(
      getClientMessagesVersionForSync({
        details: { id: "child-chat-id", messages_v: 2 },
        messages: ['{"id":"message-id"}'],
      }),
      2,
    );
  });
});
