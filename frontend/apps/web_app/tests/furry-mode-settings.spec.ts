/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Furry Mode settings E2E test.
 *
 * Verifies the account-synced Interface → Customization toggle that switches
 * mate avatar CSS assets and persists the preference across reloads.
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

async function setFurryModeViaApi(page: any, enabled: boolean): Promise<void> {
	const result = await page.evaluate(async (nextEnabled: boolean) => {
		const response = await fetch('/v1/settings/user/interface-preferences', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
			credentials: 'include',
			body: JSON.stringify({ furry_mode_enabled: nextEnabled })
		});
		const body = await response.json().catch(() => null);
		return { ok: response.ok, status: response.status, body };
	}, enabled);

	expect(result.ok, `Expected Furry Mode cleanup API status 200, got ${result.status}`).toBe(true);
}

async function navigateToCustomizationSettings(
	page: any,
	log: (message: string, metadata?: Record<string, unknown>) => void,
	takeScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	await page.keyboard.press('Escape');
	await page.waitForTimeout(300);

	const settingsMenu = page.getByTestId('settings-menu');
	const alreadyOpen = await settingsMenu.isVisible().catch(() => false);
	if (!alreadyOpen) {
		const settingsToggle = page.locator('#settings-menu-toggle');
		await expect(settingsToggle).toBeVisible({ timeout: 10000 });
		await settingsToggle.click();
	}

	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	log('Settings menu opened.');
	await takeScreenshot(page, '02-settings-open');

	const interfaceItem = settingsMenu.getByRole('menuitem', { name: /Interface/i }).first();
	await expect(interfaceItem).toBeVisible({ timeout: 10000 });
	await interfaceItem.click();
	log('Interface settings opened.');
	await takeScreenshot(page, '03-interface-settings');

	const customizationItem = settingsMenu.getByRole('menuitem', { name: /Customization/i }).first();
	await expect(customizationItem).toBeVisible({ timeout: 10000 });
	await customizationItem.click();
	log('Customization settings opened.');

	await expect(page.getByTestId('interface-customization-settings')).toBeVisible({ timeout: 10000 });
	await takeScreenshot(page, '04-customization-settings');
}

async function getSyntheticMateBackground(page: any): Promise<string> {
	return page.evaluate(() => {
		const probe = document.createElement('div');
		probe.className = 'mate-profile software_development';
		probe.style.position = 'absolute';
		probe.style.left = '-9999px';
		document.body.appendChild(probe);
		const backgroundImage = getComputedStyle(probe).backgroundImage;
		probe.remove();
		return backgroundImage;
	});
}

test.describe('Furry Mode settings', () => {
	test.describe.configure({ timeout: 180000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('toggle switches mate avatars and persists after reload', async ({ page }: { page: any }) => {
		const log = createSignupLogger('FURRY_MODE_SETTINGS');
		const takeScreenshot = createStepScreenshotter(log, { filenamePrefix: 'furry-mode' });

		attachConsoleListeners(page, log);
		attachNetworkListeners(page, log);
		await archiveExistingScreenshots(log);

		await loginToTestAccount(page, log, takeScreenshot);
		await setFurryModeViaApi(page, false);
		await page.evaluate(() => {
			localStorage.setItem('openmates_furry_mode_enabled', 'false');
			document.documentElement.setAttribute('data-furry-mode', 'false');
		});
		log('Reset Furry Mode to off before test.');

		await navigateToCustomizationSettings(page, log, takeScreenshot);

		const furryModeRow = page.getByTestId('interface-customization-settings').getByRole('menuitem', {
			name: /Furry Mode/i
		});
		await expect(furryModeRow).toBeVisible({ timeout: 10000 });
		const furryModeToggle = furryModeRow.locator('input[type="checkbox"]');
		await expect(furryModeToggle).not.toBeChecked({ timeout: 5000 });

		const normalBackground = await getSyntheticMateBackground(page);
		expect(normalBackground).toContain('/images/mates/software_development.jpeg');

		const apiRequestPromise = page.waitForRequest(
			(req: any) =>
				req.url().includes('/v1/settings/user/interface-preferences') && req.method() === 'POST',
			{ timeout: 10000 }
		);
		await furryModeRow.getByTestId('toggle-container').click();
		const apiRequest = await apiRequestPromise;
		const requestBody = JSON.parse(apiRequest.postData() || '{}');
		expect(requestBody.furry_mode_enabled).toBe(true);
		log('Furry Mode API request sent with enabled=true.');

		await expect(furryModeToggle).toBeChecked({ timeout: 5000 });
		await expect.poll(() => page.evaluate(() => document.documentElement.getAttribute('data-furry-mode'))).toBe('true');

		const furryBackground = await getSyntheticMateBackground(page);
		expect(furryBackground).toContain('/images/mates/furry/software_development.jpeg');
		await takeScreenshot(page, '05-furry-enabled');

		await page.reload({ waitUntil: 'networkidle' });
		await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 20000 });
		await expect.poll(() => page.evaluate(() => document.documentElement.getAttribute('data-furry-mode'))).toBe('true');
		const furryBackgroundAfterReload = await getSyntheticMateBackground(page);
		expect(furryBackgroundAfterReload).toContain('/images/mates/furry/software_development.jpeg');
		log('Furry Mode persisted after reload.');

		await setFurryModeViaApi(page, false);
		await page.evaluate(() => {
			localStorage.setItem('openmates_furry_mode_enabled', 'false');
			document.documentElement.setAttribute('data-furry-mode', 'false');
		});
		log('Cleaned up Furry Mode setting.');
	});
});
