// Generates ts_vectors.json from the TypeScript row policy (flag-off implementation):
//   node --experimental-strip-types packages/openmates-rust/src/web_persist/generate_ts_vectors.mjs
// messageRowPolicy.ts imports types only, so it loads without the app. The
// committed JSON is checked against the TypeScript by persistPolicyVectors.test.ts
// and replayed against Rust by web_persist/tests.rs.
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
	hasNewEncryptedFields, isContentDuplicate, isSafeToEvictMessage, shouldUpdateMessage,
} from '../../../../frontend/packages/ui/src/services/db/messageRowPolicy.ts';

const STATUSES = ['sending', 'waiting_for_upload', 'waiting_for_internet', 'queued', 'processing', 'streaming',
	'waiting_for_user', 'failed', 'delivered', 'synced', undefined, null, 'legacy_unknown'];
const DISPATCH = [undefined, null, 'queued', 'processing', 'paused'];
const row = (extra) => ({ message_id: 'm1', chat_id: 'c1', role: 'assistant', created_at: 100, content: 'hello', ...extra });

const shouldUpdate = [];
for (const es of STATUSES) for (const is of STATUSES) {
	shouldUpdate.push([row({ status: es }), row({ status: is })]);
}
for (const ed of DISPATCH) for (const id of DISPATCH) for (const es of ['queued', 'processing', 'synced']) for (const is of ['queued', 'processing', 'synced']) {
	shouldUpdate.push([row({ status: es, queue_dispatch_status: ed }), row({ status: is, queue_dispatch_status: id })]);
}
for (const er of [undefined, null, 0, 2, 5]) for (const ir of [undefined, null, 0, 2, 5, 1.5, 9007199254740992, '3']) for (const id of DISPATCH) {
	shouldUpdate.push([row({ status: 'queued', queue_revision: er }), row({ status: 'queued', queue_revision: ir, queue_dispatch_status: id })]);
}
for (const field of ['model_name', 'category', 'thinking_content', 'thinking_signature', 'thinking_token_count', 'has_thinking']) {
	shouldUpdate.push([row({ status: 'synced' }), row({ status: 'synced', [field]: field === 'has_thinking' ? true : 'x' })]);
	shouldUpdate.push([row({ status: 'synced', [field]: 'x' }), row({ status: 'synced', [field]: null })]);
	shouldUpdate.push([row({ status: 'synced', [field]: 'x' }), row({ status: 'synced', [field]: 'x' })]);
	shouldUpdate.push([row({ status: 'synced' }), row({ status: 'synced', content: 'other', [field]: 'x' })]);
}
shouldUpdate.push([row({ status: 'streaming', content: 'a' }), row({ status: 'streaming', content: 'ab' })]);
shouldUpdate.push([{ message_id: 'legacy', chat_id: 'c1', role: 'user' }, { message_id: 'legacy', chat_id: 'c1', role: 'user' }]);

const ENC = ['encrypted_content', 'encrypted_sender_name', 'encrypted_category', 'encrypted_model_name',
	'encrypted_thinking_content', 'encrypted_thinking_signature', 'encrypted_pii_mappings'];
const FILL = [undefined, null, '', 'cipher', 0];
const hasNew = [];
for (const name of ENC) for (const e of FILL) for (const i of FILL) {
	hasNew.push([row({ [name]: e }), row({ [name]: i })]);
}
hasNew.push([row({ encrypted_content: 'a' }), row({ encrypted_sender_name: 'b' })]);
hasNew.push([row({}), row({})]);

const dup = (e, i) => [row(e), row(i)];
const duplicate = [
	dup({ role: 'user' }, { role: 'user', message_id: 'm2' }),
	dup({ role: 'user' }, { role: 'user' }),
	dup({ role: 'user' }, { role: 'assistant' }),
	dup({}, { chat_id: 'c2', message_id: 'm2' }),
	dup({}, { message_id: 'm2', created_at: 159 }),
	dup({}, { message_id: 'm2', created_at: 160 }),
	dup({}, { message_id: 'm2', created_at: 41 }),
	dup({ role: 'user' }, { role: 'user', created_at: 399 }),
	dup({ role: 'user' }, { role: 'user', created_at: 400 }),
	dup({ encrypted_content: 'x' }, { message_id: 'm2', encrypted_content: 'x' }),
	dup({ encrypted_content: 'x' }, { message_id: 'm2', encrypted_content: 'y' }),
	dup({ encrypted_content: 'x', content: 'same' }, { message_id: 'm2', content: 'same' }),
	dup({ content: undefined }, { message_id: 'm2', content: undefined }),
	dup({ content: '' }, { message_id: 'm2', content: '' }),
	dup({ encrypted_sender_name: 'a' }, { message_id: 'm2', encrypted_sender_name: 'b' }),
	dup({ role: 'user', encrypted_sender_name: 'a', message_id: 'u' }, { role: 'user', encrypted_sender_name: 'b', message_id: 'u' }),
	dup({ created_at: undefined }, { message_id: 'm2' }),
	dup({ created_at: null }, { message_id: 'm2', created_at: 30 }),
	dup({ role: 'system' }, { role: 'system', message_id: 'm2' }),
];

const evict = [
	undefined, row({ status: 'synced' }), row({ status: 'sending' }), row({ status: 'delivered' }),
	row({ status: 'queued' }), row({ status: 'failed' }), row({}),
	row({ status: 'synced', pending_turn_preflight_v1: { a: 1 } }),
	row({ status: 'synced', pending_encrypted_turn_preflight_v1: 'x' }),
	row({ status: 'synced', pending_encrypted_embed_bundle_v1: [] }),
	row({ status: 'synced', pending_turn_preflight_v1: null }),
	row({ status: 'synced', pending_turn_preflight_v1: '' }),
	row({ status: 'synced', pending_encrypted_embed_bundle_v1: 0 }),
];

const json = (value) => (value === undefined ? null : value);
const vectors = {
	shouldUpdate: shouldUpdate.map(([existing, incoming]) => ({ existing, incoming, out: shouldUpdateMessage(existing, incoming) })),
	hasNewEncryptedFields: hasNew.map(([existing, incoming]) => ({ existing, incoming, out: hasNewEncryptedFields(existing, incoming) })),
	contentDuplicate: duplicate.map(([existing, incoming]) => ({ existing, incoming, out: isContentDuplicate(existing, incoming) })),
	safeToEvict: evict.map((message) => ({ message: json(message), out: isSafeToEvictMessage(message) })),
};
const target = fileURLToPath(new URL('./ts_vectors.json', import.meta.url));
// Round-trip through JSON so the file holds exactly what the wire carries.
writeFileSync(target, JSON.stringify(JSON.parse(JSON.stringify(vectors))).replace(/\},\{"existing"/g, "},\n{\"existing\"") + '\n');
console.log(Object.entries(vectors).map(([k, v]) => `${k}: ${v.length}`).join(', '));
