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
		consoleLogs.slice(-30).forEach((log) => console.log(log));

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
 * Travel search flow tests: verify that travel app skills (connection search
 * and price calendar) render correctly with fullscreen interactions.
 *
 * Test 1: Travel connection search with fullscreen interaction
 *         - Sends a message triggering a flight connection search
 *         - Verifies the search preview card renders correctly
 *         - Opens the embed in fullscreen mode
 *         - Verifies fullscreen content (route, date, provider, connection results grid)
 *         - Tests fullscreen action buttons (share, report issue, minimize)
 *         - Clicks a connection result to open the connection fullscreen overlay
 *         - Verifies connection fullscreen content (price, route, CTA button)
 *         - Closes the connection overlay and search fullscreen
 *         - Deletes the chat
 *
 * Test 2: Travel price calendar with fullscreen interaction
 *         - Sends a message triggering a price calendar lookup
 *         - Verifies the price calendar preview card renders correctly
 *         - Opens the embed in fullscreen mode
 *         - Verifies fullscreen content (route, month, stats bar, calendar grid)
 *         - Tests fullscreen action buttons
 *         - Closes fullscreen and deletes the chat
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of an existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA OTP secret (base32) for the test account.
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL for the deployed web app under test.
 */

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

// ---------------------------------------------------------------------------
// Shared helpers (same pattern as web-search-flow.spec.ts)
// ---------------------------------------------------------------------------

/**
 * Login to the test account with email, password, and 2FA OTP.
 * Includes retry logic for OTP timing edge cases.
 */
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
		if (attempt === 1) {
			await takeStepScreenshot(page, 'otp-entered');
		}

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
 * Start a new chat session by clicking the new chat button.
 * On the welcome/demo screen, the button only becomes visible when there's content
 * in the message input. We handle this by typing a character first if needed.
 */
async function startNewChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	await page.waitForTimeout(1000);

	const currentUrl = page.url();
	logCheckpoint(`Current URL before starting new chat: ${currentUrl}`);

	const newChatButtonSelectors = [
		'.new-chat-cta-button',
		'.icon_create',
		'button[aria-label*="New"]',
		'button[aria-label*="new"]'
	];

	let clicked = false;
	for (const selector of newChatButtonSelectors) {
		const button = page.locator(selector).first();
		if (await button.isVisible({ timeout: 3000 }).catch(() => false)) {
			logCheckpoint(`Found New Chat button with selector: ${selector}`);
			await button.click();
			clicked = true;
			await page.waitForTimeout(2000);
			break;
		}
	}

	if (!clicked) {
		logCheckpoint('New Chat button not initially visible, trying to trigger it...');
		const messageEditor = page.locator('.editor-content.prose');
		if (await messageEditor.isVisible({ timeout: 3000 }).catch(() => false)) {
			await messageEditor.click();
			await page.keyboard.type(' ');
			await page.waitForTimeout(500);

			for (const selector of newChatButtonSelectors) {
				const button = page.locator(selector).first();
				if (await button.isVisible({ timeout: 3000 }).catch(() => false)) {
					logCheckpoint(`Found New Chat button after typing: ${selector}`);
					await button.click();
					clicked = true;
					await page.waitForTimeout(2000);
					break;
				}
			}

			if (clicked) {
				const newEditor = page.locator('.editor-content.prose');
				if (await newEditor.isVisible({ timeout: 2000 }).catch(() => false)) {
					await newEditor.click();
					await page.keyboard.press('Control+A');
					await page.keyboard.press('Backspace');
				}
			}
		}
	}

	if (!clicked) {
		logCheckpoint('WARNING: Could not find New Chat button with any selector.');
	}

	const newUrl = page.url();
	logCheckpoint(`URL after attempting to start new chat: ${newUrl}`);
}

/**
 * Send a message in the chat editor and wait for the send to complete.
 */
async function sendMessage(
	page: any,
	message: string,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
): Promise<void> {
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type(message);
	logCheckpoint(`Typed message: "${message}"`);
	await takeStepScreenshot(page, `${stepLabel}-message-typed`);

	const sendButton = page.locator('.send-button');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logCheckpoint('Clicked send button.');
	await takeStepScreenshot(page, `${stepLabel}-message-sent`);
}

/**
 * Delete the active chat via context menu (best-effort cleanup).
 * Does not fail the test if cleanup is not possible.
 */
async function deleteActiveChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
): Promise<void> {
	logCheckpoint('Attempting to delete the chat (best-effort cleanup)...');

	try {
		// Open sidebar if collapsed (use short timeout to avoid blocking)
		const sidebarToggle = page.locator('.sidebar-toggle-button');
		if (await sidebarToggle.isVisible({ timeout: 3000 }).catch(() => false)) {
			await sidebarToggle.click();
			await page.waitForTimeout(500);
		}

		const activeChatItem = page.locator('.chat-item-wrapper.active');

		if (!(await activeChatItem.isVisible({ timeout: 5000 }).catch(() => false))) {
			logCheckpoint('No active chat item visible - skipping cleanup.');
			return;
		}

		try {
			const chatTitle = await activeChatItem.locator('.chat-title').textContent({ timeout: 3000 });
			logCheckpoint(`Active chat title: "${chatTitle}"`);

			if (
				chatTitle &&
				(chatTitle.includes('demo') ||
					chatTitle.includes('Demo') ||
					chatTitle.includes('OpenMates'))
			) {
				logCheckpoint('Skipping deletion - appears to be a demo chat.');
				return;
			}
		} catch {
			logCheckpoint('Could not get active chat title.');
		}

		await activeChatItem.click({ button: 'right' });
		await takeStepScreenshot(page, `${stepLabel}-context-menu-open`);
		logCheckpoint('Opened chat context menu.');

		await page.waitForTimeout(300);
		const deleteButton = page.locator('.menu-item.delete');

		if (!(await deleteButton.isVisible({ timeout: 3000 }).catch(() => false))) {
			logCheckpoint('Delete button not visible in context menu - skipping cleanup.');
			await page.keyboard.press('Escape');
			return;
		}

		await deleteButton.click();
		await takeStepScreenshot(page, `${stepLabel}-delete-confirm-mode`);
		logCheckpoint('Clicked delete, now in confirm mode.');

		await deleteButton.click();
		logCheckpoint('Confirmed chat deletion.');

		await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
		await takeStepScreenshot(page, `${stepLabel}-chat-deleted`);
		logCheckpoint('Verified chat deletion successfully.');
	} catch (error) {
		logCheckpoint(`Cleanup failed (non-fatal): ${error}`);
	}
}

// ---------------------------------------------------------------------------
// Test 1: Travel connection search with fullscreen interaction
// ---------------------------------------------------------------------------

test('travel connection search with fullscreen and connection detail interaction', async ({
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

	const logCheckpoint = createSignupLogger('TRAVEL_SEARCH');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'travel-search'
	});

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting travel connection search fullscreen test.', { email: TEST_EMAIL });

	// Login and start a new chat
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	// ======================================================================
	// STEP 1: Send a message that triggers a flight connection search
	// ======================================================================
	// Use a date ~2 months out to ensure results are available.
	const futureDate = new Date();
	futureDate.setMonth(futureDate.getMonth() + 2);
	const monthNames = [
		'January',
		'February',
		'March',
		'April',
		'May',
		'June',
		'July',
		'August',
		'September',
		'October',
		'November',
		'December'
	];
	const day = futureDate.getDate();
	const daySuffix =
		day === 1 || day === 21 || day === 31
			? 'st'
			: day === 2 || day === 22
				? 'nd'
				: day === 3 || day === 23
					? 'rd'
					: 'th';
	const naturalDate = `${monthNames[futureDate.getMonth()]} ${day}${daySuffix}, ${futureDate.getFullYear()}`;
	const searchQuery = `Find me flights from Berlin to London on ${naturalDate}`;
	await sendMessage(page, searchQuery, logCheckpoint, takeStepScreenshot, 'travel-search');

	// Wait for assistant response
	logCheckpoint('Waiting for assistant response with travel search results...');
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 60000 });
	logCheckpoint('Assistant response wrapper is visible.');

	// ======================================================================
	// STEP 2: Verify the travel search embed preview appears and finishes
	// ======================================================================
	const travelSearchPreview = page.locator(
		'.unified-embed-preview[data-app-id="travel"][data-skill-id="search_connections"]'
	);
	logCheckpoint('Waiting for travel search embed preview to appear...');
	await expect(travelSearchPreview.first()).toBeVisible({ timeout: 90000 });
	await takeStepScreenshot(page, 'search-preview-visible');
	logCheckpoint('Travel search embed preview is visible.');

	// Wait for finished state
	const finishedPreview = page.locator(
		'.unified-embed-preview[data-app-id="travel"][data-skill-id="search_connections"][data-status="finished"]'
	);
	await expect(finishedPreview.first()).toBeVisible({ timeout: 90000 });
	logCheckpoint('Travel search preview reached finished state.');

	// Verify preview inner elements
	const searchQueryElement = finishedPreview.first().locator('.search-query');
	await expect(searchQueryElement).toBeVisible({ timeout: 10000 });
	const queryText = await searchQueryElement.textContent();
	logCheckpoint(`Search query displayed on preview: "${queryText}"`);

	const searchDateElement = finishedPreview.first().locator('.search-date');
	await expect(searchDateElement).toBeVisible({ timeout: 5000 });
	const dateText = await searchDateElement.textContent();
	logCheckpoint(`Search date displayed on preview: "${dateText}"`);

	const searchProviderElement = finishedPreview.first().locator('.search-provider');
	await expect(searchProviderElement).toBeVisible({ timeout: 5000 });
	logCheckpoint('Search provider label visible on preview.');

	const basicInfosBar = finishedPreview.first().locator('.basic-infos-bar');
	await expect(basicInfosBar).toBeVisible({ timeout: 5000 });
	logCheckpoint('Basic infos bar is visible on the search preview.');

	await takeStepScreenshot(page, 'search-preview-verified');

	// ======================================================================
	// STEP 3: Click the embed to open fullscreen
	// ======================================================================
	logCheckpoint('Clicking on finished preview to open fullscreen...');
	await finishedPreview.first().click();

	// Wait for the fullscreen overlay to appear and animate in
	const fullscreenOverlay = page.locator('.unified-embed-fullscreen-overlay');
	await expect(fullscreenOverlay).toBeVisible({ timeout: 10000 });
	// Wait for the animation to complete (300ms CSS transition)
	await page.waitForTimeout(500);
	logCheckpoint('Fullscreen overlay is visible.');
	await takeStepScreenshot(page, 'fullscreen-opened');

	// ======================================================================
	// STEP 4: Wait for connection results to load in fullscreen
	// The fullscreen loads child embeds asynchronously. Wait for the grid
	// and results first, then verify the header (which may populate from
	// embed data via onEmbedDataUpdated).
	// ======================================================================
	const connectionGrid = fullscreenOverlay.locator('.connection-embeds-grid');
	await expect(connectionGrid).toBeVisible({ timeout: 60000 });
	logCheckpoint('Connection embeds grid is visible in fullscreen.');

	// Wait for at least one connection result to appear in the grid
	const connectionResults = connectionGrid.locator(
		'.unified-embed-preview[data-app-id="travel"][data-skill-id="connection"]'
	);
	await expect(async () => {
		const count = await connectionResults.count();
		logCheckpoint(`Connection results in grid: ${count}`);
		expect(count).toBeGreaterThanOrEqual(1);
	}).toPass({ timeout: 60000 });

	const totalResults = await connectionResults.count();
	logCheckpoint(`Total connection results in grid: ${totalResults}`);

	// ======================================================================
	// STEP 5: Verify fullscreen header content (query, date, provider)
	// ======================================================================
	const fullscreenHeader = fullscreenOverlay.locator('.fullscreen-header');
	await expect(fullscreenHeader).toBeVisible({ timeout: 10000 });
	logCheckpoint('Fullscreen header is visible.');

	// Query text - check if populated (may be empty if props weren't passed from preview)
	const fullscreenQuery = fullscreenHeader.locator('.search-query');
	const fullscreenQueryText = await fullscreenQuery.textContent();
	logCheckpoint(`Fullscreen search query: "${fullscreenQueryText}"`);

	// Search date - derived from first connection departure time
	const fullscreenDate = fullscreenHeader.locator('.search-date');
	const hasDate = await fullscreenDate.isVisible({ timeout: 5000 }).catch(() => false);
	if (hasDate) {
		const fullscreenDateText = await fullscreenDate.textContent();
		logCheckpoint(`Fullscreen search date: "${fullscreenDateText}"`);
	} else {
		logCheckpoint('Fullscreen search date not visible.');
	}

	// Provider text (always present as it defaults to "Google")
	const fullscreenProvider = fullscreenHeader.locator('.search-provider');
	await expect(fullscreenProvider).toBeVisible({ timeout: 5000 });
	const providerText = await fullscreenProvider.textContent();
	logCheckpoint(`Fullscreen provider: "${providerText}"`);
	await takeStepScreenshot(page, 'fullscreen-connection-grid');

	// ======================================================================
	// STEP 6: Verify individual connection card content
	// ======================================================================
	const firstConnection = connectionResults.first();
	const connectionDetails = firstConnection.locator('.connection-details');
	await expect(connectionDetails).toBeVisible({ timeout: 5000 });

	// Verify price is shown
	const connectionPrice = connectionDetails.locator('.connection-price');
	await expect(connectionPrice).toBeVisible({ timeout: 5000 });
	const priceText = await connectionPrice.textContent();
	logCheckpoint(`First connection price: "${priceText}"`);

	// Verify route text
	const connectionRoute = connectionDetails.locator('.connection-route');
	await expect(connectionRoute).toBeVisible({ timeout: 5000 });
	const routeText = await connectionRoute.textContent();
	logCheckpoint(`First connection route: "${routeText}"`);

	// Verify times (departure - arrival range and duration)
	const connectionTimes = connectionDetails.locator('.connection-times');
	await expect(connectionTimes).toBeVisible({ timeout: 5000 });
	const timesText = await connectionTimes.textContent();
	logCheckpoint(`First connection times: "${timesText}"`);

	// Verify stops info
	const connectionMeta = connectionDetails.locator('.connection-meta');
	await expect(connectionMeta).toBeVisible({ timeout: 5000 });
	const metaText = await connectionMeta.textContent();
	logCheckpoint(`First connection meta: "${metaText}"`);

	await takeStepScreenshot(page, 'connection-card-verified');

	// ======================================================================
	// STEP 7: Verify fullscreen action buttons exist
	// ======================================================================
	logCheckpoint('Verifying fullscreen action buttons...');

	const shareButton = fullscreenOverlay.locator('.share-button');
	await expect(shareButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Share button is visible.');

	const reportIssueButton = fullscreenOverlay.locator('.report-issue-button');
	await expect(reportIssueButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Report issue button is visible.');

	const minimizeButton = fullscreenOverlay.locator('.minimize-button');
	await expect(minimizeButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Minimize button is visible.');

	const bottomBar = fullscreenOverlay.locator('.basic-infos-bar-wrapper');
	await expect(bottomBar).toBeVisible({ timeout: 5000 });
	logCheckpoint('Bottom BasicInfosBar wrapper is visible in fullscreen.');

	await takeStepScreenshot(page, 'fullscreen-buttons-verified');

	// ======================================================================
	// STEP 8: Click a connection result to open the connection fullscreen overlay
	// ======================================================================
	logCheckpoint('Clicking first connection result to open connection fullscreen...');
	await firstConnection.click();

	// Wait for the child embed overlay to appear (z-index 101, on top of search fullscreen)
	const childOverlay = page.locator('.child-embed-overlay');
	await expect(childOverlay).toBeVisible({ timeout: 10000 });
	// Wait for animation
	await page.waitForTimeout(500);
	logCheckpoint('Child embed overlay (connection fullscreen) is visible.');
	await takeStepScreenshot(page, 'connection-fullscreen-opened');

	// ======================================================================
	// STEP 9: Verify connection fullscreen content
	// ======================================================================
	const connectionFullscreen = childOverlay.locator('.connection-fullscreen');
	await expect(connectionFullscreen).toBeVisible({ timeout: 10000 });
	logCheckpoint('Connection fullscreen content is visible.');

	// Verify the price is shown
	const fullscreenPrice = connectionFullscreen.locator('.price');
	await expect(fullscreenPrice).toBeVisible({ timeout: 5000 });
	const fsPriceText = await fullscreenPrice.textContent();
	logCheckpoint(`Connection fullscreen price: "${fsPriceText}"`);

	// Verify the route is shown
	const fullscreenRoute = connectionFullscreen.locator('.route');
	await expect(fullscreenRoute).toBeVisible({ timeout: 5000 });
	const fsRouteText = await fullscreenRoute.textContent();
	logCheckpoint(`Connection fullscreen route: "${fsRouteText}"`);

	// Verify the CTA button exists (booking link)
	const ctaButton = connectionFullscreen.locator('.cta-button');
	await expect(ctaButton).toBeVisible({ timeout: 5000 });
	const ctaText = await ctaButton.textContent();
	logCheckpoint(`Connection CTA button text: "${ctaText}"`);

	// Verify route map is rendered (Leaflet map container)
	const routeMap = connectionFullscreen.locator('.route-map-container');
	await expect(routeMap).toBeVisible({ timeout: 10000 });
	logCheckpoint('Route map container is visible.');

	// Verify legs container (flight segments timeline)
	const legsContainer = connectionFullscreen.locator('.legs-container');
	// Legs may or may not be present (some results show summary-only instead)
	const hasLegs = await legsContainer.isVisible({ timeout: 5000 }).catch(() => false);
	if (hasLegs) {
		logCheckpoint('Legs container is visible with flight segments.');
		const legs = legsContainer.locator('.leg');
		const legCount = await legs.count();
		logCheckpoint(`Number of legs: ${legCount}`);
	} else {
		// Check for summary-only view
		const summaryOnly = connectionFullscreen.locator('.summary-only');
		const hasSummary = await summaryOnly.isVisible({ timeout: 3000 }).catch(() => false);
		logCheckpoint(`Legs not shown, summary-only view: ${hasSummary}`);
	}

	await takeStepScreenshot(page, 'connection-fullscreen-verified');

	// ======================================================================
	// STEP 10: Test 3-state CTA booking button flow
	// States: idle ("Get booking link") -> loading (spinner) -> loaded ("Book on {provider}") or error ("Open Google Flights")
	// ======================================================================
	logCheckpoint('Testing 3-state CTA booking button flow...');

	// Re-locate the CTA area inside the connection fullscreen since state may have changed
	// The CTA button lives inside .connection-header (not .connection-details)
	const ctaArea = connectionFullscreen.locator('.connection-header');

	// Determine current booking state from the DOM
	const ctaIdleButton = ctaArea
		.locator('button.cta-button:not(.cta-fallback)')
		.filter({ hasText: /get booking link/i });
	const ctaLoadedButton = ctaArea
		.locator('button.cta-button:not(.cta-fallback)')
		.filter({ hasText: /book on/i });
	const ctaFallbackButton = ctaArea.locator('button.cta-button.cta-fallback');
	const ctaLoadingDiv = ctaArea.locator('.cta-button.cta-loading');

	const isIdle = await ctaIdleButton.isVisible({ timeout: 3000 }).catch(() => false);
	const isAlreadyLoaded = await ctaLoadedButton.isVisible({ timeout: 1000 }).catch(() => false);
	const isAlreadyError = await ctaFallbackButton.isVisible({ timeout: 1000 }).catch(() => false);

	logCheckpoint(
		`CTA initial state — idle: ${isIdle}, loaded: ${isAlreadyLoaded}, error: ${isAlreadyError}`
	);

	if (isIdle) {
		// STATE: idle — click "Get booking link" to trigger the fetch
		logCheckpoint('CTA is idle. Clicking "Get booking link" to fetch booking URL...');
		await ctaIdleButton.click();

		// Should transition to loading state (spinner)
		const showedLoading = await ctaLoadingDiv.isVisible({ timeout: 3000 }).catch(() => false);
		logCheckpoint(`CTA showed loading spinner: ${showedLoading}`);

		// Wait for transition to either loaded or error state (booking link API takes ~3-5s)
		logCheckpoint('Waiting for CTA to resolve (loaded or error)...');
		try {
			await expect(ctaArea.locator('button.cta-button')).toBeVisible({ timeout: 15000 });
		} catch {
			// If still loading after 15s, that's unusual but not a test failure
			logCheckpoint('CTA still loading after 15s — API may be slow.');
		}

		// Check which state we ended up in
		const resolvedToLoaded = await ctaLoadedButton.isVisible({ timeout: 2000 }).catch(() => false);
		const resolvedToError = await ctaFallbackButton.isVisible({ timeout: 1000 }).catch(() => false);
		logCheckpoint(`CTA resolved — loaded: ${resolvedToLoaded}, error: ${resolvedToError}`);

		if (resolvedToLoaded) {
			// STATE: loaded — click "Book on {provider}" to open booking URL in new tab
			const bookOnText = await ctaLoadedButton.textContent();
			logCheckpoint(`CTA loaded with text: "${bookOnText}". Clicking to open booking URL...`);

			const [bookingPage] = await Promise.all([
				page.waitForEvent('popup', { timeout: 10000 }),
				ctaLoadedButton.click()
			]);

			// Wait for the new tab to navigate (booking redirects can take a moment)
			logCheckpoint(`New tab opened with initial URL: ${bookingPage.url()}`);
			try {
				await bookingPage.waitForLoadState('domcontentloaded', { timeout: 15000 });
			} catch {
				logCheckpoint('New tab did not fully load within 15s — checking URL anyway.');
			}

			const finalUrl = bookingPage.url();
			logCheckpoint(`Booking tab final URL: ${finalUrl}`);

			// Verify it's not a blank page
			expect(finalUrl).not.toBe('about:blank');
			expect(finalUrl).not.toBe('');

			// Verify the page is not an error page (check title for common error indicators)
			const pageTitle = await bookingPage.title().catch(() => '');
			logCheckpoint(`Booking page title: "${pageTitle}"`);
			const errorPatterns =
				/\b(404|500|502|503|not found|server error|error page|access denied|forbidden)\b/i;
			const isErrorPage = errorPatterns.test(pageTitle);
			if (isErrorPage) {
				logCheckpoint(`WARNING: Booking page appears to be an error page (title: "${pageTitle}")`);
			} else {
				logCheckpoint('Booking page appears valid (no error indicators in title).');
			}
			// Don't hard-fail on error pages since external sites may change — just log
			expect(isErrorPage).toBe(false);

			await bookingPage.close();
			logCheckpoint('Closed booking tab.');
		} else if (resolvedToError) {
			// STATE: error — click "Open Google Flights" fallback
			logCheckpoint('CTA resolved to error state. Clicking "Open Google Flights" fallback...');

			const [fallbackPage] = await Promise.all([
				page.waitForEvent('popup', { timeout: 10000 }),
				ctaFallbackButton.click()
			]);

			logCheckpoint(`Google Flights tab opened with URL: ${fallbackPage.url()}`);
			try {
				await fallbackPage.waitForLoadState('domcontentloaded', { timeout: 15000 });
			} catch {
				logCheckpoint('Google Flights tab did not fully load within 15s.');
			}

			const fallbackUrl = fallbackPage.url();
			logCheckpoint(`Google Flights tab final URL: ${fallbackUrl}`);
			expect(fallbackUrl).toContain('google.com/travel/flights');

			await fallbackPage.close();
			logCheckpoint('Closed Google Flights tab.');
		} else {
			// Still loading or in an unexpected state — log and continue
			logCheckpoint(
				'CTA did not resolve to loaded or error state. Skipping booking link verification.'
			);
		}
	} else if (isAlreadyLoaded) {
		// STATE: loaded (pre-resolved booking URL) — click "Book on {provider}"
		const bookOnText = await ctaLoadedButton.textContent();
		logCheckpoint(`CTA already loaded with text: "${bookOnText}". Clicking to open booking URL...`);

		const [bookingPage] = await Promise.all([
			page.waitForEvent('popup', { timeout: 10000 }),
			ctaLoadedButton.click()
		]);

		logCheckpoint(`New tab opened with URL: ${bookingPage.url()}`);
		try {
			await bookingPage.waitForLoadState('domcontentloaded', { timeout: 15000 });
		} catch {
			logCheckpoint('Booking tab did not fully load within 15s.');
		}

		const finalUrl = bookingPage.url();
		logCheckpoint(`Booking tab final URL: ${finalUrl}`);
		expect(finalUrl).not.toBe('about:blank');

		const pageTitle = await bookingPage.title().catch(() => '');
		logCheckpoint(`Booking page title: "${pageTitle}"`);
		const errorPatterns =
			/\b(404|500|502|503|not found|server error|error page|access denied|forbidden)\b/i;
		if (errorPatterns.test(pageTitle)) {
			logCheckpoint(`WARNING: Booking page appears to be an error page (title: "${pageTitle}")`);
		}

		await bookingPage.close();
		logCheckpoint('Closed booking tab.');
	} else if (isAlreadyError) {
		// STATE: error — test Google Flights fallback
		logCheckpoint('CTA already in error state. Clicking "Open Google Flights" fallback...');

		const [fallbackPage] = await Promise.all([
			page.waitForEvent('popup', { timeout: 10000 }),
			ctaFallbackButton.click()
		]);

		const fallbackUrl = fallbackPage.url();
		logCheckpoint(`Google Flights tab URL: ${fallbackUrl}`);
		expect(fallbackUrl).toContain('google.com/travel/flights');

		await fallbackPage.close();
		logCheckpoint('Closed Google Flights tab.');
	} else {
		// No CTA button visible at all (no booking_token for this connection)
		logCheckpoint(
			'No CTA button visible — connection has no booking_token. Skipping booking link test.'
		);
	}

	await takeStepScreenshot(page, 'connection-cta-verified');

	// ======================================================================
	// STEP 11: Verify connection fullscreen buttons
	// ======================================================================
	const connectionFullscreenOverlay = childOverlay.locator('.unified-embed-fullscreen-overlay');
	const connShareButton = connectionFullscreenOverlay.locator('.share-button');
	await expect(connShareButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Connection fullscreen share button is visible.');

	const connReportButton = connectionFullscreenOverlay.locator('.report-issue-button');
	await expect(connReportButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Connection fullscreen report issue button is visible.');

	const connMinimizeButton = connectionFullscreenOverlay.locator('.minimize-button');
	await expect(connMinimizeButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Connection fullscreen minimize button is visible.');

	await takeStepScreenshot(page, 'connection-buttons-verified');

	// ======================================================================
	// STEP 12: Close connection fullscreen overlay via minimize button
	// ======================================================================
	logCheckpoint('Closing connection fullscreen via minimize button...');
	await connMinimizeButton.click();
	// Wait for close animation (300ms) + buffer
	await page.waitForTimeout(500);

	// The child overlay should be gone, but the search fullscreen should still be visible
	await expect(childOverlay).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Connection fullscreen overlay closed.');

	// Verify the search fullscreen is still showing
	await expect(fullscreenOverlay).toBeVisible({ timeout: 5000 });
	await expect(connectionGrid).toBeVisible({ timeout: 5000 });
	logCheckpoint('Search fullscreen is still visible after closing connection overlay.');
	await takeStepScreenshot(page, 'back-to-search-fullscreen');

	// ======================================================================
	// STEP 13: Close search fullscreen via minimize button
	// ======================================================================
	logCheckpoint('Closing search fullscreen via minimize button...');
	const searchMinimizeButton = fullscreenOverlay.locator('.minimize-button');
	await searchMinimizeButton.click();
	// Wait for close animation
	await page.waitForTimeout(500);

	await expect(fullscreenOverlay).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Search fullscreen closed successfully.');
	await takeStepScreenshot(page, 'fullscreen-closed');

	// ======================================================================
	// STEP 14: Delete the chat
	// ======================================================================
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'travel-search-cleanup');
	logCheckpoint('Travel connection search fullscreen test completed successfully.');
});

// ---------------------------------------------------------------------------
// Test 2: Travel price calendar with fullscreen interaction
// ---------------------------------------------------------------------------

test('travel price calendar with fullscreen and calendar grid verification', async ({
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

	const logCheckpoint = createSignupLogger('TRAVEL_CALENDAR');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'travel-calendar'
	});

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting travel price calendar fullscreen test.', { email: TEST_EMAIL });

	// Login and start a new chat
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	// ======================================================================
	// STEP 1: Send a message that triggers a price calendar lookup
	// ======================================================================
	// Use a month ~2 months out for reliable data availability
	const futureDate = new Date();
	futureDate.setMonth(futureDate.getMonth() + 2);
	const monthNames = [
		'January',
		'February',
		'March',
		'April',
		'May',
		'June',
		'July',
		'August',
		'September',
		'October',
		'November',
		'December'
	];
	const monthName = monthNames[futureDate.getMonth()];
	const year = futureDate.getFullYear();
	const calendarQuery = `Show me the cheapest flight prices from Berlin to Barcelona for ${monthName} ${year}. I'm flexible on dates, just show me a price calendar overview.`;
	await sendMessage(page, calendarQuery, logCheckpoint, takeStepScreenshot, 'price-calendar');

	// Wait for assistant response
	logCheckpoint('Waiting for assistant response with price calendar results...');
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 60000 });
	logCheckpoint('Assistant response wrapper is visible.');

	// ======================================================================
	// STEP 2: Verify the price calendar embed preview appears and finishes
	// ======================================================================
	const calendarPreview = page.locator(
		'.unified-embed-preview[data-app-id="travel"][data-skill-id="price_calendar"]'
	);
	logCheckpoint('Waiting for price calendar embed preview to appear...');
	await expect(calendarPreview.first()).toBeVisible({ timeout: 90000 });
	await takeStepScreenshot(page, 'calendar-preview-visible');
	logCheckpoint('Price calendar embed preview is visible.');

	// Wait for finished state
	const finishedCalendar = page.locator(
		'.unified-embed-preview[data-app-id="travel"][data-skill-id="price_calendar"][data-status="finished"]'
	);
	await expect(finishedCalendar.first()).toBeVisible({ timeout: 90000 });
	logCheckpoint('Price calendar preview reached finished state.');

	// Verify preview inner elements
	const routeSummary = finishedCalendar.first().locator('.route-summary');
	await expect(routeSummary).toBeVisible({ timeout: 10000 });
	const routeText = await routeSummary.textContent();
	logCheckpoint(`Route summary displayed on preview: "${routeText}"`);

	const monthDisplay = finishedCalendar.first().locator('.month-display');
	await expect(monthDisplay).toBeVisible({ timeout: 5000 });
	const monthText = await monthDisplay.textContent();
	logCheckpoint(`Month displayed on preview: "${monthText}"`);

	const providerText = finishedCalendar.first().locator('.provider-text');
	await expect(providerText).toBeVisible({ timeout: 5000 });
	logCheckpoint('Provider text visible on preview.');

	// Check for results info (price range and days count)
	const calendarResultsInfo = finishedCalendar.first().locator('.calendar-results-info');
	const hasResultsInfo = await calendarResultsInfo.isVisible({ timeout: 5000 }).catch(() => false);
	if (hasResultsInfo) {
		const priceRange = calendarResultsInfo.locator('.price-range');
		const hasPriceRange = await priceRange.isVisible({ timeout: 3000 }).catch(() => false);
		if (hasPriceRange) {
			const priceRangeText = await priceRange.textContent();
			logCheckpoint(`Price range on preview: "${priceRangeText}"`);
		}

		const daysInfo = calendarResultsInfo.locator('.days-info');
		const hasDaysInfo = await daysInfo.isVisible({ timeout: 3000 }).catch(() => false);
		if (hasDaysInfo) {
			const daysText = await daysInfo.textContent();
			logCheckpoint(`Days info on preview: "${daysText}"`);
		}
	} else {
		logCheckpoint('Calendar results info not visible (may have no data for this route/month).');
	}

	const basicInfosBar = finishedCalendar.first().locator('.basic-infos-bar');
	await expect(basicInfosBar).toBeVisible({ timeout: 5000 });
	logCheckpoint('Basic infos bar is visible on the calendar preview.');

	await takeStepScreenshot(page, 'calendar-preview-verified');

	// ======================================================================
	// STEP 3: Click the embed to open fullscreen
	// ======================================================================
	logCheckpoint('Clicking on finished calendar preview to open fullscreen...');
	await finishedCalendar.first().click();

	const fullscreenOverlay = page.locator('.unified-embed-fullscreen-overlay');
	await expect(fullscreenOverlay).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(500);
	logCheckpoint('Fullscreen overlay is visible.');
	await takeStepScreenshot(page, 'calendar-fullscreen-opened');

	// ======================================================================
	// STEP 4: Verify fullscreen content - header with route, codes, month, provider
	// ======================================================================
	const fullscreenHeader = fullscreenOverlay.locator('.fullscreen-header');
	await expect(fullscreenHeader).toBeVisible({ timeout: 10000 });
	logCheckpoint('Fullscreen header is visible.');

	const routeTitle = fullscreenHeader.locator('.route-title');
	await expect(routeTitle).toBeVisible({ timeout: 5000 });
	const routeTitleText = await routeTitle.textContent();
	logCheckpoint(`Fullscreen route title: "${routeTitleText}"`);

	const routeCodes = fullscreenHeader.locator('.route-codes');
	await expect(routeCodes).toBeVisible({ timeout: 5000 });
	const routeCodesText = await routeCodes.textContent();
	logCheckpoint(`Fullscreen route codes (IATA): "${routeCodesText}"`);

	const monthTitle = fullscreenHeader.locator('.month-title');
	await expect(monthTitle).toBeVisible({ timeout: 5000 });
	const monthTitleText = await monthTitle.textContent();
	logCheckpoint(`Fullscreen month title: "${monthTitleText}"`);

	const fsProviderText = fullscreenHeader.locator('.provider-text');
	await expect(fsProviderText).toBeVisible({ timeout: 5000 });
	logCheckpoint('Fullscreen provider text is visible.');

	// ======================================================================
	// STEP 5: Verify stats bar (cheapest, most expensive, coverage)
	// ======================================================================
	const statsBar = fullscreenOverlay.locator('.stats-bar');
	const hasStatsBar = await statsBar.isVisible({ timeout: 5000 }).catch(() => false);
	if (hasStatsBar) {
		const stats = statsBar.locator('.stat');
		const statCount = await stats.count();
		logCheckpoint(`Stats bar visible with ${statCount} stats.`);

		for (let i = 0; i < statCount; i++) {
			const statLabel = await stats.nth(i).locator('.stat-label').textContent();
			const statValue = await stats.nth(i).locator('.stat-value').textContent();
			logCheckpoint(`Stat ${i + 1}: "${statLabel}" = "${statValue}"`);
		}
	} else {
		logCheckpoint('Stats bar not visible (may have no data for this route/month).');
	}

	// ======================================================================
	// STEP 6: Verify calendar grid is rendered
	// ======================================================================
	const calendarContainer = fullscreenOverlay.locator('.calendar-container');
	const hasCalendar = await calendarContainer.isVisible({ timeout: 10000 }).catch(() => false);

	if (hasCalendar) {
		logCheckpoint('Calendar container is visible.');

		// Verify the calendar grid exists
		const calendarGrid = calendarContainer.locator('.calendar-grid');
		await expect(calendarGrid).toBeVisible({ timeout: 5000 });
		logCheckpoint('Calendar grid is visible.');

		// Verify weekday headers are rendered (Mon-Sun = 7 headers)
		const weekdayHeaders = calendarGrid.locator('.weekday-header');
		const headerCount = await weekdayHeaders.count();
		logCheckpoint(`Weekday headers count: ${headerCount}`);
		expect(headerCount).toBe(7);

		// Verify calendar cells exist (empty + data cells)
		const calendarCells = calendarGrid.locator('.calendar-cell');
		const cellCount = await calendarCells.count();
		logCheckpoint(`Total calendar cells: ${cellCount}`);
		// A month grid should have at least 28 cells (4 weeks min + empty cells for alignment)
		expect(cellCount).toBeGreaterThanOrEqual(28);

		// Count cells with price data
		const dataCells = calendarGrid.locator('.calendar-cell.has-data');
		const dataCellCount = await dataCells.count();
		logCheckpoint(`Calendar cells with price data: ${dataCellCount}`);

		if (dataCellCount > 0) {
			// Verify first data cell has day number and price
			const firstDataCell = dataCells.first();
			const cellDay = firstDataCell.locator('.cell-day');
			await expect(cellDay).toBeVisible({ timeout: 3000 });
			const dayText = await cellDay.textContent();
			logCheckpoint(`First data cell day: "${dayText}"`);

			const cellPrice = firstDataCell.locator('.cell-price');
			await expect(cellPrice).toBeVisible({ timeout: 3000 });
			const cellPriceText = await cellPrice.textContent();
			logCheckpoint(`First data cell price: "${cellPriceText}"`);
		}

		// Verify color legend is shown
		const legend = fullscreenOverlay.locator('.legend');
		const hasLegend = await legend.isVisible({ timeout: 3000 }).catch(() => false);
		if (hasLegend) {
			const legendGradient = legend.locator('.legend-gradient');
			await expect(legendGradient).toBeVisible({ timeout: 3000 });
			logCheckpoint('Color legend with gradient is visible.');
		} else {
			logCheckpoint('Color legend not visible.');
		}
	} else {
		// Check for no-results or error state
		const noResults = fullscreenOverlay.locator('.no-results');
		const hasNoResults = await noResults.isVisible({ timeout: 3000 }).catch(() => false);
		if (hasNoResults) {
			logCheckpoint('No results state displayed in calendar fullscreen.');
		}

		const errorState = fullscreenOverlay.locator('.error-state');
		const hasError = await errorState.isVisible({ timeout: 3000 }).catch(() => false);
		if (hasError) {
			const errorTitle = await errorState.locator('.error-title').textContent();
			logCheckpoint(`Error state in calendar fullscreen: "${errorTitle}"`);
		}
	}

	await takeStepScreenshot(page, 'calendar-fullscreen-content-verified');

	// ======================================================================
	// STEP 7: Verify fullscreen action buttons
	// ======================================================================
	logCheckpoint('Verifying fullscreen action buttons...');

	const shareButton = fullscreenOverlay.locator('.share-button');
	await expect(shareButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Share button is visible.');

	const reportIssueButton = fullscreenOverlay.locator('.report-issue-button');
	await expect(reportIssueButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Report issue button is visible.');

	const minimizeButton = fullscreenOverlay.locator('.minimize-button');
	await expect(minimizeButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Minimize button is visible.');

	const bottomBar = fullscreenOverlay.locator('.basic-infos-bar-wrapper');
	await expect(bottomBar).toBeVisible({ timeout: 5000 });
	logCheckpoint('Bottom BasicInfosBar wrapper is visible in fullscreen.');

	await takeStepScreenshot(page, 'calendar-buttons-verified');

	// ======================================================================
	// STEP 8: Close calendar fullscreen via minimize button
	// ======================================================================
	logCheckpoint('Closing calendar fullscreen via minimize button...');
	await minimizeButton.click();
	await page.waitForTimeout(500);

	await expect(fullscreenOverlay).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Calendar fullscreen closed successfully.');
	await takeStepScreenshot(page, 'calendar-fullscreen-closed');

	// ======================================================================
	// STEP 9: Delete the chat
	// ======================================================================
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'calendar-cleanup');
	logCheckpoint('Travel price calendar fullscreen test completed successfully.');
});
