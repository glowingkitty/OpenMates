/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Web search flow tests: verify that app skill uses (web search) render correctly,
 * fullscreen interactions work, and multi-search grouping behaves as expected.
 *
 * Test 1: Single web search with fullscreen interaction
 *         - Sends a message triggering one web search
 *         - Verifies the search preview card renders correctly
 *         - Opens the embed in fullscreen mode
 *         - Verifies fullscreen content (query, provider, website results grid)
 *         - Tests fullscreen action buttons (share, report issue, minimize)
 *         - Clicks a website result to open the website fullscreen overlay
 *         - Verifies website fullscreen content (title, CTA button, description)
 *         - Closes the website overlay and search fullscreen
 *         - Deletes the chat
 *
 * Test 2: Multiple web searches with grouping and fullscreen
 *         - Sends a message triggering 3 separate web searches
 *         - Verifies searches are grouped in a scrollable container
 *         - Verifies group header shows correct count
 *         - Opens one grouped embed in fullscreen
 *         - Verifies fullscreen content and website results
 *         - Closes and deletes the chat
 *
 * Console warn/error logs are captured throughout each test and saved to
 * playwright-artifacts/console-warnings-web-search-{testId}.json when any occur.
 * Tests only fail on missing/broken UI state — not on mere warnings.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of an existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA OTP secret (base32) for the test account.
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL for the deployed web app under test.
 */

const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

// ─── Log buckets ─────────────────────────────────────────────────────────────
// All console messages captured for failure diagnostics.
const consoleLogs: string[] = [];
// Only warn / error entries — written to file if non-empty.
const warnErrorLogs: Array<{ timestamp: string; type: string; text: string }> = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	warnErrorLogs.length = 0;
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
	generateTotp,
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl,
	withMockMarker
} = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Save warn/error logs to a JSON file in playwright-artifacts/.
 * Only writes the file if warnErrorLogs is non-empty.
 * Appends a new phase entry to an existing file if it already exists.
 */
function saveWarnErrorLogs(testId: string, phase: string): void {
	if (warnErrorLogs.length === 0) return;

	const artifactsDir = path.resolve(process.cwd(), 'artifacts');
	fs.mkdirSync(artifactsDir, { recursive: true });

	const filePath = path.join(artifactsDir, `console-warnings-web-search-${testId}.json`);

	// Save all console logs to a separate .txt file for context
	const allLogsPath = path.join(artifactsDir, `console-all-logs-web-search-${testId}-${phase}.txt`);
	fs.writeFileSync(allLogsPath, consoleLogs.join('\n'), 'utf8');
	console.log(`All console logs saved to ${allLogsPath}`);

	// Load existing data or start fresh
	let existing: any = {
		test_id: testId,
		test: 'web-search-flow',
		run_timestamp: new Date().toISOString(),
		phases: {},
		total_warn_errors: 0
	};
	try {
		if (fs.existsSync(filePath)) {
			existing = JSON.parse(fs.readFileSync(filePath, 'utf8'));
		}
	} catch {
		// Ignore parse errors — start fresh
	}

	existing.phases[phase] = warnErrorLogs.slice();
	existing.total_warn_errors = Object.values(existing.phases as Record<string, any[]>).reduce(
		(sum: number, entries: any[]) => sum + entries.length,
		0
	);

	fs.writeFileSync(filePath, JSON.stringify(existing, null, 2), 'utf8');
	console.log(
		`[WARN/ERROR LOGS] Saved ${warnErrorLogs.length} entries for phase "${phase}" → ${filePath}`
	);

	// Clear the buffer so the next phase starts fresh
	warnErrorLogs.length = 0;
}

/**
 * Login to the test account with email, password, and 2FA OTP.
 * Checks "Stay logged in" so keys are persisted to IndexedDB.
 * Includes retry logic for OTP timing edge cases.
 */
async function loginToTestAccount(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	await page.goto(getE2EDebugUrl('/'));
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

	// Click "Stay logged in" toggle so keys survive any page navigation during the test.
	// The Toggle component hides the <input> behind a CSS slider; click the visible label.
	const stayLoggedInLabel = page.locator(
		'label.toggle[for="stayLoggedIn"], label.toggle:has(#stayLoggedIn)'
	);
	try {
		await stayLoggedInLabel.waitFor({ state: 'visible', timeout: 3000 });
		const checkbox = page.locator('#stayLoggedIn');
		const isChecked = await checkbox.evaluate((el: HTMLInputElement) => el.checked);
		if (!isChecked) {
			await stayLoggedInLabel.click();
			logCheckpoint('Clicked "Stay logged in" toggle.');
		} else {
			logCheckpoint('"Stay logged in" toggle was already on.');
		}
	} catch {
		logCheckpoint('Could not find "Stay logged in" toggle — proceeding without it.');
	}

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
 * Uses [data-action="send-message"] for a stable selector.
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

	// The send button only appears when the editor has content (hasContent reactive state).
	// Use data-action for a stable selector; wait up to 15s for Svelte reactivity + fly-in animation.
	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 5000 });
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
		const sidebarToggle = page.locator('[data-testid="sidebar-toggle"]');
		if (await sidebarToggle.isVisible()) {
			await sidebarToggle.click();
			await page.waitForTimeout(500);
		}

		const activeChatItem = page.locator('.chat-item-wrapper.active');

		if (!(await activeChatItem.isVisible({ timeout: 5000 }).catch(() => false))) {
			logCheckpoint('No active chat item visible - skipping cleanup.');
			return;
		}

		try {
			const chatTitle = await activeChatItem.locator('.chat-title').textContent();
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
// Test 1: Single web search with fullscreen interaction
// ---------------------------------------------------------------------------

test('single web search with fullscreen, website result click, and button verification', async ({
	page
}: {
	page: any;
}) => {
	// ── Console log listeners ────────────────────────────────────────────────
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		const type = msg.type();
		const text = msg.text();
		consoleLogs.push(`[${timestamp}] [${type}] ${text}`);
		if (type === 'warning' || type === 'error') {
			warnErrorLogs.push({ timestamp, type, text });
		}
	});
	page.on('request', (request: any) => {
		networkActivities.push(`[${new Date().toISOString()}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		networkActivities.push(
			`[${new Date().toISOString()}] << ${response.status()} ${response.url()}`
		);
	});

	test.slow();
	test.setTimeout(300000);

	const logCheckpoint = createSignupLogger('WEB_SEARCH_FULLSCREEN');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'web-search-fullscreen'
	});

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting single web search fullscreen test.', { email: TEST_EMAIL });

	// Login and start a new chat
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	// ======================================================================
	// STEP 1: Send a message that triggers exactly one web search
	// ======================================================================
	const searchQuery = withMockMarker("Search on the web for 'Amadeus API'", 'web_search_single');
	await sendMessage(page, searchQuery, logCheckpoint, takeStepScreenshot, 'single-search');

	// Wait for assistant response
	logCheckpoint('Waiting for assistant response with web search results...');
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 60000 });
	logCheckpoint('Assistant response wrapper is visible.');

	// ======================================================================
	// STEP 2: Verify the web search embed preview appears and finishes
	// ======================================================================
	const webSearchPreview = page.locator(
		'.unified-embed-preview[data-app-id="web"][data-skill-id="search"]'
	);
	logCheckpoint('Waiting for web search embed preview to appear...');
	await expect(webSearchPreview.first()).toBeVisible({ timeout: 90000 });
	await takeStepScreenshot(page, 'search-preview-visible');
	logCheckpoint('Web search embed preview is visible.');

	// Wait for finished state
	const finishedPreview = page.locator(
		'.unified-embed-preview[data-app-id="web"][data-skill-id="search"][data-status="finished"]'
	);
	await expect(finishedPreview.first()).toBeVisible({ timeout: 90000 });
	logCheckpoint('Web search preview reached finished state.');

	// Check + save warn/error logs after search completes
	logCheckpoint(`Console warn/error count after search: ${warnErrorLogs.length}`);
	saveWarnErrorLogs('single-search', 'after_search_finished');

	// Verify preview inner elements
	const searchQueryElement = finishedPreview.first().locator('.search-query');
	await expect(searchQueryElement).toBeVisible({ timeout: 10000 });
	const queryText = await searchQueryElement.textContent();
	logCheckpoint(`Search query displayed on preview: "${queryText}"`);

	const searchProviderElement = finishedPreview.first().locator('.search-provider');
	await expect(searchProviderElement).toBeVisible({ timeout: 5000 });
	logCheckpoint('Search provider label visible on preview.');

	const basicInfosBar = finishedPreview.first().locator('.basic-infos-bar');
	await expect(basicInfosBar).toBeVisible({ timeout: 5000 });
	logCheckpoint('Basic infos bar is visible on the search preview.');

	await takeStepScreenshot(page, 'search-preview-verified');

	// Verify no missing translations on the chat page with search results
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations detected.');

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
	// STEP 4: Verify fullscreen content - header with query and provider
	// EmbedHeader renders as .embed-header; title is .header-title-text; provider is .header-subtitle
	// ======================================================================
	const fullscreenHeader = fullscreenOverlay.locator('.embed-header');
	await expect(fullscreenHeader).toBeVisible({ timeout: 10000 });
	logCheckpoint('Fullscreen header (.embed-header) is visible.');

	const fullscreenQuery = fullscreenHeader.locator('.header-title-text');
	await expect(fullscreenQuery).toBeVisible({ timeout: 5000 });
	const fullscreenQueryText = await fullscreenQuery.textContent();
	logCheckpoint(`Fullscreen search query: "${fullscreenQueryText}"`);
	// The query should contain something related to "Amadeus" (AI may rephrase)
	expect(fullscreenQueryText?.toLowerCase()).toContain('amadeus');

	const fullscreenProvider = fullscreenHeader.locator('.header-subtitle');
	await expect(fullscreenProvider).toBeVisible({ timeout: 5000 });
	const providerText = await fullscreenProvider.textContent();
	logCheckpoint(`Fullscreen provider: "${providerText}"`);
	// Provider should mention "Brave Search" (via Brave Search)
	expect(providerText?.toLowerCase()).toContain('brave');

	// ======================================================================
	// STEP 5: Verify website results grid is rendered with results
	// ======================================================================
	const websiteGrid = fullscreenOverlay.locator('.website-embeds-grid');
	await expect(websiteGrid).toBeVisible({ timeout: 15000 });
	logCheckpoint('Website embeds grid is visible in fullscreen.');

	// Wait for at least one website result to appear in the grid
	const websiteResults = websiteGrid.locator(
		'.unified-embed-preview[data-app-id="web"][data-skill-id="website"]'
	);
	await expect(async () => {
		const count = await websiteResults.count();
		logCheckpoint(`Website results in grid: ${count}`);
		expect(count).toBeGreaterThanOrEqual(1);
	}).toPass({ timeout: 30000 });

	const totalResults = await websiteResults.count();
	logCheckpoint(`Total website results in grid: ${totalResults}`);
	await takeStepScreenshot(page, 'fullscreen-website-grid');

	// ======================================================================
	// STEP 6: Verify fullscreen action buttons exist
	// EmbedTopBar renders buttons with icon_ classes (not semantic button names).
	// icon_minimize = close/minimize, icon_share = share, icon_bug = report issue.
	// ======================================================================
	logCheckpoint('Verifying fullscreen action buttons...');

	const shareButton = fullscreenOverlay.locator('button.icon_share');
	await expect(shareButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Share button (icon_share) is visible.');

	const reportIssueButton = fullscreenOverlay.locator('button.icon_bug');
	await expect(reportIssueButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Report issue button (icon_bug) is visible.');

	const minimizeButton = fullscreenOverlay.locator('button.icon_minimize');
	await expect(minimizeButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Minimize button (icon_minimize) is visible.');

	const topBar = fullscreenOverlay.locator('.embed-top-bar');
	await expect(topBar).toBeVisible({ timeout: 5000 });
	logCheckpoint('EmbedTopBar (.embed-top-bar) is visible in fullscreen.');

	await takeStepScreenshot(page, 'fullscreen-buttons-verified');

	// ======================================================================
	// STEP 7: Click a website result to open the website fullscreen overlay
	// ======================================================================
	logCheckpoint('Clicking first website result to open website fullscreen...');
	await websiteResults.first().click();

	const childOverlay = page.locator('.child-embed-overlay');
	await expect(childOverlay).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(500);
	logCheckpoint('Child embed overlay (website fullscreen) is visible.');
	await takeStepScreenshot(page, 'website-fullscreen-opened');

	// ======================================================================
	// STEP 8: Verify website fullscreen content
	// The website title is rendered in EmbedHeader (.header-title-text) above
	// the .website-fullscreen-content div, not inside it.
	// ======================================================================
	const websiteContent = childOverlay.locator('.website-fullscreen-content');
	await expect(websiteContent).toBeVisible({ timeout: 10000 });
	logCheckpoint('Website fullscreen content is visible.');

	// Title is rendered by EmbedHeader as .header-title-text (outside .website-fullscreen-content)
	const websiteTitle = childOverlay.locator('.header-title-text');
	await expect(websiteTitle).toBeVisible({ timeout: 5000 });
	const titleText = await websiteTitle.textContent();
	logCheckpoint(`Website title: "${titleText}"`);

	// CTA is rendered via embedHeaderCta snippet inside EmbedHeader, not inside .website-fullscreen-content
	const ctaButton = childOverlay.locator('.cta-button');
	await expect(ctaButton).toBeVisible({ timeout: 5000 });
	const ctaText = await ctaButton.textContent();
	logCheckpoint(`CTA button text: "${ctaText}"`);
	expect(ctaText?.toLowerCase()).toContain('open on');

	// ======================================================================
	// STEP 9: Test CTA button opens in new tab
	// ======================================================================
	logCheckpoint('Testing CTA button opens website in new tab...');

	const [newPage] = await Promise.all([
		page.waitForEvent('popup', { timeout: 10000 }),
		ctaButton.click()
	]);
	logCheckpoint(`New tab opened with URL: ${newPage.url()}`);
	await newPage.waitForTimeout(2000);
	const newTabUrl = newPage.url();
	logCheckpoint(`New tab final URL: ${newTabUrl}`);
	expect(newTabUrl).not.toBe('about:blank');
	await newPage.close();
	logCheckpoint('Closed new tab.');

	await takeStepScreenshot(page, 'website-cta-verified');

	// ======================================================================
	// STEP 10: Verify website fullscreen buttons
	// Buttons use icon_ CSS classes in EmbedTopBar (not semantic class names).
	// ======================================================================
	const websiteFullscreen = childOverlay.locator('.unified-embed-fullscreen-overlay');
	const websiteShareButton = websiteFullscreen.locator('button.icon_share');
	await expect(websiteShareButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Website fullscreen share button (icon_share) is visible.');

	const websiteReportButton = websiteFullscreen.locator('button.icon_bug');
	await expect(websiteReportButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Website fullscreen report issue button (icon_bug) is visible.');

	const websiteMinimizeButton = websiteFullscreen.locator('button.icon_minimize');
	await expect(websiteMinimizeButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Website fullscreen minimize button (icon_minimize) is visible.');

	await takeStepScreenshot(page, 'website-buttons-verified');

	// ======================================================================
	// STEP 11: Close website fullscreen overlay via minimize button
	// ======================================================================
	logCheckpoint('Closing website fullscreen via minimize button...');
	await websiteMinimizeButton.click();
	await page.waitForTimeout(500);

	await expect(childOverlay).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Website fullscreen overlay closed.');

	await expect(fullscreenOverlay).toBeVisible({ timeout: 5000 });
	await expect(websiteGrid).toBeVisible({ timeout: 5000 });
	logCheckpoint('Search fullscreen is still visible after closing website overlay.');
	await takeStepScreenshot(page, 'back-to-search-fullscreen');

	// ======================================================================
	// STEP 12: Close search fullscreen via minimize button
	// ======================================================================
	logCheckpoint('Closing search fullscreen via minimize button...');
	const searchMinimizeButton = fullscreenOverlay.locator('button.icon_minimize');
	await searchMinimizeButton.click();
	await page.waitForTimeout(500);

	await expect(fullscreenOverlay).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Search fullscreen closed successfully.');
	await takeStepScreenshot(page, 'fullscreen-closed');

	// Save final warn/error log snapshot
	logCheckpoint(`Final console warn/error count: ${warnErrorLogs.length}`);
	saveWarnErrorLogs('single-search', 'after_fullscreen_closed');

	// ======================================================================
	// STEP 13: Delete the chat
	// ======================================================================
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'single-search-cleanup');
	logCheckpoint('Single web search fullscreen test completed successfully.');
});

// ---------------------------------------------------------------------------
// Test 2: Multiple web searches grouped with fullscreen interaction
// ---------------------------------------------------------------------------

test('multiple web searches are grouped and fullscreen works on grouped items', async ({
	page
}: {
	page: any;
}) => {
	// ── Console log listeners ────────────────────────────────────────────────
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		const type = msg.type();
		const text = msg.text();
		consoleLogs.push(`[${timestamp}] [${type}] ${text}`);
		if (type === 'warning' || type === 'error') {
			warnErrorLogs.push({ timestamp, type, text });
		}
	});
	page.on('request', (request: any) => {
		networkActivities.push(`[${new Date().toISOString()}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		networkActivities.push(
			`[${new Date().toISOString()}] << ${response.status()} ${response.url()}`
		);
	});

	test.slow();
	// Multiple searches + AI response + fullscreen interactions; allow up to 5 minutes.
	test.setTimeout(300000);

	const logCheckpoint = createSignupLogger('WEB_SEARCH_MULTI_FS');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'web-search-multi-fs'
	});

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting multiple web search with fullscreen test.', { email: TEST_EMAIL });

	// Login and start a new chat
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	// ======================================================================
	// STEP 1: Send a message that triggers 3 separate web searches
	// ======================================================================
	const multiSearchQuery =
		'I need you to do 3 separate web searches for me: ' +
		'1) Search for the population of Paris, ' +
		'2) Search for the population of London, ' +
		'3) Search for the population of Berlin. ' +
		'Do all three searches.';
	await sendMessage(page, withMockMarker(multiSearchQuery, 'web_search_multi'), logCheckpoint, takeStepScreenshot, 'multi-search');

	// Wait for assistant response
	logCheckpoint('Waiting for assistant response with multiple web search results...');
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 60000 });
	logCheckpoint('Assistant response wrapper is visible.');

	// ======================================================================
	// STEP 2: Wait for web search embeds to appear and finish
	// ======================================================================
	const webSearchPreview = page.locator(
		'.unified-embed-preview[data-app-id="web"][data-skill-id="search"]'
	);
	logCheckpoint('Waiting for web search embed previews to appear...');
	await expect(webSearchPreview.first()).toBeVisible({ timeout: 90000 });
	logCheckpoint('First web search embed preview is visible.');

	// Wait for at least 2 finished searches (AI may consolidate or some may fail)
	const finishedSearches = page.locator(
		'.unified-embed-preview[data-app-id="web"][data-skill-id="search"][data-status="finished"]'
	);

	logCheckpoint('Waiting for at least 2 finished web search previews...');
	await expect(async () => {
		const count = await finishedSearches.count();
		logCheckpoint(`Currently ${count} finished web search previews.`);
		expect(count).toBeGreaterThanOrEqual(2);
	}).toPass({ timeout: 120000 });

	const totalFinished = await finishedSearches.count();
	logCheckpoint(`Total finished web search previews: ${totalFinished}`);
	await takeStepScreenshot(page, 'multi-search-all-finished');

	// Check + save warn/error logs after searches complete
	logCheckpoint(`Console warn/error count after searches: ${warnErrorLogs.length}`);
	saveWarnErrorLogs('multi-search', 'after_searches_finished');

	// ======================================================================
	// STEP 3: Verify grouping - scroll container and group header
	// ======================================================================
	const groupScrollContainer = page.locator('.group-scroll-container');
	await expect(groupScrollContainer.first()).toBeVisible({ timeout: 15000 });
	logCheckpoint('Group scroll container is visible.');

	const groupItems = groupScrollContainer.first().locator('.embed-group-item');
	await expect(async () => {
		const itemCount = await groupItems.count();
		logCheckpoint(`Group items in scroll container: ${itemCount}`);
		expect(itemCount).toBeGreaterThanOrEqual(2);
	}).toPass({ timeout: 15000 });

	const groupItemCount = await groupItems.count();
	logCheckpoint(`Confirmed ${groupItemCount} items in the group scroll container.`);

	const groupHeader = page.locator('.group-header');
	await expect(groupHeader.first()).toBeVisible({ timeout: 5000 });
	const headerText = await groupHeader.first().textContent();
	logCheckpoint(`Group header text: "${headerText}"`);
	expect(headerText).toMatch(/\d+\s+requests?/i);

	const errorEmbeds = page.locator('.unified-embed-preview[data-status="error"]');
	const errorCount = await errorEmbeds.count();
	logCheckpoint(`Error embeds found (should be 0): ${errorCount}`);
	expect(errorCount).toBe(0);

	const overflowX = await groupScrollContainer.first().evaluate((el: Element) => {
		return window.getComputedStyle(el).overflowX;
	});
	logCheckpoint(`group-scroll-container overflow-x: "${overflowX}"`);
	expect(['auto', 'scroll', 'visible', '']).toContain(overflowX);

	await takeStepScreenshot(page, 'multi-search-group-verified');

	// ======================================================================
	// STEP 4: Verify individual group items have valid content
	// ======================================================================
	let verifiedItems = 0;
	const maxItemsToCheck = Math.min(groupItemCount, 5);
	for (let i = 0; i < maxItemsToCheck && verifiedItems < 2; i++) {
		const item = groupItems.nth(i);
		const preview = item.locator(
			'.unified-embed-preview[data-app-id="web"][data-skill-id="search"]'
		);

		const previewCount = await preview.count();
		if (previewCount === 0) {
			logCheckpoint(`Group item ${i + 1} does not contain a web search preview, skipping.`);
			continue;
		}

		const dataStatus = await preview.getAttribute('data-status');
		logCheckpoint(`Group item ${i + 1} has status "${dataStatus}".`);
		expect(['finished', 'processing']).toContain(dataStatus);

		if (dataStatus !== 'finished') {
			continue;
		}

		const queryEl = preview.locator('.search-query');
		await expect(queryEl).toBeVisible({ timeout: 5000 });
		const itemQuery = await queryEl.textContent();
		logCheckpoint(`Group item ${i + 1} search query: "${itemQuery}"`);

		const providerEl = preview.locator('.search-provider');
		await expect(providerEl).toBeVisible({ timeout: 5000 });
		verifiedItems++;
	}
	expect(verifiedItems).toBeGreaterThanOrEqual(1);

	// ======================================================================
	// STEP 5: Open the first finished grouped embed in fullscreen
	// ======================================================================
	logCheckpoint('Opening first finished grouped embed in fullscreen...');

	let firstFinishedGroupItem: any = null;
	for (let i = 0; i < groupItemCount; i++) {
		const item = groupItems.nth(i);
		const preview = item.locator(
			'.unified-embed-preview[data-app-id="web"][data-skill-id="search"][data-status="finished"]'
		);
		const count = await preview.count();
		if (count > 0) {
			firstFinishedGroupItem = preview;
			logCheckpoint(`Found first finished embed at group item index ${i}.`);
			break;
		}
	}

	expect(firstFinishedGroupItem).not.toBeNull();
	await firstFinishedGroupItem.click();

	const fullscreenOverlay = page.locator('.unified-embed-fullscreen-overlay');
	await expect(fullscreenOverlay).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(500);
	logCheckpoint('Fullscreen overlay is visible for grouped embed.');
	await takeStepScreenshot(page, 'multi-fullscreen-opened');

	// ======================================================================
	// STEP 6: Verify fullscreen content for grouped embed
	// EmbedHeader renders as .embed-header; title is .header-title-text; provider is .header-subtitle
	// ======================================================================
	const fullscreenHeader = fullscreenOverlay.locator('.embed-header');
	await expect(fullscreenHeader).toBeVisible({ timeout: 10000 });

	const fullscreenQuery = fullscreenHeader.locator('.header-title-text');
	await expect(fullscreenQuery).toBeVisible({ timeout: 5000 });
	const fullscreenQueryText = await fullscreenQuery.textContent();
	logCheckpoint(`Grouped fullscreen search query: "${fullscreenQueryText}"`);

	const fullscreenProvider = fullscreenHeader.locator('.header-subtitle');
	await expect(fullscreenProvider).toBeVisible({ timeout: 5000 });

	const websiteGrid = fullscreenOverlay.locator('.website-embeds-grid');
	await expect(websiteGrid).toBeVisible({ timeout: 15000 });

	const websiteResults = websiteGrid.locator(
		'.unified-embed-preview[data-app-id="web"][data-skill-id="website"]'
	);
	await expect(async () => {
		const count = await websiteResults.count();
		logCheckpoint(`Website results in grouped fullscreen grid: ${count}`);
		expect(count).toBeGreaterThanOrEqual(1);
	}).toPass({ timeout: 30000 });

	await takeStepScreenshot(page, 'multi-fullscreen-content-verified');

	// ======================================================================
	// STEP 7: Test buttons in grouped fullscreen
	// Buttons use icon_ CSS classes in EmbedTopBar (not semantic class names).
	// ======================================================================
	const shareButton = fullscreenOverlay.locator('button.icon_share');
	await expect(shareButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Grouped fullscreen share button (icon_share) is visible.');

	const reportIssueButton = fullscreenOverlay.locator('button.icon_bug');
	await expect(reportIssueButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Grouped fullscreen report issue button (icon_bug) is visible.');

	const minimizeButton = fullscreenOverlay.locator('button.icon_minimize');
	await expect(minimizeButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Grouped fullscreen minimize button (icon_minimize) is visible.');

	// ======================================================================
	// STEP 8: Click a website result from the grouped fullscreen
	// ======================================================================
	logCheckpoint('Clicking website result from grouped fullscreen...');
	await websiteResults.first().click();

	const childOverlay = page.locator('.child-embed-overlay');
	await expect(childOverlay).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(500);
	logCheckpoint('Website fullscreen overlay opened from grouped search.');
	await takeStepScreenshot(page, 'multi-website-fullscreen-opened');

	const websiteContent = childOverlay.locator('.website-fullscreen-content');
	await expect(websiteContent).toBeVisible({ timeout: 10000 });

	// Title is rendered by EmbedHeader as .header-title-text (outside .website-fullscreen-content)
	const websiteTitle = childOverlay.locator('.header-title-text');
	await expect(websiteTitle).toBeVisible({ timeout: 5000 });
	const titleText = await websiteTitle.textContent();
	logCheckpoint(`Grouped website title: "${titleText}"`);

	// CTA button is rendered inside .website-fullscreen-content via the embedHeaderCta snippet
	// but the button itself is in EmbedHeader's CTA area, scoped within .embed-header
	const ctaButton = childOverlay.locator('.cta-button');
	await expect(ctaButton).toBeVisible({ timeout: 5000 });
	const ctaText = await ctaButton.textContent();
	logCheckpoint(`Grouped website CTA: "${ctaText}"`);
	expect(ctaText?.toLowerCase()).toContain('open on');

	await takeStepScreenshot(page, 'multi-website-content-verified');

	// ======================================================================
	// STEP 9: Close website overlay, then close search fullscreen
	// ======================================================================
	logCheckpoint('Closing website overlay from grouped search...');
	const websiteMinimize = childOverlay.locator('button.icon_minimize');
	await websiteMinimize.click();
	await page.waitForTimeout(500);
	await expect(childOverlay).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Website overlay closed.');

	await expect(fullscreenOverlay).toBeVisible({ timeout: 5000 });
	logCheckpoint('Search fullscreen still visible after closing website overlay.');

	logCheckpoint('Closing search fullscreen...');
	const searchMinimize = fullscreenOverlay.locator('button.icon_minimize');
	await searchMinimize.click();
	await page.waitForTimeout(500);
	await expect(fullscreenOverlay).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Search fullscreen closed.');
	await takeStepScreenshot(page, 'multi-fullscreen-closed');

	// Save final warn/error log snapshot
	logCheckpoint(`Final console warn/error count: ${warnErrorLogs.length}`);
	saveWarnErrorLogs('multi-search', 'after_fullscreen_closed');

	// ======================================================================
	// STEP 10: Delete the chat
	// ======================================================================
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'multi-search-cleanup');
	logCheckpoint('Multiple web search with fullscreen test completed successfully.');
});
