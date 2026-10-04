import test from 'node:test';
import assert from 'node:assert/strict';
import { archiveMutationOperation } from '../src/mutations.js';
import { checksum } from '../src/operations.js';

const CHAT = 'chat-1';
const OWNER = 'a'.repeat(64);
const TEAM = 'b'.repeat(64);
const sourceRows = () => [
  { id: 'row-1', chat_id: CHAT, client_message_id: 'm1', created_at: 1, encrypted_content: 'cipher-1' },
  { id: 'row-2', chat_id: CHAT, client_message_id: 'm2', created_at: 2, encrypted_content: 'cipher-2' },
];

function database() {
  const source = sourceRows();
  const rows = {
    chats: [{ id: CHAT, hashed_user_id: OWNER, hashed_team_id: null, storage_state: 'hot', archived_message_count: 2,
      archive_mutation_v: 0 }],
    chat_message_archive_pages: [{ id: 'page-1', chat_id: CHAT, segment_id: 'segment-1', hashed_user_id: OWNER,
      published: true, read_enabled: true, pruned: true, message_count: 2, message_ids: ['m1', 'm2'],
      checksum: 'b'.repeat(64), source_checksum: checksum(source),
      object_key: 'message-pages/page-1.gz', large_objects: [] }],
    chat_message_archive_segments: [{ id: 'segment-1', chat_id: CHAT, hashed_user_id: OWNER,
      hashed_team_id: null, page_count: 1, state: 'reader_active' }],
    team_memberships: [], teams: [],
    messages: [],
  };
  const client = (store) => (table) => {
    const filters = [];
    const matches = (row) => filters.every(([field, value]) => value?.in
      ? value.in.includes(row[field]) : value?.contains
        ? value.contains.every(item => row[field]?.includes(item)) : row[field] === value);
    const selected = () => (store[table] || []).filter(matches);
    const query = {
      where(field, value) {
        if (typeof field === 'object') filters.push(...Object.entries(field));
        else filters.push([field, value]);
        return query;
      },
      whereIn(field, values) {
        filters.push([field, { in: values }]);
        return query;
      },
      whereRaw(sql, args) {
        assert.match(sql, /message_ids::jsonb/);
        filters.push(['message_ids', { contains: JSON.parse(args[0]) }]);
        return query;
      },
      async limit(count) { return structuredClone(selected().slice(0, count)); },
      async count() { return [{ count: selected().length }]; },
      async select(field) { return selected().map(row => ({ [field]: row[field] })); },
      forUpdate() { return query; },
      forShare() { return query; },
      async first() { return structuredClone(selected()[0]); },
      update(values) {
        for (const row of selected()) Object.assign(row, structuredClone(values));
        return Promise.resolve(selected().length);
      },
      async delete() {
        const doomed = new Set(selected());
        store[table] = (store[table] || []).filter(row => !doomed.has(row));
        return doomed.size;
      },
      insert(values) {
        return {
          onConflict() { return this; },
          async ignore() {
            for (const row of values) {
              if (!store[table].some(current => current.id === row.id ||
                (current.chat_id === row.chat_id && current.client_message_id === row.client_message_id))) {
                store[table].push(structuredClone(row));
              }
            }
          },
        };
      },
    };
    return query;
  };
  return {
    rows,
    async transaction(callback) {
      const copy = structuredClone(rows);
      const result = await callback(client(copy));
      for (const key of Object.keys(rows)) rows[key] = copy[key];
      return result;
    },
  };
}

function request(overrides = {}) {
  const source = sourceRows();
  return { operation: 'restore_and_retire_page', data: {
    chat_id: CHAT, page_id: 'page-1', message_id: 'm1', expected_owner_hash: OWNER,
    expected_page_checksum: 'b'.repeat(64), expected_source_checksum: checksum(source),
    expected_object_key: 'message-pages/page-1.gz', expected_large_objects: [], source_rows: source,
    ...overrides,
  } };
}

// contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.deletion.global-authoritative
test('promotion restores only one bounded page and removes its reader index atomically', async () => {
  const db = database();
  const result = await archiveMutationOperation(db, request());
  assert.equal(result.promoted, true);
  assert.deepEqual(db.rows.messages, sourceRows());
  assert.equal(db.rows.chats[0].archived_message_count, 0);
  assert.equal(db.rows.chats[0].archive_mutation_v, 1);
  assert.equal(db.rows.chat_message_archive_segments[0].page_count, 0);
  assert.deepEqual(db.rows.chat_message_archive_pages, []);
  assert.deepEqual(await archiveMutationOperation(db, request()), { promoted: false, duplicate: true });
  assert.equal(db.rows.chats[0].archive_mutation_v, 1);
});

// contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
test('Team member can promote a Team-owned page; revoked member cannot retire it', async () => {
  const db = database();
  db.rows.chats[0].hashed_user_id = null;
  db.rows.chats[0].hashed_team_id = TEAM;
  db.rows.chat_message_archive_pages[0].hashed_user_id = null;
  db.rows.chat_message_archive_pages[0].hashed_team_id = TEAM;
  db.rows.chat_message_archive_segments[0].hashed_user_id = null;
  db.rows.chat_message_archive_segments[0].hashed_team_id = TEAM;
  db.rows.team_memberships.push({ hashed_team_id: TEAM, hashed_user_id: OWNER,
    role: 'member', status: 'active' });
  db.rows.teams.push({ hashed_team_id: TEAM, status: 'active' });
  const teamRequest = request({ expected_owner_hash: TEAM, expected_actor_user_hash: OWNER });
  db.rows.team_memberships[0].role = 'viewer';
  await assert.rejects(archiveMutationOperation(db, teamRequest), { code: 'team_write_permission_changed' });
  assert.equal(db.rows.chat_message_archive_pages.length, 1);
  assert.equal(db.rows.messages.length, 0);
  db.rows.team_memberships[0].role = 'member';
  assert.equal((await archiveMutationOperation(db, teamRequest)).promoted, true);
  assert.equal(db.rows.chat_message_archive_pages.length, 0);
  assert.equal(db.rows.messages.length, 2);
});

// contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.deletion.global-authoritative
test('hot edits survive promotion without an archive overwrite', async () => {
  const db = database();
  db.rows.messages.push({ ...sourceRows()[0], encrypted_content: 'newer-hot-edit' });
  await archiveMutationOperation(db, request());
  assert.equal(db.rows.messages.find(row => row.client_message_id === 'm1').encrypted_content, 'newer-hot-edit');
  assert.equal(db.rows.messages.length, 2);
});

// contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.privacy.ciphertext-boundary
test('cross-chat, checksum and identity changes roll back every mutation', async () => {
  const db = database();
  for (const changed of [
    { chat_id: 'foreign-chat' },
    { expected_owner_hash: 'c'.repeat(64) },
    { expected_page_checksum: 'c'.repeat(64) },
    { expected_object_key: 'other/page.gz' },
    { expected_large_objects: [{ object_key: 'other/large.json' }] },
    { source_rows: [{ ...sourceRows()[0], encrypted_content: 'tampered' }, sourceRows()[1]] },
    { source_rows: [sourceRows()[1], sourceRows()[0]], expected_source_checksum: checksum([sourceRows()[1], sourceRows()[0]]) },
  ]) {
    await assert.rejects(archiveMutationOperation(db, request(changed)));
    assert.deepEqual(db.rows.messages, []);
    assert.equal(db.rows.chat_message_archive_pages.length, 1);
    assert.equal(db.rows.chats[0].archived_message_count, 2);
    assert.equal(db.rows.chats[0].archive_mutation_v, 0);
  }
});

// contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
test('unpruned rollback copy retires without changing archived count', async () => {
  const db = database();
  db.rows.chat_message_archive_pages[0].pruned = false;
  db.rows.chats[0].archived_message_count = 0;
  await archiveMutationOperation(db, request());
  assert.equal(db.rows.chats[0].archived_message_count, 0);
  assert.deepEqual(db.rows.chat_message_archive_pages, []);
});

// contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.deletion.global-authoritative
test('mutation lookup sees unreadable published and unpublished intents', async () => {
  const db = database();
  db.rows.chat_message_archive_pages[0].read_enabled = false;
  const lookup = () => archiveMutationOperation(db, { operation: 'lookup_mutation_page', data: {
    chat_id: CHAT, message_id: 'm1', expected_owner_hash: OWNER,
  } });
  assert.equal((await lookup()).page.id, 'page-1');
  db.rows.chat_message_archive_pages[0].published = false;
  assert.equal((await lookup()).page.published, false);
  db.rows.chat_message_archive_pages.push({ ...db.rows.chat_message_archive_pages[0], id: 'page-2' });
  await assert.rejects(lookup(), { code: 'archive_message_has_multiple_pages' });
});

// contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.deletion.global-authoritative
test('published unreadable page promotes; stale unpublished intent waits for lease and aborts', async () => {
  const db = database();
  db.rows.chat_message_archive_pages[0].read_enabled = false;
  db.rows.chat_message_archive_pages[0].pruned = false;
  db.rows.chat_message_archive_segments[0].state = 'verified';
  db.rows.chat_message_archive_segments[0].page_count = 0;
  await archiveMutationOperation(db, request());
  assert.equal(db.rows.messages.length, 2);
  assert.equal(db.rows.chat_message_archive_segments[0].page_count, 0);

  const stale = database();
  stale.rows.chat_message_archive_pages[0].published = false;
  stale.rows.chat_message_archive_pages[0].read_enabled = false;
  stale.rows.chat_message_archive_segments[0].state = 'copying';
  stale.rows.chat_message_archive_segments[0].page_count = 0;
  stale.rows.chat_message_archive_segments[0].lease_until = 300;
  const abort = now => archiveMutationOperation(stale, { operation: 'abort_unpublished_page', data: {
    chat_id: CHAT, page_id: 'page-1', expected_owner_hash: OWNER,
    expected_page_checksum: 'b'.repeat(64), expected_object_key: 'message-pages/page-1.gz',
    expected_large_objects: [], now,
  } });
  await assert.rejects(abort(389), { code: 'archive_writer_may_still_upload' });
  assert.equal((await abort(390)).aborted, true);
  assert.equal(stale.rows.chat_message_archive_segments[0].state, 'aborted');
  assert.deepEqual(stale.rows.chat_message_archive_pages, []);
});

// contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.deletion.global-authoritative
test('published page cannot retire while a copying writer may upload again', async () => {
  const db = database();
  db.rows.chat_message_archive_segments[0].state = 'copying';
  await assert.rejects(archiveMutationOperation(db, request()), { code: 'archive_writer_may_still_upload' });
  assert.deepEqual(db.rows.messages, []);
  assert.equal(db.rows.chat_message_archive_pages.length, 1);
  assert.equal(db.rows.chats[0].archived_message_count, 2);
});
