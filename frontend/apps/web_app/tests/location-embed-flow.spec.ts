/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Location Embed Flow — E2E test
 *
 * Verifies the full user journey for sending a location embed to the AI:
 *
 *   1. Click in message input
 *   2. Click the map icon to open the map selector
 *   3. Search for "Berlin Hbf" and press Enter
 *   4. Click the result that contains "Berlin" in its name
 *   5. Verify map selector closed and embed appeared in message input
 *   6. Type a question after the embed and send
 *   7. Wait for AI response and verify it mentions "Berlin Hbf"
 *   8. Delete the chat
 *
 * This test also guards against the embed-resolution regression where
 * the server passed the raw embed UUID to the LLM instead of the resolved
 * address/coordinates (bug fixed in message_received_handler.py).
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 *
 * Run via Docker only:
 *   docker compose --env-file .env -f docker-compose.playwright.yml run --rm \
 *     -e PLAYWRIGHT_TEST_FILE="location-embed-flow.spec.ts" playwright
 */

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
		consoleLogs.slice(-30).forEach((log: string) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity: string) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations
} = require('./signup-flow-helpers');

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test('sends location embed and AI response contains the station name', async ({
	page
}: {
	page: any;
}) => {
	page.on('console', (msg: any) => {
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (req: any) => {
		networkActivities.push(`[${new Date().toISOString()}] >> ${req.method()} ${req.url()}`);
	});
	page.on('response', (res: any) => {
		networkActivities.push(`[${new Date().toISOString()}] << ${res.status()} ${res.url()}`);
	});

	test.slow();
	test.setTimeout(120000);

	const logCheckpoint = createSignupLogger('LOCATION_EMBED');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'location-embed'
	});

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting location embed flow test.', { email: TEST_EMAIL });

	// ======================================================================
	// STEP 1: Login
	// ======================================================================
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

	// OTP retry loop (timing edge case)
	for (let attempt = 1; attempt <= 3; attempt++) {
		await otpInput.fill(generateTotp(TEST_OTP_KEY));
		await submitLoginButton.click();
		try {
			await expect(otpInput).not.toBeVisible({ timeout: 10000 });
			logCheckpoint(`Login successful (attempt ${attempt}).`);
			break;
		} catch {
			if (attempt === 3) throw new Error('Login failed after 3 OTP attempts');
			await page.waitForTimeout(2000);
		}
	}

	// Wait for chat interface
	await page.waitForTimeout(3000);
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible({ timeout: 20000 });
	logCheckpoint('Chat interface loaded.');

	// ======================================================================
	// STEP 2: Start a new chat
	// ======================================================================
	const newChatButton = page.locator('.icon_create');
	if (await newChatButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		await newChatButton.click();
		await page.waitForTimeout(2000);
		logCheckpoint('Clicked new chat button.');
	} else {
		// On welcome/demo screen: type a space to reveal the new chat button
		await messageEditor.click();
		await page.keyboard.type(' ');
		await page.waitForTimeout(500);
		const newChatCta = page.locator('.new-chat-cta-button');
		if (await newChatCta.isVisible({ timeout: 3000 }).catch(() => false)) {
			await newChatCta.click();
			await page.waitForTimeout(2000);
			// Clear the space we typed
			await messageEditor.click();
			await page.keyboard.press('Control+A');
			await page.keyboard.press('Backspace');
			logCheckpoint('Clicked new-chat-cta button.');
		}
	}
	await takeStepScreenshot(page, 'new-chat-started');

	// ======================================================================
	// STEP 3: Click in the message editor to focus it
	// ======================================================================
	await messageEditor.click();
	logCheckpoint('Clicked message editor to focus it.');

	// ======================================================================
	// STEP 4: Open the map selector via the maps icon
	// ======================================================================
	const mapsButton = page.locator('button.icon_maps').first();
	await expect(mapsButton).toBeVisible({ timeout: 10000 });
	await mapsButton.click();
	logCheckpoint('Clicked maps icon — map selector opened.');
	await takeStepScreenshot(page, 'map-selector-opened');

	// ======================================================================
	// STEP 5: Wait for MapsView overlay and map to initialise
	// The map initialises after the slide-in transition completes (onintroend).
	// ======================================================================
	const mapsOverlay = page.locator('.maps-overlay');
	await expect(mapsOverlay).toBeVisible({ timeout: 15000 });
	// Allow time for Leaflet to initialise after the slide transition
	await page.waitForTimeout(2500);
	logCheckpoint('MapsView overlay visible and map initialised.');
	await takeStepScreenshot(page, 'map-initialised');

	// ======================================================================
	// STEP 6: Search for "Berlin Hbf" and press Enter
	// ======================================================================
	const searchInput = mapsOverlay.locator('input.search-input');
	await expect(searchInput).toBeVisible({ timeout: 10000 });
	await searchInput.fill('Berlin Hbf');
	await searchInput.press('Enter');
	logCheckpoint('Typed "Berlin Hbf" and pressed Enter.');
	await takeStepScreenshot(page, 'search-typed');

	// ======================================================================
	// STEP 7: Click the first result that contains "Berlin" in its name
	// ======================================================================
	const searchResultsContainer = mapsOverlay.locator('.search-results-container');
	await expect(searchResultsContainer).toBeVisible({ timeout: 30000 });
	logCheckpoint('Search results appeared.');

	// Find and click the first result whose name contains "Berlin"
	const berlinResult = searchResultsContainer
		.locator('.search-result-item')
		.filter({ has: page.locator('.result-name', { hasText: /berlin/i }) })
		.first();

	await expect(berlinResult).toBeVisible({ timeout: 10000 });
	const resultNameText = await berlinResult.locator('.result-name').textContent();
	logCheckpoint(`Clicking result: "${resultNameText?.trim()}"`);
	await takeStepScreenshot(page, 'search-results-visible');

	await berlinResult.click();
	logCheckpoint('Clicked Berlin Hbf result.');

	// ======================================================================
	// STEP 8: Verify map selector closed and embed is in the message input
	// After clicking a result: results panel closes, map pans to location,
	// user clicks "Select" in the location indicator, then MapsView closes.
	// ======================================================================

	// Wait for search results to close (result was selected, map is panning)
	await expect(searchResultsContainer).not.toBeVisible({ timeout: 10000 });
	logCheckpoint('Search results panel closed.');

	// Wait for location indicator with Select button to appear
	const locationIndicator = mapsOverlay.locator('.location-indicator');
	await expect(locationIndicator).toBeVisible({ timeout: 15000 });
	await expect(locationIndicator).not.toHaveClass(/is-moving/, { timeout: 10000 });

	const locationText = await locationIndicator.locator('.location-text').textContent();
	logCheckpoint(`Location indicator text: "${locationText?.trim()}"`);
	await takeStepScreenshot(page, 'location-indicator-visible');

	// Click the "Select" button to insert embed and close MapsView
	const selectButton = locationIndicator.locator('button');
	await expect(selectButton).toBeVisible({ timeout: 10000 });
	await selectButton.click();
	logCheckpoint('Clicked Select — embed inserted into editor.');

	// Verify MapsView is gone
	await expect(mapsOverlay).not.toBeVisible({ timeout: 10000 });
	logCheckpoint('MapsView closed.');

	// Send button visible = editor has content (the embed)
	const sendButton = page.locator('.send-button');
	await expect(sendButton).toBeVisible({ timeout: 10000 });
	logCheckpoint('Send button visible — embed is in the editor.');
	await takeStepScreenshot(page, 'embed-in-editor');

	// ======================================================================
	// STEP 9: Type the question after the embed and send
	//
	// insertMap() ends with:
	//   editor.commands.insertContent([embedNode, { type: "text", text: " " }])
	//   editor.commands.focus("end")   ← cursor is already at end, after the embed
	//
	// So we just type directly — no need to click in the editor.
	// The question asks for raw details only, suppressing app skills to keep
	// the response fast and deterministic.
	// ======================================================================
	await page.keyboard.type(
		'Simple answer please: what is the station called, what address and which lat/lon? (only give me the details i provided you, without using any app skills.)'
	);
	logCheckpoint('Typed question after embed.');
	await takeStepScreenshot(page, 'message-ready-to-send');

	await expect(sendButton).toBeEnabled({ timeout: 5000 });
	await sendButton.click();
	logCheckpoint('Message sent.');
	await takeStepScreenshot(page, 'message-sent');

	// ======================================================================
	// STEP 10: Wait for AI response containing "Berlin"
	//
	// If embed resolution works correctly the AI will know it's Berlin Hbf
	// and mention "Berlin" in the response. If the bug regressed the AI
	// would receive a raw UUID or nothing useful and would not say "Berlin".
	// ======================================================================
	logCheckpoint('Waiting for AI response containing "Berlin"...');
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.last()).toContainText('Berlin', { timeout: 45000 });
	logCheckpoint('AI response contains "Berlin" — embed was resolved correctly.');

	const responseText = await assistantMessage.last().textContent();
	logCheckpoint(`Full AI response: "${responseText?.trim()}"`);
	await takeStepScreenshot(page, 'response-received');

	// Regression guard: response must NOT contain a raw embed UUID
	// (8-4-4-4-12 hex pattern), which would mean the embed wasn't resolved.
	const uuidPattern = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
	expect(
		uuidPattern.test(responseText ?? ''),
		`AI response must NOT contain a raw embed UUID (embed resolution regression). Response: "${responseText?.substring(0, 300)}"`
	).toBe(false);
	logCheckpoint('Regression guard passed — no raw UUID in response.');

	// Check for missing translations
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations.');

	// ======================================================================
	// STEP 11: Delete the chat
	// ======================================================================
	logCheckpoint('Deleting the chat...');

	const sidebarToggle = page.locator('.sidebar-toggle-button');
	if (await sidebarToggle.isVisible({ timeout: 3000 }).catch(() => false)) {
		await sidebarToggle.click();
		await page.waitForTimeout(500);
	}

	const activeChatItem = page.locator('.chat-item-wrapper.active');
	await expect(activeChatItem).toBeVisible({ timeout: 10000 });

	await activeChatItem.click({ button: 'right' });
	await takeStepScreenshot(page, 'context-menu-open');

	const deleteButton = page.locator('.menu-item.delete');
	await expect(deleteButton).toBeVisible({ timeout: 5000 });
	await deleteButton.click(); // enter confirm mode
	await deleteButton.click(); // confirm deletion
	logCheckpoint('Chat deleted.');

	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, 'chat-deleted');
	logCheckpoint('Location embed flow test completed successfully.');
});
