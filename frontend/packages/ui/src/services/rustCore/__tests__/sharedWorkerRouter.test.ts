// Shared Rust core Worker control router (envelope v1): namespace allowlist,
// fixed refusal codes, bind generations, port opening and unbind teardown.
import { describe, expect, it, vi } from 'vitest';
import {
	createSharedWorkerRouter,
	parseSharedControlReply,
	type SharedControlReply,
	type UnitInstallers
} from '../host/sharedWorkerProtocol';

const PRINCIPAL = '11111111-2222-3333-4444-555555555555';

function harness(installers: UnitInstallers, loadBinding = vi.fn<() => Promise<unknown>>(async () => ({ wasm: true }))) {
	const replies: SharedControlReply[] = [];
	const router = createSharedWorkerRouter({ installers, loadBinding, reply: (reply) => replies.push(reply) });
	return { router, replies, loadBinding, last: () => replies[replies.length - 1] };
}
function port(): MessagePort {
	const channel = new MessageChannel();
	channel.port1.close();
	return channel.port2;
}

describe('shared worker router', () => {
	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('refuses malformed envelopes, wrong versions and namespaces outside the allowlist', async () => {
		const { router, replies } = harness({});
		await router.handle('nope', []);
		await router.handle({ v: 2, id: 1, type: 'bind', principal: PRINCIPAL }, []);
		await router.handle({ v: 1, id: 2, type: 'open', ns: 'payments', generation: null }, [port()]);
		await router.handle({ v: 1, id: 3, type: 'bind', principal: 'not-a-uuid' }, []);
		await router.handle({ v: 1, id: 4, type: 'open', ns: 'crypto', generation: null, extra: 1 }, [port()]);
		await router.handle({ v: 1, id: 5, type: 'launch' }, []);
		expect(replies).toEqual([
			{ v: 1, id: null, type: 'refused', code: 'bad_envelope' },
			{ v: 1, id: 1, type: 'refused', code: 'unsupported_version' },
			{ v: 1, id: 2, type: 'refused', code: 'unknown_namespace' },
			{ v: 1, id: 3, type: 'refused', code: 'bad_envelope' },
			{ v: 1, id: 4, type: 'refused', code: 'bad_envelope' },
			{ v: 1, id: 5, type: 'refused', code: 'bad_envelope' }
		]);
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('refuses namespaces without an installer and never loads WASM for them', async () => {
		const { router, last, loadBinding } = harness({});
		await router.handle({ v: 1, id: 1, type: 'open', ns: 'crypto', generation: null }, [port()]);
		expect(last()).toEqual({ v: 1, id: 1, type: 'refused', code: 'unit_unavailable' });
		expect(loadBinding).not.toHaveBeenCalled();
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('requires a bound generation for non pre-bind namespaces and enforces port counts', async () => {
		const installer = vi.fn();
		const { router, replies } = harness({ core: installer, crypto: installer });
		await router.handle({ v: 1, id: 1, type: 'open', ns: 'core', generation: null }, [port()]);
		await router.handle({ v: 1, id: 2, type: 'open', ns: 'core', generation: 1 }, [port()]);
		await router.handle({ v: 1, id: 3, type: 'open', ns: 'crypto', generation: null }, []);
		await router.handle({ v: 1, id: 4, type: 'open', ns: 'crypto', generation: null }, [port(), port()]);
		await router.handle({ v: 1, id: 5, type: 'bind', principal: PRINCIPAL }, [port()]);
		expect(replies.map((reply) => reply.type === 'refused' && reply.code)).toEqual([
			'not_bound', 'not_bound', 'bad_ports', 'bad_ports', 'bad_ports'
		]);
		expect(installer).not.toHaveBeenCalled();
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('increments the generation per bind, refuses double bind and stale unbind/open', async () => {
		const { router, replies } = harness({ core: () => undefined });
		await router.handle({ v: 1, id: 1, type: 'bind', principal: PRINCIPAL }, []);
		await router.handle({ v: 1, id: 2, type: 'bind', principal: PRINCIPAL }, []);
		await router.handle({ v: 1, id: 3, type: 'unbind', generation: 7 }, []);
		await router.handle({ v: 1, id: 4, type: 'unbind', generation: 1 }, []);
		await router.handle({ v: 1, id: 5, type: 'unbind', generation: 1 }, []);
		await router.handle({ v: 1, id: 6, type: 'bind', principal: PRINCIPAL }, []);
		await router.handle({ v: 1, id: 7, type: 'open', ns: 'core', generation: 1 }, [port()]);
		expect(replies).toEqual([
			{ v: 1, id: 1, type: 'ready', generation: 1 },
			{ v: 1, id: 2, type: 'refused', code: 'already_bound' },
			{ v: 1, id: 3, type: 'refused', code: 'stale_generation' },
			{ v: 1, id: 4, type: 'ready', generation: null },
			{ v: 1, id: 5, type: 'refused', code: 'not_bound' },
			{ v: 1, id: 6, type: 'ready', generation: 2 },
			{ v: 1, id: 7, type: 'refused', code: 'stale_generation' }
		]);
		expect(router.generation).toBe(2);
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('opens ports with one shared binding and tears bound units down on unbind', async () => {
		const dispose = vi.fn();
		const contexts: { binding: unknown; ports: readonly MessagePort[]; generation: number | null; signal: AbortSignal }[] = [];
		const { router, replies, loadBinding } = harness({
			crypto: (context) => { contexts.push(context); },
			core: (context) => { contexts.push(context); return dispose; }
		});
		const unit = port();
		const recovery = port();
		const close = vi.spyOn(unit, 'close');
		await router.handle({ v: 1, id: 1, type: 'open', ns: 'crypto', generation: null }, [port()]);
		await router.handle({ v: 1, id: 2, type: 'bind', principal: PRINCIPAL }, []);
		await router.handle({ v: 1, id: 3, type: 'open', ns: 'core', generation: 1 }, [unit, recovery]);
		expect(replies.slice(0, 3)).toEqual([
			{ v: 1, id: 1, type: 'ready', generation: null },
			{ v: 1, id: 2, type: 'ready', generation: 1 },
			{ v: 1, id: 3, type: 'ready', generation: 1 }
		]);
		expect(loadBinding).toHaveBeenCalledTimes(1);
		expect(contexts[0].binding).toBe(contexts[1].binding);
		expect(contexts[1].ports).toEqual([unit, recovery]);
		await router.handle({ v: 1, id: 4, type: 'unbind', generation: 1 }, []);
		expect(contexts[1].signal.aborted).toBe(true);
		expect(contexts[0].signal.aborted).toBe(false);
		expect(dispose).toHaveBeenCalledTimes(1);
		expect(close).toHaveBeenCalled();
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('maps binding and installer failures to fixed codes and retries nothing silently', async () => {
		const failing = harness({ auth: () => undefined }, vi.fn(async () => { throw new Error('wasm'); }));
		await failing.router.handle({ v: 1, id: 1, type: 'open', ns: 'auth', generation: null }, [port()]);
		expect(failing.last()).toEqual({ v: 1, id: 1, type: 'refused', code: 'binding_unavailable' });
		const broken = harness({ auth: () => { throw new Error('install'); } });
		await broken.router.handle({ v: 1, id: 1, type: 'open', ns: 'auth', generation: null }, [port()]);
		expect(broken.last()).toEqual({ v: 1, id: 1, type: 'refused', code: 'install_failed' });
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('refuses an open whose generation was unbound while the binding loaded', async () => {
		let release!: (value: unknown) => void;
		const { router, replies } = harness({ core: () => undefined }, vi.fn(() => new Promise((resolve) => { release = resolve; })));
		await router.handle({ v: 1, id: 1, type: 'bind', principal: PRINCIPAL }, []);
		const opening = router.handle({ v: 1, id: 2, type: 'open', ns: 'core', generation: 1 }, [port()]);
		await router.handle({ v: 1, id: 3, type: 'unbind', generation: 1 }, []);
		release({});
		await opening;
		expect(replies[replies.length - 1]).toEqual({ v: 1, id: 2, type: 'refused', code: 'stale_generation' });
	});

	// contract-test: supporting surface=gui.web assertions=apps.execution.direct-shared-contract
	it('validates replies on the page side', () => {
		expect(parseSharedControlReply({ v: 1, id: 1, type: 'ready', generation: 3 })).toEqual({ v: 1, id: 1, type: 'ready', generation: 3 });
		expect(parseSharedControlReply({ v: 1, id: 1, type: 'refused', code: 'made_up' })).toBeNull();
		expect(parseSharedControlReply({ v: 1, id: 1, type: 'ready', generation: 0 })).toBeNull();
	});
});
