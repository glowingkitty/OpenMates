import assert from 'node:assert/strict';
import test from 'node:test';
import { createHash, randomUUID } from 'node:crypto';
import { executeSpecification } from '../src/operations.js';
const PROJECT = '00000000-0000-4000-8000-000000000001';
const PROJECT_HASH = createHash('sha256').update(PROJECT).digest('hex');

class Query {
  constructor(rows, database) { this.rows = rows; this.database = database; this.filters = {}; }
  where(filters) { Object.assign(this.filters, filters); return this; }
  forUpdate() { this.database.locks += 1; return this; }
  selected() { return this.rows.filter((row) => Object.entries(this.filters).every(([key, value]) => row[key] === value)); }
  async first() { return this.selected()[0]; }
  async insert(row) {
    if (this.database.failInsert && row.revision_id) throw new Error('injected insert failure');
    this.rows.push(structuredClone(row));
  }
  async update(patch) { for (const row of this.selected()) Object.assign(row, patch); }
}
function database() {
  const db = { rows: { projects: [{ project_id: PROJECT, hashed_user_id: 'a'.repeat(64), hashed_team_id: null }],
    user_specifications: [], user_specification_revisions: [] }, locks: 0 };
  db.transaction = async (callback) => {
    const rows = structuredClone(db.rows);
    const result = await callback((name) => new Query(rows[name], db));
    db.rows = rows;
    return result;
  };
  return db;
}
function body() {
  return { operation: 'create', project_id: PROJECT, specification_id: randomUUID(), revision_id: randomUUID(),
    hashed_user_id: 'a'.repeat(64), hashed_team_id: null, actor_hash: 'a'.repeat(64),
    home_project_hash: PROJECT_HASH, content_hash: 'c'.repeat(64),
    project_surface_catalog_revision_id: 'catalog-1', encrypted_title: 'cipher-title',
    encrypted_summary: 'cipher-summary', encrypted_specification_document: 'cipher-doc',
    key_wrappers: [{ key_type: 'project', hashed_project_id: PROJECT_HASH, encrypted_specification_key: 'wrapped-key' }] };
}
const isError = (code) => (error) => error.code === code;

// contract-test: supporting surface=rest_api assertions=contracts.revision.exact-approval,contracts.revision.optimistic-conflict
test('approve then revise keeps approved content immutable; retries do not add revisions', async () => {
  const db = database(), initial = body();
  await executeSpecification(db, initial);
  await executeSpecification(db, { ...initial, operation: 'approve' });
  const change = { ...initial, operation: 'revise', revision_id: randomUUID(), base_revision_id: initial.revision_id,
    encrypted_specification_document: 'cipher-new', content_hash: 'd'.repeat(64) };
  const saved = await executeSpecification(db, change);
  const retry = await executeSpecification(db, change);
  assert.equal(retry.replayed, true);
  assert.equal(saved.specification.status, 'draft');
  assert.equal(saved.revision.approval_state, 'draft');
  assert.equal(db.rows.user_specification_revisions.length, 2);
  assert.equal(db.rows.user_specification_revisions[0].approval_state, 'approved');
  assert.equal(db.rows.user_specification_revisions[0].encrypted_specification_document, 'cipher-doc');
  assert.ok(db.locks >= 4);
  await assert.rejects(executeSpecification(db, { ...change, revision_id: randomUUID() }), isError('revision_conflict'));
  await assert.rejects(executeSpecification(db, { ...initial, operation: 'approve' }), isError('revision_conflict'));
});

// contract-test: supporting surface=rest_api assertions=contracts.revision.optimistic-conflict,contracts.project.encrypted-embed
test('foreign scope and changed retry payload cannot overwrite saved bytes', async () => {
  const db = database(), initial = body();
  await executeSpecification(db, initial);
  for (const patch of [{ hashed_user_id: 'd'.repeat(64) }, { home_project_hash: 'd'.repeat(64) },
    { hashed_user_id: null, hashed_team_id: 'd'.repeat(64) }]) {
    const scoped = { ...initial, ...patch };
    scoped.key_wrappers = [{ ...initial.key_wrappers[0], hashed_project_id: scoped.home_project_hash }];
    await assert.rejects(executeSpecification(db, scoped), isError(patch.home_project_hash ? 'invalid_project_hash' : 'project_not_found'));
  }
  await assert.rejects(executeSpecification(db, { ...initial, encrypted_specification_document: 'different' }), isError('revision_identity_conflict'));
  assert.equal(db.rows.user_specification_revisions[0].encrypted_specification_document, 'cipher-doc');
});

// contract-test: supporting surface=rest_api assertions=contracts.authoring.shared-direct-and-chat,contracts.project.encrypted-embed
test('failed revision persistence rolls back the new head; Project key scope is required', async () => {
  const db = database(), initial = body();
  db.failInsert = true;
  await assert.rejects(executeSpecification(db, initial), /injected insert failure/);
  assert.equal(db.rows.user_specifications.length, 0);
  assert.equal(db.rows.user_specification_revisions.length, 0);
  db.failInsert = false;
  await assert.rejects(executeSpecification(db, { ...initial, key_wrappers: [] }), isError('invalid_key_wrappers'));
  await assert.rejects(executeSpecification(db, { ...initial, key_wrappers: [{ ...initial.key_wrappers[0], hashed_project_id: 'd'.repeat(64) }] }), isError('invalid_key_wrappers'));
});
