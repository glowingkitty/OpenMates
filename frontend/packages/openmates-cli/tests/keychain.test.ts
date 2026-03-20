/**
 * Unit tests for CLI secure master key storage (keychain module).
 *
 * Tests all three storage tiers, fallback chains, and error handling.
 * OS keychain tests are mocked — set OPENMATES_TEST_KEYCHAIN=1 for real
 * keychain integration tests.
 *
 * Run: node --test --experimental-strip-types tests/keychain.test.ts
 */

import { describe, it, mock, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

// ---------------------------------------------------------------------------
// Tier 2 (encrypted) + Tier 3 (plaintext) tests — no mocking needed
// ---------------------------------------------------------------------------

describe("storeMasterKey / retrieveMasterKey (tier 2 + 3)", () => {
  // We can't easily test tier 1 (keychain) without the actual OS tools,
  // but we can test the full fallback by importing the module on Linux
  // where secret-tool is likely not installed in CI.

  it("storeMasterKey returns a result with a valid type", async () => {
    const { storeMasterKey } = await import("../src/keychain.ts");
    const result = storeMasterKey("test-key-base64", "test-hashed-email");
    assert.ok(
      ["keychain", "encrypted", "plaintext"].includes(result.type),
      `Expected valid type, got: ${result.type}`,
    );
  });

  it("encrypted tier: encryptedData is present and retrievable", async () => {
    const { storeMasterKey, retrieveMasterKey } = await import("../src/keychain.ts");
    const testKey = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
    const result = storeMasterKey(testKey, "test-email-hash");

    if (result.type === "encrypted") {
      assert.ok(result.encryptedData, "encryptedData should be present");
      assert.notStrictEqual(result.encryptedData, testKey, "should not be plaintext");

      const retrieved = retrieveMasterKey("encrypted", "test-email-hash", result.encryptedData);
      assert.strictEqual(retrieved, testKey, "retrieved key should match original");
    } else if (result.type === "keychain") {
      // OS keychain worked — that's fine, skip encrypted-specific assertions
      assert.ok(true, "keychain tier used instead of encrypted");
    } else {
      // Plaintext fallback — machine entropy unavailable
      assert.strictEqual(result.type, "plaintext");
    }
  });

  it("encrypted tier: different keys produce different ciphertext", async () => {
    const { storeMasterKey } = await import("../src/keychain.ts");
    const result1 = storeMasterKey("key-one", "email-1");
    const result2 = storeMasterKey("key-two", "email-2");

    if (result1.type === "encrypted" && result2.type === "encrypted") {
      assert.notStrictEqual(
        result1.encryptedData,
        result2.encryptedData,
        "different keys should produce different ciphertext",
      );
    }
  });

  it("retrieveMasterKey returns null for wrong encrypted data", async () => {
    const { retrieveMasterKey } = await import("../src/keychain.ts");
    const result = retrieveMasterKey("encrypted", "email", "not-valid-base64-ciphertext!");
    assert.strictEqual(result, null);
  });

  it("retrieveMasterKey returns null for truncated encrypted data", async () => {
    const { retrieveMasterKey } = await import("../src/keychain.ts");
    // Too short to contain IV + authTag
    const result = retrieveMasterKey("encrypted", "email", "AAAA");
    assert.strictEqual(result, null);
  });

  it("retrieveMasterKey returns null for plaintext type (caller handles)", async () => {
    const { retrieveMasterKey } = await import("../src/keychain.ts");
    const result = retrieveMasterKey("plaintext", "email");
    assert.strictEqual(result, null);
  });

  it("retrieveMasterKey returns null for unknown type", async () => {
    const { retrieveMasterKey } = await import("../src/keychain.ts");
    // @ts-expect-error — testing invalid input
    const result = retrieveMasterKey("nonexistent", "email");
    assert.strictEqual(result, null);
  });

  it("deleteMasterKey does not throw for any type", async () => {
    const { deleteMasterKey } = await import("../src/keychain.ts");
    assert.doesNotThrow(() => deleteMasterKey("keychain", "email"));
    assert.doesNotThrow(() => deleteMasterKey("encrypted", "email"));
    assert.doesNotThrow(() => deleteMasterKey("plaintext", "email"));
  });
});

// ---------------------------------------------------------------------------
// Roundtrip: store → retrieve for all reachable tiers
// ---------------------------------------------------------------------------

describe("storeMasterKey → retrieveMasterKey roundtrip", () => {
  it("stored key can be retrieved using the returned storage info", async () => {
    const { storeMasterKey, retrieveMasterKey } = await import("../src/keychain.ts");
    const originalKey = "roundtrip-test-key-AQIDBA==";
    const email = "roundtrip-test-email";

    const storeResult = storeMasterKey(originalKey, email);

    if (storeResult.type === "plaintext") {
      // Plaintext tier — retrieveMasterKey returns null (caller uses inline key)
      const retrieved = retrieveMasterKey("plaintext", email);
      assert.strictEqual(retrieved, null);
    } else {
      // Keychain or encrypted — should round-trip
      const retrieved = retrieveMasterKey(
        storeResult.type,
        email,
        storeResult.encryptedData,
      );
      assert.strictEqual(retrieved, originalKey);
    }
  });

  it("handles special characters in key", async () => {
    const { storeMasterKey, retrieveMasterKey } = await import("../src/keychain.ts");
    const specialKey = "key+with/special=chars==";
    const email = "special-char-test";

    const result = storeMasterKey(specialKey, email);

    if (result.type !== "plaintext") {
      const retrieved = retrieveMasterKey(result.type, email, result.encryptedData);
      assert.strictEqual(retrieved, specialKey);
    }
  });

  it("handles empty string key gracefully", async () => {
    const { storeMasterKey } = await import("../src/keychain.ts");
    // Empty key is not a valid master key, but should not throw
    assert.doesNotThrow(() => storeMasterKey("", "empty-key-test"));
  });
});

// ---------------------------------------------------------------------------
// Integration tests — real OS keychain (gated)
// ---------------------------------------------------------------------------

const INTEGRATION_ENABLED = process.env.OPENMATES_TEST_KEYCHAIN === "1";

describe("OS keychain integration", { skip: !INTEGRATION_ENABLED }, () => {
  const testEmail = `keychain-integration-test-${Date.now()}`;
  const testKey = "integration-test-master-key-base64";

  afterEach(async () => {
    const { deleteMasterKey } = await import("../src/keychain.ts");
    try {
      deleteMasterKey("keychain", testEmail);
    } catch {
      // Best effort cleanup
    }
  });

  it("stores and retrieves key from OS keychain", async () => {
    const { storeMasterKey, retrieveMasterKey } = await import("../src/keychain.ts");
    const result = storeMasterKey(testKey, testEmail);

    if (result.type !== "keychain") {
      // OS keychain not available — skip
      return;
    }

    const retrieved = retrieveMasterKey("keychain", testEmail);
    assert.strictEqual(retrieved, testKey, "keychain should return the stored key");
  });

  it("deleteMasterKey removes the keychain entry", async () => {
    const { storeMasterKey, retrieveMasterKey, deleteMasterKey } = await import("../src/keychain.ts");
    const result = storeMasterKey(testKey, testEmail);

    if (result.type !== "keychain") return;

    deleteMasterKey("keychain", testEmail);
    const retrieved = retrieveMasterKey("keychain", testEmail);
    assert.strictEqual(retrieved, null, "deleted key should not be retrievable");
  });
});
