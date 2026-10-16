/* Durable Workflow trigger claims and event receipts. No payload or predicate plaintext crosses this boundary. */
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { websiteChanges } from './website_changes.js';
import { deliveryHistory } from './delivery_history.js';

const TRIGGERS = 'workflow_triggers';
const RUNS = 'workflow_runs';
const RECEIPTS = 'workflow_event_receipts';
const WORKFLOWS = 'workflows';
const VERSIONS = 'workflow_versions';
const PROTOCOL_VERSION = 1;
const CLAIM_LEASE_SECONDS = 120;
const MANUAL_RUN_RECLAIM_SECONDS = 1860;
const MANUAL_RUN_RECONCILE_GRACE_SECONDS = 180;
const ACTIVE_RUN_STATUSES = ['queued', 'running', 'waiting', 'cancellation_requested'];
const OPERATIONS = Object.freeze({
  health_check: new Set(['protocol_version']),
  list_due_triggers: new Set(['protocol_version', 'now', 'limit']),
  claim_due_trigger: new Set(['protocol_version', 'trigger_id']),
  accept_manual_run: new Set(['protocol_version', 'workflow_id', 'hashed_user_id', 'trigger_type', 'idempotency_key', 'encrypted_invocation_ref', 'invocation_hash']),
  start_accepted_run: new Set(['protocol_version', 'workflow_id', 'run_id', 'hashed_user_id', 'reclaim_after_seconds']),
  request_run_cancellation: new Set(['protocol_version', 'workflow_id', 'run_id', 'hashed_user_id']),
  start_claimed_run: new Set(['protocol_version', 'trigger_id', 'run_id', 'claim_generation', 'claim_token']),
  advance_claimed_trigger: new Set(['protocol_version', 'trigger_id', 'claim_generation', 'claim_token', 'next_run_at']),
  accept_event_trigger: new Set(['protocol_version', 'trigger_id', 'event_id', 'hashed_user_id', 'hashed_project_id', 'source', 'event_type']),
  reconcile_stale_workflow_state: new Set(['protocol_version', 'now', 'limit', 'queued_timeout_seconds', 'active_timeout_seconds', 'wait_default_timeout_seconds']),
});

export class WorkflowRuntimeError extends Error {
  constructor(status, code) { super(code); this.name = 'WorkflowRuntimeError'; this.status = status; this.code = code; }
}

const fail = (status, code) => { throw new WorkflowRuntimeError(status, code); };
const string = (value, code, max = 255) => {
  if (typeof value !== 'string' || !value || Buffer.byteLength(value, 'utf8') > max) fail(400, code);
  return value;
};
const integer = (value, code) => {
  if (!Number.isSafeInteger(value) || value < 0 || value > 2_147_483_647) fail(400, code);
  return value;
};
const bodyFor = (raw, operation) => {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) fail(400, 'invalid_request');
  const allowed = OPERATIONS[operation];
  if (!allowed || Object.keys(raw).some((key) => !allowed.has(key)) || raw.protocol_version !== PROTOCOL_VERSION) fail(400, 'invalid_request');
  return raw;
};
const tokenDigest = (value) => createHash('sha256').update(value, 'utf8').digest('hex');
const nowSeconds = (now) => Math.floor(now.getTime() / 1000);

const dueClaimIsActive = (trigger, current) => trigger.claim_status === 'claimed' && Number(trigger.claim_expires_at || 0) > current;

async function lockedTrigger(trx, triggerId) {
  const trigger = await trx(TRIGGERS).where({ trigger_id: triggerId }).forUpdate().first();
  if (!trigger) fail(404, 'trigger_not_found');
  return trigger;
}

async function activeScheduledRun(trx, trigger) {
  return trx(RUNS)
    .where({ workflow_id: trigger.workflow_id, trigger_id: trigger.trigger_id })
    .whereIn('status', ACTIVE_RUN_STATUSES)
    .first();
}

function activeClaim(trigger, now) {
  return trigger.claim_status === 'claimed' && Number(trigger.claim_expires_at || 0) > nowSeconds(now);
}

async function listDueTriggers(database, raw, now) {
  const body = bodyFor(raw, 'list_due_triggers');
  const current = integer(body.now ?? nowSeconds(now), 'invalid_now');
  const limit = integer(body.limit, 'invalid_limit');
  if (limit <= 0 || limit > 500) fail(400, 'invalid_limit');
  return database.transaction(async (trx) => {
    const rows = await trx(TRIGGERS)
      .where({ trigger_type: 'schedule', enabled: true })
      .where('next_run_at', '<=', current)
      .orderBy('next_run_at', 'asc')
      .orderBy('trigger_id', 'asc')
      .limit(limit);
    const triggerIds = [];
    for (const trigger of rows) {
      if (dueClaimIsActive(trigger, current) || await activeScheduledRun(trx, trigger)) continue;
      if (typeof trigger.trigger_id === 'string' && trigger.trigger_id) triggerIds.push(trigger.trigger_id);
    }
    return { trigger_ids: triggerIds };
  });
}

function acceptanceKey(trigger, occurrence) {
  return `sha256:${tokenDigest(`${trigger.trigger_id}:${trigger.version_id}:${occurrence}`)}`;
}

function manualAcceptanceKey(workflowId, ownerHash, triggerType, idempotencyKey) {
  return `sha256:${tokenDigest(`manual:${workflowId}:${ownerHash}:${triggerType}:${idempotencyKey}`)}`;
}

function queuedRun(trigger, idempotencyKey, claimTokenHash, now) {
  return {
    id: randomUUID(), run_id: randomUUID(), workflow_id: trigger.workflow_id, version_id: trigger.version_id,
    hashed_user_id: trigger.hashed_user_id, trigger_id: trigger.trigger_id, trigger_type: trigger.trigger_type,
    hashed_project_id: trigger.hashed_project_id || null,
    acceptance_idempotency_key: idempotencyKey, claim_token_hash: claimTokenHash, status: 'queued',
    accepted_at: nowSeconds(now), content_retention_mode: 'last_5', content_available: false,
  };
}

async function claimDueTrigger(database, raw, now) {
  const body = bodyFor(raw, 'claim_due_trigger');
  const triggerId = string(body.trigger_id, 'invalid_trigger_id');
  return database.transaction(async (trx) => {
    const trigger = await lockedTrigger(trx, triggerId);
    const current = nowSeconds(now);
    if (trigger.trigger_type !== 'schedule' || !trigger.enabled || !Number.isSafeInteger(trigger.next_run_at) || trigger.next_run_at > current) fail(409, 'trigger_not_due');
    if (!trigger.encrypted_schedule_config_ref) fail(409, 'encrypted_schedule_required');
    const ownerUserId = string(trigger.owner_user_id, 'owner_reference_required');
    const idempotencyKey = acceptanceKey(trigger, trigger.next_run_at);
    const existing = await trx(RUNS).where({ acceptance_idempotency_key: idempotencyKey }).first();
    const activeRun = await activeScheduledRun(trx, trigger);
    if (activeRun && activeRun.acceptance_idempotency_key !== idempotencyKey) {
      return { accepted: false, run_id: activeRun.run_id, workflow_id: activeRun.workflow_id, version_id: activeRun.version_id, hashed_user_id: activeRun.hashed_user_id, status: activeRun.status };
    }
    if (activeClaim(trigger, now)) {
      if (existing) return { accepted: false, run_id: existing.run_id, workflow_id: existing.workflow_id, version_id: existing.version_id, hashed_user_id: existing.hashed_user_id };
      fail(409, 'trigger_claimed');
    }
    if (existing?.status === 'running') return { accepted: false, run_id: existing.run_id, workflow_id: existing.workflow_id, version_id: existing.version_id, hashed_user_id: existing.hashed_user_id };
    const claimToken = randomBytes(32).toString('base64url');
    const claimTokenHash = tokenDigest(claimToken);
    const generation = Number(trigger.claim_generation || 0) + 1;
    const run = existing || queuedRun(trigger, idempotencyKey, claimTokenHash, now);
    if (existing) {
      await trx(RUNS).where({ run_id: run.run_id, status: 'queued' }).update({ claim_token_hash: claimTokenHash });
    } else {
      await trx(RUNS).insert(run);
    }
    const updated = await trx(TRIGGERS).where({ trigger_id: triggerId, claim_generation: trigger.claim_generation || 0 }).update({
      claim_status: 'claimed', claim_token_hash: claimTokenHash, claim_generation: generation,
      claimed_at: current, claim_expires_at: current + CLAIM_LEASE_SECONDS,
    });
    if (updated !== 1) fail(409, 'claim_conflict');
    return { accepted: true, recovered: Boolean(existing), run_id: run.run_id, workflow_id: run.workflow_id, version_id: run.version_id, hashed_user_id: run.hashed_user_id, owner_user_id: ownerUserId, encrypted_schedule_config_ref: trigger.encrypted_schedule_config_ref, claim_token: claimToken, claim_generation: generation };
  });
}

async function acceptManualRun(database, raw, now) {
  const body = bodyFor(raw, 'accept_manual_run');
  const workflowId = string(body.workflow_id, 'invalid_workflow_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const triggerType = string(body.trigger_type, 'invalid_trigger_type', 16);
  if (triggerType !== 'manual' && triggerType !== 'test') fail(400, 'invalid_trigger_type');
  const requestIdempotencyKey = string(body.idempotency_key, 'invalid_idempotency_key', 255);
  const invocationRef = body.encrypted_invocation_ref === undefined ? null : string(body.encrypted_invocation_ref, 'invalid_invocation_ref', 255);
  const invocationHash = body.invocation_hash === undefined ? null : string(body.invocation_hash, 'invalid_invocation_hash', 64);
  if ((invocationRef === null) !== (invocationHash === null)) fail(400, 'invalid_invocation');
  if (invocationRef && (!/^vault:\/\/workflows\/workflow_run_invocation\/[a-f0-9-]{36}$/.test(invocationRef) || !/^[a-f0-9]{64}$/.test(invocationHash))) fail(400, 'invalid_invocation');
  const idempotencyKey = manualAcceptanceKey(workflowId, ownerHash, triggerType, requestIdempotencyKey);
  return database.transaction(async (trx) => {
    const workflow = await trx(WORKFLOWS).where({ workflow_id: workflowId, hashed_user_id: ownerHash }).forUpdate().first();
    if (!workflow || workflow.status === 'deleted') fail(404, 'workflow_not_found');

    if (invocationRef) {
      const blob = await trx('workflow_encrypted_blobs').where({ ref: invocationRef, hashed_user_id: ownerHash, kind: 'workflow_run_invocation' }).first();
      if (!blob) fail(403, 'invocation_not_owned');
    }

    const existing = await trx(RUNS).where({ acceptance_idempotency_key: idempotencyKey }).first();
    if (existing) {
      if ((existing.invocation_hash || null) !== invocationHash) fail(409, 'run_invocation_conflict');
      return {
        accepted: false, run_id: existing.run_id, workflow_id: existing.workflow_id,
        version_id: existing.version_id, status: existing.status,
      };
    }

    const versionId = string(workflow.current_version_id, 'workflow_version_required');
    const version = await trx(VERSIONS).where({ version_id: versionId, workflow_id: workflowId, hashed_user_id: ownerHash }).forUpdate().first();
    if (!version) fail(409, 'workflow_version_not_found');

    const run = {
      id: randomUUID(), run_id: randomUUID(), workflow_id: workflowId, version_id: versionId,
      hashed_user_id: ownerHash, hashed_project_id: null, trigger_id: null, trigger_type: triggerType,
      acceptance_idempotency_key: idempotencyKey, claim_token_hash: null, status: 'queued',
      accepted_at: nowSeconds(now), content_retention_mode: 'last_5', content_available: false,
      encrypted_invocation_ref: invocationRef, invocation_hash: invocationHash,
    };
    await trx(RUNS).insert(run);
    return { accepted: true, run_id: run.run_id, workflow_id: workflowId, version_id: versionId, status: run.status };
  });
}

async function startAcceptedRun(database, raw, now) {
  const body = bodyFor(raw, 'start_accepted_run');
  const workflowId = string(body.workflow_id, 'invalid_workflow_id');
  const runId = string(body.run_id, 'invalid_run_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  return database.transaction(async (trx) => {
    const run = await trx(RUNS).where({ run_id: runId, workflow_id: workflowId, hashed_user_id: ownerHash }).forUpdate().first();
    if (!run) fail(404, 'run_not_found');
    if (!['manual', 'test'].includes(run.trigger_type)) fail(409, 'run_requires_trigger_claim');
    const requestedReclaim = body.reclaim_after_seconds === undefined
      ? MANUAL_RUN_RECLAIM_SECONDS : integer(body.reclaim_after_seconds, 'invalid_reclaim_timeout');
    if (requestedReclaim < 120 || requestedReclaim > 14400) fail(400, 'invalid_reclaim_timeout');
    const reclaimAfter = Number(run.reclaim_after_seconds || requestedReclaim);
    if (run.reclaim_after_seconds && requestedReclaim !== reclaimAfter) fail(409, 'reclaim_timeout_conflict');
    if (run.status === 'running' && Number(run.started_at || 0) + reclaimAfter <= nowSeconds(now)) {
      const generation = Number(run.manual_recovery_generation || 0) + 1;
      const updated = await trx(RUNS).where({ run_id: runId, status: 'running', started_at: run.started_at }).update({
        started_at: nowSeconds(now), manual_recovery_generation: generation, last_recovered_at: nowSeconds(now),
      });
      if (updated !== 1) fail(409, 'start_conflict');
      return { started: true, recovered: true, recovery_generation: generation, run_id: run.run_id,
        workflow_id: run.workflow_id, version_id: run.version_id, status: 'running' };
    }
    if (run.status === 'running' || run.status === 'cancellation_requested' || run.status === 'cancelled' || run.status === 'completed' || run.status === 'failed') {
      return { started: false, run_id: run.run_id, workflow_id: run.workflow_id, version_id: run.version_id, status: run.status };
    }
    if (run.status !== 'queued') fail(409, 'run_not_startable');
    const updated = await trx(RUNS).where({ run_id: runId, status: 'queued' }).update({
      status: 'running', started_at: nowSeconds(now), reclaim_after_seconds: reclaimAfter,
    });
    if (updated !== 1) fail(409, 'start_conflict');
    return { started: true, run_id: run.run_id, workflow_id: run.workflow_id, version_id: run.version_id, status: 'running' };
  });
}

async function requestRunCancellation(database, raw, now) {
  const body = bodyFor(raw, 'request_run_cancellation');
  const workflowId = string(body.workflow_id, 'invalid_workflow_id');
  const runId = string(body.run_id, 'invalid_run_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  return database.transaction(async (trx) => {
    const run = await trx(RUNS).where({ run_id: runId, workflow_id: workflowId, hashed_user_id: ownerHash }).forUpdate().first();
    if (!run) fail(404, 'run_not_found');
    if (run.status === 'cancellation_requested' || run.status === 'cancelled') {
      return { run_id: run.run_id, status: run.status };
    }
    if (!['queued', 'running', 'waiting'].includes(run.status)) fail(400, 'run_not_cancellable');
    const requestedAt = nowSeconds(now);
    const cancelledBeforeStart = run.status === 'queued';
    const status = cancelledBeforeStart ? 'cancelled' : 'cancellation_requested';
    const updated = await trx(RUNS).where({ run_id: runId, status: run.status }).update({
      status, cancellation_requested_at: requestedAt, cancelled_at: cancelledBeforeStart ? requestedAt : null, cancelled_by_hash: ownerHash,
    });
    if (updated !== 1) fail(409, 'cancellation_conflict');
    if (cancelledBeforeStart && run.trigger_type === 'schedule' && run.trigger_id) {
      const trigger = await lockedTrigger(trx, run.trigger_id);
      if (trigger.claim_token_hash === run.claim_token_hash) {
        await trx(TRIGGERS).where({ trigger_id: run.trigger_id, claim_generation: trigger.claim_generation }).update({
          claim_status: null, claim_token_hash: null, claimed_at: null, claim_expires_at: null,
        });
      }
      return { run_id: run.run_id, status, trigger_id: run.trigger_id, requeue_scheduled_trigger: true };
    }
    return { run_id: run.run_id, status };
  });
}

async function startClaimedRun(database, raw, now) {
  const body = bodyFor(raw, 'start_claimed_run');
  const triggerId = string(body.trigger_id, 'invalid_trigger_id');
  const runId = string(body.run_id, 'invalid_run_id');
  const generation = integer(body.claim_generation, 'invalid_claim_generation');
  const claimToken = string(body.claim_token, 'invalid_claim_token', 64);
  const claimTokenHash = tokenDigest(claimToken);
  return database.transaction(async (trx) => {
    const trigger = await lockedTrigger(trx, triggerId);
    if (!activeClaim(trigger, now) || trigger.claim_generation !== generation || trigger.claim_token_hash !== claimTokenHash) fail(409, 'stale_claim');
    const run = await trx(RUNS).where({ run_id: runId, trigger_id: triggerId }).forUpdate().first();
    if (!run) {
      await trx(TRIGGERS).where({ trigger_id: triggerId, claim_generation: generation }).update({
        claim_status: null, claim_token_hash: null, claimed_at: null, claim_expires_at: null,
      });
      return { started: false, run_id: runId, status: 'missing_run', stale_claim_released: true };
    }
    if (['running', 'cancellation_requested', 'cancelled', 'completed', 'failed'].includes(run.status)) {
      return { started: false, run_id: run.run_id, workflow_id: run.workflow_id, version_id: run.version_id, status: run.status };
    }
    if (run.status !== 'queued' || run.claim_token_hash !== claimTokenHash) fail(409, 'stale_claim');
    const updated = await trx(RUNS).where({ run_id: runId, status: 'queued', claim_token_hash: claimTokenHash }).update({ status: 'running', started_at: nowSeconds(now) });
    if (updated !== 1) fail(409, 'start_conflict');
    return { started: true, run_id: run.run_id, workflow_id: run.workflow_id, version_id: run.version_id, encrypted_schedule_config_ref: trigger.encrypted_schedule_config_ref };
  });
}

async function advanceClaimedTrigger(database, raw, now) {
  const body = bodyFor(raw, 'advance_claimed_trigger');
  const triggerId = string(body.trigger_id, 'invalid_trigger_id');
  const generation = integer(body.claim_generation, 'invalid_claim_generation');
  const claimToken = string(body.claim_token, 'invalid_claim_token', 64);
  const nextRunAt = integer(body.next_run_at, 'invalid_next_run_at');
  return database.transaction(async (trx) => {
    const trigger = await lockedTrigger(trx, triggerId);
    if (!activeClaim(trigger, now) || trigger.claim_generation !== generation || trigger.claim_token_hash !== tokenDigest(claimToken)) fail(409, 'stale_claim');
    const completesOneTimeTrigger = nextRunAt === 0;
    if (!completesOneTimeTrigger && nextRunAt <= Number(trigger.next_run_at || 0)) fail(409, 'invalid_next_run_at');
    await trx(TRIGGERS).where({ trigger_id: triggerId, claim_generation: generation }).update({
      next_run_at: completesOneTimeTrigger ? null : nextRunAt, enabled: completesOneTimeTrigger ? false : trigger.enabled,
      claim_status: null, claim_token_hash: null, claimed_at: null, claim_expires_at: null,
    });
    return { trigger_id: triggerId, next_run_at: completesOneTimeTrigger ? null : nextRunAt, completed: completesOneTimeTrigger };
  });
}

async function acceptEventTrigger(database, raw, now) {
  const body = bodyFor(raw, 'accept_event_trigger');
  const triggerId = string(body.trigger_id, 'invalid_trigger_id');
  const eventId = string(body.event_id, 'invalid_event_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const projectHash = string(body.hashed_project_id, 'invalid_project', 128);
  const source = string(body.source, 'invalid_source', 64);
  const eventType = string(body.event_type, 'invalid_event_type', 128);
  return database.transaction(async (trx) => {
    const trigger = await lockedTrigger(trx, triggerId);
    if (!trigger.enabled || trigger.trigger_type !== 'event' || trigger.hashed_user_id !== ownerHash || trigger.hashed_project_id !== projectHash || trigger.source !== source || trigger.event_type !== eventType) fail(409, 'event_trigger_mismatch');
    const receipt = await trx(RECEIPTS).where({ trigger_id: triggerId, event_id: eventId }).forUpdate().first();
    if (receipt) return { accepted: false, run_id: receipt.run_id || null };
    const idempotencyKey = acceptanceKey(trigger, `event:${eventId}`);
    const existing = await trx(RUNS).where({ acceptance_idempotency_key: idempotencyKey }).first();
    if (existing) return { accepted: false, run_id: existing.run_id };
    const run = queuedRun(trigger, idempotencyKey, null, now);
    await trx(RUNS).insert(run);
    await trx(RECEIPTS).insert({
      id: randomUUID(), trigger_id: triggerId, event_id: eventId, hashed_user_id: ownerHash,
      source, event_type: eventType, dispatch_status: 'accepted', run_id: run.run_id, created_at: nowSeconds(now),
    });
    return { accepted: true, run_id: run.run_id, version_id: run.version_id };
  });
}

async function reconcileStaleWorkflowState(database, raw, now) {
  const body = bodyFor(raw, 'reconcile_stale_workflow_state');
  const current = integer(body.now ?? nowSeconds(now), 'invalid_now');
  const limit = integer(body.limit, 'invalid_limit');
  const queuedTimeout = integer(body.queued_timeout_seconds, 'invalid_timeout');
  const activeTimeout = integer(body.active_timeout_seconds, 'invalid_timeout');
  const waitDefaultTimeout = integer(body.wait_default_timeout_seconds, 'invalid_timeout');
  if (!limit || limit > 500 || !queuedTimeout || !activeTimeout || !waitDefaultTimeout) fail(400, 'invalid_limit');
  return database.transaction(async (trx) => {
    const finished = [];
    let offset = 0;
    while (finished.length < limit) {
      const candidates = await trx(RUNS).whereIn('status', ACTIVE_RUN_STATUSES)
        .orderBy('accepted_at', 'asc').orderBy('run_id', 'asc').limit(limit).offset(offset);
      if (!candidates.length) break;
      offset += candidates.length;
      let terminalizedThisPage = 0;
      for (const candidate of candidates) {
      const run = await trx(RUNS).where({ run_id: candidate.run_id }).forUpdate().first();
      if (!run || !ACTIVE_RUN_STATUSES.includes(run.status)) continue;
      const acceptedAt = Number(run.accepted_at || run.started_at || 0);
      const startedAt = Number(run.started_at || acceptedAt);
      const requestedAt = Number(run.cancellation_requested_at || startedAt);
      const waitExpiresAt = Number(run.record_json?.wait_expires_at || startedAt + waitDefaultTimeout);
      const due = run.status === 'queued' ? acceptedAt + queuedTimeout <= current
        : run.status === 'running' ? startedAt + (
          ['manual', 'test'].includes(run.trigger_type)
            ? Math.max(activeTimeout, Number(run.reclaim_after_seconds || MANUAL_RUN_RECLAIM_SECONDS) + MANUAL_RUN_RECONCILE_GRACE_SECONDS)
            : activeTimeout
        ) <= current
        : run.status === 'waiting' ? waitExpiresAt <= current
        : Math.min(startedAt + activeTimeout, requestedAt + queuedTimeout) <= current;
      if (!due) continue;
      const status = run.status === 'cancellation_requested' ? 'cancelled' : 'failed';
      const reason = status === 'cancelled' ? 'Workflow cancellation completed after the worker stopped'
        : run.status === 'waiting' ? 'Workflow user response timed out'
        : run.status === 'queued' ? 'Workflow execution did not start in time'
        : 'Workflow execution timed out';
      const record = run.record_json ? { ...run.record_json, status, finished_at: current,
        error_summary: reason, wait_expires_at: null } : null;
      await trx(RUNS).where({ id: run.id }).update({ status, finished_at: current, error_summary: reason,
        cancelled_at: status === 'cancelled' ? current : run.cancelled_at, record_json: record });
      const deliveryScope = { workflow_id: run.workflow_id, run_id: run.run_id,
        hashed_user_id: String(run.hashed_user_id || '').replace(/^user_sha256:/, '') };
      const pending = await trx('workflow_chat_deliveries').where(deliveryScope).whereIn('status', ['delivery_pending', 'claimed']);
      const persistedIds = new Set(pending.filter((delivery) => delivery.client_persisted_at).map((delivery) => delivery.delivery_id));
      for (const delivery of pending) {
        if (delivery.client_persisted_at) continue;
        await trx('workflow_chat_deliveries').where({ id: delivery.id }).update({ status: 'cancelled', cancelled_at: current,
          encrypted_payload: '', claim_generation: Number(delivery.claim_generation || 0) + 1,
          claim_token_hash: null, revision: Number(delivery.revision || 0) + 1 });
      }
      const reservations = await trx('workflow_delivery_history').where({ workflow_id: run.workflow_id,
        run_id: run.run_id, hashed_user_id: run.hashed_user_id, status: 'reserved' });
      for (const reservation of reservations) {
        if (!persistedIds.has(reservation.delivery_id)) await trx('workflow_delivery_history').where({ id: reservation.id }).del();
      }
      finished.push(run.run_id);
      terminalizedThisPage += 1;
      if (finished.length >= limit) break;
      }
      // The candidate set shrinks as terminal rows are written. Revisit the
      // current page position so those shifts cannot hide the next live run.
      offset -= terminalizedThisPage;
      if (offset < 0) offset = 0;
    }
    const expired = [];
    let deliveryOffset = 0;
    while (expired.length < limit) {
      const dueDeliveries = await trx('workflow_chat_deliveries').whereIn('status', ['delivery_pending', 'claimed'])
        .where('expires_at', '<=', current).orderBy('expires_at', 'asc').orderBy('delivery_id', 'asc')
        .limit(limit).offset(deliveryOffset);
      if (!dueDeliveries.length) break;
      deliveryOffset += dueDeliveries.length;
      let expiredThisPage = 0;
      for (const candidate of dueDeliveries) {
      const delivery = await trx('workflow_chat_deliveries').where({ delivery_id: candidate.delivery_id }).forUpdate().first();
      if (!delivery || !['delivery_pending', 'claimed'].includes(delivery.status)
          || delivery.expires_at === null || delivery.expires_at === undefined
          || delivery.expires_at > current) continue;
      if (delivery.client_persisted_at) {
        if (delivery.encrypted_payload) await trx('workflow_chat_deliveries').where({ id: delivery.id }).update({ encrypted_payload: '' });
        continue;
      }
      await trx('workflow_chat_deliveries').where({ id: delivery.id }).update({ status: 'expired', expired_at: current,
        encrypted_payload: '', claim_generation: Number(delivery.claim_generation || 0) + 1,
        claim_token_hash: null, claim_issued_at: null, claim_expires_at: null, claim_device_id: null,
        revision: Number(delivery.revision || 0) + 1 });
      await trx('workflow_delivery_history').where({ delivery_id: delivery.delivery_id, status: 'reserved' }).del();
      expired.push(delivery.delivery_id);
      expiredThisPage += 1;
      if (expired.length >= limit) break;
      }
      deliveryOffset -= expiredThisPage;
    }
    return { finished_run_ids: finished, expired_delivery_ids: expired };
  });
}

const handlers = Object.freeze({ list_due_triggers: listDueTriggers, claim_due_trigger: claimDueTrigger, accept_manual_run: acceptManualRun, start_accepted_run: startAcceptedRun, request_run_cancellation: requestRunCancellation, start_claimed_run: startClaimedRun, advance_claimed_trigger: advanceClaimedTrigger, accept_event_trigger: acceptEventTrigger, reconcile_stale_workflow_state: reconcileStaleWorkflowState });
export async function executeOperation(database, operation, body, now = new Date()) {
  if (operation === 'website_changes') return websiteChanges(database, body, now, fail);
  if (operation === 'delivery_history') return deliveryHistory(database, body, now, fail);
  if (operation === 'health_check') {
    bodyFor(body, operation);
    return { ready: true };
  }
  const handler = handlers[operation];
  if (!handler) fail(400, 'unsupported_operation');
  return handler(database, body, now);
}
