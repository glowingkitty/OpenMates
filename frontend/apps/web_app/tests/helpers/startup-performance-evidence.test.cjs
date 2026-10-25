'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createFrameSummary, recordFrame, longTaskWindow, persistedCounts, createStartupEvidence } = require('./startup-performance-evidence.cjs');
test('aggregates UTF-8 application bytes and whitelisted shape counts without sensitive values', () => {
  const summary = createFrameSummary();
  const secret = 'NEVER_EXPORT_ID_AUTH_KEY_CURSOR_TITLE';
  const parsed = { type: 'phase_1b_chat_content_ready', payload: { chats: [{ chat_id: secret, title: secret, messages: [{ encrypted_content: secret }], message_window: { start_cursor: secret } }], embed_keys: [secret] } };
  const raw = JSON.stringify(parsed) + 'é';
  recordFrame(summary, raw, parsed, 100);
  recordFrame(summary, '{}', { type: secret, payload: { auth: secret } }, 110);
  recordFrame(summary, Buffer.from([255]), null, 115);
  assert.equal(summary.utf8ApplicationBytes, Buffer.byteLength(raw) + 3);
  assert.equal(summary.shapes.chats, 1); assert.equal(summary.shapes.messages, 1);
  assert.equal(summary.shapes.embedKeys, 1); assert.equal(summary.types.other, 1);
  assert.equal(summary.nonJsonFrames, 1); assert.equal(summary.firstPhase1bAtMs, 100);
  assert.equal(JSON.stringify(summary).includes(secret), false);
});
test('repeated phase frames preserve first receipt and count every bounded shape', () => {
  const summary = createFrameSummary();
  const parsed = { type: 'phase_2_last_20_chats_ready', payload: { chats: [{},{}] } };
  recordFrame(summary, '{}', parsed, 10); recordFrame(summary, '{}', parsed, 20);
  assert.equal(summary.firstPhase2AtMs, 10); assert.equal(summary.shapes.chats, 4);
});
test('long task window excludes starts and completions crossing window boundaries', () => {
  assert.deepEqual(longTaskWindow({ supported: true, omitted: 4, tasks: [{ startEpochMs: 9, durationMs: 90 },{ startEpochMs: 10, durationMs: 50 },{ startEpochMs: 20, durationMs: 60 },{ startEpochMs: 90, durationMs: 50 },{ startEpochMs: 100, durationMs: 50 }] }, 10, 100), {
    supported: true, count: 2, durationMs: 110, maxDurationMs: 60, omittedDocumentTasks: 4, thresholdMs: 50, maxStoredDocumentTasks: 4096,
  });
  assert.equal(longTaskWindow(null, 10, 20).supported, false);
});
test('snapshot never opens or creates database when listing API unavailable', async () => {
  const original = global.indexedDB;
  try {
    global.indexedDB = { open() { throw new Error('must not open'); } };
    assert.deepEqual(await persistedCounts({ evaluate: (fn) => fn() }), { available: false, chats: null, messages: null, reason: 'database_listing_unsupported' });
    global.indexedDB.databases = async () => [];
    assert.deepEqual(await persistedCounts({ evaluate: (fn) => fn() }), { available: false, chats: null, messages: null, reason: 'database_absent' });
  } finally { global.indexedDB = original; }
});

test('list/open race aborts upgrade and closes database without creating stores', async () => {
  const original = global.indexedDB;
  let aborted = 0, closed = 0;
  try {
    global.indexedDB = { databases: async () => [{ name: 'chats_db' }], open() {
      const request = { transaction: { abort() { aborted++; } }, result: { close() { closed++; } } };
      queueMicrotask(() => request.onupgradeneeded());
      return request;
    } };
    const result = await persistedCounts({ evaluate: (fn) => fn() });
    assert.equal(result.available, false); assert.equal(result.reason, 'snapshot_unavailable');
    assert.equal(aborted, 1); assert.equal(closed, 1);
  } finally { global.indexedDB = original; }
});
test('blocked open reports bounded unavailable and closes any late successful connection', async () => {
  const original = global.indexedDB;
  let closed = 0, request;
  try {
    global.indexedDB = { databases: async () => [{ name: 'chats_db' }], open() {
      request = { result: { close() { closed++; } } };
      queueMicrotask(() => request.onblocked());
      return request;
    } };
    const result = await persistedCounts({ evaluate: (fn) => fn() });
    assert.equal(result.available, false);
    request.onsuccess(); assert.equal(closed, 1);
  } finally { global.indexedDB = original; }
});
test('stalled open returns unavailable after its bound and closes late success', async () => {
  const original = global.indexedDB;
  let closed = 0, request;
  try {
    global.indexedDB = { databases: async () => [{ name: 'chats_db' }], open() {
      request = { result: { close() { closed++; } } };
      return request;
    } };
    const result = await persistedCounts({ evaluate: (fn) => fn() });
    assert.equal(result.available, false);
    request.onsuccess(); assert.equal(closed, 1);
  } finally { global.indexedDB = original; }
});

test('closed window excludes a frame received while its count snapshot is blocked', async () => {
  let releaseCounts, evaluation = 0, attached;
  const blockedCounts = new Promise((resolve) => { releaseCounts = resolve; });
  const page = {
    addInitScript: async () => {},
    evaluate: async () => {
      evaluation++;
      if (evaluation === 1) return blockedCounts;
      return {};
    },
    context: () => ({ browser: () => ({ version: () => '123.0' }) }),
    viewportSize: () => ({ width: 800, height: 600 }),
  };
  const evidence = await createStartupEvidence(page);
  evidence.begin('startup-transport');
  const phase1b = { type: 'phase_1b_chat_content_ready', payload: { chats: [] } };
  evidence.recordFrame('{}', phase1b);
  const ending = evidence.end();
  evidence.recordFrame('{}', { type: 'phase_2_last_20_chats_ready', payload: { chats: [] } });
  releaseCounts({ available: true, chats: 23, messages: 1 });
  await ending;
  await evidence.attach({ project: { use: { browserName: 'chromium' } }, attach: async (_name, value) => { attached = JSON.parse(value.body); } });
  assert.equal(attached.windows[0].received.frames, 1);
  assert.equal(attached.windows[0].received.types.phase_2_last_20_chats_ready, undefined);
  assert.equal(attached.windows[0].phaseReceiptMs.phase2, null);
  assert.equal(attached.received.frames, 2);
  assert.equal(attached.received.types.phase_2_last_20_chats_ready, 1);
  const snapshot = attached.windows[0].persistedCountsSnapshot;
  assert.ok(snapshot.startedMsAfterWindowEnd >= 0);
  assert.ok(snapshot.completedMsAfterWindowEnd >= snapshot.startedMsAfterWindowEnd);
  assert.equal(snapshot.counts.chats, 23);
});
