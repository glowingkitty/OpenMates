// Bounded deterministic OpenCode continuation contract tests.
// Purpose: allow typed operation resumption without generic idle prompting.
// Security: pure helpers receive only sanitized operation metadata.
// Run: node --test scripts/tests/test_opencode_operation_continuation.mjs.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { OpenMatesHooks } from "../../.opencode/plugins/openmates-hooks.js";

const {
  continuationSignalForTest,
  continuationSuppressedForTest,
  reconcilePresenceStatesForTest,
} = OpenMatesHooks.test;
const source = readFileSync(new URL("../../.opencode/plugins/openmates-hooks.js", import.meta.url), "utf8");

test("typed ready signals carry bounded continuation metadata", () => {
  const payload = {
    signal: "OPENMATES_HEALTH_READY",
    operation_type: "health_ready",
    operation_key: "api-health",
    next_action: "Continue exact verification.",
  };
  assert.deepEqual(continuationSignalForTest(`progress\n${JSON.stringify(payload)}\nready`), payload);
  assert.equal(continuationSignalForTest('{"signal":"UNRELATED"}'), null);
  assert.equal(continuationSignalForTest("not json"), null);
});

test("stop failure permission and question states suppress continuation", () => {
  const base = { turn: "completed", execution: "idle", pending_permission_ids: [], pending_question_ids: [] };
  assert.equal(continuationSuppressedForTest(base), false);
  assert.equal(continuationSuppressedForTest({ ...base, turn: "aborted" }), true);
  assert.equal(continuationSuppressedForTest({ ...base, execution: "error" }), true);
  assert.equal(continuationSuppressedForTest({ ...base, pending_permission_ids: ["permission"] }), true);
  assert.equal(continuationSuppressedForTest({ ...base, pending_question_ids: ["question"] }), true);
});

test("presence timer cannot perpetually renew stale busy records", () => {
  const states = [
    { session_id: "stale", execution: "busy", turn: "streaming", pending_permission_ids: [], pending_question_ids: [] },
    { session_id: "active", execution: "busy", turn: "streaming", pending_permission_ids: [], pending_question_ids: [] },
  ];
  const reconciled = reconcilePresenceStatesForTest(states, { active: { type: "busy" } }, { now: "2026-08-27T13:40:00Z" });
  assert.equal(reconciled.find((item) => item.session_id === "stale").execution, "idle");
  assert.equal(reconciled.find((item) => item.session_id === "active").execution, "busy");
  assert.equal(reconciled.find((item) => item.session_id === "active").heartbeat_at, "2026-08-27T13:40:00Z");
});

test("an older absent status snapshot cannot erase a fresh busy event", () => {
  const now = "2026-08-27T13:40:00Z";
  const fresh = {
    session_id: "fresh",
    execution: "busy",
    turn: "streaming",
    heartbeat_at: now,
    updated_at: now,
    pending_permission_ids: [],
    pending_question_ids: [],
  };

  assert.deepEqual(reconcilePresenceStatesForTest([fresh], {}, { now }), []);
  const later = reconcilePresenceStatesForTest([fresh], {}, { now: "2026-08-27T13:40:30Z" });
  assert.equal(later[0].execution, "idle");
});

test("idle delivery claims durable operation before prompting", () => {
  assert.match(source, /continuationCommand\("claim", sessionID\)/);
  assert.match(source, /messageID: record\.message_id/);
  assert.match(source, /client\.session\.promptAsync\(/);
  assert.doesNotMatch(source, /client\.session\.prompt\(\{/);
  assert.match(source, /automaticDeliverySessions\.has\(sessionID\)/);
  assert.match(source, /continuationCommand\("ack", sessionID\)/);
  assert.match(source, /continuationCommand\("release", sessionID\)/);
});
