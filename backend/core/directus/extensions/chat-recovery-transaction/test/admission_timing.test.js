// Payload-free operational timing contract for the internal admission endpoint.
// contract-test-file: tooling
import assert from 'node:assert/strict';
import { test } from 'node:test';
import endpoint, { createAdmissionTimer, FIRST_PERSONAL_PHASES } from '../src/index.js';
import { executeOperation, testing } from '../src/operations.js';

const body = { operation: 'verify_routing_admission', data: {
  protocol_version: 1, hashed_user_id: 'a'.repeat(64), hashed_team_id: null,
  chat_id: '018f4444-4444-7444-8444-444444444444',
  inference_task_id: '018f2222-2222-7222-8222-222222222222',
  preflight_id: '018f1111-1111-7111-8111-111111111111',
  turn_id: '018f5555-5555-7555-8555-555555555555', message_id: 'private-message-id',
} };

function fixture({ authenticated = true, enabled = true, requestBody = body,
  loggerFails = false, database = null } = {}) {
  let handle;
  const logs = [];
  const logger = {
    info(fields, message) { if (loggerFails) throw Error('logger unavailable'); logs.push([fields, message]); },
    warn() {}, error() {},
  };
  endpoint.handler({ post(path, callback) { handle = callback; } }, {
    database: database ?? { transaction() { throw Error('private SQL failure'); } }, logger,
    env: { INTERNAL_API_SHARED_TOKEN: 'configured-token',
      CHAT_RECOVERY_ADMISSION_TIMING_ENABLED: enabled ? 'true' : 'false' },
  });
  const response = { statusCode: null, payload: null,
    status(code) { this.statusCode = code; return this; },
    json(payload) { this.payload = payload; return this; } };
  const req = { headers: { 'x-internal-service-token': authenticated ? 'configured-token' : 'wrong-token' },
    body: requestBody };
  return { run: () => handle(req, response), response, logs };
}

function routingDatabase({ fenced = false, proof = false } = {}) {
  const request = body.data;
  const message = { chat_id: request.chat_id, client_message_id: request.message_id,
    role: 'user', hashed_user_id: request.hashed_user_id, queue_pending_revision: null,
    queue_dispatch_status: 'queued' };
  const digest = testing.routingMessageDigest(message);
  const preflight = { id: request.preflight_id, hashed_user_id: request.hashed_user_id,
    chat_id: request.chat_id, turn_id: request.turn_id, user_message_id: request.message_id,
    inference_task_id: request.inference_task_id, state: 'ENQUEUED',
    expires_at: '2099-01-01T00:00:00Z', committed_messages_v: 1,
    outbox_id: 'outbox', routing_message_digest: proof ? digest : null };
  const rows = {
    chat_recovery_account_fences: fenced ? [{ id: request.hashed_user_id }] : [],
    chat_recovery_chat_deletion_fences: [],
    chat_recovery_protocol_state: [{ id: 'chat-recovery', protocol_epoch: 1, sends_paused: false }],
    chats: [{ id: request.chat_id, hashed_user_id: request.hashed_user_id,
      hashed_team_id: null, messages_v: proof ? 2 : 1 }],
    chat_turn_preflights: [preflight], messages: [message],
    chat_inference_outbox: [{ id: 'outbox', preflight_id: request.preflight_id,
      inference_task_id: request.inference_task_id, hashed_user_id: request.hashed_user_id,
      chat_id: request.chat_id, turn_id: request.turn_id, state: 'PENDING' }],
    chat_routing_proofs: proof ? [{ chat_id: request.chat_id,
      hashed_user_id: request.hashed_user_id, preflight_id: request.preflight_id,
      inference_task_id: request.inference_task_id, messages_v: 2, message_digest: digest }] : [],
  };
  const trx = (table) => {
    let candidates = rows[table] ?? [];
    const query = { where(match) {
      candidates = candidates.filter((row) => Object.entries(match).every(([key, value]) => row[key] === value));
      return query;
    }, forShare() { return query; }, forUpdate() { return query; },
    async first() { return candidates[0]; } };
    return query;
  };
  trx.raw = async () => {};
  trx.schema = { hasTable: async () => true, hasColumn: async () => true };
  return { transaction: async (callback) => callback(trx) };
}

test('operation marks success, optional proof and locked-account failure without changing results', async () => {
  const phases = [];
  let failedAt;
  const timing = { enter: (phase) => phases.push(phase), failHere: () => { failedAt = phases.at(-1); } };
  assert.deepEqual(await executeOperation(routingDatabase(), 'verify_routing_admission',
    body.data, new Date(), timing), { authorized: true });
  assert.deepEqual(phases, ['transaction_setup', 'account_chat_locks', 'fences_reads', 'commit_result']);
  phases.length = 0;
  assert.deepEqual(await executeOperation(routingDatabase({ proof: true }), 'verify_routing_admission',
    body.data, new Date(), timing), { authorized: true });
  assert.deepEqual(phases, ['transaction_setup', 'account_chat_locks', 'fences_reads',
    'proof', 'fences_reads', 'commit_result']);
  phases.length = 0;
  await assert.rejects(executeOperation(routingDatabase({ fenced: true }),
    'verify_routing_admission', body.data, new Date(), timing), /account_recovery_fenced/);
  assert.equal(failedAt, 'account_chat_locks');
  assert.equal(phases.at(-1), 'commit_result');
});

test('authenticated failure is attributed to transaction setup with numeric-only fields', async () => {
  const testCase = fixture();
  await testCase.run();
  assert.equal(testCase.response.statusCode, 500);
  assert.equal(testCase.logs.length, 1);
  const [fields, message] = testCase.logs[0];
  assert.equal(message, 'Routing admission timing');
  assert.equal(fields.failed, 1);
  assert.equal(fields.terminal_phase, 2);
  assert.ok(fields.transaction_setup_ms >= 0);
  assert.ok(fields.total_ms >= fields.transaction_setup_ms);
  assert.ok(Object.values(fields).every((value) => typeof value === 'number' && Number.isFinite(value)));
  assert.ok(!JSON.stringify(testCase.logs).includes('private-message-id'));
  assert.ok(!JSON.stringify(testCase.logs).includes('private SQL failure'));
});

test('validation failure stays in validation; opt-out and unauthenticated calls emit no timing', async () => {
  const invalid = fixture({ requestBody: { operation: 'verify_routing_admission', data: {} } });
  await invalid.run();
  assert.equal(invalid.response.statusCode, 426);
  assert.equal(invalid.logs[0][0].terminal_phase, 1);
  const disabled = fixture({ enabled: false });
  await disabled.run();
  assert.deepEqual(disabled.logs, []);
  const unauthorized = fixture({ authenticated: false });
  await unauthorized.run();
  assert.equal(unauthorized.response.statusCode, 401);
  assert.deepEqual(unauthorized.logs, []);
});

test('timing logger failure cannot change the operation response', async () => {
  const testCase = fixture({ loggerFails: true, requestBody: { operation: 'verify_routing_admission', data: {} } });
  await testCase.run();
  assert.equal(testCase.response.statusCode, 426);
  assert.equal(testCase.response.payload.error.code, 'client_update_required');
});

test('timer reports successful phase durations and a fixed numeric schema', () => {
  let current = 0;
  const timer = createAdmissionTimer(() => current++);
  timer.enter('transaction_setup');
  timer.enter('account_chat_locks');
  timer.enter('fences_reads');
  timer.enter('proof');
  timer.enter('fences_reads');
  timer.enter('commit_result');
  const fields = timer.finish(false);
  assert.equal(fields.failed, 0);
  assert.equal(fields.terminal_phase, 6);
  assert.equal(fields.proof_ms, 1);
  assert.equal(fields.fences_reads_ms, 2);
  assert.equal(fields.total_ms, 7);
  assert.ok(Object.values(fields).every((value) => typeof value === 'number'));
});

test('first Personal event-loop delta remains numeric and observer failures are inert', () => {
  let now = 0;
  const samples = [{ active: 10, idle: 20 }, { active: 16, idle: 24 }];
  const timer = createAdmissionTimer(() => now++, FIRST_PERSONAL_PHASES, 0,
    () => samples.shift());
  timer.enter('validation');
  timer.operationDone();
  const fields = timer.finish(false);
  assert.equal(fields.event_loop_active_ms, 6);
  assert.equal(fields.event_loop_idle_ms, 4);
  assert.equal(fields.event_loop_utilization_permille, 600);
  assert.equal(fields.event_loop_observed, 1);
  const failedSampler = createAdmissionTimer(() => now++, FIRST_PERSONAL_PHASES, now,
    () => { throw Error('private observer failure'); });
  const failedFields = failedSampler.finish(false);
  assert.equal(failedFields.event_loop_observed, 0);
  assert.equal(failedFields.event_loop_active_ms, 0);
  assert.ok(Object.values(failedFields).every((value) => typeof value === 'number' && Number.isFinite(value)));
  assert.ok(!JSON.stringify(failedFields).includes('private observer failure'));
  let samplesTaken = 0;
  const lateFailure = createAdmissionTimer(() => now++, FIRST_PERSONAL_PHASES, now,
    () => { if (samplesTaken++ === 0) return { active: 1, idle: 1 };
      throw Error('private late observer failure'); });
  const lateFields = lateFailure.finish(true);
  assert.equal(lateFields.failed, 1);
  assert.equal(lateFields.event_loop_observed, 0);
  assert.ok(!JSON.stringify(lateFields).includes('private late observer failure'));
});

const firstPersonalBody = { operation: 'admit_first_personal', data: {
  protocol_version: 1, hashed_user_id: 'a'.repeat(64),
  chat_id: body.data.chat_id, turn_id: body.data.turn_id,
  user_message_id: 'private-message-id', device_hash: 'private-device', chat_key_version: 1,
  wrapped_chat_key: 'private-wrapped-key',
  recovery_public_key: Buffer.alloc(32, 7).toString('base64url'),
  inference_commitment: 'b'.repeat(64), commitment_version: 1, expected_messages_v: 0,
  encrypted_user_message: { client_message_id: 'private-message-id', chat_id: body.data.chat_id,
    hashed_user_id: 'a'.repeat(64), encrypted_content: 'private-ciphertext',
    role: 'user', created_at: 100, updated_at: 100 },
  encrypted_chat_metadata: { encrypted_title: 'private-title',
    encrypted_chat_key: 'private-wrapped-key', created_at: 100, updated_at: 100 },
} };

function firstPersonalDatabase({ proofSchema = false, accountFenced = false, deletionFenced = false } = {}) {
  const rows = { chat_recovery_protocol_state: [{ id: 'chat-recovery', protocol_epoch: 1,
    sends_paused: false, legacy_in_flight: 0, active_legacy_tasks: [], legacy_task_lifecycle: [] }],
  chat_recovery_account_fences: accountFenced ? [{ id: firstPersonalBody.data.hashed_user_id }] : [],
  chat_recovery_chat_deletion_fences: deletionFenced ? [{ id: firstPersonalBody.data.chat_id }] : [],
  chats: [], messages: [], chat_turn_preflights: [], chat_inference_outbox: [], chat_routing_proofs: [] };
  const calls = [];
  const trx = (table) => {
    let matching = () => rows[table] ?? [];
    const filter = (predicate) => { const previous = matching; matching = () => previous().filter(predicate); };
    const query = {
      where(criteria) { calls.push(`${table}.where`);
        filter((row) => Object.entries(criteria).every(([key, value]) => row[key] === value)); return query; },
      whereNull(key) { calls.push(`${table}.whereNull`); filter((row) => row[key] == null); return query; },
      orderBy() { calls.push(`${table}.orderBy`); return query; },
      forUpdate() { calls.push(`${table}.forUpdate`); return query; },
      forShare() { calls.push(`${table}.forShare`); return query; },
      async first() { calls.push(`${table}.first`); return matching()[0]; },
      async insert(value) { calls.push(`${table}.insert`); (rows[table] ??= []).push(value); return 1; },
      async update(value) { calls.push(`${table}.update`);
        const found = matching(); for (const row of found) Object.assign(row, value); return found.length; },
    };
    return query;
  };
  trx.raw = async () => { calls.push('raw'); };
  // Both presence and absence of the optional proof schema are supported.
  trx.schema = { hasTable: async () => proofSchema, hasColumn: async () => proofSchema };
  return { calls, rows, transaction: async (callback) => { calls.push('transaction');
    const result = await callback(trx); calls.push('commit'); return result; } };
}

test('first Personal timing preserves successful result and exact database call sequence', async () => {
  const baseline = firstPersonalDatabase();
  const observed = firstPersonalDatabase();
  const at = new Date('2029-01-01T00:00:00Z');
  const plain = await executeOperation(baseline, 'admit_first_personal', firstPersonalBody.data, at);
  const phases = [];
  const instrumented = await executeOperation(observed, 'admit_first_personal', firstPersonalBody.data, at,
    { enter: (phase) => phases.push(phase), failHere: () => assert.fail('unexpected failure') });
  assert.deepEqual(observed.calls, baseline.calls);
  assert.equal(instrumented.state, plain.state);
  assert.equal(instrumented.committed_messages_v, plain.committed_messages_v);
  assert.deepEqual(instrumented.admission_chat_projection, plain.admission_chat_projection);
  assert.deepEqual(phases, ['transaction_setup', 'account_lock', 'protocol_read', 'chat_lock_reads',
    'chat_insert', 'canonical_preflight_read', 'message_identity_read',
    'message_insert', 'chat_version_cas', 'preflight_schema_check',
    'preflight_write', 'post_prepare_reads',
    'outbox_write', 'proof_schema_check', 'commit_result']);
});

test('atomic first Personal reuses only its held protocol read when writing a routing proof', async () => {
  const database = firstPersonalDatabase({ proofSchema: true });
  const at = new Date('2029-01-01T00:00:00Z');
  const phases = [];
  const first = await executeOperation(database, 'admit_first_personal', firstPersonalBody.data, at,
    { enter: (phase) => phases.push(phase), failHere: () => assert.fail('unexpected failure') });
  assert.equal(first.state, 'ENQUEUED');
  assert.equal(database.rows.chat_routing_proofs.length, 1);
  assert.equal(database.calls.filter((call) => call === 'chat_recovery_protocol_state.first').length, 1);
  assert.equal(database.calls.filter((call) => call === 'messages.first').length, 2);
  assert.equal(database.calls.filter((call) => call === 'chat_routing_proofs.first').length, 1);
  assert.equal(database.calls.filter((call) => call === 'chat_routing_proofs.insert').length, 1);
  assert.deepEqual(phases.slice(-5), ['proof_schema_check', 'proof_message_read',
    'proof_row_read', 'proof_write', 'commit_result']);

  const replay = await executeOperation(database, 'admit_first_personal', firstPersonalBody.data,
    new Date(at.getTime() + 1_000));
  assert.deepEqual(replay, first);
  assert.equal(database.rows.chat_routing_proofs.length, 1);
  assert.equal(database.rows.messages.length, 1);
  await assert.rejects(executeOperation(database, 'admit_first_personal',
    { ...firstPersonalBody.data, turn_id: '018f9999-9999-7999-8999-999999999999' }, at),
  /existing_chat_metadata_forbidden/);
  assert.equal(database.rows.chat_routing_proofs.length, 1);
});

test('atomic proof path still rejects account and deletion fences before writing', async () => {
  for (const option of [{ accountFenced: true }, { deletionFenced: true }]) {
    const database = firstPersonalDatabase({ ...option, proofSchema: true });
    await assert.rejects(executeOperation(database, 'admit_first_personal', firstPersonalBody.data,
      new Date('2029-01-01T00:00:00Z')));
    assert.equal(database.rows.messages.length, 0);
    assert.equal(database.rows.chat_routing_proofs.length, 0);
  }
});

test('first Personal endpoint emits numeric timing only after auth, including failures', async () => {
  const success = fixture({ requestBody: firstPersonalBody, database: firstPersonalDatabase() });
  await success.run();
  assert.equal(success.response.statusCode, 200);
  assert.equal(success.logs[0][0].failed, 0);
  assert.equal(success.logs[0][0].terminal_phase, 23);
  assert.equal(success.logs[0][1], 'First Personal admission timing');
  for (const requestBody of [firstPersonalBody,
    { operation: 'admit_first_personal', data: {} }]) {
    const item = fixture({ requestBody });
    await item.run();
    assert.equal(item.logs.length, 1);
    const [fields, label] = item.logs[0];
    assert.equal(label, 'First Personal admission timing');
    assert.equal(fields.failed, 1);
    assert.ok(fields.operation_total_ms >= 0);
    assert.ok(fields.total_ms >= fields.operation_total_ms);
    assert.ok(Object.values(fields).every((value) => typeof value === 'number' && Number.isFinite(value)));
    const serialized = JSON.stringify(item.logs);
    for (const secret of ['private-message-id', 'private-device', 'private-ciphertext',
      'private-title', 'private-wrapped-key', 'private SQL failure']) {
      assert.ok(!serialized.includes(secret));
    }
  }
  const unauthorized = fixture({ authenticated: false, requestBody: firstPersonalBody });
  await unauthorized.run();
  assert.equal(unauthorized.response.statusCode, 401);
  assert.deepEqual(unauthorized.logs, []);
  const disabled = fixture({ enabled: false, requestBody: firstPersonalBody });
  await disabled.run();
  assert.deepEqual(disabled.logs, []);
});

test('first Personal timing logger failure leaves its response unchanged', async () => {
  const requestBody = { operation: 'admit_first_personal', data: {} };
  const ordinary = fixture({ requestBody });
  const brokenLogger = fixture({ requestBody, loggerFails: true });
  await ordinary.run(); await brokenLogger.run();
  assert.equal(brokenLogger.response.statusCode, ordinary.response.statusCode);
  assert.deepEqual(brokenLogger.response.payload, ordinary.response.payload);
  const success = fixture({ requestBody: firstPersonalBody,
    database: firstPersonalDatabase(), loggerFails: true });
  await success.run();
  assert.equal(success.response.statusCode, 200);
  assert.equal(success.response.payload.data.state, 'ENQUEUED');
});
