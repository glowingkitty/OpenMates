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
const { bytesToBase64, createApiKeyCryptoMaterial } = await import("../src/crypto.ts");

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
      assert.equal(typeof update.payload.server_vault_encrypted_processing_payload, "string");
      assert.equal(typeof update.payload.client_encrypted_future_user_message, "string");
      assert.equal(typeof update.payload.client_encrypted_ideabucket_system_event, "string");
      assert.equal(JSON.stringify(update.payload).includes("ship the menu bar MVP"), false);
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
    const server = createServer((request, response) => {
      let body = "";
      request.on("data", (chunk) => { body += chunk.toString(); });
      request.on("end", () => {
        requests.push({ method: request.method, url: request.url, body });
        response.writeHead(200, { "content-type": "application/json" });
        if (request.method === "POST" && request.url === "/v1/sdk/session") {
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
      { method: "POST", url: "/v1/sdk/session" },
      { method: "POST", url: "/v1/sdk/ideabucket/buckets/2026-07-18/add" },
      { method: "GET", url: "/v1/sdk/ideabucket/buckets/2026-07-18" },
      { method: "POST", url: "/v1/sdk/ideabucket/buckets/2026-07-18/process" },
    ]);
    assert.equal(requests[1].body.includes("ship"), false);
    assert.equal(JSON.parse(requests[1].body).ideabucket_processing_window_id, "2026-07-18");
    assert.equal(typeof JSON.parse(requests[1].body).encrypted_draft_md, "string");
    assert.deepEqual(JSON.parse(requests[3].body), { now: true });
  });
});
