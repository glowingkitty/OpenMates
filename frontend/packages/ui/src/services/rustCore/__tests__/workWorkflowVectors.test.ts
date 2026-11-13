import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { webcrypto } from 'node:crypto';
import { beforeEach, describe, expect, it, vi } from 'vitest';

Object.defineProperty(globalThis, 'crypto', { configurable: true, value: webcrypto });

vi.mock('../../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock('../../cryptoService', () => ({
	decryptChatKeyWithMasterKey: vi.fn(async () => new Uint8Array(32).fill(3)),
	encryptChatKeyWithMasterKey: vi.fn(async () => 'wrapped-master'),
	decryptWithEmbedKey: vi.fn(async () => null),
	encryptWithEmbedKey: vi.fn(async () => 'sealed'),
}));
vi.mock('../../shortUrlEncryption', () => ({
	generateShortUrlParts: () => ({ token: 'tok/1', shortKey: 'short' }),
	encryptShareUrl: vi.fn(async (url: string) => `enc:${url.length}`),
	buildShortUrlDecided: vi.fn(async (token: string) => `https://s.test/${token}`),
}));
vi.mock('../../projectCreationNavigation', () => ({ syncBoundWorkflowRemoteFiles: vi.fn(async () => undefined) }));

import * as templates from '../../workflowTemplateService';
import * as inputs from '../../workflowInputService';
import { listAppsWorkflows } from '../../appsWorkflowLibraryService';
import { loadWorkflowRunPreviewMetadata } from '../../workflowRunPreviewMetadata';
import { workflowWorkspaceStore, type WorkflowDetail } from '../../../stores/workflowWorkspaceStore';
import { setActiveTeamContext } from '../../../stores/teamStore';
import type { TeamViewModel } from '../../teamService';
import {
	FRESH_ID, VALID_PAYLOAD, importCases, libraryCases, payloadCases, previewCases, projectionCases, sessionCases, validateCases, workflow,
} from './helpers/workWorkflowCases';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_work/workflows_ts_vectors.json');
type Json = Record<string, unknown>;
type Reply = { status: number; body: unknown };

let respond: (url: string, method: string) => Reply = () => ({ status: 200, body: {} });
let requests: Array<{ url: string; init?: RequestInit }> = [];

const json = <T>(value: T): T => (value === undefined ? value : (JSON.parse(JSON.stringify(value)) as T));
const strip = (url: string) => url.replace(/^https:\/\/api\.test/, '');
const message = (error: unknown) => ({ error: (error as Error).message });
const ok = (body: unknown): Reply => ({ status: 200, body });

/** Runs one call; the outcome is its value or `{error}` with the thrown message. */
async function attempt<T>(run: () => Promise<T> | T): Promise<T | { error: string }> {
	try { return await run(); } catch (error) { return message(error); }
}

async function decisions(): Promise<Json[]> {
	const out: Json[] = [];
	// Ordered ops: input and expected are compared as JSON text (TS key order).
	const push = (name: string, op: string, input: unknown, expected: unknown) => out.push({
		name, op, input_text: JSON.stringify(input), expected_text: JSON.stringify(expected),
	});
	for (const c of payloadCases) {
		const result = await attempt(() => templates.buildWorkflowTemplatePayload(c.workflow as unknown as WorkflowDetail));
		push(c.name, 'workflowTemplatePayload', { workflow: c.workflow }, 'error' in (result as Json) ? result : { payload: result });
	}
	for (const c of validateCases) {
		const result = await attempt(() => templates.validateWorkflowTemplatePayload(c.value));
		push(c.name, 'workflowTemplateValidate', { value: c.value }, result && typeof result === 'object' && 'error' in result ? result : { ok: true });
	}
	for (const c of projectionCases) {
		respond = () => ok(c.projection);
		const result = await attempt(() => templates.loadSharedWorkflowTemplate(c.templateId, 'AAAA'));
		const compat = (result as Json).error === 'Workflow template projection is not compatible with this app version.';
		push(c.name, 'workflowTemplateProjectionCheck', { template_id: c.templateId, projection: c.projection }, compat ? result : { ok: true });
	}
	for (const c of importCases) {
		respond = () => ok(c.reply);
		const result = await attempt(() => templates.importWorkflowTemplate(VALID_PAYLOAD as unknown as templates.WorkflowTemplatePayload));
		push(c.name, 'workflowTemplateImportCheck', { response: c.reply }, 'error' in (result as Json) ? result : { ok: true });
	}
	for (const c of sessionCases) {
		respond = () => ok({ session: c.session });
		push(c.name, 'workflowInputSession', { session: c.session }, { session: await inputs.getWorkflowInstruction('s-1') });
	}
	for (const c of libraryCases) {
		respond = () => ok(c.reply);
		push(c.name, 'workflowAppsLibraryPage', { result: c.reply }, await withTeam(c.args[1], () => listAppsWorkflows(...c.args)));
	}
	for (const c of previewCases) {
		respond = (url) => {
			const target = url.includes('/runs/') ? c.run : c.workflow;
			return target === 'fail' ? { status: 500, body: {} } : ok(url.includes('/runs/') ? { run: target } : { workflow: target });
		};
		const merged = await loadWorkflowRunPreviewMetadata(c.provenance as never);
		const fetched = (target: Json | 'fail' | undefined) => (target === 'fail' ? undefined : target);
		push(c.name, 'workflowRunPreviewMerge', { provenance: c.provenance, workflow: fetched(c.workflow), run: fetched(c.run) }, merged);
	}
	return out;
}

/** Runs with the active team set (workflowApiFetch refuses a foreign `team_id` otherwise). */
async function withTeam<T>(teamId: string | undefined, run: () => Promise<T>): Promise<T> {
	if (teamId) setActiveTeamContext({ team_id: teamId } as TeamViewModel);
	try { return await run(); } finally { if (teamId) setActiveTeamContext(null); }
}

async function paths(): Promise<Json[]> {
	const out: Json[] = [];
	const reply = { workflow: { id: 'wf/1', title: 'T', lifecycle: 'reusable' }, run: { id: 'r?1', status: 'ok' }, status: 'deleted', version: {}, session: { session_id: 's' } };
	const record = async (name: string, op: string, input: Json, run: () => Promise<unknown>, index = 0) => {
		requests = [];
		respond = () => ok(reply);
		await run();
		out.push({ name, op, input, expected: strip(requests[index].url) });
	};
	const store = workflowWorkspaceStore;
	await record('save as reusable', 'workflowPath', { route: 'save_reusable', workflow_id: 'wf/1' }, () => store.saveAsReusableWorkflow('wf/1', 'k'));
	await record('binding complete', 'workflowPath', { route: 'binding_complete', workflow_id: 'wf/1' }, () => store.completeBindingRequirement('wf/1', { type: 'x', node_id: 'n' } as never));
	await record('patch', 'workflowPath', { route: 'detail', workflow_id: 'wf/1' }, () => store.patchWorkflow('wf/1', {}));
	await record('versions', 'workflowPath', { route: 'versions', workflow_id: 'wf/1' }, () => store.getWorkflowVersions('wf/1'));
	await record('version', 'workflowPath', { route: 'version', workflow_id: 'wf/1', version_id: 'v 1' }, () => store.getWorkflowVersion('wf/1', 'v 1'));
	await record('restore', 'workflowPath', { route: 'restore', workflow_id: 'wf/1', version_id: 'v 1' }, () => store.restoreWorkflowVersion('wf/1', 'v 1'));
	await record('enable', 'workflowPath', { route: 'toggle', workflow_id: 'wf/1', enabled: true }, () => store.setWorkflowEnabled('wf/1', true));
	await record('disable', 'workflowPath', { route: 'toggle', workflow_id: 'wf/1', enabled: false }, () => store.setWorkflowEnabled('wf/1', false));
	await record('run detail', 'workflowPath', { route: 'run_detail', workflow_id: 'wf/1', run_id: 'r?1' }, () => store.getWorkflowRun('wf/1', 'r?1'));
	await record('cancel run', 'workflowPath', { route: 'cancel', workflow_id: 'wf/1', run_id: 'r?1' }, () => store.cancelWorkflowRun('wf/1', 'r?1'));
	await record('delete run', 'workflowPath', { route: 'run_detail', workflow_id: 'wf/1', run_id: 'r?1' }, () => store.deleteWorkflowRun('wf/1', 'r?1'));
	await record('delete workflow', 'workflowPath', { route: 'detail', workflow_id: 'wf/1' }, () => store.deleteWorkflow('wf/1'));
	for (const route of ['get', 'stop', 'undo'] as const) {
		const run = { get: inputs.getWorkflowInstruction, stop: inputs.stopWorkflowInstruction, undo: inputs.undoWorkflowInstruction }[route];
		await record(`input ${route}`, 'workflowInputPath', { route, session_id: 'a/b c' }, () => run('a/b c'));
	}
	await record('unrevoke', 'workflowTemplatePath', { route: 'unrevoke', workflow_id: 'wf/1' }, () => templates.unrevokeWorkflowTemplateShare('wf/1'));
	await record('public projection', 'workflowTemplatePath', { route: 'public', template_id: 'wt 1' }, () => attempt(() => templates.loadSharedWorkflowTemplate('wt 1', 'AAAA')));
	await record('projection', 'workflowTemplatePath', { route: 'projection', workflow_id: 'wf/1' }, () => attempt(() => templates.upsertWorkflowTemplateProjection(workflow({ id: 'wf/1' }) as never)));
	// A share leaves a short token, so revoking also deletes the short URL.
	respond = () => ok({ template_id: 'wt_9', source_version: 3, updated_at: 1, owner_wrapped_key: 'w', ciphertext: 'c', ciphertext_checksum: 'x', projection_schema_version: 1, revoked_at: null });
	await templates.createWorkflowTemplateShare(workflow({ id: 'wf/1' }) as never);
	await record('revoke', 'workflowTemplatePath', { route: 'revoke', workflow_id: 'wf/1' }, () => templates.revokeWorkflowTemplateShare('wf/1'));
	await record('short url delete', 'workflowTemplatePath', { route: 'short_url_delete', token: 'tok/1' }, () => templates.revokeWorkflowTemplateShare('wf/1'), 1);
	for (const c of libraryCases) {
		const [appId, teamId, offset = 0, limit = 20] = c.args;
		await record(c.name, 'workflowAppsLibraryPath', json({ app_id: appId, team_id: teamId, offset, limit }), () => attempt(() => withTeam(teamId, () => listAppsWorkflows(...c.args))));
	}
	for (const c of previewCases) {
		requests = [];
		respond = (url) => ok(url.includes('/runs/') ? { run: {} } : { workflow: {} });
		await loadWorkflowRunPreviewMetadata(c.provenance as never);
		const urls = requests.map((r) => strip(r.url));
		out.push({ name: c.name, op: 'workflowRunPreviewPaths', input: { provenance: c.provenance }, expected: {
			workflow: urls.find((u) => !u.includes('/runs/')) ?? null, run: urls.find((u) => u.includes('/runs/')) ?? null,
		} });
	}
	return out;
}

async function bodies(): Promise<Json[]> {
	const out: Json[] = [];
	const vector = async (name: string, op: string, input: Json, slots: string[], run: () => Promise<unknown>, pick: 'first' | 'last' = 'last', reply: (url: string, method: string) => Reply = () => ok({ workflow: { id: 'wf-1' }, run: { id: 'r', status: 'queued' }, session: { session_id: 's' } })) => {
		requests = [];
		respond = reply;
		const result = await attempt(run);
		const sent = requests.filter((r) => r.init?.method && r.init.method !== 'GET');
		const chosen = pick === 'first' ? sent[0] : sent[sent.length - 1];
		const error = result && typeof result === 'object' && 'error' in (result as Json) ? result : null;
		const body = chosen ? JSON.parse(String(chosen.init?.body)) as Json : null;
		const key = chosen ? new Headers(chosen.init?.headers).get('Idempotency-Key') : null;
		out.push({ name, op, input: json(input), slots, expected: json(error && !chosen ? error : {
			path: strip(String(chosen?.url)), method: chosen?.init?.method, body, keys: Object.keys(body ?? {}), ...(key !== null ? { idempotency_key: key } : {}),
		}) });
	};
	const graph = (workflow().graph as Json);
	const create = [
		{ name: 'create in the personal workspace', input: { title: 'T', description: 'D', category: 'c', icon: 'i', graph, enabled: true, runContentRetention: 'last_5' } },
		{ name: 'create with an explicit null team', input: { title: 'T', graph, enabled: false, runContentRetention: 'none', teamId: null } },
		{ name: 'create for another workspace is refused', input: { title: 'T', graph, enabled: false, runContentRetention: 'none', teamId: 'team-x' } },
	];
	for (const c of create) {
		await vector(c.name, 'workflowCreateBody', { input: c.input, context_team_id: null }, ['graph'], () => workflowWorkspaceStore.createWorkflow(c.input as never));
	}
	const runs = [
		{ name: 'run with defaults', invocation: {}, slots: [] },
		{ name: 'run with every option', invocation: { mode: 'manual', input: { b: 1, a: 2 }, sourceChatId: 'c', messageDestinationOverrides: { x: 'y' }, returnOutputs: { n: { a: 'b' } }, idempotencyKey: 'k' }, slots: ['input', 'message_destination_overrides', 'return_outputs'] },
		{ name: 'run with null input and empty strings', invocation: { input: null, sourceChatId: '', idempotencyKey: '' }, slots: [] },
	];
	for (const c of runs) {
		await vector(c.name, 'workflowRunBody', { workflow_id: 'wf 1', invocation: c.invocation, uuid: FRESH_ID }, c.slots, () => workflowWorkspaceStore.runWorkflow('wf 1', c.invocation as never));
	}
	const notFound = (url: string, method: string): Reply => (method === 'GET' ? { status: 404, body: {} } : ok({ template_id: FRESH_ID, source_version: 3, updated_at: 1 }));
	const upsertSlots = ['ciphertext', 'ciphertext_checksum', 'owner_wrapped_key'];
	await vector('first projection of a workflow', 'workflowTemplateUpsertBody', { workflow_id: 'wf/1', template_id: `wt_${FRESH_ID.replace(/-/g, '')}`, version: 3 }, upsertSlots,
		() => templates.upsertWorkflowTemplateProjection(workflow({ id: 'wf/1' }) as never), 'last', notFound);
	await vector('projection without a version', 'workflowTemplateUpsertBody', { workflow_id: 'wf-1', template_id: `wt_${FRESH_ID.replace(/-/g, '')}` }, upsertSlots,
		() => templates.upsertWorkflowTemplateProjection({ ...workflow(), version: undefined } as never), 'last', notFound);
	const existing = () => ok({ template_id: 'wt_old', source_version: 1, updated_at: 1, owner_wrapped_key: 'w', ciphertext: 'c', ciphertext_checksum: 'x', projection_schema_version: 1, revoked_at: null });
	await vector('existing projection keeps its template id', 'workflowTemplateUpsertBody', { workflow_id: 'wf-1', template_id: 'wt_old', version: 3 }, upsertSlots,
		() => templates.upsertWorkflowTemplateProjection(workflow() as never), 'last', existing);
	await vector('short url registration', 'workflowTemplateShortUrlBody', { token: 'tok/1', template_id: 'wt_old' }, ['encrypted_url'],
		() => templates.createWorkflowTemplateShare(workflow() as never), 'last', existing);
	await vector('binding completion', 'workflowTemplateBindingBody', { workflow_id: 'wf/2', requirement: { type: 'app_skill', node_id: 'a', app_id: 'web' } }, [],
		() => templates.completeWorkflowTemplateBinding('wf/2', { type: 'app_skill', node_id: 'a', app_id: 'web' }));
	const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
	await vector('instruction for a selected workflow', 'workflowInputBody', { route: 'input', text: 'Make it daily', selected_workflow_id: 'wf-1', timezone }, [],
		() => inputs.submitWorkflowInstruction('Make it daily', 'wf-1'));
	await vector('instruction without a selection', 'workflowInputBody', { route: 'input', text: 'New', timezone }, [], () => inputs.submitWorkflowInstruction('New'));
	const stream = () => ({ status: 200, body: 'data: {"type":"session","session":{"session_id":"s","status":"executed"}}\n\n' });
	await vector('streamed instruction with an idempotency key', 'workflowInputBody', { route: 'stream', text: 'Go', timezone, idempotency_key: 'idem-1' }, [],
		() => inputs.streamWorkflowInstruction('Go', undefined, () => undefined, undefined, 'idem-1'), 'last', stream);
	const resolved = Intl.DateTimeFormat.prototype.resolvedOptions;
	vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockImplementation(function (this: Intl.DateTimeFormat) {
		return { ...resolved.call(this), timeZone: '' };
	});
	await vector('an empty timezone falls back to UTC', 'workflowInputBody', { route: 'input', text: 'Go', timezone: '' }, [], () => inputs.submitWorkflowInstruction('Go'));
	return out;
}

describe('Workflow work parity vectors (TypeScript side)', () => {
	beforeEach(() => {
		window.localStorage.clear();
		workflowWorkspaceStore.reset();
		vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(FRESH_ID);
		vi.spyOn(globalThis.crypto, 'getRandomValues').mockImplementation(((array: ArrayBufferView) => {
			new Uint8Array(array.buffer).fill(7);
			return array;
		}) as typeof globalThis.crypto.getRandomValues);
		vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
			requests.push({ url: String(url), init });
			const reply = respond(String(url), init?.method ?? 'GET');
			const text = typeof reply.body === 'string' ? reply.body : JSON.stringify(reply.body);
			return new Response(text, { status: reply.status, headers: { 'content-type': 'application/json' } });
		});
	});

	// contract-test: supporting surface=gui.web assertions=workflows.portability.private-content-boundary,workflows.portability.disabled-validated-import,workflows.authoring.atomic-update
	it('the flag-off workflow services reproduce every committed vector', async () => {
		const fresh = json({ decisions: await decisions(), paths: await paths(), bodies: await bodies() });
		if (process.env.WORK_VECTORS_WRITE === '1') writeFileSync(VECTORS, `${JSON.stringify(fresh, null, 1)}\n`);
		let committed: unknown = null;
		try { committed = JSON.parse(readFileSync(VECTORS, 'utf8')); } catch { /* First generation: no committed file yet. */ }
		// Hosts that cannot write the file (isolated CI) get the regenerated document in the log.
		if (JSON.stringify(fresh) !== JSON.stringify(committed)) console.log(`WORK_VECTORS_FRESH_BEGIN\n${JSON.stringify(fresh, null, 1)}\nWORK_VECTORS_FRESH_END`);
		expect((fresh.decisions as unknown[]).length + (fresh.bodies as unknown[]).length).toBeGreaterThanOrEqual(60);
		expect(fresh).toEqual(committed);
	});
});
