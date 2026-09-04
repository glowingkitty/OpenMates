/* Contract tests for the internal sub-chat orchestration boundary. */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import test from 'node:test';

import { isAuthorized } from '../src/index.js';
import {
  executeOperation,
  SubChatOrchestrationError,
  testing,
} from '../src/operations.js';

const CHILD_ID = '11111111-1111-4111-8111-111111111111';
const USER_ID = '22222222-2222-4222-8222-222222222222';
const OWNER = 'a'.repeat(64);
const OUTBOX_ID = '33333333-3333-4333-8333-333333333333';

function fakeDatabase(seed) {
  const rows = structuredClone(seed);
  const client = (table) => {
    const predicates = [];
    const matching = () => (rows[table] ?? []).filter(
      (row) => predicates.every((predicate) => predicate(row)),
    );
    const query = {
      where(values) {
        predicates.push((row) => Object.entries(values).every(([key, value]) => row[key] === value));
        return query;
      },
      forUpdate() { return query; },
      async first() { return matching()[0]; },
      async insert(value) {
        rows[table] ??= [];
        rows[table].push(structuredClone(value));
        return 1;
      },
      async update(values) {
        const found = matching();
        found.forEach((row) => Object.assign(row, structuredClone(values)));
        return found.length;
      },
    };
    return query;
  };
  client.rows = rows;
  client.transaction = async (callback) => callback(client);
  return client;
}

test('internal endpoint authentication fails closed', () => {
  assert.equal(isAuthorized({}, 'secret'), false);
  assert.equal(isAuthorized({ 'x-internal-service-token': 'secret' }, ''), false);
  assert.equal(isAuthorized({ 'x-internal-service-token': 'wrong' }, 'secret'), false);
  assert.equal(isAuthorized({ 'x-internal-service-token': 'secret' }, 'secret'), true);
});

test('child preparation rejects content-bearing fields', () => {
  assert.throws(
    () => testing.validatedChildren([{
      child_chat_id: CHILD_ID,
      user_message_id: 'message-1',
      dispatch_token: 'dispatch-token',
      prompt: 'private prompt',
    }]),
    (error) => error instanceof SubChatOrchestrationError
      && error.code === 'private_child_field_forbidden',
  );
});

test('child preparation accepts identifiers and hashes dispatch tokens', () => {
  const [child] = testing.validatedChildren([{
    child_chat_id: CHILD_ID,
    user_message_id: 'message-1',
    dispatch_token: 'dispatch-token',
    budget_limit: 500,
  }]);

  assert.equal(child.child_chat_id, CHILD_ID);
  assert.equal(testing.tokenHash(child.dispatch_token).length, 64);
});

test('protocol version and operation allow-list fail closed', async () => {
  await assert.rejects(
    executeOperation({}, 'missing', { protocol_version: 1 }),
    (error) => error instanceof SubChatOrchestrationError
      && error.code === 'unsupported_operation',
  );
  await assert.rejects(
    executeOperation({ raw: async () => ({}) }, 'health_check', { protocol_version: 2 }),
    (error) => error instanceof SubChatOrchestrationError
      && error.code === 'client_update_required',
  );
});

test('operation reservations include spent and concurrent reserved credits', () => {
  const root = { spent_credits: 600, reserved_credits: 900, credit_limit: 2_000 };

  assert.equal(testing.operationReservationFits(root, 500), true);
  assert.equal(testing.operationReservationFits(root, 501), false);
});

// contract-test: direct surface=rest_api assertions=billing.credits.retryable-completion-safe
test('pending settlement creation is idempotent for one immutable charge identity', async () => {
  const request = {
    protocol_version: 1,
    charge_id: 'chat:turn-1:ask:final',
    user_id: USER_ID,
    hashed_user_id: OWNER,
    vault_key_id: 'vault-key',
    encrypted_settlement_payload: 'ciphertext',
    settlement_payload_hash: 'b'.repeat(64),
    retryable_error_code: 'stale_credit_balance',
  };
  const database = fakeDatabase({ billing_charge_identities: [], billing_settlement_outbox: [] });

  const first = await executeOperation(database, 'create_or_reuse_pending_settlement', request);
  const replay = await executeOperation(database, 'create_or_reuse_pending_settlement', {
    ...request,
    encrypted_settlement_payload: 'different-vault-ciphertext-for-the-same-plaintext',
  });

  assert.equal(first.charge_id, request.charge_id);
  assert.equal(first.state, 'pending');
  assert.equal(replay.idempotent, true);
  assert.equal(replay.outbox_id, first.outbox_id);
  assert.equal(replay.encrypted_settlement_payload, request.encrypted_settlement_payload);
});

// contract-test: direct surface=rest_api assertions=billing.credits.idempotent-charge,billing.credits.retryable-completion-safe
test('pending settlement replay returns a committed charge without another usage mutation', async () => {
  const chargeId = 'chat:turn-1:ask:final';
  const database = fakeDatabase({
    billing_charge_identities: [{
      charge_id: chargeId, hashed_user_id: OWNER, charged_credits: 8,
      encrypted_balance_after: 'after', usage_id: CHILD_ID,
    }],
    billing_settlement_outbox: [{
      id: OUTBOX_ID, charge_id: chargeId, user_id: USER_ID,
      hashed_user_id: OWNER, vault_key_id: 'vault-key',
      encrypted_settlement_payload: 'ciphertext', state: 'retry_scheduled',
      attempts: 1, retryable_error_code: 'stale_credit_balance',
    }],
  });
  const result = await executeOperation(database, 'replay_pending_settlement', {
    protocol_version: 1,
    outbox_id: OUTBOX_ID,
    charge_id: chargeId,
    hashed_user_id: OWNER,
  });

  assert.deepEqual(result, {
    charge_id: 'chat:turn-1:ask:final',
    state: 'committed',
    idempotent: true,
    duplicate_usage_created: false,
  });
});

// contract-test: direct surface=rest_api assertions=billing.credits.retryable-completion-safe
test('exhausted settlement retries transition to observable manual review', async () => {
  const chargeId = 'chat:turn-1:ask:final';
  const database = fakeDatabase({
    billing_settlement_outbox: [{
      id: OUTBOX_ID, charge_id: chargeId, user_id: USER_ID,
      hashed_user_id: OWNER, vault_key_id: 'vault-key',
      encrypted_settlement_payload: 'ciphertext', state: 'retry_scheduled', attempts: 2,
    }],
  });
  const result = await executeOperation(database, 'transition_pending_settlement_to_manual_review', {
    protocol_version: 1,
    outbox_id: OUTBOX_ID,
    charge_id: chargeId,
    hashed_user_id: OWNER,
    attempts: 3,
    retryable_error_code: 'stale_credit_balance',
  });

  assert.deepEqual(result, {
    state: 'manual_review',
    alert_required: true,
  });
});

// contract-test: direct surface=rest_api assertions=billing.credits.idempotent-charge
test('personal refunds use encrypted balance CAS under the subject mutation boundary', async () => {
  const database = fakeDatabase({
    directus_users: [{ id: USER_ID, encrypted_credit_balance: 'before' }],
    billing_refund_identities: [],
  });
  const request = {
    protocol_version: 1,
    refund_id: 'pdf:embed-1:process:refund',
    user_id: USER_ID,
    hashed_user_id: OWNER,
    app_id: 'pdf',
    skill_id: 'process',
    credits_to_refund: 8,
    expected_encrypted_balance: 'before',
    new_encrypted_balance: 'after',
  };

  const result = await executeOperation(database, 'commit_personal_refund', request);

  assert.equal(result.state, 'committed');
  assert.equal(database.rows.directus_users[0].encrypted_credit_balance, 'after');
  const replay = await executeOperation(database, 'commit_personal_refund', request);
  assert.equal(replay.idempotent, true);
  assert.equal(database.rows.directus_users[0].encrypted_credit_balance, 'after');
  assert.equal(database.rows.billing_refund_identities.length, 1);
});
