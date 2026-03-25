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
    it("starts with empty unread counts", () => {
      const state = get(unreadMessagesStore);
      expect(state.unreadCounts.size).toBe(0);
    });

    it("getUnreadCount returns 0 for unknown chat", () => {
      expect(unreadMessagesStore.getUnreadCount("unknown")).toBe(0);
    });

    it("getTotalUnread returns 0 when empty", () => {
      expect(unreadMessagesStore.getTotalUnread()).toBe(0);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // incrementUnread
  // ──────────────────────────────────────────────────────────────────

  describe("incrementUnread", () => {
    it("increments from 0 to 1", () => {
      unreadMessagesStore.incrementUnread("chat-1");
      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(1);
    });

    it("increments cumulatively", () => {
      unreadMessagesStore.incrementUnread("chat-1");
      unreadMessagesStore.incrementUnread("chat-1");
      unreadMessagesStore.incrementUnread("chat-1");
      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(3);
    });

    it("increments independently per chat", () => {
      unreadMessagesStore.incrementUnread("chat-1");
      unreadMessagesStore.incrementUnread("chat-1");
      unreadMessagesStore.incrementUnread("chat-2");

      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(2);
      expect(unreadMessagesStore.getUnreadCount("chat-2")).toBe(1);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // setUnread
  // ──────────────────────────────────────────────────────────────────

  describe("setUnread", () => {
    it("sets count to a specific value", () => {
      unreadMessagesStore.setUnread("chat-1", 5);
      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(5);
    });

    it("setting count to 0 removes the entry", () => {
      unreadMessagesStore.setUnread("chat-1", 5);
      unreadMessagesStore.setUnread("chat-1", 0);

      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(0);
      expect(get(unreadMessagesStore).unreadCounts.has("chat-1")).toBe(false);
    });

    it("setting negative count removes the entry", () => {
      unreadMessagesStore.setUnread("chat-1", 3);
      unreadMessagesStore.setUnread("chat-1", -1);

      expect(get(unreadMessagesStore).unreadCounts.has("chat-1")).toBe(false);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // clearUnread
  // ──────────────────────────────────────────────────────────────────

  describe("clearUnread", () => {
    it("removes unread count for a chat", () => {
      unreadMessagesStore.incrementUnread("chat-1");
      unreadMessagesStore.clearUnread("chat-1");
      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(0);
    });

    it("does not affect other chats", () => {
      unreadMessagesStore.incrementUnread("chat-1");
      unreadMessagesStore.incrementUnread("chat-2");
      unreadMessagesStore.clearUnread("chat-1");

      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(0);
      expect(unreadMessagesStore.getUnreadCount("chat-2")).toBe(1);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // getTotalUnread
  // ──────────────────────────────────────────────────────────────────

  describe("getTotalUnread", () => {
    it("sums unread counts across all chats", () => {
      unreadMessagesStore.setUnread("chat-1", 3);
      unreadMessagesStore.setUnread("chat-2", 7);
      unreadMessagesStore.incrementUnread("chat-3");

      expect(unreadMessagesStore.getTotalUnread()).toBe(11);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // clearAll
  // ──────────────────────────────────────────────────────────────────

  describe("clearAll", () => {
    it("removes all unread counts", () => {
      unreadMessagesStore.setUnread("chat-1", 5);
      unreadMessagesStore.setUnread("chat-2", 3);
      unreadMessagesStore.clearAll();

      expect(unreadMessagesStore.getTotalUnread()).toBe(0);
      expect(get(unreadMessagesStore).unreadCounts.size).toBe(0);
    });
  });
});
