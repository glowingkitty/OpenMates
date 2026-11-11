/* Contract tests for commitUserEmbedRevision (feature.embed-user-edits). An
 * in-memory transactional table store stands in for knex/PostgreSQL. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

import { ProtocolError } from '../src/operations.js';
import { commitUserEmbedRevision } from '../src/user-revisions.js';

const hash = (value) => createHash('sha256').update(value, 'utf8').digest('hex');
const OWNER = 'a'.repeat(64);
const MEMBER = 'b'.repeat(64);
const STRANGER = 'f'.repeat(64);
const CHAT_ID = 'chat-a';
const TEAM_ID = 'team-a';
const PROJECT_ID = 'project-kitchen-renovation';
const DIAGRAM_ID = '0b6f0f0e-7c1a-4d2b-9a3e-1f2e3d4c5b6a';
const PROJECT_FILE_ID = '11111111-1111-5111-8111-111111111111';
const IMAGE_CHILD_ID = '33333333-3333-5333-8333-333333333333';
const IMAGE_PARENT_ID = '44444444-4444-4444-8444-444444444444';

function fakeDatabase(initial) {
  const rows = structuredClone(initial);
  let tail = Promise.resolve();
  const client = (store) => {
    const knex = (table) => {
      const filters = [];
      const matching = () => (store[table] ?? []).filter((row) => filters.every((filter) => filter(row)));
      const query = {
        where(field, value) {
          if (typeof field === 'object') {
            for (const [key, expected] of Object.entries(field)) filters.push((row) => row[key] === expected);
          } else filters.push((row) => row[field] === value);
          return query;
        },
        whereIn(field, values) { filters.push((row) => values.includes(row[field])); return query; },
        whereNull(field) { filters.push((row) => row[field] == null); return query; },
        forUpdate() { return query; },
        forShare() { return query; },
        async first() { return matching()[0]; },
        async insert(value) { store[table] ??= []; store[table].push(structuredClone(value)); return 1; },
        async update(value) {
          const found = matching();
          for (const row of found) Object.assign(row, structuredClone(value));
          return found.length;
        },
        then(resolve, reject) { return Promise.resolve(structuredClone(matching())).then(resolve, reject); },
      };
      return query;
    };
    knex.raw = async (sql, bindings) => { database.locks.push(bindings[0]); };
    return knex;
  };
  const database = client(rows);
  database.rows = rows;
  database.locks = [];
  database.transaction = async (callback) => {
    const run = tail.then(async () => {
      const working = structuredClone(rows);
      const result = await callback(client(working));
      for (const key of new Set([...Object.keys(rows), ...Object.keys(working)])) rows[key] = working[key] ?? [];
      return result;
    });
    tail = run.catch(() => undefined);
    return run;
  };
  return database;
}

function seed({ team = false, embed = {} } = {}) {
  const teamHash = team ? hash(TEAM_ID) : null;
  return {
    chats: [{ id: CHAT_ID, hashed_user_id: OWNER, hashed_team_id: teamHash, storage_state: 'hot' }],
    embeds: [{
      id: 'embed-row', embed_id: DIAGRAM_ID, hashed_user_id: OWNER, hashed_chat_id: hash(CHAT_ID),
      hashed_team_id: teamHash, app_id: 'diagrams', skill_id: 'html', workspace_origin: 'chat',
      root_embed_id: DIAGRAM_ID, parent_embed_id: null, encryption_mode: 'client',
      encrypted_content: 'cipher-v1', version_number: 1, s3_file_keys: null, ...embed,
    }],
    embed_diffs: [{ id: 'diff-v1', embed_id: embed.embed_id ?? DIAGRAM_ID, hashed_user_id: OWNER,
      version_number: 1, encrypted_snapshot: 'cipher-snapshot-v1', encrypted_patch: null, created_at: 10 }],
    project_items: [], projects: [], teams: team ? [{ hashed_team_id: teamHash, status: 'active' }] : [],
    team_memberships: team ? [{ hashed_team_id: teamHash, hashed_user_id: MEMBER, status: 'active', role: 'member' }] : [],
    embed_user_revision_commits: [], pending_embed_notices: [], image_enhance_jobs: [],
  };
}

function body(overrides = {}) {
  return {
    operation_id: 'user-edit-1', embed_id: DIAGRAM_ID,
    scope: { kind: 'chat', chat_id: CHAT_ID }, action: 'edit',
    expected_revision: 1, expected_content_hash: hash('cipher-v1'),
    head: { encrypted_content: 'cipher-v2', status: 'finished', updated_at: 20 },
    history_rows: [{ version_number: 2, encrypted_snapshot: 'cipher-snapshot-v2', created_at: 20 }],
    actor_user_hash: OWNER, ...overrides,
  };
}

function linkToProject(rows, embedId, { team = false, itemType = 'embed', deletedTargetState = null } = {}) {
  const teamHash = team ? hash(TEAM_ID) : null;
  rows.projects.push({ id: 'project-row', project_id: PROJECT_ID, hashed_user_id: team ? null : OWNER,
    hashed_team_id: teamHash });
  rows.project_items.push({ id: 'item-row', hashed_project_id: hash(PROJECT_ID), hashed_user_id: team ? null : OWNER,
    hashed_team_id: teamHash, item_type: itemType, target_id_hash: hash(embedId),
    deleted_target_state: deletedTargetState });
}

const rejectsWith = (promise, status, code) => assert.rejects(promise,
  (error) => error instanceof ProtocolError && error.status === status && error.code === code);

// contract-test: direct surface=rest_api assertions=embed-user-edits.edit.next-version,embed-user-edits.history.one-per-embed
test('chat owner edit becomes version 2 with a user history row, receipt and pending notice', async () => {
  const db = fakeDatabase(seed());
  const result = await commitUserEmbedRevision(db, body());
  assert.equal(result.status, 'committed');
  assert.equal(result.current_revision, 2);
  assert.equal(result.current_content_hash, hash('cipher-v2'));
  assert.equal(result.pending_notice, true);
  assert.equal(db.rows.embeds[0].encrypted_content, 'cipher-v2');
  assert.equal(db.rows.embeds[0].version_number, 2);
  const v2 = db.rows.embed_diffs.find((row) => row.version_number === 2);
  assert.deepEqual([v2.revision_origin, v2.revision_action, v2.encrypted_patch, v2.has_snapshot], ['user', 'edit', null, true]);
  assert.equal(db.rows.embed_diffs.length, 2);
  assert.equal(db.rows.embed_user_revision_commits.length, 1);
  assert.deepEqual(db.rows.pending_embed_notices.map(({ hashed_chat_id, embed_id, version, action, surface, restored_from }) =>
    ({ hashed_chat_id, embed_id, version, action, surface, restored_from })),
  [{ hashed_chat_id: hash(CHAT_ID), embed_id: DIAGRAM_ID, version: 2, action: 'edit', surface: 'chat', restored_from: null }]);
  await rejectsWith(commitUserEmbedRevision(db, body({ actor_user_hash: STRANGER, operation_id: 'other' })),
    403, 'chat_access_denied');
});

// contract-test: direct surface=rest_api assertions=embed-user-edits.edit.next-version
test('Team owner/admin/member may edit a Team chat embed; viewers and non-members may not', async () => {
  const rows = seed({ team: true });
  const db = fakeDatabase(rows);
  const teamBody = body({ actor_user_hash: MEMBER, scope: { kind: 'chat', chat_id: CHAT_ID, team_id: TEAM_ID } });
  assert.equal((await commitUserEmbedRevision(db, teamBody)).current_revision, 2);
  // The history row stays under the owner hash so the one history is read for everyone.
  assert.equal(db.rows.embed_diffs.find((row) => row.version_number === 2).hashed_user_id, OWNER);
  const viewer = fakeDatabase(seed({ team: true }));
  viewer.rows.team_memberships[0].role = 'viewer';
  await rejectsWith(commitUserEmbedRevision(viewer, teamBody), 403, 'chat_access_denied');
  await rejectsWith(commitUserEmbedRevision(fakeDatabase(seed({ team: true })), body({ actor_user_hash: STRANGER,
    scope: { kind: 'chat', chat_id: CHAT_ID, team_id: TEAM_ID } })), 403, 'chat_access_denied');
  await rejectsWith(commitUserEmbedRevision(fakeDatabase(seed({ team: true })), body()), 403, 'chat_access_denied');
});

// contract-test: direct surface=rest_api assertions=embed-user-edits.event.project-edit-reaches-chat,projects.files.user-edit-direct
test('an adopted Project file is accepted only in Project scope and still notifies its chat', async () => {
  const rows = seed();
  linkToProject(rows, DIAGRAM_ID);
  const db = fakeDatabase(rows);
  await rejectsWith(commitUserEmbedRevision(db, body()), 403, 'project_context_required');
  const result = await commitUserEmbedRevision(db, body({ scope: { kind: 'project', project_id: PROJECT_ID } }));
  assert.equal(result.current_revision, 2);
  assert.equal(result.pending_notice, true);
  assert.equal(db.rows.pending_embed_notices[0].hashed_chat_id, hash(CHAT_ID));
  assert.equal(db.rows.embed_user_revision_commits[0].scope_kind, 'project');
  assert.equal(db.rows.embed_user_revision_commits[0].hashed_scope_id, hash(PROJECT_ID));
  await rejectsWith(commitUserEmbedRevision(db, body({ operation_id: 'other', expected_revision: 2,
    expected_content_hash: hash('cipher-v2'), actor_user_hash: STRANGER,
    history_rows: [{ version_number: 3, encrypted_snapshot: 's3', created_at: 30 }],
    scope: { kind: 'project', project_id: PROJECT_ID } })), 403, 'project_access_denied');
});

// contract-test: direct surface=rest_api assertions=projects.files.user-edit-direct,embed-user-edits.event.project-edit-reaches-chat
test('a Project-only file takes Team writer edits in Project scope and writes no chat notice', async () => {
  const rows = seed({ embed: { embed_id: PROJECT_FILE_ID, app_id: null, skill_id: null, workspace_origin: null,
    root_embed_id: null, hashed_team_id: null } });
  linkToProject(rows, PROJECT_FILE_ID, { team: true });
  rows.teams.push({ hashed_team_id: hash(TEAM_ID), status: 'active' });
  rows.team_memberships.push({ hashed_team_id: hash(TEAM_ID), hashed_user_id: MEMBER, status: 'active', role: 'admin' });
  const db = fakeDatabase(rows);
  const projectBody = body({ embed_id: PROJECT_FILE_ID, actor_user_hash: MEMBER,
    scope: { kind: 'project', project_id: PROJECT_ID, team_id: TEAM_ID } });
  const result = await commitUserEmbedRevision(db, projectBody);
  assert.equal(result.current_revision, 2);
  assert.equal(result.pending_notice, false);
  assert.equal(db.rows.pending_embed_notices.length, 0);
  await rejectsWith(commitUserEmbedRevision(fakeDatabase(rows), { ...projectBody,
    scope: { kind: 'chat', chat_id: CHAT_ID, team_id: TEAM_ID } }), 403, 'chat_access_denied');
});

// contract-test: direct surface=rest_api assertions=projects.files.user-edit-direct
test('only a live embed or upload link makes a Project file; a deleted link neither authorizes nor blocks', async () => {
  const uploaded = seed();
  linkToProject(uploaded, DIAGRAM_ID, { itemType: 'upload' });
  await rejectsWith(commitUserEmbedRevision(fakeDatabase(uploaded), body()), 403, 'project_context_required');
  assert.equal((await commitUserEmbedRevision(fakeDatabase(uploaded),
    body({ scope: { kind: 'project', project_id: PROJECT_ID } }))).current_revision, 2);

  const chatLink = seed();
  linkToProject(chatLink, DIAGRAM_ID, { itemType: 'chat' });
  assert.equal((await commitUserEmbedRevision(fakeDatabase(chatLink), body())).current_revision, 2);

  const removed = seed();
  linkToProject(removed, DIAGRAM_ID, { deletedTargetState: 'deleted' });
  await rejectsWith(commitUserEmbedRevision(fakeDatabase(removed),
    body({ scope: { kind: 'project', project_id: PROJECT_ID } })), 403, 'project_item_access_denied');
  const db = fakeDatabase(removed);
  assert.equal((await commitUserEmbedRevision(db, body())).current_revision, 2);
  assert.equal(db.rows.embed_user_revision_commits[0].scope_kind, 'chat');
});

function imageSeed() {
  const rows = seed({ embed: { embed_id: IMAGE_CHILD_ID, app_id: 'images', skill_id: 'generated_image',
    parent_embed_id: IMAGE_PARENT_ID, root_embed_id: IMAGE_PARENT_ID, workspace_origin: null, version_number: 2,
    s3_file_keys: JSON.stringify([{ bucket: 'chatfiles', key: 'u/v1.webp' }, { bucket: 'chatfiles', key: 'u/v2.webp' }]) } });
  rows.embed_diffs = [1, 2].map((version) => ({ id: `img-${version}`, embed_id: IMAGE_CHILD_ID, hashed_user_id: OWNER,
    version_number: version, encrypted_snapshot: `img-snapshot-v${version}`, encrypted_patch: null, created_at: version }));
  return rows;
}
const imageBody = (overrides = {}) => body({ embed_id: IMAGE_CHILD_ID, operation_id: 'restore-1', action: 'restore',
  restored_from: 1, expected_revision: 2, files: { head_file_keys: [{ bucket: 'chatfiles', key: 'u/v1.webp' }] },
  history_rows: [{ version_number: 3, encrypted_snapshot: 'img-snapshot-v3', created_at: 30 }], ...overrides });

// contract-test: direct surface=rest_api assertions=embed-user-edits.restore.creates-version
test('a generated image child (UUIDv5) restores version 1 as version 3 and keeps its parent and files', async () => {
  const db = fakeDatabase(imageSeed());
  const result = await commitUserEmbedRevision(db, imageBody());
  assert.equal(result.current_revision, 3);
  assert.deepEqual(result.image, { head_file_keys: [{ bucket: 'chatfiles', key: 'u/v1.webp' }], owner_is_actor: true });
  const head = db.rows.embeds[0];
  assert.deepEqual([head.parent_embed_id, head.root_embed_id, head.hashed_chat_id],
    [IMAGE_PARENT_ID, IMAGE_PARENT_ID, hash(CHAT_ID)]);
  assert.equal(JSON.parse(head.s3_file_keys).length, 2);
  assert.equal(db.rows.embed_diffs.length, 3);
  assert.equal(db.rows.embed_diffs[2].revision_action, 'restore');
  assert.equal(db.rows.embed_user_revision_commits[0].restored_from, 1);
  const notice = db.rows.pending_embed_notices[0];
  assert.deepEqual([notice.action, notice.surface, notice.restored_from], ['restore', 'chat', 1]);
  assert.equal(Object.values(notice).some((value) => typeof value === 'string' && value.includes('img-snapshot')), false);
  // Any other UUIDv5 id stays reserved for Project files in chat scope.
  const other = fakeDatabase(imageSeed());
  other.rows.embeds[0].parent_embed_id = null;
  await rejectsWith(commitUserEmbedRevision(other, imageBody()), 403, 'project_context_required');
});

// contract-test: direct surface=rest_api assertions=embed-user-edits.files.client-made-version
test('file keys outside the embed and client-made upload sources are refused', async () => {
  const db = fakeDatabase(imageSeed());
  await rejectsWith(commitUserEmbedRevision(db, imageBody({
    files: { head_file_keys: [{ bucket: 'chatfiles', key: 'someone-else/file.webp' }] } })), 403, 'foreign_file_key');
  await rejectsWith(commitUserEmbedRevision(db, imageBody({ action: 'crop', restored_from: undefined,
    files: { new_files: [{ kind: 'upload', upload_id: 'up-1' }] } })), 400, 'unsupported_file_source');
  await rejectsWith(commitUserEmbedRevision(fakeDatabase(seed()), body({
    files: { head_file_keys: [{ bucket: 'chatfiles', key: 'x' }] } })), 400, 'invalid_file_source');
  assert.equal(db.rows.embeds[0].version_number, 2);
  assert.equal(db.rows.embed_user_revision_commits.length, 0);
});

// contract-test: direct surface=rest_api assertions=embed-user-edits.files.client-made-version,embed-user-edits.edit.next-version
test('an Enhance result is committed only from a ready job of this user, embed and version', async () => {
  const rows = imageSeed();
  rows.image_enhance_jobs = [{ operation_id: 'enhance-1', embed_id: IMAGE_CHILD_ID, hashed_user_id: OWNER,
    state: 'ready', target_version: 3, version: 4, expires_at: Math.floor(Date.now() / 1000) + 3600,
    scope_kind: 'chat', scope_id_hash: hash(CHAT_ID),
    result_file_keys: [{ bucket: 'chatfiles', key: 'u/v3-2k.webp' }] }];
  const enhance = imageBody({ operation_id: 'commit-enhance-1', action: 'enhance', restored_from: undefined,
    files: { new_files: [{ kind: 'enhance', operation_id: 'enhance-1' }] } });
  delete enhance.restored_from;
  const stranger = fakeDatabase(rows);
  stranger.rows.image_enhance_jobs[0].hashed_user_id = STRANGER;
  await rejectsWith(commitUserEmbedRevision(stranger, enhance), 403, 'enhance_result_not_found');
  const wrongVersion = fakeDatabase(rows);
  wrongVersion.rows.image_enhance_jobs[0].target_version = 4;
  await rejectsWith(commitUserEmbedRevision(wrongVersion, enhance), 409, 'enhance_version_mismatch');
  const expired = fakeDatabase(rows);
  expired.rows.image_enhance_jobs[0].expires_at = Math.floor(Date.now() / 1000) - 1;
  await rejectsWith(commitUserEmbedRevision(expired, enhance), 409, 'enhance_result_expired');
  for (const [field, value] of [['scope_kind', 'project'], ['scope_id_hash', hash('chat-b')]]) {
    const otherScope = fakeDatabase(rows);
    otherScope.rows.image_enhance_jobs[0][field] = value;
    await rejectsWith(commitUserEmbedRevision(otherScope, enhance), 409, 'enhance_scope_mismatch');
    assert.equal(otherScope.rows.image_enhance_jobs[0].state, 'ready');
  }
  const db = fakeDatabase(rows);
  const result = await commitUserEmbedRevision(db, enhance);
  assert.equal(result.current_revision, 3);
  assert.deepEqual([db.rows.image_enhance_jobs[0].state, db.rows.image_enhance_jobs[0].version], ['committed', 5]);
  assert.deepEqual(JSON.parse(db.rows.embeds[0].s3_file_keys).map((ref) => ref.key),
    ['u/v1.webp', 'u/v2.webp', 'u/v3-2k.webp']);
  await rejectsWith(commitUserEmbedRevision(db, { ...enhance, operation_id: 'commit-enhance-2', expected_revision: 3,
    expected_content_hash: hash('cipher-v2'),
    history_rows: [{ version_number: 4, encrypted_snapshot: 's4', created_at: 40 }] }), 409, 'enhance_result_not_ready');
});

// contract-test: direct surface=rest_api assertions=embed-user-edits.edit.next-version
test('types outside the allowlist are refused', async () => {
  const db = fakeDatabase(seed({ embed: { app_id: 'code', skill_id: 'code' } }));
  await rejectsWith(commitUserEmbedRevision(db, body()), 403, 'embed_type_not_editable');
  await rejectsWith(commitUserEmbedRevision(fakeDatabase(seed({ embed: { encryption_mode: 'vault' } })), body()),
    403, 'embed_access_denied');
});

// contract-test: direct surface=rest_api assertions=embed-user-edits.edit.next-version
test('a stale version or head hash is a conflict that writes nothing', async () => {
  for (const stale of [{ expected_content_hash: hash('older-cipher') }, { expected_revision: 2,
    history_rows: [{ version_number: 3, encrypted_snapshot: 's3', created_at: 30 }] }]) {
    const db = fakeDatabase(seed());
    const result = await commitUserEmbedRevision(db, body(stale));
    assert.deepEqual([result.status, result.current_revision, result.current_content_hash],
      ['conflict', 1, hash('cipher-v1')]);
    assert.equal(db.rows.embeds[0].encrypted_content, 'cipher-v1');
    assert.equal(db.rows.embed_diffs.length, 1);
    assert.equal(db.rows.embed_user_revision_commits.length + db.rows.pending_embed_notices.length, 0);
  }
});

// contract-test: direct surface=rest_api assertions=embed-user-edits.edit.next-version,embed-user-edits.history.one-per-embed
test('a missing base version needs its snapshot in the same commit', async () => {
  const rows = seed();
  rows.embed_diffs = [];
  await rejectsWith(commitUserEmbedRevision(fakeDatabase(rows), body()), 409, 'base_snapshot_required');
  const db = fakeDatabase(rows);
  await commitUserEmbedRevision(db, body({ history_rows: [
    { version_number: 1, encrypted_snapshot: 'base-v1', created_at: 10 },
    { version_number: 2, encrypted_snapshot: 'cipher-snapshot-v2', created_at: 20 },
  ] }));
  assert.deepEqual(db.rows.embed_diffs.map((row) => [row.version_number, row.revision_origin]), [[1, null], [2, 'user']]);
});

// contract-test: direct surface=rest_api assertions=embed-user-edits.edit.next-version
test('a replay by operation_id returns the first result; a changed payload is refused', async () => {
  const db = fakeDatabase(seed());
  const first = await commitUserEmbedRevision(db, body());
  const replay = await commitUserEmbedRevision(db, body());
  assert.equal(first.idempotent, false);
  assert.deepEqual({ ...replay, idempotent: false }, first);
  assert.equal(db.rows.embed_diffs.length, 2);
  assert.equal(db.rows.pending_embed_notices.length, 1);
  await rejectsWith(commitUserEmbedRevision(db, body({ head: { ...body().head, encrypted_content: 'changed' } })),
    409, 'operation_payload_mismatch');
});

// contract-test: direct surface=rest_api assertions=embed-user-edits.event.project-edit-reaches-chat
test('a pending notice is written only when the embed has a chat', async () => {
  const rows = seed({ embed: { hashed_chat_id: null } });
  linkToProject(rows, DIAGRAM_ID);
  const db = fakeDatabase(rows);
  const result = await commitUserEmbedRevision(db, body({ scope: { kind: 'project', project_id: PROJECT_ID } }));
  assert.equal(result.pending_notice, false);
  assert.equal(db.rows.pending_embed_notices.length, 0);
});

// contract-test: direct surface=rest_api assertions=embed-user-edits.edit.next-version
test('malformed requests are refused before any read', async () => {
  const db = fakeDatabase(seed());
  for (const [changed, code] of [
    [{ action: 'paint' }, 'invalid_action'],
    [{ scope: { kind: 'chat', chat_id: CHAT_ID, project_id: PROJECT_ID } }, 'invalid_scope'],
    [{ history_rows: [{ version_number: 2, encrypted_patch: 'p', created_at: 1 }] }, 'invalid_request'],
    [{ head: { encrypted_content: 'x', status: 'processing', updated_at: 1 } }, 'invalid_status'],
    [{ action: 'restore' }, 'invalid_restored_from'],
    [{ action: 'enhance' }, 'file_source_required'],
  ]) await rejectsWith(commitUserEmbedRevision(db, body(changed)), 400, code);
  assert.equal(db.locks.length, 0);
});
