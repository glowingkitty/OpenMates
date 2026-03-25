/*
 * OpenMates CLI crypto utilities.
 *
 * Purpose: keep pair-login and chat metadata crypto in one Node-safe module.
 * Architecture: mirrors the web pair flow in settings pair components.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: AES-256-GCM + PBKDF2-SHA256(100k) to match server/browser flows.
 * Tests: frontend/packages/openmates-cli/tests/crypto.test.ts
 */

import { webcrypto, createHash } from "node:crypto";

const cryptoApi = globalThis.crypto ?? webcrypto;
const PAIR_KDF_ITERATIONS = 100_000;
const AES_GCM_IV_LENGTH = 12;

// New ciphertext format: [0x4F 0x4D][4-byte key fingerprint][IV][ciphertext]
// The web app's encryptWithChatKey() now prepends "OM" magic + fingerprint.
// We detect this header and skip it to find the actual IV.
const CIPHERTEXT_MAGIC_0 = 0x4f; // 'O'
const CIPHERTEXT_MAGIC_1 = 0x4d; // 'M'
const FINGERPRINT_LENGTH = 4;
const CIPHERTEXT_HEADER_LENGTH = 2 + FINGERPRINT_LENGTH; // 6 bytes

export function base64ToBytes(input: string): Uint8Array {
  return new Uint8Array(Buffer.from(input, "base64"));
}

export function bytesToBase64(input: Uint8Array): string {
  return Buffer.from(input).toString("base64");
}

function toArrayBuffer(input: Uint8Array): ArrayBuffer {
  const output = new ArrayBuffer(input.byteLength);
  new Uint8Array(output).set(input);
  return output;
}

export async function derivePairKey(
  pin: string,
  upperToken: string,
): Promise<CryptoKey> {
  const encoder = new TextEncoder();
  const keyMaterial = await cryptoApi.subtle.importKey(
    "raw",
    encoder.encode(pin),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  return cryptoApi.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: encoder.encode(upperToken),
      iterations: PAIR_KDF_ITERATIONS,
      hash: "SHA-256",
    },
    keyMaterial,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

export async function decryptBundle(params: {
  encryptedBundleB64: string;
  ivB64: string;
  pin: string;
  token: string;
}): Promise<unknown> {
  const aesKey = await derivePairKey(params.pin, params.token.toUpperCase());
  const iv = base64ToBytes(params.ivB64);
  const ciphertext = base64ToBytes(params.encryptedBundleB64);
  const plaintext = await cryptoApi.subtle.decrypt(
    { name: "AES-GCM", iv: toArrayBuffer(iv) },
    aesKey,
    toArrayBuffer(ciphertext),
  );
  return JSON.parse(new TextDecoder().decode(plaintext));
}

export async function decryptWithAesGcmCombined(
  encryptedWithIvB64: string,
  rawKeyBytes: Uint8Array,
): Promise<string | null> {
  try {
    const combined = base64ToBytes(encryptedWithIvB64);
    if (combined.length <= AES_GCM_IV_LENGTH) {
      return null;
    }

    // Detect new "OM" format: [magic 2B][fingerprint 4B][IV 12B][ciphertext]
    let offset = 0;
    if (
      combined.length > CIPHERTEXT_HEADER_LENGTH + AES_GCM_IV_LENGTH &&
      combined[0] === CIPHERTEXT_MAGIC_0 &&
      combined[1] === CIPHERTEXT_MAGIC_1
    ) {
      offset = CIPHERTEXT_HEADER_LENGTH;
    }

    const iv = combined.slice(offset, offset + AES_GCM_IV_LENGTH);
    const ciphertext = combined.slice(offset + AES_GCM_IV_LENGTH);
    const key = await cryptoApi.subtle.importKey(
      "raw",
      toArrayBuffer(rawKeyBytes),
      { name: "AES-GCM" },
      false,
      ["decrypt"],
    );
    const decrypted = await cryptoApi.subtle.decrypt(
      { name: "AES-GCM", iv: toArrayBuffer(iv) },
      key,
      toArrayBuffer(ciphertext),
    );
    return new TextDecoder().decode(decrypted);
  } catch {
    return null;
  }
}

/**
 * Decrypt AES-GCM-combined data and return the raw decrypted bytes.
 *
 * Mirrors the browser's `decryptChatKeyWithMasterKey()` from cryptoService.ts.
 * This MUST be used for decrypting binary payloads (e.g. chat keys) where the
 * result is raw bytes, NOT a UTF-8 string. Using TextDecoder on binary data
 * corrupts it.
 */
export async function decryptBytesWithAesGcm(
  encryptedWithIvB64: string,
  rawKeyBytes: Uint8Array,
): Promise<Uint8Array | null> {
  try {
    const combined = base64ToBytes(encryptedWithIvB64);
    if (combined.length <= AES_GCM_IV_LENGTH) {
      return null;
    }

    // Detect new "OM" format: [magic 2B][fingerprint 4B][IV 12B][ciphertext]
    let offset = 0;
    if (
      combined.length > CIPHERTEXT_HEADER_LENGTH + AES_GCM_IV_LENGTH &&
      combined[0] === CIPHERTEXT_MAGIC_0 &&
      combined[1] === CIPHERTEXT_MAGIC_1
    ) {
      offset = CIPHERTEXT_HEADER_LENGTH;
    }

    const iv = combined.slice(offset, offset + AES_GCM_IV_LENGTH);
    const ciphertext = combined.slice(offset + AES_GCM_IV_LENGTH);
    const key = await cryptoApi.subtle.importKey(
      "raw",
      toArrayBuffer(rawKeyBytes),
      { name: "AES-GCM" },
      false,
      ["decrypt"],
    );
    const decrypted = await cryptoApi.subtle.decrypt(
      { name: "AES-GCM", iv: toArrayBuffer(iv) },
      key,
      toArrayBuffer(ciphertext),
    );
    return new Uint8Array(decrypted);
  } catch {
    return null;
  }
}

/**
 * Encrypt raw bytes with AES-256-GCM and return base64(IV || ciphertext).
 *
 * Mirrors cryptoService.ts encryptChatKeyWithMasterKey() — used for wrapping
 * a 32-byte chat key with the master key. MUST use this (not the string
 * variant) because the input is binary, not UTF-8.
 */
export async function encryptBytesWithAesGcm(
  data: Uint8Array,
  rawKeyBytes: Uint8Array,
): Promise<string> {
  const iv = cryptoApi.getRandomValues(new Uint8Array(AES_GCM_IV_LENGTH));
  const key = await cryptoApi.subtle.importKey(
    "raw",
    toArrayBuffer(rawKeyBytes),
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );
  const encrypted = await cryptoApi.subtle.encrypt(
    { name: "AES-GCM", iv: toArrayBuffer(iv) },
    key,
    toArrayBuffer(data),
  );
  const cipherBytes = new Uint8Array(encrypted);
  const combined = new Uint8Array(iv.length + cipherBytes.length);
  combined.set(iv);
  combined.set(cipherBytes, iv.length);
  return bytesToBase64(combined);
}

export async function encryptWithAesGcmCombined(
  plaintext: string,
  rawKeyBytes: Uint8Array,
): Promise<string> {
  const iv = cryptoApi.getRandomValues(new Uint8Array(AES_GCM_IV_LENGTH));
  const key = await cryptoApi.subtle.importKey(
    "raw",
    toArrayBuffer(rawKeyBytes),
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );
  const encrypted = await cryptoApi.subtle.encrypt(
    { name: "AES-GCM", iv: toArrayBuffer(iv) },
    key,
    new TextEncoder().encode(plaintext),
  );
  const cipherBytes = new Uint8Array(encrypted);
  const combined = new Uint8Array(iv.length + cipherBytes.length);
  combined.set(iv);
  combined.set(cipherBytes, iv.length);
  return bytesToBase64(combined);
}

/**
 * Hash an item key for zero-knowledge storage in Directus.
 *
 * Mirrors the browser's appSettingsMemoriesStore behaviour:
 *   SHA-256(`${appId}-${itemKey}-${timestamp}`).slice(0, 32) hex chars.
 *
 * The cleartext key is stored INSIDE the encrypted payload (_original_item_key)
 * so the CLI/browser can recover it on decrypt without the server ever seeing it.
 *
 * @param appId   - App identifier (e.g. "code")
 * @param itemKey - Human-readable key (e.g. "preferred_technologies")
 * @returns First 32 hex characters of SHA-256 hash
 */
export function hashItemKey(appId: string, itemKey: string): string {
  const raw = `${appId}-${itemKey}-${Date.now()}`;
  return createHash("sha256").update(raw).digest("hex").slice(0, 32);
}
