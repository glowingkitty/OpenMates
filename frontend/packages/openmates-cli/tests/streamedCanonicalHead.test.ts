import { after, describe, it } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { OpenMatesClient } from "../src/client.ts";
import { encryptBytesWithAesGcm, encryptWithAesGcmCombined, deriveEmbedKeyFromChatKey } from "../src/crypto.ts";
import { WebSocketProtocolError } from "../src/ws.ts";

const previousState = process.env.OPENMATES_STATE_DIR;
const directory = mkdtempSync(join(tmpdir(), "openmates-streamed-canonical-"));
process.env.OPENMATES_STATE_DIR = directory;
after(() => {
  if (previousState === undefined) delete process.env.OPENMATES_STATE_DIR;
  else process.env.OPENMATES_STATE_DIR = previousState;
  rmSync(directory, { recursive: true, force: true });
});

const hash = (value: string) => createHash("sha256").update(value).digest("hex");
const chatId = "canonical-chat", ownerId = "canonical-owner", embedId = "canonical-focus";
const chatKey = new Uint8Array(32).fill(7), masterKey = new Uint8Array(32).fill(3);
const content = "type: focus_mode\nfocus_id: web.deep_research\napp_id: web\nskill_id: research\nstatus: finished";

async function fixture() {
  const key = await deriveEmbedKeyFromChatKey(chatKey, embedId);
  const head: Record<string, unknown> = {
    embed_id: embedId, hashed_embed_id: hash(embedId), hashed_user_id: hash(ownerId), hashed_chat_id: hash(chatId),
    hashed_message_id: hash("canonical-message"), hashed_task_id: hash("canonical-task"), embed_ids: [],
    hashed_team_id: null, parent_embed_id: null, version_number: 1, status: "finished",
    encrypted_type: await encryptWithAesGcmCombined("focus_mode", key),
    encrypted_content: await encryptWithAesGcmCombined(content, key),
  };
  const wrapper: Record<string, unknown> = {
    hashed_embed_id: hash(embedId), hashed_user_id: hash(ownerId), key_type: "chat",
    hashed_chat_id: hash(chatId), encrypted_embed_key: await encryptBytesWithAesGcm(key, chatKey),
  };
  const frames: Array<{ type: string; payload: Record<string, unknown> }> = [];
  const reads: string[] = [];
  const waiters = new Map<string, { predicate: (payload: unknown) => boolean;
    resolve: (value: unknown) => void; reject: (error: Error) => void }>();
  const ws = {
    waitForMessage: (type: string, predicate: (payload: unknown) => boolean) => new Promise((resolve, reject) => {
      waiters.set(type, { predicate, resolve, reject });
    }),
    sendAsync: async (type: string, payload: Record<string, unknown>) => {
      frames.push({ type, payload });
      const waiter = waiters.get(type === "store_embed" ? "store_embed_confirmed" : "store_embed_keys_confirmed");
      assert.ok(waiter);
      if (type === "store_embed") {
        const error = { request_id: payload.request_id, code: "embed_write_denied" };
        // The real error frame omits embed_id; matching it must not wait for timeout.
        assert.equal(waiter.predicate({ ...error, request_id: "other-writer" }), false);
        assert.equal(waiter.predicate(error), true);
        waiter.reject(new WebSocketProtocolError("embed_write_denied", "Not authorized to store embed"));
      } else {
        waiter.resolve({ payload: { created_count: 2, failed_count: 0 } });
      }
    },
  };
  const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
  client.getMasterKeyBytes = () => masterKey;
  client.getCliRequestHeaders = () => ({});
  client.http = { get: async (path: string) => {
    reads.push(path);
    return { ok: true, status: 200, data: { embed: head, embed_keys: [wrapper] } };
  } };
  const run = (overrides: Record<string, unknown> = {}) => {
    const frame: Record<string, unknown> = {
      embed_id: embedId, type: "focus_mode", content, status: "finished", version_number: 1,
      message_id: "canonical-message", task_id: "canonical-task", app_id: "web", skill_id: "research", embed_ids: [], ...overrides,
    };
    // JSON frames omit undefined values rather than declaring empty metadata.
    for (const [field, value] of Object.entries(frame)) if (value === undefined) delete frame[field];
    return (client.persistStreamedEmbeds as (params: unknown) => Promise<void>).call(client, {
      ws, embeds: [frame], chatId, chatKeyBytes: chatKey, ownerId, fallbackMessageId: "canonical-message",
    });
  };
  return { client, head, wrapper, frames, reads, ws, run, key };
}

describe("CLI streamed canonical heads", () => {
  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("reuses a denied but identical owner-bound head without changing ciphertext or wrappers", async () => {
    const state = await fixture(), original = state.head.encrypted_content;
    await state.run();
    assert.deepEqual(state.frames.map(frame => frame.type), ["store_embed"]);
    assert.notEqual(state.frames[0].payload.encrypted_content, original);
    assert.equal(state.head.encrypted_content, original);
    assert.deepEqual(state.reads, [`/v1/embeds/chats/${chatId}/embeds/${embedId}`]);
  });

  // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("accepts an authorized Personal master wrapper when the chat wrapper is absent", async () => {
    const state = await fixture();
    state.wrapper.key_type = "master";
    state.wrapper.hashed_chat_id = null;
    state.wrapper.encrypted_embed_key = await encryptBytesWithAesGcm(state.key, masterKey);
    await state.run();
    assert.equal(state.frames.length, 1);
  });

  // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("accepts null and empty child declarations against a null canonical list", async () => {
    for (const declared of [null, undefined, []]) {
      const state = await fixture();
      state.head.embed_ids = null;
      await state.run({ embed_ids: declared });
      assert.equal(state.frames.length, 1);
    }
  });

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("reuses an identical head with canonical children when the stream omits top-level child metadata", async () => {
    const state = await fixture();
    const parentContent = "type: app_skill_use\napp_id: web\nskill_id: search\nembed_ids[1]: canonical-child\nstatus: finished";
    state.head.encrypted_type = await encryptWithAesGcmCombined("app_skill_use", state.key);
    state.head.encrypted_content = await encryptWithAesGcmCombined(parentContent, state.key);
    state.head.embed_ids = ["canonical-child"];
    const originalHead = structuredClone(state.head), originalWrapper = structuredClone(state.wrapper);
    // send_embed_data preserves the wire payload; embed_ids is optional and
    // its absence does not assert that this parent has no canonical children.
    await state.run({ type: "app_skill_use", content: parentContent, skill_id: "search", embed_ids: undefined });
    assert.deepEqual(state.frames.map(frame => frame.type), ["store_embed"]);
    assert.equal(state.frames[0].payload.embed_ids, undefined);
    assert.deepEqual(state.head, originalHead);
    assert.deepEqual(state.wrapper, originalWrapper);
  });

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("rejects known null or empty child declarations when canonical children are nonempty", async () => {
    for (const declared of [null, []]) {
      const state = await fixture();
      state.head.embed_ids = ["canonical-child"];
      await assert.rejects(state.run({ embed_ids: declared }), /no matching canonical head/);
      assert.deepEqual(state.frames.map(frame => frame.type), ["store_embed"]);
    }
  });

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("verifies the supplied fallback message binding when the streamed message ID is absent", async () => {
    const state = await fixture();
    await state.run({ message_id: undefined });
    state.head.hashed_message_id = hash("other-fallback");
    await assert.rejects(state.run({ message_id: undefined }), /no matching canonical head/);
    assert.deepEqual(state.frames.map(frame => frame.type), ["store_embed", "store_embed"]);
  });

  for (const mismatch of ["owner", "chat", "team", "parent", "version", "message", "task", "children", "app", "skill", "type", "content", "wrapper"] as const) {
    // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
    it(`rejects a denied head with different ${mismatch} without rewriting or acknowledging it`, async () => {
      const state = await fixture();
      if (mismatch === "owner") state.head.hashed_user_id = hash("other-owner");
      if (mismatch === "chat") state.head.hashed_chat_id = hash("other-chat");
      if (mismatch === "team") state.head.hashed_team_id = hash("other-team");
      if (mismatch === "parent") state.head.parent_embed_id = "other-parent";
      if (mismatch === "version") state.head.version_number = 2;
      if (mismatch === "message") state.head.hashed_message_id = hash("other-message");
      if (mismatch === "task") state.head.hashed_task_id = hash("other-task");
      if (mismatch === "children") state.head.embed_ids = ["other-child"];
      if (mismatch === "app") state.head.app_id = "other-app";
      if (mismatch === "skill") state.head.skill_id = "other-skill";
      if (mismatch === "type") state.head.encrypted_type = await encryptWithAesGcmCombined("code", state.key);
      if (mismatch === "content") state.head.encrypted_content = await encryptWithAesGcmCombined("changed source", state.key);
      if (mismatch === "wrapper") state.wrapper.encrypted_embed_key = await encryptBytesWithAesGcm(new Uint8Array(32).fill(8), chatKey);
      const original = state.head.encrypted_content;
      await assert.rejects(state.run(), /no matching canonical head|does not match streamed source/);
      assert.deepEqual(state.frames.map(frame => frame.type), ["store_embed"]);
      assert.equal(state.head.encrypted_content, original);
    });
  }

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("keeps a denied or missing canonical read as a failure", async () => {
    for (const status of [403, 404, 503]) {
      const state = await fixture();
      state.client.http = { get: async () => ({ ok: false, status }) };
      await assert.rejects(state.run(), /no matching canonical head/);
      assert.equal(state.frames.length, 1);
    }
  });
});
