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

  // ──────────────────────────────────────────────────────────────────
  // incrementUnread
  // ──────────────────────────────────────────────────────────────────

  describe("incrementUnread", () => {
    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
    it("increments from 0 to 1", () => {
      unreadMessagesStore.incrementUnread("chat-1");
      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(1);
    });

    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
    it("increments cumulatively", () => {
      unreadMessagesStore.incrementUnread("chat-1");
      unreadMessagesStore.incrementUnread("chat-1");
      unreadMessagesStore.incrementUnread("chat-1");
      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(3);
    });

    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
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
    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
    it("sets count to a specific value", () => {
      unreadMessagesStore.setUnread("chat-1", 5);
      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(5);
    });

    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
    it("setting count to 0 removes the entry", () => {
      unreadMessagesStore.setUnread("chat-1", 5);
      unreadMessagesStore.setUnread("chat-1", 0);

      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(0);
      expect(get(unreadMessagesStore).unreadCounts.has("chat-1")).toBe(false);
    });

    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
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
    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
    it("removes unread count for a chat", () => {
      unreadMessagesStore.incrementUnread("chat-1");
      unreadMessagesStore.clearUnread("chat-1");
      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(0);
    });

    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
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
    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
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
    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
    it("removes all unread counts", () => {
      unreadMessagesStore.setUnread("chat-1", 5);
      unreadMessagesStore.setUnread("chat-2", 3);
      unreadMessagesStore.clearAll();

      expect(unreadMessagesStore.getTotalUnread()).toBe(0);
      expect(get(unreadMessagesStore).unreadCounts.size).toBe(0);
    });
  });

  describe("per-reply dedupe", () => {
    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
    it("counts the same reply once when local and server signals both arrive", () => {
      unreadMessagesStore.incrementUnread("chat-1", "reply-1");
      unreadMessagesStore.setUnread("chat-1", 1, "reply-1");
      unreadMessagesStore.incrementUnread("chat-1", "reply-1");
      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(1);
    });

    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
    it("ignores a late local increment for a reply the server already counted", () => {
      unreadMessagesStore.setUnread("chat-1", 1, "reply-1");
      unreadMessagesStore.incrementUnread("chat-1", "reply-1");
      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(1);
    });

    // contract-test: supporting surface=gui.web assertions=chat-unread.persistence.cross-device
    it("does not resurrect a read reply when its late local increment arrives", () => {
      unreadMessagesStore.setUnread("chat-1", 1, "reply-1");
      unreadMessagesStore.clearUnread("chat-1");
      unreadMessagesStore.incrementUnread("chat-1", "reply-1");
      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(0);
    });

    // contract-test: supporting surface=gui.web assertions=chat-unread.followup.implies-read,chat-unread.persistence.cross-device
    it("counts a follow-up reply after the previous one was read as one", () => {
      unreadMessagesStore.incrementUnread("chat-1", "reply-1");
      unreadMessagesStore.clearUnread("chat-1");
      unreadMessagesStore.incrementUnread("chat-1", "reply-2");
      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(1);
    });
  });

  describe("manual unread", () => {
    // contract-test: supporting surface=gui.web assertions=chat-unread.manual.mark-unread
    it("sets exactly one and is flagged until released or read", () => {
      unreadMessagesStore.incrementUnread("chat-1", "reply-1");
      unreadMessagesStore.incrementUnread("chat-1", "reply-2");
      unreadMessagesStore.markManuallyUnread("chat-1");
      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(1);
      expect(unreadMessagesStore.isManuallyUnread("chat-1")).toBe(true);
      unreadMessagesStore.releaseManualUnread("chat-1");
      expect(unreadMessagesStore.isManuallyUnread("chat-1")).toBe(false);
      expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(1);
    });

    // contract-test: supporting surface=gui.web assertions=chat-unread.manual.mark-unread
    it("is cleared by clearUnread", () => {
      unreadMessagesStore.markManuallyUnread("chat-1");
      unreadMessagesStore.clearUnread("chat-1");
      expect(unreadMessagesStore.isManuallyUnread("chat-1")).toBe(false);
    });
  });
});
