// Flag-on natural-language Apps request and result policy adapters
// (rustAppsRequest.ts, rustAppsRetention.ts) over the real `apps` unit router
// with a scripted binding: the page follows each Rust decision (handoff, body,
// interpretation, validation, freshness, outbox scope) with no TS fallback. The
// decisions themselves are proven by web_apps/*_tests.rs over TS vectors.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.example.test${path}` }));
vi.mock('../../anonymousChatStorage', () => ({ anonymousChatStorage: { getAnonymousId: () => 'guest-1' } }));
vi.mock('../../../stores/authState', async () => ({ authStore: (await import('svelte/store')).writable({ isAuthenticated: true, isInitialized: true }) }));
vi.mock('../../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'user-A' }) }));
vi.mock('../../../stores/teamStore', async (importOriginal) => ({ ...(await importOriginal<object>()), activeTeamContext: (await import('svelte/store')).writable({ teamId: null, epoch: 0 }) }));
const executed: unknown[] = [];
vi.mock('../../appsWorkspaceService', () => ({
	getAppsSkillDetails: async () => ({ app_id: 'web', skill_id: 'search', input_schema: { type: 'object' } }),
	executeAppsSkill: async (_app: string, skill: string, input: unknown) => { executed.push({ skill, input }); return { success: true, data: { results: [] } }; },
}));
vi.mock('../../appsWorkspaceResultsService', () => ({ retainAppsResult: async () => 'embed-1' }));
vi.mock('../../appsWorkspaceImageRankingService', () => ({ rankAppsWorkspaceImageResults: async (body: unknown) => body }));
vi.mock('../../appsWorkspaceAttachmentService', () => ({ prepareAppsRequestAttachments: async () => ({ attachments: [], assets: {} }) }));

import { createSharedCoreClient, registerSharedRustCore, type SharedWorkerEndpoint } from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter } from '../host/sharedWorkerProtocol';
import { installAppsUnit } from '../apps/appsUnit';
import { rustAppsStats } from '../apps/appsUnitClient';
import type { AppsBinding } from '../apps/appsProtocol';
import { runRustAppsWorkspaceRequest, type AppsRequestDeps } from '../apps/rustAppsRequest';
import { assertRustOutboxScope, freshRustRecommendations } from '../apps/rustAppsRetention';
import type { PendingAppsResult } from '../../appsWorkspaceResultOutbox';

const calls: string[] = [];
let plan = '';
let interpretation = '';
let issues = '[]';
const unused = () => { throw new Error('protocol'); };
const binding: AppsBinding = {
	apps_details_request: unused, apps_details_outcome: unused, apps_execution_request: unused, apps_availability_request: unused,
	apps_availability_outcome: unused, apps_skill_response: unused, apps_poll_step: unused, apps_assemble_tasks: unused, apps_task_result: unused,
	apps_request_plan: (facts) => (calls.push(`plan ${JSON.parse(facts).text}`), plan),
	apps_request_body: (_facts, requestId, protectedText) => (calls.push(`body ${requestId} ${protectedText}`),
		JSON.stringify({ kind: 'send', body: `{"text":${JSON.stringify(protectedText)}}` })),
	apps_interpretation: (ok, text) => (calls.push(`interpret ${ok} ${text}`), interpretation),
	apps_validate_input: (_schema, input) => (calls.push(`validate ${input}`), issues),
	apps_retention_plan: unused,
	apps_outbox_scope_valid: (scope) => JSON.parse(scope).revision === 'ok',
	apps_fresh_recommendations: (items, now) => (calls.push(`fresh ${now}`), JSON.stringify(JSON.parse(items).length ? [1] : [])),
};

function fakeWorker() {
	const listeners: Record<string, ((event: Event) => void)[]> = { message: [], error: [], messageerror: [] };
	const router = createSharedWorkerRouter({
		installers: { apps: installAppsUnit },
		loadBinding: async () => binding,
		reply: (reply) => queueMicrotask(() => { for (const l of listeners.message) l({ data: reply } as MessageEvent); }),
	});
	const endpoint: SharedWorkerEndpoint = {
		postMessage(message, transfer) { void router.handle(message, transfer as MessagePort[]); },
		addEventListener(type, listener) { listeners[type].push(listener); },
		terminate() {},
	};
	return endpoint;
}

const deps: AppsRequestDeps = {
	identityGeneration: () => 0,
	requestPrivacy: async () => ({ protect: (t) => t.split('Alice').join('PERSON_1'), restore: (t) => t.split('PERSON_1').join('Alice'), assertCurrent: () => {} }),
};
const base = { appId: 'web', guest: false, locale: 'en-US', timezone: 'UTC' };

let unregister: (() => void) | null = null;
beforeEach(() => {
	calls.length = 0;
	executed.length = 0;
	issues = '[]';
	unregister = registerSharedRustCore(createSharedCoreClient(fakeWorker));
});
afterEach(() => {
	unregister?.();
	vi.unstubAllGlobals();
});

describe('flag-on Apps request adapter', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,apps.requests.natural-language
	it('sends the Rust body, restores and validates the interpreted input, then executes', async () => {
		plan = JSON.stringify({ kind: 'ok', text: 'Find Alice', requestId: 'req-9', next: { kind: 'protect' } });
		interpretation = JSON.stringify({ kind: 'execute', skillId: 'search', input: '{"q":"PERSON_1"}', reason: '"direct"' });
		const posts: string[] = [];
		vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => { posts.push(String(init?.body)); return new Response('{"action":"execute"}'); }));
		const before = rustAppsStats.calls;
		await expect(runRustAppsWorkspaceRequest({ ...base, text: ' Find Alice ' }, deps)).resolves.toEqual({
			action: 'execute', requestId: 'req-9', reason: 'direct', skillId: 'search', input: { q: 'Alice' }, embedId: 'embed-1',
		});
		expect(posts).toEqual(['{"text":"Find PERSON_1"}']);
		expect(executed).toEqual([{ skill: 'search', input: { q: 'Alice' } }]);
		expect(calls).toEqual(['plan  Find Alice ', 'body req-9 Find PERSON_1', 'interpret true {"action":"execute"}', 'validate {"q":"Alice"}']);
		expect(rustAppsStats.calls - before).toBe(4);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('follows Rust handoffs and errors without a TypeScript fallback', async () => {
		plan = JSON.stringify({ kind: 'ok', text: 'More', requestId: 'req-2', next: { kind: 'handoff', target: 'chat', reason: '"result_context_too_large"', identityFirst: true, unavailable: null } });
		const handoffs: unknown[] = [];
		await expect(runRustAppsWorkspaceRequest({ ...base, text: 'More', onChat: async (r) => { handoffs.push(r); } }, deps))
			.resolves.toEqual({ action: 'chat', requestId: 'req-2', reason: 'result_context_too_large' });
		expect(handoffs).toEqual([{ text: 'More', context: undefined, attachments: undefined, reason: 'result_context_too_large' }]);
		plan = JSON.stringify({ kind: 'error', message: 'request_required' });
		await expect(runRustAppsWorkspaceRequest({ ...base, text: ' ' }, deps)).rejects.toThrow('request_required');
		plan = JSON.stringify({ kind: 'ok', text: 'x', requestId: 'r', next: { kind: 'protect' } });
		interpretation = JSON.stringify({ kind: 'execute', skillId: 'search', input: '{}', reason: null });
		issues = '[{"code":"required","path":"q"}]';
		vi.stubGlobal('fetch', vi.fn(async () => new Response('{}')));
		await expect(runRustAppsWorkspaceRequest({ ...base, text: 'x' }, deps)).rejects.toThrow('invalid_native_input');
		expect(executed).toEqual([]);
		interpretation = JSON.stringify({ kind: 'syntax' });
		vi.stubGlobal('fetch', vi.fn(async () => new Response('{oops')));
		await expect(runRustAppsWorkspaceRequest({ ...base, text: 'x' }, deps)).rejects.toThrow(SyntaxError);
	});
});

describe('flag-on Apps result policy adapter', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('checks the outbox scope and recommendation freshness in Rust', async () => {
		const record = (revision: string) => ({ id: 'i', userId: 'u', teamId: null, rootEmbedId: 'r', revision, graph: { root_embed_id: 'r' } }) as unknown as PendingAppsResult;
		await expect(assertRustOutboxScope(record('ok'))).resolves.toBeUndefined();
		await expect(assertRustOutboxScope(record('bad'))).rejects.toThrow('Invalid Apps result outbox scope');
		await expect(freshRustRecommendations([{ id: 'a' }, { id: 'b' }], 5000)).resolves.toEqual([{ id: 'b' }]);
		expect(calls).toContain('fresh 5000');
	});
});
