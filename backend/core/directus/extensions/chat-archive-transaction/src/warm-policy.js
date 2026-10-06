import { createHash } from 'node:crypto';
import { teamArchiveFinancialReady } from './team-storage-readiness.js';

const MAX_CANDIDATE_PREFIX = 1000;
const MAX_NEWEST_WINDOW = 101;
const DAY_SECONDS = 86400;

function positiveLimit(name, fallback) {
  const value = Number(process.env[name] ?? fallback);
  if (!Number.isSafeInteger(value) || value <= 0) return null;
  return value;
}

function limits() {
  const recentMain = positiveLimit('CHAT_WARM_RECENT_MAIN_COUNT', 10);
  const messages = positiveLimit('CHAT_WARM_MESSAGES_PER_CHAT', 100);
  const bytes = positiveLimit('CHAT_WARM_ENCRYPTED_BYTES_PER_CHAT', 2 * 1024 * 1024);
  const inactiveDays = positiveLimit('CHAT_WARM_INACTIVE_DAYS', 30);
  if (!recentMain || !messages || messages >= MAX_NEWEST_WINDOW || !bytes || !inactiveDays) return null;
  return { recentMain, messages, bytes, inactiveDays };
}

/** One bounded indexed keyset sweep. The cursor advances over scanned IDs, not
 * merely eligible IDs, so sparse candidate sets cannot starve later chats. */
export async function policyCandidates(trx, now, { afterChatId = null, limit = 1000 } = {}) {
  const policy = limits();
  if (!policy) return { chat_ids: [], next_cursor: null, scanned_count: 0, reason: 'invalid_warm_policy_configuration' };
  const boundedLimit = Number.isSafeInteger(limit) && limit > 0 ? Math.min(limit, 1000) : 1000;
  const cutoff = now - policy.inactiveDays * DAY_SECONDS;
  const teamFinancialReady = teamArchiveFinancialReady('team');
  const sql = `
    WITH page AS (
      SELECT c.id, c.hashed_user_id, c.hashed_team_id, c.parent_id, c.is_sub_chat,
        c.last_edited_overall_timestamp, c.updated_at,
        c.child_result_delivered_at, c.child_parent_consumed_at,
        c.child_canonical_acknowledged_at, c.encrypted_chat_key
      FROM chats c
      WHERE (?::uuid IS NULL OR c.id > ?::uuid)
        AND (c.storage_state IS NULL OR c.storage_state = 'hot')
      ORDER BY c.id LIMIT ?
    ), eligible AS (
      SELECT p.id FROM page p
      JOIN LATERAL (
        SELECT COUNT(*)::bigint AS message_count,
          COALESCE(SUM(COALESCE(OCTET_LENGTH(m.encrypted_content), 0)
            + COALESCE(OCTET_LENGTH(m.encrypted_thinking_content), 0)), 0)::bigint AS cipher_bytes
        FROM messages m WHERE m.chat_id = p.id::text
      ) stats ON true
      WHERE stats.message_count > 0
        AND (p.hashed_team_id IS NULL OR ${teamFinancialReady ? 'TRUE' : 'FALSE'})
        AND NOT EXISTS (SELECT 1 FROM chat_turn_preflights f WHERE f.chat_id = p.id AND f.state IN ('PREPARED','ENQUEUED','RUNNING'))
        AND NOT EXISTS (SELECT 1 FROM chat_completion_recovery_jobs j WHERE j.chat_id = p.id AND j.state IN ('AVAILABLE','LEASED'))
        AND NOT EXISTS (SELECT 1 FROM chat_recovery_outputs o WHERE (o.target_chat_id = p.id OR o.root_chat_id = p.id) AND o.state IN ('PREPARING','PENDING') AND o.deleted_at IS NULL)
        AND (
          ((p.is_sub_chat = true OR p.parent_id IS NOT NULL)
            AND p.child_result_delivered_at IS NOT NULL
            AND p.child_parent_consumed_at IS NOT NULL
            AND p.child_canonical_acknowledged_at IS NOT NULL
            AND p.encrypted_chat_key IS NOT NULL)
          OR ((p.is_sub_chat IS NULL OR p.is_sub_chat = false) AND p.parent_id IS NULL
            AND (
              (COALESCE(p.last_edited_overall_timestamp, p.updated_at, 0) > 0
                AND COALESCE(p.last_edited_overall_timestamp, p.updated_at, 0) <= ?)
              OR stats.message_count > ? OR stats.cipher_bytes > ?
              OR (SELECT COUNT(*) FROM chats newer
                WHERE ((p.hashed_team_id IS NOT NULL AND newer.hashed_team_id = p.hashed_team_id)
                  OR (p.hashed_team_id IS NULL AND newer.hashed_team_id IS NULL
                    AND newer.hashed_user_id = p.hashed_user_id))
                  AND newer.parent_id IS NULL AND COALESCE(newer.is_sub_chat, false) = false
                  AND (newer.storage_state IS NULL OR newer.storage_state = 'hot')
                  AND (COALESCE(newer.last_edited_overall_timestamp, newer.updated_at, 0), newer.id)
                    > (COALESCE(p.last_edited_overall_timestamp, p.updated_at, 0), p.id)) >= ?
            ))
        )
    )
    SELECT (SELECT id FROM page ORDER BY id DESC LIMIT 1) AS next_cursor,
      (SELECT COUNT(*)::integer FROM page) AS scanned_count,
      COALESCE((SELECT ARRAY_AGG(id ORDER BY id) FROM eligible), ARRAY[]::uuid[]) AS chat_ids
  `;
  const result = await trx.raw(sql, [afterChatId, afterChatId, boundedLimit, cutoff,
    policy.messages, policy.bytes, policy.recentMain]);
  const row = result.rows?.[0] || result[0] || {};
  return {
    chat_ids: Array.isArray(row.chat_ids) ? row.chat_ids.map(String) : [],
    next_cursor: row.next_cursor ? String(row.next_cursor) : null,
    scanned_count: Number(row.scanned_count || 0),
  };
}

const pos = (row) => [Number(row.created_at), String(row.client_message_id)];
const cmp = (left, right) => left[0] - right[0]
  || (left[1] < right[1] ? -1 : left[1] > right[1] ? 1 : 0);
const defer = (reason) => ({ eligible: false, reason });

function measuredBytes(row) {
  return Number(row.cipher_bytes || 0);
}

function canonical(row) {
  return row.client_message_id && Number.isSafeInteger(Number(row.created_at))
    && row.has_ciphertext === true && !String(row.cipher_prefix || '').startsWith('vault:')
    && Number.isSafeInteger(measuredBytes(row)) && measuredBytes(row) > 0;
}

const messageProjection = (trx) => [
  'client_message_id', 'created_at',
  trx.raw("(encrypted_content IS NOT NULL AND encrypted_content <> '') AS has_ciphertext"),
  trx.raw("LEFT(encrypted_content, 9) AS cipher_prefix"),
  trx.raw("(COALESCE(OCTET_LENGTH(encrypted_content), 0) + COALESCE(OCTET_LENGTH(encrypted_thinking_content), 0)) AS cipher_bytes"),
];

async function pendingBarrier(trx, chatId) {
  if (await trx('chat_turn_preflights').where({ chat_id: chatId })
    .whereIn('state', ['PREPARED', 'ENQUEUED', 'RUNNING']).first()) return 'active_preflight';
  if (await trx('chat_completion_recovery_jobs').where({ chat_id: chatId })
    .whereIn('state', ['AVAILABLE', 'LEASED']).first()) return 'pending_recovery';
  if (await trx('chat_recovery_outputs').where(function () { this.where('target_chat_id', chatId).orWhere('root_chat_id', chatId); }).whereIn('state', ['PREPARING', 'PENDING'])
    .whereNull('deleted_at').first()) return 'pending_recovery_output';
  return null;
}

async function recentMainRank(trx, chat) {
  const activity = Number(chat.last_edited_overall_timestamp || chat.updated_at || 0);
  const owner = chat.hashed_team_id
    ? { hashed_team_id: chat.hashed_team_id }
    : { hashed_user_id: chat.hashed_user_id, hashed_team_id: null };
  const row = await trx('chats').where(owner)
    .whereNull('parent_id')
    .whereRaw('COALESCE(is_sub_chat, false) = false')
    .whereRaw("(storage_state IS NULL OR storage_state = 'hot')")
    .whereRaw('(COALESCE(last_edited_overall_timestamp, updated_at, 0), id) > (?, ?)', [activity, chat.id])
    .count('* as count').first();
  return Number(row?.count || 0);
}

async function latestSegmentEnd(trx, chatId) {
  const previous = await trx('chat_message_archive_segments').where({ chat_id: chatId })
    .whereIn('state', ['verified', 'reader_active', 'pruned'])
    .orderBy('end_timestamp', 'desc').orderBy('end_message_id', 'desc')
    .select('end_timestamp', 'end_message_id').first();
  return previous ? [Number(previous.end_timestamp), String(previous.end_message_id)] : null;
}

/**
 * Select one bounded, contiguous, canonical ciphertext prefix inside a chat lock.
 * SQL aggregates may scan indexed rows but never materialize whole transcripts.
 * The transaction claim and page writer independently recheck this boundary.
 */
export async function policyBoundary(trx, chat, data = {}, now = Math.floor(Date.now() / 1000)) {
  const policy = limits();
  if (!policy) return defer('invalid_warm_policy_configuration');
  if (!chat?.id || !(chat.hashed_team_id || chat.hashed_user_id)
    || !['hot', null, undefined].includes(chat.storage_state))
    return defer('chat_unavailable');

  const barrier = await pendingBarrier(trx, chat.id);
  if (barrier) return defer(barrier);

  const child = Boolean(chat.is_sub_chat || chat.parent_id);
  if (child && !(chat.child_result_delivered_at && chat.child_parent_consumed_at
    && chat.child_canonical_acknowledged_at && chat.encrypted_chat_key)) {
    return defer('child_durability_or_synthesis_pending');
  }

  const aggregate = await trx('messages').where({ chat_id: chat.id }).select(trx.raw(
    "COUNT(*)::bigint AS message_count, "
    + "COALESCE(SUM(COALESCE(OCTET_LENGTH(encrypted_content), 0) "
    + "+ COALESCE(OCTET_LENGTH(encrypted_thinking_content), 0)), 0)::bigint AS cipher_bytes",
  )).first();
  const messageCount = Number(aggregate?.message_count || 0);
  const totalBytes = Number(aggregate?.cipher_bytes || 0);
  if (!Number.isSafeInteger(messageCount) || !Number.isSafeInteger(totalBytes) || messageCount < 1)
    return defer('no_bounded_canonical_messages');

  let reason;
  let eligibleEnd = null;
  if (child) {
    reason = 'completed_child';
  } else {
    const lastActivity = Number(chat.last_edited_overall_timestamp || chat.updated_at || 0);
    if (lastActivity > 0 && lastActivity <= now - policy.inactiveDays * DAY_SECONDS) {
      reason = 'inactive';
    } else {
      const rank = await recentMainRank(trx, chat);
      if (rank >= policy.recentMain) reason = 'outside_recent_main';
    }
  }

  if (!reason) {
    if (messageCount <= policy.messages && totalBytes <= policy.bytes) return defer('within_warm_limits');
    const newest = await trx('messages').where({ chat_id: chat.id })
      .select(messageProjection(trx)).orderBy('created_at', 'desc')
      .orderBy('client_message_id', 'desc').limit(Math.min(MAX_NEWEST_WINDOW, policy.messages + 1));
    if (!Array.isArray(newest) || newest.length < Math.min(messageCount, policy.messages + 1)
      || newest.some(row => !canonical(row))) return defer('unsupported_or_incomplete_newest_window');
    let kept = 0;
    let keptBytes = 0;
    while (kept < newest.length && kept < policy.messages
      && keptBytes + measuredBytes(newest[kept]) <= policy.bytes) {
      keptBytes += measuredBytes(newest[kept]);
      kept += 1;
    }
    if (kept >= newest.length) return defer('within_warm_limits');
    eligibleEnd = pos(newest[kept]);
    reason = kept === policy.messages ? 'message_count_limit' : 'ciphertext_byte_limit';
  }

  // Restored mutation pages and new client-encrypted writes can be older than
  // the largest previous segment. Hot canonical rows remain eligible; copied
  // but unpruned overlap is fenced by source validation and reader de-duplication.
  let candidates = trx('messages').where({ chat_id: chat.id }).whereRaw("NOT EXISTS (SELECT 1 FROM chat_message_archive_pages p WHERE p.chat_id = messages.chat_id AND p.message_ids::jsonb @> jsonb_build_array(messages.client_message_id))");
  if (eligibleEnd) candidates = candidates.whereRaw('(created_at, client_message_id) <= (?, ?)', eligibleEnd);
  const prefix = await candidates.select(messageProjection(trx))
    .orderBy('created_at').orderBy('client_message_id').limit(MAX_CANDIDATE_PREFIX);
  if (!Array.isArray(prefix) || !prefix.length) return defer('no_new_prefix');
  if (prefix.some(row => !canonical(row))) return defer('unsupported_canonical_ciphertext');
  for (let index = 1; index < prefix.length; index++) {
    if (cmp(pos(prefix[index - 1]), pos(prefix[index])) >= 0) return defer('unstable_message_order');
  }
  const end = pos(prefix[prefix.length - 1]);
  const sourceMessageIds = prefix.map(row => row.client_message_id);
  const generation = Number(chat.archive_mutation_v ?? 0);
  if (!Number.isSafeInteger(generation) || generation < 0) return defer('invalid_archive_mutation_generation');
  const sourceDigest = createHash('sha256').update(JSON.stringify(sourceMessageIds)).digest('hex');
  const policyId = createHash('sha256').update(`${chat.id}:${reason}:${end[0]}:${end[1]}:${generation}:${sourceDigest}`).digest('hex');
  if (data.reason && data.reason !== reason) return defer('warm_policy_reason_changed');
  if (data.policy_id && data.policy_id !== policyId) return defer('warm_policy_identity_changed');
  if (data.end_timestamp != null && Number(data.end_timestamp) !== end[0]) return defer('warm_policy_boundary_changed');
  if (data.end_message_id && data.end_message_id !== end[1]) return defer('warm_policy_boundary_changed');
  return {
    eligible: true, reason, policy_id: policyId,
    end_timestamp: end[0], end_message_id: end[1],
    source_message_ids: sourceMessageIds,
    message_count: prefix.length, encrypted_payload_bytes: prefix.reduce((sum, row) => sum + measuredBytes(row), 0),
    recent_main_rank: child ? null : await recentMainRank(trx, chat),
  };
}
