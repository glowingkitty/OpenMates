// `apps` unit of the shared Rust core Worker: the real router and installer over
// a scripted binding (the Rust decisions themselves are proven by
// web_apps_tests.rs over the TS-generated vectors), and the flag-on page adapter
// (rustAppsSkillExecution.ts) following those decisions with no TS fallback.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createSharedCoreClient, registerSharedRustCore, type SharedWorkerEndpoint } from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter } from '../host/sharedWorkerProtocol';
import { installAppsUnit } from '../apps/appsUnit';
import { rustAppsStats } from '../apps/appsUnitClient';
import { createRustAppsSkillExecution, type AppsServiceDeps } from '../apps/rustAppsSkillExecution';
import type { AppsBinding } from '../apps/appsProtocol';
import type { AppsSkillDetails } from '../../../types/appsWorkspace';

const calls: string[] = [];
const binding: AppsBinding = {
	apps_details_request: (app, skill, hasSignal) => (calls.push(`detailsRequest ${app}/${skill} ${hasSignal}`),
		JSON.stringify({ path: `/v1/apps/${app}/skills/${skill}/details`, credentials: 'omit', cacheable: !hasSignal })),
	apps_details_outcome: (status) => JSON.stringify(status === 200 ? { kind: 'ok', valid: true } : { kind: 'error', message: 'details_failed' }),
	apps_execution_request: (app, skill, guest, teamId, metadata) => {
		calls.push(`executionRequest ${guest} ${teamId} ${JSON.parse(metadata).app_id}`);
		return JSON.stringify({ kind: 'ok', path: `/v1/apps/${app}/skills/${skill}`, teamId: teamId || null, availabilityPath: null });
	},
	apps_availability_request: () => JSON.stringify({ path: '/v1/anonymous/apps/web/skills/search/availability' }),
	apps_availability_outcome: () => JSON.stringify({ allowed: true, reason: null }),
	apps_skill_response: (_status, _ok, text) => JSON.stringify(text.includes('task_id')
		? { kind: 'tasks', ids: ['task-1'] } : text === 'bad' ? { kind: 'error', message: 'provider_failed' } : { kind: 'done', valid: true }),
	apps_poll_step: (_id, _status, _ok, text) => JSON.stringify(text.includes('completed') ? { kind: 'completed' }
		: { kind: 'retry', delayMs: 1, deadlineMs: 60_000, timeoutMessage: 'still processing' }),
	apps_assemble_tasks: (envelope, polls, checkFailure) => {
		calls.push(`assemble ${checkFailure} ${JSON.parse(polls).length}`);
		return JSON.stringify({ kind: 'done', text: `{"envelope":${envelope},"data":${JSON.stringify(JSON.parse(JSON.parse(polls)[0]).result)}}` });
	},
	apps_task_result: () => { throw new Error('protocol'); },
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

const metadata = { app_id: 'web', skill_id: 'search', execution_available: true, execution_mode: 'sync', anonymous_allowed: false } as AppsSkillDetails;
const deps: AppsServiceDeps = {
	apiEndpoint: (path) => `https://api.example.test${path}`,
	anonymousId: () => 'guest-1',
	authGeneration: () => 0,
	captureIdentity: () => ({ userId: 'user-A', anonymousId: null, authGeneration: 0 }),
	assertIdentity: () => {},
};

let unregister: (() => void) | null = null;
beforeEach(() => {
	calls.length = 0;
	unregister = registerSharedRustCore(createSharedCoreClient(fakeWorker));
});
afterEach(() => {
	unregister?.();
	vi.unstubAllGlobals();
});

describe('shared apps unit', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses a binding without the apps exports', () => {
		const channel = new MessageChannel();
		expect(() => installAppsUnit({ binding: {}, ports: [channel.port2], generation: null, principal: null, signal: new AbortController().signal }))
			.toThrow('unavailable');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('executes a synchronous skill from the unit decisions and returns the parsed body', async () => {
		const posts: string[] = [];
		vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => { posts.push(`${init?.method} ${url}`); return new Response('{"success":true,"data":{"b":1,"a":2}}'); }));
		const apps = createRustAppsSkillExecution(deps);
		const before = rustAppsStats.calls;
		await expect(apps.executeAppsSkill('web', 'search', { q: 'x' }, { guest: false, teamId: 'team-1', metadata }))
			.resolves.toEqual({ success: true, data: { b: 1, a: 2 } });
		expect(posts).toEqual(['POST https://api.example.test/v1/apps/web/skills/search?team_id=team-1']);
		expect(calls).toEqual(['executionRequest false team-1 web']);
		expect(rustAppsStats.calls - before).toBe(2);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('polls accepted tasks until Rust reports completion and returns the Rust-assembled envelope', async () => {
		const polls = ['{"status":"processing"}', '{"status":"completed","result":{"z":1}}'];
		vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(url.includes('/v1/tasks/') ? polls.shift()! : '{"data":{"task_id":"task-1"}}')));
		const submitted: string[] = [];
		const apps = createRustAppsSkillExecution(deps);
		await expect(apps.executeAppsSkill('web', 'search', { q: 'y' }, { guest: false, metadata, onTaskSubmitted: async (id) => { submitted.push(id); } }))
			.resolves.toEqual({ envelope: { data: { task_id: 'task-1' } }, data: { z: 1 } });
		expect(submitted).toEqual(['task-1']);
		expect(calls).toContain('assemble true 1');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('surfaces Rust failures and refusals without a TypeScript fallback', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response('bad')));
		const apps = createRustAppsSkillExecution(deps);
		await expect(apps.executeAppsSkill('web', 'search', { q: 'z' }, { guest: false, metadata })).rejects.toThrow('provider_failed');
		vi.stubGlobal('fetch', vi.fn(async () => new Response('{"status":"completed","result":1}')));
		await expect(apps.pollAppsSkillTask('task-9')).rejects.toThrow('protocol');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('caches public details only when Rust marks them cacheable', async () => {
		const fetchMock = vi.fn(async () => Response.json({ app_id: 'web' }));
		vi.stubGlobal('fetch', fetchMock);
		const apps = createRustAppsSkillExecution(deps);
		await apps.getAppsSkillDetails('web', 'search');
		await apps.getAppsSkillDetails('web', 'search');
		await apps.getAppsSkillDetails('web', 'search', new AbortController().signal);
		expect(fetchMock).toHaveBeenCalledTimes(2);
		expect(calls).toEqual(['detailsRequest web/search false', 'detailsRequest web/search true']);
	});
});
