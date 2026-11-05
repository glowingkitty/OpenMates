// contract-test-file: tooling
// Offline producer for tests/crypto_fixtures/ts_hidden_chat_lifecycle.json.
// Runs the ACTUAL web hiddenChatService.ts + cryptoService.ts (transpiled with the
// installed TypeScript, no bundler) against synthetic keys, a deterministic RNG and
// a controllable clock: hide wrappers for boundary/non-ASCII codes, invalid codes,
// classification, unlock counting, unhide re-wrap and the rate-limit sequence.
// Only chatDB/chatSyncService are replaced by in-memory stubs; no account,
// network, IndexedDB or production key material is involved.
// Usage (from repo root): node packages/openmates-rust/tests/crypto_fixtures/ts_hidden_chat_lifecycle/generate.cjs
// Optional OPENMATES_FIXTURE_NODE_ROOT=<checkout with node_modules> for typescript/tweetnacl/hash-wasm.
"use strict";
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const { createRequire } = require("node:module"), { webcrypto, createHash } = require("node:crypto");

const root = path.resolve(__dirname, "../../../../..");
const uiDir = path.join(root, "frontend/packages/ui/src");
// Tooling packages may come from a checkout with installed node_modules (worktrees have none).
const toolingRoot = process.env.OPENMATES_FIXTURE_NODE_ROOT || root;
const nodeRequire = createRequire(path.join(toolingRoot, "frontend/packages/ui/package.json"));
const ts = nodeRequire("typescript");
const OUT = path.join(__dirname, "../ts_hidden_chat_lifecycle.json");
let nowMs = 1_790_000_000_000;

let rngCounter = 0;
function fillRandom(bytes) {
  let offset = 0;
  while (offset < bytes.length) {
    const block = createHash("sha256").update(`openmates-ts-hidden-fixture-rng-${rngCounter++}`).digest();
    const take = Math.min(block.length, bytes.length - offset);
    bytes.set(block.subarray(0, take), offset);
    offset += take;
  }
  return bytes;
}
const store = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), clear: () => m.clear() }; };
const sessionStorage = store(), localStorage = store();
class ClockDate extends Date { constructor(...a) { super(...(a.length ? a : [nowMs])); } static now() { return nowMs; } }
const silent = { log() {}, debug() {}, info() {}, warn() {}, error() {} };
const context = vm.createContext({
  crypto: { subtle: webcrypto.subtle, getRandomValues: fillRandom }, CryptoKey: globalThis.CryptoKey, Uint8Array, ArrayBuffer, DataView, TextEncoder, TextDecoder,
  URLSearchParams, atob, btoa, Date: ClockDate, Math, JSON, Promise, Error, TypeError, RangeError, Number, String, Object, Array, Map, Set, Symbol,
  console: silent, sessionStorage, localStorage, setTimeout, clearTimeout, setInterval, clearInterval,
  window: { atob, btoa, sessionStorage, localStorage, addEventListener() {}, removeEventListener() {} },
  document: { addEventListener() {}, removeEventListener() {} },
  navigator: {},
});

let activeMaster = null;
const chats = new Map();
const keyUpdates = [];
const stubs = {
  "./cryptoKeyStorage": { saveMasterKey: async () => {}, getMasterKey: async () => activeMaster, clearMasterKey: async () => {}, clearMasterKeyFromIndexedDB: async () => {}, deleteCryptoDatabase: async () => {} },
  "./ChatKeyManager": { chatKeyManager: { getProvenance: () => null, findCandidateKeyByFingerprint: async () => null, promoteCandidateKey() {} } },
  "$app/environment": { browser: true },
  "./db": { chatDB: { getAllChats: async () => [...chats.values()], getChat: async (id) => chats.get(id) ?? null, updateChat: async (c) => { chats.set(c.chat_id, c); }, clearChatKey() {}, clearAllChatKeys() {} } },
  "./chatSyncService": { chatSyncService: { sendUpdateEncryptedChatKey: async (id, key) => { keyUpdates.push({ id, key }); } } },
  "tweetnacl": nodeRequire("tweetnacl"),
  "hash-wasm": nodeRequire("hash-wasm"),
};
const cache = new Map(), sources = {};
function load(rel) {
  const file = path.join(uiDir, rel);
  if (cache.has(file)) return cache.get(file).exports;
  let source = fs.readFileSync(file, "utf8");
  sources[path.relative(root, file)] = createHash("sha256").update(source).digest("hex");
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
    if (name.startsWith(".")) return load(path.join(dir, name) + ".ts");
    throw Error(`dependency:${name}`);
  };
  vm.runInContext(`(function(exports,require,module){${out.outputText}\n})`, context)(mod.exports, req, mod);
  return mod.exports;
}

const b64 = (bytes) => Buffer.from(bytes).toString("base64");
const bytesOf = (n, start) => new Uint8Array(Array.from({ length: n }, (_, i) => (start + i * 7) & 0xff));
const eq = (a, b) => a !== null && b !== null && Buffer.from(a).equals(Buffer.from(b));
const must = (cond, label) => { if (!cond) throw Error(`ts_reader_check_failed:${label}`); };

(async () => {
  const cs = load("services/cryptoService.ts");
  const hidden = load("services/hiddenChatService.ts").hiddenChatService;
  const masterRaw = bytesOf(32, 0x13), emailSalt = bytesOf(24, 0xa3);
  const chatKey = bytesOf(32, 0x44), normalKey = bytesOf(32, 0x48), otherHiddenKey = bytesOf(32, 0x4c);
  activeMaster = await webcrypto.subtle.importKey("raw", masterRaw, "AES-GCM", true, ["encrypt", "decrypt"]);
  const resetSalt = () => { sessionStorage.removeItem("hidden_chat_salt"); localStorage.setItem("openmates_email_salt", b64(emailSalt)); };
  resetSalt();
  const fixture = {
    schema_version: 1,
    synthetic_only: true,
    provenance: "Produced by tests/crypto_fixtures/ts_hidden_chat_lifecycle/generate.cjs running the actual web TypeScript modules listed in ts_sources (sha256 of source at generation) with a deterministic SHA-256 RNG and controlled clock. Every wrapper was re-read by the same TS reader before writing.",
    ts_sources: sources,
    keys: { master_b64: b64(masterRaw), email_salt_b64: b64(emailSalt), chat_key_b64: b64(chatKey), normal_chat_key_b64: b64(normalKey), other_hidden_chat_key_b64: b64(otherHiddenKey) },
  };

  // 1. Hide wrappers across code lengths and scripts (length is UTF-16 units).
  const codes = [["min-ascii", "4821"], ["max-ascii", "a".repeat(30)], ["umlaut-emoji", "Grüße🔒"], ["astral-only-min", "🔒🔒"], ["cjk", "日本語コード"], ["max-astral", "🔒".repeat(15)]];
  fixture.codes = [];
  for (const [label, code] of codes) {
    const wrapped = await hidden.encryptChatKeyWithCode(chatKey, code);
    must(wrapped, `wrap:${label}`);
    must((await cs.decryptChatKeyWithMasterKey(wrapped)) === null, `not-master:${label}`);
    const secret = await hidden.deriveCombinedSecret(code);
    hidden.combinedSecret = secret;
    must(eq(await hidden.decryptChatKeyWithCombinedSecret(wrapped), chatKey), `read:${label}`);
    fixture.codes.push({ label, code, combined_secret_b64: b64(secret), encrypted_chat_key: wrapped });
    await hidden.lockHiddenChats();
  }
  fixture.invalid_codes = [];
  for (const code of ["abc", "a".repeat(31), "🔒a", "🔒".repeat(16), ""]) {
    must((await hidden.deriveCombinedSecret(code)) === null, `invalid:${code.length}`);
    fixture.invalid_codes.push(code);
  }

  // 2. Classification and unlock counting over a stored chat list.
  const code = "4821", otherCode = "9999";
  const hiddenWrapped = await hidden.encryptChatKeyWithCode(chatKey, code);
  const otherWrapped = await hidden.encryptChatKeyWithCode(otherHiddenKey, otherCode);
  const normalWrapped = await cs.encryptChatKeyWithMasterKey(normalKey);
  must(eq(await cs.decryptChatKeyWithMasterKey(normalWrapped), normalKey), "normal-read");
  chats.set("hidden-a", { chat_id: "hidden-a", encrypted_chat_key: hiddenWrapped });
  chats.set("hidden-b", { chat_id: "hidden-b", encrypted_chat_key: otherWrapped });
  chats.set("normal", { chat_id: "normal", encrypted_chat_key: normalWrapped });
  chats.set("empty", { chat_id: "empty", encrypted_chat_key: "" });
  const classify = async (wrapped) => {
    const r = await hidden.tryDecryptChatKey(wrapped);
    return r.chatKey ? { class: r.isHidden ? "hidden" : "normal", chat_key_b64: b64(r.chatKey) } : { class: "locked_candidate", chat_key_b64: null };
  };
  fixture.stored_chats = [...chats.values()].map((c) => ({ chat_id: c.chat_id, encrypted_chat_key: c.encrypted_chat_key }));
  fixture.locked_classification = [];
  for (const c of fixture.stored_chats.filter((c) => c.encrypted_chat_key)) fixture.locked_classification.push({ chat_id: c.chat_id, ...(await classify(c.encrypted_chat_key)) });
  const unlock = await hidden.unlockHiddenChats(code);
  must(unlock.success && unlock.decryptedCount === 1, "unlock-count");
  fixture.unlock = { code, decrypted_count: unlock.decryptedCount };
  fixture.unlocked_classification = [];
  for (const c of fixture.stored_chats.filter((c) => c.encrypted_chat_key)) fixture.unlocked_classification.push({ chat_id: c.chat_id, ...(await classify(c.encrypted_chat_key)) });
  must(fixture.unlocked_classification.find((c) => c.chat_id === "hidden-a").class === "hidden", "unlocked-hidden");
  const fresh = await hidden.encryptChatKeyWithCode(bytesOf(32, 0x50), "7777");
  await hidden.lockHiddenChats();
  const verified = await hidden.unlockHiddenChats("7777", fresh);
  must(verified.success && verified.decryptedCount === 1, "verified-fast-path");
  fixture.verified_unlock = { code: "7777", verified_encrypted_chat_key: fresh, decrypted_count: verified.decryptedCount };
  await hidden.lockHiddenChats();
  const none = await hidden.unlockHiddenChats("0000");
  must(none.success && none.decryptedCount === 0, "unlock-zero");
  fixture.zero_unlock = { code: "0000", decrypted_count: 0 };

  // 3. Unhide: combined-secret wrapper re-wrapped as master Format C.
  await hidden.lockHiddenChats();
  await hidden.unlockHiddenChats(code);
  must(await hidden.unhideChat("hidden-a"), "unhide");
  const rewrapped = chats.get("hidden-a").encrypted_chat_key;
  must(keyUpdates.length === 1 && keyUpdates[0].key === rewrapped, "unhide-sync");
  must(eq(await cs.decryptChatKeyWithMasterKey(rewrapped), chatKey), "unhide-master-read");
  fixture.unhide = { chat_id: "hidden-a", source_encrypted_chat_key: hiddenWrapped, encrypted_chat_key: rewrapped };
  await hidden.lockHiddenChats();

  // 4. Rate limit: replay of failures, lockout and expiry with the clock.
  hidden.failedAttempts = 0; hidden.lockoutUntil = null;
  const steps = [];
  const attempt = async (label, codeValue, setup) => {
    if (setup) setup();
    let outcome;
    try {
      const r = await hidden.unlockHiddenChats(codeValue);
      outcome = r.success ? "unlocked" : "failed";
    } catch { outcome = "locked_out"; }
    steps.push({ label, now_ms: nowMs, code: codeValue, salt_missing: localStorage.getItem("openmates_email_salt") === null, outcome, remaining_s: hidden.getRemainingLockoutTime(), is_unlocked: hidden.isUnlocked() });
    await hidden.lockHiddenChats();
  };
  await attempt("short-1", "ab");
  nowMs += 1000; await attempt("short-2", "abc");
  nowMs += 1000; await attempt("short-3-locks", "x");
  nowMs += 10_500; await attempt("during-lockout", code);
  nowMs += 18_000; await attempt("still-locked", code);
  nowMs += 1_000; await attempt("after-expiry", code);
  nowMs += 1_000; await attempt("salt-missing-counts-twice", code, () => { sessionStorage.removeItem("hidden_chat_salt"); localStorage.removeItem("openmates_email_salt"); });
  nowMs += 1_000; await attempt("short-after-salt-locks", "zz", resetSalt);
  nowMs += 30_000; await attempt("expired-again", code);
  fixture.rate_limit = { max_failed_attempts: 3, lockout_ms: 30_000, steps };

  fs.writeFileSync(OUT, JSON.stringify(fixture, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ status: "passed", out: path.relative(root, OUT), sources: Object.keys(sources).length }) + "\n");
})().catch((error) => { console.error(error); process.exitCode = 1; });
