// contract-test-file: tooling
// Offline producer for tests/fixtures/ts_voice_call_lifecycle.json. Transpiles the
// ACTUAL web voiceCallLifecycleEvent.ts and runs its parser/id function plus the
// content shape `recordCallLifecycle` builds. No network or account data.
// Usage (repo root): node packages/openmates-rust/tests/fixtures/ts_voice_call_lifecycle.generate.cjs
"use strict";
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const { createRequire } = require("node:module");
const root = path.resolve(__dirname, "../../../..");
const ts = createRequire(process.env.OM_UI_PACKAGE_JSON || path.join(root, "frontend/packages/ui/package.json"))("typescript");
const src = fs.readFileSync(path.join(root, "frontend/packages/ui/src/services/voiceCallLifecycleEvent.ts"), "utf8");
const js = ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
const mod = { exports: {} };
vm.runInNewContext(js, { module: mod, exports: mod.exports });
const { parseVoiceCallHistoryEvent, voiceCallLifecycleMessageId } = mod.exports;
const build = (type, callId, occurredAt, secs) => JSON.stringify({ schema_version: 1, type: "voice_call", action: type,
  call_id: callId, created_at: occurredAt, active_elapsed_seconds: Math.floor(secs) });
const builds = [["started", "call_abc12345", 1790000000, 0], ["ended", "call_abc12345", 1790000100, 61.9], ["ended", "A-b_c-d_e", 1, 3]]
  .map(([a, c, t, s]) => ({ action: a, call_id: c, occurred_at: t, elapsed: s, content: build(a, c, t, s), message_id: voiceCallLifecycleMessageId(c, a) }));
const parses = [
  build("started", "call_abc12345", 1790000000, 0),
  build("ended", "call_abc12345", 1790000100, 61.9),
  '{"schema_version":2,"type":"voice_call","action":"started","call_id":"call_abc12345","created_at":1,"active_elapsed_seconds":0}',
  '{"schema_version":1,"type":"other","action":"started","call_id":"call_abc12345","created_at":1,"active_elapsed_seconds":0}',
  '{"schema_version":1,"type":"voice_call","action":"paused","call_id":"call_abc12345","created_at":1,"active_elapsed_seconds":0}',
  '{"schema_version":1,"type":"voice_call","action":"started","call_id":"short","created_at":1,"active_elapsed_seconds":0}',
  '{"schema_version":1,"type":"voice_call","action":"started","call_id":"call_abc12345","created_at":0,"active_elapsed_seconds":0}',
  '{"schema_version":1,"type":"voice_call","action":"started","call_id":"call_abc12345","created_at":1}',
  '{"schema_version":1,"type":"voice_call","action":"started","call_id":"call_abc12345","created_at":1,"active_elapsed_seconds":-1}',
  '{"schema_version":1,"type":"voice_call","action":"started","call_id":"call_abc12345","created_at":1.5,"active_elapsed_seconds":0}',
  '{"schema_version":1,"type":"voice_call","action":"ended","call_id":"call_abc12345","created_at":5,"active_elapsed_seconds":2,"extra":true}',
  "not json",
].map((content) => { const e = parseVoiceCallHistoryEvent(content); return { content, notice: e ? { action: e.action, call_id: e.call_id, created_at: e.created_at, active_elapsed_seconds: e.active_elapsed_seconds } : null }; });
fs.writeFileSync(path.join(__dirname, "ts_voice_call_lifecycle.json"), JSON.stringify({ builds, parses }, null, 2) + "\n");
