"use strict";
// Generates ../ts_embed_writes.json from the actual web TypeScript embed write
// modules (MetadataEncryptor, embedUnifiedDiff, embedVersionReconstruction,
// timestampUtils, embedStateMachine, embedRefIndex). The streamed write and
// revision-history sections compose those exact primitives in the order used by
// chatSyncServiceHandlersAI.handleSendEmbedDataImpl / handleEmbedUpdateImpl and
// streamedEmbedRevisionHistory.persistClientEncryptedEmbedDiffRows.
// Usage: OPENMATES_UI_PACKAGE_JSON=<ui package.json with node_modules> node generate.cjs
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const { createRequire } = require("node:module"), { webcrypto, createHash } = require("node:crypto");

const root = path.resolve(__dirname, "../../../../..");
const uiDir = path.join(root, "frontend/packages/ui/src");
const nodeRequire = createRequire(process.env.OPENMATES_UI_PACKAGE_JSON || path.join(root, "frontend/packages/ui/package.json"));
const ts = nodeRequire("typescript");
const OUT = path.join(__dirname, "../ts_embed_writes.json");
const FIXED_NOW_MS = 1_790_000_000_000;

let rngCounter = 0;
function fillRandom(bytes) {
  let offset = 0;
  while (offset < bytes.length) {
    const block = createHash("sha256").update(`openmates-ts-embed-write-rng-${rngCounter++}`).digest();
    const take = Math.min(block.length, bytes.length - offset);
    bytes.set(block.subarray(0, take), offset);
    offset += take;
  }
  return bytes;
}
const store = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), clear: () => m.clear() }; };
const sessionStorage = store(), localStorage = store();
class FixedDate extends Date { constructor(...a) { super(...(a.length ? a : [FIXED_NOW_MS])); } static now() { return FIXED_NOW_MS; } }
const silent = { log() {}, debug() {}, info() {}, warn() {}, error() {} };
const context = vm.createContext({
  crypto: { subtle: webcrypto.subtle, getRandomValues: fillRandom }, CryptoKey: globalThis.CryptoKey,
  Uint8Array, ArrayBuffer, DataView, TextEncoder, TextDecoder, URLSearchParams, atob, btoa, Date: FixedDate, Math, JSON,
  Promise, Error, TypeError, RangeError, Number, String, Object, Array, Map, Set, Symbol, RegExp,
  console: silent, sessionStorage, localStorage, setTimeout, clearTimeout, setInterval, clearInterval,
  window: { atob, btoa, sessionStorage, localStorage, addEventListener() {}, removeEventListener() {} },
  document: { addEventListener() {}, removeEventListener() {} }, navigator: {},
});

let activeMaster = null;
let refIndexVersion = 0;
const stubs = {
  "./cryptoKeyStorage": { saveMasterKey: async () => {}, getMasterKey: async () => activeMaster, clearMasterKey: async () => {}, clearMasterKeyFromIndexedDB: async () => {}, deleteCryptoDatabase: async () => {} },
  "./ChatKeyManager": { chatKeyManager: { getProvenance: () => null, findCandidateKeyByFingerprint: async () => null, promoteCandidateKey() {} } },
  "$app/environment": { browser: true },
  "svelte/store": { writable: (initial) => { refIndexVersion = initial; return { update: (fn) => { refIndexVersion = fn(refIndexVersion); }, set: (v) => { refIndexVersion = v; }, subscribe: () => () => {} }; } },
  "tweetnacl": nodeRequire("tweetnacl"),
  "hash-wasm": nodeRequire("hash-wasm"),
};
const cache = new Map(), sources = {};
function load(rel) {
  const file = path.join(uiDir, rel.replace(/\.js$/, ".ts").replace(/(\.ts)?$/, ".ts"));
  if (cache.has(file)) return cache.get(file).exports;
  let source = fs.readFileSync(file, "utf8");
  sources[path.relative(root, file)] = createHash("sha256").update(source).digest("hex");
  source = source.replace(/import\.meta/g, "({})");
  const out = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, reportDiagnostics: true });
  if (out.diagnostics.length) throw Error(`syntax:${rel}`);
  const mod = { exports: {} };
  cache.set(file, mod);
  const dir = path.dirname(path.relative(uiDir, file));
  const req = (name) => {
    if (stubs[name]) return stubs[name];
    if (name.endsWith("/ChatKeyManager")) return stubs["./ChatKeyManager"];
    if (name.endsWith("/cryptoKeyStorage")) return stubs["./cryptoKeyStorage"];
    if (name.startsWith(".")) return load(path.join(dir, name));
    throw Error(`dependency:${name}`);
  };
  vm.runInContext(`(function(exports,require,module){${out.outputText}\n})`, context)(mod.exports, req, mod);
  return mod.exports;
}

const b64 = (bytes) => Buffer.from(bytes).toString("base64");
const bytesOf = (n, start) => new Uint8Array(Array.from({ length: n }, (_, i) => (start + i * 7) & 0xff));
const eq = (a, b) => a && b && Buffer.from(a).equals(Buffer.from(b));
const must = (cond, label) => { if (!cond) throw Error(`ts_reader_check_failed:${label}`); };
const sha = (s) => createHash("sha256").update(s, "utf8").digest("hex");
const ivOf = (ciphertext) => b64(Buffer.from(ciphertext, "base64").subarray(0, 12));
const clean = (value) => JSON.parse(JSON.stringify(value));

(async () => {
  const meta = load("services/encryption/MetadataEncryptor.ts");
  const diff = load("utils/embedUnifiedDiff.ts");
  const recon = load("utils/embedVersionReconstruction.ts");
  const time = load("services/timestampUtils.ts");
  const status = load("services/embedStateMachine.ts");
  const refs = load("services/embedRefIndex.ts");
  const toon = await import(nodeRequire.resolve("@toon-format/toon"));

  const masterRaw = bytesOf(32, 0x11), chatKey = bytesOf(32, 0x42), otherChatKey = bytesOf(32, 0x43);
  activeMaster = await webcrypto.subtle.importKey("raw", masterRaw, "AES-GCM", true, ["encrypt", "decrypt"]);
  const nowSeconds = Math.floor(FIXED_NOW_MS / 1000);
  const ids = {
    chat_id: "0d9f1a2b-3c4d-4e5f-8a9b-0c1d2e3f4a5b", message_id: "a1b2c3d4-0000-4000-8000-00000000c0de",
    user_id: "5e6f7a8b-1111-4222-8333-444455556666", task_id: "task-7f3e",
    parent_embed_id: "6f1c2d3e-4b5a-4c6d-8e7f-9a0b1c2d3e4f", child_embed_id: "7a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
    second_child_embed_id: "8b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e",
  };
  const fixture = {
    schema_version: 1, synthetic_only: true,
    provenance: "Produced by tests/crypto_fixtures/ts_embed_writes/generate.cjs running the web TypeScript modules in ts_sources (sha256 at generation) with a deterministic SHA-256 RNG. Every ciphertext was re-read by the TS reader before writing.",
    ts_sources: sources, now_seconds: nowSeconds,
    keys: { master_b64: b64(masterRaw), chat_key_b64: b64(chatKey), other_chat_key_b64: b64(otherChatKey) },
    ids,
  };

  // 1. HKDF embed key derivation (existing embeds keep their derived keys).
  fixture.derivation = [];
  for (const embedId of [ids.parent_embed_id, ids.child_embed_id, "embed-ü-ä-日本", ""]) {
    const key = await meta.deriveEmbedKeyFromChatKey(chatKey, embedId);
    fixture.derivation.push({ chat_key_b64: b64(chatKey), embed_id: embedId, embed_key_b64: b64(key) });
  }
  const parentKey = await meta.deriveEmbedKeyFromChatKey(chatKey, ids.parent_embed_id);

  // 2. Field encryption with an embed key (content/type/preview/history/aad).
  fixture.fields = [];
  for (const [label, plaintext, aad] of [["toon", "type: code\nlanguage: rust\ncode: \"fn main() {}\"", undefined], ["unicode", "Grüße 👋 — 日本語 \u0000 tail", undefined], ["empty", "", undefined], ["long", "y".repeat(8192), undefined], ["aad", "comment ✓", "task_activity_comment:task-1:entry-1:v1"]]) {
    const ciphertext = await meta.encryptWithEmbedKey(plaintext, parentKey, aad);
    must((await meta.decryptWithEmbedKey(ciphertext, parentKey, aad ? { associatedData: aad } : undefined)) === plaintext, `field:${label}`);
    fixture.fields.push({ label, plaintext, aad: aad ?? null, key_b64: b64(parentKey), ciphertext });
  }

  // 3. Embed key wrappers (master, chat, parent-embed for shared children).
  const masterWrap = await meta.wrapEmbedKeyWithMasterKey(parentKey);
  must(eq(await meta.unwrapEmbedKeyWithMasterKey(masterWrap), parentKey), "wrap-master");
  const chatWrap = await meta.wrapEmbedKeyWithChatKey(parentKey, chatKey);
  must(eq(await meta.unwrapEmbedKeyWithChatKey(chatWrap, chatKey), parentKey), "wrap-chat");
  must((await meta.unwrapEmbedKeyWithChatKey(chatWrap, otherChatKey)) === null, "wrap-chat-wrong");
  const childKey = bytesOf(32, 0x91);
  const childWrap = await meta.wrapEmbedKeyWithChatKey(childKey, parentKey);
  must(eq(await meta.unwrapEmbedKeyWithEmbedKey(childWrap, parentKey), childKey), "wrap-child");
  const chatKeyWrap = await meta.encryptChatKeyWithMasterKey(chatKey);
  must(eq(await meta.decryptChatKeyWithMasterKey(chatKeyWrap, activeMaster), chatKey), "chat-key-master");
  fixture.wrappers = { embed_key_b64: b64(parentKey), master: masterWrap, chat: chatWrap, child_key_b64: b64(childKey), child_by_parent: childWrap, encrypted_chat_key: chatKeyWrap };

  // 4. Finalized streamed writes (handleSendEmbedDataImpl composition).
  async function finalized(label, embedData, { child, localOnly, teamId }) {
    const embedKey = child ? parentKey : await meta.deriveEmbedKeyFromChatKey(chatKey, embedData.embed_id);
    const hashedChatId = sha(embedData.chat_id), hashedMessageId = sha(embedData.message_id), hashedUserId = sha(embedData.user_id);
    const hashedEmbedId = sha(embedData.embed_id);
    const hashedTaskId = embedData.task_id ? sha(embedData.task_id) : undefined;
    const encryptedContent = await meta.encryptWithEmbedKey(embedData.content, embedKey);
    const encryptedType = await meta.encryptWithEmbedKey(embedData.type, embedKey);
    const encryptedTextPreview = embedData.text_preview ? await meta.encryptWithEmbedKey(embedData.text_preview, embedKey) : undefined;
    const wrappedMasterKey = !child && !localOnly ? await meta.wrapEmbedKeyWithMasterKey(embedKey) : null;
    const wrappedChatKey = !child ? await meta.wrapEmbedKeyWithChatKey(embedKey, chatKey) : null;
    let decoded = null;
    try { decoded = toon.decode(embedData.content, { strict: false }); } catch { try { decoded = JSON.parse(embedData.content); } catch { decoded = null; } }
    let pre, refRegistration = null;
    if (decoded && typeof decoded === "object") {
      pre = { app_id: typeof embedData.app_id === "string" ? embedData.app_id : typeof decoded.app_id === "string" ? decoded.app_id : undefined,
        skill_id: typeof embedData.skill_id === "string" ? embedData.skill_id : typeof decoded.skill_id === "string" ? decoded.skill_id : undefined };
      if (typeof decoded.embed_ref === "string" && decoded.embed_ref) {
        refRegistration = { embed_ref: decoded.embed_ref, embed_id: embedData.embed_id, app_id: typeof decoded.app_id === "string" ? decoded.app_id : (pre.app_id ?? null), type: embedData.type, skill_id: pre.skill_id ?? null };
      }
    }
    const rawChildIds = decoded && typeof decoded === "object" ? (typeof decoded.embed_ids === "string" ? decoded.embed_ids.split("|") : decoded.embed_ids) : undefined;
    const childRefIds = Array.isArray(rawChildIds) ? rawChildIds.filter((id) => typeof id === "string" && id.length > 0).map((id) => id.trim()).map((id) => id.startsWith("embed:") ? id.slice(6) : id).filter((id) => id.length > 0).slice(0, 50) : [];
    const localEntry = {
      contentRef: `embed:${embedData.embed_id}`, type: embedData.type,
      createdAt: embedData.createdAt ?? embedData.created_at ?? FIXED_NOW_MS, updatedAt: embedData.updatedAt ?? embedData.updated_at ?? FIXED_NOW_MS,
      app_id: pre?.app_id, skill_id: pre?.skill_id, embed_id: embedData.embed_id, encrypted_content: encryptedContent, encrypted_type: encryptedType,
      encrypted_text_preview: encryptedTextPreview, status: embedData.status, hashed_chat_id: hashedChatId, hashed_message_id: hashedMessageId,
      hashed_task_id: hashedTaskId, hashed_user_id: hashedUserId, embed_ids: embedData.embed_ids, parent_embed_id: embedData.parent_embed_id,
      version_number: embedData.version_number ?? 1, file_path: embedData.file_path, content_hash: embedData.content_hash,
      text_length_chars: embedData.text_length_chars, is_private: embedData.is_private ?? false, is_shared: embedData.is_shared ?? false, encryption_mode: "client",
    };
    const localKeys = !child && wrappedChatKey ? [
      ...(wrappedMasterKey ? [{ hashed_embed_id: hashedEmbedId, key_type: "master", hashed_chat_id: null, encrypted_embed_key: wrappedMasterKey, hashed_user_id: hashedUserId, created_at: nowSeconds }] : []),
      { hashed_embed_id: hashedEmbedId, key_type: "chat", hashed_chat_id: hashedChatId, encrypted_embed_key: wrappedChatKey, hashed_user_id: hashedUserId, created_at: nowSeconds },
    ] : [];
    const storePayload = localOnly ? null : {
      embed_id: embedData.embed_id, ...(pre?.app_id ? { app_id: pre.app_id } : {}), ...(pre?.skill_id ? { skill_id: pre.skill_id } : {}),
      chat_id: embedData.chat_id, team_id: teamId ?? null, encrypted_type: encryptedType, encrypted_content: encryptedContent,
      encrypted_text_preview: encryptedTextPreview, status: embedData.status, hashed_chat_id: hashedChatId, hashed_message_id: hashedMessageId,
      hashed_task_id: hashedTaskId, hashed_user_id: hashedUserId, embed_ids: embedData.embed_ids, parent_embed_id: embedData.parent_embed_id,
      version_number: embedData.version_number ?? 1, file_path: embedData.file_path, content_hash: embedData.content_hash,
      text_length_chars: embedData.text_length_chars, is_private: embedData.is_private ?? false, is_shared: embedData.is_shared ?? false,
      created_at: time.normalizeToUnixSeconds(embedData.createdAt, nowSeconds), updated_at: time.normalizeToUnixSeconds(embedData.updatedAt, nowSeconds),
    };
    const serverKeys = !child && wrappedMasterKey && wrappedChatKey ? { keys: localKeys } : null;
    must((await meta.decryptWithEmbedKey(encryptedContent, embedKey)) === embedData.content, `${label}:content`);
    if (wrappedMasterKey) must(eq(await meta.unwrapEmbedKeyWithMasterKey(wrappedMasterKey), embedKey), `${label}:master`);
    const cacheTargets = child ? [embedData.embed_id] : [embedData.embed_id, ...(embedData.type !== "application" && embedData.type !== "authored_results" && Array.isArray(embedData.embed_ids) ? embedData.embed_ids : [])];
    return clean({
      label, origin: "stream-completion", input: { ...embedData, team_id: teamId ?? null, local_only: !!localOnly },
      embed_key_b64: b64(embedKey), key_source: child ? "inherit_parent" : "derive_from_chat",
      ivs: { content: ivOf(encryptedContent), type: ivOf(encryptedType), text_preview: encryptedTextPreview ? ivOf(encryptedTextPreview) : null, chat_wrapper: wrappedChatKey ? ivOf(wrappedChatKey) : null },
      expected: { local_entry: localEntry, local_key_wrappers: localKeys, store_payload: storePayload, server_keys: serverKeys, key_cache_embed_ids: cacheTargets, embed_ref_registration: refRegistration, child_ref_embed_ids: childRefIds, sealed_history: !child && Number(embedData.version_number ?? 1) > 1 },
    });
  }
  const codeContent = toon.encode({ type: "code", app_id: "code", skill_id: "code", language: "rust", code: "fn main() {\n    println!(\"hi\");\n}", embed_ref: "main-rs-k8D", embed_ids: [`embed:${ids.child_embed_id}`, ` ${ids.second_child_embed_id} `, ""] });
  const childContent = toon.encode({ type: "image_result", app_id: "images", skill_id: "search", url: "https://example.org/ü.png" });
  fixture.finalized = [
    await finalized("parent-ms-timestamps", { embed_id: ids.parent_embed_id, chat_id: ids.chat_id, message_id: ids.message_id, user_id: ids.user_id, task_id: ids.task_id, type: "code", content: codeContent, text_preview: "fn main", status: "finished", embed_ids: [ids.child_embed_id, ids.second_child_embed_id], version_number: 3, file_path: "src/main.rs", content_hash: sha("fn main"), text_length_chars: 42, createdAt: 1_789_999_000_123, updatedAt: 1_789_999_500_999 }, { teamId: null }),
    await finalized("parent-seconds-no-preview-team", { embed_id: ids.second_child_embed_id, chat_id: ids.chat_id, message_id: ids.message_id, user_id: ids.user_id, type: "application", content: JSON.stringify({ app_id: "web", title: "json fallback" }), status: "finished", embed_ids: [ids.child_embed_id], is_private: true, createdAt: 1_789_000_000, updatedAt: 0 }, { teamId: "team-1" }),
    await finalized("child-inherits-parent", { embed_id: ids.child_embed_id, chat_id: ids.chat_id, message_id: ids.message_id, user_id: ids.user_id, type: "image_result", content: childContent, text_preview: "", status: "finished", parent_embed_id: ids.parent_embed_id, skill_id: "image_result", is_shared: true }, { child: true }),
    await finalized("parent-local-only-missing-timestamps", { embed_id: "9c4d5e6f-7a8b-4c9d-8e0f-1a2b3c4d5e6f", chat_id: ids.chat_id, message_id: ids.message_id, user_id: ids.user_id, type: "math-plot", content: "not: [valid toon", status: "error", parent_embed_id: "" }, { localOnly: true }),
  ];

  // 5. Processing -> finished embed_update (handleEmbedUpdateImpl composition).
  {
    const existing = { embed_id: ids.parent_embed_id, type: "sheet", content: toon.encode({ type: "sheet", rows: 2 }), status: "finished", embed_ids: [ids.child_embed_id], version_number: 2, hashed_task_id: sha("t"), hashed_message_id: sha("old-message"), app_id: "sheets", skill_id: "sheet", createdAt: 1_789_999_000_000 };
    const embedKey = parentKey;
    const hashedChatId = sha(ids.chat_id), hashedEmbedId = sha(existing.embed_id), hashedUserId = sha(ids.user_id);
    const encryptedContent = await meta.encryptWithEmbedKey(existing.content, embedKey);
    const encryptedType = await meta.encryptWithEmbedKey(existing.type, embedKey);
    const wrappedMasterKey = await meta.wrapEmbedKeyWithMasterKey(embedKey);
    const wrappedChatKey = await meta.wrapEmbedKeyWithChatKey(embedKey, chatKey);
    const keys = [
      { hashed_embed_id: hashedEmbedId, key_type: "master", hashed_chat_id: null, encrypted_embed_key: wrappedMasterKey, hashed_user_id: hashedUserId, created_at: nowSeconds },
      { hashed_embed_id: hashedEmbedId, key_type: "chat", hashed_chat_id: hashedChatId, encrypted_embed_key: wrappedChatKey, hashed_user_id: hashedUserId, created_at: nowSeconds },
    ];
    const forStorage = { embed_id: existing.embed_id, encrypted_type: encryptedType, encrypted_content: encryptedContent, status: existing.status, hashed_chat_id: hashedChatId, hashed_message_id: existing.hashed_message_id, hashed_task_id: existing.hashed_task_id, hashed_user_id: hashedUserId, embed_ids: existing.embed_ids, parent_embed_id: existing.parent_embed_id, version_number: existing.version_number, file_path: existing.file_path, content_hash: existing.content_hash, text_length_chars: existing.text_length_chars, is_private: false, is_shared: false, createdAt: existing.createdAt, updatedAt: existing.updatedAt };
    const { createdAt, updatedAt, ...rest } = forStorage;
    fixture.processing_update = clean({
      label: "processing-to-finished", origin: "stream-update",
      input: { existing, chat_id: ids.chat_id, user_id: ids.user_id, message_id: null },
      embed_key_b64: b64(embedKey), ivs: { content: ivOf(encryptedContent), type: ivOf(encryptedType), chat_wrapper: ivOf(wrappedChatKey) },
      expected: {
        local_entry: { contentRef: `embed:${existing.embed_id}`, type: existing.type, createdAt: existing.createdAt, updatedAt: FIXED_NOW_MS, app_id: existing.app_id, skill_id: existing.skill_id, ...rest, encryption_mode: "client" },
        local_key_wrappers: keys, store_payload: { ...rest, created_at: time.normalizeToUnixSeconds(createdAt, nowSeconds), updated_at: time.normalizeToUnixSeconds(updatedAt, nowSeconds) },
        server_keys: { keys }, key_cache_embed_ids: [existing.embed_id, ...existing.embed_ids],
      },
    });
  }

  // 6. Streamed revision history rows (persistClientEncryptedEmbedDiffRows, ordinary path).
  const v1 = "line one\nline two\n", v2 = "line one\nline 2\nline three", v3 = "";
  const p2 = diff.buildUnifiedDiff(v1, v2, 1, 2), p3 = diff.buildUnifiedDiff(v2, v3, 2, 3);
  const historyInput = [
    { embed_id: ids.parent_embed_id, version_number: 1, snapshot: v1, created_at: 1_789_999_000_456 },
    { embed_id: ids.parent_embed_id, version_number: 2, patch: p2, created_at: 1_789_999_100 },
    { embed_id: ids.parent_embed_id, version_number: 3, patch: p3 },
    { embed_id: ids.parent_embed_id, version_number: 4 },
  ];
  const historyRows = [];
  for (const row of historyInput) {
    const encryptedSnapshot = typeof row.snapshot === "string" ? await meta.encryptWithEmbedKey(row.snapshot, parentKey) : undefined;
    const encryptedPatch = typeof row.patch === "string" ? await meta.encryptWithEmbedKey(row.patch, parentKey) : undefined;
    if (!encryptedSnapshot && !encryptedPatch) { historyRows.push(null); continue; }
    const createdAt = time.normalizeToUnixSeconds(row.created_at, nowSeconds);
    historyRows.push(clean({
      iv: ivOf(encryptedSnapshot ?? encryptedPatch),
      local_row: { id: `${row.embed_id}_v${row.version_number}`, embed_id: row.embed_id, version_number: row.version_number, encrypted_snapshot: encryptedSnapshot, encrypted_patch: encryptedPatch, created_at: createdAt },
      server_payload: { embed_id: row.embed_id, version_number: row.version_number, encrypted_snapshot: encryptedSnapshot ?? null, encrypted_patch: encryptedPatch ?? null, hashed_user_id: sha(ids.user_id), created_at: createdAt },
    }));
  }
  const reconstructed = await recon.reconstructVersionRows(historyRows.filter(Boolean).map((r) => r.local_row), (c) => meta.decryptWithEmbedKey(c, parentKey));
  must(reconstructed === v3, "history-reconstruct");
  fixture.history = { embed_key_b64: b64(parentKey), hashed_user_id: sha(ids.user_id), input: historyInput, rows: historyRows, reconstructed_v2: v2, reconstructed_v3: reconstructed };

  // 7. Unified diffs and restore planning (embedDiffStore.restoreEmbedVersion composition).
  fixture.unified_diffs = [];
  for (const [label, a, b, from, to] of [["replace", v1, v2, 1, 2], ["to-empty", v2, "", 2, 3], ["from-empty", "", "a\nb", 3, 4], ["both-empty", "", "", 4, 5], ["unicode-crlf", "ä\r\nb", "ä\r\nc\n", 31, 32]]) {
    const patch = diff.buildUnifiedDiff(a, b, from, to);
    must(recon.applyVersionPatch(a, patch) === b, `apply:${label}`);
    fixture.unified_diffs.push({ label, current: a, restored: b, current_version: from, new_version: to, patch });
  }
  fixture.restore = [];
  for (const [label, current, restored, currentVersion] of [["ordinary", v2, v1, 2], ["checkpoint", v1, v2, 31]]) {
    const newVersion = currentVersion + 1;
    const patch = diff.buildUnifiedDiff(current, restored, currentVersion, newVersion);
    const encryptedPatch = await meta.encryptWithEmbedKey(patch, parentKey);
    const encryptedSnapshot = newVersion % 32 === 0 ? await meta.encryptWithEmbedKey(restored, parentKey) : null;
    fixture.restore.push({ label, embed_id: ids.parent_embed_id, current_version: currentVersion, current_content: current, restored_content: restored,
      ivs: { patch: ivOf(encryptedPatch), snapshot: encryptedSnapshot ? ivOf(encryptedSnapshot) : null },
      expected: { new_version: newVersion, content_hash: sha(restored), diff_row: clean({ id: `${ids.parent_embed_id}_v${newVersion}`, embed_id: ids.parent_embed_id, version_number: newVersion, encrypted_patch: encryptedPatch, ...(encryptedSnapshot ? { encrypted_snapshot: encryptedSnapshot } : {}), created_at: nowSeconds }) } });
  }

  // 8. Status state machine.
  const statuses = ["processing", "rendering", "finished", "error", "cancelled", "needs_rerender", "completed", "bogus"];
  fixture.status = { transitions: [], normalize: [], terminal: [] };
  for (const from of statuses) for (const to of statuses) fixture.status.transitions.push([from, to, status.validateEmbedTransition(from, to, "x")]);
  for (const v of [...statuses, null, 3]) fixture.status.normalize.push([v, status.normalizeEmbedStatus(v)]);
  for (const v of statuses) fixture.status.terminal.push([v, status.isTerminalStatus(v)]);

  // 9. embed_ref index register/resolve sequence.
  const ops = [
    ["register", "ryanair-0600-k8D", { embedId: "e1", appId: "travel", skillId: "search", type: "flight" }],
    ["register", "  hotel–berlin-k8d ", { embedId: "e2", appId: null, skillId: null, type: null }],
    ["register", "ryanair-0600-k8D", { embedId: "e1", appId: "travel", skillId: "search", type: "flight" }],
    ["register", "", { embedId: "e3", appId: null, skillId: null, type: null }],
    ["resolve", "ryanair-0600-k8D"], ["resolve", "e1"], ["resolve", "-k8D"], ["resolve", "-K8D"], ["resolve", "−k8d"],
    ["register", "train-0900-x1", { embedId: "e4", appId: "travel", skillId: null, type: "train" }],
    ["resolve", "-x1"], ["resolve", "-x"], ["resolve", "-k8d"], ["resolve", "unknown"],
    ["register", "car-k8d", { embedId: "e1", appId: "travel", skillId: "search", type: "flight" }],
    ["resolve", "-k8d"], ["clear"], ["resolve", "e1"],
  ];
  fixture.ref_index = [];
  for (const op of ops) {
    if (op[0] === "register") { const before = refIndexVersion; refs.registerEmbedRefIndex(op[1], op[2]); fixture.ref_index.push({ op: "register", ref: op[1], entry: op[2], changed: refIndexVersion !== before }); }
    else if (op[0] === "resolve") fixture.ref_index.push({ op: "resolve", ref: op[1], result: clean(refs.resolveEmbedRefIndexReference(op[1])) });
    else { refs.clearEmbedRefIndexEntries(); fixture.ref_index.push({ op: "clear" }); }
  }

  fs.writeFileSync(OUT, JSON.stringify(fixture, null, 1) + "\n");
  console.log(`wrote ${path.relative(root, OUT)}`);
})().catch((error) => { console.error(error); process.exit(1); });
