/* eslint-disable no-console */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Accessibility page scan tests — WCAG 2.1 AA compliance via axe-core.
 *
 * Scans major pages for automated accessibility violations. Known issues
 * (e.g. color-contrast for secondary text) are tracked in KNOWN_VIOLATIONS
 * and excluded from failure assertions.
 *
 * Architecture context: docs/architecture/accessibility.md
 * Test reference: run via scripts/run-tests.sh --suite playwright
 */
export {};

const { test, expect } = require('@playwright/test');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	expectPageAccessible,
	expectComponentAccessible
} = require('./a11y-helpers');
const {
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

/** Default options applied to all page scans — excludes third-party iframes. */
const DEFAULT_SCAN_OPTIONS = {
	exclude: ['iframe[src*="stripe"]', 'iframe[src*="recaptcha"]'],
	allowedViolations: ['color-contrast']
};

// ─── Unauthenticated page scans ─────────────────────────────────────────────

test.describe('Accessibility — unauthenticated pages', () => {
	test('landing page has no unexpected a11y violations', async ({ page }: { page: any }) => {
		test.setTimeout(60000);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForTimeout(2000);

		await expectPageAccessible(page, DEFAULT_SCAN_OPTIONS);
		console.log('✅ Landing page: no unexpected a11y violations');
	});

	test('login dialog has no unexpected a11y violations', async ({ page }: { page: any }) => {
		test.setTimeout(60000);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		// Open the login dialog
		const loginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
		await expect(loginButton).toBeVisible({ timeout: 15000 });
		await loginButton.click();
		await page.waitForTimeout(1000);

		// Scan the dialog specifically
		const dialogVisible = await page.locator('[role="dialog"]').isVisible().catch(() => false);
		if (dialogVisible) {
			await expectComponentAccessible(page, '[role="dialog"]', DEFAULT_SCAN_OPTIONS);
		} else {
			// Fallback: scan full page with login form visible
			await expectPageAccessible(page, DEFAULT_SCAN_OPTIONS);
		}
		console.log('✅ Login dialog: no unexpected a11y violations');
	});

	test('404 page has no unexpected a11y violations', async ({ page }: { page: any }) => {
		test.setTimeout(60000);

		await page.goto(getE2EDebugUrl('/nonexistent-test-path'), {
			waitUntil: 'domcontentloaded'
		});
		await page.waitForLoadState('networkidle');
		await page.waitForTimeout(3000);

		await expectPageAccessible(page, DEFAULT_SCAN_OPTIONS);
		console.log('✅ 404 page: no unexpected a11y violations');
	});
});

// ─── Authenticated page scans ───────────────────────────────────────────────

test.describe('Accessibility — authenticated pages', () => {
	const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

	test('chat interface has no unexpected a11y violations', async ({ page }: { page: any }) => {
		test.setTimeout(120000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		// Use shared loginToTestAccount() with OTP clock-drift compensation
		await loginToTestAccount(page);

		await expectPageAccessible(page, DEFAULT_SCAN_OPTIONS);
		console.log('✅ Chat interface: no unexpected a11y violations');
	});

	test('settings modal has no unexpected a11y violations', async ({ page }: { page: any }) => {
		test.setTimeout(120000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		// Use shared loginToTestAccount() with OTP clock-drift compensation
		await loginToTestAccount(page);

		// Open settings — click the profile container (settings toggle)
		const settingsButton = page.locator('[data-testid="profile-container"][role="button"]');
		await expect(settingsButton).toBeVisible({ timeout: 10000 });
		await settingsButton.click();
		await page.waitForTimeout(1000);

		// Scan the settings dialog
		const dialogVisible = await page.locator('[role="dialog"]').isVisible().catch(() => false);
		if (dialogVisible) {
			await expectComponentAccessible(page, '[role="dialog"]', DEFAULT_SCAN_OPTIONS);
		} else {
			await expectPageAccessible(page, DEFAULT_SCAN_OPTIONS);
		}
		console.log('✅ Settings modal: no unexpected a11y violations');
	});
});
