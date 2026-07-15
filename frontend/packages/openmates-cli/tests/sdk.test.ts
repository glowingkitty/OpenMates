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
import { encode as toonEncode } from "@toon-format/toon";
import { createHash } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const { OpenMates } = await import("../src/sdk.ts");
const {
  createApiKeyCryptoMaterial,
  encryptBytesWithAesGcm,
  encryptWithAesGcmCombined,
  bytesToBase64,
  sealChatCompletionRecoveryPayload,
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
  it("uses an injected opaque device id without deriving it from the platform", async () => {
    await withServer((request, response) => {
      assert.equal(request.headers["x-openmates-device-identity"], "managed-device-id");
      response.end(JSON.stringify({ success: true }));
    }, async (apiUrl) => {
      await new OpenMates({ apiKey: "sk-api-test", apiUrl, deviceId: "managed-device-id" }).account.info();
    });
  });

  it("persists one opaque device id per installation path", async () => {
    const deviceIdPath = join(mkdtempSync(join(tmpdir(), "openmates-sdk-")), "device-id");
    const seen: string[] = [];
    await withServer((request, response) => {
      seen.push(String(request.headers["x-openmates-device-identity"]));
      response.end(JSON.stringify({ success: true }));
    }, async (apiUrl) => {
      await new OpenMates({ apiKey: "first-key", apiUrl, deviceIdPath }).account.info();
      await new OpenMates({ apiKey: "second-key", apiUrl, deviceIdPath }).account.info();
    });
    assert.equal(seen[0], seen[1]);
    assert.equal(seen[0], readFileSync(deviceIdPath, "utf8").trim());
    assert.equal(readFileSync(deviceIdPath, "utf8").includes("first-key"), false);
  });

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
        response.setHeader("content-type", "application/json");
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

  it("does not expose disabled models3d generation skill methods by default", () => {
    const client = new OpenMates({ apiKey: "sk-api-test", apiUrl: "https://api.example.test" });
    assert.equal(typeof client.apps.models3d.search, "function");
    assert.equal((client.apps.models3d as unknown as Record<string, unknown>).generate, undefined);
  });

  it("exposes native models3d search skill methods", async () => {
    await withServer((request, response) => {
      assert.equal(request.url, "/v1/apps/models3d/skills/search");
      let body = "";
      request.on("data", (chunk) => { body += chunk.toString(); });
      request.on("end", () => {
        assert.deepEqual(JSON.parse(body).input_data, {
          requests: [{ query: "benchy" }],
        });
        response.setHeader("content-type", "application/json");
        response.end(JSON.stringify({ success: true, data: { result_count: 1 } }));
      });
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl });
      const result = await client.apps.models3d.search({
        requests: [{ query: "benchy" }],
      });
      assert.deepEqual(result, { success: true, data: { result_count: 1 } });
    });
  });

  it("defaults new chats to non-persistent mode", async () => {
    await withServer((request, response) => {
      assert.equal(request.url, "/v1/sdk/chats");
      let body = "";
      request.on("data", (chunk) => { body += chunk.toString(); });
      request.on("end", () => {
        assert.equal(JSON.parse(body).save_to_account, false);
        response.setHeader("content-type", "application/json");
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

  it("preflights saved chats with epoch-1 encrypted recovery material", async () => {
    const masterKey = generateSalt(32);
    const material = await createApiKeyCryptoMaterial("Saved chat test", bytesToBase64(masterKey));
    const apiKey = material.apiKey;
    const requests: Array<{ url?: string; body: Record<string, unknown>; authorization?: string }> = [];
    const taskId = "77777777-7777-4777-8777-777777777777";
    const jobId = "88888888-8888-4888-8888-888888888888";
    let claimCount = 0;

    await withServer((request, response) => {
      let body = "";
      request.on("data", (chunk) => { body += chunk.toString(); });
      request.on("end", async () => {
        const parsed = JSON.parse(body) as Record<string, unknown>;
        requests.push({ url: request.url, body: parsed, authorization: request.headers.authorization });
        response.setHeader("content-type", "application/json");
        if (request.url === "/v1/sdk/session") {
          response.end(JSON.stringify({
            user: { id: "11111111-1111-4111-8111-111111111111" },
            key_wrapper: {
              encrypted_key: material.encryptedMasterKey,
              salt: material.saltB64,
              key_iv: material.keyIv,
            },
          }));
          return;
        }
        if (request.url === "/v1/sdk/chats") {
          response.end(JSON.stringify({
            persistent: true,
            chat_id: parsed.chat_id,
            preflight: { state: "ENQUEUED" },
            task_id: taskId,
          }));
          return;
        }
        if (request.url === `/v1/sdk/chats/recovery/${taskId}/claim`) {
          claimCount += 1;
          if (claimCount === 1) {
            response.statusCode = 404;
            response.end(JSON.stringify({ detail: { error: "recovery_job_not_found" } }));
            return;
          }
          const saved = requests.find((entry) => entry.url === "/v1/sdk/chats")!.body;
          const assistantMessageId = taskId;
          const plaintext = JSON.stringify({
            assistant_message_id: assistantMessageId,
            category: "general",
            chat_id: saved.chat_id,
            content: "saved reply",
            job_id: jobId,
            key_version: 1,
            model_name: "test-model",
            turn_id: saved.turn_id,
          });
          const envelope = await sealChatCompletionRecoveryPayload(
            new TextEncoder().encode(plaintext),
            {
              recoveryPublicKey: String(saved.recovery_public_key),
              ownerId: "11111111-1111-4111-8111-111111111111",
              chatId: String(saved.chat_id),
              turnId: String(saved.turn_id),
              jobId,
              assistantMessageId,
              keyVersion: 1,
            },
          );
          response.end(JSON.stringify({
            job_id: jobId,
            state: "LEASED",
            lease_token: "lease-token",
            lease_generation: 1,
            sealed_payload: JSON.stringify(envelope),
            chat_id: saved.chat_id,
            turn_id: saved.turn_id,
            assistant_message_id: assistantMessageId,
            chat_key_version: 1,
          }));
          return;
        }
        assert.equal(request.url, `/v1/sdk/chats/recovery/${taskId}/persist`);
        assert.equal(JSON.stringify(parsed).includes("saved reply"), false);
        assert.equal(parsed.expected_messages_v, 1);
        assert.equal(typeof (parsed.encrypted_assistant_message as Record<string, unknown>).encrypted_content, "string");
        response.end(JSON.stringify({ job_id: jobId, state: "TERMINAL", committed_messages_v: 2 }));
      });
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey, apiUrl });
      const result = await client.chats.send("save this", {
        saveToAccount: true,
        title: "Saved SDK chat",
        recoveryPollIntervalMs: 1,
      });
      assert.equal(result.content, "saved reply");
    });

    assert.deepEqual(requests.map((request) => request.url), [
      "/v1/sdk/session",
      "/v1/sdk/chats",
      `/v1/sdk/chats/recovery/${taskId}/claim`,
      `/v1/sdk/chats/recovery/${taskId}/claim`,
      `/v1/sdk/chats/recovery/${taskId}/persist`,
    ]);
    assert.ok(requests.every((request) => request.authorization === `Bearer ${apiKey}`));
    const saved = requests[1].body;
    assert.equal(saved.save_to_account, true);
    assert.equal(saved.protocol_version, 1);
    assert.match(String(saved.chat_id), /^[0-9a-f-]{36}$/);
    assert.match(String(saved.turn_id), /^[0-9a-f-]{36}$/);
    assert.match(String(saved.message_id), /^[0-9a-f-]{36}$/);
    assert.equal(saved.chat_key_version, 1);
    assert.equal(typeof saved.encrypted_chat_key, "string");
    assert.match(String(saved.recovery_public_key), /^[A-Za-z0-9_-]{43}$/);
    assert.equal("chat_key" in saved, false);
    assert.equal("master_key" in saved, false);
    assert.equal(typeof (saved.encrypted_user_message as Record<string, unknown>).encrypted_content, "string");
    assert.equal(typeof (saved.encrypted_chat_metadata as Record<string, unknown>).encrypted_title, "string");
  });

  it("times out clearly while a saved recovery job is unavailable", async () => {
    const masterKey = generateSalt(32);
    const material = await createApiKeyCryptoMaterial("Saved timeout test", bytesToBase64(masterKey));
    await withServer((request, response) => {
      request.resume();
      request.on("end", () => {
        response.setHeader("content-type", "application/json");
        if (request.url === "/v1/sdk/session") {
          response.end(JSON.stringify({
            user: { id: "11111111-1111-4111-8111-111111111111" },
            key_wrapper: {
              encrypted_key: material.encryptedMasterKey,
              salt: material.saltB64,
              key_iv: material.keyIv,
            },
          }));
          return;
        }
        if (request.url === "/v1/sdk/chats") {
          response.end(JSON.stringify({ task_id: "77777777-7777-4777-8777-777777777777" }));
          return;
        }
        response.statusCode = 404;
        response.end(JSON.stringify({ detail: { error: "recovery_job_not_found" } }));
      });
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: material.apiKey, apiUrl });
      await assert.rejects(
        () => client.chats.send("save this", {
          saveToAccount: true,
          recoveryPollIntervalMs: 1,
          recoveryTimeoutMs: 5,
        }),
        /Timed out waiting for saved chat recovery/,
      );
    });
  });

  it("rejects nonpositive and unbounded recovery poll intervals", async () => {
    const client = new OpenMates({ apiKey: "sk-api-test", deviceId: "test-device" });
    for (const recoveryPollIntervalMs of [0, -1, Number.POSITIVE_INFINITY]) {
      await assert.rejects(
        () => (client.chats as unknown as { pollRecoveryClaim: (id: string, timeout: number, interval: number) => Promise<unknown> })
          .pollRecoveryClaim("task", 10, recoveryPollIntervalMs),
        /finite and positive/,
      );
    }
  });

  it("fails saved chats before send when SDK key material is unavailable", async () => {
    const urls: string[] = [];
    await withServer((request, response) => {
      urls.push(request.url ?? "");
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ key_wrapper: {} }));
    }, async (apiUrl) => {
      const client = new OpenMates({ apiKey: "sk-api-test", apiUrl });
      await assert.rejects(
        () => client.chats.send("save this", { saveToAccount: true }),
        /API-key-wrapped master key material/,
      );
    });
    assert.deepEqual(urls, ["/v1/sdk/session"]);
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
    const encryptedToonEmbedType = await encryptWithAesGcmCombined("code", embedKey);
    const encryptedToonEmbedContent = await encryptWithAesGcmCombined(toonEncode({ code: "export default function App() {}", file_path: "src/App.jsx" }), embedKey);
    const encryptedToonEmbedPreview = await encryptWithAesGcmCombined("src/App.jsx", embedKey);
    const hashedToonEmbedId = createHash("sha256").update("embed-2").digest("hex");
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
        embeds: [
          { embed_id: "embed-1", encrypted_type: encryptedEmbedType, encrypted_content: encryptedEmbedContent, encrypted_text_preview: encryptedEmbedPreview },
          { embed_id: "embed-2", encrypted_type: encryptedToonEmbedType, encrypted_content: encryptedToonEmbedContent, encrypted_text_preview: encryptedToonEmbedPreview },
        ],
        embed_keys: [
          { hashed_embed_id: hashedEmbedId, key_type: "master", encrypted_embed_key: encryptedEmbedKey },
          { hashed_embed_id: hashedToonEmbedId, key_type: "master", encrypted_embed_key: encryptedEmbedKey },
        ],
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
      assert.equal(loaded.embeds[1].type, "code");
      assert.deepEqual(loaded.embeds[1].content, { code: "export default function App() {}", file_path: "src/App.jsx" });
      assert.equal(loaded.embeds[1].textPreview, "src/App.jsx");
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
