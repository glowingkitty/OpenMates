// frontend/packages/ui/src/services/encryption/__tests__/deriveEmbedKey.test.ts
// Tests for deterministic embed key derivation via HKDF.
//
// Bug this guards against:
//  - Multi-tab race condition: two tabs generate different random embed keys for
//    the same embed, causing permanent key/content mismatch after server upsert.
//    Fix: HKDF(chatKey, embedId) produces the same key on every tab.

import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { webcrypto } from "node:crypto";

// The global test-setup.ts mocks crypto.subtle with vi.fn() stubs.
// We need real Web Crypto for HKDF. Swap in Node's webcrypto for this suite.
let originalCrypto: typeof globalThis.crypto;

beforeAll(() => {
  originalCrypto = globalThis.crypto;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).crypto = webcrypto;
});

afterAll(() => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).crypto = originalCrypto;
});

// Import AFTER crypto is replaced (dynamic import ensures correct binding)
async function getDeriveFunction() {
  const { deriveEmbedKeyFromChatKey } = await import("../../cryptoService");
  return deriveEmbedKeyFromChatKey;
}

describe("deriveEmbedKeyFromChatKey", () => {
  // Use a fixed chat key for reproducible tests
  const chatKey = new Uint8Array(32);
  chatKey.set([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]);

  it("produces a 32-byte key", async () => {
    const derive = await getDeriveFunction();
    const key = await derive(chatKey, "embed-001");
    expect(key).toBeInstanceOf(Uint8Array);
    expect(key.length).toBe(32);
  });

  it("is deterministic — same inputs produce identical output", async () => {
    const derive = await getDeriveFunction();
    const key1 = await derive(chatKey, "embed-001");
    const key2 = await derive(chatKey, "embed-001");
    expect(Array.from(key1)).toEqual(Array.from(key2));
  });

  it("produces different keys for different embed IDs", async () => {
    const derive = await getDeriveFunction();
    const keyA = await derive(chatKey, "embed-aaa");
    const keyB = await derive(chatKey, "embed-bbb");
    expect(Array.from(keyA)).not.toEqual(Array.from(keyB));
  });

  it("produces different keys for different chat keys", async () => {
    const derive = await getDeriveFunction();
    const chatKey2 = new Uint8Array(32);
    chatKey2.set([99, 98, 97, 96]);

    const keyA = await derive(chatKey, "embed-001");
    const keyB = await derive(chatKey2, "embed-001");
    expect(Array.from(keyA)).not.toEqual(Array.from(keyB));
  });

  it("handles UUID-style embed IDs", async () => {
    const derive = await getDeriveFunction();
    const key = await derive(
      chatKey,
      "174d837c-e31f-4485-9604-b84b6b353bbb",
    );
    expect(key.length).toBe(32);
    // Verify determinism with UUID
    const key2 = await derive(
      chatKey,
      "174d837c-e31f-4485-9604-b84b6b353bbb",
    );
    expect(Array.from(key)).toEqual(Array.from(key2));
  });

  it("key is not all zeros", async () => {
    const derive = await getDeriveFunction();
    const key = await derive(chatKey, "embed-001");
    const isAllZeros = key.every((b) => b === 0);
    expect(isAllZeros).toBe(false);
  });
});
