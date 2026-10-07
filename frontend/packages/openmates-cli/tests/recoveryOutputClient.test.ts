import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { OpenMatesClient } from "../src/client.ts";
import {
  decryptWithAesGcmCombined, deriveEmbedKeyFromChatKey,
  encryptBytesWithAesGcm, encryptWithAesGcmCombined, sealRecoveryOutputEnvelopeForTest,
} from "../src/crypto.ts";
import { encode as toonEncode } from "@toon-format/toon";
import type { AvailableRecoveryOutputFrame } from "../src/ws.ts";

// Private client methods are invoked through explicit test-only callable shapes.
// The WS/cache arguments are purpose-built mocks in these tests.
type ReplayOutputPages = (
  ws: unknown, ownerId: string, pages: AvailableRecoveryOutputFrame[][],
  cache: unknown, teamId: string | null,
  onPending?: () => void,
) => Promise<number>;
type ReplayCurrentTurnPages = (
  ws: unknown, ownerId: string, pages: AvailableRecoveryOutputFrame[][],
  cache: unknown, teamId: string | null, chatId: string,
) => Promise<void>;
type ReplayAvailableOutputs = (
  ws: unknown, ownerId: string, outputs: AvailableRecoveryOutputFrame[],
  cache: unknown, teamId: string | null,
) => Promise<number>;
type PersistAvailableOutputs = (
  ws: unknown, ownerId: string, cache: unknown,
  outputs: AvailableRecoveryOutputFrame[], teamId: string | null,
) => Promise<number>;

const keyVector = JSON.parse(readFileSync(
  new URL("../../../../backend/tests/fixtures/chat_completion_recovery_vectors.json", import.meta.url), "utf8",
)).vectors[0];
const outputVector = JSON.parse(readFileSync(
  new URL("../../../../backend/tests/fixtures/chat_recovery_output_v2.json", import.meta.url), "utf8",
));

describe("CLI typed recovery replay", () => {
  // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("loads and caches verified chat history when canonical recovery reread is unavailable", async () => {
    const previous = process.env.OPENMATES_STATE_DIR;
    const directory = mkdtempSync(join(tmpdir(), "tui-pending-recovery-"));
    process.env.OPENMATES_STATE_DIR = directory;
    try {
      const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
      client.resolveTeamContext = () => null;
      client.getMasterKeyBytes = () => new Uint8Array(32);
      client.getChatWrappingKey = async () => new Uint8Array(32);
      client.hasSession = () => true;
      client.decryptChatListItem = async (chat: {details: {id: string}}) => ({ id: chat.details.id, title: "Saved conversation" });
      const calls: string[] = [];
      client.openWsClient = async () => ({ ownerId: "owner", ws: {
        collectMessages: async () => [{ type: "phase_2_last_20_chats_ready", payload: {
          chats: [{chat_details: {id: "chat-1"}}], total_chat_count: 1,
        } }, {type: "phased_sync_complete", payload: {}}],
        send: () => {}, drainPassiveTaskUpdateJobs: () => [],
        waitForRecoveryOutputDiscovery: async () => {},
        drainAvailableRecoveryOutputPages: () => [[{record_id: "pending-embed"}]],
        close: () => { calls.push("close"); },
      } });
      client.persistPendingAIResponsesFromSync = async () => {};
      client.persistPendingWorkflowChatDeliveries = async () => 0;
      client.persistPendingTaskUpdateJobs = async () => new Set();
      client.replayAvailableRecoveryOutputs = async () => { calls.push("recovery"); throw new Error("Canonical recovery embed reread failed before acknowledgement."); };
      const page = await (client as unknown as OpenMatesClient).listChats();
      assert.equal(page.chats[0].id, "chat-1");
      assert.equal(page.pendingRecoveryOutputs, 1);
      assert.deepEqual(calls, ["recovery", "close"]);
      const cached = JSON.parse(readFileSync(join(directory, "sync_cache.json"), "utf8"));
      assert.equal(cached.pendingRecoveryOutputs, 1);
      assert.equal(cached.chats[0].details.id, "chat-1");
    } finally {
      if (previous === undefined) delete process.env.OPENMATES_STATE_DIR; else process.env.OPENMATES_STATE_DIR = previous;
      rmSync(directory, {recursive: true, force: true});
    }
  });
  // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("keeps failed browsing recovery pending while later verified records remain recoverable", async () => {
    const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
    const calls: string[] = [];
    client.replayAvailableRecoveryOutputs = async (_ws: unknown, _owner: unknown, outputs: AvailableRecoveryOutputFrame[]) => {
      calls.push(outputs[0].record_id);
      if (outputs[0].record_id === "broken") throw new Error("Canonical recovery embed reread failed before acknowledgement.");
      return 1;
    };
    const output = (recordId: string): AvailableRecoveryOutputFrame => ({ record_id: recordId,
      root_chat_id: "root", target_chat_id: "child", turn_id: "turn", subject_id: recordId,
      output_kind: "embed", output_version: 1, chat_key_version: 1 });
    let pending = 0;
    const replay = client.replayRecoveryOutputPages as ReplayOutputPages;
    assert.equal(await replay.call(client, {}, "owner", [[output("broken"), output("good")]], {}, null,
      () => { pending += 1; }), 1);
    assert.equal(pending, 1); assert.deepEqual(calls, ["broken", "good"]);
    await assert.rejects(replay.call(client, {}, "owner", [[output("broken")]], {}, null), /reread failed/);
  });
  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.message.identity-idempotent
  it("waits for each discovered page to settle before replaying the next one", async () => {
    const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
    const calls: string[] = [];
    let releaseFirst!: () => void;
    const firstSettled = new Promise<void>((resolve) => { releaseFirst = resolve; });
    client.replayAvailableRecoveryOutputs = async (_ws: unknown, _owner: unknown,
      outputs: AvailableRecoveryOutputFrame[]) => {
      calls.push(outputs[0].record_id);
      if (outputs[0].record_id === "first") await firstSettled;
      return 1;
    };
    const output = (recordId: string): AvailableRecoveryOutputFrame => ({
      record_id: recordId, root_chat_id: "root", target_chat_id: "child", turn_id: "turn",
      subject_id: recordId, output_kind: "message", output_version: 1, chat_key_version: 1,
    });
    const pending = (client.replayRecoveryOutputPages as ReplayOutputPages)(
      {}, "owner", [[output("first")], [output("second")]], {}, null,
    );
    await new Promise<void>((resolve) => setImmediate(resolve));
    assert.deepEqual(calls, ["first"]);
    releaseFirst();
    assert.equal(await pending, 2);
    assert.deepEqual(calls, ["first", "second"]);
  });

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery,chats.persistence.client-encrypted
  it("persists the active turn while an older root without a wrapper remains rediscoverable", async () => {
    const identity = outputVector.identity;
    const active: AvailableRecoveryOutputFrame = {
      record_id: identity.record_id, root_chat_id: identity.root_chat_id,
      target_chat_id: identity.target_chat_id, turn_id: identity.turn_id,
      subject_id: identity.subject_id, output_kind: "message",
      output_version: identity.output_version, chat_key_version: identity.key_version,
      message_role: "assistant",
    };
    const old = { ...active, record_id: "old-pending-output", root_chat_id: "old-root" };
    const sealed = await sealRecoveryOutputEnvelopeForTest(new TextEncoder().encode(JSON.stringify({
      record_id: active.record_id, target_chat_id: active.target_chat_id,
      subject_id: active.subject_id, output_kind: active.output_kind,
      output_version: active.output_version,
      content: { role: "assistant", content: "current reply", created_at: 1_700_000_000 },
    })), {
      ownerId: identity.owner_id, rootChatId: active.root_chat_id,
      targetChatId: active.target_chat_id, turnId: active.turn_id,
      recordId: active.record_id, subjectId: active.subject_id,
      outputKind: active.output_kind, outputVersion: active.output_version,
      keyVersion: active.chat_key_version, recoveryPublicKey: keyVector.recovery_public_key,
      ephemeralPrivateKey: keyVector.ephemeral_private_key, nonce: keyVector.nonce,
    });
    const rawKey = new Uint8Array(Buffer.from(keyVector.chat_key, "base64url"));
    const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
    client.getMasterKeyBytes = () => new Uint8Array(32);
    client.getChatWrappingKey = async () => new Uint8Array(32);
    client.resolveChatKey = async (_cache: unknown, root: { details: { id: string } }) =>
      root.details.id === active.root_chat_id ? rawKey : null;
    client.getCliRequestHeaders = () => ({});
    const lookups: string[] = [];
    client.http = { get: async (path: string) => {
      lookups.push(path);
      return { ok: true, data: { wrappers: [] } };
    } };
    const sent: string[] = [];
    const waiters: Array<{ type: string; resolve: (value: unknown) => void }> = [];
    const ws = {
      waitForMessage: (type: string, predicate: (value: unknown) => boolean) => new Promise((resolve) => {
        waiters.push({ type, resolve: (value: unknown) => {
          if (predicate((value as { payload: unknown }).payload)) resolve(value);
        } });
      }),
      sendAsync: async (type: string, payload: Record<string, unknown>) => {
        sent.push(type);
        const responseType = type === "recovery_output_get" ? "recovery_output_ready" : "recovery_output_persisted";
        const responsePayload = type === "recovery_output_get"
          ? { ...active, sealed_payload: JSON.stringify(sealed), messages_v: 0 }
          : { record_id: active.record_id, state: "ACKNOWLEDGED", committed_messages_v: 1 };
        const waiter = waiters.find((item) => item.type === responseType);
        assert.ok(waiter);
        waiter.resolve({ payload: { ...responsePayload, request_id: payload.request_id } });
      },
    };
    const cache = { syncedAt: Date.now(), totalChatCount: 1, loadedChatCount: 1,
      chats: [{ details: { id: active.root_chat_id }, messages: [] }],
      embeds: [], embedKeys: [], chatKeyWrappers: [] };
    const replay = client.replayCurrentTurnRecoveryOutputPages as ReplayCurrentTurnPages;
    await replay.call(client, ws, identity.owner_id, [[old, active]], cache, null, active.root_chat_id);
    assert.deepEqual(sent, ["recovery_output_get", "recovery_output_persist_message"]);
    assert.deepEqual(lookups, ["/v1/chats/old-root/wrappers/window"]);
    await replay.call(client, ws, identity.owner_id, [[old]], cache, null, active.root_chat_id);
    assert.deepEqual(lookups, ["/v1/chats/old-root/wrappers/window", "/v1/chats/old-root/wrappers/window"]);
    assert.equal(sent.length, 2, "the older output was never fetched, persisted, or acknowledged");

    await assert.rejects(replay.call(client, ws, identity.owner_id, [[active]],
      { ...cache, chats: [] }, null, active.root_chat_id), /key wrapper is unavailable/);
    await assert.rejects(replay.call(client, ws, identity.owner_id, [[
      { ...old, target_chat_id: active.root_chat_id },
    ]], cache, null, active.root_chat_id), /key wrapper is unavailable/,
    "a child chat being answered must also keep strict recovery validation");
  });

  // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("selects the authorized Team wrapping context from the discovered root hash", async () => {
    const previousStateDir = process.env.OPENMATES_STATE_DIR;
    const stateDir = mkdtempSync(join(tmpdir(), "openmates-cli-recovery-team-"));
    process.env.OPENMATES_STATE_DIR = stateDir;
    try {
      const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
      const teamId = "known-recovery-team";
      const hash = createHash("sha256").update(teamId).digest("hex");
      const output: AvailableRecoveryOutputFrame = {
        record_id: outputVector.identity.record_id,
        root_chat_id: outputVector.identity.root_chat_id,
        target_chat_id: outputVector.identity.target_chat_id,
        turn_id: outputVector.identity.turn_id,
        subject_id: outputVector.identity.subject_id,
        output_kind: "message", output_version: 1, chat_key_version: 1,
        root_hashed_team_id: hash,
      };
      const calls: Array<string | null> = [];
      client.getCliRequestHeaders = () => ({});
      client.http = { get: async (path: string) => {
        assert.equal(path, "/v1/teams");
        return { ok: true, data: { teams: [{ team_id: teamId }] } };
      } };
      client.cacheTeamKeyFromRecord = async () => {};
      client.persistAvailableRecoveryOutputs = async (_ws: unknown, _owner: string, _cache: unknown,
        _outputs: unknown, selectedTeamId: string | null) => {
        calls.push(selectedTeamId);
        return 1;
      };
      const cache = { syncedAt: Date.now(), totalChatCount: 0, loadedChatCount: 0,
        chats: [], embeds: [], embedKeys: [], chatKeyWrappers: [] };
      assert.equal(await (client.replayAvailableRecoveryOutputs as ReplayAvailableOutputs)({}, "owner", [output], cache, null), 1);
      assert.deepEqual(calls, [teamId]);
      await assert.rejects(
        (client.replayAvailableRecoveryOutputs as ReplayAvailableOutputs)({}, "owner", [
          { ...output, root_hashed_team_id: "0".repeat(64) },
        ], cache, null),
        /Team identity is no longer available/,
      );
      assert.deepEqual(calls, [teamId]);
    } finally {
      if (previousStateDir === undefined) delete process.env.OPENMATES_STATE_DIR;
      else process.env.OPENMATES_STATE_DIR = previousStateDir;
      rmSync(stateDir, { recursive: true, force: true });
    }
  });

  for (const role of ["assistant", "user"] as const) {
  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted,chats.message.identity-idempotent
  it(`persists the sealed child ${role} message before its canonical ACK`, async () => {
    const identity = outputVector.identity;
    const output: AvailableRecoveryOutputFrame = {
      record_id: identity.record_id, root_chat_id: identity.root_chat_id,
      target_chat_id: identity.target_chat_id, turn_id: identity.turn_id,
      subject_id: identity.subject_id, output_kind: "message",
      output_version: identity.output_version, chat_key_version: identity.key_version,
      root_hashed_team_id: null,
      message_role: role,
    };
    const sealed = await sealRecoveryOutputEnvelopeForTest(new TextEncoder().encode(JSON.stringify({
      record_id: output.record_id, target_chat_id: output.target_chat_id,
      subject_id: output.subject_id, output_kind: output.output_kind,
      output_version: output.output_version,
      content: { role, content: "sealed child output", category: null, model_name: null, created_at: 1_700_000_000 },
    })), {
      ownerId: identity.owner_id, rootChatId: output.root_chat_id,
      targetChatId: output.target_chat_id, turnId: output.turn_id,
      recordId: output.record_id, subjectId: output.subject_id,
      outputKind: output.output_kind, outputVersion: output.output_version,
      keyVersion: output.chat_key_version, recoveryPublicKey: keyVector.recovery_public_key,
      ephemeralPrivateKey: keyVector.ephemeral_private_key, nonce: keyVector.nonce,
    });
    const rawKey = new Uint8Array(Buffer.from(keyVector.chat_key, "base64url"));
    const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
    client.getMasterKeyBytes = () => new Uint8Array(32);
    client.getChatWrappingKey = async () => new Uint8Array(32);
    client.resolveChatKey = async () => rawKey;
    let persisted: Record<string, unknown> | null = null;
    const sent: string[] = [];
    const pending: Array<{ type: string; resolve: (value: unknown) => void }> = [];
    const ws = {
      waitForMessage: (type: string, predicate: (value: unknown) => boolean) => new Promise((resolve) => {
        pending.push({ type, resolve: (value: unknown) => { if (predicate((value as { payload: unknown }).payload)) resolve(value); } });
      }),
      sendAsync: async (type: string, payload: Record<string, unknown>) => {
        sent.push(type);
        if (type === "recovery_output_persist_message") persisted = payload;
        const responseType = type === "recovery_output_get" ? "recovery_output_ready" : "recovery_output_persisted";
        const responsePayload = type === "recovery_output_get"
          ? { ...output, sealed_payload: JSON.stringify(sealed), messages_v: 0, encrypted_chat_key: null, encrypted_title: null }
          : { record_id: output.record_id, state: "ACKNOWLEDGED", committed_messages_v: 1 };
        const waiter = pending.find((item) => item.type === responseType);
        assert.ok(waiter);
        waiter.resolve({ type: responseType, payload: { ...responsePayload, request_id: payload.request_id } });
      },
    };
    const cache = {
      syncedAt: Date.now(), totalChatCount: 1, loadedChatCount: 1,
      chats: [{ details: { id: output.root_chat_id }, messages: [] }],
      embeds: [], embedKeys: [], chatKeyWrappers: [],
    };
    const count = await (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(
      ws, identity.owner_id, cache, [output], null,
    );
    assert.equal(count, 1);
    assert.deepEqual(sent, ["recovery_output_get", "recovery_output_persist_message"]);
    const encrypted = (persisted?.[role === "user" ? "encrypted_user_message" : "encrypted_assistant_message"] ?? {}) as Record<string, unknown>;
    assert.equal(encrypted.client_message_id, output.subject_id);
    assert.equal(encrypted.role, role);
    assert.equal(encrypted.created_at, 1_700_000_000);
    assert.equal(await decryptWithAesGcmCombined(String(encrypted.encrypted_content), rawKey), "sealed child output");
    assert.ok(typeof persisted?.encrypted_chat_key === "string");
    assert.equal(JSON.stringify(persisted).includes("sealed child output"), false);
  });
  }

  // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  for (const child of [false, true]) {
  it(`ACKs a ${child ? "child" : "root"} embed with wrapper-gated reads and an unchanged historical version`, async () => {
    const identity = outputVector.identity;
    const output: AvailableRecoveryOutputFrame = {
      record_id: identity.record_id, root_chat_id: identity.root_chat_id,
      target_chat_id: identity.target_chat_id, turn_id: identity.turn_id,
      subject_id: identity.subject_id, output_kind: "embed",
      output_version: 1, chat_key_version: identity.key_version,
    };
    const parentId = child ? "77777777-7777-4777-8777-777777777777" : null;
    const keySubject = parentId || output.subject_id;
    const content = {
      embed_id: output.subject_id, version_number: 1, type: "code",
      content: toonEncode({ type: "code", code: "private recovered source" }),
      parent_embed_id: parentId,
      message_id: "55555555-5555-4555-8555-555555555555",
    };
    const sealed = await sealRecoveryOutputEnvelopeForTest(new TextEncoder().encode(JSON.stringify({
      record_id: output.record_id, target_chat_id: output.target_chat_id,
      subject_id: output.subject_id, output_kind: output.output_kind,
      output_version: output.output_version, content,
    })), {
      ownerId: identity.owner_id, rootChatId: output.root_chat_id,
      targetChatId: output.target_chat_id, turnId: output.turn_id,
      recordId: output.record_id, subjectId: output.subject_id,
      outputKind: output.output_kind, outputVersion: output.output_version,
      keyVersion: output.chat_key_version, recoveryPublicKey: keyVector.recovery_public_key,
      ephemeralPrivateKey: keyVector.ephemeral_private_key, nonce: keyVector.nonce,
    });
    const rawKey = new Uint8Array(Buffer.from(keyVector.chat_key, "base64url"));
    const embedKey = await deriveEmbedKeyFromChatKey(rawKey, keySubject);
    const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
    client.getMasterKeyBytes = () => new Uint8Array(32);
    client.getChatWrappingKey = async () => new Uint8Array(32);
    client.resolveChatKey = async () => rawKey;
    client.getCliRequestHeaders = () => ({});
    let stored: Record<string, unknown> | null = null;
    // A recovered parent may have only its master wrapper. A new root has none.
    const wrappers: Array<Record<string, unknown>> = child ? [{
      hashed_embed_id: createHash("sha256").update(keySubject).digest("hex"), key_type: "master",
      encrypted_embed_key: await encryptBytesWithAesGcm(embedKey, new Uint8Array(32)),
    }] : [];
    let historicalSnapshot: string | null = null;
    const sent: string[] = [];
    const digest = (value: string) => createHash("sha256").update(value).digest("hex");
    client.http = { get: async (path: string) => path.includes("/versions/1?")
      ? { ok: true, status: 200, data: { embed_id: output.subject_id,
        version_number: 1, rows: [{ version_number: 1, encrypted_snapshot: historicalSnapshot, encrypted_patch: null }] } }
      : parentId && path.includes(`/embeds/${parentId}`) && wrappers.length ? { ok: true, status: 200, data: { embed: {
        embed_id: parentId, hashed_chat_id: createHash("sha256").update(output.target_chat_id).digest("hex"),
      }, embed_keys: wrappers } }
      : stored && wrappers.length ? { ok: true, status: 200, data: { embed: stored, embed_keys: wrappers } }
        : { ok: false, status: 404, data: {} } };
    const pending: Array<{ type: string; resolve: (value: unknown) => void }> = [];
    const ws = {
      waitForMessage: (type: string, predicate: (value: unknown) => boolean) => new Promise((resolve) => {
        pending.push({ type, resolve: (value: unknown) => { if (predicate((value as { payload: unknown }).payload)) resolve(value); } });
      }),
      sendAsync: async (type: string, payload: Record<string, unknown>) => {
        sent.push(type);
        if (type === "store_embed") stored = payload;
        if (type === "store_embed_keys") {
          assert.ok(stored, "head receipt must precede wrapper bootstrap");
          const keys = payload.keys as Array<Record<string, unknown>>;
          assert.ok(keys.every((key) => key.hashed_embed_id === digest(keySubject)));
          wrappers.push(...keys);
        }
        if (type === "recovery_output_ack_embed") {
          assert.equal(payload.canonical_digest, historicalSnapshot
            ? digest(JSON.stringify([historicalSnapshot, null])) : digest(String(stored?.encrypted_content)));
          assert.equal(payload.canonical_source, historicalSnapshot ? "version_row" : "head");
          assert.equal(wrappers.length, 2);
        }
        const responseType: Record<string, string> = {
          recovery_output_get: "recovery_output_ready", store_embed: "store_embed_confirmed",
          store_embed_keys: "store_embed_keys_confirmed", recovery_output_ack_embed: "recovery_output_embed_acknowledged",
        };
        const typeToSend = responseType[type];
        assert.ok(typeToSend);
        const responsePayload = type === "recovery_output_get"
          ? { ...output, sealed_payload: JSON.stringify(sealed), messages_v: 1, encrypted_chat_key: "wrapped" }
          : type === "store_embed" ? { embed_id: output.subject_id,
            canonical_digest: digest(String(stored?.encrypted_content)), canonical_source: "head" }
            : type === "store_embed_keys" ? { created_count: (payload.keys as unknown[]).length,
              failed_count: 0, requested_count: (payload.keys as unknown[]).length }
              : { record_id: output.record_id, state: "ACKNOWLEDGED" };
        const waiterIndex = pending.findIndex((item) => item.type === typeToSend);
        const waiter = waiterIndex >= 0 ? pending.splice(waiterIndex, 1)[0] : null;
        assert.ok(waiter);
        waiter.resolve({ type: typeToSend, payload: { ...responsePayload, request_id: payload.request_id } });
      },
    };
    const cache = {
      syncedAt: Date.now(), totalChatCount: 1, loadedChatCount: 1,
      chats: [{ details: { id: output.root_chat_id }, messages: [] }],
      embeds: [], embedKeys: [], chatKeyWrappers: [],
    };
    assert.equal(await (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null), 1);
    assert.equal(await (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null), 1);
    assert.equal(sent.filter((type) => type === "store_embed").length, 1);
    assert.equal(sent.filter((type) => type === "store_embed_keys").length, 1);
    assert.equal(sent.filter((type) => type === "recovery_output_ack_embed").length, 2);
    historicalSnapshot = await encryptWithAesGcmCombined("private recovered source", embedKey);
    stored!.version_number = 2;
    stored!.encrypted_content = await encryptWithAesGcmCombined("newer unrelated content", embedKey);
    assert.equal(await (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null), 1);
    assert.equal(sent.filter((type) => type === "store_embed").length, 1);
    assert.equal(sent.filter((type) => type === "recovery_output_ack_embed").length, 3);
    wrappers[0].encrypted_embed_key = await encryptBytesWithAesGcm(new Uint8Array(32), new Uint8Array(32));
    await assert.rejects(
      (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null),
      /key wrapper does not match/,
    );
    assert.equal(sent.filter((type) => type === "recovery_output_ack_embed").length, 3);
  });
  }

  // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("ACKs an existing checkpoint using its canonical ciphertext and source manifest", async () => {
    const identity = outputVector.identity;
    const output: AvailableRecoveryOutputFrame = {
      record_id: identity.record_id, root_chat_id: identity.root_chat_id,
      target_chat_id: identity.target_chat_id, turn_id: identity.turn_id,
      subject_id: "66666666-6666-4666-8666-666666666666", output_kind: "checkpoint",
      output_version: 1, chat_key_version: identity.key_version,
    };
    const content = {
      summary_message_id: output.subject_id, summary_content: "secret compressed history",
      compressed_up_to_timestamp: 1_700_000_000,
      compressed_up_to_message_id: "55555555-5555-4555-8555-555555555555",
      covered_message_ids: ["11111111-1111-4111-8111-111111111111", "55555555-5555-4555-8555-555555555555"],
      compressed_message_count: 2, summary_token_estimate: 12,
    };
    const sealed = await sealRecoveryOutputEnvelopeForTest(new TextEncoder().encode(JSON.stringify({
      record_id: output.record_id, target_chat_id: output.target_chat_id,
      subject_id: output.subject_id, output_kind: output.output_kind,
      output_version: output.output_version, content,
    })), {
      ownerId: identity.owner_id, rootChatId: output.root_chat_id,
      targetChatId: output.target_chat_id, turnId: output.turn_id,
      recordId: output.record_id, subjectId: output.subject_id,
      outputKind: output.output_kind, outputVersion: output.output_version,
      keyVersion: output.chat_key_version, recoveryPublicKey: keyVector.recovery_public_key,
      ephemeralPrivateKey: keyVector.ephemeral_private_key, nonce: keyVector.nonce,
    });
    const rawKey = new Uint8Array(Buffer.from(keyVector.chat_key, "base64url"));
    const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
    client.getMasterKeyBytes = () => new Uint8Array(32);
    client.getChatWrappingKey = async () => new Uint8Array(32);
    client.resolveChatKey = async () => rawKey;
    let checkpoint: Record<string, unknown> | null = null;
    const acks: Record<string, unknown>[] = [];
    const pending: Array<{ type: string; resolve: (value: unknown) => void }> = [];
    const ws = {
      waitForMessage: (type: string, predicate: (value: unknown) => boolean) => new Promise((resolve) => {
        pending.push({ type, resolve: (value: unknown) => { if (predicate((value as { payload: unknown }).payload)) resolve(value); } });
      }),
      sendAsync: async (type: string, payload: Record<string, unknown>) => {
        if (type === "store_chat_compression_checkpoint" && !checkpoint) {
          checkpoint = { id: output.subject_id, encrypted_summary: payload.encrypted_summary,
            compressed_up_to_message_id: payload.compressed_up_to_message_id,
            covered_message_ids: payload.covered_message_ids };
        }
        if (type === "recovery_output_ack_checkpoint") {
          acks.push(payload);
          assert.equal(payload.encrypted_summary, checkpoint?.encrypted_summary);
          assert.deepEqual(payload.covered_message_ids, content.covered_message_ids);
        }
        const responseType: Record<string, string> = {
          recovery_output_get: "recovery_output_ready",
          store_chat_compression_checkpoint: "chat_compression_checkpoint_stored",
          recovery_output_ack_checkpoint: "recovery_output_checkpoint_acknowledged",
        };
        const typeToSend = responseType[type];
        assert.ok(typeToSend);
        const responsePayload = type === "recovery_output_get"
          ? { ...output, sealed_payload: JSON.stringify(sealed), messages_v: 1, encrypted_chat_key: "wrapped" }
          : type === "store_chat_compression_checkpoint"
            ? { chat_id: output.target_chat_id, checkpoint }
            : { record_id: output.record_id, state: "ACKNOWLEDGED" };
        const waiterIndex = pending.findIndex((item) => item.type === typeToSend);
        const waiter = waiterIndex >= 0 ? pending.splice(waiterIndex, 1)[0] : null;
        assert.ok(waiter);
        waiter.resolve({ type: typeToSend, payload: { ...responsePayload, request_id: payload.request_id } });
      },
    };
    const cache = {
      syncedAt: Date.now(), totalChatCount: 1, loadedChatCount: 1,
      chats: [{ details: { id: output.root_chat_id }, messages: [] }],
      embeds: [], embedKeys: [], chatKeyWrappers: [],
    };
    assert.equal(await (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null), 1);
    assert.equal(await (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null), 1);
    assert.equal(acks.length, 2);
    assert.equal(await decryptWithAesGcmCombined(String(checkpoint?.encrypted_summary), rawKey), content.summary_content);
  });

  // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("reuses a matching canonical diff row and ACKs its ciphertext digest", async () => {
    const identity = outputVector.identity;
    const output: AvailableRecoveryOutputFrame = {
      record_id: identity.record_id, root_chat_id: identity.root_chat_id,
      target_chat_id: identity.target_chat_id, turn_id: identity.turn_id,
      subject_id: identity.subject_id, output_kind: "diff",
      output_version: 1, chat_key_version: identity.key_version,
    };
    const content = { embed_id: output.subject_id, version_number: 1, snapshot: "first private version" };
    const sealed = await sealRecoveryOutputEnvelopeForTest(new TextEncoder().encode(JSON.stringify({
      record_id: output.record_id, target_chat_id: output.target_chat_id,
      subject_id: output.subject_id, output_kind: output.output_kind,
      output_version: output.output_version, content,
    })), {
      ownerId: identity.owner_id, rootChatId: output.root_chat_id,
      targetChatId: output.target_chat_id, turnId: output.turn_id,
      recordId: output.record_id, subjectId: output.subject_id,
      outputKind: output.output_kind, outputVersion: output.output_version,
      keyVersion: output.chat_key_version, recoveryPublicKey: keyVector.recovery_public_key,
      ephemeralPrivateKey: keyVector.ephemeral_private_key, nonce: keyVector.nonce,
    });
    const rawKey = new Uint8Array(Buffer.from(keyVector.chat_key, "base64url"));
    const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
    client.getMasterKeyBytes = () => new Uint8Array(32);
    client.getChatWrappingKey = async () => new Uint8Array(32);
    client.resolveChatKey = async () => rawKey;
    client.getCliRequestHeaders = () => ({});
    let diff: Record<string, unknown> | null = null;
    const wrappers: Array<Record<string, unknown>> = [];
    const sent: string[] = [];
    client.http = { get: async (path: string) => path.includes("/versions/")
      ? diff ? { ok: true, status: 200, data: { rows: [diff] } }
        : { ok: false, status: 404, data: {} }
      : { ok: true, status: 200, data: { embed: {
        embed_id: output.subject_id, hashed_chat_id: createHash("sha256").update(output.target_chat_id).digest("hex"),
        version_number: 1, encrypted_content: "canonical encrypted head", parent_embed_id: null,
      }, embed_keys: wrappers } } };
    const pending: Array<{ type: string; resolve: (value: unknown) => void }> = [];
    const ws = {
      waitForMessage: (type: string, predicate: (value: unknown) => boolean) => new Promise((resolve) => {
        pending.push({ type, resolve: (value: unknown) => { if (predicate((value as { payload: unknown }).payload)) resolve(value); } });
      }),
      sendAsync: async (type: string, payload: Record<string, unknown>) => {
        sent.push(type);
        if (type === "store_embed_diff") diff = payload;
        if (type === "store_embed_keys") wrappers = payload.keys as Array<Record<string, unknown>>;
        const canonicalDigest = createHash("sha256").update(JSON.stringify([
          diff?.encrypted_snapshot ?? null, diff?.encrypted_patch ?? null,
        ])).digest("hex");
        if (type === "recovery_output_ack_embed") {
          assert.equal(payload.canonical_digest, canonicalDigest);
          assert.equal(payload.canonical_source, "version_row");
          assert.equal(wrappers.length, 2);
        }
        const responseType: Record<string, string> = {
          recovery_output_get: "recovery_output_ready", store_embed_diff: "store_embed_diff_confirmed",
          store_embed_keys: "store_embed_keys_confirmed",
          recovery_output_ack_embed: "recovery_output_embed_acknowledged",
        };
        const typeToSend = responseType[type];
        assert.ok(typeToSend);
        const responsePayload = type === "recovery_output_get"
          ? { ...output, sealed_payload: JSON.stringify(sealed), messages_v: 1, encrypted_chat_key: "wrapped" }
          : type === "store_embed_diff"
            ? { embed_id: output.subject_id, version_number: 1,
              canonical_digest: canonicalDigest, canonical_source: "version_row" }
            : type === "store_embed_keys" ? { created_count: 2, failed_count: 0, requested_count: 2 }
            : { record_id: output.record_id, state: "ACKNOWLEDGED" };
        const waiterIndex = pending.findIndex((item) => item.type === typeToSend);
        const waiter = waiterIndex >= 0 ? pending.splice(waiterIndex, 1)[0] : null;
        assert.ok(waiter);
        waiter.resolve({ type: typeToSend, payload: { ...responsePayload, request_id: payload.request_id } });
      },
    };
    const cache = {
      syncedAt: Date.now(), totalChatCount: 1, loadedChatCount: 1,
      chats: [{ details: { id: output.root_chat_id }, messages: [] }],
      embeds: [], embedKeys: [], chatKeyWrappers: [],
    };
    assert.equal(await (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null), 1);
    assert.equal(await (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null), 1);
    assert.equal(sent.filter((type) => type === "store_embed_diff").length, 1);
    assert.equal(sent.filter((type) => type === "store_embed_keys").length, 1);
    assert.equal(sent.filter((type) => type === "recovery_output_ack_embed").length, 2);
  });

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("persists a child summary through the version-fenced encrypted transaction", async () => {
    const identity = outputVector.identity;
    const output: AvailableRecoveryOutputFrame = {
      record_id: identity.record_id, root_chat_id: identity.root_chat_id,
      target_chat_id: identity.target_chat_id, turn_id: identity.turn_id,
      subject_id: identity.subject_id, output_kind: "summary",
      output_version: 1, chat_key_version: identity.key_version,
    };
    const sealed = await sealRecoveryOutputEnvelopeForTest(new TextEncoder().encode(JSON.stringify({
      record_id: output.record_id, target_chat_id: output.target_chat_id,
      subject_id: output.subject_id, output_kind: output.output_kind,
      output_version: output.output_version, content: { summary: "private child synthesis" },
    })), {
      ownerId: identity.owner_id, rootChatId: output.root_chat_id,
      targetChatId: output.target_chat_id, turnId: output.turn_id,
      recordId: output.record_id, subjectId: output.subject_id,
      outputKind: output.output_kind, outputVersion: output.output_version,
      keyVersion: output.chat_key_version, recoveryPublicKey: keyVector.recovery_public_key,
      ephemeralPrivateKey: keyVector.ephemeral_private_key, nonce: keyVector.nonce,
    });
    const rawKey = new Uint8Array(Buffer.from(keyVector.chat_key, "base64url"));
    const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
    client.getMasterKeyBytes = () => new Uint8Array(32);
    client.getChatWrappingKey = async () => new Uint8Array(32);
    client.resolveChatKey = async () => rawKey;
    const pending: Array<{ type: string; resolve: (value: unknown) => void }> = [];
    let persisted: Record<string, unknown> | null = null;
    const ws = {
      waitForMessage: (type: string, predicate: (value: unknown) => boolean) => new Promise((resolve) => {
        pending.push({ type, resolve: (value: unknown) => { if (predicate((value as { payload: unknown }).payload)) resolve(value); } });
      }),
      sendAsync: async (type: string, payload: Record<string, unknown>) => {
        if (type === "recovery_output_persist_summary") persisted = payload;
        const responseType = type === "recovery_output_get" ? "recovery_output_ready" : "recovery_output_summary_persisted";
        const responsePayload = type === "recovery_output_get"
          ? { ...output, sealed_payload: JSON.stringify(sealed), messages_v: 1, metadata_v: 3, encrypted_chat_key: "wrapped" }
          : { record_id: output.record_id, state: "ACKNOWLEDGED", committed_metadata_v: 4 };
        const waiterIndex = pending.findIndex((item) => item.type === responseType);
        const waiter = waiterIndex >= 0 ? pending.splice(waiterIndex, 1)[0] : null;
        assert.ok(waiter);
        waiter.resolve({ type: responseType, payload: { ...responsePayload, request_id: payload.request_id } });
      },
    };
    const cache = {
      syncedAt: Date.now(), totalChatCount: 1, loadedChatCount: 1,
      chats: [{ details: { id: output.root_chat_id }, messages: [] }],
      embeds: [], embedKeys: [], chatKeyWrappers: [],
    };
    assert.equal(await (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null), 1);
    assert.equal(persisted?.expected_metadata_v, 3);
    assert.equal(await decryptWithAesGcmCombined(String(persisted?.encrypted_summary), rawKey), "private child synthesis");
    assert.equal(JSON.stringify(persisted).includes("private child synthesis"), false);
  });
});
