// contract-test-file: tooling
// Parity of the shared Rust signup / pair / recovery-print policy with the
// deployed TypeScript. webAuthFlowVectors.json is consumed by this file (against
// the TS originals) and by packages/openmates-rust/src/web_auth_flow_tests.rs
// (against Rust), so both implementations are pinned to the same values.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import vectors from './webAuthFlowVectors.json';
import { installAuthWorker, type RustWebAuthBinding } from '../authWorkerRuntime';
import { runFlowOp } from '../flowOps';

vi.mock('../../../../i18n/translations', async () => {
	const { readable } = await import('svelte/store');
	return { text: readable((key: string) => key) };
});

interface Vector { op: string; args: Record<string, unknown>; expect: unknown }
const all = vectors.vectors as Vector[];
const byOp = (op: string) => all.filter((vector) => vector.op === op);

describe('signup policy (stores/signupState.ts)', () => {
	it('step_from_path / path_from_step / is_signup_path / is_settings_step / sequence match the vectors', async () => {
		const state = await import('../../../../stores/signupState');
		for (const v of byOp('signup_step_from_path')) expect(state.getStepFromPath(v.args.path as string), JSON.stringify(v)).toBe(v.expect);
		for (const v of byOp('signup_path_from_step')) expect(state.getPathFromStep(v.args.step as string), JSON.stringify(v)).toBe(v.expect);
		for (const v of byOp('signup_is_signup_path')) expect(state.isSignupPath(v.args.path as string | null), JSON.stringify(v)).toBe(v.expect);
		for (const v of byOp('signup_is_settings_step')) expect(state.isSettingsStep(v.args.step as string), JSON.stringify(v)).toBe(v.expect);
		expect(state.STEP_SEQUENCE).toEqual(byOp('signup_step_sequence')[0].expect);
	});
});

describe('pair policy (services/pairV2.ts, stores/pairSessionStore.ts)', () => {
	beforeEach(() => { vi.useFakeTimers(); });
	afterEach(() => { vi.useRealTimers(); sessionStorage.clear(); vi.resetModules(); });

	it('is_terminal and expired match the vectors', async () => {
		const pair = await import('../../../pairV2');
		for (const v of byOp('pair_is_terminal')) expect(pair.isPairTerminal(v.args.status as never), JSON.stringify(v)).toBe(v.expect);
		for (const v of byOp('pair_expired')) {
			vi.setSystemTime(v.args.nowMs as number);
			expect(pair.pairExpired((v.args.expiresAt as number | null) ?? Number.NaN), JSON.stringify(v)).toBe(v.expect);
		}
	});

	it('error_message matches the vectors', async () => {
		const pair = await import('../../../pairV2');
		for (const v of byOp('pair_error_message')) {
			vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(v.args.body), { status: v.args.status as number })));
			await expect(pair.pairRequest('/x'), JSON.stringify(v)).rejects.toThrow(v.expect as string);
		}
		vi.unstubAllGlobals();
	});

	it('view derives the same state from a stored record', async () => {
		for (const v of byOp('pair_view')) {
			vi.resetModules();
			sessionStorage.clear();
			vi.setSystemTime(v.args.nowMs as number);
			if (v.args.data) sessionStorage.setItem('openmates_pair_session', JSON.stringify(v.args.data));
			const store = await import('../../../../stores/pairSessionStore');
			expect(get(store.pairSessionState), JSON.stringify(v)).toEqual(v.expect);
		}
	});

	it('activate stores the same record', async () => {
		for (const v of byOp('pair_activate')) {
			vi.resetModules();
			sessionStorage.clear();
			vi.setSystemTime(v.args.nowMs as number);
			const store = await import('../../../../stores/pairSessionStore');
			store.activatePairSession(v.args.input as never);
			expect(JSON.parse(sessionStorage.getItem('openmates_pair_session') ?? 'null'), JSON.stringify(v)).toEqual(v.expect);
		}
	});
});

describe('recovery print page (utils/recoveryKeyUtils.ts)', () => {
	it('generatePrintPageHtml equals the vector', async () => {
		const { generatePrintPageHtml } = await import('../../../../utils/recoveryKeyUtils');
		const v = byOp('recovery_print_html')[0];
		expect(generatePrintPageHtml(v.args.recoveryKey as string, v.args.translations as never)).toBe(v.expect);
	});
});

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
