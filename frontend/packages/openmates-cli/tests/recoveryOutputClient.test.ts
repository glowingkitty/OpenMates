import { describe, it, before, after } from "node:test";
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
import { WebSocketProtocolError, type AvailableRecoveryOutputFrame } from "../src/ws.ts";

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

// contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
for (const placement of ['outer', 'nested-toon', 'nested-team', 'incomplete', 'invalid', 'absent'] as const) {
  it(`initial root catalog bootstrap preserves a real v1 to v2 replay (${placement})`, async () => {
    const identity = outputVector.identity;
    const teamId = placement === 'nested-team' ? '77777777-7777-4777-8777-777777777777' : null;
    const hash = (value: string) => createHash('sha256').update(value).digest('hex');
    const master = new Uint8Array(32), chatKey = new Uint8Array(Buffer.from(keyVector.chat_key, 'base64url'));
    const _key = await deriveEmbedKeyFromChatKey(chatKey, identity.subject_id);
    let head: Record<string, any> | null = null;
    let wrappers: Array<Record<string, any>> = [];
    let writes = 0, acknowledgements = 0;
    let output: AvailableRecoveryOutputFrame;
    let content: Record<string, unknown>;
    let sealed: unknown;
    const client = Object.create(OpenMatesClient.prototype) as Record<string, any>;
    client.session = { sessionId: 'bootstrap-fixture', hashedEmail: 'fixture', activeTeamId: teamId,
      apiUrl: 'http://fixture.invalid', createdAt: 1, masterKeyExportedB64: 'fixture' };
    client.getMasterKeyBytes = () => master;
    client.getChatWrappingKey = async () => master;
    client.resolveChatKey = async () => chatKey;
    client.getCliRequestHeaders = () => ({});
    client.http = {
      post: async () => ({ ok: true, status: 200,
        data: { results: [{ embed_id: identity.subject_id, state: head ? 'ready' : 'missing' }] } }),
      get: async () => head && wrappers.length === 2
        ? { ok: true, status: 200, data: { embed: { ...head }, embed_keys: wrappers } }
        : { ok: false, status: 404, data: {} },
    };
    const pending: Array<{ type: string; predicate: (value: any) => boolean; resolve: (value: any) => void }> = [];
    const ws = {
      waitForMessage: (type: string, predicate: (value: any) => boolean) =>
        new Promise(resolve => pending.push({ type, predicate, resolve })),
      sendAsync: async (type: string, payload: Record<string, any>) => {
        let replyType: string, reply: Record<string, unknown>;
        if (type === 'recovery_output_get') {
          replyType = 'recovery_output_ready'; reply = { ...output, sealed_payload: JSON.stringify(sealed), messages_v: 1 };
        } else if (type === 'store_embed') {
          if (placement !== 'absent') {
            assert.equal(payload.app_id, 'code'); assert.equal(payload.skill_id, 'code');
            assert.equal(payload.chat_id, identity.target_chat_id); assert.equal(payload.team_id ?? null, teamId);
          } else {
            assert.equal(payload.app_id, undefined); assert.equal(payload.skill_id, undefined);
          }
          // Emulate the real server projection: catalog metadata is never inferred
          // from ciphertext and only exists when the client supplied a full pair.
          head = { ...payload, embed_id: identity.subject_id, hashed_embed_id: hash(identity.subject_id),
            hashed_team_id: payload.app_id ? (teamId ? hash(teamId) : null) : null,
            workspace_origin: payload.app_id ? 'chat' : null,
            root_embed_id: payload.app_id ? identity.subject_id : null };
          writes++;
          replyType = 'store_embed_confirmed';
          reply = { embed_id: identity.subject_id, canonical_source: 'head', canonical_digest: hash(String(head.encrypted_content)) };
        } else if (type === 'store_embed_keys') {
          assert.equal(wrappers.length, 0, 'Existing wrappers must never be replaced during v2 advance');
          wrappers = payload.keys;
          replyType = 'store_embed_keys_confirmed';
          reply = { created_count: 2, requested_count: 2, failed_count: 0 };
        } else {
          assert.equal(type, 'recovery_output_ack_embed');
          assert.equal(payload.canonical_digest, hash(String(head!.encrypted_content)));
          assert.equal(payload.canonical_source, 'head');
          acknowledgements++; replyType = 'recovery_output_embed_acknowledged';
          reply = { record_id: output.record_id, state: 'ACKNOWLEDGED' };
        }
        const response = { ...reply, request_id: payload.request_id };
        const index = pending.findIndex(waiter => waiter.type === replyType && waiter.predicate(response));
        assert.ok(index >= 0); pending.splice(index, 1)[0].resolve({ payload: response });
      },
    };
    async function recover(version: number) {
      output = { record_id: version === 1 ? identity.record_id : '11111111-1111-4111-8111-111111111112',
        root_chat_id: identity.root_chat_id, target_chat_id: identity.target_chat_id, turn_id: identity.turn_id,
        subject_id: identity.subject_id, output_kind: 'embed', output_version: version,
        chat_key_version: identity.key_version, root_hashed_team_id: teamId ? hash(teamId) : null };
      const nested = placement.startsWith('nested') ? { app_id: 'code', skill_id: 'code' } : {};
      content = { embed_id: identity.subject_id, version_number: version, type: 'code',
        content: toonEncode({ type: 'code', code: `return ${version}`, ...nested }), message_id: `bootstrap-message-${version}`,
        ...(placement === 'outer' || version > 1 ? { app_id: 'code', skill_id: 'code' } : {}),
        ...(placement === 'incomplete' && version === 1 ? { app_id: 'code' } : {}),
        ...(placement === 'invalid' && version === 1 ? { app_id: 'Code invalid', skill_id: 'code' } : {}) };
      sealed = await sealRecoveryOutputEnvelopeForTest(new TextEncoder().encode(JSON.stringify({ ...output, content })), {
        ownerId: identity.owner_id, rootChatId: output.root_chat_id, targetChatId: output.target_chat_id,
        turnId: output.turn_id, recordId: output.record_id, subjectId: output.subject_id,
        outputKind: 'embed', outputVersion: version, keyVersion: output.chat_key_version,
        recoveryPublicKey: keyVector.recovery_public_key, ephemeralPrivateKey: keyVector.ephemeral_private_key,
        nonce: keyVector.nonce,
      });
      return client.persistAvailableRecoveryOutputs(ws, identity.owner_id, {
        chats: [{ details: { id: identity.root_chat_id }, messages: [] }], chatKeyWrappers: [],
      }, [output], teamId);
    }
    if (placement === 'incomplete' || placement === 'invalid') {
      await assert.rejects(recover(1), /Initial recovery root catalog identity was invalid/);
      assert.equal(writes, 0); assert.equal(acknowledgements, 0); return;
    }
    await recover(1);
    assert.equal(writes, 1); assert.equal(acknowledgements, 1);
    const oldType = head!.encrypted_type, oldWrappers = JSON.stringify(wrappers);
    if (placement === 'absent') {
      await assert.rejects(recover(2), /Canonical recovery revision catalog identity was invalid/);
      assert.equal(writes, 1); assert.equal(acknowledgements, 1); return;
    }
    await recover(2);
    assert.equal(head!.version_number, 2); assert.equal(writes, 2); assert.equal(acknowledgements, 2);
    assert.equal(head!.app_id, 'code'); assert.equal(head!.skill_id, 'code');
    assert.equal(head!.encrypted_type, oldType); assert.equal(JSON.stringify(wrappers), oldWrappers);
  });
}

// contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
for (const currentVersion of [1, 2]) {
for (const transport of ["sealed", "streamed", "sealed-team"] as const) {
  for (const fault of ["none", "type", "wrapper", "scope", "future", "reread", "missing", "catalog", "unacknowledged", "wrong-ack", "wrong-ack-version", "gap"] as const) {
    // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
    it(`${transport} root v${currentVersion} to v${currentVersion + 1} preserves canonical type and keys (${fault})`, async () => {
      const identity = outputVector.identity;
      const teamId = transport === "sealed-team" ? "77777777-7777-4777-8777-777777777777" : null;
      const output: AvailableRecoveryOutputFrame = {
        record_id: identity.record_id, root_chat_id: identity.root_chat_id,
        target_chat_id: identity.target_chat_id, turn_id: identity.turn_id,
        subject_id: identity.subject_id, output_kind: "embed", output_version: currentVersion + 1,
        chat_key_version: identity.key_version,
      };
      const hash = (value: string) => createHash("sha256").update(value).digest("hex");
      output.root_hashed_team_id = teamId ? hash(teamId) : null;
      const master = new Uint8Array(32), chatKey = new Uint8Array(Buffer.from(keyVector.chat_key, "base64url"));
      const key = await deriveEmbedKeyFromChatKey(chatKey, output.subject_id);
      if (fault === "gap") output.output_version = currentVersion + 2;
      const nextVersion = output.output_version;
      const content = { embed_id: output.subject_id, version_number: nextVersion, type: "code",
        content: "new verified revision", message_id: "new-message", app_id: "web", skill_id: "search" };
      const oldType = await encryptWithAesGcmCombined(fault === "type" ? "website" : "code", key);
      const v1Snapshot = await encryptWithAesGcmCombined("old source", key);
      const oldHistory = { version_number: currentVersion,
        encrypted_snapshot: currentVersion === 1 ? v1Snapshot : null,
        encrypted_patch: currentVersion > 1 ? await encryptWithAesGcmCombined("old patch", key) : null };
      const oldHistoryBytes = JSON.stringify(oldHistory);
      let head: Record<string, unknown> = {
        embed_id: output.subject_id, hashed_embed_id: hash(output.subject_id),
        hashed_user_id: hash(identity.owner_id), hashed_chat_id: hash(output.target_chat_id),
        hashed_message_id: hash("old-message"), version_number: fault === "future" ? currentVersion + 2 : currentVersion,
        encrypted_content: await encryptWithAesGcmCombined("old revision", key),
        encrypted_type: oldType, status: "finished", parent_embed_id: null,
        app_id: "web", skill_id: "search", workspace_origin: "chat", root_embed_id: output.subject_id,
        hashed_team_id: teamId ? hash(teamId) : null,
      };
      if (fault === "scope") head.hashed_user_id = hash("foreign-owner");
      if (fault === "catalog") head.app_id = "foreign-app";
      const wrappers = await Promise.all(["master", "chat"].map(async (key_type) => ({
        hashed_embed_id: hash(output.subject_id), hashed_user_id: hash(identity.owner_id), key_type,
        hashed_chat_id: key_type === "chat" ? hash(output.target_chat_id) : null,
        encrypted_embed_key: await encryptBytesWithAesGcm(fault === "wrapper" ? new Uint8Array(32).fill(9) : key,
          key_type === "master" ? master : chatKey),
      })));
      const originalWrappers = JSON.stringify(wrappers);
      const sealed = await sealRecoveryOutputEnvelopeForTest(new TextEncoder().encode(JSON.stringify({ ...output, content })), {
        ownerId: identity.owner_id, rootChatId: output.root_chat_id, targetChatId: output.target_chat_id,
        turnId: output.turn_id, recordId: output.record_id, subjectId: output.subject_id,
        outputKind: "embed", outputVersion: nextVersion, keyVersion: output.chat_key_version,
        recoveryPublicKey: keyVector.recovery_public_key, ephemeralPrivateKey: keyVector.ephemeral_private_key,
        nonce: keyVector.nonce,
      });
      const client = Object.create(OpenMatesClient.prototype) as Record<string, any>;
      client.session = { sessionId: "fixture", hashedEmail: "fixture", activeTeamId: teamId,
        apiUrl: "http://fixture.invalid", createdAt: 1, masterKeyExportedB64: "fixture" };
      client.getMasterKeyBytes = () => master;
      client.getChatWrappingKey = async () => master;
      client.resolveChatKey = async () => chatKey;
      client.getCliRequestHeaders = () => ({});
      let reads = 0, writes = 0, acks = 0;
      client.http = {
        post: async (path: string, body: Record<string, unknown>) => {
          assert.equal(path, `/v1/embeds/chats/${output.target_chat_id}/references/availability`
            + (teamId ? `?team_id=${teamId}` : ""));
          assert.deepEqual(body, { embed_ids: [output.subject_id],
            ...(body.required_recovery_versions ? { required_recovery_versions: { [output.subject_id]: nextVersion } } : {}) });
          return { ok: true, status: 200,
          data: { results: [{ embed_id: output.subject_id, state: fault === "missing" ? "missing" : "ready",
            ...(body.required_recovery_versions && acks && fault !== "unacknowledged" ? { recovery_ack: {
              state: "ACKNOWLEDGED", version: fault === "wrong-ack-version" ? currentVersion : nextVersion,
              canonical_digest: fault === "wrong-ack" ? "f".repeat(64) : hash(String(head.encrypted_content)),
            } } : {}),
          }] } }; },
        get: async () => { reads++; return { ok: true, status: 200,
          data: { embed: fault === "reread" && writes ? { ...head, version_number: nextVersion + 1 } : { ...head }, embed_keys: wrappers } }; },
      };
      const pending: Array<{ type: string; predicate: (value: any) => boolean; resolve: (value: any) => void }> = [];
      const ws = {
        waitForMessage: (type: string, predicate: (value: any) => boolean) => new Promise(resolve => pending.push({ type, predicate, resolve })),
        sendAsync: async (type: string, payload: Record<string, any>) => {
          let replyType: string, reply: Record<string, unknown>;
          if (type === "recovery_output_get") {
            replyType = "recovery_output_ready"; reply = { ...output, sealed_payload: JSON.stringify(sealed), messages_v: 1 };
          } else if (type === "store_embed") {
            // Match the API catalog boundary that reconstructs protected Team/root provenance.
            assert.equal(payload.app_id, head.app_id); assert.equal(payload.skill_id, head.skill_id);
            assert.equal(payload.chat_id, output.target_chat_id); assert.equal(payload.team_id ?? null, teamId);
            assert.equal(payload.encrypted_type, oldType);
            assert.equal(payload.version_number, nextVersion);
            assert.equal(await decryptWithAesGcmCombined(payload.encrypted_content, key), content.content);
            writes++; head = { ...head, ...payload };
            replyType = "store_embed_confirmed";
            reply = { embed_id: output.subject_id, canonical_source: "head", canonical_digest: hash(String(head.encrypted_content)) };
          } else {
            assert.equal(type, "recovery_output_ack_embed", "existing wrappers and history must not be rewritten");
            assert.ok(reads >= 2); assert.equal(payload.canonical_digest, hash(String(head.encrypted_content)));
            acks++; replyType = "recovery_output_embed_acknowledged"; reply = { record_id: output.record_id, state: "ACKNOWLEDGED" };
          }
          const response = { ...reply, request_id: payload.request_id };
          const index = pending.findIndex(row => row.type === replyType && row.predicate(response));
          assert.ok(index >= 0); pending.splice(index, 1)[0].resolve({ payload: response });
        },
      };
      const recover = () => client.persistAvailableRecoveryOutputs(ws, identity.owner_id, {
        chats: [{ details: { id: output.root_chat_id }, messages: [] }], chatKeyWrappers: [],
      }, [output], teamId);
      const streamed = { ws, embeds: [{ ...content, status: "finished" }],
        chatId: output.target_chat_id, chatKeyBytes: chatKey, fallbackMessageId: content.message_id, ownerId: identity.owner_id, teamId };
      const run = () => transport !== "streamed" ? recover()
        : client.persistRecoveredTerminalEmbeds(streamed, recover);
      if (fault === "none" || (transport !== "streamed" && ["unacknowledged", "wrong-ack", "wrong-ack-version"].includes(fault))) {
        if (transport === "streamed") {
          await assert.rejects(client.persistRecoveredTerminalEmbeds(streamed, async () => {}), /has not durably settled/);
          assert.equal(writes, 0, "unsealed streaming cannot advance the head");
          await assert.rejects(client.persistRecoveredTerminalEmbeds(streamed, async () => { throw new Error("typed recovery failed"); }), /typed recovery failed/);
          assert.equal(writes, 0);
        }
        await run(); assert.equal(writes, 1); assert.equal(acks, 1);
        assert.equal(head.encrypted_type, oldType); assert.equal(head.version_number, nextVersion);
        if (transport === "streamed") {
          // Mixed terminal frames also reuse already-recovered v1 siblings;
          // no predictable denied recipher request may precede verification.
          const siblingId = "88888888-8888-4888-8888-888888888888";
          const siblingKey = await deriveEmbedKeyFromChatKey(chatKey, siblingId);
          const sibling = { ...content, embed_id: siblingId, version_number: 1, content: "recovered sibling" };
          const siblingHead = { ...head, embed_id: siblingId, hashed_embed_id: hash(siblingId),
            root_embed_id: siblingId, version_number: 1,
            encrypted_type: await encryptWithAesGcmCombined("code", siblingKey),
            encrypted_content: await encryptWithAesGcmCombined(sibling.content, siblingKey) };
          const siblingWrappers = await Promise.all(wrappers.map(async wrapper => ({ ...wrapper,
            hashed_embed_id: hash(siblingId), encrypted_embed_key: await encryptBytesWithAesGcm(siblingKey,
              wrapper.key_type === "master" ? master : chatKey),
          })));
          const read = client.http.get;
          client.http.get = async (path: string) => path.endsWith(siblingId)
            ? { ok: true, status: 200, data: { embed: siblingHead, embed_keys: siblingWrappers } } : read(path);
          await client.persistRecoveredTerminalEmbeds({ ...streamed, embeds: [...streamed.embeds, sibling] }, async () => {});
          assert.equal(writes, 1, "settled v2 and mixed v1 terminal heads must not send a recipher write");
        }
      } else {
        await assert.rejects(run());
        const proofFailure = ["unacknowledged", "wrong-ack", "wrong-ack-version"].includes(fault);
        assert.equal(acks, proofFailure ? 1 : 0);
        assert.equal(writes, fault === "reread" || proofFailure ? 1 : 0);
      }
      assert.equal(JSON.stringify(wrappers), originalWrappers);
      assert.equal(await decryptWithAesGcmCombined(v1Snapshot, key), "old source");
      assert.equal(JSON.stringify(oldHistory), oldHistoryBytes, "the prior immutable history row must remain byte-identical");
    });
  }
}

}

describe("CLI typed recovery replay", () => {
  // contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted
  it("omits absent thinking and rejects malformed observed metadata without estimating metrics", async () => {
    const client = Object.create(OpenMatesClient.prototype) as unknown as {
      encryptThinkingFields: (source: Record<string, unknown>, key: Uint8Array) => Promise<Record<string, unknown>>;
    };
    const key = new Uint8Array(32);
    assert.deepEqual(await client.encryptThinkingFields({}, key), {});
    assert.deepEqual(await client.encryptThinkingFields({ thinking_content: "  ", has_thinking: true }, key), {});
    const stored = await client.encryptThinkingFields({ thinking_content: "Observed fixture reasoning" }, key);
    assert.equal(stored.has_thinking, true);
    assert.equal("thinking_token_count" in stored, false);
    assert.equal("thinking_duration_seconds" in stored, false);
    await assert.rejects(client.encryptThinkingFields({ thinking_content: 1 }, key), /Invalid completion/);
    await assert.rejects(client.encryptThinkingFields({ thinking_content: "x", thinking_token_count: -1 }, key), /Invalid completion/);
  });

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery
  it("reconciles a stale discovered embed only with owner-bound ACK and decrypted canonical bytes", async () => {
    const identity = outputVector.identity;
    const output: AvailableRecoveryOutputFrame = {
      record_id: identity.record_id, root_chat_id: identity.root_chat_id,
      target_chat_id: identity.target_chat_id, turn_id: identity.turn_id,
      subject_id: identity.subject_id, output_kind: "embed",
      output_version: 1, chat_key_version: identity.key_version,
    };
    const rawKey = new Uint8Array(Buffer.from(keyVector.chat_key, "base64url"));
    const embedKey = await deriveEmbedKeyFromChatKey(rawKey, output.subject_id);
    const encryptedContent = await encryptWithAesGcmCombined(toonEncode({ type: "code", code: "verified source" }), embedKey);
    const encryptedType = await encryptWithAesGcmCombined("code", embedKey);
    const digest = createHash("sha256").update(encryptedContent).digest("hex");
    const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
    client.session = { sessionId: "fixture", hashedEmail: "fixture", activeTeamId: null, apiUrl: "http://fixture.invalid", createdAt: 1, masterKeyExportedB64: "fixture" };
    client.getMasterKeyBytes = () => new Uint8Array(32);
    client.getChatWrappingKey = async () => new Uint8Array(32);
    client.resolveChatKey = async () => rawKey;
    client.getCliRequestHeaders = () => ({});
    let canonicalContent = encryptedContent;
    client.http = { get: async () => ({ ok: true, status: 200, data: { embed: {
      hashed_chat_id: createHash("sha256").update(output.target_chat_id).digest("hex"),
      version_number: 1, parent_embed_id: null, encrypted_content: canonicalContent, encrypted_type: encryptedType,
    } } }) };
    let statusVerified = true;
    let statusSubject = output.subject_id;
    const sent: string[] = [];
    const ws = {
      waitForMessage: (type: string, predicate: (value: unknown) => boolean) => {
        if (type === "recovery_output_ready") return Promise.reject(new WebSocketProtocolError(
          "recovery_output_not_found", "Output no longer pending",
        ));
        assert.equal(type, "recovery_output_status_ready");
        return new Promise((resolve) => { statusWaiter = (payload: Record<string, unknown>) => {
          assert.equal(predicate(payload), true);
          resolve({ payload });
        }; });
      },
      sendAsync: async (type: string, payload: Record<string, unknown>) => {
        sent.push(type);
        if (type === "recovery_output_status") statusWaiter({
          ...output, subject_id: statusSubject, root_hashed_team_id: null,
          message_role: null, state: "ACKNOWLEDGED", canonical_verified: statusVerified,
          canonical_digest: digest, canonical_source: "head", request_id: payload.request_id,
        });
      },
    };
    let statusWaiter!: (payload: Record<string, unknown>) => void;
    const cache = { chats: [{ details: { id: output.root_chat_id }, messages: [] }] };
    const replay = client.persistAvailableRecoveryOutputs as PersistAvailableOutputs;
    assert.equal(await replay.call(client, ws, identity.owner_id, cache, [output], null), 1);
    assert.deepEqual(sent, ["recovery_output_get", "recovery_output_status"]);
    statusVerified = false;
    await assert.rejects(replay.call(client, ws, identity.owner_id, cache, [output], null), /lacks verified canonical acknowledgement/);
    statusVerified = true;
    statusSubject = "unrelated-embed";
    await assert.rejects(replay.call(client, ws, identity.owner_id, cache, [output], null), /status identity mismatch: subject_id/);
    statusSubject = output.subject_id;
    canonicalContent = await encryptWithAesGcmCombined(toonEncode({ type: "code", code: "different" }), embedKey);
    await assert.rejects(replay.call(client, ws, identity.owner_id, cache, [output], null), /canonical head digest differs/);
  });
  // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("loads and caches verified chat history when canonical recovery reread is unavailable", async () => {
    const previous = process.env.OPENMATES_STATE_DIR;
    const directory = mkdtempSync(join(tmpdir(), "tui-pending-recovery-"));
    process.env.OPENMATES_STATE_DIR = directory;
    try {
      const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
      client.resolveTeamContext = () => null;
      client.session = { sessionId: "fixture", hashedEmail: "fixture", activeTeamId: null, apiUrl: "http://fixture.invalid", createdAt: 1, masterKeyExportedB64: "fixture" };
    client.getMasterKeyBytes = () => new Uint8Array(32);
      client.getChatWrappingKey = async () => new Uint8Array(32);
      client.hasSession = () => true;
      client.session = { apiUrl: "http://localhost", sessionId: "recovery-fixture", hashedEmail: "owner-hash",
        masterKeyExportedB64: "fixture-key", createdAt: 1 };
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
    client.session = { sessionId: "fixture", hashedEmail: "fixture", activeTeamId: null, apiUrl: "http://fixture.invalid", createdAt: 1, masterKeyExportedB64: "fixture" };
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
    assert.deepEqual(lookups, [], "current-turn recovery leaves unrelated roots pending");
    await replay.call(client, ws, identity.owner_id, [[old]], cache, null, active.root_chat_id);
    assert.deepEqual(lookups, [], "unrelated-only pages do not perform current-turn key lookups");
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
  for (const withThinking of [false, true]) {
  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted,chats.message.identity-idempotent
  it(`persists the sealed child ${role} message ${withThinking ? "with" : "without"} thinking before its canonical ACK`, async () => {
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
      content: { role, content: "sealed child output", category: null, model_name: null, created_at: 1_700_000_000,
        ...(withThinking ? { thinking_content: "Observed fixture reasoning", thinking_signature: "fixture signature", thinking_token_count: 7 } : {}),
      },
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
    client.session = { sessionId: "fixture", hashedEmail: "fixture", activeTeamId: null, apiUrl: "http://fixture.invalid", createdAt: 1, masterKeyExportedB64: "fixture" };
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
    if (withThinking && role === "assistant") {
      assert.equal(await decryptWithAesGcmCombined(String(encrypted.encrypted_thinking_content), rawKey), "Observed fixture reasoning");
      assert.equal(await decryptWithAesGcmCombined(String(encrypted.encrypted_thinking_signature), rawKey), "fixture signature");
      assert.equal(encrypted.has_thinking, true);
      assert.equal(encrypted.thinking_token_count, 7);
      assert.equal(JSON.stringify(persisted).includes("Observed fixture reasoning"), false);
    } else {
      assert.equal("encrypted_thinking_content" in encrypted, false);
      assert.equal("has_thinking" in encrypted, false);
    }
    assert.equal(encrypted.chat_id, output.target_chat_id);
    assert.ok(typeof persisted?.encrypted_chat_key === "string");
    assert.equal(JSON.stringify(persisted).includes("sealed child output"), false);
  });
  }
  }

  for (const bootstrap of ["none", "same-key", "different-key"] as const) {
  // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted,chats.message.identity-idempotent
  it(`recovers both child message roles with immutable envelopes (${bootstrap})`, async () => {
    const identity = outputVector.identity;
    const rawKey = new Uint8Array(Buffer.from(keyVector.chat_key, "base64url"));
    const wrappingKey = new Uint8Array(32);
    const outputs: AvailableRecoveryOutputFrame[] = ["user", "assistant"].map((role, index) => ({
      record_id: index ? "77777777-7777-4777-8777-777777777777" : identity.record_id,
      root_chat_id: identity.root_chat_id, target_chat_id: identity.target_chat_id,
      turn_id: identity.turn_id,
      subject_id: index ? "88888888-8888-4888-8888-888888888888" : identity.subject_id,
      output_kind: "message", output_version: 1, chat_key_version: identity.key_version,
      root_hashed_team_id: null, message_role: role as "user" | "assistant",
    }));
    const sealed = new Map<string, string>();
    for (const [index, output] of outputs.entries()) {
      const nonce = Buffer.from(keyVector.nonce, "base64url");
      nonce[0] ^= index;
      sealed.set(output.record_id, JSON.stringify(await sealRecoveryOutputEnvelopeForTest(
        new TextEncoder().encode(JSON.stringify({
          record_id: output.record_id, target_chat_id: output.target_chat_id,
          subject_id: output.subject_id, output_kind: output.output_kind, output_version: 1,
          content: { role: output.message_role, content: `sealed ${output.message_role}`, created_at: 1_700_000_000 },
        })), {
          ownerId: identity.owner_id, rootChatId: output.root_chat_id,
          targetChatId: output.target_chat_id, turnId: output.turn_id,
          recordId: output.record_id, subjectId: output.subject_id,
          outputKind: "message", outputVersion: 1, keyVersion: output.chat_key_version,
          recoveryPublicKey: keyVector.recovery_public_key,
          ephemeralPrivateKey: keyVector.ephemeral_private_key, nonce: nonce.toString("base64url"),
        },
      )));
    }
    const client = Object.create(OpenMatesClient.prototype) as Record<string, any>;
    client.session = { sessionId: "fixture", hashedEmail: "fixture", activeTeamId: null,
      apiUrl: "http://fixture.invalid", createdAt: 1, masterKeyExportedB64: "fixture" };
    client.getMasterKeyBytes = () => wrappingKey;
    client.getChatWrappingKey = async () => wrappingKey;
    client.resolveChatKey = async () => rawKey;
    const waiters: Array<{ type: string; predicate: (value: any) => boolean;
      resolve: (value: any) => void; reject: (error: Error) => void }> = [];
    let canonicalKey: string | null = null, messagesVersion = 0;
    let bootstrapPending = bootstrap !== "none";
    const attempts: Array<Record<string, any>> = [], accepted: Array<Record<string, any>> = [];
    const failures: string[] = [];
    const ws = {
      waitForMessage: (type: string, predicate: (value: any) => boolean) =>
        new Promise((resolve, reject) => waiters.push({ type, predicate, resolve, reject })),
      sendAsync: async (type: string, payload: Record<string, any>) => {
        const output = outputs.find(item => item.record_id === payload.record_id)!;
        const responseType = type === "recovery_output_get" ? "recovery_output_ready" : "recovery_output_persisted";
        const response: Record<string, any> = { record_id: output.record_id, request_id: payload.request_id };
        const waiterIndex = waiters.findIndex(item => item.type === responseType && item.predicate(response));
        assert.ok(waiterIndex >= 0);
        const waiter = waiters.splice(waiterIndex, 1)[0];
        if (type === "recovery_output_get") {
          waiter.resolve({ payload: { ...response, ...output, sealed_payload: sealed.get(output.record_id),
            messages_v: messagesVersion, encrypted_chat_key: canonicalKey, encrypted_title: null } });
          return;
        }
        assert.equal(type, "recovery_output_persist_message");
        attempts.push(payload);
        if (bootstrapPending) {
          bootstrapPending = false;
          canonicalKey = await encryptBytesWithAesGcm(bootstrap === "same-key" ? rawKey : new Uint8Array(32).fill(9), wrappingKey);
        }
        const code = canonicalKey && payload.encrypted_chat_key && payload.encrypted_chat_key !== canonicalKey
          ? "immutable_chat_key_mismatch" : payload.expected_messages_v !== messagesVersion ? "version_conflict" : null;
        if (code) {
          failures.push(code);
          waiter.reject(new WebSocketProtocolError(code, "Fixture recovery rejected"));
          return;
        }
        canonicalKey ??= payload.encrypted_chat_key;
        assert.equal(typeof canonicalKey, "string");
        const message = payload.encrypted_user_message ?? payload.encrypted_assistant_message;
        assert.equal(await decryptWithAesGcmCombined(message.encrypted_content, rawKey), `sealed ${message.role}`);
        accepted.push(message);
        waiter.resolve({ payload: { ...response, state: "ACKNOWLEDGED", committed_messages_v: ++messagesVersion } });
      },
    };
    const cache = { chats: [{ details: { id: identity.root_chat_id }, messages: [] }], embeds: [], embedKeys: [] };
    const pending = (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, outputs, null);
    if (bootstrap === "different-key") {
      await assert.rejects(pending, /child chat key differs/);
      assert.equal(accepted.length, 0);
      assert.equal(attempts.length, 1, "A different canonical raw key must never be overwritten or retried");
    } else {
      assert.equal(await pending, 2);
      assert.deepEqual(accepted.map(message => message.role), ["user", "assistant"]);
      if (bootstrap === "none") {
        assert.equal(attempts[0].encrypted_chat_key, attempts[1].encrypted_chat_key,
          "Prepared outputs reuse the exact acknowledged envelope, including its nonce");
      }
      assert.equal(attempts.at(-1)!.encrypted_chat_key, undefined, "Refreshed canonical metadata omits bootstrap fields");
      assert.ok(failures.includes("version_conflict"));
    }
    if (bootstrap !== "none") assert.equal(failures[0], "immutable_chat_key_mismatch");
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
      task_id: "66666666-6666-4666-8666-666666666666",
      file_path: "src/recovered.ts", content_hash: "a".repeat(64),
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
    client.session = { sessionId: "fixture", hashedEmail: "fixture", activeTeamId: null, apiUrl: "http://fixture.invalid", createdAt: 1, masterKeyExportedB64: "fixture" };
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
    let ackConflict = false;
    const sent: string[] = [];
    const digest = (value: string) => createHash("sha256").update(value).digest("hex");
    let availabilityResponse: unknown = null;
    let preStoreGets = 0;
    client.http = {
      post: async (path: string, body: unknown) => {
        assert.ok(path.endsWith(`/chats/${output.target_chat_id}/references/availability`));
        assert.deepEqual(body, { embed_ids: [output.subject_id] });
        return availabilityResponse ?? { ok: true, status: 200,
          data: { results: [{ embed_id: output.subject_id, state: stored ? "ready" : "missing" }] } };
      },
      get: async (path: string) => {
      if (!stored && !parentId) preStoreGets++;
      return path.includes("/versions/1?")
      ? { ok: true, status: 200, data: { embed_id: output.subject_id,
        version_number: 1, rows: [{ version_number: 1, encrypted_snapshot: historicalSnapshot, encrypted_patch: null }] } }
      : parentId && path.includes(`/embeds/${parentId}`) && wrappers.length ? { ok: true, status: 200, data: { embed: {
        embed_id: parentId, hashed_chat_id: createHash("sha256").update(output.target_chat_id).digest("hex"),
      }, embed_keys: wrappers } }
      : stored && wrappers.length ? { ok: true, status: 200, data: { embed: { ...stored, hashed_embed_id: digest(output.subject_id) }, embed_keys: wrappers } }
        : { ok: false, status: 404, data: {} }; } };
    let terminalReplay = false;
    const terminalFrames: string[] = [];
    const pending: Array<{ type: string; resolve: (value: unknown) => void; reject: (error: Error) => void }> = [];
    const ws = {
      waitForMessage: (type: string, predicate: (value: unknown) => boolean) => new Promise((resolve, reject) => {
        pending.push({ type, reject, resolve: (value: unknown) => { if (predicate((value as { payload: unknown }).payload)) resolve(value); } });
      }),
      sendAsync: async (type: string, payload: Record<string, unknown>) => {
        if (terminalReplay) {
          terminalFrames.push(type);
          assert.equal(type, "store_embed");
          const index = pending.findIndex((item) => item.type === "store_embed_confirmed");
          const waiter = pending.splice(index, 1)[0];
          assert.ok(waiter);
          waiter.reject(new WebSocketProtocolError("embed_write_denied", "ACKed canonical head"));
          return;
        }
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
          if (ackConflict) throw new WebSocketProtocolError("canonical_output_mismatch", "Another device acknowledged this output.");
        }
        const responseType: Record<string, string> = {
          recovery_output_get: "recovery_output_ready", store_embed: "store_embed_confirmed",
          store_embed_keys: "store_embed_keys_confirmed", recovery_output_ack_embed: "recovery_output_embed_acknowledged",
          recovery_output_status: "recovery_output_status_ready",
        };
        const typeToSend = responseType[type];
        assert.ok(typeToSend);
        const responsePayload = type === "recovery_output_get"
          ? { ...output, sealed_payload: JSON.stringify(sealed), messages_v: 1, encrypted_chat_key: "wrapped" }
          : type === "store_embed" ? { embed_id: output.subject_id,
            canonical_digest: digest(String(stored?.encrypted_content)), canonical_source: "head" }
            : type === "store_embed_keys" ? { created_count: (payload.keys as unknown[]).length,
              failed_count: 0, requested_count: (payload.keys as unknown[]).length }
              : type === "recovery_output_status" ? { ...output, root_hashed_team_id: null,
                message_role: null, state: "ACKNOWLEDGED", canonical_verified: true,
                canonical_digest: historicalSnapshot
                  ? digest(JSON.stringify([historicalSnapshot, null])) : digest(String(stored?.encrypted_content)),
                canonical_source: historicalSnapshot ? "version_row" : "head" }
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
    if (!child) {
      // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
      for (const response of [
        { ok: false, status: 503 }, { ok: true, status: 200, data: {} },
        { ok: true, status: 200, data: { results: [] } },
        { ok: true, status: 200, data: { results: [{ embed_id: "foreign", state: "missing" }] } },
        { ok: true, status: 200, data: { results: [{ embed_id: output.subject_id, state: "unknown" }] } },
        { ok: true, status: 200, data: { results: [{ embed_id: output.subject_id, state: "unusable" }] } },
        { ok: true, status: 200, data: { results: [
          { embed_id: output.subject_id, state: "missing" }, { embed_id: output.subject_id, state: "ready" },
        ] } },
      ]) {
        availabilityResponse = response;
        await assert.rejects((client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null), /availability|unusable/);
        assert.equal(sent.some((type) => ["store_embed", "store_embed_keys", "recovery_output_ack_embed"].includes(type)), false);
      }
      availabilityResponse = null;
    }
    assert.equal(await (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null), 1);
    assert.equal(await (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null), 1);
    assert.equal(sent.filter((type) => type === "store_embed").length, 1);
    if (!child) assert.equal(preStoreGets, 0, "fresh root must not use a failing existence GET");
    assert.equal(stored?.hashed_task_id, digest(content.task_id));
    assert.equal(stored?.file_path, content.file_path);
    assert.equal(stored?.content_hash, content.content_hash);
    assert.equal(sent.filter((type) => type === "store_embed_keys").length, 1);
    assert.equal(sent.filter((type) => type === "recovery_output_ack_embed").length, 2);
    if (!child) {
      // Recovery can win before the terminal send_embed_data repeats this same
      // real producer metadata. Its first write must need no legacy repair.
      const originalCiphertext = stored!.encrypted_content;
      terminalReplay = true;
      await (client.persistStreamedEmbeds as (params: unknown) => Promise<void>).call(client, {
        ws, embeds: [{ ...content, status: "finished" }], chatId: output.target_chat_id,
        chatKeyBytes: rawKey, ownerId: identity.owner_id, fallbackMessageId: content.message_id,
      });
      terminalReplay = false;
      assert.deepEqual(terminalFrames, ["store_embed"]);
      assert.equal(stored!.encrypted_content, originalCiphertext);
    }
    historicalSnapshot = await encryptWithAesGcmCombined("private recovered source", embedKey);
    stored!.version_number = 2;
    stored!.encrypted_content = await encryptWithAesGcmCombined("newer unrelated content", embedKey);
    assert.equal(await (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null), 1);
    assert.equal(sent.filter((type) => type === "store_embed").length, 1);
    assert.equal(sent.filter((type) => type === "recovery_output_ack_embed").length, 3);
    ackConflict = true;
    assert.equal(await (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null), 1);
    assert.equal(sent.filter((type) => type === "recovery_output_status").length, 1);
    ackConflict = false;
    wrappers[0].encrypted_embed_key = await encryptBytesWithAesGcm(new Uint8Array(32), new Uint8Array(32));
    await assert.rejects(
      (client.persistAvailableRecoveryOutputs as PersistAvailableOutputs)(ws, identity.owner_id, cache, [output], null),
      /key wrapper does not match/,
    );
    assert.equal(sent.filter((type) => type === "recovery_output_ack_embed").length, 4);
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
    client.session = { sessionId: "fixture", hashedEmail: "fixture", activeTeamId: null, apiUrl: "http://fixture.invalid", createdAt: 1, masterKeyExportedB64: "fixture" };
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
    client.session = { sessionId: "fixture", hashedEmail: "fixture", activeTeamId: null, apiUrl: "http://fixture.invalid", createdAt: 1, masterKeyExportedB64: "fixture" };
    client.getMasterKeyBytes = () => new Uint8Array(32);
    client.getChatWrappingKey = async () => new Uint8Array(32);
    client.resolveChatKey = async () => rawKey;
    client.getCliRequestHeaders = () => ({});
    let diff: Record<string, unknown> | null = null;
    let wrappers: Array<Record<string, unknown>> = [];
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
    client.session = { sessionId: "fixture", hashedEmail: "fixture", activeTeamId: null, apiUrl: "http://fixture.invalid", createdAt: 1, masterKeyExportedB64: "fixture" };
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

// contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery,chats.persistence.client-encrypted
describe("CLI sealed parent dependencies", () => {
  const previousStateDir = process.env.OPENMATES_STATE_DIR;
  const stateDir = mkdtempSync(join(tmpdir(), "openmates-cli-parent-dependencies-"));
  before(() => { process.env.OPENMATES_STATE_DIR = stateDir; });
  after(() => {
    if (previousStateDir === undefined) delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR = previousStateDir;
    rmSync(stateDir, { recursive: true, force: true });
  });
  for (const scenario of ["same-page", "cross-page", "current-turn-cross-page", "orphan-head", "missing", "wrong-root", "wrong-target", "wrong-turn", "wrong-key-version", "wrong-team", "invalid-parent-wrapper", "cycle"] as const) {
    // contract-test: supporting surface=cli assertions=storage.background.complete-sealed-recovery
    it(`recovers parents before children without weakening scope: ${scenario}`, async () => {
      const identity = outputVector.identity;
      const parentId = "77777777-7777-4777-8777-777777777777";
      const messageId = "55555555-5555-4555-8555-555555555555";
      const child: AvailableRecoveryOutputFrame = {
        record_id: identity.record_id, root_chat_id: identity.root_chat_id,
        target_chat_id: identity.target_chat_id, turn_id: identity.turn_id,
        subject_id: identity.subject_id, output_kind: "embed", output_version: 1,
        chat_key_version: identity.key_version, root_hashed_team_id: null,
      };
      const parent: AvailableRecoveryOutputFrame = { ...child,
        record_id: "88888888-8888-4888-8888-888888888888", subject_id: parentId };
      if (scenario === "wrong-root") parent.root_chat_id = "99999999-9999-4999-8999-999999999999";
      if (scenario === "wrong-target") parent.target_chat_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
      if (scenario === "wrong-turn") parent.turn_id = "99999999-9999-4999-8999-999999999999";
      if (scenario === "wrong-key-version") parent.chat_key_version += 1;
      if (scenario === "wrong-team") parent.root_hashed_team_id = "a".repeat(64);
      const childContent = { embed_id: child.subject_id, version_number: 1, type: "website",
        content: toonEncode({ type: "website", url: "https://example.test/recovery" }),
        parent_embed_id: parentId, message_id: messageId };
      const parentContent = { embed_id: parentId, version_number: 1, type: "app_skill_use",
        content: toonEncode({ type: "app_skill_use", app_id: "web", skill_id: "search" }),
        parent_embed_id: scenario === "cycle" ? child.subject_id : null,
        embed_ids: [child.subject_id], message_id: messageId };
      const seal = async (output: AvailableRecoveryOutputFrame, content: unknown) => sealRecoveryOutputEnvelopeForTest(
        new TextEncoder().encode(JSON.stringify({ record_id: output.record_id,
          target_chat_id: output.target_chat_id, subject_id: output.subject_id,
          output_kind: output.output_kind, output_version: output.output_version, content })), {
          ownerId: identity.owner_id, rootChatId: output.root_chat_id,
          targetChatId: output.target_chat_id, turnId: output.turn_id,
          recordId: output.record_id, subjectId: output.subject_id,
          outputKind: output.output_kind, outputVersion: output.output_version,
          keyVersion: output.chat_key_version, recoveryPublicKey: keyVector.recovery_public_key,
          ephemeralPrivateKey: keyVector.ephemeral_private_key, nonce: keyVector.nonce,
        });
      const sealed = new Map([[child.record_id, await seal(child, childContent)],
        [parent.record_id, await seal(parent, parentContent)]]);
      const rawKey = new Uint8Array(Buffer.from(keyVector.chat_key, "base64url"));
      const master = new Uint8Array(32);
      const embedKey = await deriveEmbedKeyFromChatKey(rawKey, parentId);
      const hash = (value: string) => createHash("sha256").update(value).digest("hex");
      const heads = new Map<string, Record<string, unknown>>();
      const wrappers: Array<Record<string, unknown>> = [];
      let orphanCiphertext: string | null = null;
      if (scenario === "orphan-head") {
        orphanCiphertext = await encryptWithAesGcmCombined(childContent.content, embedKey);
        heads.set(child.subject_id, { ...childContent, encrypted_content: orphanCiphertext,
          encrypted_type: await encryptWithAesGcmCombined(childContent.type, embedKey),
          hashed_chat_id: hash(child.target_chat_id), hashed_message_id: hash(messageId) });
      }
      if (scenario === "invalid-parent-wrapper") {
        heads.set(parentId, { embed_id: parentId, hashed_chat_id: hash(child.target_chat_id), parent_embed_id: null });
        wrappers.push({ hashed_embed_id: hash(parentId), key_type: "master",
          encrypted_embed_key: await encryptBytesWithAesGcm(new Uint8Array(32), master) });
      }
      const client = Object.create(OpenMatesClient.prototype) as Record<string, unknown>;
      client.session = { sessionId: "fixture", hashedEmail: "fixture", activeTeamId: null, apiUrl: "http://fixture.invalid", createdAt: 1, masterKeyExportedB64: "fixture" };
    client.getMasterKeyBytes = () => master;
      client.getChatWrappingKey = async () => master;
      client.resolveChatKey = async () => rawKey;
      client.getCliRequestHeaders = () => ({});
      client.invalidateSyncedHistory = () => {};
      client.http = { post: async (_path: string, body: { embed_ids: string[] }) => ({
        ok: true, status: 200, data: { results: body.embed_ids.map((embed_id) => ({
          embed_id, state: heads.has(embed_id) ? "ready" : "missing",
        })) },
      }), get: async (path: string) => {
        const id = decodeURIComponent(path.split("/embeds/").at(-1)!.split("?")[0]);
        const head = heads.get(id);
        const keySubject = String(head?.parent_embed_id || id);
        const keys = wrappers.filter((row) => row.hashed_embed_id === hash(keySubject));
        if (!head || !keys.length || head.parent_embed_id && !heads.has(String(head.parent_embed_id))) {
          return { ok: false, status: 404, data: {} };
        }
        return { ok: true, status: 200, data: { embed: head, embed_keys: keys } };
      } };
      const frames: Array<{ type: string; payload: Record<string, unknown> }> = [];
      const pending: Array<{ type: string; predicate: (value: unknown) => boolean; resolve: (value: unknown) => void }> = [];
      const ws = {
        waitForMessage: (type: string, predicate: (value: unknown) => boolean) => new Promise(resolve => {
          pending.push({ type, predicate, resolve });
        }),
        sendAsync: async (type: string, payload: Record<string, unknown>) => {
          frames.push({ type, payload });
          let responseType: string, response: Record<string, unknown>;
          if (type === "recovery_output_get") {
            const output = payload.record_id === child.record_id ? child : parent;
            responseType = "recovery_output_ready";
            response = { ...output, sealed_payload: JSON.stringify(sealed.get(output.record_id)), messages_v: 1 };
          } else if (type === "store_embed") {
            if (payload.parent_embed_id) {
              assert.ok(heads.has(String(payload.parent_embed_id)), "child must never store before parent head");
              assert.equal(wrappers.length, 2, "parent wrappers must be readable before child storage");
            }
            heads.set(String(payload.embed_id), payload);
            responseType = "store_embed_confirmed";
            response = { embed_id: payload.embed_id, recovery_record_id: payload.recovery_record_id,
              canonical_source: "head", canonical_digest: hash(String(payload.encrypted_content)) };
          } else if (type === "store_embed_keys") {
            wrappers.push(...payload.keys as Array<Record<string, unknown>>);
            responseType = "store_embed_keys_confirmed";
            response = { failed_count: 0, created_count: (payload.keys as unknown[]).length, requested_count: (payload.keys as unknown[]).length };
          } else {
            assert.equal(type, "recovery_output_ack_embed");
            const output = payload.record_id === child.record_id ? child : parent;
            assert.equal(payload.canonical_digest, hash(String(heads.get(output.subject_id)?.encrypted_content)));
            responseType = "recovery_output_embed_acknowledged";
            response = { record_id: payload.record_id, state: "ACKNOWLEDGED" };
          }
          response.request_id = payload.request_id;
          const index = pending.findIndex(row => row.type === responseType && row.predicate(response));
          assert.ok(index >= 0, `matching receipt for ${type}`);
          pending.splice(index, 1)[0].resolve({ payload: response });
        },
      };
      const cache = { chats: [{ details: { id: child.root_chat_id }, messages: [] }], embeds: [], embedKeys: [] };
      const crossPage = scenario === "cross-page" || scenario === "current-turn-cross-page";
      const pages = scenario === "missing" ? [[child]] : crossPage ? [[child], [parent]] : [[child, parent]];
      const replay = () => scenario === "current-turn-cross-page"
        ? (client.replayCurrentTurnRecoveryOutputPages as ReplayCurrentTurnPages)(ws, identity.owner_id, pages, cache, null, child.root_chat_id)
        : (client.replayRecoveryOutputPages as ReplayOutputPages)(ws, identity.owner_id, pages, cache, null);
      const valid = ["same-page", "cross-page", "current-turn-cross-page", "orphan-head"].includes(scenario);
      if (!valid) {
        await assert.rejects(replay(), scenario === "invalid-parent-wrapper"
          ? /Existing canonical recovery embed identity was invalid/
          : /parent embed key scope|dependency is cyclic|Recovery Team|key wrapper does not match/);
        assert.equal(frames.some(row => ["store_embed", "store_embed_keys", "recovery_output_ack_embed"].includes(row.type)), false);
        assert.equal(heads.size, scenario === "invalid-parent-wrapper" ? 1 : 0);
      } else {
        const count = await replay();
        if (scenario !== "current-turn-cross-page") assert.equal(count, 2);
        assert.deepEqual(frames.filter(row => row.type === "recovery_output_ack_embed").map(row => row.payload.record_id),
          [parent.record_id, child.record_id]);
        assert.equal(frames.filter(row => row.type === "recovery_output_get" && row.payload.record_id === parent.record_id).length, 1);
        assert.deepEqual(frames.filter(row => row.type === "store_embed").map(row => row.payload.embed_id),
          scenario === "orphan-head" ? [parentId] : [parentId, child.subject_id]);
        assert.equal(await decryptWithAesGcmCombined(String(heads.get(child.subject_id)?.encrypted_content), embedKey), childContent.content);
        if (orphanCiphertext) assert.equal(heads.get(child.subject_id)?.encrypted_content, orphanCiphertext);
      }
    });
  }
});
