/** Internal endpoint authentication and cursor precision regression tests. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { authorized } from '../src/index.js';
import { parseCursor, readProjectChanges } from '../src/operations.js';

test('internal authentication fails closed and never accepts an empty token', () => {
  assert.equal(authorized({}, ''), false);
  assert.equal(authorized({'x-internal-service-token': 'wrong'}, 'expected'), false);
  assert.equal(authorized({'x-internal-service-token': 'expected'}, 'expected'), true);
});

test('cursor is epoch-bound and preserves integer precision', () => {
  assert.equal(parseCursor('epoch:9007199254740993', 'epoch'), 9007199254740993n);
  assert.equal(parseCursor('old:1', 'new'), null);
  for (const cursor of ['epoch:-1', 'epoch:1:extra', 'epoch:NaN', null]) assert.equal(parseCursor(cursor, 'epoch'), null);
});

test('invalid scope cannot reach the database', async () => {
  const db = { transaction: () => { throw new Error('must not query'); } };
  await assert.rejects(readProjectChanges(db, { scope: 'user-supplied-id', project_hash: 'a'.repeat(64) }), /invalid_sync_scope/);
});
