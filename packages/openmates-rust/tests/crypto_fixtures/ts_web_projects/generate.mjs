// contract-test-file: tooling
// Offline producer for packages/openmates-rust/src/web_projects_ts_vectors.json.
// Runs the ACTUAL TypeScript rules (frontend/packages/ui/src/services/projectState/*Policy.ts,
// loaded with Node's built-in type stripping, no bundler) on a fixed case list and
// records each outcome; web_projects_tests.rs replays them through Rust and
// projectStateVectors.test.ts re-runs the TypeScript rules against the recorded file.
// No account, network, IndexedDB or key material is involved.
// Usage (repo root): node packages/openmates-rust/tests/crypto_fixtures/ts_web_projects/generate.mjs
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../../../../..");
const dir = resolve(root, "frontend/packages/ui/src/services/projectState");
const load = async (name) => import(pathToFileURL(resolve(dir, `${name}.ts`)).href);
const POLICY = Object.assign(
  {},
  (await load("remoteAccessPolicy")).REMOTE_ACCESS_OPS, (await load("projectRecordPolicy")).RECORD_OPS,
  (await load("projectFocusPolicy")).FOCUS_OPS, (await load("projectReadmePolicy")).README_OPS,
  (await load("remoteFilePolicy")).REMOTE_FILE_OPS, (await load("projectWorkflowPolicy")).WORKFLOW_OPS,
);

// Same contract as policy.ts runProjectStatePolicy.
function run(op, input) {
  try {
    return JSON.parse(JSON.stringify(POLICY[op](input)) ?? "null");
  } catch (error) {
    return { error: error.message };
  }
}

const ops = {};
const add = (op, name, input) => {
  const wire = JSON.parse(JSON.stringify(input));
  (ops[op] ??= []).push({ name, input: wire, expected: run(op, wire) });
};
const hex = (c) => c.repeat(64);

// --- remote access -------------------------------------------------------------------
const pre = (over) => ({ status: "connected", capabilities: ["read", "write_request"], operation: "list", args: {}, hasOwner: true, ...over });
add("projectRemotePreflight", "offline", pre({ status: "offline" }));
add("projectRemotePreflight", "list ok", pre({}));
add("projectRemotePreflight", "read_text limits", pre({ operation: "read_text" }));
add("projectRemotePreflight", "search content without read", pre({ operation: "search", args: { include_content: true }, capabilities: ["search"] }));
add("projectRemotePreflight", "search content truthy not true", pre({ operation: "search", args: { include_content: 1 }, capabilities: [] }));
add("projectRemotePreflight", "no owner", pre({ hasOwner: false }));
add("projectRemotePreflight", "copy user initiated", pre({ operation: "copy_entries", args: { user_initiated: true } }));
add("projectRemotePreflight", "move not user initiated", pre({ operation: "move_entries", args: {} }));
add("projectRemotePreflight", "copy without write cap", pre({ operation: "copy_entries", args: { user_initiated: true }, capabilities: ["read"] }));

const tr = (paths, destinationPath = ".") => ({ paths, destinationPath });
add("projectRemoteTransfer", "single file to root", tr(["src/a.ts"]));
add("projectRemoteTransfer", "into folder", tr(["a.txt", "b/c.txt"], "dest/sub"));
add("projectRemoteTransfer", "empty list", tr([]));
add("projectRemoteTransfer", "not array", tr("a.txt"));
add("projectRemoteTransfer", "duplicates", tr(["a", "a"]));
add("projectRemoteTransfer", "too many", tr(Array.from({ length: 21 }, (_, i) => `f${i}`)));
add("projectRemoteTransfer", "twenty ok", tr(Array.from({ length: 20 }, (_, i) => `f${i}`)));
add("projectRemoteTransfer", "absolute", tr(["/etc/passwd"]));
add("projectRemoteTransfer", "backslash", tr(["a\\b"]));
add("projectRemoteTransfer", "dot dot", tr(["a/../b"]));
add("projectRemoteTransfer", "hidden part", tr(["a/.git/config"]));
add("projectRemoteTransfer", "empty part", tr(["a//b"]));
add("projectRemoteTransfer", "control char", tr(["a\u0001b"]));
add("projectRemoteTransfer", "del char", tr(["a\u007fb"]));
add("projectRemoteTransfer", "non-string path", tr([5]));
add("projectRemoteTransfer", "bad destination", tr(["a"], "../x"));
add("projectRemoteTransfer", "unicode path", tr(["docs/über ✓.md"]));
add("projectRemoteTransfer", "long path", tr(["a".repeat(4097)]));

const approved = { path: "secret.env", chatId: "chat-1", operationId: "op-1" };
add("projectIgnoredRead", "exact match", { operation: "read_text", path: "secret.env", approved });
add("projectIgnoredRead", "wrong op", { operation: "list", path: "secret.env", approved });
add("projectIgnoredRead", "wrong path", { operation: "read_text", path: "other", approved });
add("projectIgnoredRead", "missing chat", { operation: "read_text", path: "secret.env", approved: { ...approved, chatId: "" } });

add("projectRemoteCreated", "matches", { created: { source_session_id: "s1", key_epoch: 2 }, sourceSessionId: "s1", keyEpoch: 2 });
add("projectRemoteCreated", "empty ack", { created: {}, sourceSessionId: "s1", keyEpoch: 2 });
add("projectRemoteCreated", "session changed", { created: { source_session_id: "s2" }, sourceSessionId: "s1", keyEpoch: 2 });
add("projectRemoteCreated", "epoch changed", { created: { key_epoch: 3 }, sourceSessionId: "s1", keyEpoch: 2 });
add("projectRemoteCreated", "epoch zero ignored", { created: { key_epoch: 0 }, sourceSessionId: "s1", keyEpoch: 2 });

add("projectRoutingCreated", "team ok", { created: { source_session_id: "s", key_epoch: 1, routing_identity: { context_type: "team" } } });
add("projectRoutingCreated", "personal", { created: { source_session_id: "s", key_epoch: 1, routing_identity: { context_type: "personal" } } });
add("projectRoutingCreated", "no identity", { created: { source_session_id: "s", key_epoch: 1 } });
add("projectRoutingCreated", "no epoch", { created: { source_session_id: "s", routing_identity: { context_type: "team" } } });

add("projectRoutingResult", "ok", { discovery: JSON.stringify({ type: "routing_discovery_result", nonce: "n1" }), nonce: "n1" });
add("projectRoutingResult", "nonce mismatch", { discovery: JSON.stringify({ type: "routing_discovery_result", nonce: "n2" }), nonce: "n1" });
add("projectRoutingResult", "wrong type", { discovery: JSON.stringify({ type: "x", nonce: "n1" }), nonce: "n1" });
add("projectRoutingResult", "invalid json", { discovery: "{nope", nonce: "n1" });
add("projectRoutingResult", "null discovery", { discovery: null, nonce: "n1" });
add("projectRoutingResult", "array discovery", { discovery: "[1]", nonce: "n1" });

const resp = (doc) => ({ plaintext: JSON.stringify(doc) });
add("projectRemoteResponse", "ok with result", resp({ ok: true, result: { entries: [1, 2] } }));
add("projectRemoteResponse", "ok without result", resp({ ok: true }));
add("projectRemoteResponse", "known error", resp({ ok: false, error: "file_changed" }));
add("projectRemoteResponse", "unknown error code", resp({ ok: false, error: "weird_code" }));
add("projectRemoteResponse", "bad error code", resp({ ok: false, error: "Bad Code" }));
add("projectRemoteResponse", "no error", resp({}));
add("projectRemoteResponse", "ok truthy not true", resp({ ok: 1, result: 1 }));
add("projectRemoteResponse", "prototype key error", resp({ ok: false, error: "constructor" }));
add("projectRemoteResponse", "invalid plaintext", { plaintext: "not json" });
add("projectRemoteResponse", "number plaintext", { plaintext: "42" });

const text = (over) => ({ operation: "read_text", value: { content: "hi", truncated: false, sizeBytes: 2, lineCount: 1, expected_base: hex("a"), ...over } });
add("projectRemoteNormalize", "text ok", text({}));
add("projectRemoteNormalize", "text as json string", { operation: "read_text", value: JSON.stringify(text({}).value) });
add("projectRemoteNormalize", "text truncated null base", text({ truncated: true, expected_base: null }));
add("projectRemoteNormalize", "text truncated with base", text({ truncated: true }));
add("projectRemoteNormalize", "text bad base", text({ expected_base: "ABC" }));
add("projectRemoteNormalize", "text negative size", text({ sizeBytes: -1 }));
add("projectRemoteNormalize", "text fractional lines", text({ lineCount: 1.5 }));
add("projectRemoteNormalize", "text missing content", text({ content: 5 }));
const img = (over) => ({ operation: "read_image_chunk", value: { content_base64: "aGk=", mime_type: "image/png", size_bytes: 300000, offset: 131072, content_hash: hex("b"), extra: 1, ...over } });
add("projectRemoteNormalize", "image ok", img({}));
add("projectRemoteNormalize", "image bad mime", img({ mime_type: "image/svg+xml" }));
add("projectRemoteNormalize", "image unaligned offset", img({ offset: 5 }));
add("projectRemoteNormalize", "image offset past end", img({ offset: 393216 }));
add("projectRemoteNormalize", "image too big", img({ size_bytes: 2 * 1024 * 1024 + 1 }));
add("projectRemoteNormalize", "image bad base64", img({ content_base64: "a" }));
add("projectRemoteNormalize", "image empty base64", img({ content_base64: "" }));
const file = (over) => ({ operation: "read_file_chunk", value: { content_base64: "YWJj", size_bytes: 3, offset: 0, file_identity: hex("c"), chunk_hash: hex("d"), ...over } });
add("projectRemoteNormalize", "file ok", file({}));
add("projectRemoteNormalize", "file empty", file({ size_bytes: 0, content_base64: "" }));
add("projectRemoteNormalize", "file bad identity", file({ file_identity: "x" }));
add("projectRemoteNormalize", "file offset past end", file({ offset: 131072 }));
add("projectRemoteNormalize", "unchecked op", { operation: "list", value: {} });
add("projectRemoteNormalize", "invalid value", { operation: "read_file_chunk", value: "nope" });

for (const [name, status, detail] of [
  ["409 device", 409, "REQUESTER_DEVICE_IDENTITY_UNAVAILABLE"], ["409 other", 409, "x"], ["409 none", 409, undefined],
  ["401", 401], ["403", 403], ["404", 404], ["429", 429], ["500", 500],
]) add("projectRemoteHttpError", name, { status, detail });

// --- records -------------------------------------------------------------------------
const wrappers = [
  { key_type: "master", encrypted_project_key: "mk" },
  { key_type: "team", encrypted_project_key: "tk", hashed_team_id: "th" },
];
add("projectWrapperSelect", "team found", { teamId: "t", teamHash: "th", keyWrappers: wrappers, encryptedProjectKey: "ek" });
add("projectWrapperSelect", "team missing", { teamId: "t", teamHash: "other", keyWrappers: wrappers, encryptedProjectKey: "ek" });
add("projectWrapperSelect", "personal master", { teamId: null, teamHash: null, encryptedProjectKey: "ek" });
add("projectWrapperSelect", "personal none", { teamId: null, teamHash: null });
add("projectWrapperSelect", "hash without team id", { teamId: null, teamHash: "th", keyWrappers: wrappers, encryptedProjectKey: "ek" });

add("projectPublishMerge", "newer cached wins", { projectId: "p", incomingVersion: 2, current: { version: 3 }, cachedIds: ["p"], isNew: false });
add("projectPublishMerge", "replace", { projectId: "p", incomingVersion: 3, current: { version: 3 }, cachedIds: ["p"], isNew: false });
add("projectPublishMerge", "prepend", { projectId: "p", incomingVersion: 1, current: null, cachedIds: ["q"], isNew: true });
add("projectPublishMerge", "reset", { projectId: "p", incomingVersion: 1, current: null, cachedIds: ["q"], isNew: false });
add("projectPublishMerge", "invalidate", { projectId: "p", incomingVersion: null, current: { version: null }, cachedIds: null, isNew: false });
add("projectDeleteMerge", "filter", { cachedIds: [] });
add("projectDeleteMerge", "invalidate", { cachedIds: null });

add("projectCreatePlan", "named", { name: "  My Project ", writeMode: "always_ask", focusId: "f1", timestamp: 1700000000 });
add("projectCreatePlan", "blank name no mode", { name: "   ", writeMode: null, focusId: "f2", timestamp: 1 });
add("projectMetadataPatch", "with version", { version: 4, name: true, description: false });
add("projectMetadataPatch", "null version", { version: null, name: false, description: true });
add("projectSettingsInit", "already set", { settings: { encrypted_settings: "x" }, projectName: "P", focusId: "f", timestamp: 1 });
add("projectSettingsInit", "init default mode", { settings: { write_mode: "bogus" }, projectName: "P", focusId: "f", timestamp: 2 });
add("projectSettingsInit", "init keep mode", { settings: { encrypted_settings: "", write_mode: "always_ask" }, projectName: "", focusId: "f", timestamp: 3 });
add("projectSettingsPatch", "all fields", { writeMode: "apply_and_show", autoSelection: false, focusActivationPolicy: "immediate", timestamp: 5 });
add("projectSettingsPatch", "only timestamp", { writeMode: null, timestamp: 6 });
add("projectSettingsView", "full", { settings: { auto_selection: true, focus_activation_policy: "approval", write_mode: "always_ask", other: 1 }, settingsText: JSON.stringify({ default_focus: { focus_id: "f" } }) });
add("projectSettingsView", "defaults", { settings: {}, settingsText: "" });
add("projectSettingsView", "non-object settings text", { settings: { selection_required: true, write_mode: "apply_and_show" }, settingsText: "[1]" });
add("projectSettingsView", "invalid settings text", { settings: { auto_selection: false, focus_activation_policy: "x" }, settingsText: "{bad" });
add("projectSourceView", "full", { source: { source_id: "s", source_type: "remote_cli", capabilities: ["read"], status: "offline", source_session_id: "ss", key_epoch: 2 }, metadataText: JSON.stringify({ root: "/x" }), displayName: "Laptop" });
add("projectSourceView", "defaults", { source: { source_id: "s", source_type: "upload" }, metadataText: "nope", displayName: "" });
add("projectSourceCreate", "filtered caps", { sourceId: "s", sourceType: "remote_cli", encryptedDisplayName: "e1", encryptedMetadata: "e2", capabilities: ["read", "delete", "write_request"], timestamp: 9 });
add("projectSourceCreate", "defaults with indexed", { sourceId: "s", sourceType: "upload", encryptedDisplayName: "e1", encryptedMetadata: "e2", timestamp: 9, lastIndexedAt: null });
add("projectSourceCreate", "status given", { sourceId: "s", sourceType: "upload", encryptedDisplayName: "e1", encryptedMetadata: "e2", timestamp: 9, status: "offline", lastIndexedAt: 7 });
add("projectContentsView", "folders and items", {
  folders: [{ record: { folder_id: "f1", hashed_parent_folder_id: "h" }, name: "Docs" }, { record: { folder_id: "f2" }, name: "Root" }],
  items: [
    { record: { project_item_id: "i1", item_type: "embed" }, metadataText: JSON.stringify({ path: "README.md" }), targetId: "e1", displayName: "README.md" },
    { record: { project_item_id: "i2", item_type: "chat" }, metadataText: "\"str\"", targetId: "c1", displayName: "Chat" },
    { record: { project_item_id: "i3", item_type: "chat" }, metadataText: "", targetId: "c2", displayName: "Chat 2" },
  ],
});
for (const [name, fileName, fileType, importedFromRemote] of [
  ["readme", "README.md", "", false], ["remote ts", "src/app.ts", "", true], ["local ts", "app.ts", "", false],
  ["remote text mime", "notes.unknown", "text/plain", true], ["mindmap", "plan.ommindmap", "", false],
  ["mindmap json", "Plan.OpenMates-Mindmap.json", "application/json", false], ["dotfile", ".env", "", true],
  ["header", "lib/x.H", "", true], ["windows path", "dir\\file.py", "", true],
]) add("projectUploadRoute", name, { fileName, fileType, importedFromRemote });
for (const [name, filename, contentType] of [
  ["pdf mime", "x", "application/pdf"], ["pdf ext", "X.PDF", ""], ["image", "a.png", "image/png"], ["video", "a", "video/mp4"],
  ["audio", "a", "audio/mpeg"], ["sheet", "a.xlsx", ""], ["mail", "a.eml", ""], ["code", "a.svelte", ""], ["plain", "a.bin", "application/octet-stream"],
]) add("projectUploadEmbedType", name, { filename, contentType });
add("projectFileHead", "project wrapper", { embedKeys: [{ key_type: "master", encrypted_embed_key: "m" }, { key_type: "project", encrypted_embed_key: "p" }], versionNumber: 3 });
add("projectFileHead", "no keys default revision", {});
add("projectFileHead", "string revision", { embedKeys: [], versionNumber: "7" });
add("projectFileHead", "zero revision", { embedKeys: null, versionNumber: 0 });
add("projectFileHead", "fractional revision", { versionNumber: 1.5 });
add("projectFileHead", "non-string wrapper skipped", { embedKeys: [{ key_type: "project", encrypted_embed_key: 5 }] });

// --- focus ---------------------------------------------------------------------------
const mention = (attrs) => ({ type: "genericMention", attrs });
const doc = (...nodes) => ({ type: "doc", content: [{ type: "paragraph", content: nodes }] });
add("projectFocusIntent", "no document", { document: null });
add("projectFocusIntent", "plain text", { document: doc({ type: "text", text: "@project:abc" }) });
add("projectFocusIntent", "direct id", { document: doc(mention({ mentionType: "project", projectId: " p1 " })) });
add("projectFocusIntent", "syntax recovery", { document: doc(mention({ mentionType: "project_file", mentionSyntax: "@project-file:p2:src/a.ts" })) });
add("projectFocusIntent", "same project twice", { document: doc(mention({ mentionType: "project", projectId: "p1" }), mention({ mentionType: "project_folder", projectId: "p1" })) });
add("projectFocusIntent", "two projects", { document: doc(mention({ mentionType: "project", projectId: "p1" }), mention({ mentionType: "project", projectId: "p2" })) });
add("projectFocusIntent", "other mention", { document: doc(mention({ mentionType: "app", projectId: "p1" })) });
add("projectFocusIntent", "wrong prefix", { document: doc(mention({ mentionType: "project", mentionSyntax: "@project-file:p3" })) });
add("projectDefaultFocusRead", "ok", { settings: { default_focus: { focus_id: " f ", instructions: " do it " } } });
add("projectDefaultFocusRead", "missing", { settings: {} });
add("projectDefaultFocusRead", "array", { settings: { default_focus: [] } });
add("projectDefaultFocusRead", "blank instructions", { settings: { default_focus: { focus_id: "f", instructions: "  " } } });

// --- README --------------------------------------------------------------------------
const item = (over, metadata = {}, encrypted = {}) => ({
  item_type: "embed", displayName: "README.md", metadata, encrypted: { hashed_folder_id: null, updated_at: 1, created_at: 1, ...encrypted }, ...over,
});
add("projectReadmeFind", "none", { items: [item({ displayName: "notes.md" })] });
add("projectReadmeFind", "newest upload wins", { items: [
  item({}, {}, { updated_at: 9 }), item({}, { readme_uploaded_at_ms: 5 }), item({ displayName: "readme.MD" }, { readme_uploaded_at_ms: 6 }),
] });
add("projectReadmeFind", "updated then created", { items: [item({}, {}, { updated_at: 2, created_at: 1 }), item({}, {}, { updated_at: 2, created_at: 3 })] });
add("projectReadmeFind", "nested and foldered skipped", { items: [item({}, { path: "docs/README.md" }), item({}, {}, { hashed_folder_id: "h" }), item({ item_type: "chat" })] });
add("projectReadmeFind", "remote_path fallback", { items: [item({ displayName: "x" }, { remote_path: "README.md" })] });
add("projectReadmeText", "code field", { content: { code: "# Hi", text: "no" } });
add("projectReadmeText", "later field", { content: { code: 5, markdown: "md" } });
add("projectReadmeText", "none", { content: {} });
const md = [
  "# Title", "![logo](./img/logo.png)", "![remote](https://example.com/a.png \"t\")", "![proto](//cdn.example.org/b.png)",
  "![local](http://localhost/x.png)", "![ip](http://10.0.0.1/x.png)", "![abs](/abs.png)", "![esc](img/a%20b.png?raw=1)",
  "![up](../outside.png)", "![dup](./img/logo.png)", "![angle](<docs/my pic.png>)", "![ref][Logo Ref]", "![Collapsed][]",
  "", "[logo ref]: assets/ref.png", "  [collapsed]: <assets/c.png> 'x'", "![bad](%E0%A4%A.png)", "![data](data:image/png;base64,xx)",
  "![creds](https://u:p@example.com/x.png)", "![ftp](ftp://example.com/x.png)",
].join("\n");
add("projectReadmeImages", "remote source", { markdown: md, items: [], remote: true });
add("projectReadmeImages", "stored items", { markdown: md, remote: false, items: [
  item({ displayName: "logo.png" }, { path: "img/logo.png" }), item({ displayName: "a b.png" }, { path: "img/a b.png" }),
  item({ displayName: "ref.png" }, { remote_path: "assets/ref.png" }, { hashed_folder_id: "h" }),
] });
add("projectReadmeImages", "remote cap of eight", { remote: true, items: [], markdown: Array.from({ length: 10 }, (_, i) => `![i](p${i}.png)`).join(" ") });
add("projectReadmeImages", "no images", { markdown: "plain", items: [], remote: false });
add("projectReadmeRemotePick", "found", { entries: [{ path: "docs", kind: "folder" }, { path: "./Readme.md", kind: "file" }], omitted: 0 });
add("projectReadmeRemotePick", "missing incomplete", { entries: [{ path: "a.md", kind: "file" }], omitted: 3 });
add("projectReadmeRemotePick", "missing complete", { entries: [{ path: "README.md", kind: "folder" }], omitted: 0 });
const chunk = (over, result) => ({ offset: 0, size: 300000, mime: "image/png", hash: hex("a"), ...over, result: { offset: 0, size_bytes: 300000, mime_type: "image/png", content_hash: hex("a"), ...result } });
add("projectImageChunkCheck", "first chunk", chunk({}, {}));
add("projectImageChunkCheck", "last chunk short", chunk({ offset: 262144 }, { offset: 262144 }));
add("projectImageChunkCheck", "offset mismatch", chunk({ offset: 131072 }, {}));
add("projectImageChunkCheck", "hash changed", chunk({ offset: 131072 }, { offset: 131072, content_hash: hex("b") }));
add("projectImageChunkCheck", "too large", chunk({}, { size_bytes: 3 * 1024 * 1024 }));
add("projectImageChunkCheck", "first chunk ignores mime", chunk({ mime: "image/gif" }, {}));

// --- connected-source files ----------------------------------------------------------
for (const path of ["README.md", "notes.MDX", "data.jsonl", "log.txt", "Dockerfile", "src/Makefile", "a\\b\\main.rs", "x.toml",
  "photo.JPG", "archive.tar.gz", "noext", "weird.xyz", ".bashrc", "dir/"]) add("projectRemoteClassify", path, { path });
const preview = (over) => ({ sourceId: "s1", path: "src/a.ts", displayName: "a.ts", snippet: "let a = 1;", ...over });
add("projectRemotePreview", "minimal", preview({}));
add("projectRemotePreview", "full", preview({
  remoteItemId: "r1", kind: "file", language: "typescript", snippetTruncated: true, baseHash: hex("a"), sizeBytes: 10, lineCount: 1,
  mtime: "2026-01-01T00:00:00Z", contentHash: hex("b"), gitStatus: "modified", previewPolicy: "snippet", safetyFlags: ["secret_like"],
}));
add("projectRemotePreview", "empty optional strings omitted", preview({ remoteItemId: "", baseHash: "", mtime: "", sizeBytes: 0 }));
add("projectRemotePreview", "missing source", preview({ sourceId: "" }));
add("projectRemotePreview", "long path", preview({ path: "a".repeat(1025) }));
add("projectRemotePreview", "long language", preview({ language: "x".repeat(129) }));
add("projectRemotePreview", "long snippet", preview({ snippet: "x".repeat(20001) }));
add("projectRemotePreview", "negative size", preview({ sizeBytes: -1 }));
add("projectRemotePreview", "fractional lines", preview({ lineCount: 2.5 }));
add("projectRemotePreview", "too many flags", preview({ safetyFlags: Array.from({ length: 21 }, () => "f") }));
add("projectRemotePreview", "empty flag", preview({ safetyFlags: [""] }));
const built = POLICY.projectRemotePreview(preview({ baseHash: hex("a"), contentHash: hex("b"), mtime: "m", gitStatus: "g", language: "rust", lineCount: 3 }));
const bare = POLICY.projectRemotePreview(preview({ displayName: "dir/<evil>?.ts", language: "" }));
add("projectRemoteUploadPlan", "matching read", { preview: built, readResult: { truncated: false, expectedBase: hex("a") } });
add("projectRemoteUploadPlan", "changed read", { preview: built, readResult: { truncated: false, expectedBase: hex("c") } });
add("projectRemoteUploadPlan", "sanitized name plain mime", { preview: bare, readResult: { truncated: false, expectedBase: hex("c") } });
add("projectRemoteUploadPlan", "bidi and dots", { preview: POLICY.projectRemotePreview(preview({ displayName: "a‮b.txt" })), readResult: { truncated: false, expectedBase: hex("c") } });
add("projectRemoteUploadPlan", "dot name", { preview: POLICY.projectRemotePreview(preview({ displayName: "x/.." })), readResult: { truncated: false, expectedBase: hex("c") } });
add("projectRemoteUploadPlan", "truncated", { preview: built, readResult: { truncated: true, expectedBase: hex("a") } });
add("projectRemoteUploadPlan", "bad base", { preview: built, readResult: { truncated: false, expectedBase: "abc" } });
add("projectRemoteFullscreen", "with lines", { preview: built, fullContent: "fn main() {}\n" });
add("projectRemoteFullscreen", "without lines", { preview: bare, fullContent: "" });

// --- workflow and authoring ----------------------------------------------------------
const sources = [
  { source_id: "up", source_type: "upload" },
  { source_id: "rc", source_type: "remote_cli" },
  { source_id: "sess", source_type: "desktop", sourceSessionId: "x" },
];
const wf = (over) => ({ projectId: "p", workflowId: "w", targetSourceId: null, folderPath: null, sources: [], items: [], ...over });
add("projectWorkflowTarget", "local only", wf({ sources: [sources[0]] }));
add("projectWorkflowTarget", "single remote source", wf({ sources: sources.slice(0, 2), folderPath: "flows" }));
add("projectWorkflowTarget", "two remote sources", wf({ sources }));
add("projectWorkflowTarget", "explicit target", wf({ sources, targetSourceId: "sess" }));
add("projectWorkflowTarget", "unknown target", wf({ sources, targetSourceId: "gone" }));
add("projectWorkflowTarget", "prior binding", wf({ sources, items: [
  { item_type: "chat", target_id: "w", metadata: {} },
  { item_type: "workflow", target_id: "w", metadata: { remote_workflow_file: { source_id: "rc", path: "a.yml" } } },
] }));
add("projectWorkflowTarget", "existing item no binding", wf({ sources: [sources[0]], items: [{ item_type: "workflow", target_id: "w", metadata: {} }] }));
add("projectWorkflowTarget", "prior without source id", wf({ sources: [sources[0]], items: [{ item_type: "workflow", target_id: "w", metadata: { remote_workflow_file: { path: "a" } } }] }));
const gate = (over) => ({ phase: "source", projectId: "p", bindingProjectId: "p", sourceFound: true, sourceStatus: "connected", chatId: "c", focusProjectId: "p", ...over });
add("projectWorkflowRemoteGate", "source ok", gate({}));
add("projectWorkflowRemoteGate", "source offline", gate({ sourceStatus: "offline" }));
add("projectWorkflowRemoteGate", "other project binding", gate({ bindingProjectId: "q" }));
add("projectWorkflowRemoteGate", "focus ok", gate({ phase: "focus" }));
add("projectWorkflowRemoteGate", "focus missing chat", gate({ phase: "focus", chatId: null }));
add("projectWorkflowRemoteGate", "focus other project", gate({ phase: "focus", focusProjectId: "q" }));
add("projectWorkflowRemoteGate", "focus source missing", gate({ phase: "focus", sourceFound: false }));
const msg = (role, content, created_at, status = "synced") => ({ role, content, status, created_at });
add("projectAuthoringHistory", "basic", { anchorCreatedAt: null, messages: [msg("user", "hi", 1), msg("assistant", "hello", 2), msg("system", "x", 3)] });
add("projectAuthoringHistory", "anchor and status filter", { anchorCreatedAt: 3, messages: [
  msg("user", "a", 1), msg("assistant", "b", 2, "streaming"), msg("assistant", "c", 3, "failed"), msg("user", "  ", 3), msg("user", "late", 4), msg("assistant", null, 2),
] });
add("projectAuthoringHistory", "budget cut", { anchorCreatedAt: null, messages: [msg("user", "x".repeat(5000), 1), msg("assistant", "y".repeat(8000), 2), msg("user", "z".repeat(100), 3)] });
add("projectAuthoringHistory", "budget exact", { anchorCreatedAt: null, messages: [msg("user", "a", 1), msg("assistant", "é".repeat(12000), 2)] });
add("projectAuthoringHistory", "unavailable", { anchorCreatedAt: null, messages: [msg("assistant", "x", 1, "processing")] });
add("projectAuthoringHistory", "empty", { anchorCreatedAt: 5, messages: [] });
const focusEntry = (id) => ({ kind: "focus", id, title: `T ${id}`, summary: "s", revision: "1", extra: true });
const flows = [
  { id: "w1", title: "Flow one", version: 2, description: "desc" },
  { id: "w2", title: "W".repeat(250), version: 3, description: null, trigger_summary: "S".repeat(2100) },
  { id: "w3", title: "Unversioned", version: "4" },
  { id: "w4", title: "Not linked", version: 1 },
  { id: "w5", title: "No summary", version: 0 },
];
add("projectAuthoringCatalog", "focuses and linked workflows", { focuses: [focusEntry("f1")], workflows: flows, linkedIds: ["w1", "w2", "w3", "w5"], workflowsOk: true });
add("projectAuthoringCatalog", "catalog unavailable with links", { focuses: [focusEntry("f1")], workflows: [], linkedIds: ["w1"], workflowsOk: false });
add("projectAuthoringCatalog", "catalog unavailable no links", { focuses: [focusEntry("f1")], workflows: flows, linkedIds: [], workflowsOk: false });
add("projectAuthoringCatalog", "over forty", { focuses: Array.from({ length: 41 }, (_, i) => focusEntry(`f${i}`)), workflows: [], linkedIds: [], workflowsOk: true });
add("projectAuthoringCatalog", "exactly forty", { focuses: Array.from({ length: 40 }, (_, i) => focusEntry(`f${i}`)), workflows: [], linkedIds: [], workflowsOk: true });

const missing = Object.keys(POLICY).filter((op) => !ops[op]);
if (missing.length) throw new Error(`ops without vectors: ${missing.join(", ")}`);
const out = resolve(root, "packages/openmates-rust/src/web_projects_ts_vectors.json");
writeFileSync(out, `${JSON.stringify({
  generated_by: "packages/openmates-rust/tests/crypto_fixtures/ts_web_projects/generate.mjs",
  note: "Outcomes of the TypeScript rules in frontend/packages/ui/src/services/projectState; replayed by web_projects_tests.rs and projectStateVectors.test.ts.",
  ops,
}, null, 1)}\n`);
console.log(`wrote ${Object.values(ops).reduce((n, c) => n + c.length, 0)} cases for ${Object.keys(ops).length} ops`);
