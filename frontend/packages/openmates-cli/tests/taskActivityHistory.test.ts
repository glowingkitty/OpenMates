/*
 * Task Activity pagination behavior with synthetic local pages.
 * Verifies hard read bounds and searches beyond the visible context window.
 * No live account, server or decrypted user content is used.
 * Run with Node's TypeScript stripping support.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readActivityHistory } from "../src/taskActivityHistory.ts";

// contract-test: supporting surface=cli assertions=tasks.activity.client-encrypted,tasks.activity.single-final-section
test("context reads stop at twenty entries without following all cursors", async () => {
  let calls = 0;
  const result = await readActivityHistory({ maxEntries: 20, page: async (_, limit) => {
    calls++;
    assert.equal(limit, 20);
    return { entries: Array.from({ length: limit }, () => ({ message: "recent" })), next_cursor: "older" };
  } });
  assert.equal(calls, 1);
  assert.equal(result.entries.length, 20);
  assert.equal(result.truncated, true);
  assert.equal(result.next_cursor, "older");
});

// contract-test: supporting surface=cli assertions=tasks.activity.client-encrypted,tasks.activity.single-final-section
test("search scans full history and bounds matching output", async () => {
  let calls = 0;
  const result = await readActivityHistory({ maxEntries: 1, query: "correction", page: async (cursor) => {
    calls++;
    return cursor ? { entries: [{ message: "Older CORRECTION" }, { message: "Another correction" }] }
      : { entries: [{ message: "Recent milestone" }], next_cursor: "older" };
  } });
  assert.equal(calls, 2);
  assert.equal(result.matched, 2);
  assert.equal(result.entries[0].message, "Older CORRECTION");
  assert.equal(result.truncated, true);
});

// contract-test: supporting surface=cli assertions=tasks.activity.client-encrypted,tasks.activity.single-final-section
test("invalid limits and stuck pagination fail visibly", async () => {
  await assert.rejects(readActivityHistory({ maxEntries: 0, page: async () => ({ entries: [] }) }), /max-entries/);
  await assert.rejects(readActivityHistory({ maxEntries: 20, query: "x", page: async () => ({ entries: [], next_cursor: "same" }) }), /repeated a cursor/);
});
