// frontend/packages/ui/src/services/encryption/__tests__/shareEncryption.test.ts
// Unit tests for shareEncryption — the client-side share link encryption service.
//
// Bug history this test suite guards against:
//  - Share links becoming inaccessible due to key derivation changes
//  - Password-protected shares accepting wrong passwords
//  - Expiration check using client time instead of server time
//
// These tests use Node.js's built-in WebCrypto API (same as browser crypto.subtle)
// to validate actual encrypt/decrypt roundtrips without mocking crypto operations.
//
// Architecture: docs/architecture/share_chat.md

import { describe, it, expect, beforeAll, vi } from "vitest";
import { webcrypto } from "node:crypto";

// Install real WebCrypto before importing the module under test.
// The test-setup.ts stubs crypto.subtle with vi.fn() (incomplete for our needs),
// so we override with the real implementation from Node.js.
beforeAll(() => {
  // Override the global crypto with Node's webcrypto
  Object.defineProperty(globalThis, "crypto", {
    value: webcrypto,
    writable: true,
    configurable: true,
  });

  // Ensure btoa/atob are available (test-setup provides these on window,
  // but shareEncryption may call them as globals)
  if (typeof globalThis.btoa === "undefined") {
    globalThis.btoa = (str: string) =>
      Buffer.from(str, "binary").toString("base64");
  }
  if (typeof globalThis.atob === "undefined") {
    globalThis.atob = (str: string) =>
      Buffer.from(str, "base64").toString("binary");
  }
});

// Import after crypto is set up
import {
  generateShareKeyBlob,
  decryptShareKeyBlob,
} from "../../shareEncryption";

describe("shareEncryption", () => {
  const TEST_CHAT_ID = "test-chat-abc123";
  const TEST_CHAT_KEY = "base64-encoded-chat-encryption-key-here";

  // ──────────────────────────────────────────────────────────────────
  // Roundtrip: generate → decrypt
  // ──────────────────────────────────────────────────────────────────

  describe("encrypt/decrypt roundtrip", () => {
    it("roundtrips without password or expiration", async () => {
      const blob = await generateShareKeyBlob(TEST_CHAT_ID, TEST_CHAT_KEY);
      expect(typeof blob).toBe("string");
      expect(blob.length).toBeGreaterThan(0);

      const result = await decryptShareKeyBlob(
        TEST_CHAT_ID,
        blob,
        Math.floor(Date.now() / 1000),
      );

      expect(result.success).toBe(true);
      expect(result.chatEncryptionKey).toBe(TEST_CHAT_KEY);
    });

    it("roundtrips with password protection", async () => {
      const password = "secret123";

      const blob = await generateShareKeyBlob(
        TEST_CHAT_ID,
        TEST_CHAT_KEY,
        0,
        password,
      );

      // Without password → password_required
      const noPassword = await decryptShareKeyBlob(
        TEST_CHAT_ID,
        blob,
        Math.floor(Date.now() / 1000),
      );
      expect(noPassword.success).toBe(false);
      expect(noPassword.error).toBe("password_required");

      // With correct password → success
      const withPassword = await decryptShareKeyBlob(
        TEST_CHAT_ID,
        blob,
        Math.floor(Date.now() / 1000),
        password,
      );
      expect(withPassword.success).toBe(true);
      expect(withPassword.chatEncryptionKey).toBe(TEST_CHAT_KEY);
    });

    it("rejects wrong password", async () => {
      const blob = await generateShareKeyBlob(
        TEST_CHAT_ID,
        TEST_CHAT_KEY,
        0,
        "correct-pw",
      );

      const result = await decryptShareKeyBlob(
        TEST_CHAT_ID,
        blob,
        Math.floor(Date.now() / 1000),
        "wrong-pw",
      );
      expect(result.success).toBe(false);
      expect(result.error).toBe("invalid_password");
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // Expiration
  // ──────────────────────────────────────────────────────────────────

  describe("expiration", () => {
    it("allows access before expiration", async () => {
      const now = Math.floor(Date.now() / 1000);
      const blob = await generateShareKeyBlob(
        TEST_CHAT_ID,
        TEST_CHAT_KEY,
        3600, // 1 hour
      );

      // Access 30 minutes later (within expiration window)
      const result = await decryptShareKeyBlob(
        TEST_CHAT_ID,
        blob,
        now + 1800,
      );
      expect(result.success).toBe(true);
      expect(result.chatEncryptionKey).toBe(TEST_CHAT_KEY);
    });

    it("rejects access after expiration", async () => {
      const now = Math.floor(Date.now() / 1000);
      const blob = await generateShareKeyBlob(
        TEST_CHAT_ID,
        TEST_CHAT_KEY,
        60, // 1 minute
      );

      // Access 2 minutes later (after expiration)
      const result = await decryptShareKeyBlob(
        TEST_CHAT_ID,
        blob,
        now + 120,
      );
      expect(result.success).toBe(false);
      expect(result.error).toBe("expired");
    });

    it("no expiration with duration 0", async () => {
      const blob = await generateShareKeyBlob(
        TEST_CHAT_ID,
        TEST_CHAT_KEY,
        0, // no expiration
      );

      // Access way in the future
      const farFuture = Math.floor(Date.now() / 1000) + 999999999;
      const result = await decryptShareKeyBlob(
        TEST_CHAT_ID,
        blob,
        farFuture,
      );
      expect(result.success).toBe(true);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // Key isolation
  // ──────────────────────────────────────────────────────────────────

  describe("key isolation", () => {
    it("different chat IDs produce different blobs", async () => {
      const blob1 = await generateShareKeyBlob("chat-1", TEST_CHAT_KEY);
      const blob2 = await generateShareKeyBlob("chat-2", TEST_CHAT_KEY);
      expect(blob1).not.toBe(blob2);
    });

    it("blob encrypted for one chat cannot be decrypted with another chat ID", async () => {
      const blob = await generateShareKeyBlob("chat-1", TEST_CHAT_KEY);

      const result = await decryptShareKeyBlob(
        "chat-2",
        blob,
        Math.floor(Date.now() / 1000),
      );
      expect(result.success).toBe(false);
      expect(result.error).toBe("decryption_failed");
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // Edge cases
  // ──────────────────────────────────────────────────────────────────

  describe("edge cases", () => {
    it("handles empty chat encryption key", async () => {
      const blob = await generateShareKeyBlob(TEST_CHAT_ID, "");
      const result = await decryptShareKeyBlob(
        TEST_CHAT_ID,
        blob,
        Math.floor(Date.now() / 1000),
      );
      expect(result.success).toBe(true);
      expect(result.chatEncryptionKey).toBe("");
    });

    it("returns decryption_failed for corrupted blob", async () => {
      const result = await decryptShareKeyBlob(
        TEST_CHAT_ID,
        "not-a-valid-blob",
        Math.floor(Date.now() / 1000),
      );
      expect(result.success).toBe(false);
      expect(result.error).toBe("decryption_failed");
    });
  });
});
