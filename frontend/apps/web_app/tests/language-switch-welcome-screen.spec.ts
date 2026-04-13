/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Language switch — welcome screen elements E2E test.
 *
 * Validates that the welcome screen UI elements update correctly when switching
 * languages via Settings → Interface → Language:
 *
 * 1. Suggestion cards (translate to the new locale, CJK languages visible)
 * 2. Welcome description text (translates with locale)
 * 3. No missing translation keys after each switch
 *
 * Tests three languages: English → German → Japanese → English (cleanup).
 *
 * Runs as NON-AUTHENTICATED user to test the default/demo content path.
 * No login required — uses the public welcome screen.
 *
 * REQUIRED ENV VARS:
 * - PLAYWRIGHT_TEST_BASE_URL (defaults to https://app.dev.openmates.org)
 */

const { test, expect } = require('./helpers/cookie-audit');

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	assertNoMissingTranslations,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

// ---------------------------------------------------------------------------
// Selectors (data-testid based)
// ---------------------------------------------------------------------------

const SELECTORS = {
	// Settings navigation
	profileContainer: '[data-testid="profile-container"]',

	// Language list items (language names are the same in all locales)
	deutschMenuItem: '[role="menuitem"]:has-text("Deutsch")',
	japaneseMenuItem: '[role="menuitem"]:has-text("日本語")',
	englishMenuItem: '[role="menuitem"]:has-text("English")',

	// Welcome screen elements
	suggestionsWrapper: '[data-testid="suggestions-wrapper"]',
	dailyInspirationLabel: '[data-testid="daily-inspiration-label"]',
};

/** Menu item labels per locale (Interface, Language) */
const MENU_LABELS: Record<string, { interface: string; language: string }> = {
	en: { interface: 'Interface', language: 'Language' },
	de: { interface: 'Oberfläche', language: 'Sprache' },
	ja: { interface: 'インターフェース', language: '言語' },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Open Settings → Interface → Language list, select a language, then close
 * settings by clicking the profile container again.
 *
 * @param currentLang - The current locale code (menu items are translated).
 * @param targetSelector - Selector for the target language menuitem.
 * @param targetLangCode - Expected lang code after switch (e.g. 'de').
 */
async function switchLanguage(
	page: any,
	log: (msg: string) => void,
	currentLang: string,
	targetSelector: string,
	targetLangCode: string
): Promise<void> {
	const labels = MENU_LABELS[currentLang] ?? MENU_LABELS.en;

	// Open settings
	const profileBtn = page.locator(SELECTORS.profileContainer);
	await expect(profileBtn).toBeVisible({ timeout: 10000 });
	await profileBtn.click();
	await page.waitForTimeout(600);

	// Navigate: Interface → Language
	const interfaceItem = page.locator(`[role="menuitem"]:has-text("${labels.interface}")`).first();
	await expect(interfaceItem).toBeVisible({ timeout: 10000 });
	await interfaceItem.click();
	await page.waitForTimeout(600);

	const languageSubItem = page.locator(`[role="menuitem"]:has-text("${labels.language}")`).first();
	await expect(languageSubItem).toBeVisible({ timeout: 10000 });
	await languageSubItem.click();
	await page.waitForTimeout(600);

	// Select the target language
	const langItem = page.locator(targetSelector).first();
	await expect(langItem).toBeVisible({ timeout: 5000 });
	await langItem.click();
	log(`Selected language: ${targetLangCode}`);

	// Wait for translations to load
	await page.waitForTimeout(2500);

	// Close settings via the close (X) button inside the settings panel.
	// The close-icon-container overlaps the profile-container, making
	// profileBtn.click() fail with "pointer events intercepted".
	const closeBtn = page.locator('[data-testid="icon-button-close"]');
	await expect(closeBtn).toBeVisible({ timeout: 5000 });
	await closeBtn.click();
	await page.waitForTimeout(800);

	// Verify locale was applied
	const htmlLang: string = await page.evaluate(() => document.documentElement.lang);
	expect(htmlLang).toBe(targetLangCode);
	log(`Switched to ${targetLangCode} (html[lang] = "${htmlLang}").`);
}

/**
 * Get all visible suggestion card text content.
 */
async function getSuggestionsText(page: any): Promise<string> {
	const container = page.locator(SELECTORS.suggestionsWrapper);
	const isVisible = await container.isVisible().catch(() => false);
	if (!isVisible) return '';
	return container.innerText();
}

/**
 * Get the full visible text of the welcome/main content area.
 * Used to verify translated description text.
 */
async function getWelcomePageText(page: any): Promise<string> {
	// The main content area is the chat-side container
	const body = await page.locator('body').innerText();
	return body;
}

// ---------------------------------------------------------------------------
// The test
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
		consoleLogs.slice(-40).forEach((log) => console.log(log));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

test('welcome screen elements update when switching languages (EN → DE → JA → EN)', async ({
	page
}: {
	page: any;
}) => {
	page.on('console', (msg: any) => {
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`);
	});

	test.slow(); // triples timeout
	test.setTimeout(180000);

	const log = createSignupLogger('LANG_SWITCH_WELCOME');
	const takeScreenshot = createStepScreenshotter(log);

	await archiveExistingScreenshots(log);
	log('Starting welcome screen language switch test.');

	// ─────────────────────────────────────────────────────────────────────────
	// Step 1 — Load the welcome screen (non-auth)
	// ─────────────────────────────────────────────────────────────────────────

	await page.goto(getE2EDebugUrl('/'));
	await page
		.waitForLoadState('networkidle', { timeout: 15000 })
		.catch(() => log('WARNING: networkidle timeout — continuing.'));

	// Ensure language starts as English
	await page.evaluate(() => {
		localStorage.setItem('preferredLanguage', 'en');
	});
	// Reload to apply English locale cleanly
	await page.goto(getE2EDebugUrl('/'));
	await page
		.waitForLoadState('networkidle', { timeout: 15000 })
		.catch(() => log('WARNING: networkidle timeout — continuing.'));

	// Wait for the welcome screen to render
	await page.waitForTimeout(3000);
	await takeScreenshot(page, '01-welcome-english');

	// ─────────────────────────────────────────────────────────────────────────
	// Step 2 — Verify English baseline
	// ─────────────────────────────────────────────────────────────────────────

	const enSuggestions = await getSuggestionsText(page);
	log(`EN suggestions text (first 200): "${enSuggestions.slice(0, 200)}"`);

	// Suggestions should be visible with English text
	expect(enSuggestions.length).toBeGreaterThan(10);
	log('✓ Suggestion cards visible with English text');

	// Verify English content somewhere on the page
	const enPage = await getWelcomePageText(page);
	expect(enPage).toContain('Digital team mates');
	log('✓ Welcome page contains English description');

	await assertNoMissingTranslations(page);
	log('✓ No missing translation keys (English).');

	// ─────────────────────────────────────────────────────────────────────────
	// Step 3 — Switch to German
	// ─────────────────────────────────────────────────────────────────────────

	await switchLanguage(page, log, 'en', SELECTORS.deutschMenuItem, 'de');

	// Wait for UI to fully update
	await page.waitForTimeout(1500);
	await takeScreenshot(page, '02-welcome-german');

	const deSuggestions = await getSuggestionsText(page);
	log(`DE suggestions text (first 200): "${deSuggestions.slice(0, 200)}"`);

	// Suggestions should now be in German
	expect(deSuggestions.length).toBeGreaterThan(10);
	// Verify at least some German text replaced English
	expect(deSuggestions).not.toContain('What do you want to explore');
	log('✓ Suggestion cards updated to German');

	// Page description should be in German
	const dePage = await getWelcomePageText(page);
	expect(dePage).toContain('Digitale Team-Mates');
	expect(dePage).not.toContain('Digital team mates');
	log('✓ Welcome page description updated to German');

	// Daily inspiration label (if visible)
	const deInspirationLabel = page.locator(SELECTORS.dailyInspirationLabel);
	if (await deInspirationLabel.isVisible().catch(() => false)) {
		const labelText = await deInspirationLabel.innerText();
		expect(labelText.toLowerCase()).toContain('tägliche inspiration');
		log('✓ Daily inspiration label is in German');
	} else {
		log('⊘ Daily inspiration banner not visible (expected for non-auth)');
	}

	await assertNoMissingTranslations(page);
	log('✓ No missing translation keys (German).');

	// ─────────────────────────────────────────────────────────────────────────
	// Step 4 — Switch to Japanese (CJK language test)
	// ─────────────────────────────────────────────────────────────────────────

	await switchLanguage(page, log, 'de', SELECTORS.japaneseMenuItem, 'ja');

	await page.waitForTimeout(1500);
	await takeScreenshot(page, '03-welcome-japanese');

	// CRITICAL: Japanese suggestions must be visible (tests the CJK word count fix)
	const jaSuggestions = await getSuggestionsText(page);
	log(`JA suggestions text (first 200): "${jaSuggestions.slice(0, 200)}"`);

	expect(jaSuggestions.length).toBeGreaterThan(10);
	// Verify it's not still showing German or English
	expect(jaSuggestions).not.toContain('What do you want to explore');
	expect(jaSuggestions).not.toContain('Was möchtest du');
	log('✓ Suggestion cards visible with Japanese text (CJK word count fix works)');

	// Page should contain Japanese text
	const jaPage = await getWelcomePageText(page);
	expect(jaPage).not.toContain('Digital team mates');
	expect(jaPage).not.toContain('Digitale Team-Mates');
	log('✓ Welcome page description updated to Japanese');

	await assertNoMissingTranslations(page);
	log('✓ No missing translation keys (Japanese).');

	// ─────────────────────────────────────────────────────────────────────────
	// Step 5 — Reset to English (cleanup)
	// ─────────────────────────────────────────────────────────────────────────

	await switchLanguage(page, log, 'ja', SELECTORS.englishMenuItem, 'en');

	await page.waitForTimeout(1500);
	await takeScreenshot(page, '04-welcome-english-reset');

	const enResetSuggestions = await getSuggestionsText(page);
	expect(enResetSuggestions.length).toBeGreaterThan(10);
	log('✓ Suggestions reset to English');

	const enResetPage = await getWelcomePageText(page);
	expect(enResetPage).toContain('Digital team mates');
	log('✓ Welcome page reset to English');

	await assertNoMissingTranslations(page);
	log('✓ No missing translation keys after reset.');

	await takeScreenshot(page, '05-done');
	log('Welcome screen language switch test complete.');
});
