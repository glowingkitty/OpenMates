#!/usr/bin/env node
/*
 * Performance contracts for debounced presence persistence.
 * Streaming bursts must collapse to bounded asynchronous writes and must never
 * synchronously spawn one Python process per token delta.
 * Run: node --test scripts/tests/test_opencode_presence_performance.mjs.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { OpenMatesHooks } from "../../.opencode/plugins/openmates-hooks.js";

const { createPresenceSchedulerForTest, runProcessForTest } = OpenMatesHooks.test;

test("slow presence polling remains single-flight and disposal aborts pending work", async () => {
  let calls = 0;
  let signal;
  let release;
  const poll = OpenMatesHooks.test.createPresencePollForTest(async nextSignal => {
    calls++;
    signal = nextSignal;
    await new Promise(resolve => { release = resolve; });
  });
  const pending = Array.from({ length: 100 }, () => poll.run());
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 1);
  poll.dispose();
  assert.equal(signal.aborted, true);
  release();
  await Promise.all(pending);
  await poll.run();
  assert.equal(calls, 1);
});

test("failed status responses cannot be mistaken for an empty idle snapshot", () => {
  const validate = OpenMatesHooks.test.validatedPresenceStatusesForTest;
  assert.throws(() => validate({ error: { message: "timeout" } }), /preserving presence/);
  assert.throws(() => validate({ data: [] }), /preserving presence/);
  assert.deepEqual(validate({ data: { "ses-a": { type: "busy" } } }), { "ses-a": { type: "busy" } });
  assert.deepEqual(validate({ data: {} }), {});
});

test("disposed presence schedulers cancel queued writes", async () => {
  let writes = 0;
  let cancelled = false;
  const scheduler = createPresenceSchedulerForTest({
    persist: async () => { writes++; },
    setTimer: () => 1,
    clearTimer: () => { cancelled = true; },
  });
  scheduler.schedule({ session_id: "ses-a" });
  scheduler.dispose();
  scheduler.schedule({ session_id: "ses-b" });
  await scheduler.flush();
  assert.equal(writes, 0);
  assert.equal(cancelled, true);
});

test("guard subprocesses do not block the server event loop", async () => {
  let ticked = false;
  const timer = setTimeout(() => { ticked = true; }, 10);
  const result = await runProcessForTest(process.execPath, ["-e", "setTimeout(() => {}, 100)"]);
  clearTimeout(timer);
  assert.equal(result.status, 0);
  assert.equal(ticked, true);
});

test("streaming burst persists at most once per debounce interval", async () => {
  const writes = [];
  let callback;
  const scheduler = createPresenceSchedulerForTest({
    debounceMs: 100,
    persist: async (record) => writes.push(record),
    setTimer: (fn) => { callback = fn; return 1; },
    clearTimer: () => {},
  });
  for (let index = 0; index < 100; index += 1) scheduler.schedule({ session_id: "ses-a", sequence: index });
  assert.equal(writes.length, 0);
  await callback();
  assert.equal(writes.length, 1);
  assert.equal(writes[0].sequence, 99);
});

test("slow stores retain only the latest bounded pending record", async () => {
  let release;
  const writes = [];
  const scheduler = createPresenceSchedulerForTest({
    debounceMs: 0,
    persist: async (record) => { writes.push(record.sequence); await new Promise((resolve) => { release = resolve; }); },
    setTimer: (fn) => { queueMicrotask(fn); return 1; },
    clearTimer: () => {},
  });
  scheduler.schedule({ session_id: "ses-a", sequence: 1 });
  await new Promise((resolve) => setImmediate(resolve));
  for (let index = 2; index <= 50; index += 1) scheduler.schedule({ session_id: "ses-a", sequence: index });
  assert.ok(scheduler.pendingCount() <= 1);
  release();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(writes, [1, 50]);
  release();
});
