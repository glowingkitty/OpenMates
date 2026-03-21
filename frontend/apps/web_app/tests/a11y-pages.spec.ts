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
const {
	expectPageAccessible,
	expectComponentAccessible
} = require('./a11y-helpers');
const {
	getTestAccount,
	generateTotp,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

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

	/**
	 * Perform login and return after landing on the chat page.
	 * Reuses the same login pattern as chat-flow.spec.ts.
	 */
	async function loginAndWait(page: any): Promise<void> {
		await page.goto(getE2EDebugUrl('/'));
		await page.waitForLoadState('networkidle');

		const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
		await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
		await headerLoginButton.click();

		const emailInput = page.locator('#login-email-input');
		await expect(emailInput).toBeVisible({ timeout: 15000 });
		await emailInput.fill(TEST_EMAIL);
		await page.locator('#login-continue-button').click();

		const passwordInput = page.locator('#login-password-input');
		await expect(passwordInput).toBeVisible({ timeout: 15000 });
		await passwordInput.fill(TEST_PASSWORD);

		const otpCode = generateTotp(TEST_OTP_KEY);
		const otpInput = page.locator('#login-otp-input');
		await expect(otpInput).toBeVisible({ timeout: 15000 });
		await otpInput.fill(otpCode);

		const submitButton = page.locator('#login-submit-button');
		await expect(submitButton).toBeVisible();
		await submitButton.click();

		await page.waitForURL(/chat/, { timeout: 30000 });
		// Wait for phased sync to complete
		await page.waitForTimeout(5000);
	}

	test('chat interface has no unexpected a11y violations', async ({ page }: { page: any }) => {
		test.setTimeout(120000);
		test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
		test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
		test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

		await loginAndWait(page);

		await expectPageAccessible(page, DEFAULT_SCAN_OPTIONS);
		console.log('✅ Chat interface: no unexpected a11y violations');
	});

	test('settings modal has no unexpected a11y violations', async ({ page }: { page: any }) => {
		test.setTimeout(120000);
		test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
		test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
		test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

		await loginAndWait(page);

		// Open settings — click the profile container (settings toggle)
		const settingsButton = page.locator('.profile-container[role="button"]');
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
