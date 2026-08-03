/**
 * Media encryption reader compatibility contracts.
 *
 * Production web readers must preserve frozen legacy media and support only
 * the explicit nonce-prefixed v2 marker. Unknown markers fail before plaintext
 * is returned, and these tests never mutate the shared fixture metadata.
 */

import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  MEDIA_ENCRYPTION_V2,
  decryptMediaPayload,
} from "../mediaEncryption";

interface LegacyMediaFixture {
  aes_key_b64: string;
  aes_nonce: string;
  variants: Record<
    string,
    { ciphertext_b64: string; plaintext: string; s3_key: string }
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
      "../../../../../../../backend/tests/fixtures/encryption_compatibility/legacy_layouts.json",
      import.meta.url,
    ),
    "utf-8",
  ),
) as { legacy_media: LegacyMediaFixture[] };

describe("media encryption compatibility", () => {
  it("decrypts every frozen legacy media variant without mutation", async () => {
    const original = structuredClone(frozenFixtures.legacy_media);

    for (const media of frozenFixtures.legacy_media) {
      for (const variant of Object.values(media.variants)) {
        const plaintext = await decryptMediaPayload({
          encryptedData: decodeBase64(variant.ciphertext_b64),
          aesKeyBase64: media.aes_key_b64,
          variant,
          legacyNonceBase64: media.aes_nonce,
        });
        expect(new TextDecoder().decode(plaintext)).toBe(variant.plaintext);
      }
    }

    expect(frozenFixtures.legacy_media).toEqual(original);
  });

  it("decrypts explicitly marked nonce-prefixed v2 media", async () => {
    const key = Uint8Array.from({ length: 32 }, (_, index) => index);
    const nonce = Uint8Array.from({ length: 12 }, (_, index) => index);
    const cryptoKey = await crypto.subtle.importKey(
      "raw",
      key,
      { name: "AES-GCM" },
      false,
      ["encrypt"],
    );
    const plaintext = new TextEncoder().encode("remotion_output:v2-video");
    const ciphertext = new Uint8Array(
      await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, cryptoKey, plaintext),
    );
    const payload = new Uint8Array(nonce.length + ciphertext.length);
    payload.set(nonce);
    payload.set(ciphertext, nonce.length);

    await expect(
      decryptMediaPayload({
        encryptedData: payload.buffer,
        aesKeyBase64: encodeBase64(key),
        variant: { encryption: MEDIA_ENCRYPTION_V2 },
        legacyNonceBase64: null,
      }),
    ).resolves.toEqual(plaintext.buffer);
  });

  it("rejects unknown media encryption markers", async () => {
    await expect(
      decryptMediaPayload({
        encryptedData: new Uint8Array(32).buffer,
        aesKeyBase64: encodeBase64(new Uint8Array(32)),
        variant: { encryption: "unknown-version" },
        legacyNonceBase64: null,
      }),
    ).rejects.toThrow("Unsupported media encryption marker");
  });
});

function decodeBase64(value: string): ArrayBuffer {
  return Uint8Array.from(Buffer.from(value, "base64")).buffer;
}

function encodeBase64(value: Uint8Array): string {
  return Buffer.from(value).toString("base64");
}
