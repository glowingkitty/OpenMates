/**
 * Ciphertext Format Byte-Layout Validation
 *
 * Validates that the actual byte structure of encrypted output matches
 * the documented format specifications in docs/architecture/core/encryption-formats.md.
 * Tests the format constants, magic bytes, fingerprint computation, and layout offsets.
 * These tests ensure documentation stays in sync with implementation.
 *
 * Run: cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/formats.test.ts
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
// Imports (must come after crypto restoration)
// ---------------------------------------------------------------------------
import {
  encryptWithChatKey,
  computeKeyFingerprint4Bytes,
  uint8ArrayToBase64,
  base64ToUint8Array,
} from "../../cryptoService";

// ---------------------------------------------------------------------------
// Constants matching cryptoService.ts internals (validated by these tests)
// ---------------------------------------------------------------------------
const AES_IV_LENGTH = 12;
const CIPHERTEXT_HEADER_LENGTH = 6; // 2 magic + 4 fingerprint
const FULL_HEADER_LENGTH = 18; // 6 header + 12 IV

// ---------------------------------------------------------------------------
// Shared test keys
// ---------------------------------------------------------------------------
let chatKey: Uint8Array;

beforeAll(() => {
  chatKey = new Uint8Array(32);
  for (let i = 0; i < 32; i++) chatKey[i] = i;
});

// =========================================================================
// Format A: OM-header byte structure
// =========================================================================
describe("Format A: OM-header byte structure", () => {
  it("starts with magic bytes 0x4F 0x4D at offset 0-1", async () => {
    const ciphertext = await encryptWithChatKey("layout test", chatKey);
    const bytes = base64ToUint8Array(ciphertext);
    expect(bytes[0]).toBe(0x4f); // 'O'
    expect(bytes[1]).toBe(0x4d); // 'M'
  });

  it("has key fingerprint at bytes 2-5", async () => {
    const ciphertext = await encryptWithChatKey("fingerprint offset", chatKey);
    const bytes = base64ToUint8Array(ciphertext);
    const expectedFp = computeKeyFingerprint4Bytes(chatKey);

    // Fingerprint occupies bytes 2, 3, 4, 5
    const storedFp = bytes.slice(2, 6);
    expect(storedFp[0]).toBe(expectedFp[0]);
    expect(storedFp[1]).toBe(expectedFp[1]);
    expect(storedFp[2]).toBe(expectedFp[2]);
    expect(storedFp[3]).toBe(expectedFp[3]);
  });

  it("has 12-byte IV at bytes 6-17", async () => {
    const ciphertext = await encryptWithChatKey("iv offset", chatKey);
    const bytes = base64ToUint8Array(ciphertext);

    // IV is at offset CIPHERTEXT_HEADER_LENGTH (6) through 6 + 12 - 1 = 17
    const iv = bytes.slice(CIPHERTEXT_HEADER_LENGTH, CIPHERTEXT_HEADER_LENGTH + AES_IV_LENGTH);
    expect(iv.length).toBe(12);

    // IV should not be all zeros (random)
    const allZero = iv.every((b) => b === 0);
    expect(allZero).toBe(false);
  });

  it("has ciphertext starting at byte 18", async () => {
    const ciphertext = await encryptWithChatKey("payload", chatKey);
    const bytes = base64ToUint8Array(ciphertext);

    // Total header (magic + fingerprint + IV) = 18 bytes
    expect(bytes.length).toBeGreaterThan(FULL_HEADER_LENGTH);

    // The AES-GCM ciphertext (with 16-byte auth tag) starts at offset 18
    const payload = bytes.slice(FULL_HEADER_LENGTH);
    // "payload" = 7 bytes plaintext + 16 byte GCM auth tag = 23 bytes
    expect(payload.length).toBe(7 + 16);
  });

  it("total header (magic + fingerprint + IV) is exactly 18 bytes", async () => {
    // Verify our constant matches: 2 (magic) + 4 (fingerprint) + 12 (IV) = 18
    expect(CIPHERTEXT_HEADER_LENGTH + AES_IV_LENGTH).toBe(18);
    expect(FULL_HEADER_LENGTH).toBe(18);
  });
});

// =========================================================================
// FNV-1a Fingerprint
// =========================================================================
describe("FNV-1a Fingerprint", () => {
  it("produces exactly 4 bytes for any key", () => {
    const fp = computeKeyFingerprint4Bytes(chatKey);
    expect(fp.length).toBe(4);
    expect(fp).toBeInstanceOf(Uint8Array);
  });

  it("is deterministic for the same key", () => {
    const fp1 = computeKeyFingerprint4Bytes(chatKey);
    const fp2 = computeKeyFingerprint4Bytes(chatKey);
    expect(fp1).toEqual(fp2);
  });

  it("differs for different keys", () => {
    const otherKey = new Uint8Array(32);
    for (let i = 0; i < 32; i++) otherKey[i] = i + 100;

    const fp1 = computeKeyFingerprint4Bytes(chatKey);
    const fp2 = computeKeyFingerprint4Bytes(otherKey);

    // At least one byte should differ
    const same =
      fp1[0] === fp2[0] &&
      fp1[1] === fp2[1] &&
      fp1[2] === fp2[2] &&
      fp1[3] === fp2[3];
    expect(same).toBe(false);
  });

  it("computes known regression value for all-zero 32-byte key", () => {
    const zeroKey = new Uint8Array(32);
    const fp = computeKeyFingerprint4Bytes(zeroKey);
    expect(fp.length).toBe(4);

    // Anchor the actual computed value as a regression test.
    // FNV-1a offset basis: 0x811c9dc5
    // For 32 zero bytes: each iteration XOR with 0 (no change) then multiply by 0x01000193
    // This is a deterministic value we capture here to detect accidental changes.
    const fpHex = Array.from(fp)
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");

    // Store the actual value -- any future change to the fingerprint algorithm
    // will break this test, which is exactly the point.
    expect(fpHex).toMatchInlineSnapshot(`"0b2ae445"`);
  });
});

// =========================================================================
// Format C: Wrapped chat key size
// =========================================================================
describe("Format C: Wrapped chat key byte size", () => {
  it("decoded output is exactly 60 bytes (12 IV + 32 key + 16 auth tag)", async () => {
    const masterKey = await crypto.subtle.generateKey(
      { name: "AES-GCM", length: 256 },
      true,
      ["encrypt", "decrypt"],
    );

    const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
    const encrypted = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      masterKey,
      new Uint8Array(chatKey), // 32-byte chat key
    );

    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(encrypted), iv.length);

    // 12 (IV) + 32 (key plaintext) + 16 (GCM auth tag) = 60 bytes
    expect(combined.length).toBe(60);
  });
});

// =========================================================================
// Format detection
// =========================================================================
describe("Format detection", () => {
  it("identifies Format A by 0x4F 0x4D magic bytes at start", async () => {
    const ciphertext = await encryptWithChatKey("format A", chatKey);
    const bytes = base64ToUint8Array(ciphertext);

    const isFormatA =
      bytes.length > CIPHERTEXT_HEADER_LENGTH + AES_IV_LENGTH &&
      bytes[0] === 0x4f &&
      bytes[1] === 0x4d;

    expect(isFormatA).toBe(true);
  });

  it("treats non-OM-starting ciphertext as Format B legacy", async () => {
    // Construct a legacy-format ciphertext (IV starts with non-OM bytes)
    const iv = new Uint8Array(AES_IV_LENGTH);
    iv[0] = 0x00; // Not 0x4F
    iv[1] = 0x00; // Not 0x4D
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

    // Should NOT be detected as Format A
    const isFormatA =
      combined.length > CIPHERTEXT_HEADER_LENGTH + AES_IV_LENGTH &&
      combined[0] === 0x4f &&
      combined[1] === 0x4d;

    expect(isFormatA).toBe(false);
  });
});
