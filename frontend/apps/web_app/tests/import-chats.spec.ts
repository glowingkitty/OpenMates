/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Import Chats E2E test for Settings > Account > Import.
 * Purpose: verify ZIP upload, chat selection list, import completion, and cleanup.
 * Architecture context: docs/architecture/ and chat import services in frontend/packages/ui/src/services/.
 * Validation target: frontend/packages/ui/src/components/settings/account/SettingsImportAccount.svelte.
 * Test refs: docs/contributing/guides/testing.md.
 */

const path = require('path');
const { test, expect } = require('@playwright/test');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const IMPORT_CHAT_TITLE_1 = 'Playwright Import Test Chat 1';
const IMPORT_CHAT_TITLE_2 = 'Playwright Import Test Chat 2';
const IMPORT_CHAT_TITLES = [IMPORT_CHAT_TITLE_1, IMPORT_CHAT_TITLE_2];

const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.error('\n--- DEBUG INFO ON FAILURE ---');
		console.error('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log: string) => console.error(log));
		console.error('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-30).forEach((activity: string) => console.error(activity));
		console.error('\n--- END DEBUG INFO ---\n');
	}
});

async function openImportSettings(page: any): Promise<void> {
	const settingsMenuButton = page.locator('.profile-container[role="button"]');
	await expect(settingsMenuButton).toBeVisible({ timeout: 15000 });
	await settingsMenuButton.click();

	await expect(page.locator('.settings-menu.visible')).toBeVisible({ timeout: 10000 });
	await page.getByRole('menuitem', { name: /account/i }).click();
	await page.getByRole('menuitem', { name: /import/i }).click();

	await expect(page.locator('#import-file-input')).toBeAttached({ timeout: 15000 });
}

async function deleteChatByTitle(page: any, title: string): Promise<void> {
	for (let attempt = 0; attempt < 6; attempt++) {
		const chatTitle = page.locator('.chat-item-wrapper .chat-title', { hasText: title }).first();
		const exists = await chatTitle.isVisible({ timeout: 1500 }).catch(() => false);
		if (!exists) {
			return;
		}

		const chatItem = chatTitle
			.locator('xpath=ancestor::*[contains(@class,"chat-item-wrapper")]')
			.first();
		await chatItem.click({ button: 'right' });

		const deleteButton = page.locator('.menu-item.delete');
		await expect(deleteButton).toBeVisible({ timeout: 5000 });
		await deleteButton.click();
		await deleteButton.click();

		await expect(chatTitle).not.toBeVisible({ timeout: 10000 });
		await page.waitForTimeout(700);
	}
}

test('imports chats from ZIP in account settings and shows success results', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(180000);

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);
	page.on('request', (req: any) =>
		networkActivities.push(`[${new Date().toISOString()}] >> ${req.method()} ${req.url()}`)
	);
	page.on('response', (res: any) =>
		networkActivities.push(`[${new Date().toISOString()}] << ${res.status()} ${res.url()}`)
	);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('IMPORT_CHATS');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'import-chats' });
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	log('Logged in to test account.');
	await screenshot(page, 'logged-in');

	for (const title of IMPORT_CHAT_TITLES) {
		await deleteChatByTitle(page, title);
	}

	await openImportSettings(page);
	log('Opened Settings > Account > Import.');
	await screenshot(page, 'import-page');

	const zipFilePath = path.resolve(__dirname, 'fixtures', 'import-chats-test.zip');
	await page.setInputFiles('#import-file-input', zipFilePath);
	log('Uploaded import ZIP file.', { zipFilePath });

	const importSelectionSection = page.locator('.select-section');
	await expect(importSelectionSection).toBeVisible({ timeout: 15000 });
	await expect(importSelectionSection.locator('.chat-item')).toHaveCount(2, { timeout: 15000 });
	await expect(
		importSelectionSection.locator('.chat-item .chat-title', { hasText: IMPORT_CHAT_TITLE_1 })
	).toBeVisible();
	await expect(
		importSelectionSection.locator('.chat-item .chat-title', { hasText: IMPORT_CHAT_TITLE_2 })
	).toBeVisible();
	await expect(
		importSelectionSection.locator('.chat-item .chat-meta', { hasText: /3\s+messages/i })
	).toBeVisible();
	await expect(
		importSelectionSection.locator('.chat-item .chat-meta', { hasText: /2\s+messages/i })
	).toBeVisible();
	await screenshot(page, 'parsed-chat-list');

	const importButton = page.getByRole('button', { name: /import selected chats/i });
	await expect(importButton).toBeEnabled({ timeout: 10000 });
	await importButton.click();
	log('Started chat import.');

	const resultsContainer = page.locator('.results-container');
	await expect(resultsContainer).toBeVisible({ timeout: 45000 });
	await expect(resultsContainer).toContainText(/import complete!/i, { timeout: 45000 });
	const resultForChat1 = resultsContainer.locator('.result-item', { hasText: IMPORT_CHAT_TITLE_1 });
	const resultForChat2 = resultsContainer.locator('.result-item', { hasText: IMPORT_CHAT_TITLE_2 });
	await expect(resultForChat1).toBeVisible();
	await expect(resultForChat2).toBeVisible();
	await expect(resultForChat1).toContainText(/(2|3)\s+messages imported/i);
	await expect(resultForChat2).toContainText(/2\s+messages imported/i);
	await expect(page.getByRole('button', { name: /import another file/i })).toBeVisible();
	await screenshot(page, 'import-success');
	log('Import success UI verified.');

	for (const title of IMPORT_CHAT_TITLES) {
		await deleteChatByTitle(page, title);
	}
	log('Cleaned up imported test chats.');

	await assertNoMissingTranslations(page);
});
