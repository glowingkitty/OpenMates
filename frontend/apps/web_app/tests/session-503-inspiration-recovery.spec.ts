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

// contract-test: direct surface=gui.web assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
test('rechecks a rejected activity session and stops requests after expiry', async ({ page, browser }: { page: any; browser: any }) => {
	test.setTimeout(120_000);
	await loginToTestAccount(page);
	await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 30_000 });
	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';
	const invalidOwner = '/v1/users/ui-test-missing-owner/profile-image';
	// Malformed owners must not turn a Directus rejection into a server error.
	expect((await page.request.get(`${apiUrl}${invalidOwner}`)).status()).toBe(404);
	const guest = await browser.newContext();
	try {
		expect((await guest.request.get(`${apiUrl}${invalidOwner}`)).status()).toBe(401);
	} finally { await guest.close(); }
	let activityRequests = 0;
	let sessionChecks = 0;
	await page.route('**/v1/chats/activity*', (route: any) => {
		activityRequests += 1;
		return route.fulfill({ status: 401, json: { detail: 'Session expired or revoked' } });
	});
	await page.route('**/v1/auth/session', (route: any) => {
		sessionChecks += 1;
		return route.fulfill({ status: 401, json: { detail: 'Session expired or revoked' } });
	});
	await page.evaluate(() => window.dispatchEvent(new Event('online')));
	await expect.poll(() => sessionChecks, { timeout: 30_000 }).toBe(1);
	await expect(page.locator('[data-authenticated="false"]')).toBeVisible({ timeout: 30_000 });
	const requestsAfterExpiry = activityRequests;
	await page.evaluate(() => {
		for (let index = 0; index < 5; index += 1) {
			window.dispatchEvent(new Event('focus'));
			window.dispatchEvent(new Event('online'));
		}
	});
	await page.waitForTimeout(2_000);
	expect(activityRequests).toBe(requestsAfterExpiry);
	await expect(page.getByTestId('header-login-signup-btn')).toBeVisible();
});

// contract-test: direct surface=gui.web assertions=auth.session.lifecycle
test('stops rejected diagnostic uploads and logs out on a session-check 401', async ({ page }: { page: any }) => {
	test.setTimeout(120_000);
	const account = getTestAccount();
	test.skip(!account.email || !account.password || !account.otpKey, 'An authenticated test account is required.');
	await loginToTestAccount(page);
	// Exercise the ordinary cookie-authenticated diagnostic uploader. E2E capture
	// intentionally takes precedence over it and survives auth transitions.
	await page.evaluate(() => sessionStorage.removeItem('openmates_e2e_log_forwarding'));
	let uploads = 0;
	await page.route('**/v1/client-logs', (route: any) => {
		uploads += 1;
		return route.fulfill({ status: 401, json: { detail: 'Session expired or revoked' } });
	});
	const restoredSession = page.waitForResponse((response: any) =>
		response.url().endsWith('/v1/auth/session') && response.status() === 200,
	);
	await page.goto('/', { waitUntil: 'domcontentloaded' });
	await restoredSession;
	await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 30_000 });
	await expect(page.getByTestId('header-login-signup-btn')).not.toBeVisible();
	await page.evaluate(() => console.warn('Diagnostic expiry regression: first batch'));
	await expect.poll(() => uploads, { timeout: 20_000 }).toBe(1);
	await page.evaluate(() => console.warn('Diagnostic expiry regression: rejected session stays stopped'));
	// Observe more than one real flush interval; an auth rejection must stop the
	// timer, not merely drop the first batch and keep generating 401 requests.
	await page.waitForTimeout(12_000);
	expect(uploads).toBe(1);

	let rejectedSessionChecks = 0;
	await page.route('**/v1/auth/session', (route: any) => {
		rejectedSessionChecks += 1;
		return route.fulfill({ status: 401, json: { detail: 'Session expired or revoked' } });
	});
	await page.reload({ waitUntil: 'domcontentloaded' });
	await expect.poll(() => rejectedSessionChecks, { timeout: 30_000 }).toBeGreaterThan(0);
	await expect(page.locator('[data-authenticated="false"]')).toBeVisible({ timeout: 30_000 });
	await expect(page.getByTestId('header-login-signup-btn')).toBeVisible({ timeout: 30_000 });
	const afterExpiry = uploads;
	await page.evaluate(() => console.warn('Diagnostic expiry regression: signed-out batch'));
	await page.waitForTimeout(12_000);
	expect(uploads).toBe(afterExpiry);
});
