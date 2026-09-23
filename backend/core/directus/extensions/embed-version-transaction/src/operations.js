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
    if ((snapshot === null) === (patch === null)) fail(400, 'invalid_history_rows');
    if (version === 1 && snapshot === null) fail(400, 'invalid_history_rows');
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
          id: randomUUID(), embed_id: body.embed_id, hashed_user_id: embed.hashed_user_id, ...row,
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

export const testing = { payloadDigest, validateRequest };
