#!/usr/bin/env node
/*
 * Tests for the OpenCode worktree guard contract.
 *
 * The plugin remains lightweight; these tests inspect exported helpers without
 * launching OpenCode or mutating the repository.
 */

import assert from "node:assert/strict";
import test from "node:test";
import { rootGuardDecisionForTest } from "../../.opencode/plugins/openmates-hooks.js";

test("root guard warns in transitional mode", () => {
  const decision = rootGuardDecisionForTest({
    mode: "warn",
    cwd: "/home/superdev/projects/OpenMates",
    target: "/home/superdev/projects/OpenMates/scripts/sessions.py",
    sessionID: "ses_test",
  });
  assert.equal(decision.decision, "warn");
  assert.match(decision.message, /worktree/);
});

test("root guard blocks strict root edits", () => {
  const decision = rootGuardDecisionForTest({
    mode: "strict",
    cwd: "/home/superdev/projects/OpenMates",
    target: "/home/superdev/projects/OpenMates/scripts/sessions.py",
    sessionID: "ses_test",
  });
  assert.equal(decision.decision, "block");
});

test("root guard allows edits outside root", () => {
  const decision = rootGuardDecisionForTest({
    mode: "strict",
    cwd: "/home/superdev/projects/OpenMates/.agent-worktrees/agent-abcd",
    target: "/home/superdev/projects/OpenMates/.agent-worktrees/agent-abcd/scripts/sessions.py",
    sessionID: "ses_test",
  });
  assert.equal(decision.decision, "allow");
});
