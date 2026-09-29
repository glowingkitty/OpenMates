import { writable } from "svelte/store";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../stores/signupState", () => ({
  forcedLogoutInProgress: writable(false),
  isLoggingOut: writable(false),
  setForcedLogoutInProgress: vi.fn(),
  lastResumeTimestamp: 0,
  RESUME_ORPHAN_GRACE_MS: 0,
}));
vi.mock("../../stores/authState", () => ({ isCheckingAuth: writable(false) }));
vi.mock("../cryptoService", () => ({ getKeyFromStorage: vi.fn(async () => null) }));

import { userDB } from "../userDB";

function request<T>(): IDBOpenDBRequest & { result: T } {
  return {
    result: undefined as T,
    onblocked: null,
    onsuccess: null,
    onerror: null,
    onupgradeneeded: null,
  } as unknown as IDBOpenDBRequest & { result: T };
}

function signal(handler: ((event: Event) => unknown) | null): void {
  handler?.(new Event("success"));
}

beforeEach(() => {
  userDB.db = null;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("user database deletion and schema recovery", () => {
  // contract-test: supporting surface=gui.web assertions=auth.secrets.lifecycle
  it("keeps local operations fenced until a blocked delete really completes", async () => {
    const deletionRequest = request<IDBDatabase>();
    const deleteDatabase = vi.fn(() => deletionRequest);
    vi.stubGlobal("indexedDB", { deleteDatabase });

    const deletion = userDB.deleteDatabase();
    await new Promise((resolve) => setTimeout(resolve, 120));
    signal(deletionRequest.onblocked as (event: Event) => unknown);
    await expect(deletion).rejects.toThrow("blocked");

    await expect(userDB.saveUserData({} as never)).rejects.toThrow("deletion is pending");
    const duplicateDelete = userDB.deleteDatabase();
    expect(deleteDatabase).toHaveBeenCalledTimes(1);

    signal(deletionRequest.onsuccess as (event: Event) => unknown);
    await expect(duplicateDelete).resolves.toBeUndefined();
    expect(deleteDatabase).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=auth.keys.independent-unlock
  it("repairs a database at the current version when its user_data store is missing", async () => {
    const first = request<IDBDatabase>();
    const repair = request<IDBDatabase>();
    const close = vi.fn();
    let hasStore = false;
    const createObjectStore = vi.fn(() => { hasStore = true; });
    first.result = {
      version: 2,
      objectStoreNames: { contains: () => false },
      close,
    } as unknown as IDBDatabase;
    repair.result = {
      version: 3,
      objectStoreNames: { contains: () => hasStore },
      createObjectStore,
      close: vi.fn(),
    } as unknown as IDBDatabase;
    const open = vi.fn()
      .mockReturnValueOnce(first)
      .mockReturnValueOnce(repair);
    vi.stubGlobal("indexedDB", { open });

    const initialization = userDB.init();
    await vi.waitFor(() => expect(open).toHaveBeenCalledTimes(1));
    signal(first.onsuccess as (event: Event) => unknown);
    expect(close).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenLastCalledWith("user_db", 3);
    signal(repair.onupgradeneeded as (event: Event) => unknown);
    signal(repair.onsuccess as (event: Event) => unknown);
    await expect(initialization).resolves.toBeUndefined();
    expect(createObjectStore).toHaveBeenCalledWith("user_data");
    expect(userDB.db).toBe(repair.result);
    userDB.db?.close();
    userDB.db = null;
  });

  // contract-test: supporting surface=gui.web assertions=auth.secrets.lifecycle
  it("closes a late open result after its blocked request was abandoned", async () => {
    const pendingOpen = request<IDBDatabase>();
    const close = vi.fn();
    pendingOpen.result = {
      objectStoreNames: { contains: () => true },
      close,
    } as unknown as IDBDatabase;
    vi.stubGlobal("indexedDB", { open: vi.fn(() => pendingOpen) });

    const initialization = userDB.init();
    await vi.waitFor(() => expect(pendingOpen.onblocked).not.toBeNull());
    signal(pendingOpen.onblocked as (event: Event) => unknown);
    await expect(initialization).rejects.toThrow("blocked");
    signal(pendingOpen.onsuccess as (event: Event) => unknown);

    expect(close).toHaveBeenCalledTimes(1);
    expect(userDB.db).toBeNull();
  });
});
