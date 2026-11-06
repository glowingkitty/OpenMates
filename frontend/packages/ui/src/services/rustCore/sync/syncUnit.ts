/**
 * `sync` namespace installer of the shared Rust core Worker.
 *
 * Serves the chat-sync decision policy (syncProtocol.ts) on the unit port from
 * the realm's single WASM binding. It holds no per-account state and does no
 * IO, so it is a pre-bind namespace. A malformed payload or any binding
 * rejection answers the fixed code `protocol` (the Rust boundary's only code).
 */
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { isSyncBinding, SYNC_OPS, type SyncBinding, type SyncUnitProtocol } from './syncProtocol';

export function createSyncHandlers(binding: SyncBinding): UnitHandlers<SyncUnitProtocol> {
	const handlers: Record<string, (payload: unknown) => unknown> = {};
	for (const [op, exportName] of Object.entries(SYNC_OPS)) {
		handlers[op] = (payload) => {
			if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) throw new UnitRefusal('protocol');
			let json: string;
			try {
				json = binding[exportName](JSON.stringify(payload));
			} catch {
				// A thrown JsValue is the Rust `protocol` code.
				throw new UnitRefusal('protocol');
			}
			return JSON.parse(json);
		};
	}
	return handlers as UnitHandlers<SyncUnitProtocol>;
}

export function installSyncUnit(context: UnitInstallContext): () => void {
	if (context.ports.length !== 1 || !isSyncBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<SyncUnitProtocol>(port, createSyncHandlers(context.binding));
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
