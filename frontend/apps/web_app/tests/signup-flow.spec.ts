/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. To keep repo-wide TypeScript
// checks happy without requiring local Playwright installation, we use CommonJS
// require() and broad lint disables limited to this spec file.
const { test, expect } = require('@playwright/test');

/**
 * Basic smoke test for the signup flow on the deployed web app.
 *
 * Flow:
 * 1. Open the app root (resolved via baseURL in playwright.config.ts).
 * 2. Click the header "Login / Sign up" (or "Sign up" on small screens).
 * 3. In the login dialog, click the "Sign up" tab.
 * 4. Verify that the signup tab is now active.
 *
 * NOTE:
 * - We only use role/text based selectors so that this test keeps working if
 *   the internal DOM structure changes but labels stay stable.
 * - This is intentionally minimal, meant as an early warning if the main
 *   signup entry point breaks.
 */
test('opens signup flow from header', async ({ page }: { page: any }) => {
	// Base URL comes from PLAYWRIGHT_TEST_BASE_URL or the default in config.
	await page.goto('/');
	await page.waitForTimeout(1000);
	await page.screenshot({
		path: 'artifacts/step-1-home.png',
		fullPage: true
	});

	// 1) Click header "Login / Sign up" (desktop) or "Sign up" (mobile).
	//    The header button is implemented in Header.svelte as .login-signup-button
	//    with an aria-label derived from translations (login.login / signup.sign_up).
	const headerLoginSignupButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});

	await expect(headerLoginSignupButton).toBeVisible();
	await headerLoginSignupButton.click();
	await page.waitForTimeout(1000);
	await page.screenshot({
		path: 'artifacts/step-2-after-header-click.png',
		fullPage: true
	});

	// 2) Wait for login / signup tabs to appear in the login dialog.
	//    The tabs container in Login.svelte uses the "login-tabs" class.
	const loginTabs = page.locator('.login-tabs');
	await expect(loginTabs).toBeVisible();
	await page.waitForTimeout(1000);
	await page.screenshot({
		path: 'artifacts/step-3-login-tabs-visible.png',
		fullPage: true
	});

	// 3) Click the "Sign up" tab inside the login dialog.
	const signupTab = loginTabs.getByRole('button', { name: /sign up/i });
	await expect(signupTab).toBeVisible();
	await signupTab.click();
	await page.waitForTimeout(1000);
	await page.screenshot({
		path: 'artifacts/step-4-after-signup-tab-click.png',
		fullPage: true
	});

	// 4) Assert that the "Sign up" tab is now the active one.
	const activeTab = loginTabs.locator('.tab-button.active');
	await expect(activeTab).toHaveText(/sign up/i);
});

