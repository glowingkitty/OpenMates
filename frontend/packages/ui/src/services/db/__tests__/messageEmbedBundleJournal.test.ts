// contract-test-file: infrastructure
import { describe, expect, it, vi } from "vitest";
import type { Message } from "../../../types/chat";

vi.mock("../../encryption/ChatKeyManager", () => ({
  chatKeyManager: { acquireCriticalOp: vi.fn(), releaseCriticalOp: vi.fn() },
}));
vi.mock("../../recentChatWindowCache", () => ({
  invalidateRecentChatWindow: vi.fn(), invalidateRecentChatWindowForMessage: vi.fn(),
}));

import {
  batchSaveMessages, decryptPendingMessageRetryRow, getPendingMessageRetryPage,
  saveMessage, updateMessageStatus,
} from "../messageOperations";

const FIELD = "pending_encrypted_embed_bundle_v1";
const TURN_FIELD = "pending_encrypted_turn_preflight_v1";
const TURN_MARKER = "pending_turn_preflight_v1";

/** Model IndexedDB request ordering and transaction completion without replacing the save functions. */
function makeTransactions() {
  const rows = new Map<string, Record<string, unknown>>();
  const makeTransaction = (_store: string | string[], mode: IDBTransactionMode) => {
    let pending = 0;
    const tx = {
      mode, error: null,
      oncomplete: null as (() => void) | null,
      onerror: null as (() => void) | null,
      onabort: null as (() => void) | null,
      objectStore: () => ({
        get: (id: string) => {
          const request = { result: undefined as Record<string, unknown> | undefined,
            error: null, onsuccess: null as (() => void) | null,
            onerror: null as (() => void) | null };
          enqueue(() => { request.result = rows.get(id) ? { ...rows.get(id)! } : undefined; request.onsuccess?.(); });
          return request;
        },
        put: (row: Record<string, unknown>) => {
          const request = { error: null, onsuccess: null as (() => void) | null,
            onerror: null as (() => void) | null };
          enqueue(() => { rows.set(String(row.message_id), { ...row }); request.onsuccess?.(); });
          return request;
        },
      }),
    };
    function enqueue(operation: () => void) {
      pending++;
      queueMicrotask(() => {
        operation();
        pending--;
        if (pending === 0) queueMicrotask(() => { if (pending === 0) tx.oncomplete?.(); });
      });
    }
    return tx as unknown as IDBTransaction;
  };
  const db = {
    db: { transaction: makeTransaction } as unknown as IDBDatabase,
    init: async () => undefined,
    encryptMessageFields: async (message: Message) => ({ ...message }),
    decryptMessageFields: async (message: Message) => ({ ...message }),
    getTransaction: async (store: string | string[], mode: IDBTransactionMode) => makeTransaction(store, mode),
  };
  return { db, rows };
}

function message(id: string, status: Message["status"]): Message {
  return {
    message_id: id, chat_id: "chat", role: "user", content: "attached code",
    sender_name: "user", created_at: 1, status,
  } as Message;
}

describe("pending encrypted message retry journals", () => {
  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,message-input.embeds.gated-send
  it("discovers synced sealed turns by numeric index in bounded pages without decrypting in the transaction", async () => {
    const indexed = [
      { ...message("synced-turn", "synced"), created_at: 1,
        encrypted_content: "x".repeat(4 * 1024 * 1024),
        [TURN_FIELD]: "sealed", [TURN_MARKER]: 1 },
      { ...message("later-turn", "sending"), created_at: 2, [TURN_FIELD]: "sealed", [TURN_MARKER]: 1 },
    ];
    const originalRange = globalThis.IDBKeyRange;
    vi.stubGlobal("IDBKeyRange", {
      bound: (lower: unknown[], upper: unknown[], lowerOpen: boolean) => ({ lower, upper, lowerOpen }),
    });
    const decrypt = vi.fn(async (row: Message) => row);
    const db = {
      decryptMessageFields: decrypt,
      getTransaction: async () => ({
        objectStore: () => ({
          index: (name: string) => {
            expect(name).toBe("pending_turn_created_at_message_id");
            return {
              openCursor: (range: { lower: [number, number, string]; lowerOpen: boolean }) => {
                const request = { result: null as unknown, onsuccess: null as (() => void) | null,
                  onerror: null as (() => void) | null, error: null };
                const candidates = indexed.filter((row) => {
                  const key: [number, number, string] = [1, row.created_at, row.message_id];
                  return key[1] > range.lower[1] ||
                    (key[1] === range.lower[1] &&
                      (range.lowerOpen ? key[2] > range.lower[2] : key[2] >= range.lower[2]));
                });
                let position = 0;
                const advance = () => queueMicrotask(() => {
                  const row = candidates[position++];
                  request.result = row ? {
                    value: row, key: [1, row.created_at, row.message_id],
                    continue: advance,
                  } : null;
                  request.onsuccess?.();
                });
                advance();
                return request;
              },
            };
          },
        }),
      }),
    };
    try {
      const first = await getPendingMessageRetryPage(db as never, "pending_turn", null, 20);
      expect(first.rows.map((row) => row.message_id)).toEqual(["synced-turn"]);
      expect(first.nextCursor).toEqual([1, 1, "synced-turn"]);
      expect(first.oversizedCount).toBe(0);
      expect(decrypt).not.toHaveBeenCalled();
      const second = await getPendingMessageRetryPage(db as never, "pending_turn", first.nextCursor, 20);
      expect(second.rows.map((row) => row.message_id)).toEqual(["later-turn"]);
      expect(await decryptPendingMessageRetryRow(db as never, second.rows[0])).toMatchObject({
        message_id: "later-turn",
      });
      expect(decrypt).toHaveBeenCalledOnce();
    } finally {
      vi.stubGlobal("IDBKeyRange", originalRange);
    }
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("isolates an unreadable pending row so the next retained turn can decrypt", async () => {
    const decrypt = vi.fn(async (row: Message) => {
      if (row.message_id === "bad-key") throw new Error("key unavailable");
      return { ...row, content: "ready" };
    });
    const db = { decryptMessageFields: decrypt };
    expect(await decryptPendingMessageRetryRow(db as never, message("bad-key", "sending"))).toBeNull();
    expect(await decryptPendingMessageRetryRow(db as never, message("good-key", "sending")))
      .toMatchObject({ message_id: "good-key", content: "ready" });
    expect(decrypt).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,message-input.embeds.gated-send
  it("preserves the reconciled canonical embed reference through final user status changes", async () => {
    const { db, rows } = makeTransactions();
    const canonicalCiphertext = "sealed embed-ref ciphertext";
    rows.set("final-user", {
      ...message("final-user", "sending"), content: undefined,
      encrypted_content: canonicalCiphertext,
      [FIELD]: "sealed bundle", [TURN_FIELD]: "sealed turn", [TURN_MARKER]: 1,
    });
    await updateMessageStatus(db, "final-user", "processing");
    await updateMessageStatus(db, "final-user", "synced");
    expect(rows.get("final-user")).toMatchObject({
      status: "synced", encrypted_content: canonicalCiphertext,
      [FIELD]: "sealed bundle", [TURN_FIELD]: "sealed turn", [TURN_MARKER]: 1,
    });
  });
  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("survives same-ID single and batch sync writes, then cannot resurrect after ACK", async () => {
    const { db, rows } = makeTransactions();
    const sealed = '{"encrypted_embeds":[{"encrypted_content":"ciphertext"}]}';
    rows.set("single", { ...message("single", "sending"), [FIELD]: sealed, [TURN_FIELD]: "sealed-turn", [TURN_MARKER]: 1 });
    await saveMessage(db, message("single", "processing"));
    expect(rows.get("single")?.[FIELD]).toBe(sealed);
    expect(rows.get("single")?.[TURN_FIELD]).toBe("sealed-turn");
    expect(rows.get("single")?.[TURN_MARKER]).toBe(1);
    await batchSaveMessages(db, [message("single", "delivered")]);
    expect(rows.get("single")?.[FIELD]).toBe(sealed);
    expect(rows.get("single")?.[TURN_FIELD]).toBe("sealed-turn");
    expect(rows.get("single")?.[TURN_MARKER]).toBe(1);
    const staleSingle = { ...message("single", "synced"), [FIELD]: sealed, [TURN_FIELD]: "sealed-turn", [TURN_MARKER]: 1 } as Message;
    delete rows.get("single")?.[FIELD]; // canonical message ACK clears the journal
    delete rows.get("single")?.[TURN_FIELD];
    delete rows.get("single")?.[TURN_MARKER];
    await saveMessage(db, staleSingle);
    expect(rows.get("single")?.status).toBe("synced");
    expect(rows.get("single")).not.toHaveProperty(FIELD);
    expect(rows.get("single")).not.toHaveProperty(TURN_FIELD);
    expect(rows.get("single")).not.toHaveProperty(TURN_MARKER);

    rows.set("batch", { ...message("batch", "sending"), [FIELD]: sealed, [TURN_FIELD]: "sealed-turn", [TURN_MARKER]: 1 });
    await batchSaveMessages(db, [message("batch", "processing")]);
    expect(rows.get("batch")?.[FIELD]).toBe(sealed);
    expect(rows.get("batch")?.[TURN_FIELD]).toBe("sealed-turn");
    expect(rows.get("batch")?.[TURN_MARKER]).toBe(1);
    delete rows.get("batch")?.[FIELD];
    delete rows.get("batch")?.[TURN_FIELD];
    delete rows.get("batch")?.[TURN_MARKER];
    await batchSaveMessages(db, [{ ...message("batch", "delivered"), [FIELD]: sealed, [TURN_FIELD]: "sealed-turn", [TURN_MARKER]: 1 } as Message]);
    expect(rows.get("batch")?.status).toBe("delivered");
    expect(rows.get("batch")).not.toHaveProperty(FIELD);
    expect(rows.get("batch")).not.toHaveProperty(TURN_FIELD);
    expect(rows.get("batch")).not.toHaveProperty(TURN_MARKER);
  });
});
