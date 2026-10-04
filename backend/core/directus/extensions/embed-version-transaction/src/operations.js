/* Atomic publication for opaque client-encrypted Project file revisions. */
import { createHash, randomUUID } from 'node:crypto';

const EMBEDS = 'embeds';
const DIFFS = 'embed_diffs';
const RECEIPTS = 'embed_version_commits';
const EMBED_KEYS = 'embed_keys';
const PROJECTS = 'projects';
const PROJECT_ITEMS = 'project_items';
const MEMBERSHIPS = 'team_memberships';
const TEAMS = 'teams';
const CHATS = 'chats';
const PREFLIGHTS = 'chat_turn_preflights';
const ARCHIVE_ROLLOUT = 'embed_version_archive_rollout';
const RECENT_VERSION_WINDOW = 32;
const MAX_CIPHERTEXT_BYTES = 4 * 1024 * 1024;
const MAX_OPERATION_BYTES = 128;
const HEX_64_RE = /^[0-9a-f]{64}$/;
const OPERATION_RE = /^[A-Za-z0-9._:-]{1,128}$/;
const UUID_V5_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HEAD_FIELDS = new Set([
  'encrypted_content', 'encrypted_text_preview', 'encrypted_diff', 'status', 'updated_at',
]);
const HISTORY_FIELDS = new Set([
  'version_number', 'encrypted_snapshot', 'encrypted_patch', 'created_at',
]);
const CREATE_FIELDS = new Set([
  'project_item_id', 'encrypted_type', 'target_id_encrypted',
  'encrypted_display_name', 'encrypted_metadata', 'key_wrappers',
]);
const KEY_WRAPPER_FIELDS = new Set(['key_type', 'encrypted_embed_key', 'created_at']);
const BODY_FIELDS = new Set([
  'operation_id', 'embed_id', 'project_id', 'chat_id', 'proposal_digest', 'team_id',
  'expected_revision', 'head', 'history_rows', 'create', 'actor_user_hash',
]);
const LEGACY_EMBED_FIELDS = new Set([
  'embed_id', 'hashed_chat_id', 'hashed_message_id', 'hashed_task_id',
  'encrypted_type', 'status', 'hashed_user_id', 'app_id', 'skill_id',
  'hashed_team_id', 'workspace_origin', 'root_embed_id',
  'is_private', 'is_shared',
  'shared_with_users', 'embed_ids', 'encrypted_content',
  'encrypted_text_preview', 'parent_embed_id', 'version_number',
  'encrypted_diff', 'file_path', 'content_hash',
  'created_at', 'updated_at', 'encryption_mode', 'vault_key_id', 's3_file_keys',
]);

export class ProtocolError extends Error {
  constructor(status, code) {
    super(code);
    this.name = 'ProtocolError';
    this.status = status;
    this.code = code;
  }
}

const fail = (status, code) => { throw new ProtocolError(status, code); };
const object = (value) => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) fail(400, 'invalid_request');
  return value;
};
const boundedString = (value, code, max = 512) => {
  if (typeof value !== 'string' || !value || Buffer.byteLength(value, 'utf8') > max) fail(400, code);
  return value;
};
const hexDigest = (value, code) => {
  const result = boundedString(value, code, 64);
  if (!HEX_64_RE.test(result)) fail(400, code);
  return result;
};
const safeInteger = (value, code) => {
  if (!Number.isSafeInteger(value) || value < 0 || value > 2_147_483_646) fail(400, code);
  return value;
};
const sha256 = (value) => createHash('sha256').update(value, 'utf8').digest('hex');
const stableJson = (value) => {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
};
const payloadDigest = (value) => sha256(stableJson(value));

function exactFields(value, allowed, required = []) {
  const result = object(value);
  if (Object.keys(result).some((key) => !allowed.has(key))
    || required.some((key) => !(key in result))) fail(400, 'invalid_request');
  return result;
}

function optionalCiphertext(value) {
  if (value == null) return null;
  return boundedString(value, 'invalid_ciphertext', MAX_CIPHERTEXT_BYTES);
}

function validateHead(raw) {
  const head = exactFields(raw, HEAD_FIELDS, ['encrypted_content']);
  const result = {
    encrypted_content: boundedString(
      head.encrypted_content,
      'invalid_ciphertext',
      MAX_CIPHERTEXT_BYTES,
    ),
  };
  if ('encrypted_text_preview' in head) result.encrypted_text_preview = optionalCiphertext(head.encrypted_text_preview);
  if ('encrypted_diff' in head) result.encrypted_diff = optionalCiphertext(head.encrypted_diff);
  if ('status' in head) result.status = boundedString(head.status, 'invalid_status', 64);
  if ('updated_at' in head) result.updated_at = safeInteger(head.updated_at, 'invalid_timestamp');
  return result;
}

function validateCreate(raw, expectedRevision, embedId) {
  if (raw == null) return null;
  if (expectedRevision !== 0 || !UUID_V5_RE.test(embedId)) fail(400, 'invalid_create');
  const create = exactFields(raw, CREATE_FIELDS, [
    'project_item_id', 'encrypted_type', 'target_id_encrypted',
    'encrypted_display_name', 'encrypted_metadata', 'key_wrappers',
  ]);
  const projectItemId = boundedString(create.project_item_id, 'invalid_create', 36);
  if (!UUID_V5_RE.test(projectItemId)) fail(400, 'invalid_create');
  if (!Array.isArray(create.key_wrappers) || create.key_wrappers.length !== 2) {
    fail(400, 'invalid_key_wrappers');
  }
  const wrappers = create.key_wrappers.map((rawWrapper) => {
    const wrapper = exactFields(rawWrapper, KEY_WRAPPER_FIELDS, [
      'key_type', 'encrypted_embed_key', 'created_at',
    ]);
    if (!['project', 'chat'].includes(wrapper.key_type)) fail(400, 'invalid_key_wrappers');
    return {
      key_type: wrapper.key_type,
      encrypted_embed_key: boundedString(
        wrapper.encrypted_embed_key,
        'invalid_key_wrappers',
        MAX_CIPHERTEXT_BYTES,
      ),
      created_at: safeInteger(wrapper.created_at, 'invalid_timestamp'),
    };
  });
  if (new Set(wrappers.map((wrapper) => wrapper.key_type)).size !== 2) {
    fail(400, 'invalid_key_wrappers');
  }
  return {
    project_item_id: projectItemId,
    encrypted_type: boundedString(create.encrypted_type, 'invalid_create', MAX_CIPHERTEXT_BYTES),
    target_id_encrypted: boundedString(
      create.target_id_encrypted,
      'invalid_create',
      MAX_CIPHERTEXT_BYTES,
    ),
    encrypted_display_name: boundedString(
      create.encrypted_display_name,
      'invalid_create',
      MAX_CIPHERTEXT_BYTES,
    ),
    encrypted_metadata: boundedString(
      create.encrypted_metadata,
      'invalid_create',
      MAX_CIPHERTEXT_BYTES,
    ),
    key_wrappers: wrappers,
  };
}

function validateHistoryRows(raw, newRevision) {
  if (!Array.isArray(raw) || raw.length < 1 || raw.length > 2) fail(400, 'invalid_history_rows');
  const rows = raw.map((rawRow) => {
    const row = exactFields(rawRow, HISTORY_FIELDS, ['version_number', 'created_at']);
    const version = safeInteger(row.version_number, 'invalid_history_rows');
    if (version !== 1 && version !== newRevision) fail(400, 'invalid_history_rows');
    const snapshot = optionalCiphertext(row.encrypted_snapshot);
    const patch = optionalCiphertext(row.encrypted_patch);
    if (version === 1 && (snapshot === null || patch !== null)) fail(400, 'invalid_history_rows');
    if (version > 1 && patch === null) fail(400, 'invalid_history_rows');
    return {
      version_number: version,
      encrypted_snapshot: snapshot,
      encrypted_patch: patch,
      created_at: safeInteger(row.created_at, 'invalid_timestamp'),
    };
  });
  if (!rows.some((row) => row.version_number === newRevision)
    || new Set(rows.map((row) => row.version_number)).size !== rows.length) fail(400, 'invalid_history_rows');
  return rows.sort((left, right) => left.version_number - right.version_number);
}

function validateRequest(raw) {
  const body = exactFields(raw, BODY_FIELDS, [
    'operation_id', 'embed_id', 'project_id', 'chat_id', 'proposal_digest',
    'expected_revision', 'head', 'history_rows', 'actor_user_hash',
  ]);
  const operationId = boundedString(body.operation_id, 'invalid_operation_id', MAX_OPERATION_BYTES);
  if (!OPERATION_RE.test(operationId)) fail(400, 'invalid_operation_id');
  const expectedRevision = safeInteger(body.expected_revision, 'invalid_expected_revision');
  const newRevision = expectedRevision + 1;
  const teamId = body.team_id == null ? null : boundedString(body.team_id, 'invalid_team_id', 512);
  const embedId = boundedString(body.embed_id, 'invalid_embed_id', 512);
  return {
    operation_id: operationId,
    embed_id: embedId,
    project_id: boundedString(body.project_id, 'invalid_project_id', 512),
    chat_id: boundedString(body.chat_id, 'invalid_chat_id', 512),
    proposal_digest: hexDigest(body.proposal_digest, 'invalid_proposal_digest'),
    team_id: teamId,
    expected_revision: expectedRevision,
    head: validateHead(body.head),
    history_rows: validateHistoryRows(body.history_rows, newRevision),
    create: validateCreate(body.create, expectedRevision, embedId),
    actor_user_hash: hexDigest(body.actor_user_hash, 'invalid_actor'),
  };
}

async function lockIdentity(trx, value) {
  await trx.raw('SELECT pg_advisory_xact_lock(hashtextextended(?, 0))', [value]);
}

/** Serialize a legacy client ciphertext write with Project revision publication. */
export async function writeLegacyEmbed(database, raw) {
  const input = exactFields(raw, new Set(['embed_id', 'actor_user_hash', 'payload', 'bundle_context']), [
    'embed_id', 'actor_user_hash', 'payload',
  ]);
  const embedId = boundedString(input.embed_id, 'invalid_embed_id', 512);
  const actor = hexDigest(input.actor_user_hash, 'invalid_actor');
  if (UUID_V5_RE.test(embedId)) fail(403, 'project_context_required');
  const payload = exactFields(input.payload, LEGACY_EMBED_FIELDS, [
    'embed_id', 'hashed_user_id',
  ]);
  if (payload.embed_id !== embedId) fail(400, 'invalid_embed_id');
  let bundle = null;
  if (input.bundle_context !== undefined) {
    bundle = exactFields(input.bundle_context, new Set([
      'chat_id', 'message_id', 'hashed_team_id', 'allow_new_personal_chat', 'preflight_id',
      'key_wrappers',
    ]), ['chat_id', 'message_id', 'hashed_team_id', 'allow_new_personal_chat', 'key_wrappers']);
    boundedString(bundle.chat_id, 'invalid_bundle_chat', 128);
    boundedString(bundle.message_id, 'invalid_bundle_message', 255);
    if (bundle.hashed_team_id !== null) hexDigest(bundle.hashed_team_id, 'invalid_bundle_team');
    if (typeof bundle.allow_new_personal_chat !== 'boolean') fail(400, 'invalid_bundle_scope');
    if (bundle.preflight_id != null) boundedString(bundle.preflight_id, 'invalid_bundle_preflight', 128);
    if (payload.hashed_user_id !== actor || payload.hashed_chat_id !== sha256(bundle.chat_id)
      || payload.hashed_message_id !== sha256(bundle.message_id)
      || (payload.hashed_team_id != null && payload.hashed_team_id !== bundle.hashed_team_id)
      || typeof payload.encrypted_content !== 'string' || !payload.encrypted_content
      || typeof payload.encrypted_type !== 'string' || !payload.encrypted_type) {
      fail(400, 'bundle_identity_mismatch');
    }
    if (!Array.isArray(bundle.key_wrappers) || bundle.key_wrappers.length !== 2) {
      fail(400, 'bundle_wrappers_missing');
    }
    const seenTypes = new Set();
    bundle.key_wrappers = bundle.key_wrappers.map((rawWrapper) => {
      const wrapper = exactFields(rawWrapper, new Set([
        'hashed_embed_id', 'hashed_user_id', 'hashed_chat_id', 'key_type',
        'encrypted_embed_key', 'created_at',
      ]), ['hashed_embed_id', 'hashed_user_id', 'hashed_chat_id', 'key_type',
        'encrypted_embed_key', 'created_at']);
      if (!['master', 'chat'].includes(wrapper.key_type) || seenTypes.has(wrapper.key_type)
        || wrapper.hashed_embed_id !== sha256(embedId) || wrapper.hashed_user_id !== actor
        || wrapper.hashed_chat_id !== (wrapper.key_type === 'chat' ? sha256(bundle.chat_id) : null)) {
        fail(400, 'bundle_wrapper_scope_mismatch');
      }
      seenTypes.add(wrapper.key_type);
      boundedString(wrapper.encrypted_embed_key, 'invalid_bundle_wrapper', MAX_CIPHERTEXT_BYTES);
      safeInteger(wrapper.created_at, 'invalid_bundle_wrapper');
      return wrapper;
    });
    if (!seenTypes.has('master') || !seenTypes.has('chat')) fail(400, 'bundle_wrappers_missing');
  }
  // The WebSocket handler validates the client ciphertext before this request.
  // Keep the transaction boundary fail closed if another internal caller appears.
  if (payload.encryption_mode === 'vault'
    || (typeof payload.encrypted_content === 'string'
      && payload.encrypted_content.startsWith('vault:v1:'))) {
    fail(400, 'invalid_ciphertext');
  }
  const catalogFields = [
    'app_id', 'skill_id', 'hashed_team_id', 'workspace_origin', 'root_embed_id',
  ];
  const hasCatalogContext = catalogFields.some((field) => payload[field] != null);
  if (hasCatalogContext) {
    const catalogId = /^[a-z][a-z0-9_]{0,63}$/;
    if (typeof payload.app_id !== 'string' || !catalogId.test(payload.app_id)
      || typeof payload.skill_id !== 'string' || !catalogId.test(payload.skill_id)
      || (payload.hashed_team_id != null && !HEX_64_RE.test(payload.hashed_team_id))
      || (payload.workspace_origin != null && payload.workspace_origin !== 'chat')
      || payload.root_embed_id !== (payload.parent_embed_id || embedId)) {
      fail(400, 'invalid_catalog_context');
    }
  }
  const storedPayload = { ...payload };
  for (const field of ['embed_ids', 'shared_with_users', 's3_file_keys']) {
    if (storedPayload[field] != null) storedPayload[field] = JSON.stringify(storedPayload[field]);
  }
  return database.transaction(async (trx) => {
    await lockIdentity(trx, `embed:${embedId}`);
    let bundlePreflightState = null;
    if (bundle) {
      const chat = await trx(CHATS).where({ id: bundle.chat_id }).forUpdate().first();
      if (chat) {
        if (chat.storage_state === 'deleting'
          || (chat.hashed_team_id ?? null) !== bundle.hashed_team_id
          || (!bundle.hashed_team_id && chat.hashed_user_id !== actor)) {
          fail(403, 'bundle_chat_scope_mismatch');
        }
        if (bundle.hashed_team_id) {
          const membership = await trx(MEMBERSHIPS).where({
            hashed_team_id: bundle.hashed_team_id, hashed_user_id: actor, status: 'active',
          }).forShare().first();
          const team = await trx(TEAMS).where({
            hashed_team_id: bundle.hashed_team_id, status: 'active',
          }).forShare().first();
          if (!team || !membership || !['owner', 'admin', 'member'].includes(membership.role)) {
            fail(403, 'bundle_team_write_denied');
          }
        }
      } else if (bundle.hashed_team_id || bundle.preflight_id != null
        || !bundle.allow_new_personal_chat) {
        fail(403, 'bundle_chat_scope_mismatch');
      }
      if (bundle.preflight_id != null) {
        const preflight = await trx(PREFLIGHTS).where({ id: bundle.preflight_id }).forShare().first();
        if (!preflight || preflight.hashed_user_id !== actor
          || preflight.chat_id !== bundle.chat_id
          || preflight.user_message_id !== bundle.message_id
          || preflight.deletion_invalidated_at != null
          || !['PREPARED', 'ENQUEUED', 'RUNNING', 'TERMINAL'].includes(preflight.state)) {
          fail(403, 'bundle_preflight_mismatch');
        }
        bundlePreflightState = preflight.state;
      }
    }
    const linked = await trx(PROJECT_ITEMS).where({ target_id_hash: sha256(embedId) })
      .whereIn('item_type', ['embed', 'upload']).first();
    if (linked) fail(403, 'project_context_required');
    const embed = await trx(EMBEDS).where({ embed_id: embedId }).forUpdate().first();
    if (embed) {
      if (embed.hashed_user_id !== actor) fail(403, 'embed_access_denied');
      if (bundle) {
        if (Number(embed.version_number ?? 1) !== 1) fail(409, 'bundle_head_advanced');
        for (const [field, value] of Object.entries(storedPayload)) {
          if (field === 'embed_id') continue;
          if (['embed_ids', 'shared_with_users', 's3_file_keys'].includes(field)
            && value != null && embed[field] != null) {
            try {
              const existingJson = typeof embed[field] === 'string' ? JSON.parse(embed[field]) : embed[field];
              const proposedJson = typeof value === 'string' ? JSON.parse(value) : value;
              if (stableJson(existingJson) === stableJson(proposedJson)) continue;
            } catch { /* A malformed stored JSON value cannot prove an exact replay. */ }
          }
          if ((embed[field] ?? null) !== (value ?? null)) fail(409, 'bundle_head_mismatch');
        }
        await persistBundleWrappers(trx, embedId, actor, bundle.key_wrappers);
        return { status: 'idempotent', embed_id: embedId };
      }
      if (embed.workspace_origin === 'web_apps'
        || (embed.hashed_team_id != null && embed.hashed_team_id !== payload.hashed_team_id)
        || (payload.app_id != null && embed.app_id != null && embed.app_id !== payload.app_id)
        || (payload.skill_id != null && embed.skill_id != null && embed.skill_id !== payload.skill_id)
        || (embed.workspace_origin === 'chat' && payload.app_id == null)
        || (embed.root_embed_id != null && payload.root_embed_id != null
          && embed.root_embed_id !== payload.root_embed_id)) {
        fail(403, 'embed_catalog_context_mismatch');
      }
      const updated = { ...storedPayload, hashed_user_id: actor, hashed_embed_id: sha256(embedId) };
      delete updated.embed_id;
      await trx(EMBEDS).where({ id: embed.id }).update(updated);
      return { status: 'updated', embed_id: embedId };
    }
    if (payload.hashed_user_id !== actor) fail(403, 'embed_access_denied');
    if (bundle && bundlePreflightState === 'TERMINAL') fail(409, 'bundle_preflight_finished');
    await trx(EMBEDS).insert({
      id: randomUUID(), ...storedPayload, hashed_embed_id: sha256(embedId),
    });
    if (bundle) await persistBundleWrappers(trx, embedId, actor, bundle.key_wrappers);
    return { status: 'created', embed_id: embedId };
  });
}

async function persistBundleWrappers(trx, embedId, actor, wrappers) {
  const embedHash = sha256(embedId);
  for (const wrapper of wrappers) {
    const scope = {
      hashed_embed_id: embedHash, key_type: wrapper.key_type,
      hashed_chat_id: wrapper.hashed_chat_id,
    };
    const existing = await trx(EMBED_KEYS).where(scope).forUpdate().limit(2);
    if (!Array.isArray(existing) || existing.length > 1) fail(409, 'bundle_wrapper_ambiguous');
    if (existing.length === 1) {
      if (existing[0].hashed_user_id !== actor
        || existing[0].encrypted_embed_key !== wrapper.encrypted_embed_key) {
        fail(409, 'bundle_wrapper_mismatch');
      }
      continue;
    }
    await trx(EMBED_KEYS).insert({ id: randomUUID(), ...wrapper });
  }
}

async function authorize(trx, body) {
  const projectHash = sha256(body.project_id);
  const teamHash = body.team_id ? sha256(body.team_id) : null;
  await lockIdentity(trx, `project:${projectHash}`);
  const project = await trx(PROJECTS).where({ project_id: body.project_id }).forUpdate().first();
  if (!project || sha256(project.project_id) !== projectHash) fail(403, 'project_access_denied');

  if (teamHash) {
    if (project.hashed_team_id !== teamHash || project.hashed_user_id != null) fail(403, 'project_access_denied');
    const membership = await trx(MEMBERSHIPS).where({
      hashed_team_id: teamHash,
      hashed_user_id: body.actor_user_hash,
      status: 'active',
    }).first();
    if (!membership || !['owner', 'admin', 'member'].includes(membership.role)) fail(403, 'project_access_denied');
    const team = await trx(TEAMS).where({ hashed_team_id: teamHash, status: 'active' }).first();
    if (!team) fail(403, 'project_access_denied');
  } else if (project.hashed_user_id !== body.actor_user_hash || project.hashed_team_id != null) {
    fail(403, 'project_access_denied');
  }

  const itemWhere = {
    hashed_project_id: projectHash,
    target_id_hash: sha256(body.embed_id),
  };
  if (teamHash) itemWhere.hashed_team_id = teamHash;
  else itemWhere.hashed_user_id = body.actor_user_hash;
  const item = await trx(PROJECT_ITEMS).where(itemWhere).whereIn('item_type', ['embed', 'upload']).first();
  if (!item && !body.create) fail(403, 'project_item_access_denied');
  if (item && body.create && item.project_item_id !== body.create.project_item_id) {
    fail(409, 'project_item_identity_mismatch');
  }
  return { projectHash, teamHash, project, item };
}

function historiesMatch(existing, proposed) {
  return existing.encrypted_snapshot === proposed.encrypted_snapshot
    && existing.encrypted_patch === proposed.encrypted_patch
    && existing.created_at === proposed.created_at;
}

export async function commitEmbedRevision(database, raw) {
  const body = validateRequest(raw);
  const digest = payloadDigest(body);
  const commitIdentity = sha256(`${body.embed_id}\0${body.operation_id}`);
  return database.transaction(async (trx) => {
    const scope = await authorize(trx, body);
    await lockIdentity(trx, `embed:${body.embed_id}`);
    const receipt = await trx(RECEIPTS).where({ commit_identity: commitIdentity }).first();
    if (receipt) {
      if (receipt.payload_digest !== digest) fail(409, 'operation_payload_mismatch');
      return {
        status: 'committed', operation_id: body.operation_id, embed_id: body.embed_id,
        current_revision: receipt.committed_revision, idempotent: true,
      };
    }

    let embed = await trx(EMBEDS).where({ embed_id: body.embed_id }).forUpdate().first();
    if (!embed && !body.create) fail(404, 'embed_not_found');
    if (embed && !scope.teamHash && embed.hashed_user_id !== body.actor_user_hash) {
      fail(403, 'embed_access_denied');
    }

    const currentRevision = embed && Number.isSafeInteger(embed.version_number) ? embed.version_number : 0;
    if (currentRevision !== body.expected_revision) {
      return {
        status: 'conflict', operation_id: body.operation_id, embed_id: body.embed_id,
        current_revision: currentRevision,
      };
    }
    const newRevision = currentRevision + 1;
    if (!embed) {
      const initial = body.history_rows.find((row) => row.version_number === 1);
      if (!initial || !body.create) fail(400, 'invalid_create');
      const createdAt = initial.created_at;
      const hashedEmbedId = sha256(body.embed_id);
      await trx(EMBEDS).insert({
        id: randomUUID(), embed_id: body.embed_id, hashed_embed_id: hashedEmbedId,
        hashed_chat_id: sha256(body.chat_id), encrypted_type: body.create.encrypted_type,
        status: body.head.status ?? 'finished', hashed_user_id: body.actor_user_hash,
        is_private: true, is_shared: false, encrypted_content: body.head.encrypted_content,
        encrypted_text_preview: body.head.encrypted_text_preview ?? null,
        encrypted_diff: body.head.encrypted_diff ?? null, version_number: 1,
        encryption_mode: 'client', created_at: createdAt,
        updated_at: body.head.updated_at ?? createdAt,
      });
      await trx(PROJECT_ITEMS).insert({
        id: randomUUID(), project_item_id: body.create.project_item_id,
        hashed_project_id: scope.projectHash, hashed_folder_id: null,
        hashed_user_id: scope.teamHash ? null : body.actor_user_hash,
        hashed_team_id: scope.teamHash, attached_by_user_hash: body.actor_user_hash,
        item_type: 'embed', target_id_hash: hashedEmbedId,
        target_id_encrypted: body.create.target_id_encrypted,
        encrypted_display_name: body.create.encrypted_display_name,
        encrypted_note: null, encrypted_metadata: body.create.encrypted_metadata,
        deleted_target_state: null, created_at: createdAt, updated_at: createdAt,
        position: 0,
      });
      await trx(PROJECTS).where({ id: scope.project.id }).increment('item_count', 1);
      for (const wrapper of body.create.key_wrappers) {
        await trx(EMBED_KEYS).insert({
          id: randomUUID(), hashed_embed_id: hashedEmbedId,
          key_type: wrapper.key_type,
          hashed_chat_id: wrapper.key_type === 'chat' ? sha256(body.chat_id) : null,
          hashed_project_id: wrapper.key_type === 'project' ? scope.projectHash : null,
          hashed_plan_id: null, hashed_team_id: null, team_key_epoch: null,
          encrypted_embed_key: wrapper.encrypted_embed_key,
          hashed_user_id: body.actor_user_hash, created_at: wrapper.created_at,
        });
      }
      embed = {
        id: null, embed_id: body.embed_id, hashed_user_id: body.actor_user_hash,
        version_number: 1,
      };
    } else if (body.create) {
      return {
        status: 'conflict', operation_id: body.operation_id, embed_id: body.embed_id,
        current_revision: currentRevision,
      };
    }
    const proposedVersions = new Set(body.history_rows.map((row) => row.version_number));
    const existingRows = await trx(DIFFS).where({ embed_id: body.embed_id })
      .whereIn('version_number', [...proposedVersions]);
    const existingByVersion = new Map(existingRows.map((row) => [row.version_number, row]));
    for (const row of body.history_rows) {
      const existing = existingByVersion.get(row.version_number);
      if (existing && !historiesMatch(existing, row)) fail(409, 'immutable_history_mismatch');
      if (!existing) {
        await trx(DIFFS).insert({
          id: randomUUID(), embed_id: body.embed_id, hashed_user_id: embed.hashed_user_id,
          ...row, has_snapshot: row.encrypted_snapshot !== null,
          has_patch: row.encrypted_patch !== null,
        });
      }
    }
    const historyCount = await trx(DIFFS).where({ embed_id: body.embed_id })
      .where('version_number', '<=', newRevision).count({ count: '*' }).first();
    if (Number(historyCount?.count ?? 0) !== newRevision) fail(409, 'incomplete_history');

    if (embed.id !== null) {
      await trx(EMBEDS).where({ id: embed.id }).update({ ...body.head, version_number: newRevision });
    }
    await trx(RECEIPTS).insert({
      id: randomUUID(), operation_id: body.operation_id, commit_identity: commitIdentity,
      embed_id: body.embed_id,
      hashed_project_id: scope.projectHash, hashed_team_id: scope.teamHash,
      actor_user_hash: body.actor_user_hash, hashed_chat_id: sha256(body.chat_id),
      proposal_digest: body.proposal_digest, payload_digest: digest,
      expected_revision: body.expected_revision, committed_revision: newRevision,
      created_at: Math.floor(Date.now() / 1000),
    });
    return {
      status: 'committed', operation_id: body.operation_id, embed_id: body.embed_id,
      current_revision: newRevision, idempotent: false,
    };
  });
}

/** Attach one immutable client-encrypted checkpoint without changing the revision graph. */
export async function publishEmbedSnapshot(database, raw) {
  const input = exactFields(raw, new Set([
    'embed_id', 'version_number', 'expected_revision', 'encrypted_snapshot',
    'operation_id', 'actor_user_hash', 'project_id', 'team_id',
  ]), ['embed_id', 'version_number', 'expected_revision', 'encrypted_snapshot', 'operation_id', 'actor_user_hash']);
  const embedId = boundedString(input.embed_id, 'invalid_embed_id', 512);
  const version = safeInteger(input.version_number, 'invalid_version');
  const expectedRevision = safeInteger(input.expected_revision, 'invalid_expected_revision');
  const ciphertext = boundedString(input.encrypted_snapshot, 'invalid_ciphertext', MAX_CIPHERTEXT_BYTES);
  const operationId = boundedString(input.operation_id, 'invalid_operation_id', MAX_OPERATION_BYTES);
  if (!OPERATION_RE.test(operationId) || version < 2 || version > expectedRevision) {
    fail(400, 'invalid_snapshot');
  }
  const actor = hexDigest(input.actor_user_hash, 'invalid_actor');
  const projectId = input.project_id == null ? null : boundedString(input.project_id, 'invalid_project_id', 512);
  const teamId = input.team_id == null ? null : boundedString(input.team_id, 'invalid_team_id', 512);
  if (teamId && !projectId) fail(400, 'invalid_project_id');
  const digest = sha256(ciphertext);
  return database.transaction(async (trx) => {
    if (projectId) {
      await authorize(trx, {
        project_id: projectId, team_id: teamId, actor_user_hash: actor,
        embed_id: embedId, create: null,
      });
    } else {
      const linked = await trx(PROJECT_ITEMS).where({ target_id_hash: sha256(embedId) })
        .whereIn('item_type', ['embed', 'upload']).first();
      if (linked) fail(403, 'project_context_required');
    }
    await lockIdentity(trx, `embed:${embedId}`);
    const embed = await trx(EMBEDS).where({ embed_id: embedId }).forUpdate().first();
    if (!embed) fail(404, 'embed_not_found');
    if (!projectId && embed.hashed_user_id !== actor) fail(403, 'embed_access_denied');
    const row = await trx(DIFFS).where({ embed_id: embedId, version_number: version }).forUpdate().first();
    if (!row) fail(404, 'version_not_found');
    if (row.hashed_user_id !== embed.hashed_user_id) fail(409, 'history_owner_mismatch');
    if (row.snapshot_operation_id != null || row.encrypted_snapshot != null) {
      if (row.snapshot_operation_id === operationId && row.snapshot_digest === digest) {
        return { status: 'committed', embed_id: embedId, version_number: version, idempotent: true };
      }
      fail(409, 'immutable_snapshot_mismatch');
    }
    if (row.archive_state === 'pruned') fail(409, 'snapshot_target_pruned');
    if (embed.version_number !== expectedRevision) {
      return { status: 'conflict', embed_id: embedId, current_revision: embed.version_number };
    }
    await trx(DIFFS).where({ id: row.id }).update({
      encrypted_snapshot: ciphertext, has_snapshot: true,
      snapshot_operation_id: operationId, snapshot_digest: digest,
      ...(['copied', 'reader_active', 'preparing'].includes(row.archive_state) ? {
        archive_state: 'stale', archive_reader_activated_at: null,
        archive_source_copy_until: null,
      } : {}),
    });
    return { status: 'committed', embed_id: embedId, version_number: version, idempotent: false };
  });
}

/** Register an immutable S3 key and bounded writer lease before any upload. */
export async function prepareEmbedArchiveCopy(database, raw) {
  const input = exactFields(raw, new Set([
    'row_id', 'embed_id', 'version_number', 'source_checksum', 'archive_object_key',
  ]), ['row_id', 'embed_id', 'version_number', 'source_checksum', 'archive_object_key']);
  const identity = {
    row_id: boundedString(input.row_id, 'invalid_row_id', 512),
    embed_id: boundedString(input.embed_id, 'invalid_embed_id', 512),
    version_number: safeInteger(input.version_number, 'invalid_version'),
  };
  const checksum = hexDigest(input.source_checksum, 'invalid_checksum');
  const objectKey = boundedString(input.archive_object_key, 'invalid_object_key', 1024);
  if (objectKey !== `embed-versions/${sha256(identity.embed_id)}/${identity.version_number}/${checksum}.json`) {
    fail(400, 'invalid_archive_object_scope');
  }
  return database.transaction(async (trx) => {
    const { embed, row } = await archiveRowAndHead(trx, identity);
    const chat = await trx('chats')
      .whereRaw("encode(digest(id::text, 'sha256'), 'hex') = ?", [embed.hashed_chat_id])
      .forUpdate().first();
    if (!chat || chat.storage_state === 'deleting') fail(409, 'archive_chat_deleting');
    const prunedExpansion = row.archive_state === 'pruned'
      && row.archive_object_key === objectKey && row.archive_checksum === checksum;
    if (!prunedExpansion && (row.archive_state === 'pruned' || archiveSourceChecksum(row) !== checksum)) {
      fail(409, 'archive_prepare_source_changed');
    }
    if (row.archive_pending_object_key && (row.archive_pending_object_key !== objectKey
        || row.archive_pending_checksum !== checksum)) fail(409, 'archive_pending_cleanup_required');
    const leaseUntil = Math.floor(Date.now() / 1000) + 300;
    await trx(DIFFS).where({ id: row.id }).update({
      archive_pending_object_key: objectKey, archive_pending_checksum: checksum,
      archive_copy_lease_until: leaseUntil,
      ...(!prunedExpansion ? { archive_state: 'preparing', archive_reader_activated_at: null,
        archive_source_copy_until: null } : {}),
    });
    return { status: 'preparing', archive_object_key: objectKey,
      source_checksum: checksum, lease_until: leaseUntil };
  });
}

/** Retire a stale pending key only after a durable tombstone and writer grace. */
export async function retireEmbedArchiveCopy(database, raw) {
  const input = exactFields(raw, new Set(['row_id', 'embed_id', 'version_number',
    'archive_object_key']), ['row_id', 'embed_id', 'version_number', 'archive_object_key']);
  const rowId = boundedString(input.row_id, 'invalid_row_id', 512);
  const embedId = boundedString(input.embed_id, 'invalid_embed_id', 512);
  const version = safeInteger(input.version_number, 'invalid_version');
  const objectKey = boundedString(input.archive_object_key, 'invalid_object_key', 1024);
  return database.transaction(async (trx) => {
    const row = await trx(DIFFS).where({ id: rowId, embed_id: embedId, version_number: version }).forUpdate().first();
    if (!row) fail(404, 'version_not_found');
    if (row.archive_pending_object_key !== objectKey) fail(409, 'archive_pending_identity_changed');
    const now = Math.floor(Date.now() / 1000);
    if (!Number.isSafeInteger(row.archive_copy_lease_until)
        || now < row.archive_copy_lease_until + 90) fail(409, 'archive_writer_may_still_upload');
    await trx(DIFFS).where({ id: row.id }).update({
      archive_pending_object_key: null, archive_pending_checksum: null,
      archive_copy_lease_until: null,
      ...(row.archive_state === 'preparing' ? { archive_state: 'stale' } : {}),
    });
    return { status: 'retired', archive_object_key: objectKey };
  });
}

/** Fence archive indexing against a snapshot attached while object copy ran. */
export async function finalizeEmbedArchiveCopy(database, raw) {
  const input = exactFields(raw, new Set([
    'row_id', 'embed_id', 'version_number', 'source_checksum',
    'archive_object_key', 'archive_regions',
  ]), ['row_id', 'embed_id', 'version_number', 'source_checksum', 'archive_object_key', 'archive_regions']);
  const rowId = boundedString(input.row_id, 'invalid_row_id', 512);
  const embedId = boundedString(input.embed_id, 'invalid_embed_id', 512);
  const version = safeInteger(input.version_number, 'invalid_version');
  const checksum = hexDigest(input.source_checksum, 'invalid_checksum');
  const objectKey = boundedString(input.archive_object_key, 'invalid_object_key', 1024);
  if (!Array.isArray(input.archive_regions) || input.archive_regions.length < 1
      || input.archive_regions.some((region) => typeof region !== 'string' || !region || region.length > 128)) {
    fail(400, 'invalid_archive_regions');
  }
  return database.transaction(async (trx) => {
    const row = await trx(DIFFS).where({ id: rowId, embed_id: embedId, version_number: version }).forUpdate().first();
    if (!row) fail(404, 'version_not_found');
    if (row.archive_pending_object_key !== objectKey || row.archive_pending_checksum !== checksum
        || !Number.isSafeInteger(row.archive_copy_lease_until)
        || row.archive_copy_lease_until < Math.floor(Date.now() / 1000)) {
      fail(409, 'archive_copy_intent_missing_or_expired');
    }
    if (row.archive_state === 'pruned') {
      if (row.archive_checksum === checksum && row.archive_object_key === objectKey) {
        const recordedRegions = Array.isArray(row.archive_regions) ? row.archive_regions : [];
        if (input.archive_regions.some((region) => !recordedRegions.includes(region))) {
          await trx(DIFFS).where({ id: rowId }).update({
            archive_regions: [...new Set([...recordedRegions, ...input.archive_regions])],
            archive_pending_object_key: null, archive_pending_checksum: null,
            archive_copy_lease_until: null,
          });
        } else {
          await trx(DIFFS).where({ id: rowId }).update({ archive_pending_object_key: null,
            archive_pending_checksum: null, archive_copy_lease_until: null });
        }
        return { status: 'pruned', version_number: version, idempotent: true,
          superseded_object_key: row.archive_superseded_object_key ?? null };
      }
      fail(409, 'pruned_archive_immutable');
    }
    const actual = sha256(stableJson({
      encrypted_patch: row.encrypted_patch ?? null,
      encrypted_snapshot: row.encrypted_snapshot ?? null,
      version_number: version,
    }));
    if (actual !== checksum) {
      return { status: 'stale', version_number: version };
    }
    if (['copied', 'reader_active', 'pruned'].includes(row.archive_state)
        && row.archive_checksum === checksum
        && row.archive_object_key === objectKey) {
      const recordedRegions = Array.isArray(row.archive_regions) ? row.archive_regions : [];
        if (input.archive_regions.some((region) => !recordedRegions.includes(region))) {
          await trx(DIFFS).where({ id: rowId }).update({
            archive_regions: [...new Set([...recordedRegions, ...input.archive_regions])],
            archive_pending_object_key: null, archive_pending_checksum: null,
            archive_copy_lease_until: null,
          });
        } else {
          await trx(DIFFS).where({ id: rowId }).update({ archive_pending_object_key: null,
            archive_pending_checksum: null, archive_copy_lease_until: null });
        }
      return { status: row.archive_state, version_number: version, idempotent: true,
        superseded_object_key: row.archive_superseded_object_key ?? null };
    }
    if (row.archive_superseded_object_key && row.archive_superseded_object_key !== objectKey) {
      fail(409, 'superseded_archive_cleanup_required');
    }
    const superseded = row.archive_object_key && row.archive_object_key !== objectKey
      ? row.archive_object_key : null;
    await trx(DIFFS).where({ id: rowId }).update({
      archive_state: 'copied', archive_object_key: objectKey,
      archive_checksum: checksum, archive_regions: input.archive_regions,
      archive_superseded_object_key: superseded,
      archive_pending_object_key: null, archive_pending_checksum: null,
      archive_copy_lease_until: null,
      archive_copied_at: Math.floor(Date.now() / 1000),
      archive_reader_activated_at: null, archive_source_copy_until: null,
    });
    return { status: 'copied', version_number: version, idempotent: false,
      superseded_object_key: superseded };
  });
}

function archiveSourceChecksum(row) {
  return sha256(stableJson({
    encrypted_patch: row.encrypted_patch ?? null,
    encrypted_snapshot: row.encrypted_snapshot ?? null,
    version_number: row.version_number,
  }));
}

async function archiveRowAndHead(trx, input) {
  await lockIdentity(trx, `embed:${input.embed_id}`);
  const embed = await trx(EMBEDS).where({ embed_id: input.embed_id }).forUpdate().first();
  if (!embed) fail(404, 'embed_not_found');
  const row = await trx(DIFFS).where({
    id: input.row_id, embed_id: input.embed_id, version_number: input.version_number,
  }).forUpdate().first();
  if (!row) fail(404, 'version_not_found');
  if (row.hashed_user_id !== embed.hashed_user_id) fail(409, 'history_owner_mismatch');
  if (!Number.isSafeInteger(embed.version_number)
      || embed.version_number - row.version_number < RECENT_VERSION_WINDOW) {
    fail(409, 'recent_version_protected');
  }
  return { embed, row };
}

function archiveOperationInput(raw) {
  const input = exactFields(raw, new Set([
    'row_id', 'embed_id', 'version_number', 'source_checksum',
  ]), ['row_id', 'embed_id', 'version_number', 'source_checksum']);
  return {
    row_id: boundedString(input.row_id, 'invalid_row_id', 512),
    embed_id: boundedString(input.embed_id, 'invalid_embed_id', 512),
    version_number: safeInteger(input.version_number, 'invalid_version'),
    source_checksum: hexDigest(input.source_checksum, 'invalid_checksum'),
  };
}

function copiedArchiveReady(row, checksum) {
  if (row.archive_checksum !== checksum || archiveSourceChecksum(row) !== checksum
      || !row.archive_object_key || row.archive_superseded_object_key
      || !Array.isArray(row.archive_regions) || row.archive_regions.length === 0) {
    fail(409, 'archive_source_changed_or_unverified');
  }
}

async function pendingRecoveryForArchive(trx, embed) {
  const result = await trx.raw(`
    SELECT (
      EXISTS (SELECT 1 FROM chat_recovery_outputs
        WHERE state IN ('PREPARING', 'PENDING') AND deleted_at IS NULL
          AND (subject_id = ?
            OR encode(digest(target_chat_id::text, 'sha256'), 'hex') = ?
            OR encode(digest(root_chat_id::text, 'sha256'), 'hex') = ?))
      OR EXISTS (SELECT 1 FROM chat_completion_recovery_jobs
        WHERE state IN ('AVAILABLE', 'LEASED') AND invalidated_at IS NULL
          AND encode(digest(chat_id::text, 'sha256'), 'hex') = ?)
      OR EXISTS (SELECT 1 FROM chat_turn_preflights
        WHERE state = 'RUNNING' AND deletion_invalidated_at IS NULL
          AND encode(digest(chat_id::text, 'sha256'), 'hex') = ?)
    ) AS pending`, [embed.embed_id, embed.hashed_chat_id, embed.hashed_chat_id,
      embed.hashed_chat_id, embed.hashed_chat_id]);
  const pending = result?.rows?.[0]?.pending;
  if (typeof pending !== 'boolean') fail(503, 'recovery_fence_unavailable');
  return pending;
}

/** Activate verified S3 reads while retaining PostgreSQL ciphertext for rollback. */
export async function activateEmbedArchiveReader(database, raw) {
  const input = archiveOperationInput(raw);
  return database.transaction(async (trx) => {
    const rollout = await trx(ARCHIVE_ROLLOUT).where({ id: 'agentic-storage-v2' }).forShare().first();
    if (!rollout?.read_enabled || !rollout.compatibility_verified || !rollout.reader_receipt
        || rollout.failure_code) fail(409, 'version_archive_read_rollout_not_verified');
    const { row } = await archiveRowAndHead(trx, input);
    if (row.archive_state === 'reader_active' || row.archive_state === 'pruned') {
      return { status: row.archive_state, version_number: row.version_number, idempotent: true };
    }
    if (row.archive_state !== 'copied') fail(409, 'version_archive_not_copied');
    copiedArchiveReady(row, input.source_checksum);
    const now = Math.floor(Date.now() / 1000);
    const sourceCopyUntil = now + (rollout.initial_cohort ? 86400 : 0);
    await trx(DIFFS).where({ id: row.id }).update({
      archive_state: 'reader_active', archive_reader_activated_at: now,
      archive_source_copy_until: sourceCopyUntil,
    });
    return { status: 'reader_active', version_number: row.version_number,
      source_copy_until: sourceCopyUntil, idempotent: false };
  });
}

/** Clear only version payload columns after every durable reader and recovery gate. */
export async function pruneEmbedArchivePayload(database, raw) {
  const input = archiveOperationInput(raw);
  return database.transaction(async (trx) => {
    const rollout = await trx(ARCHIVE_ROLLOUT).where({ id: 'agentic-storage-v2' }).forShare().first();
    if (!rollout?.read_enabled || !rollout.pruning_enabled || !rollout.compatibility_verified
        || !rollout.reader_receipt || !rollout.validation_receipt || rollout.failure_code) {
      fail(409, 'version_archive_prune_rollout_not_verified');
    }
    const { embed, row } = await archiveRowAndHead(trx, input);
    if (row.archive_state === 'pruned') {
      if (row.archive_checksum !== input.source_checksum || row.encrypted_snapshot || row.encrypted_patch) {
        fail(409, 'pruned_archive_mismatch');
      }
      return { status: 'pruned', version_number: row.version_number, duplicate: true, pruned_count: 0 };
    }
    const now = Math.floor(Date.now() / 1000);
    if (row.archive_state !== 'reader_active' || !row.archive_reader_activated_at
        || !row.archive_source_copy_until || row.archive_source_copy_until > now) {
      fail(409, 'version_archive_rollback_buffer_active');
    }
    copiedArchiveReady(row, input.source_checksum);
    if (await pendingRecoveryForArchive(trx, embed)) fail(409, 'canonical_recovery_acknowledgement_required');
    await trx(DIFFS).where({ id: row.id }).update({
      encrypted_snapshot: null, encrypted_patch: null,
      archive_state: 'pruned', archive_pruned_at: now,
    });
    return { status: 'pruned', version_number: row.version_number, duplicate: false, pruned_count: 1 };
  });
}

export const testing = { payloadDigest, validateRequest };
