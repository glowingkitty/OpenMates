// OpenCode hook source contracts.
// Ensures stale-read checks receive pre-execution input arguments.
// Ensures local Apple audit findings keep their blocking exit status.
// Uses static source checks because the plugin host owns event dispatch.
// Run: node --test scripts/tests/test_opencode_hooks_contract.mjs.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../../.opencode/plugins/openmates-hooks.js", import.meta.url), "utf8");

test("stale-read check uses pre-execution input arguments", () => {
  assert.match(source, /editedFiles\(input\?\.args \|\| output\?\.args\)/);
});

test("Apple audit exit code two remains blocking", () => {
  assert.match(source, /commandArgs\[0\]\?\.endsWith\("audit_ui_control_visibility\.py"\)/);
  assert.doesNotMatch(source, /allowHookWarning = true/);
});
