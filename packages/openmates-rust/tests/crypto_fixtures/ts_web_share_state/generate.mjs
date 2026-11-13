// contract-test-file: tooling
// Offline producer for packages/openmates-rust/src/web_share_state_ts_vectors.json.
// Runs the ACTUAL TypeScript rules (frontend/packages/ui/src/services/shareState/*Policy.ts,
// loaded with Node's built-in type stripping, no bundler) on a fixed case list and
// records each outcome; web_share_state_tests.rs replays them through Rust and
// shareStateVectors.test.ts re-runs the TypeScript rules against the recorded file.
// No account, network, IndexedDB or key material is involved.
// Usage (repo root): node packages/openmates-rust/tests/crypto_fixtures/ts_web_share_state/generate.mjs
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../../../../..");
const dir = resolve(root, "frontend/packages/ui/src/services/shareState");
const load = async (name) => import(pathToFileURL(resolve(dir, `${name}.ts`)).href);
const tables = [
  (await load("shortUrlPolicy")).SHORT_URL_OPS, (await load("sharedChatKeyPolicy")).SHARED_KEY_OPS,
  (await load("shareMetadataQueuePolicy")).QUEUE_OPS, (await load("sharedChatDetailsPolicy")).DETAILS_OPS,
  (await load("incognitoChatPolicy")).INCOGNITO_OPS, (await load("anonymousChatPolicy")).ANONYMOUS_OPS,
];
const POLICY = Object.assign({}, ...tables);
// The Rust op answers the well-formed title (JSON/Rust strings cannot carry a lone surrogate);
// the flag-off page path keeps the raw original rule.
POLICY.anonymousTitle = (await load("anonymousChatPolicy")).anonymousTitleWire;

// Same contract as policy.ts runShareStatePolicy.
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

// ── short URL ──
for (const [name, fragment] of [
  ["hash prefix", "#abcdef-ghij"], ["no prefix", "abcdef-ghij"], ["no dash", "abcdefghij"],
  ["token too short", "abcde-ghij"], ["token too long", "abcdefghijklm-ghij"], ["token 12", "abcdefghijkl-ghij"],
  ["key too short", "abcdef-ghi"], ["key 22", `abcdef-${"K".repeat(22)}`], ["key 23", `abcdef-${"K".repeat(23)}`],
  ["symbol in token", "abc_ef-ghij"], ["second dash in key", "abcdef-gh-ij"], ["empty", ""], ["hash only", "#"],
  ["non-ascii key", "abcdef-ghijé"], ["empty key", "abcdef-"],
]) add("shortUrlParseFragment", name, { fragment });
for (const [name, pathname, fragment] of [
  ["path token and key", "/s/Ab12Cd34", "#0Oab12"], ["trailing slash", "/s/Ab12Cd34/", "0Oab12"],
  ["22 char key", "/s/Ab12Cd34", `#${"A".repeat(22)}`], ["key too short", "/s/Ab12Cd34", "#abc"],
  ["key too long", "/s/Ab12Cd34", `#${"A".repeat(23)}`], ["key symbol", "/s/Ab12Cd34", "#ab-cd1"],
  ["legacy fragment on /s/", "/s/", "#abcdef-ghij"], ["legacy fragment other path", "/x", "abcdef-ghij"],
  ["short path token falls back", "/s/Ab12C", "#abcdef-ghij"], ["13 char path token falls back", "/s/Ab12Cd34Ef567", "#abcdef-ghij"],
  ["double slash", "/s/Ab12Cd34//", "#0Oab12"], ["path prefix only", "/s/Ab12Cd34/extra", "#0Oab12"],
  ["path match key invalid blocks legacy", "/s/Ab12Cd34", "#abcdef-ghij"],
]) add("shortUrlParseParts", name, { pathname, fragment });
add("shortUrlBuild", "custom domain", { token: "Ab12Cd34", short_key: "Key123", short_domain: "omts.io", origin: "https://app.example" });
add("shortUrlBuild", "origin", { token: "Ab12Cd34", short_key: "Key123", origin: "https://app.example" });
add("shortUrlBuild", "empty domain falls back", { token: "Ab12Cd34", short_key: "Key123", short_domain: "", origin: "https://app.example" });

// ── shared chat key entries ──
add("sharedKeyEntryMeta", "with url", { chat_id: "c1", share_url: "https://x/share/chat/c1#key=a", now_ms: 1790000000999 });
add("sharedKeyEntryMeta", "no url", { chat_id: "c1", now_ms: 1790000000000 });
add("sharedKeyEntryMeta", "null url", { chat_id: "c1", share_url: null, now_ms: 1999 });
add("sharedKeyEntryMeta", "empty url stays", { chat_id: "c1", share_url: "", now_ms: 5000 });
add("sharedKeyEntryUrl", "no entry", { entry: null });
add("sharedKeyEntryUrl", "no url", { entry: {} });
add("sharedKeyEntryUrl", "null url", { entry: { share_url: null } });
add("sharedKeyEntryUrl", "empty url reads as none", { entry: { share_url: "" } });
add("sharedKeyEntryUrl", "url", { entry: { share_url: "https://x/y" } });
add("sharedKeyLoadable", "mixed rows", { entries: [
  { chat_id: "a", has_key: true }, { chat_id: "", has_key: true }, { chat_id: "b", has_key: false }, { has_key: true }, { chat_id: "c", has_key: true },
] });
add("sharedKeyLoadable", "empty", { entries: [] });

// ── share metadata queue ──
const base = { update_id: "u1", chat_id: "c1", title: "T", summary: "S", now_ms: 1790000000999 };
add("queueChatRecord", "all optional absent", base);
add("queueChatRecord", "all optional set", { ...base, share_cta_text: "cta", encrypted_shared_short_url: "enc", share_pii: true, share_highlights: false });
add("queueChatRecord", "nulls kept", { ...base, title: null, summary: null, share_cta_text: null, encrypted_shared_short_url: null });
add("queueEmbedRecord", "minimal", { update_id: "u2", embed_id: "e1", is_shared: true, now_ms: 2999 });
add("queueEmbedRecord", "with text", { update_id: "u2", embed_id: "e1", is_shared: false, title: "t", description: null, now_ms: 3000 });
const body = { chat_id: "c1", title: "T", summary: "S", is_shared: true };
add("queueChatBody", "summary becomes cta", body);
add("queueChatBody", "cta wins", { ...body, share_cta_text: "cta" });
add("queueChatBody", "empty strings become null", { ...body, title: "", summary: "", share_cta_text: "" });
add("queueChatBody", "null everywhere", { ...body, title: null, summary: null });
add("queueChatBody", "short url null kept", { ...body, encrypted_shared_short_url: null, share_pii: false, share_highlights: true });
add("queueChatBody", "short url set", { ...body, encrypted_shared_short_url: "enc" });
add("queueEmbedBody", "values", { embed_id: "e1", is_shared: true, title: "t", description: "d" });
add("queueEmbedBody", "absent and empty", { embed_id: "e1", is_shared: false, description: "" });
for (const retry_count of [0, 4, 5, 6]) add("queueRetryDecision", `retry ${retry_count}`, { retry_count });
add("queueAttemptOutcome", "success", { success: true, retry_count: 2 });
add("queueAttemptOutcome", "failure increments", { success: false, retry_count: 2 });
add("queueAttemptOutcome", "failure from zero", { success: false, retry_count: 0 });
add("queueResponseSuccess", "true", { body: { success: true } });
add("queueResponseSuccess", "string true is not success", { body: { success: "true" } });
add("queueResponseSuccess", "false", { body: { success: false } });
add("queueResponseSuccess", "no body", { body: null });
add("queueResponseSuccess", "empty body", { body: {} });

// ── shared plan/task pages ──
for (const [name, cursor] of [
  ["none", null], ["valid", { timestamp: 5, id: "x" }], ["zero timestamp", { timestamp: 0, id: "x" }],
  ["negative", { timestamp: -1, id: "x" }], ["fractional", { timestamp: 1.5, id: "x" }], ["empty id", { timestamp: 3, id: "" }],
  ["unsafe integer", { timestamp: 2 ** 53, id: "x" }],
]) add("detailsCursorCheck", name, { kind: "plans", cursor });
const item = (id, updated_at, primary_chat_id = "chat") => ({ id, updated_at, primary_chat_id });
const page = (over = {}) => ({
  items_is_array: true, items: [item("a", 10), item("b", 20)], key_wrappers_is_array: true,
  has_more_before: false, payload_bytes: 500, start_cursor: { timestamp: 10, id: "a" }, oversized_id: null, ...over,
});
const check = (name, over, extra = {}) => add("detailsPageCheck", name, { kind: "plans", chat_id: "chat", page: page(over), ...extra });
check("valid", {});
check("valid tasks kind", {}, { kind: "tasks" });
check("empty page", { items: [], start_cursor: null });
check("items not array", { items_is_array: false, items: undefined });
check("21 items", { items: Array.from({ length: 21 }, (_, i) => item(`i${String(i).padStart(2, "0")}`, i + 1)), start_cursor: { timestamp: 1, id: "i00" } });
check("20 items ok", { items: Array.from({ length: 20 }, (_, i) => item(`i${String(i).padStart(2, "0")}`, i + 1)), start_cursor: { timestamp: 1, id: "i00" } });
check("wrappers not array", { key_wrappers_is_array: false });
check("has_more_before not boolean", { has_more_before: "yes" });
check("payload too large", { payload_bytes: 131073 });
check("payload at limit", { payload_bytes: 131072 });
check("payload negative", { payload_bytes: -1 });
check("payload fractional", { payload_bytes: 1.5 });
check("payload string", { payload_bytes: "5" });
check("payload missing", { payload_bytes: undefined });
check("empty id", { items: [item("", 10)], start_cursor: { timestamp: 10, id: "" } });
check("id not string", { items: [{ id: 5, updated_at: 10, primary_chat_id: "chat" }], start_cursor: { timestamp: 10, id: 5 } });
check("fractional timestamp", { items: [item("a", 10.5)], start_cursor: { timestamp: 10.5, id: "a" } });
check("foreign chat", { items: [item("a", 10, "other")] });
check("null primary chat", { items: [item("a", 10, null)] });
check("missing primary chat", { items: [{ id: "a", updated_at: 10 }] });
check("timestamp order", { items: [item("a", 20), item("b", 10)], start_cursor: { timestamp: 20, id: "a" } });
check("same timestamp id ascending", { items: [item("a", 10), item("b", 10)] });
check("same timestamp id descending", { items: [item("b", 10), item("a", 10)], start_cursor: { timestamp: 10, id: "b" } });
check("duplicate id", { items: [item("a", 10), item("a", 10)] });
check("utf16 order astral before bmp-high", { items: [item("\u{1F600}", 10), item("～", 10)], start_cursor: { timestamp: 10, id: "\u{1F600}" } });
check("utf16 order bmp-high before astral rejected", { items: [item("～", 10), item("\u{1F600}", 10)], start_cursor: { timestamp: 10, id: "～" } });
check("start cursor wrong id", { start_cursor: { timestamp: 10, id: "z" } });
check("start cursor wrong timestamp", { start_cursor: { timestamp: 11, id: "a" } });
check("start cursor missing", { start_cursor: null });
check("more before without cursor or oversized", { items: [], start_cursor: null, has_more_before: true });
check("more before with oversized id", { items: [], start_cursor: null, has_more_before: true, oversized_id: "big" });
check("more before with empty oversized id", { items: [], start_cursor: null, has_more_before: true, oversized_id: "" });
check("cursor advances", {}, { cursor: { timestamp: 11, id: "a" } });
check("cursor equal timestamp bigger id advances", {}, { cursor: { timestamp: 10, id: "b" } });
check("cursor same does not advance", {}, { cursor: { timestamp: 10, id: "a" } });
check("cursor behind does not advance", {}, { cursor: { timestamp: 9, id: "z" } });
const exact = (over = {}) => ({ has_item: true, key_wrappers_is_array: true, item_id: "big", updated_at: 7, primary_chat_id: "chat", ...over });
const ex = (name, over, kind = "plans") => add("detailsExactCheck", name, { kind, chat_id: "chat", id: "big", exact: exact(over) });
ex("valid", {}); ex("valid tasks", {}, "tasks"); ex("no item", { has_item: false }); ex("wrappers not array", { key_wrappers_is_array: false });
ex("id changed", { item_id: "other" }); ex("fractional updated_at", { updated_at: 7.5 }); ex("foreign chat", { primary_chat_id: "other" });
ex("null chat ok", { primary_chat_id: null }); ex("missing updated_at", { updated_at: undefined });
for (const [name, cursor, start_cursor] of [
  ["no cursor", null, { timestamp: 5, id: "a" }], ["advances", { timestamp: 9, id: "a" }, { timestamp: 5, id: "a" }],
  ["same", { timestamp: 5, id: "a" }, { timestamp: 5, id: "a" }], ["later id", { timestamp: 5, id: "a" }, { timestamp: 5, id: "b" }],
  ["no start", { timestamp: 5, id: "a" }, null],
]) add("detailsOversizedAdvance", name, { kind: "tasks", cursor, start_cursor });
add("detailsWrapperStep", "oversized wins", { kind: "plans", window: { has_more_after: true, end_cursor: "e", oversized_key_id: "o" } });
add("detailsWrapperStep", "end cursor", { kind: "plans", window: { has_more_after: true, end_cursor: "e" } });
add("detailsWrapperStep", "neither", { kind: "tasks", window: { has_more_after: true } });
add("detailsWrapperStep", "null cursors", { kind: "tasks", window: { has_more_after: true, end_cursor: null, oversized_key_id: null } });
const adv = (name, window, continuation, kind = "plans") => add("detailsWrapperAdvance", name, { kind, window, continuation });
adv("wrappers not array", { has_more_after: true, end_cursor: "a" }, { key_wrappers_is_array: false, window: { has_more_after: false } });
adv("window missing", { has_more_after: true, end_cursor: "a" }, { key_wrappers_is_array: true });
adv("window null", { has_more_after: true, end_cursor: "a" }, { key_wrappers_is_array: true, window: null });
adv("oversized merges", { has_more_after: true, oversized_key_id: "o" }, { key_wrappers_is_array: true, window: { has_more_after: false, end_cursor: "z", extra: 1 } });
adv("advances", { has_more_after: true, end_cursor: "a" }, { key_wrappers_is_array: true, window: { has_more_after: true, end_cursor: "b" } }, "tasks");
adv("stuck", { has_more_after: true, end_cursor: "a" }, { key_wrappers_is_array: true, window: { has_more_after: true, end_cursor: "a" } });
adv("same cursor but done", { has_more_after: true, end_cursor: "a" }, { key_wrappers_is_array: true, window: { has_more_after: false, end_cursor: "a" } });
adv("same cursor with oversized id", { has_more_after: true, end_cursor: "a" }, { key_wrappers_is_array: true, window: { has_more_after: true, end_cursor: "a", oversized_key_id: "o" } });
adv("undefined vs null end cursor", { has_more_after: true }, { key_wrappers_is_array: true, window: { has_more_after: true, end_cursor: null } });
adv("both undefined end cursor is stuck", { has_more_after: true }, { key_wrappers_is_array: true, window: { has_more_after: true } });
for (const [name, window, count] of [
  ["more after", { has_more_after: true }, 0], ["last allowed round", { has_more_after: true }, 19], ["limit reached", { has_more_after: true }, 20],
  ["done", { has_more_after: false }, 0], ["no window", null, 0],
]) add("detailsWrapperContinue", name, { window, count });
add("detailsWrapperDone", "outstanding", { kind: "plans", window: { has_more_after: true } });
add("detailsWrapperDone", "finished", { kind: "plans", window: { has_more_after: false } });
add("detailsWrapperDone", "no window", { kind: "tasks", window: null });
add("detailsWrapperDedup", "mixed", { seen: ["a", "b"], wrappers: [{ id: "a" }, { id: "c" }, {}, { id: "c" }, { id: "" }, { id: "d" }, { id: null }] });
add("detailsWrapperDedup", "empty", { seen: [], wrappers: [] });

// ── shared sub-chat pages ──
for (const [name, chat_id, before] of [
  ["first page", "chat", null], ["valid before", "chat", { timestamp: 5, id: "x" }], ["empty chat id", "", null],
  ["zero timestamp", "chat", { timestamp: 0, id: "x" }], ["fractional", "chat", { timestamp: 1.5, id: "x" }], ["empty id", "chat", { timestamp: 3, id: "" }],
]) add("subChatCursorCheck", name, { chat_id, before });
const row = (id, created_at, over = {}) => ({ id, parent_id: "chat", is_sub_chat: true, created_at, ...over });
const sub = (name, over) => add("subChatPageCheck", name, { chat_id: "chat", page: {
  items_is_array: true, rows: [row("a", 5), row("b", 6)], has_more_before: false, payload_bytes: 100,
  start_cursor: { timestamp: 5, id: "a" }, oversized_id: undefined, ...over } });
sub("valid", {});
sub("empty page", { rows: [], start_cursor: null });
sub("empty page without cursor field", { rows: [], start_cursor: undefined });
sub("items not array", { items_is_array: false, rows: undefined });
sub("21 rows", { rows: Array.from({ length: 21 }, (_, i) => row(`r${i}`, i + 1)) });
sub("has_more_before not boolean", { has_more_before: 1 });
sub("payload too large", { payload_bytes: 131073 });
sub("payload negative", { payload_bytes: -5 });
sub("row not object", { rows: [null] });
sub("row wrong parent", { rows: [row("a", 5, { parent_id: "other" })] });
sub("row not a sub chat", { rows: [row("a", 5, { is_sub_chat: false })] });
sub("row zero created_at", { rows: [row("a", 0)] });
sub("row fractional created_at", { rows: [row("a", 1.5)] });
sub("row empty id", { rows: [row("", 5)] });
sub("start cursor invalid timestamp", { start_cursor: { timestamp: 0, id: "a" } });
sub("start cursor invalid id", { start_cursor: { timestamp: 5, id: "" } });
sub("start cursor id not string", { start_cursor: { timestamp: 5, id: 5 } });
sub("oversized fetch", { rows: [], has_more_before: true, start_cursor: null, oversized_id: "big" });
sub("oversized with rows", { rows: [row("a", 5)], has_more_before: true, oversized_id: "big" });
sub("oversized without more", { rows: [], has_more_before: false, oversized_id: "big" });
sub("oversized empty id", { rows: [], has_more_before: true, oversized_id: "" });
sub("oversized not string", { rows: [], has_more_before: true, oversized_id: 7 });
sub("oversized null is absent", { rows: [], start_cursor: null, oversized_id: null });
add("subChatOversizedCheck", "valid", { chat_id: "chat", oversized_id: "big", item: row("big", 9) });
add("subChatOversizedCheck", "other id", { chat_id: "chat", oversized_id: "big", item: row("other", 9) });
add("subChatOversizedCheck", "invalid row", { chat_id: "chat", oversized_id: "big", item: row("big", 0) });
add("subChatOversizedCheck", "null row", { chat_id: "chat", oversized_id: "big", item: null });
const fin = (name, input) => add("subChatFinalCheck", name, { rows: [], cursor: null, has_more_before: false, before: null, ...input });
fin("empty", {});
fin("contiguous", { rows: [{ id: "a", created_at: 5 }, { id: "b", created_at: 6 }], cursor: { timestamp: 5, id: "a" } });
fin("cursor mismatch id", { rows: [{ id: "a", created_at: 5 }], cursor: { timestamp: 5, id: "z" } });
fin("cursor mismatch timestamp", { rows: [{ id: "a", created_at: 5 }], cursor: { timestamp: 6, id: "a" } });
fin("rows without cursor", { rows: [{ id: "a", created_at: 5 }], cursor: null });
fin("time order", { rows: [{ id: "a", created_at: 6 }, { id: "b", created_at: 5 }], cursor: { timestamp: 6, id: "a" } });
fin("same time id order", { rows: [{ id: "b", created_at: 5 }, { id: "a", created_at: 5 }], cursor: { timestamp: 5, id: "b" } });
fin("same time duplicate", { rows: [{ id: "a", created_at: 5 }, { id: "a", created_at: 5 }], cursor: { timestamp: 5, id: "a" } });
fin("more before needs cursor", { has_more_before: true });
fin("more before with cursor", { has_more_before: true, cursor: { timestamp: 5, id: "a" } });
fin("advances", { rows: [{ id: "a", created_at: 5 }], cursor: { timestamp: 5, id: "a" }, before: { timestamp: 9, id: "a" } });
fin("does not advance", { rows: [{ id: "a", created_at: 9 }], cursor: { timestamp: 9, id: "a" }, before: { timestamp: 9, id: "a" } });
fin("later cursor does not advance", { rows: [{ id: "a", created_at: 10 }], cursor: { timestamp: 10, id: "a" }, before: { timestamp: 9, id: "a" } });

// ── incognito ──
add("incognitoNormalize", "adds flags", { chats: [{ chat_id: "a" }, { chat_id: "b", is_incognito: false, group_key: "today", title: "T" }] });
add("incognitoNormalize", "empty", { chats: [] });
add("incognitoMetadata", "projection", { chats: [{
  chat_id: "a", is_incognito: false, group_key: "x", encrypted_title: "e", title: "T", category: "c", icon: "i", created_at: 1, updated_at: 2,
  last_edited_overall_timestamp: 3, unread_count: 0, messages_v: 4, title_v: 5, draft_v: 6, encrypted_draft_md: null, encrypted_draft_preview: "p",
  waiting_for_metadata: false, chat_summary: "dropped", encrypted_icon: "dropped", extra: { deep: 1 },
}, { chat_id: "b" }] });
add("incognitoMetadata", "empty", { chats: [] });
add("incognitoUpdateAccepted", "same ids", { message_id: "m", chat_id: "c", next: { message_id: "m", chat_id: "c" } });
add("incognitoUpdateAccepted", "message id changed", { message_id: "m", chat_id: "c", next: { message_id: "n", chat_id: "c" } });
add("incognitoUpdateAccepted", "chat id changed", { message_id: "m", chat_id: "c", next: { message_id: "m", chat_id: "d" } });
add("incognitoUpdateAccepted", "update returned nothing", { message_id: "m", chat_id: "c", next: null });
add("incognitoUpdateAccepted", "missing ids", { message_id: "m", chat_id: "c", next: {} });

// ── anonymous chats ──
add("anonymousNextTimestamp", "no messages", { created_ats: [], fallback: 100 });
add("anonymousNextTimestamp", "newer message wins", { created_ats: [10, 200, 30], fallback: 100 });
add("anonymousNextTimestamp", "older message loses", { created_ats: [10, 20], fallback: 100 });
add("anonymousNextTimestamp", "equal to fallback", { created_ats: [100], fallback: 100 });
add("anonymousNextTimestamp", "null and zero", { created_ats: [null, 0], fallback: 100 });
add("anonymousNextTimestamp", "negative", { created_ats: [-5], fallback: 100 });
const aid = (name, over) => add("anonymousAssistantMessageId", name, { chat_id: "anonymous-0123456789abcdef", user_message_id: "u-1", new_uuid: "uuid-1", ...over });
aid("no response id", {}); aid("empty response id", { response_message_id: "" }); aid("null response id", { response_message_id: null });
aid("same as user", { response_message_id: "u-1" });
aid("streamed keeps id", { response_message_id: "srv-9", streamed: true });
aid("prefixed keeps id", { response_message_id: "anonymous-0123456789abcdef-srv" });
aid("unprefixed gets prefix", { response_message_id: "srv-9" });
aid("short chat id", { chat_id: "abc", response_message_id: undefined });
for (const [name, markdown] of [
  ["plain", "Hello world"], ["leading blank lines", "\n\n  Second line \nthird"], ["only whitespace", "  \n\t\n"], ["empty", ""],
  ["fenced json removed", "```json\n{\"a\":1}\n```\nQuestion here"], ["only fence", "```json\n{}\n```"],
  ["two fences", "a```json x```b```json y```c"], ["unclosed fence kept", "```json\nstill open"],
  ["fence closes at first backticks", "```json {} ``` tail ``` more"], ["non-json fence kept", "```js\ncode\n```"],
  ["exactly 50", "x".repeat(50)], ["51 chars", "y".repeat(51)], ["long line", "z".repeat(120)],
  ["crlf", "Title line\r\nsecond"], ["nbsp trim", "  Title "], ["bom trim", "﻿Title"],
  ["emoji cut in pair", `${"a".repeat(49)}\u{1F600}tail`], ["emoji kept whole", `${"a".repeat(48)}\u{1F600}tail`],
  ["astral line under 50 units", "\u{1F600}".repeat(25)], ["astral line over 50 units", "\u{1F600}".repeat(26)],
  ["unicode space not trimmed by rust whitespace", "\u0085Title"], ["line separator trimmed", " Title "],
]) add("anonymousTitle", name, { markdown });
for (const length of [0, 1, 47, 48, 49, 96, 97, 500, 864, 865, 2000]) add("anonymousChunkEnds", `length ${length}`, { length });
add("anonymousConversationRows", "mixed", { rows: [
  { status: "synced", role: "user", content: "hi" }, { status: "failed", role: "user", content: "x" }, { role: "system", content: "s" },
  { role: "assistant", content: "  " }, { role: "assistant", content: "ok" }, { role: "assistant" }, { role: "user", content: 5 },
  { role: "user", content: " 　" }, { role: "tool", content: "t" }, {},
] });
add("anonymousConversationRows", "empty", { rows: [] });
add("anonymousStripPlain", "removes plaintext fields", { chat: {
  chat_id: "a", title: "T", category: "c", icon: "i", chat_summary: "s", encrypted_title: "e", encrypted_category: "ec", messages_v: 2,
} });
add("anonymousStripPlain", "nothing to strip", { chat: { chat_id: "a" } });

writeFileSync(resolve(root, "packages/openmates-rust/src/web_share_state_ts_vectors.json"), `${JSON.stringify({
  generated_by: "packages/openmates-rust/tests/crypto_fixtures/ts_web_share_state/generate.mjs",
  note: "Outcomes of the TypeScript rules in frontend/packages/ui/src/services/shareState; replayed by web_share_state_tests.rs and shareStateVectors.test.ts.",
  ops,
}, null, 1)}\n`);
console.log(`${Object.keys(ops).length} ops, ${Object.values(ops).reduce((n, c) => n + c.length, 0)} cases`);
