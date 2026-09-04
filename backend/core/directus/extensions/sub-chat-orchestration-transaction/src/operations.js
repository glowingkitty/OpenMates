/*
 * PostgreSQL-backed root limits and atomic encrypted-safe child preparation.
 * Payload validation rejects content-bearing fields before any database write.
 */
import { createHash, randomUUID } from 'node:crypto';

const ORCHESTRATIONS = 'sub_chat_orchestrations';
const CHILDREN = 'sub_chat_orchestration_children';
const BATCHES = 'sub_chat_orchestration_batches';
const OPERATIONS = 'sub_chat_orchestration_operations';
const CHATS = 'chats';
const USERS = 'directus_users';
const CHARGE_IDENTITIES = 'billing_charge_identities';
const REFUND_IDENTITIES = 'billing_refund_identities';
const SETTLEMENT_OUTBOX = 'billing_settlement_outbox';
const SETTLEMENT_RETRY_DELAYS_MS = [5_000, 30_000, 120_000, 300_000];
const USAGE = 'usage';
const TEAM_ACCOUNTS = 'team_credit_accounts';
const TEAM_CREDIT_EVENTS = 'team_credit_events';
const TEAM_USAGE_EVENTS = 'team_usage_events';
const PROTOCOL_VERSION = 1;
const MAX_DEPTH = 2;
const AUTO_DESCENDANT_LIMIT = 3;
const MAX_DESCENDANT_LIMIT = 20;
const AUTO_CREDIT_LIMIT = 2_000;
const ROOT_TTL_MS = 24 * 60 * 60_000;
const TERMINAL_ROOT_STATES = new Set(['completed', 'failed', 'cancelled', 'expired']);
const CHILD_STATES = new Set(['prepared', 'dispatched', 'running', 'completed', 'failed', 'cancelled']);
const PRIVATE_CHILD_FIELDS = new Set([
  'prompt', 'prompt_template', 'title', 'summary', 'report', 'chat_key', 'encrypted_chat_key',
]);
const OPERATION_FIELDS = Object.freeze({
  health_check: new Set(['protocol_version']),
  create_root: new Set([
    'protocol_version', 'orchestration_id', 'hashed_user_id', 'hashed_team_id',
    'root_chat_id', 'root_turn_id', 'descendant_limit', 'credit_limit',
  ]),
  approve_root_limits: new Set([
    'protocol_version', 'orchestration_id', 'hashed_user_id', 'descendant_limit', 'credit_limit',
  ]),
  prepare_batch: new Set([
    'protocol_version', 'orchestration_id', 'hashed_user_id', 'batch_id',
    'parent_chat_id', 'parent_depth', 'is_continuation', 'children',
  ]),
  claim_child: new Set([
    'protocol_version', 'orchestration_id', 'hashed_user_id', 'child_chat_id',
    'dispatch_token', 'inference_task_id', 'is_continuation',
  ]),
  transition_child: new Set([
    'protocol_version', 'orchestration_id', 'hashed_user_id', 'child_chat_id', 'state',
  ]),
  transition_root: new Set([
    'protocol_version', 'orchestration_id', 'hashed_user_id', 'state',
  ]),
  claim_parent_continuation: new Set([
    'protocol_version', 'orchestration_id', 'hashed_user_id', 'batch_id',
  ]),
  mark_parent_continuation_dispatched: new Set([
    'protocol_version', 'orchestration_id', 'hashed_user_id', 'batch_id', 'continuation_task_id',
  ]),
  get_root_state: new Set(['protocol_version', 'orchestration_id', 'hashed_user_id']),
  reserve_operation: new Set([
    'protocol_version', 'operation_id', 'charge_id', 'orchestration_id', 'hashed_user_id',
    'root_chat_id', 'actual_chat_id', 'depth', 'app_id', 'skill_id', 'phase', 'quoted_credits',
  ]),
  fail_operation: new Set([
    'protocol_version', 'operation_id', 'orchestration_id', 'hashed_user_id',
  ]),
  cleanup_expired_reservations: new Set(['protocol_version']),
  commit_personal_charge: new Set([
    'protocol_version', 'charge_id', 'user_id', 'hashed_user_id', 'app_id', 'skill_id',
    'requested_credits', 'charged_credits', 'expected_encrypted_balance', 'new_encrypted_balance', 'usage_entry',
  ]),
  commit_personal_refund: new Set([
    'protocol_version', 'refund_id', 'user_id', 'hashed_user_id', 'app_id', 'skill_id', 'credits_to_refund',
    'expected_encrypted_balance', 'new_encrypted_balance',
  ]),
  get_personal_charge: new Set([
    'protocol_version', 'charge_id', 'hashed_user_id', 'app_id', 'skill_id', 'requested_credits',
  ]),
  create_or_reuse_pending_settlement: new Set([
    'protocol_version', 'charge_id', 'user_id', 'hashed_user_id', 'vault_key_id',
    'encrypted_settlement_payload', 'settlement_payload_hash', 'retryable_error_code',
  ]),
  get_pending_settlement: new Set([
    'protocol_version', 'outbox_id', 'charge_id', 'hashed_user_id',
  ]),
  replay_pending_settlement: new Set([
    'protocol_version', 'outbox_id', 'charge_id', 'hashed_user_id',
  ]),
  complete_pending_settlement: new Set([
    'protocol_version', 'outbox_id', 'charge_id', 'hashed_user_id',
  ]),
  transition_pending_settlement_to_manual_review: new Set([
    'protocol_version', 'outbox_id', 'charge_id', 'hashed_user_id', 'attempts',
    'retryable_error_code',
  ]),
  commit_team_charge: new Set([
    'protocol_version', 'event_id', 'hashed_team_id', 'actor_user_hash', 'credits',
    'expected_version', 'encrypted_balance', 'workspace_type', 'object_id_hash',
    'encrypted_metadata', 'occurred_at', 'orchestration_id',
  ]),
  commit_team_credit_add: new Set([
    'protocol_version', 'event_id', 'hashed_team_id', 'actor_user_hash', 'credits',
    'expected_version', 'encrypted_balance', 'event_type', 'encrypted_metadata', 'occurred_at',
  ]),
});
const CHILD_FIELDS = new Set(['child_chat_id', 'user_message_id', 'dispatch_token', 'budget_limit']);
const USAGE_FIELDS = new Set([
  'id', 'user_id_hash', 'app_id', 'skill_id', 'type', 'source', 'created_at', 'updated_at',
  'encrypted_credits_costs_total', 'chat_id', 'root_chat_id', 'actual_chat_id', 'root_turn_id',
  'orchestration_id', 'depth', 'charge_id', 'operation_id', 'message_id',
  'api_key_hash', 'device_hash', 'encrypted_model_used', 'encrypted_input_tokens',
  'encrypted_output_tokens', 'encrypted_user_input_tokens', 'encrypted_system_prompt_tokens',
  'encrypted_credits_costs_system_prompt', 'encrypted_credits_costs_history',
  'encrypted_credits_costs_response', 'encrypted_server_provider', 'encrypted_server_region',
  'encrypted_code_run_filenames', 'encrypted_code_run_duration_seconds', 'tool_inference_iterations',
]);

export class SubChatOrchestrationError extends Error {
  constructor(status, code) {
    super(code);
    this.name = 'SubChatOrchestrationError';
    this.status = status;
    this.code = code;
  }
}

const fail = (status, code) => { throw new SubChatOrchestrationError(status, code); };
const object = (value) => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail(400, 'invalid_request');
  return value;
};
const string = (value, code, max = 255) => {
  if (typeof value !== 'string' || !value || Buffer.byteLength(value, 'utf8') > max) fail(400, code);
  return value;
};
const integer = (value, code) => {
  if (!Number.isSafeInteger(value) || value < 0 || value > 2_147_483_647) fail(400, code);
  return value;
};
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const uuid = (value, code) => {
  const result = string(value, code, 36);
  if (!UUID_RE.test(result)) fail(400, code);
  return result;
};
const tokenHash = (value) => createHash('sha256').update(value, 'utf8').digest('hex');
const operationBody = (raw, operation) => {
  const body = object(raw);
  const allowed = OPERATION_FIELDS[operation];
  if (!allowed || Object.keys(body).some((key) => !allowed.has(key))) fail(400, 'invalid_request');
  if (body.protocol_version !== PROTOCOL_VERSION) fail(426, 'client_update_required');
  return body;
};
const rootResponse = (row) => ({
  orchestration_id: row.id,
  root_chat_id: row.root_chat_id,
  root_turn_id: row.root_turn_id,
  max_depth: row.max_depth,
  descendant_limit: row.descendant_limit,
  descendant_count: row.descendant_count,
  credit_limit: row.credit_limit,
  reserved_credits: row.reserved_credits,
  spent_credits: row.spent_credits,
  approved: row.approved,
  status: row.status,
  version: row.version,
});
const operationReservationFits = (root, quotedCredits) => (
  root.spent_credits + root.reserved_credits + quotedCredits <= root.credit_limit
);
const reservedOperationResponse = (row, idempotent) => ({
  operation_id: row.operation_id,
  charge_id: row.charge_id,
  orchestration_id: row.orchestration_id,
  quoted_credits: row.quoted_credits,
  actual_credits: row.actual_credits,
  state: row.state,
  idempotent,
});

function assertOperationIdentity(row, identity) {
  for (const [key, value] of Object.entries(identity)) {
    if (row[key] !== value) fail(409, 'operation_identity_mismatch');
  }
}

function validatedChildren(rawChildren) {
  if (!Array.isArray(rawChildren) || rawChildren.length === 0 || rawChildren.length > MAX_DESCENDANT_LIMIT) {
    fail(400, 'invalid_children');
  }
  const ids = new Set();
  return rawChildren.map((raw) => {
    const child = object(raw);
    if (Object.keys(child).some((key) => !CHILD_FIELDS.has(key) || PRIVATE_CHILD_FIELDS.has(key))) {
      fail(400, 'private_child_field_forbidden');
    }
    const childChatId = uuid(child.child_chat_id, 'invalid_child_chat_id');
    if (ids.has(childChatId)) fail(409, 'duplicate_child_chat');
    ids.add(childChatId);
    const budgetLimit = child.budget_limit == null ? null : integer(child.budget_limit, 'invalid_budget_limit');
    return {
      child_chat_id: childChatId,
      user_message_id: string(child.user_message_id, 'invalid_message_id'),
      dispatch_token: string(child.dispatch_token, 'invalid_dispatch_token', 255),
      budget_limit: budgetLimit,
    };
  });
}

async function lockedRoot(trx, orchestrationId, ownerHash) {
  const row = await trx(ORCHESTRATIONS).where({ id: orchestrationId }).forUpdate().first();
  if (!row || row.hashed_user_id !== ownerHash) fail(404, 'orchestration_not_found');
  return row;
}

async function lockedTeamAccount(trx, teamHash) {
  const accounts = await trx(TEAM_ACCOUNTS).where({ hashed_team_id: teamHash }).forUpdate().limit(2);
  if (!accounts.length) fail(404, 'team_credit_account_not_found');
  if (accounts.length > 1) fail(409, 'duplicate_team_credit_accounts');
  return accounts[0];
}

async function healthCheck(database, raw) {
  operationBody(raw, 'health_check');
  await database.raw('SELECT 1');
  return { status: 'ok', protocol_version: PROTOCOL_VERSION };
}

async function createRoot(database, raw, now) {
  const body = operationBody(raw, 'create_root');
  const id = uuid(body.orchestration_id, 'invalid_orchestration_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const teamHash = body.hashed_team_id == null ? null : string(body.hashed_team_id, 'invalid_team', 64);
  const rootChatId = uuid(body.root_chat_id, 'invalid_root_chat_id');
  const rootTurnId = uuid(body.root_turn_id, 'invalid_root_turn_id');
  const descendantLimit = integer(body.descendant_limit ?? AUTO_DESCENDANT_LIMIT, 'invalid_descendant_limit');
  const creditLimit = integer(body.credit_limit ?? AUTO_CREDIT_LIMIT, 'invalid_credit_limit');
  if (descendantLimit > AUTO_DESCENDANT_LIMIT || creditLimit > AUTO_CREDIT_LIMIT) fail(403, 'root_approval_required');
  return database.transaction(async (trx) => {
    const existing = await trx(ORCHESTRATIONS).where({ id }).forUpdate().first();
    if (existing) {
      if (existing.hashed_user_id !== ownerHash || existing.root_chat_id !== rootChatId
        || existing.root_turn_id !== rootTurnId || existing.hashed_team_id !== teamHash) {
        fail(409, 'orchestration_identity_mismatch');
      }
      return rootResponse(existing);
    }
    const row = {
      id, hashed_user_id: ownerHash, hashed_team_id: teamHash,
      root_chat_id: rootChatId, root_turn_id: rootTurnId, max_depth: MAX_DEPTH,
      descendant_limit: descendantLimit, descendant_count: 0,
      credit_limit: creditLimit, reserved_credits: 0, spent_credits: 0,
      approved: false, status: 'active', version: 1,
      created_at: now, updated_at: now, expires_at: new Date(now.getTime() + ROOT_TTL_MS),
    };
    await trx(ORCHESTRATIONS).insert(row);
    return rootResponse(row);
  });
}

async function approveRootLimits(database, raw, now) {
  const body = operationBody(raw, 'approve_root_limits');
  const id = uuid(body.orchestration_id, 'invalid_orchestration_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const descendantLimit = integer(body.descendant_limit, 'invalid_descendant_limit');
  const creditLimit = integer(body.credit_limit, 'invalid_credit_limit');
  if (descendantLimit <= AUTO_DESCENDANT_LIMIT || descendantLimit > MAX_DESCENDANT_LIMIT
    || creditLimit <= 0) fail(400, 'invalid_approved_limits');
  return database.transaction(async (trx) => {
    const row = await lockedRoot(trx, id, ownerHash);
    if (row.status !== 'active') fail(409, 'orchestration_not_active');
    if (descendantLimit < row.descendant_count || creditLimit < row.spent_credits + row.reserved_credits) {
      fail(409, 'approved_limits_below_usage');
    }
    const update = {
      descendant_limit: descendantLimit, credit_limit: creditLimit,
      approved: true, version: row.version + 1, updated_at: now,
    };
    await trx(ORCHESTRATIONS).where({ id, version: row.version }).update(update);
    return rootResponse({ ...row, ...update });
  });
}

async function prepareBatch(database, raw, now) {
  const body = operationBody(raw, 'prepare_batch');
  const orchestrationId = uuid(body.orchestration_id, 'invalid_orchestration_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const batchId = uuid(body.batch_id, 'invalid_batch_id');
  const parentChatId = uuid(body.parent_chat_id, 'invalid_parent_chat_id');
  const parentDepth = integer(body.parent_depth, 'invalid_parent_depth');
  if (body.is_continuation !== false) fail(409, 'continuation_spawn_forbidden');
  const children = validatedChildren(body.children);
  return database.transaction(async (trx) => {
    const root = await lockedRoot(trx, orchestrationId, ownerHash);
    if (root.status !== 'active' || new Date(root.expires_at) <= now) fail(409, 'orchestration_not_active');
    if (parentDepth >= root.max_depth) fail(409, 'maximum_depth_reached');
    if (parentDepth === 0 && parentChatId !== root.root_chat_id) fail(409, 'parent_identity_mismatch');
    if (parentDepth > 0) {
      const parent = await trx(CHILDREN).where({ orchestration_id: orchestrationId, child_chat_id: parentChatId }).first();
      if (!parent || parent.depth !== parentDepth || !['dispatched', 'running'].includes(parent.state)) {
        fail(409, 'parent_not_authorized');
      }
    }
    const existing = await trx(CHILDREN).where({ orchestration_id: orchestrationId, batch_id: batchId });
    if (existing.length) {
      const requested = children
        .map((child) => `${child.child_chat_id}:${child.user_message_id}:${tokenHash(child.dispatch_token)}`)
        .sort().join('|');
      const persisted = existing
        .map((child) => `${child.child_chat_id}:${child.user_message_id}:${child.dispatch_token_hash}`)
        .sort().join('|');
      if (requested !== persisted) fail(409, 'batch_identity_mismatch');
      return { orchestration_id: orchestrationId, batch_id: batchId, prepared: false, idempotent: true, child_chat_ids: existing.map((row) => row.child_chat_id) };
    }
    if (root.descendant_count + children.length > root.descendant_limit) fail(409, 'descendant_limit_exceeded');
    const depth = parentDepth + 1;
    const timestamp = Math.floor(now.getTime() / 1000);
    await trx(BATCHES).insert({
      id: batchId, orchestration_id: orchestrationId, parent_chat_id: parentChatId,
      parent_depth: parentDepth, child_count: children.length, terminal_count: 0,
      continuation_claimed: false, created_at: now, updated_at: now,
    });
    for (const child of children) {
      if (await trx(CHATS).where({ id: child.child_chat_id }).first()) fail(409, 'child_chat_exists');
      await trx(CHATS).insert({
        id: child.child_chat_id, hashed_user_id: root.hashed_user_id,
        hashed_team_id: root.hashed_team_id, created_at: timestamp, updated_at: timestamp,
        messages_v: 1, title_v: 0, metadata_v: 0,
        last_edited_overall_timestamp: timestamp, last_message_timestamp: timestamp,
        unread_count: 0, encrypted_title: '', parent_id: parentChatId, is_sub_chat: true,
        budget_limit: child.budget_limit, budget_spent: 0,
      });
      await trx(CHILDREN).insert({
        id: randomUUID(), orchestration_id: orchestrationId, batch_id: batchId,
        child_chat_id: child.child_chat_id, parent_chat_id: parentChatId,
        user_message_id: child.user_message_id, depth,
        dispatch_token_hash: tokenHash(child.dispatch_token), state: 'prepared',
        created_at: now, updated_at: now,
      });
    }
    const updated = await trx(ORCHESTRATIONS).where({ id: orchestrationId, version: root.version }).update({
      descendant_count: root.descendant_count + children.length,
      version: root.version + 1, updated_at: now,
    });
    if (updated !== 1) fail(409, 'orchestration_conflict');
    return {
      orchestration_id: orchestrationId, batch_id: batchId,
      prepared: true, idempotent: false, depth,
      child_chat_ids: children.map((child) => child.child_chat_id),
    };
  });
}

async function transitionChild(database, raw, now) {
  const body = operationBody(raw, 'transition_child');
  const orchestrationId = uuid(body.orchestration_id, 'invalid_orchestration_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const childChatId = uuid(body.child_chat_id, 'invalid_child_chat_id');
  const state = string(body.state, 'invalid_child_state', 24);
  if (!CHILD_STATES.has(state) || state === 'prepared') fail(400, 'invalid_child_state');
  return database.transaction(async (trx) => {
    const root = await lockedRoot(trx, orchestrationId, ownerHash);
    const child = await trx(CHILDREN).where({ orchestration_id: orchestrationId, child_chat_id: childChatId }).forUpdate().first();
    if (!child) fail(404, 'child_not_found');
    if (child.state === state) {
      const batch = await trx(BATCHES).where({ id: child.batch_id, orchestration_id: orchestrationId }).first();
      return {
        child_chat_id: childChatId, state, transitioned: false, batch_id: child.batch_id,
        batch_complete: Boolean(batch && batch.terminal_count === batch.child_count),
      };
    }
    if (['completed', 'failed', 'cancelled'].includes(child.state)) fail(409, 'child_already_terminal');
    const update = { state, updated_at: now };
    if (state === 'dispatched') update.dispatched_at = now;
    if (['completed', 'failed', 'cancelled'].includes(state)) update.terminal_at = now;
    await trx(CHILDREN).where({ id: child.id, state: child.state }).update(update);
    let batchComplete = false;
    if (['completed', 'failed', 'cancelled'].includes(state)) {
      const batch = await trx(BATCHES).where({ id: child.batch_id, orchestration_id: orchestrationId }).forUpdate().first();
      if (!batch) fail(500, 'batch_not_found');
      const terminalCount = batch.terminal_count + 1;
      batchComplete = terminalCount === batch.child_count;
      await trx(BATCHES).where({ id: batch.id }).update({
        terminal_count: terminalCount,
        updated_at: now,
      });
      if (['failed', 'cancelled'].includes(state)) {
        const reservations = await trx(OPERATIONS).where({
          orchestration_id: orchestrationId, actual_chat_id: childChatId, state: 'reserved',
        }).forUpdate();
        const releasedCredits = reservations.reduce((total, row) => total + row.quoted_credits, 0);
        if (releasedCredits > 0) {
          const rootUpdated = await trx(ORCHESTRATIONS).where({ id: root.id, version: root.version }).update({
            reserved_credits: Math.max(root.reserved_credits - releasedCredits, 0),
            version: root.version + 1,
            updated_at: now,
          });
          if (rootUpdated !== 1) fail(409, 'orchestration_conflict');
          await trx(OPERATIONS).whereIn('id', reservations.map((row) => row.id)).update({
            state: 'failed', actual_credits: 0, updated_at: now, settled_at: now,
          });
        }
      }
    }
    return {
      child_chat_id: childChatId, state, transitioned: true,
      batch_id: child.batch_id, batch_complete: batchComplete,
    };
  });
}

async function claimChild(database, raw, now) {
  const body = operationBody(raw, 'claim_child');
  const orchestrationId = uuid(body.orchestration_id, 'invalid_orchestration_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const childChatId = uuid(body.child_chat_id, 'invalid_child_chat_id');
  const dispatchTokenHash = tokenHash(string(body.dispatch_token, 'invalid_dispatch_token', 255));
  const inferenceTaskId = uuid(body.inference_task_id, 'invalid_inference_task_id');
  if (typeof body.is_continuation !== 'boolean') fail(400, 'invalid_continuation_state');
  return database.transaction(async (trx) => {
    const root = await lockedRoot(trx, orchestrationId, ownerHash);
    if (root.status !== 'active' || new Date(root.expires_at) <= now) fail(409, 'orchestration_not_active');
    const child = await trx(CHILDREN).where({ orchestration_id: orchestrationId, child_chat_id: childChatId }).forUpdate().first();
    if (!child || child.dispatch_token_hash !== dispatchTokenHash) fail(404, 'child_dispatch_not_found');
    if (child.inference_task_id) {
      if (body.is_continuation && child.state === 'running') {
        return {
          child_chat_id: childChatId, depth: child.depth, state: child.state,
          claimed: true, continuation: true,
        };
      }
      if (child.inference_task_id !== inferenceTaskId) fail(409, 'child_already_claimed');
      return { child_chat_id: childChatId, depth: child.depth, state: child.state, claimed: false };
    }
    if (!['prepared', 'dispatched'].includes(child.state)) fail(409, 'child_not_claimable');
    const updated = await trx(CHILDREN).where({ id: child.id, state: child.state }).update({
      state: 'running', inference_task_id: inferenceTaskId,
      dispatched_at: child.dispatched_at || now, updated_at: now,
    });
    if (updated !== 1) fail(409, 'child_claim_conflict');
    return { child_chat_id: childChatId, depth: child.depth, state: 'running', claimed: true };
  });
}

async function transitionRoot(database, raw, now) {
  const body = operationBody(raw, 'transition_root');
  const orchestrationId = uuid(body.orchestration_id, 'invalid_orchestration_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const state = string(body.state, 'invalid_root_state', 24);
  if (!TERMINAL_ROOT_STATES.has(state)) fail(400, 'invalid_root_state');
  return database.transaction(async (trx) => {
    const root = await lockedRoot(trx, orchestrationId, ownerHash);
    if (root.status === state) return { ...rootResponse(root), transitioned: false };
    if (TERMINAL_ROOT_STATES.has(root.status)) fail(409, 'root_already_terminal');
    let releasedCredits = 0;
    if (['failed', 'cancelled', 'expired'].includes(state)) {
      const reservations = await trx(OPERATIONS).where({ orchestration_id: orchestrationId, state: 'reserved' }).forUpdate();
      releasedCredits = reservations.reduce((total, row) => total + row.quoted_credits, 0);
      if (reservations.length) {
        await trx(OPERATIONS).whereIn('id', reservations.map((row) => row.id)).update({
          state: 'failed', actual_credits: 0, updated_at: now, settled_at: now,
        });
      }
    }
    const update = {
      status: state, terminal_at: now, updated_at: now, version: root.version + 1,
      reserved_credits: Math.max(root.reserved_credits - releasedCredits, 0),
    };
    await trx(ORCHESTRATIONS).where({ id: orchestrationId, version: root.version }).update(update);
    return { ...rootResponse({ ...root, ...update }), transitioned: true };
  });
}

async function claimParentContinuation(database, raw, now) {
  const body = operationBody(raw, 'claim_parent_continuation');
  const orchestrationId = uuid(body.orchestration_id, 'invalid_orchestration_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const batchId = uuid(body.batch_id, 'invalid_batch_id');
  return database.transaction(async (trx) => {
    await lockedRoot(trx, orchestrationId, ownerHash);
    const batch = await trx(BATCHES).where({ id: batchId, orchestration_id: orchestrationId }).forUpdate().first();
    if (!batch) fail(404, 'batch_not_found');
    if (batch.terminal_count !== batch.child_count) fail(409, 'batch_not_terminal');
    const continuationTaskId = batch.continuation_task_id || randomUUID();
    if (!batch.continuation_task_id) {
      await trx(BATCHES).where({ id: batch.id }).update({
        continuation_claimed: true, continuation_claimed_at: now,
        continuation_task_id: continuationTaskId, updated_at: now,
      });
    }
    return {
      batch_id: batchId, continuation_task_id: continuationTaskId,
      dispatch_required: !batch.continuation_dispatched_at,
    };
  });
}

async function markParentContinuationDispatched(database, raw, now) {
  const body = operationBody(raw, 'mark_parent_continuation_dispatched');
  const orchestrationId = uuid(body.orchestration_id, 'invalid_orchestration_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const batchId = uuid(body.batch_id, 'invalid_batch_id');
  const taskId = uuid(body.continuation_task_id, 'invalid_continuation_task_id');
  return database.transaction(async (trx) => {
    await lockedRoot(trx, orchestrationId, ownerHash);
    const batch = await trx(BATCHES).where({ id: batchId, orchestration_id: orchestrationId }).forUpdate().first();
    if (!batch || batch.continuation_task_id !== taskId) fail(404, 'continuation_claim_not_found');
    if (batch.continuation_dispatched_at) return { batch_id: batchId, dispatched: false, idempotent: true };
    await trx(BATCHES).where({ id: batch.id }).update({ continuation_dispatched_at: now, updated_at: now });
    return { batch_id: batchId, dispatched: true, idempotent: false };
  });
}

async function getRootState(database, raw) {
  const body = operationBody(raw, 'get_root_state');
  const orchestrationId = uuid(body.orchestration_id, 'invalid_orchestration_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const root = await database(ORCHESTRATIONS).where({ id: orchestrationId, hashed_user_id: ownerHash }).first();
  if (!root) fail(404, 'orchestration_not_found');
  return rootResponse(root);
}

async function reserveOperation(database, raw, now) {
  const body = operationBody(raw, 'reserve_operation');
  const operationId = string(body.operation_id, 'invalid_operation_id', 255);
  const chargeId = string(body.charge_id, 'invalid_charge_id', 255);
  const orchestrationId = uuid(body.orchestration_id, 'invalid_orchestration_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const rootChatId = uuid(body.root_chat_id, 'invalid_root_chat_id');
  const actualChatId = uuid(body.actual_chat_id, 'invalid_actual_chat_id');
  const depth = integer(body.depth, 'invalid_depth');
  const appId = string(body.app_id, 'invalid_app_id', 100);
  const skillId = string(body.skill_id, 'invalid_skill_id', 100);
  const phase = string(body.phase, 'invalid_phase', 64);
  const quotedCredits = integer(body.quoted_credits, 'invalid_quoted_credits');
  if (quotedCredits <= 0 || depth > MAX_DEPTH) fail(400, 'invalid_operation_reservation');
  const identity = {
    charge_id: chargeId, orchestration_id: orchestrationId, root_chat_id: rootChatId,
    actual_chat_id: actualChatId, depth, app_id: appId, skill_id: skillId,
    phase, quoted_credits: quotedCredits,
  };
  return database.transaction(async (trx) => {
    const existing = await trx(OPERATIONS).where({ operation_id: operationId }).forUpdate().first();
    if (existing) {
      assertOperationIdentity(existing, identity);
      return reservedOperationResponse(existing, true);
    }
    const root = await lockedRoot(trx, orchestrationId, ownerHash);
    if (root.status !== 'active' || new Date(root.expires_at) <= now) fail(409, 'orchestration_not_active');
    if (root.root_chat_id !== rootChatId) fail(409, 'root_identity_mismatch');
    if (depth === 0 && actualChatId !== rootChatId) fail(409, 'operation_chat_identity_mismatch');
    if (depth > 0) {
      const child = await trx(CHILDREN).where({
        orchestration_id: orchestrationId, child_chat_id: actualChatId, depth,
      }).first();
      if (!child || !['dispatched', 'running'].includes(child.state)) fail(409, 'operation_child_not_authorized');
    }
    if (!operationReservationFits(root, quotedCredits)) {
      fail(409, 'orchestration_credit_limit_exceeded');
    }
    const row = {
      id: randomUUID(), operation_id: operationId, ...identity,
      actual_credits: null, state: 'reserved', created_at: now, updated_at: now, settled_at: null,
    };
    await trx(OPERATIONS).insert(row);
    const updated = await trx(ORCHESTRATIONS).where({ id: root.id, version: root.version }).update({
      reserved_credits: root.reserved_credits + quotedCredits,
      version: root.version + 1,
      updated_at: now,
    });
    if (updated !== 1) fail(409, 'orchestration_conflict');
    return reservedOperationResponse(row, false);
  });
}

async function failOperation(database, raw, now) {
  const body = operationBody(raw, 'fail_operation');
  const operationId = string(body.operation_id, 'invalid_operation_id', 255);
  const orchestrationId = uuid(body.orchestration_id, 'invalid_orchestration_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  return database.transaction(async (trx) => {
    const root = await lockedRoot(trx, orchestrationId, ownerHash);
    const operation = await trx(OPERATIONS).where({ operation_id: operationId }).forUpdate().first();
    if (!operation || operation.orchestration_id !== orchestrationId) fail(404, 'operation_not_found');
    if (operation.state === 'failed') return reservedOperationResponse(operation, true);
    if (operation.state !== 'reserved') fail(409, 'operation_not_reserved');
    const updated = await trx(ORCHESTRATIONS).where({ id: root.id, version: root.version }).update({
      reserved_credits: Math.max(root.reserved_credits - operation.quoted_credits, 0),
      version: root.version + 1,
      updated_at: now,
    });
    if (updated !== 1) fail(409, 'orchestration_conflict');
    const operationUpdate = { state: 'failed', actual_credits: 0, updated_at: now, settled_at: now };
    await trx(OPERATIONS).where({ id: operation.id }).update(operationUpdate);
    return reservedOperationResponse({ ...operation, ...operationUpdate }, false);
  });
}

async function settleChargeReservations(trx, {
  chargeId, orchestrationId, ownerHash, expectedTeamHash, actualCredits, now,
}) {
  const root = await lockedRoot(trx, orchestrationId, ownerHash);
  if (expectedTeamHash === null && root.hashed_team_id !== null) fail(409, 'billing_subject_mismatch');
  if (typeof expectedTeamHash === 'string' && root.hashed_team_id !== expectedTeamHash) {
    fail(409, 'billing_subject_mismatch');
  }
  const reservations = await trx(OPERATIONS)
    .where({ orchestration_id: orchestrationId, charge_id: chargeId })
    .orderBy('created_at', 'asc')
    .forUpdate();
  if (!reservations.length) {
    fail(409, 'operation_reservation_required');
  }
  if (reservations.some((row) => row.state !== 'reserved')) {
    fail(409, 'operation_reservation_required');
  }
  const quotedCredits = reservations.reduce((total, row) => total + row.quoted_credits, 0);
  if (root.spent_credits + root.reserved_credits - quotedCredits + actualCredits > root.credit_limit) {
    fail(409, 'orchestration_credit_limit_exceeded');
  }
  const updated = await trx(ORCHESTRATIONS).where({ id: root.id, version: root.version }).update({
    reserved_credits: Math.max(root.reserved_credits - quotedCredits, 0),
    spent_credits: root.spent_credits + actualCredits,
    version: root.version + 1,
    updated_at: now,
  });
  if (updated !== 1) fail(409, 'orchestration_conflict');
  let remainingActual = actualCredits;
  for (const [index, operation] of reservations.entries()) {
    const operationActual = index === reservations.length - 1
      ? remainingActual
      : Math.min(remainingActual, Math.floor(actualCredits * operation.quoted_credits / quotedCredits));
    remainingActual -= operationActual;
    await trx(OPERATIONS).where({ id: operation.id }).update({
      state: 'settled', actual_credits: operationActual, updated_at: now, settled_at: now,
    });
  }
  return { quoted_credits: quotedCredits, actual_credits: actualCredits };
}

async function cleanupExpiredReservations(database, raw, now) {
  operationBody(raw, 'cleanup_expired_reservations');
  return database.transaction(async (trx) => {
    const expiredRoots = await trx(ORCHESTRATIONS).where({ status: 'active' }).andWhere('expires_at', '<=', now).select('id');
    const rootIds = expiredRoots.map((row) => row.id);
    if (rootIds.length) {
      await trx(OPERATIONS).whereIn('orchestration_id', rootIds).andWhere({ state: 'reserved' }).update({
        state: 'failed', actual_credits: 0, updated_at: now, settled_at: now,
      });
    }
    const expiredCount = await trx(ORCHESTRATIONS).whereIn('id', rootIds).update({
      status: 'expired', terminal_at: now, updated_at: now, version: trx.raw('version + 1'),
      reserved_credits: 0,
    });
    return { expired_roots: expiredCount };
  });
}

async function commitPersonalCharge(database, raw, now) {
  const body = operationBody(raw, 'commit_personal_charge');
  const chargeId = string(body.charge_id, 'invalid_charge_id', 255);
  const userId = uuid(body.user_id, 'invalid_user_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const appId = string(body.app_id, 'invalid_app_id', 100);
  const skillId = string(body.skill_id, 'invalid_skill_id', 100);
  const requestedCredits = integer(body.requested_credits, 'invalid_requested_credits');
  const chargedCredits = integer(body.charged_credits, 'invalid_charged_credits');
  const expectedBalance = string(body.expected_encrypted_balance, 'invalid_expected_balance', 16_384);
  const newBalance = string(body.new_encrypted_balance, 'invalid_new_balance', 16_384);
  const usageEntry = object(body.usage_entry);
  if (Object.keys(usageEntry).some((key) => !USAGE_FIELDS.has(key))) fail(400, 'invalid_usage_entry');
  const usageId = uuid(usageEntry.id, 'invalid_usage_id');
  if (usageEntry.charge_id !== chargeId || usageEntry.user_id_hash !== ownerHash
    || usageEntry.app_id !== appId || usageEntry.skill_id !== skillId) fail(409, 'usage_identity_mismatch');
  string(usageEntry.encrypted_credits_costs_total, 'invalid_usage_credits', 16_384);
  integer(usageEntry.created_at, 'invalid_usage_timestamp');
  integer(usageEntry.updated_at, 'invalid_usage_timestamp');
  return database.transaction(async (trx) => {
    let existing = await trx(CHARGE_IDENTITIES).where({ charge_id: chargeId }).forUpdate().first();
    if (existing) {
      if (existing.hashed_user_id !== ownerHash || existing.app_id !== appId
        || existing.skill_id !== skillId || existing.requested_credits !== requestedCredits) {
        fail(409, 'charge_identity_mismatch');
      }
      return {
        charge_id: chargeId, charged_credits: existing.charged_credits,
        encrypted_balance_after: existing.encrypted_balance_after,
        usage_id: existing.usage_id, state: existing.state, idempotent: true,
      };
    }
    const user = await trx(USERS).where({ id: userId }).forUpdate().first();
    if (!user) fail(404, 'billing_user_not_found');
    existing = await trx(CHARGE_IDENTITIES).where({ charge_id: chargeId }).first();
    if (existing) {
      if (existing.hashed_user_id !== ownerHash || existing.app_id !== appId
        || existing.skill_id !== skillId || existing.requested_credits !== requestedCredits) {
        fail(409, 'charge_identity_mismatch');
      }
      return {
        charge_id: chargeId, charged_credits: existing.charged_credits,
        encrypted_balance_after: existing.encrypted_balance_after,
        usage_id: existing.usage_id, state: existing.state, idempotent: true,
      };
    }
    if (usageEntry.orchestration_id) {
      await settleChargeReservations(trx, {
        chargeId,
        orchestrationId: uuid(usageEntry.orchestration_id, 'invalid_usage_orchestration_id'),
        ownerHash,
        expectedTeamHash: null,
        actualCredits: chargedCredits,
        now,
      });
    }
    if (user.encrypted_credit_balance !== expectedBalance) fail(409, 'stale_credit_balance');
    const updated = await trx(USERS).where({ id: userId, encrypted_credit_balance: expectedBalance }).update({
      encrypted_credit_balance: newBalance,
    });
    if (updated !== 1) fail(409, 'stale_credit_balance');
    await trx(USAGE).insert(usageEntry);
    await trx(CHARGE_IDENTITIES).insert({
      id: randomUUID(), charge_id: chargeId, hashed_user_id: ownerHash,
      app_id: appId, skill_id: skillId, requested_credits: requestedCredits,
      charged_credits: chargedCredits,
      encrypted_balance_before: expectedBalance, encrypted_balance_after: newBalance,
      usage_id: usageId,
      state: 'committed', created_at: now, committed_at: now,
    });
    return {
      charge_id: chargeId, charged_credits: chargedCredits,
      encrypted_balance_after: newBalance, usage_id: usageId,
      state: 'committed', idempotent: false,
    };
  });
}

async function commitPersonalRefund(database, raw, now) {
  const body = operationBody(raw, 'commit_personal_refund');
  const refundId = string(body.refund_id, 'invalid_refund_id', 255);
  const userId = uuid(body.user_id, 'invalid_user_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const appId = string(body.app_id, 'invalid_app_id', 100);
  const skillId = string(body.skill_id, 'invalid_skill_id', 100);
  const creditsToRefund = integer(body.credits_to_refund, 'invalid_refund_credits');
  const expectedBalance = string(body.expected_encrypted_balance, 'invalid_expected_balance', 16_384);
  const newBalance = string(body.new_encrypted_balance, 'invalid_new_balance', 16_384);
  if (creditsToRefund <= 0) fail(400, 'invalid_refund_credits');
  return database.transaction(async (trx) => {
    let existing = await trx(REFUND_IDENTITIES).where({ refund_id: refundId }).forUpdate().first();
    if (existing) {
      if (existing.hashed_user_id !== ownerHash || existing.app_id !== appId
        || existing.skill_id !== skillId || existing.refunded_credits !== creditsToRefund) {
        fail(409, 'refund_identity_mismatch');
      }
      return {
        refund_id: refundId, state: existing.state, idempotent: true,
        refunded_credits: existing.refunded_credits,
        encrypted_balance_after: existing.encrypted_balance_after,
      };
    }
    const user = await trx(USERS).where({ id: userId }).forUpdate().first();
    if (!user) fail(404, 'billing_user_not_found');
    existing = await trx(REFUND_IDENTITIES).where({ refund_id: refundId }).first();
    if (existing) {
      if (existing.hashed_user_id !== ownerHash || existing.app_id !== appId
        || existing.skill_id !== skillId || existing.refunded_credits !== creditsToRefund) {
        fail(409, 'refund_identity_mismatch');
      }
      return {
        refund_id: refundId, state: existing.state, idempotent: true,
        refunded_credits: existing.refunded_credits,
        encrypted_balance_after: existing.encrypted_balance_after,
      };
    }
    if (user.encrypted_credit_balance !== expectedBalance) fail(409, 'stale_credit_balance');
    const updated = await trx(USERS).where({ id: userId, encrypted_credit_balance: expectedBalance }).update({
      encrypted_credit_balance: newBalance,
    });
    if (updated !== 1) fail(409, 'stale_credit_balance');
    await trx(REFUND_IDENTITIES).insert({
      id: randomUUID(), refund_id: refundId, hashed_user_id: ownerHash,
      app_id: appId, skill_id: skillId, refunded_credits: creditsToRefund,
      encrypted_balance_before: expectedBalance, encrypted_balance_after: newBalance,
      state: 'committed', created_at: now, committed_at: now,
    });
    return {
      refund_id: refundId, state: 'committed', idempotent: false,
      refunded_credits: creditsToRefund, encrypted_balance_after: newBalance,
    };
  });
}

async function getPersonalCharge(database, raw) {
  const body = operationBody(raw, 'get_personal_charge');
  const chargeId = string(body.charge_id, 'invalid_charge_id', 255);
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const appId = string(body.app_id, 'invalid_app_id', 100);
  const skillId = string(body.skill_id, 'invalid_skill_id', 100);
  const requestedCredits = integer(body.requested_credits, 'invalid_requested_credits');
  const existing = await database(CHARGE_IDENTITIES).where({ charge_id: chargeId }).first();
  if (!existing) return { found: false, charge_id: chargeId };
  if (existing.hashed_user_id !== ownerHash || existing.app_id !== appId
    || existing.skill_id !== skillId || existing.requested_credits !== requestedCredits) {
    fail(409, 'charge_identity_mismatch');
  }
  return {
    found: true, charge_id: chargeId, charged_credits: existing.charged_credits,
    encrypted_balance_after: existing.encrypted_balance_after,
    usage_id: existing.usage_id, state: existing.state,
  };
}

const pendingSettlementResponse = (row, idempotent, claimed = false) => ({
  outbox_id: row.id,
  charge_id: row.charge_id,
  user_id: row.user_id,
  vault_key_id: row.vault_key_id,
  encrypted_settlement_payload: row.encrypted_settlement_payload,
  state: row.state,
  attempts: row.attempts,
  retryable_error_code: row.retryable_error_code,
  idempotent,
  claimed,
});

function assertPendingSettlementIdentity(row, { chargeId, ownerHash }) {
  if (row.charge_id !== chargeId || row.hashed_user_id !== ownerHash) {
    fail(409, 'settlement_identity_mismatch');
  }
}

async function createOrReusePendingSettlement(database, raw, now) {
  const body = operationBody(raw, 'create_or_reuse_pending_settlement');
  const chargeId = string(body.charge_id, 'invalid_charge_id', 255);
  const userId = uuid(body.user_id, 'invalid_user_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const vaultKeyId = string(body.vault_key_id, 'invalid_vault_key_id', 64);
  const encryptedPayload = string(body.encrypted_settlement_payload, 'invalid_settlement_payload', 65_535);
  const payloadHash = string(body.settlement_payload_hash, 'invalid_settlement_payload_hash', 64);
  if (!/^[a-f0-9]{64}$/.test(payloadHash)) fail(400, 'invalid_settlement_payload_hash');
  const errorCode = string(body.retryable_error_code, 'invalid_retryable_error_code', 64);
  return database.transaction(async (trx) => {
    const committed = await trx(CHARGE_IDENTITIES).where({ charge_id: chargeId }).forUpdate().first();
    if (committed) {
      if (committed.hashed_user_id !== ownerHash) fail(409, 'charge_identity_mismatch');
      return {
        charge_id: chargeId, state: 'committed', idempotent: true,
        charged_credits: committed.charged_credits,
        encrypted_balance_after: committed.encrypted_balance_after,
        usage_id: committed.usage_id,
      };
    }
    const existing = await trx(SETTLEMENT_OUTBOX).where({ charge_id: chargeId }).forUpdate().first();
    if (existing) {
      assertPendingSettlementIdentity(existing, { chargeId, ownerHash });
      if (existing.user_id !== userId || existing.vault_key_id !== vaultKeyId
        || existing.settlement_payload_hash !== payloadHash) {
        fail(409, 'settlement_identity_mismatch');
      }
      return pendingSettlementResponse(existing, true);
    }
    const row = {
      id: randomUUID(), charge_id: chargeId, user_id: userId,
      hashed_user_id: ownerHash, vault_key_id: vaultKeyId,
      encrypted_settlement_payload: encryptedPayload,
      settlement_payload_hash: payloadHash,
      state: 'pending', attempts: 0,
      retryable_error_code: errorCode, next_attempt_at: now,
      created_at: now, updated_at: now, committed_at: null,
    };
    await trx(SETTLEMENT_OUTBOX).insert(row);
    return pendingSettlementResponse(row, false);
  });
}

async function getPendingSettlement(database, raw) {
  const body = operationBody(raw, 'get_pending_settlement');
  const outboxId = uuid(body.outbox_id, 'invalid_outbox_id');
  const chargeId = string(body.charge_id, 'invalid_charge_id', 255);
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const row = await database(SETTLEMENT_OUTBOX).where({ id: outboxId }).first();
  if (!row) fail(404, 'settlement_not_found');
  assertPendingSettlementIdentity(row, { chargeId, ownerHash });
  return pendingSettlementResponse(row, true);
}

async function replayPendingSettlement(database, raw, now) {
  const body = operationBody(raw, 'replay_pending_settlement');
  const outboxId = uuid(body.outbox_id, 'invalid_outbox_id');
  const chargeId = string(body.charge_id, 'invalid_charge_id', 255);
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  return database.transaction(async (trx) => {
    const row = await trx(SETTLEMENT_OUTBOX).where({ id: outboxId }).forUpdate().first();
    if (!row) fail(404, 'settlement_not_found');
    assertPendingSettlementIdentity(row, { chargeId, ownerHash });
    const committed = await trx(CHARGE_IDENTITIES).where({ charge_id: chargeId }).first();
    if (committed) {
      await trx(SETTLEMENT_OUTBOX).where({ id: outboxId }).update({
        state: 'committed', committed_at: now, updated_at: now,
      });
      return {
        charge_id: chargeId, state: 'committed', idempotent: true,
        duplicate_usage_created: false,
      };
    }
    if (row.state === 'manual_review') return pendingSettlementResponse(row, true);
    if (row.state === 'retry_scheduled' && row.next_attempt_at
      && new Date(row.next_attempt_at).getTime() > now.getTime()) {
      return pendingSettlementResponse(row, true, false);
    }
    const nextAttempt = row.attempts + 1;
    const retryDelay = SETTLEMENT_RETRY_DELAYS_MS[Math.min(
      nextAttempt - 1,
      SETTLEMENT_RETRY_DELAYS_MS.length - 1,
    )];
    const update = {
      state: 'retry_scheduled', attempts: nextAttempt,
      next_attempt_at: new Date(now.getTime() + retryDelay), updated_at: now,
    };
    await trx(SETTLEMENT_OUTBOX).where({ id: outboxId }).update(update);
    return pendingSettlementResponse({ ...row, ...update }, false, true);
  });
}

async function completePendingSettlement(database, raw, now) {
  const body = operationBody(raw, 'complete_pending_settlement');
  const outboxId = uuid(body.outbox_id, 'invalid_outbox_id');
  const chargeId = string(body.charge_id, 'invalid_charge_id', 255);
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  return database.transaction(async (trx) => {
    const row = await trx(SETTLEMENT_OUTBOX).where({ id: outboxId }).forUpdate().first();
    if (!row) fail(404, 'settlement_not_found');
    assertPendingSettlementIdentity(row, { chargeId, ownerHash });
    const committed = await trx(CHARGE_IDENTITIES).where({ charge_id: chargeId }).first();
    if (!committed) fail(409, 'charge_not_committed');
    if (row.state !== 'committed') {
      await trx(SETTLEMENT_OUTBOX).where({ id: outboxId }).update({
        state: 'committed', committed_at: now, updated_at: now,
      });
    }
    return { charge_id: chargeId, state: 'committed', idempotent: row.state === 'committed' };
  });
}

async function transitionPendingSettlementToManualReview(database, raw, now) {
  const body = operationBody(raw, 'transition_pending_settlement_to_manual_review');
  const outboxId = uuid(body.outbox_id, 'invalid_outbox_id');
  const chargeId = string(body.charge_id, 'invalid_charge_id', 255);
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 128);
  const attempts = integer(body.attempts, 'invalid_attempts');
  const errorCode = string(body.retryable_error_code, 'invalid_retryable_error_code', 64);
  return database.transaction(async (trx) => {
    const row = await trx(SETTLEMENT_OUTBOX).where({ id: outboxId }).forUpdate().first();
    if (!row) fail(404, 'settlement_not_found');
    assertPendingSettlementIdentity(row, { chargeId, ownerHash });
    if (row.state !== 'committed' && row.state !== 'manual_review') {
      await trx(SETTLEMENT_OUTBOX).where({ id: outboxId }).update({
        state: 'manual_review', attempts, retryable_error_code: errorCode,
        next_attempt_at: null, updated_at: now,
      });
    }
    return { state: row.state === 'committed' ? 'committed' : 'manual_review', alert_required: row.state !== 'committed' };
  });
}

async function commitTeamCharge(database, raw) {
  const body = operationBody(raw, 'commit_team_charge');
  const eventId = string(body.event_id, 'invalid_event_id', 255);
  const teamHash = string(body.hashed_team_id, 'invalid_team', 128);
  const actorHash = string(body.actor_user_hash, 'invalid_actor', 128);
  const credits = integer(body.credits, 'invalid_credits');
  if (credits <= 0) fail(400, 'invalid_credits');
  const expectedVersion = integer(body.expected_version, 'invalid_account_version');
  const encryptedBalance = string(body.encrypted_balance, 'invalid_encrypted_balance', 16_384);
  const workspaceType = string(body.workspace_type, 'invalid_workspace_type', 64);
  const objectIdHash = body.object_id_hash == null ? null : string(body.object_id_hash, 'invalid_object_id_hash', 255);
  const encryptedMetadata = body.encrypted_metadata == null ? null : string(body.encrypted_metadata, 'invalid_encrypted_metadata', 16_384);
  const occurredAt = integer(body.occurred_at, 'invalid_occurred_at');
  return database.transaction(async (trx) => {
    const existing = await trx(TEAM_CREDIT_EVENTS).where({ event_id: eventId }).forUpdate().first();
    if (existing) {
      if (existing.hashed_team_id !== teamHash || existing.actor_user_hash !== actorHash
        || existing.event_type !== 'deduction' || existing.amount !== -credits) fail(409, 'team_charge_identity_mismatch');
      const account = await lockedTeamAccount(trx, teamHash);
      const usageEvent = await trx(TEAM_USAGE_EVENTS).where({ event_id: eventId }).first();
      return { account, credit_event: existing, usage_event: usageEvent, idempotent: true };
    }
    const account = await lockedTeamAccount(trx, teamHash);
    const concurrent = await trx(TEAM_CREDIT_EVENTS).where({ event_id: eventId }).first();
    if (concurrent) {
      if (concurrent.hashed_team_id !== teamHash || concurrent.actor_user_hash !== actorHash
        || concurrent.event_type !== 'deduction' || concurrent.amount !== -credits) fail(409, 'team_charge_identity_mismatch');
      const usageEvent = await trx(TEAM_USAGE_EVENTS).where({ event_id: eventId }).first();
      return { account, credit_event: concurrent, usage_event: usageEvent, idempotent: true };
    }
    if (account.version !== expectedVersion) fail(409, 'stale_team_credit_balance');
    if (account.balance_credits < credits) fail(402, 'insufficient_team_credits');
    if (body.orchestration_id) {
      await settleChargeReservations(trx, {
        chargeId: eventId,
        orchestrationId: uuid(body.orchestration_id, 'invalid_usage_orchestration_id'),
        ownerHash: actorHash,
        expectedTeamHash: teamHash,
        actualCredits: credits,
        now: new Date(occurredAt * 1000),
      });
    }
    const updatedAccount = {
      ...account, balance_credits: account.balance_credits - credits,
      encrypted_balance: encryptedBalance, version: expectedVersion + 1, updated_at: occurredAt,
    };
    const updated = await trx(TEAM_ACCOUNTS).where({ id: account.id, version: expectedVersion }).update({
      balance_credits: updatedAccount.balance_credits, encrypted_balance: encryptedBalance,
      version: updatedAccount.version, updated_at: occurredAt,
    });
    if (updated !== 1) fail(409, 'stale_team_credit_balance');
    const creditEvent = {
      id: randomUUID(), event_id: eventId, hashed_team_id: teamHash, actor_user_hash: actorHash,
      event_type: 'deduction', amount: -credits, encrypted_metadata: encryptedMetadata, created_at: occurredAt,
    };
    const usageEvent = {
      id: randomUUID(), event_id: eventId, hashed_team_id: teamHash, actor_user_hash: actorHash,
      workspace_type: workspaceType, object_id_hash: objectIdHash,
      credit_amount: credits, created_at: occurredAt,
    };
    await trx(TEAM_CREDIT_EVENTS).insert(creditEvent);
    await trx(TEAM_USAGE_EVENTS).insert(usageEvent);
    return { account: updatedAccount, credit_event: creditEvent, usage_event: usageEvent, idempotent: false };
  });
}

async function commitTeamCreditAdd(database, raw) {
  const body = operationBody(raw, 'commit_team_credit_add');
  const eventId = string(body.event_id, 'invalid_event_id', 255);
  const teamHash = string(body.hashed_team_id, 'invalid_team', 128);
  const actorHash = string(body.actor_user_hash, 'invalid_actor', 128);
  const credits = integer(body.credits, 'invalid_credits');
  if (credits <= 0) fail(400, 'invalid_credits');
  const expectedVersion = integer(body.expected_version, 'invalid_account_version');
  const encryptedBalance = string(body.encrypted_balance, 'invalid_encrypted_balance', 16_384);
  const eventType = string(body.event_type, 'invalid_event_type', 32);
  if (!['purchase', 'personal_transfer_in'].includes(eventType)) fail(400, 'invalid_event_type');
  const encryptedMetadata = body.encrypted_metadata == null ? null : string(body.encrypted_metadata, 'invalid_encrypted_metadata', 16_384);
  const occurredAt = integer(body.occurred_at, 'invalid_occurred_at');
  return database.transaction(async (trx) => {
    const existing = await trx(TEAM_CREDIT_EVENTS).where({ event_id: eventId }).forUpdate().first();
    if (existing) {
      if (existing.hashed_team_id !== teamHash || existing.actor_user_hash !== actorHash
        || existing.event_type !== eventType || existing.amount !== credits) fail(409, 'team_credit_identity_mismatch');
      const account = await lockedTeamAccount(trx, teamHash);
      return { account, credit_event: existing, idempotent: true };
    }
    const account = await lockedTeamAccount(trx, teamHash);
    const concurrent = await trx(TEAM_CREDIT_EVENTS).where({ event_id: eventId }).first();
    if (concurrent) {
      if (concurrent.hashed_team_id !== teamHash || concurrent.actor_user_hash !== actorHash
        || concurrent.event_type !== eventType || concurrent.amount !== credits) fail(409, 'team_credit_identity_mismatch');
      return { account, credit_event: concurrent, idempotent: true };
    }
    if (account.version !== expectedVersion) fail(409, 'stale_team_credit_balance');
    const updatedAccount = {
      ...account, balance_credits: account.balance_credits + credits,
      encrypted_balance: encryptedBalance, version: expectedVersion + 1, updated_at: occurredAt,
    };
    const updated = await trx(TEAM_ACCOUNTS).where({ id: account.id, version: expectedVersion }).update({
      balance_credits: updatedAccount.balance_credits, encrypted_balance: encryptedBalance,
      version: updatedAccount.version, updated_at: occurredAt,
    });
    if (updated !== 1) fail(409, 'stale_team_credit_balance');
    const creditEvent = {
      id: randomUUID(), event_id: eventId, hashed_team_id: teamHash, actor_user_hash: actorHash,
      event_type: eventType, amount: credits, encrypted_metadata: encryptedMetadata, created_at: occurredAt,
    };
    await trx(TEAM_CREDIT_EVENTS).insert(creditEvent);
    return { account: updatedAccount, credit_event: creditEvent, idempotent: false };
  });
}

export const operations = Object.freeze({
  health_check: healthCheck,
  create_root: createRoot,
  approve_root_limits: approveRootLimits,
  prepare_batch: prepareBatch,
  claim_child: claimChild,
  transition_child: transitionChild,
  transition_root: transitionRoot,
  claim_parent_continuation: claimParentContinuation,
  mark_parent_continuation_dispatched: markParentContinuationDispatched,
  get_root_state: getRootState,
  reserve_operation: reserveOperation,
  fail_operation: failOperation,
  cleanup_expired_reservations: cleanupExpiredReservations,
  commit_personal_charge: commitPersonalCharge,
  commit_personal_refund: commitPersonalRefund,
  get_personal_charge: getPersonalCharge,
  create_or_reuse_pending_settlement: createOrReusePendingSettlement,
  get_pending_settlement: getPendingSettlement,
  replay_pending_settlement: replayPendingSettlement,
  complete_pending_settlement: completePendingSettlement,
  transition_pending_settlement_to_manual_review: transitionPendingSettlementToManualReview,
  commit_team_charge: commitTeamCharge,
  commit_team_credit_add: commitTeamCreditAdd,
});

export async function executeOperation(database, operation, data, now = new Date()) {
  const handler = operations[operation];
  if (!handler) fail(400, 'unsupported_operation');
  return handler(database, data, now);
}

export const testing = Object.freeze({
  validatedChildren, tokenHash, PROTOCOL_VERSION, MAX_DEPTH,
  AUTO_DESCENDANT_LIMIT, MAX_DESCENDANT_LIMIT, AUTO_CREDIT_LIMIT,
  operationReservationFits,
});
