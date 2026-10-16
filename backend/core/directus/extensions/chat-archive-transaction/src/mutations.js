/* Atomic bounded promotion of one archived ciphertext page before mutation. */
import { ArchiveProtocolError, checksum, stable } from './operations.js';

const PAGES = 'chat_message_archive_pages';
const SEGMENTS = 'chat_message_archive_segments';
const MAX_SOURCE_BYTES = 2 * 1024 * 1024 + 8192;

function requireState(condition, code, status = 409) {
  if (!condition) throw new ArchiveProtocolError(code, status);
}

const ownerOf = row => row?.hashed_team_id || row?.hashed_user_id || null;

async function requireMutationOwner(trx, chat, data) {
  requireState(ownerOf(chat) === data.expected_owner_hash, 'archive_authority_changed');
  const actorHash = data.expected_actor_user_hash || data.expected_owner_hash;
  requireState(typeof actorHash === 'string' && actorHash.length > 0, 'invalid_archive_mutation_actor', 400);
  if (!chat.hashed_team_id) {
    requireState(chat.hashed_user_id === actorHash, 'archive_authority_changed');
    return;
  }
  requireState(typeof data.expected_actor_user_hash === 'string' && data.expected_actor_user_hash.length > 0,
    'invalid_archive_mutation_actor', 400);
  const member = await trx('team_memberships').where({ hashed_team_id: chat.hashed_team_id,
    hashed_user_id: actorHash, status: 'active' }).whereIn('role', ['owner', 'admin', 'member']).forShare().first();
  const team = await trx('teams').where({ hashed_team_id: chat.hashed_team_id,
    status: 'active' }).forShare().first();
  requireState(member && team, 'team_write_permission_changed');
}

export async function archiveMutationOperation(database, body) {
  const data = body?.data;
  requireState(['lookup_mutation_page', 'abort_unpublished_page', 'restore_and_retire_page'].includes(body?.operation)
    && data && typeof data === 'object', 'invalid_archive_mutation', 400);
  if (body.operation === 'lookup_mutation_page') {
    requireState(typeof data.chat_id === 'string' && typeof data.message_id === 'string'
      && typeof data.expected_owner_hash === 'string', 'invalid_archive_mutation_identity', 400);
    return database.transaction(async trx => {
      const chat = await trx('chats').where('id', data.chat_id).forUpdate().first();
      requireState(chat && chat.storage_state !== 'deleting', 'chat_unavailable', 404);
      await requireMutationOwner(trx, chat, data);
      const pages = await trx(PAGES).where('chat_id', data.chat_id)
        .whereRaw('message_ids::jsonb @> ?::jsonb', [JSON.stringify([data.message_id])]).limit(2);
      requireState(pages.length <= 1, 'archive_message_has_multiple_pages');
      const page = pages[0] || null;
      const segment = page ? await trx(SEGMENTS).where('id', page.segment_id).first() : null;
      requireState(!page || (segment && segment.chat_id === chat.id
        && ownerOf(page) === ownerOf(chat) && ownerOf(segment) === ownerOf(chat)), 'archive_authority_changed');
      return { page, segment };
    });
  }
  if (body.operation === 'abort_unpublished_page') {
    for (const field of ['chat_id', 'page_id', 'expected_owner_hash', 'expected_page_checksum', 'expected_object_key']) {
      requireState(typeof data[field] === 'string' && data[field], 'invalid_archive_mutation_identity', 400);
    }
    requireState(Number.isSafeInteger(data.now), 'invalid_archive_mutation_time', 400);
    return database.transaction(async trx => {
      const chat = await trx('chats').where('id', data.chat_id).forUpdate().first();
      requireState(chat && chat.storage_state !== 'deleting', 'chat_unavailable', 404);
      await requireMutationOwner(trx, chat, data);
      const page = await trx(PAGES).where({ id: data.page_id, chat_id: chat.id }).forUpdate().first();
      if (!page) return { aborted: false, duplicate: true };
      requireState(ownerOf(page) === ownerOf(chat) && !page.published
        && page.checksum === data.expected_page_checksum && page.object_key === data.expected_object_key
        && stable(page.large_objects) === stable(data.expected_large_objects), 'archive_page_changed');
      const segment = await trx(SEGMENTS).where('id', page.segment_id).forUpdate().first();
      requireState(segment && segment.state === 'copying' && segment.chat_id === chat.id
        && ownerOf(segment) === ownerOf(chat), 'archive_authority_changed');
      requireState(data.now >= Number(segment.lease_until) + 90, 'archive_writer_may_still_upload');
      const [{ count }] = await trx(PAGES).where('segment_id', segment.id).count('* as count');
      requireState(Number(count) === 1, 'archive_segment_has_other_pages');
      await trx(SEGMENTS).where('id', segment.id).update({ state: 'aborted', version: segment.version + 1 });
      requireState(await trx(PAGES).where('id', page.id).delete() === 1, 'archive_page_retirement_failed');
      return { aborted: true, page_id: page.id };
    });
  }
  for (const field of ['chat_id', 'page_id', 'message_id', 'expected_owner_hash', 'expected_page_checksum', 'expected_source_checksum', 'expected_object_key']) {
    requireState(typeof data[field] === 'string' && data[field].length > 0, 'invalid_archive_mutation_identity', 400);
  }
  const rows = data.source_rows;
  requireState(Array.isArray(rows) && rows.length > 0 && rows.length <= 20, 'invalid_archive_mutation_rows', 400);
  requireState(Buffer.byteLength(stable(rows), 'utf8') <= MAX_SOURCE_BYTES, 'archive_mutation_budget_exceeded', 400);
  requireState(checksum(rows) === data.expected_source_checksum, 'archive_mutation_source_checksum_changed');

  return database.transaction(async trx => {
    const chat = await trx('chats').where('id', data.chat_id).forUpdate().first();
    requireState(chat && chat.storage_state !== 'deleting', 'chat_unavailable', 404);
    await requireMutationOwner(trx, chat, data);
    const page = await trx(PAGES).where({ id: data.page_id, chat_id: data.chat_id }).forUpdate().first();
    if (!page) return { promoted: false, duplicate: true };
    requireState(ownerOf(page) === ownerOf(chat) && page.published,
      'archive_page_not_readable');
    requireState(page.checksum === data.expected_page_checksum && page.source_checksum === data.expected_source_checksum
      && page.object_key === data.expected_object_key
      && stable(page.large_objects) === stable(data.expected_large_objects),
      'archive_page_changed');
    requireState(Array.isArray(page.message_ids) && page.message_ids.includes(data.message_id), 'archive_message_not_in_page');
    requireState(rows.length === page.message_count && stable(rows.map(row => row.client_message_id)) === stable(page.message_ids),
      'archive_mutation_page_identity_changed');
    requireState(rows.every(row => row.chat_id === chat.id && typeof row.id === 'string'
      && typeof row.client_message_id === 'string' && typeof row.encrypted_content === 'string'
      && row.encrypted_content.length > 0 && !row.encrypted_content.startsWith('vault:')),
    'archive_mutation_not_canonical');
    const segment = await trx(SEGMENTS).where('id', page.segment_id).forUpdate().first();
    requireState(segment && segment.chat_id === chat.id && ownerOf(segment) === ownerOf(chat), 'archive_authority_changed');
    requireState(['verified', 'reader_active', 'pruned'].includes(segment.state), 'archive_writer_may_still_upload');
    // PostgreSQL ON CONFLICT DO NOTHING keeps a concurrently edited hot row.
    // The page index is removed in this SAME transaction, so it cannot resurrect
    // the deleted or edited message after promotion commits.
    await trx('messages').insert(rows).onConflict().ignore();
    const retained = await trx('messages').where('chat_id', chat.id)
      .whereIn('client_message_id', page.message_ids).select('client_message_id');
    requireState(retained.length === rows.length && stable(retained.map(row => row.client_message_id).sort())
      === stable([...page.message_ids].sort()), 'archive_restore_incomplete');
    if (page.pruned) {
      const count = Number(chat.archived_message_count);
      requireState(Number.isSafeInteger(count) && count >= page.message_count, 'archive_count_invalid');
      await trx('chats').where('id', chat.id).update({ archived_message_count: count - page.message_count });
    }
    requireState(Number.isSafeInteger(Number(segment.page_count)) && Number(segment.page_count) >= 0,
      'archive_segment_count_invalid');
    if (Number(segment.page_count) > 0) {
      await trx(SEGMENTS).where('id', segment.id).update({ page_count: Number(segment.page_count) - 1 });
    }
    const deleted = await trx(PAGES).where('id', page.id).delete();
    requireState(deleted === 1, 'archive_page_retirement_failed');
    const generation = Number(chat.archive_mutation_v ?? 0);
    requireState(Number.isSafeInteger(generation) && generation >= 0 && generation < Number.MAX_SAFE_INTEGER,
      'archive_mutation_generation_invalid');
    await trx('chats').where('id', chat.id).update({ archive_mutation_v: generation + 1 });
    return { promoted: true, page_id: page.id, restored_count: rows.length };
  });
}
