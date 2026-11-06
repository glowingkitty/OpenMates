// contract-test-file: tooling
// Offline producer for tests/crypto_fixtures/ts_web_policy.json: chat-content
// read outcomes, key fingerprints, the chat-key write guard, the key-slot
// compare-and-swap (ChatKeyManager.injectKey) and the decryption failure cache.
// Runs the ACTUAL web TypeScript modules (transpiled with the installed
// TypeScript, no bundler) with synthetic keys, a deterministic RNG and stubs
// for non-crypto platform dependencies only (IndexedDB rows, notifications).
// Usage (from repo root): node packages/openmates-rust/tests/crypto_fixtures/ts_web_policy/generate.cjs [out]
"use strict";
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const { createRequire } = require("node:module"), { webcrypto, createHash, createCipheriv } = require("node:crypto");

const root = path.resolve(__dirname, "../../../../..");
const uiDir = path.join(root, "frontend/packages/ui/src");
const nodeRequire = createRequire(path.join(root, "frontend/packages/ui/package.json"));
const ts = nodeRequire("typescript");
const OUT = process.argv[2] ? path.resolve(process.argv[2]) : path.join(__dirname, "../ts_web_policy.json");

let rngCounter = 0;
function fillRandom(bytes) {
  let offset = 0;
  while (offset < bytes.length) {
    const block = createHash("sha256").update(`openmates-ts-policy-rng-${rngCounter++}`).digest();
    const take = Math.min(block.length, bytes.length - offset);
    bytes.set(block.subarray(0, take), offset);
    offset += take;
  }
  return bytes;
}
const silent = { log() {}, debug() {}, info() {}, warn() {}, error() {} };
const win = { atob, btoa, addEventListener() {}, removeEventListener() {} };
const context = vm.createContext({
  crypto: { subtle: webcrypto.subtle, getRandomValues: fillRandom, randomUUID: () => "00000000-0000-4000-8000-000000000000" },
  CryptoKey: globalThis.CryptoKey, Uint8Array, ArrayBuffer, DataView, TextEncoder, TextDecoder, URLSearchParams, atob, btoa,
  Date, Math, JSON, Promise, Error, TypeError, RangeError, Number, String, Object, Array, Map, Set, WeakMap, Symbol,
  console: silent, setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask,
  window: win, document: { addEventListener() {}, removeEventListener() {} }, navigator: {},
});

// ── Platform stubs (controlled per scenario) ──
const state = { chat: null, encryptedKey: null, anonymousKey: null, masterUnwrap: null, teamUnwrap: null, candidates: [], notices: [], candidateLookups: [] };
const stubs = {
  "../stores/notificationStore": { notificationStore: { error: (message) => state.notices.push(message), warning() {}, info() {}, success() {} } },
  "./anonymousChatKeyWrapping": { unwrapAnonymousChatKey: async () => state.anonymousKey },
  "../anonymousChatKeyWrapping": { unwrapAnonymousChatKey: async () => state.anonymousKey },
  "./db": { chatDB: { getChat: async () => state.chat, getEncryptedChatKey: async () => state.encryptedKey } },
  "./db/chatCrudOperations": { addCandidateKey: async (_db, _chatId, key) => { state.candidates.push(key); } },
  "./encryption/MetadataEncryptor": { decryptChatKeyWithMasterKey: async () => { if (state.masterUnwrap === "throw") throw Error("unwrap"); return state.masterUnwrap; } },
  "./directChatService": { unwrapTeamOrDirectChatKey: async () => { if (state.teamUnwrap === "throw") throw Error("team"); return state.teamUnwrap; } },
  "../recentChatWindowCache": { invalidateRecentChatWindow() {} },
  "./ChatKeyManager": { chatKeyManager: { getProvenance: () => null, findCandidateKeyByFingerprint: async (_chat, fp) => { state.candidateLookups.push(fp); return null; }, promoteCandidateKey() {} } },
  "./cryptoKeyStorage": { getMasterKey: async () => null, saveMasterKey: async () => {}, clearMasterKey: async () => {}, clearMasterKeyFromIndexedDB: async () => {}, deleteCryptoDatabase: async () => {} },
  "$app/environment": { browser: true },
  "tweetnacl": nodeRequire("tweetnacl"),
  "hash-wasm": nodeRequire("hash-wasm"),
};
const cache = new Map(), sources = {};
function load(rel) {
  const file = path.join(uiDir, rel);
  if (cache.has(file)) return cache.get(file).exports;
  const source = fs.readFileSync(file, "utf8");
  sources[path.relative(root, file)] = createHash("sha256").update(source).digest("hex");
  const out = ts.transpileModule(source.replace(/import\.meta/g, "({})"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, reportDiagnostics: true });
  if (out.diagnostics.length) throw Error(`syntax:${rel}`);
  const mod = { exports: {} };
  cache.set(file, mod);
  const dir = path.dirname(rel);
  const req = (name) => {
    // ChatKeyManager itself is the module under test when loaded directly.
    if (name.endsWith("/ChatKeyManager") && rel.endsWith("MessageEncryptor.ts")) return stubs["./ChatKeyManager"];
    if (stubs[name]) return stubs[name];
    if (name.endsWith("/cryptoKeyStorage")) return stubs["./cryptoKeyStorage"];
    if (name.startsWith(".")) return load(path.join(dir, name) + ".ts");
    throw Error(`dependency:${name}`);
  };
  vm.runInContext(`(function(exports,require,module){${out.outputText}\n})`, context)(mod.exports, req, mod);
  return mod.exports;
}

const b64 = (bytes) => Buffer.from(bytes).toString("base64");
const key = (start) => new Uint8Array(Array.from({ length: 32 }, (_, i) => (start + i * 13) & 0xff));
const must = (cond, label) => { if (!cond) throw Error(`ts_check_failed:${label}`); };

(async () => {
  const msg = load("services/encryption/MessageEncryptor.ts");
  const ckm = load("services/encryption/ChatKeyManager.ts");
  const guard = load("services/chatKeyWriteGuard.ts");
  const failures = load("services/db/decryptionFailureCache.ts");
  const fixture = {
    schema_version: 1,
    synthetic_only: true,
    provenance: "Produced by tests/crypto_fixtures/ts_web_policy/generate.cjs running the actual web TypeScript modules listed in ts_sources with a deterministic RNG and stubbed IndexedDB/notification dependencies.",
    ts_sources: sources,
  };
  const k1 = key(0x21), k2 = key(0x77);
  fixture.keys = { k1_b64: b64(k1), k2_b64: b64(k2) };

  // 1. Fingerprints.
  fixture.fingerprints = [k1, k2, new Uint8Array(32), key(0xff)].map((k) => ({
    key_b64: b64(k), fp16: ckm.computeKeyFingerprint(k), fp4: Buffer.from(msg.computeKeyFingerprint4Bytes(k)).toString("hex"),
  }));

  // 2. Chat-content read outcomes (decryptWithChatKey with a chat context so
  // the candidate-recovery lookup is observable).
  const gcm = (k, iv, plain) => { const c = createCipheriv("aes-256-gcm", k, iv); return Buffer.concat([c.update(plain), c.final(), c.getAuthTag()]); };
  const plain = Buffer.from("policy ✓ text");
  const omIv = Buffer.from([0x4f, 0x4d, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  const cases = [
    ["om-matching", await msg.encryptWithChatKey(plain.toString(), k1), "k1"],
    ["om-other-key", await msg.encryptWithChatKey(plain.toString(), k2), "k1"],
    ["legacy-iv", b64(Buffer.concat([Buffer.alloc(12, 3), gcm(k1, Buffer.alloc(12, 3), plain)])), "k1"],
    ["legacy-wrong-key", b64(Buffer.concat([Buffer.alloc(12, 3), gcm(k2, Buffer.alloc(12, 3), plain)])), "k1"],
    ["legacy-iv-starts-om", b64(Buffer.concat([omIv, gcm(k1, omIv, plain)])), "k1"],
    ["python-marker", b64(Buffer.concat([Buffer.from([0x4f, 0x4d, 1, 0, 0, 0]), Buffer.alloc(12, 9), gcm(k1, Buffer.alloc(12, 9), plain)])), "k1"],
    ["truncated", b64(Buffer.alloc(20, 1)), "k1"],
    ["empty", "", "k1"],
  ];
  const om = cases[0][1];
  cases.push(["om-urlsafe-unpadded", om.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""), "k1"]);
  cases.push(["om-tampered", b64(Buffer.from(Buffer.from(om, "base64").map((b, i, a) => (i === a.length - 1 ? b ^ 1 : b)))), "k1"]);
  fixture.chat_content = [];
  for (const [label, ciphertext, keyName] of cases) {
    state.candidateLookups = [];
    const out = await msg.decryptWithChatKey(ciphertext, keyName === "k1" ? k1 : k2, { chatId: "chat-1", fieldName: "content" });
    fixture.chat_content.push({ label, ciphertext, key: keyName, ts_plaintext: out, ts_candidate_lookup: state.candidateLookups[0] ?? null });
  }
  must(fixture.chat_content[0].ts_plaintext === plain.toString(), "om");
  must(fixture.chat_content[1].ts_candidate_lookup !== null, "mismatch-lookup");

  // 3. Write guard scenarios.
  const fp1 = ckm.computeKeyFingerprint(k1), fp2 = ckm.computeKeyFingerprint(k2);
  const scenarios = [
    ["no-chat-no-key", null, null, {}],
    ["no-chat-allow-missing", null, null, { allowMissingEncryptedChatKey: true }],
    ["direct-allow-missing", { chat_visibility: "direct" }, null, { allowMissingEncryptedChatKey: true }],
    ["candidates-pending", { candidate_encrypted_keys: ["x"], encrypted_chat_key: "W" }, null, {}],
    ["fingerprint-mismatch", { key_fingerprint: fp2, encrypted_chat_key: "W" }, null, {}],
    ["fingerprint-mismatch-no-wrapper", { key_fingerprint: fp2 }, null, {}],
    ["fingerprint-match-master-ok", { key_fingerprint: fp1, encrypted_chat_key: "W" }, null, {}, { master: "k1" }],
    ["master-mismatch", { encrypted_chat_key: "W" }, null, {}, { master: "k2" }],
    ["master-null", { encrypted_chat_key: "W" }, null, {}, { master: null }],
    ["master-throw", { encrypted_chat_key: "W" }, null, {}, { master: "throw" }],
    ["fallback-encrypted-key", { }, "W", {}, { master: "k1" }],
    ["direct-no-team", { chat_visibility: "direct", encrypted_chat_key: "W" }, null, {}, { master: "k1" }],
    ["omdm-no-team", { encrypted_chat_key: "OMDM1.abc" }, null, {}, { master: "k1" }],
    ["team-ok", { team_id: "t1", encrypted_chat_key: "OMDM1.abc" }, null, {}, { team: "k1" }],
    ["team-mismatch", { team_id: "t1", encrypted_chat_key: "W" }, null, {}, { team: "k2" }],
    ["team-throw", { team_id: "t1", encrypted_chat_key: "W" }, null, {}, { team: "throw" }],
    ["anonymous-ok", { is_anonymous: true }, null, {}, { anonymous: "k1" }],
    ["anonymous-mismatch", { is_anonymous: true }, null, {}, { anonymous: "k2" }],
    ["anonymous-unwrap-failed", { is_anonymous: true }, null, {}, { anonymous: null }],
    ["anonymous-with-wrapper", { is_anonymous: true, encrypted_chat_key: "W" }, null, {}, { master: "k1" }],
    ["report-off-mismatch", { key_fingerprint: fp2, encrypted_chat_key: "W" }, null, { reportFailure: false }],
  ];
  const named = (v) => (v === "k1" ? k1 : v === "k2" ? k2 : v);
  fixture.write_guard = [];
  for (const [label, chat, fallbackKey, options, unwraps = {}] of scenarios) {
    Object.assign(state, { chat, encryptedKey: fallbackKey, anonymousKey: named(unwraps.anonymous ?? null), masterUnwrap: named(unwraps.master ?? null), teamUnwrap: named(unwraps.team ?? null), candidates: [], notices: [] });
    delete win.__openmatesLastChatKeyGuardDebug;
    const allowed = await guard.ensureChatKeySafeForWrite("chat-1", k1, "test", options);
    await new Promise((r) => setTimeout(r, 0));
    fixture.write_guard.push({
      label, chat, fallback_encrypted_key: fallbackKey, options, unwraps,
      ts_allowed: allowed, ts_reason: win.__openmatesLastChatKeyGuardDebug?.reason ?? null,
      ts_added_candidate: state.candidates.length > 0, ts_notices: state.notices.length,
    });
  }

  // 4. Key-slot compare-and-swap.
  const sources4 = ["direct_chat", "master_key", "server_sync", "created", "hidden_chat", "bulk_init", "anonymous_session", "shared_storage", "share_link", "injected"];
  fixture.inject = [];
  for (const [label, first, second] of [
    ["insert", null, ["k1", "share_link", false]],
    ["same-upgrade", ["k1", "share_link"], ["k1", "master_key", false]],
    ["same-downgrade", ["k1", "master_key"], ["k1", "share_link", false]],
    ["same-equal", ["k1", "server_sync"], ["k1", "server_sync", false]],
    ["different-rejected", ["k1", "master_key"], ["k2", "server_sync", false]],
    ["different-forced", ["k1", "master_key"], ["k2", "injected", true]],
    ...sources4.map((s) => [`same-from-injected-to-${s}`, ["k1", "injected"], ["k1", s, false]]),
  ]) {
    const manager = new ckm.ChatKeyManager();
    if (first) manager.injectKey("chat-1", named(first[0]), first[1]);
    const before = manager.getProvenance("chat-1")?.source ?? null;
    const accepted = manager.injectKey("chat-1", named(second[0]), second[1], second[2]);
    const after = manager.getProvenance("chat-1")?.source ?? null;
    const current = manager.getKeySync("chat-1");
    fixture.inject.push({ label, existing: first, inject: second, ts_accepted: accepted, ts_source_before: before, ts_source_after: after, ts_key_after: current ? (Buffer.from(current).equals(Buffer.from(k1)) ? "k1" : "k2") : null });
  }

  // 5. Decryption failure cache: an operation script and each answer.
  const ops = [
    ["record", "c1", "m1", "content", "fpA"], ["is", "c1", "m1", "content", "fpA"], ["is", "c1", "m1", "content", "fpB"],
    ["is", "c1", "m1", "content", null], ["is", "c1", "m1", "cont", null], ["is", "c1", "m1x", "content", null],
    ["record", "c1", "m2", "title", null], ["is", "c1", "m2", "title", null], ["is", "c1", "m2", "title", "fpA"],
    ["is", "c2", "m1", "content", "fpA"], ["clear", "c1"], ["is", "c1", "m1", "content", "fpA"],
    ["record", "c1", "m1", "content", "fpA"], ["record", "c2", "m1", "content", ""], ["is", "c2", "m1", "content", null],
    ["clear", null], ["is", "c1", "m1", "content", "fpA"], ["is", "c2", "m1", "content", null],
  ];
  failures.clearDecryptionFailureCache();
  fixture.failure_cache = ops.map(([op, chat, message, field, fp]) => {
    if (op === "record") { failures.recordDecryptionFailure(chat, message, field, fp ?? undefined); return { op, chat, message, field, fp }; }
    if (op === "clear") { failures.clearDecryptionFailureCache(chat ?? undefined); return { op, chat }; }
    return { op, chat, message, field, fp, ts_known: failures.isKnownDecryptionFailure(chat, message, field, fp ?? undefined) };
  });

  fs.writeFileSync(OUT, JSON.stringify(fixture, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ status: "passed", out: path.relative(root, OUT), sources: Object.keys(sources).length }) + "\n");
})().catch((error) => { console.error(error); process.exitCode = 1; });
