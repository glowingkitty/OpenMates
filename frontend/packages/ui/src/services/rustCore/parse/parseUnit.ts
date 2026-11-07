/**
 * `parse` namespace installer of the shared Rust core Worker.
 *
 * Serves the render-plan block model (parseProtocol.ts) on the unit port from
 * the realm's single WASM binding. Stateless and IO-free, hence pre-bind. A
 * malformed payload or any binding rejection answers the fixed code `protocol`.
 */
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { isParseBinding, type ParseBinding, type ParseUnitProtocol } from './parseProtocol';

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
function text(value: unknown): string {
	if (typeof value !== 'string') throw new UnitRefusal('protocol');
	return value;
}
function record(payload: unknown): Record<string, unknown> {
	if (!isRecord(payload)) throw new UnitRefusal('protocol');
	return payload;
}
/** Binding results are JSON text; a thrown JsValue is the Rust `protocol` code. */
function call<T>(run: () => string): T {
	let json: string;
	try {
		json = run();
	} catch {
		throw new UnitRefusal('protocol');
	}
	return JSON.parse(json) as T;
}

export function createParseHandlers(binding: ParseBinding): UnitHandlers<ParseUnitProtocol> {
	return {
		planBlocks: (payload) => {
			const p = record(payload);
			return call(() => binding.parse_plan_blocks(text(p.markdown), text(p.phase), text(p.previous)));
		},
		normalizePlan: (payload) => {
			const p = record(payload);
			return call(() => binding.parse_normalize_plan(text(p.plan)));
		},
	};
}

export function installParseUnit(context: UnitInstallContext): () => void {
	if (context.ports.length !== 1 || !isParseBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<ParseUnitProtocol>(port, createParseHandlers(context.binding));
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
