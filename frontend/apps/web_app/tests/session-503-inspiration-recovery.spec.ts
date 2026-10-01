/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

// contract-test: direct surface=gui.web assertions=auth.session.lifecycle,daily-inspiration.authenticated-continuity
test('keeps inspirations through repeated session 503 and WebSocket retries, then resyncs', async ({ page }: { page: any }) => {
	test.setTimeout(120000);
	const account = getTestAccount();
	test.skip(!account.email || !account.password || !account.otpKey, 'An authenticated test account is required.');
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await loginToTestAccount(page, () => {}, async () => {});

	let sessionUnavailable = true;
	let dropConnections = true;
	let failedSessionChecks = 0;
	let defaultRequests = 0;
	let phasedSyncRequests = 0;
	await page.route('**/v1/auth/session', (route: any) => {
		if (!sessionUnavailable) return route.continue();
		failedSessionChecks += 1;
		return route.fulfill({ status: 503, json: { detail: 'Session security state unavailable' } });
	});
	await page.route('**/v1/default-inspirations?*', async (route: any) => {
		defaultRequests += 1;
		const response = await route.fetch();
		const data = await response.json();
		return route.fulfill({ response, json: { ...data, inspirations: data.inspirations.slice(0, 1) } });
	});
	await page.routeWebSocket(/\/v1\/ws(?:\?|$)/, (socket: any) => {
		if (dropConnections) socket.close();
		else socket.connectToServer();
	});
	page.on('websocket', (socket: any) => socket.on('framesent', (frame: any) => {
		try {
			if (JSON.parse(String(frame.payload)).type === 'phased_sync_request') phasedSyncRequests += 1;
		} catch {
			// Ignore non-protocol frames.
		}
	}));

	await page.reload({ waitUntil: 'domcontentloaded' });
	await expect.poll(() => failedSessionChecks, { timeout: 30000 }).toBeGreaterThanOrEqual(3);
	await expect(page.getByTestId('daily-inspiration-phrase').first()).toBeVisible();
	// The initial authenticated restore may fetch once; repeated offline checks
	// must not replace that set or restart the carousel.
	expect(defaultRequests).toBeLessThanOrEqual(2);

	sessionUnavailable = false;
	dropConnections = false;
	await expect.poll(() => phasedSyncRequests, { timeout: 60000 }).toBeGreaterThan(0);
});
