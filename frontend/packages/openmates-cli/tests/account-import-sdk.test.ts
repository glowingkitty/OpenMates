/**
 * Account Import V1 npm SDK contract tests.
 *
 * Purpose: verify the npm SDK exposes Account Import parsing and endpoint
 * helpers after the CLI contract is green.
 * Security: fixtures are synthetic and the fake server asserts SDK import
 * persistence sends encrypted private fields instead of raw plaintext.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/account-import-sdk.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

const { OpenMates } = await import("../src/sdk.ts");
const { createApiKeyCryptoMaterial } = await import("../src/crypto.ts");

describe("account import npm SDK", () => {
  it("exposes ChatGPT import parsing through the account facade", async () => {
    const client = new OpenMates({ apiKey: "sk-api-test", apiUrl: "http://127.0.0.1:9", deviceId: "sdk-chatgpt-test" });
    const parsed = await client.account.parseChatGPTImport(JSON.stringify([{
      id: "chatgpt-chat-1",
      conversation_id: "chatgpt-conversation-1",
      title: "Synthetic ChatGPT SDK chat",
      current_node: "assistant-1",
      mapping: {
        root: { id: "root", message: null, parent: null },
        "user-1": {
          id: "user-1",
          parent: "root",
          message: { id: "message-user-1", author: { role: "user" }, content: { content_type: "text", parts: ["Synthetic ChatGPT SDK user text."] } },
        },
        "assistant-1": {
          id: "assistant-1",
          parent: "user-1",
          message: { id: "message-assistant-1", author: { role: "assistant" }, content: { content_type: "text", parts: ["Synthetic ChatGPT SDK assistant text."] } },
        },
      },
    }]));

    assert.equal(parsed.source, "chatgpt");
    assert.equal(parsed.chats[0].provider, "chatgpt");
    assert.deepEqual(parsed.chats[0].messages.map((message) => message.role), ["user", "assistant"]);
  });

  it("exposes OpenCode transcript parsing through the account facade", async () => {
    const client = new OpenMates({ apiKey: "sk-api-test", apiUrl: "http://127.0.0.1:9", deviceId: "sdk-opencode-test" });
    const parsed = await client.account.parseOpenCodeImport(JSON.stringify({
      info: { id: "ses_opencode_1", title: "Synthetic OpenCode SDK chat", time: { created: 1785000000000 } },
      messages: [{
        info: { id: "msg_user_1", role: "user", time: { created: 1785000001000 } },
        parts: [{ id: "part_user_1", type: "text", text: "Synthetic OpenCode SDK user text." }],
      }],
    }));

    assert.equal(parsed.source, "opencode");
    assert.equal(parsed.chats[0].provider, "opencode");
    assert.equal(parsed.chats[0].messages[0].content, "Synthetic OpenCode SDK user text.");
  });

  it("exposes strict generic parsing with explicit Gemini or Other identity", async () => {
    const client = new OpenMates({ apiKey: "sk-api-test", apiUrl: "http://127.0.0.1:9", deviceId: "sdk-generic-test" });
    const parsed = await client.account.parseGenericImport(JSON.stringify({
      messages: [{ role: "assistant", content: "Synthetic generic assistant text." }],
    }), "generic.json", "gemini");

    assert.equal(parsed.source, "gemini");
    assert.equal(parsed.parserFormat, "generic");
    assert.equal(parsed.chats[0].messages[0].imported_assistant_identity?.sender_name, "Gemini");
  });

  it("parses, previews, scans, encrypts, persists, and completes imports", async () => {
    const requests: Array<{ method?: string; url?: string; body?: Record<string, unknown> }> = [];
    const masterKeyB64 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
    const keyMaterial = await createApiKeyCryptoMaterial("SDK import test", masterKeyB64);
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      let raw = "";
      request.on("data", (chunk) => { raw += chunk.toString(); });
      request.on("end", () => {
        const body = raw ? JSON.parse(raw) as Record<string, unknown> : undefined;
        requests.push({ method: request.method, url: request.url, body });
        response.setHeader("content-type", "application/json");
        if (request.method === "POST" && request.url === "/v1/account-imports/preview") {
          response.end(JSON.stringify({ import_id: "import-1", default_selection_count: 1, max_batch_count: 1, can_import: true }));
          return;
        }
        if (request.method === "POST" && request.url === "/v1/account-imports/import-1/confirm") {
          response.end(JSON.stringify({ status: "confirmed" }));
          return;
        }
        if (request.method === "POST" && request.url === "/v1/account-imports/import-1/scan") {
          response.end(JSON.stringify({ batch_id: "scan-1", sequence: 0, status: "acknowledged", chats: body?.chats ?? [], failures: [] }));
          return;
        }
        if (request.method === "GET" && request.url === "/v1/account-imports/import-1/status") {
          response.end(JSON.stringify({ status: "processing", last_scan_sequence: 0, last_compression_sequence: -1 }));
          return;
        }
        if (request.method === "POST" && request.url === "/v1/account-imports/import-1/compress") {
          response.end(JSON.stringify({ batch_id: "compress-1", sequence: 0, status: "acknowledged", final_batch: true, usage: {} }));
          return;
        }
        if (request.method === "POST" && request.url === "/v1/sdk/session") {
          response.end(JSON.stringify({ key_wrapper: { encrypted_key: keyMaterial.encryptedMasterKey, salt: keyMaterial.saltB64, key_iv: keyMaterial.keyIv } }));
          return;
        }
        if (request.method === "POST" && request.url === "/v1/account-imports/import-1/persist-encrypted") {
          response.end(JSON.stringify({ status: "complete", imported_chat_ids: ["chat-imported-1"], encrypted_record_counts: { chats: 1, messages: 1 }, failures: [] }));
          return;
        }
        if (request.method === "POST" && request.url === "/v1/account-imports/import-1/complete") {
          response.end(JSON.stringify({ status: "complete", imported_count: 1, failures: [] }));
          return;
        }
        response.statusCode = 404;
        response.end(JSON.stringify({ detail: "not found" }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      const client = new OpenMates({ apiKey: keyMaterial.apiKey, apiUrl: `http://127.0.0.1:${address.port}`, deviceId: "sdk-import-test" });
      const parsed = await client.account.parseClaudeImport(Buffer.from(JSON.stringify([{ uuid: "chat-1", name: "SDK import", chat_messages: [{ uuid: "msg-1", sender: "human", text: "SDK plaintext message" }] }])));
      const result = await client.account.importChats(parsed);
      assert.equal(result.complete.status, "complete");
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }

    assert.deepEqual(requests.map((request) => `${request.method} ${request.url}`), [
      "POST /v1/account-imports/preview",
      "POST /v1/account-imports/import-1/confirm",
      "GET /v1/account-imports/import-1/status",
      "POST /v1/account-imports/import-1/scan",
      "POST /v1/account-imports/import-1/compress",
      "POST /v1/sdk/session",
      "POST /v1/account-imports/import-1/persist-encrypted",
      "POST /v1/account-imports/import-1/complete",
    ]);
    const previewBody = requests[0].body as Record<string, unknown>;
    assert.equal(previewBody.source, "claude");
    assert.equal(previewBody.chat_count, 1);
    const scanBody = requests[3].body as Record<string, unknown>;
    assert.equal(scanBody.batch_id, "scan-0");
    assert.equal(scanBody.sequence, 0);
    assert.equal(scanBody.final_batch, true);
    const persistBody = requests[6].body as { chats?: Array<Record<string, unknown>> };
    assert.equal(persistBody.chats?.length, 1);
    assert.equal(typeof persistBody.chats?.[0]?.encrypted_title, "string");
    assert.equal(String(persistBody.chats?.[0]?.encrypted_title).includes("SDK import"), false);
    const messages = persistBody.chats?.[0]?.messages as Array<Record<string, unknown>>;
    assert.equal(typeof messages[0].encrypted_content, "string");
    assert.equal(String(messages[0].encrypted_content).includes("SDK plaintext message"), false);
  });
});
