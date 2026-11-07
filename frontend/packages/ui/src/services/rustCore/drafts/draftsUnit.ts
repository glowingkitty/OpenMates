/**
 * `drafts` namespace installer of the shared Rust core Worker.
 *
 * Draft policy (encryption, versioning, closed IndexedDB predicates, durable
 * encrypted sync intent, readback) is shared Rust (`prepare_local_draft_with_preview`,
 * `remote_payload`, `acknowledge_transport`). This unit only marshals: it runs the
 * Rust calls on the ADMITTED client of the bound history `core` lease (borrowed
 * via coreClientBorrow, never a second client or admission) and executes Rust's
 * IndexedDB plans on the existing chats_db in this realm, next to the data.
 *
 * Borrows are short (local write, transport ack); the network send happens on
 * the page's existing socket with the ciphertext payload Rust returns, so the
 * shared client is never held across network IO.
 *
 * Bound namespace only (one port per generation). Disposed when the generation
 * ends; prepared writes not yet acknowledged are freed (their durable intent
 * stays in pending_sync_changes for the page's offline replay).
 */
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { serveUnitPort, UnitRefusal } from '../host/unitPort';
import { createDraftEffectHandler } from '../browserDraftIO';
import { parseBrowserDraftPlan } from '../browserDraftProtocol';
import type { BrowserDraftEffectHandler } from '../browserDraftProtocol';
import { borrowCoreClient } from './coreClientBorrow';
import type { CoreBorrowRefusal, CoreClientBorrow } from './coreClientBorrow';
import { isDraftRoutingCode, validDraftRemotePayload, validDraftResourceRequest, validDraftSaveRequest } from './draftsProtocol';
import type { DraftsProtocol } from './draftsProtocol';

/** Bounded wait for the history dispatcher to become idle before routing TS. */
export const DRAFT_BORROW_TIMEOUT_MS = 3_000;
/** Prepared, not yet acknowledged writes kept per unit (one editor saves serially). */
export const MAX_PREPARED_DRAFTS = 8;
const CHATS_DB = 'chats_db';

interface DraftsPublication { take(client: unknown): string; free(): void }
interface DraftsWrite {
	local_result(client: unknown): string;
	remote_payload(client: unknown): string;
	acknowledge_transport(client: unknown, effect: (plan: string) => Promise<string>): Promise<DraftsPublication>;
	free(): void;
}
interface DraftsClient {
	prepare_local_draft_with_preview(handle: string, generation: number, owner: string, chatId: string, markdown: string,
		preview: string, scope: string, now: number, effect: (plan: string) => Promise<string>): Promise<DraftsWrite>;
}

export interface DraftsUnitDeps {
	borrow(principal: string, signal: AbortSignal): Promise<CoreClientBorrow | CoreBorrowRefusal>;
	effects(current: () => void): BrowserDraftEffectHandler;
	resourceId(): string;
}

const defaultDeps: DraftsUnitDeps = {
	borrow: (principal, signal) => borrowCoreClient(principal, signal, DRAFT_BORROW_TIMEOUT_MS),
	effects: (current) => createDraftEffectHandler({
		current() {},
		open: () => indexedDB.open(CHATS_DB),
		transaction: (db, stores, mode) => db.transaction(stores, mode)
	}, current),
	resourceId: () => crypto.randomUUID()
};

/** Fixed code of a refused wasm call (binding errors are fixed code strings). */
function wasmCode(error: unknown): string {
	return typeof error === 'string' ? error : 'unavailable';
}

/**
 * Write-failure code naming the step that failed after Rust may have written:
 * `draft_effect_<plan kind>` (an IndexedDB plan threw), `draft_prepare_<code>_after_<last plan|none>`,
 * `draft_result_<code>`, `draft_payload_<code>` or `draft_payload_shape`.
 */
function writeFailure(stage: string, code: string): string {
	return `draft_${stage}_${code}`.replace(/[^a-z0-9_]/g, '_').slice(0, 64);
}

export function installDraftsUnit(context: UnitInstallContext, deps: DraftsUnitDeps = defaultDeps): () => void {
	const principal = context.principal;
	if (context.ports.length !== 1 || !principal) throw new Error('unavailable');
	const port = context.ports[0];
	const prepared = new Map<string, { chatId: string; write: DraftsWrite }>();
	let disposed = false;
	const current = () => { if (disposed || context.signal.aborted) throw new Error('cancelled'); };

	/** Runs `work` on a borrowed admitted client with a fresh plan executor; always releases and drains. */
	async function withClient<T>(signal: AbortSignal, work: (client: DraftsClient, borrow: CoreClientBorrow,
		effect: (plan: string) => Promise<string>, ran: Set<string>) => Promise<T>): Promise<T> {
		current();
		const borrow = await deps.borrow(principal!, signal);
		if (borrow === 'none') throw new UnitRefusal('not_admitted');
		if (borrow === 'busy') throw new UnitRefusal('core_busy');
		if (borrow === 'local') throw new UnitRefusal('local_session');
		const handler = deps.effects(current);
		const ran = new Set<string>();
		const effect = async (plan: string) => {
			const kind = parseBrowserDraftPlan(plan).kind;
			ran.add(kind);
			try {
				return await handler.execute(plan, signal);
			} catch (error) {
				ran.add(`failed:${kind}`);
				// A read-only capture of a chat that has no chats_db row (new, public or
				// incognito chat) is a shape refusal, not a write failure.
				if (kind === 'capture_draft' && error instanceof Error && error.message === 'existing_chat_required') ran.add('missing_row');
				throw error;
			}
		};
		try {
			return await work(borrow.client as unknown as DraftsClient, borrow, effect, ran);
		} finally {
			borrow.release();
			await handler.close();
		}
	}

	const stop = serveUnitPort<DraftsProtocol>(port, {
		async save(request, signal) {
			if (!validDraftSaveRequest(request)) throw new UnitRefusal('invalid_request');
			const markdown = new TextDecoder('utf-8', { fatal: true }).decode(request.markdown);
			request.markdown.fill(0);
			return withClient(signal, async (client, borrow, effect, ran) => {
				let write: DraftsWrite;
				try {
					write = await client.prepare_local_draft_with_preview(borrow.status.handle, borrow.status.generation,
						borrow.status.principal, request.chatId, markdown, request.preview, JSON.stringify(request.scope),
						request.nowSeconds, effect);
				} catch (error) {
					const code = ran.has('missing_row') ? 'existing_chat_required' : wasmCode(error);
					// Routing to the TS writer is only sound when Rust refused before any write.
					if (isDraftRoutingCode(code) && !ran.has('store_draft')) throw new UnitRefusal(code);
					const failedEffect = [...ran].find((kind) => kind.startsWith('failed:'));
					const lastPlan = [...ran].filter((kind) => !kind.startsWith('failed:')).pop() ?? 'none';
					throw new UnitRefusal(failedEffect ? writeFailure('effect', failedEffect.slice(7)) : writeFailure('prepare', `${code}_after_${lastPlan}`));
				}
				try {
					current();
					let stage = 'result';
					let local: { version?: unknown };
					let payload: unknown;
					try {
						local = JSON.parse(write.local_result(borrow.client)) as { version?: unknown };
						stage = 'payload';
						payload = JSON.parse(write.remote_payload(borrow.client));
					} catch (error) {
						throw new UnitRefusal(writeFailure(stage, wasmCode(error)));
					}
					if (typeof local.version !== 'number' || !validDraftRemotePayload(payload, request.chatId) || payload.draft_v !== local.version) {
						throw new UnitRefusal(writeFailure('payload', 'shape'));
					}
					if (prepared.size >= MAX_PREPARED_DRAFTS) {
						const [oldest] = prepared.keys();
						prepared.get(oldest)?.write.free();
						prepared.delete(oldest);
					}
					const resourceId = deps.resourceId();
					prepared.set(resourceId, { chatId: request.chatId, write });
					return { resourceId, version: local.version, payload };
				} catch (error) {
					write.free();
					if (error instanceof UnitRefusal) throw error;
					throw new UnitRefusal('draft_write_failed');
				}
			});
		},
		async acknowledge(request, signal) {
			if (!validDraftResourceRequest(request)) throw new UnitRefusal('invalid_request');
			const entry = prepared.get(request.resourceId);
			if (!entry) throw new UnitRefusal('draft_resource_unknown');
			prepared.delete(request.resourceId);
			return withClient(signal, async (_client, borrow, effect) => {
				let publication: DraftsPublication;
				try {
					// acknowledge_transport consumes the write handle.
					publication = await entry.write.acknowledge_transport(borrow.client, effect);
				} catch {
					throw new UnitRefusal('draft_ack_failed');
				}
				const result = JSON.parse(publication.take(borrow.client)) as { version?: unknown; remoteSynced?: unknown };
				if (typeof result.version !== 'number' || result.remoteSynced !== true) throw new UnitRefusal('draft_ack_failed');
				return { version: result.version, remoteSynced: true as const };
			});
		},
		release(request) {
			if (!validDraftResourceRequest(request)) throw new UnitRefusal('invalid_request');
			const entry = prepared.get(request.resourceId);
			entry?.write.free();
			prepared.delete(request.resourceId);
			return { released: entry !== undefined };
		}
	});

	const dispose = () => {
		if (disposed) return;
		disposed = true;
		stop();
		for (const entry of prepared.values()) entry.write.free();
		prepared.clear();
		port.close();
	};
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}
