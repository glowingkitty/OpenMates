/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Language auto-detection E2E test (OPE-39).
 *
 * Validates that the UI language is correctly determined from the browser locale
 * when no explicit user preference exists, and that invalid localStorage values
 * are properly rejected.
 *
 * Test matrix:
 * 1. German browser (de-DE) → UI in German (html[lang]="de")
 * 2. Czech browser (cs-CZ) → UI in Czech (html[lang]="cs", normalized)
 * 3. Unsupported browser locale (sw-TZ) → English fallback
 * 4. Invalid localStorage value → cleared, browser language used
 * 5. Valid localStorage overrides browser language
 *
 * These tests do NOT require login — they test the pre-auth language detection
 * flow in i18n/setup.ts.
 *
 * Bug history this test suite guards against:
 * - OPE-39: Users got wrong language (cs-CZ) despite English/German browser,
 *   caused by unvalidated localStorage values and duplicate locale init in Footer
 *
 * REQUIRED ENV VARS:
 * - PLAYWRIGHT_TEST_BASE_URL (defaults to https://app.dev.openmates.org)
 */

const { test, expect } = require('@playwright/test');

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	assertNoMissingTranslations,
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

	// Seed localStorage before navigation if requested
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
 * The i18n setup runs synchronously on module load, but translations
 * load asynchronously — we wait for the lang attribute to stabilize.
 */
async function waitForLocaleInit(page: any): Promise<string> {
	// Wait for DOM to be ready and i18n to initialize
	await page.waitForLoadState('domcontentloaded');
	// Give i18n setup time to run (it sets html[lang] synchronously on module load,
	// but the module itself loads asynchronously via Vite)
	await page.waitForTimeout(3000);

	return page.evaluate(() => document.documentElement.getAttribute('lang') || '');
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

const consoleLogs: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log) => console.log(log));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

test.describe('language auto-detection (OPE-39)', () => {
	test('German browser (de-DE) → German UI', async ({ browser }) => {
		test.setTimeout(60000);

		const log = createSignupLogger('LANG_DETECT_DE');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		const { page, context } = await createLocalizedPage(browser, 'de-DE');
		page.on('console', (msg: any) => {
			consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
		});

		log('Navigating with locale de-DE...');
		await page.goto(getE2EDebugUrl('/'));
		const htmlLang = await waitForLocaleInit(page);
		await takeScreenshot(page, '01-de-detected');

		log(`html[lang] = "${htmlLang}"`);
		expect(htmlLang).toBe('de');

		// Verify no missing translation keys
		await assertNoMissingTranslations(page);
		log('✓ German browser → German UI confirmed.');

		await context.close();
	});

	test('Czech browser (cs-CZ) → Czech UI (normalized from cs-CZ)', async ({ browser }) => {
		test.setTimeout(60000);

		const log = createSignupLogger('LANG_DETECT_CS');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		const { page, context } = await createLocalizedPage(browser, 'cs-CZ');
		page.on('console', (msg: any) => {
			consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
		});

		log('Navigating with locale cs-CZ...');
		await page.goto(getE2EDebugUrl('/'));
		const htmlLang = await waitForLocaleInit(page);
		await takeScreenshot(page, '01-cs-detected');

		log(`html[lang] = "${htmlLang}"`);
		// cs-CZ should be normalized to "cs" (base language code)
		expect(htmlLang).toBe('cs');

		await assertNoMissingTranslations(page);
		log('✓ Czech browser → Czech UI confirmed (cs-CZ normalized to cs).');

		await context.close();
	});

	test('unsupported browser locale (sw-TZ) → English fallback', async ({ browser }) => {
		test.setTimeout(60000);

		const log = createSignupLogger('LANG_DETECT_FALLBACK');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		const { page, context } = await createLocalizedPage(browser, 'sw-TZ');
		page.on('console', (msg: any) => {
			consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
		});

		log('Navigating with unsupported locale sw-TZ (Swahili)...');
		await page.goto(getE2EDebugUrl('/'));
		const htmlLang = await waitForLocaleInit(page);
		await takeScreenshot(page, '01-en-fallback');

		log(`html[lang] = "${htmlLang}"`);
		expect(htmlLang).toBe('en');

		await assertNoMissingTranslations(page);
		log('✓ Unsupported locale → English fallback confirmed.');

		await context.close();
	});

	test('invalid localStorage preferredLanguage is cleared, browser language used', async ({
		browser
	}) => {
		test.setTimeout(60000);

		const log = createSignupLogger('LANG_DETECT_INVALID_LS');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		// Seed localStorage with an invalid locale value before page load
		const { page, context } = await createLocalizedPage(browser, 'de-DE', {
			preferredLanguage: 'xyz-invalid'
		});
		page.on('console', (msg: any) => {
			consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
		});

		log('Navigating with locale de-DE + invalid localStorage "xyz-invalid"...');
		await page.goto(getE2EDebugUrl('/'));
		const htmlLang = await waitForLocaleInit(page);
		await takeScreenshot(page, '01-invalid-ls-cleared');

		log(`html[lang] = "${htmlLang}"`);
		// Invalid localStorage should be ignored → browser language (de) used
		expect(htmlLang).toBe('de');

		// Verify the invalid value was cleared from localStorage
		const lsValue = await page.evaluate(() => localStorage.getItem('preferredLanguage'));
		log(`localStorage.preferredLanguage = ${lsValue === null ? '(null)' : `"${lsValue}"`}`);
		expect(lsValue).toBeNull();

		await assertNoMissingTranslations(page);
		log('✓ Invalid localStorage cleared, browser language used.');

		await context.close();
	});

	test('valid localStorage overrides browser language', async ({ browser }) => {
		test.setTimeout(60000);

		const log = createSignupLogger('LANG_DETECT_LS_OVERRIDE');
		const takeScreenshot = createStepScreenshotter(log);
		await archiveExistingScreenshots(log);

		// Browser is de-DE but localStorage says French
		const { page, context } = await createLocalizedPage(browser, 'de-DE', {
			preferredLanguage: 'fr'
		});
		page.on('console', (msg: any) => {
			consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
		});

		log('Navigating with locale de-DE + valid localStorage "fr"...');
		await page.goto(getE2EDebugUrl('/'));
		const htmlLang = await waitForLocaleInit(page);
		await takeScreenshot(page, '01-fr-from-ls');

		log(`html[lang] = "${htmlLang}"`);
		// Valid localStorage preference should override browser language
		expect(htmlLang).toBe('fr');

		// localStorage should remain set
		const lsValue = await page.evaluate(() => localStorage.getItem('preferredLanguage'));
		expect(lsValue).toBe('fr');

		await assertNoMissingTranslations(page);
		log('✓ Valid localStorage overrides browser language confirmed.');

		await context.close();
	});
});
