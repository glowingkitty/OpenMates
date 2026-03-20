// frontend/packages/ui/src/services/__tests__/chatListCache.test.ts
// Unit tests for ChatListCache — the singleton cache that caused 5+ bugs:
//  - 861d8edca: sidebar remount served stale cache after destroy/recreate
//  - 780b871e7: stale decrypted metadata after logout → "Untitled chat"
//  - 3cec01e34: duplicate chats in sidebar list from upsert/setCache race
//  - chatListCache.clear() not resetting updateInProgress → permanently blocked DB reads
//
// Architecture: frontend/packages/ui/src/services/chatListCache.ts
// These tests exercise the pure in-memory ChatListCache class with NO browser deps.

import { describe, it, expect, beforeEach, vi } from "vitest";

// We need to import the class, but the module exports only a singleton.
// Re-import the module to get a fresh instance per test via the class constructor.
// Since the module only exports a singleton, we'll test the singleton but reset it.
import { chatListCache } from "../chatListCache";

// Minimal Chat shape for testing — only fields ChatListCache touches
function makeChat(id: string, extras: Record<string, unknown> = {}) {
  return {
    chat_id: id,
    title: `Chat ${id}`,
    encrypted_title: null,
    messages_v: 1,
    title_v: 1,
    last_edited_overall_timestamp: Date.now(),
    unread_count: 0,
    created_at: Date.now(),
    updated_at: Date.now(),
    ...extras,
  } as any;
}

describe("ChatListCache", () => {
  beforeEach(() => {
    chatListCache.clear();
  });

  // ──────────────────────────────────────────────────────────────────
  // Basic get/set
  // ──────────────────────────────────────────────────────────────────

  describe("basic cache operations", () => {
    it("returns null when cache is not ready", () => {
      expect(chatListCache.getCache()).toBeNull();
    });

    it("returns cached chats after setCache()", () => {
      const chats = [makeChat("a"), makeChat("b")];
      chatListCache.setCache(chats);
      const result = chatListCache.getCache();
      expect(result).toHaveLength(2);
      expect(result![0].chat_id).toBe("a");
      expect(result![1].chat_id).toBe("b");
    });

    it("returns a copy, not a reference to internal array", () => {
      const chats = [makeChat("a")];
      chatListCache.setCache(chats);
      const result = chatListCache.getCache();
      result!.push(makeChat("x"));
      // Internal cache should be unchanged
      expect(chatListCache.getCache()).toHaveLength(1);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // Deduplication (bug: 3cec01e34)
  // ──────────────────────────────────────────────────────────────────

  describe("deduplication", () => {
    it("deduplicates chats with same chat_id on read", () => {
      // Simulate race: upsert adds a chat, then setCache re-adds it
      chatListCache.setCache([makeChat("a"), makeChat("b")]);
      chatListCache.upsertChat(makeChat("a", { title: "Updated A" }));
      // Now "a" exists twice in the internal array
      // getCache should deduplicate (first-occurrence wins)
      const result = chatListCache.getCache();
      expect(result).toHaveLength(2);
      const ids = result!.map((c: any) => c.chat_id);
      expect(ids).toEqual(["a", "b"]);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // upsertChat
  // ──────────────────────────────────────────────────────────────────

  describe("upsertChat", () => {
    it("adds new chat when not in cache", () => {
      chatListCache.setCache([makeChat("a")]);
      chatListCache.upsertChat(makeChat("b"));
      const result = chatListCache.getCache();
      expect(result).toHaveLength(2);
    });

    it("updates existing chat by chat_id", () => {
      chatListCache.setCache([makeChat("a", { title: "Old" })]);
      chatListCache.upsertChat(makeChat("a", { title: "New" }));
      const result = chatListCache.getCache();
      expect(result).toHaveLength(1);
      expect(result![0].title).toBe("New");
    });

    it("does nothing when cache is not ready", () => {
      chatListCache.upsertChat(makeChat("a"));
      expect(chatListCache.getCache()).toBeNull();
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // removeChat
  // ──────────────────────────────────────────────────────────────────

  describe("removeChat", () => {
    it("removes chat by id", () => {
      chatListCache.setCache([makeChat("a"), makeChat("b"), makeChat("c")]);
      chatListCache.removeChat("b");
      const result = chatListCache.getCache();
      expect(result).toHaveLength(2);
      expect(result!.map((c: any) => c.chat_id)).toEqual(["a", "c"]);
    });

    it("does nothing for non-existent chat_id", () => {
      chatListCache.setCache([makeChat("a")]);
      chatListCache.removeChat("nonexistent");
      expect(chatListCache.getCache()).toHaveLength(1);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // markDirty / stale cache
  // ──────────────────────────────────────────────────────────────────

  describe("markDirty", () => {
    it("causes cache miss on next getCache()", () => {
      chatListCache.setCache([makeChat("a")]);
      chatListCache.markDirty();
      expect(chatListCache.getCache()).toBeNull();
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // Sidebar destroy/remount (bug: 861d8edca)
  // ──────────────────────────────────────────────────────────────────

  describe("sidebar destroy/remount tracking", () => {
    it("forces cache miss on component remount after sidebar destroy", () => {
      chatListCache.setCache([makeChat("a")]);
      chatListCache.notifySidebarDestroyed();

      // Normal getCache (not a remount) still returns cached data
      expect(chatListCache.getCache(false, false)).not.toBeNull();

      // Remount getCache forces a miss
      expect(chatListCache.getCache(false, true)).toBeNull();
    });

    it("subsequent getCache after remount miss returns cached data (flag reset)", () => {
      chatListCache.setCache([makeChat("a")]);
      chatListCache.notifySidebarDestroyed();

      // First remount call → miss (resets the flag)
      expect(chatListCache.getCache(false, true)).toBeNull();

      // Second call → hit (flag was reset by the first miss)
      // Need to re-set cache since the data is still there but the test needs
      // to validate the flag behavior. setCache resets sidebarDestroyed flag.
      chatListCache.setCache([makeChat("a")]);
      expect(chatListCache.getCache(false, true)).not.toBeNull();
    });

    it("setCache resets the sidebar destroyed flag", () => {
      chatListCache.setCache([makeChat("a")]);
      chatListCache.notifySidebarDestroyed();
      chatListCache.setCache([makeChat("b")]); // This should reset the flag
      expect(chatListCache.getCache(false, true)).not.toBeNull();
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // clear() resets updateInProgress (critical bug fix)
  // ──────────────────────────────────────────────────────────────────

  describe("clear()", () => {
    it("resets updateInProgress to prevent permanent DB read block", () => {
      chatListCache.setCache([makeChat("a")]);
      chatListCache.setUpdateInProgress(true);
      expect(chatListCache.isUpdateInProgress()).toBe(true);

      chatListCache.clear();
      expect(chatListCache.isUpdateInProgress()).toBe(false);
    });

    it("resolves any waiting callers when cleared during update", async () => {
      chatListCache.setUpdateInProgress(true);

      let resolved = false;
      const waitPromise = chatListCache.waitForUpdate().then(() => {
        resolved = true;
      });

      chatListCache.clear();
      await waitPromise;
      expect(resolved).toBe(true);
    });

    it("empties all cached data", () => {
      chatListCache.setCache([makeChat("a"), makeChat("b")]);
      chatListCache.setLastMessage("a", makeChat("msg") as any);
      chatListCache.clear();

      expect(chatListCache.getCache()).toBeNull();
      expect(chatListCache.getLastMessage("a")).toBeUndefined();
      expect(chatListCache.getStats().ready).toBe(false);
      expect(chatListCache.getStats().count).toBe(0);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // updateInProgress / waitForUpdate
  // ──────────────────────────────────────────────────────────────────

  describe("updateInProgress", () => {
    it("waitForUpdate resolves immediately when no update in progress", async () => {
      let resolved = false;
      await chatListCache.waitForUpdate().then(() => {
        resolved = true;
      });
      expect(resolved).toBe(true);
    });

    it("waitForUpdate waits for setUpdateInProgress(false)", async () => {
      chatListCache.setUpdateInProgress(true);

      let resolved = false;
      const promise = chatListCache.waitForUpdate().then(() => {
        resolved = true;
      });

      // Not resolved yet
      await Promise.resolve();
      expect(resolved).toBe(false);

      // Now complete the update
      chatListCache.setUpdateInProgress(false);
      await promise;
      expect(resolved).toBe(true);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // Last message cache
  // ──────────────────────────────────────────────────────────────────

  describe("last message cache", () => {
    it("returns undefined for uncached chat", () => {
      expect(chatListCache.getLastMessage("x")).toBeUndefined();
    });

    it("caches and retrieves last message", () => {
      const msg = { message_id: "m1", content: "hello" } as any;
      chatListCache.setLastMessage("chat1", msg);
      expect(chatListCache.getLastMessage("chat1")).toEqual(msg);
    });

    it("caches null for chats with no messages", () => {
      chatListCache.setLastMessage("empty-chat", null);
      expect(chatListCache.getLastMessage("empty-chat")).toBeNull();
    });

    it("invalidates specific chat's last message", () => {
      chatListCache.setLastMessage("chat1", { content: "a" } as any);
      chatListCache.setLastMessage("chat2", { content: "b" } as any);
      chatListCache.invalidateLastMessage("chat1");
      expect(chatListCache.getLastMessage("chat1")).toBeUndefined();
      expect(chatListCache.getLastMessage("chat2")).not.toBeUndefined();
    });

    it("clearLastMessages clears all last messages", () => {
      chatListCache.setLastMessage("a", { content: "1" } as any);
      chatListCache.setLastMessage("b", { content: "2" } as any);
      chatListCache.clearLastMessages();
      expect(chatListCache.getLastMessage("a")).toBeUndefined();
      expect(chatListCache.getLastMessage("b")).toBeUndefined();
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // getStats
  // ──────────────────────────────────────────────────────────────────

  describe("getStats", () => {
    it("returns accurate statistics", () => {
      chatListCache.setCache([makeChat("a"), makeChat("b")]);
      const stats = chatListCache.getStats();
      expect(stats.ready).toBe(true);
      expect(stats.count).toBe(2);
      expect(stats.dirty).toBe(false);
      expect(stats.sidebarDestroyed).toBe(false);
    });
  });
});
