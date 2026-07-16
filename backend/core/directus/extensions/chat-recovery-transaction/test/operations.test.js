/* Focused security and validation tests for the recovery extension. */
import assert from 'node:assert/strict';
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
const RECOVERY_KEY = b64(32, 7);
const COMMITMENT = 'b'.repeat(64);
const SEALED_PAYLOAD = JSON.stringify({ v: 1, epk: b64(32, 1), nonce: b64(12, 2), ciphertext: b64(17, 3) });

function fakeDatabase(seed, injectedFailure = null) {
  const rows = structuredClone(seed);
  let transactions = 0;
  let transactionTail = Promise.resolve();
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
        whereNull(field) { predicates.push((row) => row[field] == null); return query; },
        whereIn(field, values) { predicates.push((row) => values.includes(row[field])); return query; },
        forUpdate() { return query; },
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

test('prepare_preflight atomically writes chat, user message, and preflight', async () => {
  const database = fakeDatabase({ chats: [], messages: [], chat_turn_preflights: [] });
  const result = await executeOperation(database, 'prepare_preflight', prepareBody(), new Date('2029-01-01T00:00:00Z'));

  assert.equal(result.state, 'PREPARED');
  assert.equal(result.committed_messages_v, 1);
  assert.equal(database.rows.chats.length, 1);
  assert.equal(database.rows.chats[0].messages_v, 1);
  assert.equal(database.rows.chats[0].is_private, true);
  assert.equal(database.rows.messages.length, 1);
  assert.equal(database.rows.messages[0].id, 'user-message-1');
  assert.equal(database.rows.messages[0].client_message_id, 'user-message-1');
  assert.equal(database.rows.chat_turn_preflights.length, 1);
  assert.equal(database.rows.chat_turn_preflights[0].state, 'PREPARED');
});

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
  assert.equal(database.rows.messages[1].id, 'assistant-message-1');
  assert.equal(database.rows.messages[1].client_message_id, 'assistant-message-1');
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

test('cleanup_expired removes seven-day jobs and 24-hour terminal tombstones at the boundary', async () => {
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

  assert.equal(result.expired_jobs, 1);
  assert.equal(result.expired_tombstones, 1);
  assert.deepEqual(database.rows.chat_completion_recovery_jobs.map((row) => row.id), ['018faaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa']);
});

test('chat deletion invalidates recovery state and rejects a late sealed job', async () => {
  const seed = leasedSeed();
  seed.chat_turn_preflights[0].inference_task_id = TASK_ID;
  seed.chat_turn_preflights[0].chat_key_version = 1;
  seed.chat_inference_outbox.push({ id: OUTBOX_ID, hashed_user_id: OWNER, chat_id: CHAT_ID });
  const database = fakeDatabase(seed);
  const invalidated = await executeOperation(database, 'invalidate_deletion', {
    protocol_version: 1, hashed_user_id: OWNER, scope: 'chat', chat_id: CHAT_ID,
  }, new Date('2029-01-01T00:00:00Z'));

  assert.deepEqual(invalidated, { deleted_preflights: 1, deleted_jobs: 1, deleted_outbox: 1 });
  await assert.rejects(
    executeOperation(database, 'create_sealed_job', {
      protocol_version: 1, job_id: JOB_ID, hashed_user_id: OWNER, chat_id: CHAT_ID, turn_id: TURN_ID,
      preflight_id: PREFLIGHT_ID, inference_task_id: TASK_ID, assistant_message_id: 'assistant-message-1',
      chat_key_version: 1, sealed_payload: SEALED_PAYLOAD,
    }, new Date('2029-01-01T00:00:01Z')),
    (error) => error instanceof ProtocolError && error.code === 'inference_not_running',
  );
});
