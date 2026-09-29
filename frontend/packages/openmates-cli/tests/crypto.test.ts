/**
 * Unit tests for CLI crypto utilities.
 *
 * Tests AES-GCM roundtrip compatibility, hashItemKey format,
 * and edge-case error handling.
 *
 * Run: node --test --experimental-strip-types tests/crypto.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

import {
  base64ToBytes,
  bytesToBase64,
  encryptWithAesGcmCombined,
  encryptBytesWithAesGcm,
  decryptWithAesGcmCombined,
  decryptBytesWithAesGcm,
  deriveEmbedKeyFromChatKey,
  deriveEmailEncryptionKeyB64,
  createRecoveryKeyMaterial,
  createApiKeyCryptoMaterial,
  createSignupCryptoMaterial,
  createPasswordMigrationMaterialV2,
  derivePasswordMaterialV2,
  derivePasswordKeysV2,
  deriveKeyFromPassword,
  PASSWORD_KDF_V2,
  passwordProofV2,
  unwrapPasswordMasterKey,
  hashEmail,
  hashKey,
  hashItemKey,
  buildRecoveryAssociatedData,
  deriveChatCompletionRecoveryKeypair,
  openChatCompletionRecoveryEnvelope,
  sealChatCompletionRecoveryPayload,
  sealChatCompletionRecoveryPayloadForTest,
} from "../src/crypto.ts";

const recoveryVectors = JSON.parse(
  readFileSync(
    new URL("../../../../backend/tests/fixtures/chat_completion_recovery_vectors.json", import.meta.url),
    "utf8",
  ),
).vectors;

describe("chat-completion-recovery shared vectors", () => {
  for (const vector of recoveryVectors) {
    // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover
    it(`matches exact recovery bytes for ${vector.name}`, async () => {
      const keypair = await deriveChatCompletionRecoveryKeypair(
        vector.chat_key,
        vector.chat_id,
        vector.key_version,
      );
      assert.equal(keypair.privateKey, vector.recovery_private_key);
      assert.equal(keypair.publicKey, vector.recovery_public_key);
      assert.equal(buildRecoveryAssociatedData(vector), vector.associated_data);

      const envelope = await sealChatCompletionRecoveryPayloadForTest(
        new TextEncoder().encode(vector.plaintext),
        {
          recoveryPublicKey: vector.recovery_public_key,
          ownerId: vector.owner_id,
          chatId: vector.chat_id,
          turnId: vector.turn_id,
          jobId: vector.job_id,
          assistantMessageId: vector.assistant_message_id,
          keyVersion: vector.key_version,
          ephemeralPrivateKey: vector.ephemeral_private_key,
          nonce: vector.nonce,
        },
      );
      assert.deepEqual(envelope, vector.envelope);

      const opened = await openChatCompletionRecoveryEnvelope(envelope, {
        recoveryPrivateKey: keypair.privateKey,
        ownerId: vector.owner_id,
        chatId: vector.chat_id,
        turnId: vector.turn_id,
        jobId: vector.job_id,
        assistantMessageId: vector.assistant_message_id,
        keyVersion: vector.key_version,
      });
      assert.equal(new TextDecoder().decode(opened), vector.plaintext);
    });

    // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover
    it(`rejects deterministic production sealing inputs for ${vector.name}`, async () => {
      await assert.rejects(
        () => sealChatCompletionRecoveryPayload(
          new TextEncoder().encode(vector.plaintext),
          {
            recoveryPublicKey: vector.recovery_public_key,
            ownerId: vector.owner_id,
            chatId: vector.chat_id,
            turnId: vector.turn_id,
            jobId: vector.job_id,
            assistantMessageId: vector.assistant_message_id,
            keyVersion: vector.key_version,
            ephemeralPrivateKey: vector.ephemeral_private_key,
            nonce: vector.nonce,
          } as Parameters<typeof sealChatCompletionRecoveryPayload>[1],
        ),
        /deterministic recovery sealing inputs are test-only/,
      );
    });

    // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover
    it(`uses fresh production sealing inputs for ${vector.name}`, async () => {
      const options = {
        recoveryPublicKey: vector.recovery_public_key,
        ownerId: vector.owner_id,
        chatId: vector.chat_id,
        turnId: vector.turn_id,
        jobId: vector.job_id,
        assistantMessageId: vector.assistant_message_id,
        keyVersion: vector.key_version,
      };
      const plaintext = new TextEncoder().encode(vector.plaintext);

      const first = await sealChatCompletionRecoveryPayload(plaintext, options);
      const second = await sealChatCompletionRecoveryPayload(plaintext, options);

      assert.notEqual(first.epk, second.epk);
      assert.notEqual(first.nonce, second.nonce);
    });

    for (const field of ["ciphertext", "nonce", "epk"] as const) {
      // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover
      it(`rejects ${field} tampering for ${vector.name}`, async () => {
        const encoded = vector.envelope[field];
        const envelope = {
          ...vector.envelope,
          [field]: `${encoded[0] === "A" ? "B" : "A"}${encoded.slice(1)}`,
        };
        await assert.rejects(() => openChatCompletionRecoveryEnvelope(envelope, {
          recoveryPrivateKey: vector.recovery_private_key,
          ownerId: vector.owner_id,
          chatId: vector.chat_id,
          turnId: vector.turn_id,
          jobId: vector.job_id,
          assistantMessageId: vector.assistant_message_id,
          keyVersion: vector.key_version,
        }));
      });
    }

    // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover
    it(`rejects associated-data tampering for ${vector.name}`, async () => {
      await assert.rejects(() => openChatCompletionRecoveryEnvelope(vector.envelope, {
        recoveryPrivateKey: vector.recovery_private_key,
        ownerId: vector.owner_id,
        chatId: vector.chat_id,
        turnId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        jobId: vector.job_id,
        assistantMessageId: vector.assistant_message_id,
        keyVersion: vector.key_version,
      }));
    });
  }
});

// ---------------------------------------------------------------------------
// base64 helpers
// ---------------------------------------------------------------------------

describe("base64ToBytes / bytesToBase64", () => {
  // contract-test: infrastructure
  it("roundtrips correctly for short input", () => {
    const original = new Uint8Array([72, 101, 108, 108, 111]); // "Hello"
    const b64 = bytesToBase64(original);
    const restored = base64ToBytes(b64);
    assert.deepEqual(restored, original);
  });

  // contract-test: infrastructure
  it("roundtrips for 32-byte key-size buffer", () => {
    const key = new Uint8Array(32).fill(0xab);
    const b64 = bytesToBase64(key);
    const restored = base64ToBytes(b64);
    assert.deepEqual(restored, key);
  });

  // contract-test: infrastructure
  it("bytesToBase64 produces standard base64 (no URL encoding)", () => {
    const bytes = new Uint8Array([0xfb, 0xff, 0xfe]); // produces +/
    const b64 = bytesToBase64(bytes);
    // Standard base64 uses + and /, not - and _
    assert.ok(!b64.includes("-"), "should not contain URL-safe '-'");
    assert.ok(!b64.includes("_"), "should not contain URL-safe '_'");
  });
});

describe("deriveEmailEncryptionKeyB64", () => {
  // contract-test: supporting surface=cli assertions=auth.signup.current-flow
  it("derives SHA-256(email + salt) as base64", async () => {
    const salt = new Uint8Array([1, 2, 3, 4]);
    const derived = await deriveEmailEncryptionKeyB64(
      "user@example.com",
      bytesToBase64(salt),
    );
    assert.strictEqual(derived, "iL9MLsZR1cIgat2zQ1t2dfBf0/PdIXlYzN3PK5TxGoE=");
  });
});

describe("signup crypto material", () => {
  // contract-test: supporting surface=cli assertions=auth.password.versioned-protection
  it("matches an independent Argon2id v2 password vector", async () => {
    const salt = Uint8Array.from({ length: 16 }, (_, index) => index);
    assert.deepEqual(PASSWORD_KDF_V2, {
      version: 2, algorithm: "argon2id", memoryKiB: 65_536,
      iterations: 3, parallelism: 1, hashLength: 32,
    });
    assert.equal(
      Buffer.from(await derivePasswordMaterialV2("correct horse battery staple", salt)).toString("hex"),
      "0d1a3c6523c8f06e4e0af9c515aa5b5448cfebd6838f2d52c3d8b6ef8ddc3c2e",
    );
    await assert.rejects(derivePasswordMaterialV2("password", new Uint8Array(8)), /at least 16 salt bytes/);
  });

  // contract-test: supporting surface=cli assertions=auth.password.versioned-protection
  it("domain-separates v2 authentication and wrapping keys across clients", async () => {
    const { authKey, wrapKey } = await derivePasswordKeysV2(
      "Correct Horse Battery Staple!",
      Uint8Array.from({ length: 16 }, (_, index) => index),
    );
    const b64url = (value: Uint8Array) => Buffer.from(value).toString("base64url");
    assert.equal(b64url(authKey), "vH4NzewPmDGymGUgH11VasH-0clzgc98FEOnn6SEB5o");
    assert.equal(b64url(wrapKey), "d8EIpdqJ7JF5dhaA6xIcpQJTNu9kZGZimmu--sR-2Hc");
    assert.notDeepEqual(authKey, wrapKey);
    assert.equal(
      passwordProofV2(authKey, "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8", "login"),
      "4BZxiDKNYrtneUG0v46ZS8a65q64y1AsHKXpgB9XwO0",
    );
  });

  // contract-test: supporting surface=cli assertions=auth.signup.current-flow
  it("hashEmail matches SHA-256 base64 contract", async () => {
    assert.strictEqual(
      await hashEmail("user@example.com"),
      "tMmiiTI7IaAcPpQPFQ65uMVCWH8av9jw4cwf/F5HVRQ=",
    );
  });

  // contract-test: supporting surface=cli assertions=auth.signup.current-flow
  it("hashKey combines key and salt like the web signup flow", async () => {
    const salt = new Uint8Array([1, 2, 3, 4]);
    assert.strictEqual(
      await hashKey("correct horse", salt),
      "0hJvnJrn389Ik7M3OR+qOZl6NBsSet72zG2p4yy6GwE=",
    );
  });

  // contract-test: supporting surface=cli assertions=auth.signup.current-flow,auth.password.versioned-protection
  it("creates versioned password signup payload material", async () => {
    const material = await createSignupCryptoMaterial("USER@example.com", "correct horse battery staple");

    assert.strictEqual(material.hashedEmail, await hashEmail("user@example.com"));
    assert.strictEqual(material.emailEncryptionKeyB64, await deriveEmailEncryptionKeyB64("user@example.com", material.userEmailSaltB64));
    assert.strictEqual(material.credentialVersion, 2);
    assert.strictEqual(material.saltB64, material.userEmailSaltB64);
    assert.match(material.passwordAuthKey, /^[A-Za-z0-9_-]{43}$/);
    assert.strictEqual(base64ToBytes(material.masterKeyB64).length, 32);
    assert.ok(base64ToBytes(material.encryptedEmail).length > 24);
    assert.ok(base64ToBytes(material.encryptedMasterKey).length > 32);
    assert.strictEqual(base64ToBytes(material.keyIv).length, 12);
    assert.deepEqual(await unwrapPasswordMasterKey({
      password: "correct horse battery staple",
      credentialVersion: 2,
      encryptedMasterKeyB64: material.encryptedMasterKey,
      saltB64: material.saltB64,
      keyIvB64: material.keyIv,
    }), base64ToBytes(material.masterKeyB64));
    assert.equal(await unwrapPasswordMasterKey({
      password: "wrong password",
      credentialVersion: 2,
      encryptedMasterKeyB64: material.encryptedMasterKey,
      saltB64: material.saltB64,
      keyIvB64: material.keyIv,
    }), null);
    assert.equal(await unwrapPasswordMasterKey({
      password: "correct horse battery staple",
      credentialVersion: 3,
      encryptedMasterKeyB64: material.encryptedMasterKey,
      saltB64: material.saltB64,
      keyIvB64: material.keyIv,
    }), null);
  });

  // contract-test: supporting surface=cli assertions=auth.password.versioned-protection
  it("opens a legacy PBKDF2 wrapper when the credential version is absent", async () => {
    const password = "legacy password";
    const masterKey = randomBytes(32);
    const salt = randomBytes(16);
    const iv = randomBytes(12);
    const wrappingKey = await deriveKeyFromPassword(password, salt);
    const cipher = createCipheriv("aes-256-gcm", wrappingKey, iv);
    const encrypted = Buffer.concat([cipher.update(masterKey), cipher.final(), cipher.getAuthTag()]);
    const wrapper = {
      password,
      encryptedMasterKeyB64: encrypted.toString("base64"),
      saltB64: salt.toString("base64"),
      keyIvB64: iv.toString("base64"),
    };
    assert.deepEqual(await unwrapPasswordMasterKey(wrapper), new Uint8Array(masterKey));
    assert.deepEqual(await unwrapPasswordMasterKey({ ...wrapper, credentialVersion: 1 }), new Uint8Array(masterKey));
    assert.equal(await unwrapPasswordMasterKey({ ...wrapper, password: "incorrect" }), null);
  });

  // contract-test: supporting surface=cli assertions=auth.password.versioned-protection,auth.keys.independent-unlock
  it("rewraps the same master key for a legacy password migration", async () => {
    const masterKey = new Uint8Array(32).fill(17);
    const userEmailSalt = Uint8Array.from({ length: 16 }, (_, index) => index);
    const material = await createPasswordMigrationMaterialV2(
      "Correct Horse Battery Staple!", bytesToBase64(masterKey), bytesToBase64(userEmailSalt),
    );
    assert.equal(material.oldLookupHash, await hashKey("Correct Horse Battery Staple!", userEmailSalt));
    assert.equal(material.passwordAuthKey, "vH4NzewPmDGymGUgH11VasH-0clzgc98FEOnn6SEB5o");
    const { wrapKey } = await derivePasswordKeysV2("Correct Horse Battery Staple!", userEmailSalt);
    const ciphertext = Buffer.from(material.encryptedMasterKey, "base64");
    const decipher = createDecipheriv("aes-256-gcm", wrapKey, Buffer.from(material.keyIv, "base64"));
    decipher.setAuthTag(ciphertext.subarray(-16));
    assert.deepEqual(
      Buffer.concat([decipher.update(ciphertext.subarray(0, -16)), decipher.final()]),
      Buffer.from(masterKey),
    );
  });

  // contract-test: supporting surface=cli assertions=auth.signup.current-flow
  it("creates recovery key material that wraps the existing master key", async () => {
    const signup = await createSignupCryptoMaterial("user@example.com", "password");
    const recovery = await createRecoveryKeyMaterial(signup.masterKeyB64, signup.userEmailSaltB64);

    assert.match(recovery.recoveryKey, /^(?=.*[A-Z])(?=.*[a-z])(?=.*[2-9])(?=.*[#\-=+_&%$])[^0O]{24}$/);
    assert.strictEqual(recovery.lookupHash, await hashKey(recovery.recoveryKey, base64ToBytes(signup.userEmailSaltB64)));
    assert.ok(base64ToBytes(recovery.wrappedMasterKey).length > 32);
    assert.strictEqual(base64ToBytes(recovery.keyIv).length, 12);
  });

  // contract-test: direct surface=cli assertions=sdk.auth.credential-separation
  it("creates web-compatible API key material without exposing plaintext fields", async () => {
    const signup = await createSignupCryptoMaterial("user@example.com", "password");
    const material = await createApiKeyCryptoMaterial("SDK live test", signup.masterKeyB64);

    assert.match(material.apiKey, /^sk-api-[A-NP-Za-z1-9]{32}\.[A-NP-Za-z1-9]{32}$/);
    assert.equal(material.apiKeyHash, createHash("sha256").update(material.apiKey.split(".")[0]).digest("hex"));
    assert.match(material.apiKeyHash, /^[a-f0-9]{64}$/);
    assert.ok(base64ToBytes(material.encryptedName).length > 12);
    assert.ok(base64ToBytes(material.encryptedKeyPrefix).length > 12);
    assert.ok(base64ToBytes(material.encryptedMasterKey).length > 32);
    assert.strictEqual(base64ToBytes(material.keyIv).length, 12);
    assert.strictEqual(base64ToBytes(material.saltB64).length, 16);
  });
});

// ---------------------------------------------------------------------------
// AES-GCM encrypt / decrypt roundtrip
// ---------------------------------------------------------------------------

describe("encryptWithAesGcmCombined / decryptWithAesGcmCombined", () => {
  // contract-test: infrastructure
  it("encrypts and decrypts back to the same plaintext", async () => {
    const key = new Uint8Array(32).fill(0x42);
    const plaintext = "Hello, OpenMates!";

    const encrypted = await encryptWithAesGcmCombined(plaintext, key);
    const decrypted = await decryptWithAesGcmCombined(encrypted, key);

    assert.strictEqual(decrypted, plaintext);
  });

  // contract-test: infrastructure
  it("produces different ciphertexts for the same input (random IV)", async () => {
    const key = new Uint8Array(32).fill(0x42);
    const plaintext = "Same plaintext";

    const c1 = await encryptWithAesGcmCombined(plaintext, key);
    const c2 = await encryptWithAesGcmCombined(plaintext, key);

    assert.notStrictEqual(c1, c2, "two encryptions should differ (random IV)");
  });

  // contract-test: infrastructure
  it("returns null when decrypting with the wrong key", async () => {
    const key1 = new Uint8Array(32).fill(0x11);
    const key2 = new Uint8Array(32).fill(0x22);
    const encrypted = await encryptWithAesGcmCombined("secret", key1);
    const result = await decryptWithAesGcmCombined(encrypted, key2);
    assert.strictEqual(result, null);
  });

  // contract-test: infrastructure
  it("returns null for empty / too-short input", async () => {
    const key = new Uint8Array(32).fill(0x42);
    // An empty base64 string decodes to 0 bytes — must fail gracefully
    const result = await decryptWithAesGcmCombined("", key);
    assert.strictEqual(result, null);
  });

  // contract-test: infrastructure
  it("handles unicode plaintext (emoji)", async () => {
    const key = new Uint8Array(32).fill(0x77);
    const plaintext = "🚀 OpenMates 日本語";
    const encrypted = await encryptWithAesGcmCombined(plaintext, key);
    const decrypted = await decryptWithAesGcmCombined(encrypted, key);
    assert.strictEqual(decrypted, plaintext);
  });

  // contract-test: infrastructure
  it("handles JSON payloads (memory-like structure)", async () => {
    const key = new Uint8Array(32).fill(0x55);
    const payload = {
      name: "Python",
      proficiency: "advanced",
      settings_group: "code",
      _original_item_key: "preferred_tech",
      added_date: 1710000000,
    };
    const plaintext = JSON.stringify(payload);
    const encrypted = await encryptWithAesGcmCombined(plaintext, key);
    const decrypted = await decryptWithAesGcmCombined(encrypted, key);
    assert.strictEqual(decrypted, plaintext);
    const parsed = JSON.parse(decrypted!);
    assert.strictEqual(parsed.name, "Python");
    assert.strictEqual(parsed._original_item_key, "preferred_tech");
  });

  // contract-test: infrastructure
  it("combined format starts with 12-byte IV followed by ciphertext", async () => {
    const key = new Uint8Array(32).fill(0x33);
    const plaintext = "test";
    const encrypted = await encryptWithAesGcmCombined(plaintext, key);
    const bytes = base64ToBytes(encrypted);
    // Minimum: 12 IV + 4 data + 16 GCM auth tag = 32 bytes
    assert.ok(bytes.length >= 32, `combined blob too short: ${bytes.length}`);
  });
});

// ---------------------------------------------------------------------------
// encryptBytesWithAesGcm / decryptBytesWithAesGcm roundtrip (chat key wrapping)
// ---------------------------------------------------------------------------

describe("encryptBytesWithAesGcm / decryptBytesWithAesGcm", () => {
  // contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted
  it("roundtrips a 32-byte chat key through master-key wrapping", async () => {
    const masterKey = new Uint8Array(32).fill(0xaa);
    const chatKey = new Uint8Array(32);
    // Fill with a recognizable pattern
    for (let i = 0; i < 32; i++) chatKey[i] = i;

    const encrypted = await encryptBytesWithAesGcm(chatKey, masterKey);
    const decrypted = await decryptBytesWithAesGcm(encrypted, masterKey);

    assert.ok(decrypted, "decryption should succeed");
    assert.deepEqual(decrypted, chatKey, "roundtrip must preserve exact bytes");
  });

  // contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted
  it("returns null when decrypting with wrong master key", async () => {
    const masterKey1 = new Uint8Array(32).fill(0x11);
    const masterKey2 = new Uint8Array(32).fill(0x22);
    const chatKey = new Uint8Array(32).fill(0xff);

    const encrypted = await encryptBytesWithAesGcm(chatKey, masterKey1);
    const result = await decryptBytesWithAesGcm(encrypted, masterKey2);
    assert.strictEqual(result, null, "wrong key should return null");
  });

  // contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted
  it("produces different ciphertexts for the same key (random IV)", async () => {
    const masterKey = new Uint8Array(32).fill(0xbb);
    const chatKey = new Uint8Array(32).fill(0xcc);

    const c1 = await encryptBytesWithAesGcm(chatKey, masterKey);
    const c2 = await encryptBytesWithAesGcm(chatKey, masterKey);
    assert.notStrictEqual(c1, c2, "random IV should make ciphertexts differ");
  });
});

describe("deriveEmbedKeyFromChatKey", () => {
  // contract-test: infrastructure
  it("matches the browser HKDF embed-key derivation contract", async () => {
    const chatKey = new Uint8Array(32).fill(7);
    const key = await deriveEmbedKeyFromChatKey(chatKey, "embed-123");
    const repeated = await deriveEmbedKeyFromChatKey(chatKey, "embed-123");
    const differentEmbed = await deriveEmbedKeyFromChatKey(chatKey, "embed-456");

    assert.equal(bytesToBase64(key), "C1aHZnpAOX6QQZR+wToF+2BU8m8ib8ZGOIcK+KLvLsA=");
    assert.deepEqual(repeated, key);
    assert.notDeepEqual(differentEmbed, key);
  });
});

// ---------------------------------------------------------------------------
// hashItemKey
// ---------------------------------------------------------------------------

describe("hashItemKey", () => {
  // contract-test: infrastructure
  it("returns exactly 32 hex characters", () => {
    const hash = hashItemKey("code", "preferred_tech");
    assert.strictEqual(hash.length, 32);
    assert.match(hash, /^[0-9a-f]{32}$/);
  });

  // contract-test: infrastructure
  it("different inputs produce different hashes", () => {
    const h1 = hashItemKey("code", "preferred_tech");
    const h2 = hashItemKey("code", "projects");
    const h3 = hashItemKey("books", "preferred_tech");
    assert.notStrictEqual(h1, h2);
    assert.notStrictEqual(h1, h3);
  });

  // contract-test: infrastructure
  it("same appId+itemKey in the same millisecond produces equal hashes", () => {
    // hashItemKey uses Date.now() — call twice within the same ms
    const t = Date.now();
    // Monkey-patch Date.now to return a fixed value
    const originalNow = Date.now;
    Date.now = () => t;
    try {
      const h1 = hashItemKey("ai", "communication_style");
      const h2 = hashItemKey("ai", "communication_style");
      assert.strictEqual(h1, h2, "same ms → same hash");
    } finally {
      Date.now = originalNow;
    }
  });

  // contract-test: infrastructure
  it("same appId+itemKey at different timestamps produces different hashes", () => {
    const originalNow = Date.now;
    let counter = 1000;
    Date.now = () => counter++;
    try {
      const h1 = hashItemKey("ai", "communication_style");
      const h2 = hashItemKey("ai", "communication_style");
      assert.notStrictEqual(h1, h2, "different ms → different hash");
    } finally {
      Date.now = originalNow;
    }
  });
});
