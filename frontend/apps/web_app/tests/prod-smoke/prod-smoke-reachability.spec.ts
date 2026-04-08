/*
Purpose: Cheap pre-flight smoke check that asserts the three critical prod
         pages (root, /login, /signup) load and render their key DOM markers.
Architecture: Runs from the hourly prod-smoke GitHub Actions workflow (OPE-76)
              before the heavier signup + login specs so a dead prod short-
              circuits the expensive flows.
Tests: N/A (this file is the Playwright E2E test entrypoint).

The three checks intentionally use ONLY data-testid and aria role selectors —
no CSS classes — per .claude/rules/testing.md. Any single failure here means
something is so broken on prod that running the other specs would just produce
noise.
*/
/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { test, expect } = require('../helpers/cookie-audit');
// These specs are designed to run against live production. A misconfigured
// PLAYWRIGHT_TEST_BASE_URL (pointing at dev) would mask prod outages — fail
// loudly on obvious misroutes.
const PROD_BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
test.beforeAll(() => {
	if (!PROD_BASE_URL) {
		throw new Error('PLAYWRIGHT_TEST_BASE_URL must be set for prod-smoke specs.');
	}
});

test('prod reachability: root page loads with login/signup header button', async ({ page }: { page: any }) => {
	const response = await page.goto('/');
	expect(response, 'Navigation to / must return a response').toBeTruthy();
	expect(response!.ok(), `Expected 2xx for ${PROD_BASE_URL}/, got ${response!.status()}`).toBe(true);

	// The top-right header always shows the login/signup button when logged out.
	// This doubles as a check that the SvelteKit shell hydrated.
	const loginSignupButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(loginSignupButton).toBeVisible({ timeout: 15000 });
});

test('prod reachability: signup entry renders the login/signup tabs', async ({ page }: { page: any }) => {
	await page.goto('/');
	const headerButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(headerButton).toBeVisible({ timeout: 15000 });
	await headerButton.click();

	// login-tabs is a stable data-testid rendered by the signup interface —
	// its absence means the dialog failed to mount (critical signup regression).
	const loginTabs = page.getByTestId('login-tabs');
	await expect(loginTabs).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('tab-login')).toBeVisible();
	// The signup tab label varies by locale, match via role.
	await expect(loginTabs.getByRole('button', { name: /sign up/i })).toBeVisible();
});

test('prod reachability: login tab shows email input', async ({ page }: { page: any }) => {
	await page.goto('/');
	const headerButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(headerButton).toBeVisible({ timeout: 15000 });
	await headerButton.click();

	const loginTab = page.getByTestId('tab-login');
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 10000 });
	await expect(emailInput).toBeEditable();
});
