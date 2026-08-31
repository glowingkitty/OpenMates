#!/usr/bin/env node
/*
 * Event reducer contracts for privacy-minimal OpenCode presence.
 * Fixtures mirror the installed unversioned SDK event union and capability-
 * gated V2 question events. No message text or tool payload is retained.
 * Run: node --test scripts/tests/test_opencode_presence_events.mjs.
 */

// contract-test-file: tooling

import assert from "node:assert/strict";
import test from "node:test";

import { OpenMatesHooks } from "../../.opencode/plugins/openmates-hooks.js";

const { initialPresenceForTest, reconcilePresenceStatesForTest, reducePresenceEventForTest } = OpenMatesHooks.test;

const reduce = (state, event, options = {}) => reducePresenceEventForTest(state, event, { now: "2026-08-05T00:00:00Z", ...options });

test("busy, stream, completion, and idle remain distinct", () => {
  let state = initialPresenceForTest("ses-a");
  state = reduce(state, { type: "session.status", properties: { sessionID: "ses-a", status: { type: "busy" } } });
  state = reduce(state, { type: "message.part.updated", properties: { part: { sessionID: "ses-a", messageID: "msg-a", type: "text", text: "private" }, delta: "secret" } });
  assert.equal(state.execution, "busy");
  assert.equal(state.turn, "streaming");
  assert.equal(state.turn_id, "msg-a");
  assert.doesNotMatch(JSON.stringify(state), /private|secret/);

  state = reduce(state, { type: "message.updated", properties: { info: { id: "msg-a", sessionID: "ses-a", role: "assistant", time: { created: 1, completed: 2 } } } });
  state = reduce(state, { type: "session.status", properties: { sessionID: "ses-a", status: { type: "idle" } } });
  assert.equal(state.execution, "idle");
  assert.equal(state.turn, "completed");
  assert.equal(state.attention, "optional");
});

test("permission and question requests resolve independently by ID", () => {
  let state = initialPresenceForTest("ses-a", { questionCapability: "supported" });
  state = reduce(state, { type: "permission.updated", properties: { id: "perm-1", sessionID: "ses-a", title: "private", metadata: { secret: true } } });
  state = reduce(state, { type: "question.asked", properties: { id: "question-1", sessionID: "ses-a", questions: [{ question: "private" }] } });
  assert.equal(state.attention, "required_both");
  assert.deepEqual(state.pending_permission_ids, ["perm-1"]);
  assert.deepEqual(state.pending_question_ids, ["question-1"]);
  state = reduce(state, { type: "session.status", properties: { sessionID: "ses-a", status: { type: "idle" } } });
  assert.equal(state.attention, "required_both");
  state = reduce(state, { type: "permission.replied", properties: { sessionID: "ses-a", permissionID: "perm-1", response: "once" } });
  assert.equal(state.attention, "required_question");
  state = reduce(state, { type: "question.rejected", properties: { sessionID: "ses-a", requestID: "question-1" } });
  assert.equal(state.attention, "optional");
  assert.doesNotMatch(JSON.stringify(state), /private|secret/);
});

test("unsupported question capability is explicit and idle does not guess", () => {
  let state = initialPresenceForTest("ses-a", { questionCapability: "unsupported" });
  state = reduce(state, { type: "session.status", properties: { sessionID: "ses-a", status: { type: "idle" } } });
  assert.equal(state.capabilities.question, "unsupported");
  assert.equal(state.attention, "optional");
  assert.deepEqual(state.pending_question_ids, []);
});

test("abort remains terminal after a following idle event", () => {
  let state = initialPresenceForTest("ses-a");
  state = reduce(state, { type: "session.status", properties: { sessionID: "ses-a", status: { type: "busy" } } });
  state = reduce(state, { type: "session.error", properties: { sessionID: "ses-a", error: { name: "MessageAbortedError", data: { message: "private" } } } });
  state = reduce(state, { type: "session.status", properties: { sessionID: "ses-a", status: { type: "idle" } } });
  assert.equal(state.execution, "stopped");
  assert.equal(state.turn, "aborted");
});

test("late prior-turn events cannot overwrite a resumed turn", () => {
  let state = initialPresenceForTest("ses-a");
  state = reduce(state, { type: "message.updated", properties: { info: { id: "user-2", sessionID: "ses-a", role: "user", time: { created: 20 } } } });
  state = reduce(state, { type: "message.part.updated", properties: { part: { sessionID: "ses-a", messageID: "assistant-2", type: "text", text: "new" } } });
  state = reduce(state, { type: "message.updated", properties: { info: { id: "assistant-1", sessionID: "ses-a", role: "assistant", time: { created: 10, completed: 30 } } } });
  assert.equal(state.turn_id, "assistant-2");
  assert.equal(state.turn, "streaming");
});

test("late replay of the completed turn's user message cannot leave idle", () => {
  let state = initialPresenceForTest("ses-a");
  state = reduce(state, { type: "message.updated", properties: { info: { id: "assistant-1", parentID: "user-1", sessionID: "ses-a", role: "assistant", time: { created: 2, completed: 3 } } } });
  state = reduce(state, { type: "session.status", properties: { sessionID: "ses-a", status: { type: "idle" } } });
  state = reduce(state, { type: "message.updated", properties: { info: { id: "user-1", sessionID: "ses-a", role: "user", time: { created: 1 } } } });
  assert.equal(state.execution, "idle");
  assert.equal(state.turn, "completed");
});

test("parent grouping never infers a child role", () => {
  let state = initialPresenceForTest("ses-child");
  state = reduce(state, { type: "session.created", properties: { info: { id: "ses-child", parentID: "ses-parent" } } });
  assert.equal(state.parent_id, "ses-parent");
  assert.equal(state.child_role, "unknown");
  state = reduce(state, { type: "openmates.child.role", properties: { sessionID: "ses-child", parentID: "ses-parent", role: "reviewer" } });
  assert.equal(state.child_role, "reviewer");
});

test("session agent metadata explicitly classifies a child before its first tool", () => {
  let state = initialPresenceForTest("ses-child");
  state = reduce(state, {
    type: "session.created",
    properties: { info: { id: "ses-child", parentID: "ses-parent", agent: "explore" } },
  });
  assert.equal(state.parent_id, "ses-parent");
  assert.equal(state.child_role, "read_only");
});

test("session closure clears pending request identities", () => {
  let state = initialPresenceForTest("ses-a", { questionCapability: "supported" });
  state = reduce(state, { type: "permission.updated", properties: { id: "perm-1", sessionID: "ses-a" } });
  state = reduce(state, { type: "question.asked", properties: { id: "question-1", sessionID: "ses-a" } });
  state = reduce(state, { type: "session.deleted", properties: { info: { id: "ses-a" } } });
  assert.equal(state.execution, "closed");
  assert.equal(state.attention, "none");
  assert.deepEqual(state.pending_permission_ids, []);
  assert.deepEqual(state.pending_question_ids, []);
});

test("authoritative reconciliation clears requests resolved while the hook was offline", () => {
  const state = {
    ...initialPresenceForTest("ses-a", { questionCapability: "supported" }),
    execution: "busy",
    turn: "streaming",
    attention: "required_both",
    pending_permission_ids: ["perm-stale", "perm-live"],
    pending_question_ids: ["question-stale", "question-live"],
  };

  const [reconciled] = reconcilePresenceStatesForTest(
    [state],
    { "ses-a": { type: "busy" } },
    {
      now: "2026-08-05T00:00:00Z",
      authoritativePending: {
        permissionIDs: new Set(["perm-live"]),
        questionIDs: new Set(["question-live"]),
      },
    },
  );

  assert.deepEqual(reconciled.pending_permission_ids, ["perm-live"]);
  assert.deepEqual(reconciled.pending_question_ids, ["question-live"]);
  assert.equal(reconciled.attention, "required_both");
});
