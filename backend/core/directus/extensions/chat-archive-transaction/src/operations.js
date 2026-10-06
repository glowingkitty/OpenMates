import { createHash, randomUUID } from 'node:crypto';
import { policyBoundary, policyCandidates } from './warm-policy.js';
import { teamArchiveFinancialReady } from './team-storage-readiness.js';
import { selectWindowLocators } from './locator-window.js';

const SEGMENTS = 'chat_message_archive_segments';
const PAGES = 'chat_message_archive_pages';
const ROLLOUT = 'chat_message_archive_rollout';
const MAX_PAGE_MESSAGES = 20;
const MAX_SEGMENT_PAGES = 1000;
const jsonColumns = row => Object.fromEntries(Object.entries(row).map(([key, value]) => [key, value != null && ['source_message_ids','message_ids','message_positions','source_fields','verified_regions','large_objects'].includes(key) ? JSON.stringify(value) : value]));
export class ArchiveProtocolError extends Error {
  constructor(code, status = 409) { super(code); this.code = code; this.status = status; }
}
function requireState(condition, code, status) { if (!condition) throw new ArchiveProtocolError(code, status); }
function text(value) { requireState(typeof value === 'string' && value.length > 0 && value.length <= 256, 'invalid_identity', 400); return value; }
function integer(value) { requireState(Number.isSafeInteger(value) && value >= 0, 'invalid_integer', 400); return value; }
function ownerOf(row) { return row.hashed_team_id
  ? `team:${row.hashed_team_id}` : row.hashed_user_id ? `user:${row.hashed_user_id}` : null; }
function teamFinancialReady(chat) { return teamArchiveFinancialReady(chat.hashed_team_id); }
export function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${stable(value[k])}`).join(',')}}`;
  return JSON.stringify(value);
}
export const checksum = (value) => createHash('sha256').update(stable(value), 'utf8').digest('hex');
const position = (timestamp, id) => [Number(timestamp), String(id)];
const compare = (a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0);
function prefix(query, segment) {
  query.where('chat_id', segment.chat_id).andWhere(function () {
    this.where('created_at', '<', segment.end_timestamp).orWhere(function () {
      this.where('created_at', segment.end_timestamp).where('client_message_id', '<=', segment.end_message_id);
    });
  });
  if (segment.start_message_id) query.andWhere(function () {
    this.where('created_at', '>', segment.start_timestamp).orWhere(function () {
      this.where('created_at', segment.start_timestamp).where('client_message_id', '>', segment.start_message_id);
    });
  });
  return query;
}
async function lockedChat(trx, chatId) {
  const chat = await trx('chats').where('id', text(chatId)).forUpdate().first();
  requireState(chat && chat.storage_state !== 'deleting', 'chat_unavailable', 404);
  requireState(chat.hashed_user_id || chat.hashed_team_id, 'archive_owner_missing');
  return chat;
}
async function lockedSegment(trx, data) {
  const initial = await trx(SEGMENTS).where('id', text(data.segment_id)).first();
  requireState(initial, 'archive_segment_missing', 404);
  const chat = await lockedChat(trx, initial.chat_id);
  const segment = await trx(SEGMENTS).where('id', initial.id).forUpdate().first();
  requireState(segment.version === data.expected_version, 'archive_generation_changed');
  requireState(ownerOf(segment) === ownerOf(chat), 'archive_authority_changed');
  return { chat, segment };
}
async function sourceMatches(trx, page) {
  requireState(Array.isArray(page.source_fields) && page.source_fields.includes('encrypted_content') && page.source_fields.includes('id'), 'invalid_source_projection', 400);
  const rows = await trx('messages').select(page.source_fields)
    .where('chat_id', page.chat_id).whereIn('client_message_id', page.message_ids)
    .orderBy('created_at').orderBy('client_message_id').forUpdate();
  requireState(rows.length === page.message_count && checksum(rows) === page.source_checksum, 'archive_source_changed');
  requireState(rows.every(r => typeof r.encrypted_content === 'string' && r.encrypted_content && !r.encrypted_content.startsWith('vault:')), 'archive_source_not_canonical');
  requireState(stable(rows.map(r => r.client_message_id)) === stable(page.message_ids) && rows[0].created_at === page.first_timestamp && rows[0].client_message_id === page.first_message_id && rows.at(-1).created_at === page.last_timestamp && rows.at(-1).client_message_id === page.last_message_id && compare(position(page.first_timestamp, page.first_message_id), position(page.last_timestamp, page.last_message_id)) <= 0, 'archive_page_order_invalid');
  requireState(stable(rows.map(r => [Number(r.created_at), r.client_message_id])) === stable(page.message_positions), 'archive_page_positions_changed');
  return rows;
}

export async function archiveOperation(database, body) {
  requireState(body && typeof body.data === 'object', 'invalid_request', 400);
  const { operation, data } = body;
  const now = integer(data.now ?? Math.floor(Date.now() / 1000));
  return database.transaction(async trx => {
    if (operation === 'transfer_chat_to_team') {
      const chat = await lockedChat(trx, data.chat_id);
      const personalHash = text(data.expected_hashed_user_id);
      const teamHash = text(data.hashed_team_id);
      requireState(/^[0-9a-f]{64}$/.test(personalHash) && /^[0-9a-f]{64}$/.test(teamHash), 'invalid_archive_owner', 400);
      requireState(chat.hashed_user_id === personalHash && !chat.hashed_team_id, 'archive_authority_changed');
      const membership = await trx('team_memberships').where({
        hashed_user_id: personalHash, hashed_team_id: teamHash, status: 'active',
      }).whereIn('role', ['owner', 'admin', 'member']).forShare().first();
      const team = await trx('teams').where({ hashed_team_id: teamHash, status: 'active' }).forShare().first();
      requireState(membership && team, 'team_write_permission_changed');
      requireState(!['archiving', 'promoting'].includes(chat.storage_state), 'chat_storage_transition_active');
      const preflight = await trx('chat_turn_preflights').where({ chat_id: chat.id })
        .whereIn('state', ['PREPARED', 'ENQUEUED', 'RUNNING']).first();
      const recovery = await trx('chat_completion_recovery_jobs').where({ chat_id: chat.id })
        .whereIn('state', ['AVAILABLE', 'LEASED']).first();
      const output = await trx('chat_recovery_outputs').where(function () {
        this.where('root_chat_id', chat.id).orWhere('target_chat_id', chat.id);
      }).whereIn('state', ['PREPARING', 'PENDING']).whereNull('deleted_at').first();
      requireState(!preflight && !recovery && !output, 'chat_recovery_or_write_pending');
      const segments = await trx(SEGMENTS).where({ chat_id: chat.id }).forUpdate();
      const pages = await trx(PAGES).where({ chat_id: chat.id }).forUpdate();
      requireState(segments.every(row => row.hashed_user_id === personalHash && !row.hashed_team_id)
        && pages.every(row => row.hashed_user_id === personalHash && !row.hashed_team_id), 'archive_authority_changed');
      requireState(segments.every(row => row.state !== 'copying' || Number(row.lease_until) + 90 <= now),
        'archive_copy_in_progress');
      const version = Number(chat.archive_version ?? 1);
      requireState(Number.isSafeInteger(version) && version >= 0, 'invalid_archive_generation');
      const patch = { hashed_user_id: null, hashed_team_id: teamHash,
        updated_at: integer(data.updated_at), archive_version: version + 1 };
      if (data.encrypted_slug !== undefined) {
        requireState(typeof data.encrypted_slug === 'string' && data.encrypted_slug.length > 0
          && data.encrypted_slug.length <= 8192, 'invalid_encrypted_slug', 400);
        patch.encrypted_slug = data.encrypted_slug;
      }
      if (data.slug_lookup_hash !== undefined) {
        requireState(typeof data.slug_lookup_hash === 'string' && /^[0-9a-f]{64}$/.test(data.slug_lookup_hash),
          'invalid_slug_lookup_hash', 400);
        patch.slug_lookup_hash = data.slug_lookup_hash;
      }
      const [updated] = await trx('chats').where('id', chat.id).update(patch).returning('*');
      await trx(SEGMENTS).where({ chat_id: chat.id }).update({ hashed_user_id: null, hashed_team_id: teamHash });
      await trx(PAGES).where({ chat_id: chat.id }).update({ hashed_user_id: null, hashed_team_id: teamHash });
      return { chat: updated };
    }
    if (operation === 'policy_candidates') {
      return await policyCandidates(trx, now, { afterChatId: data.after_chat_id || null, limit: Math.min(integer(data.limit || 100), 1000) });
    }
    if (operation === 'resolve_chat_hashes') {
      const hashes = data.hashes;
      requireState(Array.isArray(hashes) && hashes.length > 0 && hashes.length <= 20
        && new Set(hashes).size === hashes.length
        && hashes.every(value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)),
      'invalid_chat_hash_batch', 400);
      const result = await trx.raw(`
        SELECT id, encode(digest(id::text, 'sha256'), 'hex') AS hashed_chat_id,
          hashed_user_id, hashed_team_id,
          COALESCE(storage_state, 'hot') AS storage_state
        FROM chats
        WHERE encode(digest(id::text, 'sha256'), 'hex') = ANY(?::text[])
      `, [hashes]);
      const rows = result.rows || result[0];
      requireState(Array.isArray(rows) && rows.every(row => hashes.includes(row.hashed_chat_id)),
        'chat_hash_resolution_failed');
      return { chats: rows };
    }
    if (operation === 'progress_candidates') {
      const afterId = data.after_id;
      requireState(afterId == null || (typeof afterId === 'string'
        && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(afterId)),
      'invalid_archive_progress_cursor', 400);
      requireState(typeof data.reads_enabled === 'boolean' && typeof data.prune_enabled === 'boolean',
        'invalid_archive_progress_gates', 400);
      const query = trx(SEGMENTS).select('id').where(function () {
        this.where(function () { this.where('state', 'copying').where('lease_until', '<=', now); });
        if (data.reads_enabled) this.orWhere('state', 'verified');
        if (data.prune_enabled) this.orWhere(function () {
          this.where('state', 'reader_active').where('source_copy_until', '<=', now);
        });
      }).orderBy('id');
      if (afterId) query.where('id', '>', afterId);
      return { segments: await query.limit(Math.min(integer(data.limit ?? 25), 25)) };
    }
    if (operation === 'checkpoint_candidates') {
      const query = trx('chat_compression_checkpoints as cp').select(['cp.id', 'cp.chat_id'])
        .whereNotNull('cp.covered_message_ids').whereNotNull('cp.compressed_up_to_message_id')
        .whereNotNull('cp.encrypted_summary')
        .whereRaw('NOT EXISTS (SELECT 1 FROM chat_message_archive_segments s WHERE s.chat_id = cp.chat_id AND s.checkpoint_id = cp.id::text)')
        .orderBy('cp.id').limit(Math.min(integer(data.limit || 100), 1000));
      if (data.after_id) query.where('cp.id', '>', text(data.after_id));
      const checkpoints = await query;
      return { checkpoints, next_cursor: checkpoints.at(-1)?.id || null };
    }
    if (operation === 'lookup_message') {
      await lockedChat(trx, data.chat_id);
      const page = await trx(PAGES).where({ chat_id: data.chat_id, read_enabled: true })
        .whereRaw('message_ids::jsonb @> ?::jsonb', [JSON.stringify([text(data.message_id)])]).first();
      return { page: page || null };
    }
    if (operation === 'window_locators') {
      await lockedChat(trx, data.chat_id);
      requireState(['before', 'after'].includes(data.direction), 'invalid_window_direction', 400);
      const missing = await trx(PAGES).where({ chat_id: data.chat_id, read_enabled: true }).whereNull('message_positions').first();
      requireState(!missing, 'archive_page_position_index_required');
      const before = data.direction === 'before';
      const limit = Math.min(integer(data.limit || MAX_PAGE_MESSAGES), MAX_PAGE_MESSAGES);
      const cursor = data.cursor_timestamp == null ? null : position(integer(data.cursor_timestamp), text(data.cursor_message_id));
      const eligibleEdge = before ? 'first' : 'last';
      const catalogEdge = before ? 'last' : 'first';
      const op = before ? '<' : '>';
      const sort = before ? 'DESC' : 'ASC';
      const fetchChunk = async (catalogCursor, chunkLimit) => {
        const result = await trx.raw(`
          SELECT id, first_timestamp, first_message_id, last_timestamp, last_message_id,
            message_positions, message_count
          FROM chat_message_archive_pages
          WHERE chat_id = ? AND read_enabled
          ${cursor ? `AND (${eligibleEdge}_timestamp, ${eligibleEdge}_message_id) ${op} (?, ?)` : ''}
          ${catalogCursor ? `AND (${catalogEdge}_timestamp, ${catalogEdge}_message_id, id) ${op} (?, ?, ?)` : ''}
          ORDER BY ${catalogEdge}_timestamp ${sort}, ${catalogEdge}_message_id ${sort}, id ${sort}
          LIMIT ?
        `, [data.chat_id, ...(cursor || []), ...(catalogCursor || []), chunkLimit]);
        const rows = result.rows || result[0];
        requireState(Array.isArray(rows), 'archive_locator_query_failed');
        return rows;
      };
      const { locators, has_more } = await selectWindowLocators({ fetchChunk, direction: data.direction, cursor, limit });
      const pages = locators.length ? await trx(PAGES).whereIn('id', [...new Set(locators.map(r => r.page_id))]) : [];
      return { locators, pages, has_more };
    }
    if (operation === 'claim_segment') {
      const chat = await lockedChat(trx, data.chat_id);
      requireState(teamFinancialReady(chat), 'team_storage_billing_not_ready');
      if (data.resume_segment_id) {
        const existing = await trx(SEGMENTS).where({ id: text(data.resume_segment_id), chat_id: chat.id }).forUpdate().first();
        requireState(existing?.state === 'copying' && existing.lease_until <= now, 'archive_copy_in_progress');
        requireState(ownerOf(existing) === ownerOf(chat), 'archive_authority_changed');
        const [resumed] = await trx(SEGMENTS).where('id', existing.id).update({ version: existing.version + 1, lease_until: now + 300 }).returning('*');
        return { segment: resumed };
      }
      let checkpointId;
      let coveredIds = null;
      if (data.checkpoint_id) {
        checkpointId = text(data.checkpoint_id);
        const checkpoint = await trx('chat_compression_checkpoints').where({ id: checkpointId, chat_id: chat.id }).first();
        requireState(checkpoint && checkpoint.encrypted_summary, 'canonical_checkpoint_required');
        coveredIds = checkpoint.covered_message_ids;
        requireState(Array.isArray(coveredIds) && coveredIds.length > 0 && coveredIds.length <= 20000 && new Set(coveredIds).size === coveredIds.length && coveredIds.every(id => typeof id === 'string' && id && id.length <= 256), 'exact_checkpoint_manifest_required');
        requireState(checkpoint.compressed_up_to_message_id === data.end_message_id && checkpoint.compressed_up_to_timestamp === data.end_timestamp, 'stable_checkpoint_boundary_required');
      } else {
        const boundary = await policyBoundary(trx, chat, data, now);
        requireState(boundary.eligible, boundary.reason || 'archive_policy_not_eligible');
        checkpointId = `policy:${boundary.policy_id}`;
        coveredIds = boundary.source_message_ids;
        data.end_timestamp = boundary.end_timestamp;
        data.end_message_id = boundary.end_message_id;
      }
      let segment = await trx(SEGMENTS).where({ chat_id: chat.id, checkpoint_id: checkpointId }).forUpdate().first();
      if (segment) {
        if (segment.state !== 'copying') return { segment };
        requireState(segment.lease_until <= now, 'archive_copy_in_progress');
        [segment] = await trx(SEGMENTS).where('id', segment.id).update({ version: segment.version + 1, lease_until: now + 300 }).returning('*');
        return { segment };
      }
      const pending = await trx(SEGMENTS).where({ chat_id: chat.id, state: 'copying' }).first();
      requireState(!pending, 'previous_archive_copy_incomplete');
      const previous = await trx(SEGMENTS).where('chat_id', chat.id).whereIn('state', ['verified', 'reader_active', 'pruned'])
        .orderBy('end_timestamp', 'desc').orderBy('end_message_id', 'desc').first();
      const end = position(integer(data.end_timestamp), text(data.end_message_id));
      requireState(!data.checkpoint_id || !previous || compare(end, position(previous.end_timestamp, previous.end_message_id)) > 0, 'checkpoint_does_not_advance');
      if (coveredIds) {
        const candidates = await prefix(trx('messages').whereIn('client_message_id', coveredIds), { chat_id: chat.id, end_timestamp: end[0], end_message_id: end[1], start_timestamp: data.checkpoint_id ? previous?.end_timestamp ?? 0 : 0, start_message_id: data.checkpoint_id ? previous?.end_message_id ?? null : null }).select([
          'client_message_id',
          trx.raw("(encrypted_content IS NOT NULL AND encrypted_content <> '' AND LEFT(encrypted_content, 6) <> 'vault:') AS canonical_ciphertext"),
        ]);
        requireState(candidates.length === coveredIds.length && candidates.every(r => r.canonical_ciphertext === true), 'canonical_checkpoint_sources_not_ready');
      }
      [segment] = await trx(SEGMENTS).insert(jsonColumns({
        id: randomUUID(), chat_id: chat.id, chat_hash: createHash('sha256').update(chat.id).digest('hex'),
        hashed_user_id: chat.hashed_team_id ? null : chat.hashed_user_id,
        hashed_team_id: chat.hashed_team_id || null,
        checkpoint_id: checkpointId, source_message_ids: coveredIds, start_timestamp: data.checkpoint_id ? previous?.end_timestamp ?? 0 : 0,
        start_message_id: data.checkpoint_id ? previous?.end_message_id ?? null : null,
        end_timestamp: end[0], end_message_id: end[1], state: 'copying', version: 1,
        page_count: 0, lease_until: now + 300, created_at: now,
      })).returning('*');
      return { segment };
    }
    const { chat, segment } = await lockedSegment(trx, data);
    if (operation === 'source_page') {
      requireState(segment.state === 'copying' && segment.lease_until >= now, 'archive_copy_lease_expired');
      const query = prefix(trx('messages'), segment);
      if (segment.source_message_ids) query.whereIn('client_message_id', segment.source_message_ids);
      if (data.after_message_id != null) query.andWhere(function () {
        this.where('created_at', '>', integer(data.after_timestamp)).orWhere(function () {
          this.where('created_at', data.after_timestamp).where('client_message_id', '>', text(data.after_message_id));
        });
      });
      return { messages: await query.orderBy('created_at').orderBy('client_message_id').limit(MAX_PAGE_MESSAGES) };
    }
    if (operation === 'prepare_page' || operation === 'publish_page') {
      const page = data.page;
      requireState(segment.state === 'copying' && segment.lease_until >= now, 'archive_copy_lease_expired');
      requireState(page && integer(page.page_number) > 0 && page.page_number <= MAX_SEGMENT_PAGES, 'invalid_archive_page', 400);
      requireState(integer(page.message_count) > 0 && page.message_count <= MAX_PAGE_MESSAGES && Array.isArray(page.message_ids) && page.message_ids.length === page.message_count, 'invalid_page_count', 400);
      requireState(new Set(page.message_ids).size === page.message_count && Array.isArray(page.verified_regions) && Array.isArray(page.large_objects), 'invalid_page_identity_or_replication', 400);
      requireState(Array.isArray(page.message_positions) && page.message_positions.length === page.message_count, 'invalid_page_position_index', 400);
      requireState(integer(page.size_bytes) > 0 && page.size_bytes <= 270336 && integer(page.raw_size_bytes) > 0 && page.raw_size_bytes <= 266240, 'page_budget_exceeded', 400);
      const objectPrefix = `message-pages/${segment.chat_hash}/${segment.id}/${page.id}/`;
      requireState(typeof page.object_key === 'string' && page.object_key.startsWith(objectPrefix), 'invalid_archive_object_scope', 400);
      requireState(/^[0-9a-f]{64}$/.test(page.checksum) && /^[0-9a-f]{64}$/.test(page.source_checksum), 'invalid_archive_checksum', 400);
      requireState(page.large_objects.every(ref => typeof ref.object_key === 'string' && ref.object_key.startsWith(objectPrefix) && ref.size_bytes > 0 && ref.size_bytes <= 2097152 && /^[0-9a-f]{64}$/.test(ref.checksum) && Array.isArray(ref.verified_regions)), 'invalid_large_archive_object', 400);
      const fields = { ...page, segment_id: segment.id, chat_id: chat.id,
        hashed_user_id: chat.hashed_team_id ? null : chat.hashed_user_id || null,
        hashed_team_id: chat.hashed_team_id || null,
        read_enabled: false, pruned: false, published: false, created_at: now };
      requireState(!segment.source_message_ids || page.message_ids.every(id => segment.source_message_ids.includes(id)), 'archive_page_outside_checkpoint_manifest');
      await sourceMatches(trx, fields);
      const existing = await trx(PAGES).where({ segment_id: segment.id, page_number: page.page_number }).forUpdate().first();
      const immutable = p => ({ id: p.id, object_key: p.object_key, checksum: p.checksum,
        source_checksum: p.source_checksum, size_bytes: p.size_bytes, raw_size_bytes: p.raw_size_bytes,
        message_ids: p.message_ids, message_positions: p.message_positions, source_fields: p.source_fields, message_count: p.message_count,
        first_timestamp: p.first_timestamp, first_message_id: p.first_message_id,
        last_timestamp: p.last_timestamp, last_message_id: p.last_message_id,
        large_objects: p.large_objects.map(ref => ({ object_key: ref.object_key, checksum: ref.checksum, size_bytes: ref.size_bytes })) });
      if (existing) requireState(stable(immutable(existing)) === stable(immutable(fields)), 'archive_retry_source_changed');
      if (operation === 'prepare_page') {
        const saved = existing || (await trx(PAGES).insert(jsonColumns(fields)).returning('*'))[0];
        await trx(SEGMENTS).where('id', segment.id).update({ lease_until: now + 300 });
        return { page: saved };
      }
      requireState(existing, 'archive_upload_intent_required');
      requireState(page.verified_regions.length > 0 && page.large_objects.every(ref => stable([...ref.verified_regions].sort()) === stable([...page.verified_regions].sort())), 'archive_replication_incomplete');
      const [saved] = await trx(PAGES).where('id', existing.id).update(jsonColumns({ published: true,
        verified_regions: page.verified_regions, large_objects: page.large_objects })).returning('*');
      await trx(SEGMENTS).where('id', segment.id).update({ lease_until: now + 300 });
      return { page: saved };
    }
    if (operation === 'verify_segment') {
      requireState(segment.state === 'copying', 'archive_not_copying');
      const count = integer(data.page_count);
      requireState(count > 0 && count <= MAX_SEGMENT_PAGES, 'invalid_segment_page_count');
      const pages = await trx(PAGES).where('segment_id', segment.id).orderBy('page_number');
      requireState(pages.length === count && pages.every(p => p.published), 'archive_pages_incomplete');
      let end = segment.start_message_id ? position(segment.start_timestamp, segment.start_message_id) : null;
      let messageCount = 0;
      for (let i = 0; i < pages.length; i++) {
        const page = pages[i];
        requireState(page.page_number === i + 1 && (!end || compare(position(page.first_timestamp, page.first_message_id), end) > 0), 'archive_page_order_invalid');
        await sourceMatches(trx, page);
        end = position(page.last_timestamp, page.last_message_id);
        messageCount += page.message_count;
      }
      const source = prefix(trx('messages'), segment);
      if (segment.source_message_ids) source.whereIn('client_message_id', segment.source_message_ids);
      const [{ count: sourceCount }] = await source.count('* as count');
      requireState(!segment.source_message_ids || messageCount === segment.source_message_ids.length, 'archive_checkpoint_manifest_incomplete');
      requireState(Number(sourceCount) === messageCount && compare(end, position(segment.end_timestamp, segment.end_message_id)) === 0, 'archive_prefix_incomplete');
      const [saved] = await trx(SEGMENTS).where('id', segment.id).update({ state: 'verified', page_count: count, version: segment.version + 1, verified_at: now }).returning('*');
      return saved;
    }
    if (operation === 'record_reader_verification') {
      requireState(segment.state === 'verified', 'archive_not_verified');
      const page = await trx(PAGES).where({ id: text(data.page_id), segment_id: segment.id }).forUpdate().first();
      requireState(page?.published && page.checksum === data.checksum && page.source_checksum === data.source_checksum, 'archive_reader_generation_changed');
      await sourceMatches(trx, page);
      await trx(PAGES).where('id', page.id).update({ reader_verified: true });
      return { page_id: page.id, reader_verified: true };
    }
    if (operation === 'activate_segment') {
      const rollout = await trx(ROLLOUT).where('id', 'agentic-storage-v2').forShare().first();
      requireState(rollout?.read_enabled && rollout.compatibility_verified && rollout.reader_receipt && !rollout.failure_code, 'archive_read_rollout_not_verified');
      requireState(segment.state === 'verified', 'archive_not_verified');
      const activationPages = await trx(PAGES).where('segment_id', segment.id).orderBy('page_number');
      requireState(activationPages.length === segment.page_count && activationPages.every(p => p.published && p.reader_verified), 'archive_reader_verification_incomplete');
      for (const page of activationPages) await sourceMatches(trx, page);
      const overlaps = (left, right) => compare(position(left.first_timestamp, left.first_message_id),
        position(right.last_timestamp, right.last_message_id)) <= 0
        && compare(position(left.last_timestamp, left.last_message_id),
          position(right.first_timestamp, right.first_message_id)) >= 0;
      for (const page of activationPages) {
        const prospective = activationPages.filter(other => overlaps(page, other)).length;
        requireState(prospective <= 128, 'archive_page_overlap_budget_exceeded');
        const existing = await trx(PAGES).where({ chat_id: chat.id, read_enabled: true })
          .whereRaw('(first_timestamp, first_message_id) <= (?, ?)', [page.last_timestamp, page.last_message_id])
          .whereRaw('(last_timestamp, last_message_id) >= (?, ?)', [page.first_timestamp, page.first_message_id])
          .select('id').limit(129 - prospective);
        requireState(existing.length + prospective <= 128, 'archive_page_overlap_budget_exceeded');
      }
      const [saved] = await trx(SEGMENTS).where('id', segment.id).update({
        state: 'reader_active', reader_activated_at: now,
        source_copy_until: now + (rollout.initial_cohort ? 86400 : 0), version: segment.version + 1,
      }).returning('*');
      await trx(PAGES).where('segment_id', segment.id).update({ read_enabled: true });
      return saved;
    }
    if (operation === 'prune_page') {
      requireState(teamFinancialReady(chat), 'team_storage_billing_not_ready');
      const rollout = await trx(ROLLOUT).where('id', 'agentic-storage-v2').forShare().first();
      requireState(rollout?.pruning_enabled && rollout.compatibility_verified && rollout.validation_receipt && !rollout.failure_code, 'archive_prune_gates_not_verified');
      requireState(segment.state === 'reader_active' && segment.source_copy_until <= now, 'archive_rollback_buffer_active');
      const page = await trx(PAGES).where({ id: text(data.page_id), segment_id: segment.id }).forUpdate().first();
      requireState(page?.read_enabled, 'archive_page_not_readable');
      if (page.pruned) return { pruned: true, duplicate: true, message_count: page.message_count };
      const pendingRecovery = await trx('chat_completion_recovery_jobs').where('chat_id', chat.id).whereIn('state', ['AVAILABLE', 'LEASED']).first();
      const pendingOutputs = await trx('chat_recovery_outputs').where(function () { this.where('target_chat_id', chat.id).orWhere('root_chat_id', chat.id); }).whereIn('state', ['PREPARING', 'PENDING']).whereNull('deleted_at').first();
      requireState(!pendingRecovery && !pendingOutputs, 'canonical_recovery_acknowledgement_required');
      const rows = await sourceMatches(trx, page);
      await trx('messages').where('chat_id', chat.id).whereIn('id', rows.map(r => r.id)).delete();
      await trx('chats').where('id', chat.id).update({ archived_message_count: trx.raw('COALESCE(archived_message_count, 0) + ?', [rows.length]) });
      await trx(PAGES).where('id', page.id).update({ pruned: true, pruned_at: now });
      return { pruned: true, message_count: rows.length };
    }
    if (operation === 'finish_pruning') {
      requireState(teamFinancialReady(chat), 'team_storage_billing_not_ready');
      requireState(segment.state === 'reader_active', 'archive_reader_not_active');
      const remaining = await trx(PAGES).where('segment_id', segment.id).where({ pruned: false }).first();
      requireState(!remaining, 'archive_pruning_incomplete');
      const [saved] = await trx(SEGMENTS).where('id', segment.id).update({ state: 'pruned', version: segment.version + 1 }).returning('*');
      return saved;
    }
    throw new ArchiveProtocolError('unsupported_archive_operation', 400);
  });
}
