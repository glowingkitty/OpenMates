/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed (request-count and session-state check; the Playwright video is kept)
/**
 * Default (TypeScript) logout with two tabs open. Tab B holds open IndexedDB
 * connections; they must close on versionchange so tab A's database deletion is
 * not blocked. Server logout is sent exactly once and tab B ends logged out.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
test('logout with a second tab open sends one server logout and logs out both tabs', async ({ page, context }: { page: any; context: any }) => {
	test.slow();
	test.setTimeout(240000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	// Pin the default TypeScript auth path even on Rust-core builds.
	await context.addInitScript(() => localStorage.setItem('openmates_rust_auth', 'ts'));

	const logoutRequests: string[] = [];
	const track = (target: any) => target.on('request', (request: any) => {
		if (new URL(request.url()).pathname === '/v1/auth/logout') logoutRequests.push(request.method());
	});
	track(page);

	const log = createSignupLogger('LOGOUT_MULTI_TAB');
	const screenshot = createStepScreenshotter(log);
	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
	await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 30000 });

	const peer = await context.newPage();
	track(peer);
	await peer.goto(getE2EDebugUrl('/'));
	await expect(peer.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 30000 });
	logoutRequests.splice(0);

	const settings = page.locator('[data-testid="settings-menu"].visible');
	if (!(await settings.isVisible().catch(() => false))) await page.getByTestId('profile-container').click();
	await expect(settings).toBeVisible({ timeout: 10000 });
	await page.getByRole('menuitem', { name: /logout|abmelden/i }).click();

	await expect(page.locator('[data-authenticated="true"]')).toHaveCount(0, { timeout: 15000 });
	await expect(peer.locator('[data-authenticated="true"]'), 'the second tab must end logged out')
		.toHaveCount(0, { timeout: 20000 });
	await expect.poll(() => logoutRequests.length, { timeout: 20000, message: 'server logout must be sent' }).toBeGreaterThanOrEqual(1);
	await page.waitForTimeout(2000);
	expect(logoutRequests.length, 'exactly one /v1/auth/logout across both tabs').toBe(1);
	await peer.close();
});
