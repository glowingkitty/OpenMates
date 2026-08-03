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
  hkdf,
} from "../../cryptoService";

const originalCrypto = globalThis.crypto;
const ZERO_KEY = new Uint8Array(32);

function setCrypto(value: Crypto | undefined): void {
  Object.defineProperty(globalThis, "crypto", {
    value,
    writable: true,
    configurable: true,
  });
}

beforeEach(() => setCrypto(webcrypto as Crypto));
afterEach(() => setCrypto(originalCrypto));

describe("WebCrypto derivation hardening", () => {
  it("derives password, email, and passkey keys in a worker-compatible runtime", async () => {
    const salt = new Uint8Array([1, 3, 3, 7, 9, 2, 4, 6]);
    const passwordKey = await deriveKeyFromPassword("correct horse", salt);
    const emailKey = await deriveEmailEncryptionKey("person@example.invalid", salt);
    const passkeyKey = await hkdf(salt, new Uint8Array(32).fill(11), "masterkey_wrapping");

    expect(passwordKey).toHaveLength(32);
    expect(emailKey).toHaveLength(32);
    expect(passkeyKey).toHaveLength(32);
    expect(passwordKey).not.toEqual(ZERO_KEY);
    expect(emailKey).not.toEqual(ZERO_KEY);
    expect(passkeyKey).not.toEqual(ZERO_KEY);
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

describe("embed persistence key hardening", () => {
  it("contains no random embed-key fallback when the chat key is unavailable", () => {
    const source = readFileSync(new URL("../../sendersChatMessages.ts", import.meta.url), "utf8");

    expect(source).not.toContain("generateEmbedKey");
    expect(source).not.toContain("using random key for embed");
  });
});
