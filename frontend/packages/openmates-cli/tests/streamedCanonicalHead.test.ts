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
  const enrichment = { race: null as "version" | "cipher" | "metadata" | "receipt" | "reread" | "missing-wrapper" | "unreadable-wrapper" | "changed-wrapper" | "fresh-wrapper" | "changed-app" | "changed-skill" | "changed-children" | "changed-root" | "changed-workspace" | "normalized-children" | null };
  const rejection = { code: "embed_write_denied" };
  const ws = {
    waitForMessage: (type: string, predicate: (payload: unknown) => boolean) => new Promise((resolve, reject) => {
      waiters.set(type, { predicate, resolve, reject });
    }),
    sendAsync: async (type: string, payload: Record<string, unknown>) => {
      frames.push({ type, payload });
      const waiter = waiters.get(type === "store_embed" ? "store_embed_confirmed" : "store_embed_keys_confirmed");
      assert.ok(waiter);
      if (type === "store_embed" && payload.canonical_metadata_enrichment) {
        const marker = payload.canonical_metadata_enrichment as Record<string, unknown>;
        assert.equal(payload.encrypted_content, undefined);
        assert.equal(payload.encrypted_type, undefined);
        assert.equal(payload.version_number, undefined);
        assert.equal(payload.embed_ids, undefined);
        assert.equal(marker.expected_version, 1);
        assert.equal(marker.expected_ciphertext_sha256, hash(String(head.encrypted_content)));
        if (enrichment.race === "version" || enrichment.race === "cipher" || enrichment.race === "metadata") {
          waiter.reject(new WebSocketProtocolError("embed_write_denied", "Canonical metadata changed"));
          return;
        }
        for (const field of ["hashed_task_id", "file_path", "content_hash"]) {
          if (payload[field] !== undefined) head[field] = payload[field];
        }
        const receipt = { request_id: payload.request_id, embed_id: embedId,
          canonical_source: "head", canonical_digest: enrichment.race === "receipt" ? "0".repeat(64) : hash(String(head.encrypted_content)) };
        assert.equal(waiter.predicate(receipt), true);
        waiter.resolve({ payload: receipt });
        if (enrichment.race === "reread") head.encrypted_content = await encryptWithAesGcmCombined(content, key);
        if (enrichment.race === "unreadable-wrapper") wrapper.encrypted_embed_key = "not-a-ciphertext";
        if (enrichment.race === "changed-wrapper") wrapper.encrypted_embed_key = await encryptBytesWithAesGcm(new Uint8Array(32).fill(8), chatKey);
        if (enrichment.race === "fresh-wrapper") wrapper.encrypted_embed_key = await encryptBytesWithAesGcm(key, chatKey);
        if (enrichment.race === "changed-app") head.app_id = "other-app";
        if (enrichment.race === "changed-skill") head.skill_id = "other-skill";
        if (enrichment.race === "changed-children") head.embed_ids = ["other-child"];
        if (enrichment.race === "changed-root") head.root_embed_id = "other-root";
        if (enrichment.race === "changed-workspace") head.workspace_origin = "other-workspace";
        if (enrichment.race === "normalized-children") head.embed_ids = JSON.stringify(head.embed_ids);
      } else if (type === "store_embed") {
        const error = { request_id: payload.request_id, code: rejection.code };
        // The real error frame omits embed_id; matching it must not wait for timeout.
        assert.equal(waiter.predicate({ ...error, request_id: "other-writer" }), false);
        assert.equal(waiter.predicate(error), true);
        waiter.reject(new WebSocketProtocolError(rejection.code, "Canonical write rejected"));
      } else {
        waiter.resolve({ payload: { created_count: 2, failed_count: 0 } });
      }
    },
  };
  const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
  // Use a real fixture session so the production owner fence remains active.
  client.session = { sessionId: "canonical-fixture", hashedEmail: "canonical-fixture",
    activeTeamId: null, apiUrl: "http://fixture.invalid", createdAt: 1,
    masterKeyExportedB64: "canonical-fixture" };
  client.getMasterKeyBytes = () => masterKey;
  client.getCliRequestHeaders = () => ({});
  client.http = { get: async (path: string) => {
    reads.push(path);
    return { ok: true, status: 200, data: { embed: head, embed_keys: reads.length > 1 && enrichment.race === "missing-wrapper" ? [] : [wrapper] } };
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
  return { client, head, wrapper, frames, reads, ws, run, key, enrichment, rejection };
}

describe("CLI streamed canonical heads", () => {
  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted,authored-results.lifecycle.encrypted-and-stable
  it("reads the exact persisted assistant after another device completed a job without a final frame", async () => {
    const state = await fixture();
    const message = { id: "server-row", clientMessageId: "canonical-assistant", chatId,
      role: "assistant", content: "Card reference\n\nThe complete trailing explanation. 🗓️",
      category: "events", modelName: null };
    state.client.getChatMessages = async (id: string, options: unknown) => {
      assert.equal(id, chatId);
      assert.deepEqual(options, { freshChatOnly: true, maxHistoryPages: 1, personal: true, teamId: null });
      return { chat: { id: chatId }, messages: [message], historyIncomplete: true };
    };
    const read = state.client.readTerminalRecoveryResponse as (...args: unknown[]) => Promise<unknown>;
    assert.deepEqual(await read.call(state.client, chatId, "canonical-assistant", null), message);
    assert.equal(state.frames.length, 0);
  });

  for (const mismatch of ["chat", "message-chat", "role", "assistant", "duplicate", "missing", "content", "unreadable", "account"] as const) {
    // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
    it(`rejects a persisted recovery assistant with mismatched ${mismatch}`, async () => {
      const state = await fixture();
      state.client.getChatMessages = async () => {
        const message: Record<string, unknown> = { id: "canonical-assistant", chatId, role: "assistant", content: "Complete reply" };
        if (mismatch === "message-chat") message.chatId = "other-chat";
        if (mismatch === "role") message.role = "user";
        if (mismatch === "assistant") message.clientMessageId = "other-assistant";
        if (mismatch === "content") message.content = null;
        // The existing message decoder represents failed decryption as ''.
        if (mismatch === "unreadable") message.content = "";
        if (mismatch === "account") state.client.session = null;
        return { chat: { id: mismatch === "chat" ? "other-chat" : chatId },
          messages: mismatch === "missing" ? [] : mismatch === "duplicate" ? [message, { ...message }] : [message] };
      };
      const read = state.client.readTerminalRecoveryResponse as (...args: unknown[]) => Promise<unknown>;
      await assert.rejects(read.call(state.client, chatId, "canonical-assistant", null),
        /Persisted recovery assistant|Not logged in|Recovery account, Team or key changed/);
      assert.equal(state.frames.length, 0);
    });
  }

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("rejects a logged-out canonical fixture before reading or writing", async () => {
    const state = await fixture();
    state.client.session = null;
    await assert.rejects(state.run(), /Not logged in/);
    assert.equal(state.frames.length, 0);
    assert.equal(state.reads.length, 0);
  });

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("stops canonical reconciliation when the account changes during a write", async () => {
    const state = await fixture();
    const send = state.ws.sendAsync;
    state.ws.sendAsync = async (type, payload) => {
      state.client.session = { ...(state.client.session as Record<string, unknown>), sessionId: "other-account" };
      await send(type, payload);
    };
    await assert.rejects(state.run(), /Recovery account, Team or key changed/);
    assert.equal(state.frames.length, 1);
    assert.equal(state.reads.length, 0);
  });

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("atomically fills absent ACKed recovery provenance without reciphering or downgrading the head", async () => {
    const state = await fixture();
    state.head.hashed_task_id = null;
    const original = structuredClone(state.head), wrapper = structuredClone(state.wrapper);
    await state.run({ file_path: "src/recovered.ts", content_hash: "a".repeat(64) });
    assert.equal(state.head.hashed_task_id, hash("canonical-task"));
    assert.equal(state.head.file_path, "src/recovered.ts");
    assert.equal(state.head.content_hash, "a".repeat(64));
    for (const field of ["encrypted_content", "encrypted_type", "version_number", "hashed_user_id", "hashed_chat_id", "hashed_message_id"]) {
      assert.equal(state.head[field], original[field]);
    }
    assert.deepEqual(state.wrapper, wrapper);
    assert.deepEqual(state.frames.map(frame => frame.type), ["store_embed", "store_embed"]);
    assert.equal(state.frames[1].payload.canonical_metadata_enrichment !== undefined, true);
    assert.equal(state.reads.length, 2);
  });

  for (const race of ["version", "cipher", "metadata", "receipt", "reread"] as const) {
    // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
    it(`rejects metadata enrichment ${race} conflicts without raw rewrite or ACK`, async () => {
      const state = await fixture();
      state.head.hashed_task_id = null;
      state.enrichment.race = race;
      await assert.rejects(state.run(), /Canonical metadata changed|enrichment receipt|enrichment canonical reread/);
      assert.deepEqual(state.frames.map(frame => frame.type), ["store_embed", "store_embed"]);
      assert.equal(state.frames[1].payload.encrypted_content, undefined);
    });
  }

  for (const change of ["missing-wrapper", "unreadable-wrapper", "changed-wrapper", "changed-app", "changed-skill", "changed-children"] as const) {
    // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
    it(`rejects an enriched canonical reread with ${change}`, async () => {
      const state = await fixture();
      state.head.hashed_task_id = null;
      state.enrichment.race = change;
      await assert.rejects(state.run(), /enrichment canonical reread failed/);
      assert.deepEqual(state.frames.map(frame => frame.type), ["store_embed", "store_embed"]);
      assert.equal(state.frames[1].payload.encrypted_content, undefined);
    });
  }

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("accepts a fresh-nonce canonical wrapper only when it wraps the same embed key", async () => {
    const state = await fixture();
    state.head.hashed_task_id = null;
    state.enrichment.race = "fresh-wrapper";
    const originalCiphertext = state.head.encrypted_content;
    const originalWrapper = state.wrapper.encrypted_embed_key;
    await state.run();
    assert.equal(state.head.encrypted_content, originalCiphertext);
    assert.notEqual(state.wrapper.encrypted_embed_key, originalWrapper);
    assert.deepEqual(state.frames.map(frame => frame.type), ["store_embed", "store_embed"]);
  });

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("preserves stable canonical catalog and normalized children when the stream omits them", async () => {
    const state = await fixture();
    state.head.hashed_task_id = null;
    state.head.app_id = "web";
    state.head.skill_id = "research";
    state.head.root_embed_id = "canonical-root";
    state.head.workspace_origin = "canonical-workspace";
    state.head.embed_ids = ["canonical-child"];
    state.enrichment.race = "normalized-children";
    await state.run({ app_id: undefined, skill_id: undefined, embed_ids: undefined });
    assert.equal(state.head.encrypted_content !== undefined, true);
    assert.equal(state.head.hashed_task_id, hash("canonical-task"));
    assert.deepEqual(state.frames.map(frame => frame.type), ["store_embed", "store_embed"]);
  });

  for (const change of ["changed-app", "changed-skill", "changed-children", "changed-root", "changed-workspace"] as const) {
    // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
    it(`rejects changed canonical ${change} even when the source frame omits catalog and children`, async () => {
      const state = await fixture();
      state.head.hashed_task_id = null;
      state.head.app_id = "web";
      state.head.skill_id = "research";
      state.head.root_embed_id = "canonical-root";
      state.head.workspace_origin = "canonical-workspace";
      state.head.embed_ids = ["canonical-child"];
      state.enrichment.race = change;
      const originalCiphertext = state.head.encrypted_content;
      await assert.rejects(state.run({ app_id: undefined, skill_id: undefined, embed_ids: undefined }), /enrichment canonical reread failed/);
      assert.equal(state.head.encrypted_content, originalCiphertext);
      assert.equal(state.head.version_number, 1);
      assert.deepEqual(state.frames.map(frame => frame.type), ["store_embed", "store_embed"]);
    });
  }

  for (const field of ["file_path", "content_hash"] as const) {
    // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
    it(`rejects explicitly different canonical ${field} before enrichment`, async () => {
      const state = await fixture();
      state.head.hashed_task_id = null;
      state.head[field] = "other-value";
      await assert.rejects(state.run({ [field]: "declared-value" }), /no matching canonical head/);
      assert.equal(state.frames.length, 1);
    });
  }

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("reuses a denied but identical owner-bound head without changing ciphertext or wrappers", async () => {
    const state = await fixture(), original = state.head.encrypted_content;
    await state.run();
    assert.deepEqual(state.frames.map(frame => frame.type), ["store_embed"]);
    assert.notEqual(state.frames[0].payload.encrypted_content, original);
    assert.equal(state.head.encrypted_content, original);
    assert.deepEqual(state.reads, [`/v1/embeds/chats/${chatId}/embeds/${embedId}`]);
  });

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted,authored-results.lifecycle.encrypted-and-stable
  it("reuses an identical revision after another client has made its ciphertext immutable", async () => {
    const state = await fixture();
    state.rejection.code = "embed_revision_conflict";
    const head = structuredClone(state.head), wrapper = structuredClone(state.wrapper);
    await state.run();
    assert.deepEqual(state.head, head);
    assert.deepEqual(state.wrapper, wrapper);
    assert.deepEqual(state.frames.map(frame => frame.type), ["store_embed"]);
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
    for (const code of ["embed_write_denied", "embed_revision_conflict"]) {
      // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
      it(`rejects ${code} with different ${mismatch} without rewriting or acknowledging it`, async () => {
        const state = await fixture();
        state.rejection.code = code;
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
