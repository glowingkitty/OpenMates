/**
 * Regression tests for fail-closed browser and worker cryptography.
 *
 * These tests ensure supported WebCrypto runtimes derive real key material,
 * unsupported runtimes throw typed errors, and embed persistence cannot fall
 * back to an unrelated random key when its chat key is unavailable.
 */

import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  deriveEmailEncryptionKey,
  deriveKeyFromPassword,
  generateSecureRecoveryKey,
  hkdf,
} from "../cryptoService";
import {
  clearCryptoKeyCache,
  computeKeyFingerprint4Bytes,
  decryptWithChatKey,
  encryptWithChatKey,
} from "../encryption/MessageEncryptor";

const originalCrypto = globalThis.crypto;
const ZERO_KEY = new Uint8Array(32);
const KEY_BITS = 256;
const PBKDF2_ITERATIONS = 100_000;
const COLLIDING_KEY_ONE = Uint8Array.from(
  Buffer.from("a7529306441c37f4fb644de0d27096d614ae0b09701eebe522f18e429711f509", "hex"),
);
const COLLIDING_KEY_TWO = Uint8Array.from(
  Buffer.from("4f18ac6fbd4d1478ec38d1c5caf855bb6ce7db8d17e1f5d77cab3111331399af", "hex"),
);

function setCrypto(value: Crypto | undefined): void {
  Object.defineProperty(globalThis, "crypto", {
    value,
    writable: true,
    configurable: true,
  });
}

async function referencePasswordKey(password: string, salt: Uint8Array): Promise<Uint8Array> {
  const material = await webcrypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const bits = await webcrypto.subtle.deriveBits(
    {
      name: "PBKDF2",
      salt,
      iterations: PBKDF2_ITERATIONS,
      hash: "SHA-256",
    },
    material,
    KEY_BITS,
  );
  return new Uint8Array(bits);
}

async function referenceEmailKey(email: string, salt: Uint8Array): Promise<Uint8Array> {
  const emailBytes = new TextEncoder().encode(email);
  const input = new Uint8Array(emailBytes.length + salt.length);
  input.set(emailBytes);
  input.set(salt, emailBytes.length);
  return new Uint8Array(await webcrypto.subtle.digest("SHA-256", input));
}

async function referencePasskeyKey(
  salt: Uint8Array,
  inputKeyMaterial: Uint8Array,
  info: string,
): Promise<Uint8Array> {
  const material = await webcrypto.subtle.importKey("raw", inputKeyMaterial, "HKDF", false, ["deriveBits"]);
  const bits = await webcrypto.subtle.deriveBits(
    {
      name: "HKDF",
      hash: "SHA-256",
      salt,
      info: new TextEncoder().encode(info),
    },
    material,
    KEY_BITS,
  );
  return new Uint8Array(bits);
}

beforeEach(() => setCrypto(webcrypto as Crypto));
afterEach(() => setCrypto(originalCrypto));

describe("WebCrypto derivation hardening", () => {
  it("matches standard PBKDF2 in a worker-compatible runtime", async () => {
    const salt = new Uint8Array([1, 3, 3, 7, 9, 2, 4, 6]);
    const passwordKey = await deriveKeyFromPassword("correct horse", salt);

    expect(passwordKey).toHaveLength(32);
    expect(passwordKey).not.toEqual(ZERO_KEY);
    expect(passwordKey).toEqual(await referencePasswordKey("correct horse", salt));
  });

  it("matches standard SHA-256 email derivation in a worker-compatible runtime", async () => {
    const email = "person@example.invalid";
    const salt = new Uint8Array([1, 3, 3, 7, 9, 2, 4, 6]);
    const emailKey = await deriveEmailEncryptionKey(email, salt);

    expect(emailKey).toHaveLength(32);
    expect(emailKey).not.toEqual(ZERO_KEY);
    expect(emailKey).toEqual(await referenceEmailKey(email, salt));
  });

  it("matches standard HKDF passkey derivation in a worker-compatible runtime", async () => {
    const salt = new Uint8Array([1, 3, 3, 7, 9, 2, 4, 6]);
    const inputKeyMaterial = new Uint8Array(32).fill(11);
    const info = "masterkey_wrapping";
    const passkeyKey = await hkdf(salt, inputKeyMaterial, info);

    expect(passkeyKey).toHaveLength(32);
    expect(passkeyKey).not.toEqual(ZERO_KEY);
    expect(passkeyKey).toEqual(await referencePasskeyKey(salt, inputKeyMaterial, info));
  });

  it.each([
    ["password PBKDF2", () => deriveKeyFromPassword("password", new Uint8Array([1]))],
    ["email SHA-256", () => deriveEmailEncryptionKey("person@example.invalid", new Uint8Array([1]))],
    ["passkey HKDF", () => hkdf(new Uint8Array([1]), new Uint8Array([2]), "masterkey_wrapping")],
  ])("throws a typed error when %s has no WebCrypto", async (_name, derive) => {
    setCrypto(undefined);

    await expect(derive()).rejects.toMatchObject({
      name: "UnsupportedClientCryptoError",
      code: "unsupported_client_crypto",
    });
  });
});

describe("recovery key randomness", () => {
  it("uses rejection sampling and the approved 24-character shape", () => {
    let calls = 0;
    setCrypto({
      getRandomValues<T extends ArrayBufferView>(values: T): T {
        new Uint8Array(values.buffer, values.byteOffset, values.byteLength).fill(
          calls++ % 2 === 0 ? 255 : 0,
        );
        return values;
      },
    } as Crypto);

    const recoveryKey = generateSecureRecoveryKey();

    expect(calls).toBeGreaterThan(47);
    expect(recoveryKey).toHaveLength(24);
    expect(recoveryKey).toMatch(/^[^0O]+$/);
    expect(recoveryKey).toMatch(/[A-Z]/);
    expect(recoveryKey).toMatch(/[a-z]/);
    expect(recoveryKey).toMatch(/[2-9]/);
    expect(recoveryKey).toMatch(/[#\-=+_&%$]/);
  });

  it("fails closed when secure randomness fails", () => {
    setCrypto({
      getRandomValues(): never {
        throw new Error("rng unavailable");
      },
    } as unknown as Crypto);

    expect(() => generateSecureRecoveryKey()).toThrow("rng unavailable");
  });
});

describe("embed persistence key hardening", () => {
  it("contains no random embed-key fallback when the chat key is unavailable", () => {
    const source = readFileSync(new URL("../sendersChatMessages.ts", import.meta.url), "utf8");

    expect(source).not.toContain("generateEmbedKey");
    expect(source).not.toContain("using random key for embed");
  });
});

describe("chat CryptoKey cache hardening", () => {
  it("does not share an encryption cache entry between colliding FNV keys", async () => {
    expect(computeKeyFingerprint4Bytes(COLLIDING_KEY_ONE)).toEqual(
      computeKeyFingerprint4Bytes(COLLIDING_KEY_TWO),
    );

    clearCryptoKeyCache();
    await encryptWithChatKey("first key", COLLIDING_KEY_ONE);
    const secondCiphertext = await encryptWithChatKey("second key", COLLIDING_KEY_TWO);
    clearCryptoKeyCache();

    expect(await decryptWithChatKey(secondCiphertext, COLLIDING_KEY_TWO)).toBe("second key");
  });

  it("does not share a decryption cache entry or change ciphertext headers", async () => {
    clearCryptoKeyCache();
    const firstCiphertext = await encryptWithChatKey("first key", COLLIDING_KEY_ONE);
    clearCryptoKeyCache();
    const secondCiphertext = await encryptWithChatKey("second key", COLLIDING_KEY_TWO);
    clearCryptoKeyCache();

    const firstHeader = Buffer.from(firstCiphertext, "base64").subarray(0, 6).toString("hex");
    const secondHeader = Buffer.from(secondCiphertext, "base64").subarray(0, 6).toString("hex");
    expect(firstHeader).toBe("4f4d3f1fbc49");
    expect(secondHeader).toBe(firstHeader);
    expect(await decryptWithChatKey(firstCiphertext, COLLIDING_KEY_ONE)).toBe("first key");
    expect(await decryptWithChatKey(secondCiphertext, COLLIDING_KEY_TWO)).toBe("second key");
  });
});
