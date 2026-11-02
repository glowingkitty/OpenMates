// contract-test-file: tooling
// Offline producer for tests/crypto_fixtures/ts_web_formats.json.
// Runs the ACTUAL web TypeScript encryption modules (transpiled with the installed
// TypeScript, no bundler) against synthetic keys and a deterministic RNG, then
// checks every ciphertext with the same TS reader before writing the fixture.
// No account, network, IndexedDB or production key material is involved.
// Usage (from repo root): node packages/openmates-rust/tests/crypto_fixtures/ts_web_formats/generate.cjs
"use strict";
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const { createRequire } = require("node:module"), { webcrypto, createHash, createCipheriv } = require("node:crypto");

const root = path.resolve(__dirname, "../../../../..");
const uiDir = path.join(root, "frontend/packages/ui/src");
const nodeRequire = createRequire(path.join(root, "frontend/packages/ui/package.json"));
const ts = nodeRequire("typescript");
const OUT = path.join(__dirname, "../ts_web_formats.json");
const FIXED_NOW_MS = 1_790_000_000_000;

// Deterministic synthetic RNG: SHA-256(counter) stream. Fixture-only.
let rngCounter = 0;
function fillRandom(bytes) {
  let offset = 0;
  while (offset < bytes.length) {
    const block = createHash("sha256").update(`openmates-ts-fixture-rng-${rngCounter++}`).digest();
    const take = Math.min(block.length, bytes.length - offset);
    bytes.set(block.subarray(0, take), offset);
    offset += take;
  }
  return bytes;
}
const sandboxCrypto = { subtle: webcrypto.subtle, getRandomValues: fillRandom };
const store = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), clear: () => m.clear() }; };
const sessionStorage = store(), localStorage = store();
class FixedDate extends Date { constructor(...a) { super(...(a.length ? a : [FIXED_NOW_MS])); } static now() { return FIXED_NOW_MS; } }
const silent = { log() {}, debug() {}, info() {}, warn() {}, error() {} };
const context = vm.createContext({
  crypto: sandboxCrypto, CryptoKey: globalThis.CryptoKey, Uint8Array, ArrayBuffer, DataView, TextEncoder, TextDecoder,
  URLSearchParams, atob, btoa, Date: FixedDate, Math, JSON, Promise, Error, TypeError, RangeError, Number, String, Object, Array, Map, Set, Symbol,
  console: silent, sessionStorage, localStorage, setTimeout, clearTimeout, setInterval, clearInterval,
  window: { atob, btoa, sessionStorage, localStorage, addEventListener() {}, removeEventListener() {} },
  document: { addEventListener() {}, removeEventListener() {} },
  navigator: {},
});

// Stubs replace only non-crypto platform dependencies.
let activeMaster = null;
let embedKeyForShare = null;
const stubs = {
  "./cryptoKeyStorage": { saveMasterKey: async () => {}, getMasterKey: async () => activeMaster, clearMasterKey: async () => {}, clearMasterKeyFromIndexedDB: async () => {}, deleteCryptoDatabase: async () => {} },
  "./ChatKeyManager": { chatKeyManager: { getProvenance: () => null, findCandidateKeyByFingerprint: async () => null, promoteCandidateKey() {} } },
  "$app/environment": { browser: true },
  "./embedStore": { embedStore: { getEmbedKey: async () => embedKeyForShare } },
  "tweetnacl": nodeRequire("tweetnacl"),
  "hash-wasm": nodeRequire("hash-wasm"),
};
const cache = new Map(), sources = {};
function load(rel) {
  const file = path.join(uiDir, rel);
  if (cache.has(file)) return cache.get(file).exports;
  let source = fs.readFileSync(file, "utf8");
  sources[path.relative(root, file)] = createHash("sha256").update(source).digest("hex");
  // CommonJS cannot parse import.meta; only buildShortUrl (no crypto) reads it.
  source = source.replace(/import\.meta/g, "({})");
  const out = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, reportDiagnostics: true });
  if (out.diagnostics.length) throw Error(`syntax:${rel}`);
  const mod = { exports: {} };
  cache.set(file, mod);
  const dir = path.dirname(rel);
  const req = (name) => {
    if (stubs[name]) return stubs[name];
    if (name.endsWith("/ChatKeyManager")) return stubs["./ChatKeyManager"];
    if (name.endsWith("/cryptoKeyStorage")) return stubs["./cryptoKeyStorage"];
    if (name.endsWith("/embedStore")) return stubs["./embedStore"];
    if (name.startsWith(".")) return load(path.join(dir, name) + ".ts");
    throw Error(`dependency:${name}`);
  };
  vm.runInContext(`(function(exports,require,module){${out.outputText}\n})`, context)(mod.exports, req, mod);
  return mod.exports;
}

const b64 = (bytes) => Buffer.from(bytes).toString("base64");
const bytesOf = (n, start) => new Uint8Array(Array.from({ length: n }, (_, i) => (start + i * 7) & 0xff));
const eq = (a, b) => Buffer.from(a).equals(Buffer.from(b));
const must = (cond, label) => { if (!cond) throw Error(`ts_reader_check_failed:${label}`); };

(async () => {
  const cs = load("services/cryptoService.ts");
  const msg = load("services/encryption/MessageEncryptor.ts");
  const meta = load("services/encryption/MetadataEncryptor.ts");
  const media = load("services/encryption/mediaEncryption.ts");
  const share = load("services/shareEncryption.ts");
  const embedShare = load("services/embedShareEncryption.ts");
  const shortUrl = load("services/shortUrlEncryption.ts");
  const pwv2 = load("services/passwordV2Core.ts");
  const hidden = load("services/hiddenChatService.ts").hiddenChatService;

  const masterRaw = bytesOf(32, 0x10), chatKey = bytesOf(32, 0x40), otherChatKey = bytesOf(32, 0x41);
  const parentEmbedKey = bytesOf(32, 0x70), childEmbedKey = bytesOf(32, 0x90), emailSalt = bytesOf(16, 0xa0), prf = bytesOf(32, 0xc0);
  const extractableMaster = await webcrypto.subtle.importKey("raw", masterRaw, "AES-GCM", true, ["encrypt", "decrypt"]);
  activeMaster = extractableMaster;
  localStorage.setItem("openmates_email_salt", b64(emailSalt));
  const fixture = {
    schema_version: 1,
    synthetic_only: true,
    provenance: "Produced by tests/crypto_fixtures/ts_web_formats/generate.cjs running the actual web TypeScript modules listed in ts_sources (sha256 of source at generation) with a deterministic SHA-256 RNG. Each ciphertext was re-read by the same TS reader before writing.",
    ts_sources: sources,
    keys: { master_b64: b64(masterRaw), chat_key_b64: b64(chatKey), other_chat_key_b64: b64(otherChatKey), parent_embed_key_b64: b64(parentEmbedKey), child_embed_key_b64: b64(childEmbedKey), email_salt_b64: b64(emailSalt), prf_b64: b64(prf) },
  };

  // 1. Chat-key message/metadata content: current OM header and legacy IV-prefixed.
  const texts = [["ascii", "Hello from the web client"], ["unicode", "Grüße 👋 — 日本語 \u0000 tail"], ["empty", ""], ["long", "x".repeat(4096) + "end"]];
  fixture.chat_content = [];
  for (const [label, plaintext] of texts) {
    const om = await msg.encryptWithChatKey(plaintext, chatKey);
    must((await msg.decryptWithChatKey(om, chatKey)) === plaintext, `om:${label}`);
    must((await msg.decryptWithChatKey(om, otherChatKey)) === null, `om-wrong:${label}`);
    // Pre-header deployed writer layout (base64(IV||ct||tag)); same AES-GCM call as wrapEmbedKeyWithChatKey.
    const legacy = await meta.wrapEmbedKeyWithChatKey(new TextEncoder().encode(plaintext), chatKey);
    must((await msg.decryptWithChatKey(legacy, chatKey)) === plaintext, `legacy:${label}`);
    fixture.chat_content.push({ label, layout: "om-fnv", plaintext, ciphertext: om });
    fixture.chat_content.push({ label, layout: "legacy-iv", plaintext, ciphertext: legacy });
  }
  const arr = [{ type: "text", text: "hi" }, 3, null];
  const arrayCt = await msg.encryptArrayWithChatKey(arr, chatKey);
  must(JSON.stringify(await msg.decryptArrayWithChatKey(arrayCt, chatKey)) === JSON.stringify(arr), "array");
  fixture.chat_content.push({ label: "json-array", layout: "om-fnv", plaintext: JSON.stringify(arr), ciphertext: arrayCt });
  const highlight = { start: 1, end: 9, note: "ü" };
  const highlightCt = await msg.encryptHighlightPayload(highlight, chatKey);
  must(JSON.stringify(await msg.decryptHighlightPayload(highlightCt, chatKey)) === JSON.stringify(highlight), "highlight");
  fixture.chat_content.push({ label: "highlight", layout: "om-fnv", plaintext: JSON.stringify(highlight), ciphertext: highlightCt });
  fixture.chat_content_other_key = await msg.encryptWithChatKey("other key", otherChatKey);

  // 2. Format D master-key text (drafts, titles, memories/settings, suggestions).
  fixture.master_text = [];
  for (const [label, plaintext] of [["draft-markdown", "# Draft\n\n- [ ] item ✓"], ["memory-json", JSON.stringify({ name: "Ada", likes: ["tea"] })], ["empty", ""]]) {
    const ct = await meta.encryptWithMasterKeyDirect(plaintext, extractableMaster);
    must((await meta.decryptWithMasterKeyDirect(ct, extractableMaster)) === plaintext, `D:${label}`);
    fixture.master_text.push({ label, plaintext, ciphertext: ct });
  }

  // 3. Format C chat-key wrapper and embed key wrappers.
  const formatC = await meta.encryptChatKeyWithMasterKey(chatKey);
  must(eq(await meta.decryptChatKeyWithMasterKey(formatC, extractableMaster), chatKey), "C");
  const embedId = "6f1c2d3e-4b5a-4c6d-8e7f-9a0b1c2d3e4f";
  const derivedEmbed = await meta.deriveEmbedKeyFromChatKey(chatKey, embedId);
  const embedMaster = await meta.wrapEmbedKeyWithMasterKey(derivedEmbed);
  must(eq(await meta.unwrapEmbedKeyWithMasterKey(embedMaster), derivedEmbed), "embed-master");
  const embedChat = await meta.wrapEmbedKeyWithChatKey(derivedEmbed, chatKey);
  must(eq(await meta.unwrapEmbedKeyWithChatKey(embedChat, chatKey), derivedEmbed), "embed-chat");
  const child = await meta.wrapEmbedKeyWithChatKey(childEmbedKey, parentEmbedKey);
  must(eq(await meta.unwrapEmbedKeyWithEmbedKey(child, parentEmbedKey), childEmbedKey), "embed-child");
  const embedContent = JSON.stringify({ type: "web-website", url: "https://example.org/ü", status: "finished" });
  const embedCt = await meta.encryptWithEmbedKey(embedContent, derivedEmbed);
  must((await meta.decryptWithEmbedKey(embedCt, derivedEmbed)) === embedContent, "embed-content");
  const aad = "task_activity_comment:task-1:entry-1:v1";
  const aadCt = await meta.encryptWithEmbedKey("comment ✓", parentEmbedKey, aad);
  must((await meta.decryptWithEmbedKey(aadCt, parentEmbedKey, { associatedData: aad })) === "comment ✓", "aad");
  must((await meta.decryptWithEmbedKey(aadCt, parentEmbedKey, {})) === null, "aad-missing");
  fixture.wrappers = {
    chat_key_master_format_c: formatC,
    embed_id: embedId, derived_embed_key_b64: b64(derivedEmbed),
    embed_key_master: embedMaster, embed_key_chat: embedChat, child_embed_key_parent: child,
    embed_content: { plaintext: embedContent, ciphertext: embedCt },
    embed_content_aad: { plaintext: "comment ✓", aad, key: "parent_embed_key_b64", ciphertext: aadCt },
  };

  // 4. Master-key wrapping: password v1 (PBKDF2), recovery key, passkey PRF, password v2.
  const wrapWith = async (wrappingKey) => { const r = await cs.encryptKey(extractableMaster, wrappingKey); const back = await cs.decryptKey(r.wrapped, r.iv, wrappingKey); must(back && eq(new Uint8Array(await webcrypto.subtle.exportKey("raw", back)), masterRaw), "decryptKey"); return r; };
  const loginSalt = bytesOf(16, 0x33);
  fixture.master_wrapping = [];
  const recoveryKey = cs.generateSecureRecoveryKey(24);
  for (const [label, secret] of [["password-v1-ascii", "correct horse battery"], ["password-v1-unicode", "pässwörd 🔐"], ["recovery-key", recoveryKey]]) {
    const wrap = await cs.deriveKeyFromPassword(secret, loginSalt);
    const r = await wrapWith(wrap);
    fixture.master_wrapping.push({ label, kind: "pbkdf2", secret, salt_b64: b64(loginSalt), ciphertext: r.wrapped, iv: r.iv });
  }
  const prfWrap = await cs.deriveWrappingKeyFromPRF(prf, emailSalt);
  const prfR = await wrapWith(prfWrap);
  fixture.master_wrapping.push({ label: "passkey-prf", kind: "prf", prf_b64: b64(prf), email_salt_b64: b64(emailSalt), wrapping_key_b64: b64(prfWrap), ciphertext: prfR.wrapped, iv: prfR.iv });
  const v2 = await pwv2.derivePasswordV2Direct("pässwörd v2", emailSalt);
  const v2R = await wrapWith(v2.wrapKey);
  fixture.master_wrapping.push({ label: "password-v2", kind: "argon2id-v2", secret: "pässwörd v2", salt_b64: b64(emailSalt), auth_key_b64: b64(v2.authKey), wrap_key_b64: b64(v2.wrapKey), ciphertext: v2R.wrapped, iv: v2R.iv });

  // 5. Share links: chat key blob, embed key blob, short URL.
  const chatId = "0d9f1a2b-3c4d-4e5f-8a9b-0c1d2e3f4a5b";
  const nowS = Math.floor(FIXED_NOW_MS / 1000);
  fixture.share = { chat_id: chatId, generated_at: nowS, chat: [], embed: [], short_url: null };
  for (const [label, duration, password] of [["no-password-forever", 0, undefined], ["password-1day", 86400, "share pw ü"]]) {
    const blob = await share.generateShareKeyBlob(chatId, b64(chatKey), duration, password);
    const ok = await share.decryptShareKeyBlob(chatId, blob, nowS + 10, password);
    must(ok.success && ok.chatEncryptionKey === b64(chatKey), `share:${label}`);
    if (duration) must((await share.decryptShareKeyBlob(chatId, blob, nowS + duration + 1, password)).error === "expired", "share-expired");
    if (password) {
      must((await share.decryptShareKeyBlob(chatId, blob, nowS, undefined)).error === "password_required", "share-pw-req");
      must((await share.decryptShareKeyBlob(chatId, blob, nowS, "wrong")).error === "invalid_password", "share-pw-bad");
    }
    fixture.share.chat.push({ label, duration_seconds: duration, password: password ?? null, blob });
  }
  embedKeyForShare = derivedEmbed;
  for (const [label, duration, password] of [["no-password-forever", 0, undefined], ["password-1week", 604800, "embed pw"]]) {
    const blob = await embedShare.generateEmbedShareKeyBlob(embedId, duration, password);
    const ok = await embedShare.decryptEmbedShareKeyBlob(embedId, blob, nowS + 10, password);
    must(ok.success && eq(ok.embedKey, derivedEmbed), `embed-share:${label}`);
    if (password) must((await embedShare.decryptEmbedShareKeyBlob(embedId, blob, nowS, undefined)).error === "password_required", "embed-pw-req");
    fixture.share.embed.push({ label, duration_seconds: duration, password: password ?? null, blob });
  }
  const parts = shortUrl.generateShortUrlParts();
  const fullUrl = `https://openmates.org/share/chat/${chatId}#key=abc-_123`;
  const encUrl = await shortUrl.encryptShareUrl(fullUrl, parts.token, parts.shortKey);
  must((await shortUrl.decryptShareUrl(encUrl, parts.token, parts.shortKey)) === fullUrl, "short-url");
  fixture.share.short_url = { token: parts.token, short_key: parts.shortKey, url: fullUrl, encrypted: encUrl };

  // 6. Hidden chats: chat key wrapped by PBKDF2(base64(master||code), email_salt[0:16]).
  const code = "4821abcd";
  const hiddenWrapped = await hidden.encryptChatKeyWithCode(chatKey, code);
  must(hiddenWrapped, "hidden-wrap");
  must((await meta.decryptChatKeyWithMasterKey(hiddenWrapped, extractableMaster)) === null, "hidden-not-master");
  hidden.combinedSecret = await hidden.deriveCombinedSecret(code);
  must(eq(await hidden.decryptChatKeyWithCombinedSecret(hiddenWrapped), chatKey), "hidden-read");
  fixture.hidden_chat = { code, email_salt_b64: b64(emailSalt), combined_secret_b64: b64(hidden.combinedSecret), encrypted_chat_key: hiddenWrapped };

  // 7. Media payloads (server-produced bytes; TS decryptMediaPayload is the reader).
  const mediaKey = bytesOf(32, 0x55), mediaPlain = Buffer.from("\x89PNG synthetic media bytes ✓");
  const gcm = (nonce) => { const c = createCipheriv("aes-256-gcm", mediaKey, nonce); return Buffer.concat([c.update(mediaPlain), c.final(), c.getAuthTag()]); };
  const nonce = Buffer.from(fillRandom(new Uint8Array(12)));
  const sealed = gcm(nonce);
  const prefixed = Buffer.concat([nonce, sealed]);
  const cases = [
    { label: "v2-marker-prefixed", data: prefixed, variant: { encryption: "aes-gcm-nonce-prefixed-v1" }, legacy_nonce: null },
    { label: "legacy-variant-nonce", data: sealed, variant: { aes_nonce: nonce.toString("base64") }, legacy_nonce: null },
    { label: "legacy-arg-nonce-urlsafe", data: sealed, variant: {}, legacy_nonce: nonce.toString("base64url") },
    { label: "legacy-empty-nonce-prefixed", data: prefixed, variant: {}, legacy_nonce: "" },
  ];
  fixture.media = { key_b64: b64(mediaKey), plaintext_b64: mediaPlain.toString("base64"), cases: [] };
  for (const c of cases) {
    const ab = c.data.buffer.slice(c.data.byteOffset, c.data.byteOffset + c.data.byteLength);
    const out = await media.decryptMediaPayload({ encryptedData: ab, aesKeyBase64: b64(mediaKey), variant: c.variant, legacyNonceBase64: c.legacy_nonce });
    must(eq(new Uint8Array(out), mediaPlain), `media:${c.label}`);
    fixture.media.cases.push({ label: c.label, data_b64: c.data.toString("base64"), encryption: c.variant.encryption ?? null, aes_nonce: c.variant.aes_nonce ?? null, legacy_nonce: c.legacy_nonce });
  }
  let rejected = false;
  try { await media.decryptMediaPayload({ encryptedData: prefixed.buffer.slice(prefixed.byteOffset, prefixed.byteOffset + prefixed.length), aesKeyBase64: b64(mediaKey), variant: { encryption: "future-v9" }, legacyNonceBase64: null }); } catch { rejected = true; }
  must(rejected, "media-unknown-marker");
  rejected = false;
  try { await media.decryptMediaPayload({ encryptedData: sealed.buffer.slice(sealed.byteOffset, sealed.byteOffset + sealed.length), aesKeyBase64: b64(mediaKey), variant: {}, legacyNonceBase64: null }); } catch { rejected = true; }
  must(rejected, "media-missing-nonce");

  fs.writeFileSync(OUT, JSON.stringify(fixture, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ status: "passed", out: path.relative(root, OUT), sources: Object.keys(sources).length }) + "\n");
})().catch((error) => { console.error(error); process.exitCode = 1; });
