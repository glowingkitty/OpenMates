// contract-test-file: supporting surface=cli assertions=chats.persistence.client-encrypted
import assert from "node:assert/strict";
import { webcrypto, randomBytes } from "node:crypto";
import { it, mock } from "node:test";

import {
  base64ToBytes,
  bytesToBase64,
  createAesGcmCombinedDecryptor,
  decryptWithAesGcmCombined,
  encryptWithAesGcmCombined,
} from "../src/crypto.ts";

// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted
it("decrypts legacy and OM combined fields with one nonextractable import per operation", async () => {
  const key = new Uint8Array(32).fill(0x41);
  const plaintexts = ["first", "résumé 🚀", ""];
  const encrypted = await Promise.all(plaintexts.map((value) => encryptWithAesGcmCombined(value, key)));
  const legacyBytes = base64ToBytes(encrypted[0]);
  const om = bytesToBase64(new Uint8Array([0x4f, 0x4d, 1, 2, 3, 4, ...legacyBytes]));
  const subtle = (globalThis.crypto ?? webcrypto).subtle;
  const originalImport = subtle.importKey.bind(subtle);
  const imports: Array<{ extractable: boolean; usages: KeyUsage[] }> = [];
  const spy = mock.method(subtle, "importKey", async (...args: Parameters<typeof subtle.importKey>) => {
    imports.push({ extractable: args[3], usages: [...args[4]] });
    return originalImport(...args);
  });

  try {
    const decrypt = await createAesGcmCombinedDecryptor(key);
    assert.deepEqual(await Promise.all(encrypted.map((value) => decrypt(value))), plaintexts);
    assert.equal(await decrypt(om), plaintexts[0]);
    assert.deepEqual(imports, [{ extractable: false, usages: ["decrypt"] }]);
  } finally {
    spy.mock.restore();
  }
  assert.equal(await decryptWithAesGcmCombined(om, key), plaintexts[0]);
});

// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted
it("preserves null results for tamper, wrong key, malformed ciphertext and AAD mismatch", async () => {
  const key = new Uint8Array(32).fill(0x51);
  const wrongKey = new Uint8Array(32).fill(0x52);
  const aad = "chat-id:é";
  const encrypted = await encryptWithAesGcmCombined("bound value", key, aad);
  const tampered = base64ToBytes(encrypted);
  tampered[tampered.length - 1] ^= 1;
  const decrypt = await createAesGcmCombinedDecryptor(key);
  const wrongDecrypt = await createAesGcmCombinedDecryptor(wrongKey);

  assert.equal(await decrypt(encrypted, aad), "bound value");
  for (const [ciphertext, associatedData] of [
    [encrypted, undefined],
    [encrypted, "wrong"],
    [bytesToBase64(tampered), aad],
    [bytesToBase64(new Uint8Array(12)), aad],
  ] as const) {
    assert.equal(await decrypt(ciphertext, associatedData), null);
    assert.equal(await decryptWithAesGcmCombined(ciphertext, key, associatedData), null);
  }
  assert.equal(await wrongDecrypt(encrypted, aad), null);
  assert.equal(await decryptWithAesGcmCombined(encrypted, wrongKey, aad), null);
});

// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted
it("returns null for invalid AES key length in both decrypt APIs", async () => {
  const validKey = new Uint8Array(32).fill(0x61);
  const invalidKey = new Uint8Array(7);
  const ciphertext = await encryptWithAesGcmCombined("secret", validKey);
  const decrypt = await createAesGcmCombinedDecryptor(invalidKey);
  assert.equal(await decrypt(ciphertext), null);
  assert.equal(await decryptWithAesGcmCombined(ciphertext, invalidKey), null);
});

// contract-test: supporting surface=cli assertions=chats.completion.lease-fenced
it("batch chat decryptor authenticates each field and preserves associated-data binding", async () => {
  const key = randomBytes(32);
  const decrypt = await createAesGcmCombinedDecryptor(key);
  const plain = await encryptWithAesGcmCombined("message", key);
  const bound = await encryptWithAesGcmCombined("private metadata", key, "chat:one");
  assert.deepEqual(await Promise.all([decrypt(plain), decrypt(bound, "chat:one"), decrypt(bound, "chat:two"), decrypt("invalid")]),
    ["message", "private metadata", null, null]);
  const wrongKey = await createAesGcmCombinedDecryptor(randomBytes(32));
  assert.equal(await wrongKey(plain), null);
  const tagged = Buffer.concat([Buffer.from([0x4f, 0x4d, 0, 0, 0, 0]), Buffer.from(plain, "base64")]).toString("base64");
  assert.equal(await decrypt(tagged), "message");
});
