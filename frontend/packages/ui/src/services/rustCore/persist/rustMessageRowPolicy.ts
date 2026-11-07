/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) message-row decisions: the page adapter over
 * the shared Rust core Worker `persist` unit. Loaded only by the guarded branches
 * of db/messageOperations.ts, so default builds never bundle it.
 *
 * Rust (packages/openmates-rust/src/web_persist/message_policy.rs) decides which
 * stored/incoming version wins, whether new encrypted fields force a write, which
 * stored row duplicates an incoming one and which cached rows may be evicted.
 * IndexedDB reads, writes and encryption stay on the page; only the fields the
 * policy reads cross the Worker boundary, never whole rows (embed bundles,
 * ciphertext of unrelated fields). There is no TypeScript fallback.
 *
 * spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
 */
import type { Message } from '../../../types/chat';
import { persistCall } from './persistUnitClient';

type Row = Record<string, unknown>;

const UPDATE_FIELDS = [
	'status', 'queue_dispatch_status', 'queue_revision', 'content', 'model_name', 'category',
	'thinking_content', 'thinking_signature', 'thinking_token_count', 'has_thinking',
] as const;
const ENCRYPTED_FIELDS = [
	'encrypted_content', 'encrypted_sender_name', 'encrypted_category', 'encrypted_model_name',
	'encrypted_thinking_content', 'encrypted_thinking_signature', 'encrypted_pii_mappings',
] as const;
const DUPLICATE_FIELDS = [
	'message_id', 'chat_id', 'role', 'created_at', 'content', 'encrypted_content', 'encrypted_sender_name',
] as const;
const EVICT_FIELDS = [
	'status', 'pending_turn_preflight_v1', 'pending_encrypted_turn_preflight_v1', 'pending_encrypted_embed_bundle_v1',
] as const;

/** The listed fields of `message` that are present (a missing field is JS `undefined`). */
function pick(message: Message, fields: readonly string[]): Message {
	const source = message as unknown as Row;
	const out: Row = {};
	for (const field of fields) if (source[field] !== undefined) out[field] = source[field];
	return out as unknown as Message;
}

/** `shouldUpdateMessage` for each stored/incoming pair, in order. */
export async function rustShouldUpdateMessages(pairs: Array<{ existing: Message; incoming: Message }>): Promise<boolean[]> {
	if (pairs.length === 0) return [];
	const fields = [...UPDATE_FIELDS];
	const { results } = await persistCall('messageShouldUpdate', {
		pairs: pairs.map(({ existing, incoming }) => ({ existing: pick(existing, fields), incoming: pick(incoming, fields) })),
	});
	return results;
}

export async function rustShouldUpdateMessage(existing: Message, incoming: Message): Promise<boolean> {
	return (await rustShouldUpdateMessages([{ existing, incoming }]))[0];
}

/** The update and fill-encrypted-fields checks `saveMessage` runs against the stored row. */
export function rustSaveDecision(
	existing: Message, incoming: Message, incomingEncrypted: Message,
): Promise<{ shouldUpdate: boolean; fillsEncrypted: boolean }> {
	return persistCall('messageSaveDecision', {
		existing: pick(existing, [...UPDATE_FIELDS, ...ENCRYPTED_FIELDS]),
		incoming: pick(incoming, UPDATE_FIELDS),
		incomingEncrypted: pick(incomingEncrypted, ENCRYPTED_FIELDS),
	});
}

/** `findContentDuplicate`'s scan: the first stored message duplicating `message`, or null. */
export async function rustFindContentDuplicate(candidates: Message[], message: Message): Promise<Message | null> {
	if (candidates.length === 0) return null;
	const { index } = await persistCall('messageContentDuplicate', {
		candidates: candidates.map((candidate) => pick(candidate, DUPLICATE_FIELDS)),
		message: pick(message, DUPLICATE_FIELDS),
	});
	return index === null ? null : candidates[index];
}

/** `isSafeToEvictMessage` for a stored row (`undefined` is a missing row). */
export async function rustIsSafeToEvictMessage(message: Message | undefined): Promise<boolean> {
	const { results } = await persistCall('messageSafeToEvict', { messages: [message ? pick(message, EVICT_FIELDS) : null] });
	return results[0];
}
