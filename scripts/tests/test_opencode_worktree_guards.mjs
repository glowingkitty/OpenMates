#!/usr/bin/env node
/*
 * Tests for the OpenCode worktree guard contract.
 *
 * The plugin remains lightweight; these tests inspect exported helpers without
 * launching OpenCode or mutating the repository.
 */

import assert from "node:assert/strict";
import test from "node:test";
import { OpenMatesHooks } from "../../.opencode/plugins/openmates-hooks.js";

const { editedFilesForTest, rewriteEditArgsForTest, rootGuardDecisionForTest, routingFailureForTest } = OpenMatesHooks.test;

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

test("root guard recommends the mapped sessions.py ID", () => {
  const decision = rootGuardDecisionForTest({
    mode: "strict",
    cwd: "/home/superdev/projects/OpenMates",
    target: "/home/superdev/projects/OpenMates/scripts/sessions.py",
    opencodeSessionID: "ses_test",
    sessions: {
      sessions: {
        "4429": { opencode_session_id: "ses_test" },
      },
    },
  });
  assert.match(decision.message, /worktree ensure --session 4429/);
  assert.doesNotMatch(decision.message, /worktree ensure --session ses_test/);
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

test("root guard blocks root edits by default", () => {
  const decision = rootGuardDecisionForTest({
    cwd: "/home/superdev/projects/OpenMates",
    target: "/home/superdev/projects/OpenMates/scripts/sessions.py",
    sessionID: "ses_test",
  });
  assert.equal(decision.decision, "block");
});

test("root guard blocks root edits whenever an active worktree exists", () => {
  const decision = rootGuardDecisionForTest({
    mode: "warn",
    cwd: "/home/superdev/projects/OpenMates",
    target: "/home/superdev/projects/OpenMates/scripts/sessions.py",
    worktreePath: "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd",
    sessionID: "ses_test",
  });
  assert.equal(decision.decision, "block");
  assert.match(decision.message, /\.openmates-agent-worktrees\/agent-abcd/);
});

test("root guard escape hatch still allows emergency root edits", () => {
  const decision = rootGuardDecisionForTest({
    mode: "off",
    cwd: "/home/superdev/projects/OpenMates",
    target: "/home/superdev/projects/OpenMates/scripts/sessions.py",
    worktreePath: "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd",
    sessionID: "ses_test",
  });
  assert.equal(decision.decision, "allow");
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

test("routing recovery allows spawning an independent OpenCode chat", () => {
  const decision = routingFailureForTest({
    tool: "bash",
    sessionID: "ses_test",
    command: "python3 scripts/sessions.py spawn-chat --name research-x --prompt 'Research X'",
  });
  assert.equal(decision.decision, "allow_recovery");
});

test("edited files resolve relative paths against active worktree cwd", () => {
  const cwd = "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd";
  assert.deepEqual(
    editedFilesForTest({ file_path: "scripts/sessions.py" }, cwd),
    [`${cwd}/scripts/sessions.py`],
  );
});

test("patch file headers resolve relative paths against active worktree cwd", () => {
  const cwd = "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd";
  assert.deepEqual(
    editedFilesForTest(
      {
        patchText: "*** Begin Patch\n*** Update File: docs/example.md\n@@\n-old\n+new\n*** End Patch",
      },
      cwd,
    ),
    [`${cwd}/docs/example.md`],
  );
});

test("relative edit args rewrite to the active session worktree", () => {
  const worktree = "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd";
  assert.deepEqual(
    rewriteEditArgsForTest({ file_path: "scripts/sessions.py" }, worktree),
    { file_path: `${worktree}/scripts/sessions.py` },
  );
});

test("absolute root edit args rewrite to the active session worktree", () => {
  const worktree = "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd";
  assert.deepEqual(
    rewriteEditArgsForTest({ file_path: "/home/superdev/projects/OpenMates/scripts/sessions.py" }, worktree),
    { file_path: `${worktree}/scripts/sessions.py` },
  );
});

test("patch headers rewrite to the active session worktree", () => {
  const worktree = "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd";
  assert.deepEqual(
    rewriteEditArgsForTest(
      {
        patchText: "*** Begin Patch\n*** Update File: docs/example.md\n@@\n-old\n+new\n*** End Patch",
      },
      worktree,
    ),
    {
      patchText: `*** Begin Patch\n*** Update File: ${worktree}/docs/example.md\n@@\n-old\n+new\n*** End Patch`,
    },
  );
});

test("absolute root patch headers rewrite to the active session worktree", () => {
  const worktree = "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd";
  assert.deepEqual(
    rewriteEditArgsForTest(
      {
        patchText: "*** Begin Patch\n*** Update File: /home/superdev/projects/OpenMates/docs/example.md\n@@\n-old\n+new\n*** End Patch",
      },
      worktree,
    ),
    {
      patchText: `*** Begin Patch\n*** Update File: ${worktree}/docs/example.md\n@@\n-old\n+new\n*** End Patch`,
    },
  );
});

test("absolute and already-worktree edit args are not double rewritten", () => {
  const worktree = "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd";
  assert.deepEqual(
    rewriteEditArgsForTest({ file_path: `${worktree}/scripts/sessions.py`, path: "/tmp/example.txt" }, worktree),
    { file_path: `${worktree}/scripts/sessions.py`, path: "/tmp/example.txt" },
  );
});

test("absolute external paths remain outside the active worktree", () => {
  const worktree = "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd";
  assert.deepEqual(
    rewriteEditArgsForTest({ file_path: "/tmp/example.txt", path: "/home/superdev/projects/other/file.ts" }, worktree),
    { file_path: "/tmp/example.txt", path: "/home/superdev/projects/other/file.ts" },
  );
});

test("absolute root traversal paths are not rewritten through the worktree", () => {
  const worktree = "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd";
  const traversal = "/home/superdev/projects/OpenMates/../../tmp/example.txt";
  assert.deepEqual(
    rewriteEditArgsForTest({ file_path: traversal }, worktree),
    { file_path: traversal },
  );
});

test("relative traversal paths are not rewritten through the worktree", () => {
  const worktree = "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd";
  for (const traversal of ["./../outside.txt", "scripts/../../outside.txt"]) {
    assert.deepEqual(
      rewriteEditArgsForTest({ file_path: traversal }, worktree),
      { file_path: traversal },
    );
  }
});

test("relative traversal patch headers are not rewritten through the worktree", () => {
  const worktree = "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd";
  const patchText = "*** Begin Patch\n*** Update File: scripts/../../outside.txt\n@@\n-old\n+new\n*** End Patch";
  assert.deepEqual(
    rewriteEditArgsForTest({ patchText }, worktree),
    { patchText },
  );
});

test("worktree marker traversal back to root is rewritten safely", () => {
  const worktree = "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd";
  const traversal = `${worktree}/../../scripts/sessions.py`;
  assert.deepEqual(
    rewriteEditArgsForTest({ file_path: traversal }, worktree),
    { file_path: `${worktree}/scripts/sessions.py` },
  );
});

test("root guard blocks worktree marker traversal back to root", () => {
  const worktree = "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-abcd";
  const decision = rootGuardDecisionForTest({
    mode: "strict",
    cwd: "/home/superdev/projects/OpenMates",
    target: `${worktree}/../../scripts/sessions.py`,
    sessionID: "ses_test",
  });
  assert.equal(decision.decision, "block");
});
