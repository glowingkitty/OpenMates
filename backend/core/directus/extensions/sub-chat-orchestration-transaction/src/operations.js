/*
 * PostgreSQL-backed root limits and atomic encrypted-safe child preparation.
 * Payload validation rejects content-bearing fields before any database write.
 */
import { createHash, randomUUID } from 'node:crypto';
import { quoteUsage } from '../../storage-usage-metering/src/quote.js';

const ORCHESTRATIONS = 'sub_chat_orchestrations';
const CHILDREN = 'sub_chat_orchestration_children';
const BATCHES = 'sub_chat_orchestration_batches';
const OPERATIONS = 'sub_chat_orchestration_operations';
const CHATS = 'chats';
const USERS = 'directus_users';
const CHARGE_IDENTITIES = 'billing_charge_identities';
const REFUND_IDENTITIES = 'billing_refund_identities';
const SETTLEMENT_OUTBOX = 'billing_settlement_outbox';
const STORAGE_PERIODS = 'storage_billing_periods';
const STORAGE_OWNERS = 'storage_billing_owner_state';
const TEAM_STORAGE_PERIODS = 'team_storage_billing_periods';
const TEAM_STORAGE_OWNERS = 'team_storage_billing_owner_state';
const TEAM_STORAGE_UNITS = 'team_storage_billing_warning_units';
const TEAM_STORAGE_POLICY = 'team-storage-1gb-3credits-week-v1';
const TEAM_STORAGE_SYSTEM_ACTOR = createHash('sha256').update('system:team-storage').digest('hex');
const EMAIL_DELIVERIES = 'email_deliveries';
const STORAGE_WARNING_INTERVAL_SECONDS = 7 * 24 * 60 * 60;
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
  freeze_storage_period: new Set([
    'protocol_version', 'user_id', 'hashed_user_id', 'period_start_at',
    'measured_bytes', 'credits_due', 'charge_id', 'free_bytes',
    'credits_per_gib', 'policy_version', 'source_version', 'category_bytes',
  ]),
  list_storage_debt: new Set(['protocol_version', 'user_id', 'hashed_user_id']),
  mark_storage_period_paid: new Set([
    'protocol_version', 'user_id', 'hashed_user_id', 'period_id',
  ]),
  claim_storage_warning: new Set([
    'protocol_version', 'user_id', 'hashed_user_id', 'now_at',
  ]),
  acknowledge_storage_warning: new Set([
    'protocol_version', 'user_id', 'hashed_user_id', 'episode_id',
    'warning_stage', 'delivery_id', 'now_at',
  ]),
  record_storage_delivery_receipt: new Set([
    'protocol_version', 'user_id', 'hashed_user_id', 'episode_id',
    'warning_stage', 'delivery_id', 'message_id', 'state', 'observed_at', 'now_at',
  ]),
  freeze_storage_warning_units: new Set(['protocol_version','user_id','hashed_user_id','episode_id','now_at']),
  list_storage_warning_units: new Set(['protocol_version','user_id','hashed_user_id','episode_id','after_unit_id','limit']),
  apply_storage_expiry: new Set(['protocol_version','user_id','hashed_user_id','episode_id','expected_encrypted_balance','regions','now_at']),
  inspect_storage_expiry: new Set([
    'protocol_version', 'user_id', 'hashed_user_id', 'now_at',
  ]),
  close_storage_billing_for_deleted_account: new Set([
    'protocol_version', 'user_id', 'hashed_user_id',
  ]),
  mark_storage_warning_manual_review: new Set([
    'protocol_version', 'user_id', 'hashed_user_id', 'episode_id',
    'warning_stage', 'delivery_id', 'now_at',
  ]),
  freeze_team_storage_period: new Set(['protocol_version','hashed_team_id','period_start_at','measured_bytes','credits_due','charge_id','free_bytes','credits_per_gib','policy_version','source_version','category_bytes']),
  list_team_storage_debt: new Set(['protocol_version','hashed_team_id']),
  commit_team_storage_charge: new Set(['protocol_version','hashed_team_id','period_id','expected_version','occurred_at']),
  claim_team_storage_warning: new Set(['protocol_version','hashed_team_id','now_at']),
  list_team_storage_recipients: new Set(['protocol_version','hashed_team_id']),
  freeze_team_storage_warning_units: new Set(['protocol_version','hashed_team_id','episode_id','now_at']),
  list_team_storage_warning_units: new Set(['protocol_version','hashed_team_id','episode_id','limit','after_unit_id']),
  acknowledge_team_storage_warning: new Set(['protocol_version','hashed_team_id','episode_id','warning_stage','recipient_hashes','now_at']),
  record_team_storage_delivery_receipt: new Set(['protocol_version','hashed_team_id','episode_id','warning_stage','recipient_hash','delivery_id','message_id','state','observed_at','now_at']),
  mark_team_storage_warning_manual_review: new Set(['protocol_version','hashed_team_id','episode_id','warning_stage','recipient_hash','delivery_id','now_at']),
  set_team_storage_notice_hold: new Set(['protocol_version','hashed_team_id','episode_id','reason']),
  inspect_team_storage_expiry: new Set(['protocol_version','hashed_team_id','now_at']),
  apply_team_storage_expiry: new Set(['protocol_version','hashed_team_id','episode_id','expected_version','now_at','regions']),
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
    await trx.raw('SELECT pg_advisory_xact_lock(hashtextextended(?, 0))', [`storage-billing:${ownerHash}`]);
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
    if (appId === 'system' && skillId === 'storage') {
      const storageOwner = await trx(STORAGE_OWNERS).where({ id: ownerHash }).first();
      // Legacy workers identify invoices by Unix week number, while frozen
      // invoices use Sunday epoch seconds. Permit only that exact old namespace
      // to drain; existing frozen rows always keep their terminal-state fence.
      const suffix=chargeId.startsWith(`storage:${ownerHash}:`)?chargeId.slice(`storage:${ownerHash}:`.length):'';
      const legacyWeek=/^(0|[1-9][0-9]*)$/.test(suffix)&&Number.isSafeInteger(Number(suffix))
        && Number(suffix)<=Math.floor(now.getTime()/1000/STORAGE_WARNING_INTERVAL_SECONDS)+1;
      if (storageOwner?.closed_at || (!storageOwner&&!legacyWeek)) fail(409, 'storage_owner_closed');
      const period=await trx(STORAGE_PERIODS).where({charge_id:chargeId,user_id:userId,hashed_user_id:ownerHash}).forUpdate().first();
      if((period&&period.state!=='unpaid')||(!period&&!legacyWeek)) fail(409,'storage_period_not_chargeable');

    }
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
    await trx.raw('SELECT pg_advisory_xact_lock(hashtextextended(?, 0))', [`storage-billing:${ownerHash}`]);
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
    if (chargeId.startsWith('storage:')) {
      const prefix = `storage:${ownerHash}:`;
      if (!chargeId.startsWith(prefix)) fail(409, 'storage_owner_mismatch');
      const suffix = chargeId.slice(prefix.length);
      const legacyWeek = /^(0|[1-9][0-9]*)$/.test(suffix)
        && Number.isSafeInteger(Number(suffix))
        && Number(suffix) <= Math.floor(now.getTime() / 1000 / STORAGE_WARNING_INTERVAL_SECONDS) + 1;
      const owner = await trx(STORAGE_OWNERS).where({ id: ownerHash }).forUpdate().first();
      if (owner?.closed_at || (!owner && !legacyWeek)) fail(409, 'storage_owner_closed');
      const period = await trx(STORAGE_PERIODS).where({
        charge_id: chargeId, user_id: userId, hashed_user_id: ownerHash,
      }).forUpdate().first();
      if ((period && period.state !== 'unpaid') || (!period && !legacyWeek)) {
        fail(409, 'storage_period_not_chargeable');
      }
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
  if (eventId.startsWith('team-storage:')) fail(403, 'reserved_team_storage_charge');
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
  if (eventId.startsWith('team-storage:')) fail(403, 'reserved_team_storage_charge');
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

// Only selected complete units are persisted. Discovery stays in PostgreSQL;
// fingerprints commit to canonical rows without retaining keys or ciphertext.
const STORAGE_UNITS = 'storage_billing_warning_units';
const FREE_STORAGE_BYTES = 1_073_741_824;
const EXPIRY_TABLES = [
  'upload_files', 'embeds', 'embed_keys', 'embed_diffs', 'chats', 'chat_key_wrappers',
  'messages', 'drafts', 'chat_compression_checkpoints', 'code_run_outputs',
  'notebook_run_outputs', 'message_highlights', 'cold_archive_manifests', 'cold_archive_parts',
  'chat_message_archive_pages', 'chat_message_archive_segments', 'chat_recovery_outputs',
  'project_items', 'storage_replication_jobs', 'storage_deletion_tombstones',
  'workspace_change_archives', 'sub_chat_orchestrations', 'sub_chat_orchestration_children',
];
const jsonValue = (value) => typeof value === 'string' ? JSON.parse(value) : value;
const safeUnit = (unit) => ({ unit_id: unit.unit_id, kind: ({independent_upload:'upload',archived_chat_graph:'cold_chat',artifact_history_prefix:'artifact_history'})[unit.kind],
  resource_id: unit.resource_id, oldest_at: Number(unit.oldest_at),
  bytes: Number(unit.bytes), fingerprint: unit.fingerprint });

// Coarse locks prevent a new reference, publication, ownership move or writer
// lease from racing the final validation. All waits remain transaction scoped.
async function lockExpiryReferences(trx) {
  await trx.raw("SET LOCAL lock_timeout = '2s'");
  await trx.raw(`LOCK TABLE ${[...EXPIRY_TABLES].sort().join(', ')} IN SHARE ROW EXCLUSIVE MODE`);
}

const unitFingerprint = (unit) => tokenHash(JSON.stringify({
  kind: unit.kind, resource_id: unit.resource_id, oldest_at: Number(unit.oldest_at),
  bytes: Number(unit.bytes), rows: unit.rows, objects: unit.objects,
}));

async function discoverStorageUnits(trx, userId, ownerHash, nowAt, ownerKind = 'personal') {
  const response = await trx.raw(`
WITH scope AS (SELECT ?::text AS user_id, ?::text AS owner_hash, ?::integer AS now_at),
independent_uploads AS (
  SELECT 'independent_upload'::text AS kind, u.id::text AS resource_id,
    u.created_at AS oldest_at, u.file_size_bytes::bigint AS bytes,
    jsonb_build_array(jsonb_build_object('collection','upload_files','id',u.id,
      'fingerprint',encode(digest(to_jsonb(u)::text,'sha256'),'hex'))) AS rows,
    (SELECT jsonb_agg(jsonb_build_object('logical_bucket','chatfiles','object_key',v.value->>'s3_key')
      ORDER BY v.value->>'s3_key') FROM jsonb_each(u.files_metadata::jsonb) v) AS objects
  FROM upload_files u, scope s
  WHERE u.user_id=s.user_id AND coalesce(u.embed_id,'')<>'' AND u.created_at IS NOT NULL AND u.file_size_bytes>0
    AND jsonb_typeof(u.files_metadata::jsonb)='object' AND u.files_metadata::jsonb<>'{}'::jsonb
    AND NOT EXISTS (SELECT 1 FROM jsonb_each(u.files_metadata::jsonb) v
      WHERE jsonb_typeof(v.value)<>'object' OR coalesce(v.value->>'s3_key','')='')
    AND NOT EXISTS (SELECT 1 FROM embeds e WHERE e.embed_id=u.embed_id
      OR e.parent_embed_id=u.embed_id OR coalesce(e.embed_ids::text,'') LIKE '%'||u.embed_id||'%')
    AND NOT EXISTS (SELECT 1 FROM embed_keys k
      WHERE k.hashed_embed_id=encode(digest(u.embed_id,'sha256'),'hex'))
    AND NOT EXISTS (SELECT 1 FROM project_items p WHERE p.target_id_hash IN
      (encode(digest(u.id::text,'sha256'),'hex'),encode(digest(u.embed_id,'sha256'),'hex')))
),
standalone_cold AS (
 SELECT 'archived_chat_graph'::text AS kind,c.id::text AS resource_id,
   m.archived_at AS oldest_at,sum(p.size_bytes)::bigint AS bytes,
   jsonb_build_array(jsonb_build_object('collection','chats','id',c.id,
     'fingerprint',encode(digest(to_jsonb(c)::text,'sha256'),'hex')),
     jsonb_build_object('collection','cold_archive_manifests','id',m.id,
     'fingerprint',encode(digest(to_jsonb(m)::text,'sha256'),'hex')))
   ||jsonb_agg(jsonb_build_object('collection','cold_archive_parts','id',p.id,
     'fingerprint',encode(digest(to_jsonb(p)::text,'sha256'),'hex')) ORDER BY p.id) AS rows,
   jsonb_agg(jsonb_build_object('logical_bucket',p.logical_bucket,'object_key',p.object_key)
     ORDER BY p.logical_bucket,p.object_key) AS objects
 FROM chats c JOIN cold_archive_manifests m ON m.resource_id=c.id::text
 JOIN cold_archive_parts p ON p.archive_id=m.archive_id,scope s
 WHERE ((s.user_id IS NULL AND c.hashed_team_id=s.owner_hash AND m.hashed_team_id=s.owner_hash)
     OR (s.user_id IS NOT NULL AND c.hashed_user_id=s.owner_hash AND c.hashed_team_id IS NULL
       AND m.hashed_user_id=s.owner_hash AND m.hashed_team_id IS NULL)) AND c.storage_state='cold'
   AND c.parent_id IS NULL AND NOT coalesce(c.is_shared,false) AND NOT coalesce(c.shared_public,false)
   AND NOT coalesce(c.share_with_community,false) AND coalesce(c.shared_with_user_hashes::text,'[]') IN ('[]','null')
   AND m.state='cold' AND m.resource_type='chat'
   AND m.hashed_resource_id=encode(digest(c.id::text,'sha256'),'hex')
   AND m.archive_id=c.cold_archive_id AND m.active_generation=c.cold_generation
   AND m.file_references::jsonb='[]'::jsonb AND m.promotion_intent IS NULL
   AND NOT EXISTS (SELECT 1 FROM chats child WHERE child.parent_id=c.id)
   AND NOT EXISTS (SELECT 1 FROM cold_archive_manifests other
     WHERE other.resource_id=c.id::text AND other.id<>m.id)
   AND NOT EXISTS (SELECT 1 FROM chat_key_wrappers k
     WHERE k.hashed_chat_id=encode(digest(c.id::text,'sha256'),'hex'))
   AND NOT EXISTS (SELECT 1 FROM project_items pi
     WHERE pi.target_id_hash=encode(digest(c.id::text,'sha256'),'hex'))
   AND NOT EXISTS (SELECT 1 FROM embeds e WHERE e.hashed_chat_id=encode(digest(c.id::text,'sha256'),'hex'))
   AND NOT EXISTS (SELECT 1 FROM messages x WHERE x.chat_id=c.id::text)
   AND NOT EXISTS (SELECT 1 FROM chat_message_archive_pages x WHERE x.chat_id=c.id::text)
   AND NOT EXISTS (SELECT 1 FROM chat_message_archive_segments x WHERE x.chat_id=c.id::text)
   AND NOT EXISTS (SELECT 1 FROM chat_recovery_outputs x WHERE x.root_chat_id=c.id OR x.target_chat_id=c.id)
   AND NOT EXISTS (SELECT 1 FROM sub_chat_orchestrations x WHERE x.root_chat_id=c.id AND x.status='active')
   AND NOT EXISTS (SELECT 1 FROM sub_chat_orchestration_children x WHERE x.child_chat_id=c.id AND x.state IN ('prepared','dispatched','running'))
   AND NOT EXISTS (SELECT 1 FROM drafts x WHERE x.chat_id=c.id::text)
   AND NOT EXISTS (SELECT 1 FROM chat_compression_checkpoints x WHERE x.chat_id=c.id::text)
   AND NOT EXISTS (SELECT 1 FROM code_run_outputs x WHERE x.chat_id=c.id::text)
   AND NOT EXISTS (SELECT 1 FROM notebook_run_outputs x WHERE x.chat_id=c.id::text)
   AND NOT EXISTS (SELECT 1 FROM message_highlights x WHERE x.chat_id=c.id::text)
 GROUP BY c.id,m.id
 HAVING count(*)=m.part_count AND count(DISTINCT p.logical_bucket||':'||p.object_key)=count(*) AND bool_and(p.generation=m.active_generation
   AND p.size_bytes>0 AND p.object_key<>'' AND p.logical_bucket='cold_archives'
   AND p.checksum<>'' AND jsonb_typeof(p.regional_states::jsonb)='object'
   AND p.regional_states::jsonb<>'{}'::jsonb
   AND NOT EXISTS (SELECT 1 FROM jsonb_each_text(p.regional_states::jsonb) region WHERE region.value<>'verified'))
),
version_boundaries AS (
 SELECT e.embed_id,e.id,c.id AS chat_id,max(d.version_number) FILTER
   (WHERE d.version_number<e.version_number AND coalesce(d.has_snapshot,false)
     AND (coalesce(d.encrypted_snapshot,'')<>'' OR (d.archive_state IN ('reader_active','pruned')
       AND d.archive_object_key<>'' AND d.archive_checksum<>'' AND d.archive_reader_activated_at IS NOT NULL))) AS boundary
 FROM embeds e JOIN chats c ON e.hashed_chat_id=encode(digest(c.id::text,'sha256'),'hex')
 JOIN embed_diffs d ON d.embed_id=e.embed_id AND d.hashed_user_id=e.hashed_user_id,scope s
 WHERE s.user_id IS NOT NULL AND e.hashed_user_id=s.owner_hash AND c.hashed_user_id=s.owner_hash AND c.hashed_team_id IS NULL
   AND coalesce(c.storage_state,'hot') IN ('hot','cold')
   AND coalesce(c.updated_at,c.last_message_timestamp,c.created_at)>0
   AND coalesce(c.updated_at,c.last_message_timestamp,c.created_at)<=s.now_at-28*86400
   AND coalesce(e.updated_at,e.created_at)>0 AND coalesce(e.updated_at,e.created_at)<=s.now_at-28*86400
   AND NOT coalesce(e.is_shared,false)
   AND NOT coalesce(c.is_shared,false) AND NOT coalesce(c.shared_public,false)
   AND NOT coalesce(c.share_with_community,false)
   AND coalesce(c.shared_with_user_hashes::text,'[]') IN ('[]','null')
   AND NOT EXISTS (SELECT 1 FROM project_items pi WHERE pi.target_id_hash IN
     (encode(digest(e.embed_id,'sha256'),'hex'),encode(digest(c.id::text,'sha256'),'hex')))
   AND NOT EXISTS (SELECT 1 FROM embed_keys k WHERE k.hashed_embed_id=encode(digest(e.embed_id,'sha256'),'hex')
     AND (k.hashed_user_id<>s.owner_hash OR k.key_type NOT IN ('master','chat')
       OR k.hashed_project_id IS NOT NULL OR k.hashed_plan_id IS NOT NULL OR k.hashed_team_id IS NOT NULL
       OR (k.key_type='chat' AND k.hashed_chat_id IS DISTINCT FROM e.hashed_chat_id)))
   AND NOT EXISTS (SELECT 1 FROM chat_recovery_outputs recovery
     WHERE (recovery.root_chat_id=c.id OR recovery.target_chat_id=c.id) AND recovery.deleted_at IS NULL)
   AND NOT EXISTS (SELECT 1 FROM sub_chat_orchestrations active WHERE active.root_chat_id=c.id AND active.status='active')
   AND NOT EXISTS (SELECT 1 FROM sub_chat_orchestration_children active WHERE active.child_chat_id=c.id
     AND active.state IN ('prepared','dispatched','running'))
   AND NOT EXISTS (SELECT 1 FROM chat_key_wrappers k WHERE k.hashed_chat_id=e.hashed_chat_id
     AND (k.hashed_user_id<>s.owner_hash OR k.key_type<>'master' OR k.hashed_team_id IS NOT NULL
       OR k.hashed_project_id IS NOT NULL OR k.hashed_plan_id IS NOT NULL))
   AND NOT EXISTS (SELECT 1 FROM embeds other WHERE other.embed_id=e.embed_id AND other.id<>e.id)
 GROUP BY e.embed_id,e.id,c.id
),
old_prefixes AS (
 SELECT 'artifact_history_prefix'::text AS kind,b.embed_id AS resource_id,min(d.created_at) AS oldest_at,
   sum(d.archive_size_bytes)::bigint AS bytes,
   jsonb_agg(jsonb_build_object('collection','embed_diffs','id',d.id,
     'fingerprint',encode(digest(to_jsonb(d)::text,'sha256'),'hex')) ORDER BY d.id) AS rows,
   jsonb_agg(jsonb_build_object('logical_bucket','chatfiles','object_key',d.archive_object_key)
     ORDER BY d.archive_object_key) AS objects
 FROM version_boundaries b JOIN embed_diffs d ON d.embed_id=b.embed_id,scope s
 WHERE b.boundary>2 AND d.archive_hashed_chat_id=encode(digest(b.chat_id::text,'sha256'),'hex') AND d.version_number>1 AND d.version_number<b.boundary
 GROUP BY b.embed_id,b.boundary
 HAVING count(*)=b.boundary-2 AND count(DISTINCT d.archive_object_key)=count(*) AND bool_and(d.hashed_user_id=(SELECT owner_hash FROM scope)
   AND d.archive_state IN ('reader_active','pruned') AND d.archive_owner_kind='personal'
   AND d.archive_owner_hash=(SELECT owner_hash FROM scope) AND d.archive_object_key<>''
   AND d.archive_checksum<>'' AND d.archive_size_bytes>0 AND d.archive_reader_activated_at IS NOT NULL
   AND d.archive_pending_object_key IS NULL AND d.archive_superseded_object_key IS NULL
   AND d.archive_copy_lease_until IS NULL)
)
, candidates AS (
 SELECT * FROM independent_uploads UNION ALL SELECT * FROM standalone_cold UNION ALL SELECT * FROM old_prefixes
), bounded AS (
 SELECT candidates.*,sum(jsonb_array_length(objects)) OVER (ORDER BY oldest_at,kind,resource_id) AS object_count
 FROM candidates WHERE jsonb_array_length(rows)<=2000 AND jsonb_array_length(objects)<=2000
)
SELECT kind,resource_id,oldest_at,bytes,rows,objects FROM bounded WHERE object_count<=2000
 ORDER BY oldest_at,kind,resource_id LIMIT 100
`, [ownerKind === 'team' ? null : userId, ownerHash, nowAt]);
  return response.rows.map((row) => {
    const unit = { ...row, oldest_at: Number(row.oldest_at), bytes: Number(row.bytes),
      rows: jsonValue(row.rows), objects: jsonValue(row.objects) };
    unit.unit_id = tokenHash(`${unit.kind}:${unit.resource_id}`);
    unit.fingerprint = unitFingerprint(unit);
    return unit;
  });
}

// Every supported live object reference is inventoried globally. Unknown shapes
// protect candidates instead of treating a missing locator as absence.
async function storageObjectReferences(trx, objects) {
  const requestedObjects = [...new Map(objects.map((obj)=>[`${obj.logical_bucket}\0${obj.object_key}`,obj])).values()];
  const response = await trx.raw(`
WITH requested_objects AS (SELECT * FROM jsonb_to_recordset(?::jsonb) AS x(logical_bucket text,object_key text)), refs AS (
 SELECT 'upload_files'::text AS collection,u.id::text AS id,'chatfiles'::text AS bucket,
   v.value->>'s3_key' AS object_key FROM upload_files u CROSS JOIN LATERAL jsonb_each(
     CASE WHEN jsonb_typeof(u.files_metadata::jsonb)='object' THEN u.files_metadata::jsonb ELSE '{}'::jsonb END) v
 UNION ALL SELECT 'embeds',e.id::text,v.value->>'bucket',v.value->>'key'
   FROM embeds e CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(e.s3_file_keys::jsonb)='array'
     THEN e.s3_file_keys::jsonb ELSE '[]'::jsonb END) v
 UNION ALL SELECT 'embed_diffs',id::text,'chatfiles',archive_object_key FROM embed_diffs WHERE archive_object_key IS NOT NULL
 UNION ALL SELECT 'embed_diffs',id::text,'chatfiles',archive_pending_object_key FROM embed_diffs WHERE archive_pending_object_key IS NOT NULL
 UNION ALL SELECT 'embed_diffs',id::text,'chatfiles',archive_superseded_object_key FROM embed_diffs WHERE archive_superseded_object_key IS NOT NULL
 UNION ALL SELECT 'cold_archive_parts',id::text,logical_bucket,object_key FROM cold_archive_parts
 UNION ALL SELECT 'cold_archive_manifests',m.id::text,v.value->>'logical_bucket',v.value->>'object_key'
   FROM cold_archive_manifests m CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(m.file_references::jsonb)='array'
     THEN m.file_references::jsonb ELSE '[]'::jsonb END) v
 UNION ALL SELECT 'chat_message_archive_pages',id::text,'cold_archives',object_key FROM chat_message_archive_pages
 UNION ALL SELECT 'chat_message_archive_pages',p.id::text,'cold_archives',v.value->>'object_key'
   FROM chat_message_archive_pages p CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(p.large_objects::jsonb)='array'
     THEN p.large_objects::jsonb ELSE '[]'::jsonb END) v
 UNION ALL SELECT 'chat_recovery_outputs',id::text,'cold_archives',payload_s3_key FROM chat_recovery_outputs WHERE payload_s3_key IS NOT NULL
 UNION ALL SELECT 'workspace_change_archives',id::text,s3_bucket_key,s3_object_key FROM workspace_change_archives WHERE s3_object_key IS NOT NULL
)
SELECT coalesce(jsonb_agg(to_jsonb(matching)),'[]'::jsonb) AS refs,
 EXISTS(SELECT 1 FROM embeds WHERE s3_file_keys IS NOT NULL AND jsonb_typeof(s3_file_keys::jsonb)<>'array')
 OR EXISTS(SELECT 1 FROM upload_files WHERE files_metadata IS NULL OR jsonb_typeof(files_metadata::jsonb)<>'object')
 OR EXISTS(SELECT 1 FROM cold_archive_manifests WHERE file_references IS NULL OR jsonb_typeof(file_references::jsonb)<>'array')
 OR EXISTS(SELECT 1 FROM chat_message_archive_pages WHERE large_objects IS NULL OR jsonb_typeof(large_objects::jsonb)<>'array')
 OR EXISTS(SELECT 1 FROM embed_diffs WHERE
   (archive_state IS NOT NULL AND archive_state NOT IN ('hot','preparing','stale','copied','ready','reader_active','pruned'))
   OR (archive_state IN ('copied','ready','reader_active','pruned') AND coalesce(btrim(archive_object_key),'')='')
   OR (archive_state='preparing' AND coalesce(btrim(archive_pending_object_key),'')=''))
 OR EXISTS(SELECT 1 FROM chat_recovery_outputs WHERE
   (payload_storage IS NOT NULL AND payload_storage NOT IN ('inline','s3'))
   OR (payload_storage='s3' AND coalesce(btrim(payload_s3_key),'')=''))
 OR EXISTS(SELECT 1 FROM refs WHERE coalesce(btrim(bucket),'')='' OR coalesce(btrim(object_key),'')='') AS ambiguous
FROM (SELECT refs.* FROM refs JOIN requested_objects o ON o.logical_bucket=refs.bucket AND o.object_key=refs.object_key LIMIT 2001) matching`, [JSON.stringify(requestedObjects)]);
  const row = response.rows[0];
  if (!row || row.ambiguous !== false || jsonValue(row.refs).length>2000) fail(409, 'storage_reference_inventory_incomplete');
  return jsonValue(row.refs);
}

function independentlyReferenced(unit, references) {
  const rowIds = new Set(unit.rows.map((row) => `${row.collection}:${row.id}`));
  return unit.objects.some((obj) => references.some((ref) => ref.bucket === obj.logical_bucket
    && ref.object_key === obj.object_key && !rowIds.has(`${ref.collection}:${ref.id}`)));
}

async function blockedStorageWriters(trx,objects) {
  const response=await trx.raw(`WITH requested_objects AS
    (SELECT * FROM jsonb_to_recordset(?::jsonb) AS x(logical_bucket text,object_key text))
    SELECT DISTINCT j.logical_bucket,j.object_key FROM storage_replication_jobs j
    JOIN requested_objects o ON o.logical_bucket=j.logical_bucket AND o.object_key=j.object_key
    WHERE j.state IS NULL OR j.state NOT IN ('verified','completed','cancelled') LIMIT 2001`,[JSON.stringify(objects)]);
  if(response.rows.length>2000) fail(409,'storage_writer_inventory_incomplete');
  return new Set(response.rows.map((row)=>`${row.logical_bucket}\0${row.object_key}`));
}

async function currentStorageQuote(trx, userId, sourceVersion, teamHash = null) {
  if (!['legacy-upload-files-v1','logical-s3-v1'].includes(sourceVersion)) fail(409,'storage_warning_policy_unknown');
  if (teamHash && sourceVersion !== 'logical-s3-v1') fail(409,'storage_warning_policy_unknown');
  return (await quoteUsage(trx, { user_ids: teamHash ? [] : [userId], team_hashes: teamHash ? [teamHash] : [], legacy_only: sourceVersion==='legacy-upload-files-v1' }))[0];
}

async function freezeStorageWarningUnits(database, raw, now) {
  const { body, userId, ownerHash } = storageOwner(raw, 'freeze_storage_warning_units');
  const nowAt = integer(body.now_at, 'invalid_storage_now');
  const suppliedEpisode = body.episode_id == null ? null : uuid(body.episode_id, 'invalid_storage_episode');
  return database.transaction(async (trx) => {
    const owner = await lockedStorageOwner(trx, userId, ownerHash, now);
    if (owner.closed_at || owner.warning_manual_review_at) return { frozen: false, held: true, reason: 'owner_held' };
    if (suppliedEpisode && owner.episode_id !== suppliedEpisode) fail(409, 'storage_episode_mismatch');
    if (owner.selection_hash) {
      const units = await trx(STORAGE_UNITS).where({ hashed_user_id: ownerHash, episode_id: owner.episode_id }).orderBy('unit_id','asc');
      return { frozen: true, held: false, idempotent: true, episode_id: owner.episode_id,
        unit_selection_hash: owner.selection_hash, units: units.map(safeUnit),
        period_ids: jsonValue(owner.warned_period_ids), selected_bytes: Number(owner.selected_bytes) };
    }
    if (Number(owner.warning_count)>0) return { frozen: false, held: true, reason: 'warning_selection_missing' };
    const periods = await trx(STORAGE_PERIODS).where({ hashed_user_id: ownerHash,state:'unpaid' }).orderBy('period_start_at','asc').limit(101);
    if (!periods.length) return { frozen: false,held:true,reason:'no_debt' };
    if (periods.length>100) return { frozen:false,held:true,reason:'warning_debt_limit' };
    const sourceVersion=periods[0].source_version;
    if(periods.some((period)=>period.source_version!==sourceVersion||period.policy_version!==periods[0].policy_version)) {
      return {frozen:false,held:true,reason:'mixed_storage_policy'};
    }
    await lockExpiryReferences(trx);
    const quote = await currentStorageQuote(trx,userId,sourceVersion);
    if (quote.total_bytes<=FREE_STORAGE_BYTES) return { frozen:false,held:true,reason:'within_free_storage' };
    const candidates = (await discoverStorageUnits(trx,userId,ownerHash,nowAt)).filter((unit)=>sourceVersion!=='legacy-upload-files-v1'||unit.kind==='independent_upload');
    const references = await storageObjectReferences(trx,candidates.flatMap((unit)=>unit.objects));
    const blocked=await blockedStorageWriters(trx,candidates.flatMap((unit)=>unit.objects));
    const units=[]; let selectedBytes=0; let objectCount=0;
    const seen = new Set();
    for (const unit of candidates) {
      if (units.length>=100 || objectCount+unit.objects.length>2000) break;
      if (!Number.isSafeInteger(unit.bytes) || unit.bytes<=0 || unit.rows.length>2000
        || independentlyReferenced(unit,references)
        || unit.objects.some((obj)=>blocked.has(`${obj.logical_bucket}\0${obj.object_key}`))) continue;
      if (unit.objects.some((obj) => seen.has(`${obj.logical_bucket}:${obj.object_key}`))) continue;
      units.push(unit); selectedBytes+=unit.bytes; objectCount+=unit.objects.length;
      unit.objects.forEach((obj)=>seen.add(`${obj.logical_bucket}:${obj.object_key}`));
      if (quote.total_bytes-selectedBytes<=FREE_STORAGE_BYTES) break;
    }
    if (!units.length || quote.total_bytes-selectedBytes>FREE_STORAGE_BYTES) {
      return { frozen:false,held:true,reason:'no_complete_safe_set',total_bytes:quote.total_bytes };
    }
    const episodeId=owner.episode_id||randomUUID();
    const selectionHash=tokenHash(JSON.stringify(units.map((unit)=>[unit.unit_id,unit.fingerprint])));
    for (const unit of units) await trx(STORAGE_UNITS).insert({
      id: tokenHash(`${episodeId}:${unit.unit_id}`),hashed_user_id:ownerHash,episode_id:episodeId,
      unit_id:unit.unit_id,kind:unit.kind,resource_id:unit.resource_id,oldest_at:unit.oldest_at,
      bytes:unit.bytes,fingerprint:unit.fingerprint,membership:JSON.stringify(unit.rows),
      object_references:JSON.stringify(unit.objects),created_at:now,
    });
    await trx(STORAGE_OWNERS).where({id:ownerHash}).update({episode_id:episodeId,
      selection_hash:selectionHash,selection_at:nowAt,selected_bytes:selectedBytes,
      selection_source_version:sourceVersion,selection_policy_version:periods[0].policy_version,
      warned_period_ids:JSON.stringify(periods.map((period)=>period.id)),updated_at:now});
    return { frozen:true,held:false,idempotent:false,episode_id:episodeId,
      unit_selection_hash:selectionHash,units:[...units].sort((a,b)=>a.unit_id.localeCompare(b.unit_id)).map(safeUnit),period_ids:periods.map((period)=>period.id),
      total_bytes:quote.total_bytes,selected_bytes:selectedBytes,expected_after_bytes:quote.total_bytes-selectedBytes };
  });
}

async function listStorageWarningUnits(database,raw,now) {
  const {body,userId,ownerHash}=storageOwner(raw,'list_storage_warning_units');
  const episodeId=body.episode_id==null?null:uuid(body.episode_id,'invalid_storage_episode');
  const limit=integer(body.limit??100,'invalid_storage_unit_limit');
  if(limit<1||limit>100) fail(400,'invalid_storage_unit_limit');
  const after=body.after_unit_id==null?null:string(body.after_unit_id,'invalid_storage_unit_cursor',64);
  return database.transaction(async(trx)=>{
    const owner=await trx(STORAGE_OWNERS).where({id:ownerHash,user_id:userId}).first();
    if(!owner) return {episode_id:null,warning_count:0,deadline_at:null,manual_review:false,unit_selection_hash:null,units:[],has_more:false,next_after_unit_id:null};
    if(episodeId && episodeId!==owner.episode_id) fail(409,'storage_episode_mismatch');
    const query=trx(STORAGE_UNITS).where({hashed_user_id:ownerHash,episode_id:owner.episode_id}).orderBy('unit_id','asc').limit(limit+1);
    if(after) query.where('unit_id','>',after);
    const rows=owner.episode_id?await query:[];
    const units=rows.slice(0,limit).map(safeUnit);
    return {episode_id:owner.episode_id,warning_count:Number(owner.warning_count),deadline_at:owner.deadline_at,
      manual_review:Boolean(owner.warning_manual_review_at),unit_selection_hash:owner.selection_hash??null,
      units,has_more:rows.length>limit,next_after_unit_id:rows.length>limit?units.at(-1).unit_id:null};
  });
}

async function storageExpiryGate(trx,owner,userId,nowAt) {
  if(owner.closed_at||owner.warning_manual_review_at||!owner.selection_hash||Number(owner.warning_count)!==4) return false;
  const keys=[1,2,3,4].map((stage)=>`storage-billing-warning:${owner.episode_id}:directus_user:${userId}:week-${stage}`);
  const receipts=await trx(EMAIL_DELIVERIES).whereIn('delivery_key',keys).forShare();
  if(receipts.length!==4) return false;
  let firstAt; let priorAt;
  for(const key of keys) {
    const matches=receipts.filter((r)=>r.delivery_key===key);
    if(matches.length!==1) return false;
    const r=matches[0]; const at=Math.floor(Date.parse(r.provider_delivered_at)/1000);
    let metadata; try{metadata=jsonValue(r.metadata);}catch{return false;}
    const date=metadata?.context?.deadline_date;
    if(r.status!=='sent'||r.provider_delivery_state!=='delivered'||!r.storage_warning_acknowledged_at
      ||!Number.isFinite(at)||at<Number(owner.selection_at)||metadata?.context?.unit_selection_hash!==owner.selection_hash
      ||typeof date!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(date)) return false;
    const advertised=Math.floor(Date.parse(`${date}T00:00:00Z`)/1000);
    if(!Number.isFinite(advertised)||nowAt<advertised|| (priorAt!=null&&at<priorAt+STORAGE_WARNING_INTERVAL_SECONDS)) return false;
    firstAt??=at;priorAt=at;
  }
  return nowAt>=firstAt+4*STORAGE_WARNING_INTERVAL_SECONDS && nowAt>=priorAt+STORAGE_WARNING_INTERVAL_SECONDS
    && nowAt>=Number(owner.deadline_at) && nowAt>=Number(owner.advertised_not_before_at);
}

async function applyStorageExpiry(database,raw,now) {
  const {body,userId,ownerHash}=storageOwner(raw,'apply_storage_expiry');
  const episodeId=uuid(body.episode_id,'invalid_storage_episode');
  const nowAt=integer(body.now_at,'invalid_storage_now');
  const expected=string(body.expected_encrypted_balance,'invalid_expected_balance',16384);
  const regions=body.regions;
  if(!Array.isArray(regions)||!regions.length||regions.length>8||new Set(regions).size!==regions.length
    ||regions.some((region)=>typeof region!=='string'||!/^[a-z0-9_-]{1,16}$/.test(region))) fail(400,'invalid_storage_regions');
  return database.transaction(async(trx)=>{
    const owner=await lockedStorageOwner(trx,userId,ownerHash,now);
    const priorWaiver=await trx(STORAGE_PERIODS).where({hashed_user_id:ownerHash,waived_episode_id:episodeId}).first();
    if(priorWaiver?.waiver_audit) return {...jsonValue(priorWaiver.waiver_audit),idempotent:true};
    if(owner.expiry_audit) {
      const audit=jsonValue(owner.expiry_audit);
      if(audit.episode_id===episodeId) return {...audit,idempotent:true};
    }
    if(owner.episode_id!==episodeId) fail(409,'storage_episode_mismatch');
    const user=await trx(USERS).where({id:userId}).forUpdate().first();
    if(!user||user.encrypted_credit_balance!==expected) fail(409,'stale_credit_balance');
    if(!await storageExpiryGate(trx,owner,userId,nowAt)) return {applied:false,held:true,reason:'warning_gate'};
    const periodIds=jsonValue(owner.warned_period_ids);
    if(!Array.isArray(periodIds)||!periodIds.length||periodIds.length>100) fail(409,'storage_warning_periods_missing');
    const warned=await trx(STORAGE_PERIODS).whereIn('id',periodIds).where({hashed_user_id:ownerHash}).forUpdate();
    if(warned.length!==periodIds.length||warned.some((p)=>p.state!=='unpaid')) return {applied:false,held:true,reason:'warned_debt_changed'};
    const charges=await trx(CHARGE_IDENTITIES).whereIn('charge_id',warned.map((p)=>p.charge_id)).forShare();
    if(charges.some((charge)=>charge.state==='committed')) return {applied:false,held:true,reason:'warned_payment_committed'};
    const laterPaid=await trx(STORAGE_PERIODS).where({hashed_user_id:ownerHash,state:'paid'})
      .where('created_at','>=',new Date(Number(owner.selection_at)*1000)).first();
    if(laterPaid) return {applied:false,held:true,reason:'later_paid_storage'};
    // Paid protection also sees a charge committed before its invoice state catches up.
    const laterCommitted=await trx.raw(`SELECT 1 FROM storage_billing_periods p JOIN billing_charge_identities c
      ON c.charge_id=p.charge_id WHERE p.hashed_user_id=? AND p.created_at>=?
      AND c.state='committed' LIMIT 1`,[ownerHash,new Date(Number(owner.selection_at)*1000)]);
    if(laterCommitted.rows.length) return {applied:false,held:true,reason:'later_paid_storage'};
    const pendingSettlements=await trx.raw(`SELECT 1 FROM billing_settlement_outbox o
      JOIN storage_billing_periods p ON p.charge_id=o.charge_id
      WHERE p.hashed_user_id=? AND o.hashed_user_id=?
      AND o.state IN ('pending','retry_scheduled','manual_review') LIMIT 1`,[ownerHash,ownerHash]);
    if(pendingSettlements.rows.length) return {applied:false,held:true,reason:'storage_settlement_unresolved'};
    await lockExpiryReferences(trx);
    const frozen=await trx(STORAGE_UNITS).where({hashed_user_id:ownerHash,episode_id:episodeId}).orderBy('unit_id','asc').forUpdate();
    if(!frozen.length||frozen.length>100) fail(409,'storage_warning_units_missing');
    const before=await currentStorageQuote(trx,userId,owner.selection_source_version);
    if(before.total_bytes<=FREE_STORAGE_BYTES) return {applied:false,held:true,reason:'within_free_storage'};
    const current=await discoverStorageUnits(trx,userId,ownerHash,nowAt);
    const references=await storageObjectReferences(trx,frozen.flatMap((unit)=>jsonValue(unit.object_references)));
    const committedSelection=[...frozen].sort((a,b)=>Number(a.oldest_at)-Number(b.oldest_at)||a.kind.localeCompare(b.kind)||a.resource_id.localeCompare(b.resource_id));
    if(tokenHash(JSON.stringify(committedSelection.map((unit)=>[unit.unit_id,unit.fingerprint])))!==owner.selection_hash) fail(409,'storage_warning_selection_mismatch');
    const eligible=[];
    for(const record of frozen) {
      const unit=current.find((candidate)=>candidate.unit_id===record.unit_id);
      if(unit && unit.fingerprint===record.fingerprint && !independentlyReferenced(unit,references)) eligible.push(unit);
    }
    eligible.sort((a,b)=>a.oldest_at-b.oldest_at||a.kind.localeCompare(b.kind)||a.resource_id.localeCompare(b.resource_id));
    const units=[];let planned=0;
    for(const unit of eligible) {
      units.push(unit);planned+=unit.bytes;
      if(before.total_bytes-planned<=FREE_STORAGE_BYTES) break;
    }
    if(!units.length||before.total_bytes-planned>FREE_STORAGE_BYTES) return {applied:false,held:true,reason:'no_complete_safe_set'};
    const tombstones=[]; const objectKeys=new Set();
    for(const unit of units) for(const obj of unit.objects) {
      const identity=`${obj.logical_bucket}\0${obj.object_key}`;
      if(objectKeys.has(identity)) continue;objectKeys.add(identity);
      const existing=await trx('storage_deletion_tombstones').where({idempotency_key:tokenHash(identity)}).forUpdate().first();
      if(existing) return {applied:false,held:true,reason:'object_already_tombstoned'};
      const jobs=await trx('storage_replication_jobs').where({logical_bucket:obj.logical_bucket,object_key:obj.object_key}).forUpdate();
      if(jobs.some((job)=>!['verified','completed','cancelled'].includes(job.state))) return {applied:false,held:true,reason:'object_writer_active'};
      const generations=[...new Set([1,...jobs.map((job)=>Number(job.generation))])].sort((a,b)=>a-b);
      if(generations.some((generation)=>!Number.isSafeInteger(generation)||generation<1)) fail(409,'storage_generation_ambiguous');
      const jobRegions=[];
      for(const job of jobs) {
        const desired=jsonValue(job.desired_regions);const states=jsonValue(job.region_states);
        if(!Array.isArray(desired)||!states||typeof states!=='object'||Array.isArray(states)) fail(409,'storage_region_inventory_ambiguous');
        jobRegions.push(...desired,job.active_region,...Object.keys(states));
      }
      const allRegions=[...new Set([...regions,...jobRegions])];
      if(allRegions.some((region)=>typeof region!=='string'||!/^[a-z0-9_-]{1,16}$/.test(region))) fail(409,'storage_region_inventory_ambiguous');
      const tombstone={id:randomUUID(),idempotency_key:tokenHash(identity),...obj,
        generations:JSON.stringify(generations),generation_keys:JSON.stringify(Object.fromEntries(generations.map((g)=>[g,obj.object_key]))),
        purge_states:JSON.stringify(Object.fromEntries(generations.map((g)=>[g,Object.fromEntries(allRegions.map((region)=>[region,'pending']))]))),
        state:'prepared',version:1,attempts:0,next_attempt_at:now,created_at:now,updated_at:now};
      tombstones.push(tombstone);
    }
    for(const tombstone of tombstones) await trx('storage_deletion_tombstones').insert(tombstone);
    const tombstoneIds=tombstones.map((tombstone)=>tombstone.id);
    const removed=[];
    for(const unit of units) {
      // Parts precede manifest and root; other units contain independent rows.
      const ordered=[...unit.rows].sort((a,b)=>['cold_archive_parts','cold_archive_manifests','chats'].indexOf(a.collection)
        -['cold_archive_parts','cold_archive_manifests','chats'].indexOf(b.collection));
      for(const row of ordered) {
        const deleted=await trx(row.collection).where({id:row.id}).delete();
        if(deleted!==1) fail(409,'storage_selected_row_changed');
        removed.push({collection:row.collection,id:row.id});
      }
    }
    const after=await currentStorageQuote(trx,userId,owner.selection_source_version);
    if(after.total_bytes>FREE_STORAGE_BYTES) fail(409,'storage_expiry_after_quote_above_free');
    const surviving=await storageObjectReferences(trx,units.flatMap((unit)=>unit.objects));
    if(units.some((unit)=>unit.objects.some((obj)=>surviving.some((ref)=>ref.bucket===obj.logical_bucket&&ref.object_key===obj.object_key)))) {
      fail(409,'storage_expiry_surviving_reference');
    }
    await trx('storage_deletion_tombstones').whereIn('id',tombstoneIds).update({state:'pending',version:2,next_attempt_at:now,updated_at:now});
    await trx(STORAGE_PERIODS).whereIn('id',periodIds).where({state:'unpaid',hashed_user_id:ownerHash})
      .update({state:'waived_on_expiry',waived_at:now,waived_episode_id:episodeId});
    const audit={applied:true,held:false,episode_id:episodeId,removed_unit_ids:units.map((u)=>u.unit_id),
      removed_row_ids:removed,removed_bytes:before.total_bytes-after.total_bytes,before_bytes:before.total_bytes,
      after_bytes:after.total_bytes,waived_period_ids:periodIds,tombstone_ids:tombstoneIds,applied_at:nowAt};
    await trx(STORAGE_PERIODS).whereIn('id',periodIds).where({waived_episode_id:episodeId})
      .update({waiver_audit:JSON.stringify(audit)});
    await trx(STORAGE_OWNERS).where({id:ownerHash}).update({expiry_audit:JSON.stringify(audit),
      episode_id:null,warning_count:0,first_warning_at:null,last_warning_at:null,deadline_at:null,
      advertised_not_before_at:null,selection_hash:null,selection_at:null,selected_bytes:null,selection_source_version:null,selection_policy_version:null,
      warned_period_ids:null,updated_at:now});
    return {...audit,idempotent:false};
  });
}

function storageOwner(raw, operation) {
  const body = operationBody(raw, operation);
  const userId = uuid(body.user_id, 'invalid_user_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  if (ownerHash !== tokenHash(userId)) fail(403, 'storage_owner_mismatch');
  return { body, userId, ownerHash };
}

async function lockedStorageOwner(trx, userId, ownerHash, now) {
  await trx.raw('SELECT pg_advisory_xact_lock(hashtextextended(?, 0))', [`storage-billing:${ownerHash}`]);
  let owner = await trx(STORAGE_OWNERS).where({ id: ownerHash }).forUpdate().first();
  if (owner && owner.user_id !== userId) fail(403, 'storage_owner_mismatch');
  if (!owner) {
    owner = {
      id: ownerHash, user_id: userId, episode_id: null, warning_count: 0,
      first_warning_at: null, last_warning_at: null, deadline_at: null,
      advertised_not_before_at: null, warning_manual_review_at: null,
      warning_manual_review_reason: null, closed_at: null, updated_at: now,
    };
    await trx(STORAGE_OWNERS).insert(owner);
  }
  return owner;
}

async function freezeStoragePeriod(database, raw, now) {
  const { body, userId, ownerHash } = storageOwner(raw, 'freeze_storage_period');
  const periodStart = integer(body.period_start_at, 'invalid_storage_period');
  const bytes = body.measured_bytes;
  if (!Number.isSafeInteger(bytes) || bytes < 0) fail(400, 'invalid_storage_bytes');
  const credits = integer(body.credits_due, 'invalid_storage_credits');
  if (credits <= 0) fail(400, 'invalid_storage_credits');
  const freeBytes = body.free_bytes;
  if (freeBytes !== 1_073_741_824) fail(409, 'storage_policy_mismatch');
  const rate = integer(body.credits_per_gib, 'invalid_storage_rate');
  const excess = BigInt(Math.max(0, bytes - freeBytes));
  const expectedCredits = Number((excess + BigInt(freeBytes) - 1n) / BigInt(freeBytes)) * rate;
  if (rate !== 3 || credits !== expectedCredits) {
    fail(409, 'storage_quote_mismatch');
  }
  const policyVersion = string(body.policy_version, 'invalid_storage_policy_version', 100);
  const sourceVersion = string(body.source_version, 'invalid_storage_source_version', 100);
  const categories = object(body.category_bytes);
  if (Object.keys(categories).length > 20 || Object.values(categories).some(
    (value) => !Number.isSafeInteger(value) || value < 0
  )) fail(400, 'invalid_storage_categories');
  const chargeId = string(body.charge_id, 'invalid_charge_id', 255);
  if (chargeId !== `storage:${ownerHash}:${periodStart}`) fail(409, 'storage_charge_identity_mismatch');
  const periodId = tokenHash(`storage-period:${ownerHash}:${periodStart}`);
  return database.transaction(async (trx) => {
    const owner = await lockedStorageOwner(trx, userId, ownerHash, now);
    if (owner.closed_at) fail(409, 'storage_owner_closed');
    const existing = await trx(STORAGE_PERIODS).where({ id: periodId }).forUpdate().first();
    if (existing) {
      if (existing.user_id !== userId || existing.hashed_user_id !== ownerHash
        || existing.period_start_at !== periodStart || existing.charge_id !== chargeId) {
        fail(409, 'storage_period_identity_mismatch');
      }
      return { period: existing, idempotent: true };
    }
    const period = {
      id: periodId, user_id: userId, hashed_user_id: ownerHash,
      period_start_at: periodStart, measured_bytes: bytes, credits_due: credits,
      free_bytes: freeBytes, credits_per_gib: rate, policy_version: policyVersion,
      source_version: sourceVersion, category_bytes: JSON.stringify(categories),
      charge_id: chargeId, state: 'unpaid', created_at: now, paid_at: null,
    };
    await trx(STORAGE_PERIODS).insert(period);
    return { period, idempotent: false };
  });
}

async function listStorageDebt(database, raw, now) {
  const { userId, ownerHash } = storageOwner(raw, 'list_storage_debt');
  return database.transaction(async (trx) => {
    const owner = await lockedStorageOwner(trx, userId, ownerHash, now);
    if (owner.closed_at) return { periods: [], has_more: false, closed: true };
    const periods = await trx(STORAGE_PERIODS)
      .where({ hashed_user_id: ownerHash, state: 'unpaid' })
      .orderBy('period_start_at', 'asc').limit(21);
    return { periods: periods.slice(0, 20), has_more: periods.length > 20,
      warning_count: owner.warning_count, deadline_at: owner.deadline_at };
  });
}

async function markStoragePeriodPaid(database, raw, now) {
  const { body, userId, ownerHash } = storageOwner(raw, 'mark_storage_period_paid');
  const periodId = string(body.period_id, 'invalid_storage_period', 64);
  return database.transaction(async (trx) => {
    const owner = await lockedStorageOwner(trx, userId, ownerHash, now);
    if (owner.closed_at) fail(409, 'storage_owner_closed');
    const period = await trx(STORAGE_PERIODS).where({ id: periodId, hashed_user_id: ownerHash }).forUpdate().first();
    if (!period) fail(404, 'storage_period_not_found');
    if(!['unpaid','paid'].includes(period.state)) fail(409,'storage_period_not_chargeable');
    const charge = await trx(CHARGE_IDENTITIES).where({ charge_id: period.charge_id }).forUpdate().first();
    if (!charge || charge.hashed_user_id !== ownerHash
      || charge.app_id !== 'system' || charge.skill_id !== 'storage'
      || charge.requested_credits !== period.credits_due
      || charge.charged_credits !== period.credits_due || charge.state !== 'committed') {
      fail(409, 'storage_charge_not_fully_committed');
    }
    if (period.state !== 'paid') {
      await trx(STORAGE_PERIODS).where({ id: periodId }).update({ state: 'paid', paid_at: now });
    }
    const remaining = await trx(STORAGE_PERIODS).where({ hashed_user_id: ownerHash, state: 'unpaid' }).first();
    if (!remaining) {
      await trx(STORAGE_OWNERS).where({ id: ownerHash }).update({
        episode_id: null, warning_count: 0, first_warning_at: null,
        last_warning_at: null, deadline_at: null, advertised_not_before_at: null,
        warning_manual_review_at: null, warning_manual_review_reason: null,
        selection_hash: null, selection_at: null, selected_bytes: null, warned_period_ids: null,
        selection_source_version: null, selection_policy_version: null,
        updated_at: now,
      });
    }
    return { state: 'paid', all_debt_settled: !remaining, idempotent: period.state === 'paid' };
  });
}

async function claimStorageWarning(database, raw, now) {
  const { body, userId, ownerHash } = storageOwner(raw, 'claim_storage_warning');
  const nowAt = integer(body.now_at, 'invalid_storage_now');
  return database.transaction(async (trx) => {
    const owner = await lockedStorageOwner(trx, userId, ownerHash, now);
    if (owner.closed_at) return { due: false, reason: 'owner_closed' };
    if (owner.warning_manual_review_at) return { due: false, reason: 'manual_review' };
    const oldest = await trx(STORAGE_PERIODS)
      .where({ hashed_user_id: ownerHash, state: 'unpaid' })
      .orderBy('period_start_at', 'asc').first();
    if (!oldest) return { due: false, reason: 'no_debt' };
    if (owner.warning_count >= 4) return { due: false, reason: 'four_delivered',
      episode_id: owner.episode_id, deadline_at: owner.deadline_at };
    if (owner.last_warning_at != null
      && nowAt < Number(owner.last_warning_at) + STORAGE_WARNING_INTERVAL_SECONDS) {
      return { due: false, reason: 'waiting', next_due_at: Number(owner.last_warning_at) + STORAGE_WARNING_INTERVAL_SECONDS };
    }
    const episodeId = owner.episode_id || randomUUID();
    if (!owner.episode_id) {
      await trx(STORAGE_OWNERS).where({ id: ownerHash }).update({ episode_id: episodeId, updated_at: now });
    }
    const total = await trx(STORAGE_PERIODS)
      .where({ hashed_user_id: ownerHash, state: 'unpaid' })
      .sum({ outstanding_credits: 'credits_due' }).first();
    return { due: true, episode_id: episodeId, warning_stage: Number(owner.warning_count) + 1,
      oldest_period_id: oldest.id, measured_bytes: Number(oldest.measured_bytes),
      credits_due: oldest.credits_due, outstanding_credits: Number(total.outstanding_credits),
      first_warning_at: owner.first_warning_at };
  });
}

async function acknowledgeStorageWarning(database, raw, now) {
  const { body, userId, ownerHash } = storageOwner(raw, 'acknowledge_storage_warning');
  const episodeId = uuid(body.episode_id, 'invalid_storage_episode');
  const stage = integer(body.warning_stage, 'invalid_storage_warning');
  const deliveryId = uuid(body.delivery_id, 'invalid_storage_delivery');
  const nowAt = integer(body.now_at, 'invalid_storage_now');
  if (stage < 1 || stage > 4) fail(400, 'invalid_storage_warning');
  return database.transaction(async (trx) => {
    const owner = await lockedStorageOwner(trx, userId, ownerHash, now);
    if (owner.closed_at) fail(409, 'storage_owner_closed');
    if (owner.episode_id !== episodeId) fail(409, 'storage_episode_mismatch');
    if (Number(owner.warning_count) >= stage) return { warning_count: owner.warning_count, idempotent: true };
    if (Number(owner.warning_count) + 1 !== stage) fail(409, 'storage_warning_order_mismatch');
    const oldest = await trx(STORAGE_PERIODS).where({ hashed_user_id: ownerHash, state: 'unpaid' }).first();
    if (!oldest) fail(409, 'storage_debt_settled');
    const delivery = await trx(EMAIL_DELIVERIES).where({ id: deliveryId }).forShare().first();
    const expectedKey = `storage-billing-warning:${episodeId}:directus_user:${userId}:week-${stage}`;
    if (!delivery || delivery.delivery_key !== expectedKey || delivery.status !== 'sent'
      || delivery.provider_delivery_state !== 'delivered' || !delivery.provider_delivered_at) {
      fail(409, 'storage_warning_not_delivered');
    }
    const sentAtMs = Date.parse(delivery.provider_delivered_at);
    if (!Number.isFinite(sentAtMs)) fail(409, 'storage_warning_receipt_missing');
    const sentAt = Math.floor(sentAtMs / 1000);
    if (sentAt > nowAt + 60) fail(409, 'storage_warning_receipt_in_future');
    const firstAt = stage === 1 ? sentAt : Number(owner.first_warning_at);
    let metadata;
    try {
      metadata = typeof delivery.metadata === 'string'
        ? JSON.parse(delivery.metadata) : delivery.metadata;
    } catch {
      fail(409, 'storage_warning_advertised_deadline_missing');
    }
    if (!owner.selection_hash || owner.selection_at == null || sentAt < Number(owner.selection_at)
      || metadata?.context?.unit_selection_hash !== owner.selection_hash) {
      fail(409, 'storage_warning_selection_mismatch');
    }
    const dateText = metadata?.context?.deadline_date;
    if (typeof dateText !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(dateText)) {
      fail(409, 'storage_warning_advertised_deadline_missing');
    }
    const advertisedMs = Date.parse(`${dateText}T00:00:00Z`);
    if (!Number.isFinite(advertisedMs)) fail(409, 'storage_warning_advertised_deadline_invalid');
    const advertisedAt = Math.floor(advertisedMs / 1000);
    // The notice states a UTC calendar date; the actual gate may occur later
    // within that day when provider delivery crosses midnight.
    // A provider may deliver later than submission. The notice explicitly
    // permits moving the date later; expiry uses the later delivered-time
    // gates as well as every date advertised to the owner.
    if (stage > 1 && (owner.last_warning_at == null
      || sentAt < Number(owner.last_warning_at) + STORAGE_WARNING_INTERVAL_SECONDS)) {
      fail(409, 'storage_warning_too_early');
    }
    await trx(STORAGE_OWNERS).where({ id: ownerHash }).update({
      warning_count: stage, first_warning_at: firstAt, last_warning_at: sentAt,
      deadline_at: firstAt + 4 * STORAGE_WARNING_INTERVAL_SECONDS, updated_at: now,
      advertised_not_before_at: Math.max(Number(owner.advertised_not_before_at || 0), advertisedAt),
      warning_manual_review_at: null, warning_manual_review_reason: null,
    });
    await trx(EMAIL_DELIVERIES).where({ id: deliveryId })
      .update({ storage_warning_acknowledged_at: now });
    return { warning_count: stage, first_warning_at: firstAt,
      deadline_at: firstAt + 4 * STORAGE_WARNING_INTERVAL_SECONDS, idempotent: false };
  });
}

async function recordStorageDeliveryReceipt(database, raw, now) {
  const { body, userId, ownerHash } = storageOwner(raw, 'record_storage_delivery_receipt');
  const episodeId = uuid(body.episode_id, 'invalid_storage_episode');
  const stage = integer(body.warning_stage, 'invalid_storage_warning');
  const deliveryId = uuid(body.delivery_id, 'invalid_storage_delivery');
  const messageId = string(body.message_id, 'invalid_provider_message_id', 255);
  const state = string(body.state, 'invalid_provider_delivery_state', 24);
  const observedAt = integer(body.observed_at, 'invalid_provider_event_time');
  const nowAt = integer(body.now_at, 'invalid_storage_now');
  if (stage < 1 || stage > 4 || !['delivered', 'failed'].includes(state)
    || observedAt > nowAt + 60) fail(400, 'invalid_provider_delivery_receipt');
  return database.transaction(async (trx) => {
    const owner = await lockedStorageOwner(trx, userId, ownerHash, now);
    const delivery = await trx(EMAIL_DELIVERIES).where({ id: deliveryId }).forUpdate().first();
    const key = `storage-billing-warning:${episodeId}:directus_user:${userId}:week-${stage}`;
    if (!delivery || delivery.delivery_key !== key || delivery.provider_message_id !== messageId
      || delivery.status !== 'sent') fail(409, 'storage_delivery_identity_mismatch');
    if (owner.episode_id !== episodeId || owner.closed_at) fail(409, 'storage_episode_mismatch');
    const submittedAt = Date.parse(delivery.sent_at);
    if (state === 'delivered' && (!Number.isFinite(submittedAt)
      || observedAt < Math.floor(submittedAt / 1000) - 60)) {
      fail(409, 'storage_delivery_event_before_submission');
    }
    if (state === 'failed') {
      if (delivery.provider_delivery_state !== 'failed') {
        await trx(EMAIL_DELIVERIES).where({ id: deliveryId })
          .update({ provider_delivery_state: 'failed' });
      }
      await trx(STORAGE_OWNERS).where({ id: ownerHash }).update({
        warning_manual_review_at: now,
        warning_manual_review_reason: 'provider_delivery_failed',
        updated_at: now,
      });
      return { state: 'failed', held: true };
    }
    if (delivery.provider_delivery_state === 'failed') {
      return { state: 'failed', held: true };
    }
    if (delivery.provider_delivery_state !== 'delivered') {
      await trx(EMAIL_DELIVERIES).where({ id: deliveryId }).update({
        provider_delivery_state: 'delivered',
        provider_delivered_at: new Date(observedAt * 1000),
      });
    }
    return { state: 'delivered', held: false };
  });
}

async function inspectStorageExpiry(database, raw, now) {
  const { body, userId, ownerHash } = storageOwner(raw, 'inspect_storage_expiry');
  const nowAt = integer(body.now_at, 'invalid_storage_now');
  return database.transaction(async (trx) => {
    const owner = await lockedStorageOwner(trx, userId, ownerHash, now);
    if (owner.closed_at) return { due: false, reason: 'owner_closed' };
    if (owner.warning_manual_review_at) return { due: false, reason: 'manual_review' };
    const oldest = await trx(STORAGE_PERIODS).where({ hashed_user_id: ownerHash, state: 'unpaid' })
      .orderBy('period_start_at', 'asc').first();
    const due = Boolean(oldest && await storageExpiryGate(trx, owner, userId, nowAt));
    return { due, oldest_period_id: due ? oldest.id : null,
      episode_id: due ? owner.episode_id : null, deadline_at: owner.deadline_at };

  });
}

async function closeStorageBillingForDeletedAccount(database, raw, now) {
  const { userId, ownerHash } = storageOwner(raw, 'close_storage_billing_for_deleted_account');
  return database.transaction(async (trx) => {
    const owner = await lockedStorageOwner(trx, userId, ownerHash, now);
    if (owner.closed_at) return { closed: true, waived_count: 0, idempotent: true };
    // Personal charges lock this same row before committing a ledger identity.
    // Once acquired, every earlier charge is visible and future storage
    // charges will see closed_at after this transaction commits.
    const user = await trx(USERS).where({ id: userId }).forUpdate().first();
    if (!user) fail(404, 'billing_user_not_found');
    let waived = 0;
    let paid = 0;
    while (true) {
      const periods = await trx(STORAGE_PERIODS)
        .where({ hashed_user_id: ownerHash, state: 'unpaid' })
        .orderBy('period_start_at', 'asc').limit(20);
      if (!periods.length) break;
      for (const period of periods) {
        const charge = await trx(CHARGE_IDENTITIES).where({ charge_id: period.charge_id }).first();
        const fullyCommitted = charge && charge.hashed_user_id === ownerHash
          && charge.app_id === 'system' && charge.skill_id === 'storage'
          && charge.requested_credits === period.credits_due
          && charge.charged_credits === period.credits_due && charge.state === 'committed';
        await trx(STORAGE_PERIODS).where({ id: period.id }).update(
          fullyCommitted ? { state: 'paid', paid_at: now } : { state: 'waived' }
        );
        if (fullyCommitted) paid += 1; else waived += 1;
      }
    }
    await trx(STORAGE_OWNERS).where({ id: ownerHash }).update({
      closed_at: now, episode_id: null, warning_count: 0,
      first_warning_at: null, last_warning_at: null, deadline_at: null,
      advertised_not_before_at: null, warning_manual_review_at: null,
      warning_manual_review_reason: null, updated_at: now,
    });
    return { closed: true, waived_count: waived, paid_count: paid, idempotent: false };
  });
}

async function markStorageWarningManualReview(database, raw, now) {
  const { body, userId, ownerHash } = storageOwner(raw, 'mark_storage_warning_manual_review');
  const episodeId = uuid(body.episode_id, 'invalid_storage_episode');
  const stage = integer(body.warning_stage, 'invalid_storage_warning');
  const deliveryId = uuid(body.delivery_id, 'invalid_storage_delivery');
  const nowAt = integer(body.now_at, 'invalid_storage_now');
  if (stage < 1 || stage > 4) fail(400, 'invalid_storage_warning');
  return database.transaction(async (trx) => {
    const owner = await lockedStorageOwner(trx, userId, ownerHash, now);
    const delivery = await trx(EMAIL_DELIVERIES).where({ id: deliveryId }).forUpdate().first();
    const expectedKey = `storage-billing-warning:${episodeId}:directus_user:${userId}:week-${stage}`;
    if (!delivery || delivery.delivery_key !== expectedKey) fail(409, 'storage_delivery_identity_mismatch');
    const startedMs = Date.parse(delivery.processing_started_at);
    const acceptedExpired = delivery.status === 'sent'
      && delivery.provider_delivery_state === 'accepted'
      && (!Number.isFinite(startedMs)
        || nowAt >= Math.floor(startedMs / 1000) + 90 * 86400);
    if (!['failed', 'processing'].includes(delivery.status) && !acceptedExpired) {
      return { held: false, reason: 'delivery_changed' };
    }
    if (Number.isFinite(startedMs) && nowAt < Math.floor(startedMs / 1000) + 600) {
      return { held: false, reason: 'retry_window_open' };
    }
    const reason = acceptedExpired ? 'provider_delivery_unverified' : 'provider_receipt_uncertain';
    await trx(EMAIL_DELIVERIES).where({ id: deliveryId }).update({
      status: 'manual_review', error: reason,
    });
    if (!owner.closed_at && owner.episode_id === episodeId
      && Number(owner.warning_count) + 1 === stage) {
      await trx(STORAGE_OWNERS).where({ id: ownerHash }).update({
        warning_manual_review_at: now,
        warning_manual_review_reason: reason,
        updated_at: now,
      });
      return { held: true, reason };
    }
    return { held: false, reason: 'owner_episode_changed' };
  });
}

function teamStorageOwner(raw, operation) {
  const body = operationBody(raw, operation);
  const teamHash = string(body.hashed_team_id, 'invalid_team', 64);
  if (!/^[a-f0-9]{64}$/.test(teamHash)) fail(400, 'invalid_team');
  return { body, teamHash };
}

async function teamStorageRecipients(trx, teamHash) {
  const rows = await trx('team_memberships').where({ hashed_team_id: teamHash, status: 'active' })
    .whereIn('role', ['owner', 'admin']).select('hashed_user_id').limit(101);
  const hashes = [...new Set(rows.map((row) => row.hashed_user_id))].sort();
  if (!hashes.length || rows.length > 100 || hashes.some((hash) => !/^[a-f0-9]{64}$/.test(hash))) {
    fail(409, 'team_storage_recipients_unresolved');
  }
  // Non-passkey users are included: membership hashes resolve through the
  // canonical Directus user ID, regardless of their login mechanism.
  const users = await trx.raw(`SELECT encode(digest(id::text,'sha256'),'hex') AS user_hash
    FROM directus_users WHERE encode(digest(id::text,'sha256'),'hex') = ANY(?::text[])`, [hashes]);
  if (users.rows.length !== hashes.length || users.rows.some((row) => !hashes.includes(row.user_hash))) {
    fail(409, 'team_storage_recipients_unresolved');
  }
  return hashes;
}

async function listTeamStorageRecipients(database, raw, now) {
  const { teamHash } = teamStorageOwner(raw, 'list_team_storage_recipients');
  return database.transaction(async (trx) => {
    await lockedTeamStorageOwner(trx, teamHash, now);
    const hashes = await teamStorageRecipients(trx, teamHash);
    const result = await trx.raw(`SELECT id::text AS user_id,
      encode(digest(id::text,'sha256'),'hex') AS user_hash FROM directus_users
      WHERE encode(digest(id::text,'sha256'),'hex') = ANY(?::text[])`, [hashes]);
    if (result.rows.length !== hashes.length) fail(409, 'team_storage_recipients_unresolved');
    return { recipients: result.rows.sort((a, b) => a.user_hash.localeCompare(b.user_hash)) };
  });
}

async function lockedTeamStorageOwner(trx, teamHash, now) {
  await trx.raw('SELECT pg_advisory_xact_lock(hashtextextended(?, 0))', [`team-storage-billing:${teamHash}`]);
  const team = await trx('teams').where({ hashed_team_id: teamHash, status: 'active' }).first();
  if (!team) fail(409, 'team_storage_owner_inactive');
  let owner = await trx(TEAM_STORAGE_OWNERS).where({ id: teamHash }).forUpdate().first();
  if (owner && (owner.hashed_team_id !== teamHash || owner.owner_kind !== 'team')) fail(409, 'team_storage_owner_mismatch');
  if (!owner) {
    owner = { id: teamHash, owner_kind: 'team', hashed_team_id: teamHash,
      episode_id: null, warning_count: 0, updated_at: now };
    await trx(TEAM_STORAGE_OWNERS).insert(owner);
  }
  return owner;
}

const resetTeamStorageWarning = (now) => ({ episode_id: null, warning_count: 0,
  first_warning_at: null, last_warning_at: null, deadline_at: null,
  advertised_not_before_at: null, warning_manual_review_at: null,
  warning_manual_review_reason: null, selection_hash: null, selection_at: null,
  selection_source_version: null, selection_policy_version: null,
  selected_bytes: null, warned_period_ids: null, warned_recipient_hashes: null, updated_at: now });

async function freezeTeamStoragePeriod(database, raw, now) {
  const { body, teamHash } = teamStorageOwner(raw, 'freeze_team_storage_period');
  const periodStart = integer(body.period_start_at, 'invalid_storage_period');
  const bytes = body.measured_bytes;
  if (!Number.isSafeInteger(bytes) || bytes <= FREE_STORAGE_BYTES) fail(400, 'invalid_storage_bytes');
  const credits = integer(body.credits_due, 'invalid_storage_credits');
  const freeBytes = body.free_bytes;
  const rate = integer(body.credits_per_gib, 'invalid_storage_rate');
  const expected = Number((BigInt(bytes - FREE_STORAGE_BYTES) + BigInt(FREE_STORAGE_BYTES) - 1n)
    / BigInt(FREE_STORAGE_BYTES)) * 3;
  if (freeBytes !== FREE_STORAGE_BYTES || rate !== 3 || credits !== expected) fail(409, 'storage_quote_mismatch');
  const policy = string(body.policy_version, 'invalid_storage_policy_version', 100);
  const source = string(body.source_version, 'invalid_storage_source_version', 100);
  if (policy !== TEAM_STORAGE_POLICY || source !== 'logical-s3-v1') fail(409, 'storage_policy_mismatch');
  const categories = object(body.category_bytes);
  if (Object.keys(categories).length > 20 || Object.values(categories).some((value) => !Number.isSafeInteger(value) || value < 0)
    || Object.values(categories).reduce((sum, value) => sum + value, 0) !== bytes) fail(409, 'storage_quote_mismatch');
  const chargeId = string(body.charge_id, 'invalid_charge_id', 255);
  if (chargeId !== `team-storage:${teamHash}:${periodStart}`) fail(409, 'storage_charge_identity_mismatch');
  const id = tokenHash(`team-storage-period:${teamHash}:${periodStart}`);
  return database.transaction(async (trx) => {
    await lockedTeamStorageOwner(trx, teamHash, now);
    const existing = await trx(TEAM_STORAGE_PERIODS).where({ id }).forUpdate().first();
    if (existing) {
      if (existing.owner_kind !== 'team' || existing.hashed_team_id !== teamHash
        || existing.charge_id !== chargeId || Number(existing.measured_bytes) !== bytes
        || existing.credits_due !== credits || existing.policy_version !== policy
        || existing.source_version !== source) fail(409, 'storage_period_identity_mismatch');
      return { period: existing, idempotent: true };
    }
    const period = { id, owner_kind: 'team', hashed_team_id: teamHash, period_start_at: periodStart,
      measured_bytes: bytes, credits_due: credits, free_bytes: freeBytes, credits_per_gib: rate,
      policy_version: policy, source_version: source, category_bytes: JSON.stringify(categories),
      charge_id: chargeId, state: 'unpaid', created_at: now, paid_at: null };
    await trx(TEAM_STORAGE_PERIODS).insert(period);
    return { period, idempotent: false };
  });
}

async function listTeamStorageDebt(database, raw, now) {
  const { teamHash } = teamStorageOwner(raw, 'list_team_storage_debt');
  return database.transaction(async (trx) => {
    const owner = await lockedTeamStorageOwner(trx, teamHash, now);
    const periods = await trx(TEAM_STORAGE_PERIODS).where({ hashed_team_id: teamHash, state: 'unpaid' })
      .orderBy('period_start_at', 'asc').limit(21);
    const totals = await trx(TEAM_STORAGE_PERIODS).where({ hashed_team_id: teamHash, state: 'unpaid' })
      .sum({ outstanding_credits: 'credits_due' }).first();
    return { periods: periods.slice(0, 20), has_more: periods.length > 20,
      outstanding_credits: Number(totals.outstanding_credits || 0),
      warning_count: owner.warning_count, deadline_at: owner.deadline_at };
  });
}

async function commitTeamStorageCharge(database, raw, now) {
  const { body, teamHash } = teamStorageOwner(raw, 'commit_team_storage_charge');
  const periodId = string(body.period_id, 'invalid_storage_period', 64);
  const expectedVersion = integer(body.expected_version, 'invalid_account_version');
  const occurredAt = integer(body.occurred_at, 'invalid_occurred_at');
  return database.transaction(async (trx) => {
    await lockedTeamStorageOwner(trx, teamHash, now);
    const period = await trx(TEAM_STORAGE_PERIODS).where({ id: periodId, hashed_team_id: teamHash }).forUpdate().first();
    if (!period || period.owner_kind !== 'team') fail(404, 'storage_period_not_found');
    const account = await lockedTeamAccount(trx, teamHash);
    const event = await trx(TEAM_CREDIT_EVENTS).where({ event_id: period.charge_id }).forUpdate().first();
    if (period.state === 'paid') {
      if (!event || event.hashed_team_id !== teamHash || event.actor_user_hash !== TEAM_STORAGE_SYSTEM_ACTOR
        || event.event_type !== 'deduction' || event.amount !== -period.credits_due) fail(409, 'storage_charge_not_fully_committed');
      return { state: 'paid', idempotent: true, charged_credits: period.credits_due, account };
    }
    if (period.state !== 'unpaid' || event) fail(409, 'storage_period_not_chargeable');
    if (account.version !== expectedVersion) fail(409, 'stale_team_credit_balance');
    if (!Number.isSafeInteger(account.balance_credits) || account.balance_credits < period.credits_due) {
      fail(402, 'insufficient_team_credits');
    }
    const updated = await trx(TEAM_ACCOUNTS).where({ id: account.id, version: expectedVersion })
      .where('balance_credits', '>=', period.credits_due).update({
        balance_credits: account.balance_credits - period.credits_due,
        version: expectedVersion + 1, updated_at: occurredAt,
        // encrypted_balance is an opaque client snapshot. The numeric ledger
        // and version are authoritative for this trusted SYSTEM debit.
      });
    if (updated !== 1) fail(409, 'stale_team_credit_balance');
    await trx(TEAM_CREDIT_EVENTS).insert({ id: randomUUID(), event_id: period.charge_id,
      hashed_team_id: teamHash, actor_user_hash: TEAM_STORAGE_SYSTEM_ACTOR,
      event_type: 'deduction', amount: -period.credits_due, encrypted_metadata: null,
      created_at: occurredAt });
    await trx(TEAM_USAGE_EVENTS).insert({ id: randomUUID(), event_id: period.charge_id,
      hashed_team_id: teamHash, actor_user_hash: TEAM_STORAGE_SYSTEM_ACTOR,
      workspace_type: 'team_storage', object_id_hash: null,
      credit_amount: period.credits_due, created_at: occurredAt });
    await trx(TEAM_STORAGE_PERIODS).where({ id: period.id, state: 'unpaid' }).update({ state: 'paid', paid_at: now });
    const next = await trx(TEAM_STORAGE_PERIODS).where({ hashed_team_id: teamHash, state: 'unpaid' }).first();
    if (!next) await trx(TEAM_STORAGE_OWNERS).where({ id: teamHash }).update(resetTeamStorageWarning(now));
    return { state: 'paid', idempotent: false, charged_credits: period.credits_due,
      account: { ...account, balance_credits: account.balance_credits - period.credits_due, version: expectedVersion + 1 } };
  });
}

async function claimTeamStorageWarning(database, raw, now) {
  const { body, teamHash } = teamStorageOwner(raw, 'claim_team_storage_warning');
  const nowAt = integer(body.now_at, 'invalid_storage_now');
  return database.transaction(async (trx) => {
    let owner = await lockedTeamStorageOwner(trx, teamHash, now);
    const recipients = await teamStorageRecipients(trx, teamHash);
    const oldest = await trx(TEAM_STORAGE_PERIODS).where({ hashed_team_id: teamHash, state: 'unpaid' })
      .orderBy('period_start_at', 'asc').first();
    if (!oldest) return { due: false, reason: 'no_debt' };
    const frozenRecipients = owner.warned_recipient_hashes == null ? null : jsonValue(owner.warned_recipient_hashes);
    if (frozenRecipients && JSON.stringify(frozenRecipients) !== JSON.stringify(recipients)) {
      // Newly appointed owners/admins need their own four-week notice clock.
      // Old provider receipts remain retained, but cannot authorize expiry.
      await trx(TEAM_STORAGE_OWNERS).where({ id: teamHash }).update(resetTeamStorageWarning(now));
      owner = { ...owner, ...resetTeamStorageWarning(now) };
    }
    if (owner.warning_manual_review_at) return { due: false, reason: 'manual_review' };
    if (Number(owner.warning_count) >= 4) return { due: false, reason: 'four_delivered',
      episode_id: owner.episode_id, deadline_at: owner.deadline_at, recipient_hashes: recipients };
    if (owner.last_warning_at != null && nowAt < Number(owner.last_warning_at) + STORAGE_WARNING_INTERVAL_SECONDS) {
      return { due: false, reason: 'waiting', next_due_at: Number(owner.last_warning_at) + STORAGE_WARNING_INTERVAL_SECONDS };
    }
    const episodeId = owner.episode_id || randomUUID();
    if (!owner.episode_id) await trx(TEAM_STORAGE_OWNERS).where({ id: teamHash }).update({
      episode_id: episodeId, warned_recipient_hashes: JSON.stringify(recipients), updated_at: now });
    const total = await trx(TEAM_STORAGE_PERIODS).where({ hashed_team_id: teamHash, state: 'unpaid' })
      .sum({ outstanding_credits: 'credits_due' }).first();
    return { due: true, episode_id: episodeId, warning_stage: Number(owner.warning_count) + 1,
      oldest_period_id: oldest.id, measured_bytes: Number(oldest.measured_bytes),
      credits_due: oldest.credits_due, outstanding_credits: Number(total.outstanding_credits),
      first_warning_at: owner.first_warning_at, recipient_hashes: recipients };
  });
}

async function freezeTeamStorageWarningUnits(database, raw, now) {
  const { body, teamHash } = teamStorageOwner(raw, 'freeze_team_storage_warning_units');
  const episodeId = uuid(body.episode_id, 'invalid_storage_episode');
  const nowAt = integer(body.now_at, 'invalid_storage_now');
  return database.transaction(async (trx) => {
    const owner = await lockedTeamStorageOwner(trx, teamHash, now);
    if (owner.episode_id !== episodeId || owner.warning_manual_review_at) fail(409, 'storage_episode_mismatch');
    const recipients = await teamStorageRecipients(trx, teamHash);
    if (JSON.stringify(recipients) !== JSON.stringify(jsonValue(owner.warned_recipient_hashes))) {
      return { frozen: false, held: true, reason: 'team_recipients_changed' };
    }
    if (owner.selection_hash) {
      const rows = await trx(TEAM_STORAGE_UNITS).where({ hashed_team_id: teamHash, episode_id: episodeId }).orderBy('unit_id', 'asc');
      return { frozen: true, held: false, idempotent: true, episode_id: episodeId,
        unit_selection_hash: owner.selection_hash, units: rows.map(safeUnit),
        period_ids: jsonValue(owner.warned_period_ids), selected_bytes: Number(owner.selected_bytes) };
    }
    if (Number(owner.warning_count) > 0) return { frozen: false, held: true, reason: 'warning_selection_missing' };
    const periods = await trx(TEAM_STORAGE_PERIODS).where({ hashed_team_id: teamHash, state: 'unpaid' })
      .orderBy('period_start_at', 'asc').limit(101);
    if (!periods.length || periods.length > 100) return { frozen: false, held: true, reason: 'warning_debt_limit' };
    if (periods.some((p) => p.source_version !== 'logical-s3-v1' || p.policy_version !== TEAM_STORAGE_POLICY)) {
      return { frozen: false, held: true, reason: 'mixed_storage_policy' };
    }
    await lockExpiryReferences(trx);
    const quote = await currentStorageQuote(trx, null, 'logical-s3-v1', teamHash);
    if (quote.total_bytes <= FREE_STORAGE_BYTES) return { frozen: false, held: true, reason: 'within_free_storage' };
    const candidates = await discoverStorageUnits(trx, null, teamHash, nowAt, 'team');
    const references = await storageObjectReferences(trx, candidates.flatMap((unit) => unit.objects));
    const blocked = await blockedStorageWriters(trx, candidates.flatMap((unit) => unit.objects));
    const units = []; let selectedBytes = 0; let objectCount = 0;
    const seen = new Set();
    for (const unit of candidates) {
      if (units.length >= 100 || objectCount + unit.objects.length > 2000) break;
      if (!Number.isSafeInteger(unit.bytes) || unit.bytes <= 0 || unit.rows.length > 2000
        || independentlyReferenced(unit, references)
        || unit.objects.some((obj) => blocked.has(`${obj.logical_bucket}\0${obj.object_key}`))
        || unit.objects.some((obj) => seen.has(`${obj.logical_bucket}:${obj.object_key}`))) continue;
      units.push(unit); selectedBytes += unit.bytes; objectCount += unit.objects.length;
      unit.objects.forEach((obj) => seen.add(`${obj.logical_bucket}:${obj.object_key}`));
      if (quote.total_bytes - selectedBytes <= FREE_STORAGE_BYTES) break;
    }
    if (!units.length || quote.total_bytes - selectedBytes > FREE_STORAGE_BYTES) {
      return { frozen: false, held: true, reason: 'no_complete_safe_set', total_bytes: quote.total_bytes };
    }
    const selectionHash = tokenHash(JSON.stringify(units.map((unit) => [unit.unit_id, unit.fingerprint])));
    for (const unit of units) await trx(TEAM_STORAGE_UNITS).insert({
      id: tokenHash(`${episodeId}:${unit.unit_id}`), owner_kind: 'team', hashed_team_id: teamHash,
      episode_id: episodeId, unit_id: unit.unit_id, kind: unit.kind, resource_id: unit.resource_id,
      oldest_at: unit.oldest_at, bytes: unit.bytes, fingerprint: unit.fingerprint,
      membership: JSON.stringify(unit.rows), object_references: JSON.stringify(unit.objects), created_at: now });
    await trx(TEAM_STORAGE_OWNERS).where({ id: teamHash }).update({ selection_hash: selectionHash,
      selection_at: nowAt, selected_bytes: selectedBytes, selection_source_version: 'logical-s3-v1',
      selection_policy_version: TEAM_STORAGE_POLICY,
      warned_period_ids: JSON.stringify(periods.map((p) => p.id)), updated_at: now });
    return { frozen: true, held: false, idempotent: false, episode_id: episodeId,
      unit_selection_hash: selectionHash,
      units: [...units].sort((a, b) => a.unit_id.localeCompare(b.unit_id)).map(safeUnit),
      period_ids: periods.map((p) => p.id), total_bytes: quote.total_bytes,
      selected_bytes: selectedBytes, expected_after_bytes: quote.total_bytes - selectedBytes };
  });
}

async function listTeamStorageWarningUnits(database, raw, now) {
  const { body, teamHash } = teamStorageOwner(raw, 'list_team_storage_warning_units');
  const episodeId = body.episode_id == null ? null : uuid(body.episode_id, 'invalid_storage_episode');
  const limit = integer(body.limit ?? 100, 'invalid_storage_unit_limit');
  if (limit < 1 || limit > 100) fail(400, 'invalid_storage_unit_limit');
  const after = body.after_unit_id == null ? null : string(body.after_unit_id, 'invalid_storage_unit_cursor', 64);
  return database.transaction(async (trx) => {
    const owner = await lockedTeamStorageOwner(trx, teamHash, now);
    if (episodeId && episodeId !== owner.episode_id) fail(409, 'storage_episode_mismatch');
    const query = trx(TEAM_STORAGE_UNITS).where({ hashed_team_id: teamHash, episode_id: owner.episode_id })
      .orderBy('unit_id', 'asc').limit(limit + 1);
    if (after) query.where('unit_id', '>', after);
    const rows = owner.episode_id ? await query : [];
    const units = rows.slice(0, limit).map(safeUnit);
    return { episode_id: owner.episode_id, warning_count: Number(owner.warning_count),
      deadline_at: owner.deadline_at, manual_review: Boolean(owner.warning_manual_review_at),
      notice_held: Boolean(owner.warning_manual_review_reason && !owner.warning_manual_review_at),
      notice_hold_reason: owner.warning_manual_review_at ? null : owner.warning_manual_review_reason,
      unit_selection_hash: owner.selection_hash ?? null, units, has_more: rows.length > limit,
      next_after_unit_id: rows.length > limit ? units.at(-1).unit_id : null };
  });
}

async function teamStorageStageReceipts(trx, owner, teamHash, stage, recipients) {
  const rows = await trx(EMAIL_DELIVERIES).where({ email_type: 'team-storage-billing-warning',
    campaign_key: owner.episode_id, stage: `week-${stage}` }).forShare();
  if (rows.length !== recipients.length) return null;
  const byHash = new Map();
  for (const row of rows) {
    if (row.recipient_kind !== 'directus_user' || typeof row.recipient_id !== 'string') return null;
    const userHash = tokenHash(row.recipient_id);
    const expectedKey = `team-storage-billing-warning:${owner.episode_id}:directus_user:${row.recipient_id}:week-${stage}`;
    if (!recipients.includes(userHash) || byHash.has(userHash) || row.delivery_key !== expectedKey) return null;
    byHash.set(userHash, row);
  }
  return byHash.size === recipients.length ? rows : null;
}

async function teamStorageCurrentEmailHashes(trx, recipients) {
  const users = await trx('directus_users').whereIn(trx.raw("encode(digest(id::text,'sha256'),'hex')"), recipients)
    .select('id', 'hashed_email').forShare();
  if (users.length !== recipients.length) return null;
  const contacts = await trx('account_contact_emails').whereIn('user_id', users.map((user) => user.id))
    .where({ purpose: 'account_lifecycle' }).select('user_id', 'hashed_email', 'verified_at').forShare();
  if (contacts.length !== recipients.length) return null;
  const contactByUser = new Map(contacts.map((contact) => [contact.user_id, contact]));
  const hashes = new Map();
  for (const user of users) {
    if (typeof user.hashed_email !== 'string' || !/^[A-Za-z0-9+/]{43}=$/.test(user.hashed_email)) return null;
    const contact = contactByUser.get(user.id);
    if (!contact?.verified_at || contact.hashed_email !== user.hashed_email) return null;
    const emailHash = Buffer.from(user.hashed_email, 'base64');
    if (emailHash.length !== 32) return null;
    hashes.set(tokenHash(user.id), emailHash.toString('hex'));
  }
  return hashes.size === recipients.length ? hashes : null;
}

function teamStorageDeliveredReceipt(row, owner, nowAt) {
  const sentAt = Math.floor(Date.parse(row.provider_delivered_at) / 1000);
  let metadata; try { metadata = jsonValue(row.metadata); } catch { return null; }
  const date = metadata?.context?.deadline_date;
  const advertised = typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date)
    ? Math.floor(Date.parse(`${date}T00:00:00Z`) / 1000) : NaN;
  if (row.status !== 'sent' || row.provider_delivery_state !== 'delivered'
    || !Number.isFinite(sentAt) || sentAt < Number(owner.selection_at) || sentAt > nowAt + 60
    || !Number.isFinite(advertised) || metadata?.context?.unit_selection_hash !== owner.selection_hash) return null;
  return { sentAt, advertised };
}

async function acknowledgeTeamStorageWarning(database, raw, now) {
  const { body, teamHash } = teamStorageOwner(raw, 'acknowledge_team_storage_warning');
  const episodeId = uuid(body.episode_id, 'invalid_storage_episode');
  const stage = integer(body.warning_stage, 'invalid_storage_warning');
  const nowAt = integer(body.now_at, 'invalid_storage_now');
  if (stage < 1 || stage > 4) fail(400, 'invalid_storage_warning');
  return database.transaction(async (trx) => {
    const owner = await lockedTeamStorageOwner(trx, teamHash, now);
    if (owner.episode_id !== episodeId || !owner.selection_hash) fail(409, 'storage_episode_mismatch');
    const recipients = await teamStorageRecipients(trx, teamHash);
    if (JSON.stringify(recipients) !== JSON.stringify(jsonValue(owner.warned_recipient_hashes))
      || JSON.stringify(recipients) !== JSON.stringify(body.recipient_hashes)) fail(409, 'team_storage_recipients_changed');
    if (Number(owner.warning_count) >= stage) return { warning_count: owner.warning_count, idempotent: true };
    if (Number(owner.warning_count) + 1 !== stage) fail(409, 'storage_warning_order_mismatch');
    const debt = await trx(TEAM_STORAGE_PERIODS).where({ hashed_team_id: teamHash, state: 'unpaid' }).first();
    if (!debt) fail(409, 'storage_debt_settled');
    const receipts = await teamStorageStageReceipts(trx, owner, teamHash, stage, recipients);
    if (!receipts) fail(409, 'storage_warning_not_delivered');
    let deliveredAt = 0; let advertisedAt = 0;
    for (const row of receipts) {
      const evidence = teamStorageDeliveredReceipt(row, owner, nowAt);
      if (!evidence) fail(409, 'storage_warning_not_delivered');
      deliveredAt = Math.max(deliveredAt, evidence.sentAt);
      advertisedAt = Math.max(advertisedAt, evidence.advertised);
    }
    if (stage > 1 && (owner.last_warning_at == null
      || deliveredAt < Number(owner.last_warning_at) + STORAGE_WARNING_INTERVAL_SECONDS)) {
      fail(409, 'storage_warning_too_early');
    }
    const firstAt = stage === 1 ? deliveredAt : Number(owner.first_warning_at);
    await trx(TEAM_STORAGE_OWNERS).where({ id: teamHash }).update({ warning_count: stage,
      first_warning_at: firstAt, last_warning_at: deliveredAt,
      deadline_at: firstAt + 4 * STORAGE_WARNING_INTERVAL_SECONDS,
      advertised_not_before_at: Math.max(Number(owner.advertised_not_before_at || 0), advertisedAt),
      warning_manual_review_at: null, warning_manual_review_reason: null, updated_at: now });
    await trx(EMAIL_DELIVERIES).whereIn('id', receipts.map((row) => row.id))
      .update({ storage_warning_acknowledged_at: now });
    return { warning_count: stage, first_warning_at: firstAt,
      deadline_at: firstAt + 4 * STORAGE_WARNING_INTERVAL_SECONDS, idempotent: false };
  });
}

async function recordTeamStorageDeliveryReceipt(database, raw, now) {
  const { body, teamHash } = teamStorageOwner(raw, 'record_team_storage_delivery_receipt');
  const episodeId = uuid(body.episode_id, 'invalid_storage_episode');
  const stage = integer(body.warning_stage, 'invalid_storage_warning');
  const userHash = string(body.recipient_hash, 'invalid_storage_recipient', 64);
  const deliveryId = uuid(body.delivery_id, 'invalid_storage_delivery');
  const messageId = string(body.message_id, 'invalid_provider_message_id', 255);
  const state = string(body.state, 'invalid_provider_delivery_state', 24);
  const observedAt = integer(body.observed_at, 'invalid_provider_event_time');
  const nowAt = integer(body.now_at, 'invalid_storage_now');
  if (stage < 1 || stage > 4 || !['delivered', 'failed'].includes(state)
    || observedAt > nowAt + 60) fail(400, 'invalid_provider_delivery_receipt');
  return database.transaction(async (trx) => {
    const owner = await lockedTeamStorageOwner(trx, teamHash, now);
    if (owner.episode_id !== episodeId) fail(409, 'storage_episode_mismatch');
    const recipients = await teamStorageRecipients(trx, teamHash);
    if (!recipients.includes(userHash) || JSON.stringify(recipients) !== JSON.stringify(jsonValue(owner.warned_recipient_hashes))) {
      fail(409, 'team_storage_recipients_changed');
    }
    const delivery = await trx(EMAIL_DELIVERIES).where({ id: deliveryId }).forUpdate().first();
    const key = `team-storage-billing-warning:${episodeId}:directus_user:${delivery?.recipient_id}:week-${stage}`;
    if (!delivery || tokenHash(delivery.recipient_id) !== userHash || delivery.delivery_key !== key
      || delivery.provider_message_id !== messageId || delivery.status !== 'sent') fail(409, 'storage_delivery_identity_mismatch');
    const submittedAt = Date.parse(delivery.sent_at);
    if (state === 'delivered' && (!Number.isFinite(submittedAt)
      || observedAt < Math.floor(submittedAt / 1000) - 60)) fail(409, 'storage_delivery_event_before_submission');
    if (state === 'failed') {
      await trx(EMAIL_DELIVERIES).where({ id: deliveryId }).update({ provider_delivery_state: 'failed' });
      await trx(TEAM_STORAGE_OWNERS).where({ id: teamHash }).update({
        warning_manual_review_at: now, warning_manual_review_reason: 'provider_delivery_failed', updated_at: now });
      return { state: 'failed', held: true };
    }
    if (delivery.provider_delivery_state === 'failed') return { state: 'failed', held: true };
    if (delivery.provider_delivery_state !== 'delivered') await trx(EMAIL_DELIVERIES).where({ id: deliveryId }).update({
      provider_delivery_state: 'delivered', provider_delivered_at: new Date(observedAt * 1000) });
    return { state: 'delivered', held: false };
  });
}

async function markTeamStorageWarningManualReview(database, raw, now) {
  const { body, teamHash } = teamStorageOwner(raw, 'mark_team_storage_warning_manual_review');
  const episodeId = uuid(body.episode_id, 'invalid_storage_episode');
  const stage = integer(body.warning_stage, 'invalid_storage_warning');
  const userHash = string(body.recipient_hash, 'invalid_storage_recipient', 64);
  const deliveryId = uuid(body.delivery_id, 'invalid_storage_delivery');
  const nowAt = integer(body.now_at, 'invalid_storage_now');
  if (stage < 1 || stage > 4) fail(400, 'invalid_storage_warning');
  return database.transaction(async (trx) => {
    const owner = await lockedTeamStorageOwner(trx, teamHash, now);
    const delivery = await trx(EMAIL_DELIVERIES).where({ id: deliveryId }).forUpdate().first();
    const key = `team-storage-billing-warning:${episodeId}:directus_user:${delivery?.recipient_id}:week-${stage}`;
    if (!delivery || tokenHash(delivery.recipient_id) !== userHash || delivery.delivery_key !== key) {
      fail(409, 'storage_delivery_identity_mismatch');
    }
    const startedMs = Date.parse(delivery.processing_started_at);
    const acceptedExpired = delivery.status === 'sent' && delivery.provider_delivery_state === 'accepted'
      && (!Number.isFinite(startedMs) || nowAt >= Math.floor(startedMs / 1000) + 90 * 86400);
    if (!['failed', 'processing'].includes(delivery.status) && !acceptedExpired) return { held: false, reason: 'delivery_changed' };
    if (Number.isFinite(startedMs) && nowAt < Math.floor(startedMs / 1000) + 600) return { held: false, reason: 'retry_window_open' };
    const reason = acceptedExpired ? 'provider_delivery_unverified' : 'provider_receipt_uncertain';
    await trx(EMAIL_DELIVERIES).where({ id: deliveryId }).update({ status: 'manual_review', error: reason });
    if (owner.episode_id === episodeId && Number(owner.warning_count) + 1 === stage) {
      await trx(TEAM_STORAGE_OWNERS).where({ id: teamHash }).update({
        warning_manual_review_at: now, warning_manual_review_reason: reason, updated_at: now });
      return { held: true, reason };
    }
    return { held: false, reason: 'owner_episode_changed' };
  });
}

async function setTeamStorageNoticeHold(database, raw, now) {
  const { body, teamHash } = teamStorageOwner(raw, 'set_team_storage_notice_hold');
  const episodeId = uuid(body.episode_id, 'invalid_storage_episode');
  const reason = body.reason === null ? null : string(body.reason, 'invalid_storage_notice_hold', 80);
  if (reason !== null && reason !== 'recipient_contact_unavailable') fail(400, 'invalid_storage_notice_hold');
  return database.transaction(async (trx) => {
    const owner = await lockedTeamStorageOwner(trx, teamHash, now);
    if (owner.episode_id !== episodeId || owner.warning_manual_review_at) {
      return { held: false, reason: 'owner_episode_changed' };
    }
    await trx(TEAM_STORAGE_OWNERS).where({ id: teamHash }).update({
      warning_manual_review_reason: reason, updated_at: now });
    return { held: reason !== null, reason };
  });
}

async function teamStorageExpiryGate(trx, owner, teamHash, nowAt) {
  if (owner.warning_manual_review_at || owner.warning_manual_review_reason
    || !owner.selection_hash || Number(owner.warning_count) !== 4) return false;
  const recipients = await teamStorageRecipients(trx, teamHash);
  if (JSON.stringify(recipients) !== JSON.stringify(jsonValue(owner.warned_recipient_hashes))) return false;
  // User email changes can leave old-address provider receipts intact. Lock
  // current identities through removal and require every notice to match.
  const currentEmails = await teamStorageCurrentEmailHashes(trx, recipients);
  if (!currentEmails) return false;
  let firstAt; let priorAt;
  for (let stage = 1; stage <= 4; stage += 1) {
    const receipts = await teamStorageStageReceipts(trx, owner, teamHash, stage, recipients);
    if (!receipts) return false;
    let stageAt = 0;
    for (const row of receipts) {
      if (currentEmails.get(tokenHash(row.recipient_id)) !== row.recipient_hash) return false;
      const evidence = teamStorageDeliveredReceipt(row, owner, nowAt);
      if (!evidence || !row.storage_warning_acknowledged_at || nowAt < evidence.advertised) return false;
      stageAt = Math.max(stageAt, evidence.sentAt);
    }
    if (priorAt != null && stageAt < priorAt + STORAGE_WARNING_INTERVAL_SECONDS) return false;
    firstAt ??= stageAt; priorAt = stageAt;
  }
  return nowAt >= firstAt + 4 * STORAGE_WARNING_INTERVAL_SECONDS
    && nowAt >= priorAt + STORAGE_WARNING_INTERVAL_SECONDS
    && nowAt >= Number(owner.deadline_at) && nowAt >= Number(owner.advertised_not_before_at);
}

async function inspectTeamStorageExpiry(database, raw, now) {
  const { body, teamHash } = teamStorageOwner(raw, 'inspect_team_storage_expiry');
  const nowAt = integer(body.now_at, 'invalid_storage_now');
  return database.transaction(async (trx) => {
    const owner = await lockedTeamStorageOwner(trx, teamHash, now);
    const oldest = await trx(TEAM_STORAGE_PERIODS).where({ hashed_team_id: teamHash, state: 'unpaid' })
      .orderBy('period_start_at', 'asc').first();
    const due = Boolean(oldest && await teamStorageExpiryGate(trx, owner, teamHash, nowAt));
    return { due, oldest_period_id: due ? oldest.id : null,
      episode_id: due ? owner.episode_id : null, deadline_at: owner.deadline_at };
  });
}

async function applyTeamStorageExpiry(database, raw, now) {
  const { body, teamHash } = teamStorageOwner(raw, 'apply_team_storage_expiry');
  const episodeId = uuid(body.episode_id, 'invalid_storage_episode');
  const expectedVersion = integer(body.expected_version, 'invalid_account_version');
  const nowAt = integer(body.now_at, 'invalid_storage_now');
  const regions = body.regions;
  if (!Array.isArray(regions) || !regions.length || regions.length > 8 || new Set(regions).size !== regions.length
    || regions.some((region) => typeof region !== 'string' || !/^[a-z0-9_-]{1,16}$/.test(region))) {
    fail(400, 'invalid_storage_regions');
  }
  return database.transaction(async (trx) => {
    const owner = await lockedTeamStorageOwner(trx, teamHash, now);
    const priorWaiver = await trx(TEAM_STORAGE_PERIODS).where({ hashed_team_id: teamHash,
      waived_episode_id: episodeId }).first();
    if (priorWaiver?.waiver_audit) return { ...jsonValue(priorWaiver.waiver_audit), idempotent: true };
    if (owner.expiry_audit) {
      const audit = jsonValue(owner.expiry_audit);
      if (audit.episode_id === episodeId) return { ...audit, idempotent: true };
    }
    if (owner.episode_id !== episodeId) fail(409, 'storage_episode_mismatch');
    const account = await lockedTeamAccount(trx, teamHash);
    if (account.version !== expectedVersion) fail(409, 'stale_team_credit_balance');
    // Role changes are concurrent writes. Hold both membership and Team status
    // through the final receipt check and removal transaction.
    await trx.raw('LOCK TABLE team_memberships, teams IN SHARE ROW EXCLUSIVE MODE');
    if (!await trx('teams').where({ hashed_team_id: teamHash, status: 'active' }).first()) {
      return { applied: false, held: true, reason: 'team_inactive' };
    }
    if (!await teamStorageExpiryGate(trx, owner, teamHash, nowAt)) return { applied: false, held: true, reason: 'warning_gate' };
    const periodIds = jsonValue(owner.warned_period_ids);
    if (!Array.isArray(periodIds) || !periodIds.length || periodIds.length > 100) fail(409, 'storage_warning_periods_missing');
    const warned = await trx(TEAM_STORAGE_PERIODS).whereIn('id', periodIds)
      .where({ hashed_team_id: teamHash }).orderBy('period_start_at', 'asc').forUpdate();
    if (warned.length !== periodIds.length || warned.some((period) => period.state !== 'unpaid')) {
      return { applied: false, held: true, reason: 'warned_debt_changed' };
    }
    if (!Number.isSafeInteger(account.balance_credits) || account.balance_credits >= warned[0].credits_due) {
      return { applied: false, held: true, reason: 'payment_available' };
    }
    const chargeIds = warned.map((period) => period.charge_id);
    const committed = await trx(TEAM_CREDIT_EVENTS).whereIn('event_id', chargeIds).forShare();
    if (committed.length) return { applied: false, held: true, reason: 'warned_payment_committed' };
    const laterPaid = await trx(TEAM_STORAGE_PERIODS).where({ hashed_team_id: teamHash, state: 'paid' })
      .where('created_at', '>=', new Date(Number(owner.selection_at) * 1000)).first();
    if (laterPaid) return { applied: false, held: true, reason: 'later_paid_storage' };
    const laterCommitted = await trx.raw(`SELECT 1 FROM team_storage_billing_periods p
      JOIN team_credit_events e ON e.event_id=p.charge_id
      WHERE p.hashed_team_id=? AND p.created_at>=? LIMIT 1`,
    [teamHash, new Date(Number(owner.selection_at) * 1000)]);
    if (laterCommitted.rows.length) return { applied: false, held: true, reason: 'later_paid_storage' };
    await lockExpiryReferences(trx);
    const frozen = await trx(TEAM_STORAGE_UNITS).where({ hashed_team_id: teamHash, episode_id: episodeId })
      .orderBy('unit_id', 'asc').forUpdate();
    if (!frozen.length || frozen.length > 100) fail(409, 'storage_warning_units_missing');
    const before = await currentStorageQuote(trx, null, owner.selection_source_version, teamHash);
    if (before.total_bytes <= FREE_STORAGE_BYTES) return { applied: false, held: true, reason: 'within_free_storage' };
    const current = await discoverStorageUnits(trx, null, teamHash, nowAt, 'team');
    const references = await storageObjectReferences(trx, frozen.flatMap((unit) => jsonValue(unit.object_references)));
    const committedSelection = [...frozen].sort((a, b) => Number(a.oldest_at) - Number(b.oldest_at)
      || a.kind.localeCompare(b.kind) || a.resource_id.localeCompare(b.resource_id));
    if (tokenHash(JSON.stringify(committedSelection.map((unit) => [unit.unit_id, unit.fingerprint]))) !== owner.selection_hash) {
      fail(409, 'storage_warning_selection_mismatch');
    }
    const eligible = [];
    for (const record of frozen) {
      const unit = current.find((candidate) => candidate.unit_id === record.unit_id);
      if (unit && unit.fingerprint === record.fingerprint && !independentlyReferenced(unit, references)) eligible.push(unit);
    }
    eligible.sort((a, b) => a.oldest_at - b.oldest_at || a.kind.localeCompare(b.kind)
      || a.resource_id.localeCompare(b.resource_id));
    const units = []; let planned = 0;
    for (const unit of eligible) {
      units.push(unit); planned += unit.bytes;
      if (before.total_bytes - planned <= FREE_STORAGE_BYTES) break;
    }
    if (!units.length || before.total_bytes - planned > FREE_STORAGE_BYTES) {
      return { applied: false, held: true, reason: 'no_complete_safe_set' };
    }
    const tombstones = []; const objectKeys = new Set();
    for (const unit of units) for (const obj of unit.objects) {
      const identity = `${obj.logical_bucket}\0${obj.object_key}`;
      if (objectKeys.has(identity)) continue;
      objectKeys.add(identity);
      const existing = await trx('storage_deletion_tombstones').where({ idempotency_key: tokenHash(identity) }).forUpdate().first();
      if (existing) return { applied: false, held: true, reason: 'object_already_tombstoned' };
      const jobs = await trx('storage_replication_jobs').where({ logical_bucket: obj.logical_bucket,
        object_key: obj.object_key }).forUpdate();
      if (jobs.some((job) => !['verified', 'completed', 'cancelled'].includes(job.state))) {
        return { applied: false, held: true, reason: 'object_writer_active' };
      }
      const generations = [...new Set([1, ...jobs.map((job) => Number(job.generation))])].sort((a, b) => a - b);
      if (generations.some((generation) => !Number.isSafeInteger(generation) || generation < 1)) fail(409, 'storage_generation_ambiguous');
      const jobRegions = [];
      for (const job of jobs) {
        const desired = jsonValue(job.desired_regions); const states = jsonValue(job.region_states);
        if (!Array.isArray(desired) || !states || typeof states !== 'object' || Array.isArray(states)) {
          fail(409, 'storage_region_inventory_ambiguous');
        }
        jobRegions.push(...desired, job.active_region, ...Object.keys(states));
      }
      const allRegions = [...new Set([...regions, ...jobRegions])];
      if (allRegions.some((region) => typeof region !== 'string' || !/^[a-z0-9_-]{1,16}$/.test(region))) {
        fail(409, 'storage_region_inventory_ambiguous');
      }
      tombstones.push({ id: randomUUID(), idempotency_key: tokenHash(identity), ...obj,
        generations: JSON.stringify(generations),
        generation_keys: JSON.stringify(Object.fromEntries(generations.map((g) => [g, obj.object_key]))),
        purge_states: JSON.stringify(Object.fromEntries(generations.map((g) =>
          [g, Object.fromEntries(allRegions.map((region) => [region, 'pending']))]))),
        state: 'prepared', version: 1, attempts: 0, next_attempt_at: now, created_at: now, updated_at: now });
    }
    for (const tombstone of tombstones) await trx('storage_deletion_tombstones').insert(tombstone);
    const tombstoneIds = tombstones.map((tombstone) => tombstone.id);
    const removed = [];
    for (const unit of units) {
      const ordered = [...unit.rows].sort((a, b) => ['cold_archive_parts', 'cold_archive_manifests', 'chats'].indexOf(a.collection)
        - ['cold_archive_parts', 'cold_archive_manifests', 'chats'].indexOf(b.collection));
      for (const row of ordered) {
        const deleted = await trx(row.collection).where({ id: row.id }).delete();
        if (deleted !== 1) fail(409, 'storage_selected_row_changed');
        removed.push({ collection: row.collection, id: row.id });
      }
    }
    const after = await currentStorageQuote(trx, null, owner.selection_source_version, teamHash);
    if (after.total_bytes > FREE_STORAGE_BYTES) fail(409, 'storage_expiry_after_quote_above_free');
    const surviving = await storageObjectReferences(trx, units.flatMap((unit) => unit.objects));
    if (units.some((unit) => unit.objects.some((obj) => surviving.some((ref) =>
      ref.bucket === obj.logical_bucket && ref.object_key === obj.object_key)))) fail(409, 'storage_expiry_surviving_reference');
    await trx('storage_deletion_tombstones').whereIn('id', tombstoneIds).update({
      state: 'pending', version: 2, next_attempt_at: now, updated_at: now });
    await trx(TEAM_STORAGE_PERIODS).whereIn('id', periodIds).where({ state: 'unpaid', hashed_team_id: teamHash })
      .update({ state: 'waived_on_expiry', waived_at: now, waived_episode_id: episodeId });
    const audit = { applied: true, held: false, episode_id: episodeId,
      removed_unit_ids: units.map((unit) => unit.unit_id), removed_row_ids: removed,
      removed_bytes: before.total_bytes - after.total_bytes, before_bytes: before.total_bytes,
      after_bytes: after.total_bytes, waived_period_ids: periodIds, tombstone_ids: tombstoneIds, applied_at: nowAt };
    await trx(TEAM_STORAGE_PERIODS).whereIn('id', periodIds).where({ waived_episode_id: episodeId })
      .update({ waiver_audit: JSON.stringify(audit) });
    await trx(TEAM_STORAGE_OWNERS).where({ id: teamHash }).update({
      ...resetTeamStorageWarning(now), expiry_audit: JSON.stringify(audit) });
    return { ...audit, idempotent: false };
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
  freeze_storage_period: freezeStoragePeriod,
  list_storage_debt: listStorageDebt,
  mark_storage_period_paid: markStoragePeriodPaid,
  claim_storage_warning: claimStorageWarning,
  acknowledge_storage_warning: acknowledgeStorageWarning,
  record_storage_delivery_receipt: recordStorageDeliveryReceipt,
  freeze_storage_warning_units: freezeStorageWarningUnits,
  list_storage_warning_units: listStorageWarningUnits,
  apply_storage_expiry: applyStorageExpiry,
  inspect_storage_expiry: inspectStorageExpiry,
  close_storage_billing_for_deleted_account: closeStorageBillingForDeletedAccount,
  mark_storage_warning_manual_review: markStorageWarningManualReview,
  freeze_team_storage_period: freezeTeamStoragePeriod,
  list_team_storage_debt: listTeamStorageDebt,
  commit_team_storage_charge: commitTeamStorageCharge,
  claim_team_storage_warning: claimTeamStorageWarning,
  list_team_storage_recipients: listTeamStorageRecipients,
  freeze_team_storage_warning_units: freezeTeamStorageWarningUnits,
  list_team_storage_warning_units: listTeamStorageWarningUnits,
  acknowledge_team_storage_warning: acknowledgeTeamStorageWarning,
  record_team_storage_delivery_receipt: recordTeamStorageDeliveryReceipt,
  mark_team_storage_warning_manual_review: markTeamStorageWarningManualReview,
  set_team_storage_notice_hold: setTeamStorageNoticeHold,
  inspect_team_storage_expiry: inspectTeamStorageExpiry,
  apply_team_storage_expiry: applyTeamStorageExpiry,
});

export async function executeOperation(database, operation, data, now = new Date()) {
  const handler = operations[operation];
  if (!handler) fail(400, 'unsupported_operation');
  return handler(database, data, now);
}

export const testing = Object.freeze({
  validatedChildren, tokenHash, PROTOCOL_VERSION, MAX_DEPTH,
  AUTO_DESCENDANT_LIMIT, MAX_DESCENDANT_LIMIT, AUTO_CREDIT_LIMIT,
  operationReservationFits, unitFingerprint, independentlyReferenced, storageExpiryGate,
});
