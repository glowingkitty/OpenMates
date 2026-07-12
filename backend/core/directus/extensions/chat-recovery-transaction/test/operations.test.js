/* Focused security and validation tests for the recovery extension. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isAuthorized } from '../src/index.js';
import { operations, ProtocolError, executeOperation, testing } from '../src/operations.js';

const b64 = (length, fill) => Buffer.alloc(length, fill).toString('base64url');
const TASK_ID = '018f2222-2222-7222-8222-222222222222';
const OUTBOX_ID = '018f3333-3333-7333-8333-333333333333';

function fakeDatabase(seed) {
  const rows = structuredClone(seed);
  let transactions = 0;
  const database = {
    rows,
    get transactions() { return transactions; },
    async transaction(callback) {
      transactions += 1;
      const trx = (table) => {
        let filters = {};
        const query = {
          where(values) { filters = { ...filters, ...values }; return query; },
          forUpdate() { return query; },
          async first() { return rows[table]?.find((row) => Object.entries(filters).every(([key, value]) => row[key] === value)); },
          async update(values) {
            const matching = (rows[table] ?? []).filter((row) => Object.entries(filters).every(([key, value]) => row[key] === value));
            for (const row of matching) Object.assign(row, values);
            return matching.length;
          },
        };
        return query;
      };
      trx.raw = (value) => value;
      return callback(trx);
    },
  };
  return database;
}

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
  for (const operation of ['claim_inference', 'mark_outbox_dispatched', 'mark_inference_failed', 'list_available_jobs']) {
    assert.equal(typeof operations[operation], 'function');
  }
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
