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
	generateTotp,
	assertNoMissingTranslations
} = require('./signup-flow-helpers');

/**
 * Embed JSON leak regression test: verify that raw JSON embed references like
 * {"type": "code", "embed_id": "..."} are NOT shown as visible text alongside
 * rendered code embed components.
 *
 * This test:
 * 1. Logs in to the test account
 * 2. Sends a message that triggers code embeds (asks for code examples)
 * 3. Waits for the AI response with code embeds to render
 * 4. Verifies code embed components are visible
 * 5. Checks that NO raw JSON embed references leak into visible text
 * 6. Cleans up by deleting the chat
 *
 * The bug (issue b32b50d6): when markdown-it fails to recognize ```json fences
 * (e.g., inside list items), raw JSON like {"type":"code","embed_id":"..."} was
 * shown alongside the rendered embed component.
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

test('code embeds render without raw JSON embed references leaking', async ({
	page
}: {
	page: any;
}) => {
	// Listen for console logs
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});

	// Listen for network requests
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});

	// Listen for network responses
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	// Allow extra time for login + AI response + embed rendering
	test.setTimeout(180000);

	// Setup logging and screenshots
	const logCheckpoint = createSignupLogger('EMBED_JSON_LEAK');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'embed-json-leak'
	});

	// Pre-test skip checks
	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting embed JSON leak regression test.', { email: TEST_EMAIL });

	// ======================================================================
	// STEP 1: Login
	// ======================================================================
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
				logCheckpoint(`OTP attempt ${attempt} failed, retrying...`);
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

	// ======================================================================
	// STEP 2: Start a new chat
	// ======================================================================
	await page.waitForTimeout(1000);

	const newChatButtonSelectors = ['.new-chat-cta-button', '.icon_create'];
	let clicked = false;
	for (const selector of newChatButtonSelectors) {
		const button = page.locator(selector).first();
		if (await button.isVisible({ timeout: 3000 }).catch(() => false)) {
			logCheckpoint(`Found New Chat button: ${selector}`);
			await button.click();
			clicked = true;
			await page.waitForTimeout(2000);
			break;
		}
	}

	if (!clicked) {
		// On welcome screen, type a space to trigger button, then retry
		if (await messageEditor.isVisible({ timeout: 3000 }).catch(() => false)) {
			await messageEditor.click();
			await page.keyboard.type(' ');
			await page.waitForTimeout(500);
			for (const selector of newChatButtonSelectors) {
				const button = page.locator(selector).first();
				if (await button.isVisible({ timeout: 3000 }).catch(() => false)) {
					await button.click();
					clicked = true;
					await page.waitForTimeout(2000);
					break;
				}
			}
			// Clear the space
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
	logCheckpoint(clicked ? 'Started new chat.' : 'WARNING: Could not click new chat button.');

	// ======================================================================
	// STEP 3: Send a message that triggers code embeds
	// ======================================================================
	// Ask for multiple code examples in a list context — this is the scenario
	// that triggers the embed rendering where markdown-it may fail to parse
	// fenced code blocks inside list items, causing JSON embed refs to leak.
	const testMessage =
		'Write me a numbered list of 3 code examples: ' +
		'1) Hello World in Python, ' +
		'2) Hello World in JavaScript, ' +
		'3) Hello World in Bash. ' +
		'Show each as a code block.';

	const editor = page.locator('.editor-content.prose');
	await expect(editor).toBeVisible();
	await editor.click();
	await page.keyboard.type(testMessage);
	logCheckpoint(`Typed message: "${testMessage}"`);
	await takeStepScreenshot(page, 'message-typed');

	const sendButton = page.locator('.send-button');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logCheckpoint('Clicked send button.');
	await takeStepScreenshot(page, 'message-sent');

	// ======================================================================
	// STEP 4: Wait for chat ID to appear in URL (confirms message was sent)
	// ======================================================================
	logCheckpoint('Waiting for chat ID to appear in URL...');
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const urlAfterSend = page.url();
	const chatIdMatch = urlAfterSend.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
	logCheckpoint(`Chat ID detected: ${chatId}`);

	// ======================================================================
	// STEP 5: Wait for assistant response with code embeds
	// ======================================================================
	logCheckpoint('Waiting for assistant response...');

	// Wait for the assistant message to appear (use last() since demo messages may also exist)
	const assistantMessages = page.locator('.message-wrapper.assistant');
	await expect(assistantMessages.last()).toBeVisible({ timeout: 60000 });
	logCheckpoint('Assistant response wrapper is visible.');

	// Wait for at least one code embed preview to appear in the chat
	const codeEmbeds = page.locator('.message-wrapper.assistant .unified-embed-preview');
	logCheckpoint('Waiting for code embed previews to appear...');
	await expect(async () => {
		const count = await codeEmbeds.count();
		logCheckpoint(`Code embed count: ${count}`);
		expect(count).toBeGreaterThanOrEqual(1);
	}).toPass({ timeout: 90000 });

	const embedCount = await codeEmbeds.count();
	logCheckpoint(`Found ${embedCount} code embed previews.`);

	// Wait for at least one embed to reach finished state
	const finishedEmbeds = page.locator(
		'.message-wrapper.assistant .unified-embed-preview[data-status="finished"]'
	);
	logCheckpoint('Waiting for at least one embed to finish...');
	await expect(async () => {
		const count = await finishedEmbeds.count();
		logCheckpoint(`Finished embed count: ${count}`);
		expect(count).toBeGreaterThanOrEqual(1);
	}).toPass({ timeout: 60000 });

	const finishedCount = await finishedEmbeds.count();
	logCheckpoint(`${finishedCount} embeds reached finished state.`);
	await takeStepScreenshot(page, 'embeds-finished');

	// Wait for the streaming to complete (message status changes from streaming to synced)
	// We detect this by waiting for the typing indicator to disappear
	logCheckpoint('Waiting for AI response to finish streaming...');
	const typingIndicator = page.locator('.typing-indicator');
	await expect(typingIndicator).not.toBeVisible({ timeout: 90000 });
	logCheckpoint('AI response streaming completed.');

	// Extra wait to ensure all embed rendering is complete
	await page.waitForTimeout(3000);

	// ======================================================================
	// STEP 6: THE CRITICAL CHECK - no raw JSON embed references in visible text
	// ======================================================================
	logCheckpoint('Performing critical check: scanning for raw JSON embed references...');
	await takeStepScreenshot(page, 'before-json-check');

	// Get the full text content of the LAST assistant message (the one we triggered)
	// Use .last() to skip any demo chat assistant messages
	const lastAssistantMessage = assistantMessages.last();
	const assistantProseMirror = lastAssistantMessage
		.locator('.read-only-message .ProseMirror')
		.first();
	await expect(assistantProseMirror).toBeVisible({ timeout: 10000 });

	// IMPORTANT: Use page.evaluate() to get text EXCLUDING embed component internals.
	// A plain textContent() call includes text rendered inside .unified-embed-preview
	// components (file names, line counts, language labels), which may contain the embed_id
	// in data attributes or hidden elements. We only want the prose text around embeds.
	const fullText = await assistantProseMirror.evaluate((el: HTMLElement) => {
		const clone = el.cloneNode(true) as HTMLElement;
		// Remove all embed preview components from the clone
		clone.querySelectorAll('.unified-embed-preview').forEach((embed) => embed.remove());
		// Also remove any node-view wrappers that contain embeds
		clone.querySelectorAll('[data-embed-id]').forEach((embed) => embed.remove());
		return clone.textContent || '';
	});
	logCheckpoint(`Full assistant message text (excl. embeds) length: ${fullText?.length}`);
	logCheckpoint(`First 500 chars: ${fullText?.substring(0, 500)}`);

	// Pattern 1: Raw JSON embed references (unfenced)
	// Matches: {"type": "code", "embed_id": "uuid"} or similar
	const jsonEmbedRefPattern = /\{\s*"type"\s*:\s*"[^"]*"\s*,\s*"embed_id"\s*:\s*"[a-f0-9-]+"/gi;
	const jsonMatches = fullText?.match(jsonEmbedRefPattern) || [];

	if (jsonMatches.length > 0) {
		logCheckpoint(
			`FAILURE: Found ${jsonMatches.length} raw JSON embed references in visible text!`
		);
		jsonMatches.forEach((match: string, i: number) => {
			logCheckpoint(`  JSON leak ${i + 1}: ${match}`);
		});
	} else {
		logCheckpoint('SUCCESS: No raw JSON embed references found in visible text.');
	}

	await takeStepScreenshot(page, 'json-leak-check');

	// This is the critical assertion — if any raw JSON embed refs are visible, the bug persists
	expect(jsonMatches.length).toBe(0);

	// Pattern 2: Stray fence markers (```json { ... )
	const fencePattern = /```json\s*\{/gi;
	const fenceMatches = fullText?.match(fencePattern) || [];

	if (fenceMatches.length > 0) {
		logCheckpoint(`WARNING: Found ${fenceMatches.length} stray fence markers in text.`);
	} else {
		logCheckpoint('No stray fence markers found.');
	}

	expect(fenceMatches.length).toBe(0);

	// Verify no missing translations on the chat page with code embeds
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations detected.');

	// ======================================================================
	// STEP 7: Cleanup - navigate away (no UI chat deletion needed)
	// ======================================================================
	// The test chat will be cleaned up naturally. We simply navigate away to
	// avoid leaving the test stuck on a long-running chat page.
	logCheckpoint(`Test assertions passed. Chat ${chatId} created during test.`);
	logCheckpoint('Embed JSON leak regression test completed successfully.');
});
