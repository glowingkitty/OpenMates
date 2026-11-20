// contract-test-file: tooling
/** Runner relay order: sealed blob before frames, prompt -> decide -> frames, UI events, inactive chat, privacy failure. */
import { describe, expect, it, vi } from 'vitest';

import { createProjectFileJobRunner, type ProjectFileJobRunnerDeps } from '../projectFileJobRunner';
import type { ProjectFileJobStep } from '../projectFileJobsProtocol';
import type { ProjectFileMutation } from '../../../../utils/projectFileMutationProtocol';

const EMPTY: ProjectFileJobStep = { frames: [], prompts: [], applied: [], notices: [] };
const EVENT = { chat_id: 'c1', project_id: 'p1', operation_id: 'op1' };
const frame = (name: 'project_file_operation_claim' | 'project_file_operation_result') => ({ name, payload: { operation_id: 'op1' } });

function setup(overrides: Partial<ProjectFileJobRunnerDeps> = {}) {
	const order: string[] = [];
	const store = new Map<string, string>();
	const deps: ProjectFileJobRunnerDeps = {
		send: vi.fn(async (name: string) => { order.push(`send:${name}`); }),
		isActiveChat: () => true,
		step: vi.fn(async () => EMPTY),
		decide: vi.fn(async () => EMPTY),
		setMappings: vi.fn(async () => undefined),
		setPrivacy: vi.fn(async () => undefined),
		chatMappings: vi.fn(async () => [{ placeholder: 'x' }]),
		privacyMemories: () => [],
		privacyEnabled: () => true,
		storage: {
			getItem: (key: string) => store.get(key) ?? null,
			setItem: (key: string, value: string) => { order.push('persist'); store.set(key, value); }
		},
		requestWrite: vi.fn(async () => true),
		requestRead: vi.fn(async () => true),
		onApplied: vi.fn(),
		onFilesChanged: vi.fn(),
		...overrides
	};
	return { deps, order, store, runner: createProjectFileJobRunner(deps) };
}

describe('projectFileJobRunner', () => {
	it('persists the sealed blob before sending frames and reinstalls privacy before every step', async () => {
		const { deps, order, store, runner } = setup({
			step: vi.fn(async () => ({ ...EMPTY, frames: [frame('project_file_operation_result')],
				privacy: { chat_id: 'c1', project_id: 'p1', ciphertext: 'sealed' } }))
		});
		await runner.request(EVENT);
		await runner.request(EVENT);
		expect(order.slice(0, 2)).toEqual(['persist', 'send:project_file_operation_result']);
		expect(store.get('openmates_project_file_privacy:["c1","p1"]')).toBe('sealed');
		// Reinstalled each step (the core may have dropped the chat or restarted),
		// with the blob the previous step persisted.
		expect(deps.setPrivacy).toHaveBeenCalledTimes(2);
		expect(deps.setPrivacy).toHaveBeenNthCalledWith(1, 'c1', 'p1', true, [], null);
		expect(deps.setPrivacy).toHaveBeenNthCalledWith(2, 'c1', 'p1', true, [], 'sealed');
		expect(deps.setMappings).toHaveBeenCalledTimes(2);
		expect(deps.step).toHaveBeenCalledWith('project_file_operation_request', EVENT, true);
	});

	it('answers a write prompt through decide and sends the resulting frames', async () => {
		const mutation: ProjectFileMutation = { operation: 'update_file', operation_id: 'op1', path: '/a.txt', expected_base: 'b', patch: 'x' };
		const { deps, runner } = setup({
			step: vi.fn(async () => ({ ...EMPTY, prompts: [{ kind: 'write' as const, operation_id: 'op1', chat_id: 'c1', project_id: 'p1', mutation }] })),
			decide: vi.fn(async () => ({ ...EMPTY, frames: [frame('project_file_operation_claim')],
				applied: [{ project_id: 'p1', chat_id: 'c1', operation: 'update_file', path: '/a.txt', mutation }] }))
		});
		await runner.request(EVENT);
		await vi.waitFor(() => expect(deps.send).toHaveBeenCalledWith('project_file_operation_claim', { operation_id: 'op1' }));
		expect(deps.requestWrite).toHaveBeenCalledWith({ projectId: 'p1', chatId: 'c1', mutation });
		expect(deps.decide).toHaveBeenCalledWith('c1', 'op1', true);
		expect(deps.onApplied).toHaveBeenCalledWith({ projectId: 'p1', chatId: 'c1', mutation });
		expect(deps.onFilesChanged).toHaveBeenCalledWith('p1');
	});

	it('maps a read prompt and passes a decline to the core', async () => {
		const { deps, runner } = setup({
			step: vi.fn(async () => ({ ...EMPTY, prompts: [{ kind: 'read' as const, operation_id: 'op1', chat_id: 'c1', project_id: 'p1', source_id: 's1', path: '.env' }] })),
			requestRead: vi.fn(async () => false)
		});
		await runner.request(EVENT);
		await vi.waitFor(() => expect(deps.decide).toHaveBeenCalledWith('c1', 'op1', false));
		expect(deps.requestRead).toHaveBeenCalledWith({ projectId: 'p1', sourceId: 's1', chatId: 'c1', operationId: 'op1', path: '.env' });
	});

	it('ignores events of an inactive chat and after stop', async () => {
		const inactive = setup({ isActiveChat: () => false });
		await inactive.runner.available(EVENT);
		expect(inactive.deps.step).not.toHaveBeenCalled();
		const stopped = setup();
		stopped.runner.stop();
		await stopped.runner.request(EVENT);
		expect(stopped.deps.step).not.toHaveBeenCalled();
	});

	it('still hands the job to the core when the privacy layer cannot be installed, so it is answered fail-closed', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
		const failed = { name: 'project_file_operation_result' as const,
			payload: { operation_id: 'op1', status: 'failed', result: { code: 'pii_mapping_unavailable' } } };
		const { deps, runner } = setup({
			setPrivacy: vi.fn(async () => { throw Object.assign(new Error('secret'), { code: 'pii_mapping_unavailable' }); }),
			step: vi.fn(async () => ({ ...EMPTY, frames: [failed] }))
		});
		await runner.request(EVENT);
		expect(deps.step).toHaveBeenCalledWith('project_file_operation_request', EVENT, true);
		expect(deps.send).toHaveBeenCalledWith('project_file_operation_result', failed.payload);
		expect(warn).toHaveBeenCalledWith('[ProjectFiles] Privacy layer unavailable', 'pii_mapping_unavailable');
		expect(JSON.stringify(warn.mock.calls)).not.toContain('secret');
		warn.mockRestore();
	});
});
