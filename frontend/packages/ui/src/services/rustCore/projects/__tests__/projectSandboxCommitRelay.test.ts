// contract-test-file: tooling
/** Sandbox commit relay: only sandbox commits reach the core, its card is recorded, refusals log a code only; the unit parser is strict. */
import { describe, expect, it, vi } from 'vitest';

import { installProjectSandboxCommitRelay, type ProjectSandboxCommitRelayDeps } from '../projectSandboxCommitRelay';
import { parseProjectSandboxChange } from '../projectFileJobsUnit';

const EVENT = { embed_id: 'e1', current_revision: 2, operation_id: 'op-1', chat_id: 'c1', project_id: 'p1', kind: 'create', source: 'project_sandbox' };
const CARD = {
	projectId: 'p1', chatId: 'c1',
	mutation: { operation: 'create_file' as const, operation_id: 'op-1:e1', path: 'web-app/package.json', expected_base: null, content: '{}' },
};

function setup(describeCommit: ProjectSandboxCommitRelayDeps['describe']) {
	const handlers = new Map<string, (payload: unknown) => void>();
	const deps: ProjectSandboxCommitRelayDeps = {
		describe: vi.fn(describeCommit),
		record: vi.fn(),
		on: vi.fn((type: string, handler: (payload: unknown) => void) => { handlers.set(type, handler); }),
		off: vi.fn((type: string) => { handlers.delete(type); }),
	};
	return { deps, handlers, remove: installProjectSandboxCommitRelay(deps) };
}

describe('projectSandboxCommitRelay', () => {
	it('records the core card of a sandbox commit', async () => {
		const { deps, handlers } = setup(async () => CARD);
		expect([...handlers.keys()]).toEqual(['embed_revision_committed']);
		handlers.get('embed_revision_committed')!(EVENT);
		await vi.waitFor(() => expect(deps.record).toHaveBeenCalledWith(CARD));
		expect(deps.describe).toHaveBeenCalledWith(EVENT);
	});

	it('leaves device commits and non-objects alone and records nothing for a null card', async () => {
		const { deps, handlers } = setup(async () => null);
		handlers.get('embed_revision_committed')!({ ...EVENT, source: 'device' });
		handlers.get('embed_revision_committed')!('x');
		expect(deps.describe).not.toHaveBeenCalled();
		handlers.get('embed_revision_committed')!(EVENT);
		await vi.waitFor(() => expect(deps.describe).toHaveBeenCalledTimes(1));
		expect(deps.record).not.toHaveBeenCalled();
	});

	it('logs only a stable code when the core refuses, and records nothing after uninstall', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
		const { deps, handlers } = setup(async () => { throw Object.assign(new Error('secret text'), { code: 'file_key_unavailable' }); });
		handlers.get('embed_revision_committed')!(EVENT);
		await vi.waitFor(() => expect(warn).toHaveBeenCalledWith('[ProjectSandboxCommit] card failed', 'file_key_unavailable'));
		expect(deps.record).not.toHaveBeenCalled();
		warn.mockRestore();
		let release: (value: typeof CARD) => void = () => undefined;
		const late = setup(() => new Promise((resolve) => { release = resolve; }));
		late.handlers.get('embed_revision_committed')!(EVENT);
		await vi.waitFor(() => expect(late.deps.describe).toHaveBeenCalled());
		late.remove();
		release(CARD);
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(late.deps.record).not.toHaveBeenCalled();
		expect(late.handlers.size).toBe(0);
	});
});

describe('parseProjectSandboxChange', () => {
	it('accepts null and a create/update card only', () => {
		expect(parseProjectSandboxChange('null')).toBeNull();
		expect(parseProjectSandboxChange(JSON.stringify(CARD))).toEqual(CARD);
		const bad = [
			{ ...CARD, mutation: { ...CARD.mutation, operation: 'delete_file' } },
			{ ...CARD, mutation: { ...CARD.mutation, expected_base: 'a' } },
			{ ...CARD, mutation: { ...CARD.mutation, extra: 1 } },
			{ chatId: 'c1', mutation: CARD.mutation },
		];
		for (const value of bad) expect(() => parseProjectSandboxChange(JSON.stringify(value))).toThrow();
		expect(() => parseProjectSandboxChange('{')).toThrow();
		expect(() => parseProjectSandboxChange(1)).toThrow();
	});
});
