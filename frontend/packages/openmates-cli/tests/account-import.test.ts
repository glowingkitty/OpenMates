/**
 * Account Import V1 CLI contract tests.
 *
 * Purpose: verify local parser normalization and REST client calls for import
 * preview, scan, and complete endpoints before CLI command wiring is finished.
 * Security: fixtures are synthetic and use a fake local HTTP server only.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/account-import.test.ts
 */

import { after, describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import JSZip from "jszip";

const originalHome = process.env.HOME;
const tempHome = mkdtempSync(join(tmpdir(), "openmates-account-import-"));
process.env.HOME = tempHome;
mkdirSync(join(tempHome, ".openmates"), { recursive: true, mode: 0o700 });

const { OpenMatesClient } = await import("../src/client.ts");
const { parseClaudeImportBuffer, parseChatGPTImportBuffer, parseOpenMatesImportBuffer } = await import("../src/accountImport.ts");

after(() => {
  if (originalHome === undefined) delete process.env.HOME;
  else process.env.HOME = originalHome;
  rmSync(tempHome, { recursive: true, force: true });
});

function writeSession(apiUrl: string): void {
  writeFileSync(join(tempHome, ".openmates", "session.json"), JSON.stringify({
    apiUrl,
    sessionId: "session-1",
    wsToken: "ws-token",
    cookies: { auth_refresh_token: "refresh-token" },
    masterKeyExportedB64: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    hashedEmail: "hashed-email",
    userEmailSalt: "email-salt",
    createdAt: Date.now(),
  }));
}

describe("account import parser", () => {
  it("normalizes synthetic Claude JSON exports without plaintext fingerprints", async () => {
    const parsed = await parseClaudeImportBuffer(Buffer.from(JSON.stringify([
      {
        uuid: "claude-chat-1",
        name: "Synthetic Claude chat",
        chat_messages: [
          { uuid: "message-1", sender: "human", text: "Synthetic user text." },
          { uuid: "message-2", sender: "assistant", content: [{ type: "text", text: "Synthetic assistant text." }] },
        ],
      },
    ])), "conversations.json");

    assert.equal(parsed.source, "claude");
    assert.equal(parsed.chats.length, 1);
    assert.equal(parsed.chats[0].messages[0].role, "user");
    assert.equal(parsed.chats[0].messages[1].role, "assistant");
    assert.ok(parsed.chats[0].source_fingerprint);
    assert.equal(parsed.chats[0].source_fingerprint.includes("Synthetic"), false);
  });

  it("discovers OpenMates V1 chat files and skipped domains", async () => {
    const zip = new JSZip();
    zip.file("manifest.yml", "format: openmates-account-export\nversion: 1\ndomains:\n  chats:\n    count: 1\n  projects:\n    count: 1\n");
    zip.file("chats/chat-1.yml", "id: chat-1\ntitle: Synthetic chat\n");
    const parsed = await parseOpenMatesImportBuffer(await zip.generateAsync({ type: "nodebuffer" }), "openmates.zip");

    assert.equal(parsed.source, "openmates");
    assert.equal(parsed.chats[0].source_chat_id, "chat-1");
    assert.deepEqual(parsed.skippedDomains, ["projects"]);
  });

  it("normalizes synthetic ChatGPT nested ZIP exports from the active path", async () => {
    const zip = new JSZip();
    zip.file("ChatGPT Export/conversations.json", JSON.stringify([{
      id: "chatgpt-chat-1",
      conversation_id: "chatgpt-conversation-1",
      title: "Synthetic ChatGPT chat",
      current_node: "assistant-1",
      mapping: {
        root: { id: "root", message: null, parent: null },
        "user-1": {
          id: "user-1",
          parent: "root",
          message: {
            id: "message-user-1",
            author: { role: "user" },
            create_time: 1785000001,
            content: { content_type: "multimodal_text", parts: ["Synthetic ChatGPT user text.", { asset_pointer: "file-service://redacted" }] },
          },
        },
        "assistant-1": {
          id: "assistant-1",
          parent: "user-1",
          message: {
            id: "message-assistant-1",
            author: { role: "assistant" },
            create_time: 1785000002,
            content: { content_type: "text", parts: ["Synthetic ChatGPT assistant text."] },
          },
        },
        branch: {
          id: "branch",
          parent: "user-1",
          message: { id: "message-branch", author: { role: "assistant" }, content: { content_type: "text", parts: ["This branch must not import."] } },
        },
      },
    }]));
    const parsed = await parseChatGPTImportBuffer(await zip.generateAsync({ type: "nodebuffer" }), "chatgpt.zip");

    assert.equal(parsed.source, "chatgpt");
    assert.equal(parsed.chats[0].provider, "chatgpt");
    assert.deepEqual(parsed.chats[0].messages.map((message) => message.role), ["user", "assistant"]);
    assert.equal(parsed.chats[0].messages[0].content, "Synthetic ChatGPT user text.");
    assert.deepEqual(parsed.chats[0].messages[0].provider_metadata, { content_type: "multimodal_text", asset_count: 1 });
    assert.equal(JSON.stringify(parsed).includes("This branch must not import"), false);
    assert.equal(parsed.chats[0].source_fingerprint.includes("Synthetic"), false);
  });
});

describe("account import client", () => {
  it("previews, scans, and completes imports through /v1/account-imports", async () => {
    const requests: Array<{ method?: string; url?: string; body?: Record<string, unknown> }> = [];
    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
      let raw = "";
      request.on("data", (chunk) => { raw += chunk.toString(); });
      request.on("end", () => {
        requests.push({ method: request.method, url: request.url, body: raw ? JSON.parse(raw) as Record<string, unknown> : undefined });
        response.setHeader("content-type", "application/json");
        if (request.method === "POST" && request.url === "/v1/account-imports/preview") {
          response.end(JSON.stringify({ default_selection_count: 1, max_batch_count: 1, can_import: true }));
          return;
        }
        if (request.method === "POST" && request.url === "/v1/account-imports/import-1/scan") {
          response.end(JSON.stringify({ chats: [], credits_reserved: 1, messages_blocked: [], failures: [] }));
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
      const apiUrl = `http://127.0.0.1:${address.port}`;
      writeSession(apiUrl);
      const client = OpenMatesClient.load({ apiUrl });
      await client.previewAccountImport({ source: "claude", chatCount: 1, sourceFingerprints: ["fingerprint-1"] });
      await client.scanAccountImport("import-1", [{ source_fingerprint: "fingerprint-1", messages: [] }]);
      await client.persistEncryptedAccountImport("import-1", [{
        provider: "claude",
        source_chat_id: "claude-chat-1",
        source_fingerprint: "fingerprint-1",
        title: "Synthetic imported chat",
        created_at: "2026-07-18T00:00:00Z",
        updated_at: "2026-07-18T00:00:01Z",
        messages: [{ role: "user", content: "Synthetic plaintext encrypted locally.", provider_metadata: {} }],
        embeds: [],
        uploads: [],
        provider_labels: ["claude"],
        source_metadata: {},
      }]);
      await client.completeAccountImport("import-1", {
        importedChatIds: ["chat-1"],
        sourceFingerprints: ["fingerprint-1"],
        encryptedRecordCounts: { chats: 1, messages: 2 },
      });
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }

    assert.deepEqual(requests.map((request) => `${request.method} ${request.url}`), [
      "POST /v1/account-imports/preview",
      "POST /v1/account-imports/import-1/scan",
      "POST /v1/account-imports/import-1/persist-encrypted",
      "POST /v1/account-imports/import-1/complete",
    ]);
    assert.deepEqual(requests[0].body, {
      source: "claude",
      chat_count: 1,
      source_fingerprints: ["fingerprint-1"],
      estimated_tokens: 0,
      estimated_bytes: 0,
    });
    const persistBody = requests[2].body as { chats?: Array<Record<string, unknown>> };
    assert.equal(persistBody.chats?.length, 1);
    assert.equal(typeof persistBody.chats?.[0]?.encrypted_title, "string");
    assert.notEqual(String(persistBody.chats?.[0]?.encrypted_title), "Synthetic imported chat");
    const persistedMessages = persistBody.chats?.[0]?.messages as Array<Record<string, unknown>>;
    assert.equal(typeof persistedMessages[0].encrypted_content, "string");
    assert.notEqual(String(persistedMessages[0].encrypted_content), "Synthetic plaintext encrypted locally.");
    assert.deepEqual(requests[3].body, {
      imported_chat_ids: ["chat-1"],
      source_fingerprints: ["fingerprint-1"],
      encrypted_record_counts: { chats: 1, messages: 2 },
      client_failures: [],
    });
  });
});
