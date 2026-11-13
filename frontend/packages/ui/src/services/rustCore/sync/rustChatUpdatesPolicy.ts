/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) chat-update and recovery helpers: the page
 * adapter over the shared Rust core Worker `sync` unit. Loaded only through
 * chatSyncUpdatesPolicy.ts' guarded branches, so default builds never bundle it.
 *
 * Rust (packages/openmates-rust/src/web_sync/updates.rs) decides the assistant
 * notification preview and whether the thinking fields of a recovered message
 * are valid; the page keeps the plaintext and copies only the keys Rust
 * admitted. Signatures match chatSyncUpdatesLogic.ts; there is no TypeScript
 * fallback.
 */
import type { Message } from '../../../types/chat';
import { THINKING_FIELD_ERRORS, thinkingFieldsRequest } from '../../chatSyncUpdatesLogic';
import { syncCall } from './syncUnitClient';

/** Notification preview of an assistant reply (UTF-16 units rebuilt into a string). */
export async function messagePreview(content: string | undefined): Promise<string> {
	const { units } = await syncCall('messagePreview', { content: content ?? null });
	// A cut inside a surrogate pair stays a lone surrogate, exactly like substring().
	let text = '';
	for (let offset = 0; offset < units.length; offset += 4096) {
		text += String.fromCharCode(...units.slice(offset, offset + 4096));
	}
	return text;
}

/** Validated thinking fields of a recovered payload; throws the TypeScript error texts. */
export async function recoveredThinkingFields(payload: Record<string, unknown>): Promise<Partial<Message>> {
	const outcome = await syncCall('thinkingFields', { payload: thinkingFieldsRequest(payload) });
	if ('code' in outcome) throw new Error(THINKING_FIELD_ERRORS[outcome.code]);
	const fields: Record<string, unknown> = {};
	for (const key of outcome.keys) fields[key] = payload[key];
	return fields as Partial<Message>;
}
