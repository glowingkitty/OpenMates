/* Atomic Specification head/revision publication. All authored text is ciphertext. */
import { createHash, randomUUID } from 'node:crypto';

const HEADS = 'user_specifications';
const REVISIONS = 'user_specification_revisions';
const HASH = /^[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CONTENT_FIELDS = ['content_hash', 'project_surface_catalog_revision_id',
  'encrypted_title', 'encrypted_summary', 'encrypted_specification_document'];

export class SpecificationError extends Error {
  constructor(status, code) { super(code); this.status = status; this.code = code; }
}
const fail = (status, code) => { throw new SpecificationError(status, code); };
const validHash = (value) => typeof value === 'string' && HASH.test(value);
const validId = (value) => typeof value === 'string' && UUID.test(value);

function validate(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) fail(400, 'invalid_request');
  if (!['create', 'revise', 'approve'].includes(raw.operation)
      || !validId(raw.specification_id) || !validId(raw.project_id) || !validHash(raw.home_project_hash)
      || !validHash(raw.actor_hash)
      || !((validHash(raw.hashed_user_id) && raw.hashed_team_id === null)
        || (raw.hashed_user_id === null && validHash(raw.hashed_team_id)))) fail(400, 'invalid_request');
  if (!validId(raw.revision_id)) fail(400, 'invalid_revision');
  if (createHash('sha256').update(raw.project_id).digest('hex') !== raw.home_project_hash) fail(400, 'invalid_project_hash');
  if (!validHash(raw.content_hash)) fail(400, 'invalid_content_hash');
  if (raw.operation === 'approve') return raw;
  for (const name of CONTENT_FIELDS) {
    if (typeof raw[name] !== 'string' || !raw[name]
        || Buffer.byteLength(raw[name], 'utf8') > (name === 'encrypted_specification_document' ? 4 * 1024 * 1024 : 16384)) {
      fail(400, 'invalid_revision');
    }
  }
  if (raw.operation === 'revise' && !validId(raw.base_revision_id)) fail(400, 'invalid_base_revision');
  if (raw.operation === 'create') {
    const wrappers = raw.key_wrappers;
    if (!Array.isArray(wrappers) || !wrappers.length || wrappers.length > 20) fail(400, 'invalid_key_wrappers');
    let projectWrapper = false;
    for (const wrapper of wrappers) {
      if (!wrapper || !['master', 'project', 'team'].includes(wrapper.key_type)
          || typeof wrapper.encrypted_specification_key !== 'string'
          || !wrapper.encrypted_specification_key || wrapper.encrypted_specification_key.length > 16384
          || Object.keys(wrapper).some((key) => !['key_type', 'encrypted_specification_key', 'hashed_project_id', 'hashed_team_id', 'team_key_epoch'].includes(key))) {
        fail(400, 'invalid_key_wrappers');
      }
      if (wrapper.key_type === 'project') {
        if (wrapper.hashed_project_id !== raw.home_project_hash || wrapper.hashed_team_id || wrapper.team_key_epoch !== undefined) fail(400, 'invalid_key_wrappers');
        projectWrapper = true;
      } else if (wrapper.key_type === 'master') {
        if (!raw.hashed_user_id || wrapper.hashed_project_id || wrapper.hashed_team_id || wrapper.team_key_epoch !== undefined) fail(400, 'invalid_key_wrappers');
      } else if (!raw.hashed_team_id || wrapper.hashed_team_id !== raw.hashed_team_id
          || wrapper.hashed_project_id || !Number.isSafeInteger(wrapper.team_key_epoch) || wrapper.team_key_epoch < 1) {
        fail(400, 'invalid_key_wrappers');
      }
    }
    if (!projectWrapper) fail(400, 'missing_project_key_wrapper');
  }
  return raw;
}

function sameScope(head, body) {
  return head.hashed_user_id === body.hashed_user_id
    && head.hashed_team_id === body.hashed_team_id && head.home_project_hash === body.home_project_hash;
}

function sameRevision(revision, body) {
  return revision.specification_id === body.specification_id
    && revision.supersedes_revision_id === (body.operation === 'create' ? null : body.base_revision_id)
    && CONTENT_FIELDS.every((name) => revision[name] === body[name]);
}

export async function executeSpecification(database, raw) {
  const body = validate(raw);
  return database.transaction(async (trx) => {
    // Lock the parent before its head, also serializing with Project moves.
    const project = await trx('projects').where({ project_id: body.project_id,
      hashed_user_id: body.hashed_user_id, hashed_team_id: body.hashed_team_id }).forUpdate().first();
    if (!project) fail(404, 'project_not_found');
    // Serialize edits and approval on the same head, even across API replicas.
    let head = await trx(HEADS).where({ specification_id: body.specification_id }).forUpdate().first();
    if (head && !sameScope(head, body)) fail(404, 'specification_not_found');
    if (!head && body.operation !== 'create') fail(404, 'specification_not_found');
    const now = Math.floor(Date.now() / 1000);

    if (body.operation === 'approve') {
      if (head.current_revision_id !== body.revision_id) fail(409, 'revision_conflict');
      const revision = await trx(REVISIONS).where({ specification_id: body.specification_id, revision_id: body.revision_id }).first();
      if (!revision || revision.content_hash !== body.content_hash) fail(409, 'revision_conflict');
      if (revision.approval_state !== 'approved') {
        const approval = { approval_state: 'approved', approved_by_hash: body.actor_hash, approved_at: now };
        await trx(REVISIONS).where({ id: revision.id }).update(approval);
        head = { ...head, status: 'approved', version: head.version + 1, updated_at: now };
        await trx(HEADS).where({ id: head.id }).update({ status: head.status, version: head.version, updated_at: now });
        return { specification: head, revision: { ...revision, ...approval } };
      }
      return { specification: head, revision };
    }

    const previous = await trx(REVISIONS).where({ revision_id: body.revision_id }).first();
    if (previous) {
      if (!head || !sameRevision(previous, body)) fail(409, 'revision_identity_conflict');
      if (body.operation === 'create') {
        const wrappers = typeof head.key_wrappers === 'string' ? JSON.parse(head.key_wrappers) : head.key_wrappers;
        if (JSON.stringify(wrappers) !== JSON.stringify(body.key_wrappers)) fail(409, 'revision_identity_conflict');
      }
      return { specification: head, revision: previous, replayed: true };
    }
    if (body.operation === 'create' && head) fail(409, 'specification_exists');
    if (body.operation === 'revise' && head.current_revision_id !== body.base_revision_id) fail(409, 'revision_conflict');
    const number = head ? head.current_revision_number + 1 : 1;
    const revision = { id: randomUUID(), revision_id: body.revision_id,
      specification_id: body.specification_id, revision_number: number,
      hashed_user_id: body.hashed_user_id, hashed_team_id: body.hashed_team_id, home_project_hash: body.home_project_hash,
      supersedes_revision_id: body.operation === 'create' ? null : body.base_revision_id,
      ...Object.fromEntries(CONTENT_FIELDS.map((name) => [name, body[name]])),
      approval_state: 'draft', approved_by_hash: null, approved_at: null, created_at: now };
    const update = { current_revision_id: revision.revision_id, current_revision_number: number,
      status: 'draft', encrypted_title: body.encrypted_title, encrypted_summary: body.encrypted_summary,
      version: head ? head.version + 1 : 1, updated_at: now };
    if (!head) {
      head = { id: randomUUID(), specification_id: body.specification_id,
        hashed_user_id: body.hashed_user_id, hashed_team_id: body.hashed_team_id,
        home_project_hash: body.home_project_hash, linked_project_hashes: JSON.stringify([body.home_project_hash]),
        key_wrappers: JSON.stringify(body.key_wrappers), created_at: now, ...update };
      await trx(HEADS).insert(head);
    } else {
      await trx(HEADS).where({ id: head.id }).update(update);
      head = { ...head, ...update };
    }
    await trx(REVISIONS).insert(revision);
    return { specification: head, revision };
  });
}
