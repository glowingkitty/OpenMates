// contract-test-file: tooling
// Regenerates fixtures/sdk-api-key-memories.json from the actual npm SDK crypto
// helpers (synthetic key and plaintext only). Run from the repository root:
//   node --experimental-strip-types tests/sdk-conformance/generate_sdk_api_key_memories.mjs [--verify <b64> <expected>]
import { writeFileSync } from "node:fs";
import { decryptWithAesGcmCombined, encryptBytesWithAesGcm, encryptWithAesGcmCombined, hashItemKey } from "../../frontend/packages/openmates-cli/src/crypto.ts";

const key = Uint8Array.from({ length: 32 }, (_, i) => (i * 7 + 1) & 0xff);
const chatKey = Uint8Array.from({ length: 32 }, (_, i) => (i * 11 + 5) & 0xff);
const b64 = (bytes) => Buffer.from(bytes).toString("base64");

if (process.argv[2] === "--verify") {
  const plain = await decryptWithAesGcmCombined(process.argv[3], key);
  process.exit(plain === process.argv[4] ? 0 : 1);
}

const plaintexts = {
  structured_unicode: JSON.stringify({ title: "Dune 界", settings_group: "books", _original_item_key: "favorite_books", added_date: 1700000000 }),
  ideabucket_settings: JSON.stringify({ processing_prompt: "Process my ideas", processing_times: "09:00,17:30", settings_group: "ideabucket", _original_item_key: "processing_settings", added_date: 1700000001 }),
  plain_string: "not json at all",
};
const vectors = [];
for (const [name, plaintext] of Object.entries(plaintexts)) {
  vectors.push({ name, plaintext, ciphertext: await encryptWithAesGcmCombined(plaintext, key) });
}
const realNow = Date.now;
Date.now = () => 1700000000123;
const hashes = [["books", "favorite_books"], ["ideabucket", "processing_settings"]].map(([app, type]) => ({ app, type, millis: 1700000000123, hash: hashItemKey(app, type) }));
Date.now = realNow;
const fixture = {
  schema: "sdk-api-key-memories.v1",
  master_key_b64: b64(key),
  chat_key_b64: b64(chatKey),
  vectors,
  hashes,
  wrapped_chat_key: await encryptBytesWithAesGcm(chatKey, key),
};
writeFileSync(new URL("./fixtures/sdk-api-key-memories.json", import.meta.url), JSON.stringify(fixture, null, 2) + "\n");
