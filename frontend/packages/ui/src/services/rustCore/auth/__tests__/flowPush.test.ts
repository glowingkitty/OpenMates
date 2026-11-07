// contract-test-file: tooling
// Flag-on push adapters (flowPush.ts): the Worker answer is replayed from the
// shared vectors (the Rust side is pinned to the same file by
// web_auth_flow_tests.rs), and the page-side stores/caches must return the
// neutral default first and the pushed value afterwards.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import vectors from './webAuthFlowVectors.json';

interface Vector { op: string; args: Record<string, unknown>; expect: unknown }
const all = vectors.vectors as Vector[];
const byOp = (op: string) => all.filter((vector) => vector.op === op);

const TFA_REPLY = [{ name: 'Alpha App', icon: 'alpha' }, { name: 'Beta App', icon: 'beta' }];

/** Replays the vector whose op and args match, as the Worker would answer. */
const rustAuthFlow = vi.fn(async (name: string, args: Record<string, unknown>) => {
	const hit = all.find((v) => v.op === name && Object.entries(v.args).every(([k, val]) => JSON.stringify(args[k]) === JSON.stringify(val)));
	if (hit) return hit.expect;
	// Ops or argument sets without a vector get a fixed Worker answer (the Rust list/verdicts are pinned in Rust tests).
	if (name === 'tfa_apps') return TFA_REPLY;
	if (name === 'signup_step_from_path') return 'basics';
	if (name === 'signup_is_signup_path') return String(args.path).startsWith('#signup/') || String(args.path).startsWith('/signup/');
	throw new Error(`no vector for ${name} ${JSON.stringify(args)}`);
});
vi.mock('../../authOperation', () => ({ rustAuthFlow: (name: string, args: Record<string, unknown>) => rustAuthFlow(name, args) }));

// The adapter loads authOperation lazily, so pushes arrive after a few macrotasks.
const flush = async () => { for (let i = 0; i < 5; i++) await new Promise((resolve) => setTimeout(resolve, 0)); };

beforeEach(() => { vi.stubEnv('VITE_OPENMATES_RUST_CORE', '1'); vi.resetModules(); rustAuthFlow.mockClear(); });
afterEach(() => { vi.unstubAllEnvs(); sessionStorage.clear(); });

describe('signup push cache', () => {
	it('returns the neutral default first, then the pushed Rust answer', async () => {
		const { getStepFromPath, isSignupPath } = await import('../../../../stores/signupState');
		for (const v of byOp('signup_step_from_path').filter((x) => x.expect !== 'basics')) {
			const path = v.args.path as string;
			expect(getStepFromPath(path)).toBe('basics');
			await flush();
			expect(getStepFromPath(path), JSON.stringify(v)).toBe(v.expect);
		}
		for (const v of byOp('signup_is_signup_path').filter((x) => x.expect === true)) {
			const path = v.args.path as string;
			expect(isSignupPath(path)).toBe(false);
			await flush();
			expect(isSignupPath(path), JSON.stringify(v)).toBe(true);
		}
	});

	it('primeSignupLocation makes the next synchronous read exact', async () => {
		const { getStepFromPath, primeSignupLocation } = await import('../../../../stores/signupState');
		const v = byOp('signup_step_from_path').find((x) => x.expect !== 'basics') as Vector;
		await primeSignupLocation(v.args.path as string);
		expect(getStepFromPath(v.args.path as string)).toBe(v.expect);
	});
});

describe('pair push', () => {
	it('pairSessionState starts unrestricted and receives the Rust view', async () => {
		const v = byOp('pair_view').find((x) => (x.expect as { isPairSession: boolean }).isPairSession) as Vector;
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(v.args.nowMs as number);
		sessionStorage.setItem('openmates_pair_session', JSON.stringify(v.args.data));
		const store = await import('../../../../stores/pairSessionStore');
		const seen: unknown[] = [];
		const stop = store.pairSessionState.subscribe((value) => seen.push(value));
		expect(seen[0]).toMatchObject({ isPairSession: false });
		await flush();
		expect(get(store.pairSessionState)).toEqual(v.expect);
		stop();
		vi.useRealTimers();
	});

	it('pairExpired answers not-expired first, then the pushed verdict', async () => {
		const v = byOp('pair_expired').find((x) => x.expect === true && x.args.expiresAt !== null) as Vector;
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(v.args.nowMs as number);
		const { pairExpired } = await import('../../../pairV2');
		expect(pairExpired(v.args.expiresAt as number)).toBe(false);
		await flush();
		expect(pairExpired(v.args.expiresAt as number)).toBe(true);
		vi.useRealTimers();
	});

	it('activatePairSession stores the record Rust built', async () => {
		const v = byOp('pair_activate')[0];
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(v.args.nowMs as number);
		const store = await import('../../../../stores/pairSessionStore');
		await store.activatePairSession(v.args.input as never);
		expect(JSON.parse(sessionStorage.getItem('openmates_pair_session') ?? 'null')).toEqual(v.expect);
		vi.useRealTimers();
	});
});

describe('2FA apps push', () => {
	it('fills the shared lists in place from Rust and none are left from TypeScript', async () => {
		const { tfaApps, tfaAppIcons } = await import('../../../../config/tfa');
		expect(tfaApps).toEqual([]);
		await flush();
		const list = TFA_REPLY;
		expect(tfaApps).toEqual(list.map((app) => app.name));
		expect(tfaAppIcons).toEqual(Object.fromEntries(list.map((app) => [app.name, app.icon])));
	});
});

describe('flag-off bundle surface', () => {
	it('selects the TypeScript path when localStorage pins "ts"', async () => {
		localStorage.setItem('openmates_rust_auth', 'ts');
		const { isSignupPath } = await import('../../../../stores/signupState');
		expect(isSignupPath('#signup/basics')).toBe(true);
		expect(rustAuthFlow).not.toHaveBeenCalled();
		localStorage.removeItem('openmates_rust_auth');
	});
});
