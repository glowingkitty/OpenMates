/**
 * CLI encrypted draft lifecycle contracts.
 *
 * The paired CLI uses the existing WebSocket protocol and stores ciphertext
 * only. Authoritative reconciliation must never treat a partial omission as a
 * deletion.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import type { Socket } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { WebSocket } from "ws";

const { reconcileAuthoritativeChats } = await import("../src/client.ts");
const require = createRequire(import.meta.url);
const { WebSocketServer } = require("ws");

describe("CLI draft reconciliation", () => {
  it("preserves partial omissions and removes only explicit authoritative deletions", () => {
    const chats = [
      { details: { id: "kept" }, messages: [] },
      { details: { id: "omitted" }, messages: [] },
      { details: { id: "deleted" }, messages: [] },
    ];

    assert.deepEqual(
      reconcileAuthoritativeChats(chats, { authoritative: false }),
      chats,
    );
    assert.deepEqual(
      reconcileAuthoritativeChats(chats, {
        authoritative: false,
        deleted_chat_ids: ["deleted"],
      }).map((chat: { details: { id: string } }) => chat.details.id),
      ["kept", "omitted"],
    );
    assert.deepEqual(
      reconcileAuthoritativeChats(chats, {
        authoritative: true,
        authoritative_chat_ids: ["kept", "omitted"],
        deleted_chat_ids: ["deleted"],
      }).map((chat: { details: { id: string } }) => chat.details.id),
      ["kept", "omitted"],
    );
  });

  it("runs create, list, get, version sync, and clear through encrypted WebSocket frames", async () => {
    const originalHome = process.env.HOME;
    const home = mkdtempSync(join(tmpdir(), "openmates-drafts-"));
    const state = join(home, ".openmates");
    mkdirSync(state, { recursive: true });
    process.env.HOME = home;
    const seen: Array<{ type: string; payload: Record<string, unknown> }> = [];
    const seenHttp: Array<{ method?: string; url?: string }> = [];
    let storedDraft: { chatId: string; encryptedDraftMd: string; encryptedDraftPreview: string | null; draftV: number } | null = null;
    const server = createServer((request, response) => {
      seenHttp.push({ method: request.method, url: request.url });
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-token" }));
        return;
      }
      if (request.url === `/v1/drafts/${storedDraft?.chatId}`) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          draft: {
            chat_id: storedDraft.chatId,
            encrypted_draft_md: storedDraft.encryptedDraftMd,
            encrypted_draft_preview: storedDraft.encryptedDraftPreview,
            draft_v: storedDraft.draftV,
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
          storedDraft = {
            chatId: String(frame.payload.chat_id),
            encryptedDraftMd: String(frame.payload.encrypted_draft_md),
            encryptedDraftPreview: typeof frame.payload.encrypted_draft_preview === "string"
              ? String(frame.payload.encrypted_draft_preview)
              : null,
            draftV: 1,
          };
          socket.send(JSON.stringify({
            type: "draft_update_receipt",
            payload: { chat_id: frame.payload.chat_id, draft_v: 1, success: true },
          }));
        } else if (frame.type === "get_draft_versions") {
          socket.send(JSON.stringify({
            type: "draft_versions_response",
            payload: { versions: { [frame.payload.chats[0].chat_id]: 1 } },
          }));
        } else if (frame.type === "delete_draft") {
          socket.send(JSON.stringify({
            type: "draft_delete_receipt",
            payload: { chat_id: frame.payload.chat_id, success: true },
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
      const { OpenMatesClient } = await import(`../src/client.ts?draft-test=${Date.now()}`);
      const client = OpenMatesClient.load({ apiUrl });
      const created = await client.saveDraft({ markdown: "private draft", preview: "private preview" });
      assert.equal((await client.listDrafts()).length, 1);
      assert.equal((await client.getDraft(created.chatId))?.markdown, "private draft");
      assert.equal((await client.getDraft(created.chatId, true))?.markdown, "private draft");
      assert.deepEqual(await client.reconcileDraftVersions(), { [created.chatId]: 1 });
      await client.clearDraft(created.chatId);

      const update = seen.find((frame) => frame.type === "update_draft");
      assert.ok(update);
      assert.equal(JSON.stringify(update.payload).includes("private draft"), false);
      assert.deepEqual(seen.map((frame) => frame.type), [
        "update_draft",
        "get_draft_versions",
        "delete_draft",
      ]);
      assert.equal(
        seenHttp.some((request) => request.method === "GET" && request.url === `/v1/drafts/${created.chatId}`),
        true,
      );
    } finally {
      process.env.HOME = originalHome;
      wss.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("clears cached drafts when REST returns null", async () => {
    const originalHome = process.env.HOME;
    const home = mkdtempSync(join(tmpdir(), "openmates-drafts-rest-null-"));
    const state = join(home, ".openmates");
    mkdirSync(state, { recursive: true });
    process.env.HOME = home;
    const seen: Array<{ type: string; payload: Record<string, unknown> }> = [];
    let storedDraft: { chatId: string; encryptedDraftMd: string; encryptedDraftPreview: string | null; draftV: number } | null = null;
    const server = createServer((request, response) => {
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-token" }));
        return;
      }
      if (request.url === `/v1/drafts/${storedDraft?.chatId}`) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ draft: null }));
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
          storedDraft = {
            chatId: String(frame.payload.chat_id),
            encryptedDraftMd: String(frame.payload.encrypted_draft_md),
            encryptedDraftPreview: typeof frame.payload.encrypted_draft_preview === "string"
              ? String(frame.payload.encrypted_draft_preview)
              : null,
            draftV: 1,
          };
          socket.send(JSON.stringify({
            type: "draft_update_receipt",
            payload: { chat_id: frame.payload.chat_id, draft_v: 1, success: true },
          }));
          return;
        }
        if (frame.type === "phased_sync_request") {
          socket.send(JSON.stringify({
            type: "phase_2_last_20_chats_ready",
            payload: {
              chats: storedDraft ? [{
                chat_details: {
                  id: storedDraft.chatId,
                  encrypted_draft_md: storedDraft.encryptedDraftMd,
                  encrypted_draft_preview: storedDraft.encryptedDraftPreview,
                  draft_v: storedDraft.draftV,
                  messages_v: 0,
                  title_v: 0,
                },
              }] : [],
              total_chat_count: storedDraft ? 1 : 0,
            },
          }));
          socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
          return;
        }
        if (frame.type === "get_draft_versions") {
          socket.send(JSON.stringify({
            type: "draft_versions_response",
            payload: { versions: { [frame.payload.chats[0].chat_id]: 0 } },
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
      const { OpenMatesClient } = await import(`../src/client.ts?draft-rest-null-test=${Date.now()}`);
      const client = OpenMatesClient.load({ apiUrl });
      const created = await client.saveDraft({ markdown: "private draft", preview: "private preview" });
      assert.equal(await client.getDraft(created.chatId, true), null);
      assert.equal(await client.getDraft(created.chatId), null);
      assert.deepEqual(seen.map((frame) => frame.type), ["update_draft"]);
    } finally {
      process.env.HOME = originalHome;
      wss.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("does not resurrect stale cached drafts when REST returns null", async () => {
    const originalHome = process.env.HOME;
    const home = mkdtempSync(join(tmpdir(), "openmates-drafts-stale-cache-"));
    const state = join(home, ".openmates");
    mkdirSync(state, { recursive: true });
    process.env.HOME = home;
    const seen: Array<{ type: string; payload: Record<string, unknown> }> = [];
    let storedDraft: { chatId: string; encryptedDraftMd: string; encryptedDraftPreview: string | null; draftV: number } | null = null;
    const server = createServer((request, response) => {
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-token" }));
        return;
      }
      if (request.url === `/v1/drafts/${storedDraft?.chatId}`) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ draft: null }));
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
          storedDraft = {
            chatId: String(frame.payload.chat_id),
            encryptedDraftMd: String(frame.payload.encrypted_draft_md),
            encryptedDraftPreview: typeof frame.payload.encrypted_draft_preview === "string"
              ? String(frame.payload.encrypted_draft_preview)
              : null,
            draftV: 1,
          };
          socket.send(JSON.stringify({
            type: "draft_update_receipt",
            payload: { chat_id: frame.payload.chat_id, draft_v: 1, success: true },
          }));
          return;
        }
        if (frame.type === "phased_sync_request") {
          socket.send(JSON.stringify({
            type: "phase_2_last_20_chats_ready",
            payload: {
              chats: storedDraft ? [{
                chat_details: {
                  id: storedDraft.chatId,
                  encrypted_draft_md: storedDraft.encryptedDraftMd,
                  encrypted_draft_preview: storedDraft.encryptedDraftPreview,
                  draft_v: storedDraft.draftV,
                  messages_v: 0,
                  title_v: 0,
                },
              }] : [],
              total_chat_count: storedDraft ? 1 : 0,
            },
          }));
          socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
          return;
        }
        if (frame.type === "get_draft_versions") {
          const chatId = frame.payload.chats?.[0]?.chat_id ?? storedDraft?.chatId;
          socket.send(JSON.stringify({
            type: "draft_versions_response",
            payload: { versions: chatId ? { [chatId]: 2 } : {} },
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
      const { OpenMatesClient } = await import(`../src/client.ts?draft-stale-cache-test=${Date.now()}`);
      const client = OpenMatesClient.load({ apiUrl });
      const created = await client.saveDraft({ markdown: "old draft", preview: "old draft" });
      const masterKey = Buffer.alloc(32);
      storedDraft = {
        chatId: created.chatId,
        encryptedDraftMd: await (await import("../src/crypto.ts")).encryptWithAesGcmCombined("new draft", masterKey),
        encryptedDraftPreview: await (await import("../src/crypto.ts")).encryptWithAesGcmCombined("new draft", masterKey),
        draftV: 2,
      };

      const refreshed = await client.getDraft(created.chatId, true);

      assert.equal(refreshed, null);
      assert.equal(await client.getDraft(created.chatId), null);
      assert.deepEqual(seen.map((frame) => frame.type), ["update_draft"]);
    } finally {
      process.env.HOME = originalHome;
      wss.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("uses targeted sync when REST refresh fails before a response", async () => {
    const originalHome = process.env.HOME;
    const home = mkdtempSync(join(tmpdir(), "openmates-drafts-rest-failed-"));
    const state = join(home, ".openmates");
    mkdirSync(state, { recursive: true });
    process.env.HOME = home;
    const seen: Array<{ type: string; payload: Record<string, unknown> }> = [];
    let storedDraft: { chatId: string; encryptedDraftMd: string; encryptedDraftPreview: string | null; draftV: number } | null = null;
    const server = createServer((request, response) => {
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-token" }));
        return;
      }
      if (request.url === `/v1/drafts/${storedDraft?.chatId}`) {
        request.socket.destroy();
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
          storedDraft = {
            chatId: String(frame.payload.chat_id),
            encryptedDraftMd: String(frame.payload.encrypted_draft_md),
            encryptedDraftPreview: typeof frame.payload.encrypted_draft_preview === "string"
              ? String(frame.payload.encrypted_draft_preview)
              : null,
            draftV: 1,
          };
          socket.send(JSON.stringify({
            type: "draft_update_receipt",
            payload: { chat_id: frame.payload.chat_id, draft_v: 1, success: true },
          }));
          return;
        }
        if (frame.type === "phased_sync_request") {
          socket.send(JSON.stringify({
            type: "phase_2_last_20_chats_ready",
            payload: {
              chats: storedDraft ? [{
                chat_details: {
                  id: storedDraft.chatId,
                  encrypted_draft_md: storedDraft.encryptedDraftMd,
                  encrypted_draft_preview: storedDraft.encryptedDraftPreview,
                  draft_v: storedDraft.draftV,
                  messages_v: 0,
                  title_v: 0,
                },
              }] : [],
              total_chat_count: storedDraft ? 1 : 0,
            },
          }));
          socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
          return;
        }
        if (frame.type === "get_draft_versions") {
          const chatId = frame.payload.chats?.[0]?.chat_id ?? storedDraft?.chatId;
          socket.send(JSON.stringify({
            type: "draft_versions_response",
            payload: { versions: chatId ? { [chatId]: 2 } : {} },
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
      const { OpenMatesClient } = await import(`../src/client.ts?draft-rest-failed-test=${Date.now()}`);
      const client = OpenMatesClient.load({ apiUrl });
      const created = await client.saveDraft({ markdown: "old draft", preview: "old draft" });
      const masterKey = Buffer.alloc(32);
      storedDraft = {
        chatId: created.chatId,
        encryptedDraftMd: await (await import("../src/crypto.ts")).encryptWithAesGcmCombined("new draft", masterKey),
        encryptedDraftPreview: await (await import("../src/crypto.ts")).encryptWithAesGcmCombined("new draft", masterKey),
        draftV: 2,
      };

      const refreshed = await client.getDraft(created.chatId, true);

      assert.equal(refreshed?.markdown, "new draft");
      assert.equal(refreshed?.draftV, 2);
      assert.deepEqual(seen.map((frame) => frame.type), ["update_draft", "get_draft_versions", "phased_sync_request", "get_draft_versions"]);
      assert.deepEqual(seen[2]?.payload.refresh_chat_ids, [created.chatId]);
    } finally {
      process.env.HOME = originalHome;
      wss.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("uses targeted sync when REST refresh stalls", async () => {
    const originalHome = process.env.HOME;
    const originalTimeout = process.env.OPENMATES_CLI_HTTP_TIMEOUT_MS;
    const home = mkdtempSync(join(tmpdir(), "openmates-drafts-rest-stalled-"));
    const state = join(home, ".openmates");
    mkdirSync(state, { recursive: true });
    process.env.HOME = home;
    process.env.OPENMATES_CLI_HTTP_TIMEOUT_MS = "25";
    const stalledSockets = new Set<Socket>();
    const seen: Array<{ type: string; payload: Record<string, unknown> }> = [];
    let storedDraft: { chatId: string; encryptedDraftMd: string; encryptedDraftPreview: string | null; draftV: number } | null = null;
    const server = createServer((request, response) => {
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-token" }));
        return;
      }
      if (request.url === `/v1/drafts/${storedDraft?.chatId}`) {
        stalledSockets.add(request.socket);
        response.writeHead(200, { "content-type": "application/json" });
        response.write(" ");
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
          storedDraft = {
            chatId: String(frame.payload.chat_id),
            encryptedDraftMd: String(frame.payload.encrypted_draft_md),
            encryptedDraftPreview: typeof frame.payload.encrypted_draft_preview === "string"
              ? String(frame.payload.encrypted_draft_preview)
              : null,
            draftV: 1,
          };
          socket.send(JSON.stringify({
            type: "draft_update_receipt",
            payload: { chat_id: frame.payload.chat_id, draft_v: 1, success: true },
          }));
          return;
        }
        if (frame.type === "phased_sync_request") {
          socket.send(JSON.stringify({
            type: "phase_2_last_20_chats_ready",
            payload: {
              chats: storedDraft ? [{
                chat_details: {
                  id: storedDraft.chatId,
                  encrypted_draft_md: storedDraft.encryptedDraftMd,
                  encrypted_draft_preview: storedDraft.encryptedDraftPreview,
                  draft_v: storedDraft.draftV,
                  messages_v: 0,
                  title_v: 0,
                },
              }] : [],
              total_chat_count: storedDraft ? 1 : 0,
            },
          }));
          socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
          return;
        }
        if (frame.type === "get_draft_versions") {
          const chatId = frame.payload.chats?.[0]?.chat_id ?? storedDraft?.chatId;
          socket.send(JSON.stringify({
            type: "draft_versions_response",
            payload: { versions: chatId ? { [chatId]: 2 } : {} },
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
      const { OpenMatesClient } = await import(`../src/client.ts?draft-rest-stalled-test=${Date.now()}`);
      const client = OpenMatesClient.load({ apiUrl });
      const created = await client.saveDraft({ markdown: "old draft", preview: "old draft" });
      const masterKey = Buffer.alloc(32);
      storedDraft = {
        chatId: created.chatId,
        encryptedDraftMd: await (await import("../src/crypto.ts")).encryptWithAesGcmCombined("new draft", masterKey),
        encryptedDraftPreview: await (await import("../src/crypto.ts")).encryptWithAesGcmCombined("new draft", masterKey),
        draftV: 2,
      };

      const refreshed = await client.getDraft(created.chatId, true);

      assert.equal(refreshed?.markdown, "new draft");
      assert.equal(refreshed?.draftV, 2);
      assert.deepEqual(seen.map((frame) => frame.type), ["update_draft", "get_draft_versions", "phased_sync_request", "get_draft_versions"]);
    } finally {
      process.env.HOME = originalHome;
      if (originalTimeout === undefined) {
        delete process.env.OPENMATES_CLI_HTTP_TIMEOUT_MS;
      } else {
        process.env.OPENMATES_CLI_HTTP_TIMEOUT_MS = originalTimeout;
      }
      for (const socket of stalledSockets) socket.destroy();
      wss.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("clears stale cached drafts when REST refresh fails and versions report deletion", async () => {
    const originalHome = process.env.HOME;
    const home = mkdtempSync(join(tmpdir(), "openmates-drafts-rest-failed-delete-"));
    const state = join(home, ".openmates");
    mkdirSync(state, { recursive: true });
    process.env.HOME = home;
    const seen: Array<{ type: string; payload: Record<string, unknown> }> = [];
    let storedDraft: { chatId: string; encryptedDraftMd: string; encryptedDraftPreview: string | null; draftV: number } | null = null;
    const server = createServer((request, response) => {
      if (request.url === "/v1/auth/session") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ success: true, ws_token: "fresh-token" }));
        return;
      }
      if (request.url === `/v1/drafts/${storedDraft?.chatId}`) {
        request.socket.destroy();
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
          storedDraft = {
            chatId: String(frame.payload.chat_id),
            encryptedDraftMd: String(frame.payload.encrypted_draft_md),
            encryptedDraftPreview: typeof frame.payload.encrypted_draft_preview === "string"
              ? String(frame.payload.encrypted_draft_preview)
              : null,
            draftV: 1,
          };
          socket.send(JSON.stringify({
            type: "draft_update_receipt",
            payload: { chat_id: frame.payload.chat_id, draft_v: 1, success: true },
          }));
          return;
        }
        if (frame.type === "phased_sync_request") {
          socket.send(JSON.stringify({
            type: "phase_2_last_20_chats_ready",
            payload: {
              chats: storedDraft ? [{
                chat_details: {
                  id: storedDraft.chatId,
                  encrypted_draft_md: storedDraft.encryptedDraftMd,
                  encrypted_draft_preview: storedDraft.encryptedDraftPreview,
                  draft_v: storedDraft.draftV,
                  messages_v: 0,
                  title_v: 0,
                },
              }] : [],
              total_chat_count: storedDraft ? 1 : 0,
            },
          }));
          socket.send(JSON.stringify({ type: "phased_sync_complete", payload: {} }));
          return;
        }
        if (frame.type === "get_draft_versions") {
          const chatId = frame.payload.chats?.[0]?.chat_id ?? storedDraft?.chatId;
          socket.send(JSON.stringify({
            type: "draft_versions_response",
            payload: { versions: chatId ? { [chatId]: 0 } : {} },
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
      const { OpenMatesClient } = await import(`../src/client.ts?draft-rest-failed-delete-test=${Date.now()}`);
      const client = OpenMatesClient.load({ apiUrl });
      const created = await client.saveDraft({ markdown: "old draft", preview: "old draft" });

      const refreshed = await client.getDraft(created.chatId, true);
      const refreshedAgain = await client.getDraft(created.chatId, true);

      assert.equal(refreshed, null);
      assert.equal(refreshedAgain, null);
      assert.equal(await client.getDraft(created.chatId), null);
      assert.deepEqual(seen.map((frame) => frame.type), ["update_draft", "get_draft_versions", "get_draft_versions"]);
    } finally {
      process.env.HOME = originalHome;
      wss.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      rmSync(home, { recursive: true, force: true });
    }
  });
});
