// contract-test-file: tooling
/**
 * Unit tests for CLI secure master key storage (keychain module).
 *
 * Tests keyring/file selection, legacy decoding, and unavailable-keyring handling.
 * OS keychain tests are mocked — set OPENMATES_TEST_KEYCHAIN=1 for real
 * keychain integration tests.
 *
 * Run: node --test --experimental-strip-types tests/keychain.test.ts
 */

import { describe, it, afterEach } from "node:test";
import assert from "node:assert/strict";

// ---------------------------------------------------------------------------
// Keyring/file selection and legacy machine-ID decoding.
// ---------------------------------------------------------------------------

describe("storeMasterKey / retrieveMasterKey", () => {
  // The normal headless CI path has no unlocked system keyring.

  // contract-test: supporting surface=cli assertions=cli.credentials.storage-mode
  it("storeMasterKey returns a result with a valid type", async () => {
    const { storeMasterKey } = await import("../src/keychain.ts");
    const result = storeMasterKey("test-key-base64", "test-hashed-email");
    assert.ok(
      ["keychain", "file"].includes(result.type),
      `Expected valid type, got: ${result.type}`,
    );
  });

  // contract-test: direct surface=cli assertions=cli.credentials.storage-mode
  it("new storage never claims machine-ID encryption", async () => {
    const { storeMasterKey, retrieveMasterKey } = await import("../src/keychain.ts");
    const testKey = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
    const result = storeMasterKey(testKey, "test-email-hash");

    assert.notStrictEqual(result.type, "encrypted");
    assert.notStrictEqual(result.type, "plaintext");
    if (result.type === "file") assert.strictEqual(retrieveMasterKey("file", "test-email-hash"), null);
  });

  // contract-test: direct surface=cli assertions=cli.credentials.storage-mode
  it("preserves an existing keyring record when the keyring cannot write", async () => {
    const { storeMasterKey } = await import("../src/keychain.ts");
    const originalPath = process.env.PATH;
    process.env.PATH = "";
    try {
      assert.throws(
        () => storeMasterKey("new-key", "existing-keyring-id", "keychain"),
        /Existing OS keyring entry is unavailable/,
      );
      assert.strictEqual(storeMasterKey("new-key", "new-id").type, "file");
    } finally {
      process.env.PATH = originalPath;
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
    assert.doesNotThrow(() => deleteMasterKey("file", "email"));
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

    if (storeResult.type === "file") {
      const retrieved = retrieveMasterKey("file", email);
      assert.strictEqual(retrieved, null);
    } else {
      // Working keyring should round-trip.
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

    if (result.type === "keychain") {
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
