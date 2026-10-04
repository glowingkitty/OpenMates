import test from 'node:test';
import assert from 'node:assert/strict';
import { selectWindowLocators } from '../src/locator-window.js';

function page(id, positions) {
  return {
    id, message_count: positions.length, message_positions: positions,
    first_timestamp: positions[0][0], first_message_id: positions[0][1],
    last_timestamp: positions.at(-1)[0], last_message_id: positions.at(-1)[1],
  };
}

function catalog(pages, direction) {
  const before = direction === 'before';
  const edge = row => before
    ? [row.last_timestamp, row.last_message_id, row.id]
    : [row.first_timestamp, row.first_message_id, row.id];
  const compare = (a, b) => a[0] - b[0] || a[1].localeCompare(b[1]) || a[2].localeCompare(b[2]);
  const sorted = [...pages].sort((a, b) => (before ? -1 : 1) * compare(edge(a), edge(b)));
  const calls = [];
  return {
    calls,
    fetchChunk: async (cursor, limit) => {
      calls.push({ cursor, limit });
      return sorted.filter(row => !cursor || (before ? compare(edge(row), cursor) < 0
        : compare(edge(row), cursor) > 0)).slice(0, limit);
    },
  };
}

// contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.independent-message-pages
test('sparse wide pages cannot hide a better locator in a later catalog chunk', async () => {
  const broad = Array.from({ length: 32 }, (_, index) =>
    page(`wide-${String(index).padStart(2, '0')}`, [[index + 1, `low-${index}`], [1000 + index, `high-${index}`]]));
  const source = catalog([...broad, page('later', [[49, 'wanted']])], 'before');
  const result = await selectWindowLocators({ fetchChunk: source.fetchChunk,
    direction: 'before', cursor: [50, 'cursor'], limit: 1 });
  assert.deepEqual(result.locators.map(item => item.message_id), ['wanted']);
  assert.equal(result.has_more, true);
  assert.equal(source.calls.length, 2);
  assert.equal(source.calls[0].limit, 32);
});

// contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.independent-message-pages
test('identical timestamps use exact message ID order in both directions', async () => {
  const pages = [page('one', [[10, 'a'], [10, 'c']]), page('two', [[10, 'b'], [10, 'd']])];
  const before = catalog(pages, 'before');
  const older = await selectWindowLocators({ fetchChunk: before.fetchChunk,
    direction: 'before', cursor: [10, 'd'], limit: 2 });
  assert.deepEqual(older.locators.map(item => item.message_id), ['c', 'b']);
  const after = catalog(pages, 'after');
  const newer = await selectWindowLocators({ fetchChunk: after.fetchChunk,
    direction: 'after', cursor: [10, 'a'], limit: 2 });
  assert.deepEqual(newer.locators.map(item => item.message_id), ['b', 'c']);
});

// contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.integrity.observable-reconcilable
test('ambiguous catalog exceeding 256 metadata pages fails instead of truncating history', async () => {
  const pages = Array.from({ length: 257 }, (_, index) =>
    page(`wide-${String(index).padStart(3, '0')}`,
      [[index + 1, `low-${index}`], [1000 + index, `high-${index}`]]));
  const source = catalog(pages, 'before');
  await assert.rejects(selectWindowLocators({ fetchChunk: source.fetchChunk,
    direction: 'before', cursor: [500, 'cursor'], limit: 1 }),
  { code: 'archive_locator_metadata_budget_exceeded' });
  assert.equal(source.calls.length, 8);
});
