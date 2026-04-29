/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Language auto-detection E2E test.
 *
 * Validates the new "English-first" language loading strategy:
 *  - All first-time visitors land on English regardless of browser locale.
 *  - If the browser locale is a supported non-English language and no
 *    preferredLanguage is stored, a one-time "Language Detected" notification
 *    appears offering to switch, with a "Switch to <NativeName>" action button.
 *  - Clicking "Switch to …" applies the language and saves it to localStorage.
 *  - Dismissing the notification sets language_suggestion_shown so it never
 *    re-appears on subsequent visits.
 *  - An explicit ?lang=XX URL param still applies the language directly
 *    (existing behaviour) and prevents the notification from appearing.
 *  - A valid localStorage preferredLanguage is respected, no notification shown.
 *
 * Test matrix:
 * 1. German browser, no preference   → English UI, notification "Switch to Deutsch"
 * 2. Czech browser, no preference    → English UI, notification "Switch to Čeština"
 * 3. Unsupported locale (sw-TZ)      → English UI, no notification
 * 4. Invalid LS cleared + de browser → English UI, notification shown
 * 5. Valid LS (fr) + de browser      → French UI, no notification
 * 6. Click "Switch to Deutsch"       → html[lang]="de", preferredLanguage saved
 * 7. Dismiss notification            → language_suggestion_shown set, English kept
 * 8. Revisit after dismiss           → no notification shown again
 * 9. ?lang=de URL param              → German UI, no notification (preferredLanguage saved by handler)
 *
 * These tests do NOT require login — they test the pre-auth language detection
 * flow in i18n/setup.ts and the onMount notification logic in +page.svelte.
 *
 * Bug history: OPE-39 (wrong language auto-applied from stale localStorage).
 *
 * REQUIRED ENV VARS:
 * - PLAYWRIGHT_TEST_BASE_URL (defaults to https://app.dev.openmates.org)
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Creates a fresh browser context with a specific locale and optional
 * localStorage seeding, then navigates to the app root.
 */
async function createLocalizedPage(
	browser: any,
	locale: string,
	localStorageSeed?: Record<string, string>
): Promise<any> {
	const context = await browser.newContext({ locale });
	const page = await context.newPage();

	if (localStorageSeed) {
		await page.addInitScript((seed: Record<string, string>) => {
			for (const [key, value] of Object.entries(seed)) {
				localStorage.setItem(key, value);
			}
		}, localStorageSeed);
	}

	return { page, context };
}

/**
 * Waits for the app to initialize i18n (html[lang] attribute is set).
 */
async function waitForLocaleInit(page: any): Promise<string> {
	await page.waitForLoadState('domcontentloaded');
	// i18n setup is synchronous at module load; allow Vite module hydration
	await page.waitForTimeout(3000);
	return page.evaluate(() => document.documentElement.getAttribute('lang') || '');
}

/**
 * Waits for the language-suggestion notification to appear (or confirms it
 * does not appear within the timeout).
 *
 * Returns true if a notification with "Language Detected" is visible.
 */
async function waitForLanguageNotification(page: any, timeoutMs = 8000): Promise<boolean> {
	try {
		// The notification title is always "Language Detected"
		await page.getByText('Language Detected').waitFor({ state: 'visible', timeout: timeoutMs });
		return true;
	} catch {
		return false;
	}
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

const consoleLogs: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		consoleLogs.slice(-30).forEach((log) => console.log(log));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

test.describe('language selection — English-first with browser suggestion', () => {
	// ── 1 ──────────────────────────────────────────────────────────────────
	test('German browser, no preference → English UI + language notification', async ({
		browser
	}) => {
		test.setTimeout(60000);

		const log = createSignupLogger('LANG_DE_EN_DEFAULT');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		const { page, context } = await createLocalizedPage(browser, 'de-DE');
		page.on('console', (msg: any) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

		log('Navigating with locale de-DE, no preferredLanguage...');
		await page.goto(getE2EDebugUrl('/'));
		const htmlLang = await waitForLocaleInit(page);
		await takeScreenshot(page, '01-initial-load');

		log(`html[lang] = "${htmlLang}"`);
		expect(htmlLang).toBe('en');

		log('Waiting for language suggestion notification...');
		const notifVisible = await waitForLanguageNotification(page);
		await takeScreenshot(page, '02-notification');

		expect(notifVisible).toBe(true);
		await expect(page.getByText('Language Detected')).toBeVisible();
		// Use the action button (unique element) to confirm the correct language is shown.
		// getByText('Deutsch') would match both the message text and the button — strict mode violation.
		await expect(page.getByTestId('notification-action')).toHaveText('Switch to Deutsch');

		log('✓ German browser → English default + notification confirmed.');
		await context.close();
	});

	// ── 2 ──────────────────────────────────────────────────────────────────
	test('Czech browser, no preference → English UI + notification for Čeština', async ({
		browser
	}) => {
		test.setTimeout(60000);

		const log = createSignupLogger('LANG_CS_EN_DEFAULT');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		const { page, context } = await createLocalizedPage(browser, 'cs-CZ');
		page.on('console', (msg: any) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

		log('Navigating with locale cs-CZ, no preferredLanguage...');
		await page.goto(getE2EDebugUrl('/'));
		const htmlLang = await waitForLocaleInit(page);
		await takeScreenshot(page, '01-initial-load');

		expect(htmlLang).toBe('en');

		const notifVisible = await waitForLanguageNotification(page);
		await takeScreenshot(page, '02-notification');

		expect(notifVisible).toBe(true);
		// nativeName for Czech is "Čeština" — use the action button (unique) to avoid strict mode violation.
		await expect(page.getByTestId('notification-action')).toHaveText('Switch to Čeština');

		log('✓ Czech browser → English default + Čeština notification confirmed.');
		await context.close();
	});

	// ── 3 ──────────────────────────────────────────────────────────────────
	test('unsupported browser locale (sw-TZ) → English fallback, no notification', async ({
		browser
	}) => {
		test.setTimeout(60000);

		const log = createSignupLogger('LANG_UNSUPPORTED_FALLBACK');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		const { page, context } = await createLocalizedPage(browser, 'sw-TZ');
		page.on('console', (msg: any) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

		log('Navigating with unsupported locale sw-TZ...');
		await page.goto(getE2EDebugUrl('/'));
		const htmlLang = await waitForLocaleInit(page);
		await takeScreenshot(page, '01-en-fallback');

		expect(htmlLang).toBe('en');

		// Swahili is not a supported language → no notification
		const notifVisible = await waitForLanguageNotification(page, 4000);
		expect(notifVisible).toBe(false);

		log('✓ Unsupported locale → English, no notification confirmed.');
		await context.close();
	});

	// ── 4 ──────────────────────────────────────────────────────────────────
	test('invalid localStorage value cleared → English UI + notification for German browser', async ({
		browser
	}) => {
		test.setTimeout(60000);

		const log = createSignupLogger('LANG_INVALID_LS_CLEARED');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		const { page, context } = await createLocalizedPage(browser, 'de-DE', {
			preferredLanguage: 'xyz-invalid'
		});
		page.on('console', (msg: any) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

		log('Navigating with locale de-DE + invalid localStorage "xyz-invalid"...');
		await page.goto(getE2EDebugUrl('/'));
		const htmlLang = await waitForLocaleInit(page);
		await takeScreenshot(page, '01-invalid-ls');

		// Invalid LS is cleared → English default
		expect(htmlLang).toBe('en');

		// Invalid value should have been cleared
		const lsValue = await page.evaluate(() => localStorage.getItem('preferredLanguage'));
		expect(lsValue).toBeNull();

		// With no valid preference and German browser → notification appears
		const notifVisible = await waitForLanguageNotification(page);
		await takeScreenshot(page, '02-notification');
		expect(notifVisible).toBe(true);

		log('✓ Invalid LS cleared → English + notification confirmed.');
		await context.close();
	});

	// ── 5 ──────────────────────────────────────────────────────────────────
	test('valid localStorage preferredLanguage overrides browser language, no notification', async ({
		browser
	}) => {
		test.setTimeout(60000);

		const log = createSignupLogger('LANG_LS_OVERRIDE');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		// Browser is de-DE but localStorage says French
		const { page, context } = await createLocalizedPage(browser, 'de-DE', {
			preferredLanguage: 'fr'
		});
		page.on('console', (msg: any) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

		log('Navigating with locale de-DE + valid localStorage "fr"...');
		await page.goto(getE2EDebugUrl('/'));
		const htmlLang = await waitForLocaleInit(page);
		await takeScreenshot(page, '01-fr-from-ls');

		expect(htmlLang).toBe('fr');

		// preferredLanguage is set → no notification
		const notifVisible = await waitForLanguageNotification(page, 4000);
		expect(notifVisible).toBe(false);

		const lsValue = await page.evaluate(() => localStorage.getItem('preferredLanguage'));
		expect(lsValue).toBe('fr');

		log('✓ Valid LS overrides browser language, no notification confirmed.');
		await context.close();
	});

	// ── 6 ──────────────────────────────────────────────────────────────────
	test('clicking "Switch to Deutsch" applies German and saves preferredLanguage', async ({
		browser
	}) => {
		test.setTimeout(90000);

		const log = createSignupLogger('LANG_SWITCH_ACTION');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		const { page, context } = await createLocalizedPage(browser, 'de-DE');
		page.on('console', (msg: any) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

		log('Navigating with locale de-DE, no preferredLanguage...');
		await page.goto(getE2EDebugUrl('/'));
		await waitForLocaleInit(page);

		log('Waiting for language suggestion notification...');
		const notifVisible = await waitForLanguageNotification(page);
		expect(notifVisible).toBe(true);
		await takeScreenshot(page, '01-notification');

		log('Clicking "Switch to Deutsch" action button...');
		await page.getByTestId('notification-action').click();

		// Wait for locale change to propagate
		await page.waitForTimeout(2000);
		await takeScreenshot(page, '02-after-switch');

		const htmlLangAfter = await page.evaluate(() =>
			document.documentElement.getAttribute('lang')
		);
		log(`html[lang] after switch = "${htmlLangAfter}"`);
		expect(htmlLangAfter).toBe('de');

		const savedPref = await page.evaluate(() => localStorage.getItem('preferredLanguage'));
		log(`localStorage.preferredLanguage = "${savedPref}"`);
		expect(savedPref).toBe('de');

		log('✓ Switch to Deutsch applied language and saved preference.');
		await context.close();
	});

	// ── 7 ──────────────────────────────────────────────────────────────────
	test('dismissing notification keeps English and sets language_suggestion_shown', async ({
		browser
	}) => {
		test.setTimeout(90000);

		const log = createSignupLogger('LANG_DISMISS_NOTIFICATION');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		const { page, context } = await createLocalizedPage(browser, 'de-DE');
		page.on('console', (msg: any) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

		log('Navigating with locale de-DE...');
		await page.goto(getE2EDebugUrl('/'));
		await waitForLocaleInit(page);

		log('Waiting for language suggestion notification...');
		const notifVisible = await waitForLanguageNotification(page);
		expect(notifVisible).toBe(true);
		await takeScreenshot(page, '01-notification');

		// language_suggestion_shown is set immediately when notification fires
		const shownFlag = await page.evaluate(() =>
			localStorage.getItem('language_suggestion_shown')
		);
		expect(shownFlag).toBe('1');

		// Dismiss the notification via the close/X button
		await page.getByTestId('notification-dismiss').first().click();
		await page.waitForTimeout(1000);
		await takeScreenshot(page, '02-after-dismiss');

		// HTML lang should still be English
		const htmlLang = await page.evaluate(() =>
			document.documentElement.getAttribute('lang')
		);
		expect(htmlLang).toBe('en');

		// preferredLanguage should NOT be saved
		const pref = await page.evaluate(() => localStorage.getItem('preferredLanguage'));
		expect(pref).toBeNull();

		log('✓ Dismiss keeps English, language_suggestion_shown set.');
		await context.close();
	});

	// ── 8 ──────────────────────────────────────────────────────────────────
	test('revisit after dismiss → no notification shown again', async ({ browser }) => {
		test.setTimeout(90000);

		const log = createSignupLogger('LANG_NO_REPEAT_NOTIFICATION');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		// Simulate a return visitor: language_suggestion_shown already set
		const { page, context } = await createLocalizedPage(browser, 'de-DE', {
			language_suggestion_shown: '1'
		});
		page.on('console', (msg: any) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

		log('Navigating with locale de-DE + language_suggestion_shown="1"...');
		await page.goto(getE2EDebugUrl('/'));
		await waitForLocaleInit(page);
		await takeScreenshot(page, '01-revisit');

		// No notification should appear on revisit
		const notifVisible = await waitForLanguageNotification(page, 5000);
		expect(notifVisible).toBe(false);

		// Still English
		const htmlLang = await page.evaluate(() =>
			document.documentElement.getAttribute('lang')
		);
		expect(htmlLang).toBe('en');

		log('✓ No notification on revisit after prior dismiss confirmed.');
		await context.close();
	});

	// ── 9 ──────────────────────────────────────────────────────────────────
	test('?lang=de URL param applies German directly, no notification', async ({ browser }) => {
		test.setTimeout(60000);

		const log = createSignupLogger('LANG_URL_PARAM');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		// No locale override on the context — browser appears English
		const context = await browser.newContext();
		const page = await context.newPage();
		page.on('console', (msg: any) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

		log('Navigating with ?lang=de URL parameter...');
		await page.goto(getE2EDebugUrl('/?lang=de'));
		await waitForLocaleInit(page);
		await takeScreenshot(page, '01-lang-param');

		const htmlLang = await page.evaluate(() =>
			document.documentElement.getAttribute('lang')
		);
		log(`html[lang] = "${htmlLang}"`);
		expect(htmlLang).toBe('de');

		const savedPref = await page.evaluate(() => localStorage.getItem('preferredLanguage'));
		expect(savedPref).toBe('de');

		// preferredLanguage is set by the ?lang= handler → no notification
		const notifVisible = await waitForLanguageNotification(page, 4000);
		expect(notifVisible).toBe(false);

		log('✓ ?lang=de applies German directly, no notification shown.');
		await context.close();
	});

	// ── 10 ─────────────────────────────────────────────────────────────────
	test('?lang=de intro chat title renders in German without reload (race condition guard)', async ({
		browser
	}) => {
		test.setTimeout(90000);

		const log = createSignupLogger('LANG_URL_INTRO_CHAT');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		// English-browser context so the page would default to English
		const context = await browser.newContext();
		const page = await context.newPage();
		page.on('console', (msg: any) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

		log('Navigating with ?lang=de, checking intro chat sidebar title...');
		await page.goto(getE2EDebugUrl('/?lang=de'));
		await waitForLocaleInit(page);
		// Extra buffer for language-changed-complete propagation to Chats.svelte
		await page.waitForTimeout(2000);
		await takeScreenshot(page, '01-after-lang-param');

		// The for-everyone intro chat title in German is "OpenMates | Für alle".
		// If the race condition exists it will be "OpenMates | For everyone" (English).
		log('Checking intro chat title in German...');
		const germanTitle = page.getByText('OpenMates | Für alle');
		await expect(germanTitle).toBeVisible({ timeout: 5000 });
		await takeScreenshot(page, '02-german-intro-chat');

		// Confirm English title is NOT present
		const englishTitle = page.getByText('OpenMates | For everyone');
		await expect(englishTitle).not.toBeVisible();

		log('✓ Intro chat title renders in German without reload confirmed.');
		await context.close();
	});
});
