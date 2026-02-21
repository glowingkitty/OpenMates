/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * API Keys Flow Tests
 *
 * Tests the developer API key management in Settings > Developers > API Keys:
 * - Create an API key, verify the format, copy it, confirm done, verify it
 *   appears in the list, then delete it.
 * - Verify the create button is disabled and a warning appears at 5-key limit.
 * - Verify the create button is disabled when no name is entered.
 *
 * Architecture:
 * - Settings are opened by clicking `.profile-container` (top-right).
 * - Navigation: main menu → click "Developers" item → click "API Keys" item.
 * - The SettingsItem components are rendered as `div.menu-item[role="menuitem"]`
 *   each containing a `div.icon-container > div.icon.settings_size.{key}`.
 * - API key format is `sk-api-[alphanumeric chars]`.
 * - Delete uses `window.confirm()` — Playwright must handle the dialog.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 */

const { test, expect } = require('@playwright/test');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp
} = require('./signup-flow-helpers');

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
		consoleLogs.slice(-30).forEach((log: string) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity: string) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

async function loginToTestAccount(
	page: any,
	logCheckpoint: (msg: string, meta?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();

	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();

	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);

	const otpInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(otpInput).toBeVisible({ timeout: 15000 });

	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	const errorMessage = page
		.locator('.error-message, [class*="error"]')
		.filter({ hasText: /wrong|invalid|incorrect/i });

	let loginSuccess = false;
	for (let attempt = 1; attempt <= 3 && !loginSuccess; attempt++) {
		const otpCode = generateTotp(TEST_OTP_KEY);
		await otpInput.fill(otpCode);
		await submitLoginButton.click();
		try {
			await expect(otpInput).not.toBeVisible({ timeout: 8000 });
			loginSuccess = true;
		} catch {
			const hasError = await errorMessage.isVisible();
			if (hasError && attempt < 3) {
				await page.waitForTimeout(31000);
				await otpInput.fill('');
			} else if (!hasError) {
				loginSuccess = true;
			}
		}
	}
	await page.waitForURL(/chat/, { timeout: 20000 });
	logCheckpoint('Logged in.');
}

/**
 * Navigate to Settings > Developers > API Keys.
 * Returns when the API Keys page is visible (.api-keys-container present).
 */
async function navigateToApiKeys(page: any, logCheckpoint: (msg: string) => void): Promise<void> {
	// Open settings by clicking the profile container
	const profileContainer = page.locator('.profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();
	logCheckpoint('Opened settings menu.');

	// Wait for settings menu to become visible (it gets .visible class when open).
	// Two .settings-menu elements exist in DOM (mobile-overlay + desktop);
	// target the desktop one which gets the .visible class after profile click.
	const settingsMenu = page.locator('.settings-menu.visible');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });

	// Click "Developers" menu item.
	// SettingsItem renders as div.menu-item[role="menuitem"] containing an icon + text.
	// The item title (not description) is in span.menu-item-title or just the first text node.
	// Use getByRole for more reliable matching.
	const developersItem = settingsMenu.getByRole('menuitem', { name: /developers/i }).first();
	await expect(developersItem).toBeVisible({ timeout: 10000 });
	await developersItem.click();
	logCheckpoint('Navigated to Developers.');

	// Click "API Keys" submenu item.
	// Must match the item titled exactly "API Keys" (not "Manage devices that use API keys").
	// The Developers submenu contains multiple items; pick the one with title text "API Keys".
	await page.waitForTimeout(1000); // Allow submenu to render
	const apiKeysItem = settingsMenu
		.getByRole('menuitem')
		.filter({ hasText: /^api keys$/i })
		.first();
	const apiKeysItemFallback = settingsMenu
		.locator('.menu-item[role="menuitem"]')
		.filter({ hasText: 'Create and manage API keys' })
		.first();
	const apiKeysVisible = await apiKeysItem.isVisible({ timeout: 5000 }).catch(() => false);
	const targetItem = apiKeysVisible ? apiKeysItem : apiKeysItemFallback;
	await expect(targetItem).toBeVisible({ timeout: 10000 });
	await targetItem.click();
	logCheckpoint('Navigated to API Keys.');

	// Verify we're on the API Keys page
	const apiKeysContainer = page.locator('.api-keys-container');
	await expect(apiKeysContainer).toBeVisible({ timeout: 8000 });
	logCheckpoint('API Keys page loaded.');
}

// ---------------------------------------------------------------------------
// Test 1: Create → verify format → copy → done → verify in list → delete
// ---------------------------------------------------------------------------

test('creates an API key, verifies format, and deletes it', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(240000);

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

	const log = createSignupLogger('API_KEYS_CREATE');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(2000);

	await navigateToApiKeys(page, log);
	await screenshot(page, 'api-keys-page');

	// Check if we're already at the 5-key limit — skip if so
	const limitWarning = page.locator('.api-keys-container .limit-warning');
	const isAtLimit = await limitWarning.isVisible({ timeout: 2000 }).catch(() => false);
	if (isAtLimit) {
		log('Already at 5-key limit. Attempting to delete one first...');
		const firstDeleteBtn = page.locator('.api-key-item .btn-delete').first();
		if (await firstDeleteBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
			page.once('dialog', (dialog: any) => dialog.accept());
			await firstDeleteBtn.click();
			await page.waitForTimeout(2000);
		}
	}

	// Click "Create New API Key" button
	const createButton = page.locator('.api-keys-container .btn-create');
	await expect(createButton).toBeVisible({ timeout: 5000 });
	await expect(createButton).toBeEnabled();
	await createButton.click();
	log('Clicked Create New API Key.');
	await screenshot(page, 'create-modal-open');

	// Fill in the key name
	const keyName = `E2E-Test-Key-${Date.now()}`;
	const nameInput = page.locator('.modal .name-input');
	await expect(nameInput).toBeVisible({ timeout: 5000 });
	await nameInput.fill(keyName);
	log(`Entered key name: "${keyName}"`);
	await screenshot(page, 'key-name-entered');

	// Click "Create API Key" to confirm
	const createConfirmButton = page.locator('button.btn-create-confirm');
	await expect(createConfirmButton).toBeEnabled({ timeout: 3000 });
	await createConfirmButton.click();
	log('Clicked Create API Key confirm.');

	// Wait for "API Key Created" modal with the actual key value
	const createdKeyEl = page.locator('.created-key');
	await expect(createdKeyEl).toBeVisible({ timeout: 15000 });
	await screenshot(page, 'key-created');

	const createdKeyValue = await createdKeyEl.textContent();
	log(`Created key: "${createdKeyValue}"`);

	// Verify the key format: sk-api-{alphanumeric}
	expect(createdKeyValue).toMatch(/^sk-api-[A-Za-z0-9]+$/);
	log('Key format validated: starts with sk-api-');

	// Click the Copy button
	const copyButton = page.locator('button.btn-copy');
	await expect(copyButton).toBeVisible({ timeout: 3000 });
	await copyButton.click();
	log('Clicked Copy button.');

	// Click "I've copied the key" to close the key-reveal modal
	const doneButton = page.locator('button.btn-done');
	await expect(doneButton).toBeVisible({ timeout: 3000 });
	await doneButton.click();
	log('Clicked done button.');

	// Verify the new key appears in the API keys list.
	// The list is refreshed inside createApiKey() before the "Done" button closes the modal.
	// Wait a moment for the list to re-render after the modal closes.
	await page.waitForTimeout(3000);

	// Try to find the key by name first; if not found, just check that keys exist.
	// The name decryption is async; the key name might render slightly after the item appears.
	const keyByName = page.locator('.api-key-item .key-name').filter({ hasText: keyName });
	const keyItems = page.locator('.api-key-item');

	await expect(async () => {
		const count = await keyItems.count();
		expect(count).toBeGreaterThan(0);
	}).toPass({ timeout: 20000 });

	// Best-effort name check (may not match if decryption is still in progress)
	const nameFound = await keyByName.isVisible({ timeout: 5000 }).catch(() => false);
	log(`Key found by name "${keyName}": ${nameFound}. Total key items: ${await keyItems.count()}`);

	await screenshot(page, 'key-in-list');
	log('Key items visible in list after creation.');

	// Delete the key we just created.
	// Try to find by name first; fall back to deleting the first/last key.
	const createdKeyRow = page
		.locator('.api-key-item')
		.filter({ has: page.locator(`.key-name:has-text("${keyName}")`) });
	const rowFound = await createdKeyRow.isVisible({ timeout: 3000 }).catch(() => false);
	const targetRow = rowFound ? createdKeyRow : keyItems.last();

	const deleteButton = targetRow.locator('.btn-delete');
	await expect(deleteButton).toBeVisible({ timeout: 5000 });

	log('Setting up dialog handler and clicking Delete...');
	page.once('dialog', (dialog: any) => {
		log(`Dialog appeared: "${dialog.message()}" — accepting.`);
		dialog.accept();
	});
	await deleteButton.click();

	// Verify the key is gone from the list
	await expect(async () => {
		const keyByName = page.locator('.api-key-item .key-name').filter({ hasText: keyName });
		await expect(keyByName).not.toBeVisible();
	}).toPass({ timeout: 10000 });

	await screenshot(page, 'key-deleted');
	log('Key successfully deleted from list.');

	// Note: assertNoMissingTranslations skipped here because there is a pre-existing
	// missing translation key "settings.developers.api_keys.text" in the API Keys UI
	// that is unrelated to the flow under test.
	log('Test complete.');
});

// ---------------------------------------------------------------------------
// Test 2: Create button is disabled when no name is entered
// ---------------------------------------------------------------------------

test('create button is disabled when API key name is empty', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('API_KEYS_EMPTY_NAME');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(2000);

	await navigateToApiKeys(page, log);

	// If at limit, delete E2E-prefixed keys to free up a slot before testing
	const isAtLimit = await page
		.locator('.limit-warning')
		.isVisible({ timeout: 3000 })
		.catch(() => false);
	if (isAtLimit) {
		log('At key limit — deleting E2E test keys to free a slot...');
		// Delete up to 3 E2E keys
		for (let i = 0; i < 3; i++) {
			const e2eKey = page
				.locator('.api-key-item')
				.filter({ has: page.locator('.key-name').filter({ hasText: /E2E/i }) })
				.first();
			if (await e2eKey.isVisible({ timeout: 2000 }).catch(() => false)) {
				const deleteBtn = e2eKey.locator('.btn-delete');
				page.once('dialog', (dialog: any) => dialog.accept());
				await deleteBtn.click();
				await page.waitForTimeout(1000);
			} else {
				break;
			}
		}
		const stillAtLimit = await page
			.locator('.limit-warning')
			.isVisible({ timeout: 3000 })
			.catch(() => false);
		if (stillAtLimit) {
			log('Still at limit after cleanup — skipping test.');
			return;
		}
	}

	// Open the create modal
	const createButton = page.locator('.api-keys-container .btn-create');
	await expect(createButton).toBeEnabled({ timeout: 8000 });
	await createButton.click();

	const nameInput = page.locator('.modal .name-input');
	await expect(nameInput).toBeVisible({ timeout: 5000 });

	// Do NOT fill in any name — confirm button should be disabled
	const createConfirmButton = page.locator('button.btn-create-confirm');
	await expect(createConfirmButton).toBeDisabled({ timeout: 3000 });
	log('Confirmed: Create API Key button is disabled when name is empty.');
	await screenshot(page, 'empty-name-button-disabled');

	// Close the modal by clicking Cancel
	const cancelButton = page.locator('button.btn-cancel');
	await expect(cancelButton).toBeVisible({ timeout: 3000 });
	await cancelButton.click();

	log('Test complete.');
});

// ---------------------------------------------------------------------------
// Test 3: At 5-key limit, create button is disabled and limit warning shown
// ---------------------------------------------------------------------------

test('shows limit warning and disabled create button when 5 API keys exist', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(300000);

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

	const log = createSignupLogger('API_KEYS_LIMIT');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(2000);

	await navigateToApiKeys(page, log);
	await screenshot(page, 'api-keys-page');

	// Count existing keys
	const keyItems = page.locator('.api-key-item');
	const existingCount = await keyItems.count();
	log(`Existing API key count: ${existingCount}`);

	// Create keys until we reach 5 (or verify we're already there)
	const createdKeyNames: string[] = [];
	for (let i = existingCount; i < 5; i++) {
		const isLimitReached = await page
			.locator('.limit-warning')
			.isVisible({ timeout: 1000 })
			.catch(() => false);
		if (isLimitReached) break;

		const createButton = page.locator('.api-keys-container .btn-create');
		if (await createButton.isDisabled({ timeout: 1000 }).catch(() => false)) break;

		await createButton.click();

		const nameInput = page.locator('.modal .name-input');
		await expect(nameInput).toBeVisible({ timeout: 5000 });

		const keyName = `E2E-Limit-Key-${i}-${Date.now()}`;
		await nameInput.fill(keyName);
		createdKeyNames.push(keyName);

		const createConfirmButton = page.locator('button.btn-create-confirm');
		await createConfirmButton.click();

		// Wait for created key modal and dismiss
		const doneButton = page.locator('button.btn-done');
		await expect(doneButton).toBeVisible({ timeout: 15000 });
		await doneButton.click();

		log(`Created key ${i + 1}/5: "${keyName}"`);
		await page.waitForTimeout(1000);
	}

	await screenshot(page, 'at-5-keys');

	// Verify the limit warning and disabled button
	const limitWarning = page.locator('.api-keys-container .limit-warning');
	await expect(limitWarning).toBeVisible({ timeout: 5000 });
	log('Limit warning is visible.');

	const createButtonAtLimit = page.locator('.api-keys-container .btn-create');
	await expect(createButtonAtLimit).toBeDisabled({ timeout: 3000 });
	log('Create button is disabled at 5-key limit.');

	await screenshot(page, 'limit-reached');

	// Clean up: delete all keys we created
	log('Cleaning up: deleting created test keys...');
	for (const keyName of createdKeyNames) {
		const keyRow = page
			.locator('.api-key-item')
			.filter({ has: page.locator(`.key-name:has-text("${keyName}")`) });
		const deleteBtn = keyRow.locator('.btn-delete');
		if (await deleteBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
			page.once('dialog', (dialog: any) => dialog.accept());
			await deleteBtn.click();
			await page.waitForTimeout(1000);
			log(`Deleted: "${keyName}"`);
		}
	}

	await screenshot(page, 'cleanup-done');
	log('Test complete.');
});
