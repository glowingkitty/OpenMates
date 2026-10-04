// contract-test-file: infrastructure
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../message_parsing/utils", () => ({
  computeSHA256: async (value: string) => `hash:${value}`,
}));
vi.mock("../../recentChatWindowCache", () => ({ invalidateRecentChatWindow: vi.fn() }));
vi.mock("../../cryptoService", () => ({
  encryptChatKeyWithMasterKey: vi.fn(), decryptChatKeyWithMasterKey: vi.fn(),
}));
vi.mock("../../encryption/ChatKeyManager", () => ({
  chatKeyManager: {}, computeKeyFingerprint: vi.fn(),
}));
vi.mock("../../anonymousChatKeyWrapping", () => ({ unwrapAnonymousChatKey: vi.fn() }));
vi.mock("../../chatKeyConsistency", () => ({ chatKeysEqual: vi.fn() }));
vi.mock("../../../stores/signupState", () => ({
  forcedLogoutInProgress: {}, isLoggingOut: {},
}));
vi.mock("../../../demo_chats/convertToChat", () => ({ isPublicChat: vi.fn() }));
vi.mock("../../anonymousChatIds", () => ({ isAnonymousChatId: vi.fn() }));
vi.mock("../../teamService", () => ({
  unwrapTeamChatKey: vi.fn(), wrapTeamChatKey: vi.fn(),
}));

import { deleteChatIfNoPendingTurn } from "../chatCrudOperations";

function guardedDeletionDb(pendingTurn: boolean) {
  const head = {
    contentRef: "embed:artifact", embed_id: "artifact", hashed_chat_id: "hash:draft-chat",
    encrypted_content: "sealed head", version_number: 1,
  };
  const wrappers = [
    { id: "master", key_type: "master", hashed_embed_id: "hash:artifact", hashed_chat_id: null },
    { id: "chat", key_type: "chat", hashed_embed_id: "hash:artifact", hashed_chat_id: "hash:draft-chat" },
  ];
  const writes: string[] = [];
  const request = <T>(result: T) => {
    const item = { result, error: null, onsuccess: null as (() => void) | null,
      onerror: null as (() => void) | null };
    queueMicrotask(() => item.onsuccess?.());
    return item;
  };
  const candidate = {
    objectStore: (name: string) => {
      expect(name).toBe("embeds");
      return { index: () => ({ getAll: () => request([head]) }) };
    },
  };
  const writer = {
    error: null,
    oncomplete: null as (() => void) | null,
    onerror: null as (() => void) | null,
    onabort: null as (() => void) | null,
    abort: vi.fn(),
    objectStore: (name: string) => {
      if (name === "messages") return {
        index: (indexName: string) => ({ openCursor: () => {
          if (indexName === "pending_turn_created_at_message_id") {
            return request(pendingTurn ? { value: {
              chat_id: "draft-chat", pending_encrypted_turn_preflight_v1: "sealed journal",
            } } : null);
          }
          expect(indexName).toBe("chat_id");
          return request(null);
        } }),
      };
      if (name === "chats") return { delete: (id: string) => { writes.push(`chat:${id}`); return request(undefined); } };
      if (name === "embeds") return {
        index: () => ({ getAll: () => request([head]) }),
        delete: (id: string) => { writes.push(`head:${id}`); return request(undefined); },
      };
      if (name === "embed_keys") return {
        index: () => ({ getAll: () => request(wrappers) }),
        delete: (id: string) => { writes.push(`key:${id}`); return request(undefined); },
      };
      throw new Error(`Unexpected store ${name}`);
    },
  };
  const db = {
    CHATS_STORE_NAME: "chats", init: async () => undefined,
    getTransaction: vi.fn(async (_stores: string | string[], mode: string) => {
      if (mode === "readonly") return candidate;
      expect(_stores).toEqual(["chats", "messages", "embeds", "embed_keys"]);
      return writer;
    }),
  };
  return { db, writer, writes };
}

afterEach(() => vi.unstubAllGlobals());

describe("inferred Phase 2 chat deletion", () => {
  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
  it("retains the complete encrypted draft when a pending journal appears before the write transaction", async () => {
    vi.stubGlobal("IDBKeyRange", { bound: () => ({}), only: () => ({}) });
    const { db, writer, writes } = guardedDeletionDb(true);
    const result = deleteChatIfNoPendingTurn(db as never, "draft-chat");
    await vi.waitFor(() => expect(writer.oncomplete).toBeTypeOf("function"));
    writer.oncomplete?.();
    expect(await result).toEqual({ deleted: false, deletedEmbedIds: [] });
    expect(writes).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("deletes an unpending inferred chat, its head, and wrappers inside one write transaction", async () => {
    vi.stubGlobal("IDBKeyRange", { bound: () => ({}), only: () => ({}) });
    const { db, writer, writes } = guardedDeletionDb(false);
    const result = deleteChatIfNoPendingTurn(db as never, "draft-chat");
    await vi.waitFor(() => expect(writes).toContain("chat:draft-chat"));
    expect(writes).toEqual(expect.arrayContaining([
      "chat:draft-chat", "head:embed:artifact", "key:master", "key:chat",
    ]));
    writer.oncomplete?.();
    expect(await result).toEqual({ deleted: true, deletedEmbedIds: ["artifact"] });
  });
});
