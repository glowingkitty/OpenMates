/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Interface font settings E2E test.
 *
 * Validates Settings -> Interface -> Font:
 * 1. Login with the shared test account.
 * 2. Select the System UI font.
 * 3. Verify localStorage, the root data attribute, computed font family, and server POST.
 * 4. Reset to the OpenMates default Lexend Deca font.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const { openSignupInterface, submitPasswordAndHandleOtp } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
const API_BASE_URL = BASE_URL.replace('://app.dev.', '://api.dev.').replace('://app.', '://api.');

const SELECTORS = {
	emailInput: '#login-email-input',
	passwordInput: '#login-password-input',
	messageEditor: '[data-testid="message-editor"]',
	openSettingsButton: '[aria-label="Open settings menu"]',
	interfaceMenuItem: '[role="menuitem"]:has-text("Interface")',
	fontSubMenuItem: '[role="menuitem"]:has-text("Font")',
	systemFontItem: '[role="menuitem"]:has-text("System")',
	lexendFontItem: '[role="menuitem"]:has-text("Lexend Deca")',
	systemCheckbox: 'input[aria-label="Toggle system mode"]',
	lexendCheckbox: 'input[aria-label="Toggle lexend deca mode"]'
};

async function postUiFont(page: any, apiBaseUrl: string, font: string) {
	return page.evaluate(
		async ({ apiUrl, uiFont }: { apiUrl: string; uiFont: string }) => {
			try {
				const response = await fetch(`${apiUrl}/v1/settings/user/ui-font`, {
					method: 'POST',
					headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
					body: JSON.stringify({ ui_font: uiFont }),
					credentials: 'include'
				});
				const body = await response.json().catch(() => null);
				return { status: response.status, ok: response.ok, body };
			} catch (err: any) {
				return { status: -1, ok: false, error: err?.message };
			}
		},
		{ apiUrl: apiBaseUrl, uiFont: font }
	);
}

test('interface font settings — change to System, verify client + server, reset to Lexend', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(120000);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('FONT_SETTINGS');
	const takeScreenshot = createStepScreenshotter(log);

	await archiveExistingScreenshots(log);
	log('Starting interface font settings flow test.', { email: TEST_EMAIL });

	await page.goto(getE2EDebugUrl('/'));
	await page
		.waitForLoadState('networkidle', { timeout: 15000 })
		.catch(() => log('WARNING: networkidle timeout — continuing anyway.'));
	await takeScreenshot(page, '01-home');

	await openSignupInterface(page);
	await page.getByTestId('tab-login').click();

	await expect(page.locator(SELECTORS.emailInput)).toBeVisible({ timeout: 15000 });
	await page.locator(SELECTORS.emailInput).fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();

	await expect(page.locator(SELECTORS.passwordInput)).toBeVisible({ timeout: 15000 });
	await page.locator(SELECTORS.passwordInput).fill(TEST_PASSWORD);
	await submitPasswordAndHandleOtp(page, TEST_OTP_KEY, log);

	await expect(page.locator(SELECTORS.messageEditor)).toBeVisible({ timeout: 20000 });
	await takeScreenshot(page, '02-logged-in');

	const cleanup = async () => {
		const cleanupResult = await postUiFont(page, API_BASE_URL, 'lexend');
		log(
			`Cleanup UI font reset: status=${cleanupResult.status} ok=${cleanupResult.ok} ` +
				`body=${JSON.stringify(cleanupResult.body)}`
		);
		await page.evaluate(() => {
			localStorage.setItem('ui_font', 'lexend');
			document.documentElement.dataset.uiFont = 'lexend';
			document.documentElement.style.setProperty(
				'--font-primary',
				'"Lexend Deca Variable", "Lexend Deca", system-ui, sans-serif'
			);
			document.documentElement.style.setProperty(
				'--button-font-family',
				'"Lexend Deca Variable", "Lexend Deca", system-ui, sans-serif'
			);
		});
	};

	await cleanup();

	try {
		await page.locator(SELECTORS.openSettingsButton).click();
		await expect(page.locator(SELECTORS.interfaceMenuItem).first()).toBeVisible({ timeout: 10000 });
		await page.locator(SELECTORS.interfaceMenuItem).first().click();
		await takeScreenshot(page, '03-interface-view');

		await expect(page.locator(SELECTORS.fontSubMenuItem).first()).toBeVisible({ timeout: 10000 });
		await page.locator(SELECTORS.fontSubMenuItem).first().click();
		await takeScreenshot(page, '04-font-list');

		const systemFontItem = page.locator(SELECTORS.systemFontItem).first();
		const lexendCheckbox = page.locator(SELECTORS.lexendCheckbox);
		const systemCheckbox = page.locator(SELECTORS.systemCheckbox);
		await expect(systemFontItem).toBeVisible({ timeout: 5000 });
		await expect(lexendCheckbox).toBeChecked({ timeout: 5000 });

		const fontApiRequestPromise = page.waitForRequest(
			(req: any) => req.url().includes('/v1/settings/user/ui-font') && req.method() === 'POST',
			{ timeout: 10000 }
		);

		await systemFontItem.click();
		const fontApiRequest = await fontApiRequestPromise;
		await page.waitForTimeout(1000);
		await takeScreenshot(page, '05-system-selected');

		const requestBody = JSON.parse(fontApiRequest.postData() || '{}');
		expect(requestBody.ui_font).toBe('system');
		await expect(systemCheckbox).toBeChecked({ timeout: 5000 });
		await expect(lexendCheckbox).not.toBeChecked({ timeout: 5000 });

		const clientState = await page.evaluate(() => ({
			storedFont: localStorage.getItem('ui_font'),
			rootFont: document.documentElement.dataset.uiFont,
			computedFont: getComputedStyle(document.body).fontFamily
		}));
		expect(clientState.storedFont).toBe('system');
		expect(clientState.rootFont).toBe('system');
		expect(clientState.computedFont.toLowerCase()).toContain('system');

		const serverResult = await postUiFont(page, API_BASE_URL, 'system');
		expect(serverResult.ok, 'Expected 200 OK from server for ui_font=system').toBe(true);
		expect(serverResult.status).toBe(200);
		expect(serverResult.body?.success).toBe(true);
	} finally {
		await cleanup();
		await takeScreenshot(page, '06-reset-lexend');
	}
});
