import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

import { isAuthorized } from '../src/index.js';
import { activateEmbedArchiveReader, commitEmbedRevision, finalizeEmbedArchiveCopy,
  prepareEmbedArchiveCopy, retireEmbedArchiveCopy, pruneEmbedArchivePayload,
  publishEmbedSnapshot, writeLegacyEmbed, ProtocolError, testing } from '../src/operations.js';

const ACTOR = 'a'.repeat(64);
const PROJECT_ID = 'project-1';
const PROJECT_HASH = createHash('sha256').update(PROJECT_ID).digest('hex');
const EMBED_ID = '11111111-1111-5111-8111-111111111111';
const PROJECT_ITEM_ID = '22222222-2222-5222-8222-222222222222';

function fakeDatabase(initial) {
  const rows = structuredClone(initial);
  let tail = Promise.resolve();

  const client = (store) => {
    const knex = (table) => {
      const filters = [];
      let countRequested = false;
      let limitRequested = null;
      const matching = () => (store[table] ?? []).filter((row) => filters.every((filter) => filter(row)));
      const query = {
        where(field, operator, value) {
          if (typeof field === 'object') {
            for (const [key, expected] of Object.entries(field)) {
              filters.push((row) => row[key] === expected);
            }
          } else if (operator === '<=') {
            filters.push((row) => row[field] <= value);
          } else {
            filters.push((row) => row[field] === operator);
          }
          return query;
        },
        whereIn(field, values) {
          filters.push((row) => values.includes(row[field]));
          return query;
        },
        whereRaw(sql, bindings) {
          if (table === 'chats' && sql.includes("encode(digest(id::text")) {
            filters.push((row) => createHash('sha256').update(row.id).digest('hex') === bindings[0]);
          } else throw new Error(`Unexpected raw filter: ${sql}`);
          return query;
        },
        forUpdate() { return query; },
        forShare() { return query; },
        limit(value) { limitRequested = value; return query; },
        count() { countRequested = true; return query; },
        async first() {
          if (countRequested) return { count: matching().length };
          return matching()[0];
        },
        async insert(value) {
          store[table] ??= [];
          store[table].push(structuredClone(value));
          return 1;
        },
        async update(value) {
          const found = matching();
          for (const row of found) Object.assign(row, structuredClone(value));
          return found.length;
        },
        async increment(field, amount) {
          const found = matching();
          for (const row of found) row[field] = Number(row[field] ?? 0) + amount;
          return found.length;
        },
        then(resolve, reject) {
          const matches = matching();
          return Promise.resolve(structuredClone(limitRequested == null
            ? matches : matches.slice(0, limitRequested))).then(resolve, reject);
        },
      };
      return query;
    };
    knex.raw = async (sql) => String(sql).includes('AS pending')
      ? { rows: [{ pending: database.pendingRecovery ?? false }] } : undefined;
    return knex;
  };

  const database = client(rows);
  database.rows = rows;
  database.pendingRecovery = false;
  database.transaction = async (callback) => {
    const transaction = tail.then(async () => {
      const working = structuredClone(rows);
      const result = await callback(client(working));
      for (const key of new Set([...Object.keys(rows), ...Object.keys(working)])) {
        rows[key] = working[key] ?? [];
      }
      return result;
    });
    tail = transaction.catch(() => undefined);
    return transaction;
  };
  return database;
}

function existingSeed() {
  return {
    projects: [{
      id: 'project-row', project_id: PROJECT_ID, hashed_user_id: ACTOR,
      hashed_team_id: null, item_count: 1,
    }],
    project_items: [{
      id: 'item-row', project_item_id: PROJECT_ITEM_ID, hashed_project_id: PROJECT_HASH,
      hashed_user_id: ACTOR, hashed_team_id: null, item_type: 'embed',
      target_id_hash: createHash('sha256').update(EMBED_ID).digest('hex'),
    }],
    embeds: [{
      id: 'embed-row', embed_id: EMBED_ID, hashed_user_id: ACTOR,
      hashed_chat_id: createHash('sha256').update('chat-a').digest('hex'),
      encrypted_content: 'cipher-head-v1', version_number: 1,
    }],
    chats: [{ id: 'chat-a', storage_state: 'hot' }],
    embed_diffs: [{
      id: 'history-v1', embed_id: EMBED_ID, hashed_user_id: ACTOR,
      version_number: 1, encrypted_snapshot: 'cipher-snapshot-v1',
      encrypted_patch: null, created_at: 10,
    }],
    embed_version_commits: [], embed_keys: [], team_memberships: [], teams: [],
    embed_version_archive_rollout: [{
      id: 'agentic-storage-v2', read_enabled: false, pruning_enabled: false,
      initial_cohort: true, compatibility_verified: false,
      reader_receipt: null, validation_receipt: null, failure_code: null,
    }],
  };
}

function updateBody(overrides = {}) {
  return {
    operation_id: 'operation-1', embed_id: EMBED_ID, project_id: PROJECT_ID,
    chat_id: 'chat-a', proposal_digest: 'b'.repeat(64), expected_revision: 1,
    head: { encrypted_content: 'cipher-head-v2', encrypted_diff: 'cipher-head-diff-v2', updated_at: 20 },
    history_rows: [{
      version_number: 2, encrypted_snapshot: null,
      encrypted_patch: 'cipher-patch-v2', created_at: 20,
    }],
    actor_user_hash: ACTOR,
    ...overrides,
  };
}

function createBody(overrides = {}) {
  return {
    operation_id: 'create-1', embed_id: EMBED_ID, project_id: PROJECT_ID,
    chat_id: 'chat-a', proposal_digest: 'c'.repeat(64), expected_revision: 0,
    head: { encrypted_content: 'cipher-head-v1', updated_at: 10 },
    history_rows: [{
      version_number: 1, encrypted_snapshot: 'cipher-snapshot-v1',
      encrypted_patch: null, created_at: 10,
    }],
    create: {
      project_item_id: PROJECT_ITEM_ID,
      encrypted_type: 'cipher-type',
      target_id_encrypted: 'cipher-target-id',
      encrypted_display_name: 'cipher-display-name',
      encrypted_metadata: 'cipher-private-path-metadata',
      key_wrappers: [
        { key_type: 'project', encrypted_embed_key: 'project-wrapped-key', created_at: 10 },
        { key_type: 'chat', encrypted_embed_key: 'chat-wrapped-key', created_at: 10 },
      ],
    },
    actor_user_hash: ACTOR,
    ...overrides,
  };
}

// contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit
test('internal endpoint authentication fails closed', () => {
  assert.equal(isAuthorized({}, ''), false);
  assert.equal(isAuthorized({ 'x-internal-service-token': 'wrong' }, 'expected'), false);
  assert.equal(isAuthorized({ 'x-internal-service-token': 'expected' }, 'expected'), true);
});

// contract-test: direct surface=rest_api assertions=projects.files.concurrent-chat-safety
test('legacy embed write checks current Project link inside the serialized write transaction', async () => {
  const seed = existingSeed();
  const legacyId = 'legacy-embed-1';
  seed.embeds.push({
    id: 'legacy-row', embed_id: legacyId, hashed_user_id: ACTOR,
    encrypted_content: 'original', version_number: 1,
  });
  const database = fakeDatabase(seed);
  const body = {
    embed_id: legacyId, actor_user_hash: ACTOR,
    payload: { embed_id: legacyId, hashed_user_id: ACTOR, encrypted_content: 'legacy-update' },
  };
  const first = await writeLegacyEmbed(database, body);
  assert.equal(first.status, 'updated');
  assert.equal(database.rows.embeds[1].encrypted_content, 'legacy-update');

  database.rows.project_items.push({
    id: 'new-link', item_type: 'embed', target_id_hash: createHash('sha256').update(legacyId).digest('hex'),
  });
  await assert.rejects(writeLegacyEmbed(database, {
    ...body, payload: { ...body.payload, encrypted_content: 'stale-write' },
  }), (error) => error instanceof ProtocolError && error.code === 'project_context_required');
  assert.equal(database.rows.embeds[1].encrypted_content, 'legacy-update');
});

function registeredChildFixture({ team = false } = {}) {
  const seed = existingSeed();
  const childId = '33333333-3333-5333-8333-333333333333';
  const parentId = 'parent-embed';
  const chatId = 'registered-chat';
  const messageId = 'registered-message';
  const teamHash = team ? 'c'.repeat(64) : null;
  const producerId = '44444444-4444-4444-8444-444444444444';
  seed.project_items = [];
  seed.chats.push({ id: chatId, hashed_user_id: ACTOR,
    hashed_team_id: teamHash, storage_state: 'hot' });
  seed.chat_recovery_output_producers = [{
    id: producerId, hashed_user_id: ACTOR, hashed_team_id: teamHash,
    primary_embed_id: parentId, primary_message_id: messageId,
    target_chat_id: chatId, root_chat_id: chatId, state: 'PENDING', invalidated_at: null,
  }];
  seed.chat_recovery_output_producer_children = [{
    producer_intent_id: producerId, ordinal: 1, subject_id: childId,
    output_kind: 'embed', output_version: 1,
  }];
  seed.chat_recovery_outputs = [{
    id: 'recovery-child-output',
    subject_id: childId, hashed_user_id: ACTOR, output_kind: 'embed', output_version: 1,
    producer_intent_id: producerId, producer_ordinal: 1,
    target_chat_id: chatId, root_chat_id: chatId, state: 'PENDING', deleted_at: null,
  }];
  if (team) {
    seed.team_memberships.push({ hashed_team_id: teamHash, hashed_user_id: ACTOR,
      status: 'active', role: 'member' });
    seed.teams.push({ hashed_team_id: teamHash, status: 'active' });
  }
  const body = { embed_id: childId, actor_user_hash: ACTOR, payload: {
    embed_id: childId, hashed_user_id: ACTOR,
    hashed_chat_id: createHash('sha256').update(chatId).digest('hex'),
    hashed_message_id: createHash('sha256').update(messageId).digest('hex'),
    hashed_team_id: teamHash, parent_embed_id: parentId,
    app_id: 'web', skill_id: 'search', root_embed_id: parentId,
    encrypted_content: 'cipher-child', version_number: 1,
  } };
  return { seed, body, childId };
}

// contract-test: direct surface=rest_api assertions=storage.background.complete-sealed-recovery,projects.files.concurrent-chat-safety
test('legacy transaction admits only durable registered AI child heads in the UUIDv5 namespace', async () => {
  const { seed, body, childId } = registeredChildFixture();
  const database = fakeDatabase(seed);
  assert.equal((await writeLegacyEmbed(database, body)).status, 'created');
  assert.equal(database.rows.embeds.at(-1).embed_id, childId);
  assert.equal((await writeLegacyEmbed(database, { ...body,
    payload: { ...body.payload, encrypted_content: 'cipher-updated' },
  })).status, 'updated');
  assert.equal(database.rows.embeds.at(-1).encrypted_content, 'cipher-updated');

  const ordinary = registeredChildFixture();
  ordinary.seed.chat_recovery_outputs = [];
  await assert.rejects(writeLegacyEmbed(fakeDatabase(ordinary.seed), ordinary.body),
    (error) => error instanceof ProtocolError && error.code === 'project_context_required');
  for (const mutation of [
    (fixture) => { fixture.body.payload.parent_embed_id = 'forged-parent';
      fixture.body.payload.root_embed_id = 'forged-parent'; },
    (fixture) => { fixture.body.payload.hashed_chat_id = 'b'.repeat(64); },
    (fixture) => { fixture.body.actor_user_hash = 'b'.repeat(64); fixture.body.payload.hashed_user_id = 'b'.repeat(64); },
    (fixture) => { fixture.seed.chat_recovery_outputs[0].deleted_at = 1; },
    (fixture) => { fixture.seed.chat_recovery_output_producer_children = []; },
    (fixture) => { fixture.seed.project_items.push({ item_type: 'embed',
      target_id_hash: createHash('sha256').update(childId).digest('hex') }); },
  ]) {
    const fixture = registeredChildFixture();
    mutation(fixture);
    await assert.rejects(writeLegacyEmbed(fakeDatabase(fixture.seed), fixture.body),
      (error) => error instanceof ProtocolError && error.code === 'project_context_required');
  }
});

// contract-test: direct surface=rest_api assertions=teams.chat.encrypted-until-invoked,projects.files.concurrent-chat-safety
test('registered child write rechecks current Team access and chat scope', async () => {
  const { seed, body } = registeredChildFixture({ team: true });
  const database = fakeDatabase(seed);
  assert.equal((await writeLegacyEmbed(database, body)).status, 'created');
  database.rows.team_memberships[0].status = 'inactive';
  await assert.rejects(writeLegacyEmbed(database, body),
    (error) => error instanceof ProtocolError && error.code === 'project_context_required');
  database.rows.team_memberships[0].status = 'active';
  database.rows.chats.at(-1).hashed_team_id = 'd'.repeat(64);
  await assert.rejects(writeLegacyEmbed(database, body),
    (error) => error instanceof ProtocolError && error.code === 'project_context_required');
});

// contract-test: direct surface=rest_api assertions=storage.background.complete-sealed-recovery,teams.chat.encrypted-until-invoked
test('registered Team child without CLI catalog fields receives verified chat Team scope', async () => {
  const { seed, body } = registeredChildFixture({ team: true });
  delete body.payload.app_id;
  delete body.payload.skill_id;
  delete body.payload.root_embed_id;
  delete body.payload.hashed_team_id;
  const database = fakeDatabase(seed);
  assert.equal((await writeLegacyEmbed(database, body)).status, 'created');
  assert.equal(database.rows.embeds.at(-1).hashed_team_id, 'c'.repeat(64));
  assert.equal((await writeLegacyEmbed(database, { ...body,
    payload: { ...body.payload, encrypted_content: 'cipher-cli-replay' },
  })).status, 'updated');
  assert.equal(database.rows.embeds.at(-1).encrypted_content, 'cipher-cli-replay');
});

// contract-test: direct surface=rest_api assertions=storage.background.complete-sealed-recovery,teams.chat.encrypted-until-invoked
test('registered child write rejects changed root scope and account deletion fence', async () => {
  const { seed, body } = registeredChildFixture({ team: true });
  const rootId = 'registered-root';
  seed.chats.push({ id: rootId, hashed_user_id: ACTOR,
    hashed_team_id: 'c'.repeat(64), storage_state: 'hot' });
  seed.chat_recovery_output_producers[0].root_chat_id = rootId;
  seed.chat_recovery_outputs[0].root_chat_id = rootId;
  const database = fakeDatabase(seed);
  assert.equal((await writeLegacyEmbed(database, body)).status, 'created');
  database.rows.chats.at(-1).hashed_team_id = 'd'.repeat(64);
  await assert.rejects(writeLegacyEmbed(database, body),
    (error) => error instanceof ProtocolError && error.code === 'project_context_required');
  database.rows.chats.at(-1).hashed_team_id = 'c'.repeat(64);
  database.rows.chat_recovery_account_fences = [{ id: ACTOR }];
  await assert.rejects(writeLegacyEmbed(database, body),
    (error) => error instanceof ProtocolError && error.code === 'project_context_required');
});

// contract-test: direct surface=rest_api assertions=projects.files.concurrent-chat-safety
test('legacy write cannot overwrite a committed Project revision head', async () => {
  const database = fakeDatabase(existingSeed());
  await commitEmbedRevision(database, updateBody());
  await assert.rejects(writeLegacyEmbed(database, {
    embed_id: EMBED_ID, actor_user_hash: ACTOR,
    payload: { embed_id: EMBED_ID, hashed_user_id: ACTOR, encrypted_content: 'stale-head' },
  }), (error) => error instanceof ProtocolError && error.code === 'project_context_required');
  assert.equal(database.rows.embeds[0].encrypted_content, 'cipher-head-v2');
  assert.equal(database.rows.embeds[0].version_number, 2);
});

// contract-test: direct surface=rest_api assertions=projects.files.concurrent-chat-safety
test('legacy composite embed JSON values are bound as JSON on create and update', async () => {
  const database = fakeDatabase(existingSeed());
  const embedId = 'legacy-composite-1';
  const body = {
    embed_id: embedId, actor_user_hash: ACTOR,
    payload: {
      embed_id: embedId, hashed_user_id: ACTOR, encrypted_content: 'cipher-composite',
      embed_ids: ['child-1', 'child-2'], shared_with_users: [ACTOR],
      s3_file_keys: [{ bucket: 'chatfiles', key: 'encrypted-object' }],
    },
  };
  assert.equal((await writeLegacyEmbed(database, body)).status, 'created');
  const row = database.rows.embeds.at(-1);
  assert.equal(row.embed_ids, '["child-1","child-2"]');
  assert.equal(row.shared_with_users, JSON.stringify([ACTOR]));
  assert.equal(row.s3_file_keys, '[{"bucket":"chatfiles","key":"encrypted-object"}]');

  assert.equal((await writeLegacyEmbed(database, {
    ...body, payload: { ...body.payload, embed_ids: ['child-3'], s3_file_keys: null },
  })).status, 'updated');
  assert.equal(database.rows.embeds.at(-1).embed_ids, '["child-3"]');
  assert.equal(database.rows.embeds.at(-1).s3_file_keys, null);
});

// contract-test: direct surface=rest_api assertions=projects.files.concurrent-chat-safety
test('legacy chat catalog projection survives atomic create and same-scope update', async () => {
  const database = fakeDatabase(existingSeed());
  const embedId = 'legacy-catalog-1';
  const payload = {
    embed_id: embedId, hashed_user_id: ACTOR, encrypted_content: 'cipher-first',
    app_id: 'web', skill_id: 'search', root_embed_id: embedId,
    workspace_origin: 'chat', hashed_team_id: 'c'.repeat(64),
  };
  const body = { embed_id: embedId, actor_user_hash: ACTOR, payload };
  assert.equal((await writeLegacyEmbed(database, body)).status, 'created');
  assert.equal(database.rows.embeds.at(-1).app_id, 'web');
  assert.equal(database.rows.embeds.at(-1).workspace_origin, 'chat');
  assert.equal((await writeLegacyEmbed(database, {
    ...body, payload: { ...payload, encrypted_content: 'cipher-second' },
  })).status, 'updated');
  assert.equal(database.rows.embeds.at(-1).encrypted_content, 'cipher-second');
});

// contract-test: direct surface=rest_api assertions=projects.files.concurrent-chat-safety
test('legacy atomic update rejects catalog, Team, and root scope rewrites', async () => {
  const seed = existingSeed();
  const embedId = 'legacy-catalog-2';
  seed.embeds.push({
    id: 'catalog-row', embed_id: embedId, hashed_user_id: ACTOR,
    encrypted_content: 'unchanged', app_id: 'web', skill_id: 'search',
    hashed_team_id: 'c'.repeat(64), workspace_origin: 'chat',
    root_embed_id: embedId,
  });
  const database = fakeDatabase(seed);
  const base = {
    embed_id: embedId, hashed_user_id: ACTOR, encrypted_content: 'stale-update',
    app_id: 'web', skill_id: 'search', hashed_team_id: 'c'.repeat(64),
    workspace_origin: 'chat', root_embed_id: embedId,
  };
  for (const change of [
    { app_id: 'mail' }, { skill_id: 'write' }, { hashed_team_id: 'd'.repeat(64) },
    { root_embed_id: 'different-root' }, { app_id: undefined, skill_id: undefined,
      hashed_team_id: undefined, root_embed_id: undefined, workspace_origin: undefined },
  ]) {
    await assert.rejects(writeLegacyEmbed(database, {
      embed_id: embedId, actor_user_hash: ACTOR, payload: { ...base, ...change },
    }), (error) => error instanceof ProtocolError
      && ['embed_catalog_context_mismatch', 'invalid_catalog_context'].includes(error.code));
  }
  assert.equal(database.rows.embeds.at(-1).encrypted_content, 'unchanged');
  database.rows.embeds.at(-1).workspace_origin = 'web_apps';
  await assert.rejects(writeLegacyEmbed(database, {
    embed_id: embedId, actor_user_hash: ACTOR, payload: base,
  }), (error) => error instanceof ProtocolError && error.code === 'embed_catalog_context_mismatch');
});

const bundleHash = (value) => createHash('sha256').update(value).digest('hex');
function bundleWrite({ chatId = 'new-personal-chat', messageId = 'message-1',
  teamHash = null, preflightId = null, allowNew = true } = {}) {
  const embedId = 'bundle-embed-1';
  return {
    embed_id: embedId, actor_user_hash: ACTOR,
    payload: {
      embed_id: embedId, hashed_user_id: ACTOR,
      hashed_chat_id: bundleHash(chatId), hashed_message_id: bundleHash(messageId),
      encrypted_type: 'cipher-type', encrypted_content: 'cipher-content',
      status: 'finished', created_at: 10, updated_at: 10,
    },
    bundle_context: {
      chat_id: chatId, message_id: messageId, hashed_team_id: teamHash,
      allow_new_personal_chat: allowNew, preflight_id: preflightId,
      key_wrappers: [
        { hashed_embed_id: bundleHash(embedId), hashed_user_id: ACTOR,
          hashed_chat_id: null, key_type: 'master',
          encrypted_embed_key: 'master-cipher', created_at: 10 },
        { hashed_embed_id: bundleHash(embedId), hashed_user_id: ACTOR,
          hashed_chat_id: bundleHash(chatId), key_type: 'chat',
          encrypted_embed_key: 'chat-cipher', created_at: 10 },
      ],
    },
  };
}

// contract-test: direct surface=rest_api assertions=projects.files.concurrent-chat-safety
test('bundle write permits scoped personal create and exact retry but rejects changed head', async () => {
  const database = fakeDatabase(existingSeed());
  const body = bundleWrite();
  assert.equal((await writeLegacyEmbed(database, body)).status, 'created');
  assert.equal(database.rows.embed_keys.length, 2);
  assert.equal((await writeLegacyEmbed(database, body)).status, 'idempotent');
  assert.equal(database.rows.embed_keys.length, 2);
  assert.equal(database.rows.embeds.at(-1).encrypted_content, 'cipher-content');
  await assert.rejects(writeLegacyEmbed(database, {
    ...body, bundle_context: { ...body.bundle_context, key_wrappers: [
      { ...body.bundle_context.key_wrappers[0], encrypted_embed_key: 'wrong-key' },
      body.bundle_context.key_wrappers[1],
    ] },
  }), (error) => error instanceof ProtocolError && error.code === 'bundle_wrapper_mismatch');
  assert.equal(database.rows.embed_keys[0].encrypted_embed_key, 'master-cipher');
  await assert.rejects(writeLegacyEmbed(database, {
    ...body, payload: { ...body.payload, encrypted_content: 'fresh-nonce' },
  }), (error) => error instanceof ProtocolError && error.code === 'bundle_head_mismatch');
  database.rows.embeds.at(-1).version_number = 2;
  await assert.rejects(writeLegacyEmbed(database, body),
    (error) => error instanceof ProtocolError && error.code === 'bundle_head_advanced');
  assert.equal(database.rows.embeds.at(-1).encrypted_content, 'cipher-content');
});

// contract-test: direct surface=rest_api assertions=projects.files.concurrent-chat-safety
test('bundle exact retry accepts parsed JSON projection and rejects changed child IDs', async () => {
  const database = fakeDatabase(existingSeed());
  const body = bundleWrite();
  body.payload.embed_ids = ['child-1', 'child-2'];
  assert.equal((await writeLegacyEmbed(database, body)).status, 'created');
  database.rows.embeds.at(-1).embed_ids = ['child-1', 'child-2'];
  assert.equal((await writeLegacyEmbed(database, body)).status, 'idempotent');
  await assert.rejects(writeLegacyEmbed(database, {
    ...body, payload: { ...body.payload, embed_ids: ['child-3'] },
  }), (error) => error instanceof ProtocolError && error.code === 'bundle_head_mismatch');
});

// contract-test: direct surface=rest_api assertions=projects.files.concurrent-chat-safety
test('bundle transaction rolls back head and first wrapper when second wrapper conflicts', async () => {
  const seed = existingSeed();
  const body = bundleWrite();
  seed.embed_keys.push({ id: 'conflicting-chat-wrapper', hashed_embed_id: bundleHash(body.embed_id),
    hashed_user_id: ACTOR, key_type: 'chat', hashed_chat_id: bundleHash('new-personal-chat'),
    encrypted_embed_key: 'other-key', created_at: 10 });
  const database = fakeDatabase(seed);
  await assert.rejects(writeLegacyEmbed(database, body),
    (error) => error instanceof ProtocolError && error.code === 'bundle_wrapper_mismatch');
  assert.equal(database.rows.embeds.some((row) => row.embed_id === body.embed_id), false);
  assert.equal(database.rows.embed_keys.length, 1);
});

// contract-test: direct surface=rest_api assertions=teams.chat.encrypted-until-invoked
test('bundle write checks current Team membership and chat scope under transaction locks', async () => {
  const seed = existingSeed();
  const teamHash = 'c'.repeat(64);
  seed.chats.push({ id: 'team-chat', hashed_team_id: teamHash, storage_state: 'hot' });
  seed.team_memberships.push({ hashed_team_id: teamHash, hashed_user_id: ACTOR,
    status: 'active', role: 'member' });
  seed.teams.push({ hashed_team_id: teamHash, status: 'active' });
  const database = fakeDatabase(seed);
  const body = bundleWrite({ chatId: 'team-chat', teamHash, allowNew: false });
  assert.equal((await writeLegacyEmbed(database, body)).status, 'created');
  database.rows.team_memberships[0].status = 'inactive';
  await assert.rejects(writeLegacyEmbed(database, body),
    (error) => error instanceof ProtocolError && error.code === 'bundle_team_write_denied');
  database.rows.team_memberships[0].status = 'active';
  database.rows.chats[1].hashed_team_id = 'd'.repeat(64);
  await assert.rejects(writeLegacyEmbed(database, body),
    (error) => error instanceof ProtocolError && error.code === 'bundle_chat_scope_mismatch');
});

// contract-test: direct surface=rest_api assertions=projects.files.concurrent-chat-safety
test('bundle write binds a committed preflight and rejects missing chat after deletion', async () => {
  const seed = existingSeed();
  seed.chats.push({ id: 'preflight-chat', hashed_user_id: ACTOR, hashed_team_id: null,
    storage_state: 'hot' });
  seed.chat_turn_preflights = [{ id: 'preflight-1', hashed_user_id: ACTOR,
    chat_id: 'preflight-chat', user_message_id: 'message-1', state: 'PREPARED' }];
  const database = fakeDatabase(seed);
  const body = bundleWrite({ chatId: 'preflight-chat', preflightId: 'preflight-1', allowNew: false });
  assert.equal((await writeLegacyEmbed(database, body)).status, 'created');
  database.rows.chat_turn_preflights[0].state = 'ABANDONED';
  await assert.rejects(writeLegacyEmbed(database, body),
    (error) => error instanceof ProtocolError && error.code === 'bundle_preflight_mismatch');
  database.rows.chat_turn_preflights[0].state = 'PREPARED';
  database.rows.chat_turn_preflights[0].state = 'TERMINAL';
  assert.equal((await writeLegacyEmbed(database, body)).status, 'idempotent');
  database.rows.embeds = database.rows.embeds.filter((row) => row.embed_id !== body.embed_id);
  await assert.rejects(writeLegacyEmbed(database, body),
    (error) => error instanceof ProtocolError && error.code === 'bundle_preflight_finished');
  database.rows.chat_turn_preflights[0].state = 'PREPARED';
  database.rows.chats.pop();
  await assert.rejects(writeLegacyEmbed(database, { ...body,
    bundle_context: { ...body.bundle_context, allow_new_personal_chat: true },
  }), (error) => error instanceof ProtocolError && error.code === 'bundle_chat_scope_mismatch');
});

// contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit,projects.files.no-server-decryption-authority
test('strict request validation admits ciphertext fields and rejects plaintext storage metadata', () => {
  assert.equal(testing.validateRequest(updateBody()).head.encrypted_content, 'cipher-head-v2');
  for (const forbidden of [
    { path: 'README.md' }, { plaintext: 'private file' }, { content_hash: 'd'.repeat(64) },
  ]) {
    assert.throws(
      () => testing.validateRequest({ ...updateBody(), ...forbidden }),
      (error) => error instanceof ProtocolError && error.code === 'invalid_request',
    );
  }
});

// contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit,projects.files.no-server-decryption-authority
test('hosted create atomically stores encrypted head, v1 history, link, wrappers, and receipt', async () => {
  const seed = existingSeed();
  seed.project_items = [];
  seed.embeds = [];
  seed.embed_diffs = [];
  seed.projects[0].item_count = 0;
  const database = fakeDatabase(seed);

  const result = await commitEmbedRevision(database, createBody());

  assert.deepEqual(result, {
    status: 'committed', operation_id: 'create-1', embed_id: EMBED_ID,
    current_revision: 1, idempotent: false,
  });
  assert.equal(database.rows.embeds[0].encrypted_content, 'cipher-head-v1');
  assert.equal(database.rows.embeds[0].version_number, 1);
  assert.equal(database.rows.project_items[0].target_id_encrypted, 'cipher-target-id');
  assert.equal(database.rows.embed_diffs[0].encrypted_snapshot, 'cipher-snapshot-v1');
  assert.deepEqual(database.rows.embed_keys.map((row) => row.key_type).sort(), ['chat', 'project']);
  assert.equal(database.rows.embed_version_commits.length, 1);
  assert.equal(database.rows.projects[0].item_count, 1);
  for (const row of [
    database.rows.embeds[0], database.rows.project_items[0],
    ...database.rows.embed_diffs, ...database.rows.embed_version_commits,
  ]) {
    assert.equal('path' in row, false);
    assert.equal('content_hash' in row, false);
    assert.equal('plaintext' in row, false);
  }
});

// contract-test: supporting surface=rest_api assertions=projects.files.commit-replay,projects.files.hosted-ciphertext-commit
test('same operation and ciphertext payload replays without a second write', async () => {
  const database = fakeDatabase(existingSeed());
  const first = await commitEmbedRevision(database, updateBody());
  const replay = await commitEmbedRevision(database, updateBody());

  assert.equal(first.idempotent, false);
  assert.equal(replay.idempotent, true);
  assert.equal(replay.current_revision, 2);
  assert.equal(database.rows.embed_diffs.length, 2);
  assert.equal(database.rows.embed_version_commits.length, 1);
  assert.equal(database.rows.embeds[0].version_number, 2);
});

// contract-test: direct surface=rest_api assertions=storage.versions.bounded-reconstruction
test('periodic client snapshot and patch publish atomically with the current revision', async () => {
  const database = fakeDatabase(existingSeed());
  const body = updateBody({ history_rows: [{
    version_number: 2, encrypted_snapshot: 'cipher-checkpoint-v2',
    encrypted_patch: 'cipher-patch-v2', created_at: 20,
  }] });
  const result = await commitEmbedRevision(database, body);
  assert.equal(result.current_revision, 2);
  assert.equal(database.rows.embed_diffs[1].has_snapshot, true);
  assert.equal(database.rows.embed_diffs[1].has_patch, true);
  assert.equal(database.rows.embed_diffs[1].encrypted_snapshot, 'cipher-checkpoint-v2');
});

// contract-test: direct surface=rest_api assertions=storage.versions.bounded-reconstruction
test('write-authorized checkpoint is version fenced, immutable and idempotent', async () => {
  const database = fakeDatabase(existingSeed());
  await commitEmbedRevision(database, updateBody());
  const body = {
    embed_id: EMBED_ID, version_number: 2, expected_revision: 2,
    encrypted_snapshot: 'cipher-checkpoint-v2', operation_id: 'snapshot-v2',
    actor_user_hash: ACTOR, project_id: PROJECT_ID,
  };
  database.rows.embed_diffs[1].archive_state = 'copied';
  database.rows.embed_diffs[1].archive_checksum = 'prior-checksum';
  database.rows.embed_diffs[1].archive_object_key = 'embed-versions/old.json';
  const first = await publishEmbedSnapshot(database, body);
  const replay = await publishEmbedSnapshot(database, body);
  assert.equal(first.idempotent, false);
  assert.equal(replay.idempotent, true);
  assert.equal(database.rows.embed_diffs[1].encrypted_snapshot, 'cipher-checkpoint-v2');
  assert.equal(database.rows.embed_diffs[1].archive_state, 'stale');
  assert.equal(database.rows.embed_diffs[1].archive_object_key, 'embed-versions/old.json');
  await assert.rejects(
    publishEmbedSnapshot(database, { ...body, encrypted_snapshot: 'changed' }),
    (error) => error instanceof ProtocolError && error.code === 'immutable_snapshot_mismatch',
  );
  database.rows.embeds[0].version_number = 3;
  assert.equal((await publishEmbedSnapshot(database, body)).idempotent, true);
  await assert.rejects(
    publishEmbedSnapshot(database, { ...body, operation_id: 'other' }),
    (error) => error instanceof ProtocolError && error.code === 'immutable_snapshot_mismatch',
  );
});

// contract-test: direct surface=rest_api assertions=storage.versions.bounded-reconstruction
test('archive locator publication rejects a client snapshot that raced object copy', async () => {
  const database = fakeDatabase(existingSeed());
  await commitEmbedRevision(database, updateBody());
  let row = database.rows.embed_diffs[1];
  const original = createHash('sha256').update(JSON.stringify({
    encrypted_patch: row.encrypted_patch, encrypted_snapshot: null, version_number: 2,
  })).digest('hex');
  await publishEmbedSnapshot(database, {
    embed_id: EMBED_ID, version_number: 2, expected_revision: 2,
    encrypted_snapshot: 'later-checkpoint', operation_id: 'snapshot-v2',
    actor_user_hash: ACTOR, project_id: PROJECT_ID,
  });
  row = database.rows.embed_diffs[1];
  const copy = {
    row_id: row.id, embed_id: EMBED_ID, version_number: 2,
    source_checksum: original, archive_object_key: 'embed-versions/key/old.json',
    archive_regions: ['eu-a', 'eu-b'],
  };
  Object.assign(row, { archive_pending_object_key: copy.archive_object_key,
    archive_pending_checksum: original, archive_copy_lease_until: Math.floor(Date.now() / 1000) + 300 });
  assert.equal((await finalizeEmbedArchiveCopy(database, copy)).status, 'stale');
  assert.equal(database.rows.embed_diffs[1].archive_object_key, undefined);
  row = database.rows.embed_diffs[1];
  const fresh = createHash('sha256').update(JSON.stringify({
    encrypted_patch: row.encrypted_patch, encrypted_snapshot: 'later-checkpoint', version_number: 2,
  })).digest('hex');
  Object.assign(row, { archive_pending_object_key: 'embed-versions/key/new.json',
    archive_pending_checksum: fresh, archive_copy_lease_until: Math.floor(Date.now() / 1000) + 300 });
  const indexed = await finalizeEmbedArchiveCopy(database, {
    ...copy, source_checksum: fresh, archive_object_key: 'embed-versions/key/new.json',
  });
  assert.equal(indexed.status, 'copied');
  assert.equal(database.rows.embed_diffs[1].archive_checksum, fresh);
});

function archivedVersionFixture() {
  const seed = existingSeed();
  seed.embeds[0].version_number = 100;
  const row = seed.embed_diffs[0];
  const checksum = createHash('sha256').update(JSON.stringify({
    encrypted_patch: null, encrypted_snapshot: row.encrypted_snapshot, version_number: 1,
  })).digest('hex');
  Object.assign(row, {
    archive_state: 'copied', archive_object_key: 'embed-versions/key/object.json',
    archive_checksum: checksum, archive_regions: ['eu-a', 'eu-b'],
    has_snapshot: true, has_patch: false, archive_copied_at: 1,
    archive_superseded_object_key: null,
  });
  const input = { row_id: row.id, embed_id: EMBED_ID, version_number: 1, source_checksum: checksum };
  return { seed, input };
}

// contract-test: direct surface=rest_api assertions=storage.versions.metadata-and-payload,storage.integrity.observable-reconcilable
test('archive prepare indexes proposed key before upload and refuses a deleting chat', async () => {
  const { seed, input } = archivedVersionFixture();
  Object.assign(seed.embed_diffs[0], { archive_state: null, archive_object_key: null,
    archive_checksum: null, archive_regions: null });
  const database = fakeDatabase(seed);
  const key = `embed-versions/${createHash('sha256').update(EMBED_ID).digest('hex')}/1/${input.source_checksum}.json`;
  const body = { ...input, archive_object_key: key };
  database.rows.chats[0].storage_state = 'deleting';
  await assert.rejects(prepareEmbedArchiveCopy(database, body),
    (error) => error instanceof ProtocolError && error.code === 'archive_chat_deleting');
  assert.equal(database.rows.embed_diffs[0].archive_pending_object_key, undefined);
  database.rows.chats[0].storage_state = 'hot';
  const prepared = await prepareEmbedArchiveCopy(database, body);
  assert.equal(prepared.status, 'preparing');
  assert.equal(database.rows.embed_diffs[0].archive_pending_object_key, key);
  assert.ok(database.rows.embed_diffs[0].archive_copy_lease_until > Math.floor(Date.now() / 1000));
  const copied = await finalizeEmbedArchiveCopy(database, { ...body, archive_regions: ['eu-a', 'eu-b'] });
  assert.equal(copied.status, 'copied');
  assert.equal(database.rows.embed_diffs[0].archive_pending_object_key, null);
});

// contract-test: direct surface=rest_api assertions=storage.integrity.observable-reconcilable
test('stale pending version key remains inventoried through writer grace', async () => {
  const { seed, input } = archivedVersionFixture();
  Object.assign(seed.embed_diffs[0], { archive_state: null, archive_object_key: null,
    archive_checksum: null, archive_regions: null });
  const database = fakeDatabase(seed);
  const key = `embed-versions/${createHash('sha256').update(EMBED_ID).digest('hex')}/1/${input.source_checksum}.json`;
  const body = { ...input, archive_object_key: key };
  await prepareEmbedArchiveCopy(database, body);
  database.rows.embed_diffs[0].encrypted_snapshot = 'changed-client-ciphertext';
  assert.equal((await finalizeEmbedArchiveCopy(database, { ...body, archive_regions: ['eu-a'] })).status, 'stale');
  assert.equal(database.rows.embed_diffs[0].archive_pending_object_key, key);
  await assert.rejects(retireEmbedArchiveCopy(database, {
    row_id: input.row_id, embed_id: EMBED_ID, version_number: 1, archive_object_key: key,
  }), (error) => error instanceof ProtocolError && error.code === 'archive_writer_may_still_upload');
  database.rows.embed_diffs[0].archive_copy_lease_until = 1;
  const retired = await retireEmbedArchiveCopy(database, {
    row_id: input.row_id, embed_id: EMBED_ID, version_number: 1, archive_object_key: key,
  });
  assert.equal(retired.status, 'retired');
  assert.equal(database.rows.embed_diffs[0].archive_pending_object_key, null);
});

// contract-test: direct surface=rest_api assertions=storage.versions.bounded-reconstruction
test('reader activation and first-cohort 24-hour rollback buffer gate version pruning', async () => {
  const { seed, input } = archivedVersionFixture();
  const database = fakeDatabase(seed);
  await assert.rejects(activateEmbedArchiveReader(database, input),
    (error) => error instanceof ProtocolError && error.code === 'version_archive_read_rollout_not_verified');
  Object.assign(database.rows.embed_version_archive_rollout[0], {
    read_enabled: true, compatibility_verified: true, reader_receipt: 'reviewed-reader',
    pruning_enabled: true, validation_receipt: 'reviewed-validation',
  });
  const activated = await activateEmbedArchiveReader(database, input);
  assert.equal(activated.status, 'reader_active');
  assert.equal(activated.source_copy_until - database.rows.embed_diffs[0].archive_reader_activated_at, 86400);
  await assert.rejects(pruneEmbedArchivePayload(database, input),
    (error) => error instanceof ProtocolError && error.code === 'version_archive_rollback_buffer_active');
  database.rows.embed_diffs[0].archive_source_copy_until = 1;
  database.pendingRecovery = true;
  await assert.rejects(pruneEmbedArchivePayload(database, input),
    (error) => error instanceof ProtocolError && error.code === 'canonical_recovery_acknowledgement_required');
  database.pendingRecovery = false;
  const pruned = await pruneEmbedArchivePayload(database, input);
  assert.equal(pruned.pruned_count, 1);
  assert.equal(database.rows.embed_diffs[0].encrypted_snapshot, null);
  assert.equal(database.rows.embed_diffs[0].has_snapshot, true);
  assert.equal((await pruneEmbedArchivePayload(database, input)).pruned_count, 0);
  database.rows.embed_diffs.push({
    ...structuredClone(database.rows.embed_diffs[0]), id: 'history-v2', version_number: 2,
    snapshot_operation_id: null, snapshot_digest: null,
  });
  await assert.rejects(publishEmbedSnapshot(database, {
    embed_id: EMBED_ID, version_number: 2, expected_revision: 100,
    encrypted_snapshot: 'late', operation_id: 'late', actor_user_hash: ACTOR,
    project_id: PROJECT_ID,
  }), (error) => error instanceof ProtocolError && error.code === 'snapshot_target_pruned');
});

// contract-test: direct surface=rest_api assertions=storage.versions.metadata-and-payload
test('verified regional expansion preserves active and pruned archive state', async () => {
  const { seed, input } = archivedVersionFixture();
  const database = fakeDatabase(seed);
  database.rows.embed_diffs[0].archive_state = 'reader_active';
  Object.assign(database.rows.embed_diffs[0], { archive_pending_object_key: 'embed-versions/key/object.json',
    archive_pending_checksum: input.source_checksum, archive_copy_lease_until: Math.floor(Date.now() / 1000) + 300 });
  await finalizeEmbedArchiveCopy(database, {
    ...input, archive_object_key: 'embed-versions/key/object.json',
    archive_regions: ['eu-a', 'eu-b', 'eu-c'],
  });
  assert.equal(database.rows.embed_diffs[0].archive_state, 'reader_active');
  assert.deepEqual(database.rows.embed_diffs[0].archive_regions, ['eu-a', 'eu-b', 'eu-c']);
  database.rows.embed_diffs[0].archive_state = 'pruned';
  database.rows.embed_diffs[0].encrypted_snapshot = null;
  Object.assign(database.rows.embed_diffs[0], { archive_pending_object_key: 'embed-versions/key/object.json',
    archive_pending_checksum: input.source_checksum, archive_copy_lease_until: Math.floor(Date.now() / 1000) + 300 });
  await finalizeEmbedArchiveCopy(database, {
    ...input, archive_object_key: 'embed-versions/key/object.json',
    archive_regions: ['eu-a', 'eu-b', 'eu-c', 'eu-d'],
  });
  assert.equal(database.rows.embed_diffs[0].archive_state, 'pruned');
  assert.deepEqual(database.rows.embed_diffs[0].archive_regions, ['eu-a', 'eu-b', 'eu-c', 'eu-d']);
});

// contract-test: direct surface=rest_api assertions=storage.versions.bounded-reconstruction
test('pruning rejects recent head, stale source and superseded archive locator', async () => {
  const { seed, input } = archivedVersionFixture();
  seed.embed_version_archive_rollout[0] = {
    id: 'agentic-storage-v2', read_enabled: true, pruning_enabled: true,
    compatibility_verified: true, reader_receipt: 'reader', validation_receipt: 'validation',
    initial_cohort: false, failure_code: null,
  };
  const database = fakeDatabase(seed);
  const row = database.rows.embed_diffs[0];
  Object.assign(row, { archive_state: 'reader_active', archive_reader_activated_at: 1,
    archive_source_copy_until: 1 });
  database.rows.embeds[0].version_number = 32;
  await assert.rejects(pruneEmbedArchivePayload(database, input),
    (error) => error instanceof ProtocolError && error.code === 'recent_version_protected');
  database.rows.embeds[0].version_number = 100;
  row.encrypted_snapshot = 'changed-ciphertext';
  await assert.rejects(pruneEmbedArchivePayload(database, input),
    (error) => error instanceof ProtocolError && error.code === 'archive_source_changed_or_unverified');
  row.encrypted_snapshot = 'cipher-snapshot-v1';
  row.archive_superseded_object_key = 'embed-versions/key/old.json';
  await assert.rejects(pruneEmbedArchivePayload(database, input),
    (error) => error instanceof ProtocolError && error.code === 'archive_source_changed_or_unverified');
});

// contract-test: direct surface=rest_api assertions=storage.versions.bounded-reconstruction
test('project viewer cannot publish a checkpoint', async () => {
  const seed = existingSeed();
  const teamHash = createHash('sha256').update('team-id').digest('hex');
  seed.projects[0].hashed_user_id = null;
  seed.projects[0].hashed_team_id = teamHash;
  seed.project_items[0].hashed_user_id = null;
  seed.project_items[0].hashed_team_id = teamHash;
  seed.team_memberships.push({ hashed_team_id: teamHash, hashed_user_id: ACTOR, status: 'active', role: 'viewer' });
  seed.teams.push({ hashed_team_id: teamHash, status: 'active' });
  const database = fakeDatabase(seed);
  await assert.rejects(
    publishEmbedSnapshot(database, {
      embed_id: EMBED_ID, version_number: 2, expected_revision: 2,
      encrypted_snapshot: 'cipher-checkpoint', operation_id: 'snapshot-v2',
      actor_user_hash: ACTOR, project_id: PROJECT_ID, team_id: 'team-id',
    }),
    (error) => error instanceof ProtocolError && error.code === 'project_access_denied',
  );
});

// contract-test: supporting surface=rest_api assertions=projects.files.commit-replay
test('same operation rejects a changed ciphertext payload', async () => {
  const database = fakeDatabase(existingSeed());
  await commitEmbedRevision(database, updateBody());
  await assert.rejects(
    commitEmbedRevision(database, updateBody({
      head: { encrypted_content: 'different-ciphertext', updated_at: 20 },
    })),
    (error) => error instanceof ProtocolError && error.code === 'operation_payload_mismatch',
  );
  assert.equal(database.rows.embed_diffs.length, 2);
  assert.equal(database.rows.embed_version_commits.length, 1);
});

// contract-test: supporting surface=rest_api assertions=projects.files.concurrent-chat-safety,projects.files.hosted-ciphertext-commit
test('two chats racing from one revision cannot both replace the encrypted head', async () => {
  const database = fakeDatabase(existingSeed());
  const [left, right] = await Promise.all([
    commitEmbedRevision(database, updateBody()),
    commitEmbedRevision(database, updateBody({
      operation_id: 'operation-2', chat_id: 'chat-b', proposal_digest: 'd'.repeat(64),
      head: { encrypted_content: 'cipher-head-from-chat-b', updated_at: 21 },
      history_rows: [{
        version_number: 2, encrypted_snapshot: null,
        encrypted_patch: 'cipher-patch-from-chat-b', created_at: 21,
      }],
    })),
  ]);

  assert.equal([left, right].filter((result) => result.status === 'committed').length, 1);
  assert.equal([left, right].filter((result) => result.status === 'conflict').length, 1);
  assert.equal(database.rows.embed_diffs.length, 2);
  assert.equal(database.rows.embed_version_commits.length, 1);
  assert.equal(database.rows.embeds[0].version_number, 2);
});

// contract-test: supporting surface=rest_api assertions=projects.files.concurrent-chat-safety,projects.files.hosted-ciphertext-commit
test('two creates for one deterministic opaque target produce one file', async () => {
  const seed = existingSeed();
  seed.project_items = [];
  seed.embeds = [];
  seed.embed_diffs = [];
  seed.projects[0].item_count = 0;
  const database = fakeDatabase(seed);
  const [left, right] = await Promise.all([
    commitEmbedRevision(database, createBody()),
    commitEmbedRevision(database, createBody({
      operation_id: 'create-2', chat_id: 'chat-b', proposal_digest: 'd'.repeat(64),
    })),
  ]);

  assert.equal([left, right].filter((result) => result.status === 'committed').length, 1);
  assert.equal([left, right].filter((result) => result.status === 'conflict').length, 1);
  assert.equal(database.rows.embeds.length, 1);
  assert.equal(database.rows.project_items.length, 1);
  assert.equal(database.rows.embed_diffs.length, 1);
  assert.equal(database.rows.embed_keys.length, 2);
});

// contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit,projects.access.explicit-context
test('Team Project commit requires an active writer role and exact Team item scope', async () => {
  const teamId = 'team-1';
  const teamHash = createHash('sha256').update(teamId).digest('hex');
  const seed = existingSeed();
  seed.projects[0].hashed_user_id = null;
  seed.projects[0].hashed_team_id = teamHash;
  seed.project_items[0].hashed_user_id = null;
  seed.project_items[0].hashed_team_id = teamHash;
  seed.embeds[0].hashed_user_id = 'f'.repeat(64);
  seed.embed_diffs[0].hashed_user_id = 'f'.repeat(64);
  seed.teams = [{ id: 'team-row', hashed_team_id: teamHash, status: 'active' }];
  seed.team_memberships = [{
    id: 'membership-row', hashed_team_id: teamHash, hashed_user_id: ACTOR,
    status: 'active', role: 'viewer',
  }];
  const denied = fakeDatabase(seed);
  await assert.rejects(
    commitEmbedRevision(denied, updateBody({ team_id: teamId })),
    (error) => error instanceof ProtocolError && error.code === 'project_access_denied',
  );
  assert.equal(denied.rows.embeds[0].version_number, 1);
  assert.equal(denied.rows.embed_version_commits.length, 0);

  seed.team_memberships[0].role = 'member';
  const allowed = fakeDatabase(seed);
  const result = await commitEmbedRevision(allowed, updateBody({ team_id: teamId }));
  assert.equal(result.status, 'committed');
  assert.equal(allowed.rows.embeds[0].version_number, 2);
});

// contract-test: supporting surface=rest_api assertions=projects.files.hosted-ciphertext-commit,projects.access.explicit-context
test('commit cannot target an embed that is not an item in the authorized Project', async () => {
  const seed = existingSeed();
  seed.project_items = [];
  const database = fakeDatabase(seed);

  await assert.rejects(
    commitEmbedRevision(database, updateBody()),
    (error) => error instanceof ProtocolError && error.code === 'project_item_access_denied',
  );
  assert.equal(database.rows.embeds[0].version_number, 1);
  assert.equal(database.rows.embed_diffs.length, 1);
  assert.equal(database.rows.embed_version_commits.length, 0);
});
