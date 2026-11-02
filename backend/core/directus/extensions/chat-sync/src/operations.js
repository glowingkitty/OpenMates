/**
 * Internal-only chat sync feed reads (architecture.sync@2).
 * The API authorizes the caller and Team before supplying hashed scopes. One
 * call returns one bounded page: the gap-free change entries after the cursor
 * plus the encrypted rows needed to hydrate them, read with a fixed number of
 * batched queries. Messages, embeds, embed keys and plaintext never leave here.
 * Cold-start cursors come from readClock before any snapshot read.
 * Change log: backend/core/directus/setup/migrate_chat_sync_feed.sql.
 */
import { createHash } from 'node:crypto';

const hash = value => createHash('sha256').update(value).digest('hex');
const SCOPE = /^(personal|team):[0-9a-f]{64}$/;
const USER_SCOPE = /^user:[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const RETENTION_DAYS = 30;
export const MAX_LIMIT = 200;
export const DEFAULT_LIMIT = 100;
export const WRAPPER_WINDOW = 20;
export const DUE_SOON_SAVED_ITEM_LIMIT = 100;
export const KIND_BITS = Object.freeze({
  metadata: 1, messages: 2, content: 4, keys: 8, draft: 16,
  deleted: 32, revoked: 64, moved: 128, last_opened: 256, due_soon: 512,
});
/** Saved-item memory categories shown by the welcome overview (savedEmbedMemoryService.ts). */
export const SAVED_ITEM_CATEGORIES = Object.freeze([
  ['events', 'saved_events'], ['travel', 'saved_connections'], ['travel', 'saved_stays'],
  ['home', 'saved_listings'], ['health', 'appointments'],
]);
export const CHAT_FIELDS = Object.freeze([
  'id', 'hashed_user_id', 'hashed_team_id', 'chat_visibility', 'participant_user_hashes',
  'participant_key_envelopes', 'encrypted_title', 'unread_count', 'created_at', 'updated_at',
  'encrypted_chat_key', 'encrypted_icon', 'encrypted_category', 'encrypted_chat_summary',
  'encrypted_share_cta_text', 'encrypted_chat_tags', 'encrypted_follow_up_request_suggestions',
  'encrypted_suggested_followup_message', 'encrypted_top_recommended_apps_for_chat',
  'encrypted_quick_tip_slugs', 'encrypted_shared_short_url', 'encrypted_active_focus_id',
  'encrypted_focus_phase_state', 'encrypted_auto_speak_response', 'last_edited_overall_timestamp',
  'messages_v', 'title_v', 'metadata_v', 'pinned', 'is_shared', 'is_private', 'parent_id',
  'is_sub_chat', 'budget_limit', 'budget_spent',
]);

export function kindNames(bits) {
  return Object.entries(KIND_BITS).filter(([, bit]) => (bits & bit) !== 0).map(([name]) => name);
}

/** One lane cursor `epoch:revision`; null when it belongs to another epoch or is malformed. */
export function parseLaneCursor(value, epoch) {
  if (typeof value !== 'string') return null;
  const [generation, revision, extra] = value.split(':');
  if (extra !== undefined || generation !== epoch || !/^\d{1,19}$/.test(revision ?? '')) return null;
  return BigInt(revision);
}

export function splitCursor(cursor) {
  if (typeof cursor !== 'string' || cursor.length > 160) return null;
  const parts = cursor.split('|');
  return parts.length === 2 ? parts : null;
}

export function formatCursor(scopeClock, scopeRevision, userClock, userRevision) {
  return `${scopeClock.epoch}:${scopeRevision}|${userClock.epoch}:${userRevision}`;
}

/** Combine every entry of one page per chat; removal and lane markers keep their latest revision. */
export function aggregateChanges(rows) {
  const byChat = new Map();
  let lastOpened;
  let dueSoon = false;
  for (const row of rows) {
    const kinds = Number(row.kinds);
    if (kinds & KIND_BITS.last_opened) {
      lastOpened = { chat_id: row.chat_id ?? null, revision: String(row.revision) };
    }
    if (kinds & KIND_BITS.due_soon) dueSoon = true;
    const entryKinds = kinds & ~(KIND_BITS.last_opened | KIND_BITS.due_soon);
    const key = row.hashed_chat_id ?? (row.chat_id ? hash(row.chat_id) : null);
    if (!entryKinds || !key) continue;
    const entry = byChat.get(key) ?? { chat_id: null, hashed_chat_id: key, kinds: 0 };
    entry.chat_id = entry.chat_id ?? row.chat_id ?? null;
    entry.kinds |= entryKinds;
    byChat.set(key, entry);
  }
  return { changes: [...byChat.values()], lastOpened, dueSoon };
}

function validateScopes(input) {
  if (!input || !SCOPE.test(input.scope ?? '') || !USER_SCOPE.test(input.user_scope ?? '')) {
    throw new Error('invalid_sync_scope');
  }
  const ownerHash = input.scope.split(':')[1];
  const userHash = input.user_scope.split(':')[1];
  // A personal scope always belongs to the same user as the user lane.
  if (input.scope.startsWith('personal:') && ownerHash !== userHash) throw new Error('invalid_sync_scope');
  return { ownerHash, userHash, team: input.scope.startsWith('team:') };
}

async function laneClock(trx, scope) {
  await trx('chat_sync_clocks').insert({ scope, revision: 0 }).onConflict('scope').ignore();
  // A committed clock value R implies every revision <= R is committed: writers
  // assign revisions while holding this row lock until their commit.
  return trx('chat_sync_clocks').where({ scope }).first();
}

async function laneFloor(trx, scope, current) {
  const earliest = await trx('chat_sync_changes').where({ scope }).min('revision as revision').first();
  return earliest?.revision == null ? current : BigInt(earliest.revision) - 1n;
}

export async function readClock(database, input) {
  validateScopes(input);
  return database.transaction(async trx => {
    const scopeClock = await laneClock(trx, input.scope);
    const userClock = await laneClock(trx, input.user_scope);
    return { cursor: formatCursor(scopeClock, BigInt(scopeClock.revision), userClock, BigInt(userClock.revision)) };
  });
}

function scopedChats(trx, owner) {
  const query = trx('chats');
  if (owner.team) return query.where('hashed_team_id', owner.ownerHash);
  return query.where('hashed_user_id', owner.ownerHash)
    .where(builder => builder.whereNull('hashed_team_id').orWhere('hashed_team_id', ''));
}

/** Read the bounded saved-item memory candidates for the personal due-soon set. */
export async function readSavedItems(trx, userHash) {
  return trx('user_app_settings_and_memories')
    .where('hashed_user_id', userHash)
    .where(builder => builder.whereNull('hashed_team_id').orWhere('hashed_team_id', ''))
    .where(builder => {
      for (const [appId, itemType] of SAVED_ITEM_CATEGORIES) builder.orWhere({ app_id: appId, item_type: itemType });
    })
    .orderBy('updated_at', 'desc').orderBy('id', 'asc').limit(DUE_SOON_SAVED_ITEM_LIMIT)
    .select('id', 'app_id', 'item_key', 'item_type', 'encrypted_item_json', 'encrypted_app_key',
      'created_at', 'updated_at', 'item_version', 'sequence_number');
}

export async function readChanges(database, input) {
  const owner = validateScopes(input);
  const limit = Number.isInteger(input.limit) ? Math.min(Math.max(input.limit, 1), MAX_LIMIT) : DEFAULT_LIMIT;
  return database.transaction(async trx => {
    const scopeClock = await laneClock(trx, input.scope);
    const userClock = await laneClock(trx, input.user_scope);
    const scopeCurrent = BigInt(scopeClock.revision);
    const userCurrent = BigInt(userClock.revision);
    const parts = splitCursor(input.cursor);
    let scopeAfter = parts ? parseLaneCursor(parts[0], scopeClock.epoch) : null;
    let userAfter = parts ? parseLaneCursor(parts[1], userClock.epoch) : null;
    if (scopeAfter !== null && (scopeAfter > scopeCurrent || scopeAfter < await laneFloor(trx, input.scope, scopeCurrent))) scopeAfter = null;
    if (userAfter !== null && (userAfter > userCurrent || userAfter < await laneFloor(trx, input.user_scope, userCurrent))) userAfter = null;
    if (scopeAfter === null || userAfter === null) {
      // Never infer deletions from a reset: the client cold-starts instead.
      return { reset: true, has_more: false, next_cursor: null, changes: [], chats: [], drafts: [], wrappers: [],
        existing_chat_ids: [], last_opened: null, due_soon_changed: false, saved_items: null };
    }
    // The small user lane (drafts, last opened, due-soon) is read first so the
    // overview converges before large Team backlogs.
    const userRows = await trx('chat_sync_changes').where({ scope: input.user_scope })
      .where('revision', '>', userAfter.toString()).where('revision', '<=', userCurrent.toString())
      .orderBy('revision').limit(limit + 1).select('revision', 'chat_id', 'hashed_chat_id', 'kinds');
    const userPage = userRows.slice(0, limit);
    const remaining = limit - userPage.length;
    const scopeRows = remaining > 0 ? await trx('chat_sync_changes').where({ scope: input.scope })
      .where('revision', '>', scopeAfter.toString()).where('revision', '<=', scopeCurrent.toString())
      .orderBy('revision').limit(remaining + 1).select('revision', 'chat_id', 'hashed_chat_id', 'kinds') : [];
    const scopePage = scopeRows.slice(0, remaining);
    const userNext = userPage.length ? BigInt(userPage.at(-1).revision) : userAfter;
    const scopeNext = scopePage.length ? BigInt(scopePage.at(-1).revision) : scopeAfter;
    const hasMore = userNext < userCurrent || scopeNext < scopeCurrent;

    const scoped = aggregateChanges(scopePage);
    const user = aggregateChanges(userPage);
    const draftChatIds = user.changes.filter(c => c.kinds & KIND_BITS.draft && c.chat_id).map(c => c.chat_id);
    const lastOpened = user.lastOpened;
    const chatIds = [...new Set([
      ...scoped.changes.map(c => c.chat_id), ...draftChatIds, lastOpened?.chat_id,
    ].filter(id => typeof id === 'string' && UUID.test(id)))];

    // Batched hydration: chats in this context, existence for draft targets,
    // the user's drafts, and caller-scoped key wrappers.
    const chats = chatIds.length ? await scopedChats(trx, owner).whereIn('id', chatIds).select(CHAT_FIELDS) : [];
    const inContext = new Set(chats.map(row => String(row.id)));
    const outside = draftChatIds.filter(id => UUID.test(id) && !inContext.has(id));
    const existing = outside.length ? await trx('chats').whereIn('id', outside).pluck('id') : [];
    const draftIds = [...new Set([...draftChatIds, ...chats.map(row => String(row.id))])];
    const drafts = draftIds.length ? await trx('drafts').where('hashed_user_id', owner.userHash)
      .whereIn('chat_id', draftIds).select('chat_id', 'encrypted_content', 'version') : [];
    const keyed = chats.filter(row => {
      const change = scoped.changes.find(c => c.chat_id === String(row.id));
      return change && (change.kinds & (KIND_BITS.keys | KIND_BITS.metadata));
    }).map(row => hash(String(row.id)));
    const wrappers = keyed.length ? await trx
      .select('*').from(trx('chat_key_wrappers')
        .whereIn('hashed_chat_id', keyed)
        .where(owner.team ? 'hashed_team_id' : 'hashed_user_id', owner.team ? owner.ownerHash : owner.userHash)
        .select('id', 'hashed_chat_id', 'hashed_user_id', 'key_type', 'hashed_project_id', 'hashed_plan_id',
          'hashed_team_id', 'team_key_epoch', 'encrypted_chat_key', 'wrapper_version', 'expires_at', 'created_at',
          trx.raw('row_number() OVER (PARTITION BY hashed_chat_id ORDER BY id DESC) AS window_position'))
        .as('ranked'))
      .where('window_position', '<=', WRAPPER_WINDOW + 1).orderBy('hashed_chat_id').orderBy('id', 'desc') : [];
    const dueSoonChanged = user.dueSoon && !owner.team;
    const savedItems = dueSoonChanged ? await readSavedItems(trx, owner.userHash) : null;
    return {
      reset: false,
      has_more: hasMore,
      next_cursor: formatCursor(scopeClock, scopeNext, userClock, userNext),
      changes: [
        ...scoped.changes.map(c => ({ ...c, lane: 'scope', kinds: kindNames(c.kinds) })),
        ...user.changes.map(c => ({ ...c, lane: 'user', kinds: kindNames(c.kinds) })),
      ],
      chats,
      drafts,
      wrappers,
      existing_chat_ids: existing.map(String),
      last_opened: user.lastOpened ? { chat_id: user.lastOpened.chat_id } : null,
      due_soon_changed: dueSoonChanged,
      saved_items: savedItems,
    };
  });
}

/** Cold-start overview inputs: the last opened chat row and the saved-item candidates. */
export async function readOverview(database, input) {
  const owner = validateScopes(input);
  const opened = typeof input.last_opened_chat_id === 'string' && UUID.test(input.last_opened_chat_id)
    ? input.last_opened_chat_id.toLowerCase() : null;
  return database.transaction(async trx => ({
    chat: opened ? (await scopedChats(trx, owner).where('id', opened).select(CHAT_FIELDS).first()) ?? null : null,
    saved_items: owner.team ? null : await readSavedItems(trx, owner.userHash),
  }));
}

/** Retention: drop entries older than the cursor lifetime in bounded batches. */
export async function pruneExpired(database, batch = 5000) {
  return database.raw(
    `DELETE FROM chat_sync_changes WHERE ctid IN (
       SELECT ctid FROM chat_sync_changes WHERE created_at < now() - interval '${RETENTION_DAYS} days' LIMIT ?)`,
    [batch],
  );
}
