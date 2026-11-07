/**
 * `sendPrep` namespace installer of the shared Rust core Worker.
 *
 * Serves the offline-outbox decisions (sendPrepProtocol.ts) on the unit port from
 * the realm's single WASM binding. It holds no account state, so it is a
 * pre-bind namespace. A malformed payload or a binding rejection answers the
 * fixed code `protocol`.
 */
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { isSendPrepBinding, type SendPrepBinding, type SendPrepUnitProtocol } from './sendPrepProtocol';

function call<T>(payload: unknown, run: (json: string) => string): T {
	if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) throw new UnitRefusal('protocol');
	let json: string;
	try {
		json = run(JSON.stringify(payload));
	} catch {
		throw new UnitRefusal('protocol');
	}
	return JSON.parse(json) as T;
}

export function createSendPrepHandlers(binding: SendPrepBinding): UnitHandlers<SendPrepUnitProtocol> {
	return {
		orderOffline: (payload) => call(payload, (json) => binding.send_prep_order_offline(json)),
		offlineReceipt: (payload) => call(payload, (json) => binding.send_prep_offline_receipt(json)),
	};
}

export function installSendPrepUnit(context: UnitInstallContext): () => void {
	if (context.ports.length !== 1 || !isSendPrepBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<SendPrepUnitProtocol>(port, createSendPrepHandlers(context.binding));
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
