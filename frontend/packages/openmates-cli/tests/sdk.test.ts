/**
 * OpenMates npm SDK contract tests.
 *
 * Purpose: verify lazy API-key SDK behavior before product implementation.
 * Architecture: docs/specs/sdk-packages-v1/spec.yml.
 * Security: tests cover API-key unwrap vectors and non-persistent default chats.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/sdk.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

const { OpenMates } = await import("../src/sdk.ts");
const {
  createApiKeyCryptoMaterial,
  encryptBytesWithAesGcm,
  encryptWithAesGcmCombined,
  bytesToBase64,
  generateSalt,
} = await import("../src/crypto.ts");

async function withServer(
  handler: (request: IncomingMessage, response: ServerResponse) => void,
  run: (baseUrl: string) => Promise<void>,
): Promise<void> {
  const server = createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

describe("OpenMates SDK", () => {
  it("does not require connect before running a native app skill", async () => {
    await withServer((request, response) => {
      assert.equal(request.url, "/v1/apps/web/skills/search");
      assert.equal(request.headers.authorization, "Bearer sk-api-test");
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ success: true, data: { results: [{ title: "ok" }] } }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl });
      assert.equal("run" in client.apps, false);
      const result = await client.apps.web.search({
        requests: [{ query: "hello" }],
      });
      assert.deepEqual(result, { success: true, data: { results: [{ title: "ok" }] } });
    });
  });

  it("exposes native image generation skill methods", async () => {
    await withServer((request, response) => {
      assert.equal(request.url, "/v1/apps/images/skills/generate");
      let body = "";
      request.on("data", (chunk) => { body += chunk.toString(); });
      request.on("end", () => {
        assert.deepEqual(JSON.parse(body).input_data, {
          requests: [{ prompt: "a friendly robot" }],
        });
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, image: "ok" }));
      });
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl });
      const result = await client.apps.images.generate({
        requests: [{ prompt: "a friendly robot" }],
      });
      assert.deepEqual(result, { success: true, image: "ok" });
    });
  });

  it("defaults new chats to non-persistent mode", async () => {
    await withServer((request, response) => {
      assert.equal(request.url, "/v1/sdk/chats");
      let body = "";
      request.on("data", (chunk) => { body += chunk.toString(); });
      request.on("end", () => {
        assert.equal(JSON.parse(body).save_to_account, false);
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          persistent: false,
          response: {
            content: "hi",
            raw: { choices: [{ message: { role: "assistant", content: "hi" } }] },
          },
        }));
      });
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl });
      const response = await client.chats.send("hello");
      assert.equal(response.content, "hi");
    });
  });

  it("sends focus mode metadata with new chat messages", async () => {
    await withServer((request, response) => {
      assert.equal(request.url, "/v1/sdk/chats");
      let body = "";
      request.on("data", (chunk) => { body += chunk.toString(); });
      request.on("end", () => {
        assert.deepEqual(JSON.parse(body).focus_mode, {
          app_id: "web",
          focus_mode_id: "research",
        });
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          response: {
            content: "focused",
            raw: { choices: [{ message: { role: "assistant", content: "focused" } }] },
          },
        }));
      });
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl });
      const response = await client.chats.send("research this", {
        focusMode: { appId: "web", focusModeId: "research" },
      });
      assert.equal(response.content, "focused");
    });
  });

  it("lists latest encrypted account chats with a limit", async () => {
    await withServer((request, response) => {
      assert.equal(request.url, "/v1/sdk/chats?limit=3");
      assert.equal(request.method, "GET");
      assert.equal(request.headers.authorization, "Bearer sk-api-test");
      assert.equal(request.headers["x-openmates-sdk"], "npm");
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ chats: [{ id: "chat-1", encrypted_title: "ciphertext" }] }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl });
      const chats = await client.chats.list({ limit: 3 });
      assert.deepEqual(chats, [{ id: "chat-1", encrypted_title: "ciphertext" }]);
    });
  });

  it("lazily unwraps API-key session material and decrypts listed chat metadata", async () => {
    const masterKey = generateSalt(32);
    const chatKey = generateSalt(32);
    const material = await createApiKeyCryptoMaterial("SDK test key", bytesToBase64(masterKey));
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, masterKey);
    const encryptedTitle = await encryptWithAesGcmCombined("Decrypted SDK chat", chatKey);
    const encryptedSummary = await encryptWithAesGcmCombined("Encrypted summary", chatKey);
    const seenUrls: string[] = [];

    await withServer((request, response) => {
      seenUrls.push(`${request.method} ${request.url}`);
      assert.equal(request.headers.authorization, `Bearer ${material.apiKey}`);
      response.writeHead(200, { "content-type": "application/json" });
      if (request.url === "/v1/sdk/session") {
        response.end(JSON.stringify({
          key_wrapper: {
            encrypted_key: material.encryptedMasterKey,
            salt: material.saltB64,
            key_iv: material.keyIv,
          },
        }));
        return;
      }
      assert.equal(request.url, "/v1/sdk/chats?limit=1");
      response.end(JSON.stringify({
        chats: [{
          id: "chat-1",
          encrypted_chat_key: encryptedChatKey,
          encrypted_title: encryptedTitle,
          encrypted_chat_summary: encryptedSummary,
        }],
      }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: material.apiKey, apiUrl });
      const chats = await client.chats.list({ limit: 1 });
      assert.equal(chats[0].title, "Decrypted SDK chat");
      assert.equal(chats[0].chat_summary, "Encrypted summary");
      assert.equal(chats[0].encrypted_title, encryptedTitle);
    });

    assert.deepEqual(seenUrls, ["GET /v1/sdk/chats?limit=1", "POST /v1/sdk/session"]);
  });

  it("searches decrypted chat metadata locally without a server plaintext search endpoint", async () => {
    const masterKey = generateSalt(32);
    const madridChatKey = generateSalt(32);
    const berlinChatKey = generateSalt(32);
    const material = await createApiKeyCryptoMaterial("SDK search key", bytesToBase64(masterKey));
    const seenUrls: string[] = [];
    const chats = [
      {
        id: "chat-madrid",
        encrypted_chat_key: await encryptBytesWithAesGcm(madridChatKey, masterKey),
        encrypted_title: await encryptWithAesGcmCombined("Madrid itinerary", madridChatKey),
      },
      {
        id: "chat-berlin",
        encrypted_chat_key: await encryptBytesWithAesGcm(berlinChatKey, masterKey),
        encrypted_title: await encryptWithAesGcmCombined("Berlin itinerary", berlinChatKey),
      },
    ];

    await withServer((request, response) => {
      seenUrls.push(`${request.method} ${request.url}`);
      response.writeHead(200, { "content-type": "application/json" });
      if (request.url === "/v1/sdk/session") {
        response.end(JSON.stringify({
          key_wrapper: {
            encrypted_key: material.encryptedMasterKey,
            salt: material.saltB64,
            key_iv: material.keyIv,
          },
        }));
        return;
      }
      assert.equal(request.url, "/v1/sdk/chats?limit=0");
      response.end(JSON.stringify({ chats }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: material.apiKey, apiUrl });
      const results = await client.chats.search("Madrid");
      assert.deepEqual(results.map((chat) => chat.id), ["chat-madrid"]);
      assert.equal(results[0].title, "Madrid itinerary");
    });

    assert.deepEqual(seenUrls, ["GET /v1/sdk/chats?limit=0", "POST /v1/sdk/session"]);
  });

  it("loads a chat and decrypts encrypted messages client-side", async () => {
    const masterKey = generateSalt(32);
    const chatKey = generateSalt(32);
    const embedKey = generateSalt(32);
    const material = await createApiKeyCryptoMaterial("SDK load key", bytesToBase64(masterKey));
    const encryptedChatKey = await encryptBytesWithAesGcm(chatKey, masterKey);
    const encryptedTitle = await encryptWithAesGcmCombined("Loaded SDK chat", chatKey);
    const encryptedContent = await encryptWithAesGcmCombined("Hello from encrypted storage", chatKey);
    const encryptedSender = await encryptWithAesGcmCombined("OpenMates", chatKey);
    const encryptedEmbedKey = await encryptBytesWithAesGcm(embedKey, masterKey);
    const encryptedEmbedType = await encryptWithAesGcmCombined("math.calculate", embedKey);
    const encryptedEmbedContent = await encryptWithAesGcmCombined(JSON.stringify({ result: 4 }), embedKey);
    const encryptedEmbedPreview = await encryptWithAesGcmCombined("2 + 2 = 4", embedKey);
    const hashedEmbedId = createHash("sha256").update("embed-1").digest("hex");
    const seenUrls: string[] = [];

    await withServer((request, response) => {
      seenUrls.push(`${request.method} ${request.url}`);
      response.writeHead(200, { "content-type": "application/json" });
      if (request.url === "/v1/sdk/session") {
        response.end(JSON.stringify({
          key_wrapper: {
            encrypted_key: material.encryptedMasterKey,
            salt: material.saltB64,
            key_iv: material.keyIv,
          },
        }));
        return;
      }
      assert.equal(request.url, "/v1/sdk/chats/chat-1");
      response.end(JSON.stringify({
        chat: { id: "chat-1", encrypted_chat_key: encryptedChatKey, encrypted_title: encryptedTitle },
        messages: [{ id: "message-1", encrypted_content: encryptedContent, encrypted_sender_name: encryptedSender }],
        embeds: [{ embed_id: "embed-1", encrypted_type: encryptedEmbedType, encrypted_content: encryptedEmbedContent, encrypted_text_preview: encryptedEmbedPreview }],
        embed_keys: [{ hashed_embed_id: hashedEmbedId, key_type: "master", encrypted_embed_key: encryptedEmbedKey }],
      }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: material.apiKey, apiUrl });
      const loaded = await client.chats.load("chat-1") as { chat: { title?: string }; messages: Array<Record<string, unknown>>; embeds: Array<Record<string, unknown>> };
      assert.equal(loaded.chat.title, "Loaded SDK chat");
      assert.equal(loaded.messages[0].content, "Hello from encrypted storage");
      assert.equal(loaded.messages[0].senderName, "OpenMates");
      assert.equal(loaded.messages[0].encrypted_content, encryptedContent);
      assert.equal(loaded.embeds[0].type, "math.calculate");
      assert.deepEqual(loaded.embeds[0].content, { result: 4 });
      assert.equal(loaded.embeds[0].textPreview, "2 + 2 = 4");
    });

    assert.deepEqual(seenUrls, ["GET /v1/sdk/chats/chat-1", "POST /v1/sdk/session"]);
  });

  it("defaults chat listing to 10 and allows limit 0 for all chats", async () => {
    const urls: string[] = [];
    await withServer((request, response) => {
      urls.push(request.url ?? "");
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ chats: [] }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl });
      await client.chats.list();
      await client.chats.list({ limit: 0 });
      assert.deepEqual(urls, ["/v1/sdk/chats?limit=10", "/v1/sdk/chats?limit=0"]);
    });
  });

  it("exposes named CLI parity namespaces without generic passthroughs", async () => {
    const requests: Array<{ method?: string; url?: string }> = [];
    await withServer((request, response) => {
      requests.push({ method: request.method, url: request.url });
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: true, suggestions: ["next"] }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl });

      assert.equal("run" in client.apps, false);
      assert.equal("newsletter" in client, false);
      assert.equal("setEmail" in client.notifications, false);
      assert.equal("setBackupReminder" in client.notifications, false);
      assert.equal("stream" in client.notifications, false);
      await client.account.info();
      await client.account.setTimezone("Europe/Berlin");
      await client.chats.search("Madrid", { limit: 5 });
      await client.chats.load("chat-1");
      await client.settings.setDarkMode(true);
      await client.billing.listInvoices();
      await client.docs.search("sdk");
      await client.embeds.versions("embed-1");
      await client.notifications.list({ limit: 2 });
      await client.reminders.list();
      await client.learningMode.status();
      await client.learningMode.enable({ ageGroup: "16_18", passcode: "teach-1234" });
      await client.learningMode.disable("teach-1234");
      await client.inspirations.list({ language: "de" });
      await client.newChatSuggestions.list({ limit: 4 });
    });

    assert.deepEqual(requests, [
      { method: "GET", url: "/v1/sdk/account" },
      { method: "POST", url: "/v1/sdk/account/timezone" },
      { method: "GET", url: "/v1/sdk/chats?limit=0" },
      { method: "GET", url: "/v1/sdk/chats/chat-1" },
      { method: "POST", url: "/v1/sdk/settings/dark-mode" },
      { method: "GET", url: "/v1/sdk/billing/invoices" },
      { method: "GET", url: "/v1/sdk/docs/search?q=sdk" },
      { method: "GET", url: "/v1/sdk/embeds/embed-1/versions" },
      { method: "GET", url: "/v1/sdk/notifications?limit=2" },
      { method: "GET", url: "/v1/sdk/reminders" },
      { method: "GET", url: "/v1/sdk/learning-mode" },
      { method: "POST", url: "/v1/sdk/learning-mode/enable" },
      { method: "POST", url: "/v1/sdk/learning-mode/disable" },
      { method: "GET", url: "/v1/sdk/inspirations?lang=de" },
      { method: "GET", url: "/v1/sdk/new-chat-suggestions?limit=4" },
    ]);
  });

  it("routes previously blocked SDK parity surfaces to concrete SDK endpoints", async () => {
    const requests: Array<{ method?: string; url?: string }> = [];
    await withServer((request, response) => {
      requests.push({ method: request.method, url: request.url });
      response.writeHead(200, { "content-type": "application/json" });
      if (request.url === "/v1/sdk/chats/chat-1") {
        response.end(JSON.stringify({ chat: { id: "chat-1" }, messages: [] }));
        return;
      }
      response.end(JSON.stringify({ ok: true, memories: [], suggestions: [], embed_keys: [] }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl });

      await client.chats.followUps("chat-1");
      await client.chats.export("chat-1");
      await client.account.listInterests();
      await client.memories.types({ query: { app_id: "code" } });
      await client.billing.usageExport();
      await client.billing.createBankTransferOrder(110000);
      await client.embeds.show("embed-1");
      await assert.rejects(() => client.connectedAccounts.import({ payload: "invalid", passcode: "123456" }), /must start with OMCA1/);
      await client.feedback.assistantResponse({ rating: 5 });
      await client.benchmark.estimate({ suite: "quick" });
      await assert.rejects(() => client.settings.shareDebugLogs({ confirmed: true }), /not available through the API-key SDK yet/);
    });

    assert.deepEqual(requests, [
      { method: "GET", url: "/v1/sdk/chats/chat-1" },
      { method: "GET", url: "/v1/sdk/chats/chat-1" },
      { method: "POST", url: "/v1/sdk/chats/chat-1/export" },
      { method: "GET", url: "/v1/sdk/account/topic-preferences" },
      { method: "GET", url: "/v1/sdk/memories/types?app_id=code" },
      { method: "GET", url: "/v1/sdk/billing/usage/export" },
      { method: "POST", url: "/v1/sdk/billing/bank-transfer-orders" },
      { method: "GET", url: "/v1/sdk/embeds/embed-1" },
      { method: "POST", url: "/v1/sdk/feedback/assistant-response" },
      { method: "POST", url: "/v1/sdk/benchmark/estimate" },
    ]);
  });

  it("requires explicit confirmation for destructive SDK operations", async () => {
    const client = new OpenMates({ apiKey: "sk-api-test", apiUrl: "http://127.0.0.1" });

    await assert.rejects(
      () => client.chats.delete("chat-1", {}),
      /requires confirmed: true/,
    );
    await assert.rejects(
      () => client.memories.delete("memory-1", {}),
      /requires confirmed: true/,
    );
    await assert.rejects(
      () => client.embeds.restoreVersion("embed-1", 1, {}),
      /requires confirmed: true/,
    );
  });
});
