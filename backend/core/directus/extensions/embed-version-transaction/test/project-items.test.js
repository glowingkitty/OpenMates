import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

import { ProtocolError, writeLegacyEmbed } from '../src/operations.js';
import { adoptProjectEmbed, deleteProjectItem, renameProjectItem } from '../src/project-items.js';

const sha = (value) => createHash('sha256').update(value).digest('hex');
const ACTOR = 'a'.repeat(64);
const OTHER = 'b'.repeat(64);
const PROJECT_ID = 'project-1';
const CHAT_ID = 'chat-1';
const EMBED_ID = '0b6f6f0e-8a3b-4c51-9d55-5c1b2d6f7a10';
const ITEM_ID = '11111111-1111-5111-8111-111111111111';
const NEW_ITEM_ID = '33333333-3333-5333-8333-333333333333';

function fakeDatabase(initial) {
  const rows = structuredClone(initial);
  const client = (store) => {
    const knex = (table) => {
      const filters = [];
      let limit = null;
      const matching = () => (store[table] ?? []).filter((row) => filters.every((filter) => filter(row)));
      const query = {
        where(field) {
          for (const [key, expected] of Object.entries(field)) filters.push((row) => row[key] === expected);
          return query;
        },
        whereIn(field, values) { filters.push((row) => values.includes(row[field])); return query; },
        whereNull(field) { filters.push((row) => row[field] == null); return query; },
        forUpdate() { return query; },
        forShare() { return query; },
        limit(value) { limit = value; return query; },
        async first() { return structuredClone(matching()[0]); },
        async insert(value) { (store[table] ??= []).push(structuredClone(value)); return 1; },
        async update(value) { const found = matching(); for (const row of found) Object.assign(row, value); return found.length; },
        async del() { const found = new Set(matching()); store[table] = store[table].filter((row) => !found.has(row)); return found.size; },
        async increment(field, amount) { for (const row of matching()) row[field] = Number(row[field] ?? 0) + amount; return 1; },
        then(resolve, reject) {
          const found = matching();
          return Promise.resolve(structuredClone(limit == null ? found : found.slice(0, limit))).then(resolve, reject);
        },
      };
      return query;
    };
    knex.raw = async () => undefined;
    return knex;
  };
  const database = client(rows);
  database.rows = rows;
  database.transaction = async (callback) => {
    const working = structuredClone(rows);
    const result = await callback(client(working));
    for (const key of Object.keys(working)) rows[key] = working[key];
    return result;
  };
  return database;
}

function seed({ skill = 'code', teamProject = false } = {}) {
  return {
    projects: [{ id: 'project-row', project_id: PROJECT_ID, item_count: 0,
      hashed_user_id: teamProject ? null : ACTOR, hashed_team_id: teamProject ? sha('team-1') : null }],
    project_items: [],
    project_item_operations: [],
    embeds: [{ id: 'embed-row', embed_id: EMBED_ID, hashed_user_id: ACTOR, hashed_chat_id: sha(CHAT_ID),
      hashed_team_id: null, skill_id: skill, encrypted_type: 'cipher-type', encrypted_content: 'cipher-v1',
      version_number: 1, parent_embed_id: null }],
    embed_keys: [{ id: 'chat-wrapper', hashed_embed_id: sha(EMBED_ID), key_type: 'chat', hashed_chat_id: sha(CHAT_ID) }],
    chats: [{ id: CHAT_ID, hashed_user_id: ACTOR, hashed_team_id: null, storage_state: 'hot' }],
    team_memberships: [], teams: [], chat_recovery_account_fences: [], chat_recovery_outputs: [],
    chat_recovery_chat_deletion_fences: [],
  };
}

const adopt = (extra = {}) => ({
  operation_id: 'op-adopt', project_id: PROJECT_ID, chat_id: CHAT_ID, embed_id: EMBED_ID,
  project_item_id: ITEM_ID, kind: 'file', target_id_encrypted: 'cipher-target',
  encrypted_display_name: 'cipher-name', encrypted_metadata: 'cipher-meta',
  project_key_wrapper: 'cipher-project-wrapper', actor_user_hash: ACTOR, ...extra,
});
const rejects = (promise, code) => assert.rejects(promise, (error) => error instanceof ProtocolError && error.code === code);

// contract-test: direct surface=rest_api assertions=projects.files.adopt-embed
test('adopt links the chat embed, keeps the chat wrapper and records a receipt', async () => {
  const database = fakeDatabase(seed());
  const result = await adoptProjectEmbed(database, adopt());
  assert.equal(result.status, 'adopted');
  assert.equal(database.rows.project_items.length, 1);
  assert.equal(database.rows.project_items[0].link_kind, 'file');
  assert.equal(database.rows.project_items[0].target_id_hash, sha(EMBED_ID));
  assert.deepEqual(database.rows.embed_keys.map((key) => key.key_type).sort(), ['chat', 'project']);
  assert.equal(database.rows.projects[0].item_count, 1);
  assert.equal(database.rows.project_item_operations[0].operation_kind, 'adopt');
  const replay = await adoptProjectEmbed(database, adopt());
  assert.equal(replay.idempotent, true);
  assert.equal(database.rows.project_items.length, 1);
  await rejects(adoptProjectEmbed(database, adopt({ encrypted_display_name: 'other' })), 'operation_payload_mismatch');
});

// contract-test: direct surface=rest_api assertions=projects.files.adopt-embed
test('adopt refuses a second link, a path collision and a foreign chat embed', async () => {
  const database = fakeDatabase(seed());
  await adoptProjectEmbed(database, adopt());
  await rejects(adoptProjectEmbed(database, adopt({ operation_id: 'op-2', project_item_id: NEW_ITEM_ID })),
    'embed_already_linked');
  const collision = fakeDatabase(seed());
  collision.rows.project_items.push({ id: 'x', project_item_id: ITEM_ID, target_id_hash: sha('other'), item_type: 'embed' });
  await rejects(adoptProjectEmbed(collision, adopt()), 'path_conflict');
  const foreign = fakeDatabase(seed());
  foreign.rows.projects[0].hashed_user_id = OTHER;
  await rejects(adoptProjectEmbed(foreign, adopt()), 'project_not_found');
  const notOwner = fakeDatabase(seed());
  notOwner.rows.embeds[0].hashed_user_id = OTHER;
  await rejects(adoptProjectEmbed(notOwner, adopt()), 'forbidden');
  await rejects(adoptProjectEmbed(fakeDatabase(seed()), adopt({ embed_id: 'missing' })), 'embed_not_found');
  await rejects(adoptProjectEmbed(fakeDatabase(seed({ skill: 'application' })), adopt()), 'invalid_request');
});

// contract-test: direct surface=rest_api assertions=projects.files.adopt-embed
test('Team adopt requires an active writing membership', async () => {
  const database = fakeDatabase(seed({ teamProject: true }));
  await rejects(adoptProjectEmbed(database, adopt({ team_id: 'team-1' })), 'forbidden');
  database.rows.team_memberships.push({ hashed_team_id: sha('team-1'), hashed_user_id: ACTOR, status: 'active', role: 'member' });
  database.rows.teams.push({ hashed_team_id: sha('team-1'), status: 'active' });
  const result = await adoptProjectEmbed(database, adopt({ team_id: 'team-1' }));
  assert.equal(result.status, 'adopted');
  assert.equal(database.rows.project_items[0].hashed_team_id, sha('team-1'));
  assert.equal(database.rows.project_items[0].hashed_user_id, null);
});

// contract-test: direct surface=rest_api assertions=projects.files.rename-delete
test('rename keeps the embed; delete removes only the link', async () => {
  const database = fakeDatabase(seed());
  await adoptProjectEmbed(database, adopt());
  const renamed = await renameProjectItem(database, {
    operation_id: 'op-rename', project_id: PROJECT_ID, project_item_id: ITEM_ID,
    new_project_item_id: NEW_ITEM_ID, encrypted_display_name: 'n2', encrypted_metadata: 'm2', actor_user_hash: ACTOR,
  });
  assert.equal(renamed.project_item_id, NEW_ITEM_ID);
  assert.equal(database.rows.project_items[0].target_id_hash, sha(EMBED_ID));
  assert.equal(database.rows.embeds.length, 1);
  const removed = await deleteProjectItem(database, {
    operation_id: 'op-delete', project_id: PROJECT_ID, project_item_id: NEW_ITEM_ID, actor_user_hash: ACTOR,
  });
  assert.equal(removed.status, 'deleted');
  assert.equal(database.rows.project_items.length, 0);
  assert.equal(database.rows.embeds.length, 1);
  assert.equal(database.rows.embed_keys.length, 2);
  assert.deepEqual(database.rows.project_item_operations.map((row) => row.operation_kind), ['adopt', 'rename', 'delete']);
});

// contract-test: direct surface=rest_api assertions=projects.files.server-owned-fields
test('linked embeds admit only server-owned refreshes for application and test-result links', async () => {
  const payload = { embed_id: EMBED_ID, hashed_user_id: ACTOR, encrypted_content: 'cipher-v2', version_number: 2 };
  const refresh = { link_kind: 'application', version_number: 2 };
  const app = fakeDatabase(seed({ skill: 'application' }));
  await adoptProjectEmbed(app, adopt({ kind: 'application', project_item_id: NEW_ITEM_ID.replace('-5', '-4') }));
  await rejects(writeLegacyEmbed(app, { embed_id: EMBED_ID, actor_user_hash: ACTOR, payload }), 'project_context_required');
  const stored = await writeLegacyEmbed(app, { embed_id: EMBED_ID, actor_user_hash: ACTOR, payload, server_owned_refresh: refresh });
  assert.equal(stored.status, 'updated');
  assert.equal(app.rows.embeds[0].encrypted_content, 'cipher-v2');
  const file = fakeDatabase(seed());
  await adoptProjectEmbed(file, adopt());
  await rejects(writeLegacyEmbed(file, { embed_id: EMBED_ID, actor_user_hash: ACTOR, payload, server_owned_refresh: refresh }),
    'project_context_required');
  assert.equal(file.rows.embeds[0].encrypted_content, 'cipher-v1');
});
