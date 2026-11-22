// contract-test-file: tooling
/** Sandbox key relay: the core's frame is sent as-is, refusals send nothing, uninstall stops late sends; the unit parser is strict. */
import { describe, expect, it, vi } from 'vitest';

import { installProjectSandboxKeyRelay, type ProjectSandboxKeyRelayDeps } from '../projectSandboxKeyRelay';
import { parseProjectSandboxKeyFrame } from '../projectFileJobsUnit';

const REQUEST = { request_id: 'r1', job_id: 'j1', sandbox_id: 's1', project_id: 'p1', chat_id: 'c1', sandbox_public_key: 'AAAA', expires_at: 1 };
const GRANT = { event: 'project_sandbox_key_grant' as const, payload: { request_id: 'r1', job_id: 'j1', sealed_grant: 'c2VhbGVk' } };

function setup(answer: ProjectSandboxKeyRelayDeps['answer']) {
	const handlers = new Map<string, (payload: unknown) => void>();
	const deps: ProjectSandboxKeyRelayDeps = {
		answer: vi.fn(answer),
		send: vi.fn(async () => undefined),
		on: vi.fn((type: string, handler: (payload: unknown) => void) => { handlers.set(type, handler); }),
		off: vi.fn((type: string) => { handlers.delete(type); }),
	};
	return { deps, handlers, remove: installProjectSandboxKeyRelay(deps) };
}

describe('projectSandboxKeyRelay', () => {
	it('sends the core frame unchanged on the request event', async () => {
		const { deps, handlers } = setup(async () => GRANT);
		expect([...handlers.keys()]).toEqual(['project_sandbox_key_request']);
		handlers.get('project_sandbox_key_request')!(REQUEST);
		await vi.waitFor(() => expect(deps.send).toHaveBeenCalledWith('project_sandbox_key_grant', GRANT.payload));
		expect(deps.answer).toHaveBeenCalledWith(REQUEST);
	});

	it('sends nothing and logs only a stable code when the core refuses', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
		const { deps, handlers } = setup(async () => { throw Object.assign(new Error('secret'), { code: 'offline' }); });
		handlers.get('project_sandbox_key_request')!(REQUEST);
		await vi.waitFor(() => expect(warn).toHaveBeenCalledWith('[ProjectSandboxKey] request failed', 'offline'));
		expect(deps.send).not.toHaveBeenCalled();
		warn.mockRestore();
	});

	it('ignores non-object payloads and sends nothing after uninstall', async () => {
		let release: () => void = () => undefined;
		const { deps, handlers, remove } = setup(() => new Promise((resolve) => { release = () => resolve(GRANT); }));
		handlers.get('project_sandbox_key_request')!('nope');
		expect(deps.answer).not.toHaveBeenCalled();
		handlers.get('project_sandbox_key_request')!(REQUEST);
		await vi.waitFor(() => expect(deps.answer).toHaveBeenCalled());
		remove();
		release();
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(deps.send).not.toHaveBeenCalled();
		expect(handlers.size).toBe(0);
	});
});

describe('parseProjectSandboxKeyFrame', () => {
	const ok = (frame: unknown) => parseProjectSandboxKeyFrame(JSON.stringify(frame));
	it('accepts a grant and each decline reason', () => {
		expect(ok(GRANT)).toEqual(GRANT);
		for (const reason of ['no_key', 'expired', 'invalid']) {
			expect(ok({ event: 'project_sandbox_key_decline', payload: { request_id: 'r1', job_id: 'j1', reason } }).payload.reason).toBe(reason);
		}
	});
	it('refuses off-contract frames, extra fields and non-JSON', () => {
		const bad = [
			{ event: 'chat_message_added', payload: GRANT.payload },
			{ event: GRANT.event, payload: { ...GRANT.payload, project_key: 'x' } },
			{ event: GRANT.event, payload: { request_id: 'r1', job_id: 'j1' } },
			{ event: 'project_sandbox_key_decline', payload: { request_id: 'r1', job_id: 'j1', reason: 'other' } },
			{ event: 'project_sandbox_key_decline', payload: { request_id: 'r1', reason: 'no_key' } },
		];
		for (const frame of bad) expect(() => ok(frame)).toThrow(/project_file_jobs_protocol/);
		expect(() => parseProjectSandboxKeyFrame('x')).toThrow(/project_file_jobs_protocol/);
		expect(() => parseProjectSandboxKeyFrame(7)).toThrow(/project_file_jobs_protocol/);
	});
});
