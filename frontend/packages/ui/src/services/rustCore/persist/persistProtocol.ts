/**
 * `persist` unit protocol of the shared Rust core Worker (unitPort.ts wire v1).
 *
 * IndexedDB stays the store; the row decisions of the `messages` store run in
 * shared Rust (packages/openmates-rust/src/web_persist/, port of
 * db/messageRowPolicy.ts). The page keeps the schema, transactions, encryption
 * and every read/write: it sends stored/incoming rows and gets decisions back.
 * Only a malformed payload refuses, with the fixed code `protocol`.
 *
 * spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
 */
import type { UnitProtocol } from '../host/unitPort';
import type { Message } from '../../../types/chat';

export interface PersistUnitProtocol extends UnitProtocol {
	/** `shouldUpdateMessage` for each stored/incoming pair, in order. */
	messageShouldUpdate: {
		request: { pairs: Array<{ existing: Message; incoming: Message }> };
		response: { results: boolean[] };
	};
	/** The two checks of `saveMessage` against the stored row. */
	messageSaveDecision: {
		request: { existing: Message; incoming: Message; incomingEncrypted: Message };
		response: { shouldUpdate: boolean; fillsEncrypted: boolean };
	};
	/** `findContentDuplicate`: index of the first candidate that duplicates `message`, or null. */
	messageContentDuplicate: {
		request: { candidates: Message[]; message: Message };
		response: { index: number | null };
	};
	/** `isSafeToEvictMessage` per stored row (`null` is a missing row). */
	messageSafeToEvict: {
		request: { messages: Array<Message | null> };
		response: { results: boolean[] };
	};
}

/** Worker module exports (snake_case, JSON text) of browser_persist.rs. */
export interface PersistBinding {
	persist_message_should_update(input: string): string;
	persist_message_save_decision(input: string): string;
	persist_message_content_duplicate(input: string): string;
	persist_message_safe_to_evict(input: string): string;
}

/** Op name -> binding export; the unit installs one handler per entry. */
export const PERSIST_OPS: Readonly<Record<keyof PersistUnitProtocol & string, keyof PersistBinding>> = {
	messageShouldUpdate: 'persist_message_should_update',
	messageSaveDecision: 'persist_message_save_decision',
	messageContentDuplicate: 'persist_message_content_duplicate',
	messageSafeToEvict: 'persist_message_safe_to_evict',
};

export function isPersistBinding(value: unknown): value is PersistBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return Object.values(PERSIST_OPS).every((name) => typeof binding[name] === 'function');
}
