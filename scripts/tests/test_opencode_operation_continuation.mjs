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

test("monitor discovery stays scoped and recovers persisted idle coordinators", () => {
  const data = { sessions: {
    own: { repo_root: "/project", opencode_session_id: "ses_own", orchestration_monitor: { status: "active" } },
    other: { repo_root: "/other", opencode_session_id: "ses_other", orchestration_monitor: { status: "active" } },
    stopped: { repo_root: "/project", opencode_session_id: "ses_stop", orchestration_monitor: { status: "stopped" } },
  } };
  assert.deepEqual(OpenMatesHooks.test.monitorSessionsForTest(data, "/project"), ["ses_own"]);
});

test("monitor waits through user questions and busy work, then resumes", () => {
  const state = { execution: "idle", turn: "completed", pending_permission_ids: [], pending_question_ids: [] };
  const allowed = OpenMatesHooks.test.monitorDeliveryAllowedForTest;
  assert.equal(allowed(state, undefined), true);
  assert.equal(allowed(state, { type: "busy" }), false);
  assert.equal(allowed(state, { type: "retry" }), false);
  assert.equal(allowed({ ...state, pending_question_ids: ["q"] }), false);
  assert.equal(allowed({ ...state, pending_permission_ids: ["p"] }), false);
  assert.equal(allowed({ ...state, turn: "aborted" }), false);
  assert.equal(allowed({ ...state, execution: "unknown" }), false);
  assert.equal(allowed(state, undefined), true);
});

test("heartbeat uses durable tick before delivery and preserves questions", async () => {
  const events = [];
  let current = { execution: "idle", turn: "completed", pending_question_ids: ["q"] };
  const options = { state: () => current,
    command: async action => events.push(action), deliver: async () => events.push("deliver") };
  await OpenMatesHooks.test.runMonitorCheckpointForTest("ses_coordinator", options);
  assert.deepEqual(events, []);
  current = { ...current, pending_question_ids: [] };
  await OpenMatesHooks.test.runMonitorCheckpointForTest("ses_coordinator", options);
  assert.deepEqual(events, ["tick", "deliver"]);
  events.length = 0;
  current = { ...current, turn: "aborted" };
  await OpenMatesHooks.test.runMonitorCheckpointForTest("ses_coordinator", options);
  assert.deepEqual(events, ["stop"]);
});

test("a user turn arriving during tick suppresses delivery", async () => {
  let current = { execution: "idle", turn: "completed" };
  let delivered = false;
  await OpenMatesHooks.test.runMonitorCheckpointForTest("ses_coordinator", {
    state: () => current,
    command: async () => { current = { execution: "busy", turn: "streaming" }; },
    deliver: async () => { delivered = true; },
  });
  assert.equal(delivered, false);
});

test("scheduler instructions are internal text parts, ordinary continuations unchanged", () => {
  const parts = OpenMatesHooks.test.continuationPartsForTest({ operation_type: "monitor_ready", next_action: "Check workers" });
  assert.equal(parts[0].synthetic, true);
  assert.equal(parts[0].metadata.openmates_monitor, true);
  assert.equal(parts[0].text, "Check workers");
  assert.equal(OpenMatesHooks.test.continuationPartsForTest({ operation_type: "task_ready", next_action: "Continue" })[0].synthetic, undefined);
});

test("every coordinator turn receives current authored reporting rules despite skill cache", () => {
  const data = { sessions: { owner: { opencode_session_id: "ses_coordinator", orchestration_monitor: { status: "active" } } } };
  const skill = "## Every reply: show current progress\nEvery reply needs a table and highlighted input.\n## Meeting style and task records\nOther instructions";
  const reporting = OpenMatesHooks.test.orchestrationReportingTextForTest;
  assert.match(reporting("ses_coordinator", data, skill), /Every reply needs a table/);
  assert.doesNotMatch(reporting("ses_coordinator", data, skill), /Other instructions/);
  assert.equal(reporting("ses_worker", data, skill), "");
  assert.match(reporting("ses_coordinator", data, skill.replace("a table", "a fresh progress table")), /fresh progress table/);
});

test("reviewed remote patch command passes source guard without allowing raw source writes", () => {
  assert.doesNotThrow(() => OpenMatesHooks.test.guardBash("python3 scripts/apple_remote.py apply-patch --repo /Users/example/project --patch /tmp/review.patch --expected /tmp/hashes.json --apply", "ses_worker"));
  assert.throws(() => OpenMatesHooks.test.guardBash("git apply /tmp/review.patch", "ses_worker"), /source write guard/);
  assert.throws(() => OpenMatesHooks.test.guardBash("python3 scripts/apple_remote.py run -- patch --dry-run -p0 -d /Users/example/project < /tmp/review.patch", "ses_worker"), /source write guard/);
});
