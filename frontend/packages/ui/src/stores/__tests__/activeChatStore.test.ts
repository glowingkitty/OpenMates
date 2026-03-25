// frontend/packages/ui/src/stores/__tests__/activeChatStore.test.ts
// Unit tests for activeChatStore — the store tracking the currently selected chat ID.
//
// Bug history this test suite guards against:
//  - Five consecutive bugs caused by stores assuming sidebar component was mounted
//  - Deep link processing race conditions with auto-loading
//  - URL hash not clearing on chat deselection
//
// Architecture: frontend/packages/ui/src/stores/activeChatStore.ts

import { describe, it, expect, beforeEach, vi } from "vitest";
import { get } from "svelte/store";

// The store reads window.location.hash at module-init time.
// We must patch location onto the global window BEFORE the module loads.
// vi.hoisted runs before vi.mock but after test-setup.ts, so it's the right place.
const locationMock = vi.hoisted(() => {
  const loc = { hash: "", pathname: "/", search: "" };
  // test-setup.ts creates window as writable; add location before any imports
  (globalThis as Record<string, unknown>).window = {
    ...(globalThis as Record<string, unknown>).window as object,
    location: loc,
  };
  return loc;
});

// Mock $app/environment and $app/navigation before importing the store
vi.mock("$app/environment", () => ({ browser: true }));
vi.mock("$app/navigation", () => ({
  replaceState: vi.fn(),
}));

// Import after mocks are set up
import {
  activeChatStore,
  deepLinkProcessing,
  isProgrammaticHashUpdate,
} from "../activeChatStore";

describe("activeChatStore", () => {
  beforeEach(() => {
    locationMock.hash = "";
    locationMock.pathname = "/";
    locationMock.search = "";
    activeChatStore.clearActiveChat();
  });

  // ──────────────────────────────────────────────────────────────────
  // Initial state
  // ──────────────────────────────────────────────────────────────────

  describe("initial state", () => {
    it("starts as null when no hash is present", () => {
      expect(activeChatStore.get()).toBeNull();
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // setActiveChat
  // ──────────────────────────────────────────────────────────────────

  describe("setActiveChat", () => {
    it("sets the active chat ID", () => {
      activeChatStore.setActiveChat("chat-123");
      expect(activeChatStore.get()).toBe("chat-123");
    });

    it("updates URL hash with chat ID", () => {
      activeChatStore.setActiveChat("chat-456");
      expect(locationMock.hash).toBe("chat-id=chat-456");
    });

    it("sets null to clear active chat", () => {
      activeChatStore.setActiveChat("chat-123");
      activeChatStore.setActiveChat(null);
      expect(activeChatStore.get()).toBeNull();
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // clearActiveChat
  // ──────────────────────────────────────────────────────────────────

  describe("clearActiveChat", () => {
    it("sets store to null", () => {
      activeChatStore.setActiveChat("chat-123");
      activeChatStore.clearActiveChat();
      expect(activeChatStore.get()).toBeNull();
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // setWithoutHashUpdate
  // ──────────────────────────────────────────────────────────────────

  describe("setWithoutHashUpdate", () => {
    it("updates store value without changing URL hash", () => {
      locationMock.hash = "";
      activeChatStore.setWithoutHashUpdate("chat-789");
      expect(activeChatStore.get()).toBe("chat-789");
      // Hash should NOT be updated
      expect(locationMock.hash).toBe("");
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // getChatIdFromHash
  // ──────────────────────────────────────────────────────────────────

  describe("getChatIdFromHash", () => {
    it("returns null when no hash present", () => {
      locationMock.hash = "";
      expect(activeChatStore.getChatIdFromHash()).toBeNull();
    });

    it("returns chat ID from valid hash", () => {
      locationMock.hash = "#chat-id=abc-123";
      expect(activeChatStore.getChatIdFromHash()).toBe("abc-123");
    });

    it("returns null for unrelated hash", () => {
      locationMock.hash = "#other-param=value";
      expect(activeChatStore.getChatIdFromHash()).toBeNull();
    });

    it("returns null for empty chat-id hash", () => {
      locationMock.hash = "#chat-id=";
      expect(activeChatStore.getChatIdFromHash()).toBeNull();
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // subscribe / get
  // ──────────────────────────────────────────────────────────────────

  describe("subscribe", () => {
    it("notifies subscribers on change", () => {
      const values: (string | null)[] = [];
      const unsubscribe = activeChatStore.subscribe((v) => values.push(v));

      activeChatStore.setActiveChat("chat-a");
      activeChatStore.setActiveChat("chat-b");
      activeChatStore.clearActiveChat();

      unsubscribe();

      // First value is the current value at subscribe time (null),
      // then chat-a, chat-b, null
      expect(values).toEqual([null, "chat-a", "chat-b", null]);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // isProgrammaticHashUpdate
  // ──────────────────────────────────────────────────────────────────

  describe("isProgrammaticHashUpdate", () => {
    it("returns true immediately after setActiveChat", () => {
      activeChatStore.setActiveChat("chat-123");
      expect(isProgrammaticHashUpdate()).toBe(true);
    });

    it("returns false when no recent programmatic update", async () => {
      // Without any setActiveChat call, should be false
      // (or enough time has passed since the last one in beforeEach)
      await new Promise((r) => setTimeout(r, 150));
      expect(isProgrammaticHashUpdate()).toBe(false);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // deepLinkProcessing store
  // ──────────────────────────────────────────────────────────────────

  describe("deepLinkProcessing", () => {
    it("starts as false", () => {
      expect(get(deepLinkProcessing)).toBe(false);
    });

    it("can be set to true during deep link processing", () => {
      deepLinkProcessing.set(true);
      expect(get(deepLinkProcessing)).toBe(true);
      deepLinkProcessing.set(false);
    });
  });
});
