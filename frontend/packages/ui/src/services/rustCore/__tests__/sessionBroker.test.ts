// Session broker over the shared Rust core Worker: one admission (bind) per
// principal, ref-counted core unit leases, lease close disposes only its unit
// (never terminates the Worker), principal switch / crash lose the old leases.
import { describe, expect, it, vi } from 'vitest';
import { createSharedCoreClient, type SharedWorkerEndpoint } from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter, type UnitInstallContext } from '../host/sharedWorkerProtocol';
import { CORE_UNIT_CLOSE, createSessionBroker, isCoreUnitClose } from '../host/sessionBroker';

const ALICE = '11111111-2222-3333-4444-555555555555';
const BOB = '66666666-7777-8888-9999-aaaaaaaaaaaa';

interface Unit { principal: string | null; generation: number | null; disposed: boolean; aborted: () => boolean }

function harness() {
	const units: Unit[] = [];
	const loadBinding = vi.fn(async () => ({ wasm: true }));
	const workers: (SharedWorkerEndpoint & { crash(): void; terminated: boolean; binds: number })[] = [];
	const spawn = () => {
		const listeners: Record<string, ((event: Event) => void)[]> = { message: [], error: [], messageerror: [] };
		const emit = (type: string, event: Event) => { for (const listener of listeners[type]) listener(event); };
		const router = createSharedWorkerRouter({
			installers: {
				core: (context: UnitInstallContext) => {
					const unit: Unit = { principal: context.principal, generation: context.generation, disposed: false, aborted: () => context.signal.aborted };
					units.push(unit);
					context.ports[0].addEventListener('message', (event) => { if (isCoreUnitClose((event as MessageEvent).data)) unit.disposed = true; });
					context.ports[0].start();
					return () => { unit.disposed = true; };
				}
			},
			loadBinding,
			reply: (reply) => queueMicrotask(() => emit('message', { data: reply } as MessageEvent))
		});
		const worker = {
			terminated: false,
			binds: 0,
			postMessage(message: unknown, transfer: Transferable[]) {
				if ((message as { type?: string }).type === 'bind') worker.binds++;
				void router.handle(message, transfer as MessagePort[]);
			},
			addEventListener(type: 'message' | 'error' | 'messageerror', listener: (event: Event) => void) { listeners[type].push(listener); },
			terminate() { worker.terminated = true; },
			crash() { emit('error', new Event('error')); }
		};
		workers.push(worker);
		return worker;
	};
	const core = createSharedCoreClient(spawn);
	return { core, broker: createSessionBroker(core), units, workers, loadBinding };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 10));

describe('session broker', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('admits a principal once and ref-counts leases on one Worker and one binding', async () => {
		const { broker, units, workers, loadBinding } = harness();
		await broker.prewarm();
		const [first, second] = await Promise.all([broker.lease(ALICE), broker.lease(ALICE)]);
		expect(workers).toHaveLength(1);
		expect(workers[0].binds).toBe(1);
		expect(loadBinding).toHaveBeenCalledTimes(1);
		expect(first.generation).toBe(second.generation);
		expect(units.map((unit) => unit.principal)).toEqual([ALICE, ALICE]);
		expect(broker.activeLeases).toBe(2);

		first.close();
		first.close();
		await settle();
		expect(first.closed).toBe(true);
		expect(units[0].disposed).toBe(true);
		expect(units[1].disposed).toBe(false);
		expect(broker.activeLeases).toBe(1);
		expect(workers[0].terminated).toBe(false);

		second.close();
		await settle();
		const third = await broker.lease(ALICE);
		expect(workers[0].binds).toBe(1);
		expect(third.generation).toBe(first.generation);
		expect(workers).toHaveLength(1);
		third.close();
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('loses the old leases and unbinds before admitting a different principal', async () => {
		const { broker, units, workers } = harness();
		const alice = await broker.lease(ALICE);
		const lost = vi.fn();
		alice.onLost(lost);
		const bob = await broker.lease(BOB);
		expect(lost).toHaveBeenCalledTimes(1);
		expect(alice.closed).toBe(true);
		expect(units[0].aborted()).toBe(true);
		expect(units[1].principal).toBe(BOB);
		expect(bob.generation).toBeGreaterThan(alice.generation);
		expect(broker.principal).toBe(BOB);
		expect(workers[0].binds).toBe(2);
		expect(workers[0].terminated).toBe(false);
		await broker.dispose();
		expect(bob.closed).toBe(true);
		expect(broker.principal).toBeNull();
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('loses every lease on a Worker crash and re-admits on a fresh Worker', async () => {
		const { broker, workers } = harness();
		const lease = await broker.lease(ALICE);
		const lost = vi.fn();
		lease.onLost(lost);
		workers[0].crash();
		expect(lost).toHaveBeenCalledTimes(1);
		expect(broker.activeLeases).toBe(0);
		const again = await broker.lease(ALICE);
		expect(workers).toHaveLength(2);
		expect(workers[1].binds).toBe(1);
		again.close();
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses malformed principals and aborted admissions with fixed codes', async () => {
		const { broker, workers } = harness();
		await expect(broker.lease('not-a-uuid')).rejects.toMatchObject({ code: 'bad_envelope' });
		const controller = new AbortController();
		controller.abort();
		await expect(broker.lease(ALICE, { signal: controller.signal })).rejects.toMatchObject({ code: 'shared_core_aborted' });
		expect(workers).toHaveLength(0);
		expect(isCoreUnitClose(CORE_UNIT_CLOSE)).toBe(true);
		expect(isCoreUnitClose({ coreUnitClose: 1, id: 1 })).toBe(false);
		expect(isCoreUnitClose({ version: 1, id: 1, operation: 'status' })).toBe(false);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('ensureBound admits the principal without a unit and later leases reuse it', async () => {
		const { broker, units, workers } = harness();
		const generation = await broker.ensureBound(ALICE);
		expect(units).toHaveLength(0);
		expect(broker.principal).toBe(ALICE);
		const lease = await broker.lease(ALICE);
		expect(lease.generation).toBe(generation);
		expect(workers[0].binds).toBe(1);
		await expect(broker.ensureBound('not-a-principal')).rejects.toThrow();
	});
});
