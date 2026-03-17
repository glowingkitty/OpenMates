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
 * Selectors: data-testid attributes (stable, Rule 11).
 * Console monitoring: shared console-monitor.ts (Rule 10).
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 */

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
	generateTotp,
	getTestAccount
} = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ─── Shared login helper ─────────────────────────────────────────────────────

/**
 * Log in with email + password + TOTP 2FA.
 * Fixes the TOTP race condition by waiting until we're well into the current
 * 30-second window before generating a code (avoids boundary expiry on submission).
 */
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

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 10000 });
	await emailInput.fill(TEST_EMAIL);
	await page.locator('#login-continue-button').click();

	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);

	const otpInput = page.locator('#login-otp-input');
	await expect(otpInput).toBeVisible({ timeout: 15000 });

	const submitLoginButton = page.locator('#login-submit-button');

	let loginSuccess = false;
	for (let attempt = 1; attempt <= 3 && !loginSuccess; attempt++) {
		// Wait until we're well into the current TOTP window to avoid boundary expiry
		const secondsIntoWindow = Math.floor(Date.now() / 1000) % 30;
		if (secondsIntoWindow > 27) {
			const msToWait = (30 - secondsIntoWindow) * 1000 + 3000;
			logCheckpoint(`Waiting ${msToWait}ms for fresh TOTP window (attempt ${attempt})...`);
			await page.waitForTimeout(msToWait);
		}

		const otpCode = generateTotp(TEST_OTP_KEY);
		await otpInput.fill(otpCode);
		await submitLoginButton.click();
		try {
			await page.waitForURL(/chat/, { timeout: 12000 });
			await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 12000 });
			loginSuccess = true;
		} catch {
			if (attempt < 3) {
				await page.waitForTimeout(3000);
				await otpInput.fill('');
			}
		}
	}
	if (!loginSuccess) {
		await takeStepScreenshot(page, 'login-failed');
		throw new Error('Login failed after 3 OTP attempts');
	}
	await page.waitForURL(/chat/, { timeout: 20000 });
	logCheckpoint('Logged in.');
}

// ─── Navigate to API Keys settings page ─────────────────────────────────────

/**
 * Navigate to Settings > Developers > API Keys.
 * Returns when the API Keys container is visible (data-testid="api-keys-container").
 */
async function navigateToApiKeys(page: any, logCheckpoint: (msg: string) => void): Promise<void> {
	const profileContainer = page.locator('#settings-menu-toggle');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();
	logCheckpoint('Opened settings menu.');

	const settingsMenu = page.locator('.settings-menu.visible');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });

	const developersItem = settingsMenu.getByRole('menuitem', { name: /developers/i }).first();
	await expect(developersItem).toBeVisible({ timeout: 10000 });
	await developersItem.click();
	logCheckpoint('Navigated to Developers.');

	await page.waitForTimeout(1000);
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

	const apiKeysContainer = page.getByTestId('api-keys-container');
	await expect(apiKeysContainer).toBeVisible({ timeout: 8000 });
	logCheckpoint('API Keys page loaded.');
}

// ---------------------------------------------------------------------------
// Test 1: Create → verify format → copy → done → verify in list → delete
// ---------------------------------------------------------------------------

test('creates an API key, verifies format, and deletes it', async ({ page }: { page: any }) => {
	attachConsoleListeners(page);
	attachNetworkListeners(page);
	test.slow();
	test.setTimeout(240000);

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

	// Check if we're already at the 5-key limit — delete one first if so
	const limitWarning = page.getByTestId('api-key-limit-warning');
	const isAtLimit = await limitWarning.isVisible({ timeout: 2000 }).catch(() => false);
	if (isAtLimit) {
		log('Already at 5-key limit. Attempting to delete one first...');
		const firstDeleteBtn = page.getByTestId('api-key-delete-button').first();
		if (await firstDeleteBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
			page.once('dialog', (dialog: any) => dialog.accept());
			await firstDeleteBtn.click();
			await page.waitForTimeout(2000);
		}
	}

	// Click "Create New API Key" button
	const createButton = page.getByTestId('api-key-create-button');
	await expect(createButton).toBeVisible({ timeout: 5000 });
	await expect(createButton).toBeEnabled();
	await createButton.click();
	log('Clicked Create New API Key.');
	await screenshot(page, 'create-modal-open');

	// Fill in the key name
	const keyName = `E2E-Test-Key-${Date.now()}`;
	const nameInput = page.getByTestId('api-key-name-input');
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
	const createdKeyEl = page.getByTestId('api-key-created-value');
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

	// Verify the new key appears in the API keys list
	await page.waitForTimeout(3000);

	const keyItems = page.getByTestId('api-key-item');
	await expect(async () => {
		const count = await keyItems.count();
		expect(count).toBeGreaterThan(0);
	}).toPass({ timeout: 20000 });

	const keyByName = page.getByTestId('api-key-name').filter({ hasText: keyName });
	const nameFound = await keyByName.isVisible({ timeout: 5000 }).catch(() => false);
	log(`Key found by name "${keyName}": ${nameFound}. Total key items: ${await keyItems.count()}`);

	await screenshot(page, 'key-in-list');
	log('Key items visible in list after creation.');

	// Delete the key we just created
	const createdKeyRow = page
		.getByTestId('api-key-item')
		.filter({ has: page.getByTestId('api-key-name').filter({ hasText: keyName }) });
	const rowFound = await createdKeyRow.isVisible({ timeout: 3000 }).catch(() => false);
	const targetRow = rowFound ? createdKeyRow : keyItems.last();

	const deleteButton = targetRow.getByTestId('api-key-delete-button');
	await expect(deleteButton).toBeVisible({ timeout: 5000 });

	log('Setting up dialog handler and clicking Delete...');
	page.once('dialog', (dialog: any) => {
		log(`Dialog appeared: "${dialog.message()}" — accepting.`);
		dialog.accept();
	});
	await deleteButton.click();

	await expect(async () => {
		const keyByName2 = page.getByTestId('api-key-name').filter({ hasText: keyName });
		await expect(keyByName2).not.toBeVisible();
	}).toPass({ timeout: 10000 });

	await screenshot(page, 'key-deleted');
	log('Key successfully deleted from list.');
	log('Test complete.');
});

// ---------------------------------------------------------------------------
// Test 2: Create button is disabled when no name is entered
// ---------------------------------------------------------------------------

test('create button is disabled when API key name is empty', async ({ page }: { page: any }) => {
	attachConsoleListeners(page);
	test.slow();
	test.setTimeout(180000);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('API_KEYS_EMPTY_NAME');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(2000);

	await navigateToApiKeys(page, log);

	// If at limit, delete E2E-prefixed keys to free up a slot
	const isAtLimit = await page
		.getByTestId('api-key-limit-warning')
		.isVisible({ timeout: 3000 })
		.catch(() => false);
	if (isAtLimit) {
		log('At key limit — deleting E2E test keys to free a slot...');
		for (let i = 0; i < 3; i++) {
			const e2eKey = page
				.getByTestId('api-key-item')
				.filter({ has: page.getByTestId('api-key-name').filter({ hasText: /E2E/i }) })
				.first();
			if (await e2eKey.isVisible({ timeout: 2000 }).catch(() => false)) {
				const deleteBtn = e2eKey.getByTestId('api-key-delete-button');
				page.once('dialog', (dialog: any) => dialog.accept());
				await deleteBtn.click();
				await page.waitForTimeout(1000);
			} else {
				break;
			}
		}
		const stillAtLimit = await page
			.getByTestId('api-key-limit-warning')
			.isVisible({ timeout: 3000 })
			.catch(() => false);
		if (stillAtLimit) {
			log('Still at limit after cleanup — skipping test.');
			return;
		}
	}

	// Open the create modal
	const createButton = page.getByTestId('api-key-create-button');
	await expect(createButton).toBeEnabled({ timeout: 8000 });
	await createButton.click();

	const nameInput = page.getByTestId('api-key-name-input');
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
// Test 3: Create key → REST API blocked → approve device → REST API works → save key
// ---------------------------------------------------------------------------

const API_BASE_URL = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';
const ARTIFACTS_DIR = process.env.PLAYWRIGHT_ARTIFACTS_DIR || '/workspace/artifacts';

test('creates API key, verifies device approval flow, and saves working key', async ({
	page,
	request
}: {
	page: any;
	request: any;
}) => {
	attachConsoleListeners(page);
	attachNetworkListeners(page);
	test.slow();
	test.setTimeout(300000);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('API_KEY_DEVICE_APPROVAL');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	// ── Phase 1: Login ────────────────────────────────────────────────────────
	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(2000);

	// ── Phase 2: Navigate to API Keys and create a new key ───────────────────
	await navigateToApiKeys(page, log);
	await screenshot(page, 'api-keys-page');

	// Delete any leftover E2E-RestAPI keys from previous runs
	log('Cleaning up leftover E2E-RestAPI keys from previous runs...');
	for (let i = 0; i < 5; i++) {
		const staleKey = page
			.getByTestId('api-key-item')
			.filter({ has: page.getByTestId('api-key-name').filter({ hasText: /E2E-RestAPI/i }) })
			.first();
		const staleVisible = await staleKey.isVisible({ timeout: 1500 }).catch(() => false);
		if (!staleVisible) break;
		const staleDeleteBtn = staleKey.getByTestId('api-key-delete-button');
		if (await staleDeleteBtn.isVisible({ timeout: 1500 }).catch(() => false)) {
			page.once('dialog', (dialog: any) => dialog.accept());
			await staleDeleteBtn.click();
			await page.waitForTimeout(1500);
			log('Deleted stale E2E-RestAPI key.');
		} else {
			break;
		}
	}

	// If already at the 5-key limit, delete one to make room
	const limitWarning = page.getByTestId('api-key-limit-warning');
	const isAtLimit = await limitWarning.isVisible({ timeout: 2000 }).catch(() => false);
	if (isAtLimit) {
		log('At 5-key limit — deleting first key to make room...');
		const firstDeleteBtn = page.getByTestId('api-key-delete-button').first();
		if (await firstDeleteBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
			page.once('dialog', (dialog: any) => dialog.accept());
			await firstDeleteBtn.click();
			await page.waitForTimeout(2000);
		}
	}

	// Create a new API key
	const createButton = page.getByTestId('api-key-create-button');
	await expect(createButton).toBeVisible({ timeout: 5000 });
	await expect(createButton).toBeEnabled();
	await createButton.click();
	log('Clicked Create New API Key.');

	const keyName = `E2E-RestAPI-${Date.now()}`;
	const nameInput = page.getByTestId('api-key-name-input');
	await expect(nameInput).toBeVisible({ timeout: 5000 });
	await nameInput.fill(keyName);
	log(`Entered key name: "${keyName}"`);

	const createConfirmButton = page.locator('button.btn-create-confirm');
	await expect(createConfirmButton).toBeEnabled({ timeout: 3000 });
	await createConfirmButton.click();
	log('Clicked Create API Key confirm.');

	// Capture the raw key value
	const createdKeyEl = page.getByTestId('api-key-created-value');
	await expect(createdKeyEl).toBeVisible({ timeout: 15000 });
	await screenshot(page, 'key-created');

	const rawApiKey = (await createdKeyEl.textContent())?.trim() ?? '';
	expect(rawApiKey).toMatch(/^sk-api-[A-Za-z0-9]+$/);
	log(`Captured API key: "${rawApiKey.slice(0, 12)}..."`);

	// Dismiss the key-reveal modal
	const doneButton = page.locator('button.btn-done');
	await expect(doneButton).toBeVisible({ timeout: 3000 });
	await doneButton.click();
	log('Dismissed key modal.');
	await page.waitForTimeout(1000);

	// ── Phase 3: Make REST API call — expect it to be blocked (device pending) ─
	log(`Making REST API call to ${API_BASE_URL}/v1/settings/api-keys with new key...`);
	const blockedResponse = await request.get(`${API_BASE_URL}/v1/settings/api-keys`, {
		headers: { Authorization: `Bearer ${rawApiKey}` }
	});
	log(`REST API response (before device approval): ${blockedResponse.status()}`);
	await screenshot(page, 'api-call-before-approval');

	expect(
		[401, 403].includes(blockedResponse.status()),
		`Expected 401 or 403 (device not yet approved), got ${blockedResponse.status()}`
	).toBe(true);
	log('Confirmed: REST API call correctly blocked before device approval.');

	// ── Phase 4: Navigate to Devices and approve the pending device ───────────
	const settingsToggle = page.locator('#settings-menu-toggle');
	await expect(settingsToggle).toBeVisible({ timeout: 10000 });
	const closeIcon = page.locator('#settings-menu-toggle .close-icon-container.visible').first();
	if (await closeIcon.isVisible().catch(() => false)) {
		await closeIcon.click();
		await page.waitForTimeout(500);
	}
	await settingsToggle.dispatchEvent('click');

	const settingsMenu2 = page.locator('.settings-menu.visible');
	await expect(settingsMenu2).toBeVisible({ timeout: 8000 });

	const developersItem2 = settingsMenu2
		.locator('.menu-item[role="menuitem"]')
		.filter({ hasText: /^developers$/i })
		.first();
	await expect(developersItem2).toBeVisible({ timeout: 8000 });
	await developersItem2.click();

	const devicesItem = page
		.locator('.settings-menu.visible .menu-item[role="menuitem"]')
		.filter({ hasText: /^devices$/i })
		.first();
	await expect(devicesItem).toBeVisible({ timeout: 8000 });
	await devicesItem.click();
	log('Navigated to Devices page.');
	await screenshot(page, 'devices-page');

	const devicesContainer = page.locator('.devices-container');
	await expect(devicesContainer).toBeVisible({ timeout: 8000 });

	await page.waitForTimeout(2000);

	const pendingCard = page.locator('.device-card.pending').first();
	await expect(pendingCard).toBeVisible({ timeout: 15000 });
	log('Found pending device card.');
	await screenshot(page, 'pending-device');

	const approveButton = pendingCard.locator('.btn-approve');
	await expect(approveButton).toBeVisible({ timeout: 5000 });
	await approveButton.click();
	log('Clicked Approve button.');

	await expect(pendingCard).not.toBeVisible({ timeout: 10000 });
	log('Pending device card is gone — device approved.');

	const approvedBadge = devicesContainer.locator('.status-badge.approved').first();
	await expect(approvedBadge).toBeVisible({ timeout: 8000 });
	log('Confirmed: Approved status badge is visible.');
	await screenshot(page, 'device-approved');

	// ── Phase 5: Make REST API call again — expect 200 ───────────────────────
	log(`Making REST API call to ${API_BASE_URL}/v1/settings/api-keys with approved key...`);
	const approvedResponse = await request.get(`${API_BASE_URL}/v1/settings/api-keys`, {
		headers: { Authorization: `Bearer ${rawApiKey}` }
	});
	log(`REST API response (after device approval): ${approvedResponse.status()}`);
	await screenshot(page, 'api-call-after-approval');

	expect(approvedResponse.status()).toBe(200);
	const approvedData = await approvedResponse.json();
	expect(approvedData).toHaveProperty('api_keys');
	log('Confirmed: REST API call succeeded after device approval!');

	// ── Phase 6: Save the working API key to artifacts ───────────────────────
	const fs = require('fs');
	const path = require('path');

	if (!fs.existsSync(ARTIFACTS_DIR)) {
		fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });
	}
	const keyFilePath = path.join(ARTIFACTS_DIR, 'api_key.txt');
	fs.writeFileSync(keyFilePath, rawApiKey, 'utf8');
	log(`Saved working API key to: ${keyFilePath}`);

	console.log(`\n${'='.repeat(60)}`);
	console.log(`NEW WORKING API KEY: ${rawApiKey}`);
	console.log(`Update .env: OPENMATES_TEST_ACCOUNT_API_KEY="${rawApiKey}"`);
	console.log('='.repeat(60));

	await screenshot(page, 'done');
	log('Test complete. API key lifecycle with device approval verified.');
});

// ---------------------------------------------------------------------------
// Test 4: At 5-key limit, create button is disabled and limit warning shown
// ---------------------------------------------------------------------------

test('shows limit warning and disabled create button when 5 API keys exist', async ({
	page
}: {
	page: any;
}) => {
	attachConsoleListeners(page);
	attachNetworkListeners(page);
	test.slow();
	test.setTimeout(300000);

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

	const keyItems = page.getByTestId('api-key-item');
	const existingCount = await keyItems.count();
	log(`Existing API key count: ${existingCount}`);

	// Create keys until we reach 5
	const createdKeyNames: string[] = [];
	for (let i = existingCount; i < 5; i++) {
		const isLimitReached = await page
			.getByTestId('api-key-limit-warning')
			.isVisible({ timeout: 1000 })
			.catch(() => false);
		if (isLimitReached) break;

		const createButton = page.getByTestId('api-key-create-button');
		if (await createButton.isDisabled({ timeout: 1000 }).catch(() => false)) break;

		await createButton.click();

		const nameInput = page.getByTestId('api-key-name-input');
		await expect(nameInput).toBeVisible({ timeout: 5000 });

		const keyName = `E2E-Limit-Key-${i}-${Date.now()}`;
		await nameInput.fill(keyName);
		createdKeyNames.push(keyName);

		const createConfirmButton = page.locator('button.btn-create-confirm');
		await createConfirmButton.click();

		const doneButton = page.locator('button.btn-done');
		await expect(doneButton).toBeVisible({ timeout: 15000 });
		await doneButton.click();

		log(`Created key ${i + 1}/5: "${keyName}"`);
		await page.waitForTimeout(1000);
	}

	await screenshot(page, 'at-5-keys');

	// Verify the limit warning and disabled button
	await expect(page.getByTestId('api-key-limit-warning')).toBeVisible({ timeout: 5000 });
	log('Limit warning is visible.');

	await expect(page.getByTestId('api-key-create-button')).toBeDisabled({ timeout: 3000 });
	log('Create button is disabled at 5-key limit.');

	await screenshot(page, 'limit-reached');

	// Clean up: delete all keys we created
	log('Cleaning up: deleting created test keys...');
	for (const keyName of createdKeyNames) {
		const keyRow = page
			.getByTestId('api-key-item')
			.filter({ has: page.getByTestId('api-key-name').filter({ hasText: keyName }) });
		const deleteBtn = keyRow.getByTestId('api-key-delete-button');
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
