// contract-test-file: tooling
// Offline producer for tests/fixtures/ts_voice_call_media.json. Transpiles the ACTUAL web
// generatedMediaGroup.ts and mediaEncryption.ts (hasMediaEncryptionMetadata; crypto imports
// stubbed) and replays the voiceCallMedia.ts resolve loop and voiceCall.ts selection rule
// over synthetic embeds. No network or account data.
// Usage (repo root): node packages/openmates-rust/tests/fixtures/ts_voice_call_media.generate.cjs
"use strict";
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const { createRequire } = require("node:module");
const root = path.resolve(__dirname, "../../../..");
const ts = createRequire(process.env.OM_UI_PACKAGE_JSON || path.join(root, "frontend/packages/ui/package.json"))("typescript");
const load = (rel) => {
  const src = fs.readFileSync(path.join(root, "frontend/packages/ui/src", rel), "utf8");
  // import.meta.env is Vite-only; the Rust-crypto flag is off for these pure helpers.
  const js = ts.transpileModule(src.replace(/import\.meta\.env\.[A-Z_]+/g, "undefined"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const mod = { exports: {} };
  vm.runInNewContext(js, { module: mod, exports: mod.exports, require: () => ({}) });
  return mod.exports;
};
const { generatedMediaChildIds, isGeneratedMediaSkill } = load("components/embeds/generatedMediaGroup.ts");
const { hasMediaEncryptionMetadata } = load("services/encryption/mediaEncryption.ts");

// Same loop as createVoiceCallMediaResolver.resolve minus fetching/decrypting.
function resolve(ids, store) {
  const media = [], pending = [...ids], seen = new Set();
  while (pending.length && seen.size < 64) {
    const id = pending.shift();
    if (seen.has(id)) continue;
    seen.add(id);
    const embed = store[id];
    if (!embed || embed._decryptionFailed || embed._decryptionPending) continue;
    const content = embed.content && typeof embed.content === "object" && !Array.isArray(embed.content) ? embed.content : null;
    if (!content) continue;
    const app = content.app_id ?? embed.app_id, skill = content.skill_id ?? embed.skill_id;
    const type = content.type ?? embed.type ?? embed.embed_type;
    const children = generatedMediaChildIds(content);
    if (children.length && isGeneratedMediaSkill(app, skill)) { pending.push(...children); continue; }
    const kind = type === "generated_image" || app === "images" && isGeneratedMediaSkill(app, skill) ? "image"
      : type === "generated_video" || app === "videos" && skill === "generate" ? "video" : null;
    if (!kind || (content.status ?? embed.status) !== "finished") continue;
    const files = content.files;
    const file = files?.original ?? (kind === "image" ? files?.preview : undefined);
    const nonce = typeof content.aes_nonce === "string" ? content.aes_nonce : "";
    if (!file || typeof file.s3_key !== "string" || typeof content.s3_base_url !== "string" || typeof content.aes_key !== "string" ||
      !hasMediaEncryptionMetadata(file, nonce)) continue;
    media.push({ embed_id: id, kind, variant: files?.original ? "original" : "preview", s3_key: file.s3_key,
      s3_base_url: content.s3_base_url, mime_type: typeof file.mime_type === "string" ? file.mime_type : null });
  }
  return media;
}
function select(items, presented, displayed) {
  const fresh = items.find((i) => !presented.includes(i.embed_id));
  if (fresh) return { displayed_index: items.indexOf(fresh), fresh: true, newly_presented: items.map((i) => i.embed_id) };
  if (items.length) return { displayed_index: Math.max(0, items.findIndex((i) => i.embed_id === displayed)), fresh: false, newly_presented: items.map((i) => i.embed_id) };
  return { displayed_index: null, fresh: false, newly_presented: [] };
}
const file = (key, extra = {}) => ({ s3_key: key, ...extra });
const img = (id, over = {}) => ({ embed_id: id, app_id: null, skill_id: null, embed_type: null, status: null,
  decryption_failed: false, decryption_pending: false,
  content: { type: "generated_image", status: "finished", s3_base_url: "https://s3.example.org/b", aes_key: "a2V5", aes_nonce: "bm9uY2U=",
    files: { original: file(`k/${id}`, { mime_type: "image/png" }) }, ...over } });
const embeds = [
  { embed_id: "grp", app_id: "images", skill_id: "generate", embed_type: null, status: null, decryption_failed: false, decryption_pending: false,
    content: { embed_ids: ["c1", "c2", "c3"], status: "finished" } },
  img("c1"), img("c2", { status: "processing" }), img("c3", { files: { original: file("k/c3", { mime_type: "image/webp" }) } }),
  img("legacy", { files: { preview: file("k/legacy-prev") } }),
  { embed_id: "vid", app_id: "videos", skill_id: "generate", embed_type: null, status: "finished", decryption_failed: false, decryption_pending: false,
    content: { files: { original: file("k/vid", { mime_type: "video/mp4" }) }, s3_base_url: "https://s3.example.org/b", aes_key: "a2V5" } },
  { ...img("vidprev"), content: { type: "generated_video", status: "finished", s3_base_url: "b", aes_key: "k", files: { preview: file("k/vp") } } },
  { ...img("broken"), decryption_failed: true }, { ...img("pend"), decryption_pending: true },
  img("nokey", { aes_key: undefined }), img("nobase", { s3_base_url: undefined }),
  { ...img("text"), content: "not an object" }, { ...img("web"), app_id: "web", content: { type: "web_search", status: "finished" } },
  { ...img("rowfallback"), embed_type: "generated_image", status: "finished", content: { s3_base_url: "b", aes_key: "k", files: { original: file("k/rf") } } },
];
const store = Object.fromEntries(embeds.map((e) => [e.embed_id, { ...e, _decryptionFailed: e.decryption_failed, _decryptionPending: e.decryption_pending }]));
// 64-visit bound: 70 distinct finished images; only the first 64 ids are visited.
const many = Array.from({ length: 70 }, (_, i) => img(`m${i}`));
for (const e of many) store[e.embed_id] = { ...e };
const cases = [
  ["group_expands_children_skips_processing", ["grp"]],
  ["legacy_preview_only", ["legacy"]],
  ["video_original_and_preview_only_video_rejected", ["vid", "vidprev"]],
  ["decryption_failed_and_pending_skipped", ["broken", "pend", "c1"]],
  ["missing_key_or_base_skipped", ["nokey", "nobase", "c1"]],
  ["non_object_content_and_other_types_skipped", ["text", "web", "missing", "c1"]],
  ["row_fields_fallback", ["rowfallback"]],
  ["newest_first_with_duplicates", ["c3", "grp", "c1", "c3"]],
  ["visit_bound_64", many.map((e) => e.embed_id)],
].map(([name, ids]) => ({ name, candidate_ids: ids, expected: resolve(ids, store) }));
const sel = [
  { items: ["a", "b", "c"], presented: [], displayed: null },
  { items: ["a", "b", "c"], presented: ["a"], displayed: "a" },
  { items: ["a", "b", "c"], presented: ["a", "b", "c"], displayed: "b" },
  { items: ["a", "b"], presented: ["a", "b"], displayed: "gone" },
  { items: ["a", "b"], presented: ["a", "b"], displayed: null },
  { items: [], presented: ["a"], displayed: "a" },
].map((c) => ({ ...c, expected: select(c.items.map((id) => ({ embed_id: id })), c.presented, c.displayed) }));
const wire = Object.fromEntries(Object.entries(store).map(([id, e]) => [id, { embed_id: e.embed_id, app_id: e.app_id ?? null, skill_id: e.skill_id ?? null,
  embed_type: e.embed_type ?? null, status: e.status ?? null, decryption_failed: !!e.decryption_failed, decryption_pending: !!e.decryption_pending, content: e.content }]));
fs.writeFileSync(path.join(__dirname, "ts_voice_call_media.json"), JSON.stringify({ embeds: wire, resolves: cases, selections: sel }, null, 2) + "\n");
