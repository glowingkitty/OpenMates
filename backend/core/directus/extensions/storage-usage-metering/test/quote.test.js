import test from 'node:test';
import assert from 'node:assert/strict';
import { isAuthorized } from '../src/index.js';
import { listPersonalOwnerIds, MeteringError, parseQuoteRows, quoteSql, quoteUsage, uploadBreakdown,
  sumLogicalReferences } from '../src/quote.js';

// contract-test: direct surface=rest_api assertions=billing.storage.logical-usage
test('one logical object is counted once across regions and repeated references', () => {
  const objects = sumLogicalReferences([
    { bucket: 'cold_archives', key: 'message-pages/chat/page', bytes: 318, owner: 'personal:a' },
    { bucket: 'cold_archives', key: 'message-pages/chat/page', bytes: 318, owner: 'personal:a' },
    { bucket: 'chatfiles', key: 'embed-versions/embed/v1', bytes: 91, owner: 'personal:a' },
  ]);
  assert.equal(objects.get('personal:a'), 409);
});

// contract-test: direct surface=rest_api assertions=billing.storage.logical-usage
test('an uploaded object referenced by an archive is paid through legacy upload measurement only', () => {
  const objects = sumLogicalReferences([
    { bucket: 'chatfiles', key: 'uploaded/one', bytes: 120, owner: 'personal:a' },
    { bucket: 'cold_archives', key: 'message-pages/chat/page', bytes: 60, owner: 'personal:a' },
  ], [{ bucket: 'chatfiles', key: 'uploaded/one', owner: 'personal:a' }]);
  assert.equal(objects.get('personal:a'), 60);
});

// contract-test: direct surface=rest_api assertions=billing.storage.logical-usage
test('conflicting size or owner of one bucket and key prevents a quote', () => {
  const first = { bucket: 'cold_archives', key: 'one', bytes: 5, owner: 'personal:a' };
  for (const second of [{ ...first, bytes: 6 }, { ...first, owner: 'team:b' }]) {
    assert.throws(() => sumLogicalReferences([first, second]),
      (error) => error instanceof MeteringError && error.code === 'storage_usage_incomplete');
  }
  assert.throws(() => sumLogicalReferences([first],
    [{ bucket: first.bucket, key: first.key, owner: 'team:b' }]),
  (error) => error instanceof MeteringError && error.code === 'storage_usage_incomplete');
});

// contract-test: direct surface=rest_api assertions=billing.storage.logical-usage
test('SQL includes only canonical reference states, never replica or pending copy rows', () => {
  const sql = quoteSql(['user-a'], ['b'.repeat(64)]);
  for (const fence of [
    'p.read_enabled = true', "s.state IN ('reader_active', 'pruned')",
    "m.state = 'cold'", "o.state = 'PENDING'", "d.archive_state IN ('reader_active', 'pruned')",
    'p.generation = m.active_generation', 'GROUP BY bucket, object_key',
    'upload_owner_id IS NULL',
  ]) assert.ok(sql.includes(fence), fence);
  assert.ok(!sql.includes('payload_verified_regions AS bytes'));
});

// contract-test: direct surface=rest_api assertions=billing.storage.logical-usage
test('archived embed owner metadata conflicts hold the whole quote, including missing fields', () => {
  const sql = quoteSql(['user-a'], []);
  const embedBranch = sql.split("r.owner_kind, r.owner_id, r.owner_hash, 'embed_versions', 5,")[1]
    ?.split('),\nobjects AS')[0];
  assert.ok(embedBranch, 'archived embed reference must be included');
  for (const check of [
    'd.archive_owner_kind = r.owner_kind',
    'd.archive_owner_hash = r.owner_hash',
    'd.archive_hashed_chat_id = e.hashed_chat_id',
    ') IS TRUE',
  ]) assert.ok(embedBranch.includes(check), check);
  assert.ok(!embedBranch.slice(embedBranch.indexOf('WHERE')).includes('archive_owner_'),
    'conflicting metadata must reach the incomplete check, not disappear from the quote');
  assert.ok(sql.includes('bool_or(owner_metadata_valid IS DISTINCT FROM true)'),
    'false or null metadata validation must hold the quote');
});

// contract-test: direct surface=rest_api assertions=billing.storage.logical-usage
test('page, cold manifest, and recovery ownership metadata is checked before billing', () => {
  const sql = quoteSql(['user-a'], ['b'.repeat(64)]);
  for (const predicate of [
    'p.hashed_user_id IS NOT DISTINCT FROM c.hashed_user_id',
    'p.hashed_team_id IS NOT DISTINCT FROM c.hashed_team_id',
    's.hashed_user_id IS NOT DISTINCT FROM c.hashed_user_id',
    's.hashed_team_id IS NOT DISTINCT FROM c.hashed_team_id',
    's.chat_id = c.id::text',
    "s.chat_hash = encode(digest(c.id::text, 'sha256'), 'hex')",
    "m.resource_type = 'chat'",
    "m.hashed_resource_id = encode(digest(c.id::text, 'sha256'), 'hex')",
    'm.hashed_user_id IS NOT DISTINCT FROM c.hashed_user_id',
    'm.hashed_team_id IS NOT DISTINCT FROM c.hashed_team_id',
    'o.root_hashed_team_id IS NOT DISTINCT FROM c.hashed_team_id',
    'c.hashed_team_id IS NOT NULL OR o.hashed_user_id = c.hashed_user_id',
  ]) assert.ok(sql.includes(predicate), predicate);
  assert.equal(sql.split('p.hashed_user_id IS NOT DISTINCT FROM c.hashed_user_id').length - 1, 2,
    'page and oversized references both require the page owner fence');
  assert.ok(sql.includes('bool_or(owner_metadata_valid IS DISTINCT FROM true)'),
    'metadata conflicts and null checks must make the whole quote incomplete');
});

// contract-test: direct surface=rest_api assertions=billing.storage.weekly-quote
test('quote rejects incomplete and malformed totals instead of returning zero', async () => {
  assert.throws(() => parseQuoteRows([{
    owner_kind: 'personal', owner_id: 'user-a', categories: {}, incomplete: true,
  }], 1), (error) => error instanceof MeteringError && error.code === 'storage_usage_incomplete');
  const database = {
    async raw(sql, bindings) {
      assert.ok(sql.includes('GROUP BY bucket, object_key'));
      assert.ok(sql.includes('statement_timestamp()'));
      assert.deepEqual(bindings, ['user-a']);
      return { rows: [{
        owner_kind: 'personal', owner_id: 'user-a', incomplete: false, measurement_at: 1791082800,
        categories: { legacy_uploads: '100', chat_pages: '60', sealed_recovery: '20' },
      }] };
    },
  };
  assert.deepEqual(await quoteUsage(database, { user_ids: ['user-a'] }), [{
    owner_kind: 'personal', owner_id: 'user-a',
    policy_version: 'personal-storage-1gb-3credits-week-v1',
    source_version: 'logical-s3-v1', complete: true, measurement_at: 1791082800,
    categories: { legacy_uploads: 100, chat_pages: 60, sealed_recovery: 20 },
    legacy_upload_bytes: 100, logical_s3_bytes: 80, total_bytes: 180,
  }]);
});

// contract-test: direct surface=rest_api assertions=billing.storage.weekly-quote
test('legacy-only quote reads upload bytes and excludes archive categories', async () => {
  const database = {
    async raw(sql, bindings) {
      assert.ok(sql.includes('FROM requested r'));
      assert.ok(sql.includes('LEFT JOIN upload_files u'));
      assert.ok(sql.includes('statement_timestamp()'));
      assert.ok(!sql.includes('chat_message_archive_pages'));
      assert.deepEqual(bindings, ['user-a']);
      return { rows: [{
        owner_kind: 'personal', owner_id: 'user-a', incomplete: false, measurement_at: 1791082800,
        categories: { legacy_uploads: '100' },
      }] };
    },
  };
  const [quote] = await quoteUsage(database, { user_ids: ['user-a'], legacy_only: true });
  assert.equal(quote.source_version, 'legacy-upload-files-v1');
  assert.equal(quote.measurement_at, 1791082800);
  assert.equal(quote.policy_version, 'legacy-upload-storage-1gb-3credits-week-v1');
  assert.equal(quote.total_bytes, 100);
  assert.equal(quote.logical_s3_bytes, 0);
  await assert.rejects(
    quoteUsage(database, { team_hashes: ['b'.repeat(64)], legacy_only: true }),
    (error) => error instanceof MeteringError && error.code === 'invalid_legacy_owner_scope',
  );
});

// contract-test: direct surface=rest_api assertions=billing.storage.weekly-quote
test('owner discovery keyset pages users with archive-only objects', async () => {
  const database = {
    async raw(sql, bindings) {
      assert.ok(sql.includes('chat_message_archive_pages'));
      assert.ok(sql.includes('cold_archive_manifests'));
      assert.ok(sql.includes('chat_recovery_outputs'));
      assert.ok(sql.includes('closed.closed_at IS NOT NULL'));
      assert.deepEqual(bindings, ['user-a', 2]);
      return { rows: [{ user_id: 'user-b' }] };
    },
  };
  assert.deepEqual(await listPersonalOwnerIds(database, {
    after_user_id: 'user-a', limit: 2,
  }), ['user-b']);
  assert.equal(isAuthorized({ 'x-internal-service-token': 'secret' }, 'secret'), true);
  assert.equal(isAuthorized({}, 'secret'), false);
});

// contract-test: supporting surface=rest_api assertions=billing.storage.disclosures
test('settings upload breakdown is a bounded SQL aggregate and fails closed', async () => {
  const database = {
    async raw(sql, bindings) {
      assert.ok(sql.includes('FROM upload_files WHERE user_id = ?'));
      assert.ok(sql.includes('GROUP BY category'));
      assert.ok(!sql.includes('SELECT content_type, file_size_bytes'));
      assert.deepEqual(bindings, ['user-a']);
      return { rows: [
        { category: 'images', file_count: '2', bytes_used: '42', incomplete: false },
        { category: 'other', file_count: '1', bytes_used: '3', incomplete: false },
      ] };
    },
  };
  assert.deepEqual(await uploadBreakdown(database, { user_id: 'user-a' }), [
    { category: 'images', file_count: 2, bytes_used: 42 },
    { category: 'other', file_count: 1, bytes_used: 3 },
  ]);
  database.raw = async () => ({ rows: [
    { category: 'images', file_count: '2', bytes_used: '42', incomplete: true },
  ] });
  await assert.rejects(uploadBreakdown(database, { user_id: 'user-a' }),
    (error) => error instanceof MeteringError && error.code === 'storage_usage_incomplete');
});

// contract-test: direct surface=rest_api assertions=billing.storage.team-policy-gate
test('Team usage is attributed separately with its own weekly billing policy', async () => {
  const teamHash = 'b'.repeat(64);
  const database = {
    async raw(sql, bindings) {
      assert.ok(sql.includes("r.owner_kind = 'team' AND c.hashed_team_id = r.owner_hash"));
      assert.deepEqual(bindings, [teamHash]);
      return { rows: [{
        owner_kind: 'team', owner_id: teamHash, incomplete: false, measurement_at: 1791082800,
        categories: { chat_pages: '90' },
      }] };
    },
  };
  const [quote] = await quoteUsage(database, { team_hashes: [teamHash] });
  assert.equal(quote.owner_kind, 'team');
  assert.equal(quote.policy_version, 'team-storage-1gb-3credits-week-v1');
  assert.equal(quote.total_bytes, 90);
});
