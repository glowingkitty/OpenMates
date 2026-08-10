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
const { buildAccountImportMessageBatches, parseClaudeImportBuffer, parseChatGPTImportBuffer, parseGenericImportBuffer, parseOpenCodeImportBuffer, parseOpenMatesImportBuffer } = await import("../src/accountImport.ts");

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

  it("keeps selected presentation source independent from the parser format", async () => {
    const parsed = await parseClaudeImportBuffer(Buffer.from(JSON.stringify([{
      uuid: "claude-shaped-chat-1",
      chat_messages: [{ uuid: "assistant-1", sender: "assistant", text: "Synthetic assistant text." }],
    }])), "renamed.json", "gemini");

    assert.equal(parsed.source, "gemini");
    assert.equal(parsed.parserFormat, "claude");
    assert.equal(parsed.chats[0].selected_source, "gemini");
    assert.equal(parsed.chats[0].parser_format, "claude");
    assert.deepEqual(parsed.chats[0].messages[0].imported_assistant_identity, {
      category: "gemini",
      sender_name: "Gemini",
      model_name: "Gemini",
      avatar_key: "gemini",
    });
  });

  it("strictly parses generic role/content JSON for Gemini and Other", async () => {
    const parsed = await parseGenericImportBuffer(Buffer.from(JSON.stringify({
      title: "Synthetic generic chat",
      messages: [
        { role: "user", content: "Synthetic user text." },
        { role: "assistant", content: "Synthetic assistant text." },
      ],
    })), "generic.json", "other");

    assert.equal(parsed.source, "other");
    assert.equal(parsed.parserFormat, "generic");
    assert.equal(parsed.chats[0].messages[0].imported_assistant_identity, null);
    assert.deepEqual(parsed.chats[0].messages[1].imported_assistant_identity, {
      category: "other",
      sender_name: "AI assistant",
      model_name: "Other",
      avatar_key: "ai-star",
    });
    await assert.rejects(
      parseGenericImportBuffer(Buffer.from(JSON.stringify({ messages: [{ author: "user", text: "ambiguous" }] })), "generic.json", "gemini"),
      /role.*content/i,
    );
    await assert.rejects(
      parseGenericImportBuffer(Buffer.from(JSON.stringify({ conversations: [] })), "takeout.json", "gemini"),
      /generic role\/content/i,
    );
    for (const ambiguous of [
      { messages: [{ role: "user", content: "text", tool_calls: [] }] },
      { messages: [{ role: "assistant", content: "text", reasoning: "hidden" }] },
      { messages: [{ role: "user", content: "text", attachments: [] }] },
      { messages: [{ role: "user", content: "text", arbitrary: true }] },
      { messages: [{ role: "user", content: "text" }], mapping: {} },
      { messages: [{ role: "user", content: "text" }], unknown: true },
    ]) {
      await assert.rejects(
        parseGenericImportBuffer(Buffer.from(JSON.stringify(ambiguous)), "generic.json", "other"),
        /unknown|unsupported|role\/content/i,
      );
    }
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

  it("normalizes OpenCode CLI transcript exports as one chat", async () => {
    const parsed = await parseOpenCodeImportBuffer(Buffer.from(JSON.stringify({
      info: {
        id: "ses_opencode_1",
        title: "Synthetic OpenCode session",
        time: { created: 1785000000000, updated: 1785000010000 },
      },
      messages: [
        {
          info: { id: "msg_user_1", role: "user", time: { created: 1785000001000 } },
          parts: [
            { id: "part_user", type: "text", text: "Synthetic OpenCode user text." },
            { id: "part_file", type: "file", filename: "notes.txt", mime: "text/plain", url: "data:text/plain;base64,cHJpdmF0ZQ==" },
          ],
        },
        {
          info: { id: "msg_assistant_1", role: "assistant", time: { created: 1785000002000 } },
          parts: [
            { id: "part_reasoning", type: "reasoning", text: "Private reasoning must not import." },
            { id: "part_assistant", type: "text", text: "Synthetic OpenCode assistant text." },
            { id: "part_tool", type: "tool", state: { status: "completed", output: "Tool output must not import." } },
          ],
        },
      ],
    })), "opencode-session.json");

    assert.equal(parsed.source, "opencode");
    assert.equal(parsed.chats[0].provider, "opencode");
    assert.equal(parsed.chats[0].source_chat_id, "ses_opencode_1");
    assert.deepEqual(parsed.chats[0].messages.map((message) => message.content), [
      "Synthetic OpenCode user text.",
      "Synthetic OpenCode assistant text.",
    ]);
    assert.equal(JSON.stringify(parsed).includes("Private reasoning must not import."), false);
    assert.equal(JSON.stringify(parsed).includes("Tool output must not import."), false);
    assert.equal(JSON.stringify(parsed).includes("cHJpdmF0ZQ=="), false);
  });

  it("splits arbitrarily long chats into stable bounded message batches", async () => {
    const parsed = await parseGenericImportBuffer(Buffer.from(JSON.stringify({
      id: "long-generic-chat",
      messages: Array.from({ length: 501 }, (_, index) => ({ role: "user", content: `Synthetic message ${index}` })),
    })), "generic.json", "other");
    const batches = buildAccountImportMessageBatches(parsed.chats);

    assert.deepEqual(batches.map((batch) => batch.chat.messages.length), [250, 250, 1]);
    assert.deepEqual(batches.map((batch) => batch.chunkIndex), [0, 1, 2]);
    assert.equal(new Set(batches.map((batch) => batch.batchId)).size, 3);
    assert.deepEqual(buildAccountImportMessageBatches(parsed.chats).map((batch) => batch.batchId), batches.map((batch) => batch.batchId));
  });
});

describe("account import client", () => {
  it("previews, confirms, scans, compresses, persists, and completes resumable imports", async () => {
    const requests: Array<{ method?: string; url?: string; body?: Record<string, unknown> }> = [];
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
          response.end(JSON.stringify({ batch_id: "compress-1", sequence: 0, status: "acknowledged", summary: "Synthetic summary", final_batch: true, usage: {} }));
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
      await client.previewAccountImport({ source: "gemini", parserFormat: "generic", chatCount: 1, sourceFingerprints: ["fingerprint-1"], estimatedTokensByChat: [10] });
      await client.confirmAccountImport("import-1", ["fingerprint-1"]);
      await client.scanAccountImport("import-1", { batchId: "scan-1", sequence: 0, finalBatch: true, chats: [{ source_fingerprint: "fingerprint-1", messages: [] }] });
      await client.getAccountImportStatus("import-1");
      await client.compressAccountImport("import-1", { batchId: "compress-1", sequence: 0, finalBatch: true, scanSequence: 0, sourceFingerprint: "fingerprint-1", sanitizedMessages: [], priorSummary: "Prior synthetic summary" });
      await client.persistEncryptedAccountImport("import-1", [{
        provider: "gemini",
        parser_format: "generic",
        selected_source: "gemini",
        source_chat_id: "claude-chat-1",
        source_fingerprint: "fingerprint-1",
        title: "Synthetic imported chat",
        created_at: "2026-07-18T00:00:00Z",
        updated_at: "2026-07-18T00:00:01Z",
        messages: [{ role: "assistant", content: "Synthetic plaintext encrypted locally.", provider_metadata: {}, imported_assistant_identity: { category: "gemini", sender_name: "Gemini", model_name: "Gemini", avatar_key: "gemini" } }],
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
      "POST /v1/account-imports/import-1/confirm",
      "POST /v1/account-imports/import-1/scan",
      "GET /v1/account-imports/import-1/status",
      "POST /v1/account-imports/import-1/compress",
      "POST /v1/account-imports/import-1/persist-encrypted",
      "POST /v1/account-imports/import-1/complete",
    ]);
    assert.deepEqual(requests[0].body, {
      source: "gemini",
      parser_format: "generic",
      chat_count: 1,
      source_fingerprints: ["fingerprint-1"],
      estimated_tokens: 0,
      estimated_tokens_by_chat: [10],
      estimated_bytes: 0,
    });
    assert.deepEqual(requests[1].body, { selected_fingerprints: ["fingerprint-1"] });
    assert.deepEqual(requests[2].body, { batch_id: "scan-1", sequence: 0, final_batch: true, chats: [{ source_fingerprint: "fingerprint-1", messages: [] }] });
    assert.deepEqual(requests[4].body, {
      batch_id: "compress-1",
      sequence: 0,
      final_batch: true,
      scan_sequence: 0,
      source_fingerprint: "fingerprint-1",
      sanitized_messages: [],
      prior_summary: "Prior synthetic summary",
    });
    const persistBody = requests[5].body as { chats?: Array<Record<string, unknown>> };
    assert.equal(persistBody.chats?.length, 1);
    assert.equal(typeof persistBody.chats?.[0]?.encrypted_title, "string");
    assert.notEqual(String(persistBody.chats?.[0]?.encrypted_title), "Synthetic imported chat");
    const persistedMessages = persistBody.chats?.[0]?.messages as Array<Record<string, unknown>>;
    assert.equal(typeof persistedMessages[0].encrypted_content, "string");
    assert.notEqual(String(persistedMessages[0].encrypted_content), "Synthetic plaintext encrypted locally.");
    assert.equal(typeof persistedMessages[0].encrypted_category, "string");
    assert.equal(typeof persistedMessages[0].encrypted_sender_name, "string");
    assert.equal(typeof persistedMessages[0].encrypted_model_name, "string");
    assert.deepEqual(requests[6].body, {
      imported_chat_ids: ["chat-1"],
      source_fingerprints: ["fingerprint-1"],
      encrypted_record_counts: { chats: 1, messages: 2 },
      client_failures: [],
    });
  });
});
