import test from 'node:test';
import assert from 'node:assert/strict';

import { archiveOperation, checksum } from '../src/operations.js';

const CHAT = 'chat-1';
const OWNER = 'a'.repeat(64);
const TEAM = 'b'.repeat(64);
const SOURCE_FIELDS = ['id', 'chat_id', 'client_message_id', 'created_at', 'encrypted_content'];

// contract-test: supporting surface=rest_api assertions=storage.compression.incremental-archive,storage.integrity.observable-reconcilable
test('archive progress pages UUID cursors and honors due-state feature gates', async () => {
  const initial = seed();
  const identity = number => `00000000-0000-4000-8000-${String(number).padStart(12, '0')}`;
  initial.chat_message_archive_segments = Array.from({ length: 26 }, (_, index) => ({
    id: identity(index + 1), state: 'copying', lease_until: 99,
  }));
  initial.chat_message_archive_segments.push(
    { id: identity(27), state: 'copying', lease_until: 101 },
    { id: identity(28), state: 'verified' },
    { id: identity(29), state: 'reader_active', source_copy_until: 100 },
    { id: identity(30), state: 'reader_active', source_copy_until: 101 },
    { id: identity(31), state: 'pruned' },
  );
  const database = fakeDatabase(initial);
  const data = { now: 100, reads_enabled: false, prune_enabled: false, limit: 1000 };
  const page = await archiveOperation(database, { operation: 'progress_candidates', data });
  assert.equal(page.segments.length, 25);
  const next = await archiveOperation(database, { operation: 'progress_candidates',
    data: { ...data, after_id: page.segments.at(-1).id } });
  assert.deepEqual(next.segments.map(row => row.id), [identity(26)]);
  const gated = await archiveOperation(database, { operation: 'progress_candidates',
    data: { ...data, after_id: identity(26), reads_enabled: true, prune_enabled: true } });
  assert.deepEqual(gated.segments.map(row => row.id), [identity(28), identity(29)]);
  await assert.rejects(archiveOperation(database, { operation: 'progress_candidates',
    data: { ...data, after_id: 'not-a-uuid' } }), { code: 'invalid_archive_progress_cursor' });
});

function sourceRows() {
  return [
    { id: 'row-1', chat_id: CHAT, client_message_id: 'm1', created_at: 1, encrypted_content: 'cipher-1' },
    { id: 'row-2', chat_id: CHAT, client_message_id: 'm2', created_at: 2, encrypted_content: 'cipher-2' },
  ];
}

function seed() {
  return {
    chats: [{ id: CHAT, hashed_user_id: OWNER, hashed_team_id: null, storage_state: 'hot', archived_message_count: 0 }],
    chat_compression_checkpoints: [{
      id: 'checkpoint-1', chat_id: CHAT, encrypted_summary: 'cipher-summary',
      compressed_up_to_timestamp: 2, compressed_up_to_message_id: 'm2',
      covered_message_ids: ['m1', 'm2'],
    }],
    messages: sourceRows(),
    chat_message_archive_segments: [], chat_message_archive_pages: [],
    chat_message_archive_rollout: [{
      id: 'agentic-storage-v2', read_enabled: false, pruning_enabled: false,
      compatibility_verified: false, reader_receipt: null, validation_receipt: null,
      initial_cohort: true, failure_code: null,
    }],
    chat_completion_recovery_jobs: [], chat_recovery_outputs: [],
    team_memberships: [], teams: [], chat_turn_preflights: [],
  };
}

function fakeDatabase(initial) {
  const rows = structuredClone(initial);
  let tail = Promise.resolve();
  const client = (store) => {
    const knex = (table) => {
      const clauses = [];
      const order = [];
      let projection = null;
      let count = false;
      const compare = (left, op, right) => {
        if (op === '<') return left < right;
        if (op === '<=') return left <= right;
        if (op === '>') return left > right;
        if (op === '>=') return left >= right;
        return left === right;
      };
      const add = (join, predicate) => { clauses.push({ join, predicate }); return query; };
      const matches = (row) => {
        let result = null;
        for (const { join, predicate } of clauses) {
          const next = predicate(row);
          result = result === null ? next : join === 'or' ? result || next : result && next;
        }
        return result ?? true;
      };
      const selected = () => (store[table] ?? []).filter(matches).sort((a, b) => {
        for (const [field, direction] of order) {
          if (a[field] !== b[field]) return (a[field] < b[field] ? -1 : 1) * (direction === 'desc' ? -1 : 1);
        }
        return 0;
      });
      const where = (join, args) => {
        if (typeof args[0] === 'function') {
          const nested = knex(table);
          args[0].call(nested);
          return add(join, (row) => nested._matches(row));
        }
        if (typeof args[0] === 'object') {
          return add(join, (row) => Object.entries(args[0]).every(([field, value]) => row[field] === value));
        }
        const [field, op, value] = args.length === 2 ? [args[0], '=', args[1]] : args;
        return add(join, (row) => compare(row[field], op, value));
      };
      const apply = (values, row) => {
        for (const [field, value] of Object.entries(values)) {
          row[field] = value?.incrementRaw ? Number(row[field] ?? 0) + value.amount : jsonColumn(field, value);
        }
      };
      const jsonColumn = (field, value) => {
        const jsonFields = new Set(['source_message_ids', 'message_ids', 'message_positions', 'source_fields', 'verified_regions', 'large_objects']);
        if (!jsonFields.has(field) || value == null) return structuredClone(value);
        assert.equal(typeof value, 'string', `${field} must be bound as serialized JSON`);
        return JSON.parse(value);
      };
      const mutation = (affected) => ({
        returning: async () => structuredClone(affected),
        then(resolve, reject) { return Promise.resolve(affected.length).then(resolve, reject); },
      });
      const query = {
        _matches: matches,
        where(...args) { return where('and', args); },
        andWhere(...args) { return where('and', args); },
        orWhere(...args) { return where('or', args); },
        whereIn(field, values) { return add('and', (row) => values.includes(row[field])); },
        whereNull(field) { return add('and', (row) => row[field] == null); },
        whereRaw(sql, args) {
          if (sql.includes('message_ids::jsonb')) {
            const wanted = JSON.parse(args[0]);
            return add('and', (row) => wanted.every((id) => row.message_ids?.includes(id)));
          }
          if (sql.startsWith('(first_timestamp, first_message_id)'))
            return add('and', (row) => row.first_timestamp < args[0]
              || (row.first_timestamp === args[0] && row.first_message_id <= args[1]));
          if (sql.startsWith('(last_timestamp, last_message_id)'))
            return add('and', (row) => row.last_timestamp > args[0]
              || (row.last_timestamp === args[0] && row.last_message_id >= args[1]));
          throw new Error(`unsupported whereRaw ${sql}`);
        },
        forUpdate() { return query; },
        forShare() { return query; },
        orderBy(field, direction = 'asc') { order.push([field, direction]); return query; },
        async limit(value) { return structuredClone(selected().slice(0, value)); },
        select(fields) { projection = Array.isArray(fields) ? fields : [fields]; return query; },
        count() { count = true; return query; },
        async first() { return structuredClone(selected()[0]); },
        insert(value) {
          const inserted = (Array.isArray(value) ? value : [value]).map((row) => Object.fromEntries(
            Object.entries(row).map(([field, item]) => [field, jsonColumn(field, item)]),
          ));
          store[table] ??= [];
          store[table].push(...inserted);
          return mutation(inserted);
        },
        update(values) {
          const affected = selected();
          for (const row of affected) apply(values, row);
          return mutation(affected);
        },
        async delete() {
          const affected = new Set(selected());
          store[table] = (store[table] ?? []).filter((row) => !affected.has(row));
          return affected.size;
        },
        then(resolve, reject) {
          const result = count ? [{ count: selected().length }] : selected().map((row) => projection
            ? Object.fromEntries(projection.map((field) => field?.canonicalCiphertext
              ? ['canonical_ciphertext', typeof row.encrypted_content === 'string'
                && row.encrypted_content.length > 0 && !row.encrypted_content.startsWith('vault:')]
              : [field, row[field]])) : row);
          return Promise.resolve(structuredClone(result)).then(resolve, reject);
        },
      };
      return query;
    };
    knex.raw = (sql, params) => {
      if (sql.includes('AS canonical_ciphertext')) {
        assert.doesNotMatch(sql, /SELECT\s+encrypted_content/i);
        return { canonicalCiphertext: true };
      }
      assert.match(sql, /COALESCE\(archived_message_count/);
      return { incrementRaw: true, amount: params[0] };
    };
    return knex;
  };
  const db = client(rows);
  db.rows = rows;
  db.transaction = async (callback) => {
    const work = tail.then(async () => {
      const copy = structuredClone(rows);
      const result = await callback(client(copy));
      for (const key of new Set([...Object.keys(rows), ...Object.keys(copy)])) rows[key] = copy[key] ?? [];
      return result;
    });
    tail = work.catch(() => undefined);
    return work;
  };
  return db;
}

const body = (operation, data) => ({ operation, data });
const claimData = (overrides = {}) => ({
  chat_id: CHAT, checkpoint_id: 'checkpoint-1', end_timestamp: 2, end_message_id: 'm2', now: 100,
  ...overrides,
});

async function claim(db, overrides = {}) {
  return (await archiveOperation(db, body('claim_segment', claimData(overrides)))).segment;
}

function pageData(segment, overrides = {}) {
  const rows = sourceRows();
  return {
    id: 'page-1', page_number: 1,
    object_key: `message-pages/${segment.chat_hash}/${segment.id}/page-1/page.json.gz`,
    checksum: 'b'.repeat(64), source_checksum: checksum(rows),
    size_bytes: 250, raw_size_bytes: 500,
    message_count: 2, message_ids: ['m1', 'm2'], message_positions: [[1, 'm1'], [2, 'm2']], source_fields: SOURCE_FIELDS,
    first_timestamp: 1, first_message_id: 'm1', last_timestamp: 2, last_message_id: 'm2',
    large_objects: [], verified_regions: ['nbg1', 'fsn1'],
    ...overrides,
  };
}

async function prepare(db, segment, page = pageData(segment), now = 101) {
  return archiveOperation(db, body('prepare_page', {
    segment_id: segment.id, expected_version: segment.version,
    page: { ...page, verified_regions: [] }, now,
  }));
}

async function publish(db, segment, page = pageData(segment), now = 102) {
  return archiveOperation(db, body('publish_page', {
    segment_id: segment.id, expected_version: segment.version, page, now,
  }));
}

async function verified(db) {
  const segment = await claim(db);
  const page = pageData(segment);
  await prepare(db, segment, page);
  await publish(db, segment, page);
  const result = await archiveOperation(db, body('verify_segment', {
    segment_id: segment.id, expected_version: segment.version, page_count: 1, now: 103,
  }));
  return { segment: result, page };
}

async function recordReaderVerification(db, segment, page) {
  return archiveOperation(db, body('record_reader_verification', {
    segment_id: segment.id, expected_version: segment.version, page_id: page.id,
    checksum: page.checksum, source_checksum: page.source_checksum, now: 150,
  }));
}

// contract-test: direct surface=rest_api assertions=storage.compression.incremental-archive,storage.cold.atomic-eligible-graphs
test('claim requires the exact chat checkpoint, canonical summary, and unfenced chat', async () => {
  const db = fakeDatabase(seed());
  await assert.rejects(claim(db, { checkpoint_id: 'wrong' }), { code: 'canonical_checkpoint_required' });
  await assert.rejects(claim(db, { end_message_id: 'm1' }), { code: 'stable_checkpoint_boundary_required' });
  db.rows.chat_compression_checkpoints[0].encrypted_summary = null;
  await assert.rejects(claim(db), { code: 'canonical_checkpoint_required' });
  db.rows.chat_compression_checkpoints[0].encrypted_summary = 'cipher-summary';
  db.rows.chats[0].storage_state = 'deleting';
  await assert.rejects(claim(db), { code: 'chat_unavailable' });
  assert.equal(db.rows.chat_message_archive_segments.length, 0);
});

// contract-test: direct surface=rest_api assertions=storage.compression.incremental-archive
test('Team checkpoint claim and page metadata accept a Team owner without a user owner', async () => {
  const rows = seed();
  rows.chats[0].hashed_user_id = null;
  rows.chats[0].hashed_team_id = TEAM;
  const db = fakeDatabase(rows);
  const segment = await claim(db);
  assert.equal(segment.hashed_user_id, null);
  assert.equal(segment.hashed_team_id, TEAM);
  await prepare(db, segment);
  assert.equal(db.rows.chat_message_archive_pages[0].hashed_user_id, null);
  assert.equal(db.rows.chat_message_archive_pages[0].hashed_team_id, TEAM);
});

// contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
test('chat hash resolver is bounded and exposes current Team authority without ciphertext', async () => {
  const hash = 'c'.repeat(64);
  let calls = 0;
  const db = { transaction: async callback => callback({
    raw: async (sql, params) => {
      calls += 1;
      assert.match(sql, /encode\(digest\(id::text, 'sha256'\), 'hex'\) = ANY/);
      assert.match(sql, /SELECT id,/);
      assert.match(sql, /COALESCE\(storage_state, 'hot'\) AS storage_state/);
      assert.doesNotMatch(sql, /encrypted_content/);
      assert.deepEqual(params, [[hash]]);
      return { rows: [{ id: 'team-chat', hashed_chat_id: hash, hashed_user_id: null,
        hashed_team_id: TEAM, storage_state: 'hot' }] };
    },
  }) };
  assert.deepEqual(await archiveOperation(db, body('resolve_chat_hashes', { hashes: [hash] })), {
    chats: [{ id: 'team-chat', hashed_chat_id: hash, hashed_user_id: null,
      hashed_team_id: TEAM, storage_state: 'hot' }],
  });
  await assert.rejects(archiveOperation(db, body('resolve_chat_hashes', {
    hashes: Array.from({ length: 21 }, (_, n) => String(n).padStart(64, '0')),
  })), { code: 'invalid_chat_hash_batch' });
  assert.equal(calls, 1);
});

// contract-test: direct surface=rest_api assertions=storage.compression.incremental-archive
test('Team owner takes precedence over a retained creator hash on legacy Team chats', async () => {
  const rows = seed();
  rows.chats[0].hashed_team_id = TEAM;
  const db = fakeDatabase(rows);
  const segment = await claim(db);
  assert.equal(segment.hashed_user_id, null);
  assert.equal(segment.hashed_team_id, TEAM);
  await prepare(db, segment);
  assert.equal(db.rows.chat_message_archive_pages[0].hashed_user_id, null);
  assert.equal(db.rows.chat_message_archive_pages[0].hashed_team_id, TEAM);
});

// contract-test: direct surface=rest_api assertions=storage.compression.incremental-archive
test('chat transfer rehomes archived references atomically and keeps Team reads authorized', async () => {
  const rows = seed();
  rows.team_memberships.push({ hashed_user_id: OWNER, hashed_team_id: TEAM,
    role: 'member', status: 'active' });
  rows.teams.push({ hashed_team_id: TEAM, status: 'active' });
  const db = fakeDatabase(rows);
  const { segment } = await verified(db);
  const move = () => archiveOperation(db, body('transfer_chat_to_team', {
    chat_id: CHAT, expected_hashed_user_id: OWNER, hashed_team_id: TEAM,
    updated_at: 200, now: 200,
  }));
  const result = await move();
  assert.equal(result.chat.hashed_user_id, null);
  assert.equal(result.chat.hashed_team_id, TEAM);
  assert.equal(result.chat.archive_version, 2);
  assert.equal(db.rows.chat_message_archive_segments.find(row => row.id === segment.id).hashed_team_id, TEAM);
  assert.equal(db.rows.chat_message_archive_pages[0].hashed_team_id, TEAM);
  assert.equal(db.rows.chat_message_archive_pages.filter(row => row.hashed_user_id === OWNER).length, 0);
  db.rows.chat_message_archive_pages[0].read_enabled = true;
  const lookup = await archiveOperation(db, body('lookup_message', { chat_id: CHAT, message_id: 'm1' }));
  assert.equal(lookup.page.id, 'page-1');
  await assert.rejects(move(), { code: 'archive_authority_changed' });
});

// contract-test: direct surface=rest_api assertions=storage.compression.incremental-archive
test('chat transfer defers active archive copy and pending recovery without changing owner', async () => {
  const rows = seed();
  rows.team_memberships.push({ hashed_user_id: OWNER, hashed_team_id: TEAM,
    role: 'member', status: 'active' });
  rows.teams.push({ hashed_team_id: TEAM, status: 'active' });
  const db = fakeDatabase(rows);
  await claim(db);
  const move = () => archiveOperation(db, body('transfer_chat_to_team', {
    chat_id: CHAT, expected_hashed_user_id: OWNER, hashed_team_id: TEAM,
    updated_at: 200, now: 200,
  }));
  await assert.rejects(move(), { code: 'archive_copy_in_progress' });
  assert.equal(db.rows.chats[0].hashed_user_id, OWNER);
  db.rows.chat_message_archive_segments[0].state = 'verified';
  db.rows.chat_recovery_outputs.push({ root_chat_id: CHAT, state: 'PREPARING', deleted_at: null });
  await assert.rejects(move(), { code: 'chat_recovery_or_write_pending' });
  assert.equal(db.rows.chat_message_archive_segments[0].hashed_user_id, OWNER);
  db.rows.chat_recovery_outputs = [];
  db.rows.team_memberships[0].role = 'viewer';
  await assert.rejects(move(), { code: 'team_write_permission_changed' });
  assert.equal(db.rows.chats[0].hashed_team_id, null);
});

// contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
test('claim lease expires into a versioned restart and disallows simultaneous copy', async () => {
  const db = fakeDatabase(seed());
  const segment = await claim(db);
  await assert.rejects(claim(db, { now: 200 }), { code: 'archive_copy_in_progress' });
  const restarted = await claim(db, { now: 401 });
  assert.equal(restarted.id, segment.id);
  assert.equal(restarted.version, segment.version + 1);
  assert.equal(db.rows.chat_message_archive_segments.length, 1);
});

// contract-test: direct surface=rest_api assertions=storage.compression.incremental-archive,storage.cold.atomic-eligible-graphs
test('exact checkpoint manifest excludes late unknown source without losing covered rows', async () => {
  const db = fakeDatabase(seed());
  const segment = await claim(db);
  assert.deepEqual(segment.source_message_ids, ['m1', 'm2']);
  db.rows.messages.push({ id: 'late-row', chat_id: CHAT, client_message_id: 'late-unknown',
    created_at: 1.5, encrypted_content: 'cipher-late' });
  const source = await archiveOperation(db, body('source_page', {
    segment_id: segment.id, expected_version: segment.version, now: 101,
  }));
  assert.deepEqual(source.messages.map(row => row.client_message_id), ['m1', 'm2']);
  await prepare(db, segment);
  await publish(db, segment);
  const verifiedSegment = await archiveOperation(db, body('verify_segment', {
    segment_id: segment.id, expected_version: segment.version, page_count: 1, now: 103,
  }));
  assert.equal(verifiedSegment.state, 'verified');
  assert.equal(db.rows.messages.length, 3);
});

// contract-test: direct surface=rest_api assertions=storage.compression.incremental-archive,storage.privacy.ciphertext-boundary
test('checkpoint claim fails before S3 work when covered IDs are absent or noncanonical', async () => {
  const missing = fakeDatabase(seed());
  missing.rows.chat_compression_checkpoints[0].covered_message_ids = ['m1', 'unknown-id'];
  await assert.rejects(claim(missing), { code: 'canonical_checkpoint_sources_not_ready' });
  const vault = fakeDatabase(seed());
  vault.rows.messages[1].encrypted_content = 'vault:v1:working-copy';
  await assert.rejects(claim(vault), { code: 'canonical_checkpoint_sources_not_ready' });
  assert.equal(vault.rows.chat_message_archive_segments.length, 0);
});

// contract-test: direct surface=rest_api assertions=storage.compression.incremental-archive,storage.cold.independent-message-pages
test('source_page enforces twenty-row cursor windows inside the exact manifest', async () => {
  const initial = seed();
  initial.messages = Array.from({ length: 25 }, (_, index) => ({
    id: `row-${index + 1}`, chat_id: CHAT, client_message_id: `m${index + 1}`,
    created_at: index + 1, encrypted_content: `cipher-${index + 1}`,
  }));
  initial.chat_compression_checkpoints[0].covered_message_ids = initial.messages.map(row => row.client_message_id);
  initial.chat_compression_checkpoints[0].compressed_up_to_timestamp = 25;
  initial.chat_compression_checkpoints[0].compressed_up_to_message_id = 'm25';
  const db = fakeDatabase(initial);
  const segment = await claim(db, { end_timestamp: 25, end_message_id: 'm25' });
  db.rows.messages.push({ id: 'unknown-row', chat_id: CHAT, client_message_id: 'unknown',
    created_at: 10, encrypted_content: 'cipher-unknown' });
  const page = async (after) => archiveOperation(db, body('source_page', {
    segment_id: segment.id, expected_version: segment.version, now: 101, ...after,
  }));
  const first = await page({});
  assert.equal(first.messages.length, 20);
  assert.equal(first.messages[0].client_message_id, 'm1');
  assert.equal(first.messages[19].client_message_id, 'm20');
  const second = await page({ after_timestamp: 20, after_message_id: 'm20' });
  assert.deepEqual(second.messages.map(row => row.client_message_id), ['m21', 'm22', 'm23', 'm24', 'm25']);
});

// contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.compression.incremental-archive
test('prepare records immutable intent before upload; publish verifies it and retry is idempotent', async () => {
  const db = fakeDatabase(seed());
  const segment = await claim(db);
  const page = pageData(segment);
  await assert.rejects(publish(db, segment, page), { code: 'archive_upload_intent_required' });
  await prepare(db, segment, page);
  assert.equal(db.rows.chat_message_archive_pages[0].published, false);
  assert.equal(db.rows.chat_message_archive_pages[0].object_key, page.object_key);
  assert.equal(db.rows.chat_message_archive_pages[0].checksum, page.checksum);
  const first = await publish(db, segment, page);
  assert.equal(first.page.published, true);
  const retry = await publish(db, segment, page);
  assert.equal(retry.page.id, first.page.id);
  assert.equal(db.rows.chat_message_archive_pages.length, 1);
});

// contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.deletion.global-authoritative
test('prepare and publish reject changed source, locator, expired lease, or another chat', async () => {
  const db = fakeDatabase(seed());
  const segment = await claim(db);
  const page = pageData(segment);
  await assert.rejects(prepare(db, segment, { ...page, object_key: 'other-chat/page.gz' }), { code: 'invalid_archive_object_scope' });
  await prepare(db, segment, page);
  await assert.rejects(publish(db, segment, { ...page, checksum: 'c'.repeat(64) }), { code: 'archive_retry_source_changed' });
  db.rows.messages[0].encrypted_content = 'changed-ciphertext';
  await assert.rejects(publish(db, segment, page), { code: 'archive_source_changed' });
  db.rows.messages[0].encrypted_content = 'cipher-1';
  await assert.rejects(publish(db, segment, page, 402), { code: 'archive_copy_lease_expired' });
  db.rows.chats[0].storage_state = 'deleting';
  await assert.rejects(publish(db, segment, page), { code: 'chat_unavailable' });
  assert.equal(db.rows.chat_message_archive_pages[0].published, false);
});

// contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages,storage.cold.atomic-eligible-graphs
test('page position index must match every canonical source position', async () => {
  const db = fakeDatabase(seed());
  const segment = await claim(db);
  const page = pageData(segment);
  await assert.rejects(prepare(db, segment, {
    ...page, message_positions: [[1, 'm1'], [3, 'm2']],
  }), { code: 'archive_page_positions_changed' });
  assert.deepEqual(db.rows.chat_message_archive_pages, []);
  await prepare(db, segment, page);
  await assert.rejects(publish(db, segment, {
    ...page, message_positions: [[1, 'm1'], [2, 'other-id']],
  }), { code: 'archive_page_positions_changed' });
  assert.equal(db.rows.chat_message_archive_pages[0].published, false);
});

// contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.compression.incremental-archive
test('verify rejects incomplete, reordered, and concurrently changed source', async () => {
  const db = fakeDatabase(seed());
  const segment = await claim(db);
  const page = pageData(segment);
  await prepare(db, segment, page);
  await assert.rejects(archiveOperation(db, body('verify_segment', {
    segment_id: segment.id, expected_version: segment.version, page_count: 1, now: 102,
  })), { code: 'archive_pages_incomplete' });
  await publish(db, segment, page);
  db.rows.chat_message_archive_pages[0].first_timestamp = 3;
  await assert.rejects(archiveOperation(db, body('verify_segment', {
    segment_id: segment.id, expected_version: segment.version, page_count: 1, now: 103,
  })), { code: 'archive_page_order_invalid' });
  db.rows.chat_message_archive_pages[0].first_timestamp = 1;
  db.rows.messages[1].encrypted_content = 'concurrent-change';
  await assert.rejects(archiveOperation(db, body('verify_segment', {
    segment_id: segment.id, expected_version: segment.version, page_count: 1, now: 103,
  })), { code: 'archive_source_changed' });
  assert.equal(db.rows.chat_message_archive_segments[0].state, 'copying');
});

// contract-test: direct surface=rest_api assertions=storage.rollout.verified-24-hour-buffer
test('activation requires reader proof and initial cohort retains 24-hour rollback copy', async () => {
  const db = fakeDatabase(seed());
  const { segment, page } = await verified(db);
  await assert.rejects(archiveOperation(db, body('activate_segment', {
    segment_id: segment.id, expected_version: segment.version, now: 200,
  })), { code: 'archive_read_rollout_not_verified' });
  Object.assign(db.rows.chat_message_archive_rollout[0], {
    read_enabled: true, compatibility_verified: true, reader_receipt: 'reader-proof',
  });
  await assert.rejects(archiveOperation(db, body('activate_segment', {
    segment_id: segment.id, expected_version: segment.version, now: 200,
  })), { code: 'archive_reader_verification_incomplete' });
  await assert.rejects(recordReaderVerification(db, segment, { ...page, checksum: 'c'.repeat(64) }),
    { code: 'archive_reader_generation_changed' });
  assert.equal(db.rows.chat_message_archive_pages[0].reader_verified, undefined);
  assert.deepEqual(await recordReaderVerification(db, segment, page), {
    page_id: page.id, reader_verified: true,
  });
  const active = await archiveOperation(db, body('activate_segment', {
    segment_id: segment.id, expected_version: segment.version, now: 200,
  }));
  assert.equal(active.source_copy_until, 200 + 86400);
  assert.equal(db.rows.chat_message_archive_pages[0].read_enabled, true);
});

// contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.atomic-eligible-graphs
test('activation defers page overlap above the bounded metadata catalog budget', async () => {
  const db = fakeDatabase(seed());
  const { segment, page } = await verified(db);
  await recordReaderVerification(db, segment, page);
  Object.assign(db.rows.chat_message_archive_rollout[0], {
    read_enabled: true, compatibility_verified: true, reader_receipt: 'reader-proof',
  });
  const olderPages = Array.from({ length: 128 }, (_, index) => ({
    id: `old-page-${index}`, chat_id: CHAT, segment_id: `old-segment-${index}`,
    read_enabled: true, first_timestamp: 1, first_message_id: 'm1',
    last_timestamp: 2, last_message_id: 'm2',
  }));
  db.rows.chat_message_archive_pages.push(...olderPages);
  const activate = () => archiveOperation(db, body('activate_segment', {
    segment_id: segment.id, expected_version: segment.version, now: 200,
  }));
  await assert.rejects(activate(), { code: 'archive_page_overlap_budget_exceeded' });
  assert.equal(db.rows.chat_message_archive_segments[0].state, 'verified');
  assert.equal(db.rows.chat_message_archive_pages[0].read_enabled, false);
  db.rows.chat_message_archive_pages.pop();
  assert.equal((await activate()).state, 'reader_active');
});

// contract-test: direct surface=rest_api assertions=storage.rollout.verified-24-hour-buffer,storage.background.saved-output-retention
test('prune requires rollback expiry and canonical recovery acknowledgement; retry never recounts', async () => {
  const db = fakeDatabase(seed());
  const { segment, page } = await verified(db);
  Object.assign(db.rows.chat_message_archive_rollout[0], {
    read_enabled: true, pruning_enabled: true, compatibility_verified: true,
    reader_receipt: 'reader-proof', validation_receipt: 'validation-proof',
  });
  await recordReaderVerification(db, segment, page);
  const active = await archiveOperation(db, body('activate_segment', {
    segment_id: segment.id, expected_version: segment.version, now: 200,
  }));
  const prune = (now) => archiveOperation(db, body('prune_page', {
    segment_id: active.id, expected_version: active.version, page_id: 'page-1', now,
  }));
  await assert.rejects(prune(200 + 86399), { code: 'archive_rollback_buffer_active' });
  db.rows.chat_completion_recovery_jobs.push({ id: 'job-1', chat_id: CHAT, state: 'LEASED' });
  await assert.rejects(prune(200 + 86400), { code: 'canonical_recovery_acknowledgement_required' });
  db.rows.chat_completion_recovery_jobs[0].state = 'TERMINAL';
  db.rows.chat_recovery_outputs.push({ id: 'output-1', target_chat_id: CHAT, state: 'PREPARING', deleted_at: null });
  await assert.rejects(prune(200 + 86400), { code: 'canonical_recovery_acknowledgement_required' });
  db.rows.chat_recovery_outputs[0].state = 'PENDING';
  await assert.rejects(prune(200 + 86400), { code: 'canonical_recovery_acknowledgement_required' });
  db.rows.chat_recovery_outputs[0].state = 'ACKNOWLEDGED';
  const done = await prune(200 + 86400);
  assert.equal(done.message_count, 2);
  assert.equal(db.rows.messages.length, 0);
  assert.equal(db.rows.chats[0].archived_message_count, 2);
  const retry = await prune(200 + 86401);
  assert.equal(retry.duplicate, true);
  assert.equal(db.rows.chats[0].archived_message_count, 2);
});
