// frontend/packages/ui/src/stores/__tests__/unreadMessagesStore.test.ts
// Unit tests for unread messages store — per-chat unread count tracking
// for background AI responses and cross-device sync.
//
// Architecture: frontend/packages/ui/src/stores/unreadMessagesStore.ts

import { describe, it, expect, beforeEach } from "vitest";
import { get } from "svelte/store";
import { unreadMessagesStore } from "../unreadMessagesStore";

describe("unreadMessagesStore", () => {
  beforeEach(() => {
    unreadMessagesStore.clearAll();
  });

  // ──────────────────────────────────────────────────────────────────
  // Initial state
  // ──────────────────────────────────────────────────────────────────

  describe("initial state", () => {
    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
    it("starts with empty unread counts", () => {
      const state = get(unreadMessagesStore);
      expect(state.unreadCounts.size).toBe(0);
    });

    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
    it("getUnreadCount returns 0 for unknown chat", () => {
      expect(unreadMessagesStore.getUnreadCount("unknown")).toBe(0);
    });

    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
    it("getTotalUnread returns 0 when empty", () => {
      expect(unreadMessagesStore.getTotalUnread()).toBe(0);
    });
  });
});
