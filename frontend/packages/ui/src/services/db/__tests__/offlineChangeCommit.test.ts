import { describe, expect, it, vi } from "vitest";
vi.mock("../chatCrudOperations", () => ({}));
import { addOfflineChange } from "../offlineChangesAndUpdates";

function makeDatabase() {
  const request = { onsuccess: null as (() => void) | null, onerror: null as (() => void) | null, error: null };
  const transaction = {
    objectStore: () => ({ put: () => request }),
    oncomplete: null as (() => void) | null,
    onerror: null as (() => void) | null,
    onabort: null as (() => void) | null,
    error: null as DOMException | null,
  };
  const db = {
    init: async () => {},
    getTransaction: async () => transaction,
  };
  return { db, request, transaction };
}

describe("offline change commit acknowledgement", () => {
  // contract-test: supporting surface=gui.web assertions=teams.cache.bounded-isolated
  it("does not acknowledge an offline save until its transaction commits", async () => {
    const { db, request, transaction } = makeDatabase();
    let settled = false;
    const saving = addOfflineChange(db as never, { change_id: "change-1" } as never)
      .then(() => { settled = true; });
    await Promise.resolve();
    await Promise.resolve();
    request.onsuccess?.();
    await Promise.resolve();
    expect(settled).toBe(false);
    transaction.oncomplete?.();
    await saving;
    expect(settled).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=teams.cache.bounded-isolated
  it("rejects a quota-aborted offline save after put was queued", async () => {
    const { db, request, transaction } = makeDatabase();
    const saving = addOfflineChange(db as never, { change_id: "change-2" } as never);
    const rejected = expect(saving).rejects.toMatchObject({ name: "QuotaExceededError" });
    await Promise.resolve();
    await Promise.resolve();
    request.onsuccess?.();
    transaction.error = new DOMException("full", "QuotaExceededError");
    transaction.onabort?.();
    await rejected;
  });
});
