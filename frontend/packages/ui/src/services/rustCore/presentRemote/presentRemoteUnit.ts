/**
 * `presentRemote` namespace installer of the shared Rust core Worker. Marshalling
 * only: encrypt and decrypt run on the ADMITTED client borrowed through
 * coreClientBorrow (the core resolves the embed key by id inside the Worker);
 * `accept` is the core's per-embed ordering rule held in the Worker. Refusals carry
 * the core's stable code; `local_session` / `not_admitted` / `core_busy` happen
 * before any core call so the page client can upgrade its session and resend.
 */
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import { borrowCoreClient } from '../drafts/coreClientBorrow';
import type { CoreBorrowRefusal, CoreClientBorrow } from '../drafts/coreClientBorrow';
import {
	isPresentRemoteBinding,
	type PresentRemoteBinding,
	type PresentRemoteClient,
	type PresentRemoteState,
	type PresentRemoteUnitProtocol,
} from './presentRemoteProtocol';

/** Bounded wait for the history dispatcher; the call is one short core call. */
export const PRESENT_REMOTE_BORROW_TIMEOUT_MS = 5_000;

export interface PresentRemoteDeps {
	borrow(principal: string, signal: AbortSignal, timeoutMs: number): Promise<CoreClientBorrow | CoreBorrowRefusal>;
}

const CODE = /^[a-z][a-z0-9_]{0,63}$/;

function code(error: unknown): string {
	if (error instanceof UnitRefusal) return error.code;
	const raw = typeof error === 'string' ? error : error instanceof Error ? error.message : '';
	return CODE.test(raw) ? raw : 'protocol';
}

function stateOf(payload: unknown): PresentRemoteState {
	const state = (payload as { state?: unknown } | null)?.state;
	if (typeof state !== 'object' || state === null || Array.isArray(state)) throw new UnitRefusal('protocol');
	return state as PresentRemoteState;
}

function text(payload: unknown, field: string): string {
	const value = (payload as Record<string, unknown> | null)?.[field];
	if (typeof value !== 'string' || value.length === 0) throw new UnitRefusal('protocol');
	return value;
}

export function createPresentRemoteHandlers(binding: PresentRemoteBinding, principal: string, deps: PresentRemoteDeps,
	lifetime: AbortSignal): UnitHandlers<PresentRemoteUnitProtocol> {
	async function withClient<T>(work: (client: PresentRemoteClient, handle: string, generation: number) => Promise<T>): Promise<T> {
		const borrow = await deps.borrow(principal, lifetime, PRESENT_REMOTE_BORROW_TIMEOUT_MS);
		if (borrow === 'none') throw new UnitRefusal('not_admitted');
		if (borrow === 'busy') throw new UnitRefusal('core_busy');
		if (borrow === 'local') throw new UnitRefusal('local_session');
		try {
			return await work(borrow.client as unknown as PresentRemoteClient, borrow.status.handle, borrow.status.generation);
		} catch (error) {
			throw new UnitRefusal(code(error));
		} finally {
			borrow.release();
		}
	}
	return {
		encrypt: (p) => withClient((client, handle, generation) =>
			client.present_remote_encrypt(handle, generation, JSON.stringify(stateOf(p)))),
		decrypt: (p) => withClient(async (client, handle, generation) =>
			JSON.parse(await client.present_remote_decrypt(handle, generation, text(p, 'embedId'), text(p, 'ciphertext'))) as PresentRemoteState),
		accept: (p) => {
			try {
				return binding.present_remote_accept(JSON.stringify(stateOf(p)));
			} catch (error) {
				throw new UnitRefusal(code(error));
			}
		},
	};
}

export function installPresentRemoteUnit(context: UnitInstallContext,
	deps: PresentRemoteDeps = { borrow: (principal, signal, timeoutMs) => borrowCoreClient(principal, signal, timeoutMs) }): () => void {
	const principal = context.principal;
	if (context.ports.length !== 1 || !principal || !isPresentRemoteBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<PresentRemoteUnitProtocol>(port, createPresentRemoteHandlers(context.binding, principal, deps, context.signal));
	let disposed = false;
	const dispose = () => {
		if (disposed) return;
		disposed = true;
		stop();
		port.close();
	};
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}
