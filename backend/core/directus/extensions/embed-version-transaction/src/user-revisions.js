/* User revision commit: a user's own edit of an embed becomes its next version.
 *
 * Specification: feature.embed-user-edits (history.one-per-embed,
 * edit.next-version, event.project-edit-reaches-chat, restore.creates-version,
 * files.client-made-version). Plan: docs/plans/embed-user-edit-versions.
 *
 * One atomic, idempotent write for an edit, an Enhance result, a restore or
 * (later) a client-made file, in either of two exclusive scopes:
 *   - chat:    {kind: "chat", chat_id, team_id?}  chat owner, or an active Team
 *              owner/admin/member of the Team chat. Project-linked embeds are
 *              refused here, so a Project file has exactly one writer scope.
 *   - project: {kind: "project", project_id, team_id?}  Project write access and
 *              an exact, live Project link to this embed.
 * "Project-linked" means a live file link (project-items.js liveProjectFileLinks):
 * a link whose target was deleted neither authorizes nor blocks.
 * The head, the history rows and the pending chat notice are opaque ciphertext
 * or content-free metadata. The server checks the expected version and the
 * SHA-256 of the current head ciphertext, so an edit based on an outdated
 * version is refused instead of overwriting the newer one. File references
 * are limited to keys the embed already owns (restore) or to the server-made
 * result of a finished Enhance job of the same user, embed and version.
 * `commitChatDiagramRevision` stays the separate WebSocket path.
 */
import { createHash, randomUUID } from 'node:crypto';
import { ProtocolError, isGeneratedImageChild, unionFileKeys } from './operations.js';
import { liveProjectFileLinks } from './project-items.js';

const EMBEDS = 'embeds';
const DIFFS = 'embed_diffs';
const RECEIPTS = 'embed_user_revision_commits';
const NOTICES = 'pending_embed_notices';
const ENHANCE_JOBS = 'image_enhance_jobs';
const PROJECTS = 'projects';
const PROJECT_ITEMS = 'project_items';
const CHATS = 'chats';
const MEMBERSHIPS = 'team_memberships';
const TEAMS = 'teams';
const WRITE_ROLES = ['owner', 'admin', 'member'];
const MAX_CIPHERTEXT_BYTES = 4 * 1024 * 1024;
const MAX_FILE_REFS = 64;
const MAX_VERSION = 2_147_483_646;
const HEX_64_RE = /^[0-9a-f]{64}$/;
const OPERATION_RE = /^[A-Za-z0-9._:-]{1,128}$/;
const UUID_V5_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

/** What the user did; stored as the plaintext `embed_diffs.revision_action`. */
export const USER_REVISION_ACTIONS = new Set(['edit', 'enhance', 'restore', 'crop']);

/**
 * Stored `app_id/skill_id` pairs a user may edit in either scope. A Project-native
 * file (UUIDv5, created by the Project commit path without a catalog projection)
 * is accepted in Project scope only; its type is client-encrypted.
 */
export const USER_EDITABLE_TYPES = new Set([
  'diagrams/html', 'slides/deck', 'sheets/sheet', 'docs/document',
  'images/generated_image', 'images/upload',
]);
const IMAGE_TYPES = new Set(['images/generated_image', 'images/upload']);
/** Enhance job states (owned by the images Enhance task). Only `ready` may be committed. */
export const ENHANCE_JOB_STATES = new Set(['pending', 'ready', 'committed', 'failed', 'expired']);

const fail = (status, code) => { throw new ProtocolError(status, code); };
const sha256 = (value) => createHash('sha256').update(value, 'utf8').digest('hex');
const stableJson = (value) => {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
};
const nowSeconds = () => Math.floor(Date.now() / 1000);

function exactFields(value, allowed, required) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)
    || Object.keys(value).some((key) => !allowed.includes(key))
    || required.some((key) => !(key in value))) fail(400, 'invalid_request');
  return value;
}
function text(value, code, max = 512) {
  if (typeof value !== 'string' || !value || Buffer.byteLength(value, 'utf8') > max) fail(400, code);
  return value;
}
function matching(value, pattern, code) {
  if (!pattern.test(text(value, code, 128))) fail(400, code);
  return value;
}
function integer(value, code, min = 0) {
  if (!Number.isSafeInteger(value) || value < min || value > MAX_VERSION) fail(400, code);
  return value;
}
function logicalVersion(value) {
  if (value == null) return 1;
  if (!Number.isSafeInteger(value) || value < 1 || value > MAX_VERSION + 1) fail(409, 'invalid_current_revision');
  return value;
}

function validateScope(raw) {
  const scope = exactFields(raw, ['kind', 'chat_id', 'project_id', 'team_id'], ['kind']);
  const teamId = scope.team_id == null ? null : text(scope.team_id, 'invalid_team_id');
  if (scope.kind === 'chat') {
    if ('project_id' in scope) fail(400, 'invalid_scope');
    return { kind: 'chat', chat_id: text(scope.chat_id, 'invalid_chat_id'), team_id: teamId };
  }
  if (scope.kind === 'project') {
    if ('chat_id' in scope) fail(400, 'invalid_scope');
    return { kind: 'project', project_id: text(scope.project_id, 'invalid_project_id'), team_id: teamId };
  }
  return fail(400, 'invalid_scope');
}

function validateHead(raw) {
  const head = exactFields(raw, [
    'encrypted_content', 'encrypted_text_preview', 'content_hash', 'status', 'updated_at',
  ], ['encrypted_content', 'status', 'updated_at']);
  const result = {
    encrypted_content: text(head.encrypted_content, 'invalid_ciphertext', MAX_CIPHERTEXT_BYTES),
    status: text(head.status, 'invalid_status', 64),
    updated_at: integer(head.updated_at, 'invalid_timestamp'),
  };
  if (result.status !== 'finished') fail(400, 'invalid_status');
  if ('encrypted_text_preview' in head) {
    result.encrypted_text_preview = head.encrypted_text_preview == null ? null
      : text(head.encrypted_text_preview, 'invalid_ciphertext', MAX_CIPHERTEXT_BYTES);
  }
  if ('content_hash' in head) result.content_hash = matching(head.content_hash, HEX_64_RE, 'invalid_content_hash');
  return result;
}

/* Full snapshots only: version N+1 always, version N only as the missing base. */
function validateHistory(raw, expectedRevision) {
  if (!Array.isArray(raw) || raw.length < 1 || raw.length > 2) fail(400, 'invalid_history_rows');
  const rows = raw.map((rawRow) => {
    const row = exactFields(rawRow, ['version_number', 'encrypted_snapshot', 'created_at'],
      ['version_number', 'encrypted_snapshot', 'created_at']);
    const version = integer(row.version_number, 'invalid_history_rows', 1);
    if (version !== expectedRevision && version !== expectedRevision + 1) fail(400, 'invalid_history_rows');
    return {
      version_number: version,
      encrypted_snapshot: text(row.encrypted_snapshot, 'invalid_history_rows', MAX_CIPHERTEXT_BYTES),
      created_at: integer(row.created_at, 'invalid_timestamp'),
    };
  });
  if (!rows.some((row) => row.version_number === expectedRevision + 1)
    || new Set(rows.map((row) => row.version_number)).size !== rows.length) fail(400, 'invalid_history_rows');
  return rows.sort((left, right) => left.version_number - right.version_number);
}

function fileRef(raw) {
  const ref = exactFields(raw, ['bucket', 'key'], ['bucket', 'key']);
  return { bucket: text(ref.bucket, 'invalid_file_reference', 128), key: text(ref.key, 'invalid_file_reference', 1024) };
}

function validateFiles(raw, action) {
  if (raw == null) {
    if (action === 'enhance' || action === 'crop') fail(400, 'file_source_required');
    return null;
  }
  const files = exactFields(raw, ['head_file_keys', 'new_files'], []);
  const hasHead = files.head_file_keys != null;
  const hasNew = files.new_files != null;
  if (hasHead === hasNew) fail(400, 'invalid_file_source');
  if (hasHead) {
    if (action !== 'restore' && action !== 'edit') fail(400, 'invalid_file_source');
    if (!Array.isArray(files.head_file_keys) || files.head_file_keys.length < 1
      || files.head_file_keys.length > MAX_FILE_REFS) fail(400, 'invalid_file_reference');
    return { head_file_keys: files.head_file_keys.map(fileRef) };
  }
  if (!Array.isArray(files.new_files) || files.new_files.length !== 1) fail(400, 'invalid_file_source');
  const source = exactFields(files.new_files[0], ['kind', 'operation_id', 'upload_id'], ['kind']);
  // Client-made files ({kind: "upload", upload_id}) are the next lane's source.
  if (source.kind === 'upload') fail(400, 'unsupported_file_source');
  if (source.kind !== 'enhance' || action !== 'enhance' || 'upload_id' in source) fail(400, 'invalid_file_source');
  return { new_files: [{ kind: 'enhance', operation_id: matching(source.operation_id, OPERATION_RE, 'invalid_operation_id') }] };
}

export function validateUserRevision(raw) {
  const body = exactFields(raw, [
    'operation_id', 'embed_id', 'scope', 'action', 'expected_revision', 'expected_content_hash',
    'head', 'history_rows', 'restored_from', 'files', 'actor_user_hash',
  ], ['operation_id', 'embed_id', 'scope', 'action', 'expected_revision', 'expected_content_hash',
    'head', 'history_rows', 'actor_user_hash']);
  if (!USER_REVISION_ACTIONS.has(body.action)) fail(400, 'invalid_action');
  const expectedRevision = integer(body.expected_revision, 'invalid_expected_revision', 1);
  let restoredFrom = null;
  if (body.action === 'restore') {
    restoredFrom = integer(body.restored_from, 'invalid_restored_from', 1);
    if (restoredFrom > expectedRevision) fail(400, 'invalid_restored_from');
  } else if (body.restored_from != null) fail(400, 'invalid_restored_from');
  return {
    operation_id: matching(body.operation_id, OPERATION_RE, 'invalid_operation_id'),
    embed_id: text(body.embed_id, 'invalid_embed_id'),
    scope: validateScope(body.scope),
    action: body.action,
    expected_revision: expectedRevision,
    expected_content_hash: matching(body.expected_content_hash, HEX_64_RE, 'invalid_content_hash'),
    head: validateHead(body.head),
    history_rows: validateHistory(body.history_rows, expectedRevision),
    restored_from: restoredFrom,
    files: validateFiles(body.files, body.action),
    actor_user_hash: matching(body.actor_user_hash, HEX_64_RE, 'invalid_actor'),
  };
}

async function lock(trx, identity) {
  await trx.raw('SELECT pg_advisory_xact_lock(hashtextextended(?, 0))', [identity]);
}

async function requireTeamWriter(trx, teamHash, actor, code) {
  const membership = await trx(MEMBERSHIPS).where({
    hashed_team_id: teamHash, hashed_user_id: actor, status: 'active',
  }).forShare().first();
  const team = await trx(TEAMS).where({ hashed_team_id: teamHash, status: 'active' }).forShare().first();
  if (!team || !membership || !WRITE_ROLES.includes(membership.role)) fail(403, code);
}

/* A Project file made by the Project commit path: hosted UUIDv5 id, no catalog projection. */
const isProjectNativeFile = (embed) => UUID_V5_RE.test(embed.embed_id)
  && embed.app_id == null && embed.skill_id == null && embed.parent_embed_id == null;

async function authorizeChat(trx, body) {
  const { chat_id: chatId } = body.scope;
  const teamHash = body.scope.team_id ? sha256(body.scope.team_id) : null;
  const actor = body.actor_user_hash;
  await lock(trx, `embed:${body.embed_id}`);
  const chat = await trx(CHATS).where({ id: chatId }).forShare().first();
  if (!chat || chat.storage_state === 'deleting' || (chat.hashed_team_id ?? null) !== teamHash) {
    fail(403, 'chat_access_denied');
  }
  if (teamHash) await requireTeamWriter(trx, teamHash, actor, 'chat_access_denied');
  else if (chat.hashed_user_id !== actor) fail(403, 'chat_access_denied');
  const linked = await liveProjectFileLinks(trx(PROJECT_ITEMS).where({ target_id_hash: sha256(body.embed_id) })).first();
  if (linked) fail(403, 'project_context_required');
  const embed = await trx(EMBEDS).where({ embed_id: body.embed_id }).forUpdate().first();
  if (!embed) fail(404, 'embed_not_found');
  if (embed.hashed_chat_id !== sha256(chatId) || (embed.hashed_team_id ?? null) !== teamHash
    || (!teamHash && embed.hashed_user_id !== actor)
    || ![null, undefined, 'chat'].includes(embed.workspace_origin)) fail(403, 'embed_access_denied');
  const generatedChild = isGeneratedImageChild(body.embed_id, embed);
  // UUIDv5 is reserved for Project files and registered producer children.
  if (UUID_V5_RE.test(body.embed_id) && !generatedChild) fail(403, 'project_context_required');
  if (embed.root_embed_id != null && embed.root_embed_id !== body.embed_id
    && !(generatedChild && embed.root_embed_id === embed.parent_embed_id)) fail(403, 'embed_access_denied');
  return { embed, teamHash, scopeHash: sha256(chatId), projectNative: false };
}

async function authorizeProject(trx, body) {
  const { project_id: projectId } = body.scope;
  const projectHash = sha256(projectId);
  const teamHash = body.scope.team_id ? sha256(body.scope.team_id) : null;
  const actor = body.actor_user_hash;
  await lock(trx, `project:${projectHash}`);
  const project = await trx(PROJECTS).where({ project_id: projectId }).forUpdate().first();
  if (!project) fail(403, 'project_access_denied');
  if (teamHash) {
    if (project.hashed_team_id !== teamHash || project.hashed_user_id != null) fail(403, 'project_access_denied');
    await requireTeamWriter(trx, teamHash, actor, 'project_access_denied');
  } else if (project.hashed_user_id !== actor || project.hashed_team_id != null) {
    fail(403, 'project_access_denied');
  }
  const itemWhere = { hashed_project_id: projectHash, target_id_hash: sha256(body.embed_id) };
  if (teamHash) itemWhere.hashed_team_id = teamHash;
  else itemWhere.hashed_user_id = actor;
  const item = await liveProjectFileLinks(trx(PROJECT_ITEMS).where(itemWhere)).first();
  if (!item) fail(403, 'project_item_access_denied');
  await lock(trx, `embed:${body.embed_id}`);
  const embed = await trx(EMBEDS).where({ embed_id: body.embed_id }).forUpdate().first();
  if (!embed) fail(404, 'embed_not_found');
  // Team Project files may be edited by any Team writer; a Personal file only by its owner.
  if ((!teamHash && (embed.hashed_user_id !== actor || embed.hashed_team_id != null))
    || (teamHash && embed.hashed_team_id != null && embed.hashed_team_id !== teamHash)
    || embed.workspace_origin === 'web_apps') fail(403, 'embed_access_denied');
  const projectNative = isProjectNativeFile(embed);
  if (UUID_V5_RE.test(body.embed_id) && !projectNative && !isGeneratedImageChild(body.embed_id, embed)) {
    fail(403, 'embed_access_denied');
  }
  return { embed, teamHash, scopeHash: projectHash, projectNative };
}

/**
 * File keys of the finished server-made Enhance result for this exact embed,
 * requester, target version and scope. The job's scope_kind and scope_id_hash
 * (SHA-256 of the raw chat_id or project_id, as POST /v1/images/enhance stores
 * them) must equal the commit's, so a result made in one scope cannot be saved
 * from another. The images Enhance lane owns the job rows
 * (schema image_enhance_jobs.yml; backend/apps/images/enhance_jobs.py). This
 * commit reads a `ready`, unexpired job under a row lock and, in the same
 * transaction, moves it to `committed` with the compare-and-set on the row
 * `version` that every job writer uses, so the expiry sweep cannot also win.
 */
export async function lookupEnhanceResult(trx, {
  operationId, embedId, actor, targetVersion, scopeKind, scopeHash, now,
}) {
  const job = await trx(ENHANCE_JOBS).where({
    operation_id: operationId, embed_id: embedId, hashed_user_id: actor,
  }).forUpdate().first();
  if (!job || !ENHANCE_JOB_STATES.has(job.state)) fail(403, 'enhance_result_not_found');
  if (job.scope_kind !== scopeKind || job.scope_id_hash !== scopeHash) fail(409, 'enhance_scope_mismatch');
  if (job.state !== 'ready') fail(409, 'enhance_result_not_ready');
  if (!Number.isSafeInteger(Number(job.expires_at)) || Number(job.expires_at) <= now) {
    fail(409, 'enhance_result_expired');
  }
  if (Number(job.target_version) !== targetVersion) fail(409, 'enhance_version_mismatch');
  const keys = unionFileKeys(job.result_file_keys, []);
  if (keys.length < 1 || keys.length > MAX_FILE_REFS) fail(409, 'enhance_result_not_ready');
  const rowVersion = Number(job.version ?? 0);
  return {
    where: { operation_id: operationId, embed_id: embedId, hashed_user_id: actor, state: 'ready', version: job.version ?? null },
    committed: { state: 'committed', version: rowVersion + 1, updated_at: now },
    keys,
  };
}

function typeAllowed(embed, scopeKind, projectNative) {
  if (USER_EDITABLE_TYPES.has(`${embed.app_id}/${embed.skill_id}`)) return true;
  return scopeKind === 'project' && projectNative;
}

async function storeHistory(trx, body, embed) {
  const versions = body.history_rows.map((row) => row.version_number);
  const base = body.expected_revision;
  const existing = await trx(DIFFS).where({ embed_id: body.embed_id })
    .whereIn('version_number', [base, base + 1]);
  const byVersion = new Map(existing.map((row) => [Number(row.version_number), row]));
  for (const row of body.history_rows) {
    const previous = byVersion.get(row.version_number);
    if (previous) {
      if (previous.encrypted_snapshot !== row.encrypted_snapshot || previous.created_at !== row.created_at) {
        fail(409, 'immutable_history_mismatch');
      }
      continue;
    }
    const isNext = row.version_number === base + 1;
    await trx(DIFFS).insert({
      id: randomUUID(), embed_id: body.embed_id, hashed_user_id: embed.hashed_user_id,
      version_number: row.version_number, encrypted_snapshot: row.encrypted_snapshot,
      encrypted_patch: null, has_snapshot: true, has_patch: false, created_at: row.created_at,
      revision_origin: isNext ? 'user' : null, revision_action: isNext ? body.action : null,
    });
  }
  if (!byVersion.has(base) && !versions.includes(base)) fail(409, 'base_snapshot_required');
}

function committedResult(body, receipt, idempotent) {
  const keys = receipt.head_file_keys == null ? null : unionFileKeys(receipt.head_file_keys, []);
  return {
    status: 'committed', operation_id: body.operation_id, embed_id: body.embed_id,
    current_revision: receipt.committed_revision, current_content_hash: receipt.content_hash,
    revision_origin: 'user', revision_action: receipt.revision_action, idempotent,
    pending_notice: Boolean(receipt.pending_notice),
    image: receipt.is_image ? { head_file_keys: keys, owner_is_actor: Boolean(receipt.owner_is_actor) } : null,
  };
}

/** Atomically publish one user-made version N+1 of an embed (see module doc). */
export async function commitUserEmbedRevision(database, raw) {
  const body = validateUserRevision(raw);
  const digest = sha256(stableJson(body));
  const identity = sha256(`${body.embed_id}\0${body.operation_id}`);
  return database.transaction(async (trx) => {
    const { embed, teamHash, scopeHash, projectNative } = body.scope.kind === 'chat'
      ? await authorizeChat(trx, body) : await authorizeProject(trx, body);
    if (embed.encryption_mode !== 'client') fail(403, 'embed_access_denied');
    if (!typeAllowed(embed, body.scope.kind, projectNative)) fail(403, 'embed_type_not_editable');
    const isImage = IMAGE_TYPES.has(`${embed.app_id}/${embed.skill_id}`);
    if (body.files && !isImage) fail(400, 'invalid_file_source');
    if (body.action === 'enhance' && !isImage) fail(400, 'invalid_action');

    const receipt = await trx(RECEIPTS).where({ commit_identity: identity }).first();
    if (receipt) {
      if (receipt.payload_digest !== digest) fail(409, 'operation_payload_mismatch');
      return committedResult(body, receipt, true);
    }

    const current = logicalVersion(embed.version_number);
    const currentHash = sha256(embed.encrypted_content ?? '');
    if (current !== body.expected_revision || currentHash !== body.expected_content_hash) {
      return { status: 'conflict', operation_id: body.operation_id, embed_id: body.embed_id,
        current_revision: current, current_content_hash: currentHash };
    }
    const next = current + 1;
    if (body.restored_from != null && body.restored_from < current) {
      const source = await trx(DIFFS).where({ embed_id: body.embed_id, version_number: body.restored_from }).first();
      if (!source) fail(409, 'restore_source_missing');
    }

    let headFileKeys = null;
    let enhanceJob = null;
    if (body.files?.head_file_keys) {
      const owned = new Set(unionFileKeys(embed.s3_file_keys, [])
        .map((ref) => `${ref.bucket}\u0000${ref.key}`));
      if (body.files.head_file_keys.some((ref) => !owned.has(`${ref.bucket}\u0000${ref.key}`))) {
        fail(403, 'foreign_file_key');
      }
      headFileKeys = unionFileKeys(body.files.head_file_keys, []);
    } else if (body.files?.new_files) {
      enhanceJob = await lookupEnhanceResult(trx, {
        operationId: body.files.new_files[0].operation_id, embedId: body.embed_id,
        actor: body.actor_user_hash, targetVersion: next, scopeKind: body.scope.kind, scopeHash,
        now: nowSeconds(),
      });
      headFileKeys = enhanceJob.keys;
    }

    await storeHistory(trx, body, embed);
    const headUpdate = { ...body.head, version_number: next };
    if (enhanceJob) headUpdate.s3_file_keys = JSON.stringify(unionFileKeys(embed.s3_file_keys, enhanceJob.keys));
    await trx(EMBEDS).where({ id: embed.id }).update(headUpdate);
    if (enhanceJob && await trx(ENHANCE_JOBS).where(enhanceJob.where).update(enhanceJob.committed) !== 1) {
      fail(409, 'enhance_result_not_ready');
    }

    const createdAt = nowSeconds();
    // A Project-native file's hashed_chat_id names the chat that authored it, not a home chat.
    const pendingNotice = Boolean(embed.hashed_chat_id) && !projectNative;
    if (pendingNotice) {
      await trx(NOTICES).insert({
        id: randomUUID(), notice_identity: sha256(`${body.embed_id}\0${next}`),
        hashed_chat_id: embed.hashed_chat_id, embed_id: body.embed_id, version: next,
        action: body.action, surface: body.scope.kind,
        restored_from: body.action === 'restore' ? body.restored_from : null, created_at: createdAt,
      });
    }
    const stored = {
      id: randomUUID(), operation_id: body.operation_id, commit_identity: identity,
      embed_id: body.embed_id, scope_kind: body.scope.kind, hashed_scope_id: scopeHash,
      hashed_team_id: teamHash, actor_user_hash: body.actor_user_hash, revision_origin: 'user',
      revision_action: body.action, payload_digest: digest, expected_revision: current,
      committed_revision: next, content_hash: sha256(body.head.encrypted_content),
      restored_from: body.restored_from, is_image: isImage,
      owner_is_actor: embed.hashed_user_id === body.actor_user_hash,
      head_file_keys: headFileKeys ? JSON.stringify(headFileKeys) : null,
      pending_notice: pendingNotice, created_at: createdAt,
    };
    await trx(RECEIPTS).insert(stored);
    return committedResult(body, stored, false);
  });
}
