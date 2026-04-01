/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Message Sync Test: Verifies that all messages are correctly synced between 
 * client (IndexedDB) and server (Directus).
 * 
 * This test specifically targets the issue where the second user message
 * was missing from the client while present on the server.
 * 
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of an existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA OTP secret (base32) for the test account.
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL for the deployed web app under test.
 */
export {};

const { test, expect } = require('@playwright/test');
const { skipWithoutCredentials } = require('./helpers/env-guard');

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
		consoleLogs.slice(-50).forEach(log => console.log(log));
		
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-30).forEach(activity => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

/**
 * Helper function to run inspectChat in the browser and return the result
 * Uses the window.inspectChat debug utility
 */
async function inspectChatInBrowser(page: any, chatId: string): Promise<any> {
	return await page.evaluate(async (id: string) => {
		// Access the debug utility exposed on window
		const inspectChat = (window as any).inspectChat;
		if (!inspectChat) {
			return { error: 'inspectChat not available on window' };
		}
		return await inspectChat(id);
	}, chatId);
}

/**
 * Helper function to get messages_v and message count from IndexedDB
 * Includes detailed message info for debugging
 */
async function getMessageStats(page: any, chatId: string): Promise<{ 
	messages_v: number; 
	messageCount: number; 
	roles: Record<string, number>;
	messageDetails: Array<{ message_id: string; role: string; status: string; created_at: number }>;
}> {
	return await page.evaluate(async (id: string) => {
		const DB_NAME = 'chats_db';
		const CHATS_STORE = 'chats';
		const MESSAGES_STORE = 'messages';

		const openDB = (): Promise<IDBDatabase> => {
			return new Promise((resolve, reject) => {
				const request = indexedDB.open(DB_NAME);
				request.onerror = () => reject(request.error);
				request.onsuccess = () => resolve(request.result);
			});
		};

		const db = await openDB();
		
		// Get chat metadata
		const chatMeta = await new Promise<any>((resolve, reject) => {
			const tx = db.transaction(CHATS_STORE, 'readonly');
			const store = tx.objectStore(CHATS_STORE);
			const request = store.get(id);
			request.onerror = () => reject(request.error);
			request.onsuccess = () => resolve(request.result);
		});

		// Get messages
		const messages = await new Promise<any[]>((resolve, reject) => {
			const tx = db.transaction(MESSAGES_STORE, 'readonly');
			const store = tx.objectStore(MESSAGES_STORE);
			const index = store.index('chat_id');
			const request = index.getAll(id);
			request.onerror = () => reject(request.error);
			request.onsuccess = () => resolve(request.result || []);
		});

		db.close();

		// Count roles and collect details
		const roles: Record<string, number> = {};
		const messageDetails: Array<{ message_id: string; role: string; status: string; created_at: number }> = [];
		
		for (const msg of messages) {
			const role = msg.role || 'unknown';
			roles[role] = (roles[role] || 0) + 1;
			messageDetails.push({
				message_id: msg.message_id,
				role: msg.role,
				status: msg.status,
				created_at: msg.created_at
			});
		}

		return {
			messages_v: chatMeta?.messages_v || 0,
			messageCount: messages.length,
			roles,
			messageDetails
		};
	}, chatId);
}

/**
 * Wait for IndexedDB to have expected message count for a chat
 * Polls until the expected count is reached or timeout
 */
async function waitForMessageCount(
	page: any, 
	chatId: string, 
	expectedCount: number, 
	timeoutMs: number = 10000
): Promise<{ messages_v: number; messageCount: number; roles: Record<string, number>; messageDetails: any[] }> {
	const startTime = Date.now();
	let lastStats = await getMessageStats(page, chatId);
	
	while (lastStats.messageCount < expectedCount && (Date.now() - startTime) < timeoutMs) {
		await page.waitForTimeout(500);
		lastStats = await getMessageStats(page, chatId);
	}
	
	return lastStats;
}

test('message sync: verifies all messages are synced after sending multiple messages', async ({ page }: { page: any }) => {
	// Listen for console logs - filter for sync-related messages
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		const text = msg.text();
		// Capture all logs but especially sync-related ones
		if (text.includes('SYNC') || text.includes('messages_v') || text.includes('saveMessage') || 
		    text.includes('DB SAVE') || text.includes('confirmed') || text.includes('ChatSyncService')) {
			consoleLogs.push(`[${timestamp}] [${msg.type()}] ${text}`);
		}
	});

	// Listen for WebSocket messages (for debugging sync events)
	page.on('websocket', (ws: any) => {
		ws.on('framesent', (frame: any) => {
			const timestamp = new Date().toISOString();
			networkActivities.push(`[${timestamp}] WS SENT: ${frame.payload?.substring(0, 200)}...`);
		});
		ws.on('framereceived', (frame: any) => {
			const timestamp = new Date().toISOString();
			const payload = frame.payload?.substring(0, 200) || '';
			if (payload.includes('message') || payload.includes('confirmed') || payload.includes('sync')) {
				networkActivities.push(`[${timestamp}] WS RECV: ${payload}...`);
			}
		});
	});

	test.slow();
	test.setTimeout(180000); // 3 minutes for multiple message exchanges

	const logCheckpoint = createSignupLogger('MSG_SYNC');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

	// Pre-test skip checks
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);

	logCheckpoint('Starting message sync test.', { email: TEST_EMAIL });

	// =========================================================================
	// STEP 1: Login (via shared helper with OTP retry + clock-drift compensation)
	// =========================================================================
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	logCheckpoint('Redirected to chat page.');

	// Wait for initial sync to complete
	await page.waitForTimeout(3000);

	// =========================================================================
	// STEP 2: Start a new chat
	// =========================================================================
	const newChatButton = page.getByTestId('new-chat-button');
	if (await newChatButton.isVisible()) {
		logCheckpoint('Clicking New Chat button.');
		await newChatButton.click();
		await page.waitForTimeout(2000);
	}
	await takeStepScreenshot(page, '05-new-chat');

	// =========================================================================
	// STEP 3: Send first user message
	// =========================================================================
	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type('What is 2 + 2?');
	await takeStepScreenshot(page, '06-first-message-typed');

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logCheckpoint('Sent first message: "What is 2 + 2?"');
	await takeStepScreenshot(page, '07-first-message-sent');

	// Wait for chat ID to appear in URL
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const urlAfterFirstMessage = page.url();
	const chatIdMatch = urlAfterFirstMessage.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
	logCheckpoint(`Chat ID detected: ${chatId}`);

	// Wait for first AI response
	logCheckpoint('Waiting for first AI response...');
	const assistantResponse = page.getByTestId('message-assistant');
	await expect(assistantResponse.last()).toContainText('4', { timeout: 45000 });
	await takeStepScreenshot(page, '08-first-response-received');
	logCheckpoint('Received first AI response containing "4".');

	// Wait for IndexedDB to have the expected message count (1 user + 1 assistant = 2)
	// This handles async save operations that might not be complete when UI shows the response
	const statsAfterFirst = await waitForMessageCount(page, chatId, 2, 10000);
	logCheckpoint('Message stats after first exchange:', statsAfterFirst);
	console.log('📊 After first exchange:', JSON.stringify(statsAfterFirst));
	console.log('📋 Message details after first exchange:', JSON.stringify(statsAfterFirst.messageDetails, null, 2));

	// Verify: Should have 1 user message and 1 assistant message
	// If there are more than expected, log the details for debugging
	if (statsAfterFirst.messageCount !== 2) {
		console.error('❌ Unexpected message count! Expected 2, got', statsAfterFirst.messageCount);
		console.error('Message IDs:', statsAfterFirst.messageDetails.map(m => `${m.role}:${m.message_id}`));
	}
	expect(statsAfterFirst.messageCount).toBe(2);
	expect(statsAfterFirst.roles['user']).toBe(1);
	expect(statsAfterFirst.roles['assistant']).toBe(1);

	// =========================================================================
	// STEP 4: Send second user message
	// =========================================================================
	await page.waitForTimeout(2000); // Wait for UI to stabilize

	await messageEditor.click();
	await page.keyboard.type('Now multiply that by 10');
	await takeStepScreenshot(page, '09-second-message-typed');

	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logCheckpoint('Sent second message: "Now multiply that by 10"');
	await takeStepScreenshot(page, '10-second-message-sent');

	// CRITICAL CHECK: Wait for the user message to be saved locally
	// We expect 3 messages now: 1 user + 1 assistant + 1 user = 3
	const statsAfterSecondSend = await waitForMessageCount(page, chatId, 3, 10000);
	logCheckpoint('Message stats after second send:', statsAfterSecondSend);
	console.log('📊 After second send (before AI response):', JSON.stringify(statsAfterSecondSend));
	console.log('📋 Message details after second send:', JSON.stringify(statsAfterSecondSend.messageDetails, null, 2));

	// Should now have 2 user messages (even before AI responds)
	expect(statsAfterSecondSend.roles['user']).toBe(2);

	// Wait for second AI response
	logCheckpoint('Waiting for second AI response...');
	await expect(assistantResponse.last()).toContainText('40', { timeout: 45000 });
	await takeStepScreenshot(page, '11-second-response-received');
	logCheckpoint('Received second AI response containing "40".');

	// =========================================================================
	// STEP 5: Verify final message state
	// =========================================================================
	// Wait for all 4 messages to be saved: 2 user + 2 assistant
	const finalStats = await waitForMessageCount(page, chatId, 4, 15000);
	logCheckpoint('Final message stats:', finalStats);
	console.log('📊 Final stats:', JSON.stringify(finalStats));
	console.log('📋 Final message details:', JSON.stringify(finalStats.messageDetails, null, 2));

	// CRITICAL VERIFICATION: All 4 messages should be present
	// 1. User message 1
	// 2. Assistant response 1
	// 3. User message 2 ← This was missing in the bug
	// 4. Assistant response 2
	if (finalStats.messageCount < 4) {
		console.error('❌ Unexpected final message count! Expected >= 4, got', finalStats.messageCount);
		console.error('Message IDs:', finalStats.messageDetails.map(m => `${m.role}:${m.message_id}`));
	}
	// At least 4 messages: 2 user + 2 assistant. A system message or tool-call
	// message may push the count to 5 — that is acceptable as long as the core
	// user/assistant messages are present.
	expect(finalStats.messageCount).toBeGreaterThanOrEqual(4);
	expect(finalStats.roles['user']).toBe(2);
	expect(finalStats.roles['assistant']).toBeGreaterThanOrEqual(2);
	
	// messages_v should match message count (or be higher for server-side versioning)
	expect(finalStats.messages_v).toBeGreaterThanOrEqual(4);

	// Run full inspection for debugging
	const inspectionResult = await inspectChatInBrowser(page, chatId);
	console.log('📋 Full chat inspection result:');
	console.log(inspectionResult);

	// Verify no missing translations on the chat page
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations detected.');

	// =========================================================================
	// STEP 6: Page refresh and verify persistence
	// =========================================================================
	logCheckpoint('Refreshing page to verify persistence...');
	await page.reload();
	await page.waitForTimeout(5000); // Wait for phased sync

	// Navigate back to the chat
	await page.goto(`${process.env.PLAYWRIGHT_TEST_BASE_URL}/chat?chat-id=${chatId}`);
	
	// Wait for messages to be loaded after navigation (should have all 4)
	const statsAfterRefresh = await waitForMessageCount(page, chatId, 4, 15000);
	await takeStepScreenshot(page, '12-after-refresh');
	logCheckpoint('Message stats after page refresh:', statsAfterRefresh);
	console.log('📊 After refresh:', JSON.stringify(statsAfterRefresh));
	console.log('📋 Message details after refresh:', JSON.stringify(statsAfterRefresh.messageDetails, null, 2));

	// CRITICAL: After refresh, all messages should still be present
	expect(statsAfterRefresh.messageCount).toBeGreaterThanOrEqual(4);
	expect(statsAfterRefresh.roles['user']).toBe(2);
	expect(statsAfterRefresh.roles['assistant']).toBeGreaterThanOrEqual(2);

	// =========================================================================
	// STEP 7: Cleanup - delete the test chat
	// =========================================================================
	logCheckpoint('Cleaning up - deleting test chat...');
	
	const sidebarToggle = page.locator('[data-testid="sidebar-toggle"]');
	if (await sidebarToggle.isVisible()) {
		await sidebarToggle.click();
		await page.waitForTimeout(500);
	}

	const activeChatItem = page.locator('[data-testid="chat-item-wrapper"].active');
	await expect(activeChatItem).toBeVisible();
	
	await activeChatItem.click({ button: 'right' });
	await takeStepScreenshot(page, '13-context-menu');

	const deleteButton = page.getByTestId('chat-context-delete');
	await expect(deleteButton).toBeVisible();
	await deleteButton.click(); // First click - enter confirm mode
	await deleteButton.click(); // Second click - confirm deletion

	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, '14-chat-deleted');
	logCheckpoint('Test chat deleted successfully.');
});

test('message sync: verifies messages_v is properly updated', async ({ page }: { page: any }) => {
	// Listen for console logs
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		const text = msg.text();
		if (text.includes('messages_v') || text.includes('confirmed')) {
			consoleLogs.push(`[${timestamp}] [${msg.type()}] ${text}`);
		}
	});

	test.slow();
	test.setTimeout(120000);

	const logCheckpoint = createSignupLogger('MSG_V_TEST');
	// Screenshot utility available but not used in this abbreviated test
	createStepScreenshotter(logCheckpoint);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);

	// Login flow (via shared helper with OTP retry + clock-drift compensation)
	await loginToTestAccount(page, logCheckpoint);
	await page.waitForTimeout(3000);

	// Start new chat
	const newChatButton = page.getByTestId('new-chat-button');
	if (await newChatButton.isVisible()) {
		await newChatButton.click();
		await page.waitForTimeout(2000);
	}

	// Send message
	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type('Hello!');

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logCheckpoint('Sent message.');

	// Get chat ID
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const urlAfterSend = page.url();
	const chatIdMatch = urlAfterSend.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';

	// Track messages_v changes over time
	const versionsOverTime: { timestamp: string; messages_v: number; messageCount: number }[] = [];

	// Wait for user message to be saved (at least 1 message)
	let stats = await waitForMessageCount(page, chatId, 1, 10000);
	versionsOverTime.push({ 
		timestamp: 'after_send', 
		messages_v: stats.messages_v, 
		messageCount: stats.messageCount 
	});
	logCheckpoint('After send:', stats);
	console.log('📋 Message details after send:', JSON.stringify(stats.messageDetails, null, 2));

	// Wait for AI response to be visible in UI
	const assistantResponse = page.getByTestId('message-assistant');
	await expect(assistantResponse.last()).toBeVisible({ timeout: 45000 });
	
	// Wait for AI response to be saved to IndexedDB (at least 2 messages)
	stats = await waitForMessageCount(page, chatId, 2, 10000);
	versionsOverTime.push({ 
		timestamp: 'after_ai_response', 
		messages_v: stats.messages_v, 
		messageCount: stats.messageCount 
	});
	logCheckpoint('After AI response:', stats);
	console.log('📋 Message details after AI response:', JSON.stringify(stats.messageDetails, null, 2));

	// Verify messages_v tracks message count
	console.log('📊 messages_v tracking over time:', versionsOverTime);
	
	// messages_v should never be 0 if there are messages
	expect(stats.messages_v).toBeGreaterThan(0);
	// messages_v should be at least equal to message count
	expect(stats.messages_v).toBeGreaterThanOrEqual(stats.messageCount);

	// Cleanup
	const activeChatItem = page.locator('[data-testid="chat-item-wrapper"].active');
	if (await activeChatItem.isVisible()) {
		await activeChatItem.click({ button: 'right' });
		const deleteButton = page.getByTestId('chat-context-delete');
		if (await deleteButton.isVisible()) {
			await deleteButton.click();
			await deleteButton.click();
		}
	}
	
	logCheckpoint('Test completed.');
});
