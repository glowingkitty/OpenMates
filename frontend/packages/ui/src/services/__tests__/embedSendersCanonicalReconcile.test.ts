import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StoreEmbedPayload } from "../../types/chat";

const state = vi.hoisted(() => ({
  queued: new Map<string, Record<string, unknown>>(),
  sent: [] as Array<{ type: string; payload: Record<string, unknown> }>,
  handlers: new Map<string, Set<(payload: unknown) => void>>(),
  closeHandlers: new Set<() => void>(),
  canonicalContent: "cipher:body:old",
  canonicalType: "cipher:app_skill_use:old",
  canonicalPreview: null as string | null | undefined,
  canonicalChildren: null as string[] | null | undefined,
  canonicalStatus: "finished",
  canonicalParent: null as string | null,
  canonicalWrapper: "wrapper",
  canonicalWrappers: null as Array<Record<string, unknown>> | null,
  canonicalVersion: 1,
  canonicalOwner: "hash:user-1",
  canonicalTask: null as string | null,
  availabilityState: "ready",
  parentAvailabilityState: "ready",
  acknowledged: true,
  writeState: "immutable",
  descriptor: true,
  writeError: "embed_write_denied",
  writeReason: undefined as string | undefined,
  descriptorForUnusable: false,
  uuidCounter: 0,
  masterReady: true,
  chatKeyReady: true,
  readStatus: 200,
  reads: 0,
  localWrites: [] as Array<Record<string, unknown>>,
  historicalSource: "matching-source",
}));

const emit = (type: string, payload: Record<string, unknown>) => {
  for (const listener of state.handlers.get(type) ?? []) listener(payload);
};

vi.mock("../db", () => ({ chatDB: {
  addPendingEmbedOperation: vi.fn(async (op: Record<string, unknown>) => state.queued.set(String(op.operation_id), op)),
  getPendingEmbedOperations: vi.fn(async () => Array.from(state.queued.values())),
  removePendingEmbedOperation: vi.fn(async (id: string) => state.queued.delete(id)),
  getRawChat: vi.fn(async (id: string) => id === "chat-1" ? { chat_id: id, team_id: null } : null),
} }));
vi.mock("../canonicalEmbedWriteCoordinator", () => ({
  assertCanonicalEmbedWriteLease: vi.fn(),
  withCanonicalEmbedWrite: vi.fn(async (embedId: string, write: (lease: unknown) => Promise<unknown>) =>
    write({ embedId })),
}));
vi.mock("../../message_parsing/utils", () => ({ computeSHA256: vi.fn(async (text: string) => text.startsWith("cipher:") ? "a".repeat(64) : `hash:${text}`) }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: { getKey: vi.fn(async () => state.chatKeyReady ? new Uint8Array([3, 4]) : null) } }));
vi.mock("../cryptoService", () => ({ getKeyFromStorage: vi.fn(async () => state.masterReady ? {} : null) }));
vi.mock("../encryption/MetadataEncryptor", () => ({
  decryptWithEmbedKey: vi.fn(async (encrypted: string) => encrypted.startsWith("cipher:")
    ? encrypted.split(":")[1] : null),
  unwrapEmbedKeyWithMasterKey: vi.fn(async (wrapped: string) => ["wrapper", "wrapper-new"].includes(wrapped)
    ? new Uint8Array([1, 2]) : null),
  unwrapEmbedKeyWithChatKey: vi.fn(async (wrapped: string) => ["chat-wrapper", "chat-wrapper-new"].includes(wrapped)
    ? new Uint8Array([1, 2]) : null),
}));
vi.mock("../embedStore", () => ({ embedStore: {
  getEmbedKey: vi.fn(async () => new Uint8Array([1, 2])),
  putEncrypted: vi.fn(async (_ref: string, embed: Record<string, unknown>) => { state.localWrites.push(embed); }),
} }));
vi.mock("../embedDiffStore", () => ({
  reconstructEncryptedVersionRows: vi.fn(async () => state.historicalSource),
}));
vi.mock("../recoveryEmbedSource", () => ({
  historySourceFromSealedEmbed: vi.fn(async () => "matching-source"),
}));
vi.mock("../../config/api", () => ({
  getApiEndpoint: (path: string) => `https://api.test${path}`,
  storageArchiveFetch: vi.fn(async (url: string) => {
    state.reads++;
    if (url.includes("/versions/")) return {
      ok: state.readStatus === 200, status: state.readStatus,
      json: async () => ({ embed_id: "embed-1",
        version_number: Number(url.match(/\/versions\/(\d+)/)?.[1]),
        rows: [{ version_number: 1, encrypted_snapshot: "cipher:old-source" },
          { version_number: 2, encrypted_patch: "cipher:patch-source" }]
          .filter((row) => row.version_number <= Number(url.match(/\/versions\/(\d+)/)?.[1])),
      }),
    };
    return {
      ok: state.readStatus === 200, status: state.readStatus,
      json: async () => ({
        embed: {
          embed_id: "embed-1", hashed_chat_id: "hash:chat-1", hashed_user_id: state.canonicalOwner,
          hashed_message_id: "hash:message-1", hashed_task_id: state.canonicalTask, parent_embed_id: state.canonicalParent,
          version_number: state.canonicalVersion, status: state.canonicalStatus, app_id: "web", skill_id: "search",
          encrypted_content: state.canonicalContent, encrypted_type: state.canonicalType,
          encrypted_text_preview: state.canonicalPreview,
          embed_ids: state.canonicalChildren,
        },
        embed_keys: state.canonicalWrappers ?? [{ hashed_embed_id: "hash:embed-1", hashed_user_id: "hash:user-1",
          hashed_chat_id: null, key_type: "master", encrypted_embed_key: state.canonicalWrapper }],
      }),
    };
  }),
}));
vi.mock("../websocketService", () => ({ webSocketService: {
  ownEmbedProtocolRequest: vi.fn((_requestId: string, listener: (payload: unknown) => void) => {
    const listeners = state.handlers.get("error") ?? new Set();
    listeners.add(listener); state.handlers.set("error", listeners);
    return () => { listeners.delete(listener); };
  }),
  on: vi.fn((type: string, listener: (payload: unknown) => void) => {
    const listeners = state.handlers.get(type) ?? new Set();
    listeners.add(listener); state.handlers.set(type, listeners);
  }),
  off: vi.fn((type: string, listener: (payload: unknown) => void) => state.handlers.get(type)?.delete(listener)),
  addEventListener: vi.fn((type: string, listener: () => void) => {
    if (type === "close") state.closeHandlers.add(listener);
  }),
  removeEventListener: vi.fn((type: string, listener: () => void) => {
    if (type === "close") state.closeHandlers.delete(listener);
  }),
  sendMessage: vi.fn(async (type: string, payload: Record<string, unknown>) => {
    state.sent.push({ type, payload });
    queueMicrotask(() => {
      if (type === "store_embed") emit("error", {
        request_id: payload.request_id, code: state.writeError, reason: state.writeReason,
      });
      if (type === "store_embed_keys") {
        const incoming = payload.keys as Array<Record<string, unknown>>;
        if (state.canonicalWrappers) {
          for (const wrapper of incoming) {
            const index = state.canonicalWrappers.findIndex((row) => row.key_type === wrapper.key_type);
            if (index < 0) state.canonicalWrappers.push({ ...wrapper });
            else state.canonicalWrappers[index] = { ...wrapper };
          }
        }
        emit("store_embed_keys_confirmed", {
          request_id: payload.request_id, created_count: incoming.length, failed_count: 0,
        });
      }
    });
  }),
} }));

import { flushPendingEmbedOperations, sendStoreEmbedImpl, sendStoreEmbedOperationImpl } from "../embedSenders";

const payload = {
  embed_id: "embed-1", chat_id: "chat-1", team_id: null,
  hashed_chat_id: "hash:chat-1", hashed_user_id: "hash:user-1",
  hashed_message_id: "hash:message-1", app_id: "web", skill_id: "search",
  encrypted_content: "cipher:body:new", encrypted_type: "cipher:app_skill_use:new",
  status: "finished", version_number: 1,
} as StoreEmbedPayload;
const keys = { keys: [{ key_type: "master", hashed_embed_id: "hash:embed-1",
  hashed_user_id: "hash:user-1", hashed_chat_id: null, encrypted_embed_key: "wrapper-new" }] };
const service = { webSocketConnected_FOR_SENDERS_ONLY: true } as never;

beforeEach(() => {
  state.uuidCounter = 0; state.masterReady = true; state.chatKeyReady = true;
  vi.mocked(crypto.randomUUID).mockImplementation(() => `canonical-op-${++state.uuidCounter}` as `${string}-${string}-${string}-${string}-${string}`);
  state.queued.clear(); state.sent.length = 0; state.handlers.clear(); state.closeHandlers.clear();
  state.canonicalContent = "cipher:body:old"; state.canonicalType = "cipher:app_skill_use:old";
  state.canonicalPreview = null;
  state.canonicalChildren = null;
  state.canonicalStatus = "finished"; state.canonicalParent = null;
  state.canonicalWrappers = null;
  state.canonicalWrapper = "wrapper"; state.readStatus = 200; state.reads = 0;
  state.canonicalVersion = 1; state.canonicalOwner = "hash:user-1"; state.canonicalTask = null;
  state.availabilityState = "ready";
  state.parentAvailabilityState = "ready";
  state.acknowledged = true;
  state.writeState = "immutable"; state.descriptor = true; state.writeError = "embed_write_denied"; state.writeReason = undefined; state.descriptorForUnusable = false;
  state.localWrites.length = 0;
  state.historicalSource = "matching-source";
  vi.stubGlobal("fetch", vi.fn(async (_url: string, options: { body: string }) => ({
    ok: true, status: 200,
    json: async () => ({ results: JSON.parse(options.body).embed_ids.map((embed_id: string, index: number) => ({
      embed_id, state: index === 0 ? state.availabilityState : state.parentAvailabilityState,
      ...(index === 0 && state.descriptor && (state.availabilityState === "ready" || state.descriptorForUnusable) ? { canonical_revision: {
        version: state.canonicalVersion, ciphertext_sha256: "a".repeat(64), write_state: state.writeState,
      } } : {}),
      ...(index === 0 && state.acknowledged ? { recovery_ack: {
        state: "ACKNOWLEDGED", version: JSON.parse(options.body).required_recovery_versions[embed_id], canonical_digest: "a".repeat(64),
      } } : {}),
    })) }),
  })));
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

describe("canonical embed conflict reconciliation", () => {

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("preserves bootstrap wrapper ciphertext through original v1 completion and sealed v2 reconciliation", async () => {
    state.canonicalWrappers = [
      { ...keys.keys[0], encrypted_embed_key: "wrapper" },
      { ...keys.keys[0], key_type: "chat", hashed_chat_id: "hash:chat-1", encrypted_embed_key: "chat-wrapper" },
    ];
    const original = JSON.stringify(state.canonicalWrappers);
    const replayKeys = { keys: [keys.keys[0],
      { ...keys.keys[0], key_type: "chat", hashed_chat_id: "hash:chat-1", encrypted_embed_key: "chat-wrapper-new" },
    ] };
    // The completion page repeats v1 after the CLI bootstrap has ACKed it.
    expect(await sendStoreEmbedImpl(service, payload, replayKeys)).toBe(true);
    expect(JSON.stringify(state.canonicalWrappers)).toBe(original);
    expect(state.sent).toEqual([]);
    // Typed CLI recovery advances the sealed head without replacing its keys;
    // the queued browser v2 must adopt that head and retain the same wrappers.
    state.canonicalVersion = 2;
    state.sent.length = 0;
    expect(await sendStoreEmbedImpl(service, { ...payload, version_number: 2 }, replayKeys)).toBe(true);
    expect(JSON.stringify(state.canonicalWrappers)).toBe(original);
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("adds only the missing permitted wrapper type to an equivalent canonical v1", async () => {
    state.canonicalWrappers = [{ ...keys.keys[0], encrypted_embed_key: "wrapper" }];
    const chatWrapper = { ...keys.keys[0], key_type: "chat", hashed_chat_id: "hash:chat-1", encrypted_embed_key: "chat-wrapper-new" };
    expect(await sendStoreEmbedImpl(service, payload, { keys: [keys.keys[0], chatWrapper] })).toBe(true);
    const sent = state.sent.filter((entry) => entry.type === "store_embed_keys");
    expect(sent).toHaveLength(1);
    expect(sent[0].payload.keys).toEqual([chatWrapper]);
    expect(state.canonicalWrappers[0].encrypted_embed_key).toBe("wrapper");
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("rejects a mismatched canonical chat wrapper even when its master wrapper matches", async () => {
    state.canonicalWrappers = [{ ...keys.keys[0], encrypted_embed_key: "wrapper" },
      { ...keys.keys[0], key_type: "chat", hashed_chat_id: "hash:chat-1", encrypted_embed_key: "wrong-key" }];
    const original = JSON.stringify(state.canonicalWrappers);
    expect(await sendStoreEmbedImpl(service, payload, keys)).toBe(false);
    expect(JSON.stringify(state.canonicalWrappers)).toBe(original);
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it.each(["conflicting-duplicate", "malformed", "wrong-chat", "foreign-scope", "oversized"])("rejects a scoped %s canonical wrapper before skipping existing types", async (fault) => {
    const master = { ...keys.keys[0], encrypted_embed_key: "wrapper" };
    state.canonicalWrappers = [master, fault === "conflicting-duplicate" ? { ...master, encrypted_embed_key: "other-wrapper" }
      : { ...master, key_type: "chat", hashed_chat_id: fault === "wrong-chat" ? "hash:other-chat" : "hash:chat-1",
        encrypted_embed_key: fault === "malformed" ? null : "chat-wrapper",
        ...(fault === "foreign-scope" ? { hashed_project_id: "foreign" } : {}) }];
    if (fault === "oversized") state.canonicalWrappers = Array(129).fill(master);
    const original = JSON.stringify(state.canonicalWrappers);
    expect(await sendStoreEmbedImpl(service, payload, keys)).toBe(false);
    expect(JSON.stringify(state.canonicalWrappers)).toBe(original);
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(1);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("defers a streamed root v2 behind v1 and settles only after canonical v2 recovery", async () => {
    const v2 = { ...payload, version_number: 2 };
    expect(await sendStoreEmbedImpl(service, v2, keys)).toBe(false);
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(1);
    expect(state.localWrites).toEqual([]);
    state.canonicalVersion = 2;
    await flushPendingEmbedOperations();
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(0);
    expect(state.localWrites).toHaveLength(1);
    expect(state.localWrites[0].encrypted_content).toBe("cipher:body:old");
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("defers v3 behind v2, then adopts exact canonical v3 without a recipher write", async () => {
    state.canonicalVersion = 2;
    const v3 = { ...payload, version_number: 3 };
    expect(await sendStoreEmbedImpl(service, v3, keys)).toBe(false);
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(1);
    state.canonicalVersion = 3;
    await flushPendingEmbedOperations();
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(0);
    expect(state.localWrites).toHaveLength(1);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery
  it("retains a v3 queue entry when the canonical head has a version gap", async () => {
    state.canonicalVersion = 1;
    expect(await sendStoreEmbedImpl(service, { ...payload, version_number: 3 }, keys)).toBe(false);
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(1);
    expect(state.localWrites).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each([[1, 2], [2, 3]])("settles old queued v%s against exact historical source after head v%s", async (queued, current) => {
    state.canonicalVersion = current;
    expect(await sendStoreEmbedImpl(service, { ...payload, version_number: queued }, keys)).toBe(true);
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(0);
    expect(state.localWrites).toHaveLength(1);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery
  it("keeps an old queued root if historical source reconstruction differs", async () => {
    state.canonicalVersion = 2;
    state.historicalSource = "different-source";
    expect(await sendStoreEmbedImpl(service, payload, keys)).toBe(false);
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(1);
    expect(state.localWrites).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each(["missing", "old", "foreign-owner", "foreign-parent", "changed-content"])(
    "retains queued root v2 without a matching canonical recovery (%s)", async (condition) => {
      if (condition === "missing") state.availabilityState = "missing";
      if (condition === "foreign-owner") state.canonicalOwner = "hash:other";
      if (condition === "foreign-parent") state.canonicalParent = "other-parent";
      if (condition === "changed-content") state.canonicalContent = "cipher:other:old";
      if (condition === "changed-content") state.canonicalVersion = 2;
      expect(await sendStoreEmbedImpl(service, { ...payload, version_number: 2 }, keys)).toBe(false);
      await flushPendingEmbedOperations();
      expect(state.sent).toEqual([]);
      expect(state.queued.size).toBe(1);
      expect(state.localWrites).toEqual([]);
    },
  );
  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("settles an equivalent re-encrypted v1 before any write or denial, including reconnect flush", async () => {
    await sendStoreEmbedImpl(service, payload, keys);
    expect(state.sent).toEqual([]);
    expect(state.reads).toBe(1);
    expect(state.queued.size).toBe(0);
    expect(state.localWrites).toHaveLength(1);
    expect(state.localWrites[0].encrypted_content).toBe("cipher:body:old");
    await flushPendingEmbedOperations();
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted
  it("defers a v1 write when its unfinished head has no canonical descriptor", async () => {
    state.availabilityState = "unusable";
    await sendStoreEmbedImpl(service, payload, keys);
    expect(state.sent).toEqual([]);
    expect(Array.from(state.queued.values())[0].state).toBe("pending");
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each([
    ["null/null", null, null],
    ["null/undefined", null, undefined],
    ["undefined/null", undefined, null],
    ["undefined/undefined", undefined, undefined],
    ["same decryptable preview", "cipher:preview:new", "cipher:preview:old"],
  ] as const)("settles an equivalent optional preview (%s)", async (_label, queued, canonical) => {
    state.canonicalPreview = canonical;
    await sendStoreEmbedImpl(service, {
      ...payload, encrypted_text_preview: queued,
    } as unknown as StoreEmbedPayload, keys);
    expect(state.queued.size).toBe(0);
    expect(state.localWrites).toHaveLength(1);
    expect(state.sent).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each([
    ["null/null", null, null],
    ["null/undefined", null, undefined],
    ["null/empty", null, []],
    ["empty/null", [], null],
    ["empty/undefined", [], undefined],
    ["empty/empty", [], []],
    ["same ordered children", ["child-a", "child-b"], ["child-a", "child-b"]],
  ] as const)("settles an equivalent canonical child list (%s)", async (_label, queued, canonical) => {
    state.canonicalChildren = canonical == null ? canonical : [...canonical];
    await sendStoreEmbedImpl(service, {
      ...payload, embed_ids: queued,
    } as unknown as StoreEmbedPayload, keys);
    expect(state.queued.size).toBe(0);
    expect(state.localWrites).toHaveLength(1);
    expect(state.localWrites[0].encrypted_content).toBe("cipher:body:old");
    expect(state.sent).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each([
    ["removed canonical children", null, ["child-a"]],
    ["added queued children", ["child-a"], null],
    ["changed child identity", ["child-a"], ["child-b"]],
    ["changed child order", ["child-b", "child-a"], ["child-a", "child-b"]],
  ] as const)("retains a queued write with %s", async (_label, queued, canonical) => {
    state.canonicalChildren = canonical == null ? canonical : [...canonical];
    await sendStoreEmbedImpl(service, {
      ...payload, embed_ids: queued,
    } as unknown as StoreEmbedPayload, keys);
    expect(state.queued.size).toBe(1);
    expect(state.localWrites).toEqual([]);
    expect(state.sent).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each([
    ["missing queued preview", undefined, "cipher:preview:old"],
    ["missing canonical preview", "cipher:preview:new", null],
    ["changed preview", "cipher:changed:new", "cipher:preview:old"],
    ["unreadable preview", "cipher:preview:new", "invalid"],
    ["both unreadable previews", "invalid-queued", "invalid-canonical"],
  ] as const)("retains a queued write when optional preview is %s", async (_label, queued, canonical) => {
    state.canonicalPreview = canonical;
    await sendStoreEmbedImpl(service, {
      ...payload, encrypted_text_preview: queued,
    } as unknown as StoreEmbedPayload, keys);
    expect(state.queued.size).toBe(1);
    expect(state.localWrites).toEqual([]);
    expect(state.sent).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("retains a changed logical head for the versioned edit path", async () => {
    state.canonicalContent = "cipher:other:old";
    await sendStoreEmbedImpl(service, payload, keys);
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(1);
    expect(state.localWrites).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("does not send or settle without an authorized canonical read", async () => {
    state.readStatus = 403;
    await sendStoreEmbedImpl(service, payload, keys);
    expect(state.queued.size).toBe(1);
    expect(state.sent).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("does not settle when the canonical wrapper or parent identity differs", async () => {
    state.canonicalWrapper = "other-wrapper";
    await sendStoreEmbedImpl(service, payload, keys);
    expect(state.queued.size).toBe(1);
    state.queued.clear();
    state.canonicalWrapper = "wrapper"; state.canonicalParent = "other-parent";
    await sendStoreEmbedImpl(service, payload, keys);
    expect(state.queued.size).toBe(1);
    expect(state.localWrites).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("does not rotate canonical wrappers to a different key after an equivalent head", async () => {
    const unsafeKeys = { keys: [{ ...keys.keys[0], encrypted_embed_key: "other-wrapper" }] };
    await sendStoreEmbedImpl(service, payload, unsafeKeys);
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(1);
    expect(state.localWrites).toEqual([]);
  });
});


describe("historical parent wrappers and child queue replay", () => {
  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each([false, true])("verifies every equivalent historical wrapper without rewriting (child=%s)", async (child) => {
    const parentId = child ? "parent-1" : null;
    state.canonicalParent = parentId;
    state.canonicalWrappers = ["wrapper", "wrapper-new"].map((encrypted_embed_key) => ({
      ...keys.keys[0], hashed_embed_id: `hash:${parentId || payload.embed_id}`, encrypted_embed_key,
    }));
    const before = JSON.stringify(state.canonicalWrappers);
    expect(await sendStoreEmbedImpl(service, { ...payload, parent_embed_id: parentId || undefined }, child ? undefined : keys)).toBe(true);
    await flushPendingEmbedOperations();
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(0);
    expect(state.localWrites).toHaveLength(1);
    expect(JSON.stringify(state.canonicalWrappers)).toBe(before);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("retains an unreadable child across reconnects and adopts it when its parent is readable", async () => {
    state.canonicalParent = "parent-1";
    state.canonicalWrappers = [{ ...keys.keys[0], hashed_embed_id: "hash:parent-1", encrypted_embed_key: "wrapper" }];
    state.availabilityState = "unusable";
    state.parentAvailabilityState = "unusable";
    const child = { ...payload, parent_embed_id: "parent-1" };
    expect(await sendStoreEmbedImpl(service, child)).toBe(false);
    await flushPendingEmbedOperations();
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(1);
    expect(state.localWrites).toEqual([]);
    state.availabilityState = "ready";
    state.parentAvailabilityState = "ready";
    await flushPendingEmbedOperations();
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(0);
    expect(state.localWrites[0].encrypted_content).toBe("cipher:body:old");
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it.each([false, true])("preserves initial mutable writes before a recovery ACK (child=%s)", async (child) => {
    state.acknowledged = false;
    state.availabilityState = child ? "unusable" : "ready";
    state.writeState = "mutable";
    const { webSocketService } = await import("../websocketService");
    if (!child) vi.mocked(webSocketService.sendMessage).mockImplementationOnce(async (type, rawPayload) => {
      const payload = rawPayload as Record<string, unknown>;
      state.sent.push({ type, payload });
      emit("store_embed_confirmed", { ...payload, canonical_digest: "a".repeat(64) });
    });
    expect(await sendStoreEmbedImpl(service, { ...payload, ...(child ? { parent_embed_id: "parent-1" } : {}) })).toBe(!child);
    expect(state.sent.map((entry) => entry.type)).toEqual(child ? [] : ["store_embed"]);
    expect(state.queued.size).toBe(child ? 1 : 0);
    if (!child) expect(state.sent[0].payload.canonical_precondition).toEqual({ version: 1, ciphertext_sha256: "a".repeat(64) });
  });
});


describe("durable canonical operation outcomes", () => {
  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("adopts a legacy null-v1 immutable head without relying on a recovery ACK", async () => {
    state.acknowledged = false;
    const { storageArchiveFetch } = await import("../../config/api");
    const original = vi.mocked(storageArchiveFetch).getMockImplementation()!;
    vi.mocked(storageArchiveFetch).mockImplementationOnce(async (...args) => {
      const response = await original(...args);
      const page = await response.json();
      page.embed.version_number = null;
      return { ...response, json: async () => page };
    });
    expect(await sendStoreEmbedOperationImpl(service, payload, keys)).toMatchObject({ status: "adopted" });
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("permits only proven read-only adoption without a descriptor or ACK", async () => {
    state.acknowledged = false; state.descriptor = false;
    expect(await sendStoreEmbedOperationImpl(service, payload, keys)).toMatchObject({ status: "adopted" });
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(0);
    state.canonicalContent = "cipher:changed:old";
    expect(await sendStoreEmbedOperationImpl(service, payload, keys)).toMatchObject({ status: "conflict" });
    await flushPendingEmbedOperations();
    expect(state.sent).toEqual([]);
    expect(Array.from(state.queued.values())[0]).toMatchObject({ state: "conflict", store_embed_payload: payload, store_embed_keys_payload: keys });
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("preserves original conflicting ciphertext and wrappers and skips it on reconnect", async () => {
    state.canonicalContent = "cipher:other:old";
    const result = await sendStoreEmbedOperationImpl(service, payload, keys);
    expect(result).toMatchObject({ status: "conflict", failure_code: "embed_content_or_type_conflict" });
    const retained = structuredClone(Array.from(state.queued.values())[0]);
    const reads = state.reads;
    await flushPendingEmbedOperations(); await flushPendingEmbedOperations();
    expect(state.reads).toBe(reads);
    expect(state.sent).toEqual([]);
    expect(Array.from(state.queued.values())[0]).toEqual(retained);
    expect(retained).toMatchObject({ operation_id: result.operation_id, state: "conflict", store_embed_payload: payload, store_embed_keys_payload: keys });
    // A new equivalent operation can settle without deleting the conflicting evidence.
    state.canonicalContent = "cipher:body:old";
    expect(await sendStoreEmbedOperationImpl(service, payload, keys)).toMatchObject({ status: "adopted" });
    expect(state.queued.size).toBe(1);
    expect(Array.from(state.queued.values())[0]).toEqual(retained);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each(["embed_revision_conflict", "embed_write_denied"])("retains terminal %s without reconnect retry", async (code) => {
    state.writeState = "mutable"; state.writeError = code;
    const result = await sendStoreEmbedOperationImpl(service, payload, keys);
    expect(result).toMatchObject({ status: code === "embed_write_denied" ? "denied" : "conflict", failure_code: code });
    expect(state.sent).toHaveLength(1);
    expect(state.sent[0].payload).toMatchObject({ canonical_precondition: { version: 1, ciphertext_sha256: "a".repeat(64) }, operation_id: result.operation_id });
    await flushPendingEmbedOperations();
    expect(state.sent).toHaveLength(1);
    expect(state.queued.size).toBe(1);
    expect(state.localWrites).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("retries a transient canonical read using the same durable operation identity", async () => {
    state.readStatus = 503;
    const result = await sendStoreEmbedOperationImpl(service, payload, keys);
    expect(result.status).toBe("waiting");
    expect(Array.from(state.queued.values())[0].operation_id).toBe(result.operation_id);
    state.readStatus = 200;
    await flushPendingEmbedOperations();
    expect(state.queued.size).toBe(0);
    expect(state.sent).toEqual([]);
    expect(state.localWrites).toHaveLength(1);
  });
});


describe("canonical reconciliation dependencies", () => {
  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each(["master", "chat"])("defers unavailable local %s keys without recording a semantic conflict", async (scope) => {
    if (scope === "master") state.masterReady = false;
    else {
      state.chatKeyReady = false;
      state.canonicalWrappers = [{ ...keys.keys[0], key_type: "chat", hashed_chat_id: "hash:chat-1", encrypted_embed_key: "chat-wrapper" }];
    }
    expect(await sendStoreEmbedOperationImpl(service, payload, keys)).toMatchObject({ status: "waiting" });
    expect(Array.from(state.queued.values())[0]).toMatchObject({ state: "pending", store_embed_keys_payload: keys });
    state.masterReady = true; state.chatKeyReady = true;
    await flushPendingEmbedOperations();
    expect(state.queued.size).toBe(0);
  });
});


describe("guarded initial completion", () => {
  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each([false, true])("completes a scoped mutable processing head with a descriptor (child=%s)", async (child) => {
    state.availabilityState = "unusable"; state.descriptorForUnusable = true;
    state.writeState = "mutable";
    const { webSocketService } = await import("../websocketService");
    vi.mocked(webSocketService.sendMessage).mockImplementationOnce(async (type, rawPayload) => {
      const payload = rawPayload as Record<string, unknown>;
      state.sent.push({ type, payload });
      emit("store_embed_confirmed", { ...payload, canonical_digest: "a".repeat(64) });
    });
    expect(await sendStoreEmbedOperationImpl(service, { ...payload, ...(child ? { parent_embed_id: "parent-1" } : {}) })).toMatchObject({ status: "persisted" });
    expect(state.sent).toHaveLength(1);
    expect(state.sent[0].payload.canonical_precondition).toEqual({ version: 1, ciphertext_sha256: "a".repeat(64) });
    expect(state.reads).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each(["canonical_precondition_mismatch", "acknowledged_embed_revision_immutable"])("adopts an equivalent completion after another consumer wins (%s)", async (reason) => {
    state.writeState = "mutable"; state.writeError = "embed_revision_conflict";
    state.writeReason = reason;
    expect(await sendStoreEmbedOperationImpl(service, payload, keys)).toMatchObject({ status: "adopted" });
    expect(state.sent.filter(row => row.type === "store_embed")).toHaveLength(1);
    expect(state.reads).toBe(1);
    expect(state.queued.size).toBe(0);
    expect(state.localWrites[0].encrypted_content).toBe("cipher:body:old");
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each(["different-content", "unavailable", "missing-wrapper"])("preserves evidence after a raced %s canonical read", async (mode) => {
    state.writeState = "mutable"; state.writeError = "embed_revision_conflict";
    state.writeReason = "canonical_precondition_mismatch";
    if (mode === "different-content") state.canonicalContent = "cipher:other:old";
    if (mode === "unavailable") state.readStatus = 404;
    if (mode === "missing-wrapper") state.canonicalWrappers = [];
    expect(await sendStoreEmbedOperationImpl(service, payload, keys)).toMatchObject({
      status: mode === "different-content" ? "conflict" : "waiting",
    });
    expect(state.sent).toHaveLength(1);
    expect(state.localWrites).toEqual([]);
    expect(Array.from(state.queued.values())[0].store_embed_payload).toEqual(payload);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each([
    ["canonical_precondition_mismatch", false], ["canonical_precondition_mismatch", true],
    ["acknowledged_embed_revision_immutable", false], ["acknowledged_embed_revision_immutable", true],
  ] as const)("keeps %s read-only across unavailable proof and reconnect (different=%s)", async (reason, different) => {
    state.writeState = "mutable"; state.writeError = "embed_revision_conflict";
    state.writeReason = reason; state.readStatus = 404;
    expect(await sendStoreEmbedOperationImpl(service, payload, keys)).toMatchObject({ status: "waiting" });
    expect(Array.from(state.queued.values())[0].failure_code).toBe(reason);
    state.readStatus = 200;
    if (different) state.canonicalContent = "cipher:other:old";
    // A second realm can begin flushing with a snapshot taken before the first
    // realm persisted the read-only marker. Honor the fresh queue row instead.
    const { chatDB } = await import("../db");
    vi.mocked(chatDB.getPendingEmbedOperations).mockResolvedValueOnce(
      Array.from(state.queued.values()).map(op => ({ ...op, failure_code: undefined })) as never,
    );
    await flushPendingEmbedOperations();
    expect(state.sent).toHaveLength(1);
    expect(state.queued.size).toBe(different ? 1 : 0);
    if (different) expect(Array.from(state.queued.values())[0]).toMatchObject({
      state: "conflict", failure_code: "embed_content_or_type_conflict",
    });
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each([null, "hash:task-1", "hash:other-task"])("reconciles optional legacy task metadata (%s)", async (canonicalTask) => {
    state.canonicalTask = canonicalTask;
    expect(await sendStoreEmbedOperationImpl(service, { ...payload, hashed_task_id: "hash:task-1" }, keys))
      .toMatchObject({ status: canonicalTask === "hash:other-task" ? "conflict" : "adopted" });
    expect(state.sent).toHaveLength(0);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it.each(["canonical_precondition_mismatch", "acknowledged_embed_revision_immutable", "embed_identity_or_version_conflict"])("rechecks retained %s conflicts without server writes", async (failure_code) => {
    const retained = { operation_id: "retained", embed_id: payload.embed_id,
      store_embed_payload: { ...payload, hashed_task_id: "hash:task-1" }, store_embed_keys_payload: keys,
      created_at: 1, state: "conflict", failure_code };
    state.queued.set("retained", retained);
    state.readStatus = 404;
    await flushPendingEmbedOperations();
    expect(state.queued.get("retained")).toEqual(retained);
    state.readStatus = 200;
    await flushPendingEmbedOperations();
    expect(state.queued.size).toBe(0);
    expect(state.sent).toHaveLength(0);
    expect(state.localWrites[0].encrypted_content).toBe("cipher:body:old");
  });
});
