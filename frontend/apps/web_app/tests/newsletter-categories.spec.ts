/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Newsletter category toggles — Settings → Newsletter
 *
 * Two independent scenarios:
 *
 *  1. Unauthenticated visitor: the subscribe form is shown, but the per-
 *     category toggles section MUST NOT render (nothing to attach them to).
 *
 *  2. Authenticated user: the toggles section ALWAYS renders (regardless of
 *     subscription state). On first toggle the backend auto-creates a
 *     subscriber row using the account email. We verify:
 *       - toggles visible immediately after login
 *       - flipping daily_inspirations persists via the API
 *       - "Use a different email address" link is present
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const {
	attachConsoleListeners,
	attachNetworkListeners
} = require('./console-monitor');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
const API_BASE_URL = BASE_URL.replace('://app.dev.', '://api.dev.').replace('://app.', '://api.');

const CATEGORY_KEYS = [
	'updates_and_announcements',
	'tips_and_tricks',
	'daily_inspirations'
] as const;

/** Open Settings → Newsletter (works for both auth + unauth users). */
async function openNewsletterSettings(page: any, log: any): Promise<void> {
	const openSettingsBtn = page.getByRole('button', { name: /open settings menu/i });
	await expect(openSettingsBtn).toBeVisible({ timeout: 15000 });
	await openSettingsBtn.click();
	log('Settings menu opened.');

	const newsletterItem = page.getByRole('menuitem', { name: /^newsletter$/i });
	await expect(newsletterItem).toBeVisible({ timeout: 10000 });
	await newsletterItem.click();
	await page.waitForTimeout(800);
	log('Navigated to Newsletter settings.');
}

/**
 * Call the categories API from inside the browser so the auth cookie is
 * picked up automatically — mirrors what the settings page does on mount.
 */
async function fetchCategoriesViaBrowser(
	page: any
): Promise<{ success: boolean; subscribed: boolean; categories: Record<string, boolean> }> {
	return await page.evaluate(async (apiBase: string) => {
		const resp = await fetch(`${apiBase}/v1/newsletter/categories`, {
			method: 'GET',
			credentials: 'include',
			headers: { Accept: 'application/json' }
		});
		return await resp.json();
	}, API_BASE_URL);
}

// ---------------------------------------------------------------------------
// Scenario 1 — unauthenticated
// ---------------------------------------------------------------------------

test('newsletter categories: unauthenticated visitor does not see category toggles', async ({
	page
}: {
	page: any;
}) => {
	test.setTimeout(60000);

	const log = createSignupLogger('NEWSLETTER_CATEGORIES_UNAUTH');
	const screenshot = createStepScreenshotter(log, {
		filenamePrefix: 'newsletter-categories-unauth'
	});
	await archiveExistingScreenshots(log);
	attachConsoleListeners(page, log);
	attachNetworkListeners(page, log);

	await page.goto(getE2EDebugUrl('/'));
	await page.waitForLoadState('networkidle');
	await screenshot(page, '01-homepage');

	await openNewsletterSettings(page, log);
	await screenshot(page, '02-newsletter-settings');

	// The subscribe form is still available to anonymous visitors.
	const emailInput = page.getByPlaceholder(/enter your email address/i);
	await expect(emailInput).toBeVisible({ timeout: 10000 });
	log('Subscribe form is visible (expected).');

	// The per-category toggles section must NOT render for anonymous visitors —
	// there's no subscriber row to attach preferences to.
	const categoriesSection = page.getByTestId('newsletter-categories-section');
	await expect(categoriesSection).toHaveCount(0);
	log('Category toggles section is hidden (expected for anonymous visitor).');

	// And individually no toggle element should be present.
	for (const key of CATEGORY_KEYS) {
		await expect(page.getByTestId(`newsletter-category-toggle-${key}`)).toHaveCount(0);
	}
	log('No individual category toggles rendered — PASS.');
});

// ---------------------------------------------------------------------------
// Scenario 2 — authenticated
// ---------------------------------------------------------------------------

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('newsletter categories (authenticated)', () => {
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('authenticated user sees toggles matching their subscription state', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(180000);

		const log = createSignupLogger('NEWSLETTER_CATEGORIES_AUTH');
		const screenshot = createStepScreenshotter(log, {
			filenamePrefix: 'newsletter-categories-auth'
		});
		await archiveExistingScreenshots(log);
		attachConsoleListeners(page, log);
		attachNetworkListeners(page, log);

		// ── Login ──────────────────────────────────────────────────────
		await loginToTestAccount(page, log, screenshot);
		log('Logged in successfully.');

		// ── Open Settings → Newsletter ───────────────────────────────
		await openNewsletterSettings(page, log);
		await screenshot(page, '01-newsletter-settings');

		// Toggles MUST always be visible for authenticated users
		const categoriesSection = page.getByTestId('newsletter-categories-section');
		await expect(categoriesSection).toBeVisible({ timeout: 10000 });
		log('Category toggles section is visible.');

		for (const key of CATEGORY_KEYS) {
			const toggle = page.getByTestId(`newsletter-category-toggle-${key}`);
			await expect(toggle).toBeVisible();
		}
		log('All 3 category toggles rendered.');
		await screenshot(page, '02-toggles-visible');

		// "Use a different email address" link should be present
		const changeEmailBtn = page.getByTestId('newsletter-change-email-button');
		await expect(changeEmailBtn).toBeVisible({ timeout: 5000 });
		log('"Use a different email address" link is visible.');

		// ── Probe current subscription state via the API ─────────────
		const apiState = await fetchCategoriesViaBrowser(page);
		log(
			`API state: success=${apiState.success} subscribed=${apiState.subscribed} ` +
				`categories=${JSON.stringify(apiState.categories)}`
		);
		expect(apiState.success).toBe(true);
		for (const key of CATEGORY_KEYS) {
			expect(typeof apiState.categories[key]).toBe('boolean');
		}

		// ── Flip daily_inspirations and confirm the API echoes the new state
		// (this may auto-create a subscriber row if the test account wasn't subscribed)
		const dailyToggle = page.getByTestId('newsletter-category-toggle-daily_inspirations');
		const beforeState = apiState.categories.daily_inspirations;
		log(`daily_inspirations before flip: ${beforeState}`);

		await dailyToggle.click();
		await page.waitForTimeout(1500); // let the PATCH settle

		const afterState = await fetchCategoriesViaBrowser(page);
		log(`daily_inspirations after flip: ${afterState.categories.daily_inspirations}`);
		expect(afterState.success).toBe(true);
		expect(afterState.categories.daily_inspirations).toBe(!beforeState);

		// Flip back so the test is idempotent for repeated runs.
		await dailyToggle.click();
		await page.waitForTimeout(1500);

		const restoredState = await fetchCategoriesViaBrowser(page);
		expect(restoredState.categories.daily_inspirations).toBe(beforeState);
		log('daily_inspirations restored to original — toggles are persistent + reversible.');

		await screenshot(page, '03-toggle-persisted');
	});
});
