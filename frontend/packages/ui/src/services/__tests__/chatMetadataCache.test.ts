// frontend/packages/ui/src/services/__tests__/chatMetadataCache.test.ts
// Unit tests for ChatMetadataCache — the decrypted title/icon/category cache.
//
// Bug history this test suite guards against:
//  - 780b871e7: stale {title: null} entries served after re-login → "Untitled chat"
//  - aac318eee: wrong chat key used for decryption → mismatched metadata
//  - chatMetadataCache not cleared on logout → title: null served with 5min TTL
//
// Architecture: frontend/packages/ui/src/services/chatMetadataCache.ts
// Note: We test the cache logic only (invalidation, TTL, LRU), not the decryption
// which requires crypto mocking. Decryption correctness is tested in ChatKeyManager tests.

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

const keyReadyMock = vi.hoisted(() => ({
  listener: null as ((chatId: string) => void) | null,
}));

const chatKeyManagerMock = vi.hoisted(() => ({
  getKeySync: vi.fn(() => null as Uint8Array | null),
  getKey: vi.fn(async () => null as Uint8Array | null),
}));

const cryptoServiceMock = vi.hoisted(() => ({
  decryptChatKeyWithMasterKey: vi.fn(async () => null as Uint8Array | null),
  decryptWithChatKey: vi.fn(async () => null as string | null),
  decryptWithMasterKey: vi.fn(async () => null as string | null),
}));

vi.mock("../encryption/ChatKeyManager", () => ({
  chatKeyManager: {
    getKeySync: chatKeyManagerMock.getKeySync,
    getKey: chatKeyManagerMock.getKey,
    onKeyReady: vi.fn((listener: (chatId: string) => void) => {
      keyReadyMock.listener = listener;
      return vi.fn();
    }),
  },
}));

vi.mock("../cryptoService", () => cryptoServiceMock);

vi.mock("../db", () => ({
  chatDB: {
    setChatKey: vi.fn(),
  },
}));

import { chatMetadataCache } from "../chatMetadataCache";
import type { Chat } from "../../types/chat";

// We can't easily test getDecryptedMetadata() because it depends on crypto.
// Instead we test the public cache management methods that were the source of bugs.

describe("ChatMetadataCache", () => {
  beforeEach(() => {
    chatMetadataCache.clearAll();
    chatKeyManagerMock.getKeySync.mockReturnValue(null);
    chatKeyManagerMock.getKey.mockResolvedValue(null);
    cryptoServiceMock.decryptChatKeyWithMasterKey.mockResolvedValue(null);
    cryptoServiceMock.decryptWithChatKey.mockResolvedValue(null);
    cryptoServiceMock.decryptWithMasterKey.mockResolvedValue(null);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // ──────────────────────────────────────────────────────────────────
  // clearAll (bug: 780b871e7 — not called on logout)
  // ──────────────────────────────────────────────────────────────────

  describe("clearAll", () => {
    it("removes all cached entries", () => {
      const stats1 = chatMetadataCache.getCacheStats();
      expect(stats1.size).toBe(0);

      // We can't set entries directly since setCachedMetadata is private.
      // But we can verify clearAll resets the cache to empty.
      chatMetadataCache.clearAll();
      const stats2 = chatMetadataCache.getCacheStats();
      expect(stats2.size).toBe(0);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // invalidateChat
  // ──────────────────────────────────────────────────────────────────

  describe("invalidateChat", () => {
    it("can invalidate a non-existent chat without error", () => {
      // Should not throw
      chatMetadataCache.invalidateChat("nonexistent");
    });
  });

  describe("key-ready notifications", () => {
    it("ignores bulk-loaded keys when metadata was never requested", () => {
      const dispatchEventSpy = vi.spyOn(window, "dispatchEvent");
      const consoleInfoSpy = vi
        .spyOn(console, "info")
        .mockImplementation(() => undefined);

      keyReadyMock.listener?.("unrequested-chat");

      expect(dispatchEventSpy).not.toHaveBeenCalled();
      expect(consoleInfoSpy).not.toHaveBeenCalled();
    });

    it("retries a chat whose metadata request was waiting for its key", async () => {
      const dispatchEventSpy = vi.spyOn(window, "dispatchEvent");
      vi.spyOn(console, "warn").mockImplementation(() => undefined);

      await chatMetadataCache.getDecryptedMetadata({
        chat_id: "requested-chat",
        encrypted_title: "encrypted-title",
      } as Chat);
      keyReadyMock.listener?.("requested-chat");

      expect(dispatchEventSpy).toHaveBeenCalledOnce();
      expect(dispatchEventSpy.mock.calls[0][0]).toMatchObject({
        type: "chatMetadataKeyReady",
        detail: { chatId: "requested-chat" },
      });
    });

    it("bounds chats that keep waiting for unavailable keys", async () => {
      const dispatchEventSpy = vi.spyOn(window, "dispatchEvent");
      dispatchEventSpy.mockClear();
      vi.spyOn(console, "warn").mockImplementation(() => undefined);

      await Promise.all(
        Array.from({ length: 1001 }, (_, index) =>
          chatMetadataCache.getDecryptedMetadata({
            chat_id: `waiting-chat-${index}`,
            encrypted_title: "encrypted-title",
          } as Chat),
        ),
      );

      keyReadyMock.listener?.("waiting-chat-0");
      expect(dispatchEventSpy).not.toHaveBeenCalled();

      keyReadyMock.listener?.("waiting-chat-1000");
      expect(dispatchEventSpy).toHaveBeenCalledOnce();
    });
  });

  describe("chat-key metadata decryption", () => {
    it("passes chat and field context so key fingerprint recovery can run", async () => {
      const chatKey = new Uint8Array(32).fill(7);
      chatKeyManagerMock.getKeySync.mockReturnValue(chatKey);
      cryptoServiceMock.decryptWithChatKey.mockResolvedValue("Recovered title");

      const metadata = await chatMetadataCache.getDecryptedMetadata({
        chat_id: "candidate-chat",
        encrypted_title: "encrypted-title",
      } as Chat);

      expect(metadata?.title).toBe("Recovered title");
      expect(cryptoServiceMock.decryptWithChatKey).toHaveBeenCalledWith(
        "encrypted-title",
        chatKey,
        { chatId: "candidate-chat", fieldName: "encrypted_title" },
      );
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // cleanupExpired
  // ──────────────────────────────────────────────────────────────────

  describe("cleanupExpired", () => {
    it("runs without error on empty cache", () => {
      chatMetadataCache.cleanupExpired();
      expect(chatMetadataCache.getCacheStats().size).toBe(0);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // getCacheStats
  // ──────────────────────────────────────────────────────────────────

  describe("getCacheStats", () => {
    it("returns correct configuration", () => {
      const stats = chatMetadataCache.getCacheStats();
      expect(stats.maxSize).toBe(1000);
      expect(stats.maxAgeMs).toBe(5 * 60 * 1000);
      expect(stats.size).toBe(0);
    });
  });
});
