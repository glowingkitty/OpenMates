/**
 * `persist` namespace installer of the shared Rust core Worker.
 *
 * Serves the IndexedDB row policy (persistProtocol.ts) on the unit port from the
 * realm's single WASM binding. It holds no account state and does no IO (rows
 * are passed in, decisions come back), so it is a pre-bind namespace. A malformed
 * payload or any binding rejection answers the fixed code `protocol`.
 *
 * spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
 */
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { isPersistBinding, PERSIST_OPS, type PersistBinding, type PersistUnitProtocol } from './persistProtocol';

export function createPersistHandlers(binding: PersistBinding): UnitHandlers<PersistUnitProtocol> {
	const handlers: Record<string, (payload: unknown) => unknown> = {};
	for (const [op, exportName] of Object.entries(PERSIST_OPS)) {
		handlers[op] = (payload) => {
			if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) throw new UnitRefusal('protocol');
			let json: string;
			try {
				json = binding[exportName](JSON.stringify(payload));
			} catch {
				throw new UnitRefusal('protocol');
			}
			return JSON.parse(json);
		};
	}
	return handlers as UnitHandlers<PersistUnitProtocol>;
}

export function installPersistUnit(context: UnitInstallContext): () => void {
	if (context.ports.length !== 1 || !isPersistBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<PersistUnitProtocol>(port, createPersistHandlers(context.binding));
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
