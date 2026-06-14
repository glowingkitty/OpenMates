// frontend/packages/ui/src/services/__tests__/cryptoService.test.ts
// Unit tests for public cryptoService key wrapping helpers.
//
// These helpers sit on the login-critical path for password, recovery-key,
// backup-code, and passkey authentication. The test covers the public contract
// instead of WebCrypto implementation details so browser-specific workarounds
// can change without weakening the stored-key compatibility guarantee.

import { webcrypto } from "node:crypto";
import { beforeAll, describe, expect, it } from "vitest";

import { decryptKey, encryptKey, generateExtractableMasterKey } from "../cryptoService";

beforeAll(() => {
  Object.defineProperty(globalThis, "crypto", {
    value: webcrypto,
    writable: true,
    configurable: true,
  });

  if (typeof globalThis.btoa === "undefined") {
    globalThis.btoa = (str: string) => Buffer.from(str, "binary").toString("base64");
  }
  if (typeof globalThis.atob === "undefined") {
    globalThis.atob = (str: string) => Buffer.from(str, "base64").toString("binary");
  }
});

describe("cryptoService key wrapping", () => {
  it("decrypts keys produced by encryptKey", async () => {
    const masterKey = await generateExtractableMasterKey();
    const wrappingKey = new Uint8Array(32).fill(7);

    const encrypted = await encryptKey(masterKey, wrappingKey);
    const decryptedKey = await decryptKey(encrypted.wrapped, encrypted.iv, wrappingKey);

    expect(decryptedKey).not.toBeNull();
    const originalRaw = new Uint8Array(await crypto.subtle.exportKey("raw", masterKey));
    const decryptedRaw = new Uint8Array(await crypto.subtle.exportKey("raw", decryptedKey!));
    expect(Array.from(decryptedRaw)).toEqual(Array.from(originalRaw));
  });
});
