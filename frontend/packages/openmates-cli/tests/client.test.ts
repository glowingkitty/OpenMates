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
import { createHash } from "node:crypto";
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
        emailEncryptionKeyB64: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
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
  buildTaskEventSystemMessage,
  buildTaskUpdateJobPersistPayload,
  messageExplicitlyRequestsTasksAppSkill,
  taskUpdateJobBelongsToActiveTurn,
  buildConnectedAccountDirectoryPayload,
  buildSubChatConfirmationPayload,
  buildSubChatEncryptedMetadataPayloads,
  buildTurnTokenRefsRequestPayload,
  getClientMessagesVersionForSync,
} = await import("../src/client.ts");
const {
  decryptBytesWithAesGcm,
  decryptWithAesGcmCombined,
  createApiKeyCryptoMaterial,
  encryptBytesWithAesGcm,
  encryptWithAesGcmCombined,
  sealChatCompletionRecoveryPayload,
} = await import("../src/crypto.ts");

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

  it("manages application preview lifecycle through authenticated embed preview endpoints", async () => {
    const requests: Array<{ method?: string; url?: string; body?: Record<string, unknown>; cookie?: string }> = [];
    const embedId = "12345678-1234-4234-9234-123456789abc";
    const sessionId = "87654321-1234-4234-9234-123456789abc";
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      let raw = "";
      request.setEncoding("utf8");
      request.on("data", (chunk) => { raw += chunk; });
      request.on("end", () => {
        requests.push({
          method: request.method,
          url: request.url,
          body: raw ? JSON.parse(raw) as Record<string, unknown> : undefined,
          cookie: String(request.headers.cookie ?? ""),
        });
        response.writeHead(200, { "content-type": "application/json" });
        if (request.url === `/v1/applications/${embedId}/preview/start`) {
          response.end(JSON.stringify({ session_id: sessionId, preview_url: "https://preview.example/t/token/", status: "queued", credits_per_minute: 5 }));
          return;
        }
        if (request.url === `/v1/applications/preview/${sessionId}`) {
          response.end(JSON.stringify({ session_id: sessionId, status: "running", events: [], auto_started: false }));
          return;
        }
        if (request.url === `/v1/applications/preview/${sessionId}/open`) {
          response.end(JSON.stringify({ session_id: sessionId, status: "running", events: [], auto_started: false }));
          return;
        }
        if (request.url === `/v1/applications/preview/${sessionId}/stop`) {
          response.end(JSON.stringify({ session_id: sessionId, status: "stopped", charged_credits: 5 }));
          return;
        }
        response.writeHead(404);
        response.end(JSON.stringify({ detail: "not found" }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.startApplicationPreview({ embedId, chatId: "chat-1", requestedRuntime: "svelte" });
      await client.getApplicationPreviewStatus(sessionId);
      await client.openApplicationPreview(sessionId);
      await client.stopApplicationPreview(sessionId);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }

    assert.deepEqual(requests.map((request) => `${request.method} ${request.url}`), [
      `POST /v1/applications/${embedId}/preview/start`,
      `GET /v1/applications/preview/${sessionId}`,
      `POST /v1/applications/preview/${sessionId}/open`,
      `POST /v1/applications/preview/${sessionId}/stop`,
    ]);
    assert.deepEqual(requests[0].body, { chat_id: "chat-1", requested_runtime: "svelte" });
    assert.ok(requests.every((request) => request.cookie?.includes("auth_refresh_token=test-refresh-token")));
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

  it("returns the current rotated cookie jar for upload authentication", async () => {
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/apps?include_unavailable=true");
      response.writeHead(200, {
        "content-type": "application/json",
        "set-cookie": "auth_refresh_token=rotated-upload-token; Path=/; HttpOnly",
      });
      response.end(JSON.stringify({ apps: [] }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.listApps();

      const uploadSession = client.getSession();
      assert.strictEqual(uploadSession.cookies.auth_refresh_token, "rotated-upload-token");

      const saved = JSON.parse(readFileSync(sessionPath, "utf-8"));
      assert.strictEqual(saved.cookies.auth_refresh_token, "rotated-upload-token");
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

  it("creates API keys through the audited typed path while generic settings POST stays blocked", async () => {
    let seenBody: Record<string, unknown> | null = null;
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/settings/api-keys");
      assert.strictEqual(request.method, "POST");
      let raw = "";
      request.setEncoding("utf8");
      request.on("data", (chunk) => {
        raw += chunk;
      });
      request.on("end", () => {
        seenBody = JSON.parse(raw) as Record<string, unknown>;
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ id: "key-1", full_access: true, scopes: {} }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await assert.rejects(
        () => client.settingsPost("api-keys", {}),
        /Blocked operation: \/v1\/settings\/api-keys/,
      );
      const result = await client.createApiKey({ name: "SDK live test" });

      assert.match(result.api_key, /^sk-api-[A-Za-z0-9]{32}$/);
      assert.deepEqual(result.key, { id: "key-1", full_access: true, scopes: {} });
      assert.ok(seenBody);
      assert.equal(seenBody.encrypted_name, result.crypto.encryptedName);
      assert.equal(seenBody.api_key_hash, result.crypto.apiKeyHash);
      assert.equal(seenBody.encrypted_key_prefix, result.crypto.encryptedKeyPrefix);
      assert.equal(seenBody.encrypted_master_key, result.crypto.encryptedMasterKey);
      assert.equal(seenBody.full_access, true);
      assert.deepEqual(seenBody.scopes, {});
      assert.equal(seenBody.credit_limit, null);
      assert.equal(seenBody.expires_at, null);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("lists API keys with decrypted display fields and pending device counts", async () => {
    const material = await createApiKeyCryptoMaterial("CLI Listed Key", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=");
    const server = createServer((_request: IncomingMessage, response: ServerResponse) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({
        api_keys: [{
          id: "key-1",
          encrypted_name: material.encryptedName,
          encrypted_key_prefix: material.encryptedKeyPrefix,
          created_at: "2026-07-15T10:00:00Z",
          last_used_at: null,
          full_access: true,
          scopes: {},
          credit_limit: null,
          pending_device_count: 1,
        }],
      }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const result = await client.listApiKeys();

      assert.equal(result.api_keys[0].name, "CLI Listed Key");
      assert.match(result.api_keys[0].key_prefix, /^sk-api-.+\.\.\.$/);
      assert.equal(result.api_keys[0].last_used_at, null);
      assert.equal(result.api_keys[0].pending_device_count, 1);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("sends stable CLI API-key device headers for app-skill execution", async () => {
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/apps/code/skills/get_docs");
      assert.strictEqual(request.method, "POST");
      assert.strictEqual(request.headers.authorization, "Bearer sk-api-test-key");
      assert.strictEqual(request.headers["x-openmates-sdk"], "cli");
      assert.match(String(request.headers["x-openmates-device-identity"]), /^cli:.+:.+$/);
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ success: true, data: { ok: true } }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const result = await client.runSkill({
        app: "code",
        skill: "get_docs",
        inputData: { library: "React", question: "useState" },
        apiKey: "sk-api-test-key",
      });

      assert.deepEqual(result, { success: true, data: { ok: true } });
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("rejects app-skill responses that carry skill-level errors", async () => {
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      assert.strictEqual(request.url, "/v1/apps/news/skills/search");
      assert.strictEqual(request.method, "POST");
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ success: true, data: { results: [], error: "provider quota exceeded" } }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await assert.rejects(
        client.runSkill({
          app: "news",
          skill: "search",
          inputData: { requests: [{ query: "OpenMates" }] },
        }),
        /Skill execution failed: provider quota exceeded/,
      );
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("uses action-code and TOTP endpoints for destructive CLI step-up", async () => {
    const seen: Array<{ method: string | undefined; url: string | undefined; body: unknown }> = [];
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      let raw = "";
      request.setEncoding("utf8");
      request.on("data", (chunk) => { raw += chunk; });
      request.on("end", () => {
        const body = raw ? JSON.parse(raw) : undefined;
        seen.push({ method: request.method, url: request.url, body });
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });

      await client.requestActionEmailCode("delete_team");
      await client.verifyActionEmailCode("delete_team", "123456");
      await client.verifyTotpForCurrentSession("654321");

      assert.deepEqual(seen.map((request) => [request.method, request.url, request.body]), [
        ["POST", "/v1/settings/request-action-verification", { action: "delete_team", email_encryption_key: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=" }],
        ["POST", "/v1/settings/verify-action-code", { action: "delete_team", code: "123456" }],
        ["POST", "/v1/auth/2fa/verify/device", { tfa_code: "654321" }],
      ]);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("keeps polling app-skill tasks after transient task status failures", async () => {
    let taskPolls = 0;
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.url === "/v1/apps/models3d/skills/generate") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, data: { task_id: "task-1" } }));
        return;
      }

      if (request.url === "/v1/tasks/task-1") {
        taskPolls += 1;
        if (taskPolls === 1) {
          response.writeHead(502, { "content-type": "application/json" });
          response.end(JSON.stringify({ detail: "temporary gateway error" }));
          return;
        }
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ task_id: "task-1", status: "completed", result: { ok: true } }));
        return;
      }

      response.writeHead(404);
      response.end();
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const result = await client.runSkill({
        app: "models3d",
        skill: "generate",
        inputData: { image: "embed:test" },
      });

      assert.deepEqual(result, { success: true, data: { ok: true } });
      assert.equal(taskPolls, 2);
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

  it("refreshes exact chat messages before showing a selected chat", async () => {
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

    const chatId = "22222222-2222-4222-8222-222222222222";
    const chatKey = new Uint8Array(32).fill(8);
    const masterKey = new Uint8Array(32);
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, masterKey);
    const encryptedMessage = await encryptWithAesGcmCombined("Persisted fallback chat message", chatKey);
    const syncPayloads: Record<string, any>[] = [];

    wsServer.on("connection", (socket: any) => {
      socket.on("message", (raw: Buffer) => {
        const frame = JSON.parse(raw.toString());
        if (frame.type !== "phased_sync_request") return;
        syncPayloads.push(frame.payload);
        const isTargetedMetadataRefresh = Array.isArray(frame.payload?.refresh_chat_ids)
          && frame.payload.refresh_chat_ids.includes(chatId);
        if (frame.payload?.phase === "all" && !isTargetedMetadataRefresh) {
          socket.send(JSON.stringify({
            type: "phase_2_last_20_chats_ready",
            payload: {
              total_chat_count: 1,
              chats: [{
                chat_details: {
                  id: chatId,
                  encrypted_chat_key: encryptedChatKey,
                  messages_v: 1,
                  title_v: 0,
                  draft_v: 0,
                  last_edited_overall_timestamp: 1780000000,
                },
              }],
            },
          }));
        }
        if (frame.payload?.phase === "phase3") {
          socket.send(JSON.stringify({
            type: "background_message_sync",
            payload: {
              chats: [{
                chat_id: chatId,
                messages: [JSON.stringify({
                  client_message_id: "message-1",
                  chat_id: chatId,
                  encrypted_content: encryptedMessage,
                  role: "assistant",
                  created_at: 1780000000,
                })],
              }],
            },
          }));
        }
        socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
      });
    });

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      const result = await client.getChatMessages(chatId);

      assert.equal(syncPayloads.length, 3);
      assert.deepEqual(syncPayloads[1]?.refresh_chat_ids, [chatId]);
      assert.equal(syncPayloads[2]?.phase, "phase3");
      assert.equal(syncPayloads[2]?.client_chat_versions?.[chatId], undefined);
      assert.equal(result.messages.length, 1);
      assert.equal(result.messages[0]?.content, "Persisted fallback chat message");
    } finally {
      await new Promise<void>((resolve) => wsServer.close(() => resolve()));
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("persists passive task update jobs advertised during CLI reconnect sync", async () => {
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

    const chatKey = new Uint8Array(32).fill(9);
    const masterKey = new Uint8Array(32);
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, masterKey);
    let syncRequests = 0;
    const captured: { frameTypes: string[]; persistPayload?: Record<string, any>; systemMessage?: Record<string, any> } = {
      frameTypes: [],
    };

    wsServer.on("connection", (socket: any) => {
      socket.on("message", (raw: Buffer) => {
        const frame = JSON.parse(raw.toString());
        captured.frameTypes.push(frame.type);

        if (frame.type === "phased_sync_request") {
          syncRequests += 1;
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
                  last_edited_overall_timestamp: 1780000000,
                },
              }],
            },
          }));
          if (syncRequests === 1) {
            socket.send(JSON.stringify({
              type: "task_update_jobs_available",
              payload: {
                jobs: [{
                  job_id: "task-update-job-reconnect",
                  task_id: "task-reconnect-1",
                  chat_id: "chat-1",
                  revision: 1,
                  task_key_version: 1,
                  expires_at: 1780000600,
                }],
              },
            }));
          }
          socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
        }

        if (frame.type === "task_update_job_claim") {
          socket.send(JSON.stringify({
            type: "task_update_job_claimed",
            payload: {
              job_id: "task-update-job-reconnect",
              task_id: "task-reconnect-1",
              chat_id: "chat-1",
              message_id: "user-message-1",
              operation: "create",
              state: "LEASED",
              lease_token: "lease-token",
              lease_generation: 1,
              expected_task_version: 0,
              private_patch: {
                title: "Reconnect task title",
                description: "Reconnect task description",
              },
              safe_metadata: {
                status: "todo",
                assignee_type: "user",
                primary_chat_id: "chat-1",
                position: 1780000001,
                created_at: 1780000001,
                updated_at: 1780000001,
              },
            },
          }));
        }

        if (frame.type === "task_update_job_persist") {
          captured.persistPayload = frame.payload;
          socket.send(JSON.stringify({
            type: "task_update_job_persisted",
            payload: { job_id: "task-update-job-reconnect" },
          }));
        }

        if (frame.type === "chat_system_message_added") {
          captured.systemMessage = frame.payload.message;
          socket.send(JSON.stringify({
            type: "system_message_confirmed",
            payload: { message_id: frame.payload.message.message_id },
          }));
        }

        if (frame.type === "task_update_job_event_confirmed") {
          socket.send(JSON.stringify({
            type: "task_update_job_event_confirmed",
            payload: { job_id: "task-update-job-reconnect" },
          }));
        }
      });
    });

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.ensureSynced(true);

      assert.equal(syncRequests, 2);
      assert.deepEqual(
        captured.frameTypes.filter((type) => type.startsWith("task_update_job") || type === "chat_system_message_added"),
        [
          "task_update_job_claim",
          "task_update_job_persist",
          "chat_system_message_added",
          "task_update_job_event_confirmed",
        ],
      );
      assert.ok(captured.persistPayload);
      const serializedPersistPayload = JSON.stringify(captured.persistPayload);
      assert.equal(serializedPersistPayload.includes("Reconnect task title"), false);
      assert.equal(serializedPersistPayload.includes("Reconnect task description"), false);
      assert.equal(captured.persistPayload.encrypted_task_payload.task_id, "task-reconnect-1");
      assert.ok(captured.persistPayload.encrypted_task_payload.encrypted_task_key);
      assert.ok(captured.persistPayload.encrypted_task_payload.encrypted_title);
      assert.ok(captured.persistPayload.encrypted_task_payload.encrypted_description);
      assert.ok(captured.systemMessage?.encrypted_content);
      assert.equal(captured.systemMessage.encrypted_content.includes("Reconnect task title"), false);
      const eventText = await decryptWithAesGcmCombined(captured.systemMessage.encrypted_content, chatKey);
      assert.match(eventText, /Reconnect task title/);
    } finally {
      await new Promise<void>((resolve) => wsServer.close(() => resolve()));
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("skips passive task update jobs that do not include source chat context", async () => {
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

    const capturedFrameTypes: string[] = [];
    let syncRequests = 0;

    wsServer.on("connection", (socket: any) => {
      socket.on("message", (raw: Buffer) => {
        const frame = JSON.parse(raw.toString());
        capturedFrameTypes.push(frame.type);

        if (frame.type === "phased_sync_request") {
          syncRequests += 1;
          socket.send(JSON.stringify({
            type: "phase_2_last_20_chats_ready",
            payload: { total_chat_count: 0, chats: [] },
          }));
          if (syncRequests === 1) {
            socket.send(JSON.stringify({
              type: "task_update_jobs_available",
              payload: {
                jobs: [{
                  job_id: "task-update-job-no-source",
                  task_id: "task-no-source-1",
                  revision: 1,
                  task_key_version: 1,
                  expires_at: 1780000600,
                }],
              },
            }));
          }
          socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
        }

        if (frame.type === "task_update_job_claim") {
          socket.send(JSON.stringify({
            type: "task_update_job_claimed",
            payload: {
              job_id: "task-update-job-no-source",
              task_id: "task-no-source-1",
              message_id: "user-message-1",
              operation: "create",
              state: "LEASED",
              lease_token: "lease-token",
              lease_generation: 1,
              expected_task_version: 0,
              private_patch: { title: "No source title" },
              safe_metadata: { status: "todo", assignee_type: "user" },
            },
          }));
        }
      });
    });

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.ensureSynced(true);

      assert.equal(syncRequests, 2);
      assert.deepEqual(
        capturedFrameTypes.filter((type) => type.startsWith("task_update_job") || type === "chat_system_message_added"),
        ["task_update_job_claim"],
      );
    } finally {
      await new Promise<void>((resolve) => wsServer.close(() => resolve()));
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("skips passive task update jobs already leased by another device", async () => {
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

    const capturedFrameTypes: string[] = [];
    let syncRequests = 0;

    wsServer.on("connection", (socket: any) => {
      socket.on("message", (raw: Buffer) => {
        const frame = JSON.parse(raw.toString());
        capturedFrameTypes.push(frame.type);

        if (frame.type === "phased_sync_request") {
          syncRequests += 1;
          socket.send(JSON.stringify({
            type: "phase_2_last_20_chats_ready",
            payload: { total_chat_count: 0, chats: [] },
          }));
          if (syncRequests === 1) {
            socket.send(JSON.stringify({
              type: "task_update_jobs_available",
              payload: {
                jobs: [{
                  job_id: "task-update-job-leased",
                  task_id: "task-leased-1",
                  chat_id: "chat-1",
                  revision: 1,
                  task_key_version: 1,
                  expires_at: 1780000600,
                }],
              },
            }));
          }
          socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
        }

        if (frame.type === "task_update_job_claim") {
          socket.send(JSON.stringify({
            type: "error",
            payload: {
              code: "task_update_job_lease_conflict",
              message: "Task update job is leased by another device",
            },
          }));
        }
      });
    });

    try {
      writeLegacySession(`http://127.0.0.1:${address.port}`);
      const client = OpenMatesClient.load({ apiUrl: `http://127.0.0.1:${address.port}` });
      await client.ensureSynced(true);

      assert.equal(syncRequests, 2);
      assert.deepEqual(
        capturedFrameTypes.filter((type) => type.startsWith("task_update_job") || type === "chat_system_message_added"),
        ["task_update_job_claim"],
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

describe("CLI streamed embed persistence", () => {
  it("uses the same deterministic parent embed key across version updates", async () => {
    writeLegacySession();
    const client = OpenMatesClient.load();
    const masterKey = new Uint8Array(32);
    const chatKey = new Uint8Array(32).fill(7);
    const frames: { type: string; payload: Record<string, any> }[] = [];
    const ws = {
      waitForMessage: async () => undefined,
      sendAsync: async (type: string, payload: Record<string, any>) => {
        frames.push({ type, payload });
      },
    };

    const persist = async (content: string, version: number) => {
      await (client as any).persistStreamedEmbeds({
        ws,
        embeds: [{
          embed_id: "embed-123",
          type: "code-code",
          content,
          status: "finished",
          version_number: version,
          version_history_rows: [{
            embed_id: "embed-123",
            version_number: version,
            snapshot: content,
            created_at: 1780000000 + version,
          }],
        }],
        chatId: "chat-123",
        chatKeyBytes: chatKey,
        fallbackMessageId: "message-123",
        ownerId: "user-uuid-123",
      });
    };

    await persist("version one", 1);
    await persist("version two", 2);

    const keyFrames = frames.filter((frame) => frame.type === "store_embed_keys");
    const diffFrames = frames.filter((frame) => frame.type === "store_embed_diff");
    const expectedUserHash = createHash("sha256").update("user-uuid-123").digest("hex");
    const storeFrames = frames.filter((frame) => frame.type === "store_embed");
    assert.equal(storeFrames[0].payload.hashed_user_id, expectedUserHash);
    assert.equal(keyFrames.length, 2);
    assert.equal(diffFrames.length, 2);
    assert.ok(
      frames.findIndex((frame) => frame.type === "store_embed_keys") <
        frames.findIndex((frame) => frame.type === "store_embed_diff"),
    );

    const firstMasterWrapper = keyFrames[0].payload.keys.find(
      (entry: Record<string, unknown>) => entry.key_type === "master",
    );
    const secondMasterWrapper = keyFrames[1].payload.keys.find(
      (entry: Record<string, unknown>) => entry.key_type === "master",
    );
    const firstKey = await decryptBytesWithAesGcm(firstMasterWrapper.encrypted_embed_key, masterKey);
    const secondKey = await decryptBytesWithAesGcm(secondMasterWrapper.encrypted_embed_key, masterKey);
    assert.ok(firstKey);
    assert.ok(secondKey);
    assert.deepEqual(secondKey, firstKey);
    assert.equal(
      await decryptWithAesGcmCombined(diffFrames[0].payload.encrypted_snapshot, firstKey),
      "version one",
    );
    assert.equal(
      await decryptWithAesGcmCombined(diffFrames[1].payload.encrypted_snapshot, secondKey),
      "version two",
    );
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
          provider_id: "google",
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
          provider_id: "google",
          account_ref: "work",
          label: "Work",
          capabilities: ["read"],
      },
    ]);

    assert.equal(request.refs[0]?.refresh_token_envelope.refresh_token, "refresh-secret");
    assert.equal(request.refs[0]?.provider_id, "google");
    assert.equal(directory[0]?.provider_id, "google");
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

describe("task update job helpers", () => {
  it("builds encrypted task event system messages without plaintext leakage", async () => {
    const chatKey = new Uint8Array(32).fill(11);
    const systemMessage = await buildTaskEventSystemMessage({
      chatKey,
      userMessageId: "user-message-1",
      event: {
        event_id: "task-event-1",
        chat_id: "chat-1",
        task_id: "TASK-123",
        short_id: "TASK-123",
        event_type: "created",
        title: "Book flights",
        status: "todo",
        created_at: 1780000000,
      },
    });

    assert.equal(systemMessage.role, "system");
    assert.equal(systemMessage.message_id, "task-event-task-event-1");
    assert.equal(systemMessage.user_message_id, "user-message-1");
    assert.equal(systemMessage.created_at, 1780000000);
    assert.equal(systemMessage.encrypted_content.includes("Book flights"), false);
    const decrypted = await decryptWithAesGcmCombined(systemMessage.encrypted_content, chatKey);
    assert.match(decrypted, /TASK-123 created/);
    assert.match(decrypted, /Book flights/);
  });

  it("builds task update job persist payloads with only encrypted task content", () => {
    const payload = buildTaskUpdateJobPersistPayload({
      jobId: "task-update-job-1",
      leaseToken: "lease-token",
      leaseGeneration: 2,
      expectedTaskVersion: 4,
      encryptedTaskPayload: {
        encrypted_title: "cipher-title",
        encrypted_description: "cipher-description",
        version: 5,
      },
      encryptedTaskEventMessage: "cipher-system-event",
    });

    assert.deepEqual(payload, {
      protocol_version: 1,
      job_id: "task-update-job-1",
      lease_token: "lease-token",
      lease_generation: 2,
      expected_task_version: 4,
      encrypted_task_payload: {
        encrypted_title: "cipher-title",
        encrypted_description: "cipher-description",
        version: 5,
      },
      encrypted_task_event_message: "cipher-system-event",
    });
    assert.throws(
      () => buildTaskUpdateJobPersistPayload({
        jobId: "task-update-job-1",
        leaseToken: "lease-token",
        leaseGeneration: 2,
        expectedTaskVersion: 4,
        encryptedTaskPayload: { title: "Book flights" },
        encryptedTaskEventMessage: "cipher-system-event",
      }),
      /plaintext/,
    );

    const createPayload = buildTaskUpdateJobPersistPayload({
      jobId: "task-update-job-2",
      leaseToken: "lease-token",
      leaseGeneration: 3,
      expectedTaskVersion: 0,
      encryptedTaskPayload: {
        task_id: "task-1",
        short_id: undefined,
        plan_id: null,
        due_at: null,
        task_type: "verification",
        verification_id: "verify-1",
        parent_task_id: "parent-1",
        queue_state: "waiting_for_user",
        blocked_reason_code: "needs_input",
        ai_execution_state: "waiting_for_user",
        encrypted_task_key: "cipher-key",
        encrypted_title: "cipher-title",
        encrypted_description: "cipher-description",
        version: 1,
      },
    });
    assert.deepEqual(createPayload.encrypted_task_payload, {
      task_id: "task-1",
      task_type: "verification",
      verification_id: "verify-1",
      parent_task_id: "parent-1",
      queue_state: "waiting_for_user",
      blocked_reason_code: "needs_input",
      ai_execution_state: "waiting_for_user",
      encrypted_task_key: "cipher-key",
      encrypted_title: "cipher-title",
      encrypted_description: "cipher-description",
      version: 1,
    });
  });

  it("keeps task update jobs only when the current response emitted a matching event", () => {
    assert.equal(
      taskUpdateJobBelongsToActiveTurn(
        {
          job_id: "job-active-turn",
          task_id: "TASK-1",
          chat_id: "chat-active",
          revision: 1,
          task_key_version: 1,
          expires_at: 1780000900,
        },
        "chat-active",
        [
          {
            event_id: "event-active",
            chat_id: "chat-active",
            task_id: "TASK-1",
            event_type: "updated",
            task_update_job_id: "job-active-turn",
          },
        ],
      ),
      true,
    );
    assert.equal(
      taskUpdateJobBelongsToActiveTurn(
        {
          job_id: "job-same-chat-stale",
          task_id: "TASK-STALE",
          chat_id: "chat-active",
          revision: 1,
          task_key_version: 1,
          expires_at: 1780000900,
        },
        "chat-active",
        [],
      ),
      false,
    );
    assert.equal(
      taskUpdateJobBelongsToActiveTurn(
        {
          job_id: "job-stale",
          task_id: "TASK-STALE",
          chat_id: "chat-old",
          revision: 1,
          task_key_version: 1,
          expires_at: 1780000900,
        },
        "chat-active",
        [],
      ),
      false,
    );
  });

  it("detects explicit Tasks app-skill messages", () => {
    assert.equal(
      messageExplicitlyRequestsTasksAppSkill("@skill:tasks:create create launch tasks"),
      true,
    );
    assert.equal(
      messageExplicitlyRequestsTasksAppSkill("@skill:tasks:search find launch tasks"),
      true,
    );
    assert.equal(
      messageExplicitlyRequestsTasksAppSkill("@Tasks-Create create launch tasks"),
      true,
    );
    assert.equal(
      messageExplicitlyRequestsTasksAppSkill("@Tasks-Search find launch tasks"),
      true,
    );
    assert.equal(messageExplicitlyRequestsTasksAppSkill("create launch tasks"), false);
  });
});

describe("CLI saved-chat recovery preflight", () => {
  it("stops before inference when saved-chat preflight requires a client update", async () => {
    const captured: { frameTypes: string[] } = { frameTypes: [] };
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          success: true,
          ws_token: "fresh-ws-token",
          user: { id: "11111111-1111-4111-8111-111111111111" },
        }));
        return;
      }
      if (request.method === "GET" && request.url === "/v1/settings/export-account-data?include_usage=false&include_invoices=false") {
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
          const frame = JSON.parse(raw.toString()) as { type: string };
          captured.frameTypes.push(frame.type);
          if (frame.type === "chat_turn_preflight") {
            ws.send(JSON.stringify({
              type: "error",
              payload: {
                code: "client_update_required",
                message: "Please update OpenMates before sending another saved chat message.",
              },
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
      await assert.rejects(
        client.sendMessage({ message: "This must not reach inference" }),
        /OpenMates CLI update required\. Run `openmates upgrade` and retry\./,
      );
      assert.equal(captured.frameTypes.includes("chat_turn_preflight"), true);
      assert.equal(captured.frameTypes.includes("chat_message_added"), false);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("waits for preflight ack and keeps durable transaction content encrypted", async () => {
    const ownerId = "11111111-1111-4111-8111-111111111111";
    const assistantMessageId = "33333333-3333-4333-8333-333333333333";
    const recoveryJobId = "44444444-4444-4444-8444-444444444444";
    const captured: {
      messagePayload?: Record<string, unknown>;
      preflightPayload?: Record<string, unknown>;
      persistPayload?: Record<string, unknown>;
      frameTypes: string[];
      preflightAcknowledged: boolean;
      terminalSent: boolean;
    } = { frameTypes: [], preflightAcknowledged: false, terminalSent: false };
    let sealedPayloadForTest: string | null = null;
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          success: true,
          ws_token: "fresh-ws-token",
          user: { id: ownerId },
        }));
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
        ws.on("message", async (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          captured.frameTypes.push(frame.type);
          if (frame.type === "chat_turn_preflight") {
            captured.preflightPayload = frame.payload;
            const sealedPayload = await sealChatCompletionRecoveryPayload(
              new TextEncoder().encode(JSON.stringify({
                assistant_message_id: assistantMessageId,
                category: "general_knowledge",
                chat_id: frame.payload.chat_id,
                content: "ok",
                job_id: recoveryJobId,
                key_version: 1,
                model_name: "test-model",
                turn_id: frame.payload.turn_id,
              })),
              {
                recoveryPublicKey: String(frame.payload.recovery_public_key),
                ownerId,
                chatId: String(frame.payload.chat_id),
                turnId: String(frame.payload.turn_id),
                jobId: recoveryJobId,
                assistantMessageId,
                keyVersion: 1,
              },
            );
            sealedPayloadForTest = JSON.stringify(sealedPayload);
            setTimeout(() => {
              captured.preflightAcknowledged = true;
              ws.send(JSON.stringify({
                type: "chat_turn_preflight_ack",
                payload: {
                  preflight_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                  turn_id: frame.payload.turn_id,
                },
              }));
            }, 10);
          }
          if (frame.type === "chat_message_added") {
            assert.equal(captured.preflightAcknowledged, true);
            captured.messagePayload = frame.payload;
            const message = frame.payload.message as Record<string, unknown>;
            ws.send(JSON.stringify({
              type: "chat_message_confirmed",
              payload: {
                chat_id: frame.payload.chat_id,
                message_id: message.message_id,
              },
            }));
            setTimeout(() => {
              captured.terminalSent = true;
              ws.send(JSON.stringify({
                type: "ai_message_update",
                payload: {
                  chat_id: frame.payload.chat_id,
                  user_message_id: message.message_id,
                  message_id: assistantMessageId,
                  full_content_so_far: "stale streamed content",
                  is_final_chunk: true,
                  category: "general_knowledge",
                  model_name: "test-model",
                  recovery_job_id: recoveryJobId,
                  recovery_protocol_version: 1,
                },
              }));
              ws.send(JSON.stringify({
                type: "post_processing_metadata",
                payload: { chat_id: frame.payload.chat_id },
              }));
            }, 10);
          }
          if (frame.type === "recovery_job_claim") {
            assert.equal(frame.payload.job_id, recoveryJobId);
            assert.equal(captured.terminalSent, true);
            assert.ok(sealedPayloadForTest);
            ws.send(JSON.stringify({
              type: "recovery_job_claimed",
              payload: {
                job_id: recoveryJobId,
                state: "LEASED",
                lease_token: "lease-token-1",
                lease_generation: 3,
                sealed_payload: sealedPayloadForTest,
                chat_id: captured.preflightPayload?.chat_id,
                turn_id: captured.preflightPayload?.turn_id,
                assistant_message_id: assistantMessageId,
                chat_key_version: 1,
              },
            }));
          }
          if (frame.type === "recovery_job_persist") {
            captured.persistPayload = frame.payload;
            ws.send(JSON.stringify({
              type: "recovery_job_persisted",
              payload: { job_id: recoveryJobId, state: "TERMINAL", committed_messages_v: 2 },
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
      const result = await client.sendMessage({
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

      assert.ok(captured.preflightPayload);
      assert.equal(captured.frameTypes.indexOf("chat_turn_preflight") < captured.frameTypes.indexOf("chat_message_added"), true);
      assert.equal(captured.frameTypes.includes("encrypted_chat_metadata"), false);
      const inferenceRequest = captured.preflightPayload.inference_request as Record<string, unknown>;
      const finalInferenceRequest = { ...captured.messagePayload };
      delete finalInferenceRequest.protocol_version;
      delete finalInferenceRequest.preflight_id;
      assert.deepEqual(inferenceRequest, finalInferenceRequest);

      const encryptedUserMessage = captured.preflightPayload.encrypted_user_message as Record<string, unknown>;
      assert.deepEqual(Object.keys(encryptedUserMessage).sort(), [
        "chat_id",
        "client_message_id",
        "created_at",
        "encrypted_content",
        "encrypted_pii_mappings",
        "role",
        "updated_at",
      ]);
      assert.equal(typeof encryptedUserMessage.encrypted_pii_mappings, "string");
      assert.equal(JSON.stringify(encryptedUserMessage).includes("Email [EMAIL_1_com]"), false);
      assert.equal(JSON.stringify(encryptedUserMessage).includes("sarah@example.com"), false);
      const newChatMetadata = captured.preflightPayload.encrypted_chat_metadata as Record<string, unknown>;
      assert.deepEqual(Object.keys(newChatMetadata).sort(), [
        "created_at",
        "encrypted_chat_key",
        "encrypted_title",
        "updated_at",
      ]);

      const masterKey = Buffer.alloc(32);
      const encryptedChatKey = String(captured.preflightPayload.encrypted_chat_key);
      const chatKey = await decryptBytesWithAesGcm(encryptedChatKey, masterKey);
      assert.ok(chatKey);
      const mappingsJson = await decryptWithAesGcmCombined(
        String(encryptedUserMessage.encrypted_pii_mappings),
        chatKey,
      );
      assert.deepEqual(JSON.parse(mappingsJson ?? "[]"), [
        { placeholder: "[EMAIL_1_com]", original: "sarah@example.com", type: "EMAIL" },
        { placeholder: "[PHONE_1_567]", original: "+1 (555) 123-4567", type: "PHONE" },
      ]);
      assert.equal(captured.frameTypes.includes("ai_response_completed"), false);
      assert.equal(captured.frameTypes.includes("recovery_job_claim"), true);
      assert.equal(captured.frameTypes.includes("recovery_job_persist"), true);
      assert.equal(result.assistant, "ok");
      assert.ok(captured.persistPayload);
      assert.equal(captured.persistPayload.job_id, recoveryJobId);
      assert.equal(captured.persistPayload.lease_token, "lease-token-1");
      assert.equal(captured.persistPayload.lease_generation, 3);
      assert.equal(captured.persistPayload.expected_messages_v, 1);
      const encryptedAssistant = captured.persistPayload.encrypted_assistant_message as Record<string, unknown>;
      assert.equal(encryptedAssistant.client_message_id, assistantMessageId);
      assert.equal(
        await decryptWithAesGcmCombined(String(encryptedAssistant.encrypted_content), chatKey),
        "ok",
      );
      assert.equal(
        await decryptWithAesGcmCombined(String(encryptedAssistant.encrypted_sender_name), chatKey),
        "Assistant",
      );
      assert.equal(
        await decryptWithAesGcmCombined(String(encryptedAssistant.encrypted_category), chatKey),
        "general_knowledge",
      );
      assert.equal(
        await decryptWithAesGcmCombined(String(encryptedAssistant.encrypted_model_name), chatKey),
        "test-model",
      );
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("lazily registers epoch-1 recovery material for an old saved chat", async () => {
    const chatId = "11111111-1111-4111-8111-111111111111";
    const ownerId = "22222222-2222-4222-8222-222222222222";
    const assistantMessageId = "33333333-3333-4333-8333-333333333333";
    const recoveryJobId = "44444444-4444-4444-8444-444444444444";
    const rawChatKey = new Uint8Array(32).fill(7);
    const encryptedChatKey = await encryptBytesWithAesGcm(rawChatKey, new Uint8Array(32));
    writeFileSync(join(stateDir, "sync_cache.json"), JSON.stringify({
      syncedAt: Date.now(),
      totalChatCount: 1,
      loadedChatCount: 1,
      chats: [{
        details: { id: chatId, encrypted_chat_key: encryptedChatKey, messages_v: 7 },
        messages: [],
      }],
      embeds: [],
      embedKeys: [],
    }));

    const captured: {
      preflightPayload?: Record<string, unknown>;
      messagePayload?: Record<string, unknown>;
      persistPayload?: Record<string, unknown>;
      frameTypes: string[];
    } = { frameTypes: [] };
    let sealedPayloadForTest: string | null = null;
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          success: true,
          ws_token: "fresh-ws-token",
          user: { id: ownerId },
        }));
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
        ws.on("message", async (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          captured.frameTypes.push(frame.type);
          if (frame.type === "chat_turn_preflight") {
            captured.preflightPayload = frame.payload;
            sealedPayloadForTest = JSON.stringify(await sealChatCompletionRecoveryPayload(
              new TextEncoder().encode(JSON.stringify({
                assistant_message_id: assistantMessageId,
                category: null,
                chat_id: chatId,
                content: "ok",
                job_id: recoveryJobId,
                key_version: 1,
                model_name: null,
                turn_id: frame.payload.turn_id,
              })),
              {
                recoveryPublicKey: String(frame.payload.recovery_public_key),
                ownerId,
                chatId,
                turnId: String(frame.payload.turn_id),
                jobId: recoveryJobId,
                assistantMessageId,
                keyVersion: 1,
              },
            ));
            ws.send(JSON.stringify({
              type: "chat_turn_preflight_ack",
              payload: { preflight_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", turn_id: frame.payload.turn_id },
            }));
          }
          if (frame.type === "chat_message_added") {
            captured.messagePayload = frame.payload;
            const message = frame.payload.message as Record<string, unknown>;
            ws.send(JSON.stringify({
              type: "chat_message_confirmed",
              payload: { chat_id: chatId, message_id: message.message_id, new_messages_v: 9 },
            }));
            setTimeout(() => {
              ws.send(JSON.stringify({
                type: "ai_message_update",
                payload: {
                  chat_id: chatId,
                  user_message_id: message.message_id,
                  message_id: assistantMessageId,
                  full_content_so_far: "ok",
                  is_final_chunk: true,
                },
              }));
              ws.send(JSON.stringify({ type: "post_processing_metadata", payload: { chat_id: chatId } }));
            }, 10);
            setTimeout(() => {
              ws.send(JSON.stringify({
                type: "recovery_jobs_available",
                payload: {
                  jobs: [{
                    job_id: recoveryJobId,
                    chat_id: chatId,
                    turn_id: captured.preflightPayload?.turn_id,
                    assistant_message_id: assistantMessageId,
                    chat_key_version: 1,
                  }],
                },
              }));
            }, 30);
          }
          if (frame.type === "recovery_job_claim") {
            assert.ok(sealedPayloadForTest);
            ws.send(JSON.stringify({
              type: "recovery_job_claimed",
              payload: {
                job_id: recoveryJobId,
                state: "LEASED",
                lease_token: "lease-token-old-chat",
                lease_generation: 2,
                sealed_payload: sealedPayloadForTest,
                chat_id: chatId,
                turn_id: captured.preflightPayload?.turn_id,
                assistant_message_id: assistantMessageId,
                chat_key_version: 1,
              },
            }));
          }
          if (frame.type === "recovery_job_persist") {
            captured.persistPayload = frame.payload;
            ws.send(JSON.stringify({
              type: "recovery_job_persisted",
              payload: { job_id: recoveryJobId, state: "TERMINAL", committed_messages_v: 9 },
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
      await client.sendMessage({ message: "Continue this old chat", chatId });

      assert.ok(captured.preflightPayload);
      assert.equal(captured.preflightPayload.expected_messages_v, 7);
      assert.equal(captured.preflightPayload.encrypted_chat_key, encryptedChatKey);
      assert.equal(captured.preflightPayload.chat_key_version, 1);
      assert.equal(typeof captured.preflightPayload.recovery_public_key, "string");
      assert.equal(captured.preflightPayload.encrypted_chat_metadata, undefined);
      assert.equal(captured.frameTypes.includes("encrypted_chat_metadata"), false);
      assert.equal(captured.messagePayload?.protocol_version, 1);
      assert.equal(captured.messagePayload?.preflight_id, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb");
      assert.equal(captured.messagePayload?.turn_id, captured.preflightPayload.turn_id);
      assert.equal(captured.messagePayload?.recovery_public_key, captured.preflightPayload.recovery_public_key);
      assert.equal(captured.messagePayload?.chat_key_version, 1);
      assert.equal(captured.frameTypes.includes("ai_response_completed"), false);
      assert.equal(captured.persistPayload?.expected_messages_v, 9);
      assert.equal(captured.persistPayload?.lease_token, "lease-token-old-chat");
      assert.equal(captured.persistPayload?.lease_generation, 2);
    } finally {
      rmSync(join(stateDir, "sync_cache.json"), { force: true });
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("returns after confirmation for saved team messages that do not mention OpenMates", async () => {
    const teamId = "55555555-5555-4555-8555-555555555555";
    const ownerId = "66666666-6666-4666-8666-666666666666";
    const captured: {
      messagePayload?: Record<string, unknown>;
      preflightPayload?: Record<string, unknown>;
      frameTypes: string[];
    } = { frameTypes: [] };
    const wss = new WebSocketServer({ noServer: true });
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      let raw = "";
      request.setEncoding("utf8");
      request.on("data", (chunk) => { raw += chunk; });
      request.on("end", () => {
        if (request.method === "POST" && request.url === "/v1/auth/session") {
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ success: true, ws_token: "fresh-ws-token", user: { id: ownerId } }));
          return;
        }
        if (request.method === "GET" && request.url === `/v1/sdk/memories?team_id=${teamId}`) {
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ memories: [] }));
          return;
        }
        if (request.method === "POST" && request.url === "/v1/teams") {
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ team: { team_id: teamId, ...(raw ? JSON.parse(raw) as Record<string, unknown> : {}) } }));
          return;
        }
        response.writeHead(404);
        response.end();
      });
    });
    server.on("upgrade", (request, socket, head) => {
      wss.handleUpgrade(request, socket, head, (ws) => {
        ws.on("message", (raw) => {
          const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
          captured.frameTypes.push(frame.type);
          if (frame.type === "chat_turn_preflight") {
            captured.preflightPayload = frame.payload;
            ws.send(JSON.stringify({
              type: "chat_turn_preflight_ack",
              payload: { preflight_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", turn_id: frame.payload.turn_id },
            }));
          }
          if (frame.type === "chat_message_added") {
            captured.messagePayload = frame.payload;
            const message = frame.payload.message as Record<string, unknown>;
            ws.send(JSON.stringify({
              type: "chat_message_confirmed",
              payload: { chat_id: frame.payload.chat_id, message_id: message.message_id, new_messages_v: 1 },
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
      await client.createTeam({ teamId, name: "Team No AI" });
      const result = await client.sendMessage({
        message: "Team note without a mate mention",
        teamId,
        precollectResponse: true,
        responseTimeoutMs: 50,
      });

      assert.equal(result.status, "completed");
      assert.equal(result.assistant, "");
      assert.equal(result.messageId, null);
      assert.equal(captured.messagePayload?.team_id, teamId);
      assert.equal(captured.preflightPayload?.team_id, teamId);
      assert.equal(typeof captured.preflightPayload?.encrypted_chat_key, "string");
      assert.equal(captured.frameTypes.includes("recovery_job_claim"), false);
      assert.equal(captured.frameTypes.includes("ai_response_completed"), false);
    } finally {
      wss.close();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});

describe("CLI incognito chat payloads", () => {
  it("can include known Learning Mode context without changing incognito state", async () => {
    const captured: { messagePayload?: Record<string, unknown>; frameTypes: string[] } = {
      frameTypes: [],
    };
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
          captured.frameTypes.push(frame.type);
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
      assert.equal(captured.frameTypes.includes("chat_turn_preflight"), false);
      assert.equal(captured.frameTypes.includes("encrypted_chat_metadata"), false);
      assert.equal(captured.messagePayload?.protocol_version, undefined);
      assert.equal(captured.messagePayload?.preflight_id, undefined);
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

  it("caps the cached messages version to the local message count", () => {
    assert.equal(
      getClientMessagesVersionForSync({
        details: { id: "child-chat-id", messages_v: 2 },
        messages: ['{"id":"message-id"}'],
      }),
      1,
    );
  });

  it("keeps the cached messages version when it matches the local message count", () => {
    assert.equal(
      getClientMessagesVersionForSync({
        details: { id: "child-chat-id", messages_v: 2 },
        messages: ['{"id":"message-id-1"}', '{"id":"message-id-2"}'],
      }),
      2,
    );
  });
});
