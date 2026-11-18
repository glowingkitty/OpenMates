// contract-test-file: tooling
// Offline producer for tests/crypto_fixtures/ts_share_links.json (frozen vectors).
// Runs the ACTUAL web TypeScript embedShareEncryption.ts and shortUrlEncryption.ts
// (flag-off TS path, import.meta.env = {}) with a deterministic RNG and synthetic keys,
// and records every embed-key blob and short-URL format, including legacy six-character
// short links. Each ciphertext is re-read by the same TS reader before it is written.
// Usage (from repo root, needs frontend/packages/ui/node_modules):
//   node packages/openmates-rust/tests/crypto_fixtures/ts_web_formats/generate_share_links.cjs
"use strict";
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const { createRequire } = require("node:module"), { webcrypto, createHash } = require("node:crypto");

const root = path.resolve(__dirname, "../../../../..");
const uiDir = path.join(root, "frontend/packages/ui/src");
const ts = createRequire(path.join(root, "frontend/packages/ui/package.json"))("typescript");
const OUT = path.join(__dirname, "../ts_share_links.json");
const FIXED_NOW_MS = 1_790_000_000_000;

let rngCounter = 0;
function fillRandom(bytes) {
  let offset = 0;
  while (offset < bytes.length) {
    const block = createHash("sha256").update(`openmates-ts-share-links-rng-${rngCounter++}`).digest();
    const take = Math.min(block.length, bytes.length - offset);
    bytes.set(block.subarray(0, take), offset);
    offset += take;
  }
  return bytes;
}
class FixedDate extends Date { constructor(...a) { super(...(a.length ? a : [FIXED_NOW_MS])); } static now() { return FIXED_NOW_MS; } }
const silent = { log() {}, debug() {}, info() {}, warn() {}, error() {} };
const context = vm.createContext({
  crypto: { subtle: webcrypto.subtle, getRandomValues: fillRandom }, CryptoKey: globalThis.CryptoKey,
  Uint8Array, ArrayBuffer, TextEncoder, TextDecoder, URLSearchParams, atob, btoa, Date: FixedDate,
  Math, JSON, Promise, Error, Number, String, Object, Array, parseInt, console: silent,
});

let embedKeyForShare = null;
const stubs = {
  "./embedStore": { embedStore: { getEmbedKey: async () => embedKeyForShare } },
  "./rustCore/crypto/webCryptoClient": { rustWebCrypto: () => null },
  "./rustCore/crypto/webCryptoFacades": {},
  "./shareState/shortUrlPolicy": {},
  "./shareState/decide": { decideShareState: async () => null },
};
const cache = new Map(), sources = {};
function load(rel) {
  const file = path.join(uiDir, rel);
  if (cache.has(file)) return cache.get(file).exports;
  let source = fs.readFileSync(file, "utf8");
  sources[path.relative(root, file)] = createHash("sha256").update(source).digest("hex");
  source = source.replace(/import\.meta/g, "({ env: {} })");
  const out = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, reportDiagnostics: true });
  if (out.diagnostics.length) throw Error(`syntax:${rel}`);
  const mod = { exports: {} };
  cache.set(file, mod);
  const req = (name) => { if (stubs[name]) return stubs[name]; throw Error(`dependency:${name}`); };
  vm.runInContext(`(function(exports,require,module){${out.outputText}\n})`, context)(mod.exports, req, mod);
  return mod.exports;
}
const must = (c, m) => { if (!c) throw Error(`self-check failed: ${m}`); };
const b64 = (u) => Buffer.from(u).toString("base64");
const eq = (a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)) === 0;

(async () => {
  const embedShare = load("services/embedShareEncryption.ts");
  const shortUrl = load("services/shortUrlEncryption.ts");
  const nowS = Math.floor(FIXED_NOW_MS / 1000);
  const embedId = "7c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f";
  const fx = { schema_version: 1, synthetic_only: true, ts_sources: sources, generated_at: nowS, embed_id: embedId, embed_blobs: [], short_urls: [] };

  const keys = { key32: fillRandom(new Uint8Array(32)), key16: fillRandom(new Uint8Array(16)) };
  for (const [kname, key] of Object.entries(keys)) {
    embedKeyForShare = key;
    for (const [label, duration, password] of [
      ["no-password-forever", 0, undefined], ["empty-password-means-none", 0, ""],
      ["password-1week", 604800, "embed pw"], ["password-ten-chars-unicode", 3600, "pässwörd1!"],
    ]) {
      const blob = await embedShare.generateEmbedShareKeyBlob(embedId, duration, password);
      const ok = await embedShare.decryptEmbedShareKeyBlob(embedId, blob, nowS + 10, password || undefined);
      must(ok.success && eq(ok.embedKey, key), `embed:${kname}:${label}`);
      if (password) must((await embedShare.decryptEmbedShareKeyBlob(embedId, blob, nowS, undefined)).error === "password_required", "pw-required");
      if (duration) must((await embedShare.decryptEmbedShareKeyBlob(embedId, blob, nowS + duration + 1, password || undefined)).error === "expired", "expired");
      fx.embed_blobs.push({ label: `${kname}:${label}`, embed_key_b64: b64(key), duration_seconds: duration, password: password || null, blob });
    }
  }

  const chatUrl = "https://openmates.org/share/chat/0d9f1a2b-3c4d-4e5f-8a9b-0c1d2e3f4a5b#key=abc-_123";
  for (const [label, token, shortKey, url] of [
    ["current-8-22", "Qw3rTy9U", "MG56JGwigUoMz4RAbwfC0N", chatUrl],
    ["legacy-six-char-key", "a8f3kLmN", "Xk7pQr", chatUrl],
    ["legacy-six-char-token-and-key", "a8f3kL", "Xk7pQr", `https://openmates.org/share/embed/${embedId}#key=zz_-9`],
    ["non-ascii-url", "Zq81LmPd", "N0n4sc11Key0123456789a", "https://openmates.org/share/chat/ü-ö?x=日本語#key=a-b_c"],
  ]) {
    const encrypted = await shortUrl.encryptShareUrl(url, token, shortKey);
    must((await shortUrl.decryptShareUrl(encrypted, token, shortKey)) === url, `short:${label}`);
    fx.short_urls.push({ label, token, short_key: shortKey, url, encrypted });
  }
  fs.writeFileSync(OUT, JSON.stringify(fx, null, 2) + "\n");
  console.log(`wrote ${path.relative(root, OUT)}: ${fx.embed_blobs.length} embed blobs, ${fx.short_urls.length} short urls`);
})().catch((e) => { console.error(e); process.exit(1); });
