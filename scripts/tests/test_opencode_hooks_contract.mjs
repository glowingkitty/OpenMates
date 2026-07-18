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
