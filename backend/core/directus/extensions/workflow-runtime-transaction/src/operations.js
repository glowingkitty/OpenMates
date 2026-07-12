/* Durable Workflow trigger claims and event receipts. No payload or predicate plaintext crosses this boundary. */
import { createHash, randomBytes, randomUUID } from 'node:crypto';

const TRIGGERS = 'workflow_triggers';
const RUNS = 'workflow_runs';
const RECEIPTS = 'workflow_event_receipts';
const PROTOCOL_VERSION = 1;
const CLAIM_LEASE_SECONDS = 120;
const OPERATIONS = Object.freeze({
  health_check: new Set(['protocol_version']),
  claim_due_trigger: new Set(['protocol_version', 'trigger_id']),
  start_claimed_run: new Set(['protocol_version', 'trigger_id', 'run_id', 'claim_generation', 'claim_token']),
  advance_claimed_trigger: new Set(['protocol_version', 'trigger_id', 'claim_generation', 'claim_token', 'next_run_at']),
  accept_event_trigger: new Set(['protocol_version', 'trigger_id', 'event_id', 'hashed_user_id', 'hashed_project_id', 'source', 'event_type']),
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

async function lockedTrigger(trx, triggerId) {
  const trigger = await trx(TRIGGERS).where({ trigger_id: triggerId }).forUpdate().first();
  if (!trigger) fail(404, 'trigger_not_found');
  return trigger;
}

function activeClaim(trigger, now) {
  return trigger.claim_status === 'claimed' && Number(trigger.claim_expires_at || 0) > nowSeconds(now);
}

function acceptanceKey(trigger, occurrence) {
  return `sha256:${tokenDigest(`${trigger.trigger_id}:${trigger.version_id}:${occurrence}`)}`;
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
    const idempotencyKey = acceptanceKey(trigger, trigger.next_run_at);
    const existing = await trx(RUNS).where({ acceptance_idempotency_key: idempotencyKey }).first();
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
    return { accepted: !existing, run_id: run.run_id, workflow_id: run.workflow_id, version_id: run.version_id, hashed_user_id: run.hashed_user_id, encrypted_schedule_config_ref: trigger.encrypted_schedule_config_ref, claim_token: claimToken, claim_generation: generation };
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
    if (!run) fail(404, 'run_not_found');
    if (run.status === 'running') return { started: false, run_id: run.run_id, workflow_id: run.workflow_id, version_id: run.version_id };
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
    if (nextRunAt <= Number(trigger.next_run_at || 0)) fail(409, 'invalid_next_run_at');
    await trx(TRIGGERS).where({ trigger_id: triggerId, claim_generation: generation }).update({
      next_run_at: nextRunAt, claim_status: null, claim_token_hash: null, claimed_at: null, claim_expires_at: null,
    });
    return { trigger_id: triggerId, next_run_at: nextRunAt };
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

const handlers = Object.freeze({ claim_due_trigger: claimDueTrigger, start_claimed_run: startClaimedRun, advance_claimed_trigger: advanceClaimedTrigger, accept_event_trigger: acceptEventTrigger });
export async function executeOperation(database, operation, body, now = new Date()) {
  if (operation === 'health_check') {
    bodyFor(body, operation);
    return { ready: true };
  }
  const handler = handlers[operation];
  if (!handler) fail(400, 'unsupported_operation');
  return handler(database, body, now);
}
