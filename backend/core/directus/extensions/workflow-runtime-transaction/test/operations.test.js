/* Deterministic transaction tests for one accepted Workflow run per occurrence or event. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isAuthorized } from '../src/index.js';
import { executeOperation, WorkflowRuntimeError } from '../src/operations.js';

const OWNER = 'a'.repeat(64);
const NOW = new Date('2026-07-12T08:00:00Z');

function fakeDatabase(seed) {
  const rows = structuredClone(seed);
  let tail = Promise.resolve();
  const client = (store) => (table) => {
    const predicates = [];
    const match = () => (store[table] ?? []).filter((row) => predicates.every((predicate) => predicate(row)));
    const addWhere = (args) => {
      const values = typeof args[0] === 'object' ? args[0] : { [args[0]]: args.length === 2 ? args[1] : args[2] };
      predicates.push((row) => Object.entries(values).every(([key, value]) => row[key] === value));
    };
    const query = {
      where(...args) { addWhere(args); return query; },
      forUpdate() { return query; },
      async first() { return match()[0]; },
      async insert(value) { (store[table] ??= []).push(structuredClone(value)); return 1; },
      async update(values) { const found = match(); found.forEach((row) => Object.assign(row, structuredClone(values))); return found.length; },
    };
    return query;
  };
  const database = client(rows);
  database.rows = rows;
  database.transaction = async (callback) => {
    const run = tail.then(async () => {
      const working = structuredClone(rows);
      const result = await callback(client(working));
      for (const key of new Set([...Object.keys(rows), ...Object.keys(working)])) rows[key] = working[key] ?? [];
      return result;
    });
    tail = run.catch(() => undefined);
    return run;
  };
  return database;
}

function scheduleTrigger() {
  return {
    trigger_id: 'trigger-1', workflow_id: 'workflow-1', version_id: 'version-1', hashed_user_id: OWNER,
    trigger_type: 'schedule', enabled: true, next_run_at: 1_783_843_100,
    encrypted_schedule_config_ref: 'blob-schedule-1', claim_generation: 0,
  };
}

test('internal authorization fails closed', () => {
  assert.equal(isAuthorized({}, undefined), false);
  assert.equal(isAuthorized({}, 'configured'), false);
  assert.equal(isAuthorized({ 'x-internal-service-token': 'configured' }, 'configured'), true);
});

test('two concurrent due claims create one run and lease recovery reuses it', async () => {
  const database = fakeDatabase({ workflow_triggers: [scheduleTrigger()], workflow_runs: [], workflow_event_receipts: [] });
  const body = { protocol_version: 1, trigger_id: 'trigger-1' };
  const [first, second] = await Promise.all([
    executeOperation(database, 'claim_due_trigger', body, NOW),
    executeOperation(database, 'claim_due_trigger', body, NOW),
  ]);
  assert.equal([first, second].filter((result) => result.accepted).length, 1);
  assert.equal(database.rows.workflow_runs.length, 1);
  const accepted = first.accepted ? first : second;
  assert.equal(accepted.hashed_user_id, OWNER);
  const recovered = await executeOperation(database, 'claim_due_trigger', body, new Date(NOW.getTime() + 121_000));
  assert.equal(recovered.accepted, false);
  assert.equal(recovered.hashed_user_id, OWNER);
  assert.notEqual(recovered.claim_generation, accepted.claim_generation);
  await assert.rejects(
    executeOperation(database, 'advance_claimed_trigger', {
      protocol_version: 1, trigger_id: 'trigger-1', claim_generation: accepted.claim_generation,
      claim_token: accepted.claim_token, next_run_at: 1_783_929_600,
    }, new Date(NOW.getTime() + 121_000)),
    (error) => error instanceof WorkflowRuntimeError && error.code === 'stale_claim',
  );
  const started = await executeOperation(database, 'start_claimed_run', {
    protocol_version: 1, trigger_id: 'trigger-1', run_id: recovered.run_id,
    claim_generation: recovered.claim_generation, claim_token: recovered.claim_token,
  }, new Date(NOW.getTime() + 121_000));
  assert.equal(started.started, true);
  const claimedRunning = await executeOperation(database, 'claim_due_trigger', body, new Date(NOW.getTime() + 242_000));
  assert.equal(claimedRunning.accepted, false);
  assert.equal(claimedRunning.claim_token, undefined);
  const advanced = await executeOperation(database, 'advance_claimed_trigger', {
    protocol_version: 1, trigger_id: 'trigger-1', claim_generation: recovered.claim_generation,
    claim_token: recovered.claim_token, next_run_at: 1_783_929_600,
  }, new Date(NOW.getTime() + 121_000));
  assert.equal(advanced.next_run_at, 1_783_929_600);
});

test('event acceptance stores one payload-free receipt and one run', async () => {
  const eventTrigger = {
    trigger_id: 'trigger-event', workflow_id: 'workflow-1', version_id: 'version-1', hashed_user_id: OWNER,
    trigger_type: 'event', hashed_project_id: 'project-1', source: 'assistant', event_type: 'skill.completed', enabled: true,
  };
  const database = fakeDatabase({ workflow_triggers: [eventTrigger], workflow_runs: [], workflow_event_receipts: [] });
  const body = { protocol_version: 1, trigger_id: 'trigger-event', event_id: 'event-1', hashed_user_id: OWNER, hashed_project_id: 'project-1', source: 'assistant', event_type: 'skill.completed' };
  const [first, second] = await Promise.all([
    executeOperation(database, 'accept_event_trigger', body, NOW),
    executeOperation(database, 'accept_event_trigger', body, NOW),
  ]);
  assert.equal([first, second].filter((result) => result.accepted).length, 1);
  assert.equal(database.rows.workflow_runs.length, 1);
  assert.equal(database.rows.workflow_runs[0].hashed_project_id, 'project-1');
  assert.equal(database.rows.workflow_event_receipts.length, 1);
  assert.deepEqual(Object.keys(database.rows.workflow_event_receipts[0]).sort(), ['created_at', 'dispatch_status', 'event_id', 'event_type', 'hashed_user_id', 'id', 'run_id', 'source', 'trigger_id']);
});

test('event acceptance rejects cross-owner and unknown operation requests', async () => {
  const database = fakeDatabase({ workflow_triggers: [scheduleTrigger()], workflow_runs: [], workflow_event_receipts: [] });
  await assert.rejects(
    executeOperation(database, 'accept_event_trigger', { protocol_version: 1, trigger_id: 'trigger-1', event_id: 'event-1', hashed_user_id: 'b'.repeat(64), hashed_project_id: 'project-1', source: 'assistant', event_type: 'skill.completed' }, NOW),
    (error) => error instanceof WorkflowRuntimeError && error.code === 'event_trigger_mismatch',
  );
  await assert.rejects(
    executeOperation(database, 'unknown', { protocol_version: 1 }, NOW),
    (error) => error instanceof WorkflowRuntimeError && error.code === 'unsupported_operation',
  );
});
