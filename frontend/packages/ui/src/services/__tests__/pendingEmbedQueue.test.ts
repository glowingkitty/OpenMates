import { describe, expect, it, vi } from "vitest";
import { putPendingEmbedOperation } from "../db/pendingEmbedQueue";

function fakeTransaction() {
  const request = { onsuccess: null as null | (() => void), onerror: null as null | (() => void), error: null as Error | null };
  const transaction = {
    objectStore: vi.fn(() => ({ put: vi.fn(() => request) })),
    oncomplete: null as null | (() => void),
    onabort: null as null | (() => void),
    onerror: null as null | (() => void),
    error: null as Error | null,
  };
  return { transaction, request };
}

describe("durable pending embed queue write", () => {
  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("does not permit network dispatch after request success but before transaction commit", async () => {
    const { transaction, request } = fakeTransaction();
    let committed = false;
    const pending = putPendingEmbedOperation(transaction as unknown as IDBTransaction, "pending", { embed_id: "embed" })
      .then(() => { committed = true; });
    request.onsuccess?.();
    await Promise.resolve();
    expect(committed).toBe(false);
    transaction.oncomplete?.();
    await pending;
    expect(committed).toBe(true);
    expect(transaction.objectStore).toHaveBeenCalledWith("pending");
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery
  it("rejects an aborted queue transaction even if its put request was accepted", async () => {
    const { transaction, request } = fakeTransaction();
    const pending = putPendingEmbedOperation(transaction as unknown as IDBTransaction, "pending", { embed_id: "embed" });
    request.onsuccess?.();
    transaction.error = new Error("quota exceeded");
    transaction.onabort?.();
    await expect(pending).rejects.toThrow(/quota exceeded/);
  });
});
