/**
 * Worker-side embed key resolution of the `embedWrite` unit (U9 slice 2;
 * VITE_OPENMATES_RUST_CORE builds only). Replaces the page's
 * `embedStore.getEmbedKey` unwrap and key caches for stored-row reads: the
 * Rust `BrowserEmbedWriter` session plans the TS lookup order (cached key,
 * first master wrapper, the requested chat's wrapper, other chat wrappers,
 * legacy parent inheritance; openmates_sdk `client::embed_write::KeyLookup`)
 * and holds every key. This module is only the IndexedDB adapter: it reads the
 * `embed_keys` rows and the `parent_embed_id` of legacy children next to the
 * data and passes them to Rust. Keys and wrappers never return to the page;
 * the page receives decrypted fields or a typed per-row code plus the chat
 * hashes whose validated chat key it may install (`adoptPageChatKey`).
 */
import { UnitRefusal, type UnitHandlers } from '../host/unitPort';
import { getEmbedEntry, getEmbedKeyRows } from '../embedWriteIdb';
import { EMBED_DATA_MAX_ITEMS, type EmbedWriteProtocol, type OpenedEmbedFields, type StoredRowResult } from './embedDataProtocol';
import type { ChatsDbOpener } from './embedWorkerIdb';

/** Rust key-resolution exports of `BrowserEmbedWriter` (browser_embed_keys.rs). */
export interface EmbedKeyResolverPort {
	install_chat_key(chatId: string, key: Uint8Array): void;
	resolve_embed_key(embedId: string, hashedChatId: string | undefined, rowsJson: string): Promise<string>;
	inherit_parent_embed_key(childId: string, parentId: string): boolean;
	derive_early_parent_key(embedId: string, chatId: string): boolean;
	open_embed_fields(embedId: string, content: string | undefined, type: string | undefined, preview: string | undefined): Promise<unknown>;
}

type KeyHandlers = Pick<UnitHandlers<EmbedWriteProtocol>, 'adoptPageChatKey' | 'deriveEarlyKey' | 'openStoredRows'>;
type KeyState = { loaded: true } | { loaded: false; code: string; pending: string[] };

/** Legacy parent chains are short; a longer chain is refused rather than walked. */
const MAX_PARENT_DEPTH = 8;

async function sha256Hex(value: string): Promise<string> {
	const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
	return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function optionalText(value: unknown): string | undefined {
	return typeof value === 'string' && value.length > 0 ? value : undefined;
}

function opened(value: unknown): OpenedEmbedFields {
	const fields = value as Record<string, unknown> | null;
	const nullableText = (field: unknown) => field === null || typeof field === 'string';
	if (typeof fields !== 'object' || fields === null || typeof fields.content_failed !== 'boolean'
		|| !nullableText(fields.content) || !nullableText(fields.type) || !nullableText(fields.text_preview)) {
		throw new UnitRefusal('embed_write_protocol');
	}
	return fields as unknown as OpenedEmbedFields;
}

/**
 * Key-resolution handlers over the unit's Rust session. `rust` maps a Rust
 * rejection to its stable code (the unit's own wrapper); `session` throws
 * `embed_write_not_initialized` before `init`.
 */
export function createEmbedKeyHandlers(
	session: () => EmbedKeyResolverPort,
	openDb: ChatsDbOpener,
	rust: <T>(call: () => T | Promise<T>) => Promise<T>
): KeyHandlers {
	async function resolve(embedId: string, hashedChatId: string | undefined, depth: number): Promise<KeyState> {
		const db = await openDb();
		const rows = await getEmbedKeyRows(db, await sha256Hex(embedId));
		const state = JSON.parse(await rust(() => session().resolve_embed_key(embedId, hashedChatId, JSON.stringify(rows)))) as {
			state: 'loaded' | 'no_wrappers' | 'unavailable'; pending_chat_hashes?: string[];
		};
		if (state.state === 'loaded') return { loaded: true };
		if (state.state === 'unavailable') return { loaded: false, code: 'embed_key_unavailable', pending: state.pending_chat_hashes ?? [] };
		// No wrappers: a legacy child shares its parent's key (TS getEmbedKey parent fallback).
		const parentId = optionalText((await getEmbedEntry(db, `embed:${embedId}`))?.parent_embed_id);
		if (!parentId || parentId === embedId || depth >= MAX_PARENT_DEPTH) return { loaded: false, code: 'embed_key_unavailable', pending: [] };
		const parent = await resolve(parentId, hashedChatId, depth + 1);
		if (!parent.loaded) return parent;
		return session().inherit_parent_embed_key(embedId, parentId) ? { loaded: true } : { loaded: false, code: 'embed_key_unavailable', pending: [] };
	}

	return {
		async adoptPageChatKey(payload) {
			const request = payload as { chatId?: unknown; key?: unknown } | null;
			const key = request?.key;
			// Tag check, not instanceof: the bytes arrive by structured clone.
			if (Object.prototype.toString.call(key) !== '[object Uint8Array]') throw new UnitRefusal('embed_write_bad_chat_key');
			const bytes = key as Uint8Array;
			try {
				const chatId = optionalText(request?.chatId);
				if (!chatId) throw new UnitRefusal('embed_write_bad_chat_id');
				await rust(() => session().install_chat_key(chatId, bytes));
			} finally {
				bytes.fill(0);
			}
			return null;
		},
		async deriveEarlyKey(payload) {
			const request = payload as { embedId?: unknown; chatId?: unknown } | null;
			const embedId = optionalText(request?.embedId);
			const chatId = optionalText(request?.chatId);
			if (!embedId || !chatId) throw new UnitRefusal('embed_write_bad_request');
			return rust(() => session().derive_early_parent_key(embedId, chatId));
		},
		async openStoredRows(payload) {
			const rows = (payload as { rows?: unknown } | null)?.rows;
			if (!Array.isArray(rows) || rows.length > EMBED_DATA_MAX_ITEMS) throw new UnitRefusal('embed_write_bad_request');
			const results: StoredRowResult[] = [];
			for (const raw of rows as Record<string, unknown>[]) {
				const embedId = optionalText(raw?.embedId);
				if (!embedId) throw new UnitRefusal('embed_write_bad_embed_id');
				const state = await resolve(embedId, optionalText(raw.hashedChatId), 0);
				if (!state.loaded) {
					results.push({ ok: false, code: state.code, pendingChatHashes: state.pending });
					continue;
				}
				const fields = await rust(() => session().open_embed_fields(embedId, optionalText(raw.encrypted_content),
					optionalText(raw.encrypted_type), optionalText(raw.encrypted_text_preview)));
				results.push({ ok: true, fields: opened(fields) });
			}
			return results;
		}
	};
}
