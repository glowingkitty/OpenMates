/**
 * Unit tests for CLI crypto utilities.
 *
 * Tests AES-GCM roundtrip compatibility, hashItemKey format,
 * and edge-case error handling.
 *
 * Run: node --test --experimental-strip-types tests/crypto.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  base64ToBytes,
  bytesToBase64,
  encryptWithAesGcmCombined,
  encryptBytesWithAesGcm,
  decryptWithAesGcmCombined,
  decryptBytesWithAesGcm,
  hashItemKey,
} from "../src/crypto.ts";

// ---------------------------------------------------------------------------
// base64 helpers
// ---------------------------------------------------------------------------

describe("base64ToBytes / bytesToBase64", () => {
  it("roundtrips correctly for short input", () => {
    const original = new Uint8Array([72, 101, 108, 108, 111]); // "Hello"
    const b64 = bytesToBase64(original);
    const restored = base64ToBytes(b64);
    assert.deepEqual(restored, original);
  });

  it("roundtrips for 32-byte key-size buffer", () => {
    const key = new Uint8Array(32).fill(0xab);
    const b64 = bytesToBase64(key);
    const restored = base64ToBytes(b64);
    assert.deepEqual(restored, key);
  });

  it("bytesToBase64 produces standard base64 (no URL encoding)", () => {
    const bytes = new Uint8Array([0xfb, 0xff, 0xfe]); // produces +/
    const b64 = bytesToBase64(bytes);
    // Standard base64 uses + and /, not - and _
    assert.ok(!b64.includes("-"), "should not contain URL-safe '-'");
    assert.ok(!b64.includes("_"), "should not contain URL-safe '_'");
  });
});

// ---------------------------------------------------------------------------
// AES-GCM encrypt / decrypt roundtrip
// ---------------------------------------------------------------------------

describe("encryptWithAesGcmCombined / decryptWithAesGcmCombined", () => {
  it("encrypts and decrypts back to the same plaintext", async () => {
    const key = new Uint8Array(32).fill(0x42);
    const plaintext = "Hello, OpenMates!";

    const encrypted = await encryptWithAesGcmCombined(plaintext, key);
    const decrypted = await decryptWithAesGcmCombined(encrypted, key);

    assert.strictEqual(decrypted, plaintext);
  });

  it("produces different ciphertexts for the same input (random IV)", async () => {
    const key = new Uint8Array(32).fill(0x42);
    const plaintext = "Same plaintext";

    const c1 = await encryptWithAesGcmCombined(plaintext, key);
    const c2 = await encryptWithAesGcmCombined(plaintext, key);

    assert.notStrictEqual(c1, c2, "two encryptions should differ (random IV)");
  });

  it("returns null when decrypting with the wrong key", async () => {
    const key1 = new Uint8Array(32).fill(0x11);
    const key2 = new Uint8Array(32).fill(0x22);
    const encrypted = await encryptWithAesGcmCombined("secret", key1);
    const result = await decryptWithAesGcmCombined(encrypted, key2);
    assert.strictEqual(result, null);
  });

  it("returns null for empty / too-short input", async () => {
    const key = new Uint8Array(32).fill(0x42);
    // An empty base64 string decodes to 0 bytes — must fail gracefully
    const result = await decryptWithAesGcmCombined("", key);
    assert.strictEqual(result, null);
  });

  it("handles unicode plaintext (emoji)", async () => {
    const key = new Uint8Array(32).fill(0x77);
    const plaintext = "🚀 OpenMates 日本語";
    const encrypted = await encryptWithAesGcmCombined(plaintext, key);
    const decrypted = await decryptWithAesGcmCombined(encrypted, key);
    assert.strictEqual(decrypted, plaintext);
  });

  it("handles JSON payloads (memory-like structure)", async () => {
    const key = new Uint8Array(32).fill(0x55);
    const payload = {
      name: "Python",
      proficiency: "advanced",
      settings_group: "code",
      _original_item_key: "preferred_tech",
      added_date: 1710000000,
    };
    const plaintext = JSON.stringify(payload);
    const encrypted = await encryptWithAesGcmCombined(plaintext, key);
    const decrypted = await decryptWithAesGcmCombined(encrypted, key);
    assert.strictEqual(decrypted, plaintext);
    const parsed = JSON.parse(decrypted!);
    assert.strictEqual(parsed.name, "Python");
    assert.strictEqual(parsed._original_item_key, "preferred_tech");
  });

  it("combined format starts with 12-byte IV followed by ciphertext", async () => {
    const key = new Uint8Array(32).fill(0x33);
    const plaintext = "test";
    const encrypted = await encryptWithAesGcmCombined(plaintext, key);
    const bytes = base64ToBytes(encrypted);
    // Minimum: 12 IV + 4 data + 16 GCM auth tag = 32 bytes
    assert.ok(bytes.length >= 32, `combined blob too short: ${bytes.length}`);
  });
});

// ---------------------------------------------------------------------------
// encryptBytesWithAesGcm / decryptBytesWithAesGcm roundtrip (chat key wrapping)
// ---------------------------------------------------------------------------

describe("encryptBytesWithAesGcm / decryptBytesWithAesGcm", () => {
  it("roundtrips a 32-byte chat key through master-key wrapping", async () => {
    const masterKey = new Uint8Array(32).fill(0xaa);
    const chatKey = new Uint8Array(32);
    // Fill with a recognizable pattern
    for (let i = 0; i < 32; i++) chatKey[i] = i;

    const encrypted = await encryptBytesWithAesGcm(chatKey, masterKey);
    const decrypted = await decryptBytesWithAesGcm(encrypted, masterKey);

    assert.ok(decrypted, "decryption should succeed");
    assert.deepEqual(decrypted, chatKey, "roundtrip must preserve exact bytes");
  });

  it("returns null when decrypting with wrong master key", async () => {
    const masterKey1 = new Uint8Array(32).fill(0x11);
    const masterKey2 = new Uint8Array(32).fill(0x22);
    const chatKey = new Uint8Array(32).fill(0xff);

    const encrypted = await encryptBytesWithAesGcm(chatKey, masterKey1);
    const result = await decryptBytesWithAesGcm(encrypted, masterKey2);
    assert.strictEqual(result, null, "wrong key should return null");
  });

  it("produces different ciphertexts for the same key (random IV)", async () => {
    const masterKey = new Uint8Array(32).fill(0xbb);
    const chatKey = new Uint8Array(32).fill(0xcc);

    const c1 = await encryptBytesWithAesGcm(chatKey, masterKey);
    const c2 = await encryptBytesWithAesGcm(chatKey, masterKey);
    assert.notStrictEqual(c1, c2, "random IV should make ciphertexts differ");
  });
});

// ---------------------------------------------------------------------------
// hashItemKey
// ---------------------------------------------------------------------------

describe("hashItemKey", () => {
  it("returns exactly 32 hex characters", () => {
    const hash = hashItemKey("code", "preferred_tech");
    assert.strictEqual(hash.length, 32);
    assert.match(hash, /^[0-9a-f]{32}$/);
  });

  it("different inputs produce different hashes", () => {
    const h1 = hashItemKey("code", "preferred_tech");
    const h2 = hashItemKey("code", "projects");
    const h3 = hashItemKey("books", "preferred_tech");
    assert.notStrictEqual(h1, h2);
    assert.notStrictEqual(h1, h3);
  });

  it("same appId+itemKey in the same millisecond produces equal hashes", () => {
    // hashItemKey uses Date.now() — call twice within the same ms
    const t = Date.now();
    // Monkey-patch Date.now to return a fixed value
    const originalNow = Date.now;
    Date.now = () => t;
    try {
      const h1 = hashItemKey("ai", "communication_style");
      const h2 = hashItemKey("ai", "communication_style");
      assert.strictEqual(h1, h2, "same ms → same hash");
    } finally {
      Date.now = originalNow;
    }
  });

  it("same appId+itemKey at different timestamps produces different hashes", () => {
    const originalNow = Date.now;
    let counter = 1000;
    Date.now = () => counter++;
    try {
      const h1 = hashItemKey("ai", "communication_style");
      const h2 = hashItemKey("ai", "communication_style");
      assert.notStrictEqual(h1, h2, "different ms → different hash");
    } finally {
      Date.now = originalNow;
    }
  });
});
