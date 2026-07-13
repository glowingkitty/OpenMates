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
    const orderings = [];
    let rowLimit = null;
    const match = () => {
      let rows = (store[table] ?? []).filter((row) => predicates.every((predicate) => predicate(row)));
      for (const { field, direction } of orderings.slice().reverse()) {
        rows = rows.slice().sort((left, right) => {
          if (left[field] === right[field]) return 0;
          const comparison = left[field] < right[field] ? -1 : 1;
          return direction === 'desc' ? -comparison : comparison;
        });
      }
      return rowLimit === null ? rows : rows.slice(0, rowLimit);
    };
    const addWhere = (args) => {
      if (typeof args[0] === 'object') {
        const values = args[0];
        predicates.push((row) => Object.entries(values).every(([key, value]) => row[key] === value));
        return;
      }
      if (args.length === 3) {
        const [field, op, value] = args;
        predicates.push((row) => {
          if (op === '<=') return row[field] <= value;
          if (op === '<') return row[field] < value;
          if (op === '>=') return row[field] >= value;
          if (op === '>') return row[field] > value;
          return row[field] === value;
        });
        return;
      }
      const [field, value] = args;
      predicates.push((row) => row[field] === value);
    };
    const query = {
      where(...args) { addWhere(args); return query; },
      forUpdate() { return query; },
      async first() { return match()[0]; },
      async insert(value) { (store[table] ??= []).push(structuredClone(value)); return 1; },
      async update(values) { const found = match(); found.forEach((row) => Object.assign(row, structuredClone(values))); return found.length; },
      orderBy(field, direction = 'asc') { orderings.push({ field, direction }); return query; },
      limit(value) { rowLimit = value; return query; },
      then(resolve, reject) { return Promise.resolve(match()).then(resolve, reject); },
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
    owner_user_id: 'owner-user-1',
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
  assert.equal(accepted.owner_user_id, 'owner-user-1');
  assert.equal(database.rows.workflow_runs[0].owner_user_id, undefined);
  const recovered = await executeOperation(database, 'claim_due_trigger', body, new Date(NOW.getTime() + 121_000));
  assert.equal(recovered.accepted, true);
  assert.equal(recovered.recovered, true);
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

test('due trigger listing returns enabled due schedule trigger ids only', async () => {
  const activeClaim = { ...scheduleTrigger(), trigger_id: 'trigger-active', claim_status: 'claimed', claim_expires_at: 1_783_843_260 };
  const dueSecond = { ...scheduleTrigger(), trigger_id: 'trigger-2', next_run_at: 1_783_843_150 };
  const future = { ...scheduleTrigger(), trigger_id: 'trigger-future', next_run_at: 1_783_843_500 };
  const disabled = { ...scheduleTrigger(), trigger_id: 'trigger-disabled', enabled: false };
  const event = { ...scheduleTrigger(), trigger_id: 'trigger-event', trigger_type: 'event' };
  const database = fakeDatabase({ workflow_triggers: [future, dueSecond, activeClaim, disabled, event, scheduleTrigger()], workflow_runs: [], workflow_event_receipts: [] });

  const result = await executeOperation(database, 'list_due_triggers', { protocol_version: 1, now: 1_783_843_200, limit: 10 }, NOW);

  assert.deepEqual(result, { trigger_ids: ['trigger-1', 'trigger-2'] });
});

test('due claim fails closed when the scheduler-only raw owner reference is missing', async () => {
  const trigger = scheduleTrigger();
  delete trigger.owner_user_id;
  const database = fakeDatabase({ workflow_triggers: [trigger], workflow_runs: [], workflow_event_receipts: [] });

  await assert.rejects(
    executeOperation(database, 'claim_due_trigger', { protocol_version: 1, trigger_id: 'trigger-1' }, NOW),
    (error) => error instanceof WorkflowRuntimeError && error.code === 'owner_reference_required',
  );
  assert.equal(database.rows.workflow_runs.length, 0);
  assert.equal(database.rows.workflow_triggers[0].claim_status, undefined);
});

test('manual acceptance creates one queued run pinned to the locked current immutable version', async () => {
  const database = fakeDatabase({
    workflows: [{ workflow_id: 'workflow-1', hashed_user_id: OWNER, current_version_id: 'version-1', status: 'active' }],
    workflow_versions: [{ version_id: 'version-1', workflow_id: 'workflow-1', hashed_user_id: OWNER }],
    workflow_triggers: [], workflow_runs: [], workflow_event_receipts: [],
  });
  const body = {
    protocol_version: 1, workflow_id: 'workflow-1', hashed_user_id: OWNER,
    trigger_type: 'manual', idempotency_key: 'manual-request-1',
  };
  const [first, second] = await Promise.all([
    executeOperation(database, 'accept_manual_run', body, NOW),
    executeOperation(database, 'accept_manual_run', body, NOW),
  ]);

  const accepted = first.accepted ? first : second;
  assert.equal([first, second].filter((result) => result.accepted).length, 1);
  assert.equal(database.rows.workflow_runs.length, 1);
  assert.equal(accepted.version_id, 'version-1');
  assert.equal(accepted.status, 'queued');
  assert.equal(database.rows.workflow_runs[0].version_id, 'version-1');
  assert.equal(database.rows.workflow_runs[0].trigger_id, null);
  assert.equal(database.rows.workflow_runs[0].acceptance_idempotency_key.startsWith('sha256:'), true);
  assert.equal(database.rows.workflow_runs[0].acceptance_idempotency_key.includes('manual-request-1'), false);
  assert.equal(database.rows.workflow_runs[0].owner_user_id, undefined);

  database.rows.workflows[0].current_version_id = 'version-2';
  database.rows.workflow_versions.push({ version_id: 'version-2', workflow_id: 'workflow-1', hashed_user_id: OWNER });
  const replay = await executeOperation(database, 'accept_manual_run', body, NOW);
  assert.deepEqual(replay, {
    accepted: false, run_id: accepted.run_id, workflow_id: 'workflow-1', version_id: 'version-1', status: 'queued',
  });
  assert.equal(database.rows.workflow_runs.length, 1);
});

test('manual acceptance rejects a missing immutable version without creating a run', async () => {
  const database = fakeDatabase({
    workflows: [{ workflow_id: 'workflow-1', hashed_user_id: OWNER, current_version_id: 'version-missing', status: 'active' }],
    workflow_versions: [], workflow_triggers: [], workflow_runs: [], workflow_event_receipts: [],
  });

  await assert.rejects(
    executeOperation(database, 'accept_manual_run', {
      protocol_version: 1, workflow_id: 'workflow-1', hashed_user_id: OWNER,
      trigger_type: 'test', idempotency_key: 'test-request-1',
    }, NOW),
    (error) => error instanceof WorkflowRuntimeError && error.code === 'workflow_version_not_found',
  );
  assert.equal(database.rows.workflow_runs.length, 0);
});

test('only one worker can start an accepted manual run', async () => {
  const database = fakeDatabase({
    workflow_triggers: [], workflow_event_receipts: [],
    workflow_runs: [{
      run_id: 'run-manual-1', workflow_id: 'workflow-1', version_id: 'version-1',
      hashed_user_id: OWNER, trigger_type: 'manual', status: 'queued',
    }],
  });
  const body = {
    protocol_version: 1, workflow_id: 'workflow-1', run_id: 'run-manual-1', hashed_user_id: OWNER,
  };

  const [first, second] = await Promise.all([
    executeOperation(database, 'start_accepted_run', body, NOW),
    executeOperation(database, 'start_accepted_run', body, NOW),
  ]);

  assert.equal([first, second].filter((result) => result.started).length, 1);
  assert.equal(database.rows.workflow_runs[0].status, 'running');
  assert.equal(database.rows.workflow_runs[0].started_at, 1_783_843_200);
});

test('owner cancellation is durable and rejects terminal or cross-owner runs', async () => {
  const database = fakeDatabase({
    workflow_triggers: [], workflow_event_receipts: [],
    workflow_runs: [{ run_id: 'run-1', workflow_id: 'workflow-1', hashed_user_id: OWNER, status: 'running' }],
  });
  const body = { protocol_version: 1, workflow_id: 'workflow-1', run_id: 'run-1', hashed_user_id: OWNER };

  const cancelled = await executeOperation(database, 'request_run_cancellation', body, NOW);

  assert.deepEqual(cancelled, { run_id: 'run-1', status: 'cancellation_requested' });
  assert.equal(database.rows.workflow_runs[0].status, 'cancellation_requested');
  assert.equal(database.rows.workflow_runs[0].cancellation_requested_at, 1_783_843_200);
  assert.deepEqual(await executeOperation(database, 'request_run_cancellation', body, NOW), cancelled);
  database.rows.workflow_runs[0].status = 'completed';
  await assert.rejects(
    executeOperation(database, 'request_run_cancellation', body, NOW),
    (error) => error instanceof WorkflowRuntimeError && error.code === 'run_not_cancellable',
  );
  await assert.rejects(
    executeOperation(database, 'request_run_cancellation', { ...body, hashed_user_id: 'b'.repeat(64) }, NOW),
    (error) => error instanceof WorkflowRuntimeError && error.code === 'run_not_found',
  );
});

test('cancelling a queued scheduled run releases its lease and advances the occurrence without execution', async () => {
  const database = fakeDatabase({ workflow_triggers: [scheduleTrigger()], workflow_runs: [], workflow_event_receipts: [] });
  const claim = await executeOperation(database, 'claim_due_trigger', { protocol_version: 1, trigger_id: 'trigger-1' }, NOW);
  const cancelled = await executeOperation(database, 'request_run_cancellation', {
    protocol_version: 1, workflow_id: 'workflow-1', run_id: claim.run_id, hashed_user_id: OWNER,
  }, NOW);

  assert.deepEqual(cancelled, {
    run_id: claim.run_id, status: 'cancelled', trigger_id: 'trigger-1', requeue_scheduled_trigger: true,
  });
  assert.equal(database.rows.workflow_triggers[0].claim_status, null);

  const recovered = await executeOperation(database, 'claim_due_trigger', { protocol_version: 1, trigger_id: 'trigger-1' }, NOW);
  assert.equal(recovered.accepted, true);
  assert.equal(recovered.recovered, true);
  const started = await executeOperation(database, 'start_claimed_run', {
    protocol_version: 1, trigger_id: 'trigger-1', run_id: claim.run_id,
    claim_generation: recovered.claim_generation, claim_token: recovered.claim_token,
  }, NOW);
  assert.deepEqual(started, {
    started: false, run_id: claim.run_id, workflow_id: 'workflow-1', version_id: 'version-1', status: 'cancelled',
  });
  const advanced = await executeOperation(database, 'advance_claimed_trigger', {
    protocol_version: 1, trigger_id: 'trigger-1', claim_generation: recovered.claim_generation,
    claim_token: recovered.claim_token, next_run_at: 1_783_929_600,
  }, NOW);
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
