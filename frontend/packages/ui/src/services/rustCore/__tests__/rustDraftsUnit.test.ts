// Shared-core `drafts` unit: admitted-client borrow (idle only, no second
// client), Worker unit routing/failure codes around the Rust draft calls, and
// the page route (explicit TS routing, saved + synced, send failure keeps the
// durable intent and frees the handle).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { borrowCoreClient, registerCoreClientBorrows, tryBorrowCoreClient } from '../drafts/coreClientBorrow';
import { installDraftsUnit, type DraftsUnitDeps } from '../drafts/draftsUnit';
import { resetRustDraftRouteForTests, saveDraftWithRustCore } from '../drafts/rustDraftRoute';
import { createSharedCoreClient, registerSharedRustCore, type SharedWorkerEndpoint } from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter, type UnitInstallContext, type UnitInstallers } from '../host/sharedWorkerProtocol';
import { createUnitPort } from '../host/unitPort';
import type { DraftsProtocol } from '../drafts/draftsProtocol';
import type { WorkerRuntimeState } from '../workerRuntimeState';
import type { CoreClientBorrow } from '../drafts/coreClientBorrow';
import { draftProjection } from '../browserDraftProtocol';

const PRINCIPAL = '11111111-2222-3333-4444-555555555555';
const CHAT = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
const RESOURCE = '99999999-8888-7777-6666-555555555555';
const SCOPE = { lifecycleGeneration: 1, workspaceEpoch: 0 };

function fakeClient(status: { local_read_only?: boolean; principal?: string } = {}) {
	return {
		freed: false,
		admitted_status: () => ({ handle: 'h', generation: 1, principal: status.principal ?? PRINCIPAL, local_read_only: status.local_read_only ?? false, free() {} }),
		invalidate() {},
		free() { this.freed = true; }
	};
}

function fakeRuntime(client: ReturnType<typeof fakeClient> | null, overrides: Record<string, unknown> = {}) {
	return {
		disposed: false, client, busy: false, reading: null, sending: null, initialSync: null, firstSessionTask: null,
		passwordAdmission: null, cacheRead: null, localRead: null, ownedCacheReads: new Map(), retainedClients: new Map(), freedClients: new Set(),
		endpoint: new EventTarget(), receiveListener: () => {},
		configuration: { admission: 'existing_key', expectedPrincipal: PRINCIPAL }, ...overrides
	} as unknown as WorkerRuntimeState;
}

describe('core client borrow', () => {
	const cleanups: (() => void)[] = [];
	afterEach(() => { for (const c of cleanups.splice(0)) c(); });

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
	it('lends the admitted client only while the dispatcher is idle and restores it on release', () => {
		const client = fakeClient();
		const rt = fakeRuntime(client);
		cleanups.push(registerCoreClientBorrows(rt));
		const borrow = tryBorrowCoreClient(PRINCIPAL.toUpperCase()) as CoreClientBorrow;
		expect(borrow.client).toBe(client);
		expect(borrow.status).toEqual({ handle: 'h', generation: 1, principal: PRINCIPAL });
		expect(rt.busy).toBe(true);
		expect(tryBorrowCoreClient(PRINCIPAL)).toBe('busy');
		borrow.release();
		borrow.release();
		(rt.ownedCacheReads as Map<number, unknown>).set(1, {});
		expect(tryBorrowCoreClient(PRINCIPAL), 'an in-flight owned cache read keeps the client busy').toBe('busy');
		rt.ownedCacheReads.clear();
		expect(rt.busy).toBe(false);
		expect(rt.reading).toBeNull();
		expect(client.freed).toBe(false);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
	it('holds a dispatcher request that arrives during a borrow and delivers it in order on release', () => {
		const delivered: string[] = [];
		const rt = fakeRuntime(fakeClient(), { receiveListener: (event: Event) => { delivered.push((event as MessageEvent).data as string); } });
		cleanups.push(registerCoreClientBorrows(rt));
		const send = (data: string) => rt.endpoint.dispatchEvent(new MessageEvent('message', { data }));
		send('before');
		const borrow = tryBorrowCoreClient(PRINCIPAL) as CoreClientBorrow;
		send('during-1');
		send('during-2');
		expect(delivered, 'requests wait while the client is lent').toEqual(['before']);
		borrow.release();
		expect(delivered).toEqual(['before', 'during-1', 'during-2']);
		send('after');
		expect(delivered).toEqual(['before', 'during-1', 'during-2', 'after']);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
	it('refuses other principals, local-only admissions and unregistered dispatchers', () => {
		const local = fakeRuntime(fakeClient({ local_read_only: true }));
		const other = fakeRuntime(fakeClient(), { configuration: { admission: 'existing_key', expectedPrincipal: CHAT } });
		const keyless = fakeRuntime(fakeClient(), { configuration: { admission: 'password' } });
		cleanups.push(registerCoreClientBorrows(other), registerCoreClientBorrows(keyless));
		expect(tryBorrowCoreClient(PRINCIPAL)).toBe('none');
		const unregisterLocal = registerCoreClientBorrows(local);
		expect(tryBorrowCoreClient(PRINCIPAL), 'a local-only history client is named, never lent').toBe('local');
		expect(local.busy).toBe(false);
		unregisterLocal();
		const rt = fakeRuntime(fakeClient());
		registerCoreClientBorrows(rt)();
		expect(tryBorrowCoreClient(PRINCIPAL)).toBe('none');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
	it('frees a client retired during the borrow only on release', () => {
		const client = fakeClient();
		const rt = fakeRuntime(client);
		cleanups.push(registerCoreClientBorrows(rt));
		const borrow = tryBorrowCoreClient(PRINCIPAL) as CoreClientBorrow;
		(rt as unknown as { client: unknown }).client = null;
		expect(client.freed).toBe(false);
		borrow.release();
		expect(client.freed).toBe(true);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
	it('waits a bounded time for a busy dispatcher', async () => {
		const rt = fakeRuntime(fakeClient(), { busy: true });
		cleanups.push(registerCoreClientBorrows(rt));
		await expect(borrowCoreClient(PRINCIPAL, new AbortController().signal, 30)).resolves.toBe('busy');
		setTimeout(() => { (rt as unknown as { busy: boolean }).busy = false; }, 10);
		const borrow = await borrowCoreClient(PRINCIPAL, new AbortController().signal, 500);
		expect(typeof borrow).toBe('object');
		(borrow as CoreClientBorrow).release();
	});
});

interface FakeWrite { freed: boolean; acked: boolean }
function draftsHarness(options: { prepare?: (effect: (plan: string) => Promise<string>) => Promise<void>; refuse?: string; borrow?: 'none' | 'local' | 'busy'; missingRow?: boolean; ackFails?: boolean } = {}) {
	const writes: FakeWrite[] = [];
	const plans: string[] = [];
	let released = 0;
	const client = {
		async prepare_local_draft_with_preview(_h: string, _g: number, owner: string, chatId: string, markdown: string, preview: string, _scope: string, _now: number, effect: (plan: string) => Promise<string>) {
			expect(owner).toBe(PRINCIPAL);
			expect(markdown).toBe('Hello body');
			expect(preview).toBe('Hello preview');
			if (options.prepare) await options.prepare(effect);
			if (options.refuse) throw options.refuse;
			const state: FakeWrite = { freed: false, acked: false };
			writes.push(state);
			return {
				local_result: () => JSON.stringify({ version: 7 }),
				remote_payload: () => JSON.stringify({ chat_id: chatId, encrypted_draft_md: 'ct-md', encrypted_draft_preview: 'ct-preview', draft_v: 7 }),
				async acknowledge_transport() { if (options.ackFails) throw 'unavailable'; state.acked = true; return { take: () => JSON.stringify({ version: 7, remoteSynced: true }), free() {} }; },
				free() { state.freed = true; }
			};
		}
	};
	const deps: DraftsUnitDeps = {
		async borrow() {
			if (options.borrow) return options.borrow;
			return { client: client as never, status: { handle: 'h', generation: 1, principal: PRINCIPAL }, release() { released++; } };
		},
		effects: () => ({
			current() {},
			async execute(plan: string) {
				const kind = JSON.parse(plan).kind as string;
				plans.push(kind);
				if (kind === 'capture_draft' && options.missingRow) throw new Error('existing_chat_required');
				return '{}';
			},
			async close() {}
		}),
		resourceId: () => RESOURCE
	};
	return { writes, plans, deps, released: () => released };
}

const plan = (kind: string) => JSON.stringify({ version: 1, kind, operationId: RESOURCE, owner: PRINCIPAL, chatId: CHAT, scope: SCOPE, expected: null, queueMaximum: null, patch: null, change: null });

vi.mock('../browserDraftProtocol', async (original) => {
	const actual = await original<typeof import('../browserDraftProtocol')>();
	return { ...actual, parseBrowserDraftPlan: (encoded: string) => JSON.parse(encoded) };
});

function installUnit(deps: DraftsUnitDeps) {
	const channel = new MessageChannel();
	const controller = new AbortController();
	const context: UnitInstallContext = { binding: {}, ports: [channel.port2], generation: 1, principal: PRINCIPAL, signal: controller.signal } as UnitInstallContext;
	const dispose = installDraftsUnit(context, deps);
	return { port: createUnitPort<DraftsProtocol>(channel.port1), dispose, controller };
}

const saveRequest = () => ({ chatId: CHAT, markdown: new TextEncoder().encode('Hello body'), preview: 'Hello preview', scope: SCOPE, nowSeconds: 10 });

describe('drafts unit', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
	it('saves through Rust, returns only version and ciphertext payload, then acknowledges', async () => {
		const h = draftsHarness();
		const { port, dispose } = installUnit(h.deps);
		const saved = await port.request('save', saveRequest());
		expect(saved).toEqual({ resourceId: RESOURCE, version: 7, payload: { chat_id: CHAT, encrypted_draft_md: 'ct-md', encrypted_draft_preview: 'ct-preview', draft_v: 7 } });
		expect(JSON.stringify(saved)).not.toContain('Hello');
		expect(h.released()).toBe(1);
		await expect(port.request('acknowledge', { resourceId: RESOURCE })).resolves.toEqual({ version: 7, remoteSynced: true });
		expect(h.writes[0].acked).toBe(true);
		expect(h.released()).toBe(2);
		await expect(port.request('acknowledge', { resourceId: RESOURCE })).rejects.toMatchObject({ code: 'draft_resource_unknown' });
		dispose();
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
	it('routes shape refusals decided before any write and fails refusals after a write', async () => {
		const shape = installUnit(draftsHarness({ refuse: 'browser_draft_existing_personal_required' }).deps);
		await expect(shape.port.request('save', saveRequest())).rejects.toMatchObject({ code: 'browser_draft_existing_personal_required' });
		const written = installUnit(draftsHarness({ refuse: 'browser_draft_forbidden', prepare: async (effect) => { await effect(plan('store_draft')); } }).deps);
		await expect(written.port.request('save', saveRequest())).rejects.toMatchObject({ code: 'draft_prepare_browser_draft_forbidden_after_store_draft' });
		const missing = installUnit(draftsHarness({ missingRow: true, refuse: 'unavailable', prepare: async (effect) => { await expect(effect(plan('capture_draft'))).rejects.toThrow('existing_chat_required'); } }).deps);
		await expect(missing.port.request('save', saveRequest())).rejects.toMatchObject({ code: 'existing_chat_required' });
		const internal = installUnit(draftsHarness({ refuse: 'unavailable' }).deps);
		await expect(internal.port.request('save', saveRequest())).rejects.toMatchObject({ code: 'draft_prepare_unavailable_after_none' });
		for (const unit of [shape, written, missing, internal]) unit.dispose();
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
	it('refuses not_admitted / core_busy without a client and rejects malformed requests', async () => {
		const none = installUnit(draftsHarness({ borrow: 'none' }).deps);
		await expect(none.port.request('save', saveRequest())).rejects.toMatchObject({ code: 'not_admitted' });
		const local = installUnit(draftsHarness({ borrow: 'local' }).deps);
		await expect(local.port.request('save', saveRequest())).rejects.toMatchObject({ code: 'local_session' });
		local.dispose();
		const busy = installUnit(draftsHarness({ borrow: 'busy' }).deps);
		await expect(busy.port.request('save', saveRequest())).rejects.toMatchObject({ code: 'core_busy' });
		await expect(busy.port.request('save', { ...saveRequest(), preview: '  ' })).rejects.toMatchObject({ code: 'invalid_request' });
		await expect(busy.port.request('save', { ...saveRequest(), chatId: 'x' })).rejects.toMatchObject({ code: 'invalid_request' });
		none.dispose(); busy.dispose();
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
	it('frees prepared writes on release and when the generation ends', async () => {
		const h = draftsHarness();
		const { port, controller } = installUnit(h.deps);
		await port.request('save', saveRequest());
		await expect(port.request('release', { resourceId: RESOURCE })).resolves.toEqual({ released: true });
		expect(h.writes[0].freed).toBe(true);
		await port.request('save', saveRequest());
		controller.abort();
		expect(h.writes[1].freed).toBe(true);
	});
});

function fakeWorker(installers: UnitInstallers) {
	const listeners: Record<string, ((event: Event) => void)[]> = { message: [], error: [], messageerror: [] };
	const emit = (type: string, event: Event) => { for (const listener of listeners[type]) listener(event); };
	const router = createSharedWorkerRouter({ installers, loadBinding: async () => ({ wasm: true }),
		reply: (reply) => queueMicrotask(() => emit('message', { data: reply } as MessageEvent)) });
	const endpoint: SharedWorkerEndpoint = {
		postMessage(message, transfer) { void router.handle(message, transfer as MessagePort[]); },
		addEventListener(type, listener) { listeners[type].push(listener); },
		terminate() {}
	};
	return endpoint;
}

describe('rust draft route', () => {
	let unregister: (() => void) | null = null;
	afterEach(() => { unregister?.(); unregister = null; resetRustDraftRouteForTests(); delete document.documentElement.dataset.rustCoreDraft; });
	const input = (send: () => Promise<void>) => ({ chatId: CHAT, markdown: 'Hello body', preview: 'Hello preview', workspaceEpoch: 0, send });

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
	it('routes to the TS writer, marked, when no shared core is registered or bound', async () => {
		await expect(saveDraftWithRustCore(input(async () => {}))).resolves.toEqual({ kind: 'legacy', code: 'rust_core_not_enabled' });
		expect(document.documentElement.dataset.rustCoreDraft).toBe('ts-rust_core_not_enabled');
		unregister = registerSharedRustCore(createSharedCoreClient(() => fakeWorker({})));
		await expect(saveDraftWithRustCore(input(async () => {}))).resolves.toEqual({ kind: 'legacy', code: 'not_bound' });
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
	it('saves through the unit, sends the ciphertext and acknowledges it', async () => {
		const h = draftsHarness();
		const core = createSharedCoreClient(() => fakeWorker({ drafts: (context) => installDraftsUnit(context, h.deps) }));
		unregister = registerSharedRustCore(core);
		await core.bind(PRINCIPAL);
		const sent: unknown[] = [];
		const outcome = await saveDraftWithRustCore(input(async () => { sent.push('sent'); }));
		expect(outcome.kind).toBe('saved');
		if (outcome.kind !== 'saved') return;
		expect(outcome.version).toBe(7);
		await outcome.synced;
		expect(sent).toEqual(['sent']);
		expect(h.writes[0].acked).toBe(true);
		expect(document.documentElement.dataset.rustCoreDraft).toBe('rust-synced');
		expect(core.busy).toBe(false);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
	it('routes shape refusals to TS and keeps failures and send errors explicit', async () => {
		const shape = draftsHarness({ refuse: 'browser_draft_existing_personal_required' });
		let deps = shape.deps;
		const core = createSharedCoreClient(() => fakeWorker({ drafts: (context) => installDraftsUnit(context, deps) }));
		unregister = registerSharedRustCore(core);
		await core.bind(PRINCIPAL);
		await expect(saveDraftWithRustCore(input(async () => {}))).resolves.toEqual({ kind: 'legacy', code: 'browser_draft_existing_personal_required' });
		resetRustDraftRouteForTests();
		const sendFails = draftsHarness();
		deps = sendFails.deps;
		const outcome = await saveDraftWithRustCore(input(async () => { throw new Error('ws_closed'); }));
		expect(outcome.kind).toBe('saved');
		if (outcome.kind !== 'saved') return;
		await expect(outcome.synced).rejects.toThrow('ws_closed');
		await vi.waitFor(() => expect(sendFails.writes[0].freed).toBe(true));
		expect(sendFails.writes[0].acked).toBe(false);
		expect(document.documentElement.dataset.rustCoreDraft).toBe('rust-local');
		resetRustDraftRouteForTests();
		deps = draftsHarness({ ackFails: true }).deps;
		const delivered = await saveDraftWithRustCore(input(async () => {}));
		if (delivered.kind !== 'saved') throw new Error('expected a Rust save');
		await expect(delivered.synced, 'a refused ack after delivery does not mark the draft unsaved').resolves.toBeUndefined();
		expect(document.documentElement.dataset.rustCoreDraft).toBe('rust-ack-failed-draft_ack_failed');
		resetRustDraftRouteForTests();
		deps = draftsHarness({ refuse: 'unavailable', prepare: async (effect) => { await effect(plan('store_draft')); } }).deps;
		await expect(saveDraftWithRustCore(input(async () => {}))).resolves.toEqual({ kind: 'failed', code: 'draft_prepare_unavailable_after_store_draft' });
		expect(document.documentElement.dataset.rustCoreDraft).toBe('rust-failed-draft_prepare_unavailable_after_store_draft');
	});
});

describe('chats_db draft projection', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,drafts.persistence.local-first-encrypted
	it('projects undefined fields left by a TS draft clear as absent so the JSON packet keeps {present, value}', () => {
		const projection = draftProjection({ chat_id: CHAT, draft_v: 3, encrypted_draft_md: undefined, encrypted_draft_preview: undefined });
		expect(projection.encrypted_draft_md).toEqual({ present: false, value: null });
		expect(projection.draft_v).toEqual({ present: true, value: 3 });
		const wire = JSON.parse(JSON.stringify(projection)) as Record<string, Record<string, unknown>>;
		for (const field of Object.values(wire)) expect(Object.keys(field).sort()).toEqual(['present', 'value']);
	});
});
