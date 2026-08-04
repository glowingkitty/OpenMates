// OpenCode hook source contracts.
// Ensures stale-read checks receive pre-execution input arguments.
// Ensures local Apple audit findings keep their blocking exit status.
// Uses static source checks because the plugin host owns event dispatch.
// Run: node --test scripts/tests/test_opencode_hooks_contract.mjs.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import * as pluginModule from "../../.opencode/plugins/openmates-hooks.js";

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

test("plugin module exports one valid OpenCode plugin factory", async () => {
  assert.deepEqual(Object.keys(pluginModule).sort(), ["OpenMatesHooks", "dockerMutationDecisionForTest", "editedFilesForBindingForTest", "editedFilesForTest", "resolveWorktreeRouteForTest", "rewriteEditArgsForTest", "rootGuardDecisionForTest", "routeLocalToolArgsForTest", "routingDecisionForTest", "routingFailureForTest"]);
  assert.equal(typeof await pluginModule.OpenMatesHooks({}), "object");
});

test("root-hosted routing forces tool paths and shell workdir", () => {
  assert.match(source, /resolveWorktreeRoute\(client, input\.sessionID/);
  assert.match(source, /routeLocalToolArgsForTest\(tool/);
  assert.match(source, /workdir: worktreePath/);
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
  assert.doesNotMatch(source, /createSpecAutoContinue|session\.idle|opencode-spec-continuation|createFileLeaseCoordinator/);
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
  assert.match(preEditGuard, /\.sessions\[\]\?\.worktree\?\.path\?/);
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

test("bash guard allows source file references that are not writes", async () => {
  await assert.doesNotReject(() => runBeforeShell("docker compose -f backend/core/docker-compose.yml ps"));
});

test("bash guard blocks Docker Compose mutations without the Docker lock", async () => {
  await assert.rejects(
    () => runBeforeShell("docker compose -f backend/core/docker-compose.yml restart api"),
    /Reason: Docker Compose mutations require.*Next: run python3 scripts\/sessions\.py lock/,
  );
});

test("Docker mutation decision allows the current session's Docker lock", () => {
  const data = {
    locks: { docker_rebuild: { status: "IN_PROGRESS", claimed_by: "abcd" } },
    sessions: { abcd: { opencode_session_id: "test-session" } },
  };
  assert.deepEqual(
    pluginModule.dockerMutationDecisionForTest({
      command: "docker compose --env-file .env -f backend/core/docker-compose.yml build api",
      sessionID: "test-session",
      data,
    }),
    { decision: "allow", message: "Docker lock held by this session" },
  );
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

test("failed test triage output gets lease hint", async () => {
  const output = await runAfterShell(
    "python3 scripts/tests.py triage",
    "Run: latest\nFailures: 2\n#1 [chat_sync_encryption] chat-flow.spec.ts -- timeout",
  );
  assert.match(output, /\[OpenMates failed-test lease hint\]/);
  assert.match(output, /python3 scripts\/tests\.py next --lease/);
});
