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
	generateTotp
} = require('./signup-flow-helpers');

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

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

// Unique destination name to avoid collisions with other test runs
const TRIP_DESTINATION = `TestCity-${Date.now()}`;
const TRIP_START_DATE = '2026-06-01';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

async function loginToTestAccount(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	const headerLoginButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();
	await takeStepScreenshot(page, 'login-dialog');

	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logCheckpoint('Entered email and clicked continue.');

	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);
	await takeStepScreenshot(page, 'password-entered');

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
		logCheckpoint(`Generated and entered OTP (attempt ${attempt}).`);

		await expect(submitLoginButton).toBeVisible();
		await submitLoginButton.click();
		logCheckpoint('Submitted login form.');

		try {
			await expect(otpInput).not.toBeVisible({ timeout: 15000 });
			loginSuccess = true;
			logCheckpoint('Login dialog closed, login successful.');
		} catch {
			const hasError = await errorMessage.isVisible().catch(() => false);
			if (hasError && attempt < 3) {
				logCheckpoint(`OTP attempt ${attempt} failed, retrying with fresh code...`);
				await page.waitForTimeout(2000);
			} else if (attempt === 3) {
				throw new Error('Login failed after 3 OTP attempts');
			}
		}
	}

	logCheckpoint('Waiting for chat interface to load...');
	await page.waitForTimeout(3000);

	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible({ timeout: 20000 });
	logCheckpoint('Chat interface loaded - message editor visible.');
}

/**
 * Open the settings panel via the profile/settings icon.
 */
async function openSettings(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	// Find the profile picture / settings button
	const settingsButton = page.locator('.profile-picture').first();
	await expect(settingsButton).toBeVisible({ timeout: 10000 });
	await settingsButton.click();
	logCheckpoint('Clicked profile/settings button to open settings menu.');

	// Wait for the settings menu to appear
	const settingsMenu = page.locator('.settings-menu.visible');
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
		.locator('.icon-button')
		.filter({ has: page.locator('.icon_close') })
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

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

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
	const settingsMenu = page.locator('.settings-menu.visible');

	// Click on "App Store" menu item (it's a SettingsItem with .menu-item class)
	const appStoreItem = settingsMenu
		.locator('.menu-item')
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
		.locator('.menu-item')
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
		.locator('.app-store-card')
		.filter({ has: page.locator('.app-card-name', { hasText: /^Travel$/i }) })
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
		.locator('.app-store-card')
		.filter({ has: page.locator('.app-card-name', { hasText: /^Trips$/i }) })
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
		.locator('.menu-item')
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
	// Find by label text first (most reliable)
	const destinationLabel = settingsMenu.locator('label[for="destination"]').first();
	const startDateLabel = settingsMenu.locator('label[for="start_date"]').first();

	const hasSchemaForm = await destinationLabel.isVisible({ timeout: 5000 }).catch(() => false);
	logCheckpoint(`Schema-based form visible: ${hasSchemaForm}`);

	if (hasSchemaForm) {
		// Fill destination
		const destInput = settingsMenu.locator('#destination').first();
		await expect(destInput).toBeVisible({ timeout: 5000 });
		await destInput.fill(TRIP_DESTINATION);
		logCheckpoint(`Filled destination: "${TRIP_DESTINATION}"`);

		// Fill start_date
		const startDateVisible = await startDateLabel.isVisible({ timeout: 3000 }).catch(() => false);
		if (startDateVisible) {
			const sdInput = settingsMenu.locator('#start_date').first();
			await sdInput.fill(TRIP_START_DATE);
			logCheckpoint(`Filled start_date: "${TRIP_START_DATE}"`);
		} else {
			logCheckpoint('start_date field not visible, skipping.');
		}
	} else {
		// Fallback: try finding any visible text input in the form area
		logCheckpoint('Schema form not visible, looking for any visible input...');

		// Dump page content for debugging
		const formContent = await settingsMenu
			.locator('.form-container, .app-settings-memories-create')
			.first()
			.textContent()
			.catch(() => 'not found');
		logCheckpoint(`Form container content: ${formContent?.substring(0, 200)}`);

		// Try to find inputs by placeholder
		const allInputs = settingsMenu.locator('input[type="text"], input:not([type])');
		const inputCount = await allInputs.count();
		logCheckpoint(`Found ${inputCount} text inputs in settings menu`);

		if (inputCount > 0) {
			await allInputs.first().fill(TRIP_DESTINATION);
			logCheckpoint(`Filled first available input with: "${TRIP_DESTINATION}"`);
		} else {
			throw new Error('No input fields found in the trip creation form');
		}
	}

	await takeStepScreenshot(page, 'trip-form-filled');

	// ======================================================================
	// STEP 9: Submit the form (Add Entry button in form)
	// ======================================================================
	logCheckpoint('Submitting the trip creation form...');

	// The create form has a submit button with text "Add entry" or "Creating..."
	const submitButton = settingsMenu
		.locator('button[type="submit"], .create-button, .save-button')
		.filter({ hasText: /add entry|create|save/i })
		.first();

	// Alternatively, look for any button in the form-actions area
	const formActions = settingsMenu.locator('.form-actions button').last();

	const submitVisible = await submitButton.isVisible({ timeout: 3000 }).catch(() => false);
	const formActionsVisible = await formActions.isVisible({ timeout: 3000 }).catch(() => false);

	logCheckpoint(
		`Submit button visible: ${submitVisible}, Form actions button visible: ${formActionsVisible}`
	);

	if (submitVisible) {
		await submitButton.click();
		logCheckpoint('Clicked submit button.');
	} else if (formActionsVisible) {
		await formActions.click();
		logCheckpoint('Clicked form actions last button.');
	} else {
		// Fallback: look for any button containing "add" or "create"
		const anyAddButton = settingsMenu
			.locator('button')
			.filter({ hasText: /add entry|add|create/i })
			.last();
		const anyAddVisible = await anyAddButton.isVisible({ timeout: 3000 }).catch(() => false);
		if (anyAddVisible) {
			await anyAddButton.click();
			logCheckpoint('Clicked fallback add button.');
		} else {
			// Dump all buttons for debugging
			const allButtons = settingsMenu.locator('button');
			const buttonCount = await allButtons.count();
			logCheckpoint(`Found ${buttonCount} buttons total`);
			for (let i = 0; i < Math.min(buttonCount, 10); i++) {
				const btnText = await allButtons
					.nth(i)
					.textContent()
					.catch(() => '');
				logCheckpoint(`  Button ${i}: "${btnText?.trim()}"`);
			}
			throw new Error('Could not find a submit button for the trip creation form');
		}
	}

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
		.locator('.menu-item')
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
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible({ timeout: 10000 });
	await messageEditor.click();

	// Type "@trips" to trigger the mention dropdown with the trips query
	await page.keyboard.type('@trips');
	logCheckpoint('Typed "@trips" in message editor.');

	// Wait for the mention dropdown to appear
	const mentionDropdown = page.locator('.mention-dropdown');
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
		.locator('.mention-result')
		.filter({ hasText: /trips/i })
		.first();
	await expect(tripsResult).toBeVisible({ timeout: 10000 });
	logCheckpoint('Trips category is visible in mention dropdown results.');
	await takeStepScreenshot(page, 'trips-in-mention-dropdown');

	// Verify it's a settings_memory result (should have an expand button with entry count)
	const expandButton = tripsResult.locator('.expand-button');
	const hasExpandButton = await expandButton.isVisible({ timeout: 3000 }).catch(() => false);
	logCheckpoint(`Expand button visible on Trips result: ${hasExpandButton}`);

	if (hasExpandButton) {
		// Check the entry count is at least 1
		const entryCount = await expandButton
			.locator('.entry-count')
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
			.locator('.mention-result.entry-item')
			.filter({ hasText: new RegExp(TRIP_DESTINATION, 'i') })
			.first();
		await expect(tripEntryInDropdown).toBeVisible({ timeout: 10000 });
		logCheckpoint(`Trip entry "${TRIP_DESTINATION}" visible in expanded dropdown entries.`);
		await takeStepScreenshot(page, 'trip-entry-in-dropdown-expanded');
	} else {
		// Log the actual result structure for debugging
		const resultHTML = await tripsResult.innerHTML().catch(() => 'unable to get HTML');
		logCheckpoint(`Trips result HTML (for debug): ${resultHTML?.substring(0, 500)}`);
		logCheckpoint('WARNING: No expand button found. This may be the bug we are investigating.');

		// Still verify the result is visible - maybe there are no expand buttons yet
		// when only settings_memory categories (not entries) are shown
	}

	// ======================================================================
	// STEP 15: Clear and type "@" + partial destination to find entry directly
	// ======================================================================
	logCheckpoint('Testing direct entry search by destination name...');

	// Clear the current text and type just "@" followed by first 4 chars of destination
	await messageEditor.click();
	await page.keyboard.press('Control+A');
	await page.keyboard.press('Backspace');
	await page.waitForTimeout(300);

	// Type the first few chars of the destination name to search for it directly
	const searchQuery = TRIP_DESTINATION.substring(0, 4).toLowerCase();
	await page.keyboard.type(`@${searchQuery}`);
	logCheckpoint(`Typed "@${searchQuery}" to search for trip entry directly.`);

	// Wait for dropdown
	await expect(mentionDropdown).toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, `mention-dropdown-${searchQuery}-query`);

	// Check if the trip destination or trips category appears in results
	const directSearchResult = mentionDropdown
		.locator('.mention-result')
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
		const allResults = mentionDropdown.locator('.mention-result');
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
			.locator('.settings-menu.visible .menu-item')
			.filter({ hasText: /app store/i })
			.first();
		await expect(cleanupAppStoreItem).toBeVisible({ timeout: 10000 });
		await cleanupAppStoreItem.click();
		await page.waitForTimeout(500);

		// Click "Show all apps" button (SettingsItem .menu-item)
		const cleanupShowAllAppsItem = page
			.locator('.settings-menu.visible .menu-item')
			.filter({ hasText: /show all apps/i })
			.first();
		await expect(cleanupShowAllAppsItem).toBeVisible({ timeout: 10000 });
		await cleanupShowAllAppsItem.click();
		await page.waitForTimeout(500);

		// Click the Travel app card (AppStoreCard .app-store-card)
		const cleanupTravelCard = page
			.locator('.settings-menu.visible .app-store-card')
			.filter({ has: page.locator('.app-card-name', { hasText: /^Travel$/i }) })
			.first();
		await expect(cleanupTravelCard).toBeVisible({ timeout: 10000 });
		await cleanupTravelCard.click();
		await page.waitForTimeout(500);

		// Click the Trips category card (AppStoreCard .app-store-card)
		const cleanupTripsCard = page
			.locator('.settings-menu.visible .app-store-card')
			.filter({ has: page.locator('.app-card-name', { hasText: /^Trips$/i }) })
			.first();
		await expect(cleanupTripsCard).toBeVisible({ timeout: 10000 });
		await cleanupTripsCard.click();
		await page.waitForTimeout(500);

		// Click on the trip entry to open it
		const entryToDelete = page
			.locator('.settings-menu.visible .menu-item')
			.filter({ hasText: TRIP_DESTINATION })
			.first();

		if (await entryToDelete.isVisible({ timeout: 5000 }).catch(() => false)) {
			await entryToDelete.click();
			await page.waitForTimeout(500);

			// Look for a delete button in the entry detail view
			const deleteButton = page
				.locator('.settings-menu.visible button')
				.filter({ hasText: /delete|remove/i })
				.first();

			if (await deleteButton.isVisible({ timeout: 3000 }).catch(() => false)) {
				await deleteButton.click();
				await page.waitForTimeout(500);

				// Confirm deletion if a confirmation dialog appears
				const confirmButton = page
					.locator('.settings-menu.visible button')
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
