import test from 'node:test';
import assert from 'node:assert/strict';
import endpoint from '../src/index.js';
import {suppressionId, validateRequest, updateSuppression} from '../src/operations.js';

function request() {
  const hash = 'a'.repeat(64);
  const id = suppressionId('ci', hash);
  return {id, expected_version: 1, data: {id, recipient_hash: hash, environment: 'ci',
    status: 'clear', reason_code: 'delivered', last_event_at: '2026-10-14T12:00:00+00:00',
    last_event_hash: 'b'.repeat(64), suppressed_until: null, recent_failures: [], version: 2}};
}

// contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent
test('identity matches Python UUIDv5 URL namespace', () => {
  assert.equal(suppressionId('ci', 'a'.repeat(64)), 'd3281583-b9b1-54f3-82de-7eb2bfcf400d');
});

// contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent
test('rejects private text, identity mutation, invalid deadlines and unbounded history', () => {
  const original = request();
  assert.equal(validateRequest(original), original.data);
  for (const mutate of [
    (body) => {body.data.reason = 'private smtp text';},
    (body) => {body.data.environment = 'production';},
    (body) => {body.data.recipient_hash = 'c'.repeat(64);},
    (body) => {body.data.version = 3;},
    (body) => {body.data.recent_failures = Array(4).fill({hash: 'd'.repeat(64), at: body.data.last_event_at});},
    (body) => {body.data.status = 'temporary'; body.data.suppressed_until = '2026-10-16T12:00:00Z';},
  ]) {
    const body = structuredClone(original);
    mutate(body);
    assert.throws(() => validateRequest(body), (error) => error.status === 400);
  }
});

// contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent
test('SQL mutation includes version/immutable identity and event ordering predicates', async () => {
  const body = request();
  const calls = [];
  const query = {
    where(...args) {calls.push(['where', ...args]); return this;},
    whereNot(...args) {calls.push(['whereNot', ...args]); return this;},
    update(data) {calls.push(['update', data]); return this;},
    async returning() {return [body.data];},
  };
  const database = (collection) => {assert.equal(collection, 'email_delivery_suppressions'); return query;};
  assert.equal((await updateSuppression(database, body)).version, 2);
  assert.deepEqual(calls[0], ['where', {id: body.id, version: 1, environment: 'ci', recipient_hash: body.data.recipient_hash}]);
  assert.deepEqual(calls[1], ['where', 'last_event_at', '<=', body.data.last_event_at]);
  assert.deepEqual(calls[2], ['whereNot', 'status', 'permanent']);
  query.returning = async () => [];
  await assert.rejects(() => updateSuppression(database, body), (error) => error.status === 409 && error.code === 'version_conflict');
});

// contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent
test('unauthenticated/non-admin requests never reach SQL', async () => {
  let handler;
  endpoint.handler({post: (path, callback) => {handler = callback;}}, {
    database: () => {throw new Error('SQL must not run');}, logger: {error() {}},
  });
  for (const accountability of [undefined, {admin: false}, {admin: 'true'}]) {
    let status;
    const response = {status(value) {status = value; return this;}, json(body) {return body;}};
    const result = await handler({accountability, body: request()}, response);
    assert.equal(status, 403);
    assert.equal(result.error.code, 'admin_required');
  }
});
