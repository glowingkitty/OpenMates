import test from 'node:test';
import assert from 'node:assert/strict';

import { policyBoundary, policyCandidates } from '../src/warm-policy.js';

function message(number, bytes = 2, chatId = 'chat-1') {
  return {
    chat_id: chatId, client_message_id: `m-${String(number).padStart(4, '0')}`,
    created_at: number, encrypted_content: 'x'.repeat(bytes), encrypted_thinking_content: '',
  };
}

function fakeTransaction(seed) {
  const limitsSeen = [];
  const trx = (table) => {
    const predicates = [];
    const ordering = [];
    let projection = null;
    let count = false;
    const query = {
      where(values, op, operand) {
        if (typeof values === 'function') {
          const alternatives = [];
          const group = {
            where(field, value) { alternatives.push(row => row[field] === value); return group; },
            orWhere(field, value) { alternatives.push(row => row[field] === value); return group; },
          };
          values.call(group);
          predicates.push(row => alternatives.some(predicate => predicate(row)));
        } else if (typeof values === 'object') {
          predicates.push(row => Object.entries(values).every(([field, value]) => row[field] === value));
        } else {
          predicates.push(row => op === '>' ? row[values] > operand : row[values] === op);
        }
        return query;
      },
      whereIn(field, values) { predicates.push(row => values.includes(row[field])); return query; },
      whereNull(field) { predicates.push(row => row[field] == null); return query; },
      whereRaw(sql, args = []) {
        if (sql.startsWith('(created_at, client_message_id)')) {
          predicates.push(row => {
            const left = [row.created_at, row.client_message_id];
            const compare = left[0] - args[0] || left[1].localeCompare(args[1]);
            return sql.includes('<=') ? compare <= 0 : compare > 0;
          });
        } else if (sql.includes('COALESCE(is_sub_chat')) {
          predicates.push(row => !row.is_sub_chat);
        } else if (sql.includes('storage_state')) {
          predicates.push(row => row.storage_state == null || row.storage_state === 'hot');
        } else if (sql.includes('last_edited_overall_timestamp')) {
          predicates.push(row => {
            const activity = row.last_edited_overall_timestamp || row.updated_at || 0;
            return activity > args[0] || (activity === args[0] && row.id > args[1]);
          });
        } else if (sql.includes('NOT EXISTS (SELECT 1 FROM chat_message_archive_pages')) {
          predicates.push(row => !(seed.chat_message_archive_pages || []).some(page =>
            page.chat_id === row.chat_id && page.message_ids.includes(row.client_message_id)));
        } else throw new Error(`unsupported whereRaw ${sql}`);
        return query;
      },
      select(...fields) { projection = fields.flat(); return query; },
      count() { count = true; return query; },
      orderBy(field, direction = 'asc') { ordering.push([field, direction]); return query; },
      limit(value) { limitsSeen.push({ table, value }); query._limit = value; return query; },
      first() { return Promise.resolve(evaluate()[0]); },
      then(resolve, reject) { return Promise.resolve(evaluate()).then(resolve, reject); },
    };
    function evaluate() {
      let rows = (seed[table] || []).filter(row => predicates.every(predicate => predicate(row)));
      if (count) return [{ count: rows.length }];
      if (projection?.some(field => field?.sql?.includes('COUNT(*)::bigint'))) {
        return [{ message_count: rows.length, cipher_bytes: rows.reduce((sum, row) => sum
          + Buffer.byteLength(row.encrypted_content || '')
          + Buffer.byteLength(row.encrypted_thinking_content || ''), 0) }];
      }
      rows = [...rows].sort((a, b) => {
        for (const [field, direction] of ordering) {
          const comparison = a[field] < b[field] ? -1 : a[field] > b[field] ? 1 : 0;
          if (comparison) return direction === 'desc' ? -comparison : comparison;
        }
        return 0;
      });
      if (query._limit !== undefined) rows = rows.slice(0, query._limit);
      if (table === 'messages' && projection) rows = rows.map(row => ({
        client_message_id: row.client_message_id, created_at: row.created_at,
        has_ciphertext: Boolean(row.encrypted_content),
        cipher_prefix: row.encrypted_content?.slice(0, 9),
        cipher_bytes: Buffer.byteLength(row.encrypted_content || '')
          + Buffer.byteLength(row.encrypted_thinking_content || ''),
      }));
      return rows;
    }
    return query;
  };
  trx.raw = (sql) => ({ sql });
  return { trx, limitsSeen };
}

function seed(messages, chat = {}) {
  return {
    chats: [{ id: 'chat-1', hashed_user_id: 'owner', hashed_team_id: null, storage_state: 'hot',
      last_edited_overall_timestamp: 40 * 86400, ...chat }],
    messages, chat_turn_preflights: [], chat_completion_recovery_jobs: [],
    chat_recovery_outputs: [], chat_message_archive_segments: [], chat_message_archive_pages: [],
  };
}

// contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail
test('count bound selects one stable prefix using at most 101 newest and 1000 oldest rows', async () => {
  const rows = seed(Array.from({ length: 101 }, (_, number) => message(number)));
  const { trx, limitsSeen } = fakeTransaction(rows);
  const decision = await policyBoundary(trx, rows.chats[0], {}, 40 * 86400);
  assert.equal(decision.eligible, true);
  assert.equal(decision.reason, 'message_count_limit');
  assert.equal(decision.end_message_id, 'm-0000');
  assert.equal(decision.message_count, 1);
  assert.equal(decision.policy_id.length, 64);
  assert.deepEqual(limitsSeen.filter(item => item.table === 'messages').map(item => item.value), [101, 1000]);
});

// contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail
test('ciphertext byte bound counts stored body and thinking bytes', async () => {
  const original = process.env.CHAT_WARM_ENCRYPTED_BYTES_PER_CHAT;
  process.env.CHAT_WARM_ENCRYPTED_BYTES_PER_CHAT = '8';
  try {
    const rows = seed([message(1, 2), message(2, 2), message(3, 2)]);
    rows.messages.forEach(row => { row.encrypted_thinking_content = 'yy'; });
    const decision = await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400);
    assert.equal(decision.reason, 'ciphertext_byte_limit');
    assert.equal(decision.end_message_id, 'm-0001');
  } finally {
    if (original === undefined) delete process.env.CHAT_WARM_ENCRYPTED_BYTES_PER_CHAT;
    else process.env.CHAT_WARM_ENCRYPTED_BYTES_PER_CHAT = original;
  }
});

// contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail,storage.background.complete-sealed-recovery
test('pending recovery and active preflight defer the whole chat', async () => {
  const rows = seed([message(1)]);
  for (const state of ['PREPARING', 'PENDING']) {
    for (const field of ['target_chat_id', 'root_chat_id']) {
      rows.chat_recovery_outputs = [{ [field]: 'chat-1', state, deleted_at: null }];
      assert.equal((await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400)).reason,
        'pending_recovery_output');
    }
  }
  rows.chat_recovery_outputs = [{ target_chat_id: 'other', root_chat_id: 'other', state: 'PREPARING' }];
  assert.notEqual((await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400)).reason,
    'pending_recovery_output');
  rows.chat_recovery_outputs = [];
  rows.chat_turn_preflights.push({ chat_id: 'chat-1', state: 'RUNNING' });
  assert.equal((await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400)).reason,
    'active_preflight');
});

// contract-test: supporting surface=rest_api assertions=storage.subchats.durable-before-archive
test('child requires durable delivery, parent consumption, canonical ack and key wrapper', async () => {
  const rows = seed([message(1)], { is_sub_chat: true, parent_id: 'parent' });
  assert.equal((await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400)).reason,
    'child_durability_or_synthesis_pending');
  Object.assign(rows.chats[0], {
    child_result_delivered_at: 1, child_parent_consumed_at: 2,
    child_canonical_acknowledged_at: 3, encrypted_chat_key: 'wrapped',
  });
  const decision = await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400);
  assert.equal(decision.reason, 'completed_child');
  assert.equal(decision.end_message_id, 'm-0001');
});

// contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail
test('pinned and shared old chats use the same inactivity boundary', async () => {
  const rows = seed([message(1), message(2)], {
    pinned: true, is_shared: true, last_edited_overall_timestamp: 1,
  });
  const decision = await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400);
  assert.equal(decision.reason, 'inactive');
  assert.equal(decision.end_message_id, 'm-0002');
});

// contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail,storage.cold.atomic-eligible-graphs
test('warm policy selects restored old hot rows while excluding rows still represented by pages', async () => {
  const rows = seed([message(1), message(2), message(3)], { last_edited_overall_timestamp: 1 });
  rows.chat_message_archive_pages.push({ chat_id: 'chat-1', message_ids: ['m-0002'] });
  const decision = await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400);
  assert.equal(decision.eligible, true);
  assert.deepEqual(decision.source_message_ids, ['m-0001', 'm-0003']);
  assert.equal(decision.end_message_id, 'm-0003');
});

// contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail,storage.cold.rehydrate-on-mutation
test('restored same-boundary hot prefix gets a new policy identity after page retirement', async () => {
  const rows = seed([message(1), message(2)], { last_edited_overall_timestamp: 1, archive_mutation_v: 0 });
  const first = await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400);
  assert.equal(first.eligible, true);
  assert.deepEqual(first.source_message_ids, ['m-0001', 'm-0002']);
  rows.chats[0].archive_mutation_v = 1;
  const second = await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400);
  assert.equal(second.end_message_id, first.end_message_id);
  assert.deepEqual(second.source_message_ids, first.source_message_ids);
  assert.notEqual(second.policy_id, first.policy_id);
  assert.equal((await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], first, 40 * 86400)).reason,
    'warm_policy_identity_changed');
});

// contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail,storage.cold.atomic-eligible-graphs
test('same boundary with changed exact source IDs has a different policy identity', async () => {
  const rows = seed([message(1), message(2)], { last_edited_overall_timestamp: 1, archive_mutation_v: 0 });
  const first = await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400);
  rows.messages[0].client_message_id = 'replacement';
  const second = await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400);
  assert.equal(second.end_message_id, first.end_message_id);
  assert.notEqual(second.policy_id, first.policy_id);
});

// contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail
test('policy identity and end are rechecked inside transaction', async () => {
  const rows = seed(Array.from({ length: 101 }, (_, number) => message(number)));
  const decision = await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400);
  const replay = await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], decision, 40 * 86400);
  assert.deepEqual(replay, decision);
  assert.equal((await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {
    ...decision, end_message_id: 'wrong',
  }, 40 * 86400)).reason, 'warm_policy_boundary_changed');
});

// contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail
test('Vault working ciphertext is never admitted as a canonical archive prefix', async () => {
  const rows = seed([message(1)]);
  rows.chats[0].last_edited_overall_timestamp = 1;
  rows.messages[0].encrypted_content = 'vault:v2:working-only';
  const decision = await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400);
  assert.equal(decision.reason, 'unsupported_canonical_ciphertext');
});

// contract-test: direct surface=rest_api assertions=storage.warm.bounded-chat-tail
test('Team chat with no user owner ranks only against newer chats in its Team', async () => {
  const original = process.env.CHAT_WARM_RECENT_MAIN_COUNT;
  process.env.CHAT_WARM_RECENT_MAIN_COUNT = '1';
  try {
    const rows = seed([message(1)], { hashed_user_id: null, hashed_team_id: 'team-a' });
    rows.chats.push({ id: 'personal-newer', hashed_user_id: 'owner', hashed_team_id: null,
      storage_state: 'hot', last_edited_overall_timestamp: 40 * 86400 + 2 });
    rows.chats.push({ id: 'other-team-newer', hashed_user_id: null, hashed_team_id: 'team-b',
      storage_state: 'hot', last_edited_overall_timestamp: 40 * 86400 + 2 });
    assert.equal((await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400)).reason,
      'within_warm_limits');
    rows.chats.push({ id: 'same-team-newer', hashed_user_id: null, hashed_team_id: 'team-a',
      storage_state: 'hot', last_edited_overall_timestamp: 40 * 86400 + 2 });
    const decision = await policyBoundary(fakeTransaction(rows).trx, rows.chats[0], {}, 40 * 86400);
    assert.equal(decision.eligible, true);
    assert.equal(decision.reason, 'outside_recent_main');
    assert.deepEqual(decision.source_message_ids, ['m-0001']);
  } finally {
    if (original === undefined) delete process.env.CHAT_WARM_RECENT_MAIN_COUNT;
    else process.env.CHAT_WARM_RECENT_MAIN_COUNT = original;
  }
});

// contract-test: supporting surface=rest_api assertions=storage.warm.bounded-chat-tail
test('candidate sweep advances by scanned keyset and caps SQL batch', async () => {
  let observed;
  const trx = {
    raw: async (sql, params) => {
      observed = { sql, params };
      return { rows: [{ chat_ids: ['chat-10'], next_cursor: 'chat-999', scanned_count: 1000 }] };
    },
  };
  const candidates = await policyCandidates(trx, 40 * 86400, { afterChatId: 'chat-1', limit: 2000 });
  assert.deepEqual(candidates, {
    chat_ids: ['chat-10'], next_cursor: 'chat-999', scanned_count: 1000,
  });
  assert.equal(observed.params[2], 1000);
  assert.match(observed.sql, /ORDER BY c\.id LIMIT \?/);
  assert.match(observed.sql, /SELECT id FROM page ORDER BY id DESC LIMIT 1/);
  assert.doesNotMatch(observed.sql, /SELECT m\.encrypted_content/);
  assert.match(observed.sql, /p\.hashed_team_id IS NOT NULL AND newer\.hashed_team_id = p\.hashed_team_id/);
});
