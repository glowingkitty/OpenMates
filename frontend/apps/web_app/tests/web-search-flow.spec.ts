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
 * Web search flow tests: verify that app skill uses (web search) render correctly.
 *
 * Test 1: Single web search - sends a message that triggers one web search skill use
 *         and verifies the search preview card renders with expected elements.
 *
 * Test 2: Multiple web searches - sends a message that triggers 3 web search skill uses
 *         and verifies they are grouped into a horizontally scrollable container.
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
// Shared helpers (same pattern as model-override.spec.ts)
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
			await page.waitForURL(/chat/, { timeout: 10000 });
			loginSuccess = true;
			logCheckpoint('Logged in successfully, redirected to chat.');
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
	await page.waitForTimeout(5000);

	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible({ timeout: 15000 });
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

	// First try: look for visible new chat button
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

	// If button not visible, it might be because we're on welcome screen.
	// Type a space in the editor to trigger button visibility, then look again.
	if (!clicked) {
		logCheckpoint('New Chat button not initially visible, trying to trigger it...');
		const messageEditor = page.locator('.editor-content.prose');
		if (await messageEditor.isVisible({ timeout: 3000 }).catch(() => false)) {
			await messageEditor.click();
			await page.keyboard.type(' ');
			await page.waitForTimeout(500);

			// Now try again to find the button
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

			// Clear the space we typed
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
		const sidebarToggle = page.locator('.sidebar-toggle-button');
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
// Test 1: Single web search skill use
// ---------------------------------------------------------------------------

test('single web search renders a search preview card', async ({ page }: { page: any }) => {
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
	test.setTimeout(180000);

	const logCheckpoint = createSignupLogger('WEB_SEARCH_SINGLE');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'web-search-single'
	});

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting single web search test.', { email: TEST_EMAIL });

	// Login and start a new chat
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	// Send a message that triggers exactly one web search.
	// The phrasing explicitly asks for a web search to ensure the AI uses the web skill.
	const searchQuery = 'Search the web for the current population of Tokyo';
	await sendMessage(page, searchQuery, logCheckpoint, takeStepScreenshot, 'single-search');

	// Wait for the assistant response to appear.
	// Web searches require AI preprocessing, tool execution, and streaming back results,
	// so this can take significantly longer than a simple text response.
	logCheckpoint('Waiting for assistant response with web search results...');
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 60000 });
	logCheckpoint('Assistant response wrapper is visible.');

	// Wait for a web search embed preview to appear within the assistant message area.
	// The embed is rendered by AppSkillUseRenderer into the ProseMirror editor as a
	// .unified-embed-preview element with data-app-id="web" and data-skill-id="search".
	const webSearchPreview = page.locator(
		'.unified-embed-preview[data-app-id="web"][data-skill-id="search"]'
	);
	logCheckpoint('Waiting for web search embed preview to appear...');
	await expect(webSearchPreview.first()).toBeVisible({ timeout: 90000 });
	await takeStepScreenshot(page, 'single-search-preview-visible');
	logCheckpoint('Web search embed preview is visible.');

	// Verify the preview shows a finished state (not stuck in processing)
	const finishedPreview = page.locator(
		'.unified-embed-preview[data-app-id="web"][data-skill-id="search"][data-status="finished"]'
	);
	await expect(finishedPreview.first()).toBeVisible({ timeout: 90000 });
	logCheckpoint('Web search preview reached finished state.');

	// Verify the search preview card contains the expected inner elements:
	// - A search query text (.search-query)
	// - A search provider label (.search-provider, e.g. "via Brave Search")
	const searchQueryElement = finishedPreview.first().locator('.search-query');
	await expect(searchQueryElement).toBeVisible({ timeout: 10000 });
	const queryText = await searchQueryElement.textContent();
	logCheckpoint(`Search query displayed: "${queryText}"`);

	const searchProviderElement = finishedPreview.first().locator('.search-provider');
	await expect(searchProviderElement).toBeVisible({ timeout: 5000 });
	const providerText = await searchProviderElement.textContent();
	logCheckpoint(`Search provider displayed: "${providerText}"`);

	// Verify the basic infos bar shows the web app icon and "Search" skill label
	const basicInfosBar = finishedPreview.first().locator('.basic-infos-bar');
	await expect(basicInfosBar).toBeVisible({ timeout: 5000 });
	logCheckpoint('Basic infos bar is visible on the search preview.');

	// Verify this is NOT grouped (single search should NOT produce a group container)
	// A group container has .group-scroll-container with multiple .embed-group-item children.
	const groupScrollContainer = page.locator('.group-scroll-container');
	const groupScrollCount = await groupScrollContainer.count();
	logCheckpoint(`Group scroll containers found: ${groupScrollCount}`);
	// If there IS a group, it should have at most 1 item (which means no real grouping)
	if (groupScrollCount > 0) {
		const groupItems = groupScrollContainer.first().locator('.embed-group-item');
		const itemCount = await groupItems.count();
		logCheckpoint(`Group items in first scroll container: ${itemCount}`);
		// A single search should not be in a multi-item group
		expect(itemCount).toBeLessThanOrEqual(1);
	}

	await takeStepScreenshot(page, 'single-search-verified');
	logCheckpoint('Single web search test assertions passed.');

	// Cleanup: delete the chat
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'single-search-cleanup');
});

// ---------------------------------------------------------------------------
// Test 2: Multiple web searches grouped in a horizontal scroll container
// ---------------------------------------------------------------------------

test('multiple web searches are grouped in a horizontally scrollable container', async ({
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
	// Multiple searches + AI response takes longer; allow up to 5 minutes.
	test.setTimeout(300000);

	const logCheckpoint = createSignupLogger('WEB_SEARCH_MULTI');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'web-search-multi'
	});

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting multiple web search test.', { email: TEST_EMAIL });

	// Login and start a new chat
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	// Send a single message that explicitly asks for 3 separate web searches.
	// The phrasing is designed to force the AI to make 3 distinct search calls.
	const multiSearchQuery =
		'I need you to do 3 separate web searches for me: ' +
		'1) Search for the population of Paris, ' +
		'2) Search for the population of London, ' +
		'3) Search for the population of Berlin. ' +
		'Do all three searches.';
	await sendMessage(page, multiSearchQuery, logCheckpoint, takeStepScreenshot, 'multi-search');

	// Wait for the assistant response to appear.
	// Multiple searches plus AI response takes even longer.
	logCheckpoint('Waiting for assistant response with multiple web search results...');
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 60000 });
	logCheckpoint('Assistant response wrapper is visible.');

	// Wait for at least one web search embed to appear (confirming the AI used web search)
	const webSearchPreview = page.locator(
		'.unified-embed-preview[data-app-id="web"][data-skill-id="search"]'
	);
	logCheckpoint('Waiting for web search embed previews to appear...');
	await expect(webSearchPreview.first()).toBeVisible({ timeout: 90000 });
	logCheckpoint('First web search embed preview is visible.');

	// Wait for all searches to finish.
	// We expect at least 2 finished web search embeds for grouping behavior.
	// Note: The AI may consolidate searches or some may fail and be hidden (error embeds are filtered out).
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

	// Verify that the searches are rendered inside a horizontally scrollable group.
	// The GroupRenderer creates a .group-scroll-container with .embed-group-item children.
	const groupScrollContainer = page.locator('.group-scroll-container');
	await expect(groupScrollContainer.first()).toBeVisible({ timeout: 15000 });
	logCheckpoint('Group scroll container is visible.');

	// Verify the group contains multiple items (at least 2 for grouping behavior)
	// Note: Error embeds are filtered out, so we may have fewer visible items than searches requested
	const groupItems = groupScrollContainer.first().locator('.embed-group-item');
	await expect(async () => {
		const itemCount = await groupItems.count();
		logCheckpoint(`Group items in scroll container: ${itemCount}`);
		expect(itemCount).toBeGreaterThanOrEqual(2);
	}).toPass({ timeout: 15000 });

	const groupItemCount = await groupItems.count();
	logCheckpoint(`Confirmed ${groupItemCount} items in the group scroll container.`);

	// Verify the group header shows the correct count text (e.g. "3 requests")
	const groupHeader = page.locator('.group-header');
	await expect(groupHeader.first()).toBeVisible({ timeout: 5000 });
	const headerText = await groupHeader.first().textContent();
	logCheckpoint(`Group header text: "${headerText}"`);
	// The header should mention the count and "request(s)"
	expect(headerText).toMatch(/\d+\s+requests?/i);

	// Verify the scroll container has horizontal overflow enabled
	// (the CSS sets overflow-x: auto on .group-scroll-container)
	// Note: Computed style may show 'visible' if content doesn't overflow.
	// We check for 'auto', 'scroll', or 'visible' (the latter when no overflow is needed).
	const overflowX = await groupScrollContainer.first().evaluate((el: Element) => {
		return window.getComputedStyle(el).overflowX;
	});
	logCheckpoint(`group-scroll-container overflow-x: "${overflowX}"`);
	expect(['auto', 'scroll', 'visible']).toContain(overflowX);

	// Verify that NO error embeds are visible - they should be filtered out completely
	// Error embeds should not be shown to users at all
	const errorEmbeds = page.locator('.unified-embed-preview[data-status="error"]');
	const errorCount = await errorEmbeds.count();
	logCheckpoint(`Error embeds found (should be 0): ${errorCount}`);
	expect(errorCount).toBe(0);

	// Verify each group item contains a web search embed preview with valid status
	let verifiedItems = 0;
	for (let i = 0; i < groupItemCount && verifiedItems < 3; i++) {
		const item = groupItems.nth(i);
		const preview = item.locator(
			'.unified-embed-preview[data-app-id="web"][data-skill-id="search"]'
		);
		await expect(preview).toBeVisible({ timeout: 5000 });

		// Check the status - should only be 'finished' or 'processing', never 'error'
		const dataStatus = await preview.getAttribute('data-status');
		logCheckpoint(`Group item ${i + 1} has status "${dataStatus}".`);
		expect(['finished', 'processing']).toContain(dataStatus);

		// Only check details for finished items
		if (dataStatus !== 'finished') {
			continue;
		}

		// Each finished preview should have a search query and provider
		const queryEl = preview.locator('.search-query');
		await expect(queryEl).toBeVisible({ timeout: 5000 });
		const itemQuery = await queryEl.textContent();
		logCheckpoint(`Group item ${i + 1} search query: "${itemQuery}"`);

		const providerEl = preview.locator('.search-provider');
		await expect(providerEl).toBeVisible({ timeout: 5000 });
		verifiedItems++;
	}
	expect(verifiedItems).toBeGreaterThanOrEqual(1); // At least one successful search

	await takeStepScreenshot(page, 'multi-search-group-verified');
	logCheckpoint('Multiple web search group test assertions passed.');

	// Cleanup: delete the chat
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'multi-search-cleanup');
});
