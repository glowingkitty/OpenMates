// Page side of the shared Rust core Worker: the control client (bind generation,
// port open, crash supervision), the flag-off registry and typed unit ports
// (results, fixed error codes, timeouts, abort and close).
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	createSharedCoreClient,
	isSharedRustCoreRegistered,
	registerSharedRustCore,
	requireSharedRustCore,
	type SharedWorkerEndpoint
} from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter, type UnitInstallers } from '../host/sharedWorkerProtocol';
import { createUnitPort, serveUnitPort, UnitRefusal } from '../host/unitPort';

const PRINCIPAL = '11111111-2222-3333-4444-555555555555';

/** In-process fake Worker that runs the real router. */
function fakeWorker(installers: UnitInstallers) {
	const listeners: Record<string, ((event: Event) => void)[]> = { message: [], error: [], messageerror: [] };
	const emit = (type: string, event: Event) => { for (const listener of listeners[type]) listener(event); };
	const router = createSharedWorkerRouter({
		installers,
		loadBinding: async () => ({ wasm: true }),
		reply: (reply) => queueMicrotask(() => emit('message', { data: reply } as MessageEvent))
	});
	const endpoint: SharedWorkerEndpoint & { crash(): void; terminated: boolean; posted: unknown[] } = {
		posted: [],
		terminated: false,
		postMessage(message, transfer) { endpoint.posted.push(message); void router.handle(message, transfer as MessagePort[]); },
		addEventListener(type, listener) { listeners[type].push(listener); },
		terminate() { endpoint.terminated = true; },
		crash() { emit('error', new Event('error')); }
	};
	return endpoint;
}

type Echo = { echo: { request: string; response: string }; refuse: { request: null; response: never }; hang: { request: null; response: never } };

describe('shared core client', () => {
	let unregister: (() => void) | null = null;
	afterEach(() => { unregister?.(); unregister = null; vi.useRealTimers(); });

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('reports not enabled until registered (flag OFF behaviour)', () => {
		expect(isSharedRustCoreRegistered()).toBe(false);
		expect(() => requireSharedRustCore()).toThrow('rust_core_not_enabled');
		const core = createSharedCoreClient(() => fakeWorker({}));
		unregister = registerSharedRustCore(core);
		expect(requireSharedRustCore()).toBe(core);
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('spawns lazily once, binds a generation and opens a working unit port', async () => {
		const spawn = vi.fn(() => fakeWorker({
			core: ({ ports }) => serveUnitPort<Echo>(ports[0], {
				echo: (text) => text.toUpperCase(),
				refuse: () => { throw new UnitRefusal('core_locked'); },
				hang: () => new Promise<never>(() => undefined)
			})
		}));
		const core = createSharedCoreClient(spawn);
		expect(spawn).not.toHaveBeenCalled();
		await expect(core.openUnit('core')).rejects.toMatchObject({ code: 'not_bound' });
		expect(await core.bind(PRINCIPAL)).toBe(1);
		const unit = createUnitPort<Echo>(await core.openUnit('core'), { timeoutMs: 1000 });
		expect(await unit.request('echo', 'hi')).toBe('HI');
		await expect(unit.request('refuse', null)).rejects.toMatchObject({ code: 'core_locked' });
		await expect(core.bind(PRINCIPAL)).rejects.toMatchObject({ code: 'already_bound' });
		await core.unbind();
		expect(core.generation).toBeNull();
		expect(spawn).toHaveBeenCalledTimes(1);
		unit.close();
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('rejects pending work on crash, notifies listeners and respawns on the next request', async () => {
		const workers: ReturnType<typeof fakeWorker>[] = [];
		const core = createSharedCoreClient(() => { const worker = fakeWorker({}); workers.push(worker); return worker; });
		await core.bind(PRINCIPAL);
		const crashed = vi.fn();
		core.onCrash(crashed);
		const pending = core.openUnit('crypto');
		workers[0].crash();
		await expect(pending).rejects.toMatchObject({ code: 'shared_core_crashed' });
		expect(crashed).toHaveBeenCalledTimes(1);
		expect(crashed).toHaveBeenCalledWith('crashed');
		expect(workers[0].terminated).toBe(true);
		expect(core.generation).toBeNull();
		await expect(core.openUnit('crypto')).rejects.toMatchObject({ code: 'unit_unavailable' });
		expect(workers).toHaveLength(2);
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('tells listeners that a planned terminate is not a crash', async () => {
		const workers: ReturnType<typeof fakeWorker>[] = [];
		const core = createSharedCoreClient(() => { const worker = fakeWorker({}); workers.push(worker); return worker; });
		await core.prewarm();
		const stopped = vi.fn();
		core.onCrash(stopped);
		core.terminate();
		expect(stopped).toHaveBeenCalledTimes(1);
		expect(stopped).toHaveBeenCalledWith('terminated');
		expect(workers[0].terminated).toBe(true);
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('times out and aborts control requests with fixed codes', async () => {
		const silent: SharedWorkerEndpoint = { postMessage() {}, addEventListener() {}, terminate() {} };
		const core = createSharedCoreClient(() => silent, { timeoutMs: 20 });
		await expect(core.bind(PRINCIPAL)).rejects.toMatchObject({ code: 'shared_core_timeout' });
		const controller = new AbortController();
		const binding = core.bind(PRINCIPAL, controller.signal);
		controller.abort();
		await expect(binding).rejects.toMatchObject({ code: 'shared_core_aborted' });
	});
});

describe('unit port', () => {
	function pair() {
		const channel = new MessageChannel();
		const stop = serveUnitPort<Echo>(channel.port2, {
			echo: (text) => text,
			refuse: () => { throw new Error('internal detail'); },
			hang: (_, signal) => new Promise<never>((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('cancelled'))))
		});
		return { unit: createUnitPort<Echo>(channel.port1, { timeoutMs: 50 }), stop, channel };
	}

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('hides internal error text behind unit_failed and rejects unknown operations', async () => {
		const { unit, stop } = pair();
		await expect(unit.request('refuse', null)).rejects.toMatchObject({ code: 'unit_failed' });
		await expect(unit.request('missing' as 'echo', 'x')).rejects.toMatchObject({ code: 'unknown_operation' });
		stop();
		unit.close();
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('times out, aborts and closes with fixed codes', async () => {
		const { unit, stop } = pair();
		await expect(unit.request('hang', null)).rejects.toMatchObject({ code: 'unit_timeout' });
		const controller = new AbortController();
		const aborted = unit.request('hang', null, { signal: controller.signal, timeoutMs: 5000 });
		controller.abort();
		await expect(aborted).rejects.toMatchObject({ code: 'unit_aborted' });
		await expect(unit.request('echo', 'x', { signal: controller.signal })).rejects.toMatchObject({ code: 'unit_aborted' });
		const open = unit.request('hang', null, { timeoutMs: 5000 });
		unit.close();
		await expect(open).rejects.toMatchObject({ code: 'unit_closed' });
		await expect(unit.request('echo', 'x')).rejects.toMatchObject({ code: 'unit_closed' });
		expect(unit.closed).toBe(true);
		stop();
	});
});
