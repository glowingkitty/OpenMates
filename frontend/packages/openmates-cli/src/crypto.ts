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
    const iv = combined.slice(0, AES_GCM_IV_LENGTH);
    const ciphertext = combined.slice(AES_GCM_IV_LENGTH);
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
