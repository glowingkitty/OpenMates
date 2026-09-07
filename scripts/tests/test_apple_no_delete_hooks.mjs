#!/usr/bin/env node
/*
 * Tooling tests for terminal Mac deletion stops in the OpenCode adapter.
 * Injected checks and aborts run entirely locally, without a live chat or Mac.
 * The adapter must abort rather than turn a durable stop into a retry hint.
 * No transcript content or caller confirmation is accepted by this adapter.
 */
// contract-test-file: tooling
import assert from "node:assert/strict";
import test from "node:test";
import { OpenMatesHooks } from "../../.opencode/plugins/openmates-hooks.js";

const { enforceAppleStopForTest } = OpenMatesHooks.test;

test("an unlatched task continues without abort", async () => {
  await enforceAppleStopForTest({ check: async () => ({ continue: true }), abort: async () => assert.fail("abort") });
});

test("latched tool calls and repeated continuations always abort", async () => {
  let aborts = 0;
  for (const origin of ["bash", "python", "ssh", "read", "mcp", "coordinator", "timeout", "resume"]) {
    await assert.rejects(enforceAppleStopForTest({
      check: async () => ({ continue: false, stopReason: "MAC_NO_DELETE_STOP", origin, confirmed: true, role: "user" }),
      abort: async () => { aborts++; },
    }), /MAC_NO_DELETE_STOP/);
  }
  assert.equal(aborts, 8);
});

test("unavailable or malformed stop state fails closed", async () => {
  for (const check of [async () => { throw new Error("unavailable"); }, async () => ({}), async () => null]) {
    let aborted = false;
    await assert.rejects(enforceAppleStopForTest({ check, abort: async () => { aborted = true; } }));
    assert.equal(aborted, true);
  }
});

test("abort failure never allows dispatch", async () => {
  await assert.rejects(enforceAppleStopForTest({
    check: async () => ({ continue: false, stopReason: "MAC_NO_DELETE_STOP" }),
    abort: async () => { throw new Error("offline"); },
  }), /All tools remain denied/);
});
