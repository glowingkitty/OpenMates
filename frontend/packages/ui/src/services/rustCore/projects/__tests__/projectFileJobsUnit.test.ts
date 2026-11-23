// contract-test-file: tooling
// @vitest-environment node
/**
 * `projectFileJobs` unit: request marshalling onto the one borrowed admitted
 * client, strict step parsing (only claim/result/reject frames), validation and
 * stable core codes. The wasm client and the core lease are stubs.
 */
import { describe, expect, it, vi } from 'vitest';

import { createProjectFileJobsHandlers, parseProjectFileJobStep, type ProjectFileJobsClient } from '../projectFileJobsUnit';
import type { CoreClientBorrow } from '../../drafts/coreClientBorrow';

const SIGNAL = new AbortController().signal;
const STEP = {
	frames: [{ name: 'project_file_operation_claim', payload: { operation_id: 'op1' } }],
	prompts: [{ kind: 'write', operation_id: 'op1', chat_id: 'c1', project_id: 'p1' }],
	applied: [], notices: ['one'],
};

const PRIVACY = { projectId: 'p1', enabled: true, memories: [], sealed: null, mappings: [] };

function setup(client: Partial<ProjectFileJobsClient>, refusal?: 'none' | 'busy' | 'local') {
	const release = vi.fn();
	const borrow = { client, release, status: { handle: 'h1', generation: 4, principal: 'p' } } as unknown as CoreClientBorrow;
	const handlers = createProjectFileJobsHandlers('p', { borrow: async () => refusal ?? borrow }, new AbortController().signal);
	return { handlers, release };
}

describe('projectFileJobs handlers', () => {
	it('installs privacy then runs step and decide on the same borrowed client, in order, releasing each borrow', async () => {
		const calls: string[] = [];
		const client: ProjectFileJobsClient = {
			project_file_job_step: vi.fn(async () => { calls.push('step'); return JSON.stringify(STEP); }),
			project_file_job_decide: vi.fn(async () => { calls.push('decide'); return JSON.stringify({ ...STEP, prompts: [] }); }),
			project_file_job_set_mappings: vi.fn(() => { calls.push('mappings'); }),
			project_file_job_set_privacy: vi.fn(async () => { calls.push('privacy'); }),
			project_create_step: vi.fn(),
		};
		const { handlers, release } = setup(client);
		const event = { chat_id: 'c1', operation_id: 'op1' };
		const privacy = { projectId: 'p1', enabled: true, memories: [{ r: 1 }], sealed: null, mappings: [{ a: 1 }] };
		await expect(handlers.step({ kind: 'project_file_operation_request', event, interactive: true, privacy }, SIGNAL)).resolves.toEqual(STEP);
		expect(calls).toEqual(['mappings', 'privacy', 'step']);
		expect(client.project_file_job_set_mappings).toHaveBeenCalledWith('h1', 4, 'c1', '[{"a":1}]');
		expect(client.project_file_job_set_privacy).toHaveBeenCalledWith('h1', 4, 'c1', 'p1', true, '[{"r":1}]', null);
		expect(client.project_file_job_step).toHaveBeenCalledWith('h1', 4, 'project_file_operation_request', JSON.stringify(event), true);
		calls.length = 0;
		const decided = await handlers.decide({ chatId: 'c1', operationId: 'op1', accept: false, privacy }, SIGNAL);
		expect(decided.prompts).toEqual([]);
		expect(calls).toEqual(['mappings', 'privacy', 'decide']);
		expect(client.project_file_job_decide).toHaveBeenCalledWith('h1', 4, 'c1', 'op1', false);
		expect(release).toHaveBeenCalledTimes(2);
	});

	it('still steps when set_privacy is refused and reports the code as privacyError', async () => {
		const client = {
			project_file_job_step: vi.fn(async () => JSON.stringify(STEP)),
			project_file_job_decide: vi.fn(async () => JSON.stringify(STEP)),
			project_file_job_set_mappings: vi.fn(),
			project_file_job_set_privacy: vi.fn(async () => { throw 'pii_mapping_unavailable'; }),
		};
		const { handlers } = setup(client as unknown as ProjectFileJobsClient);
		const privacy = { projectId: 'p1', enabled: true, memories: [], sealed: 'x', mappings: [] };
		const step = await handlers.step({ kind: 'project_file_operation_request', event: { chat_id: 'c1' }, interactive: true, privacy }, SIGNAL);
		expect(step).toEqual({ ...STEP, privacyError: 'pii_mapping_unavailable' });
		expect(client.project_file_job_step).toHaveBeenCalledTimes(1);
		const decided = await handlers.decide({ chatId: 'c1', operationId: 'op1', accept: true, privacy }, SIGNAL);
		expect(decided.privacyError).toBe('pii_mapping_unavailable');
	});

	it('asks the borrow for the client that last ran the same chat, so its pending approval answer reaches it', async () => {
		const client = {
			project_file_job_step: vi.fn(async () => JSON.stringify(STEP)),
			project_file_job_decide: vi.fn(async () => JSON.stringify({ ...STEP, prompts: [] })),
			project_file_job_set_mappings: vi.fn(),
			project_file_job_set_privacy: vi.fn(async () => {}),
			project_create_step: vi.fn(async () => 'null'),
		};
		const borrowed = { client, release: vi.fn(), status: { handle: 'h1', generation: 4, principal: 'p' } } as unknown as CoreClientBorrow;
		const borrow = vi.fn(async () => borrowed);
		const handlers = createProjectFileJobsHandlers('p', { borrow }, SIGNAL);
		await handlers.step({ kind: 'project_file_operation_request', event: { chat_id: 'c1' }, interactive: true, privacy: PRIVACY }, SIGNAL);
		await handlers.decide({ chatId: 'c1', operationId: 'op1', accept: true, privacy: PRIVACY }, SIGNAL);
		await handlers.step({ kind: 'project_file_operation_request', event: { chat_id: 'c2' }, interactive: true, privacy: PRIVACY }, SIGNAL);
		await handlers.createStep({ kind: 'project_create_requested', event: { chat_id: 'c1' } }, SIGNAL);
		const preferred = borrow.mock.calls.map((call) => (call as unknown[])[3]);
		expect(preferred).toEqual([undefined, client, undefined, client]);
	});

	it('refuses a step whose frame is not claim, result or reject', () => {
		const bad = (frame: unknown) => JSON.stringify({ ...STEP, frames: [frame] });
		expect(() => parseProjectFileJobStep(bad({ name: 'chat_message_added', payload: {} }))).toThrow(/project_file_jobs_protocol/);
		expect(() => parseProjectFileJobStep(bad({ name: 'project_file_operation_result' }))).toThrow(/project_file_jobs_protocol/);
		expect(() => parseProjectFileJobStep('not json')).toThrow(/project_file_jobs_protocol/);
		expect(() => parseProjectFileJobStep(JSON.stringify({ frames: [] }))).toThrow(/project_file_jobs_protocol/);
		expect(() => parseProjectFileJobStep(42)).toThrow(/project_file_jobs_protocol/);
		for (const name of ['project_file_operation_claim', 'project_file_operation_result', 'project_file_operation_reject']) {
			expect(parseProjectFileJobStep(bad({ name, payload: {} })).frames).toHaveLength(1);
		}
	});

	it('keeps an optional privacy slot only when well-formed', () => {
		const privacy = { chat_id: 'c', project_id: 'p', ciphertext: 'x' };
		expect(parseProjectFileJobStep(JSON.stringify({ ...STEP, privacy })).privacy).toEqual(privacy);
		expect(parseProjectFileJobStep(JSON.stringify(STEP)).privacy).toBeUndefined();
		expect(() => parseProjectFileJobStep(JSON.stringify({ ...STEP, privacy: { chat_id: 'c' } }))).toThrow(/protocol/);
	});

	it('maps core codes, hides internal text and refuses protocol-breaking core output', async () => {
		// Every step installs the chat's privacy inputs first; those calls succeed here.
		const installs = { project_file_job_set_mappings: vi.fn(), project_file_job_set_privacy: vi.fn(async () => {}) };
		const stringCode = setup({ ...installs, project_file_job_step: vi.fn(async () => { throw 'forbidden'; }) });
		const payload = { kind: 'project_file_operation_available' as const, event: { chat_id: 'c1' }, interactive: false, privacy: PRIVACY };
		await expect(stringCode.handlers.step(payload, SIGNAL)).rejects.toMatchObject({ code: 'forbidden' });
		expect(stringCode.release).toHaveBeenCalledTimes(1);
		const internal = setup({ ...installs, project_file_job_step: vi.fn(async () => { throw new Error('Secret path /x failed'); }) });
		await expect(internal.handlers.step(payload, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_failed' });
		const evil = setup({ ...installs, project_file_job_step: vi.fn(async () => JSON.stringify({ ...STEP, frames: [{ name: 'x', payload: {} }] })) });
		await expect(evil.handlers.step(payload, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_protocol' });
	});

	it('validates requests without borrowing and maps unadmitted leases to refusals', async () => {
		const borrow = vi.fn();
		const handlers = createProjectFileJobsHandlers('p', { borrow }, SIGNAL);
		await expect(handlers.step({ kind: 'other', event: {}, interactive: true, privacy: PRIVACY } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_kind' });
		await expect(handlers.step({ kind: 'project_file_operation_request', event: [], interactive: true, privacy: PRIVACY } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_event' });
		await expect(handlers.step({ kind: 'project_file_operation_request', event: { chat_id: 'c1' }, privacy: PRIVACY } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_interactive' });
		await expect(handlers.decide({ chatId: '', operationId: 'o', accept: true, privacy: PRIVACY }, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_chat' });
		await expect(handlers.decide({ chatId: 'c', operationId: 'o', accept: 'yes', privacy: PRIVACY } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_accept' });
		await expect(handlers.step({ kind: 'project_file_operation_request', event: { chat_id: 'c' }, interactive: true } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_privacy' });
		await expect(handlers.decide({ chatId: 'c', operationId: 'o', accept: true, privacy: { ...PRIVACY, mappings: {} } } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_mappings' });
		await expect(handlers.decide({ chatId: 'c', operationId: 'o', accept: true, privacy: { ...PRIVACY, enabled: 1 } } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_enabled' });
		await expect(handlers.decide({ chatId: 'c', operationId: 'o', accept: true, privacy: { ...PRIVACY, sealed: 3 } } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_sealed' });
		expect(borrow).not.toHaveBeenCalled();
		const decide = { chatId: 'c', operationId: 'o', accept: true, privacy: PRIVACY };
		await expect(setup({}, 'none').handlers.decide(decide, SIGNAL)).rejects.toMatchObject({ code: 'not_admitted' });
		await expect(setup({}, 'busy').handlers.decide(decide, SIGNAL)).rejects.toMatchObject({ code: 'core_busy' });
		await expect(setup({}, 'local').handlers.decide(decide, SIGNAL)).rejects.toMatchObject({ code: 'local_session' });
	});
});
