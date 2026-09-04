#!/usr/bin/env node
/*
 * OpenCode hook contracts for request-only OpenMates Task context and
 * response-boundary reconciliation. These tests use exported pure helpers so
 * they cannot call the live CLI, mutate sessions, or prompt a real chat.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { OpenMatesHooks } from "../../.opencode/plugins/openmates-hooks.js";


const activeSnapshot = {
  decision: "resume_active",
  active: {
    task_id: "uuid-1",
    short_id: "TASK-1",
    title: "Implement the bridge",
    description: "Full private description",
    latest_instruction: "Keep plaintext request-only",
    status: "in_progress",
    version: 4,
    blocked_reason_code: null,
    blocked_reason: null,
  },
  remaining: [
    { short_id: "TASK-2", title: "Restart verification", status: "todo" },
  ],
};


test("request context contains full active details and title-only remaining Tasks", () => {
  const { taskContextSystemTextForTest } = OpenMatesHooks.test;
  const text = taskContextSystemTextForTest(activeSnapshot);

  assert.match(text, /Implement the bridge/);
  assert.match(text, /Full private description/);
  assert.match(text, /Keep plaintext request-only/);
  assert.match(text, /TASK-2.*Restart verification.*todo/);
  assert.doesNotMatch(text, /remaining.*description/i);
});


test("empty chats instruct the model to create tracking for implicit non-trivial work", () => {
  const { taskContextSystemTextForTest } = OpenMatesHooks.test;
  const text = taskContextSystemTextForTest({ decision: "no_work", active: null, remaining: [] });

  assert.match(text, /non-trivial multi-step/i);
  assert.match(text, /create.*openmates_task/i);
  assert.match(text, /before the first product mutation/i);
  assert.match(text, /simple informational.*do not create/i);
});


test("failed Task context tells the model not to retry or create another record", () => {
  const { taskContextSystemTextForTest } = OpenMatesHooks.test;
  const text = taskContextSystemTextForTest({
    decision: "failed_closed",
    active: null,
    remaining: [],
    error: "Passkey verification required (location_change). Please run openmates login.",
  });

  assert.match(text, /temporarily unavailable/i);
  assert.match(text, /do not retry/i);
  assert.match(text, /openmates login/i);
  assert.doesNotMatch(text, /create an AI-assigned record/i);
});


test("the first repository mutation requires an implicit Task when none exists", () => {
  const { implicitTaskMutationPayloadForTest } = OpenMatesHooks.test;
  const empty = { decision: "no_work", active: null, remaining: [] };

  assert.deepEqual(
    implicitTaskMutationPayloadForTest(empty, {
      tool: "apply_patch",
      sessionTitle: "Implement account settings",
    }),
    {
      action: "create",
      title: "Implement account settings",
      description: "Automatically created before the first repository mutation in this OpenCode chat.",
      status: "in_progress",
    },
  );
  assert.equal(
    implicitTaskMutationPayloadForTest(empty, { tool: "read", sessionTitle: "Inspect settings" }),
    null,
  );
  assert.equal(
    implicitTaskMutationPayloadForTest(activeSnapshot, { tool: "apply_patch", sessionTitle: "Existing work" }),
    null,
  );
});


test("only completed successful top-level assistant messages stage reconciliation", () => {
  const { taskBridgeCompletionForTest } = OpenMatesHooks.test;
  const completed = {
    type: "message.updated",
    properties: {
      info: { id: "msg-1", role: "assistant", time: { completed: 123 } },
      sessionID: "ses-parent",
    },
  };

  assert.deepEqual(taskBridgeCompletionForTest(completed, { topLevelSessionID: "ses-parent" }), {
    sessionID: "ses-parent",
    messageID: "msg-1",
  });
  assert.equal(taskBridgeCompletionForTest(completed, { topLevelSessionID: "ses-other" }), null);
  assert.equal(taskBridgeCompletionForTest({ ...completed, properties: { ...completed.properties, info: { ...completed.properties.info, error: "aborted" } } }, { topLevelSessionID: "ses-parent" }), null);
});


test("idle reconciliation is suppressed for user-controlled and terminal states", () => {
  const { taskBridgeSuppressedForTest } = OpenMatesHooks.test;

  assert.equal(taskBridgeSuppressedForTest({ execution: "idle", turn: "completed", pending_permission_ids: [], pending_question_ids: [] }), false);
  assert.equal(taskBridgeSuppressedForTest({ execution: "idle", turn: "completed", pending_permission_ids: ["p"], pending_question_ids: [] }), true);
  assert.equal(taskBridgeSuppressedForTest({ execution: "idle", turn: "completed", pending_permission_ids: [], pending_question_ids: ["q"] }), true);
  assert.equal(taskBridgeSuppressedForTest({ execution: "stopped", turn: "completed", pending_permission_ids: [], pending_question_ids: [] }), true);
  assert.equal(taskBridgeSuppressedForTest({ execution: "idle", turn: "aborted", pending_permission_ids: [], pending_question_ids: [] }), true);
});


test("Task continuation uses an internal instruction without decrypted Task text", () => {
  const { taskContinuationPromptForTest } = OpenMatesHooks.test;
  const prompt = taskContinuationPromptForTest({
    operation_type: "task_ready",
    operation_key: "hash:uuid-1:4:1",
    next_action: "Continue the active OpenMates Task from request-only context.",
  });

  assert.match(prompt, /Continue the active OpenMates Task/);
  assert.doesNotMatch(prompt, /Implement the bridge|Full private description/);
});


test("request context is fetched once per turn and refreshed for compaction", async () => {
  const calls = [];
  const hooks = await OpenMatesHooks({
    routingData: {
      sessions: {
        bridge: {
          opencode_session_id: "ses-parent",
          binding_mode: "worktree_routed",
          worktree: { path: "/home/superdev/projects/.openmates-agent-worktrees/bridge", status: "active" },
        },
      },
    },
    recordRouting: false,
    taskBridge: async (action, sessionID, options = {}) => {
      calls.push({ action, sessionID, options });
      return activeSnapshot;
    },
  });
  const first = { system: [] };
  const second = { system: [] };
  await hooks["experimental.chat.system.transform"]({ sessionID: "ses-parent" }, first);
  await hooks["experimental.chat.system.transform"]({ sessionID: "ses-parent" }, second);
  const compacted = { context: [] };
  await hooks["experimental.session.compacting"]({ sessionID: "ses-parent" }, compacted);

  assert.equal(calls.filter((call) => call.action === "context").length, 2);
  assert.match(first.system[0], /OpenMates authoritative Task context/);
  assert.match(compacted.context[0], /OpenMates authoritative Task context/);
});
