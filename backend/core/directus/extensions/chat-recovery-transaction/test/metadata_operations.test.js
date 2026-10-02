// contract-test-file: tooling
// Pure transactional tests; no Directus, API, credentials, or live data.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { executeOperation, ProtocolError } from '../src/operations.js';
import { fakeDatabase } from './helpers/metadata_database.js';
const OWNER = 'a'.repeat(64);
const CHAT = '22222222-2222-4222-8222-222222222222';
const TASK = '55555555-5555-4555-8555-555555555555';
const PREFLIGHT = '44444444-4444-4444-8444-444444444444';
const INITIAL = '66666666-6666-4666-8666-666666666666';
const FINAL = '77777777-7777-4777-8777-777777777777';
const NOW = new Date('2029-01-01T00:00:00Z');
const sealed = JSON.stringify({ v: 1, epk: Buffer.alloc(32, 1).toString('base64url'),
  nonce: Buffer.alloc(12, 2).toString('base64url'), ciphertext: Buffer.alloc(17, 3).toString('base64url') });
const seed = () => ({ chats: [{ id: CHAT, hashed_user_id: OWNER, encrypted_chat_key: 'wrapped',
  metadata_v: 0, title_v: 0, encrypted_title: '' }], chat_turn_preflights: [{
  id: PREFLIGHT, hashed_user_id: OWNER, chat_id: CHAT, inference_task_id: TASK, chat_key_version: 1,
  wrapped_chat_key: 'wrapped', committed_messages_v: 1, state: 'RUNNING',
}], chat_metadata_recovery_jobs: [] });
const create = (stage = 'initial') => ({ protocol_version: 1, job_id: stage === 'initial' ? INITIAL : FINAL,
  hashed_user_id: OWNER, chat_id: CHAT, task_id: TASK, inference_task_id: TASK, preflight_id: PREFLIGHT,
  chat_key_version: 1, stage, source_metadata_v: 0, generated_at: NOW.toISOString(), encrypted_fields: stage === 'initial'
    ? ['encrypted_title', 'encrypted_icon', 'encrypted_category']
    : ['encrypted_title', 'encrypted_icon', 'encrypted_category', 'encrypted_chat_summary'], sealed_payload: sealed });
const persist = (stage = 'initial') => ({ protocol_version: 1, job_id: stage === 'initial' ? INITIAL : FINAL,
  hashed_user_id: OWNER, chat_key_version: 1, wrapped_chat_key: 'wrapped', encrypted_metadata: {
    encrypted_title: `${stage}-title`, encrypted_icon: `${stage}-icon`, encrypted_category: `${stage}-category`,
    ...(stage === 'initial' ? {} : { encrypted_chat_summary: 'final-summary' }),
  } });
const run = (db, operation, data, now = NOW) => executeOperation(db, operation, data, now);
const rejects = (promise, code) => assert.rejects(promise, (error) => error instanceof ProtocolError && error.code === code);

test('lost transient metadata remains discoverable and commits once after assistant completion', async () => {
  const db = fakeDatabase(seed());
  await run(db, 'create_metadata_job', create('initial'));
  db.rows.chat_turn_preflights[0].state = 'TERMINAL'; // Assistant ACK is independent.
  await run(db, 'create_metadata_job', create('postprocessing'));
  assert.equal((await run(db, 'list_metadata_jobs', { protocol_version: 1, hashed_user_id: OWNER })).jobs.length, 2);
  const claim = await run(db, 'claim_metadata_job', { protocol_version: 1, job_id: FINAL, hashed_user_id: OWNER });
  assert.equal(claim.sealed_payload, sealed);
  const results = await Promise.all([run(db, 'persist_metadata_job', persist('postprocessing')),
    run(db, 'persist_metadata_job', persist('postprocessing'))]);
  assert.deepEqual(results[0], results[1]);
  assert.equal(db.rows.chats[0].metadata_v, 1);
  assert.equal(db.rows.chats[0].encrypted_chat_summary, 'final-summary');
  assert.equal(db.rows.chat_metadata_recovery_jobs.find((row) => row.id === FINAL).sealed_payload, null);
  assert.equal((await run(db, 'persist_metadata_job', persist())).state, 'SUPERSEDED');
  assert.equal(db.rows.chats[0].encrypted_title, 'postprocessing-title');
});

test('same-turn initial commit can advance to final metadata without losing summary', async () => {
  const db = fakeDatabase(seed());
  await run(db, 'create_metadata_job', create());
  await run(db, 'persist_metadata_job', persist());
  await run(db, 'create_metadata_job', create('postprocessing'));
  const result = await run(db, 'persist_metadata_job', persist('postprocessing'));
  assert.equal(result.state, 'TERMINAL');
  assert.equal(db.rows.chats[0].metadata_v, 2);
  assert.equal(db.rows.chats[0].encrypted_chat_summary, 'final-summary');
  assert.equal(db.rows.chats[0].encrypted_icon, 'postprocessing-icon');
});

test('intervening owner title edit survives while unchanged missing summary is recovered', async () => {
  const db = fakeDatabase(seed());
  await run(db, 'create_metadata_job', create());
  await run(db, 'persist_metadata_job', persist());
  db.rows.chats[0].encrypted_title = 'owner-title';
  db.rows.chats[0].title_v = 2;
  db.rows.chats[0].metadata_v = 2;
  await run(db, 'create_metadata_job', create('postprocessing'));
  const result = await run(db, 'persist_metadata_job', persist('postprocessing'));
  assert.equal(db.rows.chats[0].encrypted_title, 'owner-title');
  assert.equal(db.rows.chats[0].encrypted_chat_summary, 'final-summary');
  assert.equal(result.versions.title_v, 2);
});

test('edits during preprocessing and newer accepted turns supersede older metadata', async () => {
  for (const earlierEdit of [true, false]) {
    const db = fakeDatabase(seed());
    if (earlierEdit) db.rows.chats[0].metadata_v = 1;
    await run(db, 'create_metadata_job', create());
    if (!earlierEdit) db.rows.chat_turn_preflights.push({ hashed_user_id: OWNER, chat_id: CHAT, committed_messages_v: 3 });
    assert.equal((await run(db, 'persist_metadata_job', persist())).state, 'SUPERSEDED');
    assert.equal(db.rows.chats[0].encrypted_title, '');
  }
});

test('wrong owner, immutable key mismatch, deleted chat, and extra plaintext fail closed', async () => {
  const db = fakeDatabase(seed());
  await run(db, 'create_metadata_job', create());
  await rejects(run(db, 'claim_metadata_job', { protocol_version: 1, job_id: INITIAL, hashed_user_id: 'b'.repeat(64) }), 'metadata_job_not_found');
  await rejects(run(db, 'persist_metadata_job', { ...persist(), wrapped_chat_key: 'wrong' }), 'metadata_key_mismatch');
  await rejects(run(db, 'persist_metadata_job', { ...persist(), chat_key_version: 2 }), 'metadata_key_mismatch');
  await rejects(run(db, 'persist_metadata_job', { ...persist(), encrypted_metadata: { title: 'private plaintext' } }), 'invalid_metadata_fields');
  db.rows.chats = [];
  await rejects(run(db, 'claim_metadata_job', { protocol_version: 1, job_id: INITIAL, hashed_user_id: OWNER }), 'chat_not_found');
  assert.equal(db.rows.chat_metadata_recovery_jobs[0].state, 'AVAILABLE');
});

test('receipt failure rolls back chat ciphertext/version and retains sealed delivery', async () => {
  const db = fakeDatabase(seed(), { operation: 'update', table: 'chat_metadata_recovery_jobs' });
  await run(db, 'create_metadata_job', create());
  await assert.rejects(run(db, 'persist_metadata_job', persist()), /injected/);
  assert.equal(db.rows.chats[0].encrypted_title, '');
  assert.equal(db.rows.chats[0].metadata_v, 0);
  assert.equal(db.rows.chat_metadata_recovery_jobs[0].sealed_payload, sealed);
});

test('creation retry retains original sealed bytes and original baseline', async () => {
  const db = fakeDatabase(seed());
  await run(db, 'create_metadata_job', create());
  db.rows.chats[0].encrypted_title = 'owner-edit';
  const changedEnvelope = sealed.replace('AwM', 'AQE');
  await run(db, 'create_metadata_job', { ...create(), sealed_payload: changedEnvelope });
  assert.equal(db.rows.chat_metadata_recovery_jobs.length, 1);
  assert.equal(db.rows.chat_metadata_recovery_jobs[0].sealed_payload, sealed);
  assert.equal(JSON.parse(db.rows.chat_metadata_recovery_jobs[0].baseline_fields).encrypted_title, '');
});

test('expiry and owner deletion purge sealed metadata with existing recovery lifecycle', async () => {
  const db = fakeDatabase(seed());
  await run(db, 'create_metadata_job', create());
  const later = new Date(NOW.getTime() + 8 * 24 * 60 * 60_000);
  await rejects(run(db, 'claim_metadata_job', { protocol_version: 1, job_id: INITIAL, hashed_user_id: OWNER }, later), 'metadata_job_expired');
  const cleanup = await run(db, 'cleanup_expired', { protocol_version: 1 }, later);
  assert.equal(cleanup.expired_metadata_jobs, 1);
  assert.equal(db.rows.chat_metadata_recovery_jobs.length, 0);
  await run(db, 'create_metadata_job', create());
  const deleted = await run(db, 'invalidate_deletion', { protocol_version: 1, hashed_user_id: OWNER, scope: 'chat', chat_id: CHAT });
  assert.equal(deleted.deleted_metadata_jobs, 1);
  assert.equal(db.rows.chat_metadata_recovery_jobs.length, 0);
});

test('continuation keeps original preflight baseline while distinct stage jobs advance once', async () => {
  const db = fakeDatabase(seed());
  await run(db, 'create_metadata_job', create());
  await run(db, 'persist_metadata_job', persist());
  await run(db, 'create_metadata_job', create('postprocessing'));
  await run(db, 'persist_metadata_job', persist('postprocessing'));
  const continuationTask = '88888888-8888-4888-8888-888888888888';
  const continuationJob = '99999999-9999-4999-8999-999999999999';
  await run(db, 'create_metadata_job', { ...create('postprocessing'), task_id: continuationTask, job_id: continuationJob });
  const result = await run(db, 'persist_metadata_job', { ...persist('postprocessing'), job_id: continuationJob,
    encrypted_metadata: { ...persist('postprocessing').encrypted_metadata, encrypted_chat_summary: 'continuation-summary' } });
  assert.equal(result.state, 'TERMINAL');
  assert.equal(db.rows.chats[0].encrypted_chat_summary, 'continuation-summary');
  assert.equal(db.rows.chats[0].metadata_v, 3);
});

test('later continuation stage settles first and older stage cannot roll metadata back', async () => {
  const db = fakeDatabase(seed());
  await run(db, 'create_metadata_job', create('postprocessing'));
  const continuationJob = '99999999-9999-4999-8999-999999999999';
  await run(db, 'create_metadata_job', { ...create('postprocessing'), task_id: '88888888-8888-4888-8888-888888888888', job_id: continuationJob });
  await run(db, 'persist_metadata_job', { ...persist('postprocessing'), job_id: continuationJob,
    encrypted_metadata: { ...persist('postprocessing').encrypted_metadata, encrypted_title: 'continuation-title' } });
  assert.equal((await run(db, 'persist_metadata_job', persist('postprocessing'))).state, 'SUPERSEDED');
  assert.equal(db.rows.chats[0].encrypted_title, 'continuation-title');
});

test('admission routing read is exact owner/chat/task and unavailable metadata stays compatible', async () => {
  const db = fakeDatabase(seed());
  const query = { protocol_version: 1, hashed_user_id: OWNER, chat_id: CHAT, task_id: TASK };
  assert.equal((await run(db, 'metadata_job_admitted', query)).admitted, false);
  await run(db, 'create_metadata_job', create());
  assert.equal((await run(db, 'metadata_job_admitted', query)).admitted, true);
  assert.equal((await run(db, 'metadata_job_admitted', { ...query, hashed_user_id: 'b'.repeat(64) })).admitted, false);
});


test('initial outage first admission after final commit cannot reverse generated fields', async () => {
  const db = fakeDatabase(seed());
  await run(db, 'create_metadata_job', create('postprocessing'));
  await run(db, 'persist_metadata_job', persist('postprocessing'));
  await run(db, 'create_metadata_job', create()); // Independent sealed retry arrives late.
  assert.equal((await run(db, 'persist_metadata_job', persist())).state, 'SUPERSEDED');
  assert.equal(db.rows.chats[0].encrypted_title, 'postprocessing-title');
  assert.equal(db.rows.chats[0].encrypted_chat_summary, 'final-summary');
});


test('generation order survives delayed final admission after newer continuation committed', async () => {
  const db = fakeDatabase(seed());
  const continuationJob = '99999999-9999-4999-8999-999999999999';
  const later = new Date(NOW.getTime() + 1000);
  await run(db, 'create_metadata_job', { ...create('postprocessing'), task_id: '88888888-8888-4888-8888-888888888888',
    job_id: continuationJob, generated_at: later.toISOString() }, later);
  await run(db, 'persist_metadata_job', { ...persist('postprocessing'), job_id: continuationJob,
    encrypted_metadata: { ...persist('postprocessing').encrypted_metadata, encrypted_title: 'continuation-title' } }, later);
  await run(db, 'create_metadata_job', create('postprocessing'), later); // Original final retry arrives last.
  assert.equal((await run(db, 'persist_metadata_job', persist('postprocessing'), later)).state, 'SUPERSEDED');
  assert.equal(db.rows.chats[0].encrypted_title, 'continuation-title');
});

test('generation timestamp is canonical, preflight-bound, retained on retry, and expires with job', async () => {
  const db = fakeDatabase(seed());
  for (const generated_at of [null, '', '2029-01-01', 'invalid', new Date(NOW.getTime() + 1000).toISOString()]) {
    await rejects(run(db, 'create_metadata_job', { ...create(), generated_at }), 'invalid_metadata_generation');
  }
  db.rows.chat_turn_preflights[0].prepared_at = NOW;
  await rejects(run(db, 'create_metadata_job', { ...create(), generated_at: new Date(NOW.getTime() - 1000).toISOString() }), 'invalid_metadata_generation');
  await run(db, 'create_metadata_job', create());
  await rejects(run(db, 'create_metadata_job', { ...create(), generated_at: new Date(NOW.getTime() - 1).toISOString() }), 'invalid_metadata_generation');
  const after = new Date(NOW.getTime() + 8 * 24 * 60 * 60 * 1000);
  await rejects(run(db, 'create_metadata_job', create(), after), 'metadata_job_expired');
  assert.equal(+new Date(db.rows.chat_metadata_recovery_jobs[0].generated_at), +NOW);
});
