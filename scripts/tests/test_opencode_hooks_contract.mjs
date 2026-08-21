// OpenCode hook source contracts.
// Ensures stale-read checks receive pre-execution input arguments.
// Ensures local Apple audit findings keep their blocking exit status.
// Uses static source checks because the plugin host owns event dispatch.
// Run: node --test scripts/tests/test_opencode_hooks_contract.mjs.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import * as pluginModule from "../../.opencode/plugins/openmates-hooks.js";
import * as cliAutoLoginPluginModule from "../../.opencode/plugins/cli-auto-login.js";

const source = readFileSync(new URL("../../.opencode/plugins/openmates-hooks.js", import.meta.url), "utf8");
const preEditGuard = readFileSync(new URL("../../.claude/hooks/pre-edit-guard.sh", import.meta.url), "utf8");
const autoTrack = readFileSync(new URL("../../.claude/hooks/auto-track.sh", import.meta.url), "utf8");
const bridge = readFileSync(new URL("../../.codex/hooks/claude-hook-bridge.sh", import.meta.url), "utf8");
const opencodeConfig = JSON.parse(readFileSync(new URL("../../opencode.json", import.meta.url), "utf8"));
const routedTestData = {
  sessions: {
    test: {
      opencode_session_id: "test-session",
      binding_mode: "worktree_routed",
      mode: "testing",
      worktree: { path: process.cwd(), status: "active" },
    },
  },
};

async function runBeforeShell(command) {
  const result = await runBeforeShellWithExecutionArgs(command);
  return result.executionArgs;
}

async function runBeforeShellWithExecutionArgs(command) {
  const hooks = await pluginModule.OpenMatesHooks({ routingData: routedTestData, recordRouting: false });
  const executionArgs = { command, workdir: "/model-selected-root" };
  const output = { args: executionArgs };
  await hooks["tool.execute.before"](
    { tool: "bash", sessionID: "test-session" },
    output,
  );
  return { executionArgs, output };
}

async function runAfterShell(command, text) {
  const hooks = await pluginModule.OpenMatesHooks({});
  const output = { args: { command }, output: text };
  await hooks["tool.execute.after"](
    { tool: "bash", args: { command }, sessionID: "test-session" },
    output,
  );
  return output.output;
}

test("auto-discovered modules export only valid OpenCode plugin factories", async () => {
  assert.deepEqual(Object.keys(pluginModule), ["OpenMatesHooks"]);
  assert.deepEqual(Object.keys(cliAutoLoginPluginModule), ["CliAutoLogin"]);
  assert.equal(typeof await pluginModule.OpenMatesHooks({}), "object");
  assert.equal(typeof await cliAutoLoginPluginModule.CliAutoLogin({}), "object");
});

test("merged worktree routing requires an existing Git worktree", () => {
  const { routingDecisionForTest } = pluginModule.OpenMatesHooks.test;
  const worktreePath = process.cwd();
  assert.deepEqual(
    routingDecisionForTest({
      session: { worktree: { path: worktreePath, status: "merged", merged_commit: "abc123456789" } },
    }),
    { decision: "worktree_routed", worktreePath },
  );
  assert.deepEqual(
    routingDecisionForTest({
      session: {
        worktree: {
          path: "/home/superdev/projects/OpenMates/.openmates-agent-worktrees/agent-missing",
          status: "merged",
        },
      },
    }),
    { decision: "unresolved", worktreePath: "" },
  );
});

test("root-hosted routing forces tool paths and shell workdir", () => {
  assert.match(source, /resolveWorktreeRoute\(client, input\.sessionID/);
  assert.match(source, /routeLocalToolArgsForTest\(tool/);
  assert.match(source, /workdir: \(prodSshControlPlane \|\| staleCodeReportControlPlane \|\| improvementReviewControlPlane \|\| sessionsPyControlPlane\) \? PROJECT_ROOT : worktreePath/);
  assert.match(source, /Reason:/);
  assert.match(source, /Next:/);
  assert.match(source, /routedOpenCodeSessionID/);
  assert.match(source, /OPENMATES_SESSION_WORKTREE/);
});

test("loaded hook overwrites model-provided shell workdir", async () => {
  const { executionArgs, output } = await runBeforeShellWithExecutionArgs("pwd");
  assert.strictEqual(output.args, executionArgs);
  assert.equal(executionArgs.workdir, process.cwd());
});

test("loaded hook binds chained sessions.py start before later commands", async () => {
  const { executionArgs } = await runBeforeShellWithExecutionArgs(
    'python3 scripts/sessions.py start --mode bug --task "Investigate A && B" && python3 scripts/issues.py show BTWQJ --env dev',
  );
  assert.equal(
    executionArgs.command,
    'python3 scripts/sessions.py start --mode bug --task "Investigate A && B" --opencode-session test-session && python3 scripts/issues.py show BTWQJ --env dev',
  );
});

test("blocking hook messages always explain reason and next action", async () => {
  for (const command of ["docker compose restart api", "cat > scripts/example.py", "npx playwright test"]) {
    await assert.rejects(
      () => runBeforeShell(command),
      (error) => {
        assert.match(error.message, /Reason:/);
        assert.match(error.message, /Next:/);
        return true;
      },
    );
  }
});

test("Claude edit coordination stays warning-only while OpenCode uses edit leases", () => {
  assert.match(preEditGuard, /additionalContext/);
  assert.match(preEditGuard, /WARNING: File/);
  assert.match(preEditGuard, /exit 0/);
  assert.match(source, /edit-lease/);
  assert.doesNotMatch(source, /createFileLeaseCoordinator|opencode_file_leases\.py|Waiting for file lease/);
});

test("loaded hook preserves chat identity for blocking edit leases", () => {
  assert.match(source, /env: sessionID \? \{ \.\.\.process\.env, OPENCODE_SESSION_ID: sessionID \}/);
  assert.doesNotMatch(source, /createSpecAutoContinue|opencode-spec-continuation|createFileLeaseCoordinator|experimental\.chat\.system\.transform/);
  assert.match(source, /event: async \(\{ event \}\)/);
  assert.match(source, /stale-read/);
  assert.match(source, /edit-lease/);
});

test("canonical pre-edit guard prefers exact OpenCode identity", () => {
  assert.match(preEditGuard, /if \[ -n "\$OPENCODE_SESSION_ID" \]/);
  assert.match(preEditGuard, /select\(\.value\.opencode_session_id == \$id\)/);
});

test("canonical edit hooks preserve worktree-relative paths", () => {
  assert.match(bridge, /CALLER_CWD=\$\(echo "\$INPUT"/);
  assert.match(bridge, /printf '%s\/%s\\n' "\$CALLER_CWD" "\$file"/);
  assert.match(autoTrack, /\.openmates-agent-worktrees/);
  assert.match(preEditGuard, /normalize_repo_relative/);
  assert.match(preEditGuard, /\.sessions\[\]\? \| \(\.worktree\.path\? \/\/ \.repo_root\?/);
});

test("opencode config allows legacy external agent worktrees", () => {
  assert.equal(
    opencodeConfig.permission.external_directory["/home/superdev/projects/.openmates-agent-worktrees/**"],
    "allow",
  );
});

test("bash guard allows temp writes even when a repo script and source extension appear", async () => {
  await assert.doesNotReject(() => runBeforeShell("./scripts/prod-ssh.sh 'cat > /tmp/docker-compose.hotfix.yml'"));
});

test("routing recovery allows direct prod ssh status and close only", async () => {
  const hooks = await pluginModule.OpenMatesHooks({
    routingData: {
      sessions: {
        stale: {
          opencode_session_id: "stale-session",
          binding_mode: "worktree_routed",
          worktree: { path: process.cwd(), status: "missing", merged_commit: "abc123456789" },
        },
      },
    },
    recordRouting: false,
  });
  for (const command of ["./scripts/prod-ssh.sh status", "./scripts/prod-ssh.sh close"]) {
    await assert.doesNotReject(() => hooks["tool.execute.before"](
      { tool: "bash", sessionID: "stale-session" },
      { args: { command, workdir: "/model-selected-root" } },
    ));
  }
  await assert.rejects(
    () => hooks["tool.execute.before"](
      { tool: "bash", sessionID: "stale-session" },
      { args: { command: "./scripts/prod-ssh.sh 'docker ps'", workdir: "/model-selected-root" } },
    ),
    /no active sessions\.py worktree could be resolved/,
  );
});

test("merged routing continues through the source worktree", async () => {
  const commit = "a".repeat(40);
  const hooks = await pluginModule.OpenMatesHooks({
    routingData: {
      sessions: {
        stale: {
          opencode_session_id: "stale-session",
          binding_mode: "worktree_routed",
          mode: "testing",
          worktree: { path: process.cwd(), status: "merged", merged_commit: commit },
        },
      },
    },
    recordRouting: false,
  });
  const command = `python3 scripts/tests.py run --spec chat-flow.spec.ts --gate-deploy --require-exact-commit --expected-commit ${commit}`;
  const output = { args: { command, workdir: "/model-selected-root" } };
  await assert.doesNotReject(() => hooks["tool.execute.before"](
    { tool: "bash", sessionID: "stale-session" },
    output,
  ));
  assert.equal(output.args.workdir, process.cwd());

  const followUp = { args: { command: command.replace(commit, "b".repeat(40)), workdir: "/model-selected-root" } };
  await assert.doesNotReject(
    () => hooks["tool.execute.before"](
      { tool: "bash", sessionID: "stale-session" },
      followUp,
    ),
  );
  assert.equal(followUp.args.workdir, process.cwd());
});

test("question routing runs approved audits from the control plane", async () => {
  const hooks = await pluginModule.OpenMatesHooks({
    routingData: {
      sessions: {
        question: {
          opencode_session_id: "question-session",
          mode: "question",
        },
      },
    },
    recordRouting: false,
  });
  const output = {
    args: {
      command: "python3 scripts/audit_agent_tooling_parity.py --json",
      workdir: "/model-selected-root",
    },
  };
  await assert.doesNotReject(() => hooks["tool.execute.before"](
    { tool: "bash", sessionID: "question-session" },
    output,
  ));
  assert.equal(output.args.workdir, "/home/superdev/projects/OpenMates");
});

test("bash guard allows source file references that are not writes", async () => {
  await assert.doesNotReject(() => runBeforeShell("docker compose -f backend/core/docker-compose.yml ps"));
});

test("bash guard blocks direct Docker Compose lifecycle mutations", async () => {
  await assert.rejects(
    () => runBeforeShell("docker compose -f backend/core/docker-compose.yml restart api"),
    /Reason: Direct Docker Compose lifecycle mutations bypass.*Next: use openmates server/,
  );
});

test("Docker mutation decision rejects direct Compose even with a Docker lock", () => {
  const data = {
    locks: { docker_rebuild: { status: "IN_PROGRESS", claimed_by: "abcd" } },
    sessions: { abcd: { opencode_session_id: "test-session" } },
  };
  const decision = pluginModule.OpenMatesHooks.test.dockerMutationDecisionForTest({
      command: "docker compose --env-file .env -f backend/core/docker-compose.yml build api",
      sessionID: "test-session",
      data,
    });
  assert.equal(decision.decision, "block");
  assert.match(decision.message, /openmates server restart --rebuild/);
});

test("bash guard allows programmatic source reads", async () => {
  await assert.doesNotReject(() => runBeforeShell("python3 -c 'from pathlib import Path; print(Path(\"backend/core/example.py\").exists())'"));
});

test("bash guard blocks direct repo source redirection", async () => {
  await assert.rejects(
    () => runBeforeShell("cat > backend/core/example.py"),
    /Reason: Bash would mutate repository source.*Next: use apply_patch/,
  );
});

test("bash guard blocks tee into repo source files", async () => {
  await assert.rejects(
    () => runBeforeShell("printf test | tee frontend/apps/web_app/src/example.ts"),
    /Reason: Bash would mutate repository source.*Next: use apply_patch/,
  );
});

test("bash guard blocks programmatic repo source writes", async () => {
  await assert.rejects(
    () => runBeforeShell("python3 -c 'from pathlib import Path; Path(\"scripts/example.py\").write_text(\"x\")'"),
    /Reason: Bash would mutate repository source.*Next: use apply_patch/,
  );
});

test("bash guard blocks local Playwright and Vitest commands", async () => {
  await assert.rejects(
    () => runBeforeShell("npx playwright test frontend/apps/web_app/tests/chat-flow.spec.ts"),
    /Reason: .*Next: run python3 scripts\/tests\.py run --spec/,
  );
  await assert.rejects(
    () => runBeforeShell("pnpm test"),
    /Reason: .*Next: run python3 scripts\/tests\.py run --suite vitest/,
  );
});

test("bash guard allows forbidden command examples inside quoted data", async () => {
  await assert.doesNotReject(() => runBeforeShell("python3 -c 'print(\"git commit and npx playwright test are examples\")'"));
});

test("bash guard still blocks actual raw git commands", async () => {
  await assert.rejects(
    () => runBeforeShell("git commit -m test"),
    /Use sessions\.py deploy instead of raw git commit/,
  );
  await assert.rejects(
    () => runBeforeShell("git -C /home/superdev/projects/OpenMates commit -m test"),
    /root checkout.*Next: use repository-relative paths/,
  );
  await assert.rejects(
    () => runBeforeShell("env -u GIT_CONFIG git commit -m test"),
    /Use sessions\.py deploy instead of raw git commit/,
  );
  await assert.rejects(
    () => runBeforeShell("timeout -k 5 30 git commit -m test"),
    /Use sessions\.py deploy instead of raw git commit/,
  );
});

test("bash guard allows canonical tests.py Vitest wrapper", async () => {
  await assert.doesNotReject(() => runBeforeShell("python3 scripts/tests.py run --suite vitest"));
  await assert.doesNotReject(() => runBeforeShell("python3 scripts/tests.py run -- --suite vitest"));
});

test("bash guard still blocks forbidden local tests in chained commands", async () => {
  await assert.rejects(
    () => runBeforeShell("python3 scripts/tests.py run --suite vitest && npx playwright test"),
    /Reason: .*Next: run python3 scripts\/tests\.py run --spec/,
  );
});

test("command doctor appends script usage suggestions", async () => {
  const output = await runAfterShell(
    "python3 scripts/tests.py run --suite vitest",
    "usage: tests.py [-h] ...\ntests.py: error: unrecognized arguments: --suite",
  );
  assert.match(output, /\[OpenMates command doctor\]/);
  assert.match(output, /python3 scripts\/tests\.py run --suite <suite>/);
});

test("command doctor does not add failure guidance to successful test summaries", async () => {
  const output = await runAfterShell(
    "python3 scripts/tests.py run --suite vitest",
    "Total: 718  Passed: 718  Failed: 0  Dispatch errors: 0",
  );
  assert.doesNotMatch(output, /\[OpenMates command doctor\]/);
});

test("command doctor adds lease guidance only for nonzero failure summaries", async () => {
  const output = await runAfterShell(
    "python3 scripts/tests.py run --suite vitest",
    "Total: 718  Passed: 717  Failed: 1  Dispatch errors: 0",
  );
  assert.match(output, /\[OpenMates command doctor\]/);
  assert.match(output, /tests\.py next --lease/);
});

test("failed test triage output gets lease hint", async () => {
  const output = await runAfterShell(
    "python3 scripts/tests.py triage",
    "Run: latest\nFailures: 2\n#1 [chat_sync_encryption] chat-flow.spec.ts -- timeout",
  );
  assert.match(output, /\[OpenMates failed-test lease hint\]/);
  assert.match(output, /python3 scripts\/tests\.py next --lease/);
});
