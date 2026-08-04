#!/usr/bin/env node
/*
 * Contracts for root-hosted OpenCode worktree routing.
 *
 * Web chats remain in the root project while local file, shell, and child tools
 * route through durable sessions.py metadata. Tests keep recovery non-blocking.
 */

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  routeLocalToolArgsForTest,
  routingDecisionForTest,
  routingFailureForTest,
  resolveWorktreeRouteForTest,
} from "../../.opencode/plugins/openmates-hooks.js";

const ROOT = "/home/superdev/projects/OpenMates";
const WORKTREE = `${ROOT}/.openmates-agent-worktrees/agent-abcd`;

const routedSession = (bindingMode = "pending") => ({
  mode: "feature",
  binding_mode: bindingMode,
  worktree: { path: WORKTREE, status: "active", bootstrap: { status: "ready" } },
});

test("active worktree routes regardless of obsolete binding label", () => {
  for (const mode of ["pending", "native", "pilot_fallback", "worktree_routed"]) {
    assert.deepEqual(routingDecisionForTest({ session: routedSession(mode) }), {
      decision: "worktree_routed",
      worktreePath: WORKTREE,
    });
  }
});

test("merged worktree remains routed for post-deploy continuation", () => {
  assert.deepEqual(
    routingDecisionForTest({
      session: { ...routedSession("worktree_routed"), worktree: { path: WORKTREE, status: "merged" } },
    }),
    { decision: "worktree_routed", worktreePath: WORKTREE },
  );
});

test("question sessions remain read-only without a worktree", () => {
  assert.deepEqual(
    routingDecisionForTest({ session: { mode: "question", binding_mode: "legacy_grandfathered" } }),
    { decision: "read_only", worktreePath: "" },
  );
});

test("file tools route explicit, relative, and omitted paths", () => {
  assert.deepEqual(
    routeLocalToolArgsForTest("read", { filePath: `${ROOT}/scripts/sessions.py` }, WORKTREE),
    { filePath: `${WORKTREE}/scripts/sessions.py` },
  );
  assert.deepEqual(
    routeLocalToolArgsForTest("glob", { pattern: "**/*.py" }, WORKTREE),
    { pattern: "**/*.py", path: WORKTREE },
  );
  assert.deepEqual(
    routeLocalToolArgsForTest("grep", { pattern: "binding", path: "scripts" }, WORKTREE),
    { pattern: "binding", path: `${WORKTREE}/scripts` },
  );
});

test("bash always receives the resolved worktree as its real workdir", () => {
  assert.deepEqual(
    routeLocalToolArgsForTest("bash", { command: "pwd", workdir: ROOT }, WORKTREE),
    { command: "pwd", workdir: WORKTREE },
  );
});

test("root absolute paths in shell commands are rejected with an actionable alternative", () => {
  assert.throws(
    () => routeLocalToolArgsForTest("bash", { command: `git -C ${ROOT} status` }, WORKTREE),
    (error) => {
      assert.match(error.message, /Reason:/);
      assert.match(error.message, /Next:/);
      assert.match(error.message, /relative paths/);
      return true;
    },
  );
});

test("relative shell traversal cannot bypass the forced workdir", () => {
  assert.throws(
    () => routeLocalToolArgsForTest("bash", { command: "git -C ../../OpenMates status" }, WORKTREE),
    (error) => {
      assert.match(error.message, /Reason:/);
      assert.match(error.message, /Next:/);
      assert.match(error.message, /relative traversal/);
      return true;
    },
  );
});

test("relative file and search traversal cannot fall back to root", () => {
  for (const [tool, args] of [
    ["read", { filePath: "../outside.py" }],
    ["grep", { pattern: "x", path: "../outside" }],
    ["apply_patch", { patchText: "*** Begin Patch\n*** Update File: ../outside.py\n*** End Patch" }],
  ]) {
    assert.throws(
      () => routeLocalToolArgsForTest(tool, args, WORKTREE),
      (error) => {
        assert.match(error.message, /Reason:/);
        assert.match(error.message, /Next:/);
        return true;
      },
    );
  }
});

test("relative file paths cannot escape through a symlink", (context) => {
  const fixture = mkdtempSync(join(tmpdir(), "openmates-route-"));
  const worktree = join(fixture, "worktree");
  const outside = join(fixture, "outside");
  mkdirSync(worktree);
  mkdirSync(outside);
  symlinkSync(outside, join(worktree, "escape"));
  context.after(() => rmSync(fixture, { recursive: true, force: true }));

  assert.throws(
    () => routeLocalToolArgsForTest("read", { filePath: "escape/file.md" }, worktree),
    (error) => {
      assert.match(error.message, /Reason:/);
      assert.match(error.message, /Next:/);
      return true;
    },
  );
});

test("child session resolves the top-level repository worktree", async () => {
  const data = {
    sessions: {
      abcd: { ...routedSession(), opencode_session_id: "ses_parent" },
    },
  };
  const sessions = {
    ses_child: { id: "ses_child", parentID: "ses_parent" },
    ses_parent: { id: "ses_parent" },
  };
  const result = await resolveWorktreeRouteForTest({
    sessionID: "ses_child",
    data,
    getSession: async (sessionID) => sessions[sessionID],
  });
  assert.equal(result.repositorySessionID, "abcd");
  assert.equal(result.topLevelOpenCodeSessionID, "ses_parent");
  assert.equal(result.worktreePath, WORKTREE);
});

test("restart recovery reconstructs the same route without plugin-local state", async () => {
  const data = {
    sessions: {
      abcd: { ...routedSession("native"), opencode_session_id: "ses_parent" },
    },
  };
  const first = await resolveWorktreeRouteForTest({ sessionID: "ses_parent", data, getSession: async () => null });
  const afterRestart = await resolveWorktreeRouteForTest({ sessionID: "ses_parent", data, getSession: async () => null });
  assert.deepEqual(afterRestart, first);
  assert.equal(afterRestart.worktreePath, WORKTREE);
});

test("unresolved mutation preserves a recovery lane with exact next command", () => {
  const read = routingFailureForTest({ tool: "read", sessionID: "ses_missing" });
  assert.equal(read.decision, "allow_read");

  const edit = routingFailureForTest({ tool: "apply_patch", sessionID: "ses_missing" });
  assert.equal(edit.decision, "block");
  assert.match(edit.message, /Reason:/);
  assert.match(edit.message, /Next:/);
  assert.match(edit.message, /sessions\.py start/);
});
