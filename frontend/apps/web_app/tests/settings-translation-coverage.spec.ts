/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Settings translation coverage E2E test.
 *
 * Guards settings menu pages and the settings search catalog against missing
 * i18n leaf keys. This catches visible `[T:...]` placeholders and translation
 * keys that accidentally point at namespace objects instead of strings.
 *
 * Run with: python3 scripts/run_tests.py --spec settings-translation-coverage.spec.ts
 */
export {};

const fs = require('fs');
const path = require('path');

const {
	test,
	expect,
	attachConsoleListeners,
	attachNetworkListeners
} = require('./console-monitor');

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const SETTINGS_MENU_SELECTOR = '[data-testid="settings-menu"]';
const MISSING_TRANSLATION_PATTERN = /\[\s*T\s*:?[^[\]]+\]|\[object Object\]/g;
const MAX_TRAVERSAL_DEPTH = 4;
const NAVIGATION_WAIT_MS = 650;
const GIFT_CARD_SETTINGS_PATHS = [
	'billing/gift-cards',
	'billing/gift-cards/redeem',
	'billing/gift-cards/redeemed',
	'billing/gift-cards/buy',
	'billing/gift-cards/buy/payment',
	'billing/gift-cards/buy/confirmation'
];
const REQUIRED_NON_EMPTY_TRANSLATION_KEYS = [
	'app_settings_memories.mail.writing_styles.example_2.footer'
];

function repoPath(...segments: string[]): string {
	return path.resolve(process.cwd(), ...segments);
}

function getValueByDottedPath(source: Record<string, any>, dottedPath: string): unknown {
	return dottedPath.split('.').reduce((value: unknown, segment: string) => {
		if (value && typeof value === 'object' && segment in (value as Record<string, unknown>)) {
			return (value as Record<string, unknown>)[segment];
		}
		return undefined;
	}, source as unknown);
}

function isTranslationLeaf(value: unknown): boolean {
	return typeof value === 'string' || (
		value !== null &&
		typeof value === 'object' &&
		typeof (value as { text?: unknown }).text === 'string' &&
		(value as { text: string }).text.trim().length > 0
	);
}

function extractSettingsCatalogTranslationKeys(): string[] {
	const catalogPath = repoPath('../../packages/ui/src/services/searchSettingsCatalog.ts');
	const source = fs.readFileSync(catalogPath, 'utf8');
	const keys = new Set<string>();
	const regex = /translationKey:\s*["']([^"']+)["']/g;
	let match: RegExpExecArray | null;
	while ((match = regex.exec(source)) !== null) {
		keys.add(match[1]);
	}
	return [...keys].sort();
}

function validateSettingsCatalogTranslations(): void {
	const localePath = repoPath('../../packages/ui/src/i18n/locales/en.json');
	const locale = JSON.parse(fs.readFileSync(localePath, 'utf8'));
	const failures: string[] = [];

	for (const key of extractSettingsCatalogTranslationKeys()) {
		const value = getValueByDottedPath(locale, key);
		if (!isTranslationLeaf(value)) {
			failures.push(`${key} -> ${value === undefined ? 'missing' : typeof value}`);
		}
	}

	if (failures.length > 0) {
		throw new Error(
			`Settings search catalog translation keys must resolve to strings:\n${failures.join('\n')}`
		);
	}
}

function validateRequiredNonEmptyTranslations(): void {
	const localePath = repoPath('../../packages/ui/src/i18n/locales/en.json');
	const locale = JSON.parse(fs.readFileSync(localePath, 'utf8'));
	const failures = REQUIRED_NON_EMPTY_TRANSLATION_KEYS.filter((key) => {
		const value = getValueByDottedPath(locale, key);
		return !isTranslationLeaf(value);
	});

	if (failures.length > 0) {
		throw new Error(`Required runtime translation keys must be non-empty strings:\n${failures.join('\n')}`);
	}
}

async function collectMissingTranslationMarkers(page: any): Promise<string[]> {
	return page.evaluate(({ selector, patternSource }: { selector: string; patternSource: string }) => {
		const root = document.querySelector(selector);
		if (!root) return ['settings menu not mounted'];

		const pattern = new RegExp(patternSource, 'g');
		const values: string[] = [root.textContent || ''];
		const attributes = ['title', 'aria-label', 'placeholder', 'alt', 'value'];
		root.querySelectorAll('*').forEach((element) => {
			for (const attribute of attributes) {
				const value = element.getAttribute(attribute);
				if (value) values.push(value);
			}
		});

		const matches = values.flatMap((value) => value.match(pattern) || []);
		return [...new Set(matches)];
	}, {
		selector: SETTINGS_MENU_SELECTOR,
		patternSource: MISSING_TRANSLATION_PATTERN.source
	});
}

async function expectNoMissingTranslationMarkers(page: any, context: string): Promise<void> {
	const markers = await collectMissingTranslationMarkers(page);
	expect(markers, `Missing translation placeholders in ${context}`).toEqual([]);
}

async function openSettingsMenu(page: any): Promise<any> {
	const settingsToggle = page.locator('#settings-menu-toggle');
	await expect(settingsToggle).toBeVisible({ timeout: 10000 });
	await settingsToggle.click({ timeout: 10000 });

	const settingsMenu = page.locator(`${SETTINGS_MENU_SELECTOR}.visible`);
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	return settingsMenu;
}

async function currentSettingsView(settingsMenu: any): Promise<string> {
	return (await settingsMenu.getAttribute('data-active-view')) || 'main';
}

async function goBackTo(page: any, settingsMenu: any, targetView: string): Promise<void> {
	for (let attempt = 0; attempt < MAX_TRAVERSAL_DEPTH + 2; attempt++) {
		const currentView = await currentSettingsView(settingsMenu);
		if (currentView === targetView) return;

		const backButton = settingsMenu.getByTestId('banner-back-button').first();
		if (
			(await backButton.isVisible({ timeout: 1000 }).catch(() => false)) &&
			(await backButton.isEnabled({ timeout: 1000 }).catch(() => false))
		) {
			await backButton.click({ timeout: 5000 });
			await settingsMenu.waitFor({ state: 'visible', timeout: 5000 });
			await page.waitForTimeout(NAVIGATION_WAIT_MS);
			continue;
		}

		const legacyBackButton = settingsMenu.locator('#settings-back-button');
		if (
			(await legacyBackButton.isVisible({ timeout: 1000 }).catch(() => false)) &&
			(await legacyBackButton.isEnabled({ timeout: 1000 }).catch(() => false))
		) {
			await legacyBackButton.click({ timeout: 5000 });
			await page.waitForTimeout(NAVIGATION_WAIT_MS);
			continue;
		}

		break;
	}

	if ((await currentSettingsView(settingsMenu)) !== targetView) {
		await openSettingsPath(page, settingsMenu, targetView);
	}

	await expect(settingsMenu, `Expected to return to ${targetView}`).toHaveAttribute(
		'data-active-view',
		targetView,
		{ timeout: 5000 }
	);
}

async function traverseSettingsMenus(
	page: any,
	settingsMenu: any,
	visited: Set<string>,
	log: (message: string) => void,
	depth = 0
): Promise<void> {
	const parentView = await currentSettingsView(settingsMenu);
	if (visited.has(parentView) || depth > MAX_TRAVERSAL_DEPTH) return;

	visited.add(parentView);
	await expectNoMissingTranslationMarkers(page, parentView);

	const itemCount = await settingsMenu.getByRole('menuitem').count();
	for (let index = 0; index < itemCount; index++) {
		await expect(settingsMenu).toHaveAttribute('data-active-view', parentView, { timeout: 5000 });

		const item = settingsMenu.getByRole('menuitem').nth(index);
		if (!(await item.isVisible({ timeout: 1000 }).catch(() => false))) continue;
		if ((await item.getByTestId('toggle-container').count().catch(() => 0)) > 0) continue;

		const label = ((await item.innerText().catch(() => '')) || '').trim().replace(/\s+/g, ' ');
		if (!label || /^(logout|log out)$/i.test(label)) continue;

		await item.click({ timeout: 5000 });
		await page.waitForTimeout(NAVIGATION_WAIT_MS);

		const childView = await currentSettingsView(settingsMenu);
		if (childView === parentView) {
			await expectNoMissingTranslationMarkers(page, `${parentView} after ${label}`);
			continue;
		}

		log(`Visited settings view ${childView} from ${parentView} via "${label}".`);
		await expectNoMissingTranslationMarkers(page, childView);
		await traverseSettingsMenus(page, settingsMenu, visited, log, depth + 1);
		await goBackTo(page, settingsMenu, parentView);
	}
}

async function openSettingsPath(page: any, settingsMenu: any, settingsPath: string): Promise<void> {
	await page.evaluate((returnTo: string) => {
		window.dispatchEvent(new CustomEvent('openSettingsMenu', { detail: { returnTo } }));
	}, settingsPath);
	await expect(settingsMenu).toHaveAttribute('data-active-view', settingsPath, { timeout: 8000 });
	await page.waitForTimeout(NAVIGATION_WAIT_MS);
}

test.describe('Settings translation coverage', () => {
	test.describe.configure({ timeout: 180000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('settings catalog and visible settings/sub-settings menus have no missing translation placeholders', async ({ page }) => {
		validateSettingsCatalogTranslations();
		validateRequiredNonEmptyTranslations();

		const logCheckpoint = createSignupLogger('SETTINGS_TRANSLATION_COVERAGE');
		const screenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'settings-translation-coverage'
		});

		attachConsoleListeners(page, logCheckpoint);
		attachNetworkListeners(page, logCheckpoint);
		await archiveExistingScreenshots(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, screenshot);
		const settingsMenu = await openSettingsMenu(page);
		await screenshot(page, 'settings-main');

		const visited = new Set<string>();
		await traverseSettingsMenus(page, settingsMenu, visited, logCheckpoint);

		for (const settingsPath of GIFT_CARD_SETTINGS_PATHS) {
			await openSettingsPath(page, settingsMenu, settingsPath);
			logCheckpoint(`Opened direct gift-card settings path ${settingsPath}.`);
			await expectNoMissingTranslationMarkers(page, settingsPath);
		}

		expect(visited.size, `Visited settings views: ${[...visited].join(', ')}`).toBeGreaterThan(8);
	});
});
