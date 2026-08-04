#!/usr/bin/env node
/*
 * Red contracts for OpenCode native session-worktree binding.
 *
 * These tests keep rollout decisions pure and deterministic. The isolated live
 * verifier separately proves the installed OpenCode runtime and HTTP behavior.
 */

import assert from "node:assert/strict";
import test from "node:test";
import {
  editedFilesForBindingForTest,
  nativeBindingDecisionForTest,
} from "../../.opencode/plugins/openmates-hooks.js";

test("native binding disables hidden path rewriting", () => {
  assert.deepEqual(
    nativeBindingDecisionForTest({
      session: { binding_mode: "native", worktree: { path: "/repo/worktree", status: "active" } },
      currentDirectory: "/repo/worktree",
      strict: true,
    }),
    { decision: "native", rewrite: false, block: false, worktreePath: "/repo/worktree" },
  );
});

test("pilot failure uses one visible fallback mode", () => {
  const result = nativeBindingDecisionForTest({
    session: {
      binding_mode: "pilot_fallback",
      binding_failure_reason: "move_session_unavailable",
      worktree: { path: "/repo/worktree", status: "active" },
    },
    currentDirectory: "/repo",
    strict: false,
  });
  assert.equal(result.decision, "pilot_fallback");
  assert.equal(result.rewrite, true);
  assert.equal(result.block, false);
  assert.equal(result.reason, "move_session_unavailable");
});

test("strict unbound session blocks source edits", () => {
  const result = nativeBindingDecisionForTest({
    session: { binding_mode: "pending", worktree: { path: "/repo/worktree", status: "active" } },
    currentDirectory: "/repo",
    strict: true,
  });
  assert.equal(result.decision, "blocked");
  assert.equal(result.rewrite, false);
  assert.equal(result.block, true);
  assert.match(result.reason, /native binding/i);
});

test("recorded native mode blocks when the runtime directory drifted", () => {
  const result = nativeBindingDecisionForTest({
    session: { binding_mode: "native", worktree: { path: "/repo/worktree", status: "active" } },
    currentDirectory: "/repo",
    strict: false,
  });
  assert.equal(result.decision, "blocked");
  assert.equal(result.rewrite, false);
  assert.equal(result.block, true);
});

test("post-edit relative files resolve against the verified binding directory", () => {
  assert.deepEqual(
    editedFilesForBindingForTest(
      { path: "scripts/sessions.py" },
      { decision: "native", worktreePath: "/repo/worktree" },
    ),
    ["/repo/worktree/scripts/sessions.py"],
  );
});
