import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

import { isAuthorized } from '../src/index.js';
import { commitEmbedRevision, ProtocolError, testing } from '../src/operations.js';

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
        forUpdate() { return query; },
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
          return Promise.resolve(structuredClone(matching())).then(resolve, reject);
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
      encrypted_content: 'cipher-head-v1', version_number: 1,
    }],
    embed_diffs: [{
      id: 'history-v1', embed_id: EMBED_ID, hashed_user_id: ACTOR,
      version_number: 1, encrypted_snapshot: 'cipher-snapshot-v1',
      encrypted_patch: null, created_at: 10,
    }],
    embed_version_commits: [], embed_keys: [], team_memberships: [], teams: [],
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
