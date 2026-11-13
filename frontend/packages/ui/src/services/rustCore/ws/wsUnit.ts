/**
 * `ws` namespace installer of the shared Rust core Worker.
 *
 * Serves the WebSocket lifecycle policy (wsProtocol.ts) on the unit port from the
 * realm's single WASM binding. It holds no per-account state and does no IO, so
 * it is a pre-bind namespace. A malformed payload or any binding rejection
 * answers the fixed code `protocol` (the Rust boundary's only code).
 */
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { isWsBinding, WS_OPS, type WsBinding, type WsUnitProtocol } from './wsProtocol';

export function createWsHandlers(binding: WsBinding): UnitHandlers<WsUnitProtocol> {
	const handlers: Record<string, (payload: unknown) => unknown> = {};
	for (const [op, exportName] of Object.entries(WS_OPS)) {
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
	return handlers as UnitHandlers<WsUnitProtocol>;
}

export function installWsUnit(context: UnitInstallContext): () => void {
	if (context.ports.length !== 1 || !isWsBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<WsUnitProtocol>(port, createWsHandlers(context.binding));
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
