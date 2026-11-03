import test from 'node:test';
import assert from 'node:assert/strict';
import endpoint from '../src/index.js';
import { readScopedEmbedPage } from '../src/scoped-reads.js';

const CHAT = 'a'.repeat(64);
const OWNER = 'b'.repeat(64);
const EMBED = 'c'.repeat(64);
const OTHER = 'd'.repeat(64);
const id = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
function database(seed) {
  return (table) => {
    const groups = [];
    const order = [];
    let columns;
    let limit;
    const query = {
      select(value) { columns = value; return this; },
      where(...args) { return this.andWhere(...args); },
      andWhere(field, operator, value) {
        if (typeof field === 'function') {
          const nested = database({ [table]: seed[table] })(table);
          field.call(nested);
          groups.push(['and', nested.matches]);
        } else {
          const expected = arguments.length === 2 ? operator : value;
          const op = arguments.length === 2 ? '=' : operator;
          assert.ok(['=', '<', '>'].includes(op), `Unexpected SQL operator ${op}`);
          groups.push(['and', (row) => op === '<' ? row[field] < expected : op === '>' ? row[field] > expected : row[field] === expected]);
        }
        return this;
      },
      orWhere(callback) {
        const nested = database({ [table]: seed[table] })(table);
        callback.call(nested);
        groups.push(['or', nested.matches]);
        return this;
      },
      whereIn(field, values) { groups.push(['and', (row) => values.includes(row[field])]); return this; },
      orderBy(field, direction) { order.push([field, direction]); return this; },
      limit(value) { limit = value; return this; },
      matches(row) {
        return groups.reduce((result, [op, predicate], i) => i === 0 ? predicate(row)
          : op === 'or' ? result || predicate(row) : result && predicate(row), true);
      },
      then(resolve, reject) {
        assert.ok(limit <= 201);
        const rows = (seed[table] || []).filter(query.matches).sort((a, b) => {
          for (const [field, direction] of order) {
            if (a[field] !== b[field]) return (a[field] < b[field] ? -1 : 1) * (direction === 'desc' ? -1 : 1);
          }
          return 0;
        }).slice(0, limit).map((row) => Object.fromEntries(columns.filter((key) => key in row).map((key) => [key, row[key]])));
        return Promise.resolve(rows).then(resolve, reject);
      },
    };
    return query;
  };
}

// contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
test('native UUID embed continuation crosses tied timestamps with fixed scope and count', async () => {
  const rows = Array.from({ length: 75 }, (_, n) => ({ id: id(n), created_at: n < 65 ? 12 : 13,
    hashed_chat_id: CHAT, encrypted_content: `cipher-${n}`, forbidden_column: 'private' }));
  rows.push({ id: id(999), created_at: 10, hashed_chat_id: OTHER });
  const db = database({ embeds: rows });
  const seen = [];
  let cursor = { before_created_at: 13, before_id: id(75) };
  while (true) {
    const page = await readScopedEmbedPage(db, { operation: 'embed_window', hashed_chat_id: CHAT, ...cursor });
    assert.ok(page.length <= 31);
    assert.ok(page.every((row) => row.hashed_chat_id === CHAT && !('forbidden_column' in row)));
    const kept = page.slice(0, 30);
    seen.push(...kept.map((row) => row.id));
    if (page.length <= 30) break;
    const last = kept.at(-1);
    cursor = { before_created_at: last.created_at, before_id: last.id };
  }
  assert.deepEqual(seen, rows.slice(0, 75).sort((a, b) => b.created_at - a.created_at || b.id.localeCompare(a.id)).map((row) => row.id));
  assert.equal(new Set(seen).size, 75);
});

// contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
test('embed change pages ascend by updated_at then embed_id across tied seconds', async () => {
  const rows = Array.from({ length: 70 }, (_, n) => ({ id: id(n), embed_id: `embed-${String(n).padStart(3, '0')}`,
    updated_at: n < 40 ? 50 : 60 + n, hashed_chat_id: CHAT, encrypted_content: `cipher-${n}`, forbidden_column: 'private' }));
  rows.push({ id: id(900), embed_id: 'embed-old', updated_at: 5, hashed_chat_id: CHAT });
  rows.push({ id: id(901), embed_id: 'embed-legacy', updated_at: null, hashed_chat_id: CHAT });
  rows.push({ id: id(902), embed_id: 'embed-other', updated_at: 99, hashed_chat_id: OTHER });
  const db = database({ embeds: rows });
  const seen = [];
  let cursor = { after_updated_at: 10, after_embed_id: null };
  for (;;) {
    const page = await readScopedEmbedPage(db, { operation: 'embed_changes', hashed_chat_id: CHAT, limit: 31, ...cursor });
    assert.ok(page.every((row) => row.hashed_chat_id === CHAT && !('forbidden_column' in row)));
    const kept = page.slice(0, 30);
    seen.push(...kept.map((row) => row.embed_id));
    if (page.length <= 30) break;
    const last = kept.at(-1);
    cursor = { after_updated_at: last.updated_at, after_embed_id: last.embed_id };
  }
  assert.deepEqual(seen, rows.slice(0, 70).map((row) => row.embed_id));
  const bad = [
    { operation: 'embed_changes', hashed_chat_id: CHAT, after_updated_at: -1, after_embed_id: null, limit: 5 },
    { operation: 'embed_changes', hashed_chat_id: CHAT, after_updated_at: 1, after_embed_id: '', limit: 5 },
    { operation: 'embed_changes', hashed_chat_id: CHAT, after_updated_at: 1, after_embed_id: null, limit: 102 },
    { operation: 'embed_changes', hashed_chat_id: 'forged', after_updated_at: 1, after_embed_id: null, limit: 5 },
    { operation: 'embed_changes', hashed_chat_id: CHAT, after_updated_at: 1, limit: 5 },
  ];
  for (const body of bad) {
    await assert.rejects(readScopedEmbedPage(db, body), { status: 400, code: 'invalid_scoped_read' });
  }
});

// contract-test: supporting surface=rest_api assertions=storage.cold.discoverable-bounded
test('embed and key continuations accept a bounded larger limit and reject out-of-range ones', async () => {
  const embeds = Array.from({ length: 150 }, (_, n) => ({ id: id(n), created_at: 12, hashed_chat_id: CHAT }));
  const base = { operation: 'embed_window', hashed_chat_id: CHAT, before_created_at: 13, before_id: id(999) };
  assert.equal((await readScopedEmbedPage(database({ embeds }), base)).length, 31);
  assert.equal((await readScopedEmbedPage(database({ embeds }), { ...base, limit: 101 })).length, 101);
  for (const limit of [1, 102, 1.5, '50']) {
    await assert.rejects(readScopedEmbedPage(database({ embeds }), { ...base, limit }), { status: 400, code: 'invalid_scoped_read' });
  }
  const keys = Array.from({ length: 250 }, (_, n) => ({ id: id(n + 1), hashed_embed_id: EMBED, key_type: 'chat', hashed_chat_id: CHAT }));
  const keyBody = { operation: 'embed_key_window', hashed_chat_id: CHAT, hashed_user_id: null,
    hashed_embed_ids: [EMBED], include_master_keys: false, after_id: id(0) };
  assert.equal((await readScopedEmbedPage(database({ embed_keys: keys }), keyBody)).length, 61);
  assert.equal((await readScopedEmbedPage(database({ embed_keys: keys }), { ...keyBody, limit: 201 })).length, 201);
  await assert.rejects(readScopedEmbedPage(database({ embed_keys: keys }), { ...keyBody, limit: 202 }), { status: 400 });
});

// contract-test: supporting surface=rest_api assertions=storage.cold.shared-team-authorized
test('wrapper continuation restricts selected hashes, chat keys and actor master keys', async () => {
  const rows = [
    { id: id(1), hashed_embed_id: EMBED, key_type: 'chat', hashed_chat_id: CHAT },
    { id: id(2), hashed_embed_id: EMBED, key_type: 'master', hashed_user_id: OWNER },
    { id: id(3), hashed_embed_id: EMBED, key_type: 'chat', hashed_chat_id: OTHER },
    { id: id(4), hashed_embed_id: EMBED, key_type: 'master', hashed_user_id: OTHER },
    { id: id(5), hashed_embed_id: OTHER, key_type: 'chat', hashed_chat_id: CHAT },
  ];
  const body = { operation: 'embed_key_window', hashed_chat_id: CHAT, hashed_user_id: OWNER,
    hashed_embed_ids: [EMBED], include_master_keys: true, after_id: id(0) };
  assert.deepEqual((await readScopedEmbedPage(database({ embed_keys: rows }), body)).map((row) => row.id), [id(1), id(2)]);
  assert.deepEqual((await readScopedEmbedPage(database({ embed_keys: rows }), {
    ...body, include_master_keys: false, hashed_user_id: null,
  })).map((row) => row.id), [id(1)]);
});

// contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete
test('complete reads use typed UUID ordering and reject mixed scopes', async () => {
  const rows = Array.from({ length: 42 }, (_, n) => ({ id: id(n), hashed_chat_id: CHAT }));
  assert.deepEqual((await readScopedEmbedPage(database({ embeds: rows }), {
    operation: 'complete_embeds', hashed_chat_id: CHAT, after_id: id(19),
  })).map((row) => row.id), rows.slice(20, 40).map((row) => row.id));
});

// contract-test: supporting surface=rest_api assertions=storage.cold.shared-team-authorized
test('malformed or extra query shapes fail before executing SQL', async () => {
  const base = { operation: 'embed_window', hashed_chat_id: CHAT, before_created_at: 12, before_id: id(2) };
  const bad = [{ ...base, table: 'users' }, { ...base, hashed_chat_id: '' }, { ...base, before_id: 'forged' },
    { ...base, before_created_at: -1 }, { ...base, before_created_at: 1.5 },
    { operation: 'complete_embeds', hashed_chat_id: CHAT, hashed_embed_ids: [EMBED], after_id: id(1) },
    { operation: 'complete_embed_keys', hashed_chat_id: CHAT, key_type: 'master', after_id: id(1) },
    { operation: 'complete_embeds', hashed_embed_ids: Array(21).fill(EMBED), after_id: id(1) },
    { operation: 'complete_embeds', hashed_embed_ids: [EMBED, EMBED], after_id: id(1) },
    { operation: 'arbitrary' }];
  for (const body of bad) {
    await assert.rejects(readScopedEmbedPage(database({}), body), { status: 400, code: 'invalid_scoped_read' });
  }
});

// contract-test: supporting surface=rest_api assertions=storage.cold.shared-team-authorized
test('scoped endpoint denies absent and incorrect internal tokens without querying', async () => {
  const handlers = new Map();
  endpoint.handler({ get() {}, post(path, handler) { handlers.set(path, handler); } }, {
    database() { throw new Error('Unauthorized database access'); }, env: { INTERNAL_API_SHARED_TOKEN: 'unit-token' }, logger: { error() {} },
  });
  for (const headers of [{}, { 'x-internal-service-token': 'wrong-token' }]) {
    const response = { status(code) { this.code = code; return this; }, json(body) { this.body = body; return this; } };
    await handlers.get('/scoped-read')({ headers }, response);
    assert.equal(response.code, 401);
    assert.equal(response.body.error.code, 'internal_auth_failed');
  }
});
