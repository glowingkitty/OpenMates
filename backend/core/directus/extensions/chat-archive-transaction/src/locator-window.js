/* Bounded metadata selection for encrypted archive windows. */
import { ArchiveProtocolError } from './operations.js';

const CHUNK_SIZE = 32;
const MAX_CATALOG_PAGES = 256;

function fail(code) { throw new ArchiveProtocolError(code); }
function position(timestamp, id) { return [Number(timestamp), String(id)]; }
function compare(left, right) {
  return left[0] - right[0] || (left[1] < right[1] ? -1 : left[1] > right[1] ? 1 : 0);
}

export async function selectWindowLocators({ fetchChunk, direction, cursor, limit }) {
  if (!['before', 'after'].includes(direction) || !Number.isSafeInteger(limit) || limit < 1 || limit > 20)
    fail('invalid_window_direction');
  const before = direction === 'before';
  let catalogCursor = null;
  let scanned = 0;
  let selected = [];
  while (scanned < MAX_CATALOG_PAGES) {
    const chunk = await fetchChunk(catalogCursor, Math.min(CHUNK_SIZE, MAX_CATALOG_PAGES - scanned));
    if (!Array.isArray(chunk) || chunk.length > CHUNK_SIZE) fail('archive_locator_catalog_failed');
    if (!chunk.length) break;
    scanned += chunk.length;
    for (const page of chunk) {
      let entries;
      try {
        entries = typeof page.message_positions === 'string'
          ? JSON.parse(page.message_positions) : page.message_positions;
      } catch { fail('archive_page_position_index_invalid'); }
      if (!Array.isArray(entries) || entries.length < 1 || entries.length > 20
        || entries.length !== Number(page.message_count)
        || entries.some(item => !Array.isArray(item) || item.length !== 2
          || !Number.isSafeInteger(Number(item[0])) || typeof item[1] !== 'string' || !item[1]))
        fail('archive_page_position_index_invalid');
      if (compare(position(...entries[0]), position(page.first_timestamp, page.first_message_id)) !== 0
        || compare(position(...entries.at(-1)), position(page.last_timestamp, page.last_message_id)) !== 0)
        fail('archive_page_position_index_invalid');
      for (let index = 1; index < entries.length; index++) {
        if (compare(position(...entries[index - 1]), position(...entries[index])) >= 0)
          fail('archive_page_position_index_invalid');
      }
      for (const [timestamp, messageId] of entries) {
        const loc = { page_id: page.id, created_at: Number(timestamp), message_id: messageId };
        if (!cursor || (before ? compare(position(loc.created_at, messageId), cursor) < 0
          : compare(position(loc.created_at, messageId), cursor) > 0)) selected.push(loc);
      }
    }
    selected.sort((left, right) => {
      const order = compare(position(left.created_at, left.message_id), position(right.created_at, right.message_id))
        || left.page_id.localeCompare(right.page_id);
      return before ? -order : order;
    });
    selected = selected.slice(0, limit + 1);
    const last = chunk.at(-1);
    catalogCursor = before
      ? [Number(last.last_timestamp), String(last.last_message_id), String(last.id)]
      : [Number(last.first_timestamp), String(last.first_message_id), String(last.id)];
    if (chunk.length < CHUNK_SIZE) break;
    if (selected.length >= limit + 1) {
      const threshold = position(selected[limit].created_at, selected[limit].message_id);
      if (before ? compare(catalogCursor, threshold) < 0 : compare(catalogCursor, threshold) > 0) break;
    }
  }
  if (scanned === MAX_CATALOG_PAGES && selected.length < limit + 1) fail('archive_locator_metadata_budget_exceeded');
  if (scanned === MAX_CATALOG_PAGES && selected.length >= limit + 1) {
    const threshold = position(selected[limit].created_at, selected[limit].message_id);
    if (!(before ? compare(catalogCursor, threshold) < 0 : compare(catalogCursor, threshold) > 0))
      fail('archive_locator_metadata_budget_exceeded');
  }
  const locators = selected.slice(0, limit);
  if (new Set(locators.map(item => item.message_id)).size !== locators.length)
    fail('archive_locator_duplicate_identity');
  return { locators, has_more: selected.length > limit, scanned_pages: scanned };
}
