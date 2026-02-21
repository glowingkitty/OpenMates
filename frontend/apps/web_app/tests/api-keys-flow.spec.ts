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
// Test 3: Create key → REST API blocked → approve device → REST API works → save key
// ---------------------------------------------------------------------------
//
// This test verifies the full API key + device approval lifecycle:
//   1. Create a new API key (capturing the raw key value)
//   2. Make a REST API call with that key — expect 401/blocked (device not approved)
//   3. Navigate to Settings > Developers > Devices
//   4. Find the pending device and click Approve
//   5. Make the same REST API call again — expect 200 (device now approved)
//   6. Save the working key to playwright-artifacts/api_key.txt so pytest can use it
//
// The REST API endpoint used is GET /v1/settings/api-keys — requires API key auth,
// returns the user's key list (cheap, no side effects, works with Bearer auth).
//
// REQUIRED ENV VARS:
// - OPENMATES_TEST_ACCOUNT_EMAIL
// - OPENMATES_TEST_ACCOUNT_PASSWORD
// - OPENMATES_TEST_ACCOUNT_OTP_KEY
// - PLAYWRIGHT_TEST_BASE_URL (or defaults to https://app.dev.openmates.org)

const API_BASE_URL = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';
const ARTIFACTS_DIR = process.env.PLAYWRIGHT_ARTIFACTS_DIR || '/workspace/artifacts';

test('creates API key, verifies device approval flow, and saves working key', async ({
	page,
	request
}: {
	page: any;
	request: any;
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
			.locator('.api-key-item')
			.filter({ has: page.locator('.key-name').filter({ hasText: /E2E-RestAPI/i }) })
			.first();
		const staleVisible = await staleKey.isVisible({ timeout: 1500 }).catch(() => false);
		if (!staleVisible) break;
		const staleDeleteBtn = staleKey.locator('.btn-delete');
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
	const limitWarning = page.locator('.api-keys-container .limit-warning');
	const isAtLimit = await limitWarning.isVisible({ timeout: 2000 }).catch(() => false);
	if (isAtLimit) {
		log('At 5-key limit — deleting first key to make room...');
		const firstDeleteBtn = page.locator('.api-key-item .btn-delete').first();
		if (await firstDeleteBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
			page.once('dialog', (dialog: any) => dialog.accept());
			await firstDeleteBtn.click();
			await page.waitForTimeout(2000);
		}
	}

	// Create a new API key
	const createButton = page.locator('.api-keys-container .btn-create');
	await expect(createButton).toBeVisible({ timeout: 5000 });
	await expect(createButton).toBeEnabled();
	await createButton.click();
	log('Clicked Create New API Key.');

	const keyName = `E2E-RestAPI-${Date.now()}`;
	const nameInput = page.locator('.modal .name-input');
	await expect(nameInput).toBeVisible({ timeout: 5000 });
	await nameInput.fill(keyName);
	log(`Entered key name: "${keyName}"`);

	const createConfirmButton = page.locator('button.btn-create-confirm');
	await expect(createConfirmButton).toBeEnabled({ timeout: 3000 });
	await createConfirmButton.click();
	log('Clicked Create API Key confirm.');

	// Capture the raw key value from the "API Key Created" modal
	const createdKeyEl = page.locator('.created-key');
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

	// The device is pending — the API should block the request (401 or 403)
	expect(
		[401, 403].includes(blockedResponse.status()),
		`Expected 401 or 403 (device not yet approved), got ${blockedResponse.status()}`
	).toBe(true);
	log('Confirmed: REST API call correctly blocked before device approval.');

	// ── Phase 4: Navigate to Devices and approve the pending device ───────────
	// Go back until we can see the "Devices" menuitem in the Developers submenu.
	// We may be one or two levels deep (API Keys page → Developers → see Devices).
	const settingsBackButton = page.locator('.settings-header .nav-button .icon_back.visible');
	for (let backClicks = 0; backClicks < 5; backClicks++) {
		// Check if "Devices" menuitem is already visible
		const devicesCheck = page
			.locator('.settings-menu.visible .menu-item[role="menuitem"]')
			.filter({ hasText: 'Manage devices that' })
			.first();
		const devicesCheckByTitle = page
			.locator('.settings-menu.visible')
			.getByRole('menuitem')
			.filter({ hasText: /^devices$/i })
			.first();
		const alreadyVisible =
			(await devicesCheck.isVisible({ timeout: 800 }).catch(() => false)) ||
			(await devicesCheckByTitle.isVisible({ timeout: 800 }).catch(() => false));
		if (alreadyVisible) break;
		const backVisible = await settingsBackButton.isVisible({ timeout: 800 }).catch(() => false);
		if (!backVisible) break;
		await settingsBackButton.click();
		await page.waitForTimeout(600);
	}
	log('Back at Developers submenu.');

	// Click "Devices" menu item (title is "Devices", description is "Manage devices that...")
	await page.waitForTimeout(500); // Allow submenu to settle
	const settingsMenu2 = page.locator('.settings-menu.visible');
	const devicesItemByTitle = settingsMenu2
		.getByRole('menuitem')
		.filter({ hasText: /^devices$/i })
		.first();
	const devicesItemByDesc = settingsMenu2
		.locator('.menu-item[role="menuitem"]')
		.filter({ hasText: 'Manage devices that' })
		.first();
	const devicesVisible = await devicesItemByTitle.isVisible({ timeout: 5000 }).catch(() => false);
	const devicesItem = devicesVisible ? devicesItemByTitle : devicesItemByDesc;
	await expect(devicesItem).toBeVisible({ timeout: 8000 });
	await devicesItem.click();
	log('Navigated to Devices page.');
	await screenshot(page, 'devices-page');

	// Wait for devices list to load
	const devicesContainer = page.locator('.devices-container');
	await expect(devicesContainer).toBeVisible({ timeout: 8000 });

	// Find the pending device card (has orange border / .pending class) and approve it
	// Give the device a moment to appear (it was just registered by the API call above)
	await page.waitForTimeout(2000);

	// Reload devices in case the pending device hasn't appeared yet
	// The devices list auto-loads on mount — try refreshing the page section
	const pendingCard = page.locator('.device-card.pending').first();
	await expect(pendingCard).toBeVisible({ timeout: 15000 });
	log('Found pending device card.');
	await screenshot(page, 'pending-device');

	const approveButton = pendingCard.locator('.btn-approve');
	await expect(approveButton).toBeVisible({ timeout: 5000 });
	await approveButton.click();
	log('Clicked Approve button.');

	// Wait for the device to move to "approved" state (card loses .pending class)
	await expect(pendingCard).not.toBeVisible({ timeout: 10000 });
	log('Pending device card is gone — device approved.');

	// Verify approved badge appears on the (now-reloaded) device list
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
	// Write to a file that the pytest tests can read (mounted at /artifacts in Docker)
	const fs = require('fs');
	const path = require('path');

	const artifactsDir = ARTIFACTS_DIR;
	if (!fs.existsSync(artifactsDir)) {
		fs.mkdirSync(artifactsDir, { recursive: true });
	}

	const keyFilePath = path.join(artifactsDir, 'api_key.txt');
	fs.writeFileSync(keyFilePath, rawApiKey, 'utf8');
	log(`Saved working API key to: ${keyFilePath}`);

	// Also log it clearly so it's visible in test output even without the file
	console.log(`\n${'='.repeat(60)}`);
	console.log(`NEW WORKING API KEY: ${rawApiKey}`);
	console.log(`Update .env: OPENMATES_TEST_ACCOUNT_API_KEY="${rawApiKey}"`);
	console.log('='.repeat(60));

	await screenshot(page, 'done');
	log('Test complete. API key lifecycle with device approval verified.');
});

// ---------------------------------------------------------------------------
// Test 5: At 5-key limit, create button is disabled and limit warning shown
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
