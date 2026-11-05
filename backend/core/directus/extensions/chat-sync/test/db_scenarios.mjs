/**
 * Engineering DB scenario for the chat sync feed, run by
 * backend/tests/test_chat_sync_feed_db.py inside a disposable Directus image
 * against a disposable PostgreSQL with migrate_chat_sync_feed.sql applied.
 * Prints one JSON document with the observed pages; assertions live in pytest.
 */
import { createHash, randomUUID } from 'node:crypto';
import { readChanges, readClock, readOverview } from '../src/operations.js';

const knexModule = await import(process.env.KNEX_PATH);
const knex = (knexModule.default ?? knexModule)({ client: 'pg', connection: process.env.DATABASE_URL });
const hash = value => createHash('sha256').update(value).digest('hex');
const user = randomUUID();
const team = randomUUID();
const U = hash(user);
const T = hash(team);
const personal = { scope: `personal:${U}`, user_scope: `user:${U}` };
const teamScope = { scope: `team:${T}`, user_scope: `user:${U}` };
const out = {};
let queries = 0;
knex.on('query', () => { queries += 1; });

await knex('directus_users').insert({ id: user, last_opened: '/chat/new' });
const cold = await readClock(knex, personal);
out.cold_cursor_parts = cold.cursor.split('|').length;

const chats = [];
for (let index = 0; index < 5; index += 1) {
  const id = randomUUID();
  chats.push(id);
  await knex('chats').insert({ id, hashed_user_id: U, encrypted_title: `cipher-${index}`, messages_v: 0, title_v: 1,
    metadata_v: 1, last_edited_overall_timestamp: 100 + index, pinned: false });
}
await knex('messages').insert({ id: randomUUID(), chat_id: chats[0], hashed_user_id: U, encrypted_content: 'cipher-msg' });
await knex('drafts').insert({ id: randomUUID(), chat_id: chats[1], hashed_user_id: U, encrypted_content: 'cipher-draft', version: 3 });
await knex('chat_key_wrappers').insert({ id: randomUUID(), hashed_chat_id: hash(chats[2]), hashed_user_id: U, key_type: 'master', encrypted_chat_key: 'wrapped' });
await knex('directus_users').where({ id: user }).update({ last_opened: `/chat/${chats[3]}` });
await knex('reminders').insert({ id: randomUUID(), hashed_user_id: U, trigger_at: 2000000000, status: 'pending', target_type: 'embed' });
await knex('user_app_settings_and_memories').insert({ id: randomUUID(), hashed_user_id: U, app_id: 'events', item_type: 'saved_events', item_key: 'k', encrypted_item_json: 'cipher-item', updated_at: 5 });

queries = 0;
const first = await readChanges(knex, { ...personal, cursor: cold.cursor, limit: 4 });
out.first = { has_more: first.has_more, kinds: first.changes.map(c => [c.lane, c.kinds]), queries };
let cursor = first.next_cursor;
const pages = [first];
while (pages.at(-1).has_more && pages.length < 20) {
  const page = await readChanges(knex, { ...personal, cursor, limit: 4 });
  pages.push(page);
  cursor = page.next_cursor;
}
const all = pages.flatMap(page => page.changes);
out.pages = pages.length;
out.chat_ids_seen = [...new Set(all.map(c => c.chat_id).filter(Boolean))].sort();
out.expected_chat_ids = [...chats].sort();
out.last_opened = pages.map(p => p.last_opened).filter(Boolean).at(-1) ?? null;
out.expected_last_opened = chats[3];
out.due_soon_changed = pages.some(p => p.due_soon_changed);
out.saved_items = pages.flatMap(p => p.saved_items ?? []).map(item => item.encrypted_item_json);
out.drafts = pages.flatMap(p => p.drafts).map(d => [d.chat_id === chats[1], d.encrypted_content, d.version]);
out.wrappers = pages.flatMap(p => p.wrappers).map(w => w.hashed_chat_id === hash(chats[2]));
out.message_fields_absent = pages.every(p => JSON.stringify(p).indexOf('cipher-msg') === -1);

// Replay from the same cursor is idempotent and empty once caught up.
const caughtUp = await readChanges(knex, { ...personal, cursor, limit: 50 });
out.caught_up = { changes: caughtUp.changes.length, has_more: caughtUp.has_more };

// Move one chat to the Team and delete another.
await knex('chats').where({ id: chats[4] }).update({ hashed_team_id: T });
await knex('chats').where({ id: chats[0] }).delete();
const after = await readChanges(knex, { ...personal, cursor, limit: 50 });
out.after_move_delete = after.changes.map(c => [c.chat_id, c.hashed_chat_id === hash(c.chat_id ?? '') || c.chat_id === null, c.kinds]);
out.expected_moved = chats[4];
out.expected_deleted = chats[0];
out.moved_row_hidden = after.chats.every(row => String(row.id) !== chats[4]);
const teamClock = await readClock(knex, teamScope);
const teamCold = await readChanges(knex, { ...teamScope, cursor: `${teamClock.cursor.split('|')[0].split(':')[0]}:0|${teamClock.cursor.split('|')[1]}`, limit: 50 });
out.team_page = teamCold.changes.map(c => [c.chat_id, c.kinds]);
out.team_rows = teamCold.chats.map(row => String(row.id));

// Reset cases: foreign epoch, cursor ahead, malformed.
const [scopePart, userPart] = cursor.split('|');
const [epoch] = scopePart.split(':');
out.resets = [
  (await readChanges(knex, { ...personal, cursor: `${randomUUID()}:1|${userPart}` })).reset,
  (await readChanges(knex, { ...personal, cursor: `${epoch}:999999|${userPart}` })).reset,
  (await readChanges(knex, { ...personal, cursor: 'garbage' })).reset,
  (await readChanges(knex, { ...personal, cursor: null })).reset,
];
// Retention floor: pruned history resets old cursors but not current ones.
await knex('chat_sync_changes').where({ scope: personal.scope }).where('revision', '<=', 2).delete();
out.expired_reset = (await readChanges(knex, { ...personal, cursor: `${epoch}:1|${userPart}` })).reset;
out.current_not_reset = (await readChanges(knex, { ...personal, cursor: after.next_cursor })).reset;

// Cold-start overview inputs.
const overview = await readOverview(knex, { ...personal, last_opened_chat_id: chats[3] });
out.overview = { chat: overview.chat ? String(overview.chat.id) === chats[3] : false, saved_items: (overview.saved_items ?? []).length };
const teamOverview = await readOverview(knex, { ...teamScope, last_opened_chat_id: chats[3] });
out.team_overview = { chat: teamOverview.chat, saved_items: teamOverview.saved_items };

console.log(JSON.stringify(out));
await knex.destroy();
