import { expect, test } from '@playwright/test';

// The shared helper uses CommonJS so deployed Playwright specs can require it.
// Exercise the same exported functions here without starting a browser.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { waitForRejectedLoginResponse, waitForLoginSuccessAfterSubmit, isChatTransportReady } = require('./chat-test-helpers');

function loginResponse(version: number, status: number, body: unknown) {
	return {
		url: () => 'https://example.test/v1/auth/login',
		request: () => ({ method: () => 'POST', postDataJSON: () => ({ credential_version: version }) }),
		status: () => status,
		ok: () => status >= 200 && status < 300,
		json: async () => body
	};
}

function responsePage(responses: ReturnType<typeof loginResponse>[]) {
	const accepted: number[] = [];
	let markReady!: () => void;
	const ready = new Promise<void>((resolve) => { markReady = resolve; });
	const page = {
		waitForResponse: async (predicate: (response: ReturnType<typeof loginResponse>) => Promise<boolean>) => {
			for (const response of responses) {
				if (await predicate(response)) {
					accepted.push(responses.indexOf(response));
					markReady();
					return response;
				}
			}
			throw new Error('No response matched');
		},
		getByTestId: () => ({ waitFor: () => ready })
	};
	return { page, accepted, authSignal: { waitFor: () => ready } };
}

// contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection,auth.login.method-convergence
test('provisional v2 rejection waits for the final legacy v1 rejection', async () => {
	const { page, accepted } = responsePage([
		loginResponse(2, 200, { success: false, tfa_required: true }),
		loginResponse(1, 401, { success: false, tfa_required: true })
	]);
	const rejected = await waitForRejectedLoginResponse(page);
	expect(accepted).toEqual([1]);
	expect(rejected?.diagnostic.status).toBe(401);
});

// contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection,auth.login.method-convergence
test('provisional v2 challenge waits for successful legacy v1 login', async () => {
	const { page, accepted, authSignal } = responsePage([
		loginResponse(2, 200, { success: true, tfa_required: true, user: { id: null } }),
		loginResponse(1, 200, { success: true, tfa_required: false, user: { id: 'actor' } })
	]);
	expect(await waitForLoginSuccessAfterSubmit(page, authSignal)).toBe(true);
	expect(accepted).toEqual([1]);
});

// contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection,auth.login.method-convergence
test('successful v2 login stays final without awaiting a legacy response', async () => {
	const { page, accepted, authSignal } = responsePage([
		loginResponse(2, 200, { success: true, tfa_required: false, user: { id: 'actor' } })
	]);
	expect(await waitForLoginSuccessAfterSubmit(page, authSignal)).toBe(true);
	expect(accepted).toEqual([0]);
});

// contract-test: supporting surface=gui.web assertions=auth.password.versioned-protection,auth.login.method-convergence
test('rate-limited v2 response stays authoritative', async () => {
	const { page, accepted } = responsePage([loginResponse(2, 429, { success: false })]);
	const rejected = await waitForRejectedLoginResponse(page);
	expect(accepted).toEqual([0]);
	expect(rejected?.diagnostic.status).toBe(429);
});

// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
test('Personal readiness requires a primed cache even after phased sync completes', () => {
	const state = { hookAvailable: true, online: true, websocketConnected: true,
		teamContextActive: false, contextSyncCompleted: true, cachePrimed: false };
	expect(isChatTransportReady(state)).toBe(false);
	expect(isChatTransportReady({ ...state, cachePrimed: true })).toBe(true);
});

// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local,teams.collaboration.realtime-team-sync
test('Team readiness requires current-context phased sync completion, not Personal cache priming', () => {
	const state = { hookAvailable: true, online: true, websocketConnected: true,
		teamContextActive: true, contextSyncCompleted: false, cachePrimed: true };
	expect(isChatTransportReady(state)).toBe(false);
	expect(isChatTransportReady({ ...state, cachePrimed: false })).toBe(false);
	expect(isChatTransportReady({ ...state, contextSyncCompleted: true, cachePrimed: false })).toBe(true);
});

// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
test('both contexts require the hook, online status and a connected WebSocket', () => {
	for (const state of [
		{ teamContextActive: false, cachePrimed: true, contextSyncCompleted: false },
		{ teamContextActive: true, cachePrimed: false, contextSyncCompleted: true }
	]) {
		const ready = { hookAvailable: true, online: true, websocketConnected: true, ...state };
		expect(isChatTransportReady({ ...ready, hookAvailable: false })).toBe(false);
		expect(isChatTransportReady({ ...ready, online: false })).toBe(false);
		expect(isChatTransportReady({ ...ready, websocketConnected: false })).toBe(false);
		expect(isChatTransportReady(ready)).toBe(true);
	}
});
