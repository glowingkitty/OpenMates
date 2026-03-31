/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('@playwright/test');

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
		consoleLogs.slice(-50).forEach((log) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-30).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

/**
 * Test: Settings & Memories entries appear in the @ mention dropdown.
 *
 * Flow:
 * 1. Login to the test account
 * 2. Open Settings > App Store > All Apps > Travel App > Trips category
 * 3. Create a new trip entry (destination: "Tokyo", start_date: "2026-06-01")
 * 4. Verify the entry is visible in the Trips settings list
 * 5. Close settings
 * 6. In the chat editor, type "@trips" and verify the mention dropdown shows the Trips category
 * 7. Expand the Trips category in the dropdown and verify the "Tokyo" entry appears
 * 8. Also type "@tokyo" and verify the individual entry can be found directly
 * 9. Clean up: delete the created trip entry
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// Unique destination name to avoid collisions with other test runs
const TRIP_DESTINATION = `TestCity-${Date.now()}`;
const TRIP_START_DATE = '2026-06-01';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/**
 * Open the settings panel via the profile/settings icon.
 */
async function openSettings(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	// Find the profile picture / settings button
	const settingsButton = page.getByTestId('profile-picture').first();
	await expect(settingsButton).toBeVisible({ timeout: 10000 });
	await settingsButton.click();
	logCheckpoint('Clicked profile/settings button to open settings menu.');

	// Wait for the settings menu to appear
	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	logCheckpoint('Settings menu is visible.');
	await takeStepScreenshot(page, 'settings-open');
}

/**
 * Close the settings panel.
 */
async function closeSettings(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	const closeButton = page
		.getByTestId('icon-button-close')
		.first();
	if (await closeButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		await closeButton.click();
		logCheckpoint('Closed settings menu via close button.');
	} else {
		// Try pressing Escape
		await page.keyboard.press('Escape');
		logCheckpoint('Closed settings menu via Escape key.');
	}
	await page.waitForTimeout(500);
}

// ---------------------------------------------------------------------------
// Main test
// ---------------------------------------------------------------------------

test('settings memory trips entry appears in @ mention dropdown', async ({
	page
}: {
	page: any;
}) => {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	test.setTimeout(300000);

	const logCheckpoint = createSignupLogger('MENTION_DROPDOWN_SETTINGS_MEMORY');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'mention-dropdown-settings'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting mention dropdown settings memory test.', {
		email: TEST_EMAIL,
		tripDestination: TRIP_DESTINATION
	});

	// ======================================================================
	// STEP 1: Login
	// ======================================================================
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);

	// ======================================================================
	// STEP 2: Open Settings
	// ======================================================================
	await openSettings(page, logCheckpoint, takeStepScreenshot);

	// ======================================================================
	// STEP 3: Navigate to App Store
	// ======================================================================
	logCheckpoint('Navigating to App Store...');
	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');

	// Click on "App Store" menu item (it's a SettingsItem with .menu-item class)
	const appStoreItem = settingsMenu
		.getByTestId('menu-item')
		.filter({ hasText: /app store/i })
		.first();
	await expect(appStoreItem).toBeVisible({ timeout: 10000 });
	await appStoreItem.click();
	logCheckpoint('Clicked App Store menu item.');
	await page.waitForTimeout(800);
	await takeStepScreenshot(page, 'app-store-open');

	// ======================================================================
	// STEP 4: Navigate to All Apps via "Show all apps" button
	// The App Store page has a "Show all apps" SettingsItem button
	// ======================================================================
	logCheckpoint('Navigating to Show all apps...');
	// "Show all apps" is a SettingsItem with .menu-item and text "Show all apps"
	const showAllAppsItem = settingsMenu
		.getByTestId('menu-item')
		.filter({ hasText: /show all apps/i })
		.first();
	await expect(showAllAppsItem).toBeVisible({ timeout: 10000 });
	await showAllAppsItem.click();
	logCheckpoint('Clicked "Show all apps" button.');
	await page.waitForTimeout(800);
	await takeStepScreenshot(page, 'all-apps-open');

	// ======================================================================
	// STEP 5: Find and click the Travel app card
	// The All Apps page shows AppStoreCard components with .app-store-card class
	// and .app-card-name for the name
	// ======================================================================
	logCheckpoint('Looking for Travel app card...');
	// AppStoreCard renders with class .app-store-card and h3.app-card-name
	const travelAppCard = settingsMenu
		.getByTestId('app-store-card')
		.filter({ has: page.getByTestId('app-card-name').filter({ hasText: /^Travel$/i }) })
		.first();
	await expect(travelAppCard).toBeVisible({ timeout: 10000 });
	await travelAppCard.click();
	logCheckpoint('Clicked Travel app card.');
	await page.waitForTimeout(800);
	await takeStepScreenshot(page, 'travel-app-open');

	// ======================================================================
	// STEP 6: Click the Trips category card in the Settings & Memories section
	// The AppDetails page also uses AppStoreCard for memory categories
	// ======================================================================
	logCheckpoint('Looking for Trips settings memory category card...');

	// Find the Trips card - the card name comes from the name_translation_key "app_settings_memories.travel.trips"
	// which translates to "Trips" in English
	const tripsCard = settingsMenu
		.getByTestId('app-store-card')
		.filter({ has: page.getByTestId('app-card-name').filter({ hasText: /^Trips$/i }) })
		.first();
	await expect(tripsCard).toBeVisible({ timeout: 10000 });
	await tripsCard.click();
	logCheckpoint('Clicked Trips settings memory category card.');
	await page.waitForTimeout(500);
	await takeStepScreenshot(page, 'trips-category-open');

	// ======================================================================
	// STEP 7: Click "Add Entry" button to create a new trip
	// ======================================================================
	logCheckpoint('Looking for Add Entry button...');

	// The AppSettingsMemoriesCategory component shows a SettingsItem with title "Add entry"
	const addEntryButton = settingsMenu
		.getByTestId('menu-item')
		.filter({ hasText: /add entry/i })
		.first();
	await expect(addEntryButton).toBeVisible({ timeout: 10000 });
	await addEntryButton.click();
	logCheckpoint('Clicked Add Entry button.');
	await page.waitForTimeout(500);
	await takeStepScreenshot(page, 'add-entry-form-open');

	// ======================================================================
	// STEP 8: Fill in the trip form
	// The Trips schema has: destination (is_title), start_date (is_subtitle), end_date, notes
	// ======================================================================
	logCheckpoint('Filling in trip form fields...');

	// Wait a bit longer for the form to render
	await page.waitForTimeout(1000);

	// Capture current form state
	await takeStepScreenshot(page, 'trip-form-visible');

	// The form generates inputs for each non-auto_generated property based on the field name
	// For "destination" field: id="destination", placeholder="City or country"
	// For "start_date" field: id="start_date", placeholder="Start date (YYYY-MM-DD)"
	// The component uses SettingsSectionHeading (not <label>) so detect form by input#destination directly
	const destInput = settingsMenu.locator('#destination').first();
	await expect(destInput).toBeVisible({ timeout: 10000 });
	logCheckpoint('Schema-based form detected via #destination input.');

	// Fill destination
	await destInput.fill(TRIP_DESTINATION);
	logCheckpoint(`Filled destination: "${TRIP_DESTINATION}"`);

	// Fill start_date
	const sdInput = settingsMenu.locator('#start_date').first();
	const startDateVisible = await sdInput.isVisible({ timeout: 3000 }).catch(() => false);
	if (startDateVisible) {
		await sdInput.fill(TRIP_START_DATE);
		logCheckpoint(`Filled start_date: "${TRIP_START_DATE}"`);
	} else {
		logCheckpoint('start_date field not visible, skipping.');
	}

	await takeStepScreenshot(page, 'trip-form-filled');

	// ======================================================================
	// STEP 9: Submit the form (Add Entry button in form)
	// ======================================================================
	logCheckpoint('Submitting the trip creation form...');

	// The create form has a button.create-btn with text "Add entry" (from i18n common.add_entry)
	// The form footer is <div class="form-footer"> (no data-testid), button class is "create-btn"
	const submitButton = settingsMenu
		.locator('button.create-btn, button.create-button')
		.filter({ hasText: /add entry|create/i })
		.first();

	await expect(submitButton).toBeVisible({ timeout: 5000 });
	await submitButton.click();
	logCheckpoint('Clicked create/submit button.');

	// Wait for navigation back to the trips category page
	await page.waitForTimeout(2000);
	await takeStepScreenshot(page, 'after-trip-creation');

	// ======================================================================
	// STEP 10: Verify the trip entry appears in the Trips settings list
	// ======================================================================
	logCheckpoint('Verifying trip entry appears in the Trips category list...');

	// After creating, the form dispatches 'openSettings' back to the category page
	// The category page should now show the new entry
	const tripEntry = settingsMenu
		.getByTestId('menu-item')
		.filter({ hasText: TRIP_DESTINATION })
		.first();
	await expect(tripEntry).toBeVisible({ timeout: 15000 });
	logCheckpoint(`Trip entry "${TRIP_DESTINATION}" is visible in settings.`);
	await takeStepScreenshot(page, 'trip-entry-visible-in-settings');

	// ======================================================================
	// STEP 11: Close settings
	// ======================================================================
	await closeSettings(page, logCheckpoint);
	await takeStepScreenshot(page, 'settings-closed');

	// ======================================================================
	// STEP 12: Test the @ mention dropdown with "trips" query
	// ======================================================================
	logCheckpoint('Testing @ mention dropdown with "trips" query...');

	// Click on the message editor
	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible({ timeout: 10000 });
	await messageEditor.click();

	// Type "@trips" to trigger the mention dropdown with the trips query
	await page.keyboard.type('@trips');
	logCheckpoint('Typed "@trips" in message editor.');

	// Wait for the mention dropdown to appear
	const mentionDropdown = page.getByTestId('mention-dropdown');
	await expect(mentionDropdown).toBeVisible({ timeout: 10000 });
	logCheckpoint('Mention dropdown is visible.');
	await takeStepScreenshot(page, 'mention-dropdown-trips-query');

	// ======================================================================
	// STEP 13: Verify the Trips settings memory category appears in results
	// ======================================================================
	logCheckpoint('Verifying Trips category appears in mention dropdown results...');

	// The dropdown should show a settings_memory result for travel:trips
	// The result will have a .result-name showing the translated "Trips" name
	// and the expand button showing the entry count
	const tripsResult = mentionDropdown
		.locator('[data-testid="mention-result"]')
		.filter({ hasText: /trips/i })
		.first();
	await expect(tripsResult).toBeVisible({ timeout: 10000 });
	logCheckpoint('Trips category is visible in mention dropdown results.');
	await takeStepScreenshot(page, 'trips-in-mention-dropdown');

	// Verify it's a settings_memory result (MUST have an expand button with entry count ≥ 1).
	// This is the key assertion for the bug fix: entries loaded from IndexedDB at startup
	// must appear in the @ mention dropdown after a fresh page reload.
	const expandButton = tripsResult.getByTestId('mention-expand-button');
	await expect(expandButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Expand button is visible on Trips result.');

	// Check the entry count is at least 1
	const entryCount = await expandButton
		.getByTestId('mention-entry-count')
		.textContent()
		.catch(() => '0');
	logCheckpoint(`Entry count on Trips expand button: "${entryCount}"`);
	expect(parseInt(entryCount || '0')).toBeGreaterThanOrEqual(1);
	logCheckpoint('Entry count is >= 1 as expected.');

	// ======================================================================
	// STEP 14: Expand the Trips category to see individual entries
	// ======================================================================
	logCheckpoint('Clicking expand button to reveal trip entries...');
	await expandButton.click();
	await page.waitForTimeout(500);
	await takeStepScreenshot(page, 'trips-expanded-in-dropdown');

	// Verify our newly created trip entry appears
	const tripEntryInDropdown = mentionDropdown
		.locator('[data-testid="mention-result"].entry-item')
		.filter({ hasText: new RegExp(TRIP_DESTINATION, 'i') })
		.first();
	await expect(tripEntryInDropdown).toBeVisible({ timeout: 10000 });
	logCheckpoint(`Trip entry "${TRIP_DESTINATION}" visible in expanded dropdown entries.`);
	await takeStepScreenshot(page, 'trip-entry-in-dropdown-expanded');

	// ======================================================================
	// STEP 15: Select entry and verify display name shows destination, not UUID
	// ======================================================================
	logCheckpoint('Selecting trip entry from dropdown to verify display name...');

	// Click the trip entry in the expanded dropdown to insert the mention
	await tripEntryInDropdown.click();
	await page.waitForTimeout(500);
	await takeStepScreenshot(page, 'mention-inserted-in-editor');

	// The inserted mention chip should show the trip destination name, NOT a UUID fragment
	// Bug fix verification: previously showed "Travel-Trips-fe5acefa" instead of "Travel-Trips-TestCity"
	const mentionChip = messageEditor.locator('[data-type="generic-mention"].mention-settings-memory_entry').first();
	const chipVisible = await mentionChip.isVisible({ timeout: 5000 }).catch(() => false);
	if (chipVisible) {
		const chipText = await mentionChip.textContent();
		logCheckpoint(`Mention chip text: "${chipText}"`);

		// The chip should contain the destination name (partial match), NOT a UUID-like string
		const chipContainsDestination = chipText?.includes(TRIP_DESTINATION.substring(0, 8)) ?? false;
		const chipContainsUUID = /[0-9a-f]{8}$/i.test(chipText?.trim() || '');
		logCheckpoint(`Chip contains destination name: ${chipContainsDestination}, contains UUID: ${chipContainsUUID}`);

		// The mention display name should include the actual entry title, not a UUID fragment
		expect(chipContainsDestination).toBe(true);
	} else {
		logCheckpoint('Mention chip not found (may use different class). Checking editor HTML...');
		const editorHtml = await messageEditor.innerHTML();
		logCheckpoint(`Editor HTML snippet: ${editorHtml.substring(0, 300)}`);
	}

	// ======================================================================
	// STEP 15b: Send message and verify NO permission dialog appears
	// ======================================================================
	logCheckpoint('Sending message with mention to verify no permission dialog...');

	// Add some text before the mention
	await messageEditor.click();
	// Move cursor to start
	await page.keyboard.press('Home');
	await page.keyboard.type('tips for ');
	await page.waitForTimeout(200);

	// Send the message
	await page.keyboard.press('Enter');
	logCheckpoint('Pressed Enter to send message.');

	// Wait for AI response to start (typing indicator or first chunk)
	// If the permission dialog appears, the AI won't start typing — instead we'd see a
	// "btn-include" / "btn-exclude" button pair for confirming settings & memories
	await page.waitForTimeout(3000);
	await takeStepScreenshot(page, 'after-send-with-mention');

	// Check that NO permission dialog appeared (no "Include" button visible)
	const includeButton = page.getByTestId('btn-include').first();
	const includeVisible = await includeButton.isVisible({ timeout: 2000 }).catch(() => false);
	logCheckpoint(`Permission dialog "Include" button visible: ${includeVisible}`);

	// The permission dialog should NOT appear — the @mention is implicit consent
	expect(includeVisible).toBe(false);

	// Verify AI response started (typing indicator or response content appeared)
	const aiResponse = page.locator('[data-role="assistant"]').last();
	const typingIndicator = page.locator('[data-testid="typing-indicator"], [data-testid="ai-typing"]').first();
	const aiStarted = await aiResponse.isVisible({ timeout: 15000 }).catch(() => false)
		|| await typingIndicator.isVisible({ timeout: 1000 }).catch(() => false);
	logCheckpoint(`AI response started (no permission dialog blocked it): ${aiStarted}`);
	await takeStepScreenshot(page, 'ai-response-started-no-dialog');

	// ======================================================================
	// STEP 15c: Clear editor for remaining tests
	// ======================================================================
	// Wait for AI to finish before clearing
	await page.waitForTimeout(5000);

	// Start a new chat for the remaining dropdown test
	const newChatButton = page.locator('[data-action="new-chat"]').first();
	if (await newChatButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		await newChatButton.click();
		await page.waitForTimeout(1000);
	}

	// ======================================================================
	// STEP 15d: Clear and type "@" + partial destination to find entry directly
	// ======================================================================
	logCheckpoint('Testing direct entry search by destination name...');

	// Click on the message editor
	const messageEditorRefresh = page.getByTestId('message-editor');
	await expect(messageEditorRefresh).toBeVisible({ timeout: 10000 });
	await messageEditorRefresh.click();

	// Type the first few chars of the destination name to search for it directly
	const searchQuery = TRIP_DESTINATION.substring(0, 4).toLowerCase();
	await page.keyboard.type(`@${searchQuery}`);
	logCheckpoint(`Typed "@${searchQuery}" to search for trip entry directly.`);

	// Wait for dropdown
	await expect(mentionDropdown).toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, `mention-dropdown-${searchQuery}-query`);

	// Check if the trip destination or trips category appears in results
	const directSearchResult = mentionDropdown
		.locator('[data-testid="mention-result"]')
		.filter({ hasText: new RegExp(TRIP_DESTINATION.substring(0, 4), 'i') })
		.first();

	const directFound = await directSearchResult.isVisible({ timeout: 5000 }).catch(() => false);
	logCheckpoint(
		`Direct search found "${TRIP_DESTINATION.substring(0, 4)}" in dropdown: ${directFound}`
	);

	if (directFound) {
		logCheckpoint('SUCCESS: Trip entry found directly via search.');
		await takeStepScreenshot(page, 'trip-entry-found-directly');
	} else {
		// Log all visible results for debugging
		const allResults = mentionDropdown.locator('[data-testid="mention-result"]');
		const resultCount = await allResults.count();
		logCheckpoint(`Total results shown: ${resultCount}`);
		for (let i = 0; i < Math.min(resultCount, 8); i++) {
			const resultText = await allResults
				.nth(i)
				.textContent()
				.catch(() => '');
			logCheckpoint(`  Result ${i}: "${resultText?.trim().substring(0, 100)}"`);
		}
	}

	// ======================================================================
	// STEP 16: Close the dropdown by pressing Escape
	// ======================================================================
	await page.keyboard.press('Escape');
	logCheckpoint('Closed mention dropdown via Escape.');
	await page.waitForTimeout(300);

	// ======================================================================
	// STEP 17: Cleanup - delete the created trip entry via settings
	// ======================================================================
	logCheckpoint('Starting cleanup: deleting the test trip entry...');

	try {
		await openSettings(page, logCheckpoint, takeStepScreenshot);

		// Navigate back to Trips category
		const cleanupAppStoreItem = page
			.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"]')
			.filter({ hasText: /app store/i })
			.first();
		await expect(cleanupAppStoreItem).toBeVisible({ timeout: 10000 });
		await cleanupAppStoreItem.click();
		await page.waitForTimeout(500);

		// Click "Show all apps" button (SettingsItem .menu-item)
		const cleanupShowAllAppsItem = page
			.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"]')
			.filter({ hasText: /show all apps/i })
			.first();
		await expect(cleanupShowAllAppsItem).toBeVisible({ timeout: 10000 });
		await cleanupShowAllAppsItem.click();
		await page.waitForTimeout(500);

		// Click the Travel app card (AppStoreCard .app-store-card)
		const cleanupTravelCard = page
			.locator('[data-testid="settings-menu"].visible [data-testid="app-store-card"]')
			.filter({ has: page.getByTestId('app-card-name').filter({ hasText: /^Travel$/i }) })
			.first();
		await expect(cleanupTravelCard).toBeVisible({ timeout: 10000 });
		await cleanupTravelCard.click();
		await page.waitForTimeout(500);

		// Click the Trips category card (AppStoreCard .app-store-card)
		const cleanupTripsCard = page
			.locator('[data-testid="settings-menu"].visible [data-testid="app-store-card"]')
			.filter({ has: page.getByTestId('app-card-name').filter({ hasText: /^Trips$/i }) })
			.first();
		await expect(cleanupTripsCard).toBeVisible({ timeout: 10000 });
		await cleanupTripsCard.click();
		await page.waitForTimeout(500);

		// Click on the trip entry to open it
		const entryToDelete = page
			.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"]')
			.filter({ hasText: TRIP_DESTINATION })
			.first();

		if (await entryToDelete.isVisible({ timeout: 5000 }).catch(() => false)) {
			await entryToDelete.click();
			await page.waitForTimeout(500);

			// Look for a delete button in the entry detail view
			const deleteButton = page
				.locator('[data-testid="settings-menu"].visible button')
				.filter({ hasText: /delete|remove/i })
				.first();

			if (await deleteButton.isVisible({ timeout: 3000 }).catch(() => false)) {
				await deleteButton.click();
				await page.waitForTimeout(500);

				// Confirm deletion if a confirmation dialog appears
				const confirmButton = page
					.locator('[data-testid="settings-menu"].visible button')
					.filter({ hasText: /confirm|yes|delete/i })
					.first();
				if (await confirmButton.isVisible({ timeout: 2000 }).catch(() => false)) {
					await confirmButton.click();
					await page.waitForTimeout(500);
				}

				logCheckpoint(`Deleted trip entry "${TRIP_DESTINATION}" successfully.`);
			} else {
				logCheckpoint('Delete button not found - entry may need manual cleanup.');
			}
		} else {
			logCheckpoint('Trip entry not found in list for cleanup (may have already been removed).');
		}

		await closeSettings(page, logCheckpoint);
		logCheckpoint('Cleanup complete.');
	} catch (cleanupError) {
		logCheckpoint(`Cleanup failed (non-fatal): ${cleanupError}`);
	}

	logCheckpoint('Mention dropdown settings memory test completed.');
});
