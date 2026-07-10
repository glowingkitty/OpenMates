/**
 * Cross-client encryption contract for the native Apple composer.
 * The checked-in fixture contains deterministic synthetic keys and nonces only.
 * MessageEncryptor and MetadataEncryptor remain the authoritative web APIs.
 * Apple XCTest consumes the same Format A, C, D, and embed vectors.
 * No production identity, content, credential, or secret is used here.
 */

import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it } from "vitest";
import {
  decryptWithChatKey,
  encryptWithChatKey,
} from "../encryption/MessageEncryptor";
import {
  decryptChatKeyWithMasterKey,
  decryptWithEmbedKey,
  deriveEmbedKeyFromChatKey,
  encryptWithEmbedKey,
  encryptWithMasterKeyDirect,
  unwrapEmbedKeyWithChatKey,
  wrapEmbedKeyWithChatKey,
} from "../encryption/MetadataEncryptor";

interface CipherVector {
  iv_base64: string;
  ciphertext_base64: string;
}

interface EncryptionFixture {
  schema_version: number;
  fixture_kind: string;
  synthetic_notice: string;
  keys: {
    master_key_base64: string;
    chat_key_base64: string;
    wrong_key_base64: string;
  };
  plaintext: {
    canonical_draft_markdown: string;
    draft_preview: string;
    canonical_message_plaintext: string;
    pii_mappings_json: string;
    embed_reference_json: string;
  };
  format_a: {
    message: CipherVector;
    pii_mappings: CipherVector;
    embed_reference: CipherVector;
  };
  format_c: {
    iv_base64: string;
    wrapped_chat_key_base64: string;
  };
  format_d: {
    draft: CipherVector;
    preview: CipherVector;
  };
  embed: {
    id: string;
    content_plaintext: string;
    derived_key_base64: string;
    master_wrapped_key: CipherVector;
    chat_wrapped_key: CipherVector;
    encrypted_content: CipherVector;
  };
}

const realCrypto = webcrypto as unknown as Crypto;

Object.defineProperty(globalThis, "crypto", {
  value: realCrypto,
  writable: true,
  configurable: true,
});
Object.defineProperty(globalThis, "btoa", {
  value: (value: string) => Buffer.from(value, "binary").toString("base64"),
  writable: true,
  configurable: true,
});
Object.defineProperty(globalThis, "atob", {
  value: (value: string) => Buffer.from(value, "base64").toString("binary"),
  writable: true,
  configurable: true,
});

const fixture = JSON.parse(
  readFileSync(
    new URL(
      "../../../../../../shared/composer/fixtures/apple-composer-encryption-v1.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as EncryptionFixture;

const masterKeyBytes = decodeBase64(fixture.keys.master_key_base64);
const chatKey = decodeBase64(fixture.keys.chat_key_base64);
const wrongKey = decodeBase64(fixture.keys.wrong_key_base64);

afterEach(() => installCrypto(realCrypto));

describe("Apple composer cross-client encryption fixture", () => {
  it("contains only explicit synthetic 32-byte key material and .invalid identities", () => {
    const serialized = JSON.stringify(fixture);

    expect(fixture.schema_version).toBe(1);
    expect(fixture.fixture_kind).toBe(
      "synthetic-cross-client-composer-encryption",
    );
    expect(fixture.synthetic_notice).toContain("composer-fixture.invalid");
    expect(masterKeyBytes).toHaveLength(32);
    expect(chatKey).toHaveLength(32);
    expect(wrongKey).toHaveLength(32);
    expect(serialized).toContain(".invalid");
    expect(serialized).not.toMatch(/BEGIN (?:RSA |EC )?PRIVATE KEY|Bearer\s|sk-[A-Za-z0-9]/);
  });

  it("matches deterministic Format A message, PII, and embed-reference vectors", async () => {
    const cases = [
      [fixture.format_a.message, fixture.plaintext.canonical_message_plaintext],
      [fixture.format_a.pii_mappings, fixture.plaintext.pii_mappings_json],
      [fixture.format_a.embed_reference, fixture.plaintext.embed_reference_json],
    ] as const;

    for (const [vector, plaintext] of cases) {
      const encrypted = await withDeterministicIV(vector.iv_base64, () =>
        encryptWithChatKey(plaintext, chatKey),
      );

      expect(encrypted).toBe(vector.ciphertext_base64);
      expect(await decryptWithChatKey(vector.ciphertext_base64, chatKey)).toBe(
        plaintext,
      );
    }

    expect(
      await decryptWithChatKey(
        fixture.format_a.message.ciphertext_base64,
        wrongKey,
      ),
    ).toBeNull();
    expect(JSON.parse(fixture.plaintext.pii_mappings_json)).toEqual([
      {
        placeholder: "[EMAIL_1_invalid]",
        original: "test.user@composer-fixture.invalid",
        type: "EMAIL",
      },
    ]);
    expect(JSON.parse(fixture.plaintext.embed_reference_json)).toMatchObject({
      embed_id: fixture.embed.id,
    });
  });

  it("unwraps the deterministic Format C chat key with the direct metadata API", async () => {
    const masterKey = await importMasterKey();
    const unwrapped = await decryptChatKeyWithMasterKey(
      fixture.format_c.wrapped_chat_key_base64,
      masterKey,
    );

    expect(unwrapped).toEqual(chatKey);
    expect(decodeBase64(fixture.format_c.iv_base64)).toHaveLength(12);
    expect(decodeBase64(fixture.format_c.wrapped_chat_key_base64)).toHaveLength(
      60,
    );
  });

  it("matches deterministic Format D draft and preview vectors", async () => {
    const masterKey = await importMasterKey();
    const cases = [
      [fixture.format_d.draft, fixture.plaintext.canonical_draft_markdown],
      [fixture.format_d.preview, fixture.plaintext.draft_preview],
    ] as const;

    for (const [vector, plaintext] of cases) {
      const encrypted = await withDeterministicIV(vector.iv_base64, () =>
        encryptWithMasterKeyDirect(plaintext, masterKey),
      );

      expect(encrypted).toBe(vector.ciphertext_base64);
      expect(await decryptAESGCMText(vector.ciphertext_base64, masterKey)).toBe(
        plaintext,
      );
    }
  });

  it("matches deterministic embed derivation, wrapping, and content vectors", async () => {
    const derivedKey = await deriveEmbedKeyFromChatKey(chatKey, fixture.embed.id);
    const masterKey = await importMasterKey();

    expect(derivedKey).toEqual(decodeBase64(fixture.embed.derived_key_base64));
    expect(
      await decryptChatKeyWithMasterKey(
        fixture.embed.master_wrapped_key.ciphertext_base64,
        masterKey,
      ),
    ).toEqual(derivedKey);

    const chatWrapped = await withDeterministicIV(
      fixture.embed.chat_wrapped_key.iv_base64,
      () => wrapEmbedKeyWithChatKey(derivedKey, chatKey),
    );
    expect(chatWrapped).toBe(
      fixture.embed.chat_wrapped_key.ciphertext_base64,
    );
    expect(
      await unwrapEmbedKeyWithChatKey(chatWrapped, chatKey, {
        embedId: fixture.embed.id,
        chatId: "synthetic-chat.composer-fixture.invalid",
      }),
    ).toEqual(derivedKey);

    const encryptedContent = await withDeterministicIV(
      fixture.embed.encrypted_content.iv_base64,
      () => encryptWithEmbedKey(fixture.embed.content_plaintext, derivedKey),
    );
    expect(encryptedContent).toBe(
      fixture.embed.encrypted_content.ciphertext_base64,
    );
    expect(
      await decryptWithEmbedKey(encryptedContent, derivedKey, {
        embedId: fixture.embed.id,
      }),
    ).toBe(fixture.embed.content_plaintext);
  });
});

function decodeBase64(value: string): Uint8Array {
  return Uint8Array.from(Buffer.from(value, "base64"));
}

async function importMasterKey(): Promise<CryptoKey> {
  return realCrypto.subtle.importKey(
    "raw",
    new Uint8Array(masterKeyBytes),
    { name: "AES-GCM" },
    false,
    ["encrypt", "decrypt"],
  );
}

function installCrypto(value: Crypto): void {
  Object.defineProperty(globalThis, "crypto", {
    value,
    writable: true,
    configurable: true,
  });
}

async function withDeterministicIV<T>(
  ivBase64: string,
  operation: () => Promise<T>,
): Promise<T> {
  const iv = decodeBase64(ivBase64);
  const deterministicCrypto = {
    subtle: realCrypto.subtle,
    getRandomValues<TArray extends ArrayBufferView | null>(array: TArray): TArray {
      if (array === null) {
        throw new TypeError("Expected an ArrayBufferView");
      }
      const destination = new Uint8Array(
        array.buffer as ArrayBuffer,
        array.byteOffset,
        array.byteLength,
      );
      if (destination.byteLength !== iv.byteLength) {
        throw new RangeError(`Expected ${iv.byteLength} nonce bytes`);
      }
      destination.set(iv);
      return array;
    },
  } as Crypto;

  installCrypto(deterministicCrypto);
  try {
    return await operation();
  } finally {
    installCrypto(realCrypto);
  }
}

async function decryptAESGCMText(
  combinedBase64: string,
  key: CryptoKey,
): Promise<string> {
  const combined = decodeBase64(combinedBase64);
  const plaintext = await realCrypto.subtle.decrypt(
    { name: "AES-GCM", iv: combined.slice(0, 12) },
    key,
    combined.slice(12),
  );
  return new TextDecoder().decode(plaintext);
}
