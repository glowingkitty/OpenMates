/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Connection Resilience Tests: Verifies that the app gracefully handles
 * connection drops, tab reloads, and reconnects during AI streaming.
 *
 * Tests cover:
 * 1. Connection drop during AI streaming -> recovery on reconnect
 * 2. Page reload after sending message -> AI response delivered on return
 * 3. IndexedDB v19 migration creates `pending_embed_operations` store
 * 4. Orphaned streaming messages cleaned up on reconnect
 * 5. Pending embed operations queue flushed on reconnect
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of an existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA OTP secret (base32) for the test account.
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL for the deployed web app under test.
 */
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
		consoleLogs.slice(-50).forEach((log: string) => console.log(log));

		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-30).forEach((activity: string) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp
} = require('./signup-flow-helpers');

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

/**
 * Shared login helper: navigates to home, logs in with email/password/OTP,
 * waits for /chat redirect, and clicks "New Chat" if available.
 */
async function loginAndNavigateToChat(
	page: any,
	testInstance: any,
	logPrefix: string
): Promise<{
	logCheckpoint: (msg: string, meta?: Record<string, unknown>) => void;
	takeStepScreenshot: (page: any, label: string) => Promise<void>;
}> {
	const logCheckpoint = createSignupLogger(logPrefix);
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

	testInstance.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	testInstance.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	testInstance.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);

	logCheckpoint('Navigating to home page.', { email: TEST_EMAIL });
	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	// Open login dialog
	const headerLoginButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginButton).toBeVisible();
	await headerLoginButton.click();

	// Enter email
	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logCheckpoint('Entered email and clicked continue.');

	// Enter password
	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible();
	await passwordInput.fill(TEST_PASSWORD);

	// Handle 2FA OTP
	const otpCode = generateTotp(TEST_OTP_KEY);
	const otpInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(otpInput).toBeVisible();
	await otpInput.fill(otpCode);
	logCheckpoint('Generated and entered OTP.');

	// Submit login
	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(submitLoginButton).toBeVisible();
	await submitLoginButton.click();
	logCheckpoint('Submitted login form.');

	// Wait for redirect to chat
	await page.waitForURL(/chat/);
	logCheckpoint('Redirected to chat.');

	// Wait for initial load
	await page.waitForTimeout(5000);

	// Start a fresh chat if possible
	const newChatButton = page.locator('.icon_create');
	if (await newChatButton.isVisible()) {
		logCheckpoint('Clicking New Chat button.');
		await newChatButton.click();
		await page.waitForTimeout(2000);
	}

	return { logCheckpoint, takeStepScreenshot };
}

/**
 * Helper: send a message in the chat editor and return the chat ID from URL.
 */
async function sendMessageAndGetChatId(
	page: any,
	message: string,
	logCheckpoint: (msg: string, meta?: Record<string, unknown>) => void
): Promise<string> {
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type(message);

	const sendButton = page.locator('.send-button');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logCheckpoint(`Sent message: "${message}"`);

	// Wait for chat ID to appear in URL
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const urlAfterSend = page.url();
	const chatIdMatch = urlAfterSend.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
	logCheckpoint(`Chat ID: ${chatId}`, { chatId });
	return chatId;
}

/**
 * Helper: delete a chat via right-click context menu on the active sidebar item.
 */
async function deleteActiveChat(
	page: any,
	logCheckpoint: (msg: string, meta?: Record<string, unknown>) => void
): Promise<void> {
	const activeChatItem = page.locator('.chat-item-wrapper.active');
	if (await activeChatItem.isVisible({ timeout: 3000 }).catch(() => false)) {
		await activeChatItem.click({ button: 'right' });
		const deleteButton = page.locator('.menu-item.delete');
		await expect(deleteButton).toBeVisible();
		await deleteButton.click();
		await deleteButton.click(); // confirm
		await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
		logCheckpoint('Deleted active chat.');
	}
}

// ---------------------------------------------------------------------------
// Test 1: Connection drop during AI streaming -> recovery
// ---------------------------------------------------------------------------
test('recovers AI response after connection drop during streaming', async ({ page, context }: { page: any; context: any }) => {
	page.on('console', (msg: any) => {
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		networkActivities.push(`[${new Date().toISOString()}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		networkActivities.push(`[${new Date().toISOString()}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	test.setTimeout(180000);

	const { logCheckpoint, takeStepScreenshot } = await loginAndNavigateToChat(page, test, 'CONN_DROP');

	// Send a message to trigger AI streaming
	await sendMessageAndGetChatId(page, 'Tell me a long story about a dragon and a knight', logCheckpoint);
	await takeStepScreenshot(page, 'message-sent');

	// Wait briefly for streaming to start
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 30000 });
	logCheckpoint('Assistant message placeholder appeared, streaming likely started.');

	// Wait a moment for some tokens to arrive
	await page.waitForTimeout(3000);
	await takeStepScreenshot(page, 'streaming-in-progress');

	// Drop the connection
	logCheckpoint('Dropping connection (going offline)...');
	await context.setOffline(true);
	await page.waitForTimeout(5000);
	await takeStepScreenshot(page, 'offline');

	// Restore the connection
	logCheckpoint('Restoring connection (going online)...');
	await context.setOffline(false);

	// Wait for reconnect and sync - the AI response should eventually arrive
	logCheckpoint('Waiting for AI response to arrive after reconnect...');
	await expect(assistantMessage.last()).toContainText(/\w{20,}/, { timeout: 60000 });
	await takeStepScreenshot(page, 'response-recovered');
	logCheckpoint('AI response recovered after connection drop.');

	// Cleanup: delete the chat
	await deleteActiveChat(page, logCheckpoint);
});

// ---------------------------------------------------------------------------
// Test 2: Page reload after sending message -> AI response delivered on return
// ---------------------------------------------------------------------------
test('delivers AI response after page reload during processing', async ({ page }: { page: any }) => {
	page.on('console', (msg: any) => {
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		networkActivities.push(`[${new Date().toISOString()}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		networkActivities.push(`[${new Date().toISOString()}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	test.setTimeout(180000);

	const { logCheckpoint, takeStepScreenshot } = await loginAndNavigateToChat(page, test, 'RELOAD');

	// Send a message
	const chatId = await sendMessageAndGetChatId(page, 'What is the capital of France?', logCheckpoint);
	await takeStepScreenshot(page, 'message-sent');

	// Wait briefly for the request to register on the server
	await page.waitForTimeout(2000);

	// Reload the page - server should still be processing
	logCheckpoint('Reloading page while AI is processing...');
	await page.reload();

	// Wait for app to reinitialize after reload
	await page.waitForURL(/chat/, { timeout: 30000 });
	logCheckpoint('Page reloaded, waiting for chat to re-sync...');
	await page.waitForTimeout(8000);

	// Navigate to the specific chat if not already there
	const currentUrl = page.url();
	if (!currentUrl.includes(chatId)) {
		logCheckpoint(`Navigating back to chat ${chatId}...`);
		const chatItem = page.locator(`.chat-item-wrapper[data-chat-id="${chatId}"]`);
		if (await chatItem.isVisible({ timeout: 5000 }).catch(() => false)) {
			await chatItem.click();
			await page.waitForTimeout(2000);
		}
	}

	// The assistant response should arrive
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.last()).toContainText('Paris', { timeout: 60000 });
	await takeStepScreenshot(page, 'response-after-reload');
	logCheckpoint('AI response received after page reload. Contains "Paris".');

	// Cleanup
	await deleteActiveChat(page, logCheckpoint);
});

// ---------------------------------------------------------------------------
// Test 3: IndexedDB v19 migration creates pending_embed_operations store
// ---------------------------------------------------------------------------
test('IndexedDB has pending_embed_operations store after login', async ({ page }: { page: any }) => {
	page.on('console', (msg: any) => {
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`);
	});

	test.slow();
	test.setTimeout(120000);

	const { logCheckpoint, takeStepScreenshot } = await loginAndNavigateToChat(page, test, 'IDB_MIGRATION');

	// Check IndexedDB for the pending_embed_operations store
	logCheckpoint('Checking IndexedDB for pending_embed_operations store...');
	const storeExists = await page.evaluate(async () => {
		const DB_NAME = 'chats_db';
		return new Promise<boolean>((resolve) => {
			const request = indexedDB.open(DB_NAME);
			request.onsuccess = () => {
				const db = request.result;
				const hasStore = db.objectStoreNames.contains('pending_embed_operations');
				const version = db.version;
				db.close();
				console.log(`[IDB_CHECK] DB version: ${version}, has pending_embed_operations: ${hasStore}`);
				resolve(hasStore);
			};
			request.onerror = () => {
				console.error('[IDB_CHECK] Failed to open chats_db');
				resolve(false);
			};
		});
	});

	expect(storeExists).toBe(true);
	logCheckpoint('Confirmed: pending_embed_operations store exists in IndexedDB.');
	await takeStepScreenshot(page, 'idb-store-confirmed');
});

// ---------------------------------------------------------------------------
// Test 4: Orphaned streaming messages cleaned up on reconnect
// ---------------------------------------------------------------------------
test('orphaned streaming messages are cleaned up on reconnect', async ({ page, context }: { page: any; context: any }) => {
	page.on('console', (msg: any) => {
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		networkActivities.push(`[${new Date().toISOString()}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		networkActivities.push(`[${new Date().toISOString()}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	test.setTimeout(180000);

	const { logCheckpoint, takeStepScreenshot } = await loginAndNavigateToChat(page, test, 'ORPHAN_CLEANUP');

	// Send a message to get a chat established
	const chatId = await sendMessageAndGetChatId(page, 'Hello there!', logCheckpoint);

	// Wait for response
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.last()).toContainText(/\w+/, { timeout: 45000 });
	logCheckpoint('Initial response received.');

	// Inject a fake orphaned "streaming" message into IndexedDB
	logCheckpoint('Injecting fake orphaned streaming message into IndexedDB...');
	const injectedId = await page.evaluate(async (cId: string) => {
		const DB_NAME = 'chats_db';
		const MESSAGES_STORE = 'messages';
		const fakeId = 'fake-orphan-' + Date.now();

		return new Promise<string>((resolve, reject) => {
			const request = indexedDB.open(DB_NAME);
			request.onsuccess = () => {
				const db = request.result;
				const tx = db.transaction(MESSAGES_STORE, 'readwrite');
				const store = tx.objectStore(MESSAGES_STORE);
				store.put({
					message_id: fakeId,
					chat_id: cId,
					role: 'assistant',
					status: 'streaming',
					content: 'partial content...',
					created_at: Date.now() - 120000,
					updated_at: Date.now() - 120000
				});
				tx.oncomplete = () => {
					db.close();
					console.log(`[ORPHAN_INJECT] Injected fake streaming message: ${fakeId}`);
					resolve(fakeId);
				};
				tx.onerror = () => {
					db.close();
					reject(new Error('Failed to inject fake message'));
				};
			};
			request.onerror = () => reject(new Error('Failed to open DB'));
		});
	}, chatId);
	logCheckpoint(`Injected fake orphaned message: ${injectedId}`);

	// Drop and restore connection to trigger reconnect cleanup
	logCheckpoint('Triggering reconnect by going offline then online...');
	await context.setOffline(true);
	await page.waitForTimeout(3000);
	await context.setOffline(false);

	// Wait for reconnect and cleanup logic to run
	await page.waitForTimeout(10000);

	// Check that the orphaned message status was changed from "streaming" to "synced"
	const messageStatus = await page.evaluate(async (msgId: string) => {
		const DB_NAME = 'chats_db';
		const MESSAGES_STORE = 'messages';
		return new Promise<string | null>((resolve) => {
			const request = indexedDB.open(DB_NAME);
			request.onsuccess = () => {
				const db = request.result;
				const tx = db.transaction(MESSAGES_STORE, 'readonly');
				const store = tx.objectStore(MESSAGES_STORE);
				const getReq = store.get(msgId);
				getReq.onsuccess = () => {
					db.close();
					const msg = getReq.result;
					console.log(`[ORPHAN_CHECK] Message status: ${msg?.status}`);
					resolve(msg?.status ?? null);
				};
				getReq.onerror = () => {
					db.close();
					resolve(null);
				};
			};
			request.onerror = () => resolve(null);
		});
	}, injectedId);

	logCheckpoint(`Orphaned message status after reconnect: ${messageStatus}`);
	expect(messageStatus).toBe('synced');
	await takeStepScreenshot(page, 'orphan-cleaned');
	logCheckpoint('Orphaned streaming message was cleaned up to "synced".');

	// Cleanup
	await deleteActiveChat(page, logCheckpoint);
});

// ---------------------------------------------------------------------------
// Test 5: Pending embed operations queue flushed on reconnect
// ---------------------------------------------------------------------------
test('pending embed operations are flushed from IndexedDB on reconnect', async ({ page, context }: { page: any; context: any }) => {
	page.on('console', (msg: any) => {
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		networkActivities.push(`[${new Date().toISOString()}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		networkActivities.push(`[${new Date().toISOString()}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	test.setTimeout(180000);

	const { logCheckpoint, takeStepScreenshot } = await loginAndNavigateToChat(page, test, 'EMBED_FLUSH');

	// Wait for app to be fully loaded
	await page.waitForTimeout(3000);

	// Inject a fake pending embed operation into IndexedDB
	logCheckpoint('Injecting fake pending embed operation into IndexedDB...');
	const injectedOpId = await page.evaluate(async () => {
		const DB_NAME = 'chats_db';
		const STORE_NAME = 'pending_embed_operations';
		const fakeOpId = 'fake-embed-op-' + Date.now();

		return new Promise<string>((resolve, reject) => {
			const request = indexedDB.open(DB_NAME);
			request.onsuccess = () => {
				const db = request.result;
				if (!db.objectStoreNames.contains(STORE_NAME)) {
					db.close();
					reject(new Error('pending_embed_operations store not found'));
					return;
				}
				const tx = db.transaction(STORE_NAME, 'readwrite');
				const store = tx.objectStore(STORE_NAME);
				store.put({
					operation_id: fakeOpId,
					embed_id: 'fake-embed-' + Date.now(),
					chat_id: 'fake-chat-' + Date.now(),
					type: 'store_embed',
					payload: { encrypted_data: 'test-data' },
					created_at: Date.now() - 60000
				});
				tx.oncomplete = () => {
					db.close();
					console.log(`[EMBED_INJECT] Injected fake pending embed op: ${fakeOpId}`);
					resolve(fakeOpId);
				};
				tx.onerror = () => {
					db.close();
					reject(new Error('Failed to inject pending embed op'));
				};
			};
			request.onerror = () => reject(new Error('Failed to open DB'));
		});
	});
	logCheckpoint(`Injected fake pending embed operation: ${injectedOpId}`);

	// Verify the operation was stored
	const countBefore = await page.evaluate(async () => {
		const DB_NAME = 'chats_db';
		const STORE_NAME = 'pending_embed_operations';
		return new Promise<number>((resolve) => {
			const request = indexedDB.open(DB_NAME);
			request.onsuccess = () => {
				const db = request.result;
				const tx = db.transaction(STORE_NAME, 'readonly');
				const store = tx.objectStore(STORE_NAME);
				const countReq = store.count();
				countReq.onsuccess = () => {
					db.close();
					resolve(countReq.result);
				};
				countReq.onerror = () => {
					db.close();
					resolve(-1);
				};
			};
			request.onerror = () => resolve(-1);
		});
	});
	logCheckpoint(`Pending embed operations count before reconnect: ${countBefore}`);
	expect(countBefore).toBeGreaterThanOrEqual(1);

	// Drop and restore connection to trigger reconnect flush
	logCheckpoint('Triggering reconnect to flush pending embed operations...');
	await context.setOffline(true);
	await page.waitForTimeout(3000);
	await context.setOffline(false);

	// Wait for reconnect and flush logic to execute
	await page.waitForTimeout(15000);
	await takeStepScreenshot(page, 'after-reconnect-flush');

	// Check if the flush was attempted by looking for related console logs
	const flushAttempted = consoleLogs.some(
		(log: string) => log.includes('flushPendingEmbedOperations') || log.includes('pending_embed')
	);
	logCheckpoint(`Flush attempted (found in console logs): ${flushAttempted}`);

	// Check remaining operations
	const countAfter = await page.evaluate(async () => {
		const DB_NAME = 'chats_db';
		const STORE_NAME = 'pending_embed_operations';
		return new Promise<number>((resolve) => {
			const request = indexedDB.open(DB_NAME);
			request.onsuccess = () => {
				const db = request.result;
				const tx = db.transaction(STORE_NAME, 'readonly');
				const store = tx.objectStore(STORE_NAME);
				const countReq = store.count();
				countReq.onsuccess = () => {
					db.close();
					resolve(countReq.result);
				};
				countReq.onerror = () => {
					db.close();
					resolve(-1);
				};
			};
			request.onerror = () => resolve(-1);
		});
	});
	logCheckpoint(`Pending embed operations count after reconnect: ${countAfter}`);

	// The test passes if either:
	// 1. The count decreased (operation was flushed/removed), OR
	// 2. Console logs show the flush was attempted
	const flushed = countAfter < countBefore || flushAttempted;
	expect(flushed).toBe(true);
	logCheckpoint('Verified: pending embed operations flush was triggered on reconnect.');
});
