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
  canonicalStatus: "finished",
  canonicalParent: null as string | null,
  canonicalWrapper: "wrapper",
  readStatus: 200,
  reads: 0,
  localWrites: [] as Array<Record<string, unknown>>,
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
vi.mock("../../message_parsing/utils", () => ({ computeSHA256: vi.fn(async (text: string) => `hash:${text}`) }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: { getKey: vi.fn(async () => null) } }));
vi.mock("../encryption/MetadataEncryptor", () => ({
  decryptWithEmbedKey: vi.fn(async (encrypted: string) => encrypted.startsWith("cipher:")
    ? encrypted.split(":")[1] : null),
  unwrapEmbedKeyWithMasterKey: vi.fn(async (wrapped: string) => ["wrapper", "wrapper-new"].includes(wrapped)
    ? new Uint8Array([1, 2]) : null),
  unwrapEmbedKeyWithChatKey: vi.fn(async () => null),
}));
vi.mock("../embedStore", () => ({ embedStore: {
  getEmbedKey: vi.fn(async () => new Uint8Array([1, 2])),
  putEncrypted: vi.fn(async (_ref: string, embed: Record<string, unknown>) => { state.localWrites.push(embed); }),
} }));
vi.mock("../../config/api", () => ({
  getApiEndpoint: (path: string) => `https://api.test${path}`,
  storageArchiveFetch: vi.fn(async () => {
    state.reads++;
    return {
      ok: state.readStatus === 200, status: state.readStatus,
      json: async () => ({
        embed: {
          embed_id: "embed-1", hashed_chat_id: "hash:chat-1", hashed_user_id: "hash:user-1",
          hashed_message_id: "hash:message-1", parent_embed_id: state.canonicalParent,
          version_number: 1, status: state.canonicalStatus, app_id: "web", skill_id: "search",
          encrypted_content: state.canonicalContent, encrypted_type: state.canonicalType,
          encrypted_text_preview: state.canonicalPreview,
        },
        embed_keys: [{ hashed_embed_id: "hash:embed-1", hashed_user_id: "hash:user-1",
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
      if (type === "store_embed_keys") emit("store_embed_keys_confirmed", {
        request_id: payload.request_id, created_count: 1, failed_count: 0,
      });
    });
  }),
} }));

import { sendStoreEmbedImpl } from "../embedSenders";

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
  state.canonicalStatus = "finished"; state.canonicalParent = null;
  state.canonicalWrapper = "wrapper"; state.readStatus = 200; state.reads = 0;
  state.localWrites.length = 0;
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

describe("canonical embed conflict reconciliation", () => {
  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("settles an equivalent re-encrypted head against its owner-scoped canonical ciphertext", async () => {
    await sendStoreEmbedImpl(service, payload, keys);
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed", "store_embed_keys"]);
    expect(state.reads).toBe(1);
    expect(state.queued.size).toBe(0);
    expect(state.localWrites).toHaveLength(1);
    expect(state.localWrites[0].encrypted_content).toBe("cipher:body:old");
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
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed", "store_embed_keys"]);
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
  it("does not settle a rejected write without an authorized canonical read", async () => {
    state.readStatus = 403;
    await sendStoreEmbedImpl(service, payload, keys);
    expect(state.queued.size).toBe(1);
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed"]);
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
