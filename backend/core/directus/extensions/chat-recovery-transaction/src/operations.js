/*
 * Internal persistence state machine for encrypted chat completion recovery.
 * Durable content-bearing values are ciphertext, sealed envelopes, or digests.
 */
import { createHash, randomBytes, randomUUID } from 'node:crypto';

const PREFLIGHTS = 'chat_turn_preflights';
const JOBS = 'chat_completion_recovery_jobs';
const OUTBOX = 'chat_inference_outbox';
const CHATS = 'chats';
const MESSAGES = 'messages';
const PROTOCOL_STATE = 'chat_recovery_protocol_state';
const PROTOCOL_STATE_ID = 'chat-recovery';
const PROTOCOL_VERSION = 1;
const LEASE_MS = 60_000;
const MAX_TENURE_MS = 5 * 60_000;
const PREFLIGHT_TTL_MS = 24 * 60 * 60_000;
const JOB_TTL_MS = 7 * 24 * 60 * 60_000;
const TOMBSTONE_TTL_MS = 24 * 60 * 60_000;
const LEGACY_RUNNING_TTL_MS = 15 * 60_000;
const LEGACY_TOMBSTONE_TTL_MS = 24 * 60 * 60_000;
const MAX_CONTENT_BYTES = 16 * 1024 * 1024;
const MAX_AVAILABLE_JOBS = 100;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HEX_64_RE = /^[0-9a-f]{64}$/;
const BASE64URL_RE = /^[A-Za-z0-9_-]+$/;
const LEGACY_LIFECYCLE_STATES = new Set(['RUNNING', 'AWAITING_PERSISTENCE', 'PERSISTED']);
const LEGACY_LIFECYCLE_FIELDS = new Set([
  'task_identity', 'state', 'expires_at', 'persistence_observed',
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
  'encrypted_settings_memories_suggestions', 'created_at', 'updated_at',
]);
const OPERATION_FIELDS = Object.freeze({
  prepare_preflight: new Set([
    'protocol_version', 'hashed_user_id', 'chat_id', 'turn_id', 'user_message_id',
    'device_hash', 'chat_key_version', 'wrapped_chat_key', 'recovery_public_key',
    'inference_commitment', 'commitment_version', 'expected_messages_v', 'encrypted_user_message',
    'encrypted_chat_metadata',
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
  cleanup_expired: new Set(['protocol_version']),
  get_cutover_state: new Set(['protocol_version']),
  set_sends_paused: new Set(['protocol_version', 'sends_paused']),
  admit_legacy_inference: new Set(['protocol_version', 'task_identity']),
  mark_legacy_inference_completed: new Set(['protocol_version', 'task_identity']),
  acknowledge_legacy_persistence: new Set(['protocol_version', 'task_identity']),
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

function validateEnvelope(raw) {
  const serialized = string(raw, 'invalid_sealed_payload', 24 * 1024 * 1024);
  for (const field of ['v', 'epk', 'nonce', 'ciphertext']) {
    if ((serialized.match(new RegExp(`"${field}"\\s*:`, 'g')) ?? []).length !== 1) fail(400, 'invalid_sealed_payload');
  }
  let envelope;
  try { envelope = JSON.parse(serialized); } catch { fail(400, 'invalid_sealed_payload'); }
  exactKeys(envelope, new Set(['v', 'epk', 'nonce', 'ciphertext']), ['v', 'epk', 'nonce', 'ciphertext'], 'invalid_sealed_payload');
  if (envelope.v !== PROTOCOL_VERSION) fail(400, 'invalid_sealed_payload');
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

const cutoverResponse = (row) => ({
  protocol_epoch: row.protocol_epoch,
  sends_paused: row.sends_paused,
  legacy_in_flight: row.legacy_in_flight,
});

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

async function getCutoverState(database, raw) {
  operationBody(raw, 'get_cutover_state');
  return database.transaction(async (trx) => cutoverResponse(await lockedProtocolState(trx)));
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

async function admitLegacyInference(database, raw, now) {
  const body = operationBody(raw, 'admit_legacy_inference');
  const taskIdentity = string(body.task_identity, 'invalid_task_identity', 255);
  return database.transaction(async (trx) => {
    let row = await lockedProtocolState(trx);
    if (row.protocol_epoch !== 0) fail(426, 'client_update_required');
    if (row.sends_paused) fail(503, 'inference_temporarily_paused');
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
      return { ...cutoverResponse(row), admitted: false, idempotent: true, state: existing.state };
    }
    const activeTasks = [...row.active_legacy_tasks, taskIdentity];
    const lifecycle = [...row.legacy_task_lifecycle, {
      task_identity: taskIdentity,
      state: 'RUNNING',
      expires_at: new Date(now.getTime() + LEGACY_RUNNING_TTL_MS).toISOString(),
    }];
    await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update(
      legacyStateUpdate(activeTasks, lifecycle),
    );
    return {
      ...cutoverResponse({ ...row, legacy_in_flight: activeTasks.length }),
      admitted: true,
      idempotent: false,
      state: 'RUNNING',
    };
  });
}

async function markLegacyInferenceCompleted(database, raw, now) {
  const body = operationBody(raw, 'mark_legacy_inference_completed');
  const taskIdentity = string(body.task_identity, 'invalid_task_identity', 255);
  return database.transaction(async (trx) => {
    const row = await lockedProtocolState(trx);
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

async function acknowledgeLegacyPersistence(database, raw) {
  const body = operationBody(raw, 'acknowledge_legacy_persistence');
  const taskIdentity = string(body.task_identity, 'invalid_task_identity', 255);
  return database.transaction(async (trx) => {
    const row = await lockedProtocolState(trx);
    const record = row.legacy_task_lifecycle.find((item) => item.task_identity === taskIdentity);
    if (!record) {
      return { ...cutoverResponse(row), acknowledged: false, idempotent: true, state: null };
    }
    if (record.state === 'PERSISTED') {
      return { ...cutoverResponse(row), acknowledged: false, idempotent: true, state: record.state };
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
    return { ...cutoverResponse(row), acknowledged: true, idempotent: false, state };
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

async function releaseLegacyInference(database, raw) {
  const body = operationBody(raw, 'release_legacy_inference');
  const taskIdentity = string(body.task_identity, 'invalid_task_identity', 255);
  return database.transaction(async (trx) => {
    const row = await lockedProtocolState(trx);
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
    await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update({ protocol_epoch: targetEpoch });
    return { ...cutoverResponse({ ...row, protocol_epoch: targetEpoch }), activated: true };
  });
}
async function ownedChat(trx, chatId, ownerHash) {
  const chat = await trx(CHATS).where({ id: chatId }).forUpdate().first();
  if (!chat || chat.hashed_user_id !== ownerHash) fail(404, 'chat_not_found');
  return chat;
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
const isEmptyDraftShell = (chat) => Number(chat.messages_v ?? 0) === 0
  && Number(chat.title_v ?? 0) === 0
  && Number(chat.metadata_v ?? 0) === 0
  && chat.last_message_timestamp == null;

async function preparePreflight(database, raw, now) {
  const body = operationBody(raw, 'prepare_preflight');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
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
    await lockIdentity(trx, `${ownerHash}:${chatId}:${keyVersion}`);
    let chat = await trx(CHATS).where({ id: chatId }).forUpdate().first();
    if (chat && chat.hashed_user_id !== ownerHash) fail(404, 'chat_not_found');
    const existing = await trx(PREFLIGHTS).where({ hashed_user_id: ownerHash, chat_id: chatId, turn_id: turnId }).forUpdate().first();
    if (existing) {
      if (!samePreflight(existing, values) || existing.deletion_invalidated_at
        || (chatMetadata && (!chat || !sameChatMetadata(chat, chatMetadata)))) fail(409, 'preflight_mismatch');
      return responseForPreflight(existing);
    }
    if (chat) {
      if (chatMetadata && (!isEmptyDraftShell(chat) || !sameChatMetadata(chat, chatMetadata))) {
        fail(409, 'existing_chat_metadata_forbidden');
      }
    } else {
      if (!chatMetadata) fail(404, 'new_chat_metadata_required');
      if (expectedVersion !== 0) fail(409, 'version_conflict');
      const timestamp = Math.floor(now.getTime() / 1000);
      chat = {
        id: chatId,
        hashed_user_id: ownerHash,
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
    if (await trx(CHATS).where({ id: chatId, hashed_user_id: ownerHash, messages_v: expectedVersion })
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
    const row = await trx(PREFLIGHTS).where({ id: preflightId }).forUpdate().first();
    if (!row || row.hashed_user_id !== ownerHash || row.device_hash !== deviceHash) fail(404, 'preflight_not_found');
    if (row.deletion_invalidated_at) fail(409, 'preflight_invalidated');
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
      return { inference_task_id: taskId, claimed: false, state: row.state };
    }
    if (new Date(row.expires_at) <= now) {
      await trx(PREFLIGHTS).where({ id: row.id, state: 'ENQUEUED' }).update({
        state: 'FAILED', failed_at: now, failure_category: 'claim_expired',
      });
      await trx(OUTBOX).where({ id: row.outbox_id }).update({ state: 'FAILED', last_error_category: 'claim_expired' });
      return { inference_task_id: taskId, claimed: false, state: 'FAILED' };
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
    if (sealedJob) fail(409, 'sealed_job_exists');
    if (row.state === 'FAILED') {
      if (row.failure_category !== category) fail(409, 'failure_category_mismatch');
      return { inference_task_id: taskId, failed: false, state: 'FAILED' };
    }
    if (row.state === 'TERMINAL') return { inference_task_id: taskId, failed: false, state: 'TERMINAL' };
    if (row.state !== 'RUNNING') fail(409, 'invalid_inference_state');
    const updated = await trx(PREFLIGHTS).where({ id: row.id, state: 'RUNNING' }).update({
      state: 'FAILED', failed_at: now, failure_category: category,
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
    const existing = await trx(JOBS).where({ id: jobId }).forUpdate().first();
    if (existing) {
      if (Object.entries(identity).some(([key, value]) => existing[key] !== value)
        || (existing.state !== 'TERMINAL' && existing.sealed_payload_digest !== sealedPayloadDigest)) fail(409, 'sealed_job_mismatch');
      return { job_id: existing.id, state: existing.state, expires_at: existing.expires_at };
    }
    const preflight = await trx(PREFLIGHTS).where({ id: identity.preflight_id }).forUpdate().first();
    if (!preflight || preflight.state !== 'RUNNING' || preflight.deletion_invalidated_at
      || preflight.hashed_user_id !== identity.hashed_user_id || preflight.chat_id !== identity.chat_id
      || preflight.turn_id !== identity.turn_id || preflight.inference_task_id !== identity.inference_task_id
      || preflight.chat_key_version !== identity.chat_key_version) fail(409, 'inference_not_running');
    await ownedChat(trx, identity.chat_id, identity.hashed_user_id);
    const row = {
      id: jobId, ...identity, sealed_payload: sealedPayload, sealed_payload_digest: sealedPayloadDigest,
      state: 'AVAILABLE', lease_generation: 0, created_at: now,
      expires_at: new Date(now.getTime() + JOB_TTL_MS),
    };
    await trx(JOBS).insert(row);
    return { job_id: row.id, state: row.state, expires_at: row.expires_at };
  });
}

async function listAvailableJobs(database, raw, now) {
  const body = operationBody(raw, 'list_available_jobs');
  const ownerHash = string(body.hashed_user_id, 'invalid_owner', 64);
  string(body.device_hash, 'invalid_device', 128);
  const rows = await database(JOBS)
    .where({ hashed_user_id: ownerHash })
    .whereNull('invalidated_at')
    .andWhere('expires_at', '>', now)
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
  if (row.state !== 'TERMINAL' && new Date(row.expires_at) <= now) fail(410, 'recovery_job_expired');
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
    if (row.state === 'TERMINAL') {
      const chat = await ownedChat(trx, row.chat_id, ownerHash);
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
    const row = activeJob(await trx(JOBS).where({ id: jobId }).forUpdate().first(), ownerHash, now);
    if (row.state === 'TERMINAL') {
      if (row.terminal_ciphertext_digest !== ciphertextDigest || row.assistant_message_id !== rawMessage.client_message_id) fail(409, 'terminal_identity_mismatch');
      return { job_id: row.id, state: 'TERMINAL', idempotent: true };
    }
    verifyLease(row, body, now);
    const message = validateMessage(rawMessage, 'assistant', { chatId: row.chat_id, ownerHash });
    if (message.client_message_id !== row.assistant_message_id) fail(409, 'message_identity_mismatch');
    const chat = await ownedChat(trx, row.chat_id, ownerHash);
    if (chat.messages_v !== expectedVersion) fail(409, 'version_conflict');
    if (await trx(MESSAGES).where({ client_message_id: row.assistant_message_id }).first()) fail(409, 'message_identity_conflict');
    await trx(MESSAGES).insert({ id: randomUUID(), ...message });
    const committedVersion = expectedVersion + 1;
    const timestamp = Math.floor(now.getTime() / 1000);
    if (await trx(CHATS).where({ id: row.chat_id, hashed_user_id: ownerHash, messages_v: expectedVersion }).update({
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
    const preflights = trx(PREFLIGHTS).where({ hashed_user_id: ownerHash });
    const jobs = trx(JOBS).where({ hashed_user_id: ownerHash });
    const outbox = trx(OUTBOX).where({ hashed_user_id: ownerHash });
    if (chatId) { preflights.andWhere({ chat_id: chatId }); jobs.andWhere({ chat_id: chatId }); outbox.andWhere({ chat_id: chatId }); }
    const deletedJobs = await jobs.delete();
    const deletedOutbox = await outbox.delete();
    const deletedPreflights = await preflights.delete();
    return { deleted_preflights: deletedPreflights, deleted_jobs: deletedJobs, deleted_outbox: deletedOutbox };
  });
}

async function cleanupExpired(database, raw, now) {
  const body = operationBody(raw, 'cleanup_expired');
  return database.transaction(async (trx) => {
    const protocolState = await lockedProtocolState(trx);
    const prunedLegacy = pruneExpiredLegacyState(protocolState, now);
    if (prunedLegacy.changed) {
      await trx(PROTOCOL_STATE).where({ id: PROTOCOL_STATE_ID }).update(
        legacyStateUpdate(prunedLegacy.activeTasks, prunedLegacy.lifecycle),
      );
    }
    const abandonedIds = await trx(PREFLIGHTS).whereIn('state', ['PREPARED', 'ENQUEUED'])
      .andWhere('expires_at', '<=', now).pluck('id');
    const runningIds = await trx(PREFLIGHTS).where({ state: 'RUNNING' }).andWhere('expires_at', '<=', now).pluck('id');
    const sealedPreflightIds = runningIds.length
      ? await trx(JOBS).whereIn('preflight_id', runningIds).pluck('preflight_id')
      : [];
    const failedIds = unsealedPreflightIds(runningIds, sealedPreflightIds);
    const abandonedPreflights = abandonedIds.length
      ? await trx(PREFLIGHTS).whereIn('id', abandonedIds).update({ state: 'ABANDONED' })
      : 0;
    const failedInferences = failedIds.length
      ? await trx(PREFLIGHTS).whereIn('id', failedIds).update({
        state: 'FAILED', failed_at: now, failure_category: 'worker_timeout',
      })
      : 0;
    if (abandonedIds.length) await trx(OUTBOX).whereIn('preflight_id', abandonedIds).where({ state: 'PENDING' }).delete();
    if (failedIds.length) await trx(OUTBOX).whereIn('preflight_id', failedIds).update({
      state: 'FAILED', last_error_category: 'worker_timeout',
    });
    return {
      expired_jobs: await trx(JOBS).whereIn('state', ['AVAILABLE', 'LEASED']).andWhere('expires_at', '<=', now).delete(),
      expired_tombstones: await trx(JOBS).where({ state: 'TERMINAL' }).andWhere('tombstone_expires_at', '<=', now).delete(),
      abandoned_preflights: abandonedPreflights,
      failed_inferences: failedInferences,
      expired_outbox: await trx(OUTBOX).whereIn('state', ['DISPATCHED', 'FAILED'])
        .andWhere('created_at', '<=', new Date(now.getTime() - PREFLIGHT_TTL_MS)).delete(),
      ...prunedLegacy.counts,
    };
  });
}

export const operations = Object.freeze({
  prepare_preflight: preparePreflight, enqueue_inference: enqueueInference,
  claim_inference: claimInference, mark_outbox_dispatched: markOutboxDispatched,
  mark_inference_failed: markInferenceFailed,
  create_sealed_job: createSealedJob, list_available_jobs: listAvailableJobs,
  lease_job: leaseJob, renew_lease: renewLease,
  persist_terminal: persistTerminal, invalidate_deletion: invalidateDeletion,
  cleanup_expired: cleanupExpired,
  get_cutover_state: getCutoverState, set_sends_paused: setSendsPaused,
  admit_legacy_inference: admitLegacyInference,
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
