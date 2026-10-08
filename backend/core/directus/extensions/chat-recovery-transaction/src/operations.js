/*
 * Internal persistence state machine for encrypted chat completion recovery.
 * Durable content-bearing values are ciphertext, sealed envelopes, or digests.
 */
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { metadataOperations } from './metadata_operations.js';

const PREFLIGHTS = 'chat_turn_preflights';
const JOBS = 'chat_completion_recovery_jobs';
const OUTPUTS = 'chat_recovery_outputs';
const ACCOUNT_FENCES = 'chat_recovery_account_fences';
const CHAT_DELETION_FENCES = 'chat_recovery_chat_deletion_fences';
const OUTPUT_PRODUCERS = 'chat_recovery_output_producers';
const OUTPUT_PRODUCER_CHILDREN = 'chat_recovery_output_producer_children';
const AUTHORIZED_RERENDERS = 'chat_recovery_authorized_rerenders';
const AUTHORIZED_DIRECT_SKILLS = 'chat_recovery_authorized_direct_skills';
const LEGACY_OUTPUT_PRODUCERS = 'chat_recovery_legacy_output_producers';
const LEGACY_BATCH_CLAIMS = 'chat_recovery_legacy_batch_claims';
const ORCHESTRATION_CHILDREN = 'sub_chat_orchestration_children';
const ORCHESTRATIONS = 'sub_chat_orchestrations';
const ORCHESTRATION_BATCHES = 'sub_chat_orchestration_batches';
const METADATA_JOBS = 'chat_metadata_recovery_jobs';
const OUTBOX = 'chat_inference_outbox';
const CHATS = 'chats';
const MESSAGES = 'messages';
const CHECKPOINTS = 'chat_compression_checkpoints';
const EMBEDS = 'embeds';
const EMBED_DIFFS = 'embed_diffs';
const EMBED_KEYS = 'embed_keys';
const TEAM_MEMBERSHIPS = 'team_memberships';
const TEAMS = 'teams';
const CHAT_KEY_WRAPPERS = 'chat_key_wrappers';
const PROTOCOL_STATE = 'chat_recovery_protocol_state';
const OPERATIONAL_EVENTS = 'operational_monitoring_events';
const PROTOCOL_STATE_ID = 'chat-recovery';
const PROTOCOL_VERSION = 1;
const LEASE_MS = 60_000;
const MAX_TENURE_MS = 5 * 60_000;
const PREFLIGHT_TTL_MS = 24 * 60 * 60_000;
const JOB_TTL_MS = 7 * 24 * 60 * 60_000;
const TOMBSTONE_TTL_MS = 24 * 60 * 60_000;
const LEGACY_RUNNING_TTL_MS = 15 * 60_000;
const LEGACY_TOMBSTONE_TTL_MS = 24 * 60 * 60_000;
const SERVER_TRIGGER_TASK_IDENTITY_PREFIX = 'server-trigger:';
const MAX_CONTENT_BYTES = 16 * 1024 * 1024;
const MAX_AVAILABLE_JOBS = 100;
const MAX_CHAT_FENCE_LOOKUP = 100;
const MAX_INLINE_OUTPUT_BYTES = 256 * 1024;
const OUTPUT_KINDS = new Set(['message', 'embed', 'diff', 'summary', 'checkpoint']);
const PRODUCER_OUTPUT_KINDS = new Set(['embed', 'diff']);
const MAX_PRODUCER_CHILDREN = 32;
const MAX_FAILURE_ALERT_CANDIDATES = 100;
const EXPECTED_FAILURE_CATEGORIES = new Set([
  'harmful_content', 'harmful_or_illegal_detected', 'insufficient_credits',
  'insufficient_team_credits', 'misuse_detected', 'policy_rejection', 'user_cancelled',
]);
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HEX_64_RE = /^[0-9a-f]{64}$/;
const BASE64URL_RE = /^[A-Za-z0-9_-]+$/;
const LEGACY_LIFECYCLE_STATES = new Set(['RUNNING', 'AWAITING_PERSISTENCE', 'PERSISTED']);
const LEGACY_LIFECYCLE_FIELDS = new Set([
  'task_identity', 'state', 'expires_at', 'persistence_observed', 'admission',
]);
const MESSAGE_FIELDS = new Set([
  'client_message_id', 'chat_id', 'hashed_user_id', 'encrypted_content', 'role',
  'encrypted_sender_name', 'encrypted_category', 'encrypted_model_name',
  'encrypted_thinking_content', 'encrypted_thinking_signature', 'has_thinking',
  'thinking_token_count', 'created_at', 'updated_at', 'encrypted_pii_mappings',
  'user_message_id',
]);
const CHAT_METADATA_FIELDS = new Set([
  'encrypted_title', 'encrypted_chat_key', 'encrypted_active_focus_id',
  'encrypted_chat_summary', 'encrypted_share_cta_text', 'encrypted_chat_tags',
  'encrypted_follow_up_request_suggestions', 'encrypted_top_recommended_apps_for_chat',
  'encrypted_quick_tip_slugs', 'encrypted_icon', 'encrypted_category',
  'encrypted_settings_memories_suggestions', 'encrypted_slug', 'slug_lookup_hash',
  'created_at', 'updated_at',
]);
const OPERATION_FIELDS = Object.freeze({
  prepare_preflight: new Set([
    'protocol_version', 'hashed_user_id', 'chat_id', 'turn_id', 'user_message_id',
    'device_hash', 'chat_key_version', 'wrapped_chat_key', 'recovery_public_key',
    'inference_commitment', 'commitment_version', 'expected_messages_v', 'encrypted_user_message',
    'encrypted_chat_metadata', 'hashed_team_id',
  ]),
  verify_committed_team_message: new Set([
    'protocol_version', 'preflight_id', 'hashed_user_id', 'hashed_team_id',
    'chat_id', 'user_message_id', 'encrypted_content_digest',
  ]),
  enqueue_inference: new Set([
    'protocol_version', 'preflight_id', 'hashed_user_id', 'device_hash',
    'inference_commitment', 'inference_task_id', 'billing_identity', 'outbox_id',
  ]),
  claim_inference: new Set(['protocol_version', 'inference_task_id']),
  mark_outbox_dispatched: new Set(['protocol_version', 'outbox_id', 'inference_task_id']),
  mark_inference_failed: new Set(['protocol_version', 'inference_task_id', 'failure_category']),
  create_sealed_job: new Set([
    'protocol_version', 'job_id', 'hashed_user_id', 'chat_id', 'turn_id',
    'preflight_id', 'inference_task_id', 'assistant_message_id', 'chat_key_version', 'sealed_payload',
  ]),
  create_sealed_output: new Set([
    'protocol_version', 'record_id', 'hashed_user_id', 'root_chat_id', 'target_chat_id',
    'turn_id', 'preflight_id', 'inference_task_id', 'subject_id', 'output_kind',
    'output_version', 'chat_key_version', 'message_role', 'sealed_payload', 'payload_s3_key',
    'payload_size_bytes', 'sealed_payload_digest', 'payload_verified_regions',
    'producer_intent_id', 'producer_ordinal', 'producer_task_name',
    'producer_kwargs_binding', 'content_commitment',
  ]),
  prepare_sealed_output: new Set([
    'protocol_version', 'record_id', 'hashed_user_id', 'root_chat_id', 'target_chat_id',
    'turn_id', 'preflight_id', 'inference_task_id', 'subject_id', 'output_kind',
    'output_version', 'chat_key_version', 'message_role', 'payload_s3_key',
    'payload_size_bytes', 'sealed_payload_digest',
    'producer_intent_id', 'producer_ordinal', 'producer_task_name',
    'producer_kwargs_binding', 'content_commitment',
  ]),
  register_output_producer: new Set([
    'protocol_version', 'task_uuid', 'task_name', 'kwargs_binding', 'hashed_user_id',
    'root_chat_id', 'target_chat_id', 'turn_id', 'preflight_id', 'inference_task_id',
    'chat_key_version', 'primary_embed_id', 'primary_message_id',
    'primary_output_kind', 'primary_output_version', 'max_children',
  ]),
  register_legacy_output_producer: new Set([
    'protocol_version', 'task_uuid', 'task_name', 'kwargs_binding',
    'actor_user_id', 'hashed_user_id', 'legacy_task_identity',
    'root_chat_id', 'target_chat_id', 'root_turn_id',
    'root_user_message_id', 'primary_message_id', 'primary_embed_id',
  ]),
  verify_volatile_output_actor: new Set([
    'protocol_version', 'actor_user_id', 'hashed_user_id',
    'target_chat_id', 'hashed_team_id',
  ]),
  resolve_output_producer: new Set([
    'protocol_version', 'task_uuid', 'task_name', 'kwargs_binding',
  ]),
  register_output_producer_child: new Set([
    'protocol_version', 'producer_intent_id', 'task_name', 'kwargs_binding',
    'ordinal', 'subject_id', 'output_kind', 'output_version',
  ]),
  close_output_producer: new Set([
    'protocol_version', 'producer_intent_id', 'task_name', 'kwargs_binding',
    'expected_children',
  ]),
  get_producer_output: new Set([
    'protocol_version', 'producer_intent_id', 'task_name', 'kwargs_binding',
    'ordinal', 'content_commitment',
  ]),
  get_replay_output: new Set([
    'protocol_version', 'record_id', 'hashed_user_id', 'preflight_id',
    'root_chat_id', 'target_chat_id', 'subject_id', 'output_kind',
    'output_version', 'content_commitment',
  ]),
  classify_untagged_output_producer: new Set([
    'protocol_version', 'task_uuid', 'task_name', 'hashed_user_id',
    'target_chat_id', 'primary_message_id',
  ]),
  register_authorized_rerender: new Set([
    'protocol_version', 'task_uuid', 'task_name', 'kwargs_binding', 'hashed_user_id',
    'target_chat_id', 'primary_embed_id', 'primary_message_id',
    'source_version', 'expected_embed_version',
  ]),
  register_authorized_direct_skill: new Set([
    'protocol_version', 'task_uuid', 'task_name', 'kwargs_binding', 'actor_user_id',
    'hashed_user_id', 'hashed_team_id', 'target_chat_id', 'primary_message_id',
    'primary_embed_id',
  ]),
  complete_authorized_direct_skill: new Set([
    'protocol_version', 'task_uuid', 'task_name', 'kwargs_binding', 'completion',
  ]),
  complete_authorized_standalone_asset: new Set([
    'protocol_version', 'task_uuid', 'task_name', 'kwargs_binding',
    'asset_id',
  ]),
  complete_authorized_rerender: new Set([
    'protocol_version', 'task_uuid', 'task_name', 'kwargs_binding', 'completion',
  ]),
  complete_authorized_direct_by_embed: new Set([
    'protocol_version', 'hashed_user_id', 'primary_embed_id', 'target_chat_id',
    'canonical_version', 'intent_kind',
  ]),
  claim_authorized_direct_producer: new Set([
    'protocol_version', 'task_uuid', 'task_name', 'kwargs_binding',
  ]),
  verify_claimed_output_producer: new Set([
    'protocol_version', 'task_uuid', 'task_name', 'kwargs_binding',
  ]),
  reconcile_authorized_direct_completions: new Set([
    'protocol_version', 'after_id', 'limit',
  ]),
  list_pending_outputs: new Set(['protocol_version', 'hashed_user_id', 'device_hash',
    'after_created_at', 'after_record_id']),
  get_pending_output: new Set(['protocol_version', 'hashed_user_id', 'device_hash', 'record_id']),
  persist_output_message: new Set([
    'protocol_version', 'hashed_user_id', 'device_hash', 'record_id',
    'expected_messages_v', 'encrypted_assistant_message',
    'encrypted_user_message',
    'encrypted_chat_key', 'encrypted_title',
  ]),
  persist_output_summary: new Set([
    'protocol_version', 'hashed_user_id', 'device_hash', 'record_id',
    'expected_metadata_v', 'encrypted_summary',
  ]),
  has_pending_chat_outputs: new Set(['protocol_version', 'hashed_user_id', 'target_chat_id']),
  acknowledge_output_checkpoint: new Set([
    'protocol_version', 'hashed_user_id', 'device_hash', 'record_id',
    'encrypted_summary', 'compressed_up_to_message_id', 'covered_message_ids',
  ]),
  acknowledge_output_embed: new Set([
    'protocol_version', 'hashed_user_id', 'device_hash', 'record_id', 'canonical_digest', 'canonical_source',
  ]),
  mark_child_result_delivered: new Set([
    'protocol_version', 'hashed_user_id', 'child_chat_id', 'root_chat_id',
  ]),
  mark_child_parent_consumed: new Set([
    'protocol_version', 'hashed_user_id', 'child_chat_id', 'root_chat_id', 'continuation_task_id',
  ]),
  mark_child_canonical_acknowledged: new Set([
    'protocol_version', 'hashed_user_id', 'child_chat_id',
  ]),
  list_available_jobs: new Set(['protocol_version', 'hashed_user_id', 'device_hash']),
  lease_job: new Set(['protocol_version', 'job_id', 'hashed_user_id', 'device_hash']),
  renew_lease: new Set([
    'protocol_version', 'job_id', 'hashed_user_id', 'device_hash', 'lease_generation', 'lease_token',
  ]),
  persist_terminal: new Set([
    'protocol_version', 'job_id', 'hashed_user_id', 'device_hash', 'lease_generation',
    'lease_token', 'expected_messages_v', 'encrypted_assistant_message',
  ]),
  invalidate_deletion: new Set(['protocol_version', 'hashed_user_id', 'scope', 'chat_id', 'device_hash']),
  invalidate_rewind: new Set(['protocol_version', 'hashed_user_id', 'chat_id']),
  lookup_chat_deletion_fences: new Set(['protocol_version', 'hashed_user_id', 'chat_ids']),
  cleanup_expired: new Set(['protocol_version', 'failure_alerts_enabled']),
  acknowledge_failure_alert: new Set([
    'protocol_version', 'preflight_id', 'inference_task_id', 'failure_category',
  ]),
  get_cutover_state: new Set(['protocol_version']),
  set_sends_paused: new Set(['protocol_version', 'sends_paused']),
  admit_legacy_inference: new Set([
    'protocol_version', 'task_identity', 'actor_user_id', 'hashed_user_id',
    'chat_id', 'first_message_id', 'hashed_team_id',
  ]),
  claim_legacy_inference_start: new Set([
    'protocol_version', 'task_identity', 'actor_user_id', 'hashed_user_id',
    'chat_id', 'first_message_id', 'hashed_team_id', 'broker_task_id', 'dispatch_binding',
  ]),
  bind_ordinary_legacy_dispatch: new Set([
    'protocol_version', 'task_identity', 'actor_user_id', 'hashed_user_id',
    'chat_id', 'first_message_id', 'hashed_team_id', 'broker_task_id', 'dispatch_binding',
  ]),
  prepare_legacy_batch: new Set([
    'protocol_version', 'actor_user_id', 'hashed_user_id', 'chat_id',
    'first_message_id', 'hashed_team_id', 'task_identity', 'celery_task_id',
    'members', 'batch_commitment',
  ]),
  claim_legacy_batch: new Set([
    'protocol_version', 'actor_user_id', 'hashed_user_id', 'chat_id',
    'first_message_id', 'hashed_team_id', 'task_identity', 'celery_task_id',
    'members', 'batch_commitment',
  ]),
  mark_legacy_inference_completed: new Set(['protocol_version', 'task_identity']),
  acknowledge_legacy_persistence: new Set([
    'protocol_version', 'task_identity', 'chat_id', 'hashed_user_id',
    'assistant_message_id', 'ciphertext_digest',
  ]),
  authorize_legacy_completion: new Set(['protocol_version', 'task_identity']),
  release_legacy_inference: new Set(['protocol_version', 'task_identity']),
  activate_protocol_epoch: new Set(['protocol_version', 'target_epoch']),
});

export class ProtocolError extends Error {
  constructor(status, code) {
    super(code);
    this.name = 'ProtocolError';
    this.status = status;
    this.code = code;
  }
}
const fail = (status, code) => { throw new ProtocolError(status, code); };
const object = (value, code = 'invalid_request') => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) fail(400, code);
  return value;
};
const string = (value, code, max = 1024) => {
  if (typeof value !== 'string' || !value || Buffer.byteLength(value, 'utf8') > max) fail(400, code);
  return value;
};
const uuid = (value, code) => {
  const result = string(value, code, 36);
  if (!UUID_RE.test(result)) fail(400, code);
  return result;
};
const integer = (value, code) => {
  if (!Number.isSafeInteger(value) || value < 0 || value > 2_147_483_647) fail(400, code);
  return value;
};
const hexDigest = (value, code) => {
  const result = string(value, code, 64);
  if (!HEX_64_RE.test(result)) fail(400, code);
  return result;
};
const exactKeys = (value, allowed, required, code) => {
  const result = object(value, code);
  if (Object.keys(result).some((key) => !allowed.has(key)) || required.some((key) => !(key in result))) fail(400, code);
  return result;
};
const stableJson = (value) => {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
};
const digest = (value) => createHash('sha256').update(typeof value === 'string' ? value : stableJson(value)).digest('hex');
const tokenDigest = (value) => createHash('sha256').update(value, 'utf8').digest('hex');
const protocol = (body) => { if (body.protocol_version !== PROTOCOL_VERSION) fail(426, 'client_update_required'); };
const operationBody = (raw, operation) => {
  const body = object(raw);
  if (Object.keys(body).some((key) => !OPERATION_FIELDS[operation].has(key))) fail(400, 'invalid_request');
  protocol(body);
  return body;
};

function base64url(value, code, expectedLength) {
  const encoded = string(value, code, Math.ceil(expectedLength * 4 / 3) + 2);
  if (!BASE64URL_RE.test(encoded) || encoded.includes('=')) fail(400, code);
  const decoded = Buffer.from(encoded, 'base64url');
  if (decoded.length !== expectedLength || decoded.toString('base64url') !== encoded) fail(400, code);
  return decoded;
}

function validateMessage(raw, role, identity) {
  const message = exactKeys(raw, MESSAGE_FIELDS,
    ['client_message_id', 'chat_id', 'hashed_user_id', 'encrypted_content', 'role', 'created_at', 'updated_at'],
    'invalid_encrypted_message');
  string(message.client_message_id, 'invalid_message_id', 255);
  string(message.encrypted_content, 'invalid_encrypted_message', MAX_CONTENT_BYTES);
  if (message.chat_id !== identity.chatId || message.hashed_user_id !== identity.ownerHash || message.role !== role) fail(409, 'message_identity_mismatch');
  if (!Number.isSafeInteger(message.created_at) || !Number.isSafeInteger(message.updated_at)) fail(400, 'invalid_message_timestamp');
  for (const [key, value] of Object.entries(message)) {
    if (key.startsWith('encrypted_') && value != null) string(value, 'invalid_encrypted_message', MAX_CONTENT_BYTES);
  }
  return message;
}

function validateNewChatMetadata(raw, identity) {
  const metadata = exactKeys(
    raw,
    CHAT_METADATA_FIELDS,
    ['encrypted_title', 'encrypted_chat_key', 'created_at', 'updated_at'],
    'invalid_encrypted_chat_metadata',
  );
  if (metadata.encrypted_chat_key !== identity.wrappedKey) fail(409, 'immutable_chat_key_mismatch');
  for (const [key, value] of Object.entries(metadata)) {
    if (key.startsWith('encrypted_') && value != null) string(value, 'invalid_encrypted_chat_metadata', MAX_CONTENT_BYTES);
  }
  if (!Number.isSafeInteger(metadata.created_at) || metadata.created_at < 0
    || !Number.isSafeInteger(metadata.updated_at) || metadata.updated_at < 0) {
    fail(400, 'invalid_chat_timestamp');
  }
  return metadata;
}

function inferenceClaimDecision(state) {
  if (state === 'ENQUEUED') return true;
  if (['RUNNING', 'TERMINAL', 'FAILED'].includes(state)) return false;
  fail(409, 'invalid_inference_state');
}

function unsealedPreflightIds(runningIds, sealedIds) {
  const sealed = new Set(sealedIds);
  return runningIds.filter((id) => !sealed.has(id));
}

function availableJobMetadata(row) {
  return {
    job_id: row.id,
    chat_id: row.chat_id,
    turn_id: row.turn_id,
    inference_task_id: row.inference_task_id,
    assistant_message_id: row.assistant_message_id,
    chat_key_version: row.chat_key_version,
    state: row.state,
  };
}

function validateEnvelope(raw, version = PROTOCOL_VERSION) {
  const serialized = string(raw, 'invalid_sealed_payload', 24 * 1024 * 1024);
  for (const field of ['v', 'epk', 'nonce', 'ciphertext']) {
    if ((serialized.match(new RegExp(`"${field}"\\s*:`, 'g')) ?? []).length !== 1) fail(400, 'invalid_sealed_payload');
  }
  let envelope;
  try { envelope = JSON.parse(serialized); } catch { fail(400, 'invalid_sealed_payload'); }
  exactKeys(envelope, new Set(['v', 'epk', 'nonce', 'ciphertext']), ['v', 'epk', 'nonce', 'ciphertext'], 'invalid_sealed_payload');
  if (envelope.v !== version) fail(400, 'invalid_sealed_payload');
  base64url(envelope.epk, 'invalid_sealed_payload', 32);
  base64url(envelope.nonce, 'invalid_sealed_payload', 12);
  const ciphertext = string(envelope.ciphertext, 'invalid_sealed_payload', Math.ceil((MAX_CONTENT_BYTES + 16) * 4 / 3) + 2);
  if (!BASE64URL_RE.test(ciphertext) || ciphertext.includes('=')) fail(400, 'invalid_sealed_payload');
  const bytes = Buffer.from(ciphertext, 'base64url');
  if (bytes.length < 16 || bytes.length > MAX_CONTENT_BYTES + 16 || bytes.toString('base64url') !== ciphertext) fail(400, 'invalid_sealed_payload');
  return serialized;
}

async function lockIdentity(trx, value) {
  await trx.raw('SELECT pg_advisory_xact_lock(hashtextextended(?, 0))', [value]);
}
async function lockRecoveryChats(trx, ...chatIds) {
  for (const chatId of [...new Set(chatIds.filter(Boolean))].sort()) {
    await lockIdentity(trx, `chat-recovery-delete:${chatId}`);
  }
}
async function requireUnfencedRecoveryAccount(trx, ownerHash) {
  await lockIdentity(trx, `account-recovery:${ownerHash}`);
  if (await trx(ACCOUNT_FENCES).where({ id: ownerHash }).first()) {
    fail(409, 'account_recovery_fenced');
  }
}
async function assertNoPendingTeamAccountRecovery(trx, ownerHash) {
  const pendingLegacyBatch = await trx(LEGACY_BATCH_CLAIMS)
    .where({ hashed_user_id: ownerHash })
    .whereIn('state', ['PREPARED', 'CLAIMED'])
    .whereNotNull('hashed_team_id').first();
  if (pendingLegacyBatch) fail(409, 'pending_team_recovery');
  const pendingProducer = await trx(OUTPUT_PRODUCERS)
    .where({ hashed_user_id: ownerHash, state: 'PENDING' })
    .whereNotNull('hashed_team_id').first();
  if (pendingProducer) fail(409, 'pending_team_recovery');
  const pendingDirectSkill = await trx(AUTHORIZED_DIRECT_SKILLS)
    .where({ hashed_user_id: ownerHash })
    .whereIn('state', ['PENDING', 'RUNNING'])
    .whereNotNull('hashed_team_id').first();
  if (pendingDirectSkill) fail(409, 'pending_team_recovery');
  const pendingRerender = await trx(AUTHORIZED_RERENDERS)
    .where({ hashed_user_id: ownerHash })
    .whereIn('state', ['PENDING', 'RUNNING'])
    .whereNotNull('hashed_team_id').first();
  if (pendingRerender) fail(409, 'pending_team_recovery');
  const pendingLegacyProducer = await trx(LEGACY_OUTPUT_PRODUCERS)
    .where({ hashed_user_id: ownerHash })
    .whereIn('state', ['PENDING', 'RUNNING'])
    .whereNotNull('hashed_team_id').first();
  if (pendingLegacyProducer) fail(409, 'pending_team_recovery');
  const pendingOutput = await trx(OUTPUTS).where({ hashed_user_id: ownerHash })
    .whereIn('state', ['PREPARING', 'PENDING']).whereNull('deleted_at')
    .whereNotNull('root_hashed_team_id').first();
  if (pendingOutput) fail(409, 'pending_team_recovery');
  for (const [table, states, invalidatedField] of [
    [JOBS, ['AVAILABLE', 'LEASED'], 'invalidated_at'],
    [PREFLIGHTS, ['PREPARED', 'ENQUEUED', 'RUNNING'], 'deletion_invalidated_at'],
  ]) {
    const teamChatExists = `EXISTS (SELECT 1 FROM chats c WHERE c.id = ${table}.chat_id AND c.hashed_team_id IS NOT NULL)`;
    let query = trx(table).where({ hashed_user_id: ownerHash })
      .whereIn('state', states).whereNull(invalidatedField).whereRaw(teamChatExists);
    // Typed turns may leave the legacy preflight RUNNING after their output is
    // canonically acknowledged. The typed row itself is the deletion authority.
    if (table === PREFLIGHTS) {
      query = query.whereRaw('NOT EXISTS (SELECT 1 FROM chat_recovery_outputs o WHERE o.preflight_id = chat_turn_preflights.id AND o.deleted_at IS NULL)');
    }
    const pending = await query.first();
    if (pending) fail(409, 'pending_team_recovery');
  }
}

const cutoverResponse = (row) => ({
  protocol_epoch: row.protocol_epoch,
  sends_paused: row.sends_paused,
  legacy_in_flight: row.legacy_in_flight,
});

function validLegacyAdmission(admission) {
  if (!admission || typeof admission !== 'object' || Array.isArray(admission)) return false;
  const keys = Object.keys(admission).sort().join(',');
  if (keys !== 'actor_user_id,batch_commitment,batch_member_commitments,batch_message_ids,celery_task_id,chat_id,execution_claimed,first_message_id,hashed_team_id,hashed_user_id') {
    return false;
  }
  if (!UUID_RE.test(admission.actor_user_id) || !UUID_RE.test(admission.chat_id)
    || !HEX_64_RE.test(admission.hashed_user_id)
    || hashIdentifier(admission.actor_user_id) !== admission.hashed_user_id
    || (admission.hashed_team_id !== null && !HEX_64_RE.test(admission.hashed_team_id))
    || typeof admission.first_message_id !== 'string'
    || !admission.first_message_id || admission.first_message_id.length > 255
    || typeof admission.execution_claimed !== 'boolean') return false;
  if (admission.batch_message_ids === null) {
    return admission.batch_commitment === null
      && admission.batch_member_commitments === null && admission.celery_task_id === null
      && admission.execution_claimed === false;
  }
  return Array.isArray(admission.batch_message_ids)
    && admission.batch_message_ids.length >= 1
    && admission.batch_message_ids.length <= 20
    && admission.batch_message_ids[0] === admission.first_message_id
    && new Set(admission.batch_message_ids).size === admission.batch_message_ids.length
    && admission.batch_message_ids.every((id) => typeof id === 'string' && id.length > 0 && id.length <= 255)
    && Array.isArray(admission.batch_member_commitments)
    && admission.batch_member_commitments.length === admission.batch_message_ids.length
    && admission.batch_member_commitments.every((value) => HEX_64_RE.test(value))
    && HEX_64_RE.test(admission.batch_commitment)
    && UUID_RE.test(admission.celery_task_id);
}

function validateLegacyState(row) {
  if (!Array.isArray(row.active_legacy_tasks) || !Array.isArray(row.legacy_task_lifecycle)) {
    fail(500, 'cutover_state_corrupt');
  }
  const active = new Set();
  for (const identity of row.active_legacy_tasks) {
    if (typeof identity !== 'string' || !identity || Buffer.byteLength(identity, 'utf8') > 255
      || active.has(identity)) fail(500, 'cutover_state_corrupt');
    active.add(identity);
  }
  if (row.legacy_in_flight !== row.active_legacy_tasks.length) fail(500, 'cutover_state_corrupt');

  const lifecycleIdentities = new Set();
  const running = new Set();
  for (const record of row.legacy_task_lifecycle) {
    if (record === null || typeof record !== 'object' || Array.isArray(record)
      || Object.keys(record).some((key) => !LEGACY_LIFECYCLE_FIELDS.has(key))
      || !['task_identity', 'state', 'expires_at'].every((key) => key in record)
      || typeof record.task_identity !== 'string' || !record.task_identity
      || Buffer.byteLength(record.task_identity, 'utf8') > 255
      || lifecycleIdentities.has(record.task_identity)
      || !LEGACY_LIFECYCLE_STATES.has(record.state)
      || typeof record.expires_at !== 'string'
      || Number.isNaN(Date.parse(record.expires_at))
      || ('persistence_observed' in record && typeof record.persistence_observed !== 'boolean')) {
      fail(500, 'cutover_state_corrupt');
    }
    if ('admission' in record && !validLegacyAdmission(record.admission)) {
      fail(500, 'cutover_state_corrupt');
    }
    lifecycleIdentities.add(record.task_identity);
    if (record.state === 'RUNNING') running.add(record.task_identity);
  }
  if (running.size !== active.size || [...running].some((identity) => !active.has(identity))) {
    fail(500, 'cutover_state_corrupt');
  }
}

const legacyStateUpdate = (activeTasks, lifecycle) => ({
  active_legacy_tasks: JSON.stringify(activeTasks),
  legacy_in_flight: activeTasks.length,
  legacy_task_lifecycle: JSON.stringify(lifecycle),
});

function pruneExpiredLegacyState(row, now) {
  const expired = row.legacy_task_lifecycle.filter(
    (record) => new Date(record.expires_at) <= now,
  );
  const expiredRunning = new Set(
    expired.filter((record) => record.state === 'RUNNING').map((record) => record.task_identity),
  );
  return {
    activeTasks: row.active_legacy_tasks.filter((identity) => !expiredRunning.has(identity)),
    lifecycle: row.legacy_task_lifecycle.filter((record) => !expired.includes(record)),
    counts: {
      expired_legacy_running: expiredRunning.size,
      expired_legacy_awaiting_persistence: expired.filter(
        (record) => record.state === 'AWAITING_PERSISTENCE',
      ).length,
      expired_legacy_persisted: expired.filter((record) => record.state === 'PERSISTED').length,
    },
    changed: expired.length > 0,
  };
}

async function lockedProtocolState(trx) {
  await lockIdentity(trx, PROTOCOL_STATE_ID);
  let row = await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).forUpdate().first();
  if (!row) {
    row = {
      id: PROTOCOL_STATE_ID,
      protocol_epoch: 0,
      sends_paused: false,
      legacy_in_flight: 0,
      active_legacy_tasks: [],
      legacy_task_lifecycle: [],
    };
    await trx(PROTOCOL_STATE).insert({
      ...row,
      active_legacy_tasks: JSON.stringify([]),
      legacy_task_lifecycle: JSON.stringify([]),
    });
  }
  const hasLegacyTaskMapPlaceholder = row.active_legacy_tasks
    && typeof row.active_legacy_tasks === 'object'
    && !Array.isArray(row.active_legacy_tasks)
    && Object.keys(row.active_legacy_tasks).length === 0;
  if ((row.active_legacy_tasks == null || hasLegacyTaskMapPlaceholder)
    && row.protocol_epoch === 0 && row.legacy_in_flight === 0) {
    row.active_legacy_tasks = [];
    await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update({
      active_legacy_tasks: JSON.stringify([]),
    });
  }
  if (row.legacy_task_lifecycle == null
    && Array.isArray(row.active_legacy_tasks) && row.active_legacy_tasks.length === 0
    && row.legacy_in_flight === 0) {
    row.legacy_task_lifecycle = [];
    await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update({
      legacy_task_lifecycle: JSON.stringify([]),
    });
  }
  validateLegacyState(row);
  return row;
}

async function protocolStateSnapshot(database) {
  const row = await database(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).first();
  const hasLegacyTaskMapPlaceholder = row?.active_legacy_tasks
    && typeof row.active_legacy_tasks === 'object'
    && !Array.isArray(row.active_legacy_tasks)
    && Object.keys(row.active_legacy_tasks).length === 0;
  const needsRepair = !row
    || ((row.active_legacy_tasks == null || hasLegacyTaskMapPlaceholder)
      && row.protocol_epoch === 0 && row.legacy_in_flight === 0)
    || (row.legacy_task_lifecycle == null
      && Array.isArray(row.active_legacy_tasks) && row.active_legacy_tasks.length === 0
      && row.legacy_in_flight === 0);
  if (needsRepair) {
    return database.transaction(async (trx) => lockedProtocolState(trx));
  }
  validateLegacyState(row);
  return row;
}

async function getCutoverState(database, raw) {
  operationBody(raw, 'get_cutover_state');
  return cutoverResponse(await protocolStateSnapshot(database));
}

async function setSendsPaused(database, raw) {
  const body = operationBody(raw, 'set_sends_paused');
  if (typeof body.sends_paused !== 'boolean') fail(400, 'invalid_pause_state');
  return database.transaction(async (trx) => {
    const row = await lockedProtocolState(trx);
    await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update({ sends_paused: body.sends_paused });
    return cutoverResponse({ ...row, sends_paused: body.sends_paused });
  });
}

function legacyAdmissionInput(body, taskIdentity) {
  const fields = ['actor_user_id', 'hashed_user_id', 'chat_id', 'first_message_id', 'hashed_team_id'];
  if (!fields.some((key) => body[key] !== undefined)) return null;
  if (fields.slice(0, 4).some((key) => body[key] === undefined)) {
    fail(400, 'invalid_legacy_admission');
  }
  const admission = {
    actor_user_id: uuid(body.actor_user_id, 'invalid_actor_id'),
    hashed_user_id: hexDigest(body.hashed_user_id, 'invalid_owner'),
    chat_id: uuid(body.chat_id, 'invalid_chat_id'),
    first_message_id: string(body.first_message_id, 'invalid_message_id', 255),
    hashed_team_id: body.hashed_team_id == null ? null
      : hexDigest(body.hashed_team_id, 'invalid_team'),
    batch_message_ids: null,
    batch_member_commitments: null,
    batch_commitment: null,
    celery_task_id: null,
    execution_claimed: false,
  };
  if (admission.hashed_user_id !== hashIdentifier(admission.actor_user_id)
    || taskIdentity !== createHash('sha256').update(
      `${admission.actor_user_id}:${admission.chat_id}:${admission.first_message_id}`,
    ).digest('hex')) fail(409, 'legacy_admission_identity_mismatch');
  return admission;
}

async function checkedLegacyAdmissionAuthority(trx, admission) {
  await requireUnfencedRecoveryAccount(trx, admission.hashed_user_id);
  await lockRecoveryChats(trx, admission.chat_id);
  if (await trx(CHAT_DELETION_FENCES).where({ id: admission.chat_id }).first()) {
    fail(409, 'producer_chat_deleted');
  }
  const actor = await trx('directus_users').where({ id: admission.actor_user_id }).first();
  if (!actor || actor.status !== 'active') fail(404, 'legacy_producer_actor_not_found');
  const chat = await authorizedOutputChat(trx, admission.chat_id, admission.hashed_user_id);
  if ((chat.hashed_team_id || null) !== admission.hashed_team_id) {
    fail(409, 'producer_team_scope_changed');
  }
}

async function admitLegacyInference(database, raw, now) {
  const body = operationBody(raw, 'admit_legacy_inference');
  const taskIdentity = string(body.task_identity, 'invalid_task_identity', 255);
  const isServerTriggerIdentity = taskIdentity.startsWith(SERVER_TRIGGER_TASK_IDENTITY_PREFIX);
  const admission = legacyAdmissionInput(body, taskIdentity);
  return database.transaction(async (trx) => {
    if (admission) await checkedLegacyAdmissionAuthority(trx, admission);
    let row = await lockedProtocolState(trx);
    if (row.protocol_epoch !== 0 && !isServerTriggerIdentity) fail(426, 'client_update_required');
    if (row.sends_paused && !isServerTriggerIdentity) fail(503, 'inference_temporarily_paused');
    const claim = await trx(LEGACY_BATCH_CLAIMS).where({ task_identity: taskIdentity })
      .forUpdate().first();
    if (claim && (!admission || !legacyOrdinaryRowMatches(claim, admission))) {
      fail(409, 'legacy_task_identity_reserved');
    }
    if (claim && claim.state !== 'PREPARED') {
      return { ...cutoverResponse(row), admitted: false, idempotent: true,
        state: claim.state, admission_recorded: true };
    }
    const pruned = pruneExpiredLegacyState(row, now);
    if (pruned.changed) {
      await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update(
        legacyStateUpdate(pruned.activeTasks, pruned.lifecycle),
      );
      row = {
        ...row,
        active_legacy_tasks: pruned.activeTasks,
        legacy_in_flight: pruned.activeTasks.length,
        legacy_task_lifecycle: pruned.lifecycle,
      };
    }
    const existing = row.legacy_task_lifecycle.find((record) => record.task_identity === taskIdentity);
    if (existing) {
      if (JSON.stringify(existing.admission ?? null) !== JSON.stringify(admission)) {
        fail(409, 'legacy_admission_mismatch');
      }
      return { ...cutoverResponse(row), admitted: false, idempotent: true,
        state: existing.state, ...(admission ? { admission_recorded: true } : {}) };
    }
    if (admission && !claim) {
      await trx(LEGACY_BATCH_CLAIMS).insert({
        id: randomUUID(), task_identity: taskIdentity, kind: 'ORDINARY',
        broker_task_id: null, dispatch_binding: null,
        actor_user_id: admission.actor_user_id, hashed_user_id: admission.hashed_user_id,
        hashed_team_id: admission.hashed_team_id, chat_id: admission.chat_id,
        first_message_id: admission.first_message_id,
        batch_message_ids: null, batch_member_commitments: null,
        batch_commitment: null, state: 'PREPARED', worker_completed: false,
        persistence_observed: false, created_at: now,
      });
    }
    const activeTasks = [...row.active_legacy_tasks, taskIdentity];
    const lifecycle = [...row.legacy_task_lifecycle, {
      task_identity: taskIdentity,
      state: 'RUNNING',
      expires_at: new Date(now.getTime() + LEGACY_RUNNING_TTL_MS).toISOString(),
      ...(admission ? { admission } : {}),
    }];
    await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update(
      legacyStateUpdate(activeTasks, lifecycle),
    );
    return {
      ...cutoverResponse({ ...row, legacy_in_flight: activeTasks.length }),
      admitted: true,
      idempotent: false,
      state: 'RUNNING',
      ...(admission ? { admission_recorded: true } : {}),
    };
  });
}

function legacyOrdinaryRowMatches(row, admission) {
  return row.kind === 'ORDINARY'
    && row.actor_user_id === admission.actor_user_id
    && row.hashed_user_id === admission.hashed_user_id
    && (row.hashed_team_id || null) === admission.hashed_team_id
    && row.chat_id === admission.chat_id
    && row.first_message_id === admission.first_message_id
    && row.batch_message_ids == null && row.batch_member_commitments == null
    && row.batch_commitment == null;
}

function legacyDispatchInput(raw, operation) {
  const body = operationBody(raw, operation);
  const taskIdentity = hexDigest(body.task_identity, 'invalid_task_identity');
  const admission = legacyAdmissionInput(body, taskIdentity);
  if (!admission) fail(400, 'invalid_legacy_admission');
  const brokerTaskId = string(body.broker_task_id, 'invalid_broker_task_id', 255);
  const dispatchBinding = hexDigest(body.dispatch_binding, 'invalid_dispatch_binding');
  return { taskIdentity, admission, brokerTaskId, dispatchBinding };
}

async function bindOrdinaryLegacyDispatch(database, raw, now) {
  const { taskIdentity, admission, brokerTaskId, dispatchBinding } =
    legacyDispatchInput(raw, 'bind_ordinary_legacy_dispatch');
  return database.transaction(async (trx) => {
    await checkedLegacyAdmissionAuthority(trx, admission);
    const row = await lockedProtocolState(trx);
    if (row.protocol_epoch !== 0 || row.sends_paused) fail(409, 'legacy_admission_closed');
    const claim = await trx(LEGACY_BATCH_CLAIMS).where({ task_identity: taskIdentity })
      .forUpdate().first();
    if (!claim || !legacyOrdinaryRowMatches(claim, admission)) {
      fail(409, 'legacy_admission_not_running');
    }
    if (claim.broker_task_id && (claim.broker_task_id !== brokerTaskId
      || claim.dispatch_binding !== dispatchBinding)) fail(409, 'legacy_dispatch_mismatch');
    if (claim.state !== 'PREPARED') {
      return { bound: true, idempotent: true, enqueue_allowed: false,
        task_identity: taskIdentity, status: claim.state };
    }
    const record = row.legacy_task_lifecycle.find((item) => item.task_identity === taskIdentity);
    if (!record || record.state !== 'RUNNING'
      || !row.active_legacy_tasks.includes(taskIdentity)
      || JSON.stringify(record.admission) !== JSON.stringify(admission)
      || new Date(record.expires_at) <= now) fail(409, 'legacy_admission_not_running');
    if (await trx(MESSAGES).where({
      client_message_id: brokerTaskId, chat_id: admission.chat_id,
      hashed_user_id: admission.hashed_user_id, role: 'assistant',
    }).first()) {
      return { bound: false, idempotent: true, enqueue_allowed: false,
        task_identity: taskIdentity, status: 'CANONICAL_PRESENT' };
    }
    if (!claim.broker_task_id) {
      await trx(LEGACY_BATCH_CLAIMS).where({ task_identity: taskIdentity, state: 'PREPARED' })
        .update({ broker_task_id: brokerTaskId, dispatch_binding: dispatchBinding });
    }
    return { bound: true, idempotent: Boolean(claim.broker_task_id),
      enqueue_allowed: true, task_identity: taskIdentity, status: 'PREPARED' };
  });
}

async function claimLegacyInferenceStart(database, raw, now) {
  const { taskIdentity, admission, brokerTaskId, dispatchBinding } =
    legacyDispatchInput(raw, 'claim_legacy_inference_start');
  return database.transaction(async (trx) => {
    await checkedLegacyAdmissionAuthority(trx, admission);
    const row = await lockedProtocolState(trx);
    if (row.protocol_epoch !== 0 || row.sends_paused) fail(409, 'legacy_admission_closed');
    const claim = await trx(LEGACY_BATCH_CLAIMS).where({ task_identity: taskIdentity })
      .forUpdate().first();
    if (!claim || !legacyOrdinaryRowMatches(claim, admission)) {
      fail(409, 'legacy_admission_not_running');
    }
    if (!claim.broker_task_id || claim.broker_task_id !== brokerTaskId
      || claim.dispatch_binding !== dispatchBinding) fail(409, 'legacy_dispatch_mismatch');
    if (claim.state !== 'PREPARED') {
      return { authorized: false, claimed: false, task_identity: taskIdentity,
        status: claim.state };
    }
    const record = row.legacy_task_lifecycle.find((item) => item.task_identity === taskIdentity);
    if (!record || record.state !== 'RUNNING'
      || !row.active_legacy_tasks.includes(taskIdentity)
      || !record.admission
      || JSON.stringify(record.admission) !== JSON.stringify(admission)
      || new Date(record.expires_at) <= now) fail(409, 'legacy_admission_not_running');
    if (await trx(MESSAGES).where({
      client_message_id: brokerTaskId, chat_id: admission.chat_id,
      hashed_user_id: admission.hashed_user_id, role: 'assistant',
    }).first()) {
      return { authorized: false, claimed: false, task_identity: taskIdentity,
        status: 'CANONICAL_PRESENT' };
    }
    await trx(LEGACY_BATCH_CLAIMS).where({ task_identity: taskIdentity, state: 'PREPARED' })
      .update({ state: 'CLAIMED', claimed_at: now });
    return { authorized: true, claimed: true, task_identity: taskIdentity, status: 'RUNNING' };
  });
}

function legacyBatchInput(raw, operation) {
  const body = operationBody(raw, operation);
  const taskIdentity = hexDigest(body.task_identity, 'invalid_task_identity');
  const admission = legacyAdmissionInput(body, taskIdentity);
  if (!admission) fail(400, 'invalid_legacy_batch');
  if (!Array.isArray(body.members) || body.members.length < 1 || body.members.length > 20) {
    fail(400, 'invalid_legacy_batch');
  }
  const messageIds = [];
  const commitments = [];
  for (const member of body.members) {
    if (!member || typeof member !== 'object' || Array.isArray(member)
      || Object.keys(member).sort().join(',') !== 'chat_id,hashed_user_id,message_id,payload_commitment') {
      fail(400, 'invalid_legacy_batch');
    }
    const messageId = string(member.message_id, 'invalid_message_id', 255);
    if (uuid(member.chat_id, 'invalid_chat_id') !== admission.chat_id
      || hexDigest(member.hashed_user_id, 'invalid_owner') !== admission.hashed_user_id) {
      fail(409, 'legacy_batch_scope_mismatch');
    }
    messageIds.push(messageId);
    commitments.push(hexDigest(member.payload_commitment, 'invalid_payload_commitment'));
  }
  if (messageIds[0] !== admission.first_message_id
    || new Set(messageIds).size !== messageIds.length) fail(409, 'legacy_batch_member_mismatch');
  admission.batch_message_ids = messageIds;
  admission.batch_member_commitments = commitments;
  admission.batch_commitment = hexDigest(body.batch_commitment, 'invalid_batch_commitment');
  admission.celery_task_id = uuid(body.celery_task_id, 'invalid_task_id');
  if (!validLegacyAdmission(admission)) fail(400, 'invalid_legacy_batch');
  return { taskIdentity, admission };
}

function legacyBatchRowMatches(row, admission) {
  let memberIds;
  let commitments;
  try {
    memberIds = typeof row.batch_message_ids === 'string'
      ? JSON.parse(row.batch_message_ids) : row.batch_message_ids;
    commitments = typeof row.batch_member_commitments === 'string'
      ? JSON.parse(row.batch_member_commitments) : row.batch_member_commitments;
  } catch {
    fail(500, 'legacy_batch_state_corrupt');
  }
  return row.kind === 'BATCH' && row.id === admission.celery_task_id
    && row.actor_user_id === admission.actor_user_id
    && row.hashed_user_id === admission.hashed_user_id
    && (row.hashed_team_id || null) === admission.hashed_team_id
    && row.chat_id === admission.chat_id
    && row.first_message_id === admission.first_message_id
    && row.batch_commitment === admission.batch_commitment
    && JSON.stringify(memberIds) === JSON.stringify(admission.batch_message_ids)
    && JSON.stringify(commitments) === JSON.stringify(admission.batch_member_commitments);
}

async function prepareLegacyBatch(database, raw, now) {
  const { taskIdentity, admission } = legacyBatchInput(raw, 'prepare_legacy_batch');
  return database.transaction(async (trx) => {
    await checkedLegacyAdmissionAuthority(trx, admission);
    let row = await lockedProtocolState(trx);
    if (row.protocol_epoch !== 0) fail(426, 'client_update_required');
    if (row.sends_paused) fail(503, 'inference_temporarily_paused');
    const pruned = pruneExpiredLegacyState(row, now);
    if (pruned.changed) {
      await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update(
        legacyStateUpdate(pruned.activeTasks, pruned.lifecycle),
      );
      row = { ...row, active_legacy_tasks: pruned.activeTasks,
        legacy_in_flight: pruned.activeTasks.length, legacy_task_lifecycle: pruned.lifecycle };
    }
    const claim = await trx(LEGACY_BATCH_CLAIMS).where({ task_identity: taskIdentity })
      .forUpdate().first();
    if (claim && !legacyBatchRowMatches(claim, admission)) fail(409, 'legacy_batch_mismatch');
    if (claim?.state === 'INVALIDATED') fail(409, 'legacy_batch_invalidated');
    if (claim?.state === 'CLAIMED' || claim?.state === 'COMPLETED') {
      return { task_identity: taskIdentity, status: claim.state,
        execution_claimed: true, idempotent: true };
    }
    const existing = row.legacy_task_lifecycle.find(
      (item) => item.task_identity === taskIdentity,
    );
    if (existing) {
      if (JSON.stringify(existing.admission
        ? { ...existing.admission, execution_claimed: false } : null)
        !== JSON.stringify(admission)) {
        fail(409, 'legacy_batch_mismatch');
      }
      if (existing.admission.execution_claimed) fail(500, 'legacy_batch_state_corrupt');
      return { task_identity: taskIdentity, status: 'PREPARED',
        execution_claimed: false, idempotent: true };
    }
    if (!claim) {
      await trx(LEGACY_BATCH_CLAIMS).insert({
        id: admission.celery_task_id, task_identity: taskIdentity, kind: 'BATCH',
        broker_task_id: admission.celery_task_id, dispatch_binding: null,
        actor_user_id: admission.actor_user_id, hashed_user_id: admission.hashed_user_id,
        hashed_team_id: admission.hashed_team_id, chat_id: admission.chat_id,
        first_message_id: admission.first_message_id,
        batch_message_ids: JSON.stringify(admission.batch_message_ids),
        batch_member_commitments: JSON.stringify(admission.batch_member_commitments),
        batch_commitment: admission.batch_commitment, state: 'PREPARED',
        worker_completed: false, persistence_observed: false, created_at: now,
      });
    }
    const activeTasks = [...row.active_legacy_tasks, taskIdentity];
    const lifecycle = [...row.legacy_task_lifecycle, {
      task_identity: taskIdentity, state: 'RUNNING',
      expires_at: new Date(now.getTime() + LEGACY_RUNNING_TTL_MS).toISOString(),
      admission,
    }];
    await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update(
      legacyStateUpdate(activeTasks, lifecycle),
    );
    return { task_identity: taskIdentity, status: 'PREPARED',
      execution_claimed: false, idempotent: Boolean(claim) };
  });
}

async function claimLegacyBatch(database, raw, now) {
  const { taskIdentity, admission } = legacyBatchInput(raw, 'claim_legacy_batch');
  return database.transaction(async (trx) => {
    await checkedLegacyAdmissionAuthority(trx, admission);
    const row = await lockedProtocolState(trx);
    if (row.protocol_epoch !== 0) fail(409, 'legacy_batch_epoch_changed');
    const claim = await trx(LEGACY_BATCH_CLAIMS).where({ task_identity: taskIdentity })
      .forUpdate().first();
    if (!claim || !legacyBatchRowMatches(claim, admission)) fail(409, 'legacy_batch_mismatch');
    if (claim.state === 'INVALIDATED') fail(409, 'legacy_batch_invalidated');
    if (claim.state !== 'PREPARED') {
      return { task_identity: taskIdentity, status: claim.state, claimed: false };
    }
    const record = row.legacy_task_lifecycle.find(
      (item) => item.task_identity === taskIdentity,
    );
    if (!record || !record.admission
      || record.state !== 'RUNNING'
      || JSON.stringify({ ...record.admission, execution_claimed: false })
        !== JSON.stringify(admission)) fail(409, 'legacy_batch_mismatch');
    if (record.admission.execution_claimed) fail(500, 'legacy_batch_state_corrupt');
    if (new Date(record.expires_at) <= now
      || !row.active_legacy_tasks.includes(taskIdentity)) fail(410, 'legacy_batch_expired');
    if (await trx(MESSAGES).where({
      client_message_id: admission.celery_task_id, chat_id: admission.chat_id,
      hashed_user_id: admission.hashed_user_id, role: 'assistant',
    }).first()) {
      return { task_identity: taskIdentity, status: 'CANONICAL_PRESENT', claimed: false };
    }
    const lifecycle = row.legacy_task_lifecycle.map((item) => item === record
      ? { ...item, admission: { ...admission, execution_claimed: true } } : item);
    await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update(
      legacyStateUpdate(row.active_legacy_tasks, lifecycle),
    );
    await trx(LEGACY_BATCH_CLAIMS).where({ task_identity: taskIdentity, state: 'PREPARED' })
      .update({ state: 'CLAIMED', claimed_at: now });
    return { task_identity: taskIdentity, status: 'RUNNING', claimed: true };
  });
}

async function markLegacyInferenceCompleted(database, raw, now) {
  const body = operationBody(raw, 'mark_legacy_inference_completed');
  const taskIdentity = string(body.task_identity, 'invalid_task_identity', 255);
  return database.transaction(async (trx) => {
    const row = await lockedProtocolState(trx);
    const claim = await trx(LEGACY_BATCH_CLAIMS).where({ task_identity: taskIdentity })
      .forUpdate().first();
    if (claim?.state === 'CLAIMED' && !claim.worker_completed) {
      await trx(LEGACY_BATCH_CLAIMS).where({ task_identity: taskIdentity }).update({
        worker_completed: true,
        ...(claim.persistence_observed ? { state: 'COMPLETED', completed_at: now } : {}),
      });
    }
    const record = row.legacy_task_lifecycle.find((item) => item.task_identity === taskIdentity);
    if (!record) {
      return { ...cutoverResponse(row), completed: false, idempotent: true, state: null };
    }
    if (record.state !== 'RUNNING') {
      return { ...cutoverResponse(row), completed: false, idempotent: true, state: record.state };
    }
    const state = record.persistence_observed ? 'PERSISTED' : 'AWAITING_PERSISTENCE';
    const activeTasks = row.active_legacy_tasks.filter((identity) => identity !== taskIdentity);
    const lifecycle = row.legacy_task_lifecycle.map((item) => item === record ? {
      ...item,
      state,
      expires_at: new Date(now.getTime() + LEGACY_TOMBSTONE_TTL_MS).toISOString(),
    } : item);
    await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update(
      legacyStateUpdate(activeTasks, lifecycle),
    );
    return {
      ...cutoverResponse({ ...row, legacy_in_flight: activeTasks.length }),
      completed: true,
      idempotent: false,
      state,
    };
  });
}

async function acknowledgeLegacyPersistence(database, raw, now) {
  const body = operationBody(raw, 'acknowledge_legacy_persistence');
  const suppliedIdentity = string(body.task_identity, 'invalid_task_identity', 255);
  return database.transaction(async (trx) => {
    const row = await lockedProtocolState(trx);
    let claim = await trx(LEGACY_BATCH_CLAIMS).where({ broker_task_id: suppliedIdentity })
      .forUpdate().first();
    if (!claim) {
      claim = await trx(LEGACY_BATCH_CLAIMS).where({ task_identity: suppliedIdentity })
        .forUpdate().first();
    }
    const taskIdentity = claim?.task_identity || suppliedIdentity;
    if (claim) {
      if (claim.state === 'INVALIDATED') fail(409, 'legacy_task_invalidated');
      const receiptFields = ['chat_id', 'hashed_user_id', 'assistant_message_id', 'ciphertext_digest'];
      if (receiptFields.some((field) => body[field] === undefined)) {
        return { ...cutoverResponse(row), acknowledged: false, idempotent: true,
          state: claim.state, output_receipt_required: true };
      }
      const chatId = uuid(body.chat_id, 'invalid_chat_id');
      const ownerHash = hexDigest(body.hashed_user_id, 'invalid_owner');
      const assistantId = string(body.assistant_message_id, 'invalid_message_id', 255);
      const expectedDigest = hexDigest(body.ciphertext_digest, 'invalid_ciphertext_digest');
      if (chatId !== claim.chat_id || ownerHash !== claim.hashed_user_id
        || assistantId !== claim.broker_task_id || suppliedIdentity !== claim.broker_task_id) {
        fail(409, 'legacy_output_receipt_mismatch');
      }
      const message = await trx(MESSAGES).where({
        client_message_id: assistantId, chat_id: chatId,
        hashed_user_id: ownerHash, role: 'assistant',
      }).forShare().first();
      if (!message || typeof message.encrypted_content !== 'string'
        || digest(message.encrypted_content) !== expectedDigest) {
        fail(409, 'legacy_output_receipt_mismatch');
      }
      if (claim.state === 'PREPARED') {
        return { ...cutoverResponse(row), acknowledged: false, idempotent: true,
          state: 'PREPARED', output_receipt_required: true };
      }
    }
    if (claim?.state === 'CLAIMED' && !claim.persistence_observed) {
      await trx(LEGACY_BATCH_CLAIMS).where({ task_identity: taskIdentity }).update({
        persistence_observed: true,
        ...(claim.worker_completed ? { state: 'COMPLETED', completed_at: now } : {}),
      });
    }
    const record = row.legacy_task_lifecycle.find((item) => item.task_identity === taskIdentity);
    if (!record) {
      return { ...cutoverResponse(row), acknowledged: Boolean(claim), idempotent: true, state: null,
        ...(claim ? { output_receipt_verified: true } : {}) };
    }
    if (record.state === 'PERSISTED') {
      return { ...cutoverResponse(row), acknowledged: Boolean(claim), idempotent: true, state: record.state,
        ...(claim ? { output_receipt_verified: true } : {}) };
    }
    const state = record.state === 'AWAITING_PERSISTENCE' ? 'PERSISTED' : 'RUNNING';
    const lifecycle = row.legacy_task_lifecycle.map((item) => item === record ? {
      ...item,
      state,
      persistence_observed: true,
    } : item);
    await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update(
      legacyStateUpdate(row.active_legacy_tasks, lifecycle),
    );
    return { ...cutoverResponse(row), acknowledged: true, idempotent: false, state,
      ...(claim ? { output_receipt_verified: true } : {}) };
  });
}

async function authorizeLegacyCompletion(database, raw, now) {
  const body = operationBody(raw, 'authorize_legacy_completion');
  const taskIdentity = string(body.task_identity, 'invalid_task_identity', 255);
  return database.transaction(async (trx) => {
    const row = await lockedProtocolState(trx);
    const record = row.legacy_task_lifecycle.find((item) => item.task_identity === taskIdentity);
    if (!record) fail(404, 'legacy_completion_not_found');
    if (new Date(record.expires_at) <= now) fail(410, 'legacy_completion_expired');
    if (record.state === 'RUNNING') fail(409, 'legacy_completion_not_ready');
    return { authorized: true, task_identity: taskIdentity, state: record.state };
  });
}

async function releaseLegacyInference(database, raw, now) {
  const body = operationBody(raw, 'release_legacy_inference');
  const taskIdentity = string(body.task_identity, 'invalid_task_identity', 255);
  return database.transaction(async (trx) => {
    const row = await lockedProtocolState(trx);
    const record = row.legacy_task_lifecycle.find(
      (item) => item.task_identity === taskIdentity,
    );
    const claim = await trx(LEGACY_BATCH_CLAIMS).where({ task_identity: taskIdentity })
      .forUpdate().first();
    if ((claim && ['CLAIMED', 'COMPLETED'].includes(claim.state))
      || (!claim && record?.admission?.execution_claimed)) {
      return { ...cutoverResponse(row), released: false, held: true, idempotent: true };
    }
    await trx(LEGACY_OUTPUT_PRODUCERS)
      .where({ legacy_task_identity: taskIdentity })
      .whereIn('state', ['PENDING', 'RUNNING'])
      .update({ state: 'INVALIDATED', invalidated_at: now });
    const hasActive = row.active_legacy_tasks.includes(taskIdentity);
    const hasLifecycle = row.legacy_task_lifecycle.some(
      (record) => record.task_identity === taskIdentity,
    );
    if (!hasActive && !hasLifecycle) {
      return { ...cutoverResponse(row), released: false, idempotent: true };
    }
    const activeTasks = row.active_legacy_tasks.filter((identity) => identity !== taskIdentity);
    const lifecycle = row.legacy_task_lifecycle.filter(
      (record) => record.task_identity !== taskIdentity,
    );
    await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update(
      legacyStateUpdate(activeTasks, lifecycle),
    );
    return {
      ...cutoverResponse({ ...row, legacy_in_flight: activeTasks.length }),
      released: true,
      idempotent: false,
    };
  });
}

async function activateProtocolEpoch(database, raw, now) {
  const body = operationBody(raw, 'activate_protocol_epoch');
  const targetEpoch = integer(body.target_epoch, 'invalid_protocol_epoch');
  return database.transaction(async (trx) => {
    let row = await lockedProtocolState(trx);
    const pruned = pruneExpiredLegacyState(row, now);
    if (pruned.changed) {
      await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update(
        legacyStateUpdate(pruned.activeTasks, pruned.lifecycle),
      );
      row = {
        ...row,
        active_legacy_tasks: pruned.activeTasks,
        legacy_in_flight: pruned.activeTasks.length,
        legacy_task_lifecycle: pruned.lifecycle,
      };
    }
    if (targetEpoch < row.protocol_epoch) fail(409, 'protocol_epoch_rollback');
    if (targetEpoch === row.protocol_epoch) return { ...cutoverResponse(row), activated: false };
    if (targetEpoch !== 1) fail(400, 'invalid_protocol_epoch');
    if (!row.sends_paused) fail(409, 'sends_not_paused');
    if (row.legacy_in_flight !== 0) fail(409, 'legacy_in_flight');
    if (await trx(LEGACY_OUTPUT_PRODUCERS)
      .whereIn('state', ['PENDING', 'RUNNING']).first()) {
      fail(409, 'legacy_output_producers_pending');
    }
    if (await trx(LEGACY_BATCH_CLAIMS)
      .whereIn('state', ['PREPARED', 'CLAIMED']).first()) {
      fail(409, 'legacy_batches_pending');
    }
    await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update({ protocol_epoch: targetEpoch });
    return { ...cutoverResponse({ ...row, protocol_epoch: targetEpoch }), activated: true };
  });
}
async function ownedChat(trx, chatId, ownerHash) {
  const chat = await trx(CHATS).where({ id: chatId }).forUpdate().first();
  if (!chat || chat.hashed_user_id !== ownerHash) fail(404, 'chat_not_found');
  return chat;
}
async function authorizedTeamWriter(trx, teamHash, actorHash, lock = true) {
  let membershipQuery = trx(TEAM_MEMBERSHIPS).where({
    hashed_team_id: teamHash, hashed_user_id: actorHash, status: 'active',
  });
  let teamQuery = trx(TEAMS).where({ hashed_team_id: teamHash, status: 'active' });
  if (lock) {
    membershipQuery = membershipQuery.forShare();
    teamQuery = teamQuery.forShare();
  }
  const membership = await membershipQuery.first();
  const team = await teamQuery.first();
  if (!team || !membership || !['owner', 'admin', 'member'].includes(membership.role)) {
    fail(404, 'chat_not_found');
  }
}
async function authorizedTeamDeleter(trx, teamHash, actorHash, creatorHash) {
  const membership = await trx(TEAM_MEMBERSHIPS).where({
    hashed_team_id: teamHash, hashed_user_id: actorHash, status: 'active',
  }).forShare().first();
  const team = await trx(TEAMS).where({ hashed_team_id: teamHash, status: 'active' }).forShare().first();
  // Existing creator-owned Team chats could be deleted by their creator even
  // when that member was not an admin. A moved Team chat has no personal owner.
  if (!team || !membership || !(['owner', 'admin'].includes(membership.role)
    || (creatorHash === actorHash && membership.role === 'member'))) fail(404, 'chat_not_found');
}
async function authorizedOutputChat(trx, chatId, actorHash, lock = true) {
  let query = trx(CHATS).where({ id: chatId });
  if (lock) query = query.forUpdate();
  const chat = await query.first();
  if (!chat || chat.storage_state === 'deleting') fail(404, 'chat_not_found');
  if (!chat.hashed_team_id) {
    if (chat.hashed_user_id !== actorHash) fail(404, 'chat_not_found');
    return chat;
  }
  await authorizedTeamWriter(trx, chat.hashed_team_id, actorHash, lock);
  return chat;
}
const outputChatScope = (chat, actorHash) => chat.hashed_team_id
  ? { id: chat.id, hashed_team_id: chat.hashed_team_id }
  : { id: chat.id, hashed_user_id: actorHash };
async function authorizedOutputRecordChats(trx, row, actorHash) {
  const root = await authorizedOutputChat(trx, row.root_chat_id, actorHash);
  const target = await authorizedOutputChat(trx, row.target_chat_id, actorHash);
  if ((root.hashed_team_id || null) !== (row.root_hashed_team_id || null)
    || (target.hashed_team_id || null) !== (root.hashed_team_id || null)) {
    fail(404, 'recovery_output_not_found');
  }
  return { root, target };
}
async function lockedOutputRecord(trx, recordId, ownerHash) {
  const snapshot = await trx(OUTPUTS).where({ id: recordId, hashed_user_id: ownerHash }).first();
  if (!snapshot) fail(404, 'recovery_output_not_found');
  await requireUnfencedRecoveryAccount(trx, ownerHash);
  await lockRecoveryChats(trx, snapshot.root_chat_id, snapshot.target_chat_id);
  const row = await trx(OUTPUTS).where({ id: recordId, hashed_user_id: ownerHash })
    .forUpdate().first();
  if (!row) fail(404, 'recovery_output_not_found');
  return row;
}
const responseForPreflight = (row) => ({
  preflight_id: row.id, state: row.state, committed_messages_v: row.committed_messages_v,
  chat_key_version: row.chat_key_version, recovery_key_fingerprint: digest(row.recovery_public_key),
  commitment_version: row.commitment_version, inference_task_id: row.inference_task_id,
  billing_identity: row.billing_identity, outbox_id: row.outbox_id,
});
const samePreflight = (row, values) => Object.entries(values).every(([key, value]) => row[key] === value);
const sameChatMetadata = (chat, metadata) => Object.entries(metadata)
  .every(([key, value]) => key === 'updated_at' || chat[key] === value);
const canCompleteChatMetadata = (chat, metadata) => Object.entries(metadata)
  .every(([key, value]) => key === 'updated_at' || chat[key] == null || chat[key] === value);
const missingChatMetadata = (chat, metadata) => Object.fromEntries(Object.entries(metadata)
  .filter(([key]) => key === 'updated_at' || chat[key] == null));
const isEmptyDraftShell = (chat) => Number(chat.messages_v ?? 0) === 0
  && Number(chat.title_v ?? 0) === 0
  && Number(chat.metadata_v ?? 0) === 0
  && chat.last_message_timestamp == null;
const hashIdentifier = (value) => createHash('sha256').update(value).digest('hex');

async function preparePreflight(database, raw, now) {
  const body = operationBody(raw, 'prepare_preflight');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  const teamHash = body.hashed_team_id === undefined ? null : hexDigest(body.hashed_team_id, 'invalid_team');
  const chatId = uuid(body.chat_id, 'invalid_chat_id');
  const turnId = uuid(body.turn_id, 'invalid_turn_id');
  const userMessageId = string(body.user_message_id, 'invalid_message_id', 255);
  const deviceHash = string(body.device_hash, 'invalid_device', 128);
  const keyVersion = integer(body.chat_key_version, 'invalid_key_version');
  const wrappedKey = string(body.wrapped_chat_key, 'invalid_wrapped_chat_key', 16_384);
  const recoveryKey = string(body.recovery_public_key, 'invalid_recovery_public_key', 43);
  base64url(recoveryKey, 'invalid_recovery_public_key', 32);
  const commitment = hexDigest(body.inference_commitment, 'invalid_inference_commitment');
  const commitmentVersion = integer(body.commitment_version, 'invalid_commitment_version');
  const expectedVersion = integer(body.expected_messages_v, 'invalid_message_version');
  const chatMetadata = body.encrypted_chat_metadata === undefined
    ? null
    : validateNewChatMetadata(body.encrypted_chat_metadata, { chatId, ownerHash, wrappedKey });
  const message = validateMessage(body.encrypted_user_message, 'user', { chatId, ownerHash });
  if (message.client_message_id !== userMessageId) fail(409, 'message_identity_mismatch');
  const values = {
    user_message_id: userMessageId, device_hash: deviceHash, chat_key_version: keyVersion,
    wrapped_chat_key: wrappedKey, recovery_public_key: recoveryKey,
    encrypted_user_digest: digest(message), inference_commitment: commitment,
    commitment_version: commitmentVersion,
  };
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, ownerHash);
    if (teamHash) {
      const cutover = await lockedProtocolState(trx);
      if (cutover.sends_paused) fail(503, 'inference_temporarily_paused');
    }
    // Chat deletion takes this same advisory lock before its durable fence is
    // written. Key-version-specific locks alone cannot serialize a new key.
    await lockIdentity(trx, `chat-recovery-delete:${chatId}`);
    if (await trx(CHAT_DELETION_FENCES).where({ id: chatId }).first()) {
      // A deleted UUID has the same not-found surface for every caller.
      fail(404, 'chat_not_found');
    }
    await lockIdentity(trx, `${ownerHash}:${chatId}:${keyVersion}`);
    let chat = await trx(CHATS).where({ id: chatId }).forUpdate().first();
    if (chat && (teamHash ? chat.hashed_team_id !== teamHash : chat.hashed_user_id !== ownerHash || chat.hashed_team_id)) fail(404, 'chat_not_found');
    if (chat?.storage_state === 'deleting') fail(404, 'chat_not_found');
    if (teamHash) await authorizedTeamWriter(trx, teamHash, ownerHash);
    const existing = await trx(PREFLIGHTS).where({ hashed_user_id: ownerHash, chat_id: chatId, turn_id: turnId }).forUpdate().first();
    if (existing) {
      if (!samePreflight(existing, values) || existing.deletion_invalidated_at
        || (chatMetadata && (!chat || !sameChatMetadata(chat, chatMetadata)))) fail(409, 'preflight_mismatch');
      return responseForPreflight(existing);
    }
    if (chat) {
      if (chatMetadata) {
        if (!isEmptyDraftShell(chat) || !canCompleteChatMetadata(chat, chatMetadata)) {
          fail(409, 'existing_chat_metadata_forbidden');
        }
        const metadataCompletion = missingChatMetadata(chat, chatMetadata);
        if (Object.keys(metadataCompletion).length > 0) {
          const scope = teamHash
            ? { id: chatId, hashed_team_id: teamHash, messages_v: 0 }
            : { id: chatId, hashed_user_id: ownerHash, messages_v: 0 };
          if (await trx(CHATS).where(scope).update(metadataCompletion) !== 1) fail(409, 'version_conflict');
          chat = { ...chat, ...metadataCompletion };
        }
      }
    } else {
      if (!chatMetadata) fail(404, 'new_chat_metadata_required');
      if (expectedVersion !== 0) fail(409, 'version_conflict');
      const timestamp = Math.floor(now.getTime() / 1000);
      chat = {
        id: chatId,
        hashed_user_id: ownerHash,
        hashed_team_id: teamHash,
        ...chatMetadata,
        messages_v: 0,
        title_v: 0,
        metadata_v: 0,
        last_edited_overall_timestamp: timestamp,
        last_message_timestamp: null,
        unread_count: 0,
        pinned: false,
        is_private: true,
        is_shared: false,
        share_with_community: false,
        share_pii: false,
        share_highlights: true,
      };
      await trx(CHATS).insert(chat);
      if (teamHash) {
        await trx(CHAT_KEY_WRAPPERS).insert({
          id: randomUUID(),
          hashed_chat_id: hashIdentifier(chatId),
          hashed_team_id: teamHash,
          key_type: 'team',
          team_key_epoch: 1,
          encrypted_chat_key: wrappedKey,
          wrapper_version: 1,
          created_at: timestamp,
        });
      }
    }
    const canonical = await trx(PREFLIGHTS).where({ hashed_user_id: ownerHash, chat_id: chatId, chat_key_version: keyVersion })
      .whereNull('deletion_invalidated_at').orderBy('prepared_at', 'asc').first();
    if (chat.encrypted_chat_key && chat.encrypted_chat_key !== wrappedKey) fail(409, 'immutable_chat_key_mismatch');
    if (canonical && canonical.wrapped_chat_key !== wrappedKey) fail(409, 'immutable_chat_key_mismatch');
    if (canonical && canonical.recovery_public_key !== recoveryKey) fail(409, 'recovery_key_mismatch');
    if (chat.messages_v !== expectedVersion) fail(409, 'version_conflict');
    if (await trx(MESSAGES).where({ client_message_id: userMessageId }).first()) fail(409, 'message_identity_conflict');
    await trx(MESSAGES).insert({ id: randomUUID(), ...message });
    const committedVersion = expectedVersion + 1;
    const timestamp = Math.floor(now.getTime() / 1000);
    const chatUpdateWhere = teamHash
      ? { id: chatId, hashed_team_id: teamHash, messages_v: expectedVersion }
      : { id: chatId, hashed_user_id: ownerHash, messages_v: expectedVersion };
    if (await trx(CHATS).where(chatUpdateWhere)
      .update({ messages_v: committedVersion, updated_at: timestamp, last_edited_overall_timestamp: timestamp }) !== 1) fail(409, 'version_conflict');
    const row = {
      id: randomUUID(), hashed_user_id: ownerHash, chat_id: chatId, turn_id: turnId, ...values,
      expected_messages_v: expectedVersion, committed_messages_v: committedVersion, state: 'PREPARED',
      prepared_at: now, expires_at: new Date(now.getTime() + PREFLIGHT_TTL_MS),
    };
    await trx(PREFLIGHTS).insert(row);
    return responseForPreflight(row);
  });
}

async function verifyCommittedTeamMessage(database, raw) {
  const body = operationBody(raw, 'verify_committed_team_message');
  const preflightId = uuid(body.preflight_id, 'invalid_preflight_id');
  const ownerHash = hexDigest(body.hashed_user_id, 'invalid_owner');
  const teamHash = hexDigest(body.hashed_team_id, 'invalid_team');
  const chatId = uuid(body.chat_id, 'invalid_chat_id');
  const messageId = string(body.user_message_id, 'invalid_message_id', 255);
  const ciphertextDigest = hexDigest(body.encrypted_content_digest, 'invalid_content_digest');
  return database.transaction(async (trx) => {
    const cutover = await lockedProtocolState(trx);
    if (cutover.sends_paused) fail(503, 'inference_temporarily_paused');
    const preflight = await trx(PREFLIGHTS).where({
      id: preflightId, hashed_user_id: ownerHash, chat_id: chatId, user_message_id: messageId,
    }).first();
    if (!preflight || preflight.deletion_invalidated_at) fail(404, 'preflight_not_found');
    const chat = await trx(CHATS).where({ id: chatId, hashed_team_id: teamHash }).first();
    if (!chat) fail(404, 'chat_not_found');
    const message = await trx(MESSAGES).where({
      chat_id: chatId, client_message_id: messageId, hashed_user_id: ownerHash, role: 'user',
    }).first();
    if (!message || digest(message.encrypted_content) !== ciphertextDigest) fail(409, 'message_identity_mismatch');
    return { committed: true };
  });
}

async function enqueueInference(database, raw, now) {
  const body = operationBody(raw, 'enqueue_inference');
  const preflightId = uuid(body.preflight_id, 'invalid_preflight_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  const deviceHash = string(body.device_hash, 'invalid_device', 128);
  const commitment = hexDigest(body.inference_commitment, 'invalid_inference_commitment');
  const taskId = uuid(body.inference_task_id, 'invalid_task_id');
  const billingId = uuid(body.billing_identity, 'invalid_billing_identity');
  const outboxId = uuid(body.outbox_id, 'invalid_outbox_id');
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, ownerHash);
    const row = await trx(PREFLIGHTS).where({ id: preflightId }).forUpdate().first();
    if (!row || row.hashed_user_id !== ownerHash || row.device_hash !== deviceHash) fail(404, 'preflight_not_found');
    if (row.deletion_invalidated_at) fail(409, 'preflight_invalidated');
    await authorizedOutputChat(trx, row.chat_id, ownerHash);
    if (row.inference_commitment !== commitment) fail(409, 'preflight_mismatch');
    if (['ENQUEUED', 'RUNNING', 'FAILED', 'TERMINAL'].includes(row.state)) {
      if (row.inference_task_id !== taskId || row.billing_identity !== billingId || row.outbox_id !== outboxId) fail(409, 'enqueue_identity_mismatch');
      return responseForPreflight(row);
    }
    if (row.state !== 'PREPARED') fail(409, 'invalid_preflight_state');
    if (new Date(row.expires_at) <= now) fail(410, 'preflight_expired');
    await trx(OUTBOX).insert({
      id: outboxId, event_key: `chat-turn:${row.turn_id}`, preflight_id: row.id,
      hashed_user_id: ownerHash, chat_id: row.chat_id, turn_id: row.turn_id,
      inference_task_id: taskId, billing_identity: billingId, state: 'PENDING', attempts: 0, created_at: now,
    });
    await trx(PREFLIGHTS).where({ id: row.id, state: 'PREPARED' }).update({
      state: 'ENQUEUED', inference_task_id: taskId, billing_identity: billingId,
      outbox_id: outboxId, enqueued_at: now,
    });
    return responseForPreflight({ ...row, state: 'ENQUEUED', inference_task_id: taskId, billing_identity: billingId, outbox_id: outboxId });
  });
}

async function claimInference(database, raw, now) {
  const body = operationBody(raw, 'claim_inference');
  const taskId = uuid(body.inference_task_id, 'invalid_task_id');
  return database.transaction(async (trx) => {
    const row = await trx(PREFLIGHTS).where({ inference_task_id: taskId }).forUpdate().first();
    if (!row || row.deletion_invalidated_at) fail(404, 'inference_task_not_found');
    if (!inferenceClaimDecision(row.state)) {
      return {
        inference_task_id: taskId,
        claimed: false,
        state: row.state,
        ...(row.state === 'FAILED' ? { failure_category: row.failure_category } : {}),
      };
    }
    if (new Date(row.expires_at) <= now) {
      await trx(PREFLIGHTS).where({ id: row.id, state: 'ENQUEUED' }).update({
        state: 'FAILED', failed_at: now, failure_category: 'claim_expired',
        failure_alert_pending_at: now,
      });
      await trx(OUTBOX).where({ id: row.outbox_id }).update({ state: 'FAILED', last_error_category: 'claim_expired' });
      return {
        inference_task_id: taskId,
        claimed: false,
        state: 'FAILED',
        failure_category: 'claim_expired',
      };
    }
    const updated = await trx(PREFLIGHTS).where({ id: row.id, state: 'ENQUEUED' }).update({ state: 'RUNNING', running_at: now });
    if (updated !== 1) fail(409, 'inference_claim_conflict');
    return {
      inference_task_id: taskId,
      claimed: true,
      state: 'RUNNING',
      preflight_id: row.id,
      hashed_user_id: row.hashed_user_id,
      chat_id: row.chat_id,
      turn_id: row.turn_id,
      billing_identity: row.billing_identity,
      outbox_id: row.outbox_id,
    };
  });
}

async function markOutboxDispatched(database, raw, now) {
  const body = operationBody(raw, 'mark_outbox_dispatched');
  const outboxId = uuid(body.outbox_id, 'invalid_outbox_id');
  const taskId = uuid(body.inference_task_id, 'invalid_task_id');
  return database.transaction(async (trx) => {
    const row = await trx(OUTBOX).where({ id: outboxId }).forUpdate().first();
    if (!row || row.inference_task_id !== taskId) fail(404, 'outbox_not_found');
    if (['DISPATCHED', 'FAILED'].includes(row.state)) {
      return { outbox_id: row.id, inference_task_id: taskId, dispatched: false, state: row.state };
    }
    if (row.state !== 'PENDING') fail(409, 'invalid_outbox_state');
    const updated = await trx(OUTBOX).where({ id: row.id, state: 'PENDING' }).update({
      state: 'DISPATCHED', published_at: now, attempts: trx.raw('attempts + 1'),
    });
    if (updated !== 1) fail(409, 'outbox_dispatch_conflict');
    return { outbox_id: row.id, inference_task_id: taskId, dispatched: true, state: 'DISPATCHED' };
  });
}

async function markInferenceFailed(database, raw, now) {
  const body = operationBody(raw, 'mark_inference_failed');
  const taskId = uuid(body.inference_task_id, 'invalid_task_id');
  const category = string(body.failure_category, 'invalid_failure_category', 64);
  if (!/^[a-z0-9][a-z0-9_:-]*$/.test(category)) fail(400, 'invalid_failure_category');
  return database.transaction(async (trx) => {
    const row = await trx(PREFLIGHTS).where({ inference_task_id: taskId }).forUpdate().first();
    if (!row || row.deletion_invalidated_at) fail(404, 'inference_task_not_found');
    const sealedJob = await trx(JOBS).where({ inference_task_id: taskId }).first();
    if (sealedJob) {
      return {
        inference_task_id: taskId,
        failed: false,
        state: row.state,
        sealed_job_id: sealedJob.id,
      };
    }
    if (row.state === 'FAILED') {
      if (row.failure_category !== category) fail(409, 'failure_category_mismatch');
      return { inference_task_id: taskId, failed: false, state: 'FAILED' };
    }
    if (row.state === 'TERMINAL') return { inference_task_id: taskId, failed: false, state: 'TERMINAL' };
    if (!['ENQUEUED', 'RUNNING'].includes(row.state)) fail(409, 'invalid_inference_state');
    const previousState = row.state;
    const updated = await trx(PREFLIGHTS).where({ id: row.id, state: previousState }).update({
      state: 'FAILED', failed_at: now, failure_category: category,
      failure_alert_pending_at: EXPECTED_FAILURE_CATEGORIES.has(category) ? null : now,
    });
    if (updated !== 1) fail(409, 'inference_failure_conflict');
    await trx(OUTBOX).where({ id: row.outbox_id }).update({ state: 'FAILED', last_error_category: category });
    return { inference_task_id: taskId, failed: true, state: 'FAILED' };
  });
}

async function createSealedJob(database, raw, now) {
  const body = operationBody(raw, 'create_sealed_job');
  const identity = {
    hashed_user_id: string(body.hashed_user_id, 'invalid_owner', 64), chat_id: uuid(body.chat_id, 'invalid_chat_id'),
    turn_id: uuid(body.turn_id, 'invalid_turn_id'), preflight_id: uuid(body.preflight_id, 'invalid_preflight_id'),
    inference_task_id: uuid(body.inference_task_id, 'invalid_task_id'),
    assistant_message_id: string(body.assistant_message_id, 'invalid_message_id', 255),
    chat_key_version: integer(body.chat_key_version, 'invalid_key_version'),
  };
  const jobId = uuid(body.job_id, 'invalid_job_id');
  const sealedPayload = validateEnvelope(body.sealed_payload);
  const sealedPayloadDigest = digest(sealedPayload);
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, identity.hashed_user_id);
    await lockRecoveryChats(trx, identity.chat_id);
    const existing = await trx(JOBS).where({ id: jobId }).forUpdate().first();
    if (existing) {
      if (Object.entries(identity).some(([key, value]) => existing[key] !== value)
        || (existing.state !== 'TERMINAL' && existing.sealed_payload_digest !== sealedPayloadDigest)) fail(409, 'sealed_job_mismatch');
      await authorizedOutputChat(trx, existing.chat_id, identity.hashed_user_id);
      return { job_id: existing.id, state: existing.state, expires_at: existing.expires_at };
    }
    const preflight = await trx(PREFLIGHTS).where({ id: identity.preflight_id }).forUpdate().first();
    if (!preflight || preflight.state !== 'RUNNING' || preflight.deletion_invalidated_at
      || preflight.hashed_user_id !== identity.hashed_user_id || preflight.chat_id !== identity.chat_id
      || preflight.turn_id !== identity.turn_id || preflight.inference_task_id !== identity.inference_task_id
      || preflight.chat_key_version !== identity.chat_key_version) fail(409, 'inference_not_running');
    await authorizedOutputChat(trx, identity.chat_id, identity.hashed_user_id);
    const row = {
      id: jobId, ...identity, sealed_payload: sealedPayload, sealed_payload_digest: sealedPayloadDigest,
      state: 'AVAILABLE', lease_generation: 0, created_at: now,
      expires_at: new Date(now.getTime() + JOB_TTL_MS),
    };
    await trx(JOBS).insert(row);
    return { job_id: row.id, state: row.state, expires_at: row.expires_at };
  });
}

function producerTaskName(value) {
  const name = string(value, 'invalid_producer_task_name', 160);
  if (!/^[a-zA-Z0-9_.-]+$/.test(name)) fail(400, 'invalid_producer_task_name');
  return name;
}

function producerContext(intent) {
  return {
    hashed_user_id: intent.hashed_user_id, hashed_team_id: intent.hashed_team_id || null,
    root_chat_id: intent.root_chat_id, target_chat_id: intent.target_chat_id,
    turn_id: intent.turn_id, preflight_id: intent.preflight_id,
    inference_task_id: intent.inference_task_id, chat_key_version: intent.chat_key_version,
    recovery_public_key: intent.recovery_public_key,
    primary_embed_id: intent.primary_embed_id,
    primary_message_id: intent.primary_message_id,
  };
}

async function checkedProducerAuthority(trx, intent, allowTerminal = true) {
  await requireUnfencedRecoveryAccount(trx, intent.hashed_user_id);
  if (await trx(CHAT_DELETION_FENCES).whereIn('id',
    [...new Set([intent.root_chat_id, intent.target_chat_id])]).first()) fail(409, 'producer_chat_deleted');
  const preflight = await trx(PREFLIGHTS).where({ id: intent.preflight_id }).forUpdate().first();
  if (!preflight || preflight.deletion_invalidated_at
    || !(['RUNNING', ...(allowTerminal ? ['TERMINAL'] : [])].includes(preflight.state))
    || preflight.hashed_user_id !== intent.hashed_user_id
    || preflight.chat_id !== intent.root_chat_id || preflight.turn_id !== intent.turn_id
    || preflight.chat_key_version !== intent.chat_key_version
    || preflight.recovery_public_key !== intent.recovery_public_key) fail(409, 'producer_preflight_invalid');
  const rootChat = await authorizedOutputChat(trx, intent.root_chat_id, intent.hashed_user_id);
  const targetChat = await authorizedOutputChat(trx, intent.target_chat_id, intent.hashed_user_id);
  if ((rootChat.hashed_team_id || null) !== (intent.hashed_team_id || null)
    || (targetChat.hashed_team_id || null) !== (rootChat.hashed_team_id || null)) {
    fail(409, 'producer_team_scope_changed');
  }
  if (intent.target_chat_id !== intent.root_chat_id) {
    const child = await trx(ORCHESTRATION_CHILDREN)
      .where({ child_chat_id: intent.target_chat_id }).first();
    const root = child && await trx(ORCHESTRATIONS).where({ id: child.orchestration_id }).first();
    if (!root || root.root_chat_id !== intent.root_chat_id
      || root.hashed_user_id !== intent.hashed_user_id
      || child.inference_task_id !== intent.inference_task_id
      || child.user_message_id !== intent.primary_message_id) fail(409, 'producer_child_identity_mismatch');
  } else if (preflight.inference_task_id !== intent.inference_task_id) {
    fail(409, 'producer_inference_task_mismatch');
  } else if (preflight.user_message_id !== intent.primary_message_id) {
    fail(409, 'producer_message_mismatch');
  }
  return { preflight, rootChat, targetChat };
}

async function registeredProducer(trx, id, taskName, binding, allowCompleted = false) {
  const snapshot = await trx(OUTPUT_PRODUCERS).where({ id }).first();
  if (!snapshot || snapshot.task_name !== taskName || snapshot.kwargs_binding !== binding) {
    fail(404, 'producer_intent_not_found');
  }
  await requireUnfencedRecoveryAccount(trx, snapshot.hashed_user_id);
  await lockRecoveryChats(trx, snapshot.root_chat_id, snapshot.target_chat_id);
  const row = await trx(OUTPUT_PRODUCERS).where({ id }).forUpdate().first();
  if (!row || row.task_name !== taskName || row.kwargs_binding !== binding) {
    fail(404, 'producer_intent_not_found');
  }
  if (row.state !== 'PENDING' && !(allowCompleted && row.state === 'COMPLETED')) {
    fail(409, 'producer_intent_invalidated');
  }
  return row;
}
async function verifyVolatileOutputActor(database, raw) {
  const body = operationBody(raw, 'verify_volatile_output_actor');
  const actorId = uuid(body.actor_user_id, 'invalid_actor_id');
  const ownerHash = hexDigest(body.hashed_user_id, 'invalid_owner');
  const chatId = body.target_chat_id == null ? null
    : uuid(body.target_chat_id, 'invalid_target_chat_id');
  const teamHash = body.hashed_team_id == null ? null
    : hexDigest(body.hashed_team_id, 'invalid_team');
  if (hashIdentifier(actorId) !== ownerHash) fail(404, 'volatile_actor_not_found');
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, ownerHash);
    await lockRecoveryChats(trx, chatId);
    const actor = await trx('directus_users').where({ id: actorId }).first();
    if (!actor || actor.status !== 'active') fail(404, 'volatile_actor_not_found');
    if (chatId) {
      if (await trx(CHAT_DELETION_FENCES).where({ id: chatId }).first()) {
        fail(409, 'producer_chat_deleted');
      }
      const chat = await authorizedOutputChat(trx, chatId, ownerHash);
      if ((chat.hashed_team_id || null) !== teamHash) fail(404, 'chat_not_found');
    } else if (teamHash) {
      await authorizedTeamWriter(trx, teamHash, ownerHash);
    }
    return { authorized: true };
  });
}

async function producerSubject(trx, intent, ordinal) {
  if (ordinal === 0) return {
    subject_id: intent.primary_embed_id, output_kind: intent.primary_output_kind,
    output_version: intent.primary_output_version,
  };
  if (ordinal < 1 || ordinal > intent.max_children) fail(400, 'invalid_producer_ordinal');
  const child = await trx(OUTPUT_PRODUCER_CHILDREN)
    .where({ producer_intent_id: intent.id, ordinal }).first();
  if (!child) fail(409, 'producer_child_not_registered');
  return child;
}

async function registerOutputProducer(database, raw, now) {
  const body = operationBody(raw, 'register_output_producer');
  const intent = {
    id: uuid(body.task_uuid, 'invalid_task_id'),
    task_name: producerTaskName(body.task_name),
    kwargs_binding: hexDigest(body.kwargs_binding, 'invalid_producer_binding'),
    hashed_user_id: hexDigest(body.hashed_user_id, 'invalid_owner'),
    root_chat_id: uuid(body.root_chat_id, 'invalid_root_chat_id'),
    target_chat_id: uuid(body.target_chat_id, 'invalid_target_chat_id'),
    turn_id: uuid(body.turn_id, 'invalid_turn_id'),
    preflight_id: uuid(body.preflight_id, 'invalid_preflight_id'),
    inference_task_id: uuid(body.inference_task_id, 'invalid_task_id'),
    chat_key_version: integer(body.chat_key_version, 'invalid_key_version'),
    primary_embed_id: uuid(body.primary_embed_id, 'invalid_embed_id'),
    primary_message_id: string(body.primary_message_id, 'invalid_message_id', 255),
    primary_output_kind: string(body.primary_output_kind, 'invalid_output_kind', 24),
    primary_output_version: integer(body.primary_output_version, 'invalid_output_version'),
    max_children: integer(body.max_children, 'invalid_max_children'),
  };
  if (!PRODUCER_OUTPUT_KINDS.has(intent.primary_output_kind)
    || intent.primary_output_version < 1 || intent.chat_key_version < 1
    || intent.max_children < 0 || intent.max_children > MAX_PRODUCER_CHILDREN) {
    fail(400, 'invalid_producer_identity');
  }
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, intent.hashed_user_id);
    await lockRecoveryChats(trx, intent.root_chat_id, intent.target_chat_id);
    await lockIdentity(trx, `output-producer-task:${intent.id}`);
    if (await trx(AUTHORIZED_RERENDERS).where({ id: intent.id }).first()) {
      fail(409, 'producer_task_identity_conflict');
    }
    if (await trx(AUTHORIZED_DIRECT_SKILLS).where({ id: intent.id }).first()) {
      fail(409, 'producer_task_identity_conflict');
    }
    if (await trx(LEGACY_OUTPUT_PRODUCERS).where({ id: intent.id }).first()) {
      fail(409, 'producer_task_identity_conflict');
    }
    const existing = await trx(OUTPUT_PRODUCERS).where({ id: intent.id }).forUpdate().first();
    if (existing) {
      if (Object.entries(intent).some(([key, value]) => existing[key] !== value)) {
        fail(409, 'producer_intent_mismatch');
      }
      if (existing.state !== 'PENDING') fail(409, 'producer_intent_invalidated');
      await checkedProducerAuthority(trx, existing);
      return { producer_intent_id: intent.id, status: 'PENDING', idempotent: true };
    }
    const preflight = await trx(PREFLIGHTS).where({ id: intent.preflight_id }).forUpdate().first();
    if (!preflight || preflight.state !== 'RUNNING' || preflight.deletion_invalidated_at
      || preflight.hashed_user_id !== intent.hashed_user_id
      || preflight.chat_id !== intent.root_chat_id || preflight.turn_id !== intent.turn_id
      || preflight.chat_key_version !== intent.chat_key_version) fail(409, 'producer_preflight_invalid');
    intent.recovery_public_key = preflight.recovery_public_key;
    const rootChat = await authorizedOutputChat(trx, intent.root_chat_id, intent.hashed_user_id);
    intent.hashed_team_id = rootChat.hashed_team_id || null;
    await checkedProducerAuthority(trx, intent, false);
    await trx(OUTPUT_PRODUCERS).insert({ ...intent, state: 'PENDING', registered_at: now });
    return { producer_intent_id: intent.id, status: 'PENDING', idempotent: false };
  });
}

async function checkedLegacyProducerAuthority(trx, intent, now) {
  await requireUnfencedRecoveryAccount(trx, intent.hashed_user_id);
  if (new Date(intent.expires_at) <= now) fail(410, 'legacy_producer_expired');
  if (await trx(CHAT_DELETION_FENCES).whereIn('id',
    [...new Set([intent.root_chat_id, intent.target_chat_id])]).first()) {
    fail(409, 'producer_chat_deleted');
  }
  const actor = await trx('directus_users').where({ id: intent.actor_user_id }).first();
  if (!actor || actor.status !== 'active'
    || hashIdentifier(intent.actor_user_id) !== intent.hashed_user_id) {
    fail(404, 'legacy_producer_actor_not_found');
  }
  const rootChat = await authorizedOutputChat(trx, intent.root_chat_id, intent.hashed_user_id);
  const targetChat = await authorizedOutputChat(trx, intent.target_chat_id, intent.hashed_user_id);
  if ((rootChat.hashed_team_id || null) !== (intent.hashed_team_id || null)
    || (targetChat.hashed_team_id || null) !== (rootChat.hashed_team_id || null)) {
    fail(409, 'producer_team_scope_changed');
  }
}

async function registerLegacyOutputProducer(database, raw, now) {
  const body = operationBody(raw, 'register_legacy_output_producer');
  const intent = {
    id: uuid(body.task_uuid, 'invalid_task_id'),
    task_name: producerTaskName(body.task_name),
    kwargs_binding: hexDigest(body.kwargs_binding, 'invalid_producer_binding'),
    actor_user_id: uuid(body.actor_user_id, 'invalid_actor_id'),
    hashed_user_id: hexDigest(body.hashed_user_id, 'invalid_owner'),
    legacy_task_identity: hexDigest(body.legacy_task_identity, 'invalid_legacy_task_identity'),
    root_chat_id: uuid(body.root_chat_id, 'invalid_root_chat_id'),
    target_chat_id: uuid(body.target_chat_id, 'invalid_target_chat_id'),
    root_turn_id: body.root_turn_id == null ? null
      : uuid(body.root_turn_id, 'invalid_turn_id'),
    root_user_message_id: string(body.root_user_message_id, 'invalid_message_id', 255),
    primary_message_id: string(body.primary_message_id, 'invalid_message_id', 255),
    primary_embed_id: uuid(body.primary_embed_id, 'invalid_embed_id'),
  };
  const derivedIdentity = createHash('sha256').update(
    `${intent.actor_user_id}:${intent.root_chat_id}:${intent.root_user_message_id}`,
  ).digest('hex');
  if (intent.hashed_user_id !== hashIdentifier(intent.actor_user_id)
    || intent.legacy_task_identity !== derivedIdentity) fail(409, 'legacy_producer_identity_mismatch');
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, intent.hashed_user_id);
    await lockRecoveryChats(trx, intent.root_chat_id, intent.target_chat_id);
    await lockIdentity(trx, `output-producer-task:${intent.id}`);
    for (const table of [OUTPUT_PRODUCERS, AUTHORIZED_DIRECT_SKILLS, AUTHORIZED_RERENDERS]) {
      if (await trx(table).where({ id: intent.id }).first()) fail(409, 'producer_task_identity_conflict');
    }
    const existing = await trx(LEGACY_OUTPUT_PRODUCERS).where({ id: intent.id }).forUpdate().first();
    if (existing) {
      if (Object.entries(intent).some(([key, value]) => existing[key] !== value)) {
        fail(409, 'legacy_producer_intent_mismatch');
      }
      if (existing.state !== 'PENDING') fail(409, 'legacy_producer_already_claimed');
      await checkedLegacyProducerAuthority(trx, existing, now);
      return { producer_intent_id: intent.id, status: 'LEGACY_AUTHORIZED', idempotent: true };
    }
    const protocol = await lockedProtocolState(trx);
    const lifecycle = protocol.legacy_task_lifecycle.find(
      (item) => item.task_identity === intent.legacy_task_identity,
    );
    if (protocol.protocol_epoch !== 0 || !lifecycle || lifecycle.state !== 'RUNNING'
      || new Date(lifecycle.expires_at) <= now
      || !protocol.active_legacy_tasks.includes(intent.legacy_task_identity)) {
      fail(409, 'legacy_admission_not_running');
    }
    const rootChat = await authorizedOutputChat(trx, intent.root_chat_id, intent.hashed_user_id);
    intent.hashed_team_id = rootChat.hashed_team_id || null;
    const admission = lifecycle.admission;
    if (admission) {
      const execution = await trx(LEGACY_BATCH_CLAIMS)
        .where({ task_identity: intent.legacy_task_identity }).forUpdate().first();
      if (admission.actor_user_id !== intent.actor_user_id
        || admission.hashed_user_id !== intent.hashed_user_id
        || admission.chat_id !== intent.root_chat_id
        || admission.first_message_id !== intent.root_user_message_id
        || admission.hashed_team_id !== intent.hashed_team_id
        || !execution || execution.state !== 'CLAIMED'
        || (admission.batch_message_ids && !admission.execution_claimed)) {
        fail(409, 'legacy_producer_admission_mismatch');
      }
    } else {
      // Older plain admission has no authenticated actor/chat metadata. It can
      // authorize a producer only after the canonical user message is visible.
      const rootMessage = await trx(MESSAGES).where({
        client_message_id: intent.root_user_message_id,
        chat_id: intent.root_chat_id, hashed_user_id: intent.hashed_user_id,
        role: 'user',
      }).first();
      if (!rootMessage) fail(409, 'legacy_root_message_missing');
    }
    if (intent.target_chat_id === intent.root_chat_id) {
      if (intent.primary_message_id !== intent.root_user_message_id) {
        fail(409, 'legacy_producer_message_mismatch');
      }
    } else {
      if (!intent.root_turn_id) fail(409, 'legacy_child_identity_mismatch');
      const child = await trx(ORCHESTRATION_CHILDREN).where({
        child_chat_id: intent.target_chat_id,
        user_message_id: intent.primary_message_id,
      }).first();
      const root = child && await trx(ORCHESTRATIONS).where({ id: child.orchestration_id }).first();
      if (!root || root.root_chat_id !== intent.root_chat_id
        || root.root_turn_id !== intent.root_turn_id
        || root.hashed_user_id !== intent.hashed_user_id
        || (root.hashed_team_id || null) !== intent.hashed_team_id) {
        fail(409, 'legacy_child_identity_mismatch');
      }
    }
    intent.expires_at = new Date(now.getTime() + JOB_TTL_MS);
    await checkedLegacyProducerAuthority(trx, intent, now);
    await trx(LEGACY_OUTPUT_PRODUCERS).insert({ ...intent, state: 'PENDING', registered_at: now });
    return { producer_intent_id: intent.id, status: 'LEGACY_AUTHORIZED', idempotent: false };
  });
}

async function checkedRerenderAuthority(trx, intent) {
  await requireUnfencedRecoveryAccount(trx, intent.hashed_user_id);
  if (await trx(CHAT_DELETION_FENCES).where({ id: intent.target_chat_id }).first()) {
    fail(409, 'producer_chat_deleted');
  }
  const chat = await authorizedOutputChat(trx, intent.target_chat_id, intent.hashed_user_id);
  if ((chat.hashed_team_id || null) !== (intent.hashed_team_id || null)) {
    fail(409, 'producer_team_scope_changed');
  }
  const embed = await trx(EMBEDS).where({ embed_id: intent.primary_embed_id }).first();
  if (!embed || embed.hashed_user_id !== intent.hashed_user_id
    || embed.hashed_chat_id !== hashIdentifier(intent.target_chat_id)
    || Number(embed.version_number || 1) !== intent.expected_embed_version
    || !embed.encrypted_content
    || (intent.primary_message_id && embed.hashed_message_id
      && embed.hashed_message_id !== hashIdentifier(intent.primary_message_id))) {
    fail(409, 'producer_embed_head_changed');
  }
  return chat;
}

async function registerAuthorizedRerender(database, raw, now) {
  const body = operationBody(raw, 'register_authorized_rerender');
  const intent = {
    id: uuid(body.task_uuid, 'invalid_task_id'),
    task_name: producerTaskName(body.task_name),
    kwargs_binding: hexDigest(body.kwargs_binding, 'invalid_producer_binding'),
    hashed_user_id: hexDigest(body.hashed_user_id, 'invalid_owner'),
    target_chat_id: uuid(body.target_chat_id, 'invalid_target_chat_id'),
    primary_embed_id: uuid(body.primary_embed_id, 'invalid_embed_id'),
    primary_message_id: body.primary_message_id == null
      ? null : string(body.primary_message_id, 'invalid_message_id', 255),
    source_version: integer(body.source_version, 'invalid_source_version'),
    expected_embed_version: integer(body.expected_embed_version, 'invalid_embed_version'),
  };
  if (intent.task_name !== 'apps.videos.tasks.render_remotion'
    || intent.source_version < 1 || intent.expected_embed_version < 1) {
    fail(400, 'invalid_rerender_identity');
  }
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, intent.hashed_user_id);
    await lockRecoveryChats(trx, intent.target_chat_id);
    await lockIdentity(trx, `output-producer-task:${intent.id}`);
    if (await trx(OUTPUT_PRODUCERS).where({ id: intent.id }).first()) {
      fail(409, 'producer_task_identity_conflict');
    }
    if (await trx(AUTHORIZED_DIRECT_SKILLS).where({ id: intent.id }).first()) {
      fail(409, 'producer_task_identity_conflict');
    }
    if (await trx(LEGACY_OUTPUT_PRODUCERS).where({ id: intent.id }).first()) {
      fail(409, 'producer_task_identity_conflict');
    }
    const existing = await trx(AUTHORIZED_RERENDERS).where({ id: intent.id }).forUpdate().first();
    if (existing) {
      if (Object.entries(intent).some(([key, value]) => existing[key] !== value)) {
        fail(409, 'rerender_intent_mismatch');
      }
      if (existing.state !== 'PENDING') fail(409, 'rerender_intent_invalidated');
      await checkedRerenderAuthority(trx, existing);
      return { producer_intent_id: intent.id, status: 'DIRECT_AUTHORIZED', idempotent: true };
    }
    const chat = await authorizedOutputChat(trx, intent.target_chat_id, intent.hashed_user_id);
    intent.hashed_team_id = chat.hashed_team_id || null;
    await checkedRerenderAuthority(trx, intent);
    await lockIdentity(trx, `direct-embed:${intent.hashed_user_id}:${intent.primary_embed_id}:${intent.target_chat_id}`);
    const competing = await trx(AUTHORIZED_RERENDERS).where({
      hashed_user_id: intent.hashed_user_id, primary_embed_id: intent.primary_embed_id,
      target_chat_id: intent.target_chat_id,
      expected_embed_version: intent.expected_embed_version,
    }).whereIn('state', ['PENDING', 'RUNNING']).first();
    if (competing) fail(409, 'producer_embed_intent_conflict');
    await trx(AUTHORIZED_RERENDERS).insert({ ...intent, state: 'PENDING', registered_at: now });
    return { producer_intent_id: intent.id, status: 'DIRECT_AUTHORIZED', idempotent: false };
  });
}

async function checkedDirectSkillAuthority(trx, intent) {
  await requireUnfencedRecoveryAccount(trx, intent.hashed_user_id);
  const actor = await trx('directus_users').where({ id: intent.actor_user_id }).first();
  if (!actor || actor.status !== 'active'
    || hashIdentifier(intent.actor_user_id) !== intent.hashed_user_id) {
    fail(404, 'direct_skill_actor_not_found');
  }
  if (!intent.target_chat_id) {
    if (intent.hashed_team_id) {
      await authorizedTeamWriter(trx, intent.hashed_team_id, intent.hashed_user_id);
    }
    return;
  }
  if (await trx(CHAT_DELETION_FENCES).where({ id: intent.target_chat_id }).first()) {
    fail(409, 'producer_chat_deleted');
  }
  const chat = await authorizedOutputChat(trx, intent.target_chat_id, intent.hashed_user_id);
  if ((chat.hashed_team_id || null) !== (intent.hashed_team_id || null)) {
    fail(409, 'producer_team_scope_changed');
  }
}

async function registerAuthorizedDirectSkill(database, raw, now) {
  const body = operationBody(raw, 'register_authorized_direct_skill');
  const intent = {
    id: uuid(body.task_uuid, 'invalid_task_id'),
    task_name: producerTaskName(body.task_name),
    kwargs_binding: hexDigest(body.kwargs_binding, 'invalid_producer_binding'),
    actor_user_id: uuid(body.actor_user_id, 'invalid_actor_id'),
    hashed_user_id: hexDigest(body.hashed_user_id, 'invalid_owner'),
    hashed_team_id: body.hashed_team_id == null ? null
      : hexDigest(body.hashed_team_id, 'invalid_team'),
    target_chat_id: body.target_chat_id == null ? null
      : uuid(body.target_chat_id, 'invalid_target_chat_id'),
    primary_message_id: body.primary_message_id == null ? null
      : string(body.primary_message_id, 'invalid_message_id', 255),
    primary_embed_id: uuid(body.primary_embed_id, 'invalid_embed_id'),
  };
  if (!/^apps\.[a-z0-9_]+\.tasks\.[a-z0-9_-]+$/.test(intent.task_name)
    || (!intent.target_chat_id && intent.primary_message_id)) {
    fail(400, 'invalid_direct_skill_identity');
  }
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, intent.hashed_user_id);
    await lockRecoveryChats(trx, intent.target_chat_id);
    await lockIdentity(trx, `output-producer-task:${intent.id}`);
    if (await trx(OUTPUT_PRODUCERS).where({ id: intent.id }).first()
      || await trx(AUTHORIZED_RERENDERS).where({ id: intent.id }).first()
      || await trx(LEGACY_OUTPUT_PRODUCERS).where({ id: intent.id }).first()) {
      fail(409, 'producer_task_identity_conflict');
    }
    const existing = await trx(AUTHORIZED_DIRECT_SKILLS).where({ id: intent.id }).forUpdate().first();
    if (existing && Object.entries(intent).some(([key, value]) => existing[key] !== value)) {
      fail(409, 'direct_skill_intent_mismatch');
    }
    await checkedDirectSkillAuthority(trx, intent);
    if (existing) {
      if (existing.state !== 'PENDING') fail(409, 'direct_skill_intent_invalidated');
      return { producer_intent_id: intent.id, status: 'DIRECT_AUTHORIZED', idempotent: true };
    }
    await lockIdentity(trx, `direct-embed:${intent.hashed_user_id}:${intent.primary_embed_id}:${intent.target_chat_id || ''}`);
    const competing = await trx(AUTHORIZED_DIRECT_SKILLS).where({
      hashed_user_id: intent.hashed_user_id, primary_embed_id: intent.primary_embed_id,
      target_chat_id: intent.target_chat_id,
    }).whereIn('state', ['PENDING', 'RUNNING']).first();
    if (competing) fail(409, 'producer_embed_intent_conflict');
    if (await trx(EMBEDS).where({ embed_id: intent.primary_embed_id }).first()) {
      fail(409, 'direct_skill_embed_already_exists');
    }
    await trx(AUTHORIZED_DIRECT_SKILLS).insert({ ...intent, state: 'PENDING', registered_at: now });
    return { producer_intent_id: intent.id, status: 'DIRECT_AUTHORIZED', idempotent: false };
  });
}

async function standaloneAssetProof(trx, intent) {
  if (intent.target_chat_id || intent.primary_message_id) return null;
  const asset = await trx('upload_files').where({
    embed_id: intent.primary_embed_id, user_id: intent.actor_user_id,
  }).first();
  const variants = asset && asset.files_metadata && typeof asset.files_metadata === 'object'
    ? Object.values(asset.files_metadata) : [];
  const variantsAreDurable = variants.length > 0 && variants.every((variant) => (
    variant && typeof variant === 'object'
    && typeof variant.s3_key === 'string' && variant.s3_key.length > 0
    && Number.isInteger(Number(variant.size_bytes)) && Number(variant.size_bytes) > 0
    && [undefined, null, '', 'aes-gcm-nonce-prefixed-v1', 'chunked-aes-256-gcm-v1']
      .includes(variant.encryption)
  ));
  const hasEncryptionProof = Boolean(
    asset && typeof asset.vault_wrapped_aes_key === 'string'
    && asset.vault_wrapped_aes_key.length > 0
    && (typeof asset.aes_nonce === 'string' && asset.aes_nonce.length > 0
      || variants.every((variant) => typeof variant.encryption === 'string'
        && variant.encryption.length > 0))
  );
  return asset && typeof asset.content_hash === 'string'
    && /^[0-9a-f]{64}$/.test(asset.content_hash)
    && Number.isInteger(Number(asset.file_size_bytes)) && Number(asset.file_size_bytes) > 0
    && variantsAreDurable && hasEncryptionProof ? asset : null;
}

async function completeAuthorizedDirectSkill(database, raw, now) {
  const body = operationBody(raw, 'complete_authorized_direct_skill');
  const id = uuid(body.task_uuid, 'invalid_task_id');
  const name = producerTaskName(body.task_name);
  const binding = hexDigest(body.kwargs_binding, 'invalid_producer_binding');
  const completion = string(body.completion, 'invalid_completion', 16);
  if (!['published', 'failed'].includes(completion)) fail(400, 'invalid_completion');
  const state = completion === 'published' ? 'COMPLETED' : 'FAILED';
  return database.transaction(async (trx) => {
    const snapshot = await trx(AUTHORIZED_DIRECT_SKILLS).where({ id }).first();
    if (snapshot) {
      await requireUnfencedRecoveryAccount(trx, snapshot.hashed_user_id);
      await lockRecoveryChats(trx, snapshot.target_chat_id);
    }
    const intent = await trx(AUTHORIZED_DIRECT_SKILLS).where({ id }).forUpdate().first();
    if (!intent || intent.task_name !== name || intent.kwargs_binding !== binding) {
      fail(404, 'producer_intent_not_found');
    }
    if (intent.state === state) return { producer_intent_id: id, status: state, idempotent: true };
    if (intent.state !== 'RUNNING') fail(409, 'direct_skill_intent_invalidated');
    await checkedDirectSkillAuthority(trx, intent);
    if (state === 'COMPLETED') {
      const embed = await trx(EMBEDS).where({
        embed_id: intent.primary_embed_id, hashed_user_id: intent.hashed_user_id,
      }).first();
      if (!embed || !embed.encrypted_content
        || (intent.target_chat_id && embed.hashed_chat_id !== hashIdentifier(intent.target_chat_id))) {
        fail(409, 'direct_skill_canonical_embed_missing');
      }
      const keySubject = embed.parent_embed_id || intent.primary_embed_id;
      const wrappers = await trx(EMBED_KEYS).where({
        hashed_embed_id: hashIdentifier(keySubject), hashed_user_id: intent.hashed_user_id,
      }).select(['key_type', 'hashed_chat_id', 'hashed_team_id', 'encrypted_embed_key']);
      if (!wrappers.some((key) => key.key_type === 'master' && key.encrypted_embed_key)
        || (intent.target_chat_id && !wrappers.some((key) => key.key_type === 'chat'
          && key.hashed_chat_id === hashIdentifier(intent.target_chat_id)
          && key.encrypted_embed_key))
        || (intent.hashed_team_id && !wrappers.some((key) => key.key_type === 'team'
          && key.hashed_team_id === intent.hashed_team_id
          && key.encrypted_embed_key))) fail(409, 'direct_skill_canonical_embed_missing');
    }
    await trx(AUTHORIZED_DIRECT_SKILLS).where({ id, state: 'RUNNING' })
      .update({ state, completed_at: now });
    return { producer_intent_id: id, status: state, idempotent: false };
  });
}

async function completeAuthorizedStandaloneAsset(database, raw, now) {
  const body = operationBody(raw, 'complete_authorized_standalone_asset');
  const id = uuid(body.task_uuid, 'invalid_task_id');
  const name = producerTaskName(body.task_name);
  const binding = hexDigest(body.kwargs_binding, 'invalid_producer_binding');
  const assetId = uuid(body.asset_id, 'invalid_asset_id');
  return database.transaction(async (trx) => {
    const snapshot = await trx(AUTHORIZED_DIRECT_SKILLS).where({ id }).first();
    if (snapshot) await requireUnfencedRecoveryAccount(trx, snapshot.hashed_user_id);
    const intent = await trx(AUTHORIZED_DIRECT_SKILLS).where({ id }).forUpdate().first();
    if (!intent || intent.task_name !== name || intent.kwargs_binding !== binding) {
      fail(404, 'producer_intent_not_found');
    }
    if (intent.target_chat_id || intent.primary_message_id
      || intent.primary_embed_id !== assetId) {
      fail(409, 'standalone_asset_intent_mismatch');
    }
    if (!['RUNNING', 'COMPLETED'].includes(intent.state)) {
      fail(409, 'direct_skill_intent_invalidated');
    }
    await checkedDirectSkillAuthority(trx, intent);
    const asset = await standaloneAssetProof(trx, intent);
    if (!asset) {
      fail(409, 'standalone_asset_proof_missing');
    }
    if (intent.state === 'COMPLETED') {
      return { producer_intent_id: id, status: 'COMPLETED', asset_id: assetId,
        content_hash: asset.content_hash, idempotent: true };
    }
    await trx(AUTHORIZED_DIRECT_SKILLS).where({ id, state: 'RUNNING' })
      .update({ state: 'COMPLETED', completed_at: now });
    return { producer_intent_id: id, status: 'COMPLETED', asset_id: assetId,
      content_hash: asset.content_hash, idempotent: false };
  });
}

async function completeAuthorizedRerender(database, raw, now) {
  const body = operationBody(raw, 'complete_authorized_rerender');
  const id = uuid(body.task_uuid, 'invalid_task_id');
  const name = producerTaskName(body.task_name);
  const binding = hexDigest(body.kwargs_binding, 'invalid_producer_binding');
  const completion = string(body.completion, 'invalid_completion', 16);
  if (!['published', 'failed'].includes(completion)) fail(400, 'invalid_completion');
  const state = completion === 'published' ? 'COMPLETED' : 'FAILED';
  return database.transaction(async (trx) => {
    const snapshot = await trx(AUTHORIZED_RERENDERS).where({ id }).first();
    if (snapshot) {
      await requireUnfencedRecoveryAccount(trx, snapshot.hashed_user_id);
      await lockRecoveryChats(trx, snapshot.target_chat_id);
    }
    const intent = await trx(AUTHORIZED_RERENDERS).where({ id }).forUpdate().first();
    if (!intent || intent.task_name !== name || intent.kwargs_binding !== binding) {
      fail(404, 'producer_intent_not_found');
    }
    if (intent.state === state) return { producer_intent_id: id, status: state, idempotent: true };
    if (intent.state !== 'RUNNING') fail(409, 'rerender_intent_invalidated');
    await requireUnfencedRecoveryAccount(trx, intent.hashed_user_id);
    if (await trx(CHAT_DELETION_FENCES).where({ id: intent.target_chat_id }).first()) {
      fail(409, 'producer_chat_deleted');
    }
    const chat = await authorizedOutputChat(trx, intent.target_chat_id, intent.hashed_user_id);
    if ((chat.hashed_team_id || null) !== (intent.hashed_team_id || null)) {
      fail(409, 'producer_team_scope_changed');
    }
    if (state === 'COMPLETED') {
      const embed = await trx(EMBEDS).where({
        embed_id: intent.primary_embed_id, hashed_user_id: intent.hashed_user_id,
      }).first();
      if (!embed || !embed.encrypted_content
        || embed.hashed_chat_id !== hashIdentifier(intent.target_chat_id)
        || Number(embed.version_number || 1) !== intent.expected_embed_version + 1) {
        fail(409, 'rerender_canonical_embed_missing');
      }
      const keySubject = embed.parent_embed_id || intent.primary_embed_id;
      const wrappers = await trx(EMBED_KEYS).where({
        hashed_embed_id: hashIdentifier(keySubject), hashed_user_id: intent.hashed_user_id,
      }).select(['key_type', 'hashed_chat_id', 'hashed_team_id', 'encrypted_embed_key']);
      if (!wrappers.some((key) => key.key_type === 'master' && key.encrypted_embed_key)
        || !wrappers.some((key) => key.key_type === 'chat'
          && key.hashed_chat_id === hashIdentifier(intent.target_chat_id)
          && key.encrypted_embed_key)
        || (intent.hashed_team_id && !wrappers.some((key) => key.key_type === 'team'
          && key.hashed_team_id === intent.hashed_team_id
          && key.encrypted_embed_key))) fail(409, 'rerender_canonical_embed_missing');
    }
    await trx(AUTHORIZED_RERENDERS).where({ id, state: 'RUNNING' })
      .update({ state, completed_at: now });
    return { producer_intent_id: id, status: state, idempotent: false };
  });
}

async function claimAuthorizedDirectProducer(database, raw, now) {
  const body = operationBody(raw, 'claim_authorized_direct_producer');
  const id = uuid(body.task_uuid, 'invalid_task_id');
  const name = producerTaskName(body.task_name);
  const binding = hexDigest(body.kwargs_binding, 'invalid_producer_binding');
  return database.transaction(async (trx) => {
    const directSnapshot = await trx(AUTHORIZED_DIRECT_SKILLS).where({ id }).first();
    const rerenderSnapshot = directSnapshot ? null
      : await trx(AUTHORIZED_RERENDERS).where({ id }).first();
    const legacySnapshot = directSnapshot || rerenderSnapshot ? null
      : await trx(LEGACY_OUTPUT_PRODUCERS).where({ id }).first();
    const snapshot = directSnapshot || rerenderSnapshot || legacySnapshot;
    if (!snapshot || snapshot.task_name !== name || snapshot.kwargs_binding !== binding) {
      fail(404, 'producer_intent_not_found');
    }
    await requireUnfencedRecoveryAccount(trx, snapshot.hashed_user_id);
    await lockRecoveryChats(trx, snapshot.root_chat_id, snapshot.target_chat_id);
    const table = directSnapshot ? AUTHORIZED_DIRECT_SKILLS
      : rerenderSnapshot ? AUTHORIZED_RERENDERS : LEGACY_OUTPUT_PRODUCERS;
    const intent = await trx(table).where({ id }).forUpdate().first();
    if (intent.state !== 'PENDING') {
      return { producer_intent_id: id, status: 'BLOCKED', claimed: false,
        reason_code: 'direct_intent_already_claimed' };
    }
    await (directSnapshot ? checkedDirectSkillAuthority(trx, intent)
      : rerenderSnapshot ? checkedRerenderAuthority(trx, intent)
        : checkedLegacyProducerAuthority(trx, intent, now));
    await trx(table).where({ id, state: 'PENDING' }).update({ state: 'RUNNING', started_at: now });
    return { producer_intent_id: id, status: 'RUNNING', claimed: true,
      intent_kind: directSnapshot ? 'direct_skill' : rerenderSnapshot ? 'rerender' : 'legacy_chat' };
  });
}

async function verifyClaimedOutputProducer(database, raw, now) {
  const body = operationBody(raw, 'verify_claimed_output_producer');
  const id = uuid(body.task_uuid, 'invalid_task_id');
  const name = producerTaskName(body.task_name);
  const binding = hexDigest(body.kwargs_binding, 'invalid_producer_binding');
  return database.transaction(async (trx) => {
    let table;
    let kind;
    for (const [candidate, candidateKind] of [
      [AUTHORIZED_DIRECT_SKILLS, 'direct_skill'],
      [AUTHORIZED_RERENDERS, 'rerender'],
      [LEGACY_OUTPUT_PRODUCERS, 'legacy_chat'],
    ]) {
      if (await trx(candidate).where({ id }).first()) {
        table = candidate;
        kind = candidateKind;
        break;
      }
    }
    if (!table) fail(404, 'producer_intent_not_found');
    const snapshot = await trx(table).where({ id }).first();
    if (snapshot.task_name !== name || snapshot.kwargs_binding !== binding) {
      fail(404, 'producer_intent_not_found');
    }
    await requireUnfencedRecoveryAccount(trx, snapshot.hashed_user_id);
    await lockRecoveryChats(trx, snapshot.root_chat_id, snapshot.target_chat_id);
    const intent = await trx(table).where({ id }).forUpdate().first();
    if (!intent || intent.state !== 'RUNNING') {
      return { producer_intent_id: id, authorized: false, reason_code: 'producer_not_running' };
    }
    try {
      if (kind === 'direct_skill') await checkedDirectSkillAuthority(trx, intent);
      else if (kind === 'rerender') {
        // The expected source head may already have advanced while this worker
        // produced the next version. Current chat and Team authority still apply.
        if (await trx(CHAT_DELETION_FENCES).where({ id: intent.target_chat_id }).first()) {
          fail(409, 'producer_chat_deleted');
        }
        const chat = await authorizedOutputChat(trx, intent.target_chat_id, intent.hashed_user_id);
        if ((chat.hashed_team_id || null) !== (intent.hashed_team_id || null)) {
          fail(409, 'producer_team_scope_changed');
        }
      } else await checkedLegacyProducerAuthority(trx, intent, now);
    } catch (error) {
      if (!(error instanceof ProtocolError)) throw error;
      return { producer_intent_id: id, authorized: false, reason_code: error.code };
    }
    return { producer_intent_id: id, authorized: true, status: 'RUNNING', intent_kind: kind };
  });
}

async function completeAuthorizedDirectByEmbed(database, raw, now) {
  const body = operationBody(raw, 'complete_authorized_direct_by_embed');
  const ownerHash = hexDigest(body.hashed_user_id, 'invalid_owner');
  const embedId = uuid(body.primary_embed_id, 'invalid_embed_id');
  const chatId = body.target_chat_id == null ? null
    : uuid(body.target_chat_id, 'invalid_target_chat_id');
  const version = integer(body.canonical_version, 'invalid_embed_version');
  const intentKind = string(body.intent_kind, 'invalid_intent_kind', 16);
  if (!['direct_skill', 'rerender'].includes(intentKind)) fail(400, 'invalid_intent_kind');
  if (version < 1) fail(400, 'invalid_embed_version');
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, ownerHash);
    await lockRecoveryChats(trx, chatId);
    const direct = intentKind === 'direct_skill' ? await trx(AUTHORIZED_DIRECT_SKILLS).where({
      hashed_user_id: ownerHash, primary_embed_id: embedId,
      target_chat_id: chatId, state: 'RUNNING',
    }).forUpdate().select(['id']) : [];
    const rerenders = intentKind === 'rerender' && chatId ? await trx(AUTHORIZED_RERENDERS).where({
      hashed_user_id: ownerHash, primary_embed_id: embedId,
      target_chat_id: chatId, expected_embed_version: version - 1, state: 'RUNNING',
    }).forUpdate().select(['id']) : [];
    if (direct.length + rerenders.length === 0) {
      const completedDirect = intentKind === 'direct_skill' && await trx(AUTHORIZED_DIRECT_SKILLS).where({
        hashed_user_id: ownerHash, primary_embed_id: embedId,
        target_chat_id: chatId, state: 'COMPLETED',
      }).first();
      const completedRerender = intentKind === 'rerender' && chatId && await trx(AUTHORIZED_RERENDERS).where({
        hashed_user_id: ownerHash, primary_embed_id: embedId,
        target_chat_id: chatId, expected_embed_version: version - 1,
        state: 'COMPLETED',
      }).first();
      if (completedDirect || completedRerender) {
        return { completed: true, idempotent: true,
          intent_kind: completedDirect ? 'direct_skill' : 'rerender' };
      }
      return { completed: false, reason_code: 'no_pending_intent' };
    }
    if (direct.length + rerenders.length !== 1) fail(409, 'producer_completion_ambiguous');
    const row = direct.length
      ? await trx(AUTHORIZED_DIRECT_SKILLS).where({ id: direct[0].id }).forUpdate().first()
      : await trx(AUTHORIZED_RERENDERS).where({ id: rerenders[0].id }).forUpdate().first();
    if (direct.length) await checkedDirectSkillAuthority(trx, row);
    else {
      if (await trx(CHAT_DELETION_FENCES).where({ id: chatId }).first()) fail(409, 'producer_chat_deleted');
      const chat = await authorizedOutputChat(trx, chatId, ownerHash);
      if ((chat.hashed_team_id || null) !== (row.hashed_team_id || null)) fail(409, 'producer_team_scope_changed');
    }
    const embed = await trx(EMBEDS).where({ embed_id: embedId, hashed_user_id: ownerHash }).first();
    if (!embed || !embed.encrypted_content || Number(embed.version_number || 1) !== version
      || (chatId && embed.hashed_chat_id !== hashIdentifier(chatId))) {
      fail(409, 'producer_canonical_embed_missing');
    }
    const keySubject = embed.parent_embed_id || embedId;
    const wrappers = await trx(EMBED_KEYS).where({
      hashed_embed_id: hashIdentifier(keySubject), hashed_user_id: ownerHash,
    }).select(['key_type', 'hashed_chat_id', 'hashed_team_id', 'encrypted_embed_key']);
    if (!wrappers.some((key) => key.key_type === 'master' && key.encrypted_embed_key)
      || (chatId && !wrappers.some((key) => key.key_type === 'chat'
        && key.hashed_chat_id === hashIdentifier(chatId) && key.encrypted_embed_key))
      || (row.hashed_team_id && !wrappers.some((key) => key.key_type === 'team'
        && key.hashed_team_id === row.hashed_team_id && key.encrypted_embed_key))) {
      return { completed: false, reason_code: 'pending_wrappers' };
    }
    const table = direct.length ? AUTHORIZED_DIRECT_SKILLS : AUTHORIZED_RERENDERS;
    await trx(table).where({ id: row.id, state: 'RUNNING' })
      .update({ state: 'COMPLETED', completed_at: now });
    return { completed: true, intent_kind: direct.length ? 'direct_skill' : 'rerender' };
  });
}

async function reconcileAuthorizedDirectCompletions(database, raw, now) {
  const body = operationBody(raw, 'reconcile_authorized_direct_completions');
  const limit = integer(body.limit, 'invalid_reconcile_limit');
  const afterId = body.after_id == null ? null : uuid(body.after_id, 'invalid_reconcile_cursor');
  if (limit < 1 || limit > 100) fail(400, 'invalid_reconcile_limit');
  let query = database(AUTHORIZED_DIRECT_SKILLS).where({ state: 'RUNNING' });
  if (afterId) query = query.where('id', '>', afterId);
  const candidates = await query.orderBy('id').limit(limit).select([
    'id', 'hashed_user_id', 'primary_embed_id', 'target_chat_id',
  ]);
  let completed = 0;
  let pending = 0;
  let blocked = 0;
  for (const candidate of candidates) {
    try {
      // One owner/intent per transaction avoids holding several accounts'
      // advisory locks while reconciling an unrelated owner later in the page.
      const outcome = await database.transaction(async (trx) => {
        await requireUnfencedRecoveryAccount(trx, candidate.hashed_user_id);
        await lockRecoveryChats(trx, candidate.target_chat_id);
        const intent = await trx(AUTHORIZED_DIRECT_SKILLS)
          .where({ id: candidate.id }).forUpdate().first();
        if (!intent || intent.state !== 'RUNNING') return 'skipped';
        await checkedDirectSkillAuthority(trx, intent);
        const embed = await trx(EMBEDS).where({
          embed_id: intent.primary_embed_id, hashed_user_id: intent.hashed_user_id,
        }).first();
        if (!embed || !embed.encrypted_content
          || (intent.target_chat_id
            && embed.hashed_chat_id !== hashIdentifier(intent.target_chat_id))) {
          return 'pending';
        }
        const keySubject = embed.parent_embed_id || intent.primary_embed_id;
        const wrappers = await trx(EMBED_KEYS).where({
          hashed_embed_id: hashIdentifier(keySubject), hashed_user_id: intent.hashed_user_id,
        }).select(['key_type', 'hashed_chat_id', 'hashed_team_id', 'encrypted_embed_key']);
        if (!wrappers.some((key) => key.key_type === 'master' && key.encrypted_embed_key)
          || (intent.target_chat_id && !wrappers.some((key) => key.key_type === 'chat'
            && key.hashed_chat_id === hashIdentifier(intent.target_chat_id)
            && key.encrypted_embed_key))
          || (intent.hashed_team_id && !wrappers.some((key) => key.key_type === 'team'
            && key.hashed_team_id === intent.hashed_team_id && key.encrypted_embed_key))) {
          return 'pending';
        }
        await trx(AUTHORIZED_DIRECT_SKILLS).where({ id: intent.id, state: 'RUNNING' })
          .update({ state: 'COMPLETED', completed_at: now });
        return 'completed';
      });
      if (outcome === 'completed') completed += 1;
      if (outcome === 'pending') pending += 1;
    } catch (error) {
      if (!(error instanceof ProtocolError)) throw error;
      blocked += 1;
    }
  }
  return {
    scanned: candidates.length, completed, pending, blocked,
    next_cursor: candidates.length ? candidates[candidates.length - 1].id : null,
  };
}

async function resolveOutputProducer(database, raw, now) {
  const body = operationBody(raw, 'resolve_output_producer');
  const id = uuid(body.task_uuid, 'invalid_task_id');
  const name = producerTaskName(body.task_name);
  const binding = hexDigest(body.kwargs_binding, 'invalid_producer_binding');
  return database.transaction(async (trx) => {
    const legacySnapshot = await trx(LEGACY_OUTPUT_PRODUCERS).where({ id }).first();
    if (legacySnapshot) {
      if (legacySnapshot.task_name !== name || legacySnapshot.kwargs_binding !== binding) {
        fail(404, 'producer_intent_not_found');
      }
      await requireUnfencedRecoveryAccount(trx, legacySnapshot.hashed_user_id);
      await lockRecoveryChats(trx, legacySnapshot.root_chat_id, legacySnapshot.target_chat_id);
      const legacy = await trx(LEGACY_OUTPUT_PRODUCERS).where({ id }).forUpdate().first();
      if (!legacy || legacy.state !== 'PENDING') {
        return { producer_intent_id: id, status: 'BLOCKED',
          reason_code: 'legacy_producer_already_claimed' };
      }
      try {
        await checkedLegacyProducerAuthority(trx, legacy, now);
      } catch (error) {
        if (!(error instanceof ProtocolError)) throw error;
        return { producer_intent_id: id, status: 'BLOCKED', reason_code: error.code };
      }
      return { producer_intent_id: id, status: 'LEGACY_AUTHORIZED',
        intent_kind: 'legacy_chat', context: {
          hashed_user_id: legacy.hashed_user_id,
          hashed_team_id: legacy.hashed_team_id || null,
          root_chat_id: legacy.root_chat_id, target_chat_id: legacy.target_chat_id,
          root_turn_id: legacy.root_turn_id,
          root_user_message_id: legacy.root_user_message_id,
          primary_message_id: legacy.primary_message_id,
          primary_embed_id: legacy.primary_embed_id,
        } };
    }
    const directSnapshot = await trx(AUTHORIZED_DIRECT_SKILLS).where({ id }).first();
    if (directSnapshot) {
      await requireUnfencedRecoveryAccount(trx, directSnapshot.hashed_user_id);
      await lockRecoveryChats(trx, directSnapshot.target_chat_id);
    }
    const direct = directSnapshot
      ? await trx(AUTHORIZED_DIRECT_SKILLS).where({ id }).forUpdate().first() : null;
    if (direct) {
      if (direct.task_name !== name || direct.kwargs_binding !== binding) {
        fail(404, 'producer_intent_not_found');
      }
      if (direct.state === 'COMPLETED') {
        return { producer_intent_id: id, status: 'COMPLETED',
          reason_code: 'direct_skill_already_completed' };
      }
      if (direct.state !== 'PENDING') {
        return { producer_intent_id: id, status: 'BLOCKED', reason_code: 'direct_skill_intent_invalidated' };
      }
      try {
        await checkedDirectSkillAuthority(trx, direct);
      } catch (error) {
        if (!(error instanceof ProtocolError)) throw error;
        return { producer_intent_id: id, status: 'BLOCKED', reason_code: error.code };
      }
      return {
        producer_intent_id: id, status: 'DIRECT_AUTHORIZED', intent_kind: 'direct_skill',
        context: {
          hashed_user_id: direct.hashed_user_id, hashed_team_id: direct.hashed_team_id,
          target_chat_id: direct.target_chat_id, primary_message_id: direct.primary_message_id,
          primary_embed_id: direct.primary_embed_id,
        },
      };
    }
    const rerenderSnapshot = await trx(AUTHORIZED_RERENDERS).where({ id }).first();
    if (rerenderSnapshot) {
      await requireUnfencedRecoveryAccount(trx, rerenderSnapshot.hashed_user_id);
      await lockRecoveryChats(trx, rerenderSnapshot.target_chat_id);
    }
    const rerender = rerenderSnapshot
      ? await trx(AUTHORIZED_RERENDERS).where({ id }).forUpdate().first() : null;
    if (rerender) {
      if (rerender.task_name !== name || rerender.kwargs_binding !== binding) {
        fail(404, 'producer_intent_not_found');
      }
      if (rerender.state !== 'PENDING') {
        return { producer_intent_id: id, status: 'BLOCKED', reason_code: 'rerender_intent_invalidated' };
      }
      try {
        await checkedRerenderAuthority(trx, rerender);
      } catch (error) {
        if (!(error instanceof ProtocolError)) throw error;
        return { producer_intent_id: id, status: 'BLOCKED', reason_code: error.code };
      }
      return {
        producer_intent_id: id, status: 'DIRECT_AUTHORIZED', intent_kind: 'rerender',
        context: {
          hashed_user_id: rerender.hashed_user_id, hashed_team_id: rerender.hashed_team_id || null,
          target_chat_id: rerender.target_chat_id,
          primary_embed_id: rerender.primary_embed_id,
          primary_message_id: rerender.primary_message_id,
          source_version: rerender.source_version,
          expected_embed_version: rerender.expected_embed_version,
        },
      };
    }
    const intent = await registeredProducer(trx, id, name, binding, true);
    try {
      await checkedProducerAuthority(trx, intent);
    } catch (error) {
      if (!(error instanceof ProtocolError)) throw error;
      return { producer_intent_id: id, status: 'BLOCKED', reason_code: error.code };
    }
    const output = await trx(OUTPUTS).where({ producer_intent_id: id, producer_ordinal: 0 }).first();
    if (output && !['PENDING', 'ACKNOWLEDGED'].includes(output.state)) {
      return { producer_intent_id: id, status: 'BLOCKED', reason_code: 'producer_output_preparing' };
    }
    if (!output && await trx(OUTPUTS).where({ producer_intent_id: id }).first()) {
      return { producer_intent_id: id, status: 'BLOCKED', reason_code: 'partial_output_pending' };
    }
    return {
      producer_intent_id: id, status: output ? 'SEALED' : 'PENDING',
      context: producerContext(intent),
      ...(output ? { record_id: output.id, output_state: output.state } : {}),
    };
  });
}

async function registerOutputProducerChild(database, raw, now) {
  const body = operationBody(raw, 'register_output_producer_child');
  const id = uuid(body.producer_intent_id, 'invalid_producer_intent_id');
  const name = producerTaskName(body.task_name);
  const binding = hexDigest(body.kwargs_binding, 'invalid_producer_binding');
  const requestedOrdinal = body.ordinal === undefined
    ? null : integer(body.ordinal, 'invalid_producer_ordinal');
  const subject = {
    subject_id: uuid(body.subject_id, 'invalid_subject_id'),
    output_kind: string(body.output_kind, 'invalid_output_kind', 24),
    output_version: integer(body.output_version, 'invalid_output_version'),
  };
  if (!PRODUCER_OUTPUT_KINDS.has(subject.output_kind) || subject.output_version < 1) {
    fail(400, 'invalid_output_identity');
  }
  return database.transaction(async (trx) => {
    const intent = await registeredProducer(trx, id, name, binding);
    if (requestedOrdinal !== null && (requestedOrdinal < 1 || requestedOrdinal > intent.max_children)) {
      fail(400, 'invalid_producer_ordinal');
    }
    await checkedProducerAuthority(trx, intent);
    const duplicate = await trx(OUTPUT_PRODUCER_CHILDREN)
      .where({ producer_intent_id: id, ...subject }).first();
    if (duplicate) {
      if (requestedOrdinal !== null && requestedOrdinal !== duplicate.ordinal) fail(409, 'producer_child_mismatch');
      return { producer_intent_id: id, ordinal: duplicate.ordinal, idempotent: true };
    }
    if (intent.registration_closed_at) fail(409, 'producer_registration_closed');
    if (intent.primary_embed_id === subject.subject_id
      && intent.primary_output_kind === subject.output_kind
      && intent.primary_output_version === subject.output_version) fail(409, 'producer_child_duplicate');
    const used = new Set(await trx(OUTPUT_PRODUCER_CHILDREN)
      .where({ producer_intent_id: id }).pluck('ordinal'));
    const ordinal = requestedOrdinal ?? Array.from({ length: intent.max_children }, (_, index) => index + 1)
      .find((candidate) => !used.has(candidate));
    if (!ordinal) fail(409, 'producer_child_limit');
    if (used.has(ordinal)) fail(409, 'producer_child_mismatch');
    await trx(OUTPUT_PRODUCER_CHILDREN).insert({
      id: randomUUID(), producer_intent_id: id, ordinal, ...subject, registered_at: now,
    });
    return { producer_intent_id: id, ordinal, idempotent: false };
  });
}

async function maybeCompleteOutputProducer(trx, intentId, now) {
  if (!intentId) return;
  const intent = await trx(OUTPUT_PRODUCERS).where({ id: intentId }).forUpdate().first();
  if (!intent || intent.state !== 'PENDING' || !intent.registration_closed_at) return;
  const children = await trx(OUTPUT_PRODUCER_CHILDREN).where({ producer_intent_id: intentId }).pluck('ordinal');
  const outputs = await trx(OUTPUTS).where({ producer_intent_id: intentId }).select(['producer_ordinal', 'state']);
  const expected = new Set([0, ...children]);
  if (outputs.length !== expected.size || outputs.some((row) =>
    !expected.has(Number(row.producer_ordinal)) || row.state !== 'ACKNOWLEDGED')) return;
  await trx(OUTPUT_PRODUCERS).where({ id: intentId, state: 'PENDING' })
    .update({ state: 'COMPLETED', completed_at: now });
}

async function closeOutputProducer(database, raw, now) {
  const body = operationBody(raw, 'close_output_producer');
  const id = uuid(body.producer_intent_id, 'invalid_producer_intent_id');
  const name = producerTaskName(body.task_name);
  const binding = hexDigest(body.kwargs_binding, 'invalid_producer_binding');
  const manifest = body.expected_children;
  if (!Array.isArray(manifest) || manifest.length > MAX_PRODUCER_CHILDREN) {
    fail(400, 'invalid_producer_manifest');
  }
  const expected = manifest.map((entry) => {
    if (!entry || Array.isArray(entry) || typeof entry !== 'object'
      || Object.keys(entry).sort().join(',') !== 'output_kind,output_version,subject_id') {
      fail(400, 'invalid_producer_manifest');
    }
    const result = {
      subject_id: uuid(entry.subject_id, 'invalid_subject_id'),
      output_kind: string(entry.output_kind, 'invalid_output_kind', 24),
      output_version: integer(entry.output_version, 'invalid_output_version'),
    };
    if (!PRODUCER_OUTPUT_KINDS.has(result.output_kind) || result.output_version < 1) {
      fail(400, 'invalid_producer_manifest');
    }
    return result;
  }).sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
  if (expected.some((entry, index) => index > 0
    && JSON.stringify(entry) === JSON.stringify(expected[index - 1]))) {
    fail(400, 'invalid_producer_manifest');
  }
  return database.transaction(async (trx) => {
    const intent = await registeredProducer(trx, id, name, binding, true);
    await checkedProducerAuthority(trx, intent);
    const registeredChildren = await trx(OUTPUT_PRODUCER_CHILDREN).where({ producer_intent_id: id })
      .select(['ordinal', 'subject_id', 'output_kind', 'output_version']);
    const children = registeredChildren.map(({ ordinal: _ordinal, ...tuple }) => tuple)
      .sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
    if (JSON.stringify(children) !== JSON.stringify(expected)) fail(409, 'producer_manifest_mismatch');
    const outputs = await trx(OUTPUTS).where({ producer_intent_id: id })
      .select(['producer_ordinal', 'subject_id', 'output_kind', 'output_version', 'state', 'deleted_at']);
    if (outputs.length !== registeredChildren.length + 1 || outputs.some((row) => {
      const tuple = Number(row.producer_ordinal) === 0 ? {
        subject_id: intent.primary_embed_id, output_kind: intent.primary_output_kind,
        output_version: intent.primary_output_version,
      } : registeredChildren.find((child) => child.ordinal === Number(row.producer_ordinal));
      return !tuple || row.subject_id !== tuple.subject_id || row.output_kind !== tuple.output_kind
        || Number(row.output_version) !== tuple.output_version || row.deleted_at
        || !['PENDING', 'ACKNOWLEDGED'].includes(row.state);
    })) fail(409, 'producer_manifest_unsealed');
    if (intent.registration_closed_at) {
      if (intent.expected_children_manifest !== JSON.stringify(expected)) fail(409, 'producer_manifest_mismatch');
      return { producer_intent_id: id, status: intent.state, idempotent: true };
    }
    await trx(OUTPUT_PRODUCERS).where({ id }).update({
      registration_closed_at: now, expected_children_manifest: JSON.stringify(expected),
    });
    await maybeCompleteOutputProducer(trx, id, now);
    const updated = await trx(OUTPUT_PRODUCERS).where({ id }).first();
    return { producer_intent_id: id, status: updated.state, idempotent: false };
  });
}

async function classifyUntaggedOutputProducer(database, raw) {
  const body = operationBody(raw, 'classify_untagged_output_producer');
  uuid(body.task_uuid, 'invalid_task_id');
  producerTaskName(body.task_name);
  const ownerHash = hexDigest(body.hashed_user_id, 'invalid_owner');
  const chatId = uuid(body.target_chat_id, 'invalid_target_chat_id');
  const messageId = string(body.primary_message_id, 'invalid_message_id', 255);
  return database.transaction(async (trx) => {
    try {
      await requireUnfencedRecoveryAccount(trx, ownerHash);
      if (await trx(CHAT_DELETION_FENCES).where({ id: chatId }).first()) {
        return { status: 'BLOCKED', reason_code: 'producer_chat_deleted' };
      }
      await authorizedOutputChat(trx, chatId, ownerHash);
    } catch (error) {
      if (!(error instanceof ProtocolError)) throw error;
      return { status: 'BLOCKED', reason_code: error.code };
    }
    // Exact indexed message and child-identity lookups only. Absence is not
    // evidence of never-admitted AI work after retention cleanup; protected
    // workers must hold all untagged tasks even when this reports UNRELATED.
    const preflight = await trx(PREFLIGHTS).where({ user_message_id: messageId }).first();
    if (preflight) {
      if (preflight.hashed_user_id !== ownerHash || preflight.chat_id !== chatId
        || preflight.deletion_invalidated_at || !['RUNNING', 'TERMINAL'].includes(preflight.state)) {
        return { status: 'BLOCKED', reason_code: 'producer_preflight_invalid' };
      }
      return { status: 'ADMITTED_UNTAGGED', preflight_id: preflight.id };
    }
    const child = await trx(ORCHESTRATION_CHILDREN)
      .where({ child_chat_id: chatId, user_message_id: messageId }).first();
    if (child) {
      const root = await trx(ORCHESTRATIONS).where({ id: child.orchestration_id }).first();
      const rootPreflight = root && await trx(PREFLIGHTS)
        .where({ chat_id: root.root_chat_id, inference_task_id: root.inference_task_id }).first();
      if (!root || root.hashed_user_id !== ownerHash || !rootPreflight
        || rootPreflight.deletion_invalidated_at
        || !['RUNNING', 'TERMINAL'].includes(rootPreflight.state)) {
        return { status: 'BLOCKED', reason_code: 'producer_preflight_invalid' };
      }
      return { status: 'ADMITTED_UNTAGGED', preflight_id: rootPreflight.id };
    }
    return { status: 'UNRELATED' };
  });
}

async function getProducerOutput(database, raw) {
  const body = operationBody(raw, 'get_producer_output');
  const id = uuid(body.producer_intent_id, 'invalid_producer_intent_id');
  const name = producerTaskName(body.task_name);
  const binding = hexDigest(body.kwargs_binding, 'invalid_producer_binding');
  const ordinal = integer(body.ordinal, 'invalid_producer_ordinal');
  const commitment = body.content_commitment === undefined
    ? null : hexDigest(body.content_commitment, 'invalid_content_commitment');
  return database.transaction(async (trx) => {
    const intent = await registeredProducer(trx, id, name, binding, true);
    await checkedProducerAuthority(trx, intent);
    await producerSubject(trx, intent, ordinal);
    const row = await trx(OUTPUTS).where({ producer_intent_id: id, producer_ordinal: ordinal }).first();
    if (!row) return { status: 'ABSENT' };
    if (row.deleted_at || row.state === 'DELETED') fail(409, 'producer_output_invalidated');
    if (commitment === null) return { status: row.state, record_id: row.id };
    if (row.content_commitment !== commitment) fail(409, 'producer_content_mismatch');
    return {
      status: row.state, record_id: row.id, idempotent: true,
      sealed_payload: row.state === 'PENDING' ? row.sealed_payload : null,
      payload_storage: row.payload_storage,
      payload_s3_key: row.state === 'PENDING' ? row.payload_s3_key : null,
      payload_size_bytes: row.payload_size_bytes,
      sealed_payload_digest: row.sealed_payload_digest,
      payload_verified_regions: row.payload_verified_regions,
    };
  });
}

async function getReplayOutput(database, raw) {
  const body = operationBody(raw, 'get_replay_output');
  const identity = {
    id: uuid(body.record_id, 'invalid_record_id'),
    hashed_user_id: hexDigest(body.hashed_user_id, 'invalid_owner'),
    preflight_id: uuid(body.preflight_id, 'invalid_preflight_id'),
    root_chat_id: uuid(body.root_chat_id, 'invalid_root_chat_id'),
    target_chat_id: uuid(body.target_chat_id, 'invalid_target_chat_id'),
    subject_id: string(body.subject_id, 'invalid_subject_id', 255),
    output_kind: string(body.output_kind, 'invalid_output_kind', 24),
    output_version: integer(body.output_version, 'invalid_output_version'),
    content_commitment: hexDigest(body.content_commitment, 'invalid_content_commitment'),
  };
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, identity.hashed_user_id);
    await lockRecoveryChats(trx, identity.root_chat_id, identity.target_chat_id);
    const preflight = await trx(PREFLIGHTS).where({ id: identity.preflight_id }).forUpdate().first();
    if (!preflight || preflight.state !== 'RUNNING' || preflight.deletion_invalidated_at
      || preflight.hashed_user_id !== identity.hashed_user_id
      || preflight.chat_id !== identity.root_chat_id) fail(409, 'inference_not_running');
    await authorizedOutputChat(trx, identity.root_chat_id, identity.hashed_user_id);
    await authorizedOutputChat(trx, identity.target_chat_id, identity.hashed_user_id);
    const row = await trx(OUTPUTS).where({ id: identity.id }).forUpdate().first();
    if (!row) return { status: 'ABSENT' };
    if (row.producer_intent_id || row.deleted_at
      || Object.entries(identity).some(([key, value]) => row[key] !== value)) {
      fail(409, 'replay_output_mismatch');
    }
    return { status: row.state, ...producerOutputReceipt(row) };
  });
}

function producerOutputReceipt(row) {
  return {
    record_id: row.id, state: row.state, idempotent: true,
    sealed_payload: row.state === 'PENDING' ? row.sealed_payload : null,
    payload_storage: row.payload_storage,
    payload_s3_key: row.state === 'PENDING' ? row.payload_s3_key : null,
    payload_size_bytes: row.payload_size_bytes,
    sealed_payload_digest: row.sealed_payload_digest,
    payload_verified_regions: row.payload_verified_regions,
  };
}

async function createSealedOutput(database, raw, now, preparing = false) {
  const body = operationBody(raw, preparing ? 'prepare_sealed_output' : 'create_sealed_output');
  const identity = {
    hashed_user_id: string(body.hashed_user_id, 'invalid_owner', 64),
    root_chat_id: uuid(body.root_chat_id, 'invalid_root_chat_id'),
    target_chat_id: uuid(body.target_chat_id, 'invalid_target_chat_id'),
    turn_id: uuid(body.turn_id, 'invalid_turn_id'),
    preflight_id: uuid(body.preflight_id, 'invalid_preflight_id'),
    inference_task_id: uuid(body.inference_task_id, 'invalid_task_id'),
    subject_id: string(body.subject_id, 'invalid_subject_id', 255),
    output_kind: string(body.output_kind, 'invalid_output_kind', 24),
    output_version: integer(body.output_version, 'invalid_output_version'),
    chat_key_version: integer(body.chat_key_version, 'invalid_key_version'),
    message_role: body.output_kind === 'message'
      ? string(body.message_role ?? 'assistant', 'invalid_message_role', 16) : null,
  };
  if (!OUTPUT_KINDS.has(identity.output_kind) || identity.output_version < 1 || identity.chat_key_version < 1) {
    fail(400, 'invalid_output_identity');
  }
  if ((identity.output_kind === 'message' && !['user', 'assistant'].includes(identity.message_role))
    || (identity.output_kind !== 'message' && body.message_role != null)) fail(400, 'invalid_message_role');
  const producerId = body.producer_intent_id === undefined
    ? null : uuid(body.producer_intent_id, 'invalid_producer_intent_id');
  if (!producerId && ['producer_ordinal', 'producer_task_name', 'producer_kwargs_binding']
    .some((field) => body[field] !== undefined)) fail(400, 'invalid_producer_identity');
  const producerOrdinal = producerId ? integer(body.producer_ordinal, 'invalid_producer_ordinal') : null;
  const producerName = producerId ? producerTaskName(body.producer_task_name) : null;
  const producerBinding = producerId
    ? hexDigest(body.producer_kwargs_binding, 'invalid_producer_binding') : null;
  const contentCommitment = body.content_commitment === undefined
    ? null : hexDigest(body.content_commitment, 'invalid_content_commitment');
  if (producerId && !contentCommitment) fail(400, 'invalid_content_commitment');
  const recordId = uuid(body.record_id, 'invalid_record_id');
  const inline = body.sealed_payload !== undefined;
  const external = body.payload_s3_key !== undefined;
  if (inline === external || (preparing && !external)) fail(400, 'invalid_output_storage');
  let sealedPayload = null;
  let payloadKey = null;
  let payloadSize;
  let payloadDigest;
  let verifiedRegions = null;
  if (inline) {
    sealedPayload = validateEnvelope(body.sealed_payload, 2);
    payloadSize = Buffer.byteLength(sealedPayload, 'utf8');
    if (payloadSize > MAX_INLINE_OUTPUT_BYTES) fail(413, 'output_requires_object_storage');
    payloadDigest = digest(sealedPayload);
  } else {
    payloadKey = string(body.payload_s3_key, 'invalid_output_locator', 512);
    if (!/^chat-recovery\/v2\/[0-9a-f]{2}\/[0-9a-f-]{36}\/[0-9a-f]{64}\.json$/.test(payloadKey)
      || !payloadKey.includes(`/${recordId}/`)) fail(400, 'invalid_output_locator');
    payloadSize = integer(body.payload_size_bytes, 'invalid_output_size');
    if (payloadSize <= MAX_INLINE_OUTPUT_BYTES || payloadSize > 24 * 1024 * 1024) fail(400, 'invalid_output_size');
    payloadDigest = hexDigest(body.sealed_payload_digest, 'invalid_output_digest');
    if (!preparing) {
      if (!Array.isArray(body.payload_verified_regions) || body.payload_verified_regions.length < 1
        || body.payload_verified_regions.length > 8
        || body.payload_verified_regions.some((region) => typeof region !== 'string' || !/^[a-z0-9-]{2,32}$/.test(region))) {
        fail(400, 'invalid_output_regions');
      }
      verifiedRegions = [...new Set(body.payload_verified_regions)].sort();
    }
  }
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, identity.hashed_user_id);
    await lockRecoveryChats(trx, identity.root_chat_id, identity.target_chat_id);
    let producer = null;
    if (producerId) {
      producer = await registeredProducer(trx, producerId, producerName, producerBinding, true);
      await checkedProducerAuthority(trx, producer);
      const subject = await producerSubject(trx, producer, producerOrdinal);
      if (producer.hashed_user_id !== identity.hashed_user_id
        || producer.root_chat_id !== identity.root_chat_id
        || producer.target_chat_id !== identity.target_chat_id
        || producer.turn_id !== identity.turn_id
        || producer.preflight_id !== identity.preflight_id
        || producer.inference_task_id !== identity.inference_task_id
        || producer.chat_key_version !== identity.chat_key_version
        || subject.subject_id !== identity.subject_id
        || subject.output_kind !== identity.output_kind
        || subject.output_version !== identity.output_version) fail(409, 'producer_output_identity_mismatch');
      const priorOutput = await trx(OUTPUTS)
        .where({ producer_intent_id: producerId, producer_ordinal: producerOrdinal }).forUpdate().first();
      if (priorOutput && priorOutput.id !== recordId) {
        if (priorOutput.content_commitment !== contentCommitment) fail(409, 'producer_content_mismatch');
        if (priorOutput.deleted_at || priorOutput.state === 'DELETED') fail(409, 'producer_output_invalidated');
        return producerOutputReceipt(priorOutput);
      }
    }
    const existing = await trx(OUTPUTS).where({ id: recordId }).forUpdate().first();
    if (existing) {
      if (!producer && contentCommitment) {
        const preflight = await trx(PREFLIGHTS).where({ id: identity.preflight_id }).forUpdate().first();
        if (!preflight || preflight.state !== 'RUNNING' || preflight.deletion_invalidated_at
          || preflight.hashed_user_id !== identity.hashed_user_id) fail(409, 'inference_not_running');
        if (existing.producer_intent_id || existing.content_commitment !== contentCommitment) {
          fail(409, 'replay_output_mismatch');
        }
      }
      if (Object.entries(identity).some(([key, value]) =>
        (key === 'message_role' && identity.output_kind === 'message'
          ? (existing[key] || 'assistant') : existing[key]) !== value)) fail(409, 'sealed_output_mismatch');
      if (producer && (existing.producer_intent_id !== producerId
        || Number(existing.producer_ordinal) !== producerOrdinal
        || existing.content_commitment !== contentCommitment)) fail(409, 'producer_content_mismatch');
      if ((producer || contentCommitment) && existing.sealed_payload_digest !== payloadDigest) {
        if (existing.deleted_at || existing.state === 'DELETED') fail(409, 'producer_output_invalidated');
        return producerOutputReceipt(existing);
      }
      if (existing.sealed_payload_digest !== payloadDigest
        || existing.payload_s3_key !== payloadKey
        || existing.payload_storage !== (external ? 's3' : 'inline')
        || Number(existing.payload_size_bytes) !== payloadSize) fail(409, 'sealed_output_mismatch');
      const currentRoot = await authorizedOutputChat(trx, identity.root_chat_id, identity.hashed_user_id);
      const currentTarget = await authorizedOutputChat(trx, identity.target_chat_id, identity.hashed_user_id);
      if ((currentRoot.hashed_team_id || null) !== (existing.root_hashed_team_id || null)
        || (currentTarget.hashed_team_id || null) !== (currentRoot.hashed_team_id || null)
        || existing.deleted_at || existing.state === 'DELETED') fail(409, 'sealed_output_invalidated');
      if (preparing && existing.state === 'PREPARING') {
        const leaseUntil = new Date(now.getTime() + 90_000);
        await trx(OUTPUTS).where({ id: recordId, state: 'PREPARING' }).update({ writer_lease_until: leaseUntil });
        return { record_id: recordId, state: 'PREPARING', writer_lease_until: leaseUntil, idempotent: true };
      }
      if (!preparing && external && existing.state === 'PREPARING') {
        if (!existing.writer_lease_until || new Date(existing.writer_lease_until) <= now) {
          fail(409, 'sealed_output_writer_lease_expired');
        }
        await trx(OUTPUTS).where({ id: recordId, state: 'PREPARING' }).update({
          state: 'PENDING', payload_verified_regions: JSON.stringify(verifiedRegions), writer_lease_until: null,
        });
        return { record_id: recordId, state: 'PENDING', idempotent: false };
      }
      if (existing.state !== 'PENDING' && existing.state !== 'ACKNOWLEDGED') fail(409, 'sealed_output_invalid_state');
      return { record_id: recordId, state: existing.state, idempotent: true };
    }
    if (producer?.registration_closed_at) fail(409, 'producer_registration_closed');
    if (external && !preparing) fail(409, 'sealed_output_intent_required');
    const preflight = await trx(PREFLIGHTS).where({ id: identity.preflight_id }).forUpdate().first();
    if (!preflight || (!producer && preflight.state !== 'RUNNING')
      || (producer && !['RUNNING', 'TERMINAL'].includes(preflight.state)) || preflight.deletion_invalidated_at
      || preflight.hashed_user_id !== identity.hashed_user_id
      || preflight.chat_id !== identity.root_chat_id || preflight.turn_id !== identity.turn_id
      || preflight.chat_key_version !== identity.chat_key_version) fail(409, 'inference_not_running');
    const rootChat = await authorizedOutputChat(trx, identity.root_chat_id, identity.hashed_user_id);
    const targetChat = await authorizedOutputChat(trx, identity.target_chat_id, identity.hashed_user_id);
    if ((rootChat.hashed_team_id || null) !== (targetChat.hashed_team_id || null)) fail(409, 'recovery_team_scope_mismatch');
    if (identity.target_chat_id !== identity.root_chat_id) {
      const child = await trx(ORCHESTRATION_CHILDREN)
        .where({ child_chat_id: identity.target_chat_id }).first();
      const root = child && await trx(ORCHESTRATIONS).where({ id: child.orchestration_id }).first();
      if (!root || root.root_chat_id !== identity.root_chat_id
        || root.hashed_user_id !== identity.hashed_user_id
        || child.inference_task_id !== identity.inference_task_id) fail(409, 'child_recovery_identity_mismatch');
    } else if (preflight.inference_task_id !== identity.inference_task_id) {
      fail(409, 'inference_task_mismatch');
    }
    await trx(OUTPUTS).insert({
      id: recordId, ...identity, sealed_payload: sealedPayload,
      producer_intent_id: producerId, producer_ordinal: producerOrdinal,
      content_commitment: contentCommitment,
      root_hashed_team_id: rootChat.hashed_team_id || null,
      sealed_payload_digest: payloadDigest, payload_storage: inline ? 'inline' : 's3',
      payload_s3_key: payloadKey, payload_size_bytes: payloadSize,
      payload_verified_regions: verifiedRegions ? JSON.stringify(verifiedRegions) : null,
      state: preparing ? 'PREPARING' : 'PENDING', created_at: now,
      writer_lease_until: preparing ? new Date(now.getTime() + 90_000) : null,
    });
    return { record_id: recordId, state: preparing ? 'PREPARING' : 'PENDING', idempotent: false };
  });
}

async function listPendingOutputs(database, raw) {
  const body = operationBody(raw, 'list_pending_outputs');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  string(body.device_hash, 'invalid_device', 128);
  if ((body.after_created_at === undefined) !== (body.after_record_id === undefined)) {
    fail(400, 'invalid_output_cursor');
  }
  let cursorDate = null;
  let cursorId = null;
  if (body.after_created_at !== undefined) {
    const timestamp = string(body.after_created_at, 'invalid_output_cursor', 64);
    cursorDate = new Date(timestamp);
    if (Number.isNaN(cursorDate.getTime())) fail(400, 'invalid_output_cursor');
    cursorId = uuid(body.after_record_id, 'invalid_output_cursor');
  }
  let query = database(OUTPUTS).where({ hashed_user_id: ownerHash, state: 'PENDING' })
    .whereNull('deleted_at');
  if (cursorDate) query = query.whereRaw('(created_at, id) > (?, ?::uuid)', [cursorDate, cursorId]);
  const rows = await query.orderBy('created_at', 'asc').orderBy('id', 'asc')
    .limit(MAX_AVAILABLE_JOBS).select(['id', 'created_at', 'root_chat_id', 'root_hashed_team_id',
      'target_chat_id', 'turn_id', 'subject_id', 'output_kind', 'output_version',
      'chat_key_version', 'message_role', 'payload_storage']);
  const available = [];
  for (const row of rows) {
    try {
      const root = await authorizedOutputChat(database, row.root_chat_id, ownerHash, false);
      const target = await authorizedOutputChat(database, row.target_chat_id, ownerHash, false);
      if ((root.hashed_team_id || null) !== (row.root_hashed_team_id || null)
        || (target.hashed_team_id || null) !== (root.hashed_team_id || null)) continue;
      const { id, created_at: _createdAt, ...metadata } = row;
      available.push({ record_id: id, ...metadata });
    } catch (error) {
      if (!(error instanceof ProtocolError) || error.code !== 'chat_not_found') throw error;
    }
  }
  const last = rows.at(-1);
  return { outputs: available, next_cursor: rows.length === MAX_AVAILABLE_JOBS
    ? { after_created_at: new Date(last.created_at).toISOString(), after_record_id: last.id }
    : null };
}

async function getPendingOutput(database, raw) {
  const body = operationBody(raw, 'get_pending_output');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  string(body.device_hash, 'invalid_device', 128);
  const recordId = uuid(body.record_id, 'invalid_record_id');
  const row = await database(OUTPUTS).where({ id: recordId, hashed_user_id: ownerHash, state: 'PENDING' }).first();
  if (!row) fail(404, 'recovery_output_not_found');
  const root = await authorizedOutputChat(database, row.root_chat_id, ownerHash, false);
  const chat = await authorizedOutputChat(database, row.target_chat_id, ownerHash, false);
  if ((root.hashed_team_id || null) !== (row.root_hashed_team_id || null)
    || (chat.hashed_team_id || null) !== (root.hashed_team_id || null)) fail(404, 'recovery_output_not_found');
  return {
    record_id: row.id, root_chat_id: row.root_chat_id,
    root_hashed_team_id: row.root_hashed_team_id || null,
    target_chat_id: row.target_chat_id,
    turn_id: row.turn_id, subject_id: row.subject_id, output_kind: row.output_kind,
    output_version: row.output_version, chat_key_version: row.chat_key_version,
    message_role: row.message_role,
    sealed_payload: row.sealed_payload, payload_storage: row.payload_storage,
    payload_s3_key: row.payload_s3_key, payload_size_bytes: row.payload_size_bytes,
    payload_verified_regions: row.payload_verified_regions,
    sealed_payload_digest: row.sealed_payload_digest,
    messages_v: chat.messages_v,
    metadata_v: chat.metadata_v,
    encrypted_chat_key: chat.encrypted_chat_key || null,
    encrypted_title: chat.encrypted_title || null,
  };
}

async function persistOutputMessage(database, raw, now) {
  const body = operationBody(raw, 'persist_output_message');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  string(body.device_hash, 'invalid_device', 128);
  const recordId = uuid(body.record_id, 'invalid_record_id');
  const expectedVersion = integer(body.expected_messages_v, 'invalid_message_version');
  const rawMessage = object(body.encrypted_user_message ?? body.encrypted_assistant_message);
  const ciphertextDigest = digest(rawMessage);
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, ownerHash);
    const row = await lockedOutputRecord(trx, recordId, ownerHash);
    if (!row || row.deleted_at) fail(404, 'recovery_output_not_found');
    if (row.output_kind !== 'message') fail(409, 'output_kind_mismatch');
    const { target: chat } = await authorizedOutputRecordChats(trx, row, ownerHash);
    if (row.state === 'ACKNOWLEDGED') {
      if (row.canonical_digest !== ciphertextDigest) fail(409, 'canonical_output_mismatch');
      return { record_id: row.id, state: row.state, target_chat_id: row.target_chat_id,
        committed_messages_v: chat.messages_v, idempotent: true };
    }
    if (row.state !== 'PENDING') fail(409, 'invalid_output_state');
    const role = row.message_role || 'assistant';
    if (role === 'user' ? body.encrypted_assistant_message !== undefined
      : body.encrypted_user_message !== undefined) fail(409, 'message_role_mismatch');
    const message = validateMessage(rawMessage, role, {
      chatId: row.target_chat_id, ownerHash,
    });
    if (message.client_message_id !== row.subject_id) fail(409, 'message_identity_mismatch');
    if (row.target_chat_id !== row.root_chat_id && !chat.encrypted_chat_key) {
      const wrappedKey = string(body.encrypted_chat_key, 'missing_child_chat_key', MAX_CONTENT_BYTES);
      const encryptedTitle = string(body.encrypted_title, 'missing_child_chat_title', MAX_CONTENT_BYTES);
      await trx(CHATS).where(outputChatScope(chat, ownerHash)).update({
        encrypted_chat_key: wrappedKey, encrypted_title: encryptedTitle,
      });
    } else if (row.target_chat_id !== row.root_chat_id && body.encrypted_chat_key
      && chat.encrypted_chat_key !== body.encrypted_chat_key) {
      fail(409, 'immutable_chat_key_mismatch');
    }
    const existing = await trx(MESSAGES).where({ client_message_id: row.subject_id }).forUpdate().first();
    let committedVersion = chat.messages_v;
    let idempotent = false;
    if (existing) {
      if (existing.chat_id !== row.target_chat_id || existing.hashed_user_id !== ownerHash
        || existing.role !== role) fail(409, 'message_identity_conflict');
      if (role === 'user' && row.output_version !== 1) fail(409, 'invalid_user_source_revision');
      const currentRevision = Number(existing.assistant_source_revision || 1);
      if (currentRevision > row.output_version) fail(409, 'stale_assistant_source_revision');
      const exactCanonicalMessage = currentRevision === row.output_version
        && existing.encrypted_content === message.encrypted_content
        && (existing.encrypted_sender_name || null) === (message.encrypted_sender_name || null)
        && (existing.encrypted_category || null) === (message.encrypted_category || null)
        && (existing.encrypted_model_name || null) === (message.encrypted_model_name || null)
        && Number(existing.created_at) === Number(message.created_at)
        && Number(existing.updated_at) === Number(message.updated_at);
      if (exactCanonicalMessage) {
        idempotent = true;
      } else {
        if (currentRevision !== row.output_version
          && currentRevision + 1 !== row.output_version) fail(409, 'missing_assistant_source_revision');
        if (chat.messages_v !== expectedVersion) fail(409, 'version_conflict');
        const revisionUpdate = trx(MESSAGES).where({
          client_message_id: row.subject_id, chat_id: row.target_chat_id,
          hashed_user_id: ownerHash,
        });
        if (existing.assistant_source_revision == null) revisionUpdate.whereNull('assistant_source_revision');
        else revisionUpdate.where({ assistant_source_revision: currentRevision });
        const updated = await revisionUpdate.update({
          encrypted_content: message.encrypted_content,
          encrypted_sender_name: message.encrypted_sender_name,
          encrypted_category: message.encrypted_category,
          encrypted_model_name: message.encrypted_model_name,
          created_at: message.created_at,
          updated_at: message.updated_at,
          assistant_source_revision: role === 'assistant' ? row.output_version : null,
        });
        if (updated !== 1) fail(409, 'assistant_source_revision_conflict');
        committedVersion = expectedVersion + 1;
        const timestamp = Math.floor(now.getTime() / 1000);
        if (await trx(CHATS).where({ ...outputChatScope(chat, ownerHash),
          messages_v: expectedVersion }).update({
          messages_v: committedVersion, updated_at: timestamp,
          last_edited_overall_timestamp: timestamp,
        }) !== 1) fail(409, 'version_conflict');
      }
    } else {
      if (row.output_version !== 1) fail(409, 'missing_assistant_source_revision');
      if (chat.messages_v !== expectedVersion) fail(409, 'version_conflict');
      await trx(MESSAGES).insert({ id: randomUUID(), ...message,
        assistant_source_revision: role === 'assistant' ? 1 : null });
      committedVersion = expectedVersion + 1;
      const timestamp = Math.floor(now.getTime() / 1000);
      if (await trx(CHATS).where({ ...outputChatScope(chat, ownerHash), messages_v: expectedVersion }).update({
        messages_v: committedVersion, updated_at: timestamp,
        last_edited_overall_timestamp: timestamp, last_message_timestamp: message.created_at,
      }) !== 1) fail(409, 'version_conflict');
    }
    await trx(OUTPUTS).where({ id: row.id, state: 'PENDING' }).update({
      state: 'ACKNOWLEDGED', acknowledged_at: now,
      canonical_digest: ciphertextDigest, sealed_payload: null,
    });
    return { record_id: row.id, state: 'ACKNOWLEDGED', target_chat_id: row.target_chat_id,
      committed_messages_v: committedVersion, idempotent };
  });
}

async function persistOutputSummary(database, raw, now) {
  const body = operationBody(raw, 'persist_output_summary');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  string(body.device_hash, 'invalid_device', 128);
  const recordId = uuid(body.record_id, 'invalid_record_id');
  const expectedVersion = integer(body.expected_metadata_v, 'invalid_metadata_version');
  const encryptedSummary = string(body.encrypted_summary, 'invalid_encrypted_summary', MAX_CONTENT_BYTES);
  const ciphertextDigest = digest(encryptedSummary);
  return database.transaction(async (trx) => {
    const row = await lockedOutputRecord(trx, recordId, ownerHash);
    if (!row || row.deleted_at) fail(404, 'recovery_output_not_found');
    if (row.output_kind !== 'summary') fail(409, 'output_kind_mismatch');
    const { target: chat } = await authorizedOutputRecordChats(trx, row, ownerHash);
    if (row.state === 'ACKNOWLEDGED') {
      if (row.canonical_digest !== ciphertextDigest) fail(409, 'canonical_output_mismatch');
      return { record_id: recordId, state: 'ACKNOWLEDGED', target_chat_id: row.target_chat_id, idempotent: true };
    }
    if (row.state !== 'PENDING') fail(409, 'invalid_output_state');
    if (chat.metadata_v !== expectedVersion) fail(409, 'version_conflict');
    const updated = await trx(CHATS).where({
      ...outputChatScope(chat, ownerHash), metadata_v: expectedVersion,
    }).update({
      encrypted_chat_summary: encryptedSummary, metadata_v: expectedVersion + 1,
      updated_at: Math.floor(now.getTime() / 1000),
    });
    if (updated !== 1) fail(409, 'version_conflict');
    await trx(OUTPUTS).where({ id: recordId, state: 'PENDING' }).update({
      state: 'ACKNOWLEDGED', acknowledged_at: now,
      canonical_digest: ciphertextDigest, sealed_payload: null,
    });
    return { record_id: recordId, state: 'ACKNOWLEDGED', target_chat_id: row.target_chat_id,
      committed_metadata_v: expectedVersion + 1 };
  });
}

async function hasPendingChatOutputs(database, raw) {
  const body = operationBody(raw, 'has_pending_chat_outputs');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  const chatId = uuid(body.target_chat_id, 'invalid_target_chat_id');
  const row = await database(OUTPUTS).where({
    hashed_user_id: ownerHash, target_chat_id: chatId,
  }).whereIn('state', ['PREPARING', 'PENDING']).whereNull('deleted_at').first();
  const job = await database(JOBS).where({ hashed_user_id: ownerHash, chat_id: chatId })
    .whereIn('state', ['AVAILABLE', 'LEASED']).whereNull('invalidated_at').first();
  const inference = await database(PREFLIGHTS).where({
    hashed_user_id: ownerHash, chat_id: chatId, state: 'RUNNING',
  }).whereNull('deletion_invalidated_at').first();
  return { has_pending: !!(row || job || inference) };
}

async function acknowledgeOutputCheckpoint(database, raw, now) {
  const body = operationBody(raw, 'acknowledge_output_checkpoint');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  string(body.device_hash, 'invalid_device', 128);
  const recordId = uuid(body.record_id, 'invalid_record_id');
  const encryptedSummary = string(body.encrypted_summary, 'invalid_encrypted_summary', MAX_CONTENT_BYTES);
  const boundaryId = string(body.compressed_up_to_message_id, 'invalid_checkpoint_boundary', 255);
  const manifest = body.covered_message_ids ?? null;
  if (manifest !== null && (!Array.isArray(manifest) || manifest.length === 0
    || manifest.length > 20_000
    || manifest.some((id) => typeof id !== 'string' || id.length === 0 || id.length > 255)
    || manifest.some((id, index) => index > 0 && manifest[index - 1] >= id)
    || Buffer.byteLength(JSON.stringify(manifest), 'utf8') > 1_048_576)) {
    fail(400, 'invalid_checkpoint_manifest');
  }
  const ciphertextDigest = digest(encryptedSummary);
  return database.transaction(async (trx) => {
    const row = await lockedOutputRecord(trx, recordId, ownerHash);
    if (!row || row.deleted_at) fail(404, 'recovery_output_not_found');
    if (row.output_kind !== 'checkpoint') fail(409, 'output_kind_mismatch');
    await authorizedOutputRecordChats(trx, row, ownerHash);
    if (row.state === 'ACKNOWLEDGED') {
      if (row.canonical_digest !== ciphertextDigest) fail(409, 'canonical_output_mismatch');
      return { record_id: row.id, state: 'ACKNOWLEDGED', target_chat_id: row.target_chat_id, idempotent: true };
    }
    if (row.state !== 'PENDING') fail(409, 'invalid_output_state');
    const checkpoint = await trx(CHECKPOINTS).where({ id: row.subject_id }).first();
    const canonicalManifest = typeof checkpoint?.covered_message_ids === 'string'
      ? JSON.parse(checkpoint.covered_message_ids) : checkpoint?.covered_message_ids ?? null;
    if (!checkpoint || checkpoint.chat_id !== row.target_chat_id
      || checkpoint.hashed_user_id !== ownerHash
      || checkpoint.encrypted_summary !== encryptedSummary
      || checkpoint.compressed_up_to_message_id !== boundaryId
      || JSON.stringify(canonicalManifest) !== JSON.stringify(manifest)) {
      fail(409, 'canonical_checkpoint_mismatch');
    }
    await trx(OUTPUTS).where({ id: row.id, state: 'PENDING' }).update({
      state: 'ACKNOWLEDGED', acknowledged_at: now,
      canonical_digest: ciphertextDigest, sealed_payload: null,
    });
    return { record_id: row.id, state: 'ACKNOWLEDGED', target_chat_id: row.target_chat_id };
  });
}

async function acknowledgeOutputEmbed(database, raw, now) {
  const body = operationBody(raw, 'acknowledge_output_embed');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  string(body.device_hash, 'invalid_device', 128);
  const recordId = uuid(body.record_id, 'invalid_record_id');
  const canonicalDigest = hexDigest(body.canonical_digest, 'invalid_canonical_digest');
  const suppliedCanonicalSource = body.canonical_source == null
    ? null : string(body.canonical_source, 'invalid_canonical_source', 16);
  if (suppliedCanonicalSource && !['head', 'version_row'].includes(suppliedCanonicalSource)) {
    fail(400, 'invalid_canonical_source');
  }
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, ownerHash);
    const row = await lockedOutputRecord(trx, recordId, ownerHash);
    if (!row || row.deleted_at) fail(404, 'recovery_output_not_found');
    if (row.output_kind !== 'embed' && row.output_kind !== 'diff') fail(409, 'output_kind_mismatch');
    await authorizedOutputRecordChats(trx, row, ownerHash);
    const canonicalSource = suppliedCanonicalSource || (row.output_kind === 'diff' ? 'version_row' : 'head');
    if (row.state === 'ACKNOWLEDGED') {
      if (row.canonical_digest !== canonicalDigest) fail(409, 'canonical_output_mismatch');
      return { record_id: row.id, state: row.state, target_chat_id: row.target_chat_id, idempotent: true };
    }
    if (row.state !== 'PENDING') fail(409, 'invalid_output_state');
    const embed = await trx(EMBEDS).where({ embed_id: row.subject_id, hashed_user_id: ownerHash }).first();
    if (!embed || embed.hashed_chat_id !== hashIdentifier(row.target_chat_id)
      || !embed.encrypted_content || Number(embed.version_number || 1) < row.output_version) {
      fail(409, 'canonical_embed_missing');
    }
    const keySubject = embed.parent_embed_id || row.subject_id;
    const wrappers = await trx(EMBED_KEYS).where({
      hashed_embed_id: hashIdentifier(keySubject), hashed_user_id: ownerHash,
    }).select(['key_type', 'hashed_chat_id', 'encrypted_embed_key']);
    const masterWrapper = wrappers.some((key) => key.key_type === 'master' && key.encrypted_embed_key);
    const chatWrapper = wrappers.some((key) => key.key_type === 'chat'
      && key.hashed_chat_id === hashIdentifier(row.target_chat_id) && key.encrypted_embed_key);
    if (!masterWrapper || !chatWrapper) fail(409, 'canonical_embed_key_missing');
    if (row.output_kind === 'diff' && canonicalSource !== 'version_row') fail(409, 'canonical_source_mismatch');
    if (row.output_kind === 'embed' && canonicalSource === 'head'
      && Number(embed.version_number || 1) !== row.output_version) fail(409, 'canonical_embed_head_advanced');
    let persistedDigest = digest(embed.encrypted_content);
    if (row.output_kind === 'diff' || canonicalSource === 'version_row') {
      const diff = await trx(EMBED_DIFFS).where({
        embed_id: row.subject_id, version_number: row.output_version, hashed_user_id: ownerHash,
      }).first();
      if (!diff || !(diff.encrypted_snapshot || diff.encrypted_patch)) fail(409, 'canonical_diff_missing');
      persistedDigest = digest([diff.encrypted_snapshot || null, diff.encrypted_patch || null]);
    }
    if (persistedDigest !== canonicalDigest) fail(409, 'canonical_output_mismatch');
    await trx(OUTPUTS).where({ id: row.id, state: 'PENDING' }).update({
      state: 'ACKNOWLEDGED', acknowledged_at: now,
      canonical_digest: canonicalDigest, sealed_payload: null,
    });
    await maybeCompleteOutputProducer(trx, row.producer_intent_id, now);
    return { record_id: row.id, state: 'ACKNOWLEDGED', target_chat_id: row.target_chat_id };
  });
}

async function markChildLifecycle(database, raw, now, phase) {
  const body = operationBody(raw, phase);
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  const childChatId = uuid(body.child_chat_id, 'invalid_child_chat_id');
  const rootChatId = body.root_chat_id ? uuid(body.root_chat_id, 'invalid_root_chat_id') : null;
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, ownerHash);
    await lockRecoveryChats(trx, childChatId, rootChatId);
    const chat = await authorizedOutputChat(trx, childChatId, ownerHash);
    if (!chat.is_sub_chat || !chat.parent_id) {
      if (phase === 'mark_child_canonical_acknowledged') return { child_chat_id: childChatId, skipped: true };
      fail(409, 'not_child_chat');
    }
    const child = await trx(ORCHESTRATION_CHILDREN).where({ child_chat_id: childChatId }).first();
    const root = child && await trx(ORCHESTRATIONS).where({ id: child.orchestration_id }).first();
    if (!root || root.hashed_user_id !== ownerHash || (rootChatId && root.root_chat_id !== rootChatId)) {
      fail(409, 'child_recovery_identity_mismatch');
    }
    let field;
    if (phase === 'mark_child_result_delivered') {
      if (child.state !== 'completed') fail(409, 'child_not_completed');
      const message = await trx(OUTPUTS).where({
        hashed_user_id: ownerHash, target_chat_id: childChatId, output_kind: 'message',
      }).whereNull('deleted_at').first();
      if (!message) fail(409, 'sealed_child_result_missing');
      field = 'child_result_delivered_at';
    } else if (phase === 'mark_child_parent_consumed') {
      const batch = await trx(ORCHESTRATION_BATCHES).where({ id: child.batch_id }).first();
      const continuationTaskId = uuid(body.continuation_task_id, 'invalid_continuation_task_id');
      if (!chat.child_result_delivered_at || !batch?.continuation_dispatched_at
        || batch.continuation_task_id !== continuationTaskId
        || batch.parent_chat_id !== chat.parent_id) {
        fail(409, 'child_parent_not_consumed');
      }
      field = 'child_parent_consumed_at';
    } else {
      if (!chat.encrypted_chat_key) fail(409, 'child_key_not_acknowledged');
      const pending = await trx(OUTPUTS).where({
        hashed_user_id: ownerHash, target_chat_id: childChatId,
      }).whereIn('state', ['PREPARING', 'PENDING']).whereNull('deleted_at').first();
      const message = await trx(OUTPUTS).where({
        hashed_user_id: ownerHash, target_chat_id: childChatId,
        output_kind: 'message', state: 'ACKNOWLEDGED',
      }).whereNull('deleted_at').first();
      if (pending || !message) fail(409, 'child_canonical_ack_pending');
      field = 'child_canonical_acknowledged_at';
    }
    if (!chat[field]) await trx(CHATS).where(outputChatScope(chat, ownerHash)).update({ [field]: now });
    return { child_chat_id: childChatId, state: field, idempotent: !!chat[field] };
  });
}

async function listAvailableJobs(database, raw, now) {
  const body = operationBody(raw, 'list_available_jobs');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  string(body.device_hash, 'invalid_device', 128);
  const rows = await database(JOBS)
    .where({ hashed_user_id: ownerHash })
    .whereNull('invalidated_at')
    .andWhere(function availableOrExpiredLease() {
      this.where({ state: 'AVAILABLE' }).orWhere(function expiredLease() {
        this.where({ state: 'LEASED' }).andWhere('lease_expires_at', '<=', now);
      });
    })
    .orderBy('created_at', 'asc')
    .orderBy('id', 'asc')
    .limit(MAX_AVAILABLE_JOBS)
    .select([
      'id',
      'chat_id',
      'turn_id',
      'inference_task_id',
      'assistant_message_id',
      'chat_key_version',
      'state',
    ]);
  return { jobs: rows.map(availableJobMetadata) };
}

function activeJob(row, ownerHash, now) {
  if (!row || row.hashed_user_id !== ownerHash || row.invalidated_at) fail(404, 'recovery_job_not_found');
  // A pending sealed payload remains recoverable until canonical persistence.
  // The old seven-day job deadline cannot revoke the only durable copy.
  return row;
}
function verifyLease(row, body, now) {
  const generation = integer(body.lease_generation, 'invalid_lease_generation');
  const deviceHash = string(body.device_hash, 'invalid_device', 128);
  const leaseToken = string(body.lease_token, 'invalid_lease_token', 64);
  if (row.state !== 'LEASED' || row.lease_generation !== generation || row.lease_holder_hash !== deviceHash
    || row.lease_token_digest !== tokenDigest(leaseToken) || new Date(row.lease_expires_at) <= now) fail(409, 'stale_lease');
}

async function leaseJob(database, raw, now) {
  const body = operationBody(raw, 'lease_job');
  const jobId = uuid(body.job_id, 'invalid_job_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  const deviceHash = string(body.device_hash, 'invalid_device', 128);
  return database.transaction(async (trx) => {
    const row = activeJob(await trx(JOBS).where({ id: jobId }).forUpdate().first(), ownerHash, now);
    // A sealed payload belongs to the invoking user, but a Team chat also
    // requires that user to remain an active writer before recovery can read it.
    const chat = await authorizedOutputChat(trx, row.chat_id, ownerHash);
    if (row.state === 'TERMINAL') {
      return {
        job_id: row.id,
        state: 'TERMINAL',
        chat_id: row.chat_id,
        turn_id: row.turn_id,
        assistant_message_id: row.assistant_message_id,
        chat_key_version: row.chat_key_version,
        committed_messages_v: chat.messages_v,
      };
    }
    if (row.state === 'LEASED' && new Date(row.lease_expires_at) > now) fail(409, 'lease_conflict');
    const sameHolder = row.lease_holder_hash === deviceHash;
    const tenureStarted = sameHolder && row.tenure_started_at ? new Date(row.tenure_started_at) : now;
    if (sameHolder && now.getTime() >= tenureStarted.getTime() + MAX_TENURE_MS) fail(409, 'lease_tenure_exhausted');
    const leaseExpires = new Date(Math.min(now.getTime() + LEASE_MS, tenureStarted.getTime() + MAX_TENURE_MS));
    const leaseToken = randomBytes(32).toString('base64url');
    const generation = row.lease_generation + 1;
    await trx(JOBS).where({ id: row.id, lease_generation: row.lease_generation }).update({
      state: 'LEASED', lease_generation: generation, lease_token_digest: tokenDigest(leaseToken),
      lease_holder_hash: deviceHash, lease_expires_at: leaseExpires, tenure_started_at: tenureStarted,
    });
    return {
      job_id: row.id, state: 'LEASED', lease_token: leaseToken, lease_generation: generation,
      lease_expires_at: leaseExpires, sealed_payload: row.sealed_payload, chat_id: row.chat_id,
      turn_id: row.turn_id, assistant_message_id: row.assistant_message_id, chat_key_version: row.chat_key_version,
    };
  });
}

async function renewLease(database, raw, now) {
  const body = operationBody(raw, 'renew_lease');
  const jobId = uuid(body.job_id, 'invalid_job_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  return database.transaction(async (trx) => {
    const row = activeJob(await trx(JOBS).where({ id: jobId }).forUpdate().first(), ownerHash, now);
    await authorizedOutputChat(trx, row.chat_id, ownerHash);
    verifyLease(row, body, now);
    const tenureEnd = new Date(row.tenure_started_at).getTime() + MAX_TENURE_MS;
    if (now.getTime() >= tenureEnd) fail(409, 'lease_tenure_exhausted');
    const leaseExpires = new Date(Math.min(now.getTime() + LEASE_MS, tenureEnd));
    await trx(JOBS).where({ id: row.id, lease_generation: row.lease_generation }).update({ lease_expires_at: leaseExpires });
    return { job_id: row.id, state: row.state, lease_generation: row.lease_generation, lease_expires_at: leaseExpires };
  });
}

async function persistTerminal(database, raw, now) {
  const body = operationBody(raw, 'persist_terminal');
  const jobId = uuid(body.job_id, 'invalid_job_id');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  const expectedVersion = integer(body.expected_messages_v, 'invalid_message_version');
  const rawMessage = object(body.encrypted_assistant_message);
  const ciphertextDigest = digest(rawMessage);
  return database.transaction(async (trx) => {
    const snapshot = await trx(JOBS).where({ id: jobId }).first();
    if (!snapshot || snapshot.hashed_user_id !== ownerHash) fail(404, 'recovery_job_not_found');
    await requireUnfencedRecoveryAccount(trx, ownerHash);
    await lockRecoveryChats(trx, snapshot.chat_id);
    const row = activeJob(await trx(JOBS).where({ id: jobId }).forUpdate().first(), ownerHash, now);
    const chat = await authorizedOutputChat(trx, row.chat_id, ownerHash);
    if (row.state === 'TERMINAL') {
      if (row.terminal_ciphertext_digest !== ciphertextDigest || row.assistant_message_id !== rawMessage.client_message_id) fail(409, 'terminal_identity_mismatch');
      return { job_id: row.id, state: 'TERMINAL', idempotent: true };
    }
    verifyLease(row, body, now);
    const message = validateMessage(rawMessage, 'assistant', { chatId: row.chat_id, ownerHash });
    if (message.client_message_id !== row.assistant_message_id) fail(409, 'message_identity_mismatch');
    const existingMessage = await trx(MESSAGES).where({ client_message_id: row.assistant_message_id }).first();
    if (existingMessage) {
      if (existingMessage.chat_id !== row.chat_id || existingMessage.hashed_user_id !== ownerHash || existingMessage.role !== 'assistant') fail(409, 'message_identity_conflict');
      await trx(JOBS).where({ id: row.id, lease_generation: row.lease_generation }).update({
        state: 'TERMINAL', sealed_payload: null, sealed_payload_digest: null,
        lease_token_digest: null, lease_holder_hash: null, lease_expires_at: null, tenure_started_at: null,
        terminal_ciphertext_digest: ciphertextDigest, completed_at: now,
        tombstone_expires_at: new Date(now.getTime() + TOMBSTONE_TTL_MS),
      });
      await trx(PREFLIGHTS).where({ id: row.preflight_id }).update({ state: 'TERMINAL', terminal_at: now });
      return { job_id: row.id, state: 'TERMINAL', idempotent: true, committed_messages_v: chat.messages_v };
    }
    if (chat.messages_v !== expectedVersion) fail(409, 'version_conflict');
    await trx(MESSAGES).insert({ id: randomUUID(), ...message });
    const committedVersion = expectedVersion + 1;
    const timestamp = Math.floor(now.getTime() / 1000);
    if (await trx(CHATS).where({ ...outputChatScope(chat, ownerHash), messages_v: expectedVersion }).update({
      messages_v: committedVersion, updated_at: timestamp, last_edited_overall_timestamp: timestamp,
      last_message_timestamp: message.created_at,
    }) !== 1) fail(409, 'version_conflict');
    await trx(JOBS).where({ id: row.id, lease_generation: row.lease_generation }).update({
      state: 'TERMINAL', sealed_payload: null, sealed_payload_digest: null,
      lease_token_digest: null, lease_holder_hash: null, lease_expires_at: null, tenure_started_at: null,
      terminal_ciphertext_digest: ciphertextDigest, completed_at: now,
      tombstone_expires_at: new Date(now.getTime() + TOMBSTONE_TTL_MS),
    });
    await trx(PREFLIGHTS).where({ id: row.preflight_id }).update({ state: 'TERMINAL', terminal_at: now });
    return { job_id: row.id, state: 'TERMINAL', idempotent: false, committed_messages_v: committedVersion };
  });
}

async function invalidateRecoveryState(trx, ownerHash, chatId, now, teamHash = null) {
    const batchScope = teamHash ? { hashed_team_id: teamHash } : { hashed_user_id: ownerHash };
    const batchQuery = trx(LEGACY_BATCH_CLAIMS)
      .where(batchScope).whereIn('state', ['PREPARED', 'CLAIMED']);
    if (chatId) batchQuery.andWhere({ chat_id: chatId });
    else batchQuery.whereNull('hashed_team_id');
    const invalidatedLegacyBatches = await batchQuery.update({
      state: 'INVALIDATED', invalidated_at: now,
    });
    const producerScope = teamHash ? { hashed_team_id: teamHash } : { hashed_user_id: ownerHash };
    let invalidatedProducers = 0;
    if (chatId) {
      invalidatedProducers += await trx(OUTPUT_PRODUCERS).where(producerScope)
        .where({ root_chat_id: chatId, state: 'PENDING' })
        .update({ state: 'INVALIDATED', invalidated_at: now });
      invalidatedProducers += await trx(OUTPUT_PRODUCERS).where(producerScope)
        .where({ target_chat_id: chatId, state: 'PENDING' })
        .update({ state: 'INVALIDATED', invalidated_at: now });
    } else {
      invalidatedProducers = await trx(OUTPUT_PRODUCERS)
        .where({ hashed_user_id: ownerHash, state: 'PENDING' })
        .update({ state: 'INVALIDATED', invalidated_at: now });
    }
    const rerenderScope = teamHash ? { hashed_team_id: teamHash } : { hashed_user_id: ownerHash };
    const rerenderQuery = trx(AUTHORIZED_RERENDERS)
      .where(rerenderScope).whereIn('state', ['PENDING', 'RUNNING']);
    if (chatId) rerenderQuery.andWhere({ target_chat_id: chatId });
    const invalidatedRerenders = await rerenderQuery.update({ state: 'INVALIDATED', invalidated_at: now });
    const directScope = teamHash ? { hashed_team_id: teamHash } : { hashed_user_id: ownerHash };
    const directQuery = trx(AUTHORIZED_DIRECT_SKILLS)
      .where(directScope).whereIn('state', ['PENDING', 'RUNNING']);
    if (chatId) directQuery.andWhere({ target_chat_id: chatId });
    else directQuery.whereNull('hashed_team_id');
    const invalidatedDirectSkills = await directQuery.update({ state: 'INVALIDATED', invalidated_at: now });
    const legacyScope = teamHash ? { hashed_team_id: teamHash } : { hashed_user_id: ownerHash };
    const legacyBase = () => trx(LEGACY_OUTPUT_PRODUCERS)
      .where(legacyScope).whereIn('state', ['PENDING', 'RUNNING']);
    let invalidatedLegacyProducers = 0;
    if (chatId) {
      invalidatedLegacyProducers += await legacyBase().where({ root_chat_id: chatId })
        .update({ state: 'INVALIDATED', invalidated_at: now });
      invalidatedLegacyProducers += await legacyBase().where({ target_chat_id: chatId })
        .update({ state: 'INVALIDATED', invalidated_at: now });
    } else {
      invalidatedLegacyProducers = await legacyBase().whereNull('hashed_team_id')
        .update({ state: 'INVALIDATED', invalidated_at: now });
    }
    // A Team deletion invalidates every member's work for this globally unique
    // chat ID. A personal or account invalidation remains owner scoped.
    const scope = teamHash ? { chat_id: chatId } : { hashed_user_id: ownerHash };
    const preflights = trx(PREFLIGHTS).where(scope);
    const jobs = trx(JOBS).where(scope);
    const outbox = trx(OUTBOX).where(scope);
    if (chatId && !teamHash) { preflights.andWhere({ chat_id: chatId }); jobs.andWhere({ chat_id: chatId }); outbox.andWhere({ chat_id: chatId }); }
    const metadataJobs = trx(METADATA_JOBS).where(scope);
    if (chatId && !teamHash) metadataJobs.andWhere({ chat_id: chatId });
    const deletedMetadataJobs = await metadataJobs.delete();
    const deletedJobs = await jobs.delete();
    if (deletedJobs > 0) {
      await trx(OPERATIONAL_EVENTS).insert({
        id: randomUUID(), event_type: 'recovery_jobs_invalidated', count: deletedJobs, occurred_at: now,
      });
    }
    const deletedOutbox = await outbox.delete();
    const deletedPreflights = await preflights.delete();
    let invalidatedOutputs = 0;
    if (chatId) {
      const outputScope = teamHash ? { root_hashed_team_id: teamHash } : { hashed_user_id: ownerHash };
      invalidatedOutputs += await trx(OUTPUTS).where({ ...outputScope, root_chat_id: chatId })
        .whereNull('deleted_at').update({ state: 'DELETED', deleted_at: now });
      invalidatedOutputs += await trx(OUTPUTS).where({ ...outputScope, target_chat_id: chatId })
        .whereNull('deleted_at').update({ state: 'DELETED', deleted_at: now });
    } else {
      invalidatedOutputs = await trx(OUTPUTS).where({ hashed_user_id: ownerHash })
        .whereNull('root_hashed_team_id')
        .whereNull('deleted_at').update({ state: 'DELETED', deleted_at: now });
    }
    return { deleted_preflights: deletedPreflights, deleted_jobs: deletedJobs,
      deleted_metadata_jobs: deletedMetadataJobs, deleted_outbox: deletedOutbox,
      invalidated_outputs: invalidatedOutputs,
      invalidated_producers: invalidatedProducers,
      invalidated_rerenders: invalidatedRerenders,
      invalidated_direct_skills: invalidatedDirectSkills,
      invalidated_legacy_producers: invalidatedLegacyProducers,
      invalidated_legacy_batches: invalidatedLegacyBatches };
}

async function invalidateDeletion(database, raw, now) {
  const body = operationBody(raw, 'invalidate_deletion');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  const scope = string(body.scope, 'invalid_invalidation_scope', 16);
  if (!['chat', 'account', 'device'].includes(scope)) fail(400, 'invalid_invalidation_scope');
  const chatId = scope === 'chat' ? uuid(body.chat_id, 'invalid_chat_id') : null;
  const deviceHash = scope === 'device' ? string(body.device_hash, 'invalid_device', 128) : null;
  return database.transaction(async (trx) => {
    if (scope === 'device') {
      const count = await trx(JOBS).where({ hashed_user_id: ownerHash, lease_holder_hash: deviceHash, state: 'LEASED' }).update({
        state: 'AVAILABLE', lease_generation: trx.raw('lease_generation + 1'), lease_token_digest: null,
        lease_holder_hash: null, lease_expires_at: null, tenure_started_at: null,
      });
      return { invalidated_leases: count };
    }
    await lockIdentity(trx, `account-recovery:${ownerHash}`);
    if (scope === 'account') {
      await assertNoPendingTeamAccountRecovery(trx, ownerHash);
      if (!await trx(ACCOUNT_FENCES).where({ id: ownerHash }).first()) {
        await trx(ACCOUNT_FENCES).insert({ id: ownerHash, fenced_at: now });
      }
    } else {
      await lockIdentity(trx, `chat-recovery-delete:${chatId}`);
      const chat = await trx(CHATS).where({ id: chatId }).first();
      const prior = await trx(CHAT_DELETION_FENCES).where({ id: chatId }).first();
      if (!chat && !prior) fail(404, 'chat_not_found');
      if (chat && prior && (chat.hashed_team_id || null) !== (prior.hashed_team_id || null)) {
        fail(404, 'chat_not_found');
      }
      const teamHash = chat?.hashed_team_id || prior?.hashed_team_id || null;
      if (teamHash) {
        // The actor who created the durable fence may finish an interrupted
        // cleanup after losing Team membership; the fence cannot be planted
        // without original authority and conveys no chat contents.
        if (!prior || prior.hashed_user_id !== ownerHash) {
          await authorizedTeamDeleter(trx, teamHash, ownerHash, chat?.hashed_user_id);
        }
      } else if ((chat && chat.hashed_user_id !== ownerHash)
        || (prior && prior.hashed_user_id !== ownerHash)) {
        fail(404, 'chat_not_found');
      }
      if (!prior) {
        await trx(CHAT_DELETION_FENCES).insert({
          id: chatId, hashed_user_id: ownerHash, hashed_team_id: teamHash,
          chat_id: chatId, fenced_at: now,
        });
      }
      return {
        ...await invalidateRecoveryState(trx, ownerHash, chatId, now, teamHash),
        chat_deletion_fenced: true,
        chat_id: chatId,
      };
    }
    return invalidateRecoveryState(trx, ownerHash, chatId, now);
  });
}

async function invalidateRewind(database, raw, now) {
  const body = operationBody(raw, 'invalidate_rewind');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  const chatId = uuid(body.chat_id, 'invalid_chat_id');
  return database.transaction(async (trx) => {
    await requireUnfencedRecoveryAccount(trx, ownerHash);
    await lockIdentity(trx, `chat-recovery-delete:${chatId}`);
    const chat = await trx(CHATS).where({ id: chatId }).first();
    if (!chat || chat.hashed_user_id !== ownerHash || chat.hashed_team_id) fail(404, 'chat_not_found');
    if (await trx(CHAT_DELETION_FENCES).where({ id: chatId }).first()) {
      fail(404, 'chat_not_found');
    }
    return invalidateRecoveryState(trx, ownerHash, chatId, now);
  });
}

async function lookupChatDeletionFences(database, raw) {
  const body = operationBody(raw, 'lookup_chat_deletion_fences');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  if (!Array.isArray(body.chat_ids) || body.chat_ids.length > MAX_CHAT_FENCE_LOOKUP) {
    fail(400, 'invalid_chat_ids');
  }
  const chatIds = body.chat_ids.map((id) => uuid(id, 'invalid_chat_id'));
  if (new Set(chatIds).size !== chatIds.length) fail(400, 'duplicate_chat_id');
  if (!chatIds.length) return { fenced_chat_ids: [] };
  const rows = await database(CHAT_DELETION_FENCES)
    .whereIn('id', chatIds).select(['chat_id', 'hashed_user_id', 'hashed_team_id']);
  const fenced = new Set();
  for (const row of rows) {
    if (!row.hashed_team_id) {
      if (row.hashed_user_id === ownerHash) fenced.add(row.chat_id);
      continue;
    }
    try {
      await authorizedTeamWriter(database, row.hashed_team_id, ownerHash, false);
      fenced.add(row.chat_id);
    } catch (error) {
      if (!(error instanceof ProtocolError && error.code === 'chat_not_found')) throw error;
    }
  }
  return { fenced_chat_ids: chatIds.filter((id) => fenced.has(id)) };
}

async function cleanupExpired(database, raw, now) {
  const body = operationBody(raw, 'cleanup_expired');
  if ('failure_alerts_enabled' in body && typeof body.failure_alerts_enabled !== 'boolean') {
    fail(400, 'invalid_request');
  }
  const failureAlertsEnabled = body.failure_alerts_enabled === true;
  return database.transaction(async (trx) => {
    const protocolState = await lockedProtocolState(trx);
    const prunedLegacy = pruneExpiredLegacyState(protocolState, now);
    if (prunedLegacy.changed) {
      await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update(
        legacyStateUpdate(prunedLegacy.activeTasks, prunedLegacy.lifecycle),
      );
    }
    // Lock the preflights before inspecting sealed jobs, matching the writer's
    // preflight-first serialization point for new sealed jobs.
    const expiredRows = await trx(PREFLIGHTS).whereIn('state', ['PREPARED', 'ENQUEUED', 'RUNNING'])
      .andWhere('expires_at', '<=', now).forUpdate().select([
        'id', 'state', 'inference_task_id',
      ]);
    const preparedIds = expiredRows.filter((row) => row.state === 'PREPARED').map((row) => row.id);
    const malformedEnqueuedIds = expiredRows
      .filter((row) => row.state === 'ENQUEUED' && !row.inference_task_id).map((row) => row.id);
    const expiredEnqueuedIds = expiredRows
      .filter((row) => row.state === 'ENQUEUED' && row.inference_task_id).map((row) => row.id);
    const runningIds = expiredRows.filter((row) => row.state === 'RUNNING').map((row) => row.id);
    const sealedPreflightIds = runningIds.length
      ? await trx(JOBS).whereIn('preflight_id', runningIds).pluck('preflight_id')
      : [];
    const activeProducerPreflightIds = runningIds.length
      ? await trx(OUTPUT_PRODUCERS).whereIn('preflight_id', runningIds)
        .where({ state: 'PENDING' }).pluck('preflight_id')
      : [];
    // A detached producer can outlive the root inference job. Its immutable
    // intent keeps the original key/identity row alive until recovery or an
    // explicit deletion/rewind, even after the ordinary worker deadline.
    const workerTimeoutIds = unsealedPreflightIds(runningIds,
      [...sealedPreflightIds, ...activeProducerPreflightIds]);
    const abandonedIds = [...preparedIds, ...malformedEnqueuedIds];
    const abandonedPreflights = abandonedIds.length
      ? await trx(PREFLIGHTS).whereIn('id', abandonedIds).update({ state: 'ABANDONED' })
      : 0;
    const expiredEnqueued = expiredEnqueuedIds.length
      ? await trx(PREFLIGHTS).whereIn('id', expiredEnqueuedIds).update({
        state: 'FAILED', failed_at: now, failure_category: 'claim_expired',
        failure_alert_pending_at: now,
      })
      : 0;
    const workerTimeouts = workerTimeoutIds.length
      ? await trx(PREFLIGHTS).whereIn('id', workerTimeoutIds).update({
        state: 'FAILED', failed_at: now, failure_category: 'worker_timeout',
        failure_alert_pending_at: now,
      })
      : 0;
    if (abandonedIds.length) await trx(OUTBOX).whereIn('preflight_id', abandonedIds).where({ state: 'PENDING' }).delete();
    if (expiredEnqueuedIds.length) await trx(OUTBOX).whereIn('preflight_id', expiredEnqueuedIds).update({
      state: 'FAILED', last_error_category: 'claim_expired',
    });
    if (workerTimeoutIds.length) await trx(OUTBOX).whereIn('preflight_id', workerTimeoutIds).update({
      state: 'FAILED', last_error_category: 'worker_timeout',
    });
    const expiringJobPreflightIds = await trx(JOBS).whereIn('state', ['AVAILABLE', 'LEASED'])
      .andWhere('expires_at', '<=', now).pluck('preflight_id');
    if (expiringJobPreflightIds.length) {
      const protectedIds = await trx(OUTPUT_PRODUCERS)
        .whereIn('preflight_id', expiringJobPreflightIds)
        .where({ state: 'PENDING' }).pluck('preflight_id');
      await trx(PREFLIGHTS).whereIn('id', expiringJobPreflightIds)
        .whereNotIn('id', protectedIds).where({ state: 'RUNNING' })
        .update({ state: 'ABANDONED' });
    }
    const failureAlertCandidates = failureAlertsEnabled
      ? await trx(PREFLIGHTS)
        .where({ state: 'FAILED' })
        .whereNotIn('failure_category', [...EXPECTED_FAILURE_CATEGORIES])
        .whereNotNull('failure_alert_pending_at')
        .whereNull('failure_alert_queued_at')
        .whereNull('deletion_invalidated_at')
        .whereNotNull('inference_task_id')
        .orderBy('failed_at', 'asc')
        .orderBy('id', 'asc')
        .limit(MAX_FAILURE_ALERT_CANDIDATES)
        .select(['id', 'inference_task_id', 'chat_id', 'user_message_id', 'failure_category'])
      : [];
    return {
      expired_metadata_jobs: await trx(METADATA_JOBS).where({ state: 'AVAILABLE' }).andWhere('expires_at', '<=', now).delete(),
      expired_metadata_tombstones: await trx(METADATA_JOBS).whereIn('state', ['TERMINAL', 'SUPERSEDED']).andWhere('tombstone_expires_at', '<=', now).delete(),
      // Lease expiry is only a claim fence; it cannot delete pending user data.
      expired_jobs: 0,
      expired_tombstones: await trx(JOBS).where({ state: 'TERMINAL' }).andWhere('tombstone_expires_at', '<=', now).delete(),
      abandoned_preflights: abandonedPreflights,
      failed_inferences: expiredEnqueued + workerTimeouts,
      failure_alert_candidates: failureAlertCandidates.map((row) => ({
        preflight_id: row.id,
        inference_task_id: row.inference_task_id,
        chat_id: row.chat_id,
        user_message_id: row.user_message_id,
        failure_category: row.failure_category,
      })),
      expired_outbox: await trx(OUTBOX).whereIn('state', ['DISPATCHED', 'FAILED'])
        .andWhere('created_at', '<=', new Date(now.getTime() - PREFLIGHT_TTL_MS)).delete(),
      ...prunedLegacy.counts,
    };
  });
}

async function acknowledgeFailureAlert(database, raw, now) {
  const body = operationBody(raw, 'acknowledge_failure_alert');
  const preflightId = uuid(body.preflight_id, 'invalid_preflight_id');
  const taskId = uuid(body.inference_task_id, 'invalid_task_id');
  const category = string(body.failure_category, 'invalid_failure_category', 64);
  if (!/^[a-z0-9][a-z0-9_:-]*$/.test(category)) fail(400, 'invalid_failure_category');
  if (EXPECTED_FAILURE_CATEGORIES.has(category)) fail(409, 'failure_alert_state_mismatch');
  return database.transaction(async (trx) => {
    const row = await trx(PREFLIGHTS).where({ id: preflightId }).forUpdate().first();
    if (!row || row.inference_task_id !== taskId) fail(404, 'failure_alert_not_found');
    if (row.state !== 'FAILED' || row.failure_category !== category || !row.failure_alert_pending_at
      || row.deletion_invalidated_at) {
      fail(409, 'failure_alert_state_mismatch');
    }
    if (row.failure_alert_queued_at) {
      return { preflight_id: preflightId, acknowledged: false, idempotent: true };
    }
    const updated = await trx(PREFLIGHTS).where({
      id: preflightId,
      inference_task_id: taskId,
      state: 'FAILED',
      failure_category: category,
    }).whereNull('failure_alert_queued_at').update({ failure_alert_queued_at: now });
    if (updated !== 1) fail(409, 'failure_alert_ack_conflict');
    return { preflight_id: preflightId, acknowledged: true, idempotent: false };
  });
}

export const operations = Object.freeze({
  ...metadataOperations({ fail, exactKeys, string, uuid, integer, validateEnvelope, digest, ownedChat,
    JOB_TTL_MS, TOMBSTONE_TTL_MS }),
  prepare_preflight: preparePreflight, verify_committed_team_message: verifyCommittedTeamMessage,
  enqueue_inference: enqueueInference,
  claim_inference: claimInference, mark_outbox_dispatched: markOutboxDispatched,
  mark_inference_failed: markInferenceFailed,
  create_sealed_job: createSealedJob, list_available_jobs: listAvailableJobs,
  register_output_producer: registerOutputProducer,
  register_legacy_output_producer: registerLegacyOutputProducer,
  verify_volatile_output_actor: verifyVolatileOutputActor,
  register_authorized_rerender: registerAuthorizedRerender,
  register_authorized_direct_skill: registerAuthorizedDirectSkill,
  complete_authorized_direct_skill: completeAuthorizedDirectSkill,
  complete_authorized_standalone_asset: completeAuthorizedStandaloneAsset,
  complete_authorized_rerender: completeAuthorizedRerender,
  complete_authorized_direct_by_embed: completeAuthorizedDirectByEmbed,
  claim_authorized_direct_producer: claimAuthorizedDirectProducer,
  verify_claimed_output_producer: verifyClaimedOutputProducer,
  reconcile_authorized_direct_completions: reconcileAuthorizedDirectCompletions,
  resolve_output_producer: resolveOutputProducer,
  register_output_producer_child: registerOutputProducerChild,
  close_output_producer: closeOutputProducer,
  classify_untagged_output_producer: classifyUntaggedOutputProducer,
  get_producer_output: getProducerOutput,
  get_replay_output: getReplayOutput,
  create_sealed_output: createSealedOutput, list_pending_outputs: listPendingOutputs,
  prepare_sealed_output: (database, raw, now) => createSealedOutput(database, raw, now, true),
  get_pending_output: getPendingOutput,
  persist_output_message: persistOutputMessage,
  persist_output_summary: persistOutputSummary,
  has_pending_chat_outputs: hasPendingChatOutputs,
  acknowledge_output_checkpoint: acknowledgeOutputCheckpoint,
  acknowledge_output_embed: acknowledgeOutputEmbed,
  mark_child_result_delivered: (database, raw, now) => markChildLifecycle(database, raw, now, 'mark_child_result_delivered'),
  mark_child_parent_consumed: (database, raw, now) => markChildLifecycle(database, raw, now, 'mark_child_parent_consumed'),
  mark_child_canonical_acknowledged: (database, raw, now) => markChildLifecycle(database, raw, now, 'mark_child_canonical_acknowledged'),
  lease_job: leaseJob, renew_lease: renewLease,
  persist_terminal: persistTerminal, invalidate_deletion: invalidateDeletion,
  invalidate_rewind: invalidateRewind, lookup_chat_deletion_fences: lookupChatDeletionFences,
  cleanup_expired: cleanupExpired, acknowledge_failure_alert: acknowledgeFailureAlert,
  get_cutover_state: getCutoverState, set_sends_paused: setSendsPaused,
  admit_legacy_inference: admitLegacyInference,
  bind_ordinary_legacy_dispatch: bindOrdinaryLegacyDispatch,
  claim_legacy_inference_start: claimLegacyInferenceStart,
  prepare_legacy_batch: prepareLegacyBatch,
  claim_legacy_batch: claimLegacyBatch,
  mark_legacy_inference_completed: markLegacyInferenceCompleted,
  acknowledge_legacy_persistence: acknowledgeLegacyPersistence,
  authorize_legacy_completion: authorizeLegacyCompletion,
  release_legacy_inference: releaseLegacyInference,
  activate_protocol_epoch: activateProtocolEpoch,
});
export async function executeOperation(database, operation, body, now = new Date()) {
  const handler = operations[operation];
  if (!handler) fail(400, 'unsupported_operation');
  return handler(database, body, now);
}
export const testing = Object.freeze({
  digest, validateEnvelope, validateMessage, validateNewChatMetadata, inferenceClaimDecision,
  unsealedPreflightIds, availableJobMetadata,
  PROTOCOL_VERSION, LEASE_MS, MAX_TENURE_MS, LEGACY_RUNNING_TTL_MS, LEGACY_TOMBSTONE_TTL_MS,
});
