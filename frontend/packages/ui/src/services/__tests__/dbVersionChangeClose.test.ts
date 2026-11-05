import { describe, expect, it, vi } from "vitest";

vi.mock("$app/environment", () => ({ browser: false }));
vi.mock("../db/newChatSuggestions", () => ({}));
vi.mock("../db/pendingEmbedQueue", () => ({ putPendingEmbedOperation: vi.fn() }));
vi.mock("../db/appSettingsMemories", () => ({}));
vi.mock("../db/chatKeyManagement", () => ({}));
vi.mock("../db/messageOperations", () => ({}));
vi.mock("../db/chatCrudOperations", () => ({}));
vi.mock("../db/offlineChangesAndUpdates", () => ({}));
vi.mock("../db/quotaRecovery", () => ({ writeWithQuotaRetry: vi.fn() }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: {} }));
vi.mock("../../stores/notificationStore", () => ({ notificationStore: {} }));
vi.mock("../cryptoService", () => ({ getKeyFromStorage: async () => null }));
vi.mock("../../stores/signupState", () => ({
  forcedLogoutInProgress: {}, isLoggingOut: {},
  setForcedLogoutInProgress: vi.fn(), lastResumeTimestamp: 0, RESUME_ORPHAN_GRACE_MS: 3000,
}));

import { chatDB, IndexedDbDeleteBlockedError } from "../db";

interface Internals {
  db: unknown;
  initializationPromise: unknown;
  installVersionChangeHandler(db: IDBDatabase): void;
}

describe("ChatDatabase versionchange handling", () => {
  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it("closes the connection and drops the cached handle so a peer-tab delete is not blocked", () => {
    const internals = chatDB as unknown as Internals;
    const db = { close: vi.fn(), onversionchange: null } as unknown as IDBDatabase;
    internals.db = db;
    internals.initializationPromise = Promise.resolve();
    internals.installVersionChangeHandler(db);

    (db.onversionchange as () => void)();

    expect(db.close).toHaveBeenCalledTimes(1);
    expect(internals.db).toBeNull();
    // Next access reopens lazily through init().
    expect(internals.initializationPromise).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it("does not clear a newer connection when a stale one receives versionchange", () => {
    const internals = chatDB as unknown as Internals;
    const stale = { close: vi.fn(), onversionchange: null } as unknown as IDBDatabase;
    const current = { close: vi.fn() } as unknown as IDBDatabase;
    internals.installVersionChangeHandler(stale);
    internals.db = current;

    (stale.onversionchange as () => void)();

    expect(stale.close).toHaveBeenCalledTimes(1);
    expect(internals.db).toBe(current);
    internals.db = null;
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it("exposes a typed blocked-delete error", () => {
    const error = new IndexedDbDeleteBlockedError("chats_db");
    expect(error).toBeInstanceOf(Error);
    expect(error.databaseName).toBe("chats_db");
  });
});
