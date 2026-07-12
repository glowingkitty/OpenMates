// OpenCode idle-continuation removal tests.
// Purpose: prevent synthetic spec prompts from being injected into idle chats.
// Architecture: instantiate the loaded project hook and inspect its hook surface.
// Security: tests use no network, credentials, or live OpenCode server.
// Run: node --test scripts/tests/test_opencode_spec_autocontinue.mjs.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { OpenMatesHooks } from "../../.opencode/plugins/openmates-hooks.js";

const source = readFileSync(new URL("../../.opencode/plugins/openmates-hooks.js", import.meta.url), "utf8");

test("loaded hook exposes no idle spec continuation handler", async () => {
  const hooks = await OpenMatesHooks({
    client: { session: { messages: async () => [], prompt: async () => ({}) } },
    worktree: "/repo",
  });

  assert.equal(hooks.event, undefined);
});

test("loaded hook contains no deterministic spec continuation prompt", () => {
  assert.doesNotMatch(source, /Continue until the full spec is implemented/);
  assert.doesNotMatch(source, /session\.idle/);
});
