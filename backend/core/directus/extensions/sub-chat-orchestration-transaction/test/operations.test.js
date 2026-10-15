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
      then(resolve, reject) { return Promise.resolve(matching()).then(resolve, reject); },
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
  client.raw = async () => ({ rows: [] });
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


const RESEARCH_ROOT = '44444444-4444-4444-8444-444444444444';
const RESEARCH_BATCH = '55555555-5555-4555-8555-555555555555';
const RESEARCH_CHAT = '66666666-6666-4666-8666-666666666666';
const RESEARCH_TURN = '77777777-7777-4777-8777-777777777777';
const RESEARCH_IDS = [CHILD_ID, USER_ID, OUTBOX_ID];
function researchDatabase(stage = 'research', state = 'completed') {
  return fakeDatabase({
    sub_chat_orchestrations: [{ id: RESEARCH_ROOT, hashed_user_id: OWNER, root_chat_id: RESEARCH_CHAT,
      root_turn_id: RESEARCH_TURN, research_stage: stage, research_batch_id: RESEARCH_BATCH,
      descendant_count: 3, descendant_limit: 3, max_depth: 2, credit_limit: 2000,
      reserved_credits: 0, spent_credits: 0, version: 1, status: 'active', expires_at: '2099-01-01' }],
    sub_chat_orchestration_batches: [{ id: RESEARCH_BATCH, orchestration_id: RESEARCH_ROOT,
      parent_chat_id: RESEARCH_CHAT, parent_depth: 0, child_count: 3, terminal_count: 3,
      continuation_claimed: false }],
    sub_chat_orchestration_children: RESEARCH_IDS.map((id) => ({
      id, child_chat_id: id, orchestration_id: RESEARCH_ROOT, batch_id: RESEARCH_BATCH, state,
    })), chats: [],
  });
}
const researchClaim = { protocol_version: 1, orchestration_id: RESEARCH_ROOT, hashed_user_id: OWNER, batch_id: RESEARCH_BATCH };
function verifierPrepare(claim) {
  return { ...researchClaim, batch_id: claim.verifier_batch_id, research_batch_id: RESEARCH_BATCH,
    continuation_task_id: claim.continuation_task_id, parent_chat_id: RESEARCH_CHAT,
    parent_depth: 0, is_continuation: true, children: [{ child_chat_id: claim.verifier_child_id,
      user_message_id: claim.verifier_child_id, dispatch_token: 'server-verifier-token' }] };
}

// contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
test('three successful research children release one parent synthesis with no verifier batch', async () => {
  const db = researchDatabase();
  const first = await executeOperation(db, 'claim_parent_continuation', researchClaim);
  assert.equal(first.research_stage, 'synthesis');
  assert.equal(first.dispatch_required, true);
  assert.equal(first.verifier_child_id, undefined);
  assert.equal(first.verifier_batch_id, null);
  await assert.rejects(executeOperation(db, 'prepare_batch', verifierPrepare({ ...first,
    verifier_batch_id: CHILD_ID, verifier_child_id: USER_ID })),
    (error) => error.code === 'verification_spawn_forbidden');
  await executeOperation(db, 'mark_parent_continuation_dispatched', {
    ...researchClaim, continuation_task_id: first.continuation_task_id,
  });
  const replay = await executeOperation(db, 'claim_parent_continuation', researchClaim);
  assert.equal(replay.continuation_task_id, first.continuation_task_id);
  assert.equal(replay.dispatch_required, false);
  assert.equal(db.rows.sub_chat_orchestration_batches.length, 1);
  assert.equal(db.rows.sub_chat_orchestration_children.length, 3);
  assert.equal(db.rows.sub_chat_orchestrations[0].descendant_count, 3);
  assert.equal(db.rows.sub_chat_orchestrations[0].credit_limit, 2000);
  assert.equal(db.rows.chats.length, 0);
});

// contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
test('legacy research claims one deterministic verifier with a reserved slot and stable retry identity', async () => {
  const db = researchDatabase('verification_due');
  const first = await executeOperation(db, 'claim_parent_continuation', researchClaim);
  const replay = await executeOperation(db, 'claim_parent_continuation', researchClaim);
  assert.equal(first.research_stage, 'verification_due');
  assert.equal(replay.verifier_child_id, first.verifier_child_id);
  assert.equal(replay.continuation_task_id, first.continuation_task_id);
  const prepared = await executeOperation(db, 'prepare_batch', verifierPrepare(first));
  assert.equal(prepared.prepared, true);
  assert.equal(db.rows.sub_chat_orchestrations[0].research_stage, 'verification_running');
  assert.equal(db.rows.sub_chat_orchestrations[0].descendant_count, 4);
  assert.equal(db.rows.sub_chat_orchestrations[0].descendant_limit, 3);
  assert.equal(db.rows.sub_chat_orchestrations[0].credit_limit, 2000);
  const reused = await executeOperation(db, 'prepare_batch', verifierPrepare(first));
  assert.equal(reused.idempotent, true);
  assert.equal(db.rows.chats.length, 1);
  assert.equal(db.rows.sub_chat_orchestrations[0].descendant_count, 4);
});

// contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
test('research verifier rejects wrong owner, claim, depth, identity and multiple children', async () => {
  const db = researchDatabase('verification_due');
  const claim = await executeOperation(db, 'claim_parent_continuation', researchClaim);
  const request = verifierPrepare(claim);
  for (const changes of [
    { hashed_user_id: 'wrong' }, { continuation_task_id: CHILD_ID }, { parent_depth: 1 },
    { batch_id: CHILD_ID }, { children: [{ ...request.children[0], child_chat_id: CHILD_ID }] },
    { children: [...request.children, { child_chat_id: CHILD_ID, user_message_id: 'other', dispatch_token: 'token' }] },
  ]) {
    await assert.rejects(executeOperation(db, 'prepare_batch', { ...request, ...changes }), SubChatOrchestrationError);
  }
  assert.equal(db.rows.chats.length, 0);
});

// contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
test('research verifier terminal success alone releases synthesis and initial retry cannot bypass it', async () => {
  const db = researchDatabase('verification_due');
  const claim = await executeOperation(db, 'claim_parent_continuation', researchClaim);
  await executeOperation(db, 'prepare_batch', verifierPrepare(claim));
  const verifierBatch = db.rows.sub_chat_orchestration_batches.find((batch) => batch.id === claim.verifier_batch_id);
  const verifierChild = db.rows.sub_chat_orchestration_children.find((child) => child.child_chat_id === claim.verifier_child_id);
  await assert.rejects(executeOperation(db, 'claim_parent_continuation', { ...researchClaim, batch_id: verifierBatch.id }),
    (error) => error.code === 'batch_not_terminal');
  verifierChild.state = 'completed'; verifierBatch.terminal_count = 1;
  const synthesis = await executeOperation(db, 'claim_parent_continuation', { ...researchClaim, batch_id: verifierBatch.id });
  assert.equal(synthesis.research_stage, 'synthesis');
  assert.equal(synthesis.dispatch_required, true);
  assert.equal((await executeOperation(db, 'claim_parent_continuation', researchClaim)).dispatch_required, false);
  await executeOperation(db, 'mark_parent_continuation_dispatched', {
    ...researchClaim, batch_id: verifierBatch.id, continuation_task_id: synthesis.continuation_task_id,
  });
  const replay = await executeOperation(db, 'claim_parent_continuation', { ...researchClaim, batch_id: verifierBatch.id });
  assert.equal(replay.dispatch_required, false);
  assert.equal(replay.continuation_task_id, synthesis.continuation_task_id);
});

// contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
test('research verifier failed terminal batch permits only a failed stage', async () => {
  const db = researchDatabase('verification_due');
  const claim = await executeOperation(db, 'claim_parent_continuation', researchClaim);
  await executeOperation(db, 'prepare_batch', verifierPrepare(claim));
  const batch = db.rows.sub_chat_orchestration_batches.find((item) => item.id === claim.verifier_batch_id);
  db.rows.sub_chat_orchestration_children.find((item) => item.child_chat_id === claim.verifier_child_id).state = 'failed';
  batch.terminal_count = 1;
  const completion = await executeOperation(db, 'claim_parent_continuation', { ...researchClaim, batch_id: batch.id });
  assert.equal(completion.research_stage, 'failed');
  assert.equal(completion.verifier_child_id, undefined);
});

// contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
test('deep research failed initial reports never schedule another paid verifier', async () => {
  const db = researchDatabase('research', 'failed');
  const completion = await executeOperation(db, 'claim_parent_continuation', researchClaim);
  assert.equal(completion.research_stage, 'failed');
  assert.equal(completion.verifier_child_id, undefined);
});

// contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
test('deep research legacy roots remain final-only and ordinary continuation spawning stays forbidden', async () => {
  const db = researchDatabase(null);
  const completion = await executeOperation(db, 'claim_parent_continuation', researchClaim);
  assert.equal(completion.research_stage, null);
  assert.equal(completion.verifier_child_id, undefined);
  await assert.rejects(executeOperation(db, 'prepare_batch', { ...verifierPrepare({
    verifier_batch_id: CHILD_ID, verifier_child_id: USER_ID, continuation_task_id: CHILD_ID,
  }), research_batch_id: undefined }), (error) => error.code === 'continuation_spawn_forbidden');
  // Replaying create_root with research now active cannot upgrade an existing legacy root.
  db.rows.sub_chat_orchestrations[0].hashed_team_id = null;
  const replay = await executeOperation(db, 'create_root', { protocol_version: 1,
    orchestration_id: RESEARCH_ROOT, hashed_user_id: OWNER, root_chat_id: RESEARCH_CHAT,
    root_turn_id: RESEARCH_TURN, deep_research: true });
  assert.equal(replay.research_stage, null);
});


// contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
test('research verifier live paid work cannot be failed by a stale dispatch acknowledgement', async () => {
  const db = researchDatabase('verification_due');
  const claim = await executeOperation(db, 'claim_parent_continuation', researchClaim);
  await executeOperation(db, 'prepare_batch', verifierPrepare(claim));
  db.rows.sub_chat_orchestration_children.find((child) => child.child_chat_id === claim.verifier_child_id).state = 'running';
  await assert.rejects(executeOperation(db, 'fail_research_verification', {
    ...researchClaim, continuation_task_id: claim.continuation_task_id,
  }), (error) => error.code === 'verification_already_running');
  assert.equal(db.rows.sub_chat_orchestrations[0].research_stage, 'verification_running');
});


// contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
test('deep research initializes only new roots and preserves the global descendant ceiling', async () => {
  const db = researchDatabase('verification_due');
  const fresh = await executeOperation(db, 'create_root', { protocol_version: 1,
    orchestration_id: '88888888-8888-4888-8888-888888888888', hashed_user_id: OWNER,
    root_chat_id: RESEARCH_CHAT, root_turn_id: RESEARCH_TURN, deep_research: true });
  assert.equal(fresh.research_stage, 'research');
  assert.equal(fresh.research_batch_id, null);
  const claim = await executeOperation(db, 'claim_parent_continuation', researchClaim);
  db.rows.sub_chat_orchestrations[0].descendant_count = 20;
  db.rows.sub_chat_orchestrations[0].descendant_limit = 20;
  await assert.rejects(executeOperation(db, 'prepare_batch', verifierPrepare(claim)),
    (error) => error.code === 'descendant_limit_exceeded');
  assert.equal(db.rows.chats.length, 0);
});


// contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
test('legacy research running verifier preserves initial acknowledgement repair after dispatch', async () => {
  const db = researchDatabase('verification_due');
  const initial = await executeOperation(db, 'claim_parent_continuation', researchClaim);
  await executeOperation(db, 'prepare_batch', verifierPrepare(initial));
  const child = db.rows.sub_chat_orchestration_children.find((row) => row.child_chat_id === initial.verifier_child_id);
  child.state = 'running';
  // Dispatch succeeded, but its initial-batch acknowledgement was lost.
  const retry = await executeOperation(db, 'claim_parent_continuation', researchClaim);
  assert.equal(retry.research_stage, 'verification_running');
  assert.equal(retry.verifier_child_state, 'running');
  assert.equal(retry.dispatch_required, true);
  assert.equal(retry.continuation_task_id, initial.continuation_task_id);
  assert.equal(retry.verifier_child_id, initial.verifier_child_id);
  await executeOperation(db, 'mark_parent_continuation_dispatched', {
    ...researchClaim, continuation_task_id: retry.continuation_task_id,
  });
  assert.equal((await executeOperation(db, 'claim_parent_continuation', researchClaim)).dispatch_required, false);
  assert.equal(db.rows.sub_chat_orchestration_children.length, 4);
  assert.equal(db.rows.chats.length, 1);
});
