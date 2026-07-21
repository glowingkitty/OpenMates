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

async function runBeforeShell(command) {
  const hooks = await pluginModule.OpenMatesHooks({});
  await hooks["tool.execute.before"](
    { tool: "bash", args: { command }, sessionID: "test-session" },
    { args: { command } },
  );
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
  assert.deepEqual(Object.keys(pluginModule), ["OpenMatesHooks"]);
  assert.equal(typeof await pluginModule.OpenMatesHooks({}), "object");
});

test("concurrent edit coordination is warning-only", () => {
  assert.match(preEditGuard, /additionalContext/);
  assert.match(preEditGuard, /WARNING: File/);
  assert.match(preEditGuard, /exit 0/);
  assert.doesNotMatch(source, /createFileLeaseCoordinator|opencode_file_leases\.py|Waiting for file lease/);
});

test("loaded hook preserves chat identity without blocking file leases", () => {
  assert.match(source, /env: sessionID \? \{ \.\.\.process\.env, OPENCODE_SESSION_ID: sessionID \}/);
  assert.doesNotMatch(source, /createSpecAutoContinue|session\.idle|opencode-spec-continuation|createFileLeaseCoordinator/);
});

test("canonical pre-edit guard prefers exact OpenCode identity", () => {
  assert.match(preEditGuard, /if \[ -n "\$OPENCODE_SESSION_ID" \]/);
  assert.match(preEditGuard, /select\(\.value\.opencode_session_id == \$id\)/);
});

test("bash guard allows temp writes even when a repo script and source extension appear", async () => {
  await assert.doesNotReject(() => runBeforeShell("./scripts/prod-ssh.sh 'cat > /tmp/docker-compose.hotfix.yml'"));
});

test("bash guard allows source file references that are not writes", async () => {
  await assert.doesNotReject(() => runBeforeShell("docker compose -f backend/core/docker-compose.yml ps"));
});

test("bash guard allows programmatic source reads", async () => {
  await assert.doesNotReject(() => runBeforeShell("python3 -c 'from pathlib import Path; print(Path(\"backend/core/example.py\").exists())'"));
});

test("bash guard blocks direct repo source redirection", async () => {
  await assert.rejects(
    () => runBeforeShell("cat > backend/core/example.py"),
    /Use apply_patch for source-file changes/,
  );
});

test("bash guard blocks tee into repo source files", async () => {
  await assert.rejects(
    () => runBeforeShell("printf test | tee frontend/apps/web_app/src/example.ts"),
    /Use apply_patch for source-file changes/,
  );
});

test("bash guard blocks programmatic repo source writes", async () => {
  await assert.rejects(
    () => runBeforeShell("python3 -c 'from pathlib import Path; Path(\"scripts/example.py\").write_text(\"x\")'"),
    /Use apply_patch for source-file changes/,
  );
});

test("bash guard blocks local Playwright and Vitest commands", async () => {
  await assert.rejects(
    () => runBeforeShell("npx playwright test frontend/apps/web_app/tests/chat-flow.spec.ts"),
    /Use python3 scripts\/tests\.py run --spec/,
  );
  await assert.rejects(
    () => runBeforeShell("pnpm test"),
    /Use python3 scripts\/tests\.py run --suite vitest/,
  );
});

test("bash guard allows canonical tests.py Vitest wrapper", async () => {
  await assert.doesNotReject(() => runBeforeShell("python3 scripts/tests.py run --suite vitest"));
  await assert.doesNotReject(() => runBeforeShell("python3 scripts/tests.py run -- --suite vitest"));
});

test("bash guard still blocks forbidden local tests in chained commands", async () => {
  await assert.rejects(
    () => runBeforeShell("python3 scripts/tests.py run --suite vitest && npx playwright test"),
    /Use python3 scripts\/tests\.py run --spec/,
  );
});

test("command doctor appends script usage suggestions", async () => {
  const output = await runAfterShell(
    "python3 scripts/tests.py run --suite vitest",
    "usage: tests.py [-h] ...\ntests.py: error: unrecognized arguments: --suite",
  );
  assert.match(output, /\[OpenMates command doctor\]/);
  assert.match(output, /python3 scripts\/tests\.py run -- --suite <suite>/);
});

test("failed test triage output gets lease hint", async () => {
  const output = await runAfterShell(
    "python3 scripts/tests.py triage",
    "Run: latest\nFailures: 2\n#1 [chat_sync_encryption] chat-flow.spec.ts -- timeout",
  );
  assert.match(output, /\[OpenMates failed-test lease hint\]/);
  assert.match(output, /python3 scripts\/tests\.py next --lease/);
});
