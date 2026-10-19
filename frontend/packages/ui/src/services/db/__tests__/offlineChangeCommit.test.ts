import { describe, expect, it, vi } from "vitest";
import type { OfflineChange } from "../../../types/chat";
import { invalidateWorkspaceCaches } from "../../workspaceCacheLifecycle";
vi.mock("../chatCrudOperations", () => ({}));
import { addOfflineChange, deleteOfflineChange, getOfflineChanges } from "../offlineChangesAndUpdates";

function change(change_id: string, fields: Partial<OfflineChange> = {}): OfflineChange {
  return {
    change_id, chat_id: "chat-1", type: "draft", value: "encrypted-draft",
    version_before_edit: 0, ...fields,
  };
}

function makeDatabase(rows: OfflineChange[] = []) {
  const read = {
    result: structuredClone(rows),
    onsuccess: null as (() => void) | null,
    onerror: null as (() => void) | null,
    error: null,
  };
  const write = { onsuccess: null as (() => void) | null, onerror: null as (() => void) | null, error: null };
  const store = {
    getAll: vi.fn(() => read),
    put: vi.fn((_row: OfflineChange) => write),
  };
  const events = new EventTarget();
  const transaction = {
    objectStore: vi.fn(() => store),
    oncomplete: null as (() => void) | null,
    onerror: null as (() => void) | null,
    onabort: null as (() => void) | null,
    addEventListener: events.addEventListener.bind(events),
    abort: vi.fn(() => {
      transaction.onabort?.();
      events.dispatchEvent(new Event("abort"));
    }),
    error: null as DOMException | null,
  };
  const db = {
    init: async () => {},
    getTransaction: vi.fn(async () => transaction),
  };
  return { db, read, write, store, transaction };
}

async function deliverRead(fixture: ReturnType<typeof makeDatabase>) {
  await Promise.resolve();
  await Promise.resolve();
  fixture.read.onsuccess?.();
}

/**
 * Model the store-scoped IndexedDB writer lock: a second connection's read runs
 * only after the previous writer commits. Requests complete in separate turns,
 * and only a transaction's commit publishes its staged writes.
 */
function makeSerializedDatabase(initialRows: OfflineChange[] = []) {
  let rows = structuredClone(initialRows);
  let previousCommit = Promise.resolve();
  const transactionModes: IDBTransactionMode[] = [];
  const db = {
    init: async () => {},
    getTransaction: vi.fn(async (_store: string, mode: IDBTransactionMode) => {
      transactionModes.push(mode);
      const preceding = previousCommit;
      let release!: () => void;
      previousCommit = new Promise<void>((resolve) => { release = resolve; });
      await preceding;
      const fixture = makeDatabase(rows);
      let staged = structuredClone(rows);
      let aborted = false;
      fixture.transaction.abort.mockImplementation(() => {
        aborted = true;
        fixture.transaction.onabort?.();
        release();
      });
      fixture.store.put.mockImplementation((row) => {
        staged = staged.filter((existing) => existing.change_id !== row.change_id);
        staged.push(structuredClone(row));
        queueMicrotask(() => {
          fixture.write.onsuccess?.();
          queueMicrotask(() => {
            if (aborted) return;
            rows = staged;
            fixture.transaction.oncomplete?.();
            release();
          });
        });
        return fixture.write;
      });
      fixture.store.getAll.mockImplementation(() => {
        queueMicrotask(() => {
          fixture.read.onsuccess?.();
          // A readonly transaction has no staged write to finish it.
          if (mode === "readonly") {
            fixture.transaction.oncomplete?.();
            release();
          }
        });
        return fixture.read;
      });
      return fixture.transaction;
    }),
  };
  return { db, transactionModes, getRows: () => structuredClone(rows) };
}

describe("offline change commit acknowledgement", () => {
  // contract-test: supporting surface=gui.web assertions=teams.cache.bounded-isolated
  it("does not acknowledge an offline save until its transaction commits", async () => {
    const fixture = makeDatabase();
    let settled = false;
    const saving = addOfflineChange(fixture.db as never, change("change-1"))
      .then(() => { settled = true; });
    await deliverRead(fixture);
    fixture.write.onsuccess?.();
    await Promise.resolve();
    expect(settled).toBe(false);
    fixture.transaction.oncomplete?.();
    await saving;
    expect(settled).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=teams.cache.bounded-isolated
  it("rejects a quota-aborted offline save after put succeeded", async () => {
    const fixture = makeDatabase();
    const saving = addOfflineChange(fixture.db as never, change("change-2"));
    const rejected = expect(saving).rejects.toMatchObject({ name: "QuotaExceededError" });
    await deliverRead(fixture);
    fixture.write.onsuccess?.();
    fixture.transaction.error = new DOMException("full", "QuotaExceededError");
    fixture.transaction.abort();
    await rejected;
  });

  // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
  it("keeps caller transaction completion handlers and resolves after its put", async () => {
    const fixture = makeDatabase([change("old", { queue_order: 8 })]);
    const oncomplete = vi.fn();
    fixture.transaction.oncomplete = oncomplete;
    let settled = false;
    const saving = addOfflineChange(fixture.db as never, change("new"), fixture.transaction as never)
      .then(() => { settled = true; });
    await deliverRead(fixture);
    expect(fixture.db.getTransaction).not.toHaveBeenCalled();
    expect(fixture.store.put).toHaveBeenCalledWith(expect.objectContaining({ queue_order: 9 }));
    expect(settled).toBe(false);
    fixture.write.onsuccess?.();
    await saving;
    expect(fixture.transaction.oncomplete).toBe(oncomplete);
    expect(oncomplete).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
  it("rejects a caller transaction abort while the ordering read is pending", async () => {
    const fixture = makeDatabase();
    const saving = addOfflineChange(fixture.db as never, change("new"), fixture.transaction as never);
    const rejected = expect(saving).rejects.toThrow("Offline change save aborted");
    await Promise.resolve();
    fixture.transaction.abort();
    await rejected;
    expect(fixture.store.put).not.toHaveBeenCalled();
  });
});

describe("durable offline queue insertion order", () => {
  // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
  it("allocates distinct orders when two reads share a caller transaction", async () => {
    const fixture = makeDatabase([change("old", { queue_order: 4 })]);
    const secondRead = { ...fixture.read };
    const secondWrite = { ...fixture.write };
    fixture.store.getAll.mockReturnValueOnce(fixture.read).mockReturnValueOnce(secondRead);
    fixture.store.put.mockReturnValueOnce(fixture.write).mockReturnValueOnce(secondWrite);
    const first = addOfflineChange(fixture.db as never, change("first"), fixture.transaction as never);
    const second = addOfflineChange(fixture.db as never, change("second"), fixture.transaction as never);
    await deliverRead(fixture);
    // Both reads saw the same original rows, before either put could complete.
    secondRead.onsuccess?.();
    expect(fixture.store.put.mock.calls.map(([row]) => row.queue_order)).toEqual([5, 6]);
    fixture.write.onsuccess?.();
    secondWrite.onsuccess?.();
    await Promise.all([first, second]);
  });

  // contract-test: direct surface=gui.web assertions=drafts.persistence.local-first-encrypted
  it("allocates by insertion across concurrent connections instead of UUID or draft version", async () => {
    const fixture = makeSerializedDatabase();
    // Separate wrappers model two tabs sharing one IndexedDB database.
    const otherConnection = { ...fixture.db };
    await Promise.all([
      addOfflineChange(fixture.db as never, change("ffffffff-ffff-4fff-bfff-ffffffffffff", { version_before_edit: 9 })),
      addOfflineChange(otherConnection as never, change("00000000-0000-4000-8000-000000000000", { type: "delete_draft", value: null, version_before_edit: 10 })),
      addOfflineChange(fixture.db as never, change("11111111-1111-4111-8111-111111111111", {
        version_before_edit: 0, encrypted_draft_preview: "encrypted-preview",
      })),
    ]);
    const persisted = await getOfflineChanges(otherConnection as never);
    expect(persisted.map((row) => [row.change_id.slice(0, 8), row.queue_order])).toEqual([
      ["ffffffff", 1], ["00000000", 2], ["11111111", 3],
    ]);
    expect(persisted[2].encrypted_draft_preview).toBe("encrypted-preview");
    expect(fixture.transactionModes).toEqual(["readwrite", "readwrite", "readwrite", "readonly"]);
  });

  // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
  it("preserves legacy rows and assigns a fresh order when replacing a change ID", async () => {
    const legacy = change("legacy", { version_before_edit: 6 });
    const fixture = makeSerializedDatabase([legacy, change("existing", { queue_order: 20 })]);
    const incoming = change("existing", { queue_order: 1, value: "replacement-cipher" });
    await addOfflineChange(fixture.db as never, incoming);
    expect(fixture.getRows()).toEqual([legacy, { ...incoming, queue_order: 21, queue_token: expect.any(String) }]);
    expect(incoming.queue_order).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
  it("does not rewrite or lose queued changes when the sequence is exhausted", async () => {
    const existing = change("last", { queue_order: Number.MAX_SAFE_INTEGER });
    const fixture = makeSerializedDatabase([existing]);
    await expect(addOfflineChange(fixture.db as never, change("new")))
      .rejects.toThrow("Offline change queue insertion order exhausted");
    expect(fixture.getRows()).toEqual([existing]);
  });

  // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
  it("queues its write synchronously in the ordering read callback", async () => {
    const fixture = makeDatabase([change("valid", { queue_order: 4 })]);
    const saving = addOfflineChange(fixture.db as never, change("new"));
    await deliverRead(fixture);
    expect(fixture.store.put).toHaveBeenCalledOnce();
    expect(fixture.store.put).toHaveBeenCalledWith(expect.objectContaining({ queue_order: 5 }));
    fixture.write.onsuccess?.();
    fixture.transaction.oncomplete?.();
    await saving;
  });
});


describe("offline acknowledgement insertion fence", () => {
  // contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
  it.each([
    { saved: 8, submitted: 7, removed: false },
    { saved: 7, submitted: 7, removed: true },
    { saved: 1, submitted: undefined, removed: false },
    { saved: undefined, submitted: undefined, removed: true },
    { saved: 1, submitted: 1, token: "new-insertion", submittedToken: "old-insertion", removed: false },
    { saved: 1, submitted: 1, token: "same-insertion", submittedToken: "same-insertion", removed: true },
  ])("removes only the acknowledged insertion $saved/$submitted", async ({ saved, submitted, removed, token, submittedToken }) => {
    const read = { result: { change_id: "same-id", queue_order: saved, queue_token: token },
      onsuccess: null as (() => void) | null, onerror: null as (() => void) | null };
    const write = { onsuccess: null as (() => void) | null, onerror: null as (() => void) | null };
    const store = { get: vi.fn(() => read), delete: vi.fn(() => write) };
    const tx = { objectStore: () => store };
    const db = { init: async () => {} };
    const deleting = deleteOfflineChange(db as never, "same-id", tx as never, { queueOrder: submitted, queueToken: submittedToken });
    await Promise.resolve();
    read.onsuccess?.();
    if (removed) write.onsuccess?.();
    await deleting;
    expect(store.delete).toHaveBeenCalledTimes(removed ? 1 : 0);
  });
});

describe("offline insertion workspace boundary", () => {
  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,drafts.persistence.local-first-encrypted
  it("aborts before writing when the workspace changes while the order read is pending", async () => {
    const fixture = makeDatabase();
    const saving = addOfflineChange(fixture.db as never, change("old-account"));
    const rejected = expect(saving).rejects.toThrow("Offline change workspace changed");
    await Promise.resolve();
    await Promise.resolve();
    invalidateWorkspaceCaches();
    fixture.read.onsuccess?.();
    await rejected;
    expect(fixture.store.put).not.toHaveBeenCalled();
    expect(fixture.transaction.abort).toHaveBeenCalledOnce();
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,drafts.persistence.local-first-encrypted
  it("does not open a new account transaction after a delayed old initialization", async () => {
    const fixture = makeDatabase();
    let finish!: () => void;
    fixture.db.init = () => new Promise<void>((resolve) => { finish = resolve; });
    const saving = addOfflineChange(fixture.db as never, change("old-account"));
    const rejected = expect(saving).rejects.toThrow("Offline change workspace changed");
    invalidateWorkspaceCaches();
    finish();
    await rejected;
    expect(fixture.db.getTransaction).not.toHaveBeenCalled();
  });
});
