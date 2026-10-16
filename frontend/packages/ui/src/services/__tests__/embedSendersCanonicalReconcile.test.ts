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
  availabilityState: "ready",
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
vi.mock("../../message_parsing/utils", () => ({ computeSHA256: vi.fn(async (text: string) => `hash:${text}`) }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: { getKey: vi.fn(async () => new Uint8Array([3, 4])) } }));
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
          hashed_message_id: "hash:message-1", parent_embed_id: state.canonicalParent,
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
        request_id: payload.request_id, code: "embed_write_denied",
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

import { flushPendingEmbedOperations, sendStoreEmbedImpl } from "../embedSenders";

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
  state.queued.clear(); state.sent.length = 0; state.handlers.clear(); state.closeHandlers.clear();
  state.canonicalContent = "cipher:body:old"; state.canonicalType = "cipher:app_skill_use:old";
  state.canonicalPreview = null;
  state.canonicalChildren = null;
  state.canonicalStatus = "finished"; state.canonicalParent = null;
  state.canonicalWrappers = null;
  state.canonicalWrapper = "wrapper"; state.readStatus = 200; state.reads = 0;
  state.canonicalVersion = 1; state.canonicalOwner = "hash:user-1";
  state.availabilityState = "ready";
  state.localWrites.length = 0;
  state.historicalSource = "matching-source";
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: true, status: 200,
    json: async () => ({ results: [{ embed_id: "embed-1", state: state.availabilityState }] }),
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
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed"]);
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
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed"]);
    expect(state.queued.size).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it.each(["duplicate", "malformed", "wrong-chat"])("rejects a scoped %s canonical wrapper before skipping existing types", async (fault) => {
    const master = { ...keys.keys[0], encrypted_embed_key: "wrapper" };
    state.canonicalWrappers = [master, fault === "duplicate" ? { ...master }
      : { ...master, key_type: "chat", hashed_chat_id: fault === "wrong-chat" ? "hash:other-chat" : "hash:chat-1",
        encrypted_embed_key: fault === "malformed" ? null : "chat-wrapper" }];
    const original = JSON.stringify(state.canonicalWrappers);
    expect(await sendStoreEmbedImpl(service, payload, keys)).toBe(false);
    expect(JSON.stringify(state.canonicalWrappers)).toBe(original);
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed"]);
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
  it("settles an equivalent re-encrypted head against its owner-scoped canonical ciphertext", async () => {
    await sendStoreEmbedImpl(service, payload, keys);
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed"]);
    expect(state.reads).toBe(2);
    expect(state.queued.size).toBe(0);
    expect(state.localWrites).toHaveLength(1);
    expect(state.localWrites[0].encrypted_content).toBe("cipher:body:old");
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted
  it("keeps the ordinary v1 write path when its unfinished head is not yet readable", async () => {
    state.availabilityState = "unusable";
    await sendStoreEmbedImpl(service, payload, keys);
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed"]);
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
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed"]);
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
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed"]);
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
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed"]);
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
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed"]);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("retains a changed logical head for the versioned edit path", async () => {
    state.canonicalContent = "cipher:other:old";
    await sendStoreEmbedImpl(service, payload, keys);
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed"]);
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
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed"]);
    expect(state.queued.size).toBe(1);
    expect(state.localWrites).toEqual([]);
  });
});
