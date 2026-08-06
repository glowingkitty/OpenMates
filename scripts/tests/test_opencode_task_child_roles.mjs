#!/usr/bin/env node
/*
 * Contracts for automatic task-child role classification.
 *
 * Diagnostic children share the parent's routed worktree but remain read-only.
 * Classification uses task result metadata and never infers writable ownership.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { OpenMatesHooks } from "../../.opencode/plugins/openmates-hooks.js";

const { childMutationDecisionForTest, taskChildClassificationForTest } = OpenMatesHooks.test;

test("task result metadata classifies diagnostic and review children", () => {
  for (const [subagentType, role] of [
    ["code-reviewer", "reviewer"],
    ["explore", "read_only"],
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
