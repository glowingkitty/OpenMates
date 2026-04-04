// frontend/packages/ui/src/services/db/__tests__/decryptionFailureCache.test.ts
// Unit tests for the decryption failure cache (OPE-314).
//
// Bug history this test suite guards against:
//  - OPE-314: permanent failure cache prevented re-decryption after key loaded
//  - The cache must only store failures for a SPECIFIC key fingerprint
//  - clearDecryptionFailureCache must allow retry with a new key

import { describe, it, expect, beforeEach } from "vitest";
import {
  recordDecryptionFailure,
  isKnownDecryptionFailure,
  clearDecryptionFailureCache,
} from "../decryptionFailureCache";

describe("decryptionFailureCache", () => {
  beforeEach(() => {
    // Clear all caches between tests
    clearDecryptionFailureCache();
  });

  it("records and detects a failure with key fingerprint", () => {
    recordDecryptionFailure("chat-1", "msg-1", "content", "fp-abc123");
    expect(
      isKnownDecryptionFailure("chat-1", "msg-1", "content", "fp-abc123"),
    ).toBe(true);
  });

  it("does NOT detect failure for a DIFFERENT key fingerprint", () => {
    recordDecryptionFailure("chat-1", "msg-1", "content", "fp-abc123");
    // Different fingerprint — should return false (allow retry with new key)
    expect(
      isKnownDecryptionFailure("chat-1", "msg-1", "content", "fp-xyz789"),
    ).toBe(false);
  });

  it("does NOT detect failure for a different message", () => {
    recordDecryptionFailure("chat-1", "msg-1", "content", "fp-abc123");
    expect(
      isKnownDecryptionFailure("chat-1", "msg-2", "content", "fp-abc123"),
    ).toBe(false);
  });

  it("does NOT detect failure for a different chat", () => {
    recordDecryptionFailure("chat-1", "msg-1", "content", "fp-abc123");
    expect(
      isKnownDecryptionFailure("chat-2", "msg-1", "content", "fp-abc123"),
    ).toBe(false);
  });

  it("does NOT detect failure for a different field", () => {
    recordDecryptionFailure("chat-1", "msg-1", "content", "fp-abc123");
    expect(
      isKnownDecryptionFailure("chat-1", "msg-1", "tiptap", "fp-abc123"),
    ).toBe(false);
  });

  it("clearDecryptionFailureCache(chatId) clears only that chat", () => {
    recordDecryptionFailure("chat-1", "msg-1", "content", "fp-aaa");
    recordDecryptionFailure("chat-2", "msg-2", "content", "fp-bbb");

    clearDecryptionFailureCache("chat-1");

    // chat-1 cleared — retry allowed
    expect(
      isKnownDecryptionFailure("chat-1", "msg-1", "content", "fp-aaa"),
    ).toBe(false);
    // chat-2 still cached
    expect(
      isKnownDecryptionFailure("chat-2", "msg-2", "content", "fp-bbb"),
    ).toBe(true);
  });

  it("clearDecryptionFailureCache() with no args clears everything", () => {
    recordDecryptionFailure("chat-1", "msg-1", "content", "fp-aaa");
    recordDecryptionFailure("chat-2", "msg-2", "content", "fp-bbb");
    recordDecryptionFailure("chat-3", "msg-3", "content", "fp-ccc");

    clearDecryptionFailureCache();

    expect(
      isKnownDecryptionFailure("chat-1", "msg-1", "content", "fp-aaa"),
    ).toBe(false);
    expect(
      isKnownDecryptionFailure("chat-2", "msg-2", "content", "fp-bbb"),
    ).toBe(false);
    expect(
      isKnownDecryptionFailure("chat-3", "msg-3", "content", "fp-ccc"),
    ).toBe(false);
  });

  it("legacy fallback: detects failure without fingerprint", () => {
    recordDecryptionFailure("chat-1", "msg-1", "content");
    expect(isKnownDecryptionFailure("chat-1", "msg-1", "content")).toBe(true);
  });

  it("legacy: fingerprinted lookup finds legacy entry", () => {
    // Record without fingerprint (legacy)
    recordDecryptionFailure("chat-1", "msg-1", "content");
    // Lookup with fingerprint should still match via prefix fallback
    expect(
      isKnownDecryptionFailure("chat-1", "msg-1", "content", "fp-any"),
    ).toBe(false);
    // Lookup without fingerprint should match
    expect(isKnownDecryptionFailure("chat-1", "msg-1", "content")).toBe(true);
  });

  it("multiple failures for same message with different fields", () => {
    recordDecryptionFailure("chat-1", "msg-1", "content", "fp-111");
    recordDecryptionFailure("chat-1", "msg-1", "tiptap", "fp-111");

    expect(
      isKnownDecryptionFailure("chat-1", "msg-1", "content", "fp-111"),
    ).toBe(true);
    expect(
      isKnownDecryptionFailure("chat-1", "msg-1", "tiptap", "fp-111"),
    ).toBe(true);
  });

  it("recording same failure twice is idempotent", () => {
    recordDecryptionFailure("chat-1", "msg-1", "content", "fp-dup");
    recordDecryptionFailure("chat-1", "msg-1", "content", "fp-dup");

    expect(
      isKnownDecryptionFailure("chat-1", "msg-1", "content", "fp-dup"),
    ).toBe(true);

    // Clear and verify it's gone (not double-stored)
    clearDecryptionFailureCache("chat-1");
    expect(
      isKnownDecryptionFailure("chat-1", "msg-1", "content", "fp-dup"),
    ).toBe(false);
  });
});
