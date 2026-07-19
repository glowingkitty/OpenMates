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
      if (request.url === `/v1/sdk/drafts/${storedDraft?.chatId}`) {
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
        seenHttp.some((request) => request.method === "GET" && request.url === `/v1/sdk/drafts/${created.chatId}`),
        true,
      );
    } finally {
      process.env.HOME = originalHome;
      wss.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      rmSync(home, { recursive: true, force: true });
    }
  });
});
