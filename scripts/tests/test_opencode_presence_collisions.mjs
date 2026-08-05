#!/usr/bin/env node
/*
 * Conflict-only delivery contracts for OpenCode presence.
 * Reads remain allowed, exact writes remain delegated to existing guards, and
 * unrelated sessions receive no appended context or synthetic chat activity.
 * Run: node --test scripts/tests/test_opencode_presence_collisions.mjs.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { childMutationDecisionForTest, readConflictWarningForTest } from "../../.opencode/plugins/openmates-hooks.js";

const data = {
  sessions: {
    a111: { opencode_session_id: "ses-a", task: "edit sessions", worktree: { status: "active" } },
    b222: { opencode_session_id: "ses-b", task: "frontend", worktree: { status: "active" } },
  },
  edit_leases: { "scripts/sessions.py": { session_id: "a111", since: "2026-08-05T00:00:00Z" } },
};
const presence = { sessions: { "ses-a": { execution: "busy", child_role: "unknown" } } };

test("unrelated paths add no context", () => {
  assert.equal(readConflictWarningForTest({ path: "frontend/example.ts", sessionID: "ses-b", data, presence }), "");
});

test("read overlapping a live writer gets one concise non-blocking warning", () => {
  const warning = readConflictWarningForTest({ path: "scripts/sessions.py", sessionID: "ses-b", data, presence });
  assert.match(warning, /OpenMates presence conflict/);
  assert.match(warning, /scripts\/sessions\.py/);
  assert.match(warning, /a111/);
  assert.doesNotMatch(warning, /frontend|full active|prompt/);
});

test("a session and its explicitly read-only child do not conflict", () => {
  const grouped = {
    sessions: {
      "ses-a": { execution: "busy", child_role: "unknown" },
      "ses-child": { execution: "busy", parent_id: "ses-a", child_role: "read_only" },
    },
  };
  assert.equal(readConflictWarningForTest({ path: "scripts/sessions.py", sessionID: "ses-child", data, presence: grouped }), "");
});

test("collision calculation has no prompt or command side effects", () => {
  let calls = 0;
  const sideEffects = { prompt: () => calls++, command: () => calls++ };
  readConflictWarningForTest({ path: "scripts/sessions.py", sessionID: "ses-b", data, presence, sideEffects });
  assert.equal(calls, 0);
});

test("children cannot mutate through an inherited parent route", () => {
  for (const role of ["unknown", "read_only", "reviewer", "writable"]) {
    const decision = childMutationDecisionForTest({ inheritedParentRoute: true, childRole: role }, "apply_patch");
    assert.equal(decision.decision, "block");
    assert.match(decision.message, /Reason:/);
    assert.match(decision.message, /Next:/);
  }
  assert.equal(childMutationDecisionForTest({ inheritedParentRoute: true, childRole: "reviewer" }, "read").decision, "allow");
  assert.equal(childMutationDecisionForTest({ inheritedParentRoute: false, childRole: "writable" }, "apply_patch").decision, "allow");
});

test("inherited children can run known read-only shell diagnostics", () => {
  const route = { inheritedParentRoute: true, childRole: "unknown" };
  const commands = [
    "git status --short",
    "docker exec api python /app/backend/scripts/debug.py chat synthetic-chat-id",
    "docker exec api python /app/backend/scripts/debug.py logs --o2 --query-json '{}'",
    "docker exec api python /app/backend/scripts/debug.py issue synthetic-id --production",
    "docker exec api python /app/backend/scripts/debug.py issue synthetic-id --timeline --production",
    "python3 scripts/issues.py show synthetic-id --env prod",
    "python3 scripts/issues.py timeline synthetic-id --env prod --compact",
    "python3 scripts/issues.py --help",
    "./scripts/issues.py show synthetic-id --env prod",
    "python3 scripts/sessions.py --help",
  ];
  for (const command of commands) {
    assert.equal(childMutationDecisionForTest(route, "bash", command).decision, "allow");
  }
  assert.equal(
    childMutationDecisionForTest(route, "bash", "python3 scripts/sessions.py start --mode bug --task test").decision,
    "block",
  );
  for (const command of [
    "git status --short && touch scripts/child-write.py",
    "git status --short $(touch scripts/child-write.py)",
    "git status --short <(touch scripts/child-write.py)",
    "git diff --output=scripts/child-write.py",
    "sort -o scripts/child-write.py package.json",
    "docker exec api python /app/backend/scripts/debug.py issue synthetic-id --delete --yes",
    "docker exec api python /app/backend/scripts/debug.py logs --upload-update",
    "docker exec api python /app/backend/scripts/debug.py logs --preview-update",
    "docker exec api python /app/backend/scripts/debug.py chat synthetic-id --repair-messages-v",
    "python3 scripts/issues.py findings synthetic-id --env prod",
    "./scripts/issues.py mark synthetic-id --env prod --status resolved",
    "python3 scripts/issues.py link synthetic-id --github issue-url",
    "python3 -c 'from pathlib import Path; Path(\"scripts/child-write.py\").write_text(\"x\")' scripts/issues.py show synthetic-id",
    "python3 -m scripts.issues show synthetic-id",
    "python3 - scripts/issues.py show synthetic-id",
    "docker exec api python -c 'print(1)' /app/backend/scripts/debug.py issue synthetic-id --production",
    "python3 scripts/issues.py show synthetic-id --unknown-write-flag",
    "python3 scripts/issues.py show synthetic-id --env --unknown-write-flag",
    "python3 scripts/issues.py show synthetic-id --env=--unknown-write-flag",
    "python3 scripts/sessions.py --help --unknown-write-flag",
    "./other/issues.py show synthetic-id --env prod",
    "docker exec api python /app/backend/scripts/debug.py logs --query-json --upload-update",
    "docker exec api python /app/backend/scripts/debug.py logs --query-json=--upload-update",
  ]) {
    assert.equal(childMutationDecisionForTest(route, "bash", command).decision, "block");
  }
});
