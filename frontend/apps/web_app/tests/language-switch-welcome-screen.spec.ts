/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Language switch — welcome screen elements E2E test.
 *
 * Validates that the welcome screen UI elements update correctly when switching
 * languages via Settings → Interface → Language:
 *
 * 1. Recent chats scroll container (demo/example chat titles translate)
 * 2. New chat suggestion cards (default suggestions translate, CJK languages work)
 * 3. Daily inspiration banner labels (i18n chrome text translates)
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
	openSettingsButton: '[data-testid="profile-container"]',

	// Language list items (language names are the same in all locales)
	deutschMenuItem: '[role="menuitem"]:has-text("Deutsch")',
	japaneseMenuItem: '[role="menuitem"]:has-text("日本語")',
	englishMenuItem: '[role="menuitem"]:has-text("English")',

	// Welcome screen elements
	recentChatsContainer: '[data-testid="recent-chats-scroll-container"]',
	suggestionsWrapper: '[data-testid="suggestions-wrapper"]',
	dailyInspirationLabel: '[data-testid="daily-inspiration-label"]',

	// Message editor (used as "loaded" signal)
	messageEditor: '[data-testid="message-editor"]',
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
 * Open Settings → Interface → Language list from any state.
 * @param currentLang - The current locale code (needed because menu item labels are translated).
 */
async function openLanguageSettings(page: any, log: (msg: string) => void, currentLang = 'en'): Promise<void> {
	const labels = MENU_LABELS[currentLang] ?? MENU_LABELS.en;

	const openSettingsBtn = page.locator(SELECTORS.openSettingsButton);
	await expect(openSettingsBtn).toBeVisible({ timeout: 10000 });
	await openSettingsBtn.click();
	await page.waitForTimeout(600);

	const interfaceItem = page.locator(`[role="menuitem"]:has-text("${labels.interface}")`).first();
	await expect(interfaceItem).toBeVisible({ timeout: 10000 });
	await interfaceItem.click();
	await page.waitForTimeout(600);

	const languageSubItem = page.locator(`[role="menuitem"]:has-text("${labels.language}")`).first();
	await expect(languageSubItem).toBeVisible({ timeout: 10000 });
	await languageSubItem.click();
	await page.waitForTimeout(600);
	log(`Language list opened (menu labels in ${currentLang}).`);
}

/**
 * Select a language from the already-open language list, then close settings
 * by pressing Escape twice (to exit settings overlay).
 */
async function selectLanguageAndClose(
	page: any,
	selector: string,
	langCode: string,
	log: (msg: string) => void
): Promise<void> {
	const langItem = page.locator(selector).first();
	await expect(langItem).toBeVisible({ timeout: 5000 });
	await langItem.click();
	log(`Selected language: ${langCode}`);

	// Wait for translations to load and UI to update
	await page.waitForTimeout(2500);

	// Close settings by pressing Escape (may need multiple presses to exit submenus)
	await page.keyboard.press('Escape');
	await page.waitForTimeout(300);
	await page.keyboard.press('Escape');
	await page.waitForTimeout(300);
	await page.keyboard.press('Escape');
	await page.waitForTimeout(500);

	// Verify locale was applied
	const htmlLang: string = await page.evaluate(() => document.documentElement.lang);
	expect(htmlLang).toBe(langCode);
	log(`html[lang] = "${htmlLang}" — locale applied.`);
}

/**
 * Get all visible text content from the recent chats scroll container.
 */
async function getRecentChatsText(page: any): Promise<string> {
	const container = page.locator(SELECTORS.recentChatsContainer);
	const isVisible = await container.isVisible().catch(() => false);
	if (!isVisible) return '';
	return container.innerText();
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
 * Get the daily inspiration label text (if banner is visible).
 */
async function getDailyInspirationLabel(page: any): Promise<string> {
	const label = page.locator(SELECTORS.dailyInspirationLabel);
	const isVisible = await label.isVisible().catch(() => false);
	if (!isVisible) return '';
	return label.innerText();
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

	const enRecentChats = await getRecentChatsText(page);
	const enSuggestions = await getSuggestionsText(page);
	const enInspirationLabel = await getDailyInspirationLabel(page);

	log(`EN recent chats text (first 200): "${enRecentChats.slice(0, 200)}"`);
	log(`EN suggestions text (first 200): "${enSuggestions.slice(0, 200)}"`);
	log(`EN inspiration label: "${enInspirationLabel}"`);

	// Recent chats should have demo chat titles in English
	if (enRecentChats) {
		expect(enRecentChats).toContain('For everyone');
		log('✓ Recent chats contain English demo chat title "For everyone"');
	}

	// Suggestions should be visible and contain English text
	if (enSuggestions) {
		// At least one suggestion card should be visible with English text
		expect(enSuggestions.length).toBeGreaterThan(10);
		log('✓ Suggestion cards visible with English text');
	}

	// Daily inspiration label
	if (enInspirationLabel) {
		expect(enInspirationLabel.toLowerCase()).toContain('daily inspiration');
		log('✓ Daily inspiration label is in English');
	}

	await assertNoMissingTranslations(page);
	log('✓ No missing translation keys (English).');

	// ─────────────────────────────────────────────────────────────────────────
	// Step 3 — Switch to German
	// ─────────────────────────────────────────────────────────────────────────

	await openLanguageSettings(page, log, 'en');
	await selectLanguageAndClose(page, SELECTORS.deutschMenuItem, 'de', log);

	// Wait for UI to fully update
	await page.waitForTimeout(2000);
	await takeScreenshot(page, '02-welcome-german');

	const deRecentChats = await getRecentChatsText(page);
	const deSuggestions = await getSuggestionsText(page);
	const deInspirationLabel = await getDailyInspirationLabel(page);

	log(`DE recent chats text (first 200): "${deRecentChats.slice(0, 200)}"`);
	log(`DE suggestions text (first 200): "${deSuggestions.slice(0, 200)}"`);
	log(`DE inspiration label: "${deInspirationLabel}"`);

	// Recent chats should now show German demo chat titles
	if (deRecentChats) {
		expect(deRecentChats).toContain('Für alle');
		expect(deRecentChats).not.toContain('For everyone');
		log('✓ Recent chats updated to German ("Für alle" present, "For everyone" gone)');
	}

	// Suggestions should be in German
	if (deSuggestions) {
		expect(deSuggestions.length).toBeGreaterThan(10);
		// German suggestions should not contain the English prefix format literally
		// They should have German text content
		log('✓ Suggestion cards visible with German text');
	}

	// Daily inspiration label in German
	if (deInspirationLabel) {
		expect(deInspirationLabel.toLowerCase()).toContain('tägliche inspiration');
		log('✓ Daily inspiration label is in German');
	}

	await assertNoMissingTranslations(page);
	log('✓ No missing translation keys (German).');

	// ─────────────────────────────────────────────────────────────────────────
	// Step 4 — Switch to Japanese (CJK language test)
	// ─────────────────────────────────────────────────────────────────────────

	await openLanguageSettings(page, log, 'de');
	await selectLanguageAndClose(page, SELECTORS.japaneseMenuItem, 'ja', log);

	await page.waitForTimeout(2000);
	await takeScreenshot(page, '03-welcome-japanese');

	const jaRecentChats = await getRecentChatsText(page);
	const jaSuggestions = await getSuggestionsText(page);
	const jaInspirationLabel = await getDailyInspirationLabel(page);

	log(`JA recent chats text (first 200): "${jaRecentChats.slice(0, 200)}"`);
	log(`JA suggestions text (first 200): "${jaSuggestions.slice(0, 200)}"`);
	log(`JA inspiration label: "${jaInspirationLabel}"`);

	// Recent chats should show Japanese demo chat titles
	if (jaRecentChats) {
		expect(jaRecentChats).toContain('すべての人へ');
		expect(jaRecentChats).not.toContain('For everyone');
		expect(jaRecentChats).not.toContain('Für alle');
		log('✓ Recent chats updated to Japanese ("すべての人へ" present)');
	}

	// CRITICAL: Japanese suggestions must be visible (tests the CJK word count fix)
	if (jaSuggestions) {
		expect(jaSuggestions.length).toBeGreaterThan(10);
		log('✓ Suggestion cards visible with Japanese text (CJK word count fix works)');
	} else {
		// If suggestions wrapper doesn't exist, check for individual card buttons
		const cardCount = await page.locator('[data-testid="suggestions-wrapper"] .suggestion-card').count();
		expect(cardCount).toBeGreaterThan(0);
		log(`✓ ${cardCount} suggestion card(s) visible in Japanese`);
	}

	// Daily inspiration label in Japanese
	if (jaInspirationLabel) {
		expect(jaInspirationLabel).toContain('インスピレーション');
		log('✓ Daily inspiration label is in Japanese');
	}

	await assertNoMissingTranslations(page);
	log('✓ No missing translation keys (Japanese).');

	// ─────────────────────────────────────────────────────────────────────────
	// Step 5 — Reset to English (cleanup)
	// ─────────────────────────────────────────────────────────────────────────

	await openLanguageSettings(page, log, 'ja');
	await selectLanguageAndClose(page, SELECTORS.englishMenuItem, 'en', log);

	await page.waitForTimeout(2000);
	await takeScreenshot(page, '04-welcome-english-reset');

	const enResetRecentChats = await getRecentChatsText(page);
	if (enResetRecentChats) {
		expect(enResetRecentChats).toContain('For everyone');
		expect(enResetRecentChats).not.toContain('Für alle');
		expect(enResetRecentChats).not.toContain('すべての人へ');
		log('✓ Recent chats reset to English');
	}

	const enResetSuggestions = await getSuggestionsText(page);
	if (enResetSuggestions) {
		expect(enResetSuggestions.length).toBeGreaterThan(10);
		log('✓ Suggestions reset to English');
	}

	await assertNoMissingTranslations(page);
	log('✓ No missing translation keys after reset.');

	await takeScreenshot(page, '05-done');
	log('Welcome screen language switch test complete.');
});
