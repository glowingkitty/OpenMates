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

const { childMutationDecisionForTest, resolveWorktreeRouteForTest, taskChildClassificationForTest } = OpenMatesHooks.test;

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

test("only classified writable children can mutate the inherited parent worktree", () => {
  for (const role of ["read_only", "reviewer"]) {
    assert.equal(
      childMutationDecisionForTest({ inheritedParentRoute: true, childRole: role }, "apply_patch").decision,
      "block",
    );
  }
  assert.equal(
    childMutationDecisionForTest({ inheritedParentRoute: true, childRole: "writable" }, "apply_patch").decision,
    "allow",
  );
});

test("general child mutation routes to the parent worktree without creating a child session", async () => {
  const worktreePath = process.cwd();
  const routingData = {
    sessions: {
      parent: {
        opencode_session_id: "ses-parent",
        mode: "feature",
        repo_root: worktreePath,
        repo_name: "control-plane-test",
        worktree: { path: worktreePath, status: "active" },
      },
    },
  };
  const client = {
    session: {
      get: async ({ path: { id } }) => ({
        data: id === "ses-child"
          ? { id, parentID: "ses-parent", agent: "general" }
          : { id: "ses-parent" },
      }),
    },
  };
  const hooks = await OpenMatesHooks({ client, routingData, recordRouting: false, editLease: () => {} });
  const mutation = { args: { patchText: "*** Begin Patch\n*** Update File: scripts/example.js\n*** End Patch" } };

  await hooks["tool.execute.before"]({ tool: "apply_patch", sessionID: "ses-child" }, mutation);

  assert.match(mutation.args.patchText, new RegExp(`Update File: ${worktreePath}/scripts/example\\.js`));
  for (const command of [
    "python3 scripts/sessions.py start --mode bug --task test",
    "python scripts/sessions.py start --mode bug --task test",
    "./scripts/sessions.py start --mode bug --task test",
    "env python3 scripts/sessions.py start --mode bug --task test",
    "python3 -u scripts/../scripts/sessions.py start --mode bug --task test",
    `python3 ${worktreePath}/scripts/sessions.py start --mode bug --task test`,
    "python3 -m scripts.sessions start --mode bug --task test",
    "date && python3 scripts/sessions.py worktree ensure --session child",
  ]) {
    await assert.rejects(
      hooks["tool.execute.before"](
        { tool: "bash", sessionID: "ses-child" },
        { args: { command, workdir: "/model-selected-root" } },
      ),
      /must reuse the parent repository session and worktree/,
    );
  }
});
