// OpenCode hook source contracts.
// Ensures stale-read checks receive pre-execution input arguments.
// Ensures local Apple audit findings keep their blocking exit status.
// Uses static source checks because the plugin host owns event dispatch.
// Run: node --test scripts/tests/test_opencode_hooks_contract.mjs.

import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { after, test } from "node:test";

import * as pluginModule from "../../.opencode/plugins/openmates-hooks.js";
import * as cliAutoLoginPluginModule from "../../.opencode/plugins/cli-auto-login.js";

const source = readFileSync(new URL("../../.opencode/plugins/openmates-hooks.js", import.meta.url), "utf8");
const preEditGuard = readFileSync(new URL("../../.claude/hooks/pre-edit-guard.sh", import.meta.url), "utf8");
const autoTrack = readFileSync(new URL("../../.claude/hooks/auto-track.sh", import.meta.url), "utf8");
const bridge = readFileSync(new URL("../../.codex/hooks/claude-hook-bridge.sh", import.meta.url), "utf8");
const opencodeConfig = JSON.parse(readFileSync(new URL("../../opencode.json", import.meta.url), "utf8"));
const routedWorktree = mkdtempSync("/home/superdev/projects/.openmates-agent-worktrees/agent-hook-contract-");
mkdirSync(`${routedWorktree}/.git`);
after(() => rmSync(routedWorktree, { recursive: true, force: true }));
const routedTestData = {
  sessions: {
    test: {
      opencode_session_id: "test-session",
      binding_mode: "worktree_routed",
      mode: "testing",
      worktree: { path: routedWorktree, status: "active" },
    },
  },
};

async function runBeforeShell(command) {
  const result = await runBeforeShellWithExecutionArgs(command);
  return result.executionArgs;
}

test("worktree checkpoint scheduling is single-flight per OpenCode session", () => {
  const children = [];
  const spawns = [];
  const scheduler = pluginModule.OpenMatesHooks.test.createWorktreeCheckpointSchedulerForTest({
    spawnProcess: (...args) => {
      const child = new EventEmitter();
      child.unref = () => {};
      children.push(child);
      spawns.push(args);
      return child;
    },
    warn: () => {},
  });

  assert.equal(scheduler("ses_test", "idle"), true);
  assert.equal(scheduler("ses_test", "idle"), false);
  assert.equal(scheduler("ses_test", "closed"), false);
  assert.equal(children.length, 1);
  assert.equal(spawns[0][2].cwd, "/home/superdev/projects/.openmates-runtime/opencode-server");

  children[0].emit("close", 0);
  assert.equal(scheduler("ses_test", "closed"), true);
  assert.equal(children.length, 2);
});

test("worktree activation scheduling is single-flight per OpenCode session", () => {
  const children = [];
  const spawns = [];
  const scheduler = pluginModule.OpenMatesHooks.test.createWorktreeActivationSchedulerForTest({
    spawnProcess: (...args) => {
      const child = new EventEmitter();
      child.unref = () => {};
      children.push(child);
      spawns.push(args);
      return child;
    },
    warn: () => {},
  });

  assert.equal(scheduler("ses_test"), true);
  assert.equal(scheduler("ses_test"), false);
  assert.deepEqual(spawns[0].slice(0, 2), [
    "python3",
    ["scripts/sessions.py", "worktree", "activate", "--opencode-session", "ses_test"],
  ]);
  assert.equal(spawns[0][2].cwd, "/home/superdev/projects/.openmates-runtime/opencode-server");

  children[0].emit("close", 0);
  assert.equal(scheduler("ses_test"), true);
  assert.equal(children.length, 2);
});

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

test("task child role survives runtime output wrappers without top-level metadata", () => {
  assert.deepEqual(
    pluginModule.OpenMatesHooks.test.taskChildClassificationForTest(
      { tool: "task", sessionID: "ses_parent", args: { subagent_type: "explore" } },
      { output: '<task id="ses_child123" state="completed"><task_result>done</task_result></task>' },
    ),
    { sessionID: "ses_child123", parentID: "ses_parent", role: "read_only" },
  );
});

test("merged worktree routing requires an existing Git worktree", () => {
  const { routingDecisionForTest } = pluginModule.OpenMatesHooks.test;
  const worktreePath = routedWorktree;
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
  assert.match(source, /controlPlaneScriptRuntime \? CURRENT_CONTROL_PLANE_ROOT : PROJECT_ROOT/);
  assert.match(source, /Reason:/);
  assert.match(source, /Next:/);
  assert.match(source, /routedOpenCodeSessionID/);
  assert.match(source, /OPENMATES_SESSION_WORKTREE/);
});

test("loaded hook overwrites model-provided shell workdir", async () => {
  const { executionArgs, output } = await runBeforeShellWithExecutionArgs("pwd");
  assert.strictEqual(output.args, executionArgs);
  assert.equal(executionArgs.workdir, routedWorktree);
});

test("every canonical sessions.py command uses the deployed control-plane runtime", async () => {
  for (const command of [
    "python3 scripts/sessions.py status --json",
    "python3 scripts/sessions.py deploy --session test --title scoped --use-staged",
    "python3 scripts/sessions.py visual-smoke --session test --url https://app.dev.openmates.org",
  ]) {
    const { executionArgs } = await runBeforeShellWithExecutionArgs(command);
    assert.equal(executionArgs.workdir, "/home/superdev/projects/.openmates-runtime/opencode-server");
  }
});

test("test dispatches use the deployed control-plane runtime", async () => {
  for (const command of [
    "python3 scripts/tests.py run --spec chat-flow.spec.ts",
    "OPENCODE_SESSION_ID=test-session python3 scripts/tests.py run --suite vitest",
  ]) {
    const { executionArgs } = await runBeforeShellWithExecutionArgs(command);
    assert.equal(executionArgs.workdir, "/home/superdev/projects/.openmates-runtime/opencode-server");
  }
  await assert.rejects(
    runBeforeShellWithExecutionArgs(
      "COMMIT=$(git rev-parse origin/dev) && OPENCODE_SESSION_ID=test-session python3 scripts/tests.py run --spec chat-flow.spec.ts --gate-deploy --expected-commit $COMMIT",
    ),
    /canonical sessions\.py\/tests\.py command is mixed with another shell command/,
  );
});

test("loaded hook rejects chained sessions.py start before later commands", async () => {
  await assert.rejects(
    runBeforeShellWithExecutionArgs(
      'python3 scripts/sessions.py start --mode bug --task "Investigate A && B" && python3 scripts/issues.py show BTWQJ --env dev',
    ),
    /canonical sessions\.py\/tests\.py command is mixed with another shell command/,
  );
});

test("hook subprocesses have a bounded lifetime", async () => {
  const { runProcessForTest } = pluginModule.OpenMatesHooks.test;
  const started = Date.now();
  const result = await runProcessForTest(
    process.execPath,
    ["-e", "setTimeout(() => {}, 5_000)"],
    { timeoutMs: 50 },
  );

  assert.equal(result.status, null);
  assert.match(result.stderr, /timed out after 50ms/);
  assert.ok(Date.now() - started < 2_000);
});

test("the complete pre-tool hook has a hard deadline", async () => {
  const { withHookDeadlineForTest } = pluginModule.OpenMatesHooks.test;
  await assert.rejects(
    () => withHookDeadlineForTest("tool.execute.before", "ses-stuck", () => new Promise(() => {}), 25),
    /\[OpenMates hook deadline\].*25ms.*ses-stuck.*Next:/,
  );
  assert.equal(await withHookDeadlineForTest("tool.execute.before", "ses-ok", async () => "ok", 100), "ok");
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

test("hook routing warnings are deduplicated by session and reason", () => {
  const warnings = [];
  const { warnOnceForTest } = pluginModule.OpenMatesHooks.test;
  const message = "[OpenMates worktree routing] Reason: sessions.py could not record worktree routing. Next: repair it.";

  assert.equal(
    warnOnceForTest(message, { sessionID: "ses_warn", now: 1_000_000, ttlMs: 60_000 }, (text) => warnings.push(text)),
    true,
  );
  assert.equal(
    warnOnceForTest(message, { sessionID: "ses_warn", now: 1_000_001, ttlMs: 60_000 }, (text) => warnings.push(text)),
    false,
  );
  assert.equal(
    warnOnceForTest(message, { sessionID: "ses_other", now: 1_000_002, ttlMs: 60_000 }, (text) => warnings.push(text)),
    true,
  );
  assert.deepEqual(warnings, [message, message]);
});

test("GitHub MCP tools are rejected in favor of gh CLI", async () => {
  const hooks = await pluginModule.OpenMatesHooks({ routingData: routedTestData, recordRouting: false });
  await assert.rejects(
    () => hooks["tool.execute.before"](
      { tool: "github_get_me", sessionID: "test-session" },
      { args: {} },
    ),
    /OpenMates GitHub MCP guard.*gh CLI/s,
  );
  assert.equal(
    pluginModule.OpenMatesHooks.test.githubMcpGuardDecisionForTest("bash").decision,
    "allow",
  );
});

test("temporary shared lock output forces same-turn deterministic continuation", async () => {
  const text = await runAfterShell("python3 scripts/sessions.py status", "active lock(s): docker_rebuild");
  assert.match(text, /OpenMates temporary lock continuation/);
  assert.match(text, /wait-lock --session \$\{OPENCODE_SESSION_ID:-manual\} --type docker --follow --poll 10/);
  assert.match(text, /Do not finish this response as blocked/);
  assert.deepEqual(
    pluginModule.OpenMatesHooks.test.temporaryLockWaitTypesForTest("vercel_deploy: IN_PROGRESS"),
    ["vercel"],
  );
});

test("dev API 502 output gets coordinated health waiter guidance", async () => {
  const text = await runAfterShell(
    "python3 scripts/verify_test_account_login.py",
    "https://api.dev.openmates.org/health returned 502 Bad Gateway",
  );
  assert.match(text, /OpenMates API health coordination/);
  assert.match(text, /wait-health --session \$\{OPENCODE_SESSION_ID:-manual\} --url https:\/\/api\.dev\.openmates\.org\/health --follow --poll 10/);
  assert.match(text, /OPENMATES_HEALTH_INVESTIGATE/);
  assert.equal(
    pluginModule.OpenMatesHooks.test.apiHealthWaitUrlForTest("api.dev.openmates.org health returned 502"),
    "https://api.dev.openmates.org/health",
  );
});

test("assistant-side sleep polling is rejected in favor of the real completion signal", async () => {
  const hooks = await pluginModule.OpenMatesHooks({ routingData: routedTestData, recordRouting: false });
  await assert.rejects(
    () => hooks["tool.execute.before"](
      { tool: "bash", sessionID: "test-session" },
      { args: { command: "sleep 30" } },
    ),
    /OpenMates opaque long sleep guard.*wait-lock.*wait-health.*gh run watch.*tail --pid/s,
  );
  assert.equal(pluginModule.OpenMatesHooks.test.opaqueLongSleepDecisionForTest("sleep 9").decision, "allow");
  assert.equal(pluginModule.OpenMatesHooks.test.opaqueLongSleepDecisionForTest("sleep 10").decision, "block");
  assert.equal(pluginModule.OpenMatesHooks.test.sleepDurationSecondsForTest("2m"), 120);
});

test("Playwright response-media output does not inject progress instructions", async () => {
  const snippet = '<video controls crossorigin="anonymous"><source src="https://example.test/latest.webm" type="video/webm"></video>';
  const text = await runAfterShell(
    "python3 scripts/tests.py run --spec chat-flow.spec.ts --proof-video-profile web-phone",
    `OpenCode response-media video for latest Playwright spec run:\n${snippet}`,
  );

  assert.doesNotMatch(text, /OpenMates response-media embed required/);
  assert.match(text, /<video controls crossorigin="anonymous">/);
  assert.equal(pluginModule.OpenMatesHooks.test.firstResponseMediaVideoSnippetForTest(`before ${snippet} after`), snippet);
});

test("Figma image export output does not inject response instructions", async () => {
  const hooks = await pluginModule.OpenMatesHooks({});
  const output = {
    args: {},
    output: "download_figma_images saved test-results/figma/ai-settings/figma-default-models.png",
  };
  await hooks["tool.execute.after"](
    { tool: "download_figma_images", args: {}, sessionID: "test-session" },
    output,
  );

  assert.doesNotMatch(output.output, /OpenMates Figma reference embed required/);
  assert.doesNotMatch(output.output, /opencode_response_media.py <exported-figma-png>/);
  assert.equal(
    pluginModule.OpenMatesHooks.test.figmaExportPathForTest("saved ./test-results/figma/x/figma-screen.png"),
    "./test-results/figma/x/figma-screen.png",
  );
});

test("source code containing video HTML is not queued as response media", () => {
  const sourceListing = String.raw`359: return (
360:     f'<video controls crossorigin="anonymous" style="{style}" preload="metadata" playsinline>\n'
361:     f'  <source src="{escaped_url}" type="{content_type}">\n'
362:     '  Video fallback text.\n'
363:     '</video>'`;

  assert.equal(
    pluginModule.OpenMatesHooks.test.responseMediaArtifactForTest({ output: sourceListing }),
    null,
  );
  const snippet = '<video controls><source src="https://example.test/proof.webm" type="video/webm"></video>';
  assert.equal(
    pluginModule.OpenMatesHooks.test.responseMediaArtifactForTest({ output: snippet }),
    null,
  );
  const artifact = pluginModule.OpenMatesHooks.test.responseMediaArtifactForTest({
    command: "python3 scripts/opencode_response_media.py proof.webm",
    output: snippet,
    automationEnabled: true,
  });
  assert.deepEqual(
    artifact,
    {
      artifact_type: "video",
      artifact_key: artifact.artifact_key,
      snippet,
    },
  );
});

test("automatic response-media queueing and synthetic delivery are disabled by default", () => {
  const snippet = '<video controls><source src="https://example.test/proof.webm" type="video/webm"></video>';
  assert.equal(pluginModule.OpenMatesHooks.test.responseMediaAutomationEnabledForTest({}), false);
  assert.equal(
    pluginModule.OpenMatesHooks.test.responseMediaArtifactForTest({
      command: "python3 scripts/opencode_response_media.py proof.webm",
      output: snippet,
    }),
    null,
  );
  assert.equal(
    pluginModule.OpenMatesHooks.test.mediaDeliveryPromptForTest({ artifact_type: "video", snippet }),
    "",
  );
});

test("ordinary product tools cannot mutate control-plane paths or read secret config", () => {
  const decide = pluginModule.OpenMatesHooks.test.controlPlaneToolDecisionForTest;
  assert.equal(decide({ tool: "apply_patch", args: { filePath: `${process.cwd()}/scripts/sessions.py` } }).decision, "block");
  assert.equal(decide({ tool: "write", args: { filePath: `${process.cwd()}/.opencode/plugins/openmates-hooks.js` } }).decision, "block");
  assert.equal(decide({ tool: "bash", args: { command: "sed -i s/old/new/ scripts/sessions.py" } }).decision, "block");
  assert.equal(decide({ tool: "read", args: { filePath: "/home/superdev/.config/opencode/opencode.json" } }).decision, "block");
  assert.equal(decide({ tool: "bash", args: { command: "cat $HOME/.config/opencode/secrets.env" } }).decision, "block");
  assert.equal(decide({ tool: "bash", args: { command: "cat ~/.config/opencode/opencode.json" } }).decision, "block");
  assert.equal(decide({ tool: "read", args: { filePath: `${process.cwd()}/frontend/packages/ui/src/index.ts` } }).decision, "allow");
});

test("optional hook queues require matching sessions.py subcommands", async () => {
  const supports = pluginModule.OpenMatesHooks.test.sessionsCommandSupportedForTest;
  const calls = [];
  const run = async (_command, args) => {
    calls.push(args);
    return { status: args[1] === "restore" ? 0 : 2, stdout: "", stderr: "" };
  };
  assert.equal(await supports("continuation", run), false);
  assert.equal(await supports("media", run), false);
  assert.equal(await supports("restore", run), true);
  assert.equal(await supports("../unsafe", run), false);
  assert.deepEqual(calls, [
    ["scripts/sessions.py", "continuation", "--help"],
    ["scripts/sessions.py", "media", "--help"],
    ["scripts/sessions.py", "restore", "--help"],
  ]);
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
  assert.equal(
    opencodeConfig.permission.external_directory["/home/superdev/projects/.openmates-runtime/opencode-server/**"],
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
          worktree: { path: routedWorktree, status: "missing", merged_commit: "abc123456789" },
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

test("merged routing runs canonical test dispatches from the control plane", async () => {
  const commit = "a".repeat(40);
  const hooks = await pluginModule.OpenMatesHooks({
    routingData: {
      sessions: {
        stale: {
          opencode_session_id: "stale-session",
          binding_mode: "worktree_routed",
          mode: "testing",
          worktree: { path: routedWorktree, status: "merged", merged_commit: commit },
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
  assert.equal(output.args.workdir, "/home/superdev/projects/.openmates-runtime/opencode-server");

  const followUp = { args: { command: command.replace(commit, "b".repeat(40)), workdir: "/model-selected-root" } };
  await assert.doesNotReject(
    () => hooks["tool.execute.before"](
      { tool: "bash", sessionID: "stale-session" },
      followUp,
    ),
  );
  assert.equal(followUp.args.workdir, "/home/superdev/projects/.openmates-runtime/opencode-server");
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
    /Reason: Direct Docker Compose lifecycle mutations bypass.*Next: use python3 scripts\/sessions\.py docker restart/s,
  );
});

test("bash guard blocks OpenMates CLI server lifecycle mutations", async () => {
  await assert.rejects(
    () => runBeforeShell("openmates server restart --rebuild --services api"),
    /Reason: OpenMates server lifecycle commands spawn Docker Compose.*Next: use python3 scripts\/sessions\.py docker restart/s,
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
  assert.match(decision.message, /scripts\/sessions\.py docker restart/);
});

test("bash guard blocks nested interpreter source reads", async () => {
  await assert.rejects(
    () => runBeforeShell("python3 -c 'from pathlib import Path; print(Path(\"backend/core/example.py\").exists())'"),
    /nested interpreter evaluation is blocked/,
  );
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

test("bash guard blocks forbidden command examples inside nested interpreter data", async () => {
  await assert.rejects(
    () => runBeforeShell("python3 -c 'print(\"git commit and npx playwright test are examples\")'"),
    /nested interpreter evaluation is blocked/,
  );
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
