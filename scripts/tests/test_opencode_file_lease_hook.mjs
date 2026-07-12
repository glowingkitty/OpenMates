// OpenCode file-lease hook tests.
// Purpose: verify exact chat identity, edit blocking, and targeted waiter resume.
// Architecture: inject a fake lease runner and OpenCode client into the hook.
// Security: no live server, subprocess, credentials, or repository state.
// Run: node --test scripts/tests/test_opencode_file_lease_hook.mjs.

import assert from "node:assert/strict";
import test from "node:test";

import { createFileLeaseCoordinator, OpenMatesHooks } from "../../.opencode/plugins/openmates-hooks.js";


test("prepareCommand binds sessions.py start to the exact OpenCode chat", () => {
  const coordinator = createFileLeaseCoordinator({ client: {}, runLease: async () => ({}) });
  const output = { args: { command: "python3 scripts/sessions.py start --mode feature --task test" } };

  coordinator.prepareCommand({ sessionID: "ses_exact" }, output);

  assert.match(output.args.command, /--opencode-session ses_exact$/);
});


test("beforeEdit queues and blocks a conflicting edit without partial execution", async () => {
  const calls = [];
  const coordinator = createFileLeaseCoordinator({
    client: {},
    runLease: async (command, sessionID, files) => {
      calls.push({ command, sessionID, files });
      if (command === "acquire") return { status: "waiting", position: 1, files };
      return { newly_granted: [] };
    },
  });

  await assert.rejects(
    coordinator.beforeEdit("ses_waiting", ["/repo/b.py", "/repo/a.py"]),
    /waiting for file lease/i,
  );
  assert.deepEqual(calls.at(-1), {
    command: "acquire",
    sessionID: "ses_waiting",
    files: ["/repo/a.py", "/repo/b.py"],
  });
});


test("beforeEdit authorizes the granted generation before writing", async () => {
  const calls = [];
  const coordinator = createFileLeaseCoordinator({
    client: {},
    runLease: async (command, sessionID, files, generation) => {
      calls.push({ command, sessionID, files, generation });
      if (command === "acquire") return { status: "granted", generation: 7, files };
      if (command === "authorize") return { authorized: true };
      return { newly_granted: [] };
    },
  });

  await coordinator.beforeEdit("ses_owner", ["/repo/a.py"]);

  assert.deepEqual(calls.slice(-2).map((call) => [call.command, call.generation]), [
    ["acquire", undefined],
    ["authorize", 7],
  ]);
});


test("direct source-file mutation through bash is rejected", () => {
  const coordinator = createFileLeaseCoordinator({ client: {}, runLease: async () => ({}) });

  for (const command of [
    "sed -i 's/a/b/' frontend/example.ts",
    "printf 'export {}' > frontend/example.ts",
    "python3 -c \"open('frontend/example.ts', 'w').write('export {}')\"",
    "git apply scripts/change.patch",
    "git apply < /tmp/change.patch",
    "printf x>frontend/example.ts",
    "truncate -s 0 backend/example.py",
    "install /tmp/example.py backend/example.py",
    "rsync /tmp/example.py backend/example.py",
    "python3 -c \"from pathlib import Path; Path('backend/example.py').write_text('')\"",
  ]) {
    assert.throws(
      () => coordinator.guardBash(command),
      /apply_patch.*file lease/i,
    );
  }
});


test("loaded hook rejects direct source mutation before command execution", async () => {
  const hooks = await OpenMatesHooks({
    client: { session: { prompt: async () => {} } },
    runLease: async () => ({ pending_notifications: [] }),
  });

  await assert.rejects(
    hooks["tool.execute.before"](
      { tool: "bash", sessionID: "ses_owner", args: { command: "sed -i 's/a/b/' frontend/example.ts" } },
      { args: { command: "sed -i 's/a/b/' frontend/example.ts" } },
    ),
    /Use apply_patch for source-file changes so the file lease can be acquired and verified/,
  );
});


test("loaded hook forwards the exact OpenCode chat identity to the canonical bridge", async () => {
  const bridgeCalls = [];
  const hooks = await OpenMatesHooks({
    client: { session: { prompt: async () => {} } },
    runHookBridge: (...args) => bridgeCalls.push(args),
    runLease: async (command) => command === "claim" ? { notifications: [] } : {},
  });

  await hooks["tool.execute.before"](
    { tool: "bash", sessionID: "ses_exact", args: { command: "git status --short" } },
    { args: { command: "git status --short" } },
  );

  assert.equal(bridgeCalls.length, 1);
  assert.equal(bridgeCalls[0][2], "ses_exact");
});


test("rejected pre-tool policy does not strand an active edit", async () => {
  let rejectPolicy = true;
  const hooks = await OpenMatesHooks({
    client: { session: { prompt: async () => {} } },
    runHookBridge: () => {
      if (rejectPolicy) throw new Error("policy rejected edit");
    },
    runLease: async (command, _sessionID, files) => {
      if (command === "acquire") return { status: "granted", generation: 7, files };
      if (command === "authorize") return { authorized: true };
      if (command === "claim") return { notifications: [] };
      return {};
    },
  });
  const input = {
    tool: "apply_patch",
    sessionID: "ses_owner",
    args: { filePath: "/tmp/not-in-repository.txt" },
  };
  const output = { args: input.args };

  await assert.rejects(hooks["tool.execute.before"](input, output), /policy rejected edit/);
  rejectPolicy = false;
  await hooks["tool.execute.before"](input, output);
});


test("active edit is renewed before sweep until tool completion", async () => {
  const calls = [];
  const coordinator = createFileLeaseCoordinator({
    client: { session: { prompt: async () => {} } },
    runLease: async (command, sessionID, files) => {
      calls.push({ command, sessionID, files });
      if (command === "acquire") return { status: "granted", generation: 7, files };
      if (command === "authorize") return { authorized: true };
      return { pending_notifications: [] };
    },
  });

  await coordinator.beforeEdit("ses_owner", ["/repo/a.py"]);
  await coordinator.sweep();
  coordinator.afterEdit("ses_owner", ["/repo/a.py"]);
  await coordinator.sweep();

  assert.equal(calls.filter((call) => call.command === "heartbeat").length, 1);
  assert.deepEqual(calls.filter((call) => call.command === "heartbeat")[0], {
    command: "heartbeat",
    sessionID: "ses_owner",
    files: [],
  });
});


test("overlapping same-chat edit cannot supersede an in-flight generation", async () => {
  const calls = [];
  const coordinator = createFileLeaseCoordinator({
    client: { session: { prompt: async () => {} } },
    runLease: async (command, sessionID, files) => {
      calls.push({ command, sessionID, files });
      if (command === "acquire") return { status: "granted", generation: 7, files };
      if (command === "authorize") return { authorized: true };
      return { notifications: [] };
    },
  });

  await coordinator.beforeEdit("ses_owner", ["/repo/a.py"]);
  await assert.rejects(
    coordinator.beforeEdit("ses_owner", ["/repo/a.py", "/repo/b.py"]),
    /overlapping edit is already in flight/i,
  );

  assert.equal(calls.filter((call) => call.command === "acquire").length, 1);
  coordinator.afterEdit("ses_owner", ["/repo/a.py"]);
});


test("newly granted waiter receives one concise targeted resume prompt", async () => {
  const prompts = [];
  const coordinator = createFileLeaseCoordinator({
    client: {
      session: {
        prompt: async (input) => prompts.push(input),
      },
    },
    runLease: async (command) => command === "claim" ? {
      notifications: [{ session_id: "ses_waiter", files: ["a.py", "b.py"], generation: 2 }],
    } : {},
  });

  await coordinator.sweep();

  assert.equal(prompts.length, 1);
  assert.equal(prompts[0].path.id, "ses_waiter");
  assert.match(prompts[0].body.messageID, /^msg_[a-f0-9]{26}$/);
  assert.match(prompts[0].body.parts[0].text, /file lease is now available/i);
  assert.doesNotMatch(prompts[0].body.parts[0].text, /verification gaps|full spec/i);
});


test("sweep sends no prompt when no waiter was granted", async () => {
  const prompts = [];
  const coordinator = createFileLeaseCoordinator({
    client: { session: { prompt: async (input) => prompts.push(input) } },
    runLease: async (command) => command === "claim" ? { notifications: [] } : {},
  });

  await coordinator.sweep();

  assert.deepEqual(prompts, []);
});


test("failed grant prompt remains retryable and does not block other waiters", async () => {
  const prompts = [];
  const acknowledgements = [];
  const coordinator = createFileLeaseCoordinator({
    client: {
      session: {
        prompt: async (input) => {
          prompts.push(input.path.id);
          if (input.path.id === "ses_missing") throw new Error("missing chat");
        },
      },
    },
    runLease: async (command, sessionID, _files, generation) => {
      if (command === "acknowledge") acknowledgements.push([sessionID, generation]);
      return command === "claim" ? {
        notifications: [
          { session_id: "ses_missing", files: ["a.py"], generation: 2 },
          { session_id: "ses_valid", files: ["b.py"], generation: 3 },
        ],
      } : {};
    },
  });

  await coordinator.sweep();

  assert.deepEqual(prompts, ["ses_missing", "ses_valid"]);
  assert.deepEqual(acknowledgements, [["ses_valid", 3]]);
});


test("concurrent sweeps claim one notification only once", async () => {
  const prompts = [];
  let claimed = false;
  const coordinator = createFileLeaseCoordinator({
    client: { session: { prompt: async (input) => prompts.push(input.path.id) } },
    runLease: async (command) => {
      if (command === "claim") {
        if (claimed) return { notifications: [] };
        claimed = true;
        return { notifications: [{ session_id: "ses_waiter", files: ["a.py"], generation: 2 }] };
      }
      return { pending_notifications: [] };
    },
  });

  await Promise.all([coordinator.sweep(), coordinator.sweep()]);

  assert.deepEqual(prompts, ["ses_waiter"]);
});


test("slow prompt remains single-delivery after its claim would expire", async () => {
  const prompts = [];
  let finishPrompt;
  const promptBlocked = new Promise((resolve) => { finishPrompt = resolve; });
  const notification = { session_id: "ses_waiter", files: ["a.py"], generation: 2 };
  const coordinator = createFileLeaseCoordinator({
    client: {
      session: {
        prompt: async (input) => {
          prompts.push(input.path.id);
          await promptBlocked;
        },
      },
    },
    runLease: async (command) => command === "claim"
      ? { notifications: [notification] }
      : { pending_notifications: [] },
  });

  const firstSweep = coordinator.sweep();
  await new Promise((resolve) => setImmediate(resolve));
  const secondSweep = coordinator.sweep();
  await new Promise((resolve) => setImmediate(resolve));
  finishPrompt();
  await Promise.all([firstSweep, secondSweep]);

  assert.deepEqual(prompts, ["ses_waiter"]);
});


test("separate coordinators use one idempotent message ID for the same grant", async () => {
  const storedMessages = new Set();
  const deliveries = [];
  const client = {
    session: {
      prompt: async (input) => {
        if (storedMessages.has(input.body.messageID)) return;
        storedMessages.add(input.body.messageID);
        deliveries.push(input);
      },
    },
  };
  const notification = { session_id: "ses_waiter", files: ["a.py"], generation: 2 };
  const runLease = async (command) => command === "claim"
    ? { notifications: [notification] }
    : { pending_notifications: [] };
  const first = createFileLeaseCoordinator({ client, runLease });
  const second = createFileLeaseCoordinator({ client, runLease });

  await Promise.all([first.sweep(), second.sweep()]);

  assert.equal(deliveries.length, 1);
  assert.match(deliveries[0].body.messageID, /^msg_[a-f0-9]{26}$/);
});


test("ending an older repo session does not release a still-bound chat", async () => {
  const releases = [];
  const coordinator = createFileLeaseCoordinator({
    client: { session: { prompt: async () => {} } },
    hasActiveBinding: async () => true,
    runLease: async (command) => {
      if (command === "release") releases.push(command);
      return { newly_granted: [] };
    },
  });

  await coordinator.afterCommand(
    "ses_chat",
    "python3 scripts/sessions.py end --session aa11",
    "Session aa11 ended and removed from sessions.json.",
  );

  assert.deepEqual(releases, []);
});
