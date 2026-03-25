// frontend/packages/ui/src/stores/__tests__/phasedSyncState.test.ts
// Unit tests for phasedSyncState store — the state machine controlling sync phases.
//
// Bug history this test suite guards against:
//  - 45faffa1f: infinite syncing after forced logout (sync never re-triggered)
//  - b1edc62f6: stale Phase 1 resume data on new-chat transition
//  - 65c9be48a: stale resume card and missing summary on welcome screen
//  - 40f94e857: sync-update last_opened before new-chat transition for resume card
//  - 3dc13a5b1: Phase 1 handler not populating resume card directly
//  - Race condition where Phase 1 auto-opens old chat over user's "new chat" click
//
// Architecture: frontend/packages/ui/src/stores/phasedSyncStateStore.ts

import { describe, it, expect, beforeEach } from "vitest";
import { get } from "svelte/store";
import {
  phasedSyncState,
  NEW_CHAT_SENTINEL,
} from "../phasedSyncStateStore";

describe("phasedSyncState", () => {
  beforeEach(() => {
    phasedSyncState.reset();
  });

  // ──────────────────────────────────────────────────────────────────
  // Initial state
  // ──────────────────────────────────────────────────────────────────

  describe("initial state", () => {
    it("starts with all flags false/null", () => {
      const state = get(phasedSyncState);
      expect(state.initialSyncCompleted).toBe(false);
      expect(state.phase1ChatId).toBeNull();
      expect(state.currentActiveChatId).toBeNull();
      expect(state.lastSyncTimestamp).toBeNull();
      expect(state.initialChatLoaded).toBe(false);
      expect(state.userMadeExplicitChoice).toBe(false);
      expect(state.resumeChatData).toBeNull();
      expect(state.resumeChatTitle).toBeNull();
      expect(state.resumeChatCategory).toBeNull();
      expect(state.resumeChatIcon).toBeNull();
      expect(state.resumeChatSummary).toBeNull();
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // reset() vs resetForLogin() (bug: race condition in Phase 1 auto-select)
  // ──────────────────────────────────────────────────────────────────

  describe("reset()", () => {
    it("clears all state back to initial", () => {
      phasedSyncState.markSyncCompleted();
      phasedSyncState.markUserMadeExplicitChoice();
      phasedSyncState.setCurrentActiveChatId("chat-123");
      phasedSyncState.setPhase1ChatId("phase1-chat");

      phasedSyncState.reset();

      const state = get(phasedSyncState);
      expect(state.initialSyncCompleted).toBe(false);
      expect(state.userMadeExplicitChoice).toBe(false);
      expect(state.currentActiveChatId).toBeNull();
      expect(state.phase1ChatId).toBeNull();
    });
  });

  describe("resetForLogin()", () => {
    it("preserves userMadeExplicitChoice across login", () => {
      // User clicks "new chat" → then logs in → Phase 1 arrives
      // resetForLogin should NOT wipe their explicit choice
      phasedSyncState.markUserMadeExplicitChoice();
      phasedSyncState.setCurrentActiveChatId(NEW_CHAT_SENTINEL);

      phasedSyncState.resetForLogin();

      const state = get(phasedSyncState);
      expect(state.userMadeExplicitChoice).toBe(true);
      expect(state.currentActiveChatId).toBe(NEW_CHAT_SENTINEL);
    });

    it("resets sync progress but preserves navigation", () => {
      phasedSyncState.markSyncCompleted();
      phasedSyncState.markInitialChatLoaded();
      phasedSyncState.setPhase1ChatId("old-phase1");
      phasedSyncState.setCurrentActiveChatId("my-chat");

      phasedSyncState.resetForLogin();

      const state = get(phasedSyncState);
      expect(state.initialSyncCompleted).toBe(false);
      expect(state.initialChatLoaded).toBe(false);
      expect(state.phase1ChatId).toBeNull();
      expect(state.resumeChatData).toBeNull();
      // Preserved:
      expect(state.currentActiveChatId).toBe("my-chat");
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // shouldAutoSelectPhase1Chat (prevents sync from overriding user)
  // ──────────────────────────────────────────────────────────────────

  describe("shouldAutoSelectPhase1Chat", () => {
    it("returns true when no user interaction has happened", () => {
      expect(phasedSyncState.shouldAutoSelectPhase1Chat("chat-1")).toBe(true);
    });

    it("returns false when user made explicit choice (clicked a chat)", () => {
      phasedSyncState.markUserMadeExplicitChoice();
      expect(phasedSyncState.shouldAutoSelectPhase1Chat("chat-1")).toBe(false);
    });

    it("returns false when user is in new-chat mode (sentinel)", () => {
      phasedSyncState.setCurrentActiveChatId(NEW_CHAT_SENTINEL);
      expect(phasedSyncState.shouldAutoSelectPhase1Chat("chat-1")).toBe(false);
    });

    it("returns false when initial chat already loaded", () => {
      phasedSyncState.markInitialChatLoaded();
      expect(phasedSyncState.shouldAutoSelectPhase1Chat("chat-1")).toBe(false);
    });

    it("returns false when user is in a different chat", () => {
      phasedSyncState.setCurrentActiveChatId("other-chat");
      expect(phasedSyncState.shouldAutoSelectPhase1Chat("chat-1")).toBe(false);
    });

    it("returns true when user is in the same chat as Phase 1", () => {
      phasedSyncState.setCurrentActiveChatId("chat-1");
      expect(phasedSyncState.shouldAutoSelectPhase1Chat("chat-1")).toBe(true);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // canAutoNavigate
  // ──────────────────────────────────────────────────────────────────

  describe("canAutoNavigate", () => {
    it("returns true initially", () => {
      expect(phasedSyncState.canAutoNavigate()).toBe(true);
    });

    it("returns false after user made explicit choice", () => {
      phasedSyncState.markUserMadeExplicitChoice();
      expect(phasedSyncState.canAutoNavigate()).toBe(false);
    });

    it("returns false after initial chat loaded", () => {
      phasedSyncState.markInitialChatLoaded();
      expect(phasedSyncState.canAutoNavigate()).toBe(false);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // setResumeChatData (bugs: 65c9be48a, b1edc62f6)
  // ──────────────────────────────────────────────────────────────────

  describe("setResumeChatData", () => {
    const mockChat = { chat_id: "resume-1", title: "Test" } as any;

    it("sets resume chat data on welcome screen (no active chat)", () => {
      phasedSyncState.setResumeChatData(mockChat, "My Chat Title", "tech", "cpu");
      const state = get(phasedSyncState);
      expect(state.resumeChatData).toEqual(mockChat);
      expect(state.resumeChatTitle).toBe("My Chat Title");
      expect(state.resumeChatCategory).toBe("tech");
      expect(state.resumeChatIcon).toBe("cpu");
    });

    it("sets resume chat data in new-chat mode (sentinel)", () => {
      phasedSyncState.setCurrentActiveChatId(NEW_CHAT_SENTINEL);
      phasedSyncState.setResumeChatData(mockChat, "Title");
      expect(get(phasedSyncState).resumeChatData).toEqual(mockChat);
    });

    it("skips when user is in an active chat (defense-in-depth)", () => {
      phasedSyncState.setCurrentActiveChatId("some-other-chat");
      phasedSyncState.setResumeChatData(mockChat, "Title");
      expect(get(phasedSyncState).resumeChatData).toBeNull();
    });

    it("force flag bypasses the active chat guard", () => {
      phasedSyncState.setCurrentActiveChatId("some-other-chat");
      phasedSyncState.setResumeChatData(mockChat, "Title", null, null, true);
      expect(get(phasedSyncState).resumeChatData).toEqual(mockChat);
    });

    it("includes summary when provided", () => {
      phasedSyncState.setResumeChatData(
        mockChat,
        "Title",
        "category",
        "icon",
        false,
        "This is a summary"
      );
      expect(get(phasedSyncState).resumeChatSummary).toBe("This is a summary");
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // clearResumeChatData (bug: b1edc62f6)
  // ──────────────────────────────────────────────────────────────────

  describe("clearResumeChatData", () => {
    it("clears all resume fields", () => {
      const mockChat = { chat_id: "x" } as any;
      phasedSyncState.setResumeChatData(mockChat, "T", "C", "I", false, "S");
      phasedSyncState.clearResumeChatData();

      const state = get(phasedSyncState);
      expect(state.resumeChatData).toBeNull();
      expect(state.resumeChatTitle).toBeNull();
      expect(state.resumeChatCategory).toBeNull();
      expect(state.resumeChatIcon).toBeNull();
      expect(state.resumeChatSummary).toBeNull();
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // markSyncCompleted / updateSyncTimestamp
  // ──────────────────────────────────────────────────────────────────

  describe("sync tracking", () => {
    it("markSyncCompleted sets flag", () => {
      phasedSyncState.markSyncCompleted();
      expect(get(phasedSyncState).initialSyncCompleted).toBe(true);
    });

    it("updateSyncTimestamp sets a timestamp", () => {
      const before = Date.now();
      phasedSyncState.updateSyncTimestamp();
      const state = get(phasedSyncState);
      expect(state.lastSyncTimestamp).toBeGreaterThanOrEqual(before);
      expect(state.lastSyncTimestamp).toBeLessThanOrEqual(Date.now());
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // hasResumeChatData
  // ──────────────────────────────────────────────────────────────────

  describe("hasResumeChatData", () => {
    it("returns false when no resume data", () => {
      expect(phasedSyncState.hasResumeChatData()).toBe(false);
    });

    it("returns true when resume data is set", () => {
      phasedSyncState.setResumeChatData({ chat_id: "x" } as any, "T");
      expect(phasedSyncState.hasResumeChatData()).toBe(true);
    });
  });
});
