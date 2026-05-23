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
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
const API_BASE_URL = BASE_URL.replace('://app.dev.', '://api.dev.').replace('://app.', '://api.');

async function setFurryModeViaApi(page: any, enabled: boolean, apiBaseUrl: string): Promise<void> {
	const result = await page.evaluate(async ({ nextEnabled, apiUrl }: { nextEnabled: boolean; apiUrl: string }) => {
		const response = await fetch(`${apiUrl}/v1/settings/user/interface-preferences`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
			credentials: 'include',
			body: JSON.stringify({ furry_mode_enabled: nextEnabled })
		});
		const body = await response.json().catch(() => null);
		return { ok: response.ok, status: response.status, body };
	}, { nextEnabled: enabled, apiUrl: apiBaseUrl });

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

async function getLocatorBackground(locator: any): Promise<string> {
	return locator.evaluate((element: HTMLElement) => getComputedStyle(element).backgroundImage);
}

async function openMatesSettings(
	page: any,
	log: (message: string, metadata?: Record<string, unknown>) => void,
	takeScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	const settingsMenu = page.getByTestId('settings-menu');
	const isOpen = await settingsMenu.isVisible().catch(() => false);
	if (!isOpen) {
		const settingsToggle = page.locator('#settings-menu-toggle');
		await expect(settingsToggle).toBeVisible({ timeout: 10000 });
		await settingsToggle.click();
		await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	}

	const activeView = await settingsMenu.getAttribute('data-active-view');
	if (activeView !== 'main') {
		const backButton = page.locator('#settings-back-button');
		await expect(backButton).toBeVisible({ timeout: 10000 });
		await backButton.click();
		await expect(settingsMenu).toHaveAttribute('data-active-view', 'main', { timeout: 10000 });
	}

	const matesItem = settingsMenu.getByRole('menuitem', { name: /^Mates$/i }).first();
	await expect(matesItem).toBeVisible({ timeout: 10000 });
	await matesItem.click();
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'mates', { timeout: 10000 });
	log('Mates settings opened.');
	await takeScreenshot(page, '06-mates-settings');
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
		await setFurryModeViaApi(page, false, API_BASE_URL);
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
		expect(normalBackground).toMatch(/^url\(/);

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
		expect(furryBackground).toMatch(/^url\(/);
		expect(furryBackground).not.toBe(normalBackground);
		await takeScreenshot(page, '05-furry-enabled');

		await openMatesSettings(page, log, takeScreenshot);
		const sophiaListAvatar = page
			.getByTestId('mate-profile-settings')
			.and(page.locator('[data-mate-id="software_development"]'));
		await expect(sophiaListAvatar).toBeVisible({ timeout: 10000 });
		expect(await getLocatorBackground(sophiaListAvatar)).toBe(furryBackground);

		await page.getByRole('button', { name: /Sophia/i }).click();
		const sophiaHeaderAvatar = page.getByTestId('mate-profile-header');
		await expect(sophiaHeaderAvatar).toBeVisible({ timeout: 10000 });
		expect(await getLocatorBackground(sophiaHeaderAvatar)).toBe(furryBackground);

		await page.getByRole('button', { name: /Show full system prompt/i }).click();
		const systemPrompt = page.getByTestId('mate-system-prompt');
		await expect(systemPrompt).toContainText('Furry Mode is enabled by the user');
		await expect(systemPrompt).toContainText('arctic fox');
		await takeScreenshot(page, '07-mate-details-furry-prompt');

		await page.reload({ waitUntil: 'networkidle' });
		await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 20000 });
		await expect.poll(() => page.evaluate(() => document.documentElement.getAttribute('data-furry-mode'))).toBe('true');
		const furryBackgroundAfterReload = await getSyntheticMateBackground(page);
		expect(furryBackgroundAfterReload).toBe(furryBackground);
		log('Furry Mode persisted after reload.');

		await setFurryModeViaApi(page, false, API_BASE_URL);
		await page.evaluate(() => {
			localStorage.setItem('openmates_furry_mode_enabled', 'false');
			document.documentElement.setAttribute('data-furry-mode', 'false');
		});
		log('Cleaned up Furry Mode setting.');
	});
});
