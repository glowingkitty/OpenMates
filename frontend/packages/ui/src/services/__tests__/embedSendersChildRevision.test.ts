/**
 * The canonical embed sender runs the head of a child revision (version N+1 of
 * a generated-image child, origin "child-revision") in Rust-core builds: the
 * Rust `read_advance` plan and `advance` identity verdict (decisions proven in
 * packages/openmates-rust/src/embed_read/sender_tests.rs) make the shell write
 * N+1 under the Rust-built precondition, or adopt an equivalent N+1 head.
 * Rust decisions are scripted here; every other decision is the TS policy.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StoreEmbedPayload } from "../../types/chat";

const state = vi.hoisted(() => {
  vi.stubEnv("VITE_OPENMATES_RUST_CORE", "1");
  return {
    queued: new Map<string, Record<string, unknown>>(),
    sent: [] as Array<{ type: string; payload: Record<string, unknown> }>,
    handlers: new Map<string, Set<(payload: unknown) => void>>(),
    canonicalVersion: 1,
    canonicalContent: "cipher:image-v1",
    decisions: [] as Array<{ op: string; input: Record<string, unknown> }>,
    localWrites: [] as Array<Record<string, unknown>>,
  };
});

const CANONICAL_DIGEST = "c".repeat(64);

vi.mock("../db", () => ({ chatDB: {
  addPendingEmbedOperation: vi.fn(async (op: Record<string, unknown>) => state.queued.set(String(op.operation_id), op)),
  getPendingEmbedOperations: vi.fn(async () => Array.from(state.queued.values())),
  removePendingEmbedOperation: vi.fn(async (id: string) => state.queued.delete(id)),
  getRawChat: vi.fn(async (id: string) => id === "chat-1" ? { chat_id: id, team_id: null } : null),
} }));
vi.mock("../canonicalEmbedWriteCoordinator", () => ({
  assertCanonicalEmbedWriteLease: vi.fn(),
  withCanonicalEmbedWrite: vi.fn(async (_embedId: string, write: (lease: unknown) => Promise<unknown>) => write({})),
}));
vi.mock("../../message_parsing/utils", () => ({
  computeSHA256: vi.fn(async (text: string) => text === state.canonicalContent ? CANONICAL_DIGEST
    : text.startsWith("cipher:") ? "a".repeat(64) : `hash:${text}`),
}));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: { getKey: vi.fn(async () => new Uint8Array([3])) } }));
vi.mock("../cryptoService", () => ({ getKeyFromStorage: vi.fn(async () => ({})) }));
vi.mock("../encryption/MetadataEncryptor", () => ({
  decryptWithEmbedKey: vi.fn(async (encrypted: string) => encrypted.startsWith("cipher:") ? encrypted.slice(7) : null),
  unwrapEmbedKeyWithMasterKey: vi.fn(async () => new Uint8Array([1, 2])),
  unwrapEmbedKeyWithChatKey: vi.fn(async () => new Uint8Array([1, 2])),
}));
vi.mock("../embedStore", () => ({ embedStore: {
  getEmbedKey: vi.fn(async () => new Uint8Array([1, 2])),
  putEncrypted: vi.fn(async (_ref: string, embed: Record<string, unknown>) => { state.localWrites.push(embed); }),
} }));
vi.mock("../../config/api", () => ({
  getApiEndpoint: (path: string) => `https://api.test${path}`,
  storageArchiveFetch: vi.fn(async () => ({
    ok: true, status: 200,
    json: async () => ({
      embed: {
        embed_id: "child-1", hashed_chat_id: "hash:chat-1", hashed_user_id: "hash:user-1",
        hashed_message_id: "hash:message-1", parent_embed_id: "parent-1", version_number: state.canonicalVersion,
        status: "finished", app_id: "images", skill_id: "generated_image", is_private: false, is_shared: false,
        encrypted_content: state.canonicalContent, encrypted_type: "cipher:image",
      },
      // The child keeps its parent's wrappers.
      embed_keys: [{ hashed_embed_id: "hash:parent-1", hashed_user_id: "hash:user-1", hashed_chat_id: null,
        key_type: "master", encrypted_embed_key: "parent-wrapper" }],
    }),
  })),
}));
vi.mock("../rustCore/embeds/embedDataClient", async () => {
  const policy = await import("../embedSenderPolicy");
  return {
    decideEmbedSenderInRust: vi.fn(async (op: string, input: Record<string, unknown>) => {
      state.decisions.push({ op, input });
      // Scripted Rust answers for the child-revision outcomes (proven in sender_tests.rs).
      if (op === "senderAvailabilityPlan" && input.origin === "child-revision" && !input.read_only) {
        return { outcome: "read_advance", allow_wrapper_writes: false };
      }
      const page = input.page as { embed?: { version_number?: number } } | undefined;
      const head = input.head as { version_number?: number } | undefined;
      if (op === "senderCanonicalIdentity" && input.advance === true
        && page?.embed?.version_number === (head?.version_number ?? 1) - 1) {
        return { outcome: "advance", precondition: { version: page.embed.version_number, ciphertext_sha256: input.content_sha256 } };
      }
      return policy.decideEmbedSender(op as never, input as never);
    }),
  };
});
vi.mock("../websocketService", () => ({ webSocketService: {
  ownEmbedProtocolRequest: vi.fn(() => () => undefined),
  on: vi.fn((type: string, listener: (payload: unknown) => void) => {
    const listeners = state.handlers.get(type) ?? new Set();
    listeners.add(listener); state.handlers.set(type, listeners);
  }),
  off: vi.fn((type: string, listener: (payload: unknown) => void) => state.handlers.get(type)?.delete(listener)),
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  sendMessage: vi.fn(async (type: string, payload: Record<string, unknown>) => {
    state.sent.push({ type, payload });
    queueMicrotask(() => {
      if (type !== "store_embed") return;
      for (const listener of state.handlers.get("store_embed_confirmed") ?? []) {
        listener({ request_id: payload.request_id, embed_id: payload.embed_id, canonical_digest: "a".repeat(64), canonical_source: "head" });
      }
    });
  }),
} }));

// vi.hoisted stubs the flag before this import is evaluated.
import { sendStoreEmbedImpl } from "../embedSenders";

const head = {
  embed_id: "child-1", chat_id: "chat-1", team_id: null, parent_embed_id: "parent-1",
  hashed_chat_id: "hash:chat-1", hashed_user_id: "hash:user-1", hashed_message_id: "hash:message-1",
  hashed_task_id: "hash:task-2", app_id: "images", skill_id: "generated_image",
  encrypted_content: "cipher:image-v2", encrypted_type: "cipher:image",
  status: "finished", version_number: 2, is_private: false, is_shared: false,
} as StoreEmbedPayload;
const service = { webSocketConnected_FOR_SENDERS_ONLY: true } as never;

beforeEach(() => {
  state.queued.clear(); state.sent.length = 0; state.handlers.clear();
  state.decisions.length = 0; state.localWrites.length = 0;
  state.canonicalVersion = 1; state.canonicalContent = "cipher:image-v1";
  vi.stubGlobal("fetch", vi.fn(async (_url: string, options: { body: string }) => ({
    ok: true, status: 200,
    // A finished child: the server reports no canonical_revision for it.
    json: async () => ({ results: JSON.parse(options.body).embed_ids.map((embed_id: string) => ({ embed_id, state: "ready" })) }),
  })));
});

describe("child revision head through the canonical embed sender", () => {
  // contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version
  it("writes version N+1 under the Rust-built precondition of the canonical head N", async () => {
    expect(await sendStoreEmbedImpl(service, head, undefined, undefined, "child-revision")).toBe(true);
    const plan = state.decisions.find((entry) => entry.op === "senderAvailabilityPlan");
    expect(plan?.input.origin).toBe("child-revision");
    const identity = state.decisions.find((entry) => entry.op === "senderCanonicalIdentity");
    expect(identity?.input).toMatchObject({ advance: true, content_sha256: CANONICAL_DIGEST });
    expect(state.sent.map((entry) => entry.type)).toEqual(["store_embed"]);
    expect(state.sent[0].payload).toMatchObject({
      embed_id: "child-1", version_number: 2, parent_embed_id: "parent-1",
      hashed_message_id: "hash:message-1", encrypted_content: "cipher:image-v2",
      canonical_precondition: { version: 1, ciphertext_sha256: CANONICAL_DIGEST },
    });
    expect(state.queued.size).toBe(0);
    expect(state.localWrites).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version
  it("adopts a canonical head already at the equivalent N+1 without writing", async () => {
    state.canonicalVersion = 2;
    state.canonicalContent = "cipher:image-v2";
    expect(await sendStoreEmbedImpl(service, { ...head, hashed_task_id: undefined }, undefined, undefined,
      "child-revision")).toBe(true);
    expect(state.sent).toEqual([]);
    expect(state.localWrites).toHaveLength(1);
    expect(state.queued.size).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=images-generate.revision.same-embed-new-version
  it("keeps every other child write on the equivalence-only read", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    expect(await sendStoreEmbedImpl(service, head)).toBe(false);
    expect(state.sent).toEqual([]);
    expect([...state.queued.values()][0]).toMatchObject({
      state: "conflict", failure_code: "embed_identity_or_version_conflict",
    });
  });
});
