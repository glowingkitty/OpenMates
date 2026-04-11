/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Webhook Incoming Chat — End-to-End
 *
 * Validates the full incoming-webhook flow:
 *   1. User creates a webhook key in Settings › Developers › Webhooks
 *   2. External service POSTs {"message": "..."} to /v1/webhooks/incoming
 *   3. Backend pre-creates the chat, broadcasts a `webhook_chat` WS event
 *      with plaintext content, and unconditionally dispatches the AI
 *   4. Frontend handler (chatSyncServiceHandlersWebhooks) generates a chat key,
 *      encrypts + persists, surfaces the new chat in the sidebar
 *   5. AI ask-skill streams an assistant response into the chat
 *   6. User sees both messages and can interact with the chat normally
 *
 * Polling strategy mirrors reminder-new-chat.spec.ts: wait for the sidebar
 * item count to increase, then open the new chat and assert system + assistant
 * messages are visible.
 *
 * Architecture: docs/architecture/webhooks.md
 *
 * REQUIRED ENV VARS:
 *   OPENMATES_TEST_ACCOUNT_EMAIL
 *   OPENMATES_TEST_ACCOUNT_PASSWORD
 *   OPENMATES_TEST_ACCOUNT_OTP_KEY
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
	getTestAccount
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const API_BASE_URL = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';

// ─── Helpers ────────────────────────────────────────────────────────────────

/**
 * Navigate to Settings › Developers › Webhooks. Returns when the
 * webhooks-container element is visible.
 */
async function navigateToWebhooks(page: any, log: (msg: string) => void): Promise<void> {
	const profileContainer = page.locator('#settings-menu-toggle');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();
	log('Opened settings menu.');

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });

	const developersItem = settingsMenu.getByRole('menuitem', { name: /developers/i }).first();
	await expect(developersItem).toBeVisible({ timeout: 10000 });
	await developersItem.click();
	log('Navigated to Developers.');

	await page.waitForTimeout(1000);
	const webhooksItem = settingsMenu
		.getByRole('menuitem')
		.filter({ hasText: /^webhooks$/i })
		.first();
	const webhooksItemFallback = settingsMenu
		.getByRole('menuitem')
		.filter({ hasText: /webhook/i })
		.first();
	const webhooksVisible = await webhooksItem.isVisible({ timeout: 5000 }).catch(() => false);
	const target = webhooksVisible ? webhooksItem : webhooksItemFallback;
	await expect(target).toBeVisible({ timeout: 10000 });
	await target.click();
	log('Navigated to Webhooks.');

	const webhooksContainer = page.getByTestId('webhooks-container');
	await expect(webhooksContainer).toBeVisible({ timeout: 15000 });
	log('Webhooks page loaded.');
}

/**
 * Delete leftover E2E webhook items from previous runs (best-effort).
 */
async function cleanupStaleE2EWebhooks(page: any, log: (msg: string) => void): Promise<void> {
	for (let i = 0; i < 10; i++) {
		const stale = page
			.getByTestId('webhook-item')
			.filter({ has: page.getByTestId('webhook-name').filter({ hasText: /E2E/i }) })
			.first();
		if (!(await stale.isVisible({ timeout: 1500 }).catch(() => false))) break;
		const deleteBtn = stale.getByTestId('webhook-delete-button');
		if (!(await deleteBtn.isVisible({ timeout: 1500 }).catch(() => false))) break;
		page.once('dialog', (dialog: any) => dialog.accept());
		await deleteBtn.click();
		await page.waitForTimeout(1000);
		log('Deleted a stale E2E webhook.');
	}
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test('webhook — create key, POST to /incoming, new chat appears with AI response', async ({
	page,
	request
}: {
	page: any;
	request: any;
}) => {
	attachConsoleListeners(page);
	attachNetworkListeners(page);
	test.slow();
	test.setTimeout(420000); // 7 min — covers AI streaming

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('WEBHOOK_INCOMING_CHAT');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	// ── Phase 1: Login ────────────────────────────────────────────────────────
	await loginToTestAccount(page, log, screenshot, { waitForEditor: false });
	await page.waitForTimeout(2000);
	log('Logged in.');

	// ── Phase 2: Create a webhook key ────────────────────────────────────────
	await navigateToWebhooks(page, log);
	await screenshot(page, 'webhooks-page');

	await cleanupStaleE2EWebhooks(page, log);

	const createButton = page.getByTestId('webhook-create-button');
	await expect(createButton).toBeVisible({ timeout: 5000 });
	await expect(createButton).toBeEnabled();
	await createButton.click();
	log('Clicked Create Webhook.');

	const keyName = `E2E-Webhook-${Date.now()}`;
	const nameInput = page.getByTestId('webhook-name-input');
	await expect(nameInput).toBeVisible({ timeout: 5000 });
	await nameInput.fill(keyName);
	log(`Entered webhook name: "${keyName}"`);

	const confirmButton = page.getByTestId('webhook-create-confirm-button');
	await expect(confirmButton).toBeEnabled({ timeout: 3000 });
	await confirmButton.click();
	log('Clicked Create confirm.');

	// Capture the raw key from the "show created key" modal
	const createdKeyEl = page.getByTestId('webhook-created-value');
	await expect(createdKeyEl).toBeVisible({ timeout: 15000 });
	await screenshot(page, 'webhook-key-created');

	const rawWebhookKey = (await createdKeyEl.textContent())?.trim() ?? '';
	expect(rawWebhookKey).toMatch(/^wh-[A-Za-z0-9]{40,}$/);
	log(`Captured webhook key: "${rawWebhookKey.slice(0, 12)}..."`);

	// Dismiss the key-reveal modal
	const doneButton = page.getByRole('button', { name: /i'?ve copied the key|done/i }).first();
	if (await doneButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		await doneButton.click();
		log('Dismissed key modal.');
	}
	await page.waitForTimeout(1000);

	// Close the settings menu so the sidebar is visible for the new chat
	const closeIcon = page
		.locator('#settings-menu-toggle [data-testid="close-icon-container"].visible')
		.first();
	if (await closeIcon.isVisible({ timeout: 1500 }).catch(() => false)) {
		await closeIcon.click();
		await page.waitForTimeout(500);
	}

	// ── Phase 3: POST to the incoming endpoint ───────────────────────────────
	const webhookMessage = `Webhook E2E test ${Date.now()} — please reply with the word "acknowledged".`;
	log(`POSTing to ${API_BASE_URL}/v1/webhooks/incoming...`);
	const incomingResponse = await request.post(`${API_BASE_URL}/v1/webhooks/incoming`, {
		headers: {
			Authorization: `Bearer ${rawWebhookKey}`,
			'Content-Type': 'application/json',
			Origin: 'https://app.dev.openmates.org'
		},
		data: { message: webhookMessage }
	});
	log(`Incoming endpoint responded: ${incomingResponse.status()}`);
	expect(incomingResponse.status()).toBe(200);

	const respJson = await incomingResponse.json();
	expect(respJson).toHaveProperty('chat_id');
	expect(respJson.status).toBe('processing');
	const expectedChatId: string = respJson.chat_id;
	log(`Backend created chat ${expectedChatId}, status=${respJson.status}`);

	// ── Phase 4: Navigate directly to the new chat via its URL ───────────────
	// At the default Playwright viewport (1280×720) the chat sidebar is closed,
	// so chat-item-wrapper elements are not rendered. We already have the
	// chat_id from the POST response — give the WS event a few seconds to
	// propagate to the browser (handler creates the chat in IndexedDB), then
	// navigate directly.
	log('Waiting for webhook_chat WS event to propagate to the browser...');
	await page.waitForTimeout(8000);

	const currentFullUrl = page.url();
	const originAndPath = currentFullUrl.split('#')[0];
	const newChatUrl = `${originAndPath}#chat-id=${expectedChatId}`;
	log(`Navigating to webhook chat: ${newChatUrl}`);
	await page.goto(newChatUrl);
	await page.waitForTimeout(3000);
	await screenshot(page, 'webhook-chat-opened');

	// ── Phase 6: Assert the system message is visible ────────────────────────
	const systemMsg = page.getByTestId('message-system');
	await expect(async () => {
		expect(await systemMsg.count()).toBeGreaterThan(0);
	}).toPass({ timeout: 30000, intervals: [2000] });

	const sysText = await systemMsg.first().textContent();
	log(`System message text: "${sysText?.substring(0, 200)}"`);
	expect(sysText || '').toContain('Webhook E2E test');
	log('System message verified — webhook content rendered correctly.');

	// ── Phase 7: Assert the AI assistant response streams in ─────────────────
	const assistantMsgs = page.getByTestId('message-assistant');
	await expect(async () => {
		expect(await assistantMsgs.count()).toBeGreaterThanOrEqual(1);
	}).toPass({ timeout: 180000, intervals: [3000] });
	log('AI assistant response received.');
	await screenshot(page, 'webhook-chat-ai-responded');

	// ── Phase 8: Cleanup ─────────────────────────────────────────────────────
	// Delete the chat (currently active)
	try {
		const sidebarToggle = page.locator('[data-testid="sidebar-toggle"]');
		if (await sidebarToggle.isVisible({ timeout: 1000 }).catch(() => false)) {
			await sidebarToggle.click();
			await page.waitForTimeout(500);
		}
		const activeChatItem = page.locator('[data-testid="chat-item-wrapper"].active');
		if (await activeChatItem.isVisible({ timeout: 5000 }).catch(() => false)) {
			await activeChatItem.click({ button: 'right' });
			const deleteBtn = page.getByTestId('chat-context-delete');
			if (await deleteBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
				await deleteBtn.click();
				await deleteBtn.click();
				log('Deleted webhook chat.');
			}
		}
	} catch (e) {
		log(`Chat cleanup skipped: ${e}`);
	}

	// Delete the webhook key we created
	try {
		await navigateToWebhooks(page, log);
		const ourWebhook = page
			.getByTestId('webhook-item')
			.filter({ has: page.getByTestId('webhook-name').filter({ hasText: keyName }) })
			.first();
		if (await ourWebhook.isVisible({ timeout: 5000 }).catch(() => false)) {
			page.once('dialog', (dialog: any) => dialog.accept());
			await ourWebhook.getByTestId('webhook-delete-button').click();
			await page.waitForTimeout(1500);
			log(`Deleted webhook key "${keyName}".`);
		}
	} catch (e) {
		log(`Webhook cleanup skipped: ${e}`);
	}

	log('PASSED.');
});
