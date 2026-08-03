/**
 * Frozen cross-client encryption compatibility checks.
 *
 * Loads deterministic synthetic fixtures shared with backend compatibility
 * guards and exercises the production web readers for Formats A through D.
 * This path is intentionally included by the Node-based CI Vitest suite.
 */

import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { clearMasterKey, saveMasterKey } from "../cryptoKeyStorage";
import {
  decryptChatKeyWithMasterKey,
  decryptWithMasterKey,
} from "../encryption/MetadataEncryptor";
import { decryptWithChatKey } from "../encryption/MessageEncryptor";
import { base64ToUint8Array } from "../cryptoService";

interface FrozenCompatibilityFixtures {
  keys: {
    content_key_b64: string;
    wrapping_key_b64: string;
  };
  chat: Record<
    "format_a" | "format_b" | "format_c" | "format_d",
    { blob_b64: string; plaintext?: string; plaintext_key_b64?: string }
  >;
}

Object.defineProperty(globalThis, "crypto", {
  value: webcrypto as unknown as Crypto,
  writable: true,
  configurable: true,
});

const frozenFixtures = JSON.parse(
  readFileSync(
    new URL(
      "../../../../../../backend/tests/fixtures/encryption_compatibility/legacy_layouts.json",
      import.meta.url,
    ),
    "utf-8",
  ),
) as FrozenCompatibilityFixtures;

describe("frozen encryption compatibility fixtures", () => {
  it("decrypts frozen Format A and B messages", async () => {
    const key = base64ToUint8Array(frozenFixtures.keys.content_key_b64);

    await expect(
      decryptWithChatKey(frozenFixtures.chat.format_a.blob_b64, key),
    ).resolves.toBe(frozenFixtures.chat.format_a.plaintext);
    await expect(
      decryptWithChatKey(frozenFixtures.chat.format_b.blob_b64, key),
    ).resolves.toBe(frozenFixtures.chat.format_b.plaintext);
  });

  it("unwraps the frozen Format C chat key", async () => {
    const wrappingKey = await importWrappingKey();
    const unwrapped = await decryptChatKeyWithMasterKey(
      frozenFixtures.chat.format_c.blob_b64,
      wrappingKey,
    );

    expect(unwrapped).toEqual(
      base64ToUint8Array(frozenFixtures.chat.format_c.plaintext_key_b64!),
    );
  });

  it("decrypts frozen Format D through the stored master-key reader", async () => {
    await saveMasterKey(await importWrappingKey(), false);
    try {
      await expect(
        decryptWithMasterKey(frozenFixtures.chat.format_d.blob_b64),
      ).resolves.toBe(frozenFixtures.chat.format_d.plaintext);
    } finally {
      await clearMasterKey();
    }
  });
});

function importWrappingKey(): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new Uint8Array(
      base64ToUint8Array(frozenFixtures.keys.wrapping_key_b64),
    ),
    { name: "AES-GCM" },
    false,
    ["decrypt"],
  );
}
