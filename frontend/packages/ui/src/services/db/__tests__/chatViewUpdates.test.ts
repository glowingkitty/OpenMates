import { afterEach, describe, expect, it, vi } from "vitest";
import type { Chat } from "../../../types/chat";
import { invalidateWorkspaceCaches } from "../../workspaceCacheLifecycle";
import { updateChatReadStatus, updateChatScrollPosition } from "../offlineChangesAndUpdates";

const crud = vi.hoisted(() => ({ getChat: vi.fn(), addChat: vi.fn() }));
vi.mock("../chatCrudOperations", () => crud);

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

function makeDatabase(autoRead = false) {
  let stored = {
    chat_id: "team-chat", team_id: "team-1", updated_at: 100,
    draft_v: 0, encrypted_draft_md: "old-cipher", encrypted_draft_preview: "old-preview",
    unread_count: 2, last_visible_message_id: "old-message",
  } as Chat;
  const transactionRequested = deferred();
  const releaseTransaction = deferred();
  const readRequested = deferred();
  crud.getChat.mockImplementation(async () => {
    // Published code decrypted this snapshot before the draft write, then
    // resumed addChat with the stale whole row after the draft committed.
    const staleSnapshot = structuredClone(stored);
    transactionRequested.resolve();
    await releaseTransaction.promise;
    return staleSnapshot;
  });
  crud.addChat.mockImplementation(async (_db, chat: Chat) => { stored = structuredClone(chat); });
  const request = {
    result: undefined as Chat | undefined,
    error: null as DOMException | null,
    onsuccess: null as (() => void) | null,
    onerror: null as (() => void) | null,
  };
  const put = vi.fn((chat: Chat) => { stored = structuredClone(chat); });
  const store = {
    get: vi.fn(() => {
      readRequested.resolve();
      if (autoRead) queueMicrotask(() => {
        request.result = structuredClone(stored);
        request.onsuccess?.();
        transaction.oncomplete?.();
      });
      return request;
    }),
    put,
  };
  const transaction = {
    objectStore: () => store,
    oncomplete: null as (() => void) | null,
    onerror: null as (() => void) | null,
    onabort: null as (() => void) | null,
    error: null as DOMException | null,
  };
  const db = {
    CHATS_STORE_NAME: "chats",
    init: vi.fn(async () => undefined),
    getTransaction: vi.fn(async () => {
      transactionRequested.resolve();
      await releaseTransaction.promise;
      return transaction;
    }),
  };
  return {
    db, request, store, transaction, put,
    transactionRequested: transactionRequested.promise,
    readRequested: readRequested.promise,
    releaseTransaction: releaseTransaction.resolve,
    getStored: () => stored,
    saveDraft: () => {
      stored = { ...stored, draft_v: 3, encrypted_draft_md: "latest-cipher",
        encrypted_draft_preview: "latest-preview", team_draft_pending_sync: "update" };
    },
    deliverRead: () => {
      request.result = structuredClone(stored);
      request.onsuccess?.();
      transaction.oncomplete?.();
    },
  };
}

afterEach(() => { vi.clearAllMocks(); invalidateWorkspaceCaches(); });

describe("atomic chat view updates", () => {
  // contract-test: direct surface=gui.web assertions=teams.collaboration.realtime-team-sync,drafts.persistence.local-first-encrypted
  it.each([
    ["read status", updateChatReadStatus, 0, "unread_count"],
    ["scroll position", updateChatScrollPosition, "new-message", "last_visible_message_id"],
  ] as const)("preserves a Team draft saved while %s waits for its write transaction", async (_name, update, value, field) => {
    const fixture = makeDatabase(true);
    const updating = update(fixture.db as never, "team-chat", value as never);
    await fixture.transactionRequested;
    fixture.saveDraft();
    fixture.releaseTransaction();
    await updating;

    expect(fixture.getStored()).toEqual(expect.objectContaining({
      [field]: value, draft_v: 3, encrypted_draft_md: "latest-cipher",
      encrypted_draft_preview: "latest-preview", team_draft_pending_sync: "update",
      updated_at: 100,
    }));
    expect(fixture.put).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local,drafts.persistence.local-first-encrypted
  it("drops an in-flight view write after the account or Team cache epoch changes", async () => {
    const fixture = makeDatabase();
    const updating = updateChatReadStatus(fixture.db as never, "team-chat", 0);
    await fixture.transactionRequested;
    fixture.releaseTransaction();
    await fixture.readRequested;
    invalidateWorkspaceCaches();
    fixture.deliverRead();
    await updating;
    expect(fixture.put).not.toHaveBeenCalled();
    expect(fixture.getStored().unread_count).toBe(2);
  });

  // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
  it("reports a transaction abort instead of acknowledging a view write", async () => {
    const fixture = makeDatabase();
    const updating = updateChatReadStatus(fixture.db as never, "team-chat", 0);
    const rejected = expect(updating).rejects.toMatchObject({ name: "QuotaExceededError" });
    await fixture.transactionRequested;
    fixture.releaseTransaction();
    await fixture.readRequested;
    fixture.request.result = fixture.getStored();
    fixture.request.onsuccess?.();
    fixture.transaction.error = new DOMException("full", "QuotaExceededError");
    fixture.transaction.onabort?.();
    await rejected;
  });
});
