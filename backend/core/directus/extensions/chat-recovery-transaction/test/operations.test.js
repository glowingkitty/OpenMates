/* Focused security and validation tests for the recovery extension. */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import { isAuthorized } from '../src/index.js';
import { operations, ProtocolError, executeOperation, testing } from '../src/operations.js';

const b64 = (length, fill) => Buffer.alloc(length, fill).toString('base64url');
const TASK_ID = '018f2222-2222-7222-8222-222222222222';
const OUTBOX_ID = '018f3333-3333-7333-8333-333333333333';
const CHAT_ID = '018f4444-4444-7444-8444-444444444444';
const TURN_ID = '018f5555-5555-7555-8555-555555555555';
const PREFLIGHT_ID = '018f1111-1111-7111-8111-111111111111';
const JOB_ID = '018f7777-7777-7777-8777-777777777777';
const BILLING_ID = '018f6666-6666-7666-8666-666666666666';
const OWNER = 'a'.repeat(64);
const TEAM_HASH = 'c'.repeat(64);
const RECOVERY_KEY = b64(32, 7);
const COMMITMENT = 'b'.repeat(64);
const SEALED_PAYLOAD = JSON.stringify({ v: 1, epk: b64(32, 1), nonce: b64(12, 2), ciphertext: b64(17, 3) });
const SEALED_OUTPUT = JSON.stringify({ v: 2, epk: b64(32, 1), nonce: b64(12, 2), ciphertext: b64(17, 3) });
const sha256 = (value) => createHash('sha256').update(value).digest('hex');

function fakeDatabase(seed, injectedFailure = null) {
  const rows = structuredClone(seed);
  let transactions = 0;
  let transactionTail = Promise.resolve();
  const shareLocks = [];
  const failureCounts = new Map();
  const compare = (left, operator, right) => {
    const a = left instanceof Date ? left.getTime() : left;
    const b = right instanceof Date ? right.getTime() : right;
    if (operator === '>') return a > b;
    if (operator === '>=') return a >= b;
    if (operator === '<') return a < b;
    if (operator === '<=') return a <= b;
    return a === b;
  };
  const maybeFail = (operation, table) => {
    const key = `${operation}:${table}`;
    const count = (failureCounts.get(key) ?? 0) + 1;
    failureCounts.set(key, count);
    if (injectedFailure?.operation === operation && injectedFailure.table === table
      && (injectedFailure.occurrence ?? 1) === count) throw new Error(`injected ${key} failure`);
  };
  const makeClient = (store) => {
    const client = (table) => {
      const predicates = [];
      const orders = [];
      let limitCount = Infinity;
      const matching = () => (store[table] ?? [])
        .filter((row) => predicates.every((predicate) => predicate(row)))
        .sort((left, right) => {
          for (const [field, direction] of orders) {
            if (left[field] === right[field]) continue;
            return (left[field] < right[field] ? -1 : 1) * (direction === 'desc' ? -1 : 1);
          }
          return 0;
        })
        .slice(0, limitCount);
      const addWhere = (args) => {
        if (typeof args[0] === 'object') {
          predicates.push((row) => Object.entries(args[0]).every(([key, value]) => compare(row[key], '=', value)));
        } else {
          const [field, operator, value] = args.length === 2 ? [args[0], '=', args[1]] : args;
          predicates.push((row) => compare(row[field], operator, value));
        }
      };
      const query = {
        where(...args) { addWhere(args); return query; },
        andWhere(...args) { addWhere(args); return query; },
        whereRaw(sql, bindings) {
          if (sql === '(created_at, id) > (?, ?::uuid)') {
            predicates.push((row) => compare(row.created_at, '>', bindings[0])
              || (compare(row.created_at, '=', bindings[0]) && compare(row.id, '>', bindings[1])));
          } else if (sql === `EXISTS (SELECT 1 FROM chats c WHERE c.id = ${table}.chat_id AND c.hashed_team_id IS NOT NULL)`) {
            predicates.push((row) => (store.chats ?? []).some((chat) => chat.id === row.chat_id && chat.hashed_team_id != null));
          } else if (sql === 'NOT EXISTS (SELECT 1 FROM chat_recovery_outputs o WHERE o.preflight_id = chat_turn_preflights.id AND o.deleted_at IS NULL)') {
            predicates.push((row) => !(store.chat_recovery_outputs ?? []).some((output) => output.preflight_id === row.id && output.deleted_at == null));
          } else {
            throw new Error(`unsupported fake whereRaw: ${sql}`);
          }
          return query;
        },
        whereNull(field) { predicates.push((row) => row[field] == null); return query; },
        whereNotNull(field) { predicates.push((row) => row[field] != null); return query; },
        whereIn(field, values) { predicates.push((row) => values.includes(row[field])); return query; },
        whereNotIn(field, values) { predicates.push((row) => !values.includes(row[field])); return query; },
        forUpdate() { return query; },
        forShare() { shareLocks.push(table); return query; },
        orderBy(field, direction = 'asc') { orders.push([field, direction]); return query; },
        limit(value) { limitCount = value; return query; },
        async first() { return matching()[0]; },
        async select(fields) {
          return matching().map((row) => Object.fromEntries(fields.map((field) => [field, row[field]])));
        },
        async pluck(field) { return matching().map((row) => row[field]); },
        async insert(value) {
          maybeFail('insert', table);
          store[table] ??= [];
          for (const row of Array.isArray(value) ? value : [value]) {
            const stored = structuredClone(row);
            if (table === 'chat_recovery_protocol_state') {
              for (const field of ['active_legacy_tasks', 'legacy_task_lifecycle']) {
                if (typeof stored[field] === 'string') stored[field] = JSON.parse(stored[field]);
              }
            }
            store[table].push(stored);
          }
          return 1;
        },
        async update(values) {
          maybeFail('update', table);
          const found = matching();
          for (const row of found) {
            for (const [field, value] of Object.entries(values)) {
              if (table === 'chat_recovery_protocol_state'
                && ['active_legacy_tasks', 'legacy_task_lifecycle'].includes(field)
                && typeof value === 'string') {
                row[field] = JSON.parse(value);
              } else {
                row[field] = value?.rawExpression === `${field} + 1` ? row[field] + 1 : structuredClone(value);
              }
            }
          }
          return found.length;
        },
        async delete() {
          maybeFail('delete', table);
          const found = new Set(matching());
          store[table] = (store[table] ?? []).filter((row) => !found.has(row));
          return found.size;
        },
      };
      return query;
    };
    client.raw = (value) => typeof value === 'string' && /\w+ \+ 1/.test(value) ? { rawExpression: value } : value;
    return client;
  };
  const database = makeClient(rows);
  database.rows = rows;
  Object.defineProperty(database, 'transactions', { get: () => transactions });
  Object.defineProperty(database, 'shareLocks', { get: () => [...shareLocks] });
  database.transaction = async (callback) => {
    const run = transactionTail.then(async () => {
      transactions += 1;
      const working = structuredClone(rows);
      const result = await callback(makeClient(working));
      for (const key of new Set([...Object.keys(rows), ...Object.keys(working)])) rows[key] = working[key] ?? [];
      return result;
    });
    transactionTail = run.catch(() => undefined);
    return run;
  };
  return database;
}

const userMessage = (id = 'user-message-1') => ({
  client_message_id: id, chat_id: CHAT_ID, hashed_user_id: OWNER, encrypted_content: 'encrypted-user',
  role: 'user', created_at: 100, updated_at: 100,
});
const assistantMessage = () => ({
  client_message_id: 'assistant-message-1', chat_id: CHAT_ID, hashed_user_id: OWNER,
  encrypted_content: 'encrypted-assistant', role: 'assistant', created_at: 200, updated_at: 200,
  user_message_id: 'user-message-1',
});
const prepareBody = (overrides = {}) => ({
  protocol_version: 1, hashed_user_id: OWNER, chat_id: CHAT_ID, turn_id: TURN_ID,
  user_message_id: 'user-message-1', device_hash: 'device-a', chat_key_version: 1,
  wrapped_chat_key: 'wrapped-key-1', recovery_public_key: RECOVERY_KEY,
  inference_commitment: COMMITMENT, commitment_version: 1, expected_messages_v: 0,
  encrypted_user_message: userMessage(),
  encrypted_chat_metadata: { encrypted_title: 'encrypted-title', encrypted_chat_key: 'wrapped-key-1', created_at: 100, updated_at: 100 },
  ...overrides,
});
const preparedSeed = () => ({
  chats: [{ id: CHAT_ID, hashed_user_id: OWNER, encrypted_chat_key: 'wrapped-key-1', messages_v: 1 }],
  messages: [userMessage()],
  chat_turn_preflights: [{
    id: PREFLIGHT_ID, hashed_user_id: OWNER, chat_id: CHAT_ID, turn_id: TURN_ID,
    user_message_id: 'user-message-1', device_hash: 'device-a', chat_key_version: 1,
    wrapped_chat_key: 'wrapped-key-1', recovery_public_key: RECOVERY_KEY,
    encrypted_user_digest: testing.digest(userMessage()), inference_commitment: COMMITMENT,
    commitment_version: 1, expected_messages_v: 0, committed_messages_v: 1,
    state: 'PREPARED', prepared_at: new Date('2029-01-01T00:00:00Z'), expires_at: new Date('2030-01-01T00:00:00Z'),
  }],
  chat_inference_outbox: [], chat_completion_recovery_jobs: [],
});
const leasedSeed = (now = new Date('2029-01-01T00:00:00Z')) => ({
  chats: [{ id: CHAT_ID, hashed_user_id: OWNER, encrypted_chat_key: 'wrapped-key-1', messages_v: 1 }],
  messages: [userMessage()],
  chat_turn_preflights: [{ id: PREFLIGHT_ID, hashed_user_id: OWNER, chat_id: CHAT_ID, turn_id: TURN_ID, state: 'RUNNING' }],
  chat_inference_outbox: [],
  operational_monitoring_events: [],
  chat_completion_recovery_jobs: [{
    id: JOB_ID, hashed_user_id: OWNER, chat_id: CHAT_ID, turn_id: TURN_ID, preflight_id: PREFLIGHT_ID,
    inference_task_id: TASK_ID, assistant_message_id: 'assistant-message-1', chat_key_version: 1,
    sealed_payload: SEALED_PAYLOAD, sealed_payload_digest: testing.digest(SEALED_PAYLOAD), state: 'AVAILABLE',
    lease_generation: 0, created_at: now, expires_at: new Date(now.getTime() + 7 * 24 * 60 * 60_000),
  }],
});
const lifecycleRecord = (taskIdentity, state, expiresAt, persistenceObserved) => ({
  task_identity: taskIdentity,
  state,
  expires_at: expiresAt,
  ...(persistenceObserved === undefined ? {} : { persistence_observed: persistenceObserved }),
});
const protocolSeed = ({
  epoch = 0,
  paused = false,
  active = [],
  lifecycle = [],
} = {}) => ({
  chat_recovery_protocol_state: [{
    id: 'chat-recovery', protocol_epoch: epoch, sends_paused: paused,
    legacy_in_flight: active.length, active_legacy_tasks: active,
    legacy_task_lifecycle: lifecycle,
  }],
});
const legacyBody = (taskIdentity) => ({ protocol_version: 1, task_identity: taskIdentity });

test('internal authentication fails closed', () => {
  assert.equal(isAuthorized({}, undefined), false);
  assert.equal(isAuthorized({}, 'configured'), false);
  assert.equal(isAuthorized({ 'x-internal-service-token': 'wrong' }, 'configured'), false);
  assert.equal(isAuthorized({ 'x-internal-service-token': 'configured' }, 'configured'), true);
});

test('operation dispatch rejects unknown operations before database access', async () => {
  await assert.rejects(
    executeOperation(null, 'not_supported', {}),
    (error) => error instanceof ProtocolError && error.code === 'unsupported_operation',
  );
});

test('operation bodies reject unrecognized plaintext-bearing fields before database access', async () => {
  await assert.rejects(
    executeOperation(null, 'prepare_preflight', { protocol_version: 1, plaintext: 'must-not-cross-boundary' }),
    (error) => error instanceof ProtocolError && error.code === 'invalid_request',
  );
});

test('sealed envelope validation accepts exact fields and rejects duplicates', () => {
  const valid = JSON.stringify({ v: 1, epk: b64(32, 1), nonce: b64(12, 2), ciphertext: b64(17, 3) });
  assert.equal(testing.validateEnvelope(valid), valid);
  const duplicate = `{"v":1,"v":1,"epk":"${b64(32, 1)}","nonce":"${b64(12, 2)}","ciphertext":"${b64(17, 3)}"}`;
  assert.throws(
    () => testing.validateEnvelope(duplicate),
    (error) => error instanceof ProtocolError && error.code === 'invalid_sealed_payload',
  );
});

test('encrypted message validation rejects unknown plaintext fields', () => {
  const message = {
    client_message_id: 'message-1',
    chat_id: '018f1111-1111-7111-8111-111111111111',
    hashed_user_id: 'owner-hash',
    encrypted_content: 'ciphertext',
    role: 'user',
    created_at: 1,
    updated_at: 1,
    plaintext: 'must-not-cross-boundary',
  };
  assert.throws(
    () => testing.validateMessage(message, 'user', { chatId: message.chat_id, ownerHash: message.hashed_user_id }),
    (error) => error instanceof ProtocolError && error.code === 'invalid_encrypted_message',
  );
});

test('new-chat metadata is strict, encrypted, and private by construction', () => {
  const metadata = {
    encrypted_title: 'encrypted-title',
    encrypted_slug: 'encrypted-slug',
    slug_lookup_hash: 'a'.repeat(64),
    encrypted_chat_key: 'wrapped-chat-key',
    created_at: 100,
    updated_at: 100,
  };
  assert.deepEqual(
    testing.validateNewChatMetadata(metadata, {
      chatId: '018f1111-1111-7111-8111-111111111111',
      ownerHash: 'a'.repeat(64),
      wrappedKey: 'wrapped-chat-key',
    }),
    metadata,
  );
  assert.throws(
    () => testing.validateNewChatMetadata({ ...metadata, title: 'plaintext' }, {
      chatId: '018f1111-1111-7111-8111-111111111111',
      ownerHash: 'a'.repeat(64),
      wrappedKey: 'wrapped-chat-key',
    }),
    (error) => error instanceof ProtocolError && error.code === 'invalid_encrypted_chat_metadata',
  );
});

test('inference claim decision prevents duplicate RUNNING or terminal execution', () => {
  assert.equal(testing.inferenceClaimDecision('ENQUEUED'), true);
  assert.equal(testing.inferenceClaimDecision('RUNNING'), false);
  assert.equal(testing.inferenceClaimDecision('TERMINAL'), false);
  assert.equal(testing.inferenceClaimDecision('FAILED'), false);
  assert.throws(
    () => testing.inferenceClaimDecision('PREPARED'),
    (error) => error instanceof ProtocolError && error.code === 'invalid_inference_state',
  );
});

test('cleanup fails only RUNNING preflights that have no sealed job', () => {
  assert.deepEqual(
    testing.unsealedPreflightIds(['preflight-1', 'preflight-2'], ['preflight-2']),
    ['preflight-1'],
  );
});

test('worker lifecycle operations are explicitly registered', () => {
  for (const operation of [
    'claim_inference', 'mark_outbox_dispatched', 'mark_inference_failed', 'list_available_jobs',
    'acknowledge_failure_alert',
    'mark_legacy_inference_completed', 'acknowledge_legacy_persistence', 'authorize_legacy_completion',
  ]) {
    assert.equal(typeof operations[operation], 'function');
  }
});

test('legacy admission is serialized, durable, and released exactly once', async () => {
  const database = fakeDatabase({ chat_recovery_protocol_state: [] });
  const now = new Date('2029-01-01T00:00:00.000Z');

  const [first, second] = await Promise.all([
    executeOperation(database, 'admit_legacy_inference', legacyBody('message-a'), now),
    executeOperation(database, 'admit_legacy_inference', legacyBody('message-b'), now),
  ]);
  const duplicate = await executeOperation(database, 'admit_legacy_inference', legacyBody('message-a'), now);
  const released = await executeOperation(database, 'release_legacy_inference', legacyBody('message-a'), now);
  const duplicateRelease = await executeOperation(database, 'release_legacy_inference', legacyBody('message-a'), now);

  assert.equal(first.admitted, true);
  assert.equal(second.admitted, true);
  assert.equal(duplicate.idempotent, true);
  assert.equal(released.released, true);
  assert.equal(duplicateRelease.idempotent, true);
  assert.equal(database.rows.chat_recovery_protocol_state[0].legacy_in_flight, 1);
  assert.deepEqual(database.rows.chat_recovery_protocol_state[0].active_legacy_tasks, ['message-b']);
  assert.deepEqual(database.rows.chat_recovery_protocol_state[0].legacy_task_lifecycle, [
    lifecycleRecord('message-b', 'RUNNING', '2029-01-01T00:15:00.000Z'),
  ]);
});

test('server-trigger admission is allowed after epoch one without reopening legacy client sends', async () => {
  const now = new Date('2029-01-01T00:00:00.000Z');
  const database = fakeDatabase(protocolSeed({ epoch: 1, paused: true }));

  await assert.rejects(
    executeOperation(database, 'admit_legacy_inference', legacyBody('message-a'), now),
    (error) => error instanceof ProtocolError && error.code === 'client_update_required',
  );

  const result = await executeOperation(
    database,
    'admit_legacy_inference',
    legacyBody('server-trigger:message-a'),
    now,
  );

  assert.equal(result.admitted, true);
  assert.equal(result.idempotent, false);
  assert.equal(database.rows.chat_recovery_protocol_state[0].protocol_epoch, 1);
  assert.equal(database.rows.chat_recovery_protocol_state[0].legacy_in_flight, 1);
  assert.deepEqual(database.rows.chat_recovery_protocol_state[0].active_legacy_tasks, ['server-trigger:message-a']);
});

test('legacy admission prunes an expired running retry before admitting it once', async () => {
  const now = new Date('2029-01-01T00:15:00.000Z');
  const database = fakeDatabase(protocolSeed({
    active: ['message-a'],
    lifecycle: [lifecycleRecord('message-a', 'RUNNING', now.toISOString())],
  }));

  const result = await executeOperation(
    database, 'admit_legacy_inference', legacyBody('message-a'), now,
  );

  assert.equal(result.admitted, true);
  assert.equal(result.idempotent, false);
  assert.equal(result.legacy_in_flight, 1);
  assert.deepEqual(database.rows.chat_recovery_protocol_state[0].active_legacy_tasks, ['message-a']);
  assert.deepEqual(database.rows.chat_recovery_protocol_state[0].legacy_task_lifecycle, [
    lifecycleRecord('message-a', 'RUNNING', '2029-01-01T00:30:00.000Z'),
  ]);
  assert.equal(database.rows.chat_recovery_protocol_state[0].legacy_in_flight, 1);
});

test('early persistence does not decrement until completion, which records a persisted tombstone', async () => {
  const now = new Date('2029-01-01T00:00:00.000Z');
  const database = fakeDatabase(protocolSeed());
  await executeOperation(database, 'admit_legacy_inference', legacyBody('message-a'), now);

  const acknowledged = await executeOperation(
    database, 'acknowledge_legacy_persistence', legacyBody('message-a'), new Date(now.getTime() + 1000),
  );
  assert.equal(acknowledged.state, 'RUNNING');
  assert.equal(database.rows.chat_recovery_protocol_state[0].legacy_in_flight, 1);
  assert.deepEqual(database.rows.chat_recovery_protocol_state[0].active_legacy_tasks, ['message-a']);
  assert.equal(database.rows.chat_recovery_protocol_state[0].legacy_task_lifecycle[0].persistence_observed, true);

  const completed = await executeOperation(
    database, 'mark_legacy_inference_completed', legacyBody('message-a'), new Date(now.getTime() + 2000),
  );
  assert.equal(completed.state, 'PERSISTED');
  assert.equal(database.rows.chat_recovery_protocol_state[0].legacy_in_flight, 0);
  assert.deepEqual(database.rows.chat_recovery_protocol_state[0].active_legacy_tasks, []);
  assert.deepEqual(database.rows.chat_recovery_protocol_state[0].legacy_task_lifecycle, [
    lifecycleRecord('message-a', 'PERSISTED', '2029-01-02T00:00:02.000Z', true),
  ]);
});

test('completion awaits persistence, authorizes terminal work, and pending state does not block activation', async () => {
  const now = new Date('2029-01-01T00:00:00.000Z');
  const database = fakeDatabase(protocolSeed({ active: ['message-a'], lifecycle: [
    lifecycleRecord('message-a', 'RUNNING', '2029-01-01T00:15:00.000Z'),
  ] }));
  const completed = await executeOperation(database, 'mark_legacy_inference_completed', legacyBody('message-a'), now);
  assert.equal(completed.state, 'AWAITING_PERSISTENCE');
  assert.equal((await executeOperation(database, 'authorize_legacy_completion', legacyBody('message-a'), now)).authorized, true);
  await executeOperation(database, 'set_sends_paused', { protocol_version: 1, sends_paused: true }, now);
  const activated = await executeOperation(
    database, 'activate_protocol_epoch', { protocol_version: 1, target_epoch: 1 }, now,
  );
  assert.equal(activated.activated, true);

  const persisted = await executeOperation(
    database, 'acknowledge_legacy_persistence', legacyBody('message-a'), new Date(now.getTime() + 1000),
  );
  const retry = await executeOperation(
    database, 'acknowledge_legacy_persistence', legacyBody('message-a'), new Date(now.getTime() + 2000),
  );
  const duplicateCompletion = await executeOperation(
    database, 'mark_legacy_inference_completed', legacyBody('message-a'), new Date(now.getTime() + 3000),
  );
  assert.equal(persisted.state, 'PERSISTED');
  assert.equal((await executeOperation(
    database, 'authorize_legacy_completion', legacyBody('message-a'), new Date(now.getTime() + 3000),
  )).authorized, true);
  assert.equal(retry.idempotent, true);
  assert.equal(duplicateCompletion.idempotent, true);
});

test('legacy completion authorization rejects running, absent, and expired identities explicitly', async () => {
  const now = new Date('2029-01-01T00:00:00.000Z');
  const running = fakeDatabase(protocolSeed({ active: ['running'], lifecycle: [
    lifecycleRecord('running', 'RUNNING', '2029-01-01T00:15:00.000Z'),
  ] }));
  await assert.rejects(
    executeOperation(running, 'authorize_legacy_completion', legacyBody('running'), now),
    (error) => error instanceof ProtocolError && error.code === 'legacy_completion_not_ready',
  );
  await assert.rejects(
    executeOperation(running, 'authorize_legacy_completion', legacyBody('absent'), now),
    (error) => error instanceof ProtocolError && error.code === 'legacy_completion_not_found',
  );
  const expired = fakeDatabase(protocolSeed({ lifecycle: [
    lifecycleRecord('expired', 'AWAITING_PERSISTENCE', now.toISOString()),
  ] }));
  await assert.rejects(
    executeOperation(expired, 'authorize_legacy_completion', legacyBody('expired'), now),
    (error) => error instanceof ProtocolError && error.code === 'legacy_completion_expired',
  );
});

test('absent lifecycle updates never recreate records and release removes running state', async () => {
  const now = new Date('2029-01-01T00:00:00.000Z');
  const database = fakeDatabase(protocolSeed({ active: ['message-a'], lifecycle: [
    lifecycleRecord('message-a', 'RUNNING', '2029-01-01T00:15:00.000Z'),
  ] }));
  const absentCompletion = await executeOperation(database, 'mark_legacy_inference_completed', legacyBody('absent'), now);
  const absentPersistence = await executeOperation(database, 'acknowledge_legacy_persistence', legacyBody('absent'), now);
  assert.equal(absentCompletion.state, null);
  assert.equal(absentPersistence.state, null);
  assert.equal(database.rows.chat_recovery_protocol_state[0].legacy_task_lifecycle.length, 1);

  const released = await executeOperation(database, 'release_legacy_inference', legacyBody('message-a'), now);
  assert.equal(released.released, true);
  assert.equal(database.rows.chat_recovery_protocol_state[0].legacy_in_flight, 0);
  assert.deepEqual(database.rows.chat_recovery_protocol_state[0].active_legacy_tasks, []);
  assert.deepEqual(database.rows.chat_recovery_protocol_state[0].legacy_task_lifecycle, []);
});

test('legacy lifecycle cleanup prunes all expired states and active running identities', async () => {
  const now = new Date('2029-01-02T00:00:00.000Z');
  const database = fakeDatabase({
    ...protocolSeed({
      active: ['expired-running', 'live-running'],
      lifecycle: [
        lifecycleRecord('expired-running', 'RUNNING', now.toISOString()),
        lifecycleRecord('live-running', 'RUNNING', '2029-01-02T00:01:00.000Z'),
        lifecycleRecord('awaiting', 'AWAITING_PERSISTENCE', now.toISOString()),
        lifecycleRecord('persisted', 'PERSISTED', now.toISOString()),
      ],
    }),
    chat_turn_preflights: [], chat_completion_recovery_jobs: [], chat_inference_outbox: [],
  });
  const result = await executeOperation(database, 'cleanup_expired', { protocol_version: 1 }, now);
  assert.deepEqual({
    expired_legacy_running: result.expired_legacy_running,
    expired_legacy_awaiting_persistence: result.expired_legacy_awaiting_persistence,
    expired_legacy_persisted: result.expired_legacy_persisted,
  }, {
    expired_legacy_running: 1,
    expired_legacy_awaiting_persistence: 1,
    expired_legacy_persisted: 1,
  });
  assert.deepEqual(database.rows.chat_recovery_protocol_state[0].active_legacy_tasks, ['live-running']);
  assert.equal(database.rows.chat_recovery_protocol_state[0].legacy_in_flight, 1);
  assert.deepEqual(database.rows.chat_recovery_protocol_state[0].legacy_task_lifecycle, [
    lifecycleRecord('live-running', 'RUNNING', '2029-01-02T00:01:00.000Z'),
  ]);
});

test('activation prunes expired running identities before enforcing the active drain', async () => {
  const now = new Date('2029-01-01T00:15:00.000Z');
  const database = fakeDatabase(protocolSeed({
    paused: true,
    active: ['expired-running'],
    lifecycle: [lifecycleRecord('expired-running', 'RUNNING', now.toISOString())],
  }));
  const result = await executeOperation(
    database, 'activate_protocol_epoch', { protocol_version: 1, target_epoch: 1 }, now,
  );
  assert.equal(result.activated, true);
  assert.equal(result.legacy_in_flight, 0);
  assert.deepEqual(database.rows.chat_recovery_protocol_state[0].legacy_task_lifecycle, []);
});

test('cutover state reads an initialized valid row without taking the global transaction lock', async () => {
  const database = fakeDatabase(protocolSeed());

  const state = await executeOperation(database, 'get_cutover_state', { protocol_version: 1 });

  assert.equal(state.protocol_epoch, 0);
  assert.equal(database.transactions, 0);
});

test('legacy lifecycle state fails closed on malformed, duplicate, or mismatched records', async () => {
  const corruptStates = [
    protocolSeed({ lifecycle: {} }),
    protocolSeed({ lifecycle: [lifecycleRecord('duplicate', 'PERSISTED', '2029-01-02T00:00:00.000Z'), lifecycleRecord('duplicate', 'PERSISTED', '2029-01-02T00:00:00.000Z')] }),
    { chat_recovery_protocol_state: [{
      id: 'chat-recovery', protocol_epoch: 0, sends_paused: false,
      legacy_in_flight: 2, active_legacy_tasks: ['running'],
      legacy_task_lifecycle: [lifecycleRecord('running', 'RUNNING', '2029-01-02T00:00:00.000Z')],
    }] },
    protocolSeed({ active: ['running'], lifecycle: [lifecycleRecord('other', 'RUNNING', '2029-01-02T00:00:00.000Z')] }),
    protocolSeed({ active: ['running'], lifecycle: [lifecycleRecord('running', 'PERSISTED', '2029-01-02T00:00:00.000Z')] }),
    protocolSeed({ lifecycle: [{ ...lifecycleRecord('extra', 'PERSISTED', '2029-01-02T00:00:00.000Z'), chat_id: 'forbidden' }] }),
  ];
  for (const seed of corruptStates) {
    await assert.rejects(
      executeOperation(fakeDatabase(seed), 'get_cutover_state', { protocol_version: 1 }),
      (error) => error instanceof ProtocolError && error.code === 'cutover_state_corrupt',
    );
  }
});

test('epoch-zero cutover state repairs missing empty legacy task placeholders', async () => {
  for (const placeholder of [null, {}]) {
    const database = fakeDatabase({
      chat_recovery_protocol_state: [{
        id: 'chat-recovery', protocol_epoch: 0, sends_paused: false,
        legacy_in_flight: 0, active_legacy_tasks: placeholder, legacy_task_lifecycle: null,
      }],
    });

    const state = await executeOperation(database, 'get_cutover_state', { protocol_version: 1 });

    assert.equal(state.protocol_epoch, 0);
    assert.deepEqual(database.rows.chat_recovery_protocol_state[0].active_legacy_tasks, []);
    assert.deepEqual(database.rows.chat_recovery_protocol_state[0].legacy_task_lifecycle, []);
  }
});

test('cutover state keeps unsafe missing legacy task lists fail-closed', async () => {
  for (const state of [
    { protocol_epoch: 0, legacy_in_flight: 1 },
    { protocol_epoch: 1, legacy_in_flight: 0 },
  ]) {
    const database = fakeDatabase({
      chat_recovery_protocol_state: [{
        id: 'chat-recovery', sends_paused: false, active_legacy_tasks: null,
        legacy_task_lifecycle: null, ...state,
      }],
    });
    await assert.rejects(
      executeOperation(database, 'get_cutover_state', { protocol_version: 1 }),
      (error) => error instanceof ProtocolError && error.code === 'cutover_state_corrupt',
    );
  }
});

test('pause and activation are atomic and epoch monotonic', async () => {
  const database = fakeDatabase({ chat_recovery_protocol_state: [] });
  await executeOperation(database, 'set_sends_paused', { protocol_version: 1, sends_paused: true });
  await assert.rejects(
    executeOperation(database, 'admit_legacy_inference', { protocol_version: 1, task_identity: 'message-a' }),
    (error) => error instanceof ProtocolError && error.code === 'inference_temporarily_paused',
  );
  const activated = await executeOperation(database, 'activate_protocol_epoch', {
    protocol_version: 1, target_epoch: 1,
  });
  assert.equal(activated.protocol_epoch, 1);
  await assert.rejects(
    executeOperation(database, 'activate_protocol_epoch', { protocol_version: 1, target_epoch: 0 }),
    (error) => error instanceof ProtocolError && error.code === 'protocol_epoch_rollback',
  );
  assert.equal(database.rows.chat_recovery_protocol_state[0].protocol_epoch, 1);
});

test('activation rollback preserves epoch zero when its durable update fails', async () => {
  const database = fakeDatabase({
    chat_recovery_protocol_state: [{
      id: 'chat-recovery', protocol_epoch: 0, sends_paused: true,
      legacy_in_flight: 0, active_legacy_tasks: [], legacy_task_lifecycle: [],
    }],
  }, { operation: 'update', table: 'chat_recovery_protocol_state' });
  await assert.rejects(
    executeOperation(database, 'activate_protocol_epoch', { protocol_version: 1, target_epoch: 1 }),
    /injected update:chat_recovery_protocol_state failure/,
  );
  assert.equal(database.rows.chat_recovery_protocol_state[0].protocol_epoch, 0);
});

test('available-job projection never discloses sealed payload or lease secrets', () => {
  const projected = testing.availableJobMetadata({
    id: '018f7777-7777-7777-8777-777777777777',
    chat_id: '018f4444-4444-7444-8444-444444444444',
    turn_id: '018f5555-5555-7555-8555-555555555555',
    inference_task_id: TASK_ID,
    assistant_message_id: 'assistant-message-1',
    chat_key_version: 1,
    state: 'AVAILABLE',
    sealed_payload: 'must-not-be-returned',
    sealed_payload_digest: 'must-not-be-returned',
    lease_token_digest: 'must-not-be-returned',
    lease_holder_hash: 'must-not-be-returned',
    lease_expires_at: '2030-01-01T00:00:00.000Z',
  });

  assert.deepEqual(projected, {
    job_id: '018f7777-7777-7777-8777-777777777777',
    chat_id: '018f4444-4444-7444-8444-444444444444',
    turn_id: '018f5555-5555-7555-8555-555555555555',
    inference_task_id: TASK_ID,
    assistant_message_id: 'assistant-message-1',
    chat_key_version: 1,
    state: 'AVAILABLE',
  });
  assert.equal('sealed_payload' in projected, false);
  assert.equal('lease_token_digest' in projected, false);
  assert.equal('lease_holder_hash' in projected, false);
  assert.equal('lease_expires_at' in projected, false);
});

test('claim_inference atomically claims once and suppresses duplicate delivery', async () => {
  const database = fakeDatabase({
    chat_turn_preflights: [{
      id: '018f1111-1111-7111-8111-111111111111',
      inference_task_id: TASK_ID,
      state: 'ENQUEUED',
      expires_at: '2030-01-01T00:00:00.000Z',
      hashed_user_id: 'a'.repeat(64),
      chat_id: '018f4444-4444-7444-8444-444444444444',
      turn_id: '018f5555-5555-7555-8555-555555555555',
      billing_identity: '018f6666-6666-7666-8666-666666666666',
      outbox_id: OUTBOX_ID,
    }],
  });
  const body = { protocol_version: 1, inference_task_id: TASK_ID };

  const claimed = await executeOperation(database, 'claim_inference', body, new Date('2029-01-01T00:00:00.000Z'));
  const duplicate = await executeOperation(database, 'claim_inference', body, new Date('2029-01-01T00:00:01.000Z'));

  assert.equal(database.transactions, 2);
  assert.equal(claimed.claimed, true);
  assert.equal(duplicate.claimed, false);
  assert.equal(duplicate.state, 'RUNNING');
});

test('claim_inference returns the durable failure category for cancellation-safe classification', async () => {
  const cancelled = fakeDatabase({
    chat_turn_preflights: [{
      id: PREFLIGHT_ID, inference_task_id: TASK_ID, state: 'FAILED', failure_category: 'user_cancelled',
    }],
  });
  const cancelledResult = await executeOperation(cancelled, 'claim_inference', {
    protocol_version: 1, inference_task_id: TASK_ID,
  });
  assert.deepEqual(cancelledResult, {
    inference_task_id: TASK_ID, claimed: false, state: 'FAILED', failure_category: 'user_cancelled',
  });

  const expired = fakeDatabase({
    chat_turn_preflights: [{
      id: PREFLIGHT_ID, inference_task_id: TASK_ID, state: 'ENQUEUED', outbox_id: OUTBOX_ID,
      expires_at: new Date('2029-01-01T00:00:00Z'),
    }],
    chat_inference_outbox: [{ id: OUTBOX_ID, state: 'PENDING' }],
  });
  const expiredResult = await executeOperation(expired, 'claim_inference', {
    protocol_version: 1, inference_task_id: TASK_ID,
  }, new Date('2029-01-01T00:00:01Z'));
  assert.deepEqual(expiredResult, {
    inference_task_id: TASK_ID, claimed: false, state: 'FAILED', failure_category: 'claim_expired',
  });
});

test('outbox dispatch and worker failure transitions are idempotent and sanitized', async () => {
  const database = fakeDatabase({
    chat_turn_preflights: [{
      id: '018f1111-1111-7111-8111-111111111111',
      inference_task_id: TASK_ID,
      state: 'RUNNING',
      outbox_id: OUTBOX_ID,
    }],
    chat_inference_outbox: [{
      id: OUTBOX_ID,
      inference_task_id: TASK_ID,
      state: 'PENDING',
      attempts: 0,
    }],
    chat_completion_recovery_jobs: [],
  });
  const dispatched = await executeOperation(database, 'mark_outbox_dispatched', {
    protocol_version: 1,
    outbox_id: OUTBOX_ID,
    inference_task_id: TASK_ID,
  });
  const failed = await executeOperation(database, 'mark_inference_failed', {
    protocol_version: 1,
    inference_task_id: TASK_ID,
    failure_category: 'provider_timeout',
  });
  const duplicate = await executeOperation(database, 'mark_inference_failed', {
    protocol_version: 1,
    inference_task_id: TASK_ID,
    failure_category: 'provider_timeout',
  });

  assert.equal(dispatched.dispatched, true);
  assert.equal(failed.failed, true);
  assert.equal(duplicate.failed, false);
  assert.equal(database.rows.chat_turn_preflights[0].state, 'FAILED');
  assert.ok(database.rows.chat_turn_preflights[0].failure_alert_pending_at instanceof Date);
  assert.equal(database.rows.chat_inference_outbox[0].state, 'FAILED');
  await assert.rejects(
    executeOperation(database, 'mark_inference_failed', {
      protocol_version: 1,
      inference_task_id: TASK_ID,
      failure_category: 'contains plaintext spaces',
    }),
    (error) => error instanceof ProtocolError && error.code === 'invalid_failure_category',
  );
});

test('new failure transitions mark unknown technical failures pending but exclude expected cancellation', async () => {
  const failedDatabase = (taskId) => fakeDatabase({
    chat_turn_preflights: [{
      id: PREFLIGHT_ID, inference_task_id: taskId, state: 'RUNNING', outbox_id: OUTBOX_ID,
      chat_id: CHAT_ID, user_message_id: 'user-message-1',
    }],
    chat_inference_outbox: [{ id: OUTBOX_ID, inference_task_id: taskId, state: 'DISPATCHED' }],
    chat_completion_recovery_jobs: [],
  });
  const technical = failedDatabase(TASK_ID);
  await executeOperation(technical, 'mark_inference_failed', {
    protocol_version: 1, inference_task_id: TASK_ID, failure_category: 'future_transport_error',
  });
  assert.ok(technical.rows.chat_turn_preflights[0].failure_alert_pending_at instanceof Date);
  assert.deepEqual(
    (await executeOperation(technical, 'cleanup_expired', {
      protocol_version: 1, failure_alerts_enabled: true,
    })).failure_alert_candidates.map((candidate) => candidate.failure_category),
    ['future_transport_error'],
  );

  const cancelled = failedDatabase(TASK_ID);
  await executeOperation(cancelled, 'mark_inference_failed', {
    protocol_version: 1, inference_task_id: TASK_ID, failure_category: 'user_cancelled',
  });
  assert.equal(cancelled.rows.chat_turn_preflights[0].failure_alert_pending_at, null);
  assert.deepEqual(
    (await executeOperation(cancelled, 'cleanup_expired', {
      protocol_version: 1, failure_alerts_enabled: true,
    })).failure_alert_candidates,
    [],
  );
});

test('dispatch failure before worker claim marks enqueued inference failed', async () => {
  const database = fakeDatabase({
    chat_turn_preflights: [{
      id: '018f1111-1111-7111-8111-111111111111',
      inference_task_id: TASK_ID,
      state: 'ENQUEUED',
      outbox_id: OUTBOX_ID,
    }],
    chat_inference_outbox: [{
      id: OUTBOX_ID,
      inference_task_id: TASK_ID,
      state: 'PENDING',
      attempts: 0,
    }],
    chat_completion_recovery_jobs: [],
  });

  const failed = await executeOperation(database, 'mark_inference_failed', {
    protocol_version: 1,
    inference_task_id: TASK_ID,
    failure_category: 'dispatch_failed',
  });

  assert.deepEqual(failed, { inference_task_id: TASK_ID, failed: true, state: 'FAILED' });
  assert.equal(database.rows.chat_turn_preflights[0].state, 'FAILED');
  assert.equal(database.rows.chat_inference_outbox[0].state, 'FAILED');
  assert.equal(database.rows.chat_inference_outbox[0].last_error_category, 'dispatch_failed');
});

test('worker failure after sealed job is treated as stale and idempotent', async () => {
  const database = fakeDatabase({
    chat_turn_preflights: [{
      id: PREFLIGHT_ID,
      inference_task_id: TASK_ID,
      state: 'RUNNING',
      outbox_id: OUTBOX_ID,
    }],
    chat_inference_outbox: [{
      id: OUTBOX_ID,
      inference_task_id: TASK_ID,
      state: 'DISPATCHED',
      attempts: 1,
    }],
    chat_completion_recovery_jobs: [{
      id: JOB_ID,
      inference_task_id: TASK_ID,
      state: 'AVAILABLE',
    }],
  });

  const result = await executeOperation(database, 'mark_inference_failed', {
    protocol_version: 1,
    inference_task_id: TASK_ID,
    failure_category: 'runtime_error',
  });

  assert.deepEqual(result, {
    inference_task_id: TASK_ID,
    failed: false,
    state: 'RUNNING',
    sealed_job_id: JOB_ID,
  });
  assert.equal(database.rows.chat_turn_preflights[0].state, 'RUNNING');
  assert.equal(database.rows.chat_inference_outbox[0].state, 'DISPATCHED');
});

// contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
test('prepare_preflight atomically writes chat, user message, and preflight', async () => {
  const database = fakeDatabase({ chats: [], messages: [], chat_turn_preflights: [] });
  const result = await executeOperation(database, 'prepare_preflight', prepareBody(), new Date('2029-01-01T00:00:00Z'));

  assert.equal(result.state, 'PREPARED');
  assert.equal(result.committed_messages_v, 1);
  assert.equal(database.rows.chats.length, 1);
  assert.equal(database.rows.chats[0].messages_v, 1);
  assert.equal(database.rows.chats[0].is_private, true);
  assert.equal(database.rows.messages.length, 1);
  assert.equal(database.rows.messages[0].client_message_id, 'user-message-1');
  assert.equal(database.rows.chat_turn_preflights.length, 1);
  assert.equal(database.rows.chat_turn_preflights[0].state, 'PREPARED');
});

// contract-test: supporting surface=rest_api assertions=teams.workspace.surface-parity,chats.persistence.client-encrypted
test('prepare_preflight creates team chat wrapper for new team chats', async () => {
  const database = fakeDatabase({ chats: [], messages: [], chat_turn_preflights: [], chat_key_wrappers: [],
    chat_inference_outbox: [],
    teams: [{ hashed_team_id: TEAM_HASH, status: 'active' }],
    team_memberships: [{ hashed_team_id: TEAM_HASH, hashed_user_id: OWNER, status: 'active', role: 'member' }],
  });
  const result = await executeOperation(
    database,
    'prepare_preflight',
    prepareBody({ hashed_team_id: TEAM_HASH }),
    new Date('2029-01-01T00:00:00Z'),
  );

  assert.equal(result.state, 'PREPARED');
  assert.equal(database.rows.chats[0].hashed_team_id, TEAM_HASH);
  assert.equal(database.rows.chat_key_wrappers.length, 1);
  assert.deepEqual(
    Object.fromEntries(
      Object.entries(database.rows.chat_key_wrappers[0])
        .filter(([key]) => key !== 'id'),
    ),
    {
      hashed_chat_id: testing.digest(CHAT_ID),
      hashed_team_id: TEAM_HASH,
      key_type: 'team',
      team_key_epoch: 1,
      encrypted_chat_key: 'wrapped-key-1',
      wrapper_version: 1,
      created_at: 1861920000,
    },
  );
  database.rows.team_memberships[0].status = 'removed';
  await assert.rejects(executeOperation(database, 'prepare_preflight',
    prepareBody({ hashed_team_id: TEAM_HASH }), new Date('2029-01-01T00:00:01Z')),
  /chat_not_found/);
  await assert.rejects(executeOperation(database, 'enqueue_inference', {
    protocol_version: 1, preflight_id: result.preflight_id, hashed_user_id: OWNER,
    device_hash: 'device-a', inference_commitment: COMMITMENT,
    inference_task_id: TASK_ID, billing_identity: BILLING_ID, outbox_id: OUTBOX_ID,
  }, new Date('2029-01-01T00:00:02Z')), /chat_not_found/);
  assert.equal(database.rows.chat_inference_outbox.length, 0);
});

// contract-test: supporting surface=rest_api assertions=teams.workspace.surface-parity,chats.persistence.client-encrypted
test('prepare_preflight rolls back team chat when team wrapper insert fails', async () => {
  const seed = { chats: [], messages: [], chat_turn_preflights: [], chat_key_wrappers: [],
    teams: [{ hashed_team_id: TEAM_HASH, status: 'active' }],
    team_memberships: [{ hashed_team_id: TEAM_HASH, hashed_user_id: OWNER, status: 'active', role: 'member' }],
  };
  const database = fakeDatabase(
    seed,
    { operation: 'insert', table: 'chat_key_wrappers' },
  );

  await assert.rejects(
    executeOperation(database, 'prepare_preflight', prepareBody({ hashed_team_id: TEAM_HASH }), new Date('2029-01-01T00:00:00Z')),
    /injected insert:chat_key_wrappers failure/,
  );
  assert.deepEqual(database.rows, seed);
});

// contract-test: direct surface=rest_api assertions=teams.chat.encrypted-until-invoked,chats.message.identity-idempotent
test('ordinary Team relay proof binds preflight, sender, team, message, and ciphertext', async () => {
  const database = fakeDatabase({
    chats: [], messages: [], chat_turn_preflights: [], chat_key_wrappers: [],
    teams: [{ hashed_team_id: TEAM_HASH, status: 'active' }],
    team_memberships: [{ hashed_team_id: TEAM_HASH, hashed_user_id: OWNER, status: 'active', role: 'member' }],
    ...protocolSeed(),
  });
  const prepared = await executeOperation(database, 'prepare_preflight',
    prepareBody({ hashed_team_id: TEAM_HASH }), new Date('2029-01-01T00:00:00Z'));
  const proof = {
    protocol_version: 1, preflight_id: prepared.preflight_id,
    hashed_user_id: OWNER, hashed_team_id: TEAM_HASH, chat_id: CHAT_ID,
    user_message_id: 'user-message-1', encrypted_content_digest: testing.digest('encrypted-user'),
  };
  assert.deepEqual(await executeOperation(database, 'verify_committed_team_message', proof), { committed: true });
  assert.deepEqual(await executeOperation(database, 'verify_committed_team_message', proof), { committed: true });
  for (const [field, value] of [
    ['preflight_id', JOB_ID], ['hashed_user_id', 'd'.repeat(64)],
    ['hashed_team_id', 'd'.repeat(64)], ['chat_id', JOB_ID],
    ['user_message_id', 'different-message'], ['encrypted_content_digest', 'd'.repeat(64)],
  ]) {
    await assert.rejects(
      executeOperation(database, 'verify_committed_team_message', { ...proof, [field]: value }),
      (error) => error instanceof ProtocolError && [
        'preflight_not_found', 'chat_not_found', 'message_identity_mismatch',
      ].includes(error.code),
    );
  }
  database.rows.chat_recovery_protocol_state[0].sends_paused = true;
  await assert.rejects(
    executeOperation(database, 'verify_committed_team_message', proof),
    (error) => error instanceof ProtocolError && error.code === 'inference_temporarily_paused',
  );
});

// contract-test: direct surface=rest_api assertions=teams.chat.encrypted-until-invoked,chats.message.identity-idempotent
test('lost ordinary Team ACK replays one committed turn and rejects changed ciphertext', async () => {
  const database = fakeDatabase({
    chats: [], messages: [], chat_turn_preflights: [], chat_key_wrappers: [],
    teams: [{ hashed_team_id: TEAM_HASH, status: 'active' }],
    team_memberships: [{ hashed_team_id: TEAM_HASH, hashed_user_id: OWNER, status: 'active', role: 'member' }],
    ...protocolSeed(),
  });
  const original = prepareBody({ hashed_team_id: TEAM_HASH });
  const first = await executeOperation(database, 'prepare_preflight', original);
  const retry = await executeOperation(database, 'prepare_preflight', structuredClone(original));
  assert.deepEqual(retry, first);
  assert.equal(database.rows.chats.length, 1);
  assert.equal(database.rows.messages.length, 1);
  assert.equal(database.rows.chat_turn_preflights.length, 1);
  assert.equal(database.rows.chat_key_wrappers.length, 1);
  await assert.rejects(
    executeOperation(database, 'prepare_preflight', prepareBody({
      hashed_team_id: TEAM_HASH,
      encrypted_user_message: { ...userMessage(), encrypted_content: 'different-ciphertext' },
    })),
    (error) => error instanceof ProtocolError && error.code === 'preflight_mismatch',
  );
  assert.equal(database.rows.messages.length, 1);
});

// contract-test: direct surface=rest_api assertions=teams.chat.encrypted-until-invoked
test('failed Team preflight cannot authorize a relay', async () => {
  const database = fakeDatabase({
    chats: [], messages: [], chat_turn_preflights: [], chat_key_wrappers: [],
    teams: [{ hashed_team_id: TEAM_HASH, status: 'active' }],
    team_memberships: [{ hashed_team_id: TEAM_HASH, hashed_user_id: OWNER, status: 'active', role: 'member' }],
    ...protocolSeed(),
  }, { operation: 'insert', table: 'chat_key_wrappers' });
  await assert.rejects(
    executeOperation(database, 'prepare_preflight', prepareBody({ hashed_team_id: TEAM_HASH })),
    /injected insert:chat_key_wrappers failure/,
  );
  await assert.rejects(
    executeOperation(database, 'verify_committed_team_message', {
      protocol_version: 1, preflight_id: PREFLIGHT_ID, hashed_user_id: OWNER,
      hashed_team_id: TEAM_HASH, chat_id: CHAT_ID, user_message_id: 'user-message-1',
      encrypted_content_digest: testing.digest('encrypted-user'),
    }),
    (error) => error instanceof ProtocolError && error.code === 'preflight_not_found',
  );
});

// contract-test: supporting surface=rest_api assertions=teams.chat.encrypted-until-invoked
test('paused sends cannot commit an ordinary Team preflight', async () => {
  const database = fakeDatabase({
    chats: [], messages: [], chat_turn_preflights: [], chat_key_wrappers: [],
    teams: [{ hashed_team_id: TEAM_HASH, status: 'active' }],
    team_memberships: [{ hashed_team_id: TEAM_HASH, hashed_user_id: OWNER, status: 'active', role: 'member' }],
    ...protocolSeed({ paused: true }),
  });
  await assert.rejects(
    executeOperation(database, 'prepare_preflight', prepareBody({ hashed_team_id: TEAM_HASH })),
    (error) => error instanceof ProtocolError && error.code === 'inference_temporarily_paused',
  );
  assert.equal(database.rows.messages.length, 0);
  assert.equal(database.rows.chats.length, 0);
});

// contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
test('prepare_preflight rolls back all writes when the final preflight insert fails', async () => {
  const database = fakeDatabase(
    { chats: [], messages: [], chat_turn_preflights: [] },
    { operation: 'insert', table: 'chat_turn_preflights' },
  );

  await assert.rejects(
    executeOperation(database, 'prepare_preflight', prepareBody(), new Date('2029-01-01T00:00:00Z')),
    /injected insert:chat_turn_preflights failure/,
  );
  assert.deepEqual(database.rows, { chats: [], messages: [], chat_turn_preflights: [] });
});

// contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
test('prepare_preflight accepts matching metadata for an existing empty draft shell', async () => {
  const metadata = prepareBody().encrypted_chat_metadata;
  const database = fakeDatabase({
    chats: [{
      id: CHAT_ID,
      hashed_user_id: OWNER,
      ...metadata,
      messages_v: 0,
      title_v: 0,
      metadata_v: 0,
      last_message_timestamp: null,
    }],
    messages: [],
    chat_turn_preflights: [],
  });

  const result = await executeOperation(database, 'prepare_preflight', prepareBody(), new Date('2029-01-01T00:00:00Z'));

  assert.equal(result.state, 'PREPARED');
  assert.equal(result.committed_messages_v, 1);
  assert.equal(database.rows.chats.length, 1);
  assert.equal(database.rows.chats[0].messages_v, 1);
  assert.equal(database.rows.messages.length, 1);
  assert.equal(database.rows.chat_turn_preflights.length, 1);
});

// contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
test('prepare_preflight completes a key-only empty shell but rejects conflicting encrypted metadata', async () => {
  const metadata = prepareBody().encrypted_chat_metadata;
  const shell = {
    id: CHAT_ID,
    hashed_user_id: OWNER,
    encrypted_chat_key: metadata.encrypted_chat_key,
    created_at: metadata.created_at,
    updated_at: metadata.updated_at,
    messages_v: 0,
    title_v: 0,
    metadata_v: 0,
    last_message_timestamp: null,
  };
  const database = fakeDatabase({ chats: [shell], messages: [], chat_turn_preflights: [] });

  const result = await executeOperation(database, 'prepare_preflight', prepareBody(), new Date('2029-01-01T00:00:00Z'));

  assert.equal(result.state, 'PREPARED');
  assert.equal(database.rows.chats[0].encrypted_title, metadata.encrypted_title);
  assert.equal(database.rows.chats[0].messages_v, 1);

  const conflicting = fakeDatabase({
    chats: [{ ...shell, encrypted_title: 'different-encrypted-title' }],
    messages: [],
    chat_turn_preflights: [],
  });
  await assert.rejects(
    executeOperation(conflicting, 'prepare_preflight', prepareBody(), new Date('2029-01-01T00:00:00Z')),
    (error) => error instanceof ProtocolError && error.code === 'existing_chat_metadata_forbidden',
  );
});

// contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
test('prepare_preflight rejects metadata for an existing non-empty chat', async () => {
  const metadata = prepareBody().encrypted_chat_metadata;
  const database = fakeDatabase({
    chats: [{
      id: CHAT_ID,
      hashed_user_id: OWNER,
      ...metadata,
      messages_v: 1,
      title_v: 0,
      metadata_v: 0,
      last_message_timestamp: 100,
    }],
    messages: [userMessage()],
    chat_turn_preflights: [],
  });

  await assert.rejects(
    executeOperation(database, 'prepare_preflight', prepareBody({
      expected_messages_v: 1,
      user_message_id: 'user-message-2',
      encrypted_user_message: userMessage('user-message-2'),
    }), new Date('2029-01-01T00:00:00Z')),
    (error) => error instanceof ProtocolError && error.code === 'existing_chat_metadata_forbidden',
  );
});

// contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
test('prepare_preflight is idempotent for an exact duplicate and rejects immutable key changes', async () => {
  const database = fakeDatabase({ chats: [], messages: [], chat_turn_preflights: [] });
  const now = new Date('2029-01-01T00:00:00Z');
  const first = await executeOperation(database, 'prepare_preflight', prepareBody(), now);
  const duplicate = await executeOperation(database, 'prepare_preflight', prepareBody(), new Date(now.getTime() + 1000));

  assert.deepEqual(duplicate, first);
  assert.equal(database.rows.messages.length, 1);
  assert.equal(database.rows.chat_turn_preflights.length, 1);
  await assert.rejects(
    executeOperation(database, 'prepare_preflight', prepareBody({
      turn_id: '018f8888-8888-7888-8888-888888888888',
      user_message_id: 'user-message-2',
      wrapped_chat_key: 'wrapped-key-2',
      expected_messages_v: 1,
      encrypted_user_message: userMessage('user-message-2'),
      encrypted_chat_metadata: undefined,
    }), now),
    (error) => error instanceof ProtocolError && error.code === 'immutable_chat_key_mismatch',
  );
});

test('enqueue_inference atomically transitions PREPARED and creates its outbox row', async () => {
  const body = {
    protocol_version: 1, preflight_id: PREFLIGHT_ID, hashed_user_id: OWNER, device_hash: 'device-a',
    inference_commitment: COMMITMENT, inference_task_id: TASK_ID, billing_identity: BILLING_ID, outbox_id: OUTBOX_ID,
  };
  const database = fakeDatabase(preparedSeed());
  const result = await executeOperation(database, 'enqueue_inference', body, new Date('2029-01-01T00:01:00Z'));

  assert.equal(result.state, 'ENQUEUED');
  assert.equal(database.rows.chat_turn_preflights[0].state, 'ENQUEUED');
  assert.deepEqual(database.rows.chat_inference_outbox.map(({ id, state, inference_task_id }) => ({ id, state, inference_task_id })), [{
    id: OUTBOX_ID, state: 'PENDING', inference_task_id: TASK_ID,
  }]);

  const failing = fakeDatabase(preparedSeed(), { operation: 'update', table: 'chat_turn_preflights' });
  await assert.rejects(
    executeOperation(failing, 'enqueue_inference', body, new Date('2029-01-01T00:01:00Z')),
    /injected update:chat_turn_preflights failure/,
  );
  assert.equal(failing.rows.chat_turn_preflights[0].state, 'PREPARED');
  assert.deepEqual(failing.rows.chat_inference_outbox, []);
});

test('lease_job supports expiry takeover with monotonic generations and rejects stale leases', async () => {
  const database = fakeDatabase(leasedSeed());
  const start = new Date('2029-01-01T00:00:00Z');
  const first = await executeOperation(database, 'lease_job', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER, device_hash: 'device-a',
  }, start);
  assert.equal(first.lease_generation, 1);
  await assert.rejects(
    executeOperation(database, 'lease_job', {
      protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER, device_hash: 'device-b',
    }, new Date(start.getTime() + 59_000)),
    (error) => error instanceof ProtocolError && error.code === 'lease_conflict',
  );

  const takeover = await executeOperation(database, 'lease_job', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER, device_hash: 'device-b',
  }, new Date(start.getTime() + 60_001));
  assert.equal(takeover.lease_generation, 2);
  assert.notEqual(takeover.lease_token, first.lease_token);
  await assert.rejects(
    executeOperation(database, 'renew_lease', {
      protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER, device_hash: 'device-a',
      lease_generation: first.lease_generation, lease_token: first.lease_token,
    }, new Date(start.getTime() + 60_002)),
    (error) => error instanceof ProtocolError && error.code === 'stale_lease',
  );
});

// contract-test: direct surface=rest_api assertions=teams.workspace.surface-parity,storage.background.complete-sealed-recovery
test('active Team member can seal, lease, and persist an AI response in a chat created by another member', async () => {
  const member = 'd'.repeat(64);
  const now = new Date('2029-01-01T00:00:00Z');
  const database = fakeDatabase({
    ...protocolSeed(),
    chats: [{ id: CHAT_ID, hashed_user_id: OWNER, hashed_team_id: TEAM_HASH,
      encrypted_chat_key: 'wrapped-key-1', messages_v: 0 }],
    messages: [], chat_turn_preflights: [], chat_inference_outbox: [],
    chat_completion_recovery_jobs: [],
    teams: [{ hashed_team_id: TEAM_HASH, status: 'active' }],
    team_memberships: [{ hashed_team_id: TEAM_HASH, hashed_user_id: member,
      status: 'active', role: 'member' }],
  });
  const prepared = await executeOperation(database, 'prepare_preflight', prepareBody({
    hashed_user_id: member, hashed_team_id: TEAM_HASH,
    encrypted_user_message: { ...userMessage(), hashed_user_id: member },
    encrypted_chat_metadata: undefined,
  }), now);
  assert.equal(prepared.state, 'PREPARED');
  await executeOperation(database, 'enqueue_inference', {
    protocol_version: 1, preflight_id: prepared.preflight_id, hashed_user_id: member,
    device_hash: 'device-a', inference_commitment: COMMITMENT,
    inference_task_id: TASK_ID, billing_identity: BILLING_ID, outbox_id: OUTBOX_ID,
  }, new Date(now.getTime() + 1000));
  assert.equal((await executeOperation(database, 'claim_inference', {
    protocol_version: 1, inference_task_id: TASK_ID,
  }, new Date(now.getTime() + 2000))).state, 'RUNNING');
  const job = {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: member,
    chat_id: CHAT_ID, turn_id: TURN_ID, preflight_id: prepared.preflight_id,
    inference_task_id: TASK_ID, assistant_message_id: 'assistant-message-1',
    chat_key_version: 1, sealed_payload: SEALED_PAYLOAD,
  };
  assert.equal((await executeOperation(database, 'create_sealed_job', job,
    new Date(now.getTime() + 3000))).state, 'AVAILABLE');
  const lease = await executeOperation(database, 'lease_job', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: member, device_hash: 'device-a',
  }, new Date(now.getTime() + 4000));
  assert.equal(lease.sealed_payload, SEALED_PAYLOAD);
  const terminalBody = {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: member, device_hash: 'device-a',
    lease_generation: lease.lease_generation, lease_token: lease.lease_token,
    expected_messages_v: 1,
    encrypted_assistant_message: { ...assistantMessage(), hashed_user_id: member },
  };
  await assert.rejects(executeOperation(database, 'persist_terminal', {
    ...terminalBody, expected_messages_v: 0,
  }, new Date(now.getTime() + 5000)),
  (error) => error instanceof ProtocolError && error.code === 'version_conflict');
  await assert.rejects(executeOperation(database, 'persist_terminal', {
    ...terminalBody, encrypted_assistant_message: {
      ...terminalBody.encrypted_assistant_message, client_message_id: 'wrong-assistant-id',
    },
  }, new Date(now.getTime() + 5000)),
  (error) => error instanceof ProtocolError && error.code === 'message_identity_mismatch');
  assert.equal(database.rows.messages.length, 1);
  const response = await executeOperation(database, 'persist_terminal', terminalBody,
    new Date(now.getTime() + 5000));
  assert.equal(response.committed_messages_v, 2);
  assert.equal((await executeOperation(database, 'persist_terminal', terminalBody,
    new Date(now.getTime() + 6000))).idempotent, true);
  assert.equal(database.rows.chats[0].hashed_user_id, OWNER);
  assert.equal(database.rows.chats[0].messages_v, 2);
  assert.equal(database.rows.messages[1].hashed_user_id, member);
  assert.equal(database.rows.chat_completion_recovery_jobs[0].sealed_payload, null);
});

// contract-test: direct surface=rest_api assertions=teams.workspace.surface-parity,storage.background.complete-sealed-recovery
test('Team recovery never leases sealed payload after membership removal or role downgrade', async () => {
  const member = 'd'.repeat(64);
  for (const change of [
    { status: 'removed', role: 'member' },
    { status: 'active', role: 'viewer' },
    { status: 'active', role: 'member', hashed_team_id: 'e'.repeat(64) },
  ]) {
    const seed = leasedSeed();
    seed.chats[0].hashed_team_id = TEAM_HASH;
    seed.chats[0].hashed_user_id = OWNER;
    seed.chat_turn_preflights[0].hashed_user_id = member;
    seed.chat_completion_recovery_jobs[0].hashed_user_id = member;
    seed.teams = [{ hashed_team_id: TEAM_HASH, status: 'active' }];
    seed.team_memberships = [{ hashed_team_id: TEAM_HASH, hashed_user_id: member, ...change }];
    const database = fakeDatabase(seed);
    await assert.rejects(executeOperation(database, 'lease_job', {
      protocol_version: 1, job_id: JOB_ID, hashed_user_id: member, device_hash: 'device-a',
    }), (error) => error instanceof ProtocolError && error.code === 'chat_not_found');
    assert.equal(database.rows.chat_completion_recovery_jobs[0].state, 'AVAILABLE');
    database.rows.chat_completion_recovery_jobs = [];
    Object.assign(database.rows.chat_turn_preflights[0], {
      hashed_user_id: member, inference_task_id: TASK_ID, chat_key_version: 1,
    });
    await assert.rejects(executeOperation(database, 'create_sealed_job', {
      protocol_version: 1, job_id: JOB_ID, hashed_user_id: member,
      chat_id: CHAT_ID, turn_id: TURN_ID, preflight_id: PREFLIGHT_ID,
      inference_task_id: TASK_ID, assistant_message_id: 'assistant-message-1',
      chat_key_version: 1, sealed_payload: SEALED_PAYLOAD,
    }), (error) => error instanceof ProtocolError && error.code === 'chat_not_found');
    assert.equal(database.rows.chat_completion_recovery_jobs.length, 0);
  }
});

// contract-test: direct surface=rest_api assertions=teams.workspace.surface-parity,storage.background.complete-sealed-recovery
test('removing a Team member revokes existing sealed-job replay, renewal, and terminal persistence', async () => {
  const member = 'd'.repeat(64);
  const now = new Date('2029-01-01T00:00:00Z');
  const seed = leasedSeed(now);
  seed.chats[0].hashed_team_id = TEAM_HASH;
  seed.chat_completion_recovery_jobs[0].hashed_user_id = member;
  seed.teams = [{ hashed_team_id: TEAM_HASH, status: 'active' }];
  seed.team_memberships = [{ hashed_team_id: TEAM_HASH, hashed_user_id: member,
    status: 'active', role: 'member' }];
  const database = fakeDatabase(seed);
  const lease = await executeOperation(database, 'lease_job', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: member, device_hash: 'device-a',
  }, now);
  database.rows.team_memberships[0].status = 'removed';
  const denial = (error) => error instanceof ProtocolError && error.code === 'chat_not_found';
  await assert.rejects(executeOperation(database, 'create_sealed_job', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: member,
    chat_id: CHAT_ID, turn_id: TURN_ID, preflight_id: PREFLIGHT_ID,
    inference_task_id: TASK_ID, assistant_message_id: 'assistant-message-1',
    chat_key_version: 1, sealed_payload: SEALED_PAYLOAD,
  }, new Date(now.getTime() + 1000)), denial);
  await assert.rejects(executeOperation(database, 'renew_lease', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: member, device_hash: 'device-a',
    lease_generation: lease.lease_generation, lease_token: lease.lease_token,
  }, new Date(now.getTime() + 1000)), denial);
  await assert.rejects(executeOperation(database, 'persist_terminal', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: member, device_hash: 'device-a',
    lease_generation: lease.lease_generation, lease_token: lease.lease_token,
    expected_messages_v: 1,
    encrypted_assistant_message: { ...assistantMessage(), hashed_user_id: member },
  }, new Date(now.getTime() + 1000)), denial);
  assert.equal(database.rows.chat_completion_recovery_jobs[0].state, 'LEASED');
  assert.equal(database.rows.messages.length, 1);
});

// contract-test: direct surface=rest_api assertions=chats.persistence.client-encrypted,storage.background.complete-sealed-recovery
test('a Personal chat never lends a recovery job to a different user', async () => {
  const seed = leasedSeed();
  const member = 'd'.repeat(64);
  seed.chat_completion_recovery_jobs[0].hashed_user_id = member;
  const database = fakeDatabase(seed);
  await assert.rejects(executeOperation(database, 'lease_job', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: member, device_hash: 'device-a',
  }), (error) => error instanceof ProtocolError && error.code === 'chat_not_found');
  assert.equal(database.rows.chat_completion_recovery_jobs[0].state, 'AVAILABLE');
});

test('persist_terminal atomically commits ciphertext and erases recovery material, then retries idempotently', async () => {
  const database = fakeDatabase(leasedSeed());
  const now = new Date('2029-01-01T00:00:00Z');
  const lease = await executeOperation(database, 'lease_job', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER, device_hash: 'device-a',
  }, now);
  const body = {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER, device_hash: 'device-a',
    lease_generation: lease.lease_generation, lease_token: lease.lease_token, expected_messages_v: 1,
    encrypted_assistant_message: assistantMessage(),
  };
  const result = await executeOperation(database, 'persist_terminal', body, new Date(now.getTime() + 1000));
  const retry = await executeOperation(database, 'persist_terminal', body, new Date(now.getTime() + 2000));
  const terminalClaim = await executeOperation(database, 'lease_job', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER, device_hash: 'device-a',
  }, new Date(now.getTime() + 3000));

  assert.equal(result.idempotent, false);
  assert.equal(result.committed_messages_v, 2);
  assert.equal(retry.idempotent, true);
  assert.deepEqual(terminalClaim, {
    job_id: JOB_ID,
    state: 'TERMINAL',
    chat_id: CHAT_ID,
    turn_id: TURN_ID,
    assistant_message_id: 'assistant-message-1',
    chat_key_version: 1,
    committed_messages_v: 2,
  });
  assert.equal(database.rows.messages.length, 2);
  assert.equal(database.rows.chats[0].messages_v, 2);
  assert.equal(database.rows.chat_turn_preflights[0].state, 'TERMINAL');
  assert.deepEqual({
    state: database.rows.chat_completion_recovery_jobs[0].state,
    sealed_payload: database.rows.chat_completion_recovery_jobs[0].sealed_payload,
    sealed_payload_digest: database.rows.chat_completion_recovery_jobs[0].sealed_payload_digest,
    lease_token_digest: database.rows.chat_completion_recovery_jobs[0].lease_token_digest,
    lease_holder_hash: database.rows.chat_completion_recovery_jobs[0].lease_holder_hash,
    lease_expires_at: database.rows.chat_completion_recovery_jobs[0].lease_expires_at,
  }, {
    state: 'TERMINAL', sealed_payload: null, sealed_payload_digest: null,
    lease_token_digest: null, lease_holder_hash: null, lease_expires_at: null,
  });
});

test('persist_terminal completes idempotently when another path already stored the assistant message', async () => {
  const seed = leasedSeed();
  seed.chats[0].messages_v = 2;
  seed.messages.push(assistantMessage());
  const database = fakeDatabase(seed);
  const now = new Date('2029-01-01T00:00:00Z');
  const lease = await executeOperation(database, 'lease_job', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER, device_hash: 'device-a',
  }, now);

  const result = await executeOperation(database, 'persist_terminal', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER, device_hash: 'device-a',
    lease_generation: lease.lease_generation, lease_token: lease.lease_token, expected_messages_v: 1,
    encrypted_assistant_message: assistantMessage(),
  }, new Date(now.getTime() + 1000));

  assert.deepEqual(result, {
    job_id: JOB_ID,
    state: 'TERMINAL',
    idempotent: true,
    committed_messages_v: 2,
  });
  assert.equal(database.rows.messages.length, 2);
  assert.equal(database.rows.chats[0].messages_v, 2);
  assert.equal(database.rows.chat_completion_recovery_jobs[0].state, 'TERMINAL');
  assert.equal(database.rows.chat_completion_recovery_jobs[0].sealed_payload, null);
  assert.equal(database.rows.chat_turn_preflights[0].state, 'TERMINAL');
});

test('persist_terminal rolls back message and chat writes when terminal job update fails', async () => {
  const database = fakeDatabase(leasedSeed(), { operation: 'update', table: 'chat_completion_recovery_jobs', occurrence: 2 });
  const now = new Date('2029-01-01T00:00:00Z');
  const lease = await executeOperation(database, 'lease_job', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER, device_hash: 'device-a',
  }, now);

  await assert.rejects(
    executeOperation(database, 'persist_terminal', {
      protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER, device_hash: 'device-a',
      lease_generation: lease.lease_generation, lease_token: lease.lease_token, expected_messages_v: 1,
      encrypted_assistant_message: assistantMessage(),
    }, new Date(now.getTime() + 1000)),
    /injected update:chat_completion_recovery_jobs failure/,
  );
  assert.equal(database.rows.messages.length, 1);
  assert.equal(database.rows.chats[0].messages_v, 1);
  assert.equal(database.rows.chat_turn_preflights[0].state, 'RUNNING');
  assert.equal(database.rows.chat_completion_recovery_jobs[0].state, 'LEASED');
  assert.equal(database.rows.chat_completion_recovery_jobs[0].sealed_payload, SEALED_PAYLOAD);
});

test('cleanup_expired retains pending sealed output while removing terminal tombstones', async () => {
  const now = new Date('2029-01-08T00:00:00Z');
  const seed = leasedSeed(new Date('2029-01-01T00:00:00Z'));
  seed.chat_completion_recovery_jobs.push({
    ...structuredClone(seed.chat_completion_recovery_jobs[0]), id: '018f9999-9999-7999-8999-999999999999',
    state: 'TERMINAL', expires_at: new Date('2029-01-02T00:00:00Z'), tombstone_expires_at: now,
  });
  seed.chat_completion_recovery_jobs.push({
    ...structuredClone(seed.chat_completion_recovery_jobs[0]), id: '018faaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa',
    expires_at: new Date(now.getTime() + 1),
  });
  const database = fakeDatabase(seed);
  const result = await executeOperation(database, 'cleanup_expired', { protocol_version: 1 }, now);

  assert.equal(result.expired_jobs, 0);
  assert.equal(result.expired_tombstones, 1);
  assert.deepEqual(database.rows.chat_completion_recovery_jobs.map((row) => row.id), [JOB_ID, '018faaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa']);
  const lateLease = await executeOperation(database, 'lease_job', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER, device_hash: 'device-b',
  }, now);
  assert.equal(lateLease.state, 'LEASED');
});

test('typed output is atomically saved and remains discoverable after the old job deadline', async () => {
  const seed = preparedSeed();
  seed.chats[0].hashed_team_id = 'team-scope-hash';
  seed.team_memberships = [{ hashed_team_id: 'team-scope-hash', hashed_user_id: OWNER,
    status: 'active', role: 'member' }];
  seed.teams = [{ hashed_team_id: 'team-scope-hash', status: 'active' }];
  seed.chat_turn_preflights[0].state = 'RUNNING';
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_recovery_outputs = [];
  const database = fakeDatabase(seed);
  const recordId = '018f8888-8888-7888-8888-888888888888';
  const body = {
    protocol_version: 1, record_id: recordId, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: JOB_ID, output_kind: 'message', output_version: 2,
    chat_key_version: 1, sealed_payload: SEALED_OUTPUT,
  };
  const created = await executeOperation(database, 'create_sealed_output', body);
  assert.equal(created.state, 'PENDING');
  const listed = await executeOperation(database, 'list_pending_outputs', {
    protocol_version: 1, hashed_user_id: OWNER, device_hash: 'device-a',
  }, new Date('2040-01-01T00:00:00Z'));
  assert.equal(listed.outputs[0].record_id, recordId);
  assert.equal(listed.outputs[0].root_hashed_team_id, 'team-scope-hash');
  const fetched = await executeOperation(database, 'get_pending_output', {
    protocol_version: 1, hashed_user_id: OWNER, device_hash: 'device-a', record_id: recordId,
  });
  assert.equal(fetched.sealed_payload, SEALED_OUTPUT);
  assert.equal(fetched.output_version, 2);
  assert.equal(fetched.root_hashed_team_id, 'team-scope-hash');
  await assert.rejects(executeOperation(database, 'create_sealed_output', {
    ...body, sealed_payload: JSON.stringify({ ...JSON.parse(SEALED_OUTPUT), ciphertext: b64(17, 4) }),
  }), /sealed_output_mismatch/);
});

test('large sealed output registers a durable writer intent before regional publication', async () => {
  const seed = preparedSeed();
  seed.chat_turn_preflights[0].state = 'RUNNING';
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_recovery_outputs = [];
  const database = fakeDatabase(seed);
  const recordId = '018f8888-8888-7888-8888-888888888888';
  const checksum = 'a'.repeat(64);
  const key = `chat-recovery/v2/aa/${recordId}/${checksum}.json`;
  const intent = {
    protocol_version: 1, record_id: recordId, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: JOB_ID, output_kind: 'embed', output_version: 1,
    chat_key_version: 1, payload_s3_key: key, payload_size_bytes: 300_000,
    sealed_payload_digest: checksum,
  };
  await assert.rejects(executeOperation(database, 'create_sealed_output', {
    ...intent, payload_verified_regions: ['region-a'],
  }), /sealed_output_intent_required/);
  const prepared = await executeOperation(database, 'prepare_sealed_output', intent);
  assert.equal(prepared.state, 'PREPARING');
  assert.equal(database.rows.chat_recovery_outputs[0].payload_s3_key, key);
  assert.ok(database.rows.chat_recovery_outputs[0].writer_lease_until);
  await assert.rejects(executeOperation(database, 'prepare_sealed_output', {
    ...intent, payload_size_bytes: 300_001,
  }), /sealed_output_mismatch/);
  const discovery = { protocol_version: 1, hashed_user_id: OWNER, device_hash: 'device-a' };
  assert.deepEqual((await executeOperation(database, 'list_pending_outputs', discovery)).outputs, []);
  await assert.rejects(executeOperation(database, 'get_pending_output', {
    ...discovery, record_id: recordId,
  }), /recovery_output_not_found/);
  const published = await executeOperation(database, 'create_sealed_output', {
    ...intent, payload_verified_regions: ['region-a'],
  });
  assert.equal(published.state, 'PENDING');
  assert.equal(database.rows.chat_recovery_outputs[0].writer_lease_until, null);
  assert.equal((await executeOperation(database, 'list_pending_outputs', discovery)).outputs[0].record_id, recordId);
  await executeOperation(database, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: OWNER, scope: 'chat', chat_id: CHAT_ID,
  });
  await assert.rejects(executeOperation(database, 'create_sealed_output', {
    ...intent, payload_verified_regions: ['region-a'],
  }), /sealed_output_invalidated/);
});

test('Team recovery requires current membership before discovery, read, and canonical message write', async () => {
  const seed = preparedSeed();
  seed.chats[0].hashed_user_id = 'different-chat-creator';
  seed.chats[0].hashed_team_id = TEAM_HASH;
  seed.team_memberships = [{ hashed_team_id: TEAM_HASH, hashed_user_id: OWNER,
    status: 'active', role: 'member' }];
  seed.teams = [{ hashed_team_id: TEAM_HASH, status: 'active' }];
  seed.chat_turn_preflights[0].state = 'RUNNING';
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_recovery_outputs = [];
  const database = fakeDatabase(seed);
  const recordId = '018f8888-8888-7888-8888-888888888888';
  await executeOperation(database, 'create_sealed_output', {
    protocol_version: 1, record_id: recordId, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: 'assistant-message-1', output_kind: 'message', output_version: 1,
    chat_key_version: 1, sealed_payload: SEALED_OUTPUT,
  });
  const index = { protocol_version: 1, hashed_user_id: OWNER, device_hash: 'device-a' };
  assert.equal((await executeOperation(database, 'list_pending_outputs', index)).outputs[0].root_hashed_team_id, TEAM_HASH);
  database.rows.team_memberships[0].status = 'removed';
  assert.deepEqual((await executeOperation(database, 'list_pending_outputs', index)).outputs, []);
  await assert.rejects(executeOperation(database, 'get_pending_output', {
    ...index, record_id: recordId,
  }), /chat_not_found/);
  await assert.rejects(executeOperation(database, 'persist_output_message', {
    ...index, record_id: recordId, expected_messages_v: 1,
    encrypted_assistant_message: assistantMessage(),
  }), /chat_not_found/);
  assert.equal(database.rows.chats[0].messages_v, 1);
  database.rows.team_memberships[0].status = 'active';
  const committed = await executeOperation(database, 'persist_output_message', {
    ...index, record_id: recordId, expected_messages_v: 1,
    encrypted_assistant_message: assistantMessage(),
  });
  assert.equal(committed.committed_messages_v, 2);
  assert.equal(database.rows.chats[0].messages_v, 2);
  assert.ok(database.shareLocks.includes('team_memberships'));
  assert.ok(database.shareLocks.includes('teams'));
});

// contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery,teams.workspace.surface-parity
test('account deletion preserves the sole pending Team output and fences later publication', async () => {
  const seed = preparedSeed();
  seed.chats[0].hashed_team_id = TEAM_HASH;
  seed.team_memberships = [{ hashed_team_id: TEAM_HASH, hashed_user_id: OWNER, status: 'active', role: 'member' }];
  seed.teams = [{ hashed_team_id: TEAM_HASH, status: 'active' }];
  seed.chat_turn_preflights[0].state = 'RUNNING';
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_recovery_outputs = [];
  const database = fakeDatabase(seed);
  const recordId = '018f8888-8888-7888-8888-888888888888';
  const output = {
    protocol_version: 1, record_id: recordId, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: 'assistant-message-1', output_kind: 'message', output_version: 1,
    message_role: 'assistant', chat_key_version: 1, sealed_payload: SEALED_OUTPUT,
  };
  await executeOperation(database, 'create_sealed_output', output);
  // Typed outputs can outlive their still-RUNNING legacy preflight; the typed
  // row itself is authoritative for the deletion gate.
  const accountDelete = { protocol_version: 1, hashed_user_id: OWNER, scope: 'account' };
  for (const state of ['PREPARING', 'PENDING']) {
    database.rows.chat_recovery_outputs[0].state = state;
    await assert.rejects(executeOperation(database, 'invalidate_deletion', accountDelete), /pending_team_recovery/);
    assert.equal(database.rows.chat_recovery_account_fences?.length ?? 0, 0);
    assert.equal(database.rows.chat_recovery_outputs[0].state, state);
  }
  database.rows.chat_recovery_outputs[0].state = 'PENDING';
  await executeOperation(database, 'persist_output_message', {
    protocol_version: 1, hashed_user_id: OWNER, device_hash: 'device-a',
    record_id: recordId, expected_messages_v: 1, encrypted_assistant_message: assistantMessage(),
  });
  assert.equal(database.rows.chat_recovery_outputs[0].state, 'ACKNOWLEDGED');
  await executeOperation(database, 'invalidate_deletion', accountDelete);
  await executeOperation(database, 'invalidate_deletion', accountDelete);
  assert.equal(database.rows.chat_recovery_account_fences.length, 1);
  assert.equal(database.rows.chat_recovery_account_fences[0].id, OWNER);
  assert.equal(database.rows.chat_recovery_outputs[0].state, 'ACKNOWLEDGED');
  await assert.rejects(executeOperation(database, 'create_sealed_output', {
    ...output, record_id: '018f9999-9999-7999-9999-999999999999', subject_id: 'assistant-message-2',
  }), /account_recovery_fenced/);
  await assert.rejects(executeOperation(database, 'prepare_preflight', prepareBody()), /account_recovery_fenced/);
  await assert.rejects(executeOperation(database, 'enqueue_inference', {
    protocol_version: 1, preflight_id: PREFLIGHT_ID, hashed_user_id: OWNER,
    device_hash: 'device-a', inference_commitment: COMMITMENT,
    inference_task_id: TASK_ID, billing_identity: BILLING_ID, outbox_id: OUTBOX_ID,
  }), /account_recovery_fenced/);
});

// contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery,teams.workspace.surface-parity
test('account deletion refuses active legacy Team job or unpublished preflight', async () => {
  const seed = leasedSeed();
  seed.chats[0].hashed_team_id = TEAM_HASH;
  const database = fakeDatabase(seed);
  const accountDelete = { protocol_version: 1, hashed_user_id: OWNER, scope: 'account' };
  await assert.rejects(executeOperation(database, 'invalidate_deletion', accountDelete), /pending_team_recovery/);
  database.rows.chat_completion_recovery_jobs[0].state = 'TERMINAL';
  for (const state of ['PREPARED', 'ENQUEUED', 'RUNNING']) {
    database.rows.chat_turn_preflights[0].state = state;
    await assert.rejects(executeOperation(database, 'invalidate_deletion', accountDelete), /pending_team_recovery/);
  }
  database.rows.chat_turn_preflights[0].state = 'TERMINAL';
  const result = await executeOperation(database, 'invalidate_deletion', accountDelete);
  assert.equal(result.deleted_jobs, 1);
  assert.equal(database.rows.chat_recovery_account_fences[0].id, OWNER);
  await assert.rejects(executeOperation(database, 'create_sealed_job', {
    protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER,
    chat_id: CHAT_ID, turn_id: TURN_ID, preflight_id: PREFLIGHT_ID,
    inference_task_id: TASK_ID, assistant_message_id: 'assistant-message-1',
    chat_key_version: 1, sealed_payload: SEALED_PAYLOAD,
  }), /account_recovery_fenced/);
});

// contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,teams.workspace.surface-parity
test('discovery cursor advances past a full page of revoked Team outputs', async () => {
  const seed = preparedSeed();
  const inaccessibleChat = '018f8888-8888-7888-8888-999999999999';
  seed.chat_recovery_outputs = Array.from({ length: 101 }, (_, index) => ({
    id: `018f8888-8888-7888-8888-${index.toString(16).padStart(12, '0')}`,
    hashed_user_id: OWNER, state: 'PENDING', deleted_at: null,
    created_at: new Date(1_862_000_000_000 + index * 1000),
    root_chat_id: index < 100 ? inaccessibleChat : CHAT_ID,
    target_chat_id: index < 100 ? inaccessibleChat : CHAT_ID,
    root_hashed_team_id: index < 100 ? TEAM_HASH : null,
    turn_id: TURN_ID, subject_id: `subject-${index}`, output_kind: 'message',
    output_version: 1, chat_key_version: 1, message_role: 'assistant', payload_storage: 'inline',
  }));
  const database = fakeDatabase(seed);
  const discovery = { protocol_version: 1, hashed_user_id: OWNER, device_hash: 'device-a' };
  const first = await executeOperation(database, 'list_pending_outputs', discovery);
  assert.deepEqual(first.outputs, []);
  assert.equal(first.next_cursor.after_record_id, seed.chat_recovery_outputs[99].id);
  const second = await executeOperation(database, 'list_pending_outputs', {
    ...discovery, ...first.next_cursor,
  });
  assert.equal(second.outputs.length, 1);
  assert.equal(second.outputs[0].record_id, seed.chat_recovery_outputs[100].id);
  assert.equal(second.next_cursor, null);
});

test('account deletion invalidates an unfinished large upload without losing its object locator', async () => {
  const seed = preparedSeed();
  seed.chat_turn_preflights[0].state = 'RUNNING';
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_recovery_outputs = [];
  const database = fakeDatabase(seed);
  const recordId = '018f8888-8888-7888-8888-888888888888';
  const checksum = 'b'.repeat(64);
  const key = `chat-recovery/v2/bb/${recordId}/${checksum}.json`;
  const intent = {
    protocol_version: 1, record_id: recordId, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: JOB_ID, output_kind: 'embed', output_version: 1,
    chat_key_version: 1, payload_s3_key: key, payload_size_bytes: 300_000,
    sealed_payload_digest: checksum,
  };
  await executeOperation(database, 'prepare_sealed_output', intent);
  await executeOperation(database, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: OWNER, scope: 'account',
  });
  assert.equal(database.rows.chat_recovery_outputs[0].state, 'DELETED');
  assert.equal(database.rows.chat_recovery_outputs[0].payload_s3_key, key);
  assert.ok(database.rows.chat_recovery_outputs[0].writer_lease_until);
  await assert.rejects(executeOperation(database, 'create_sealed_output', {
    ...intent, payload_verified_regions: ['region-a'],
  }), /account_recovery_fenced/);
});

test('typed message acknowledgement atomically commits encrypted canonical replacement', async () => {
  const seed = preparedSeed();
  seed.chat_turn_preflights[0].state = 'RUNNING';
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_recovery_outputs = [];
  const database = fakeDatabase(seed);
  const recordId = '018f8888-8888-7888-8888-888888888888';
  await executeOperation(database, 'create_sealed_output', {
    protocol_version: 1, record_id: recordId, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: 'assistant-message-1', output_kind: 'message', output_version: 1,
    chat_key_version: 1, sealed_payload: SEALED_OUTPUT,
  });
  const request = {
    protocol_version: 1, hashed_user_id: OWNER, device_hash: 'device-a', record_id: recordId,
    expected_messages_v: 1, encrypted_assistant_message: assistantMessage(),
  };
  const acknowledged = await executeOperation(database, 'persist_output_message', request);
  assert.equal(acknowledged.committed_messages_v, 2);
  assert.equal(database.rows.chat_recovery_outputs[0].sealed_payload, null);
  assert.equal(database.rows.messages.length, 2);
  const retry = await executeOperation(database, 'persist_output_message', request);
  assert.equal(retry.idempotent, true);
  assert.equal(database.rows.messages.length, 2);
});

test('typed message revision advances canonical ciphertext and rejects stale source versions', async () => {
  const seed = preparedSeed();
  seed.chat_turn_preflights[0].state = 'RUNNING';
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_recovery_outputs = [];
  seed.messages.push({ id: JOB_ID, ...assistantMessage(), assistant_source_revision: 1 });
  seed.chats[0].messages_v = 2;
  const database = fakeDatabase(seed);
  const recordId = '018f8888-8888-7888-8888-888888888888';
  await executeOperation(database, 'create_sealed_output', {
    protocol_version: 1, record_id: recordId, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: 'assistant-message-1', output_kind: 'message', output_version: 2,
    chat_key_version: 1, sealed_payload: SEALED_OUTPUT,
  });
  const newer = { ...assistantMessage(), encrypted_content: 'encrypted-assistant-v2' };
  const request = { protocol_version: 1, hashed_user_id: OWNER, device_hash: 'device-a',
    record_id: recordId, expected_messages_v: 2, encrypted_assistant_message: newer };
  const ack = await executeOperation(database, 'persist_output_message', request);
  assert.equal(ack.committed_messages_v, 3);
  assert.equal(database.rows.messages[1].encrypted_content, newer.encrypted_content);
  assert.equal(database.rows.messages[1].assistant_source_revision, 2);
  assert.equal(database.rows.chats[0].messages_v, 3);
  const staleDb = fakeDatabase({ ...seed, messages: [{ ...seed.messages[0] },
    { ...seed.messages[1], assistant_source_revision: 3 }] });
  await executeOperation(staleDb, 'create_sealed_output', {
    protocol_version: 1, record_id: recordId, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: 'assistant-message-1', output_kind: 'message', output_version: 2,
    chat_key_version: 1, sealed_payload: SEALED_OUTPUT,
  });
  await assert.rejects(executeOperation(staleDb, 'persist_output_message', request), /stale_assistant_source_revision/);
});

test('sealed child prompt commits only as a user message with its fixed identity', async () => {
  const seed = preparedSeed();
  seed.chat_turn_preflights[0].state = 'RUNNING';
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_recovery_outputs = [];
  const database = fakeDatabase(seed);
  const recordId = '018f8888-8888-7888-8888-888888888888';
  const subjectId = 'child-prompt-1';
  await executeOperation(database, 'create_sealed_output', {
    protocol_version: 1, record_id: recordId, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: subjectId, output_kind: 'message', output_version: 1,
    message_role: 'user', chat_key_version: 1, sealed_payload: SEALED_OUTPUT,
  });
  const encryptedUser = { ...assistantMessage(), client_message_id: subjectId,
    role: 'user', encrypted_content: 'client-encrypted-child-prompt' };
  const base = { protocol_version: 1, hashed_user_id: OWNER,
    device_hash: 'device-a', record_id: recordId, expected_messages_v: 1 };
  await assert.rejects(executeOperation(database, 'persist_output_message', {
    ...base, encrypted_assistant_message: { ...encryptedUser, role: 'assistant' },
  }), /message_role_mismatch/);
  const committed = await executeOperation(database, 'persist_output_message', {
    ...base, encrypted_user_message: encryptedUser,
  });
  assert.equal(committed.state, 'ACKNOWLEDGED');
  assert.equal(database.rows.messages[1].role, 'user');
  assert.equal(database.rows.messages[1].assistant_source_revision, null);
});

test('same source revision acknowledges only the exact canonical ciphertext after fenced replacement', async () => {
  const seed = preparedSeed();
  seed.chat_turn_preflights[0].state = 'RUNNING';
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_recovery_outputs = [];
  seed.messages.push({ id: JOB_ID, ...assistantMessage(), assistant_source_revision: 1,
    encrypted_content: 'older-client-ciphertext' });
  seed.chats[0].messages_v = 2;
  const database = fakeDatabase(seed);
  const recordId = '018f8888-8888-7888-8888-888888888888';
  await executeOperation(database, 'create_sealed_output', {
    protocol_version: 1, record_id: recordId, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: 'assistant-message-1', output_kind: 'message', output_version: 1,
    message_role: 'assistant', chat_key_version: 1, sealed_payload: SEALED_OUTPUT,
  });
  const replacement = { ...assistantMessage(), encrypted_content: 'sealed-output-client-ciphertext' };
  const ack = await executeOperation(database, 'persist_output_message', {
    protocol_version: 1, hashed_user_id: OWNER, device_hash: 'device-a', record_id: recordId,
    expected_messages_v: 2, encrypted_assistant_message: replacement,
  });
  assert.equal(ack.idempotent, false);
  assert.equal(ack.committed_messages_v, 3);
  assert.equal(database.rows.messages[1].encrypted_content, replacement.encrypted_content);
  assert.match(database.rows.chat_recovery_outputs[0].canonical_digest, /^[0-9a-f]{64}$/);
});

test('typed summary acknowledgement updates encrypted chat metadata and clears pending fence', async () => {
  const seed = preparedSeed();
  seed.chats[0].metadata_v = 0;
  seed.chat_turn_preflights[0].state = 'RUNNING';
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_recovery_outputs = [];
  const database = fakeDatabase(seed);
  const recordId = '018f8888-8888-7888-8888-888888888888';
  await executeOperation(database, 'create_sealed_output', {
    protocol_version: 1, record_id: recordId, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: 'assistant-message-1', output_kind: 'summary', output_version: 1,
    chat_key_version: 1, sealed_payload: SEALED_OUTPUT,
  });
  const pendingBody = { protocol_version: 1, hashed_user_id: OWNER, target_chat_id: CHAT_ID };
  assert.equal((await executeOperation(database, 'has_pending_chat_outputs', pendingBody)).has_pending, true);
  const acknowledged = await executeOperation(database, 'persist_output_summary', {
    protocol_version: 1, hashed_user_id: OWNER, device_hash: 'device-a', record_id: recordId,
    expected_metadata_v: 0, encrypted_summary: 'encrypted summary',
  });
  assert.equal(acknowledged.committed_metadata_v, 1);
  assert.equal(database.rows.chats[0].encrypted_chat_summary, 'encrypted summary');
  database.rows.chat_turn_preflights[0].state = 'TERMINAL';
  assert.equal((await executeOperation(database, 'has_pending_chat_outputs', pendingBody)).has_pending, false);
});

test('checkpoint acknowledgement requires matching canonical client ciphertext and boundary', async () => {
  const seed = preparedSeed();
  seed.chat_turn_preflights[0].state = 'RUNNING';
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_recovery_outputs = [];
  seed.chat_compression_checkpoints = [];
  const database = fakeDatabase(seed);
  const recordId = '018f8888-8888-7888-8888-888888888888';
  await executeOperation(database, 'create_sealed_output', {
    protocol_version: 1, record_id: recordId, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: JOB_ID, output_kind: 'checkpoint', output_version: 1,
    chat_key_version: 1, sealed_payload: SEALED_OUTPUT,
  });
  const ack = {
    protocol_version: 1, hashed_user_id: OWNER, device_hash: 'device-a', record_id: recordId,
    encrypted_summary: 'encrypted-summary', compressed_up_to_message_id: 'older-message-id',
  };
  await assert.rejects(executeOperation(database, 'acknowledge_output_checkpoint', ack), /canonical_checkpoint_mismatch/);
  database.rows.chat_compression_checkpoints.push({
    id: JOB_ID, chat_id: CHAT_ID, hashed_user_id: OWNER,
    encrypted_summary: 'encrypted-summary', compressed_up_to_message_id: 'older-message-id',
    covered_message_ids: ['message-a', 'message-b'],
  });
  ack.covered_message_ids = ['message-a'];
  await assert.rejects(executeOperation(database, 'acknowledge_output_checkpoint', ack), /canonical_checkpoint_mismatch/);
  ack.covered_message_ids = ['message-a', 'message-b'];
  const result = await executeOperation(database, 'acknowledge_output_checkpoint', ack);
  assert.equal(result.state, 'ACKNOWLEDGED');
  assert.equal(database.rows.chat_recovery_outputs[0].sealed_payload, null);
});

test('embed and diff recovery acknowledge only after canonical encrypted rows exist', async () => {
  const seed = preparedSeed();
  seed.chat_turn_preflights[0].state = 'RUNNING';
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_recovery_outputs = [];
  seed.embeds = [];
  seed.embed_diffs = [];
  seed.embed_keys = [];
  const database = fakeDatabase(seed);
  const embedId = '018f8888-8888-7888-8888-888888888888';
  const diffId = '018f9999-9999-7999-8999-999999999999';
  for (const [recordId, kind] of [[embedId, 'embed'], [diffId, 'diff']]) {
    await executeOperation(database, 'create_sealed_output', {
      protocol_version: 1, record_id: recordId, hashed_user_id: OWNER,
      root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
      preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
      subject_id: embedId, output_kind: kind, output_version: 2,
      chat_key_version: 1, sealed_payload: SEALED_OUTPUT,
    });
  }
  const request = (record_id, canonical_digest) => ({
    protocol_version: 1, hashed_user_id: OWNER, device_hash: 'device-a', record_id, canonical_digest,
  });
  const embedDigest = sha256('client-encrypted-embed');
  const diffDigest = sha256(JSON.stringify([null, 'client-encrypted-patch']));
  await assert.rejects(executeOperation(database, 'acknowledge_output_embed', request(embedId, embedDigest)), /canonical_embed_missing/);
  database.rows.embeds.push({ embed_id: embedId, hashed_user_id: OWNER, hashed_chat_id: sha256(CHAT_ID),
    version_number: 2, encrypted_content: 'client-encrypted-embed' });
  await assert.rejects(executeOperation(database, 'acknowledge_output_embed', request(embedId, embedDigest)), /canonical_embed_key_missing/);
  database.rows.embed_keys.push(
    { hashed_embed_id: sha256(embedId), hashed_user_id: OWNER, key_type: 'master', encrypted_embed_key: 'master-wrapper' },
    { hashed_embed_id: sha256(embedId), hashed_user_id: OWNER, key_type: 'chat', hashed_chat_id: sha256(CHAT_ID), encrypted_embed_key: 'chat-wrapper' },
  );
  await assert.rejects(executeOperation(database, 'acknowledge_output_embed', request(embedId, sha256('wrong'))), /canonical_output_mismatch/);
  const embedAck = await executeOperation(database, 'acknowledge_output_embed', request(embedId, embedDigest));
  assert.equal(embedAck.state, 'ACKNOWLEDGED');
  await assert.rejects(executeOperation(database, 'acknowledge_output_embed', request(embedId, sha256('wrong'))), /canonical_output_mismatch/);
  await assert.rejects(executeOperation(database, 'acknowledge_output_embed', request(diffId, diffDigest)), /canonical_diff_missing/);
  database.rows.embed_diffs.push({ embed_id: embedId, version_number: 2,
    hashed_user_id: OWNER, encrypted_patch: 'client-encrypted-patch' });
  const diffAck = await executeOperation(database, 'acknowledge_output_embed', request(diffId, diffDigest));
  assert.equal(diffAck.state, 'ACKNOWLEDGED');
  assert.equal(database.rows.chat_recovery_outputs.every((row) => row.sealed_payload === null), true);
});

test('a progressed embed head acknowledges only against its immutable historical version row', async () => {
  const seed = preparedSeed();
  seed.chat_turn_preflights[0].state = 'RUNNING';
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_recovery_outputs = [];
  seed.embeds = [{ embed_id: JOB_ID, hashed_user_id: OWNER, hashed_chat_id: sha256(CHAT_ID),
    version_number: 3, encrypted_content: 'newer-head-ciphertext' }];
  seed.embed_diffs = [{ embed_id: JOB_ID, hashed_user_id: OWNER,
    version_number: 2, encrypted_patch: 'historical-patch-ciphertext' }];
  seed.embed_keys = [
    { hashed_embed_id: sha256(JOB_ID), hashed_user_id: OWNER, key_type: 'master', encrypted_embed_key: 'master-wrapper' },
    { hashed_embed_id: sha256(JOB_ID), hashed_user_id: OWNER, key_type: 'chat', hashed_chat_id: sha256(CHAT_ID), encrypted_embed_key: 'chat-wrapper' },
  ];
  const database = fakeDatabase(seed);
  const recordId = '018fdddd-dddd-7ddd-8ddd-dddddddddddd';
  await executeOperation(database, 'create_sealed_output', {
    protocol_version: 1, record_id: recordId, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: JOB_ID, output_kind: 'embed', output_version: 2,
    chat_key_version: 1, sealed_payload: SEALED_OUTPUT,
  });
  const base = { protocol_version: 1, hashed_user_id: OWNER,
    device_hash: 'device-a', record_id: recordId };
  await assert.rejects(executeOperation(database, 'acknowledge_output_embed', {
    ...base, canonical_digest: sha256('newer-head-ciphertext'), canonical_source: 'head',
  }), /canonical_embed_head_advanced/);
  await assert.rejects(executeOperation(database, 'acknowledge_output_embed', {
    ...base, canonical_digest: sha256('newer-head-ciphertext'), canonical_source: 'version_row',
  }), /canonical_output_mismatch/);
  const acknowledged = await executeOperation(database, 'acknowledge_output_embed', {
    ...base, canonical_digest: sha256(JSON.stringify([null, 'historical-patch-ciphertext'])),
    canonical_source: 'version_row',
  });
  assert.equal(acknowledged.state, 'ACKNOWLEDGED');
});

test('child archive markers require sealed delivery, the exact continuation task, and canonical acknowledgement', async () => {
  const seed = preparedSeed();
  const childId = '018faaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa';
  const batchId = '018fbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb';
  const continuationId = '018fcccc-cccc-7ccc-8ccc-cccccccccccc';
  seed.chats.push({ id: childId, hashed_user_id: OWNER, parent_id: CHAT_ID, is_sub_chat: true,
    encrypted_chat_key: null });
  seed.sub_chat_orchestrations = [{ id: JOB_ID, hashed_user_id: OWNER, root_chat_id: CHAT_ID }];
  seed.sub_chat_orchestration_children = [{ child_chat_id: childId, orchestration_id: JOB_ID,
    batch_id: batchId, state: 'completed' }];
  seed.sub_chat_orchestration_batches = [{ id: batchId, parent_chat_id: CHAT_ID,
    continuation_task_id: continuationId, continuation_dispatched_at: new Date() }];
  seed.chat_recovery_outputs = [{ id: '018fdddd-dddd-7ddd-8ddd-dddddddddddd',
    hashed_user_id: OWNER, target_chat_id: childId, output_kind: 'message', state: 'PENDING', deleted_at: null }];
  const database = fakeDatabase(seed);
  const base = { protocol_version: 1, hashed_user_id: OWNER,
    child_chat_id: childId, root_chat_id: CHAT_ID };
  const canonicalBase = { protocol_version: 1, hashed_user_id: OWNER, child_chat_id: childId };
  await assert.rejects(executeOperation(database, 'mark_child_canonical_acknowledged', canonicalBase), /child_key_not_acknowledged/);
  await executeOperation(database, 'mark_child_result_delivered', base);
  assert.ok(database.rows.chats[1].child_result_delivered_at);
  await assert.rejects(executeOperation(database, 'mark_child_parent_consumed', {
    ...base, continuation_task_id: TASK_ID,
  }), /child_parent_not_consumed/);
  await executeOperation(database, 'mark_child_parent_consumed', {
    ...base, continuation_task_id: continuationId,
  });
  assert.ok(database.rows.chats[1].child_parent_consumed_at);
  database.rows.chats[1].encrypted_chat_key = 'client-wrapped-key';
  await assert.rejects(executeOperation(database, 'mark_child_canonical_acknowledged', canonicalBase), /child_canonical_ack_pending/);
  database.rows.chat_recovery_outputs[0].state = 'ACKNOWLEDGED';
  await executeOperation(database, 'mark_child_canonical_acknowledged', canonicalBase);
  assert.ok(database.rows.chats[1].child_canonical_acknowledged_at);
});

test('unacknowledged technical failure alerts replay until an exact idempotent acknowledgement', async () => {
  const now = new Date('2029-01-02T00:00:00Z');
  const database = fakeDatabase({
    chat_turn_preflights: [{
      id: PREFLIGHT_ID,
      inference_task_id: TASK_ID,
      chat_id: CHAT_ID,
      user_message_id: 'user-message-1',
      state: 'FAILED',
      failed_at: new Date('2029-01-01T00:00:00Z'),
      failure_category: 'claim_expired',
      failure_alert_pending_at: new Date('2029-01-01T00:00:00Z'),
      failure_alert_queued_at: null,
    }],
    chat_completion_recovery_jobs: [],
    chat_inference_outbox: [],
  });

  const disabled = await executeOperation(database, 'cleanup_expired', { protocol_version: 1 }, now);
  assert.deepEqual(disabled.failure_alert_candidates, []);
  const cleanupBody = { protocol_version: 1, failure_alerts_enabled: true };
  const first = await executeOperation(database, 'cleanup_expired', cleanupBody, now);
  const replay = await executeOperation(database, 'cleanup_expired', cleanupBody, now);
  assert.deepEqual(first.failure_alert_candidates, replay.failure_alert_candidates);
  assert.deepEqual(first.failure_alert_candidates, [{
    preflight_id: PREFLIGHT_ID,
    inference_task_id: TASK_ID,
    chat_id: CHAT_ID,
    user_message_id: 'user-message-1',
    failure_category: 'claim_expired',
  }]);

  const acknowledged = await executeOperation(database, 'acknowledge_failure_alert', {
    protocol_version: 1,
    preflight_id: PREFLIGHT_ID,
    inference_task_id: TASK_ID,
    failure_category: 'claim_expired',
  }, now);
  const duplicate = await executeOperation(database, 'acknowledge_failure_alert', {
    protocol_version: 1,
    preflight_id: PREFLIGHT_ID,
    inference_task_id: TASK_ID,
    failure_category: 'claim_expired',
  }, new Date(now.getTime() + 1000));
  assert.deepEqual(acknowledged, { preflight_id: PREFLIGHT_ID, acknowledged: true, idempotent: false });
  assert.deepEqual(duplicate, { preflight_id: PREFLIGHT_ID, acknowledged: false, idempotent: true });
  assert.deepEqual(
    (await executeOperation(database, 'cleanup_expired', cleanupBody, now)).failure_alert_candidates,
    [],
  );
});

test('failure alert replay includes future technical categories and excludes expected outcomes', async () => {
  const technical = [
    'claim_expired', 'dispatch_failed', 'runtime_error', 'soft_time_limit',
    'unhandled_error', 'worker_timeout', 'future_transport_error',
  ];
  const rows = [...technical, 'user_cancelled', 'policy_rejection'].map((failureCategory, index) => ({
    id: `018f1111-1111-7111-8111-11111111111${index}`,
    inference_task_id: `018f2222-2222-7222-8222-22222222222${index}`,
    chat_id: CHAT_ID,
    user_message_id: `user-message-${index}`,
    state: 'FAILED',
    failed_at: new Date('2029-01-01T00:00:00Z'),
    failure_category: failureCategory,
    failure_alert_pending_at: new Date('2029-01-01T00:00:00Z'),
    failure_alert_queued_at: null,
  }));
  const database = fakeDatabase({
    chat_turn_preflights: rows,
    chat_completion_recovery_jobs: [],
    chat_inference_outbox: [],
  });

  const result = await executeOperation(database, 'cleanup_expired', {
    protocol_version: 1, failure_alerts_enabled: true,
  }, new Date('2029-01-02T00:00:00Z'));
  assert.deepEqual(
    result.failure_alert_candidates.map((candidate) => candidate.failure_category).sort(),
    [...technical].sort(),
  );
});

test('sealed recovery survives cleanup and expiring sealed jobs cannot become later timeout alerts', async () => {
  const now = new Date('2029-01-08T00:00:00Z');
  const seed = leasedSeed(new Date('2029-01-01T00:00:00Z'));
  seed.chat_turn_preflights[0].expires_at = new Date('2029-01-02T00:00:00Z');
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_turn_preflights[0].user_message_id = 'user-message-1';
  seed.chat_completion_recovery_jobs[0].expires_at = now;
  const database = fakeDatabase(seed);

  const cleanupBody = { protocol_version: 1, failure_alerts_enabled: true };
  const result = await executeOperation(database, 'cleanup_expired', cleanupBody, now);
  assert.equal(result.failed_inferences, 0);
  assert.equal(result.expired_jobs, 0);
  assert.deepEqual(result.failure_alert_candidates, []);
  assert.equal(database.rows.chat_turn_preflights[0].state, 'ABANDONED');
  assert.equal(database.rows.chat_completion_recovery_jobs.length, 1);
  const later = await executeOperation(
    database, 'cleanup_expired', cleanupBody, new Date(now.getTime() + 60_000),
  );
  assert.deepEqual(later.failure_alert_candidates, []);
});

test('cleanup alerts expired enqueued work but excludes prepared abandonment and rejects stale acknowledgements', async () => {
  const now = new Date('2029-01-02T00:00:00Z');
  const preparedId = '018faaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa';
  const database = fakeDatabase({
    chat_turn_preflights: [
      {
        id: preparedId, state: 'PREPARED', chat_id: CHAT_ID, user_message_id: 'prepared-message',
        expires_at: now, inference_task_id: null,
      },
      {
        id: PREFLIGHT_ID, state: 'ENQUEUED', chat_id: CHAT_ID, user_message_id: 'user-message-1',
        expires_at: now, inference_task_id: TASK_ID, outbox_id: OUTBOX_ID,
      },
    ],
    chat_completion_recovery_jobs: [],
    chat_inference_outbox: [{ id: OUTBOX_ID, preflight_id: PREFLIGHT_ID, state: 'PENDING' }],
  });

  const result = await executeOperation(
    database, 'cleanup_expired', { protocol_version: 1, failure_alerts_enabled: true }, now,
  );
  assert.equal(database.rows.chat_turn_preflights.find((row) => row.id === preparedId).state, 'ABANDONED');
  assert.equal(database.rows.chat_turn_preflights.find((row) => row.id === PREFLIGHT_ID).state, 'FAILED');
  assert.deepEqual(result.failure_alert_candidates.map((row) => row.preflight_id), [PREFLIGHT_ID]);
  await assert.rejects(
    executeOperation(database, 'acknowledge_failure_alert', {
      protocol_version: 1,
      preflight_id: PREFLIGHT_ID,
      inference_task_id: '018f9999-9999-7999-8999-999999999999',
      failure_category: 'claim_expired',
    }, now),
    (error) => error instanceof ProtocolError && error.code === 'failure_alert_not_found',
  );
  await assert.rejects(
    executeOperation(database, 'acknowledge_failure_alert', {
      protocol_version: 1,
      preflight_id: preparedId,
      inference_task_id: TASK_ID,
      failure_category: 'claim_expired',
    }, now),
    (error) => error instanceof ProtocolError && error.code === 'failure_alert_not_found',
  );
});

test('chat deletion invalidates recovery state and rejects a late sealed job', async () => {
  const seed = leasedSeed();
  seed.chat_recovery_outputs = [{
    id: '018f8888-8888-7888-8888-888888888888', hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, state: 'PENDING', deleted_at: null,
    payload_storage: 's3', payload_s3_key: 'chat-recovery/v2/aa/record/hash.json',
  }];
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_turn_preflights[0].chat_key_version = 1;
  seed.chat_inference_outbox.push({ id: OUTBOX_ID, hashed_user_id: OWNER, chat_id: CHAT_ID });
  const database = fakeDatabase(seed);
  const invalidated = await executeOperation(database, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: OWNER, scope: 'chat', chat_id: CHAT_ID,
  }, new Date('2029-01-01T00:00:00Z'));

  assert.deepEqual(invalidated, {
    deleted_preflights: 1, deleted_jobs: 1, deleted_metadata_jobs: 0,
    deleted_outbox: 1, invalidated_outputs: 1,
    invalidated_producers: 0, invalidated_rerenders: 0, invalidated_direct_skills: 0,
    invalidated_legacy_producers: 0, invalidated_legacy_batches: 0,
    chat_deletion_fenced: true, chat_id: CHAT_ID,
  });
  assert.equal(database.rows.chat_recovery_outputs[0].state, 'DELETED');
  assert.equal(database.rows.chat_recovery_outputs[0].payload_s3_key, 'chat-recovery/v2/aa/record/hash.json');
  assert.deepEqual(database.rows.operational_monitoring_events, [{
    id: database.rows.operational_monitoring_events[0].id,
    event_type: 'recovery_jobs_invalidated', count: 1,
    occurred_at: new Date('2029-01-01T00:00:00Z'),
  }]);
  await assert.rejects(
    executeOperation(database, 'create_sealed_job', {
      protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER, chat_id: CHAT_ID, turn_id: TURN_ID,
      preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID, assistant_message_id: 'assistant-message-1',
      chat_key_version: 1, sealed_payload: SEALED_PAYLOAD,
    }, new Date('2029-01-01T00:00:01Z')),
    (error) => error instanceof ProtocolError && error.code === 'inference_not_running',
  );
});

test('chat deletion rolls back when invalidation aggregation cannot be recorded', async () => {
  const seed = leasedSeed();
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_inference_outbox.push({ id: OUTBOX_ID, hashed_user_id: OWNER, chat_id: CHAT_ID });
  const database = fakeDatabase(seed, {
    operation: 'insert', table: 'operational_monitoring_events', occurrence: 1,
  });

  await assert.rejects(
    executeOperation(database, 'invalidate_deletion', {
      protocol_version: 1, hashed_user_id: OWNER, scope: 'chat', chat_id: CHAT_ID,
    }, new Date('2029-01-01T00:00:00Z')),
    /injected insert:operational_monitoring_events failure/,
  );
  assert.equal(database.rows.chat_completion_recovery_jobs.length, 1);
  assert.equal(database.rows.chat_turn_preflights.length, 1);
  assert.equal(database.rows.chat_inference_outbox.length, 1);
});

test('permanent chat deletion fence blocks lost-ACK preflight after the Redis tombstone lifetime', async () => {
  const database = fakeDatabase({ chats: [{ id: CHAT_ID, hashed_user_id: OWNER }], messages: [], chat_turn_preflights: [] });
  const deletedAt = new Date('2029-01-01T00:00:00Z');
  const deleted = await executeOperation(database, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: OWNER, scope: 'chat', chat_id: CHAT_ID,
  }, deletedAt);
  assert.equal(deleted.deleted_preflights, 0);
  assert.equal(deleted.chat_deletion_fenced, true);
  assert.equal(deleted.chat_id, CHAT_ID);
  assert.equal(database.rows.chat_recovery_chat_deletion_fences.length, 1);
  assert.equal(database.rows.chat_recovery_chat_deletion_fences[0].fenced_at.getTime(), deletedAt.getTime());
  const lookup = { protocol_version: 1, hashed_user_id: OWNER, chat_ids: [CHAT_ID] };
  assert.deepEqual(await executeOperation(database, 'lookup_chat_deletion_fences', lookup), {
    fenced_chat_ids: [CHAT_ID],
  });
  // The asynchronous deletion worker has now removed the chat row, and the
  // short Redis tombstone would already have expired at the next timestamp.
  database.rows.chats = [];
  await assert.rejects(
    executeOperation(database, 'prepare_preflight', prepareBody(), new Date('2029-02-02T00:00:00Z')),
    (error) => error instanceof ProtocolError && error.code === 'chat_not_found',
  );
  assert.deepEqual(database.rows.chats, []);
  assert.deepEqual(database.rows.messages, []);
  assert.deepEqual(database.rows.chat_turn_preflights, []);

  const again = await executeOperation(database, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: OWNER, scope: 'chat', chat_id: CHAT_ID,
  }, new Date('2029-02-03T00:00:00Z'));
  assert.equal(again.chat_deletion_fenced, true);
  assert.equal(again.chat_id, CHAT_ID);
  assert.equal(database.rows.chat_recovery_chat_deletion_fences.length, 1);
  assert.equal(database.rows.chat_recovery_chat_deletion_fences[0].fenced_at.getTime(), deletedAt.getTime());
});

test('chat fence lookup is owner scoped and bounded without scanning another owner', async () => {
  const otherOwner = 'd'.repeat(64);
  const otherChat = '018f9999-9999-7999-8999-999999999999';
  const database = fakeDatabase({
    chats: [], messages: [], chat_turn_preflights: [],
    chat_recovery_chat_deletion_fences: [{
      id: CHAT_ID, hashed_user_id: OWNER,
      chat_id: CHAT_ID, fenced_at: new Date('2029-01-01T00:00:00Z'),
    }],
  });
  assert.deepEqual(await executeOperation(database, 'lookup_chat_deletion_fences', {
    protocol_version: 1, hashed_user_id: OWNER, chat_ids: [otherChat, CHAT_ID],
  }), { fenced_chat_ids: [CHAT_ID] });
  assert.deepEqual(await executeOperation(database, 'lookup_chat_deletion_fences', {
    protocol_version: 1, hashed_user_id: otherOwner, chat_ids: [CHAT_ID],
  }), { fenced_chat_ids: [] });
  await assert.rejects(executeOperation(database, 'lookup_chat_deletion_fences', {
    protocol_version: 1, hashed_user_id: OWNER, chat_ids: Array(101).fill(CHAT_ID),
  }), (error) => error instanceof ProtocolError && error.code === 'invalid_chat_ids');
  await assert.rejects(executeOperation(database, 'lookup_chat_deletion_fences', {
    protocol_version: 1, hashed_user_id: OWNER, chat_ids: [CHAT_ID, CHAT_ID],
  }), (error) => error instanceof ProtocolError && error.code === 'duplicate_chat_id');
  const prepared = await executeOperation(database, 'prepare_preflight', prepareBody({
    hashed_user_id: otherOwner,
    chat_id: otherChat,
    encrypted_user_message: { ...userMessage(), hashed_user_id: otherOwner, chat_id: otherChat },
  }));
  assert.equal(prepared.state, 'PREPARED');
  assert.equal(database.rows.chats[0].id, otherChat);
});

test('foreign existing chat cannot be fenced and a failed fence insert cannot invalidate recovery', async () => {
  const foreign = fakeDatabase({
    chats: [{ id: CHAT_ID, hashed_user_id: 'd'.repeat(64) }],
    messages: [], chat_turn_preflights: [],
  });
  await assert.rejects(executeOperation(foreign, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: OWNER, scope: 'chat', chat_id: CHAT_ID,
  }), (error) => error instanceof ProtocolError && error.code === 'chat_not_found');
  assert.deepEqual(foreign.rows.chat_recovery_chat_deletion_fences ?? [], []);

  await assert.rejects(executeOperation(fakeDatabase({ chats: [] }), 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: OWNER, scope: 'chat', chat_id: CHAT_ID,
  }), (error) => error instanceof ProtocolError && error.code === 'chat_not_found');

  const seed = leasedSeed();
  const failed = fakeDatabase(seed, { operation: 'insert', table: 'chat_recovery_chat_deletion_fences' });
  await assert.rejects(executeOperation(failed, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: OWNER, scope: 'chat', chat_id: CHAT_ID,
  }), /injected insert:chat_recovery_chat_deletion_fences failure/);
  assert.equal(failed.rows.chat_turn_preflights.length, 1);
  assert.equal(failed.rows.chat_completion_recovery_jobs.length, 1);
  assert.deepEqual(failed.rows.chat_recovery_chat_deletion_fences ?? [], []);
});

test('Team chat deletion fences its UUID for every member and invalidates all member work', async () => {
  const member = 'd'.repeat(64);
  const outsider = 'e'.repeat(64);
  const seed = preparedSeed();
  seed.chats[0].hashed_team_id = TEAM_HASH;
  seed.chats[0].hashed_user_id = null;
  seed.teams = [{ hashed_team_id: TEAM_HASH, status: 'active' }];
  seed.team_memberships = [
    { hashed_team_id: TEAM_HASH, hashed_user_id: OWNER, status: 'active', role: 'admin' },
    { hashed_team_id: TEAM_HASH, hashed_user_id: member, status: 'active', role: 'member' },
  ];
  seed.chat_turn_preflights.push({ ...seed.chat_turn_preflights[0], id: JOB_ID,
    hashed_user_id: member, turn_id: '018f9999-9999-7999-8999-999999999999' });
  seed.chat_completion_recovery_jobs.push({ id: JOB_ID, chat_id: CHAT_ID, hashed_user_id: member });
  const database = fakeDatabase(seed);
  await assert.rejects(executeOperation(database, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: member, scope: 'chat', chat_id: CHAT_ID,
  }), (error) => error instanceof ProtocolError && error.code === 'chat_not_found');
  assert.deepEqual(database.rows.chat_recovery_chat_deletion_fences ?? [], []);

  const result = await executeOperation(database, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: OWNER, scope: 'chat', chat_id: CHAT_ID,
  });
  assert.equal(result.deleted_preflights, 2);
  assert.equal(result.deleted_jobs, 1);
  assert.deepEqual(database.rows.chat_recovery_chat_deletion_fences.map((fence) => ({
    id: fence.id, hashed_team_id: fence.hashed_team_id,
  })), [{ id: CHAT_ID, hashed_team_id: TEAM_HASH }]);
  const lookup = (hashed_user_id) => executeOperation(database, 'lookup_chat_deletion_fences', {
    protocol_version: 1, hashed_user_id, chat_ids: [CHAT_ID],
  });
  assert.deepEqual(await lookup(member), { fenced_chat_ids: [CHAT_ID] });
  assert.deepEqual(await lookup(outsider), { fenced_chat_ids: [] });
  await assert.rejects(executeOperation(database, 'prepare_preflight', prepareBody({
    hashed_user_id: member, hashed_team_id: TEAM_HASH,
    encrypted_user_message: { ...userMessage(), hashed_user_id: member },
  })), (error) => error instanceof ProtocolError && error.code === 'chat_not_found');
  database.rows.team_memberships[1].status = 'removed';
  assert.deepEqual(await lookup(member), { fenced_chat_ids: [] });
  database.rows.team_memberships[0].status = 'removed';
  const retry = await executeOperation(database, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: OWNER, scope: 'chat', chat_id: CHAT_ID,
  });
  assert.equal(retry.chat_deletion_fenced, true);
  assert.equal(database.rows.chat_recovery_chat_deletion_fences.length, 1);
});

test('active Team creator-member keeps existing delete authority without granting it to unrelated members', async () => {
  const member = 'd'.repeat(64);
  const database = fakeDatabase({
    chats: [{ id: CHAT_ID, hashed_user_id: OWNER, hashed_team_id: TEAM_HASH }],
    teams: [{ hashed_team_id: TEAM_HASH, status: 'active' }],
    team_memberships: [
      { hashed_team_id: TEAM_HASH, hashed_user_id: OWNER, status: 'active', role: 'member' },
      { hashed_team_id: TEAM_HASH, hashed_user_id: member, status: 'active', role: 'member' },
    ],
  });
  await assert.rejects(executeOperation(database, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: member, scope: 'chat', chat_id: CHAT_ID,
  }), (error) => error instanceof ProtocolError && error.code === 'chat_not_found');
  const result = await executeOperation(database, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: OWNER, scope: 'chat', chat_id: CHAT_ID,
  });
  assert.equal(result.chat_deletion_fenced, true);
});

test('rewind invalidates volatile recovery state without permanently deleting a surviving chat', async () => {
  const database = fakeDatabase(preparedSeed());
  const result = await executeOperation(database, 'invalidate_rewind', {
    protocol_version: 1, hashed_user_id: OWNER, chat_id: CHAT_ID,
  });
  assert.equal(result.deleted_preflights, 1);
  assert.equal(result.chat_deletion_fenced, undefined);
  assert.deepEqual(database.rows.chat_recovery_chat_deletion_fences ?? [], []);
  const nextMessage = userMessage('user-message-2');
  const next = await executeOperation(database, 'prepare_preflight', prepareBody({
    turn_id: '018f8888-8888-7888-8888-888888888888',
    user_message_id: nextMessage.client_message_id,
    encrypted_user_message: nextMessage,
    expected_messages_v: 1,
    encrypted_chat_metadata: undefined,
  }));
  assert.equal(next.state, 'PREPARED');
});

test('concurrent prepare and deletion serialize to a permanent fence and never leave a resurrected chat', async () => {
  const deleteBody = { protocol_version: 1, hashed_user_id: OWNER, scope: 'chat', chat_id: CHAT_ID };
  for (const deleteFirst of [true, false]) {
    const database = fakeDatabase(preparedSeed());
    const nextMessage = userMessage('user-message-2');
    const prepare = () => executeOperation(database, 'prepare_preflight', prepareBody({
      turn_id: '018f8888-8888-7888-8888-888888888888', user_message_id: nextMessage.client_message_id,
      encrypted_user_message: nextMessage, expected_messages_v: 1, encrypted_chat_metadata: undefined,
    }));
    const deletion = () => executeOperation(database, 'invalidate_deletion', deleteBody);
    await Promise.allSettled(deleteFirst ? [deletion(), prepare()] : [prepare(), deletion()]);
    assert.equal(database.rows.chat_recovery_chat_deletion_fences.length, 1);
    assert.equal(database.rows.chat_turn_preflights.length, 0);
    await assert.rejects(prepare(), (error) => error instanceof ProtocolError && error.code === 'chat_not_found');
  }
});

const PRODUCER_TASK = '018faaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa';
const PRODUCER_EMBED = '018fbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb';
const PRODUCER_RECORD = '018fcccc-cccc-7ccc-8ccc-cccccccccccc';
const producerBody = (overrides = {}) => ({
  protocol_version: 1, task_uuid: PRODUCER_TASK,
  task_name: 'apps.images.tasks.generate_image', kwargs_binding: 'd'.repeat(64),
  hashed_user_id: OWNER, root_chat_id: CHAT_ID, target_chat_id: CHAT_ID,
  turn_id: TURN_ID, preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
  chat_key_version: 1, primary_embed_id: PRODUCER_EMBED,
  primary_message_id: 'user-message-1', primary_output_kind: 'embed',
  primary_output_version: 1, max_children: 32, ...overrides,
});
const producerSeed = () => {
  const seed = preparedSeed();
  seed.chat_turn_preflights[0].state = 'RUNNING';
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_recovery_outputs = [];
  seed.chat_recovery_output_producers = [];
  seed.chat_recovery_output_producer_children = [];
  return seed;
};

test('registered detached producer is bound to the preflight and survives terminal only for its immutable output', async () => {
  const database = fakeDatabase(producerSeed());
  const now = new Date('2029-01-01T00:00:00Z');
  const body = producerBody();
  assert.deepEqual(await executeOperation(database, 'register_output_producer', body, now), {
    producer_intent_id: PRODUCER_TASK, status: 'PENDING', idempotent: false,
  });
  await assert.rejects(executeOperation(database, 'register_output_producer', {
    ...body, kwargs_binding: 'e'.repeat(64),
  }, now), (error) => error.code === 'producer_intent_mismatch');
  database.rows.chat_turn_preflights[0].state = 'TERMINAL';
  const resolved = await executeOperation(database, 'resolve_output_producer', {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding,
  }, now);
  assert.equal(resolved.status, 'PENDING');
  assert.equal(resolved.context.recovery_public_key, RECOVERY_KEY);
  const sealed = {
    protocol_version: 1, record_id: PRODUCER_RECORD, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: PRODUCER_EMBED, output_kind: 'embed', output_version: 1,
    chat_key_version: 1, sealed_payload: SEALED_OUTPUT,
    producer_intent_id: PRODUCER_TASK, producer_ordinal: 0,
    producer_task_name: body.task_name, producer_kwargs_binding: body.kwargs_binding,
    content_commitment: 'e'.repeat(64),
  };
  assert.equal((await executeOperation(database, 'create_sealed_output', sealed, now)).state, 'PENDING');
  const replay = await executeOperation(database, 'create_sealed_output', {
    ...sealed, record_id: '018fdddd-dddd-7ddd-8ddd-dddddddddddd',
    sealed_payload: JSON.stringify({ v: 2, epk: b64(32, 8), nonce: b64(12, 9), ciphertext: b64(17, 10) }),
  }, now);
  assert.equal(replay.record_id, PRODUCER_RECORD);
  await assert.rejects(executeOperation(database, 'create_sealed_output', {
    ...sealed, content_commitment: 'f'.repeat(64),
  }, now), (error) => error.code === 'producer_content_mismatch');
  const closeBody = {
    protocol_version: 1, producer_intent_id: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding,
    expected_children: [],
  };
  assert.equal((await executeOperation(database, 'close_output_producer', closeBody, now)).status, 'PENDING');
  assert.equal((await executeOperation(database, 'close_output_producer', closeBody, now)).idempotent, true);
  await assert.rejects(executeOperation(database, 'register_output_producer_child', {
    protocol_version: 1, producer_intent_id: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding,
    subject_id: '018feeee-eeee-7eee-8eee-eeeeeeeeeeee',
    output_kind: 'embed', output_version: 1,
  }, now), (error) => error.code === 'producer_registration_closed');
  database.rows.embeds = [{
    embed_id: PRODUCER_EMBED, hashed_user_id: OWNER, hashed_chat_id: sha256(CHAT_ID),
    encrypted_content: 'encrypted-embed', version_number: 1,
  }];
  database.rows.embed_keys = [
    { hashed_embed_id: sha256(PRODUCER_EMBED), hashed_user_id: OWNER,
      key_type: 'master', encrypted_embed_key: 'wrapped-master' },
    { hashed_embed_id: sha256(PRODUCER_EMBED), hashed_user_id: OWNER,
      key_type: 'chat', hashed_chat_id: sha256(CHAT_ID), encrypted_embed_key: 'wrapped-chat' },
  ];
  await executeOperation(database, 'acknowledge_output_embed', {
    protocol_version: 1, hashed_user_id: OWNER, device_hash: 'device-a',
    record_id: PRODUCER_RECORD, canonical_digest: testing.digest('encrypted-embed'),
  }, now);
  assert.equal(database.rows.chat_recovery_output_producers[0].state, 'COMPLETED');
  assert.equal((await executeOperation(database, 'resolve_output_producer', {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding,
  }, now)).status, 'SEALED');
});

test('child producer binds the child prompt and cannot borrow the parent message identity', async () => {
  const childChatId = '018fdddd-dddd-7ddd-8ddd-dddddddddddd';
  const childTaskId = '018feeee-eeee-7eee-8eee-eeeeeeeeeeee';
  const seed = producerSeed();
  seed.chats.push({ id: childChatId, hashed_user_id: OWNER, encrypted_chat_key: 'child-key' });
  seed.sub_chat_orchestrations = [{
    id: '018f9999-9999-7999-8999-999999999999', root_chat_id: CHAT_ID,
    hashed_user_id: OWNER,
  }];
  seed.sub_chat_orchestration_children = [{
    child_chat_id: childChatId, orchestration_id: seed.sub_chat_orchestrations[0].id,
    inference_task_id: childTaskId, user_message_id: 'child-prompt-1',
  }];
  const database = fakeDatabase(seed);
  const body = producerBody({ target_chat_id: childChatId,
    inference_task_id: childTaskId, primary_message_id: 'child-prompt-1' });
  assert.equal((await executeOperation(database, 'register_output_producer', body)).status, 'PENDING');
  await assert.rejects(executeOperation(fakeDatabase(seed), 'register_output_producer', {
    ...body, primary_message_id: 'user-message-1',
  }), (error) => error.code === 'producer_child_identity_mismatch');
});

test('same-record main-context replay uses keyed content commitment while RUNNING', async () => {
  const database = fakeDatabase(producerSeed());
  const sealed = {
    protocol_version: 1, record_id: PRODUCER_RECORD, hashed_user_id: OWNER,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, turn_id: TURN_ID,
    preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID,
    subject_id: PRODUCER_EMBED, output_kind: 'embed', output_version: 1,
    chat_key_version: 1, sealed_payload: SEALED_OUTPUT,
    content_commitment: 'e'.repeat(64),
  };
  assert.equal((await executeOperation(database, 'create_sealed_output', sealed)).state, 'PENDING');
  const retry = await executeOperation(database, 'create_sealed_output', {
    ...sealed, sealed_payload: JSON.stringify({
      v: 2, epk: b64(32, 8), nonce: b64(12, 9), ciphertext: b64(17, 10),
    }),
  });
  assert.equal(retry.record_id, PRODUCER_RECORD);
  await assert.rejects(executeOperation(database, 'create_sealed_output', {
    ...sealed, content_commitment: 'f'.repeat(64),
  }), (error) => error.code === 'replay_output_mismatch');
  const probe = await executeOperation(database, 'get_replay_output', {
    protocol_version: 1, record_id: PRODUCER_RECORD, hashed_user_id: OWNER,
    preflight_id: PREFLIGHT_ID, root_chat_id: CHAT_ID, target_chat_id: CHAT_ID,
    subject_id: PRODUCER_EMBED, output_kind: 'embed', output_version: 1,
    content_commitment: 'e'.repeat(64),
  });
  assert.equal(probe.sealed_payload, SEALED_OUTPUT);
  database.rows.chat_turn_preflights[0].state = 'TERMINAL';
  await assert.rejects(executeOperation(database, 'get_replay_output', {
    protocol_version: 1, record_id: PRODUCER_RECORD, hashed_user_id: OWNER,
    preflight_id: PREFLIGHT_ID, root_chat_id: CHAT_ID, target_chat_id: CHAT_ID,
    subject_id: PRODUCER_EMBED, output_kind: 'embed', output_version: 1,
    content_commitment: 'e'.repeat(64),
  }), (error) => error.code === 'inference_not_running');
});

test('authenticated direct skill intent waits for canonical encrypted head and wrappers', async () => {
  const actorId = '018f1212-1212-7121-8121-121212121212';
  const actorHash = sha256(actorId);
  const database = fakeDatabase({
    directus_users: [{ id: actorId, status: 'active' }],
    chat_recovery_authorized_direct_skills: [],
  });
  const body = {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: 'apps.social_media.tasks.skill_get-posts',
    kwargs_binding: 'd'.repeat(64), actor_user_id: actorId,
    hashed_user_id: actorHash, hashed_team_id: null,
    target_chat_id: null, primary_message_id: null,
    primary_embed_id: PRODUCER_EMBED,
  };
  assert.equal((await executeOperation(database, 'register_authorized_direct_skill', body)).status,
    'DIRECT_AUTHORIZED');
  const resolved = await executeOperation(database, 'resolve_output_producer', {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding,
  });
  assert.equal(resolved.intent_kind, 'direct_skill');
  assert.equal(resolved.context.target_chat_id, null);
  assert.deepEqual(await executeOperation(database, 'claim_authorized_direct_producer', {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding,
  }), {
    producer_intent_id: PRODUCER_TASK, status: 'RUNNING', claimed: true,
    intent_kind: 'direct_skill',
  });
  assert.equal((await executeOperation(database, 'claim_authorized_direct_producer', {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding,
  })).claimed, false);
  const completion = {
    protocol_version: 1, hashed_user_id: actorHash,
    primary_embed_id: PRODUCER_EMBED, target_chat_id: null,
    canonical_version: 1, intent_kind: 'direct_skill',
  };
  database.rows.embeds = [{
    embed_id: PRODUCER_EMBED, hashed_user_id: actorHash,
    encrypted_content: 'encrypted-head', version_number: 1,
  }];
  assert.deepEqual(await executeOperation(database, 'complete_authorized_direct_by_embed', completion), {
    completed: false, reason_code: 'pending_wrappers',
  });
  database.rows.embed_keys = [{
    hashed_embed_id: sha256(PRODUCER_EMBED), hashed_user_id: actorHash,
    key_type: 'master', encrypted_embed_key: 'wrapped-master',
  }];
  assert.deepEqual(await executeOperation(database, 'complete_authorized_direct_by_embed', completion), {
    completed: true, intent_kind: 'direct_skill',
  });
  assert.equal(database.rows.chat_recovery_authorized_direct_skills[0].state, 'COMPLETED');
  assert.equal((await executeOperation(database, 'resolve_output_producer', {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding,
  })).status, 'COMPLETED');
});

test('standalone direct completion requires exact immutable encrypted asset proof', async () => {
  const actorId = '018f1212-1212-7121-8121-121212121212';
  const actorHash = sha256(actorId);
  const body = {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: 'apps.images.tasks.skill_generate', kwargs_binding: 'd'.repeat(64),
    actor_user_id: actorId, hashed_user_id: actorHash, hashed_team_id: null,
    target_chat_id: null, primary_message_id: null, primary_embed_id: PRODUCER_EMBED,
  };
  const database = fakeDatabase({
    directus_users: [{ id: actorId, status: 'active' }],
    chat_recovery_authorized_direct_skills: [], upload_files: [],
  });
  await executeOperation(database, 'register_authorized_direct_skill', body);
  await executeOperation(database, 'claim_authorized_direct_producer', {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding,
  });
  const completion = {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding,
    asset_id: PRODUCER_EMBED,
  };
  await assert.rejects(
    executeOperation(database, 'complete_authorized_standalone_asset', completion),
    (error) => error.code === 'standalone_asset_proof_missing',
  );
  assert.equal(database.rows.chat_recovery_authorized_direct_skills[0].state, 'RUNNING');
  database.rows.upload_files.push({
    embed_id: PRODUCER_EMBED, user_id: '018f9999-9999-7999-8999-999999999999',
    content_hash: 'e'.repeat(64), file_size_bytes: 12,
    vault_wrapped_aes_key: 'vault-key', aes_nonce: 'nonce',
    files_metadata: { original: { s3_key: 'owner/file.png', size_bytes: 12 } },
  });
  await assert.rejects(
    executeOperation(database, 'complete_authorized_standalone_asset', completion),
    (error) => error.code === 'standalone_asset_proof_missing',
  );
  database.rows.upload_files[0].user_id = actorId;
  database.rows.upload_files[0].files_metadata.original.encryption = 'plaintext';
  await assert.rejects(
    executeOperation(database, 'complete_authorized_standalone_asset', completion),
    (error) => error.code === 'standalone_asset_proof_missing',
  );
  delete database.rows.upload_files[0].files_metadata.original.encryption;
  assert.deepEqual(
    await executeOperation(database, 'complete_authorized_standalone_asset', completion),
    { producer_intent_id: PRODUCER_TASK, status: 'COMPLETED',
      asset_id: PRODUCER_EMBED, content_hash: 'e'.repeat(64), idempotent: false },
  );
  assert.equal(database.rows.chat_recovery_authorized_direct_skills[0].state, 'COMPLETED');
  assert.equal((await executeOperation(database, 'complete_authorized_standalone_asset', completion)).idempotent,
    true);
});

test('Team standalone direct skill requires membership and reconciles only indexed encrypted output', async () => {
  const actorId = '018f1212-1212-7121-8121-121212121212';
  const actorHash = sha256(actorId);
  const seed = {
    directus_users: [{ id: actorId, status: 'active' }],
    teams: [{ hashed_team_id: TEAM_HASH, status: 'active' }],
    team_memberships: [{ hashed_team_id: TEAM_HASH, hashed_user_id: actorHash,
      status: 'active', role: 'member' }],
    chat_recovery_authorized_direct_skills: [],
  };
  const body = {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: 'apps.images.tasks.generate_image', kwargs_binding: 'd'.repeat(64),
    actor_user_id: actorId, hashed_user_id: actorHash, hashed_team_id: TEAM_HASH,
    target_chat_id: null, primary_message_id: null, primary_embed_id: PRODUCER_EMBED,
  };
  const database = fakeDatabase(seed);
  await executeOperation(database, 'register_authorized_direct_skill', body);
  await executeOperation(database, 'claim_authorized_direct_producer', {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding,
  });
  await assert.rejects(executeOperation(database, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: actorHash, scope: 'account',
  }), (error) => error.code === 'pending_team_recovery');
  await assert.rejects(executeOperation(database, 'register_authorized_direct_skill', {
    ...body, task_uuid: '018fdddd-dddd-7ddd-8ddd-dddddddddddd',
  }), (error) => error.code === 'producer_embed_intent_conflict');
  const reconcile = { protocol_version: 1, limit: 100 };
  assert.deepEqual(await executeOperation(database, 'reconcile_authorized_direct_completions', reconcile), {
    scanned: 1, completed: 0, pending: 1, blocked: 0, next_cursor: PRODUCER_TASK,
  });
  database.rows.upload_files = [{
    embed_id: PRODUCER_EMBED, user_id: actorId, content_hash: 'e'.repeat(64), file_size_bytes: 12,
    vault_wrapped_aes_key: 'vault-key', aes_nonce: 'nonce',
    files_metadata: { original: { s3_key: 'owner/team-file.png', size_bytes: 12 } },
  }];
  assert.equal((await executeOperation(database,
    'reconcile_authorized_direct_completions', reconcile)).pending, 1);
  assert.equal((await executeOperation(database, 'complete_authorized_standalone_asset', {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding,
    asset_id: PRODUCER_EMBED,
  })).status, 'COMPLETED');
  assert.equal(database.rows.chat_recovery_authorized_direct_skills[0].state, 'COMPLETED');
  assert.equal((await executeOperation(database, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: actorHash, scope: 'account',
  })).invalidated_direct_skills, 0);
  const revoked = fakeDatabase({ ...seed,
    team_memberships: [{ ...seed.team_memberships[0], status: 'revoked' }],
  });
  await assert.rejects(executeOperation(revoked, 'register_authorized_direct_skill', body),
    (error) => error.code === 'chat_not_found');
});

test('authorized rerender claims once and completes only at the exact next canonical version', async () => {
  const database = fakeDatabase({
    chats: [{ id: CHAT_ID, hashed_user_id: OWNER }],
    embeds: [{ embed_id: PRODUCER_EMBED, hashed_user_id: OWNER,
      hashed_chat_id: sha256(CHAT_ID), encrypted_content: 'source-cipher', version_number: 1 }],
    embed_keys: [
      { hashed_embed_id: sha256(PRODUCER_EMBED), hashed_user_id: OWNER,
        key_type: 'master', encrypted_embed_key: 'wrapped-master' },
      { hashed_embed_id: sha256(PRODUCER_EMBED), hashed_user_id: OWNER,
        key_type: 'chat', hashed_chat_id: sha256(CHAT_ID), encrypted_embed_key: 'wrapped-chat' },
    ],
    chat_recovery_authorized_rerenders: [],
  });
  const body = {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: 'apps.videos.tasks.render_remotion', kwargs_binding: 'd'.repeat(64),
    hashed_user_id: OWNER, target_chat_id: CHAT_ID, primary_embed_id: PRODUCER_EMBED,
    primary_message_id: null, source_version: 1, expected_embed_version: 1,
  };
  assert.equal((await executeOperation(database, 'register_authorized_rerender', body)).status,
    'DIRECT_AUTHORIZED');
  assert.equal((await executeOperation(database, 'resolve_output_producer', {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding,
  })).intent_kind, 'rerender');
  assert.equal((await executeOperation(database, 'claim_authorized_direct_producer', {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding,
  })).claimed, true);
  const completion = {
    protocol_version: 1, hashed_user_id: OWNER,
    primary_embed_id: PRODUCER_EMBED, target_chat_id: CHAT_ID,
    canonical_version: 1, intent_kind: 'rerender',
  };
  assert.equal((await executeOperation(database, 'complete_authorized_direct_by_embed', completion)).completed,
    false);
  database.rows.embeds[0].version_number = 2;
  database.rows.embeds[0].encrypted_content = 'finished-cipher';
  assert.deepEqual(await executeOperation(database, 'complete_authorized_direct_by_embed', {
    ...completion, canonical_version: 2,
  }), { completed: true, intent_kind: 'rerender' });
  assert.equal(database.rows.chat_recovery_authorized_rerenders[0].state, 'COMPLETED');
});

test('epoch-zero saved-chat producer is registered while running and claims once after terminal', async () => {
  // contract-test: storage.recovery.durable-outputs
  const actorId = '018f1212-1212-7121-8121-121212121212';
  const ownerHash = sha256(actorId);
  const identity = sha256(`${actorId}:${CHAT_ID}:user-message-1`);
  const now = new Date('2029-01-01T00:00:00Z');
  const seed = {
    ...protocolSeed({
      active: [identity],
      lifecycle: [lifecycleRecord(identity, 'RUNNING', '2029-01-01T00:15:00Z')],
    }),
    directus_users: [{ id: actorId, status: 'active' }],
    chats: [{ id: CHAT_ID, hashed_user_id: ownerHash, messages_v: 1 }],
    messages: [{ ...userMessage(), hashed_user_id: ownerHash }],
    chat_recovery_legacy_output_producers: [],
  };
  const body = {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: 'apps.images.tasks.generate_image', kwargs_binding: 'd'.repeat(64),
    actor_user_id: actorId, hashed_user_id: ownerHash, legacy_task_identity: identity,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, root_turn_id: null,
    root_user_message_id: 'user-message-1', primary_message_id: 'user-message-1',
    primary_embed_id: PRODUCER_EMBED,
  };
  const database = fakeDatabase(seed);
  assert.equal((await executeOperation(database, 'register_legacy_output_producer', body, now)).status,
    'LEGACY_AUTHORIZED');
  database.rows.chat_recovery_protocol_state[0].active_legacy_tasks = [];
  database.rows.chat_recovery_protocol_state[0].legacy_in_flight = 0;
  database.rows.chat_recovery_protocol_state[0].legacy_task_lifecycle = [
    lifecycleRecord(identity, 'PERSISTED', '2029-01-02T00:00:00Z', true),
  ];
  database.rows.chat_recovery_protocol_state[0].sends_paused = true;
  await assert.rejects(executeOperation(database, 'activate_protocol_epoch', {
    protocol_version: 1, target_epoch: 1,
  }, now), (error) => error.code === 'legacy_output_producers_pending');
  // Simulate a cutover performed by an older coordinator to prove the registered
  // detached task remains identifiable after its root lifecycle becomes terminal.
  database.rows.chat_recovery_protocol_state[0].protocol_epoch = 1;
  const task = { protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: body.task_name, kwargs_binding: body.kwargs_binding };
  await assert.rejects(executeOperation(database, 'resolve_output_producer', {
    ...task, kwargs_binding: 'e'.repeat(64),
  }, now), (error) => error.code === 'producer_intent_not_found');
  assert.equal((await executeOperation(database, 'resolve_output_producer', task)).status,
    'LEGACY_AUTHORIZED');
  assert.equal((await executeOperation(database, 'resolve_output_producer', task,
    new Date('2029-01-09T00:00:00Z'))).reason_code, 'legacy_producer_expired');
  assert.deepEqual(await executeOperation(database, 'claim_authorized_direct_producer', task), {
    producer_intent_id: PRODUCER_TASK, status: 'RUNNING', claimed: true,
    intent_kind: 'legacy_chat',
  });
  assert.deepEqual(await executeOperation(database, 'verify_claimed_output_producer', task, now), {
    producer_intent_id: PRODUCER_TASK, authorized: true, status: 'RUNNING',
    intent_kind: 'legacy_chat',
  });
  assert.equal((await executeOperation(database, 'claim_authorized_direct_producer', task)).claimed, false);
  await assert.rejects(executeOperation(database, 'register_legacy_output_producer', {
    ...body, task_uuid: '018fbbbb-aaaa-7aaa-8aaa-aaaaaaaaaaaa',
  }, now),
    (error) => error.code === 'legacy_admission_not_running');
  await executeOperation(database, 'release_legacy_inference', {
    protocol_version: 1, task_identity: identity,
  });
  assert.equal(database.rows.chat_recovery_legacy_output_producers[0].state, 'INVALIDATED');
  assert.equal((await executeOperation(database, 'verify_claimed_output_producer', task, now)).authorized,
    false);
});

test('volatile worker rechecks active actor and deletion fence without persisting intent', async () => {
  // contract-test: storage.recovery.durable-outputs
  const actorId = '018f1212-1212-7121-8121-121212121212';
  const ownerHash = sha256(actorId);
  const database = fakeDatabase({
    directus_users: [{ id: actorId, status: 'active' }],
    chats: [{ id: CHAT_ID, hashed_user_id: ownerHash }],
  });
  const body = { protocol_version: 1, actor_user_id: actorId,
    hashed_user_id: ownerHash, target_chat_id: CHAT_ID };
  assert.deepEqual(await executeOperation(database, 'verify_volatile_output_actor', body),
    { authorized: true });
  database.rows.chat_recovery_chat_deletion_fences = [{
    id: CHAT_ID, chat_id: CHAT_ID, hashed_user_id: ownerHash,
  }];
  await assert.rejects(executeOperation(database, 'verify_volatile_output_actor', body),
    (error) => error.code === 'producer_chat_deleted');
  assert.deepEqual(database.rows.chat_recovery_legacy_output_producers ?? [], []);
});

test('legacy child intent binds orchestration prompt and root turn', async () => {
  // contract-test: storage.recovery.durable-outputs
  const actorId = '018f1212-1212-7121-8121-121212121212';
  const ownerHash = sha256(actorId);
  const childId = '018fdddd-dddd-7ddd-8ddd-dddddddddddd';
  const identity = sha256(`${actorId}:${CHAT_ID}:user-message-1`);
  const seed = {
    ...protocolSeed({ active: [identity],
      lifecycle: [lifecycleRecord(identity, 'RUNNING', '2029-01-01T00:15:00Z')] }),
    directus_users: [{ id: actorId, status: 'active' }],
    chats: [{ id: CHAT_ID, hashed_user_id: ownerHash },
      { id: childId, hashed_user_id: ownerHash }],
    messages: [{ ...userMessage(), hashed_user_id: ownerHash }],
    sub_chat_orchestrations: [{
      id: '018f9999-9999-7999-8999-999999999999',
      root_chat_id: CHAT_ID, root_turn_id: TURN_ID, hashed_user_id: ownerHash,
    }],
    sub_chat_orchestration_children: [{
      child_chat_id: childId,
      orchestration_id: '018f9999-9999-7999-8999-999999999999',
      user_message_id: 'child-prompt-1',
    }],
  };
  const body = {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: 'apps.images.tasks.generate_image', kwargs_binding: 'd'.repeat(64),
    actor_user_id: actorId, hashed_user_id: ownerHash, legacy_task_identity: identity,
    root_chat_id: CHAT_ID, target_chat_id: childId, root_turn_id: TURN_ID,
    root_user_message_id: 'user-message-1', primary_message_id: 'child-prompt-1',
    primary_embed_id: PRODUCER_EMBED,
  };
  assert.equal((await executeOperation(fakeDatabase(seed), 'register_legacy_output_producer',
    body, new Date('2029-01-01T00:00:00Z'))).status, 'LEGACY_AUTHORIZED');
  await assert.rejects(executeOperation(fakeDatabase(seed), 'register_legacy_output_producer',
    { ...body, primary_message_id: 'user-message-1' }, new Date('2029-01-01T00:00:00Z')),
  (error) => error.code === 'legacy_child_identity_mismatch');
});

test('epoch-zero queued batch freezes ordered scope and claims provider execution once', async () => {
  // contract-test: storage.recovery.durable-outputs
  const actorId = '018f1212-1212-7121-8121-121212121212';
  const ownerHash = sha256(actorId);
  const taskIdentity = sha256(`${actorId}:${CHAT_ID}:queued-1`);
  const now = new Date('2029-01-01T00:00:00Z');
  const database = fakeDatabase({
    ...protocolSeed(),
    directus_users: [{ id: actorId, status: 'active' }],
    chats: [{ id: CHAT_ID, hashed_user_id: ownerHash }],
    messages: [], // queued encrypted messages may not yet be canonical
  });
  const body = {
    protocol_version: 1, actor_user_id: actorId, hashed_user_id: ownerHash,
    chat_id: CHAT_ID, first_message_id: 'queued-1', hashed_team_id: null,
    task_identity: taskIdentity, celery_task_id: PRODUCER_TASK,
    members: [
      { message_id: 'queued-1', chat_id: CHAT_ID, hashed_user_id: ownerHash,
        payload_commitment: 'a'.repeat(64) },
      { message_id: 'queued-2', chat_id: CHAT_ID, hashed_user_id: ownerHash,
        payload_commitment: 'b'.repeat(64) },
    ],
    batch_commitment: 'c'.repeat(64),
  };
  assert.deepEqual(await executeOperation(database, 'prepare_legacy_batch', body, now), {
    task_identity: taskIdentity, status: 'PREPARED', execution_claimed: false, idempotent: false,
  });
  assert.equal((await executeOperation(database, 'prepare_legacy_batch', body, now)).idempotent, true);
  await assert.rejects(executeOperation(database, 'prepare_legacy_batch', {
    ...body, batch_commitment: 'd'.repeat(64),
  }, now), (error) => error.code === 'legacy_batch_mismatch');
  await assert.rejects(executeOperation(database, 'prepare_legacy_batch', {
    ...body, members: [body.members[0], { ...body.members[1],
      hashed_user_id: 'f'.repeat(64) }],
  }, now), (error) => error.code === 'legacy_batch_scope_mismatch');
  database.rows.messages.push({
    id: OUTBOX_ID, client_message_id: PRODUCER_TASK,
    chat_id: CHAT_ID, hashed_user_id: ownerHash, role: 'assistant',
    encrypted_content: 'prior-client-ciphertext',
  });
  assert.equal((await executeOperation(database, 'claim_legacy_batch', body, now)).claimed, false);
  database.rows.messages = [];
  assert.equal((await executeOperation(database, 'claim_legacy_batch', body, now)).claimed, true);
  assert.equal((await executeOperation(database, 'claim_legacy_batch', body, now)).claimed, false);
  assert.equal((await executeOperation(database, 'prepare_legacy_batch', body, now))
    .execution_claimed, true);
  const release = await executeOperation(database, 'release_legacy_inference', {
    protocol_version: 1, task_identity: taskIdentity,
  }, now);
  assert.equal(release.held, true);
  assert.equal(database.rows.chat_recovery_protocol_state[0].legacy_in_flight, 1);
  assert.equal(database.rows.chat_recovery_protocol_state[0]
    .legacy_task_lifecycle[0].admission.batch_commitment, body.batch_commitment);
  const deleted = await executeOperation(database, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: ownerHash, scope: 'chat', chat_id: CHAT_ID,
  }, now);
  assert.equal(deleted.invalidated_legacy_batches, 1);
  assert.equal(database.rows.chat_recovery_legacy_batch_claims[0].state, 'INVALIDATED');
  await assert.rejects(executeOperation(database, 'claim_legacy_batch', body, now),
    (error) => error.code === 'producer_chat_deleted');
});

test('epoch-zero batch claim rejects deletion, plain admission upgrade, and cutover', async () => {
  // contract-test: storage.recovery.durable-outputs
  const actorId = '018f1212-1212-7121-8121-121212121212';
  const ownerHash = sha256(actorId);
  const taskIdentity = sha256(`${actorId}:${CHAT_ID}:queued-1`);
  const now = new Date('2029-01-01T00:00:00Z');
  const seed = {
    ...protocolSeed(),
    directus_users: [{ id: actorId, status: 'active' }],
    chats: [{ id: CHAT_ID, hashed_user_id: ownerHash }],
  };
  const body = {
    protocol_version: 1, actor_user_id: actorId, hashed_user_id: ownerHash,
    chat_id: CHAT_ID, first_message_id: 'queued-1', hashed_team_id: null,
    task_identity: taskIdentity, celery_task_id: PRODUCER_TASK,
    members: [{ message_id: 'queued-1', chat_id: CHAT_ID, hashed_user_id: ownerHash,
      payload_commitment: 'a'.repeat(64) }],
    batch_commitment: 'c'.repeat(64),
  };
  const plain = fakeDatabase(seed);
  await executeOperation(plain, 'admit_legacy_inference', {
    protocol_version: 1, task_identity: taskIdentity,
  }, now);
  await assert.rejects(executeOperation(plain, 'prepare_legacy_batch', body, now),
    (error) => error.code === 'legacy_batch_mismatch');
  const deleting = fakeDatabase(seed);
  deleting.rows.chat_recovery_chat_deletion_fences = [{
    id: CHAT_ID, chat_id: CHAT_ID, hashed_user_id: ownerHash,
  }];
  await assert.rejects(executeOperation(deleting, 'prepare_legacy_batch', body, now),
    (error) => error.code === 'producer_chat_deleted');
  const cutover = fakeDatabase(protocolSeed({ epoch: 1, paused: true }));
  cutover.rows.directus_users = seed.directus_users;
  cutover.rows.chats = seed.chats;
  await assert.rejects(executeOperation(cutover, 'prepare_legacy_batch', body, now),
    (error) => error.code === 'client_update_required');
});

test('authenticated ordinary legacy admission authorizes delayed canonical user message', async () => {
  // contract-test: storage.recovery.durable-outputs
  const actorId = '018f1212-1212-7121-8121-121212121212';
  const ownerHash = sha256(actorId);
  const taskIdentity = sha256(`${actorId}:${CHAT_ID}:user-message-1`);
  const now = new Date('2029-01-01T00:00:00Z');
  const database = fakeDatabase({
    ...protocolSeed(), directus_users: [{ id: actorId, status: 'active' }],
    chats: [{ id: CHAT_ID, hashed_user_id: ownerHash }], messages: [],
  });
  const admission = {
    protocol_version: 1, task_identity: taskIdentity, actor_user_id: actorId,
    hashed_user_id: ownerHash, chat_id: CHAT_ID,
    first_message_id: 'user-message-1', hashed_team_id: null,
  };
  assert.equal((await executeOperation(database, 'admit_legacy_inference', admission, now))
    .admission_recorded, true);
  const invocation = { ...admission, broker_task_id: taskIdentity,
    dispatch_binding: 'f'.repeat(64) };
  assert.equal((await executeOperation(database, 'bind_ordinary_legacy_dispatch',
    invocation, now)).enqueue_allowed, true);
  assert.equal((await executeOperation(database, 'bind_ordinary_legacy_dispatch',
    invocation, now)).idempotent, true);
  await assert.rejects(executeOperation(database, 'bind_ordinary_legacy_dispatch', {
    ...invocation, dispatch_binding: 'e'.repeat(64),
  }, now), (error) => error.code === 'legacy_dispatch_mismatch');
  await assert.rejects(executeOperation(database, 'claim_legacy_inference_start', {
    ...invocation, broker_task_id: 'other-task',
  }, now), (error) => error.code === 'legacy_dispatch_mismatch');
  database.rows.messages.push({
    id: OUTBOX_ID, client_message_id: taskIdentity,
    chat_id: CHAT_ID, hashed_user_id: ownerHash, role: 'assistant',
    encrypted_content: 'prior-client-ciphertext',
  });
  assert.equal((await executeOperation(database, 'bind_ordinary_legacy_dispatch',
    invocation, now)).enqueue_allowed, false);
  assert.equal((await executeOperation(database, 'claim_legacy_inference_start',
    invocation, now)).claimed, false);
  database.rows.messages = [];
  assert.deepEqual(await executeOperation(database, 'claim_legacy_inference_start',
    invocation, now), { authorized: true, claimed: true,
    task_identity: taskIdentity, status: 'RUNNING' });
  assert.deepEqual(await executeOperation(database, 'claim_legacy_inference_start',
    invocation, now), { authorized: false, claimed: false,
    task_identity: taskIdentity, status: 'CLAIMED' });
  assert.equal((await executeOperation(database, 'bind_ordinary_legacy_dispatch',
    invocation, now)).enqueue_allowed, false);
  await assert.rejects(executeOperation(database, 'admit_legacy_inference', {
    ...admission, first_message_id: 'other',
  }, now), (error) => error.code === 'legacy_admission_identity_mismatch');
  assert.equal((await executeOperation(database, 'register_legacy_output_producer', {
    protocol_version: 1, task_uuid: PRODUCER_TASK,
    task_name: 'apps.images.tasks.generate_image', kwargs_binding: 'd'.repeat(64),
    actor_user_id: actorId, hashed_user_id: ownerHash, legacy_task_identity: taskIdentity,
    root_chat_id: CHAT_ID, target_chat_id: CHAT_ID, root_turn_id: null,
    root_user_message_id: 'user-message-1', primary_message_id: 'user-message-1',
    primary_embed_id: PRODUCER_EMBED,
  }, now)).status, 'LEGACY_AUTHORIZED');
  database.rows.chat_recovery_protocol_state[0].legacy_task_lifecycle[0].expires_at =
    '2028-01-01T00:00:00Z';
  const later = new Date('2029-01-02T00:00:00Z');
  assert.equal((await executeOperation(database, 'admit_legacy_inference', admission, later))
    .admitted, false);
  assert.equal((await executeOperation(database, 'claim_legacy_inference_start',
    invocation, later)).claimed, false);
  assert.equal(database.rows.chat_recovery_legacy_batch_claims[0].state, 'CLAIMED');
});

test('durable batch claim survives lifecycle pruning and never repeats provider execution', async () => {
  // contract-test: storage.recovery.durable-outputs
  const actorId = '018f1212-1212-7121-8121-121212121212';
  const ownerHash = sha256(actorId);
  const taskIdentity = sha256(`${actorId}:${CHAT_ID}:queued-1`);
  const now = new Date('2029-01-01T00:00:00Z');
  const database = fakeDatabase({
    ...protocolSeed(), directus_users: [{ id: actorId, status: 'active' }],
    chats: [{ id: CHAT_ID, hashed_user_id: ownerHash }],
  });
  const body = {
    protocol_version: 1, actor_user_id: actorId, hashed_user_id: ownerHash,
    chat_id: CHAT_ID, first_message_id: 'queued-1', hashed_team_id: null,
    task_identity: taskIdentity, celery_task_id: PRODUCER_TASK,
    members: [{ message_id: 'queued-1', chat_id: CHAT_ID, hashed_user_id: ownerHash,
      payload_commitment: 'a'.repeat(64) }], batch_commitment: 'c'.repeat(64),
  };
  await executeOperation(database, 'prepare_legacy_batch', body, now);
  assert.equal((await executeOperation(database, 'claim_legacy_batch', body, now)).claimed, true);
  database.rows.chat_recovery_protocol_state[0].legacy_task_lifecycle[0].expires_at =
    '2028-01-01T00:00:00Z';
  const later = new Date('2029-01-02T00:00:00Z');
  assert.equal((await executeOperation(database, 'prepare_legacy_batch', body, later))
    .execution_claimed, true);
  assert.equal(database.rows.chat_recovery_protocol_state[0].legacy_in_flight, 0);
  assert.equal((await executeOperation(database, 'claim_legacy_batch', body, later)).claimed, false);
  await assert.rejects(executeOperation(database, 'admit_legacy_inference', {
    protocol_version: 1, task_identity: taskIdentity, actor_user_id: actorId,
    hashed_user_id: ownerHash, chat_id: CHAT_ID,
    first_message_id: 'queued-1', hashed_team_id: null,
  }, later), (error) => error.code === 'legacy_task_identity_reserved');
  await assert.rejects(executeOperation(database, 'prepare_legacy_batch', {
    ...body, batch_commitment: 'd'.repeat(64),
  }, later), (error) => error.code === 'legacy_batch_mismatch');
  database.rows.chat_recovery_protocol_state[0].sends_paused = true;
  await assert.rejects(executeOperation(database, 'activate_protocol_epoch', {
    protocol_version: 1, target_epoch: 1,
  }, later), (error) => error.code === 'legacy_batches_pending');
  assert.equal(database.rows.chat_recovery_legacy_batch_claims[0].state, 'CLAIMED');
});

test('batch cutover requires worker completion and canonical persistence together', async () => {
  // contract-test: storage.recovery.durable-outputs
  const actorId = '018f1212-1212-7121-8121-121212121212';
  const ownerHash = sha256(actorId);
  const taskIdentity = sha256(`${actorId}:${CHAT_ID}:queued-1`);
  const now = new Date('2029-01-01T00:00:00Z');
  const database = fakeDatabase({
    ...protocolSeed(), directus_users: [{ id: actorId, status: 'active' }],
    chats: [{ id: CHAT_ID, hashed_user_id: ownerHash }],
  });
  const body = {
    protocol_version: 1, actor_user_id: actorId, hashed_user_id: ownerHash,
    chat_id: CHAT_ID, first_message_id: 'queued-1', hashed_team_id: null,
    task_identity: taskIdentity, celery_task_id: PRODUCER_TASK,
    members: [{ message_id: 'queued-1', chat_id: CHAT_ID, hashed_user_id: ownerHash,
      payload_commitment: 'a'.repeat(64) }], batch_commitment: 'c'.repeat(64),
  };
  await executeOperation(database, 'prepare_legacy_batch', body, now);
  await executeOperation(database, 'claim_legacy_batch', body, now);
  await executeOperation(database, 'mark_legacy_inference_completed', {
    protocol_version: 1, task_identity: taskIdentity,
  }, now);
  assert.equal(database.rows.chat_recovery_legacy_batch_claims[0].state, 'CLAIMED');
  assert.equal((await executeOperation(database, 'acknowledge_legacy_persistence', {
    protocol_version: 1, task_identity: PRODUCER_TASK,
  }, now)).output_receipt_required, true);
  database.rows.messages = [{
    id: OUTBOX_ID, client_message_id: PRODUCER_TASK,
    chat_id: CHAT_ID, hashed_user_id: ownerHash,
    role: 'assistant', encrypted_content: 'sealed-client-ciphertext',
  }];
  assert.notEqual(database.rows.messages[0].id, database.rows.messages[0].client_message_id);
  await assert.rejects(executeOperation(database, 'acknowledge_legacy_persistence', {
    protocol_version: 1, task_identity: PRODUCER_TASK,
    assistant_message_id: PRODUCER_TASK, chat_id: CHAT_ID,
    hashed_user_id: ownerHash, ciphertext_digest: sha256('other-ciphertext'),
  }, now), (error) => error.code === 'legacy_output_receipt_mismatch');
  await executeOperation(database, 'acknowledge_legacy_persistence', {
    protocol_version: 1, task_identity: PRODUCER_TASK,
    assistant_message_id: PRODUCER_TASK, chat_id: CHAT_ID,
    hashed_user_id: ownerHash, ciphertext_digest: sha256('sealed-client-ciphertext'),
  }, now);
  const duplicateReceipt = await executeOperation(database, 'acknowledge_legacy_persistence', {
    protocol_version: 1, task_identity: PRODUCER_TASK,
    assistant_message_id: PRODUCER_TASK, chat_id: CHAT_ID,
    hashed_user_id: ownerHash, ciphertext_digest: sha256('sealed-client-ciphertext'),
  }, now);
  assert.equal(duplicateReceipt.acknowledged, true);
  assert.equal(duplicateReceipt.output_receipt_verified, true);
  assert.equal(database.rows.chat_recovery_legacy_batch_claims[0].state, 'COMPLETED');
  database.rows.chat_recovery_protocol_state[0].sends_paused = true;
  assert.equal((await executeOperation(database, 'activate_protocol_epoch', {
    protocol_version: 1, target_epoch: 1,
  }, now)).activated, true);
});
