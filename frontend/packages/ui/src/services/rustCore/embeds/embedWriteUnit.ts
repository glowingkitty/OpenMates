/**
 * `embedWrite` namespace installer of the shared Rust core Worker (U9).
 *
 * One installer call = one Rust embed write session (`BrowserEmbedWriter`)
 * under the bound generation, next to the Worker-side `chats_db` rows it
 * writes. Rust owns key choice, every ciphertext, row/payload shapes and the
 * revision-history decisions (embedWriteAdapter.ts sequences them); this unit
 * persists the prepared rows (embedWriteIdb.ts, existing stores, no schema
 * change) and returns only what the page still has to send or render: the
 * store payload, server key wrappers, ref registration and history payloads.
 * Local key wrappers never leave the Worker. Keys enter only as ciphertext
 * (master-wrapped chat keys, wrapper rows, parent-wrapped child keys) plus the
 * page's non-extractable master CryptoKey (`init`, once per unit) and chat keys
 * the page's write guard already validated (`adoptPageChatKey`, zeroed). Stored
 * rows are opened with keys resolved here (embedKeyResolution.ts).
 *
 * The page performs the network IO (WebSocket store/diff sends, canonical
 * HTTP history reads) between calls. Unbind disposes the session (the page end
 * is ended by the shared-core supervisor); a malformed request or a second
 * `init` is refused with a fixed code.
 */
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import {
	prepareProcessingUpdate,
	prepareStreamCompletion,
	type EmbedWriteFunctions,
	type EmbedWriterPort,
	type EncryptedDiffRow,
	type PreparedEmbedWrite
} from '../embedWriteAdapter';
import { getEmbedDiffs, persistPreparedEmbedWrite, putEmbedDiff } from '../embedWriteIdb';
import { isEmbedUnitClose, type EmbedWriteProtocol, type PersistedEmbedWrite } from './embedDataProtocol';
import { createWorkerChatsDb, type ChatsDbOpener } from './embedWorkerIdb';
import { createEmbedKeyHandlers, type EmbedKeyResolverPort } from './embedKeyResolution';
import { createChildRevisionHandlers } from './childRevisionHandlers';
import type { ChildRevisionFunctions, ChildRevisionWriterPort } from './childRevisionProtocol';

type WriterSession = EmbedWriterPort & EmbedKeyResolverPort & ChildRevisionWriterPort & { free?: () => void };
export interface EmbedWriteBinding extends EmbedWriteFunctions, ChildRevisionFunctions {
	BrowserEmbedWriter: new (master: CryptoKey) => WriterSession;
}

const CODE = /^[a-z][a-z0-9_]{0,63}$/;

export function isEmbedWriteBinding(value: unknown): value is EmbedWriteBinding {
	const binding = value as Partial<EmbedWriteBinding> | null;
	return typeof binding?.BrowserEmbedWriter === 'function' && typeof binding.embed_classify_canonical_read === 'function'
		&& typeof binding.embed_history_head_version === 'function';
}

function text(value: unknown, field: string): string {
	if (typeof value !== 'string' || value.length === 0) throw new UnitRefusal(`embed_write_bad_${field}`);
	return value;
}
function record(value: unknown, field: string): Record<string, unknown> {
	if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new UnitRefusal(`embed_write_bad_${field}`);
	return value as Record<string, unknown>;
}
function list(value: unknown, field: string): unknown[] {
	if (!Array.isArray(value)) throw new UnitRefusal(`embed_write_bad_${field}`);
	return value;
}
/** Tag check, not instanceof: the key arrives by structured clone (cross-realm safe). */
function isCryptoKey(value: unknown): value is CryptoKey {
	return Object.prototype.toString.call(value) === '[object CryptoKey]';
}
/** Rust rejects with a stable code string (browser_embed_write.rs); keep it, never internal text. */
async function rust<T>(call: () => T | Promise<T>): Promise<T> {
	try {
		return await call();
	} catch (error) {
		if (error instanceof UnitRefusal) throw error;
		const code = typeof error === 'string' ? error : error instanceof Error ? error.message : '';
		throw new UnitRefusal(CODE.test(code) ? code : 'embed_write_failed');
	}
}
function withoutLocalWrappers(prepared: PreparedEmbedWrite): PersistedEmbedWrite {
	const persisted: Partial<PreparedEmbedWrite> = { ...prepared };
	delete persisted.local_key_wrappers;
	return persisted as PersistedEmbedWrite;
}

/** The `embedWrite` handlers over one binding and Worker DB (exported for in-process tests). */
export function createEmbedWriteHandlers(binding: EmbedWriteBinding, openDb: ChatsDbOpener): {
	handlers: UnitHandlers<EmbedWriteProtocol>; dispose(): void;
} {
	let writer: WriterSession | null = null;
	let disposed = false;
	const session = () => {
		if (disposed || !writer) throw new UnitRefusal('embed_write_not_initialized');
		return writer;
	};
	const persist = async (prepared: PreparedEmbedWrite, normalizedType: string) => {
		await persistPreparedEmbedWrite(await openDb(), prepared, () => normalizedType);
		return withoutLocalWrappers(prepared);
	};
	const storeRows = async (rows: EncryptedDiffRow[]) => {
		const db = await openDb();
		for (const row of rows) await putEmbedDiff(db, row);
		return rows.length;
	};
	const handlers: UnitHandlers<EmbedWriteProtocol> = {
		async init(payload) {
			const masterKey = record(payload, 'request').masterKey;
			if (!isCryptoKey(masterKey) || masterKey.extractable) throw new UnitRefusal('embed_write_bad_master_key');
			if (disposed || writer) throw new UnitRefusal('embed_write_already_initialized');
			writer = await rust(() => new binding.BrowserEmbedWriter(masterKey));
			return null;
		},
		async adoptChatKey(payload) {
			const request = record(payload, 'request');
			await rust(() => session().adopt_chat_key(text(request.chatId, 'chat_id'), text(request.encryptedChatKey, 'chat_key')));
			return null;
		},
		async adoptEmbedKeyWrapper(payload) {
			const request = record(payload, 'request');
			const row = JSON.stringify(record(request.row, 'row'));
			await rust(() => session().adopt_embed_key_wrapper(text(request.embedId, 'embed_id'), text(request.chatId, 'chat_id'), row));
			return null;
		},
		async adoptChildEmbedKey(payload) {
			const request = record(payload, 'request');
			await rust(() => session().adopt_child_embed_key(text(request.childId, 'child_id'), text(request.parentId, 'parent_id'),
				text(request.wrappedByParent, 'wrapped_key')));
			return null;
		},
		hasKeys(payload) {
			const request = record(payload, 'request');
			const port = session();
			return {
				chat: typeof request.chatId === 'string' && port.has_chat_key(request.chatId),
				embed: typeof request.embedId === 'string' && port.has_embed_key(request.embedId)
			};
		},
		async prepareStreamCompletion(payload) {
			const request = record(payload, 'request');
			const input = record(request.payload, 'payload') as EmbedWriteProtocol['prepareStreamCompletion']['request']['payload'];
			const normalizedType = text(request.normalizedType, 'type');
			const prepared = await rust(() => prepareStreamCompletion(session(), input));
			if (prepared.local_entry.type !== input.type) throw new UnitRefusal('embed_write_type_mismatch');
			return persist(prepared, normalizedType);
		},
		async prepareProcessingUpdate(payload) {
			const request = record(payload, 'request');
			const optional = (value: unknown) => (typeof value === 'string' ? value : undefined);
			const normalizedType = text(request.normalizedType, 'type');
			const prepared = await rust(() => prepareProcessingUpdate(session(), record(request.existing, 'existing'),
				text(request.chatId, 'chat_id'), optional(request.userId), optional(request.messageId), normalizedType));
			return persist(prepared, normalizedType);
		},
		async reconcileSealedHistory(payload) {
			const request = record(payload, 'request');
			const embedId = text(request.embedId, 'embed_id');
			const rows = JSON.stringify(list(request.rows, 'rows'));
			if (typeof request.declaredVersion !== 'number') throw new UnitRefusal('embed_write_bad_version');
			const existing = JSON.stringify(await getEmbedDiffs(await openDb(), embedId));
			const declared = request.declaredVersion;
			return storeRows(JSON.parse(await rust(() => session().reconcile_sealed_history(embedId, rows, declared, existing))));
		},
		async encryptHistoryRow(payload) {
			const request = record(payload, 'request');
			const embedId = text(request.embedId, 'embed_id');
			const row = JSON.stringify(record(request.row, 'row'));
			const encrypted = await rust(() => session().encrypt_history_row(embedId, row, text(request.hashedUserId, 'user_id')));
			if (encrypted === undefined) return null;
			const { local_row, server_payload } = JSON.parse(encrypted) as { local_row: EncryptedDiffRow; server_payload: Record<string, unknown> };
			await storeRows([local_row]);
			return server_payload;
		},
		async adoptCanonicalRow(payload) {
			const request = record(payload, 'request');
			const embedId = text(request.embedId, 'embed_id');
			const row = JSON.stringify(record(request.row, 'row'));
			const adopted = JSON.parse(await rust(() => session().adopt_canonical_row(embedId, JSON.stringify(request.page), row))) as EncryptedDiffRow;
			await storeRows([adopted]);
			return adopted;
		},
		async verifyCanonicalHead(payload) {
			const request = record(payload, 'request');
			const embedId = text(request.embedId, 'embed_id');
			const rows = JSON.stringify(list(request.rows, 'rows'));
			return storeRows(JSON.parse(await rust(() => session().verify_canonical_head(embedId, JSON.stringify(request.page), rows))));
		},
		async reconstructVersions(payload) {
			const embedId = text(record(payload, 'request').embedId, 'embed_id');
			const rows = JSON.stringify(await getEmbedDiffs(await openDb(), embedId));
			return rust(() => session().reconstruct_versions(embedId, rows));
		},
		...createEmbedKeyHandlers(session, openDb, rust),
		...createChildRevisionHandlers({ session, binding, openDb, rust }),
		async classifyCanonicalRead(payload) {
			const request = record(payload, 'request');
			const { status, version, durableHead, body } = request;
			if (typeof status !== 'number' || typeof version !== 'number' || typeof durableHead !== 'boolean') {
				throw new UnitRefusal('embed_write_bad_request');
			}
			const bodyJson = body === undefined || body === null ? undefined : JSON.stringify(body);
			return rust(() => binding.embed_classify_canonical_read(status, bodyJson, version, durableHead));
		},
		async historyHeadVersion(payload) {
			const request = record(payload, 'request');
			const rows = JSON.stringify(list(request.rows, 'rows'));
			const head = await rust(() => binding.embed_history_head_version(rows, text(request.embedId, 'embed_id')));
			return head ?? null;
		},
		forgetChat(payload) {
			session().forget_chat(text(record(payload, 'request').chatId, 'chat_id'));
			return null;
		},
		clear() {
			session().clear();
			return null;
		}
	};
	return {
		handlers,
		dispose() {
			if (disposed) return;
			disposed = true;
			writer?.clear();
			writer?.free?.();
			writer = null;
		}
	};
}

export function createEmbedWriteUnitInstaller(openDatabase: () => { open: ChatsDbOpener; close(): void } = () => createWorkerChatsDb()) {
	return (context: UnitInstallContext): (() => void) => {
		if (context.ports.length !== 1 || context.principal === null || !isEmbedWriteBinding(context.binding)) throw new Error('unavailable');
		const port = context.ports[0];
		const database = openDatabase();
		const { handlers, dispose: disposeSession } = createEmbedWriteHandlers(context.binding, database.open);
		const stopServing = serveUnitPort<EmbedWriteProtocol>(port, handlers);
		let disposed = false;
		const dispose = () => {
			if (disposed) return;
			disposed = true;
			port.removeEventListener('message', control);
			stopServing();
			disposeSession();
			database.close();
			port.close();
		};
		function control(event: MessageEvent<unknown>): void {
			if (isEmbedUnitClose(event.data)) dispose();
		}
		port.addEventListener('message', control);
		context.signal.addEventListener('abort', () => dispose(), { once: true });
		return () => dispose();
	};
}

export const installEmbedWriteUnit = createEmbedWriteUnitInstaller();
