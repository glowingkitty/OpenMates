#!/usr/bin/env node
/*
 * Contracts for automatic task-child role classification.
 *
 * Diagnostic children share the parent's routed worktree but remain read-only.
 * Classification uses explicit child session agent metadata before the first
 * tool call, then reconciles the same role from completed task metadata.
 */

// contract-test-file: tooling

import assert from "node:assert/strict";
import test from "node:test";

import { OpenMatesHooks } from "../../.opencode/plugins/openmates-hooks.js";

const {
  childMutationDecisionForTest,
  hookRuntimeDiagnosticForTest,
  repeatedRoutingFailureMessageForTest,
  resolveWorktreeRouteForTest,
  taskChildClassificationForTest,
} = OpenMatesHooks.test;

test("task child derives its role from explicit session agent metadata before completion", async () => {
  const data = {
    sessions: {
      parent: {
        opencode_session_id: "ses-parent",
        mode: "feature",
        worktree: {
          path: "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-parent",
          status: "active",
        },
      },
    },
  };
  for (const [agent, expectedRole] of [
    ["explore", "read_only"],
    ["code-reviewer", "reviewer"],
    ["general", "writable"],
    ["unclassified-agent", "unknown"],
  ]) {
    const route = await resolveWorktreeRouteForTest({
      sessionID: `ses-${agent}`,
      data,
      childRoles: {},
      getSession: async (sessionID) => sessionID === `ses-${agent}`
        ? { id: sessionID, parentID: "ses-parent", agent }
        : { id: "ses-parent" },
    });
    assert.equal(route.childRole, expectedRole);
    assert.equal(route.inheritedParentRoute, true);
  }
});

test("task result metadata classifies diagnostic, review, and writable children", () => {
  for (const [subagentType, role] of [
    ["code-reviewer", "reviewer"],
    ["explore", "read_only"],
    ["general", "writable"],
    ["issue-forensics", "read_only"],
    ["e2e-test-investigator", "read_only"],
  ]) {
    assert.deepEqual(
      taskChildClassificationForTest(
        { tool: "task", sessionID: "ses-parent", args: { subagent_type: subagentType } },
        { metadata: { parentSessionId: "ses-parent", sessionId: "ses-child" } },
      ),
      { sessionID: "ses-child", parentID: "ses-parent", role },
    );
  }
});

test("task classification rejects incomplete, mismatched, and unknown metadata", () => {
  const validInput = { tool: "task", sessionID: "ses-parent", args: { subagent_type: "explore" } };
  assert.equal(taskChildClassificationForTest(validInput, { metadata: {} }), null);
  assert.equal(
    taskChildClassificationForTest(validInput, { metadata: { parentSessionId: "other", sessionId: "ses-child" } }),
    null,
  );
  assert.equal(
    taskChildClassificationForTest(
      { ...validInput, args: { subagent_type: "unclassified-agent" } },
      { metadata: { parentSessionId: "ses-parent", sessionId: "ses-child" } },
    ),
    null,
  );
});

test("classified children still cannot mutate the inherited parent worktree", () => {
  for (const role of ["read_only", "reviewer", "writable"]) {
    assert.equal(
      childMutationDecisionForTest({ inheritedParentRoute: true, childRole: role }, "apply_patch").decision,
      "block",
    );
  }
});

test("hook runtime diagnostics distinguish current and stale loaded source", () => {
  assert.deepEqual(
    hookRuntimeDiagnosticForTest("a".repeat(64), "a".repeat(64)),
    { runtimeHash: "a".repeat(64), sourceHash: "a".repeat(64), status: "current" },
  );
  assert.equal(
    hookRuntimeDiagnosticForTest("a".repeat(64), "b".repeat(64)).status,
    "stale_runtime",
  );
  assert.equal(hookRuntimeDiagnosticForTest("unavailable", "unavailable").status, "unavailable");
});

test("second routing block stops blind retries and reports runtime attestation", () => {
  const first = repeatedRoutingFailureMessageForTest("blocked", 1, {
    runtimeHash: "a".repeat(64),
    sourceHash: "a".repeat(64),
    status: "current",
  });
  const second = repeatedRoutingFailureMessageForTest("blocked", 2, {
    runtimeHash: "a".repeat(64),
    sourceHash: "b".repeat(64),
    status: "stale_runtime",
  });

  assert.equal(first, "blocked");
  assert.match(second, /Do not retry the same tool call/);
  assert.match(second, /stale_runtime/);
  assert.match(second, /restart the OpenCode runtime/);
});
