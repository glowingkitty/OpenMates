// Shared-core supervision of page unit ports: unbind ends the ending
// generation's ports at once (`unit_unbound`, even while the Worker is busy),
// pre-bind ports opened unbound keep working, crash/terminate end every port
// (`unit_retired`), and a new port after rebind works. The real router runs
// in-process behind a fake Worker endpoint.
import { afterEach, describe, expect, it } from 'vitest';
import { createSharedCoreClient, type SharedWorkerEndpoint } from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter, type UnitInstaller } from '../host/sharedWorkerProtocol';
import { createUnitPort, serveUnitPort, type UnitPort } from '../host/unitPort';

const PRINCIPAL = '11111111-2222-3333-4444-555555555555';
const FAST_MS = 100;

type Echo = { echo: { request: string; response: string }; hang: { request: null; response: never } };

const echoUnit: UnitInstaller = ({ ports }) => serveUnitPort<Echo>(ports[0], {
	echo: (text) => text,
	hang: () => new Promise<never>(() => undefined)
});

/** Fake Worker running the real router; `stall()` queues control messages like a Worker stuck in a long WASM call. */
function fakeWorker() {
	const listeners: Record<string, ((event: Event) => void)[]> = { message: [], error: [], messageerror: [] };
	const emit = (type: string, event: Event) => { for (const listener of listeners[type]) listener(event); };
	const router = createSharedWorkerRouter({
		installers: { embedWrite: echoUnit, search: echoUnit },
		loadBinding: async () => ({ wasm: true }),
		reply: (reply) => queueMicrotask(() => emit('message', { data: reply } as MessageEvent))
	});
	let stalled: [unknown, MessagePort[]][] | null = null;
	const endpoint: SharedWorkerEndpoint & { crash(): void; stall(): void; resume(): void } = {
		postMessage(message, transfer) {
			if (stalled) stalled.push([message, transfer as MessagePort[]]);
			else void router.handle(message, transfer as MessagePort[]);
		},
		addEventListener(type, listener) { listeners[type].push(listener); },
		terminate() { /* in-process */ },
		crash() { emit('error', new Event('error')); },
		stall() { stalled = []; },
		resume() {
			const queued = stalled ?? [];
			stalled = null;
			for (const [message, ports] of queued) void router.handle(message, ports);
		}
	};
	return endpoint;
}

async function rejectedWithin(request: Promise<unknown>, startedAt: number): Promise<{ code: unknown; ms: number }> {
	const error = await request.then(() => null, (reason: unknown) => reason as { code?: unknown });
	return { code: error?.code, ms: performance.now() - startedAt };
}

const opened: UnitPort<Echo>[] = [];
afterEach(() => { for (const unit of opened.splice(0)) unit.close(); });

function setup() {
	const workers: ReturnType<typeof fakeWorker>[] = [];
	const core = createSharedCoreClient(() => { const worker = fakeWorker(); workers.push(worker); return worker; });
	const open = async (ns: 'embedWrite' | 'search', unbound = false) => {
		const unit = createUnitPort<Echo>(await core.openUnit(ns, { unbound }));
		opened.push(unit);
		return unit;
	};
	return { core, workers, open };
}

describe('unit port supervision', () => {
	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('rejects an in-flight bound request with unit_unbound well under the timeout, then works after rebind', async () => {
		const { core, open } = setup();
		await core.bind(PRINCIPAL);
		const unit = await open('embedWrite');
		expect(await unit.request('echo', 'before')).toBe('before');
		const inFlight = unit.request('hang', null);
		const startedAt = performance.now();
		const unbinding = core.unbind();
		const result = await rejectedWithin(inFlight, startedAt);
		expect(result.code).toBe('unit_unbound');
		expect(result.ms).toBeLessThan(FAST_MS);
		await unbinding;
		expect(unit.closed).toBe(true);
		await expect(unit.request('echo', 'late')).rejects.toMatchObject({ code: 'unit_unbound' });
		await expect(core.openUnit('embedWrite')).rejects.toMatchObject({ code: 'not_bound' });
		await core.bind(PRINCIPAL);
		const reopened = await open('embedWrite');
		expect(await reopened.request('echo', 'after')).toBe('after');
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('rejects at once even while the Worker has not processed the unbind yet', async () => {
		const { core, workers, open } = setup();
		await core.bind(PRINCIPAL);
		const unit = await open('embedWrite');
		const inFlight = unit.request('hang', null);
		workers[0].stall();
		const startedAt = performance.now();
		const unbinding = core.unbind();
		const result = await rejectedWithin(inFlight, startedAt);
		expect(result).toMatchObject({ code: 'unit_unbound' });
		expect(result.ms).toBeLessThan(FAST_MS);
		workers[0].resume();
		await unbinding;
		expect(core.generation).toBeNull();
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('leaves pre-bind ports opened unbound working across unbind and retires bound pre-bind ports', async () => {
		const { core, open } = setup();
		const unboundSearch = await open('search', true);
		await core.bind(PRINCIPAL);
		const boundSearch = await open('search');
		await core.unbind();
		expect(await unboundSearch.request('echo', 'still')).toBe('still');
		await expect(boundSearch.request('echo', 'x')).rejects.toMatchObject({ code: 'unit_unbound' });
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('retires every port at once on terminate and on crash; the respawned realm serves new ports', async () => {
		const { core, workers, open } = setup();
		const unboundSearch = await open('search', true);
		await core.bind(PRINCIPAL);
		const bound = await open('embedWrite');
		const pending = [unboundSearch.request('hang', null), bound.request('hang', null)];
		let startedAt = performance.now();
		core.terminate();
		for (const request of pending) {
			const result = await rejectedWithin(request, startedAt);
			expect(result.code).toBe('unit_retired');
			expect(result.ms).toBeLessThan(FAST_MS);
		}
		const respawned = await open('search', true);
		const hanging = respawned.request('hang', null);
		startedAt = performance.now();
		workers[1].crash();
		const crashed = await rejectedWithin(hanging, startedAt);
		expect(crashed.code).toBe('unit_retired');
		expect(crashed.ms).toBeLessThan(FAST_MS);
		const fresh = await open('search', true);
		expect(await fresh.request('echo', 'ok')).toBe('ok');
		expect(workers).toHaveLength(3);
	});
});
