/** IdeaBucket CLI and npm SDK parity contract tests. */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { WebSocket } from "ws";

const require = createRequire(import.meta.url);
const { WebSocketServer } = require("ws");
const {
  bytesToBase64,
  createApiKeyCryptoMaterial,
  decryptBytesWithAesGcm,
  decryptWithAesGcmCombined,
  encryptWithAesGcmCombined,
} = await import("../src/crypto.ts");

describe("IdeaBucket CLI client", () => {
  it("captures text as encrypted draft plus cache-only processing metadata", async () => {
    const originalHome = process.env.HOME;
    const home = mkdtempSync(join(tmpdir(), "openmates-ideabucket-"));
    const state = join(home, ".openmates");
    mkdirSync(state, { recursive: true });
    process.env.HOME = home;
    const seen: Array<{ type: string; payload: Record<string, unknown> }> = [];
    const server = createServer((request, response) => {
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-token" }));
        return;
      }
      if (request.url?.startsWith("/v1/settings/export-account-data")) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ data: { app_settings_memories: [] } }));
        return;
      }
      response.writeHead(404).end();
    });
    const wss = new WebSocketServer({ server });
    wss.on("connection", (socket: WebSocket) => {
      socket.on("message", (raw: Buffer) => {
        const frame = JSON.parse(raw.toString());
        seen.push(frame);
        if (frame.type === "update_draft") {
          socket.send(JSON.stringify({
            type: "draft_update_receipt",
            payload: { chat_id: frame.payload.chat_id, draft_v: 7, success: true },
          }));
        }
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    const apiUrl = `http://127.0.0.1:${address.port}`;
    writeFileSync(join(state, "session.json"), JSON.stringify({
      apiUrl,
      sessionId: "session-1",
      wsToken: "token",
      cookies: { auth_refresh_token: "refresh" },
      masterKeyExportedB64: Buffer.alloc(32).toString("base64"),
      hashedEmail: "hashed-email",
      userEmailSalt: "salt",
      createdAt: Date.now(),
      authorizerDeviceName: "test",
      autoLogoutMinutes: null,
    }));

    try {
      const { OpenMatesClient } = await import(`../src/client.ts?ideabucket=${Date.now()}`);
      const client = OpenMatesClient.load({ apiUrl });
      const result = await client.addIdeaBucketText({
        text: "ship the menu bar MVP",
        bucketId: "2026-07-18",
        scheduledSendAt: 1_784_332_800,
      });

      assert.equal(result.processingPayloadSynced, true);
      assert.equal(result.bucketId, "2026-07-18");
      assert.equal(result.draftV, 7);
      assert.match(result.markdown, /----- Idea 1 -----/);
      assert.match(result.markdown, /ship the menu bar MVP/);

      const update = seen.find((frame) => frame.type === "update_draft");
      assert.ok(update);
      assert.equal(update.payload.ideabucket, true);
      assert.equal(update.payload.ideabucket_processing_window_id, "2026-07-18");
      assert.equal(update.payload.scheduled_send_at, 1_784_332_800);
      assert.equal(typeof update.payload.encrypted_chat_key, "string");
      assert.equal(typeof update.payload.server_vault_encrypted_processing_payload, "string");
      assert.equal(typeof update.payload.client_encrypted_future_user_message, "string");
      assert.equal(typeof update.payload.client_encrypted_ideabucket_system_event, "string");
      assert.equal(JSON.stringify(update.payload).includes("ship the menu bar MVP"), false);
      const chatKey = await decryptBytesWithAesGcm(String(update.payload.encrypted_chat_key), Buffer.alloc(32));
      assert.ok(chatKey);
      assert.match(
        String(await decryptWithAesGcmCombined(String(update.payload.client_encrypted_future_user_message), chatKey)),
        /ship the menu bar MVP/,
      );
    } finally {
      process.env.HOME = originalHome;
      wss.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("uses encrypted account settings as IdeaBucket add defaults", async () => {
    const originalHome = process.env.HOME;
    const home = mkdtempSync(join(tmpdir(), "openmates-ideabucket-settings-"));
    const state = join(home, ".openmates");
    mkdirSync(state, { recursive: true });
    process.env.HOME = home;
    const seen: Array<{ type: string; payload: Record<string, unknown> }> = [];
    const masterKey = Buffer.alloc(32);
    const encryptedSettings = await encryptWithAesGcmCombined(JSON.stringify({
      processing_prompt: "Account prompt for captured ideas",
      processing_times: "09:00,17:00",
    }), masterKey);
    const server = createServer((request, response) => {
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-token" }));
        return;
      }
      if (request.url?.startsWith("/v1/settings/export-account-data")) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          data: {
            app_settings_memories: [{
              id: "settings-entry-1",
              app_id: "ideabucket",
              item_type: "processing_settings",
              item_key: "hash",
              item_version: 3,
              created_at: 1,
              updated_at: 2,
              encrypted_item_json: encryptedSettings,
            }],
          },
        }));
        return;
      }
      response.writeHead(404).end();
    });
    const wss = new WebSocketServer({ server });
    wss.on("connection", (socket: WebSocket) => {
      socket.on("message", (raw: Buffer) => {
        const frame = JSON.parse(raw.toString());
        seen.push(frame);
        if (frame.type === "update_draft") {
          socket.send(JSON.stringify({
            type: "draft_update_receipt",
            payload: { chat_id: frame.payload.chat_id, draft_v: 9, success: true },
          }));
        }
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    const apiUrl = `http://127.0.0.1:${address.port}`;
    writeFileSync(join(state, "session.json"), JSON.stringify({
      apiUrl,
      sessionId: "session-1",
      wsToken: "token",
      cookies: { auth_refresh_token: "refresh" },
      masterKeyExportedB64: masterKey.toString("base64"),
      hashedEmail: "hashed-email",
      userEmailSalt: "salt",
      createdAt: Date.now(),
      authorizerDeviceName: "test",
      autoLogoutMinutes: null,
    }));

    try {
      const { OpenMatesClient } = await import(`../src/client.ts?ideabucket-settings=${Date.now()}`);
      const client = OpenMatesClient.load({ apiUrl });
      const result = await client.addIdeaBucketText({ text: "use settings", bucketId: "settings-bucket" });

      assert.equal(result.draftV, 9);
      assert.match(result.markdown, /Account prompt for captured ideas/);
      const update = seen.find((frame) => frame.type === "update_draft");
      assert.ok(update);
      assert.equal(JSON.stringify(update.payload).includes("Account prompt for captured ideas"), false);
      const serverPayload = JSON.parse(String(await decryptWithAesGcmCombined(String(update.payload.server_vault_encrypted_processing_payload), masterKey)));
      assert.equal(serverPayload.prompt, "Account prompt for captured ideas");
      assert.equal(typeof update.payload.scheduled_send_at, "number");
    } finally {
      process.env.HOME = originalHome;
      wss.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("stores audio embeds before syncing the encrypted bucket draft", async () => {
    const originalHome = process.env.HOME;
    const home = mkdtempSync(join(tmpdir(), "openmates-ideabucket-audio-"));
    const state = join(home, ".openmates");
    mkdirSync(state, { recursive: true });
    process.env.HOME = home;
    const seen: Array<{ type: string; payload: Record<string, unknown> }> = [];
    const server = createServer((request, response) => {
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-token", user: { id: "user-1" } }));
        return;
      }
      if (request.url?.startsWith("/v1/settings/export-account-data")) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ data: { app_settings_memories: [] } }));
        return;
      }
      response.writeHead(404).end();
    });
    const wss = new WebSocketServer({ server });
    wss.on("connection", (socket: WebSocket) => {
      socket.on("message", (raw: Buffer) => {
        const frame = JSON.parse(raw.toString());
        seen.push(frame);
        if (frame.type === "store_embed") {
          socket.send(JSON.stringify({
            type: "store_embed_confirmed",
            payload: { request_id: frame.payload.request_id, embed_id: frame.payload.embed_id },
          }));
        }
        if (frame.type === "store_embed_keys") {
          socket.send(JSON.stringify({
            type: "store_embed_keys_confirmed",
            payload: { request_id: frame.payload.request_id, created_count: frame.payload.keys.length, failed_count: 0 },
          }));
        }
        if (frame.type === "update_draft") {
          socket.send(JSON.stringify({
            type: "draft_update_receipt",
            payload: { chat_id: frame.payload.chat_id, draft_v: 8, success: true },
          }));
        }
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");
    const apiUrl = `http://127.0.0.1:${address.port}`;
    writeFileSync(join(state, "session.json"), JSON.stringify({
      apiUrl,
      sessionId: "session-1",
      wsToken: "token",
      cookies: { auth_refresh_token: "refresh" },
      masterKeyExportedB64: Buffer.alloc(32).toString("base64"),
      hashedEmail: "hashed-email",
      userEmailSalt: "salt",
      createdAt: Date.now(),
      authorizerDeviceName: "test",
      autoLogoutMinutes: null,
    }));

    try {
      const { OpenMatesClient } = await import(`../src/client.ts?ideabucket-audio=${Date.now()}`);
      const client = OpenMatesClient.load({ apiUrl });
      const result = await client["addIdeaBucketPreparedIdeas"]({
        chatId: "11111111-1111-4111-8111-111111111111",
        bucketId: "2026-07-18-audio",
        scheduledSendAt: 1_784_332_860,
        preparedEmbeds: [{
          embedId: "22222222-2222-4222-8222-222222222222",
          embedRef: "voice-note-ref",
          type: "audio-recording",
          content: "type: audio-recording\nstatus: finished\nfilename: note.m4a",
          textPreview: "note.m4a",
          status: "finished",
          contentHash: "audio-hash",
        }],
        ideas: [{
          content: "Audio: note.m4a\n[!](embed:voice-note-ref)\nTranscript: ship audio capture",
          preview: "ship audio capture",
          payload: { type: "audio", filename: "note.m4a", embed_ref: "voice-note-ref", transcript: "ship audio capture" },
        }],
      });

      assert.equal(result.draftV, 8);
      assert.match(result.markdown, /\[!\]\(embed:voice-note-ref\)/);
      const storeEmbed = seen.find((frame) => frame.type === "store_embed");
      const storeKeys = seen.find((frame) => frame.type === "store_embed_keys");
      const updateDraft = seen.find((frame) => frame.type === "update_draft");
      assert.ok(storeEmbed);
      assert.ok(storeKeys);
      assert.ok(updateDraft);
      assert.equal(storeEmbed.payload.embed_id, "22222222-2222-4222-8222-222222222222");
      assert.equal(storeEmbed.payload.status, "finished");
      assert.equal(JSON.stringify(storeEmbed.payload).includes("ship audio capture"), false);
      assert.equal(JSON.stringify(updateDraft.payload).includes("ship audio capture"), false);
      assert.equal(updateDraft.payload.ideabucket_processing_window_id, "2026-07-18-audio");
      assert.equal(typeof updateDraft.payload.encrypted_chat_key, "string");
      assert.equal(Array.isArray(storeKeys.payload.keys), true);
      assert.equal((storeKeys.payload.keys as unknown[]).length, 1);
    } finally {
      process.env.HOME = originalHome;
      wss.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      rmSync(home, { recursive: true, force: true });
    }
  });
});

describe("IdeaBucket npm SDK", () => {
  it("uses existing OpenMates package REST methods", async () => {
    const requests: Array<{ method?: string; url?: string; body: string }> = [];
    const material = await createApiKeyCryptoMaterial("IdeaBucket SDK Test", bytesToBase64(Buffer.alloc(32)));
    const apiKey = material.apiKey;
    const encryptedSettings = await encryptWithAesGcmCombined(JSON.stringify({
      processing_prompt: "NPM account prompt",
      processing_times: "09:00,17:00",
    }), Buffer.alloc(32));
    const server = createServer((request, response) => {
      let body = "";
      request.on("data", (chunk) => { body += chunk.toString(); });
      request.on("end", () => {
        requests.push({ method: request.method, url: request.url, body });
        response.writeHead(200, { "content-type": "application/json" });
        if (request.method === "GET" && request.url === "/v1/sdk/memories?app_id=ideabucket&item_type=processing_settings") {
          response.end(JSON.stringify({ memories: [{
            id: "settings-entry-1",
            app_id: "ideabucket",
            item_type: "processing_settings",
            item_version: 2,
            encrypted_item_json: encryptedSettings,
          }] }));
        } else if (request.method === "POST" && request.url === "/v1/sdk/session") {
          response.end(JSON.stringify({ key_wrapper: { encrypted_key: material.encryptedMasterKey, salt: material.saltB64, key_iv: material.keyIv } }));
        } else if (request.method === "POST" && request.url === "/v1/sdk/ideabucket/buckets/2026-07-18/add") {
          response.end(JSON.stringify({ processing_window_id: "2026-07-18", status: "draft_synced" }));
        } else if (request.method === "GET" && request.url === "/v1/sdk/ideabucket/buckets/2026-07-18") {
          response.end(JSON.stringify({ processing_window_id: "2026-07-18", status: "pending" }));
        } else if (request.method === "POST" && request.url === "/v1/sdk/ideabucket/buckets/2026-07-18/process") {
          response.end(JSON.stringify({ processing_window_id: "2026-07-18", status: "sent" }));
        } else {
          response.end(JSON.stringify({ buckets: [] }));
        }
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address === "object");

    try {
      const { OpenMates } = await import(`../src/sdk.ts?ideabucket=${Date.now()}`);
      const client = new OpenMates({ apiKey, apiUrl: `http://127.0.0.1:${address.port}` });
      assert.equal((await client.ideabucket.add({ text: "ship", bucketId: "2026-07-18" })).status, "draft_synced");
      assert.equal((await client.ideabucket.status("2026-07-18")).status, "pending");
      assert.equal((await client.ideabucket.process("2026-07-18", { now: true })).status, "sent");
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }

    assert.deepEqual(requests.map(({ method, url }) => ({ method, url })), [
      { method: "GET", url: "/v1/sdk/memories?app_id=ideabucket&item_type=processing_settings" },
      { method: "POST", url: "/v1/sdk/session" },
      { method: "POST", url: "/v1/sdk/ideabucket/buckets/2026-07-18/add" },
      { method: "GET", url: "/v1/sdk/ideabucket/buckets/2026-07-18" },
      { method: "POST", url: "/v1/sdk/ideabucket/buckets/2026-07-18/process" },
    ]);
    assert.equal(requests[2].body.includes("ship"), false);
    assert.equal(requests[2].body.includes("NPM account prompt"), false);
    const addPayload = JSON.parse(requests[2].body);
    assert.equal(addPayload.ideabucket_processing_window_id, "2026-07-18");
    assert.equal(typeof addPayload.encrypted_draft_md, "string");
    assert.equal(typeof addPayload.encrypted_chat_key, "string");
    const serverPayload = JSON.parse(String(await decryptWithAesGcmCombined(addPayload.server_vault_encrypted_processing_payload, Buffer.alloc(32))));
    assert.equal(serverPayload.prompt, "NPM account prompt");
    const chatKey = await decryptBytesWithAesGcm(addPayload.encrypted_chat_key, Buffer.alloc(32));
    assert.ok(chatKey);
    assert.match(
      String(await decryptWithAesGcmCombined(addPayload.client_encrypted_future_user_message, chatKey)),
      /ship/,
    );
    assert.deepEqual(JSON.parse(requests[4].body), { now: true });
  });
});
