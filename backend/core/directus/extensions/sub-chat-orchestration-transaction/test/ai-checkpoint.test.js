// contract-test-file: tooling
import assert from 'node:assert/strict';
import test from 'node:test';
import { executeOperation } from '../src/operations.js';

const ROOT = '11111111-1111-4111-8111-111111111111';
const CHAT = '22222222-2222-4222-8222-222222222222';
const USER = '33333333-3333-4333-8333-333333333333';
const OTHER = '44444444-4444-4444-8444-444444444444';
const OWNER = 'a'.repeat(64);
const OP = 'ai-ask:task:main:iteration:0:model:google/test';
const CHARGE = 'ai-ask:task:main';
// Serialize transactions and roll back rejected mutations, mirroring the locked
// root boundary. Production PostgreSQL supplies the actual row locks.
function database() {
  const rows = {
    sub_chat_orchestrations: [{ id: ROOT, hashed_user_id: OWNER, hashed_team_id: null,
      root_chat_id: CHAT, status: 'active', expires_at: '2099-01-01',
      reserved_credits: 1800, spent_credits: 100, credit_limit: 2000, version: 1 }],
    sub_chat_orchestration_operations: [
      { id: OP, operation_id: OP, charge_id: CHARGE, orchestration_id: ROOT,
        root_chat_id: CHAT, actual_chat_id: CHAT, app_id: 'ai', skill_id: 'ask',
        phase: 'inference_0', depth: 0, quoted_credits: 800, actual_credits: null, state: 'reserved' },
      { id: 'other', operation_id: 'other', charge_id: 'other', orchestration_id: ROOT,
        quoted_credits: 1000, actual_credits: null, state: 'reserved' },
    ], directus_users: [{ id: USER, encrypted_credit_balance: 'before' }],
    billing_charge_identities: [], billing_reservations: [], usage: [],
  };
  const db = (table) => {
    const predicates = [];
    const matching = () => (rows[table] ?? []).filter(row => predicates.every(p => p(row)));
    const q = {
      where(values) { predicates.push(row => Object.entries(values).every(([k, v]) => row[k] === v)); return q; },
      whereIn(key, values) { predicates.push(row => values.includes(row[key])); return q; },
      orderBy() { return q; }, forUpdate() { return q; },
      first: async () => matching()[0], then: (a, b) => Promise.resolve(matching()).then(a, b),
      insert: async value => { (rows[table] ??= []).push(structuredClone(value)); return 1; },
      update: async values => { const found = matching(); found.forEach(row => Object.assign(row, values)); return found.length; },
    };
    return q;
  };
  db.rows = rows;
  db.raw = async () => ({ rows: [] });
  let tail = Promise.resolve();
  db.transaction = callback => {
    const result = tail.then(async () => {
      const before = structuredClone(rows);
      try { return await callback(db); } catch (error) {
        for (const key of Object.keys(rows)) delete rows[key];
        Object.assign(rows, before); throw error;
      }
    });
    tail = result.catch(() => {}); return result;
  };
  return db;
}
const checkpoint = { protocol_version: 1, operation_id: OP, charge_id: CHARGE,
  orchestration_id: ROOT, hashed_user_id: OWNER, actual_chat_id: CHAT, actual_credits: 90 };
const reserve = { protocol_version: 1, operation_id: 'next', charge_id: 'next',
  orchestration_id: ROOT, hashed_user_id: OWNER, root_chat_id: CHAT, actual_chat_id: CHAT,
  depth: 0, app_id: 'ai', skill_id: 'ask', phase: 'inference_1', quoted_credits: 800 };
const rejects = (promise, code) => assert.rejects(promise, error => error.code === code);

// contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
test('completed AI checkpoint releases unused hold and admits a concurrent iteration within the same finite cap', async () => {
  const db = database();
  await rejects(executeOperation(db, 'reserve_operation', reserve), 'orchestration_credit_limit_exceeded');
  const [first, replay, next] = await Promise.all([
    executeOperation(db, 'checkpoint_ai_operation', checkpoint),
    executeOperation(db, 'checkpoint_ai_operation', checkpoint),
    executeOperation(db, 'reserve_operation', reserve),
  ]);
  assert.equal(first.quoted_credits, 800);
  assert.equal(first.actual_credits, 90);
  assert.equal(first.state, 'reserved'); // No wallet charge at checkpoint.
  assert.equal(replay.idempotent, true);
  assert.equal(next.idempotent, false);
  assert.equal(db.rows.sub_chat_orchestrations[0].reserved_credits, 1890);
  assert.equal(db.rows.sub_chat_orchestrations[0].spent_credits, 100);
  await rejects(executeOperation(db, 'reserve_operation', { ...reserve, operation_id: 'overflow', quoted_credits: 11 }), 'orchestration_credit_limit_exceeded');
});

// contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
test('checkpoint scope, quote ceiling, replay identity and private payload checks fail closed', async () => {
  const db = database();
  for (const [override, code] of [
    [{ hashed_user_id: 'b'.repeat(64) }, 'orchestration_not_found'],
    [{ orchestration_id: OTHER }, 'orchestration_not_found'],
    [{ actual_chat_id: OTHER }, 'operation_identity_mismatch'],
    [{ charge_id: 'foreign' }, 'operation_identity_mismatch'],
    [{ actual_credits: 801 }, 'operation_actual_exceeds_quote'],
    [{ actual_credits: -1 }, 'invalid_actual_credits'],
    [{ prompt: 'forbidden' }, 'invalid_request'],
  ]) await assert.rejects(executeOperation(db, 'checkpoint_ai_operation', { ...checkpoint, ...override }), error => error.code === code);
  assert.equal(db.rows.sub_chat_orchestrations[0].reserved_credits, 1800);
  db.rows.sub_chat_orchestration_operations[0].app_id = 'web';
  await rejects(executeOperation(db, 'checkpoint_ai_operation', checkpoint), 'operation_identity_mismatch');
  db.rows.sub_chat_orchestration_operations[0].app_id = 'ai';
  await executeOperation(db, 'checkpoint_ai_operation', checkpoint);
  await rejects(executeOperation(db, 'checkpoint_ai_operation', { ...checkpoint, actual_credits: 89 }), 'operation_checkpoint_mismatch');
  assert.equal(db.rows.sub_chat_orchestrations[0].reserved_credits, 1090);
});

// contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
test('failure releases only the confirmed hold once; root cancellation releases remaining in-flight holds', async () => {
  const db = database();
  await executeOperation(db, 'checkpoint_ai_operation', checkpoint);
  const fail = { protocol_version: 1, operation_id: OP, orchestration_id: ROOT, hashed_user_id: OWNER };
  await executeOperation(db, 'fail_operation', fail);
  assert.equal((await executeOperation(db, 'fail_operation', fail)).idempotent, true);
  assert.equal(db.rows.sub_chat_orchestrations[0].reserved_credits, 1000);
  await rejects(executeOperation(db, 'checkpoint_ai_operation', checkpoint), 'operation_not_reserved');
  await executeOperation(db, 'transition_root', { protocol_version: 1, orchestration_id: ROOT, hashed_user_id: OWNER, state: 'cancelled' });
  assert.equal(db.rows.sub_chat_orchestrations[0].reserved_credits, 0);
  assert.equal(db.rows.sub_chat_orchestrations[0].spent_credits, 100);
});

// contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
test('checkpoint plus final personal settlement charges once and leaves other holds intact', async () => {
  const db = database();
  await executeOperation(db, 'checkpoint_ai_operation', checkpoint);
  const charge = { protocol_version: 1, charge_id: CHARGE, user_id: USER, hashed_user_id: OWNER,
    app_id: 'ai', skill_id: 'ask', requested_credits: 90, charged_credits: 90,
    expected_encrypted_balance: 'before', new_encrypted_balance: 'after',
    usage_entry: { id: OTHER, charge_id: CHARGE, user_id_hash: OWNER, app_id: 'ai', skill_id: 'ask',
      orchestration_id: ROOT, encrypted_credits_costs_total: 'encrypted', created_at: 1, updated_at: 1 } };
  await executeOperation(db, 'commit_personal_charge', charge);
  assert.equal((await executeOperation(db, 'commit_personal_charge', charge)).idempotent, true);
  assert.equal(db.rows.sub_chat_orchestrations[0].reserved_credits, 1000);
  assert.equal(db.rows.sub_chat_orchestrations[0].spent_credits, 190);
  assert.equal(db.rows.sub_chat_orchestration_operations[0].state, 'settled');
  assert.equal(db.rows.sub_chat_orchestration_operations[0].quoted_credits, 800);
  assert.equal(db.rows.billing_charge_identities.length, 1);
  assert.equal(db.rows.usage.length, 1);
  assert.equal(db.rows.directus_users[0].encrypted_credit_balance, 'after');
});

// contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
test('zero-credit completed checkpoint still terminalizes and root cleanup subtracts confirmed holds', async () => {
  const db = database();
  await executeOperation(db, 'checkpoint_ai_operation', { ...checkpoint, actual_credits: 0 });
  await executeOperation(db, 'transition_root', { protocol_version: 1, orchestration_id: ROOT, hashed_user_id: OWNER, state: 'failed' });
  assert.equal(db.rows.sub_chat_orchestrations[0].reserved_credits, 0);
  assert.ok(db.rows.sub_chat_orchestration_operations.every(row => row.state === 'failed'));
});


// contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
test('failed child releases confirmed and zero holds without releasing sibling capacity', async () => {
  const db = database();
  db.rows.sub_chat_orchestration_children = [{ id: CHAT, orchestration_id: ROOT, child_chat_id: CHAT, batch_id: OTHER, state: 'running' }];
  db.rows.sub_chat_orchestration_batches = [{ id: OTHER, orchestration_id: ROOT, terminal_count: 0, child_count: 1 }];
  await executeOperation(db, 'checkpoint_ai_operation', { ...checkpoint, actual_credits: 0 });
  const transition = { protocol_version: 1, orchestration_id: ROOT, hashed_user_id: OWNER, child_chat_id: CHAT, state: 'failed' };
  await executeOperation(db, 'transition_child', transition);
  assert.equal(db.rows.sub_chat_orchestration_operations[0].state, 'failed');
  assert.equal(db.rows.sub_chat_orchestrations[0].reserved_credits, 1000);
  assert.equal((await executeOperation(db, 'transition_child', transition)).transitioned, false);
  assert.equal(db.rows.sub_chat_orchestration_batches[0].terminal_count, 1);
});

// contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
test('terminal or expired roots cannot accept a new completed checkpoint', async () => {
  for (const override of [{ status: 'failed' }, { expires_at: '2000-01-01' }]) {
    const db = database();
    Object.assign(db.rows.sub_chat_orchestrations[0], override);
    await rejects(executeOperation(db, 'checkpoint_ai_operation', checkpoint), 'orchestration_not_active');
    assert.equal(db.rows.sub_chat_orchestrations[0].reserved_credits, 1800);
  }
});
