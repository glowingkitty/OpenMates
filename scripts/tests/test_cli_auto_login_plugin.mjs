// OpenCode CLI auto-login plugin regression tests.
// Prevents stale log snippets containing the login hint from mutating CLI auth.
// The plugin may auto-login only after an actual OpenMates CLI auth failure.
// Run: node --test scripts/tests/test_cli_auto_login_plugin.mjs.

import assert from "node:assert/strict";
import test from "node:test";

import { CliAutoLogin } from "../../.opencode/plugins/cli-auto-login.js";

const { shouldAutoLoginForTest } = CliAutoLogin.test;

const LOGIN_HINT = "[OpenMates CLI login hint]";

test("auto-login ignores non-CLI commands that print the hint", () => {
  assert.equal(
    shouldAutoLoginForTest(
      { tool: "bash", args: { command: "python3 scripts/analyze_logs.py" } },
      { args: { command: "python3 scripts/analyze_logs.py" }, output: `${LOGIN_HINT}\nNot logged in. Run \`openmates login\`.` },
    ),
    false,
  );
});

test("auto-login accepts actual OpenMates CLI auth failures", () => {
  assert.equal(
    shouldAutoLoginForTest(
      { tool: "bash", args: { command: "openmates chat list" } },
      { args: { command: "openmates chat list" }, output: `${LOGIN_HINT}\nNot logged in. Run \`openmates login\`.` },
    ),
    true,
  );
});

test("auto-login ignores CLI commands without an auth failure", () => {
  assert.equal(
    shouldAutoLoginForTest(
      { tool: "bash", args: { command: "openmates chat list" } },
      { args: { command: "openmates chat list" }, output: `${LOGIN_HINT}\nUsage: openmates chat list` },
    ),
    false,
  );
});
