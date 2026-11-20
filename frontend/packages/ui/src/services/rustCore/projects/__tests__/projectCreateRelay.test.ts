// contract-test-file: tooling
/** Creation relay: core report is sent as project_create_result, nothing for null, capability on/off, no send after uninstall. */
import { describe, expect, it, vi } from 'vitest';

import { installProjectCreateRelay, type ProjectCreateRelayDeps } from '../projectCreateRelay';

function setup(step: ProjectCreateRelayDeps['step']) {
	const handlers = new Map<string, (payload: unknown) => void>();
	const deps: ProjectCreateRelayDeps = {
		step: vi.fn(step),
		send: vi.fn(async () => undefined),
		on: vi.fn((type: string, handler: (payload: unknown) => void) => { handlers.set(type, handler); }),
		off: vi.fn((type: string) => { handlers.delete(type); }),
		setCapability: vi.fn()
	};
	return { deps, handlers, remove: installProjectCreateRelay(deps) };
}

const REQUEST = { chat_id: 'c1', request_id: 'r1', pending_client_action: {} };

describe('projectCreateRelay', () => {
	it('sends the core report for a creation request and advertises the capability', async () => {
		const result = { chat_id: 'c1', request_id: 'r1', status: 'created', project_id: 'p1', focus_id: 'f1' };
		const { deps, handlers } = setup(async () => result);
		expect(deps.setCapability).toHaveBeenCalledWith(true);
		expect([...handlers.keys()]).toEqual(['project_create_requested', 'project_create_confirmed', 'project_create_error']);
		handlers.get('project_create_requested')!(REQUEST);
		await vi.waitFor(() => expect(deps.send).toHaveBeenCalledWith('project_create_result', result));
		expect(deps.step).toHaveBeenCalledWith('project_create_requested', REQUEST);
	});

	it('sends nothing when the core returns no report', async () => {
		const { deps, handlers } = setup(async () => null);
		handlers.get('project_create_confirmed')!({ chat_id: 'c1', request_id: 'r1' });
		await vi.waitFor(() => expect(deps.step).toHaveBeenCalled());
		expect(deps.send).not.toHaveBeenCalled();
	});

	it('logs a stable code when the core refuses and keeps handling later frames', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
		let calls = 0;
		const { deps, handlers } = setup(async () => {
			calls += 1;
			if (calls === 1) throw Object.assign(new Error('secret'), { code: 'core_busy' });
			return { chat_id: 'c1', request_id: 'r2', status: 'failed', error_code: 'PROJECT_CREATE_FAILED' };
		});
		handlers.get('project_create_requested')!(REQUEST);
		handlers.get('project_create_requested')!({ ...REQUEST, request_id: 'r2' });
		await vi.waitFor(() => expect(deps.send).toHaveBeenCalledTimes(1));
		expect(warn).toHaveBeenCalledWith('[ProjectCreate] project_create_requested failed', 'core_busy');
		warn.mockRestore();
	});

	it('uninstall removes the handlers, disables the capability and sends nothing late', async () => {
		let release: () => void = () => undefined;
		const { deps, handlers, remove } = setup(() => new Promise((resolve) => {
			release = () => resolve({ chat_id: 'c1', request_id: 'r1', status: 'created' });
		}));
		handlers.get('project_create_requested')!(REQUEST);
		await vi.waitFor(() => expect(deps.step).toHaveBeenCalled());
		remove();
		release();
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(deps.send).not.toHaveBeenCalled();
		expect(deps.setCapability).toHaveBeenLastCalledWith(false);
		expect(handlers.size).toBe(0);
	});
});
