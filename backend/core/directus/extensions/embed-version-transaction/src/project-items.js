/* Atomic Project link operations for existing client-encrypted embeds.
 *
 * Adopt links an existing chat embed into a Project (one embed per file),
 * rename moves a link to a new client-derived item identity, and delete removes
 * only the link. Embeds, key wrappers and revision history are never deleted
 * here, so a commit restore can relink a file. Every operation is idempotent by
 * operation_id and leaves one receipt row that the Project timeline can show.
 * The server never sees paths: a path collision is a collision of the
 * client-derived project_item_id (UUIDv5 of the Project key and the path).
 */
import { createHash, randomUUID } from 'node:crypto';
import { ProtocolError } from './operations.js';

const PROJECTS = 'projects';
const PROJECT_ITEMS = 'project_items';
const RECEIPTS = 'project_item_operations';
const EMBEDS = 'embeds';
const EMBED_KEYS = 'embed_keys';
const CHATS = 'chats';
const MEMBERSHIPS = 'team_memberships';
const TEAMS = 'teams';
const WRITE_ROLES = ['owner', 'admin', 'member'];
const MAX_CIPHERTEXT_BYTES = 4 * 1024 * 1024;
const OPERATION_RE = /^[A-Za-z0-9._:-]{1,128}$/;
const HEX_64_RE = /^[0-9a-f]{64}$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const UUID_V5_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

/** Link kinds; `file` is the only kind whose content is a Project file. */
export const LINK_KINDS = new Set(['file', 'application', 'test_result']);
/** Catalog skill that owns each non-file kind; server-owned refreshes require it. */
const KIND_SKILL = { application: 'application', test_result: 'test_result' };

const fail = (status, code) => { throw new ProtocolError(status, code); };
const sha256 = (value) => createHash('sha256').update(value, 'utf8').digest('hex');
const stableJson = (value) => {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
};

function exactFields(value, allowed, required) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)
    || Object.keys(value).some((key) => !allowed.includes(key))
    || required.some((key) => !(key in value))) fail(400, 'invalid_request');
  return value;
}
function text(value, max = 512) {
  if (typeof value !== 'string' || !value || Buffer.byteLength(value, 'utf8') > max) fail(400, 'invalid_request');
  return value;
}
const ciphertext = (value) => text(value, MAX_CIPHERTEXT_BYTES);
function matching(value, pattern) {
  if (!pattern.test(text(value, 128))) fail(400, 'invalid_request');
  return value;
}

function commonScope(body) {
  return {
    operation_id: matching(body.operation_id, OPERATION_RE),
    project_id: text(body.project_id),
    team_id: body.team_id == null ? null : text(body.team_id),
    actor_user_hash: matching(body.actor_user_hash, HEX_64_RE),
  };
}

/** Lock the Project and require write access; Personal and Team are exclusive. */
async function authorizeProjectWrite(trx, scope) {
  const projectHash = sha256(scope.project_id);
  const teamHash = scope.team_id ? sha256(scope.team_id) : null;
  await trx.raw('SELECT pg_advisory_xact_lock(hashtextextended(?, 0))', [`project:${projectHash}`]);
  const project = await trx(PROJECTS).where({ project_id: scope.project_id }).forUpdate().first();
  if (!project) fail(404, 'project_not_found');
  if (teamHash) {
    if (project.hashed_team_id !== teamHash || project.hashed_user_id != null) fail(404, 'project_not_found');
    const membership = await trx(MEMBERSHIPS).where({
      hashed_team_id: teamHash, hashed_user_id: scope.actor_user_hash, status: 'active',
    }).forShare().first();
    const team = await trx(TEAMS).where({ hashed_team_id: teamHash, status: 'active' }).forShare().first();
    if (!team || !membership || !WRITE_ROLES.includes(membership.role)) fail(403, 'forbidden');
  } else if (project.hashed_user_id !== scope.actor_user_hash || project.hashed_team_id != null) {
    fail(404, 'project_not_found');
  }
  return { project, projectHash, teamHash };
}

/** Replay returns the first result; a different payload under the same id is refused. */
async function replayedResult(trx, identity, digest) {
  const receipt = await trx(RECEIPTS).where({ operation_identity: identity }).first();
  if (!receipt) return null;
  if (receipt.payload_digest !== digest) fail(409, 'operation_payload_mismatch');
  const result = typeof receipt.result === 'string' ? JSON.parse(receipt.result) : receipt.result;
  return { ...result, idempotent: true };
}

async function recordReceipt(trx, auth, scope, fields) {
  await trx(RECEIPTS).insert({
    id: randomUUID(), operation_id: scope.operation_id,
    operation_identity: fields.identity, operation_kind: fields.kind,
    hashed_project_id: auth.projectHash,
    hashed_user_id: auth.teamHash ? null : scope.actor_user_hash,
    hashed_team_id: auth.teamHash, actor_user_hash: scope.actor_user_hash,
    target_id_hash: fields.target_id_hash, project_item_id: fields.project_item_id,
    previous_project_item_id: fields.previous_project_item_id ?? null,
    link_kind: fields.link_kind, payload_digest: fields.digest,
    result: JSON.stringify(fields.result), created_at: fields.now,
  });
}

async function requireLinkedItem(trx, auth, scope, projectItemId) {
  const where = { hashed_project_id: auth.projectHash, project_item_id: projectItemId };
  if (auth.teamHash) where.hashed_team_id = auth.teamHash;
  else where.hashed_user_id = scope.actor_user_hash;
  const item = await trx(PROJECT_ITEMS).where(where).whereIn('item_type', ['embed', 'upload'])
    .forUpdate().first();
  if (!item) fail(404, 'project_item_not_found');
  return item;
}

/** The caller must own the chat embed in the chat's own scope (Personal or Team). */
async function requireChatEmbedOwner(trx, embed, chatId, actor) {
  const chat = await trx(CHATS).where({ id: chatId }).forShare().first();
  if (!chat || chat.storage_state === 'deleting' || embed.hashed_chat_id !== sha256(chatId)
    || (embed.hashed_team_id ?? null) !== (chat.hashed_team_id ?? null)) fail(403, 'forbidden');
  if (!chat.hashed_team_id) {
    if (chat.hashed_user_id !== actor || embed.hashed_user_id !== actor) fail(403, 'forbidden');
    return;
  }
  const membership = await trx(MEMBERSHIPS).where({
    hashed_team_id: chat.hashed_team_id, hashed_user_id: actor, status: 'active',
  }).forShare().first();
  if (!membership || !WRITE_ROLES.includes(membership.role)) fail(403, 'forbidden');
}

function requireCatalogKind(embed, kind) {
  const skill = embed.skill_id ?? null;
  if (skill === null) return;
  if (kind === 'file' ? Object.values(KIND_SKILL).includes(skill) : skill !== KIND_SKILL[kind]) {
    fail(400, 'invalid_request');
  }
}

const ADOPT_FIELDS = ['operation_id', 'project_id', 'team_id', 'chat_id', 'embed_id', 'project_item_id',
  'kind', 'target_id_encrypted', 'encrypted_display_name', 'encrypted_metadata', 'project_key_wrapper',
  'actor_user_hash'];

function validateAdopt(raw) {
  const body = exactFields(raw, ADOPT_FIELDS, ADOPT_FIELDS.filter((field) => field !== 'team_id'));
  if (!LINK_KINDS.has(body.kind)) fail(400, 'invalid_request');
  return {
    ...commonScope(body),
    chat_id: text(body.chat_id),
    embed_id: text(body.embed_id),
    // Files use hosted_file_identity(Item, path) so a path maps to one id.
    project_item_id: matching(body.project_item_id, body.kind === 'file' ? UUID_V5_RE : UUID_RE),
    kind: body.kind,
    target_id_encrypted: ciphertext(body.target_id_encrypted),
    encrypted_display_name: ciphertext(body.encrypted_display_name),
    encrypted_metadata: ciphertext(body.encrypted_metadata),
    project_key_wrapper: ciphertext(body.project_key_wrapper),
  };
}

/** Link an existing chat embed into a Project and add its Project-key wrapper. */
export async function adoptProjectEmbed(database, raw) {
  const body = validateAdopt(raw);
  const digest = sha256(stableJson(body));
  const embedHash = sha256(body.embed_id);
  return database.transaction(async (trx) => {
    const auth = await authorizeProjectWrite(trx, body);
    const identity = sha256(`${auth.projectHash}\0adopt\0${body.operation_id}`);
    const replay = await replayedResult(trx, identity, digest);
    if (replay) return replay;
    await trx.raw('SELECT pg_advisory_xact_lock(hashtextextended(?, 0))', [`embed:${body.embed_id}`]);
    const embed = await trx(EMBEDS).where({ embed_id: body.embed_id }).forUpdate().first();
    if (!embed) fail(404, 'embed_not_found');
    await requireChatEmbedOwner(trx, embed, body.chat_id, body.actor_user_hash);
    requireCatalogKind(embed, body.kind);
    const links = await trx(PROJECT_ITEMS).where({ target_id_hash: embedHash })
      .whereIn('item_type', ['embed', 'upload']);
    if (links.some((link) => link.project_item_id !== body.project_item_id
      || link.hashed_project_id !== auth.projectHash)) fail(409, 'embed_already_linked');
    const now = Math.floor(Date.now() / 1000);
    if (!links.length) {
      if (await trx(PROJECT_ITEMS).where({ project_item_id: body.project_item_id }).first()) {
        fail(409, 'path_conflict');
      }
      await trx(PROJECT_ITEMS).insert({
        id: randomUUID(), project_item_id: body.project_item_id,
        hashed_project_id: auth.projectHash, hashed_folder_id: null,
        hashed_user_id: auth.teamHash ? null : body.actor_user_hash,
        hashed_team_id: auth.teamHash, attached_by_user_hash: body.actor_user_hash,
        item_type: 'embed', link_kind: body.kind, target_id_hash: embedHash,
        target_id_encrypted: body.target_id_encrypted,
        encrypted_display_name: body.encrypted_display_name, encrypted_note: null,
        encrypted_metadata: body.encrypted_metadata, deleted_target_state: null,
        created_at: now, updated_at: now, position: 0,
      });
      await trx(PROJECTS).where({ id: auth.project.id }).increment('item_count', 1);
    }
    // The chat-key wrapper stays; the Project wrapper is added beside it. An
    // earlier wrapper (link deleted, then re-adopted) wraps the same key.
    const wrapperScope = { hashed_embed_id: embedHash, key_type: 'project', hashed_project_id: auth.projectHash };
    const wrappers = await trx(EMBED_KEYS).where(wrapperScope).forUpdate().limit(2);
    if (wrappers.length > 1) fail(409, 'embed_key_ambiguous');
    if (!wrappers.length) {
      await trx(EMBED_KEYS).insert({
        id: randomUUID(), ...wrapperScope, hashed_chat_id: null, hashed_plan_id: null,
        hashed_team_id: null, team_key_epoch: null, encrypted_embed_key: body.project_key_wrapper,
        hashed_user_id: body.actor_user_hash, created_at: now,
      });
    }
    const result = {
      status: 'adopted', operation_id: body.operation_id, embed_id: body.embed_id,
      project_item_id: body.project_item_id, kind: body.kind, idempotent: false,
    };
    await recordReceipt(trx, auth, body, {
      identity, kind: 'adopt', target_id_hash: embedHash, project_item_id: body.project_item_id,
      link_kind: body.kind, digest, result, now,
    });
    return result;
  });
}

const RENAME_FIELDS = ['operation_id', 'project_id', 'team_id', 'project_item_id', 'new_project_item_id',
  'encrypted_display_name', 'encrypted_metadata', 'actor_user_hash'];

/** Move a file link to a new path; the embed id and its revision history are kept. */
export async function renameProjectItem(database, raw) {
  const input = exactFields(raw, RENAME_FIELDS, RENAME_FIELDS.filter((field) => field !== 'team_id'));
  const body = {
    ...commonScope(input),
    project_item_id: matching(input.project_item_id, UUID_RE),
    new_project_item_id: matching(input.new_project_item_id, UUID_V5_RE),
    encrypted_display_name: ciphertext(input.encrypted_display_name),
    encrypted_metadata: ciphertext(input.encrypted_metadata),
  };
  if (body.project_item_id === body.new_project_item_id) fail(400, 'invalid_request');
  const digest = sha256(stableJson(body));
  return database.transaction(async (trx) => {
    const auth = await authorizeProjectWrite(trx, body);
    const identity = sha256(`${auth.projectHash}\0rename\0${body.operation_id}`);
    const replay = await replayedResult(trx, identity, digest);
    if (replay) return replay;
    const item = await requireLinkedItem(trx, auth, body, body.project_item_id);
    if ((item.link_kind ?? 'file') !== 'file') fail(400, 'invalid_request');
    if (await trx(PROJECT_ITEMS).where({ project_item_id: body.new_project_item_id }).first()) {
      fail(409, 'path_conflict');
    }
    const now = Math.floor(Date.now() / 1000);
    await trx(PROJECT_ITEMS).where({ id: item.id }).update({
      project_item_id: body.new_project_item_id, encrypted_display_name: body.encrypted_display_name,
      encrypted_metadata: body.encrypted_metadata, updated_at: now,
    });
    const result = {
      status: 'renamed', operation_id: body.operation_id, project_item_id: body.new_project_item_id,
      previous_project_item_id: body.project_item_id, target_id_hash: item.target_id_hash, idempotent: false,
    };
    await recordReceipt(trx, auth, body, {
      identity, kind: 'rename', target_id_hash: item.target_id_hash,
      project_item_id: body.new_project_item_id, previous_project_item_id: body.project_item_id,
      link_kind: item.link_kind ?? 'file', digest, result, now,
    });
    return result;
  });
}

const DELETE_FIELDS = ['operation_id', 'project_id', 'team_id', 'project_item_id', 'actor_user_hash'];

/** Remove only the link. The embed, its wrappers and revisions stay for restore. */
export async function deleteProjectItem(database, raw) {
  const input = exactFields(raw, DELETE_FIELDS, DELETE_FIELDS.filter((field) => field !== 'team_id'));
  const body = { ...commonScope(input), project_item_id: matching(input.project_item_id, UUID_RE) };
  const digest = sha256(stableJson(body));
  return database.transaction(async (trx) => {
    const auth = await authorizeProjectWrite(trx, body);
    const identity = sha256(`${auth.projectHash}\0delete\0${body.operation_id}`);
    const replay = await replayedResult(trx, identity, digest);
    if (replay) return replay;
    const item = await requireLinkedItem(trx, auth, body, body.project_item_id);
    await trx(PROJECT_ITEMS).where({ id: item.id }).del();
    await trx(PROJECTS).where({ id: auth.project.id }).increment('item_count', -1);
    const now = Math.floor(Date.now() / 1000);
    const result = {
      status: 'deleted', operation_id: body.operation_id, project_item_id: body.project_item_id,
      target_id_hash: item.target_id_hash, idempotent: false,
    };
    await recordReceipt(trx, auth, body, {
      identity, kind: 'delete', target_id_hash: item.target_id_hash,
      project_item_id: body.project_item_id, previous_project_item_id: body.project_item_id,
      link_kind: item.link_kind ?? 'file', digest, result, now,
    });
    return result;
  });
}

/** Validate the internal server-owned refresh marker supplied by the API. */
export function validateServerOwnedRefresh(raw) {
  if (raw === undefined) return null;
  const refresh = exactFields(raw, ['link_kind', 'version_number'], ['link_kind', 'version_number']);
  if (!Object.hasOwn(KIND_SKILL, refresh.link_kind) || !Number.isSafeInteger(refresh.version_number)
    || refresh.version_number < 2) fail(400, 'invalid_server_owned_refresh');
  return refresh;
}

/** Whether every link of a fenced embed admits this server-owned refresh. File links never do. */
export function linksAdmitServerOwnedRefresh(links, refresh) {
  return refresh !== null && links.length > 0
    && links.every((link) => (link.link_kind ?? 'file') === refresh.link_kind);
}

/** The refresh is exactly the next version of an existing head of the matching catalog skill. */
export function assertServerOwnedRefresh(embed, payload, refresh, { bundle, enrichment, currentVersion }) {
  if (!embed || bundle || enrichment || embed.skill_id !== KIND_SKILL[refresh.link_kind]
    || payload.version_number !== refresh.version_number || refresh.version_number !== currentVersion + 1
    || (payload.encrypted_type != null && payload.encrypted_type !== embed.encrypted_type)
    || (payload.hashed_chat_id != null && payload.hashed_chat_id !== embed.hashed_chat_id)
    || (payload.parent_embed_id ?? null) !== (embed.parent_embed_id ?? null)) {
    fail(403, 'project_context_required');
  }
}
