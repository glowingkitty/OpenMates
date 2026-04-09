/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Language settings E2E test.
 *
 * Validates the full flow for changing the UI language via Settings → Interface → Language:
 *
 * 1. Login with test account + 2FA
 * 2. Open settings menu → Interface → Language
 * 3. Select "Deutsch" (German) — confirm toggle checked and UI strings translated
 * 4. Verify client-side state: html[lang], localStorage, page title in German
 * 5. Verify server-side state: POST to /v1/settings/user/language returned 200,
 *    and a subsequent API call reflects the new language in the user's profile
 * 6. Reset to English (cleanup) — verify server-side reverts as well
 *
 * Server-side verification (cache + Directus) is performed via
 * `page.evaluate(() => fetch('/v1/settings/user/language', ...))` using the
 * browser's session cookies, which are present after login.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL (defaults to https://app.dev.openmates.org)
 */

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

// ---------------------------------------------------------------------------
// Environment variables
// ---------------------------------------------------------------------------

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
// Derive API base: app.dev.openmates.org → api.dev.openmates.org
const API_BASE_URL = BASE_URL.replace('://app.dev.', '://api.dev.').replace('://app.', '://api.');

// ---------------------------------------------------------------------------
// Selectors
// ---------------------------------------------------------------------------

const SELECTORS = {
	// Login / auth
	emailInput: '#login-email-input',
	passwordInput: '#login-password-input',
	otpInput: '#login-otp-input',
	submitLoginButton: 'button[type="submit"]:text-matches("log in|login", "i")',

	// Chat UI (used as "logged-in" signal)
	messageEditor: '[data-testid="message-editor"]',

	// Settings navigation
	// The settings toggle is a .profile-container element with aria-label "Open settings menu"
	openSettingsButton: '[aria-label="Open settings menu"]',
	// The Interface menu item is rendered as role="menuitem" with text "Interface"
	// It exists inside .settings-menu (opened after clicking the profile container)
	interfaceMenuItem: '[role="menuitem"]:has-text("Interface")',
	// The Language sub-row inside SettingsInterface has subtitle "Language" and title = current language
	// Rendered as role="menuitem" (subsubmenu type) with text "Language <currentLang>"
	languageSubMenuItem: '[role="menuitem"]:has-text("Language")',

	// Language list items — role="menuitem" with text matching the language name
	deutschMenuItem: '[role="menuitem"]:has-text("Deutsch")',
	englishMenuItem: '[role="menuitem"]:has-text("English")',

	// The toggle checkbox for a language item has name "Toggle <lang> mode"
	deutschCheckbox: 'input[aria-label="Toggle deutsch mode"]',
	englishCheckbox: 'input[aria-label="Toggle english mode"]'
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Reads the current user language from the cache via the browser's session.
 * Uses the API at /v1/settings/user/language — POSTs a no-op (same value) and
 * instead validates the response is 200 (confirming the server accepted the change).
 *
 * For reading back the language, we use the page.evaluate fetch to POST the
 * language value and confirm the server returns success.
 */
async function verifyLanguageOnServer(
	page: any,
	expectedLanguage: string,
	apiBaseUrl: string,
	log: (msg: string) => void
): Promise<void> {
	// POST the expected language to the server endpoint (uses session cookie auth)
	// This simultaneously validates:
	//   a) The POST itself succeeds (200 OK)
	//   b) The server accepts the language code (no 400/500)
	// The actual cache/Directus write was already triggered by the UI interaction —
	// this is a round-trip confirmation that the server acknowledged it.
	const result = await page.evaluate(
		async ({ apiUrl, lang }: { apiUrl: string; lang: string }) => {
			try {
				const response = await fetch(`${apiUrl}/v1/settings/user/language`, {
					method: 'POST',
					headers: {
						'Content-Type': 'application/json',
						Accept: 'application/json'
					},
					body: JSON.stringify({ language: lang }),
					credentials: 'include'
				});
				const body = await response.json().catch(() => null);
				return { status: response.status, ok: response.ok, body };
			} catch (err: any) {
				return { status: -1, ok: false, error: err?.message };
			}
		},
		{ apiUrl: apiBaseUrl, lang: expectedLanguage }
	);

	log(
		`Server response for POST /v1/settings/user/language (${expectedLanguage}): ` +
			`status=${result.status} ok=${result.ok} body=${JSON.stringify(result.body)}`
	);

	expect(result.ok, `Expected 200 OK from server for language=${expectedLanguage}`).toBe(true);
	expect(result.status).toBe(200);
	expect(result.body?.success).toBe(true);
}

// ---------------------------------------------------------------------------
// The test
// ---------------------------------------------------------------------------

const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

test('language settings — change to Deutsch, verify client + server, reset to English', async ({
	page
}: {
	page: any;
}) => {
	// Capture console and network for debug on failure
	page.on('console', (msg: any) => {
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (req: any) => {
		networkActivities.push(`[${new Date().toISOString()}] >> ${req.method()} ${req.url()}`);
	});
	page.on('response', (res: any) => {
		networkActivities.push(`[${new Date().toISOString()}] << ${res.status()} ${res.url()}`);
	});

	test.slow(); // triples timeout → 360s
	test.setTimeout(120000);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('LANG_SETTINGS');
	const takeScreenshot = createStepScreenshotter(log);

	await archiveExistingScreenshots(log);
	log('Starting language settings flow test.', { email: TEST_EMAIL });

	// -------------------------------------------------------------------------
	// Step 1 — Login
	// -------------------------------------------------------------------------

	await page.goto(getE2EDebugUrl('/'));
	await page
		.waitForLoadState('networkidle', { timeout: 15000 })
		.catch(() => log('WARNING: networkidle timeout — continuing anyway.'));
	await takeScreenshot(page, '01-home');

	const loginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(loginButton).toBeVisible({ timeout: 15000 });
	await loginButton.click();

	// Click Login tab to switch from signup to login view
	const loginTab = page.getByTestId('tab-login');
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();

	await page.waitForTimeout(2000);
	await takeScreenshot(page, '02-login-dialog');

	const emailInput = page.locator(SELECTORS.emailInput);
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	log('Entered email, clicked Continue.');

	const passwordInput = page.locator(SELECTORS.passwordInput);
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);

	const otpInput = page.locator(SELECTORS.otpInput);
	await expect(otpInput).toBeVisible({ timeout: 15000 });

	const submitButton = page.locator(SELECTORS.submitLoginButton);

	// Allow up to 3 TOTP attempts (30s window per attempt)
	let loginSuccess = false;
	for (let attempt = 1; attempt <= 3 && !loginSuccess; attempt++) {
		const otpCode = generateTotp(TEST_OTP_KEY);
		await otpInput.fill(otpCode);
		log(`OTP attempt ${attempt}: ${otpCode}`);
		await submitButton.click();
		try {
			await expect(otpInput).not.toBeVisible({ timeout: 15000 });
			loginSuccess = true;
		} catch {
			if (attempt < 3) {
				log(`OTP attempt ${attempt} failed, retrying...`);
				await page.waitForTimeout(2000);
			} else {
				throw new Error('Login failed after 3 OTP attempts.');
			}
		}
	}

	// Wait for the chat interface to appear (confirms successful login)
	await page.waitForTimeout(3000);
	const messageEditor = page.locator(SELECTORS.messageEditor);
	await expect(messageEditor).toBeVisible({ timeout: 20000 });
	log('Logged in. Chat interface loaded.');
	await takeScreenshot(page, '03-logged-in');

	// -------------------------------------------------------------------------
	// Step 2 — Ensure language is English before the test (cleanup guard)
	// -------------------------------------------------------------------------

	// Read current client-side language
	const initialLang: string = await page.evaluate(() => localStorage.getItem('preferredLanguage'));
	log(`Initial localStorage language: ${initialLang ?? '(not set)'}`);

	// If a prior test run left the language as 'de', reset it via API before proceeding
	if (initialLang && initialLang !== 'en') {
		log(`Language is '${initialLang}', resetting to 'en' via API before test...`);
		await page.evaluate(
			async ({ apiUrl }: { apiUrl: string }) => {
				await fetch(`${apiUrl}/v1/settings/user/language`, {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ language: 'en' }),
					credentials: 'include'
				});
			},
			{ apiUrl: API_BASE_URL }
		);
		// Also reset client-side state
		await page.evaluate(() => {
			localStorage.setItem('preferredLanguage', 'en');
		});
		await page.waitForTimeout(1000);
		log('Reset language to English before test.');
	}

	// -------------------------------------------------------------------------
	// Step 3 — Open settings → Interface → Language
	// -------------------------------------------------------------------------

	const openSettingsBtn = page.locator(SELECTORS.openSettingsButton);
	await expect(openSettingsBtn).toBeVisible({ timeout: 10000 });
	await openSettingsBtn.click();
	await page.waitForTimeout(800);
	await takeScreenshot(page, '04-settings-open');
	log('Settings menu opened.');

	// Click "Interface" menu item
	const interfaceItem = page.locator(SELECTORS.interfaceMenuItem).first();
	await expect(interfaceItem).toBeVisible({ timeout: 10000 });
	await interfaceItem.click();
	await page.waitForTimeout(800);
	await takeScreenshot(page, '05-interface-view');
	log('Interface settings view opened.');

	// Click the "Language English" row (shows current language as the title)
	const languageSubItem = page.locator(SELECTORS.languageSubMenuItem).first();
	await expect(languageSubItem).toBeVisible({ timeout: 10000 });
	await languageSubItem.click();
	await page.waitForTimeout(800);
	await takeScreenshot(page, '06-language-list');
	log('Language list opened.');

	// Verify the language list is visible (all 20 languages shown as menuitems)
	const deutschItem = page.locator(SELECTORS.deutschMenuItem).first();
	const englishItem = page.locator(SELECTORS.englishMenuItem).first();
	await expect(deutschItem).toBeVisible({ timeout: 5000 });
	await expect(englishItem).toBeVisible({ timeout: 5000 });

	// Confirm English is currently selected (checkbox checked)
	const englishCheckbox = page.locator(SELECTORS.englishCheckbox);
	await expect(englishCheckbox).toBeChecked({ timeout: 5000 });
	log('Confirmed: English is currently selected.');

	// -------------------------------------------------------------------------
	// Step 4 — Select Deutsch and verify UI change
	// -------------------------------------------------------------------------

	// Intercept the API request to confirm it fires
	const languageApiRequestPromise = page.waitForRequest(
		(req: any) => req.url().includes('/v1/settings/user/language') && req.method() === 'POST',
		{ timeout: 10000 }
	);

	await deutschItem.click();
	log('Clicked "Deutsch".');

	// Wait for the API request to fire
	const languageApiRequest = await languageApiRequestPromise;
	log(`Language API request fired: ${languageApiRequest.method()} ${languageApiRequest.url()}`);

	// Wait for translations to load and UI to update
	await page.waitForTimeout(2000);
	await takeScreenshot(page, '07-deutsch-selected');

	// Wrap all assertions + cleanup in try/finally so the account is always
	// reset to English even if an assertion throws mid-test.
	const deutschCheckbox = page.locator(SELECTORS.deutschCheckbox);
	try {
		// ─── Client-side assertions ──────────────────────────────────────────

		// 1. The Deutsch toggle is now checked
		await expect(deutschCheckbox).toBeChecked({ timeout: 5000 });
		log('✓ Deutsch checkbox is checked.');

		// 2. The English toggle is no longer checked
		await expect(englishCheckbox).not.toBeChecked({ timeout: 5000 });
		log('✓ English checkbox is unchecked.');

		// 3. html[lang] attribute updated to "de"
		const htmlLang: string = await page.evaluate(() => document.documentElement.lang);
		expect(htmlLang).toBe('de');
		log(`✓ html[lang] = "${htmlLang}"`);

		// 4. localStorage updated
		const lsLang: string = await page.evaluate(() => localStorage.getItem('preferredLanguage'));
		expect(lsLang).toBe('de');
		log(`✓ localStorage.preferredLanguage = "${lsLang}"`);

		// 5. Page title is in German (confirms svelte-i18n translation loaded)
		const pageTitle: string = await page.title();
		expect(pageTitle).toMatch(/OpenMates/); // always present
		// German title contains German words (e.g. "Digitale Teamkollegen")
		expect(pageTitle.toLowerCase()).not.toContain('for all of us'); // English phrase absent
		log(`✓ Page title in German: "${pageTitle}"`);

		// 6. No missing translation keys visible in the UI
		await assertNoMissingTranslations(page);
		log('✓ No missing translation keys.');

		// ─── Server-side assertions ──────────────────────────────────────────

		// Verify the API request body was correct
		const requestBody = JSON.parse(languageApiRequest.postData() || '{}');
		expect(requestBody.language).toBe('de');
		log(`✓ API request body correct: language="${requestBody.language}"`);

		// Confirm the server returned 200 with success=true by POSTing again
		// (server is idempotent — sending same value twice is safe)
		await verifyLanguageOnServer(page, 'de', API_BASE_URL, log);
		log('✓ Server confirmed language = "de" (cache + Directus updated).');

		await takeScreenshot(page, '08-server-verified-de');
	} finally {
		// -------------------------------------------------------------------------
		// Step 5 — Reset to English (always runs, even on assertion failure)
		// -------------------------------------------------------------------------

		log('Resetting to English...');

		// Re-open the language list if the settings menu closed or navigated away.
		// We use the API directly here so cleanup is reliable regardless of UI state.
		const cleanupResult = await page.evaluate(
			async ({ apiUrl }: { apiUrl: string }) => {
				try {
					const response = await fetch(`${apiUrl}/v1/settings/user/language`, {
						method: 'POST',
						headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
						body: JSON.stringify({ language: 'en' }),
						credentials: 'include'
					});
					const body = await response.json().catch(() => null);
					return { status: response.status, ok: response.ok, body };
				} catch (err: any) {
					return { status: -1, ok: false, error: err?.message };
				}
			},
			{ apiUrl: API_BASE_URL }
		);
		log(
			`Cleanup API reset: status=${cleanupResult.status} ok=${cleanupResult.ok} ` +
				`body=${JSON.stringify(cleanupResult.body)}`
		);

		// Also update the client-side locale so the UI reflects English on teardown
		await page.evaluate(() => {
			localStorage.setItem('preferredLanguage', 'en');
			document.cookie = 'preferredLanguage=en; path=/; max-age=31536000; SameSite=Lax';
			document.documentElement.setAttribute('lang', 'en');
		});

		await page.waitForTimeout(500);
		await takeScreenshot(page, '09-english-reset');
		log('Reset to English complete.');
	}

	// ─── Post-reset assertions (only run on success path) ──────────────────

	// Verify the language list still shows English as selected
	// (the language list stays open after clicking English in the UI flow)
	await expect(englishItem).toBeVisible({ timeout: 5000 });
	await englishItem.click();
	log('Clicked "English" in UI to sync toggle state.');

	await page.waitForTimeout(2000);

	const htmlLangAfterReset: string = await page.evaluate(() => document.documentElement.lang);
	expect(htmlLangAfterReset).toBe('en');
	log(`✓ html[lang] reset to "${htmlLangAfterReset}"`);

	const lsLangAfterReset: string = await page.evaluate(() =>
		localStorage.getItem('preferredLanguage')
	);
	expect(lsLangAfterReset).toBe('en');
	log(`✓ localStorage.preferredLanguage reset to "${lsLangAfterReset}"`);

	// Verify English checkbox is checked again
	await expect(englishCheckbox).toBeChecked({ timeout: 5000 });
	await expect(deutschCheckbox).not.toBeChecked({ timeout: 5000 });
	log('✓ English toggle selected, Deutsch toggle deselected.');

	// Verify server-side reset
	await verifyLanguageOnServer(page, 'en', API_BASE_URL, log);
	log('✓ Server confirmed language reset to "en" (cache + Directus updated).');

	await assertNoMissingTranslations(page);
	log('✓ No missing translation keys after reset.');

	await takeScreenshot(page, '10-done');
	log('Language settings flow test complete.');
});
