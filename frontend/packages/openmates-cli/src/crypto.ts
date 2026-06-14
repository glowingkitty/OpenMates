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
import nacl from "tweetnacl";

const cryptoApi = globalThis.crypto ?? webcrypto;
const PAIR_KDF_ITERATIONS = 100_000;
const SIGNUP_KDF_ITERATIONS = 100_000;
const AES_GCM_IV_LENGTH = 12;
const EMAIL_SALT_LENGTH = 16;
const MASTER_KEY_LENGTH = 32;
const NACL_NONCE_LENGTH = 24;

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

export function generateSalt(length = EMAIL_SALT_LENGTH): Uint8Array {
  return cryptoApi.getRandomValues(new Uint8Array(length));
}

export function generateSecureRecoveryKey(length = 24): string {
  const uppercaseChars = "ABCDEFGHJKLMNPQRSTUVWXYZ";
  const lowercaseChars = "abcdefghijkmnopqrstuvwxyz";
  const numberChars = "23456789";
  const specialChars = "#-=+_&%$";
  const allChars = uppercaseChars + lowercaseChars + numberChars + specialChars;
  const result: string[] = new Array(length);
  const requiredSets = [uppercaseChars, lowercaseChars, numberChars, specialChars];

  for (let index = 0; index < requiredSets.length && index < length; index += 1) {
    const randomByte = cryptoApi.getRandomValues(new Uint8Array(1))[0];
    const chars = requiredSets[index];
    result[index] = chars.charAt(randomByte % chars.length);
  }

  const randomBytes = cryptoApi.getRandomValues(new Uint8Array(length));
  for (let index = requiredSets.length; index < length; index += 1) {
    result[index] = allChars.charAt(randomBytes[index] % allChars.length);
  }

  for (let index = result.length - 1; index > 0; index -= 1) {
    const randomByte = cryptoApi.getRandomValues(new Uint8Array(1))[0];
    const swapIndex = Math.floor((randomByte / 256) * (index + 1));
    [result[index], result[swapIndex]] = [result[swapIndex], result[index]];
  }

  return result.join("");
}

export async function hashEmail(email: string): Promise<string> {
  const hashBuffer = await cryptoApi.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(email),
  );
  return bytesToBase64(new Uint8Array(hashBuffer));
}

export async function hashKey(key: string, salt?: Uint8Array | null): Promise<string> {
  const keyBytes = new TextEncoder().encode(key);
  const dataToHash = salt
    ? new Uint8Array(keyBytes.length + salt.length)
    : keyBytes;
  if (salt) {
    dataToHash.set(keyBytes);
    dataToHash.set(salt, keyBytes.length);
  }
  const hashBuffer = await cryptoApi.subtle.digest("SHA-256", toArrayBuffer(dataToHash));
  return bytesToBase64(new Uint8Array(hashBuffer));
}

export async function deriveKeyFromPassword(password: string, salt: Uint8Array): Promise<Uint8Array> {
  const keyMaterial = await cryptoApi.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const derivedBits = await cryptoApi.subtle.deriveBits(
    {
      name: "PBKDF2",
      salt: toArrayBuffer(salt),
      iterations: SIGNUP_KDF_ITERATIONS,
      hash: "SHA-256",
    },
    keyMaterial,
    256,
  );
  return new Uint8Array(derivedBits);
}

export async function encryptEmail(email: string, key: Uint8Array): Promise<string> {
  if (key.length !== MASTER_KEY_LENGTH) {
    throw new Error(`Email encryption key must be 32 bytes, got ${key.length}`);
  }
  const nonce = nacl.randomBytes(NACL_NONCE_LENGTH);
  const ciphertext = nacl.secretbox(new TextEncoder().encode(email), nonce, key);
  const combined = new Uint8Array(nonce.length + ciphertext.length);
  combined.set(nonce);
  combined.set(ciphertext, nonce.length);
  return bytesToBase64(combined);
}

async function encryptRawKeyWithAesGcm(rawKey: Uint8Array, wrappingKeyBytes: Uint8Array): Promise<{ wrapped: string; iv: string }> {
  const iv = cryptoApi.getRandomValues(new Uint8Array(AES_GCM_IV_LENGTH));
  const wrappingKey = await cryptoApi.subtle.importKey(
    "raw",
    toArrayBuffer(wrappingKeyBytes),
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );
  const encrypted = await cryptoApi.subtle.encrypt(
    { name: "AES-GCM", iv: toArrayBuffer(iv) },
    wrappingKey,
    toArrayBuffer(rawKey),
  );
  return {
    wrapped: bytesToBase64(new Uint8Array(encrypted)),
    iv: bytesToBase64(iv),
  };
}

export interface SignupCryptoMaterial {
  hashedEmail: string;
  encryptedEmail: string;
  encryptedEmailWithMasterKey: string;
  userEmailSaltB64: string;
  emailEncryptionKeyB64: string;
  masterKeyB64: string;
  encryptedMasterKey: string;
  keyIv: string;
  saltB64: string;
  lookupHash: string;
}

export async function createSignupCryptoMaterial(email: string, password: string): Promise<SignupCryptoMaterial> {
  const normalizedEmail = email.trim().toLowerCase();
  const emailSalt = generateSalt(EMAIL_SALT_LENGTH);
  const passwordSalt = generateSalt(EMAIL_SALT_LENGTH);
  const masterKey = generateSalt(MASTER_KEY_LENGTH);
  const emailEncryptionKeyB64 = await deriveEmailEncryptionKeyB64(normalizedEmail, bytesToBase64(emailSalt));
  const emailEncryptionKey = base64ToBytes(emailEncryptionKeyB64);
  const wrappingKey = await deriveKeyFromPassword(password, passwordSalt);
  const encryptedMasterKey = await encryptRawKeyWithAesGcm(masterKey, wrappingKey);

  return {
    hashedEmail: await hashEmail(normalizedEmail),
    encryptedEmail: await encryptEmail(normalizedEmail, emailEncryptionKey),
    encryptedEmailWithMasterKey: await encryptWithAesGcmCombined(normalizedEmail, masterKey),
    userEmailSaltB64: bytesToBase64(emailSalt),
    emailEncryptionKeyB64,
    masterKeyB64: bytesToBase64(masterKey),
    encryptedMasterKey: encryptedMasterKey.wrapped,
    keyIv: encryptedMasterKey.iv,
    saltB64: bytesToBase64(passwordSalt),
    lookupHash: await hashKey(password, emailSalt),
  };
}

export interface RecoveryKeyMaterial {
  recoveryKey: string;
  lookupHash: string;
  wrappedMasterKey: string;
  keyIv: string;
  saltB64: string;
}

export async function createRecoveryKeyMaterial(masterKeyB64: string, userEmailSaltB64: string): Promise<RecoveryKeyMaterial> {
  const recoveryKey = generateSecureRecoveryKey();
  const userEmailSalt = base64ToBytes(userEmailSaltB64);
  const wrappingSalt = generateSalt(EMAIL_SALT_LENGTH);
  const wrappingKey = await deriveKeyFromPassword(recoveryKey, wrappingSalt);
  const encryptedMasterKey = await encryptRawKeyWithAesGcm(base64ToBytes(masterKeyB64), wrappingKey);

  return {
    recoveryKey,
    lookupHash: await hashKey(recoveryKey, userEmailSalt),
    wrappedMasterKey: encryptedMasterKey.wrapped,
    keyIv: encryptedMasterKey.iv,
    saltB64: bytesToBase64(wrappingSalt),
  };
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

export async function deriveEmailEncryptionKeyB64(
  email: string,
  emailSaltB64: string,
): Promise<string> {
  const encoder = new TextEncoder();
  const emailBytes = encoder.encode(email);
  const saltBytes = base64ToBytes(emailSaltB64);
  const combined = new Uint8Array(emailBytes.length + saltBytes.length);
  combined.set(emailBytes);
  combined.set(saltBytes, emailBytes.length);
  const hashBuffer = await cryptoApi.subtle.digest("SHA-256", toArrayBuffer(combined));
  return bytesToBase64(new Uint8Array(hashBuffer));
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
