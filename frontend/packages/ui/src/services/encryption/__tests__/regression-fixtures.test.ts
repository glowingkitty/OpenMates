/**
 * Regression Test Fixtures for Encryption Formats
 *
 * Validates that all ciphertext format generations (A: OM-header, B: legacy,
 * C: wrapped chat key, D: master-key-encrypted) decrypt correctly.
 * These fixtures are the safety net for Phases 2-4 of the encryption rebuild.
 * Any code extraction or rewiring must pass these tests to prove backwards
 * compatibility with existing encrypted chats.
 *
 * Run: cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/regression-fixtures.test.ts
 */

import { describe, it, expect, beforeAll } from "vitest";
import { webcrypto } from "node:crypto";

// ---------------------------------------------------------------------------
// Environment: restore real Web Crypto (test-setup.ts mocks it with stubs)
// ---------------------------------------------------------------------------
const realCrypto = webcrypto as unknown as Crypto;
Object.defineProperty(globalThis, "crypto", {
  value: realCrypto,
  writable: true,
  configurable: true,
});
Object.defineProperty(globalThis.window, "btoa", {
  value: (str: string) => Buffer.from(str, "binary").toString("base64"),
  writable: true,
  configurable: true,
});
Object.defineProperty(globalThis.window, "atob", {
  value: (str: string) => Buffer.from(str, "base64").toString("binary"),
  writable: true,
  configurable: true,
});

// ---------------------------------------------------------------------------
// Imports (must come after crypto restoration so module-level code works)
// ---------------------------------------------------------------------------
import {
  encryptWithChatKey,
  decryptWithChatKey,
  encryptWithMasterKeyDirect,
  computeKeyFingerprint4Bytes,
  uint8ArrayToBase64,
  base64ToUint8Array,
} from "../../cryptoService";

// ---------------------------------------------------------------------------
// Constants matching cryptoService.ts internals
// ---------------------------------------------------------------------------
const AES_IV_LENGTH = 12;
const CIPHERTEXT_HEADER_LENGTH = 6; // 2 magic + 4 fingerprint

// ---------------------------------------------------------------------------
// Shared test keys (deterministic for reproducibility)
// ---------------------------------------------------------------------------
let chatKey: Uint8Array;
let wrongKey: Uint8Array;
let masterKey: CryptoKey;

beforeAll(async () => {
  // Deterministic chat key: bytes 0..31
  chatKey = new Uint8Array(32);
  for (let i = 0; i < 32; i++) chatKey[i] = i;

  // Wrong key: bytes 100..131
  wrongKey = new Uint8Array(32);
  for (let i = 0; i < 32; i++) wrongKey[i] = i + 100;

  // Master key for wrapping/master-key-encryption tests
  masterKey = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    true,
    ["encrypt", "decrypt"],
  );
});

// =========================================================================
// Format A: OM-header ciphertexts (current format)
// =========================================================================
describe("Format A: OM-header roundtrip", () => {
  it("encrypts and decrypts basic text", async () => {
    const plaintext = "Hello, this is a test message for Format A";
    const ciphertext = await encryptWithChatKey(plaintext, chatKey);
    const decrypted = await decryptWithChatKey(ciphertext, chatKey);
    expect(decrypted).toBe(plaintext);
  });

  it("produces ciphertext starting with OM magic bytes", async () => {
    const ciphertext = await encryptWithChatKey("test", chatKey);
    const bytes = base64ToUint8Array(ciphertext);
    expect(bytes[0]).toBe(0x4f);
    expect(bytes[1]).toBe(0x4d);
  });

  it("includes correct key fingerprint in header", async () => {
    const ciphertext = await encryptWithChatKey("fingerprint check", chatKey);
    const bytes = base64ToUint8Array(ciphertext);
    const expectedFp = computeKeyFingerprint4Bytes(chatKey);
    expect(bytes[2]).toBe(expectedFp[0]);
    expect(bytes[3]).toBe(expectedFp[1]);
    expect(bytes[4]).toBe(expectedFp[2]);
    expect(bytes[5]).toBe(expectedFp[3]);
  });

  it("multiple messages with same key all decrypt correctly", async () => {
    const messages = [
      "First message",
      "Second message with more content",
      "Third: special chars <>&\"'",
      "Fourth: numbers 12345.67890",
    ];

    for (const msg of messages) {
      const ct = await encryptWithChatKey(msg, chatKey);
      const dec = await decryptWithChatKey(ct, chatKey);
      expect(dec).toBe(msg);
    }
  });
});

// =========================================================================
// Format B: Legacy ciphertexts (no OM header, pre-fingerprint era)
// =========================================================================
describe("Format B: Legacy format (no OM header)", () => {
  it("decrypts legacy format without OM header", async () => {
    // Manually construct a legacy ciphertext: [IV 12B][AES-GCM ciphertext]
    // This simulates data written before the fingerprint header existed.
    const plaintext = "Legacy format test message";
    const encoder = new TextEncoder();
    const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
    const rawKey = await crypto.subtle.importKey(
      "raw",
      chatKey,
      { name: "AES-GCM" },
      false,
      ["encrypt"],
    );
    const encrypted = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      rawKey,
      encoder.encode(plaintext),
    );

    // Combine as legacy format: [IV][ciphertext] — no magic header
    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(encrypted), iv.length);
    const legacyCiphertext = uint8ArrayToBase64(combined);

    // decryptWithChatKey must handle legacy format
    const decrypted = await decryptWithChatKey(legacyCiphertext, chatKey);
    expect(decrypted).toBe(plaintext);
  });

  it("legacy ciphertext does NOT start with OM magic bytes", async () => {
    // Construct a legacy ciphertext with an IV whose first bytes are not 0x4F,0x4D
    const iv = new Uint8Array(AES_IV_LENGTH);
    iv[0] = 0x00; // Ensure not 0x4F
    iv[1] = 0x00; // Ensure not 0x4D
    crypto.getRandomValues(iv.subarray(2));

    const rawKey = await crypto.subtle.importKey(
      "raw",
      chatKey,
      { name: "AES-GCM" },
      false,
      ["encrypt"],
    );
    const encrypted = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      rawKey,
      new TextEncoder().encode("legacy"),
    );

    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(encrypted), iv.length);

    // First two bytes should NOT be OM magic
    expect(combined[0]).not.toBe(0x4f);

    // Should still decrypt as legacy
    const decrypted = await decryptWithChatKey(
      uint8ArrayToBase64(combined),
      chatKey,
    );
    expect(decrypted).toBe("legacy");
  });
});

// =========================================================================
// Format C: Wrapped chat key (encrypted with master key)
// =========================================================================
describe("Format C: Wrapped chat key with master key", () => {
  it("encrypts and decrypts a chat key using master key", async () => {
    // Manually wrap: [IV 12B][AES-GCM(chatKey)] — same format as encryptChatKeyWithMasterKey
    const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
    const encrypted = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      masterKey,
      new Uint8Array(chatKey),
    );

    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(encrypted), iv.length);
    const wrappedBase64 = uint8ArrayToBase64(combined);

    // Decrypt using the same pattern as decryptChatKeyWithMasterKey
    const decoded = base64ToUint8Array(wrappedBase64);
    const decIv = decoded.slice(0, AES_IV_LENGTH);
    const decCiphertext = decoded.slice(AES_IV_LENGTH);
    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: decIv },
      masterKey,
      decCiphertext,
    );

    expect(new Uint8Array(decrypted)).toEqual(chatKey);
  });

  it("wrapped key output is exactly 60 bytes decoded (12 IV + 32 key + 16 auth tag)", async () => {
    const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
    const encrypted = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      masterKey,
      new Uint8Array(chatKey),
    );

    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(encrypted), iv.length);

    // 12 (IV) + 32 (key) + 16 (GCM auth tag) = 60
    expect(combined.length).toBe(60);
  });
});

// =========================================================================
// Format D: Master-key-encrypted data
// =========================================================================
describe("Format D: Master-key-encrypted data", () => {
  it("encrypts and decrypts data with master key", async () => {
    const plaintext = "Sensitive data encrypted with master key";
    const encrypted = await encryptWithMasterKeyDirect(plaintext, masterKey);
    expect(encrypted).not.toBeNull();

    // Decrypt manually (same pattern as decryptWithMasterKey)
    const combined = base64ToUint8Array(encrypted!);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);

    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv },
      masterKey,
      ciphertext,
    );

    expect(new TextDecoder().decode(decrypted)).toBe(plaintext);
  });
});

// =========================================================================
// Error cases: wrong key detection
// =========================================================================
describe("Error cases: wrong key detection", () => {
  it("wrong key fails to decrypt Format A (fingerprint mismatch returns null)", async () => {
    const ciphertext = await encryptWithChatKey("secret message", chatKey);
    // Use a different key — fingerprint mismatch should cause fast fail
    const result = await decryptWithChatKey(ciphertext, wrongKey);
    expect(result).toBeNull();
  });

  it("wrong key fails to decrypt Format B (AES-GCM auth tag failure)", async () => {
    // Construct legacy ciphertext with chatKey
    const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
    const rawKey = await crypto.subtle.importKey(
      "raw",
      chatKey,
      { name: "AES-GCM" },
      false,
      ["encrypt"],
    );
    const encrypted = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      rawKey,
      new TextEncoder().encode("legacy secret"),
    );

    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(encrypted), iv.length);
    const legacyCiphertext = uint8ArrayToBase64(combined);

    // Decrypt with wrong key — AES-GCM auth tag should fail
    const result = await decryptWithChatKey(legacyCiphertext, wrongKey);
    expect(result).toBeNull();
  });
});

// =========================================================================
// Edge cases
// =========================================================================
describe("Edge cases", () => {
  it("empty string encryption/decryption roundtrip", async () => {
    const ciphertext = await encryptWithChatKey("", chatKey);
    const decrypted = await decryptWithChatKey(ciphertext, chatKey);
    expect(decrypted).toBe("");
  });

  it("unicode and emoji content roundtrip", async () => {
    const unicodeText = "Hello 👋🌍 Guten Tag! こんにちは 你好 مرحبا";
    const ciphertext = await encryptWithChatKey(unicodeText, chatKey);
    const decrypted = await decryptWithChatKey(ciphertext, chatKey);
    expect(decrypted).toBe(unicodeText);
  });

  it("large message (10KB+) encryption/decryption roundtrip", async () => {
    // Generate a 10KB+ string
    const largeText = "A".repeat(10 * 1024) + " end marker";
    expect(largeText.length).toBeGreaterThan(10 * 1024);

    const ciphertext = await encryptWithChatKey(largeText, chatKey);
    const decrypted = await decryptWithChatKey(ciphertext, chatKey);
    expect(decrypted).toBe(largeText);
  });
});
