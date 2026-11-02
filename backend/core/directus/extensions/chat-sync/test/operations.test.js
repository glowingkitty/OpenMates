/** Chat sync feed: internal auth, cursor parsing, aggregation and scope validation. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { authorized, coalesceNotification } from '../src/index.js';
import { aggregateChanges, formatCursor, kindNames, parseLaneCursor, readChanges, splitCursor, KIND_BITS } from '../src/operations.js';

const A = 'a'.repeat(64);
const B = 'b'.repeat(64);

// contract-test: supporting surface=rest_api assertions=sync.access.first-party-authenticated
test('internal authentication fails closed', () => {
  assert.equal(authorized({}, ''), false);
  assert.equal(authorized({ 'x-internal-service-token': 'wrong' }, 'expected'), false);
  assert.equal(authorized({ 'x-internal-service-token': 'expected' }, 'expected'), true);
});

// contract-test: supporting surface=rest_api assertions=sync.delta.reset
test('lane cursors are epoch-bound and keep 64-bit precision', () => {
  assert.equal(parseLaneCursor('e:9007199254740993', 'e'), 9007199254740993n);
  assert.equal(parseLaneCursor('old:1', 'e'), null);
  for (const value of ['e:-1', 'e:1:2', 'e:NaN', null, 'e:' + '9'.repeat(20)]) assert.equal(parseLaneCursor(value, 'e'), null);
  assert.deepEqual(splitCursor('a:1|b:2'), ['a:1', 'b:2']);
  assert.equal(splitCursor('a:1'), null);
  assert.equal(splitCursor('x'.repeat(161)), null);
  assert.equal(formatCursor({ epoch: 'a' }, 3n, { epoch: 'b' }, 4n), 'a:3|b:4');
});

// contract-test: supporting surface=rest_api assertions=sync.delta.cursor-gap-free
test('page entries combine per chat and keep user-lane markers separate', () => {
  const rows = [
    { revision: '5', chat_id: 'c1', hashed_chat_id: 'h1', kinds: KIND_BITS.metadata },
    { revision: '6', chat_id: 'c1', hashed_chat_id: 'h1', kinds: KIND_BITS.messages },
    { revision: '7', chat_id: null, hashed_chat_id: 'h2', kinds: KIND_BITS.deleted },
    { revision: '8', chat_id: 'c3', hashed_chat_id: null, kinds: KIND_BITS.last_opened },
    { revision: '9', chat_id: null, hashed_chat_id: null, kinds: KIND_BITS.due_soon },
  ];
  const { changes, lastOpened, dueSoon } = aggregateChanges(rows);
  assert.deepEqual(changes.map(c => [c.hashed_chat_id, kindNames(c.kinds)]), [['h1', ['metadata', 'messages']], ['h2', ['deleted']]]);
  assert.deepEqual(lastOpened, { chat_id: 'c3', revision: '8' });
  assert.equal(dueSoon, true);
});

// contract-test: supporting surface=rest_api assertions=sync.delta.live-hint
test('notifications coalesce to the newest revision per scope and reject foreign payloads', () => {
  const pending = new Map();
  assert.equal(coalesceNotification(pending, `team:${A}|7`), true);
  assert.equal(coalesceNotification(pending, `team:${A}|5`), true);
  assert.equal(coalesceNotification(pending, `user:${B}|2`), true);
  assert.equal(coalesceNotification(pending, 'team:not-a-hash|1'), false);
  assert.deepEqual([...pending.entries()], [[`team:${A}`, '7'], [`user:${B}`, '2']]);
});

// contract-test: supporting surface=rest_api assertions=sync.delta.scope-revocation
test('scope validation never reaches the database for foreign or mismatched scopes', async () => {
  const db = { transaction: () => { throw new Error('must not query'); } };
  await assert.rejects(readChanges(db, { scope: 'user-supplied', user_scope: `user:${A}` }), /invalid_sync_scope/);
  await assert.rejects(readChanges(db, { scope: `personal:${A}`, user_scope: `user:${B}` }), /invalid_sync_scope/);
  await assert.rejects(readChanges(db, { scope: `team:${A}`, user_scope: 'user:x' }), /invalid_sync_scope/);
});
