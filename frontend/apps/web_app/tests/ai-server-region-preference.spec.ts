/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * AI server region preference E2E test.
 *
 * Settings → AI has a "Prefer EU servers" toggle (default ON). Turning it OFF
 * selects "Fastest, global" routing; the choice is device-local (IndexedDB) and
 * must survive a full page reload. Model lists show the hosting-region flag
 * after the model name.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL / OPENMATES_TEST_ACCOUNT_PASSWORD / OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL (defaults to https://app.dev.openmates.org)
 */
export {};

const { test, expect, attachConsoleListeners, attachNetworkListeners } = require('./console-monitor');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function openAiSettings(page: any): Promise<void> {
	const settingsMenu = page.getByTestId('settings-menu');
	if (!(await settingsMenu.isVisible().catch(() => false))) {
		await page.locator('#settings-menu-toggle').click({ timeout: 10000 });
	}
	const visibleMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(visibleMenu).toBeVisible({ timeout: 10000 });
	if (!(await page.getByTestId('ai-settings').isVisible().catch(() => false))) {
		await visibleMenu.getByRole('menuitem', { name: /^AI$/i }).first().click();
	}
	await expect(page.getByTestId('ai-settings')).toBeVisible({ timeout: 8000 });
}

test.describe('AI server region preference', () => {
	test.describe.configure({ timeout: 180000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		// contract-test: supporting surface=gui.web assertions=ai-model-routing.settings.hierarchy-canonical
	test('defaults to EU, switches to Fastest, global and persists', async ({ page }: { page: any }) => {
		const log = createSignupLogger('SERVER_REGION');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'server-region' });
		attachConsoleListeners(page, log);
		attachNetworkListeners(page, log);
		await archiveExistingScreenshots(log);

		await loginToTestAccount(page, log, screenshot);
		await openAiSettings(page);

		const row = page.getByTestId('ai-server-region-eu-toggle');
		await expect(row).toBeVisible({ timeout: 10000 });
		const checkbox = row.locator('input[type="checkbox"]');
		expect(await checkbox.evaluate((el: HTMLInputElement) => el.checked)).toBe(true);
		await screenshot(page, '01-default-eu');

		await row.click();
		await expect(async () => {
			expect(await checkbox.evaluate((el: HTMLInputElement) => el.checked)).toBe(false);
		}).toPass({ timeout: 10000 });
		await screenshot(page, '02-fastest-global');

		await page.reload({ waitUntil: 'networkidle' });
		await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 20000 });
		await openAiSettings(page);
		const rowAfter = page.getByTestId('ai-server-region-eu-toggle');
		await expect(rowAfter).toBeVisible({ timeout: 10000 });
		expect(await rowAfter.locator('input[type="checkbox"]').evaluate((el: HTMLInputElement) => el.checked)).toBe(false);
		await screenshot(page, '03-persisted-global');

		// Restore the default so the shared test account stays on EU routing.
		await rowAfter.click();
		await expect(async () => {
			expect(await rowAfter.locator('input[type="checkbox"]').evaluate((el: HTMLInputElement) => el.checked)).toBe(true);
		}).toPass({ timeout: 10000 });
	});
});
