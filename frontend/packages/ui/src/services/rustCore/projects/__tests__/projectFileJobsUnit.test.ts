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

function setup(client: Partial<ProjectFileJobsClient>, refusal?: 'none' | 'busy' | 'local') {
	const release = vi.fn();
	const borrow = { client, release, status: { handle: 'h1', generation: 4, principal: 'p' } } as unknown as CoreClientBorrow;
	const handlers = createProjectFileJobsHandlers('p', { borrow: async () => refusal ?? borrow }, new AbortController().signal);
	return { handlers, release };
}

describe('projectFileJobs handlers', () => {
	it('marshals step, decide and setMappings onto the borrowed client and releases each borrow', async () => {
		const client: ProjectFileJobsClient = {
			project_file_job_step: vi.fn(async () => JSON.stringify(STEP)),
			project_file_job_decide: vi.fn(async () => JSON.stringify({ ...STEP, prompts: [] })),
			project_file_job_set_mappings: vi.fn(),
			project_file_job_set_privacy: vi.fn(async () => undefined),
		};
		const { handlers, release } = setup(client);
		const event = { chat_id: 'c1', operation_id: 'op1' };
		await expect(handlers.step({ kind: 'project_file_operation_request', event, interactive: true }, SIGNAL)).resolves.toEqual(STEP);
		expect(client.project_file_job_step).toHaveBeenCalledWith('h1', 4, 'project_file_operation_request', JSON.stringify(event), true);
		const decided = await handlers.decide({ chatId: 'c1', operationId: 'op1', accept: false }, SIGNAL);
		expect(decided.prompts).toEqual([]);
		expect(client.project_file_job_decide).toHaveBeenCalledWith('h1', 4, 'c1', 'op1', false);
		await expect(handlers.setMappings({ chatId: 'c1', mappings: [{ a: 1 }] }, SIGNAL)).resolves.toEqual({ ok: true });
		expect(client.project_file_job_set_mappings).toHaveBeenCalledWith('h1', 4, 'c1', '[{"a":1}]');
		await expect(handlers.setPrivacy({ chatId: 'c1', projectId: 'p1', enabled: true, memories: [{ r: 1 }], sealed: null }, SIGNAL)).resolves.toEqual({ ok: true });
		expect(client.project_file_job_set_privacy).toHaveBeenCalledWith('h1', 4, 'c1', 'p1', true, '[{"r":1}]', null);
		expect(release).toHaveBeenCalledTimes(4);
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
		const stringCode = setup({ project_file_job_step: vi.fn(async () => { throw 'forbidden'; }) });
		const payload = { kind: 'project_file_operation_available' as const, event: {}, interactive: false };
		await expect(stringCode.handlers.step(payload, SIGNAL)).rejects.toMatchObject({ code: 'forbidden' });
		expect(stringCode.release).toHaveBeenCalledTimes(1);
		const internal = setup({ project_file_job_step: vi.fn(async () => { throw new Error('Secret path /x failed'); }) });
		await expect(internal.handlers.step(payload, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_failed' });
		const evil = setup({ project_file_job_step: vi.fn(async () => JSON.stringify({ ...STEP, frames: [{ name: 'x', payload: {} }] })) });
		await expect(evil.handlers.step(payload, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_protocol' });
	});

	it('validates requests without borrowing and maps unadmitted leases to refusals', async () => {
		const borrow = vi.fn();
		const handlers = createProjectFileJobsHandlers('p', { borrow }, SIGNAL);
		await expect(handlers.step({ kind: 'other', event: {}, interactive: true } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_kind' });
		await expect(handlers.step({ kind: 'project_file_operation_request', event: [], interactive: true } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_event' });
		await expect(handlers.step({ kind: 'project_file_operation_request', event: {} } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_interactive' });
		await expect(handlers.decide({ chatId: '', operationId: 'o', accept: true }, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_chat' });
		await expect(handlers.decide({ chatId: 'c', operationId: 'o', accept: 'yes' } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_accept' });
		await expect(handlers.setMappings({ chatId: 'c', mappings: {} } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_mappings' });
		await expect(handlers.setPrivacy({ chatId: 'c', projectId: 'p', enabled: 1, memories: [], sealed: null } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_enabled' });
		await expect(handlers.setPrivacy({ chatId: 'c', projectId: 'p', enabled: true, memories: [], sealed: 3 } as never, SIGNAL)).rejects.toMatchObject({ code: 'project_file_jobs_bad_sealed' });
		expect(borrow).not.toHaveBeenCalled();
		const decide = { chatId: 'c', operationId: 'o', accept: true };
		await expect(setup({}, 'none').handlers.decide(decide, SIGNAL)).rejects.toMatchObject({ code: 'not_admitted' });
		await expect(setup({}, 'busy').handlers.decide(decide, SIGNAL)).rejects.toMatchObject({ code: 'core_busy' });
		await expect(setup({}, 'local').handlers.decide(decide, SIGNAL)).rejects.toMatchObject({ code: 'local_session' });
	});
});
