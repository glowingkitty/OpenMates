// contract-test-file: tooling
// Flow op on the auth Worker runtime. The signup / pair / recovery-print policy
// values in webAuthFlowVectors.json are pinned by
// packages/openmates-rust/src/web_auth_flow_tests.rs against the Rust core.
import { describe, expect, it, vi } from 'vitest';
import { installAuthWorker, type RustWebAuthBinding } from '../authWorkerRuntime';
import { runFlowOp } from '../flowOps';

describe('flow op on the auth Worker runtime', () => {
	it('forwards name and args to web_auth_flow, refuses a binding without the export', () => {
		const web_auth_flow = vi.fn((name: string, args: string) => JSON.stringify({ name, args }));
		expect(runFlowOp({ web_auth_flow }, 'tfa_apps', '{}')).toEqual({ name: 'tfa_apps', args: '{}' });
		expect(() => runFlowOp({}, 'tfa_apps', '{}')).toThrow();
	});

	it('serves op "flow" over the protocol and maps Rust refusals to their fixed code', async () => {
		const posted: Record<string, unknown>[] = [];
		const listeners: ((event: MessageEvent<unknown>) => void)[] = [];
		const binding = { web_auth_flow: (name: string) => { if (name === 'nope') throw 'flow_op'; return '"ok"'; } } as unknown as RustWebAuthBinding;
		installAuthWorker({ postMessage: (m) => posted.push(m as Record<string, unknown>), addEventListener: (_t, l) => listeners.push(l), close: () => undefined }, binding);
		for (const [id, name] of [[1, 'tfa_apps'], [2, 'nope']] as const) {
			listeners[0]({ data: { v: 1, id, op: 'flow', name, args: '{}' } } as MessageEvent<unknown>);
		}
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(posted).toContainEqual({ v: 1, id: 1, ok: true, value: 'ok' });
		expect(posted).toContainEqual({ v: 1, id: 2, ok: false, code: 'flow_op' });
	});
});
