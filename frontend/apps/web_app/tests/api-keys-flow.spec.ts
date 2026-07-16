/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * API Keys Flow Tests
 *
 * Tests the developer API key management in Settings > Developers > API Keys:
 * - Create an API key from the create sub-settings page, verify the format,
 *   confirm done, verify it appears in the list, open its detail sub-settings
 *   page, then revoke it.
 * - Verify the create button is disabled and a warning appears at 5-key limit.
 * - Verify the create button is disabled when no name is entered.
 *
 * Selectors: data-testid attributes (stable, Rule 11).
 * Console monitoring: shared console-monitor.ts (Rule 10).
 *
 * REQUIRED ENV VARS:
 * - Isolated slot 20 credentials, routed by scripts/run_tests.py.
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
	getIsolatedTestAccount
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getIsolatedTestAccount(
	'api-keys-flow.spec.ts'
);
const E2E_KEY_NAME_PATTERN = /(E2E-Test-Key|E2E-RestAPI|E2E-Limit-Key)/i;

test.describe.configure({ mode: 'serial' });

// ─── Shared login helper ─────────────────────────────────────────────────────

// ─── Navigate to API Keys settings page ─────────────────────────────────────

/**
 * Navigate to Settings > Developers > API Keys.
 * Returns when the API Keys settings route is active.
 */
async function ensureSettingsMenuOpen(page: any, logCheckpoint: (msg: string) => void): Promise<any> {
	const settingsMenu = page.getByTestId('settings-menu');
	if (!(await settingsMenu.isVisible({ timeout: 1000 }).catch(() => false))) {
		const openSettingsButton = page.getByRole('button', { name: /open settings menu/i }).first();
		await expect(openSettingsButton).toBeVisible({ timeout: 10000 });
		await openSettingsButton.click();
		logCheckpoint('Opened settings menu.');
	}
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });

	for (let i = 0; i < 5; i++) {
		const activeView = await settingsMenu.getAttribute('data-active-view');
		if (activeView === 'developers/api-keys') {
			return settingsMenu;
		}
		if (!activeView || activeView === 'main') {
			return settingsMenu;
		}

		const bannerBackButton = page.getByTestId('banner-back-button').first();
		const backButton = (await bannerBackButton.isVisible({ timeout: 1000 }).catch(() => false))
			? bannerBackButton
			: page.locator('#settings-back-button');
		await expect(backButton).toBeVisible({ timeout: 5000 });
		await backButton.click();
		logCheckpoint('Returned to root settings menu.');
		await expect(settingsMenu).toHaveAttribute('data-active-view', /^(main|developers)$/i, { timeout: 5000 });
	}

	await expect(settingsMenu).toHaveAttribute('data-active-view', 'main');
	return settingsMenu;
}

async function navigateToApiKeys(page: any, logCheckpoint: (msg: string) => void): Promise<void> {
	const existingSettingsMenu = page.getByTestId('settings-menu');
	if (await existingSettingsMenu.isVisible({ timeout: 1000 }).catch(() => false)) {
		const activeView = await existingSettingsMenu.getAttribute('data-active-view');
		if (activeView === 'developers/api-keys') {
			await expect(page.getByTestId('api-key-create-button')).toBeVisible({ timeout: 15000 });
			logCheckpoint('API Keys page already loaded.');
			return;
		}
	}

	const settingsMenu = await ensureSettingsMenuOpen(page, logCheckpoint);
	const activeView = await settingsMenu.getAttribute('data-active-view');
	if (activeView === 'developers/api-keys') {
		await expect(page.getByTestId('api-key-create-button')).toBeVisible({ timeout: 15000 });
		logCheckpoint('API Keys page already loaded.');
		return;
	}

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
		.getByRole('menuitem')
		.filter({ hasText: 'Create and manage API keys' })
		.first();
	const apiKeysVisible = await apiKeysItem.isVisible({ timeout: 5000 }).catch(() => false);
	const targetItem = apiKeysVisible ? apiKeysItem : apiKeysItemFallback;
	await expect(targetItem).toBeVisible({ timeout: 10000 });
	await targetItem.click();
	logCheckpoint('Navigated to API Keys.');

	await expect(settingsMenu).toHaveAttribute('data-active-view', 'developers/api-keys', {
		timeout: 15000
	});
	await expect(page.getByTestId('api-key-create-button')).toBeVisible({ timeout: 15000 });
	logCheckpoint('API Keys page loaded.');
}

async function ensureDevelopersSettingsOpen(
	page: any,
	logCheckpoint: (msg: string) => void
): Promise<any> {
	const settingsMenu = page.getByTestId('settings-menu');
	if (!(await settingsMenu.isVisible({ timeout: 1000 }).catch(() => false))) {
		const openSettingsButton = page.getByRole('button', { name: /open settings menu/i }).first();
		await expect(openSettingsButton).toBeVisible({ timeout: 10000 });
		await openSettingsButton.click();
		logCheckpoint('Opened settings menu.');
	}
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });

	for (let i = 0; i < 5; i++) {
		const activeView = await settingsMenu.getAttribute('data-active-view');
		if (activeView === 'developers') {
			return settingsMenu;
		}
		if (!activeView || activeView === 'main') {
			break;
		}

		const bannerBackButton = page.getByTestId('banner-back-button').first();
		const backButton = (await bannerBackButton.isVisible({ timeout: 1000 }).catch(() => false))
			? bannerBackButton
			: page.locator('#settings-back-button');
		await expect(backButton).toBeVisible({ timeout: 5000 });
		await backButton.click();
		logCheckpoint('Returned toward Developers settings menu.');
		await expect(settingsMenu).toHaveAttribute('data-active-view', /^(main|developers)$/i, {
			timeout: 5000
		});
	}

	const developersItem = settingsMenu
		.getByTestId('menu-item')
		.filter({ hasText: /developers/i })
		.first();
	await developersItem.scrollIntoViewIfNeeded({ timeout: 8000 });
	await expect(developersItem).toBeVisible({ timeout: 8000 });
	await developersItem.click({ timeout: 8000 });
	logCheckpoint('Navigated to Developers.');
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'developers', { timeout: 8000 });
	return settingsMenu;
}

async function navigateToDevices(page: any, logCheckpoint: (msg: string) => void): Promise<void> {
	const settingsMenu = await ensureDevelopersSettingsOpen(page, logCheckpoint);

	const devicesItem = settingsMenu
		.getByTestId('menu-item')
		.filter({ hasText: /devices/i })
		.first();
	await devicesItem.scrollIntoViewIfNeeded({ timeout: 8000 });
	await expect(devicesItem).toBeVisible({ timeout: 8000 });
	await devicesItem.click({ timeout: 8000 });
	logCheckpoint('Navigated to Devices page.');

	await expect(page.getByTestId('devices-container')).toBeVisible({ timeout: 8000 });
}

async function completeDefaultApiKeyGuidedFlow(
	page: any,
	logCheckpoint: (msg: string) => void
): Promise<void> {
	const createConfirmButton = page.getByTestId('api-key-create-confirm');
	await expect(page.getByTestId('api-key-full-access-toggle')).toBeVisible({ timeout: 3000 });
	await expect(page.getByText(/full access can read encrypted account metadata/i)).toBeVisible({
		timeout: 3000
	});
	await expect(createConfirmButton).toBeEnabled({ timeout: 3000 });
	await createConfirmButton.click();
	logCheckpoint('Clicked Create API Key confirm from create sub-settings page.');
}

async function openApiKeyDetailsByName(
	page: any,
	keyName: string | RegExp,
	log: (msg: string) => void
): Promise<any> {
	const keyRow = page.getByTestId('api-key-item').filter({ hasText: keyName }).first();
	await expect(keyRow, `Expected API key row ${keyName.toString()} to exist.`).toBeVisible({
		timeout: 10000
	});
	await keyRow.click();
	await expect(page.getByTestId('settings-menu')).toHaveAttribute(
		'data-active-view',
		/developers\/api-keys\/.+/,
		{ timeout: 10000 }
	);
	log(`Opened API key details for ${keyName.toString()}.`);
	return keyRow;
}

async function revokeCurrentApiKeyFromDetails(page: any, log: (msg: string) => void): Promise<void> {
	const revokeButton = page.getByTestId('api-key-delete-button');
	await expect(revokeButton).toBeVisible({ timeout: 5000 });
	await revokeButton.click();

	const confirmToggle = page.getByText(/i understand this key will stop working/i).first();
	await expect(confirmToggle).toBeVisible({ timeout: 5000 });
	await confirmToggle.click();
	await expect(revokeButton).toBeEnabled({ timeout: 3000 });
	await revokeButton.click();
	await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'developers/api-keys', {
		timeout: 10000
	});
	log('Revoked API key from detail page.');
}

async function deleteFirstE2EOwnedApiKey(page: any, log: (msg: string) => void): Promise<boolean> {
	const e2eKey = page
		.getByTestId('api-key-item')
		.filter({ hasText: E2E_KEY_NAME_PATTERN })
		.first();

	if (!(await e2eKey.isVisible({ timeout: 2000 }).catch(() => false))) {
		return false;
	}

	const keyName = await e2eKey.textContent().catch(() => 'E2E-owned key');
	await e2eKey.click();
	await revokeCurrentApiKeyFromDetails(page, log);
	await page.waitForTimeout(1000);
	log(`Deleted E2E-owned API key: ${keyName?.trim() || 'unknown'}`);
	return true;
}

async function freeApiKeySlotIfLimitReached(page: any, log: (msg: string) => void): Promise<void> {
	const limitWarning = page.getByText(/maximum number of API keys/i);
	const createButton = page.getByTestId('api-key-create-button');
	const isAtLimit =
		(await limitWarning.isVisible({ timeout: 2000 }).catch(() => false)) ||
		(await createButton.isDisabled({ timeout: 1000 }).catch(() => false));
	if (!isAtLimit) {
		return;
	}

	log('At 5-key limit — deleting E2E-owned keys only to free a slot...');
	for (let i = 0; i < 5; i++) {
		if (!(await deleteFirstE2EOwnedApiKey(page, log))) {
			break;
		}

		const stillAtLimit =
			(await limitWarning.isVisible({ timeout: 2000 }).catch(() => false)) ||
			(await createButton.isDisabled({ timeout: 1000 }).catch(() => false));
		if (!stillAtLimit) {
			return;
		}
	}

	throw new Error(
		'API key test account is at the 5-key limit and has no E2E-owned key safe to delete. ' +
			'Clean the isolated account manually.'
	);
}

// ---------------------------------------------------------------------------
// Test 1: Create → verify format → copy → done → verify in list → delete
// ---------------------------------------------------------------------------

test('creates an API key, verifies format, and deletes it', async ({ page }: { page: any }) => {
	attachConsoleListeners(page);
	attachNetworkListeners(page);
	test.slow();
	test.setTimeout(240000);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('API_KEYS_CREATE', { artifactsDirname: ARTIFACTS_DIR });
	const screenshot = createStepScreenshotter(log, { artifactsDirname: ARTIFACTS_DIR });
	await archiveExistingScreenshots(log, { artifactsDirname: ARTIFACTS_DIR });

	await loginToTestAccount(page, log, screenshot, { waitForEditor: false });
	await page.waitForTimeout(2000);

	await navigateToApiKeys(page, log);
	await screenshot(page, 'api-keys-page');

	await freeApiKeySlotIfLimitReached(page, log);

	// Open the create sub-settings page.
	const createButton = page.getByTestId('api-key-create-button');
	await expect(createButton).toBeVisible({ timeout: 5000 });
	await expect(createButton).toBeEnabled();
	await createButton.click();
	log('Clicked Create New API Key.');
	await expect(page.getByTestId('settings-menu')).toHaveAttribute(
		'data-active-view',
		'developers/api-keys/create',
		{ timeout: 10000 }
	);
	await screenshot(page, 'create-subsettings-open');

	// Fill in the key name
	const keyName = `E2E-Test-Key-${Date.now()}`;
	const nameInput = page.getByTestId('api-key-name-input');
	await expect(nameInput).toBeVisible({ timeout: 5000 });
	await nameInput.fill(keyName);
	log(`Entered key name: "${keyName}"`);
	await screenshot(page, 'key-name-entered');

	// Create with default full-access, unlimited-credit, never-expiring settings.
	await completeDefaultApiKeyGuidedFlow(page, log);

	// Wait for the one-time key reveal on the create sub-settings page.
	const createdKeyEl = page.getByTestId('api-key-created-value');
	await expect(createdKeyEl).toBeVisible({ timeout: 15000 });
	await screenshot(page, 'key-created');

	const createdKeyValue = (await createdKeyEl.textContent())?.trim() ?? '';
	log(`Created key: "${createdKeyValue}"`);

	// Verify the key format: sk-api-{alphanumeric}
	expect(createdKeyValue).toMatch(/^sk-api-[A-Za-z0-9]+$/);
	log('Key format validated: starts with sk-api-');

	// Click the Copy button
	const copyButton = page.getByRole('button', { name: /copy to clipboard/i }).first();
	await expect(copyButton).toBeVisible({ timeout: 3000 });
	await copyButton.click();
	log('Clicked Copy button.');

	// Click "I've copied the key" to return to the API keys list.
	const doneButton = page.getByTestId('api-key-done-button');
	await expect(doneButton).toBeVisible({ timeout: 3000 });
	await doneButton.click();
	await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'developers/api-keys', {
		timeout: 10000
	});
	log('Clicked done button.');

	// Verify the new key appears in the API keys list immediately after Done.
	const keyItems = page.getByTestId('api-key-item');
	await expect(async () => {
		const count = await keyItems.count();
		expect(count).toBeGreaterThan(0);
	}).toPass({ timeout: 20000 });

	const keyByName = page.getByTestId('api-key-item').filter({ hasText: keyName }).first();
	await expect(keyByName, `Expected optimistic API key row ${keyName} to exist.`).toBeVisible({ timeout: 5000 });
	await expect(keyByName).toContainText(/Full access/i);
	await expect(keyByName).toContainText(/Unlimited credits/i);
	log(`Key found by name "${keyName}" immediately. Total key items: ${await keyItems.count()}`);

	await screenshot(page, 'key-in-list');
	log('Key items visible in list after creation.');

	// Delete the key we just created
	await openApiKeyDetailsByName(page, keyName, log);
	await revokeCurrentApiKeyFromDetails(page, log);

	await expect(async () => {
		const keyByName2 = page.getByTestId('api-key-item').filter({ hasText: keyName }).first();
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

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('API_KEYS_EMPTY_NAME', { artifactsDirname: ARTIFACTS_DIR });
	const screenshot = createStepScreenshotter(log, { artifactsDirname: ARTIFACTS_DIR });
	await archiveExistingScreenshots(log, { artifactsDirname: ARTIFACTS_DIR });

	await loginToTestAccount(page, log, screenshot, { waitForEditor: false });
	await page.waitForTimeout(2000);

	await navigateToApiKeys(page, log);

	await freeApiKeySlotIfLimitReached(page, log);

	// Open the create sub-settings page.
	const createButton = page.getByTestId('api-key-create-button');
	await expect(createButton).toBeEnabled({ timeout: 8000 });
	await createButton.click();
	await expect(page.getByTestId('settings-menu')).toHaveAttribute(
		'data-active-view',
		'developers/api-keys/create',
		{ timeout: 10000 }
	);

	const nameInput = page.getByTestId('api-key-name-input');
	await expect(nameInput).toBeVisible({ timeout: 5000 });

	// Do NOT fill in any name — confirm button should be disabled
	const createConfirmButton = page.getByTestId('api-key-create-confirm');
	await expect(createConfirmButton).toBeDisabled({ timeout: 3000 });
	log('Confirmed: Create API Key button is disabled when name is empty.');
	await screenshot(page, 'empty-name-button-disabled');

	// Return to the API keys list by clicking Cancel.
	const cancelButton = page.getByTestId('api-key-cancel-button');
	await expect(cancelButton).toBeVisible({ timeout: 3000 });
	await cancelButton.click();
	await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'developers/api-keys', {
		timeout: 10000
	});

	log('Test complete.');
});

// ---------------------------------------------------------------------------
// Test 3: Create key → REST API blocked → approve device → REST API works → save key
// ---------------------------------------------------------------------------

const API_BASE_URL = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';

function resolveWritableArtifactsDir(): string {
	const configuredDir = process.env.PLAYWRIGHT_ARTIFACTS_DIR || path.resolve(process.cwd(), 'artifacts');

	try {
		fs.mkdirSync(configuredDir, { recursive: true });
		const probePath = path.join(configuredDir, `.write-test-${process.pid}-${Date.now()}`);
		fs.writeFileSync(probePath, 'ok');
		fs.unlinkSync(probePath);
		return configuredDir;
	} catch (error: any) {
		if (!['EACCES', 'EROFS'].includes(error?.code)) {
			throw error;
		}

		for (const base of ['/tmp', os.tmpdir(), process.cwd()]) {
			try {
				const fallbackDir = fs.mkdtempSync(path.join(base, 'openmates-api-keys-'));
				console.warn(
					`Configured artifacts directory is not writable (${configuredDir}); using temporary directory ${fallbackDir} instead.`
				);
				return fallbackDir;
			} catch {
				continue;
			}
		}

		throw error;
	}
}

const ARTIFACTS_DIR = resolveWritableArtifactsDir();

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

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('API_KEY_DEVICE_APPROVAL', { artifactsDirname: ARTIFACTS_DIR });
	const screenshot = createStepScreenshotter(log, { artifactsDirname: ARTIFACTS_DIR });
	await archiveExistingScreenshots(log, { artifactsDirname: ARTIFACTS_DIR });

	// ── Phase 1: Login ────────────────────────────────────────────────────────
	await loginToTestAccount(page, log, screenshot, { waitForEditor: false });
	await page.waitForTimeout(2000);

	// ── Phase 2: Navigate to API Keys and create a new key ───────────────────
	await navigateToApiKeys(page, log);
	await screenshot(page, 'api-keys-page');

	// Delete any leftover E2E-RestAPI keys from previous runs
	log('Cleaning up leftover E2E-RestAPI keys from previous runs...');
	for (let i = 0; i < 5; i++) {
		const staleKey = page
			.getByTestId('api-key-item')
			.filter({ hasText: /E2E-RestAPI/i })
			.first();
		const staleVisible = await staleKey.isVisible({ timeout: 1500 }).catch(() => false);
		if (!staleVisible) break;
		await staleKey.click();
		await revokeCurrentApiKeyFromDetails(page, log);
		await page.waitForTimeout(1000);
		log('Deleted stale E2E-RestAPI key.');
	}

	await freeApiKeySlotIfLimitReached(page, log);

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

	await completeDefaultApiKeyGuidedFlow(page, log);

	// Capture the raw key value
	const createdKeyEl = page.getByTestId('api-key-created-value');
	await expect(createdKeyEl).toBeVisible({ timeout: 15000 });
	await screenshot(page, 'key-created');

	const rawApiKey = (await createdKeyEl.textContent())?.trim() ?? '';
	expect(rawApiKey).toMatch(/^sk-api-[A-Za-z0-9]+$/);
	log(`Captured API key: "${rawApiKey.slice(0, 12)}..."`);

	// Leave the one-time key reveal and return to the list.
	const doneButton = page.getByTestId('api-key-done-button');
	await expect(doneButton).toBeVisible({ timeout: 3000 });
	await doneButton.click();
	await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'developers/api-keys', {
		timeout: 10000
	});
	log('Dismissed key reveal.');
	await page.waitForTimeout(1000);

	// ── Phase 3: Make API-key-authenticated SDK call — expect device-pending block ─
	const sdkChatsUrl = `${API_BASE_URL}/v1/sdk/chats?limit=1`;
	log(`Making SDK API call to ${sdkChatsUrl} with new key...`);
	const blockedResponse = await request.get(sdkChatsUrl, {
		headers: { Authorization: `Bearer ${rawApiKey}` }
	});
	log(`REST API response (before device approval): ${blockedResponse.status()}`);
	await screenshot(page, 'api-call-before-approval');

	expect(
		blockedResponse.status() === 403,
		`Expected 403 (device not yet approved), got ${blockedResponse.status()}`
	).toBe(true);
	log('Confirmed: REST API call correctly blocked before device approval.');

	// ── Phase 4: Navigate to Devices and approve the pending device ───────────
	await page.reload();
	await page.waitForLoadState('domcontentloaded');
	await navigateToApiKeys(page, log);
	const keyRowWithPendingDevice = page.getByTestId('api-key-item').filter({ hasText: keyName }).first();
	await expect(keyRowWithPendingDevice).toBeVisible({ timeout: 15000 });
	const confirmDeviceLink = page.getByTestId('api-key-confirm-device-link').first();
	if (await confirmDeviceLink.isVisible({ timeout: 5000 }).catch(() => false)) {
		await confirmDeviceLink.click();
		await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'developers/devices', {
			timeout: 10000
		});
		log('Opened Devices from API-key Confirm device quick link.');
	} else {
		await navigateToDevices(page, log);
		log('Opened Devices from Developers menu fallback.');
	}
	await screenshot(page, 'devices-page');

	const devicesContainer = page.getByTestId('devices-container');
	await expect(devicesContainer).toBeVisible({ timeout: 8000 });

	await page.waitForTimeout(2000);

	let pendingCard = page.locator('[data-testid="device-card"].pending').first();
	if (!(await pendingCard.isVisible({ timeout: 15000 }).catch(() => false))) {
		log('Pending device card not visible yet; reloading and reopening Devices.');
		await page.reload();
		await page.waitForLoadState('domcontentloaded');
		await navigateToDevices(page, log);
		pendingCard = page.locator('[data-testid="device-card"].pending').first();
		await expect(pendingCard).toBeVisible({ timeout: 30000 });
	}
	log('Found pending device card.');
	await screenshot(page, 'pending-device');

	const approveButton = pendingCard.getByTestId('device-approve-button');
	await expect(approveButton).toBeVisible({ timeout: 5000 });
	await approveButton.click();
	log('Clicked Approve button.');

	await expect(pendingCard).not.toBeVisible({ timeout: 10000 });
	log('Pending device card is gone — device approved.');

	const approvedBadge = devicesContainer.locator('[data-testid="status-badge"].approved').first();
	await expect(approvedBadge).toBeVisible({ timeout: 8000 });
	log('Confirmed: Approved status badge is visible.');
	await screenshot(page, 'device-approved');

	// ── Phase 5: Immediately retry SDK API call — expect approval cache to be clear ─
	log(`Immediately retrying SDK API call to ${sdkChatsUrl} with approved key...`);
	const approvedResponse = await request.get(sdkChatsUrl, {
		headers: { Authorization: `Bearer ${rawApiKey}` }
	});
	const approvedResponseBody = await approvedResponse.text();
	log(`REST API response (immediately after device approval): ${approvedResponse.status()}`);
	await screenshot(page, 'api-call-after-approval');

	expect(
		approvedResponse.status(),
		`Expected immediate retry after approval to pass, got ${approvedResponse.status()}: ${approvedResponseBody}`
	).toBe(200);
	const approvedData = JSON.parse(approvedResponseBody);
	expect(approvedData).toHaveProperty('chats');
	log('Confirmed: REST API call succeeded immediately after device approval.');

	// ── Phase 5b: Register and approve the stable CLI API-key device ───────────
	const cliDeviceHeaders = {
		Authorization: `Bearer ${rawApiKey}`,
		'User-Agent': `OpenMates CLI/0.1 (${os.platform()} ${os.release()})`,
		'X-OpenMates-SDK': 'cli',
		'X-OpenMates-Device-Identity': `cli:${os.platform()}:${os.arch()}`
	};
	log('Making CLI-style SDK API call with new key; expecting pending-device block...');
	const cliBlockedResponse = await request.get(sdkChatsUrl, { headers: cliDeviceHeaders });
	log(`CLI-style SDK API response (before device approval): ${cliBlockedResponse.status()}`);
	expect(
		cliBlockedResponse.status() === 403,
		`Expected 403 for CLI device before approval, got ${cliBlockedResponse.status()}`
	).toBe(true);

	await page.reload();
	await page.waitForLoadState('domcontentloaded');
	await navigateToDevices(page, log);
	await expect(devicesContainer).toBeVisible({ timeout: 8000 });
	await page.waitForTimeout(2000);

	let cliPendingCard = page.locator('[data-testid="device-card"].pending').first();
	if (!(await cliPendingCard.isVisible({ timeout: 15000 }).catch(() => false))) {
		log('CLI pending device card not visible yet; reloading and reopening Devices.');
		await page.reload();
		await page.waitForLoadState('domcontentloaded');
		await navigateToDevices(page, log);
		cliPendingCard = page.locator('[data-testid="device-card"].pending').first();
		await expect(cliPendingCard).toBeVisible({ timeout: 30000 });
	}
	await screenshot(page, 'cli-pending-device');
	const cliApproveButton = cliPendingCard.getByTestId('device-approve-button');
	await expect(cliApproveButton).toBeVisible({ timeout: 5000 });
	await cliApproveButton.click();
	await expect(cliPendingCard).not.toBeVisible({ timeout: 10000 });
	await screenshot(page, 'cli-device-approved');

	const cliApprovedResponse = await request.get(sdkChatsUrl, { headers: cliDeviceHeaders });
	log(`CLI-style SDK API response (after device approval): ${cliApprovedResponse.status()}`);
	expect(cliApprovedResponse.status()).toBe(200);
	const cliApprovedData = await cliApprovedResponse.json();
	expect(cliApprovedData).toHaveProperty('chats');
	log('Confirmed: CLI-style API key call succeeded after device approval!');

	// ── Phase 6: Save the working API key to artifacts ───────────────────────
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

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('API_KEYS_LIMIT', { artifactsDirname: ARTIFACTS_DIR });
	const screenshot = createStepScreenshotter(log, { artifactsDirname: ARTIFACTS_DIR });
	await archiveExistingScreenshots(log, { artifactsDirname: ARTIFACTS_DIR });

	await loginToTestAccount(page, log, screenshot, { waitForEditor: false });
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
			.getByText(/maximum number of API keys/i)
			.isVisible({ timeout: 1000 })
			.catch(() => false);
		if (isLimitReached) break;

		const createButton = page.getByTestId('api-key-create-button');
		if (await createButton.isDisabled({ timeout: 1000 }).catch(() => false)) break;

		await createButton.click();
		await expect(page.getByTestId('settings-menu')).toHaveAttribute(
			'data-active-view',
			'developers/api-keys/create',
			{ timeout: 10000 }
		);

		const nameInput = page.getByTestId('api-key-name-input');
		await expect(nameInput).toBeVisible({ timeout: 5000 });

		const keyName = `E2E-Limit-Key-${i}-${Date.now()}`;
		await nameInput.fill(keyName);
		createdKeyNames.push(keyName);

		await completeDefaultApiKeyGuidedFlow(page, log);

		const doneButton = page.getByTestId('api-key-done-button');
		await expect(doneButton).toBeVisible({ timeout: 15000 });
		await doneButton.click();
		await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'developers/api-keys', {
			timeout: 10000
		});

		log(`Created key ${i + 1}/5: "${keyName}"`);
		await page.waitForTimeout(1000);
	}

	await screenshot(page, 'at-5-keys');

	// Verify the limit warning and disabled button
	await expect(page.getByText(/maximum number of API keys/i)).toBeVisible({ timeout: 5000 });
	log('Limit warning is visible.');

	await expect(page.getByTestId('api-key-create-button')).toBeDisabled({ timeout: 3000 });
	log('Create button is disabled at 5-key limit.');

	await screenshot(page, 'limit-reached');

	// Clean up: delete all keys we created
	log('Cleaning up: deleting created test keys...');
	for (const keyName of createdKeyNames) {
		const keyRow = page.getByTestId('api-key-item').filter({ hasText: keyName }).first();
		if (await keyRow.isVisible({ timeout: 3000 }).catch(() => false)) {
			await openApiKeyDetailsByName(page, keyName, log);
			await revokeCurrentApiKeyFromDetails(page, log);
			await page.waitForTimeout(1000);
			log(`Deleted: "${keyName}"`);
		}
	}

	await screenshot(page, 'cleanup-done');
	log('Test complete.');
});
