import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StoreEmbedPayload } from "../../types/chat";

const state = vi.hoisted(() => ({
  queued: new Map<string, Record<string, unknown>>(),
  sent: [] as Array<{ type: string; payload: Record<string, unknown> }>,
  handlers: new Map<string, Set<(payload: unknown) => void>>(),
  closeHandlers: new Set<() => void>(),
  keyFailure: false,
  disconnectOnKeys: false,
  holdHeads: false,
  heldHeads: [] as Array<Record<string, unknown>>,
  uuidCounter: 0,
  connected: true,
  catalogEntry: null as null | { app_id?: string; skill_id?: string; has_encrypted_content?: boolean },
  decodedCatalog: undefined as undefined | { app_id?: string; skill_id?: string },
  catalogReads: 0,
  chats: [] as Array<{ chat_id: string; team_id?: string | null }>,
  pageReads: 0,
  rawReads: 0,
}));

const emit = (type: string, payload: Record<string, unknown>) => {
  for (const handler of Array.from(state.handlers.get(type) ?? [])) handler(payload);
};

vi.mock("../embedStore", () => ({ embedStore: {
  getRawEntry: vi.fn(async () => state.catalogEntry),
  getCatalogContext: vi.fn(async () => {
    state.catalogReads++;
    return state.decodedCatalog;
  }),
} }));
vi.mock("../db", () => ({ chatDB: {
  getChatsPage: vi.fn(async (after: string | null) => {
    state.pageReads++;
    const start = after ? state.chats.findIndex((chat) => chat.chat_id === after) + 1 : 0;
    const items = state.chats.slice(start, start + 2);
    return { items, nextAfter: start + 2 < state.chats.length ? items[items.length - 1]!.chat_id : null };
  }),
  getRawChat: vi.fn(async (id: string) => {
    state.rawReads++;
    return state.chats.find((chat) => chat.chat_id === id) ?? null;
  }),
  addPendingEmbedOperation: vi.fn(async (op: Record<string, unknown>) => { state.queued.set(String(op.operation_id), op); }),
  getPendingEmbedOperations: vi.fn(async () => Array.from(state.queued.values())),
  removePendingEmbedOperation: vi.fn(async (id: string) => { state.queued.delete(id); }),
} }));
vi.mock("../../message_parsing/utils", () => ({ computeSHA256: vi.fn(async (value: string) => `digest:${value}`) }));
vi.mock("../websocketService", () => ({ webSocketService: {
  on: vi.fn((type: string, handler: (payload: unknown) => void) => {
    const group = state.handlers.get(type) ?? new Set();
    group.add(handler);
    state.handlers.set(type, group);
  }),
  off: vi.fn((type: string, handler: (payload: unknown) => void) => state.handlers.get(type)?.delete(handler)),
  addEventListener: vi.fn((type: string, handler: () => void) => {
    if (type === "close") state.closeHandlers.add(handler);
  }),
  removeEventListener: vi.fn((type: string, handler: () => void) => {
    if (type === "close") state.closeHandlers.delete(handler);
  }),
  sendMessage: vi.fn(async (type: string, payload: Record<string, unknown>) => {
    state.sent.push({ type, payload });
    if (type === "store_embed") {
      if (state.holdHeads) {
        state.heldHeads.push(payload);
        return;
      }
      queueMicrotask(() => emit("store_embed_confirmed", {
        request_id: payload.request_id, embed_id: payload.embed_id,
        canonical_digest: `digest:${payload.encrypted_content}`,
      }));
    } else if (type === "store_embed_keys") {
      if (state.disconnectOnKeys) {
        queueMicrotask(() => {
          for (const handler of Array.from(state.closeHandlers)) handler();
        });
        return;
      }
      queueMicrotask(() => emit("store_embed_keys_confirmed", {
        request_id: payload.request_id,
        created_count: state.keyFailure ? 1 : (payload.keys as unknown[]).length,
        failed_count: state.keyFailure ? 1 : 0,
      }));
    }
  }),
} }));

import { sendStoreEmbedImpl, flushPendingEmbedOperations } from "../embedSenders";
import { withCanonicalEmbedWrite } from "../canonicalEmbedWriteCoordinator";

const payload = { embed_id: "embed-1", encrypted_content: "ciphertext" } as StoreEmbedPayload;
const keys = { keys: [{ key_type: "master" }, { key_type: "chat" }] };

beforeEach(() => {
  state.queued.clear();
  state.sent.length = 0;
  state.handlers.clear();
  state.closeHandlers.clear();
  state.keyFailure = false;
  state.disconnectOnKeys = false;
  state.holdHeads = false;
  state.heldHeads.length = 0;
  state.uuidCounter = 0;
  vi.mocked(crypto.randomUUID).mockImplementation(() => `embed-test-${++state.uuidCounter}` as `${string}-${string}-${string}-${string}-${string}`);
  state.connected = true;
  state.catalogEntry = null;
  state.decodedCatalog = undefined;
  state.catalogReads = 0;
  state.chats = [];
  state.pageReads = 0;
  state.rawReads = 0;
});

describe("canonical embed sender receipts", () => {
  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("keeps an ordinary head and wrappers behind the recovered embed's exact ACK", async () => {
    let releaseAck: () => void = () => undefined;
    const ack = new Promise<void>((resolve) => { releaseAck = resolve; });
    const recovery = withCanonicalEmbedWrite("embed-1", async () => {
      state.sent.push({ type: "recovery_head_confirmed", payload: {} });
      await ack;
      state.sent.push({ type: "recovery_typed_acknowledged", payload: {} });
    });
    await vi.waitFor(() => expect(state.sent.map((entry) => entry.type)).toEqual(["recovery_head_confirmed"]));

    const ordinary = sendStoreEmbedImpl({ webSocketConnected_FOR_SENDERS_ONLY: true } as never, payload, keys);
    await vi.waitFor(() => expect(state.queued.size).toBe(1));
    expect(state.sent.map((entry) => entry.type)).toEqual(["recovery_head_confirmed"]);

    const unrelated = sendStoreEmbedImpl({ webSocketConnected_FOR_SENDERS_ONLY: true } as never,
      { ...payload, embed_id: "embed-other" }, keys);
    await unrelated;
    expect(state.sent.map((entry) => entry.type)).toEqual([
      "recovery_head_confirmed", "store_embed", "store_embed_keys",
    ]);

    releaseAck();
    await Promise.all([recovery, ordinary]);
    expect(state.sent.map((entry) => entry.type)).toEqual([
      "recovery_head_confirmed", "store_embed", "store_embed_keys",
      "recovery_typed_acknowledged", "store_embed", "store_embed_keys",
    ]);
    expect(state.queued.size).toBe(0);
    expect(state.catalogReads).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery
  it("waits for ordinary head and wrapper receipts before a recovered read, then releases after failure", async () => {
    state.holdHeads = true;
    const ordinary = sendStoreEmbedImpl({ webSocketConnected_FOR_SENDERS_ONLY: true } as never, payload, keys);
    await vi.waitFor(() => expect(state.heldHeads).toHaveLength(1));
    const recoveredRead = vi.fn(async () => { state.sent.push({ type: "recovery_read", payload: {} }); });
    const recovery = withCanonicalEmbedWrite("embed-1", recoveredRead);
    await Promise.resolve();
    expect(recoveredRead).not.toHaveBeenCalled();

    state.holdHeads = false;
    const head = state.heldHeads[0];
    emit("store_embed_confirmed", {
      request_id: head.request_id, embed_id: head.embed_id,
      canonical_digest: `digest:${head.encrypted_content}`,
    });
    await Promise.all([ordinary, recovery]);
    expect(state.sent.map((entry) => entry.type)).toEqual([
      "store_embed", "store_embed_keys", "recovery_read",
    ]);
    await expect(withCanonicalEmbedWrite("embed-1", async () => { throw new Error("socket closed"); }))
      .rejects.toThrow("socket closed");
    await expect(withCanonicalEmbedWrite("embed-1", async () => "released")).resolves.toBe("released");
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,storage.background.complete-sealed-recovery
  it("commits the encrypted head before wrappers and removes the queue only after both receipts", async () => {
    await sendStoreEmbedImpl({ webSocketConnected_FOR_SENDERS_ONLY: true } as never, payload, keys);
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed", "store_embed_keys"]);
    expect(state.queued.size).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,storage.background.complete-sealed-recovery
  it("retains the encrypted head and wrappers when a wrapper fails, then retries both on reconnect", async () => {
    state.keyFailure = true;
    await sendStoreEmbedImpl({ webSocketConnected_FOR_SENDERS_ONLY: true } as never, payload, keys);
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed", "store_embed_keys"]);
    expect(state.queued.size).toBe(1);
    expect(Array.from(state.queued.values())[0].store_embed_keys_payload).toEqual(keys);
    state.keyFailure = false;
    await flushPendingEmbedOperations();
    expect(state.sent.map((entry) => entry.type)).toEqual([
      "store_embed", "store_embed_keys", "store_embed", "store_embed_keys",
    ]);
    expect(state.queued.size).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,storage.background.complete-sealed-recovery
  it("keeps the paired operation after a disconnect between canonical receipts", async () => {
    state.disconnectOnKeys = true;
    await sendStoreEmbedImpl({ webSocketConnected_FOR_SENDERS_ONLY: true } as never, payload, keys);
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed", "store_embed_keys"]);
    expect(state.queued.size).toBe(1);
    expect(state.closeHandlers.size).toBe(0);
    state.disconnectOnKeys = false;
    await flushPendingEmbedOperations();
    expect(state.queued.size).toBe(0);
    expect(state.sent.map((entry) => entry.type)).toEqual([
      "store_embed", "store_embed_keys", "store_embed", "store_embed_keys",
    ]);
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,storage.background.complete-sealed-recovery
  it("commits an older queued revision before a newer head for the same embed", async () => {
    state.keyFailure = true;
    await sendStoreEmbedImpl({ webSocketConnected_FOR_SENDERS_ONLY: true } as never, payload, keys);
    expect(state.queued.size).toBe(1);
    state.keyFailure = false;
    await sendStoreEmbedImpl({ webSocketConnected_FOR_SENDERS_ONLY: true } as never,
      { ...payload, encrypted_content: "newer-ciphertext" }, keys);
    expect(state.sent.map((entry) => [entry.type, entry.payload.encrypted_content])).toEqual([
      ["store_embed", "ciphertext"], ["store_embed_keys", undefined],
      ["store_embed", "ciphertext"], ["store_embed_keys", undefined],
      ["store_embed", "newer-ciphertext"], ["store_embed_keys", undefined],
    ]);
    expect(state.queued.size).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery
  it("drains operations deferred by the bounded active receipt limit without a reconnect", async () => {
    state.holdHeads = true;
    const senders = Array.from({ length: 33 }, (_, index) =>
      sendStoreEmbedImpl({ webSocketConnected_FOR_SENDERS_ONLY: true } as never,
        { ...payload, embed_id: `embed-${index}`, encrypted_content: `cipher-${index}` }));
    await vi.waitFor(() => expect(state.heldHeads).toHaveLength(32));
    expect(state.queued.size).toBe(33);
    state.holdHeads = false;
    for (const head of state.heldHeads) {
      emit("store_embed_confirmed", {
        request_id: head.request_id, embed_id: head.embed_id,
        canonical_digest: `digest:${head.encrypted_content}`,
      });
    }
    await Promise.all(senders);
    await vi.waitFor(() => expect(state.queued.size).toBe(0));
    expect(state.sent.filter((entry) => entry.type === "store_embed")).toHaveLength(33);
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted
  it("keeps the paired ciphertext and wrappers offline without sending either", async () => {
    await sendStoreEmbedImpl({ webSocketConnected_FOR_SENDERS_ONLY: false } as never, payload, keys);
    expect(state.sent).toEqual([]);
    expect(state.queued.size).toBe(1);
    expect(Array.from(state.queued.values())[0].store_embed_keys_payload).toEqual(keys);
  });
});


describe("legacy embed catalog context", () => {
  const legacyPayload = {
    ...payload, hashed_chat_id: "digest:chat-1", encrypted_content: "preview-ciphertext",
  } as StoreEmbedPayload;
  const service = { webSocketConnected_FOR_SENDERS_ONLY: true } as never;

  beforeEach(() => {
    state.catalogEntry = { app_id: "web", skill_id: "search" };
    state.chats = [{ chat_id: "chat-1", team_id: null }];
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("sends preview updates with their original chat catalog context and ciphertext", async () => {
    await sendStoreEmbedImpl(service, legacyPayload);
    expect(state.sent[0]).toMatchObject({ type: "store_embed", payload: {
      app_id: "web", skill_id: "search", chat_id: "chat-1", team_id: null,
      hashed_chat_id: "digest:chat-1", encrypted_content: "preview-ciphertext",
    } });
    expect(state.queued.size).toBe(0);
    expect(state.catalogReads).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("recovers catalog identifiers from decrypted local content when a refresh omitted them", async () => {
    state.catalogEntry = { has_encrypted_content: true };
    state.decodedCatalog = { app_id: "web", skill_id: "search" };
    await sendStoreEmbedImpl(service, legacyPayload);
    expect(state.sent[0].payload).toMatchObject({
      app_id: "web", skill_id: "search", chat_id: "chat-1", team_id: null,
      encrypted_content: "preview-ciphertext",
    });
    expect(state.catalogReads).toBe(1);
    expect(state.queued.size).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("recovers an old queued write from decrypted content without replacing its ciphertext", async () => {
    state.catalogEntry = { has_encrypted_content: true };
    await sendStoreEmbedImpl({ webSocketConnected_FOR_SENDERS_ONLY: false } as never, legacyPayload);
    expect(state.catalogReads).toBe(0);
    state.decodedCatalog = { app_id: "web", skill_id: "search" };
    await flushPendingEmbedOperations();
    expect(state.sent[0].payload).toMatchObject({
      app_id: "web", skill_id: "search", chat_id: "chat-1", encrypted_content: "preview-ciphertext",
    });
    expect(state.queued.size).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("defers encrypted catalog writes while local metadata cannot be decrypted", async () => {
    state.catalogEntry = { has_encrypted_content: true };
    await sendStoreEmbedImpl(service, legacyPayload);
    expect(state.sent).toHaveLength(0);
    expect(state.queued.size).toBe(1);
    state.decodedCatalog = { app_id: "web", skill_id: "search" };
    await flushPendingEmbedOperations();
    expect(state.sent[0].payload).toMatchObject({ app_id: "web", skill_id: "search" });
    expect(state.queued.size).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("retains incomplete decrypted catalog context rather than sending an invalid write", async () => {
    state.catalogEntry = { has_encrypted_content: true };
    state.decodedCatalog = { app_id: "web" };
    await sendStoreEmbedImpl(service, legacyPayload);
    expect(state.sent).toHaveLength(0);
    expect(state.queued.size).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("keeps the original protocol for successfully decoded non-catalog embeds", async () => {
    state.catalogEntry = { has_encrypted_content: true };
    state.decodedCatalog = {};
    await sendStoreEmbedImpl(service, legacyPayload);
    expect(state.sent[0].payload).toMatchObject(legacyPayload);
    expect(state.sent[0].payload).not.toHaveProperty("app_id");
    expect(state.sent[0].payload).not.toHaveProperty("chat_id");
    expect(state.queued.size).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("preserves explicit identifiers when decrypted metadata supplies only the missing field", async () => {
    state.catalogEntry = { has_encrypted_content: true };
    state.decodedCatalog = { app_id: "web", skill_id: "search" };
    await sendStoreEmbedImpl(service, { ...legacyPayload, app_id: "images" });
    expect(state.sent[0].payload).toMatchObject({ app_id: "images", skill_id: "search", chat_id: "chat-1" });
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("repairs a previously queued preview write when reconnecting", async () => {
    await sendStoreEmbedImpl({ webSocketConnected_FOR_SENDERS_ONLY: false } as never, legacyPayload);
    expect(state.sent).toHaveLength(0);
    expect(Array.from(state.queued.values())[0].store_embed_payload).not.toHaveProperty("app_id");
    await flushPendingEmbedOperations();
    expect(state.sent[0].payload).toMatchObject({
      app_id: "web", skill_id: "search", chat_id: "chat-1", team_id: null,
    });
    expect(state.queued.size).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("derives Team context from the matching chat rather than another local chat", async () => {
    state.chats = [{ chat_id: "unrelated", team_id: "other-team" }, { chat_id: "chat-1", team_id: "team-1" }];
    await sendStoreEmbedImpl(service, legacyPayload);
    expect(state.sent[0].payload).toMatchObject({ chat_id: "chat-1", team_id: "team-1" });
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("keeps the write queued without sending when its catalog chat is not hydrated", async () => {
    state.chats = [{ chat_id: "unrelated" }];
    await sendStoreEmbedImpl(service, legacyPayload);
    expect(state.sent).toHaveLength(0);
    expect(state.queued.size).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("pages raw routing metadata once for queued writes and re-reads current Team context", async () => {
    state.chats = [{ chat_id: "a" }, { chat_id: "b" }, { chat_id: "chat-batch", team_id: "team-before" }];
    const batchPayload = { ...legacyPayload, hashed_chat_id: "digest:chat-batch" };
    await sendStoreEmbedImpl({ webSocketConnected_FOR_SENDERS_ONLY: false } as never, batchPayload);
    await sendStoreEmbedImpl({ webSocketConnected_FOR_SENDERS_ONLY: false } as never, batchPayload);
    await flushPendingEmbedOperations();
    expect(state.pageReads).toBe(2);
    expect(state.rawReads).toBe(1);
    expect(state.queued.size).toBe(0);
    state.chats[2].team_id = "team-after";
    await sendStoreEmbedImpl(service, batchPayload);
    expect(state.pageReads).toBe(2);
    expect(state.sent[state.sent.length - 1]!.payload.team_id).toBe("team-after");
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("leaves explicit catalog and authorization context for the server to validate", async () => {
    const explicit = { ...legacyPayload, app_id: "images", skill_id: "search", chat_id: "explicit-chat", team_id: "explicit-team" };
    await sendStoreEmbedImpl(service, explicit);
    expect(state.sent[0].payload).toMatchObject(explicit);
  });
});
