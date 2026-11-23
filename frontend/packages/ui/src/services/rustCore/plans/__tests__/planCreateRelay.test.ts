// contract-test-file: tooling
/** Plan create relay: ordered creates, result frames, project requirement, conflict, repeat, uninstall. */
import { describe, expect, it, vi } from 'vitest';

import { installPlanCreateRelay, type PlanCreateDecision, type PlanCreateRelayDeps } from '../planCreateRelay';

const OK: PlanCreateDecision = {
	ok: true, request_id: 'r1', chat_id: 'c1', project_ids: [],
	plan: { planId: 'p1', title: 'Kitchen renovation plan', goal: 'Renovate' },
	assumptions: [{ assumptionId: 'a1', text: 'Budget fixed' }, { assumptionId: 'a2', text: 'Permit ready' }],
	created: { request_id: 'r1', status: 'created', plan_id: 'p1' },
	failed: { request_id: 'r1', status: 'failed', plan_id: 'p1', error_code: 'PLAN_CREATE_FAILED' },
	conflict: { request_id: 'r1', status: 'failed', plan_id: 'p1', error_code: 'PLAN_ID_CONFLICT' }
};

function setup(overrides: Partial<PlanCreateRelayDeps> = {}) {
	const handlers = new Map<string, (payload: unknown) => void>();
	const deps: PlanCreateRelayDeps = {
		decide: vi.fn(async () => OK),
		projectIdsForChat: vi.fn(async () => ['proj1']),
		createPlan: vi.fn(async () => ({ plan_id: 'p1' }) as never),
		createAssumption: vi.fn(async () => undefined),
		send: vi.fn(async () => undefined),
		on: vi.fn((type: string, handler: (payload: unknown) => void) => { handlers.set(type, handler); }),
		off: vi.fn((type: string) => { handlers.delete(type); }),
		setCapability: vi.fn(),
		...overrides
	};
	return { deps, handlers, remove: installPlanCreateRelay(deps) };
}

const EVENT = { request_id: 'r1', chat_id: 'c1', pending_client_action: {} };

describe('planCreateRelay', () => {
	it('creates the Plan then each assumption in order and sends created', async () => {
		const { deps, handlers } = setup();
		expect(deps.setCapability).toHaveBeenCalledWith(true);
		handlers.get('plan_create_requested')!(EVENT);
		await vi.waitFor(() => expect(deps.send).toHaveBeenCalledWith('plan_create_result', OK.ok && OK.created));
		expect(deps.createPlan).toHaveBeenCalledWith({ planId: 'p1', title: 'Kitchen renovation plan', goal: 'Renovate', linkedProjectIds: ['proj1'] });
		expect(vi.mocked(deps.createAssumption).mock.calls.map((call) => (call[1] as { assumptionId: string }).assumptionId)).toEqual(['a1', 'a2']);
	});

	it('sends the core refusal without creating anything', async () => {
		const failed = { request_id: 'r1', status: 'failed' as const, error_code: 'PLAN_CREATE_REQUEST_EXPIRED' };
		const { deps, handlers } = setup({ decide: vi.fn(async () => ({ ok: false, result: failed }) as PlanCreateDecision) });
		handlers.get('plan_create_requested')!(EVENT);
		await vi.waitFor(() => expect(deps.send).toHaveBeenCalledWith('plan_create_result', failed));
		expect(deps.createPlan).not.toHaveBeenCalled();
	});

	it('links the Plan to the Project the server named, without the sidebar index', async () => {
		const { deps, handlers } = setup({ decide: vi.fn(async () => ({ ...OK, project_ids: ['server-proj'] }) as PlanCreateDecision) });
		handlers.get('plan_create_requested')!(EVENT);
		await vi.waitFor(() => expect(deps.send).toHaveBeenCalledWith('plan_create_result', OK.ok && OK.created));
		expect(deps.createPlan).toHaveBeenCalledWith(expect.objectContaining({ linkedProjectIds: ['server-proj'] }));
		expect(deps.projectIdsForChat).not.toHaveBeenCalled();
	});

	it('fails with PLAN_PROJECT_REQUIRED when the chat has no Project', async () => {
		const { deps, handlers } = setup({ projectIdsForChat: vi.fn(async () => []) });
		handlers.get('plan_create_requested')!(EVENT);
		await vi.waitFor(() => expect(deps.send).toHaveBeenCalledWith('plan_create_result',
			{ request_id: 'r1', status: 'failed', plan_id: 'p1', error_code: 'PLAN_PROJECT_REQUIRED' }));
		expect(deps.createPlan).not.toHaveBeenCalled();
	});

	it('maps a 409 to PLAN_ID_CONFLICT and other errors to PLAN_CREATE_FAILED without logging text', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
		const createPlan = vi.fn()
			.mockRejectedValueOnce(new Error('Plans API failed (409): secret plaintext'))
			.mockRejectedValueOnce(new Error('boom secret'));
		const { deps, handlers } = setup({
			createPlan,
			decide: vi.fn(async (event) => ({ ...OK, request_id: String(event.request_id) }) as PlanCreateDecision)
		});
		handlers.get('plan_create_requested')!({ ...EVENT, request_id: 'r1' });
		handlers.get('plan_create_requested')!({ ...EVENT, request_id: 'r2' });
		await vi.waitFor(() => expect(deps.send).toHaveBeenCalledTimes(2));
		expect(vi.mocked(deps.send).mock.calls.map((call) => (call[1] as { error_code: string }).error_code))
			.toEqual(['PLAN_ID_CONFLICT', 'PLAN_CREATE_FAILED']);
		expect(JSON.stringify(warn.mock.calls)).not.toContain('secret');
		warn.mockRestore();
	});

	it('a repeated request id re-sends the stored report and creates nothing twice', async () => {
		const { deps, handlers } = setup();
		handlers.get('plan_create_requested')!(EVENT);
		handlers.get('plan_create_requested')!(EVENT);
		await vi.waitFor(() => expect(deps.send).toHaveBeenCalledTimes(2));
		expect(deps.createPlan).toHaveBeenCalledTimes(1);
	});

	it('uninstall removes the handler and disables the capability', () => {
		const { deps, handlers, remove } = setup();
		remove();
		expect(handlers.size).toBe(0);
		expect(deps.setCapability).toHaveBeenLastCalledWith(false);
	});
});
