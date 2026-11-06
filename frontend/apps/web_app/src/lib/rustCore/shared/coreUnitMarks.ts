/**
 * Bench-profile stage marks for the shared Worker's `core` unit.
 *
 * Per core request it records fixed-name performance measures, never content:
 *   openmates:rust:op:<operation>        request in -> final response out
 *   openmates:rust:op:<operation>:effect each page round trip (effect out -> reply in)
 * Operation names come from the closed CoreRequest union and are filtered to a
 * fixed identifier shape; anything else is recorded as `other`. At most
 * MAX_MEASURES per Worker realm are recorded (the first ones of the page load),
 * so a long session never grows the performance buffer.
 */
const OPERATION = /^[a-z][a-z0-9_]{0,63}$/;
const MAX_MEASURES = 256;
let recorded = 0;

interface Pending { operation: string; startedAt: number; effectAt: number | null }

function envelopeId(data: unknown): number | null {
	if (typeof data !== 'object' || data === null) return null;
	const id = (data as { id?: unknown }).id;
	return Number.isSafeInteger(id) ? (id as number) : null;
}

function isEffect(data: object): boolean {
	return Object.keys(data).some((key) => key === 'effectId' || key.endsWith('Effect'));
}

/** Installs the marks on the unit port; returns a disposer. */
export function installCoreUnitMarks(port: MessagePort): () => void {
	const pending = new Map<number, Pending>();
	const measure = (name: string, start: number) => {
		if (recorded >= MAX_MEASURES) return;
		recorded += 1;
		performance.measure(name, { start, end: performance.now() });
	};
	const receive = (event: MessageEvent<unknown>) => {
		const id = envelopeId(event.data);
		if (id === null) return;
		const operation = (event.data as { operation?: unknown }).operation;
		const known = pending.get(id);
		if (typeof operation === 'string') {
			pending.set(id, { operation: OPERATION.test(operation) ? operation : 'other', startedAt: performance.now(), effectAt: null });
		} else if (known && known.effectAt !== null) {
			measure(`openmates:rust:op:${known.operation}:effect`, known.effectAt);
			known.effectAt = null;
		}
	};
	const original = port.postMessage.bind(port) as (message: unknown, transfer?: Transferable[]) => void;
	const post = (message: unknown, transfer?: Transferable[]) => {
		const id = envelopeId(message);
		const known = id === null ? undefined : pending.get(id);
		if (known) {
			if (isEffect(message as object)) known.effectAt = performance.now();
			else { measure(`openmates:rust:op:${known.operation}`, known.startedAt); pending.delete(id!); }
		}
		if (transfer) original(message, transfer); else original(message);
	};
	Object.defineProperty(port, 'postMessage', { value: post, configurable: true, writable: true });
	port.addEventListener('message', receive);
	return () => {
		port.removeEventListener('message', receive);
		delete (port as unknown as { postMessage?: unknown }).postMessage;
		pending.clear();
	};
}
