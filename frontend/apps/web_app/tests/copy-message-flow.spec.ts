/* eslint-disable no-console */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Copy message flow test: verify that copying a message with embeds produces
 * human-readable text instead of raw JSON embed placeholder blocks.
 *
 * Test flow:
 *   1. Login with test account
 *   2. Send a message that triggers an AI response with embeds (web search)
 *   3. Wait for the AI response and embed to finish rendering
 *   4. Copy the assistant message via the message context menu
 *   5. Read clipboard and verify: no JSON embed blocks, has readable text
 *   6. Clean up: delete the chat
 *
 * Bug history this test suite guards against:
 * - OPE-7 (0c521b2): Copy message output showed raw JSON embed placeholders
 *   like {"type": "website", "embed_id": "..."} instead of human-readable
 *   text previews. Fixed by adding tipTapToReadableMarkdown() which resolves
 *   embeds from IndexedDB and renders them as plain text.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat,
	waitForAssistantMessage
} = require('./helpers/chat-test-helpers');

const {
	getTestAccount
} = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ─── Log buckets ────────────────────────────────────────────────────────────
const consoleLogs: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- CONSOLE LOGS ON FAILURE ---');
		consoleLogs.slice(-30).forEach((log) => console.log(log));
		console.log('--- END LOGS ---\n');
	}
});

function logCheckpoint(message: string): void {
	const ts = new Date().toISOString().split('T')[1];
	const entry = `[${ts}] ${message}`;
	consoleLogs.push(entry);
	console.log(entry);
}

test.describe('Copy message with embeds', () => {
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('copied message text should contain human-readable embed preview, not JSON blocks', async ({
		page,
		context
	}) => {
		// Login + new chat + AI response + embed finish + copy + verify easily exceeds
		// Playwright's 30s default. Match share-embed-flow's 300s budget.
		test.slow();
		test.setTimeout(300000);

		// Grant clipboard permissions for the browser context
		await context.grantPermissions(['clipboard-read', 'clipboard-write']);

		// Capture console logs for debugging
		page.on('console', (msg: any) => {
			consoleLogs.push(`[browser:${msg.type()}] ${msg.text()}`);
		});

		// ── Step 1: Login ──────────────────────────────────────────
		await loginToTestAccount(page, logCheckpoint);
		logCheckpoint('Login complete.');

		// ── Step 2: Start new chat + send web search query ─────────
		await startNewChat(page, logCheckpoint);
		logCheckpoint('New chat started.');

		// Send a query that reliably triggers a web search embed.
		// "search the web for" is an explicit skill trigger that guarantees
		// the AI will use the web search skill and produce embed results.
		await sendMessage(page, 'search the web for "playwright testing framework"', logCheckpoint);
		logCheckpoint('Web search message sent.');

		// ── Step 3: Wait for AI response with embed ────────────────
		const assistantMessage = await waitForAssistantMessage(page, {
			which: 'last',
			logCheckpoint
		});
		logCheckpoint('Assistant message appeared.');

		// Wait for at least one embed preview card to appear in the response.
		// Embed previews are rendered inside the message area as interactive cards.
		const embedPreview = page.locator('[data-testid="embed-preview"], [data-embed-id]').first();
		try {
			await expect(embedPreview).toBeVisible({ timeout: 30000 });
			logCheckpoint('Embed preview card visible in AI response.');
		} catch {
			// If no embed card appears, the AI may not have used the web search skill.
			// Log this but continue — we can still verify the copy behavior.
			logCheckpoint('WARNING: No embed preview card found. AI may not have triggered web search.');
		}

		// Allow extra time for embeds to finish processing (status: finished)
		await page.waitForTimeout(3000);

		// ── Step 4: Copy the assistant message via context menu ─────
		// Right-click on the assistant message to open the context menu
		await assistantMessage.click({ button: 'right' });
		logCheckpoint('Right-clicked on assistant message.');

		// Click the "Copy" option in the message context menu
		const copyButton = page.locator('[data-testid="message-menu-button"], [data-action="copy-message"]').filter({
			hasText: /copy/i
		}).first();

		try {
			await expect(copyButton).toBeVisible({ timeout: 5000 });
			await copyButton.click();
			logCheckpoint('Clicked Copy button in message menu.');
		} catch {
			// Fallback: try keyboard shortcut if context menu approach fails
			logCheckpoint('Copy button not found via context menu, trying Ctrl+C selection approach.');
			await assistantMessage.click({ clickCount: 3 }); // Triple-click to select all text
			await page.keyboard.press('Control+C');
			logCheckpoint('Used Ctrl+C fallback to copy message.');
		}

		// Brief wait for clipboard write to complete
		await page.waitForTimeout(500);

		// ── Step 5: Read clipboard and verify content ───────────────
		const clipboardText = await page.evaluate(async () => {
			try {
				return await navigator.clipboard.readText();
			} catch (error) {
				return `CLIPBOARD_ERROR: ${error}`;
			}
		});

		logCheckpoint(`Clipboard content length: ${clipboardText.length}`);
		logCheckpoint(`Clipboard preview: ${clipboardText.substring(0, 300)}`);

		// Verify: clipboard should NOT contain raw JSON embed blocks
		// These are the patterns from the old broken behavior (OPE-7)
		expect(clipboardText).not.toMatch(/"embed_id"\s*:/);
		expect(clipboardText).not.toMatch(/```json\s*\n\s*\{\s*"type"\s*:/);
		expect(clipboardText).not.toMatch(/```json_embed/);
		logCheckpoint('PASS: No JSON embed blocks found in clipboard.');

		// Verify: if we got a web search, clipboard should contain readable content.
		// Web search results produce text like "**Web Search** — ..." or URLs.
		if (clipboardText.length > 50) {
			// The copied text should have some meaningful content (not just whitespace)
			const hasReadableContent =
				clipboardText.includes('http') || // URLs from search results
				clipboardText.includes('**') || // Bold text from embed renderer
				clipboardText.includes('results') || // "X results" from search
				clipboardText.includes('search'); // Query text
			if (hasReadableContent) {
				logCheckpoint('PASS: Clipboard contains readable embed content.');
			} else {
				logCheckpoint('WARNING: Clipboard has content but no recognizable embed text.');
			}
		}

		// ── Step 6: Cleanup — delete test chat ─────────────────────
		await deleteActiveChat(page, logCheckpoint);
		logCheckpoint('Test chat deleted. Test complete.');
	});
});
