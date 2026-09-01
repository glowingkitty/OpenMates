#!/usr/bin/env node
/*
 * Contracts for root-hosted OpenCode worktree routing.
 *
 * Web chats remain in the root project while local file, shell, and child tools
 * route through durable sessions.py metadata. Tests keep recovery non-blocking.
 */

// contract-test-file: tooling

import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { OpenMatesHooks } from "../../.opencode/plugins/openmates-hooks.js";

const {
  exactCommitDeployedTestForTest,
  isApprovedControlPlaneAuditCommand,
  routeLocalToolArgsForTest,
  routeLocalToolArgsWithCircuitBreakerForTest,
  routingDecisionForTest,
  routingFailureForTest,
  resolveWorktreeRouteForTest,
} = OpenMatesHooks.test;

const ROOT = "/home/superdev/projects/OpenMates";
const WORKTREE = `${ROOT}/.openmates-agent-worktrees/agent-abcd`;
const prodSshSource = readFileSync(new URL("../../scripts/prod-ssh.sh", import.meta.url), "utf8");

const routedSession = (bindingMode = "pending") => ({
  mode: "feature",
  binding_mode: bindingMode,
  worktree: { path: WORKTREE, status: "active", bootstrap: { status: "ready" } },
});
const routedDecision = (session) => routingDecisionForTest({ session, pathExists: () => true });

test("active worktree routes regardless of obsolete binding label", () => {
  for (const mode of ["pending", "native", "pilot_fallback", "worktree_routed"]) {
    assert.deepEqual(routedDecision(routedSession(mode)), {
      decision: "worktree_routed",
      worktreePath: WORKTREE,
    });
  }
});

test("merged worktree remains routed for post-deploy continuation", () => {
  const decision = routedDecision(
    { ...routedSession("worktree_routed"), worktree: { path: WORKTREE, status: "merged", merged_commit: "abc123456789" } },
  );
  assert.deepEqual(decision, { decision: "worktree_routed", worktreePath: WORKTREE });
});

test("question sessions remain read-only without a worktree", () => {
  assert.deepEqual(
    routingDecisionForTest({ session: { mode: "question", binding_mode: "legacy_grandfathered" } }),
    { decision: "read_only", worktreePath: "" },
  );
});

test("approved control-plane audits are narrowly parsed", () => {
  for (const command of [
    "python3 scripts/audit_opencode_output_quality.py",
    "python3 scripts/audit_opencode_output_quality.py --json --telemetry-days 7",
    "python3 scripts/audit_agent_tooling_parity.py --json",
    "python3 scripts/audit_opencode_spec_workflow.py",
    "python3 scripts/audit_opencode_automation_budget.py --all",
  ]) assert.equal(isApprovedControlPlaneAuditCommand(command), true);

  for (const command of [
    "python3 scripts/opencode_chat_improvement_review.py --dry-run-notify",
    "python3 scripts/audit_opencode_output_quality.py --telemetry-days 999",
    "python3 scripts/audit_agent_tooling_parity.py --write",
    "python3 scripts/audit_opencode_spec_workflow.py && true",
    "python3 scripts/audit_opencode_automation_budget.py --all > report.txt",
  ]) assert.equal(isApprovedControlPlaneAuditCommand(command), false);
});

test("merged verification accepts commit-aware gated spec commands", () => {
  const commit = "a".repeat(40);
  const command = `python3 scripts/tests.py run --spec chat-flow.spec.ts --gate-deploy --require-exact-commit --expected-commit ${commit}`;
  assert.deepEqual(exactCommitDeployedTestForTest(command, commit), { commit, spec: "chat-flow.spec.ts" });
  assert.deepEqual(
    exactCommitDeployedTestForTest(
      `python3 scripts/tests.py run --spec chat-flow.spec.ts --gate-deploy --expected-commit ${commit}`,
      commit,
    ),
    { commit, spec: "chat-flow.spec.ts" },
  );
  assert.deepEqual(
    exactCommitDeployedTestForTest(`${command} --proof-video-profile web-phone --detach`, commit),
    { commit, spec: "chat-flow.spec.ts" },
  );
  for (const rejected of [
    `python3 scripts/tests.py run --spec chat-flow.spec.ts --expected-commit ${commit}`,
    "python3 scripts/tests.py run --spec chat-flow.spec.ts --gate-deploy --expected-commit abc1234",
    `python3 scripts/tests.py run --suite vitest --gate-deploy --expected-commit ${commit}`,
    `${command} --proof-video-profile desktop`,
    `${command} && true`,
    `${command} > report.txt`,
  ]) assert.equal(exactCommitDeployedTestForTest(rejected, commit), null);
  assert.equal(exactCommitDeployedTestForTest(command, "b".repeat(40)), null);
  assert.deepEqual(
    exactCommitDeployedTestForTest(
      `python3 scripts/tests.py run --spec dev-smoke/reachability.spec.ts --gate-deploy --require-exact-commit --expected-commit ${commit}`,
      commit,
    ),
    { commit, spec: "dev-smoke/reachability.spec.ts" },
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

test("runtime lifecycle commands bypass stale session-local coordinators", () => {
  const runtime = "/home/superdev/projects/.openmates-runtime/opencode-server";
  for (const command of [
    "python3 scripts/sessions.py docker restart --session abcd --service api --build",
    "python3 scripts/sessions.py wait-health --session abcd --follow --poll 10 --timeout 900",
    "python3 scripts/sessions.py wait-lock --session abcd --type docker --follow --poll 10",
  ]) {
    assert.deepEqual(
      routeLocalToolArgsForTest("bash", { command, workdir: WORKTREE }, WORKTREE),
      { command, workdir: runtime },
    );
  }
  assert.equal(
    routeLocalToolArgsForTest(
      "bash",
      { command: "python3 scripts/sessions.py deploy --session abcd --title test --message test", workdir: process.cwd() },
      process.cwd(),
    ).workdir,
    process.cwd(),
  );
  assert.throws(
    () => routeLocalToolArgsForTest(
      "bash",
      { command: "python3 scripts/sessions.py status && git checkout -- docs/architecture/compliance/cookies.yml" },
      WORKTREE,
    ),
    /mixed with another shell command/,
  );
});

test("prod SSH helper routes through its root control-plane copy", () => {
  const relativeCommand = 'printf "%s\\n" "000000" | ./scripts/prod-ssh.sh open';
  const relative = routeLocalToolArgsForTest("bash", { command: relativeCommand }, WORKTREE);
  assert.equal(relative.workdir, ROOT);
  assert.equal(relative.command, relativeCommand);

  const rootedCommand = 'printf "%s\\n" "000000" | /home/superdev/projects/OpenMates/scripts/prod-ssh.sh open';
  const rooted = routeLocalToolArgsForTest(
    "bash",
    { command: rootedCommand },
    WORKTREE,
  );
  assert.equal(rooted.command, rootedCommand);
  assert.equal(rooted.workdir, ROOT);

  for (const command of [
    "./scripts/prod-ssh.sh",
    "./scripts/prod-ssh.sh status",
    "  ./scripts/prod-ssh.sh status",
    './scripts/prod-ssh.sh "docker exec api python /app/backend/scripts/debug.py health --log-access"',
    './scripts/prod-ssh.sh "hostname && whoami"',
    "./scripts/prod-ssh.sh docker ps",
    "echo 000000 | ./scripts/prod-ssh.sh open",
    `${WORKTREE}/scripts/prod-ssh.sh status`,
  ]) {
    const routed = routeLocalToolArgsForTest("bash", { command }, WORKTREE);
    assert.equal(routed.command, command);
    assert.equal(routed.workdir, ROOT);
  }
  for (const command of [
    "./scripts/prod-ssh.sh status > .env",
    "./scripts/prod-ssh.sh status 2> .env",
    "./scripts/prod-ssh.sh status > $HOME/projects/OpenMates/.env",
    "true > .env; ./scripts/prod-ssh.sh status",
    "PROD_SSH_PERSIST=5m ./scripts/prod-ssh.sh status",
    "true && ./scripts/prod-ssh.sh status",
    "./scripts/prod-ssh.sh status &",
    './scripts/prod-ssh.sh "$(touch injected)"',
    './scripts/prod-ssh.sh "`touch injected`"',
    "X=y echo 000000 | ./scripts/prod-ssh.sh open",
    "env X=y echo 000000 | ./scripts/prod-ssh.sh open",
    "command echo 000000 | ./scripts/prod-ssh.sh open",
    "builtin printf 000000 | ./scripts/prod-ssh.sh open",
  ]) {
    assert.equal(routeLocalToolArgsForTest("bash", { command }, WORKTREE).workdir, WORKTREE);
  }

  for (const command of [
    "printf '%s' './scripts/prod-ssh.sh'",
    "printf '%s' '; ./scripts/prod-ssh.sh'",
    "printf '%s' '| ./scripts/prod-ssh.sh'",
    "printf '%s' 'line one\n./scripts/prod-ssh.sh'",
  ]) {
    const routed = routeLocalToolArgsForTest("bash", { command }, WORKTREE);
    assert.equal(routed.command, command);
    assert.equal(routed.workdir, WORKTREE);
  }
  for (const command of [
    "test -f /home/superdev/projects/OpenMates/scripts/prod-ssh.sh",
    "/home/superdev/projects/OpenMates/scripts/prod-ssh.sh.bak status",
    "printf '%s' '/home/superdev/projects/OpenMates/scripts/prod-ssh.sh'",
    "cat \\/home/superdev/projects/OpenMates/.env",
    "cat /home/superdev/projects/OpenMates/\\.env",
    "cat \\/home\\/superdev\\/projects\\/OpenMates\\/.env",
    "cat $'\\057home\\057superdev\\057projects\\057OpenMates\\057.env'",
    "cat $'\\x2fhome\\x2fsuperdev\\x2fprojects\\x2fOpenMates\\x2f.env'",
  ]) {
    assert.throws(() => routeLocalToolArgsForTest("bash", { command }, WORKTREE), /session isolation/);
  }
  assert.match(prodSshSource, /rev-parse --path-format=absolute --git-common-dir/);
  assert.match(prodSshSource, /CONTROL_PLANE_ROOT/);
  assert.doesNotMatch(prodSshSource, /OPENMATES_CONTROL_PLANE_ROOT/);
  assert.match(prodSshSource, /Unable to resolve root control-plane checkout/);
});

test("stale-code report generation uses the current root control plane", () => {
  assert.equal(existsSync(join(ROOT, "scripts", "stale_code_daily.py")), true);
  for (const command of [
    "python3 scripts/stale_code_daily.py --dry-run-notify",
    "python3 scripts/stale_code_daily.py --limit 25 --dry-run-notify",
  ]) {
    assert.equal(routeLocalToolArgsForTest("bash", { command }, WORKTREE).workdir, ROOT);
  }
  for (const command of [
    "python3 scripts/stale_code_daily.py",
    "python3 scripts/stale_code_daily.py --install-cron",
    "python3 scripts/stale_code_daily.py --dry-run-notify > report.json",
    "python3 scripts/stale_code_daily.py --root /tmp --dry-run-notify",
    "python3 scripts/stale_code_daily.py --output-dir /tmp --dry-run-notify",
    "python3 scripts/stale_code_daily.py --dry-run-notify && true",
    'python3 scripts/stale_code_daily.py --dry-run-notify "$(touch injected)"',
    "python3 scripts/stale_code_daily.py --root .. --dry-run-notify",
  ]) {
    assert.throws(
      () => routeLocalToolArgsForTest("bash", { command }, WORKTREE),
      /only the report-only dry-run form is allowed/,
    );
  }
});

test("OpenCode improvement review generation uses the current root control plane", () => {
  assert.equal(existsSync(join(ROOT, "scripts", "opencode_chat_improvement_review.py")), true);
  for (const command of [
    "python3 scripts/opencode_chat_improvement_review.py --hours 72 --dry-run-notify",
    "python3 scripts/opencode_chat_improvement_review.py --dry-run-notify --hours 168",
  ]) {
    assert.equal(routeLocalToolArgsForTest("bash", { command }, WORKTREE).workdir, ROOT);
  }
  for (const command of [
    "python3 scripts/opencode_chat_improvement_review.py --hours 72",
    "python3 scripts/opencode_chat_improvement_review.py --dry-run-notify --output /tmp/report.json",
    "python3 scripts/opencode_chat_improvement_review.py --hours 72 --dry-run-notify > report.json",
    "python3 scripts/opencode_chat_improvement_review.py --hours 72 --dry-run-notify && true",
    'python3 scripts/opencode_chat_improvement_review.py --hours 72 --dry-run-notify "$(touch injected)"',
    "python3 scripts/opencode_chat_improvement_review.py --hours 0 --dry-run-notify",
    "python3 scripts/opencode_chat_improvement_review.py --hours 169 --dry-run-notify",
    "python3 scripts/opencode_chat_improvement_review.py --hours 48 --hours 72 --dry-run-notify",
    "python3 scripts/opencode_chat_improvement_review.py --dry-run-notify --dry-run-notify",
  ]) {
    assert.throws(
      () => routeLocalToolArgsForTest("bash", { command }, WORKTREE),
      /only the report-only dry-run form is allowed/,
    );
  }
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

test("proof-video rendering can consume its immutable control-plane source artifact", () => {
  const runtime = "/home/superdev/projects/.openmates-runtime/opencode-server";
  const source = `${ROOT}/test-results/proof-video-source-artifacts/source-id/artifact.webm`;
  const command = `python3 scripts/sessions.py proof-video produce-playwright --source-video ${source}`;
  assert.equal(routeLocalToolArgsForTest("bash", { command }, WORKTREE).workdir, runtime);

  for (const blockedCommand of [
    `python3 scripts/sessions.py proof-video produce-playwright --source-video ${ROOT}/test-results/other.webm`,
    `python3 scripts/sessions.py proof-video produce-playwright --source-video ${source} --contract-path ${ROOT}/contract.json`,
    `python3 scripts/sessions.py status --source-video ${source}`,
  ]) {
    assert.throws(
      () => routeLocalToolArgsForTest("bash", { command: blockedCommand }, WORKTREE),
      /session isolation/,
    );
  }
});

test("repeated isolation blocks stop identical retries", () => {
  const counts = new Map();
  const args = { command: `git -C ${ROOT} status` };
  assert.throws(
    () => routeLocalToolArgsWithCircuitBreakerForTest("bash", args, WORKTREE, { sessionID: "ses-a", counts }),
    (error) => !error.message.includes("Do not retry the same tool call"),
  );
  assert.throws(
    () => routeLocalToolArgsWithCircuitBreakerForTest("bash", args, WORKTREE, { sessionID: "ses-a", counts }),
    /Do not retry the same tool call/,
  );
});

test("root paths inside Python source cannot bypass worktree isolation", () => {
  for (const command of [
    `python3 -c 'print("${ROOT}")'`,
    `python3 -c 'print(open("${ROOT}/.env").read())'`,
  ]) {
    assert.throws(
      () => routeLocalToolArgsForTest("bash", { command }, WORKTREE),
      /root checkout|session isolation/,
    );
  }
});

test("absolute paths cannot target another managed worktree", () => {
  const otherWorktree = `${ROOT}/.openmates-agent-worktrees/agent-other`;
  for (const [tool, args] of [
    ["read", { filePath: `${otherWorktree}/scripts/sessions.py` }],
    ["grep", { pattern: "routing", path: `${otherWorktree}/scripts` }],
    ["apply_patch", { patchText: `*** Begin Patch\n*** Update File: ${otherWorktree}/example.md\n*** End Patch` }],
    ["bash", { command: `git -C ${otherWorktree} status` }],
  ]) {
    assert.throws(
      () => routeLocalToolArgsForTest(tool, args, WORKTREE),
      (error) => {
        assert.match(error.message, /Reason:/);
        assert.match(error.message, /Next:/);
        assert.match(error.message, /another managed worktree|session isolation/);
        return true;
      },
    );
  }
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

test("shared nightly reports remain readable through their worktree link", (context) => {
  const fixture = mkdtempSync(join(tmpdir(), "openmates-route-"));
  const worktree = join(fixture, "worktree");
  const reports = join(fixture, "nightly-reports");
  mkdirSync(join(worktree, "logs"), { recursive: true });
  mkdirSync(reports);
  symlinkSync(reports, join(worktree, "logs", "nightly-reports"));
  context.after(() => rmSync(fixture, { recursive: true, force: true }));

  assert.deepEqual(
    routeLocalToolArgsForTest("read", { filePath: "logs/nightly-reports/stale-code.json" }, worktree),
    { filePath: join(worktree, "logs", "nightly-reports", "stale-code.json") },
  );
  assert.deepEqual(
    routeLocalToolArgsForTest("grep", { pattern: "finding", path: "logs/nightly-reports" }, worktree),
    { pattern: "finding", path: join(worktree, "logs", "nightly-reports") },
  );
});

test("missing approved runtime artifacts fall back to the root control plane", () => {
  for (const [tool, args, expected] of [
    ["read", { filePath: "test-results/last-run.json" }, { filePath: `${ROOT}/test-results/last-run.json` }],
    ["grep", { pattern: "failure", path: "test-results/reports" }, { pattern: "failure", path: `${ROOT}/test-results/reports` }],
    ["read", { filePath: ".claude/sessions.json" }, { filePath: `${ROOT}/.claude/sessions.json` }],
    ["read", { filePath: ".opencode/presence.json" }, { filePath: `${ROOT}/.opencode/presence.json` }],
  ]) {
    assert.deepEqual(routeLocalToolArgsForTest(tool, args, WORKTREE), expected);
  }
});

test("shared env remains unavailable to read and search tools", () => {
  for (const [tool, args] of [
    ["read", { filePath: ".env" }],
    ["read", { filePath: `${ROOT}/.env` }],
    ["grep", { pattern: "TOKEN", path: ".env" }],
    ["grep", { pattern: "TOKEN", path: `${ROOT}/.env` }],
  ]) {
    assert.throws(
      () => routeLocalToolArgsForTest(tool, args, WORKTREE),
      /shared secret runtime resource/,
    );
  }
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
    pathExists: () => true,
  });
  assert.equal(result.repositorySessionID, "abcd");
  assert.equal(result.topLevelOpenCodeSessionID, "ses_parent");
  assert.equal(result.worktreePath, WORKTREE);
});

test("unbound top-level session is not classified as an inherited child", async () => {
  const result = await resolveWorktreeRouteForTest({
    sessionID: "ses_top_level",
    data: { sessions: {} },
    getSession: async () => ({ id: "ses_top_level" }),
  });
  assert.equal(result.decision, "unresolved");
  assert.equal(result.inheritedParentRoute, false);
  assert.equal(result.topLevelOpenCodeSessionID, "ses_top_level");
});

test("restart recovery reconstructs the same route without plugin-local state", async () => {
  const data = {
    sessions: {
      abcd: { ...routedSession("native"), opencode_session_id: "ses_parent" },
    },
  };
  const first = await resolveWorktreeRouteForTest({ sessionID: "ses_parent", data, getSession: async () => null, pathExists: () => true });
  const afterRestart = await resolveWorktreeRouteForTest({ sessionID: "ses_parent", data, getSession: async () => null, pathExists: () => true });
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

test("merged worktree failure uses the stale-worktree recovery message", () => {
  const failure = routingFailureForTest({
    tool: "apply_patch",
    sessionID: "ses_merged",
    routeMessage: "merged worktree is stale",
  });
  assert.deepEqual(failure, { decision: "block", message: "merged worktree is stale" });
});

test("unresolved sessions can run the bounded OpenCode workflow audit", () => {
  const audit = routingFailureForTest({
    tool: "bash",
    sessionID: "ses_missing",
    command: "python3 scripts/audit_opencode_output_quality.py --telemetry-days 1 --json",
  });
  assert.equal(audit.decision, "allow_recovery");
});

test("unresolved sessions can run the bounded report-only OpenCode review", () => {
  const review = routingFailureForTest({
    tool: "bash",
    sessionID: "ses_missing",
    command: "python3 scripts/opencode_chat_improvement_review.py --hours 48 --dry-run-notify",
  });
  assert.equal(review.decision, "allow_recovery");
  assert.equal(routingFailureForTest({
    tool: "bash",
    sessionID: "ses_missing",
    command: "python scripts/opencode_chat_improvement_review.py --dry-run-notify",
  }).decision, "allow_recovery");
});

test("question sessions can run bounded observational shell commands without a worktree", () => {
  for (const command of [
    "git blame -L 10,20 -- scripts/sessions.py",
    "git show origin/dev:scripts/sessions.py",
    "python3 scripts/issues.py show synthetic-id --env dev --full --json",
    "python3 scripts/tests.py status --json",
    "gh run view 31112777028 --log-failed",
  ]) {
    assert.equal(
      routingFailureForTest({ tool: "bash", sessionID: "ses-question", command }).decision,
      "allow_recovery",
    );
  }
  assert.equal(
    routingFailureForTest({
      tool: "bash",
      sessionID: "ses-question",
      command: "python3 scripts/sessions.py deploy --session abcd --title unsafe",
    }).decision,
    "block",
  );
});
