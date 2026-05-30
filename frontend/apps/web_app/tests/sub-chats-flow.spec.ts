/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Sub-Chats E2E Flow Test
 *
 * Verifies the sub-chats UI nesting, cards carousel, parent/child navigation,
 * and sibling broadcast toggle using a deterministic mock injection in IndexedDB.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
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
		consoleLogs.slice(-30).forEach((log: string) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity: string) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

/** Ensure sidebar is open (on narrow viewports it's closed by default). */
async function ensureSidebarOpen(page: any): Promise<void> {
	const toggle = page.locator('[data-testid="sidebar-toggle"]');
	if (await toggle.isVisible().catch(() => false)) {
		await toggle.click();
		await page.waitForTimeout(1000);
	}
}

test('verifies sub-chats UI structure, navigation, and sibling broadcast toggle', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(180000);

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);
	page.on('request', (req: any) =>
		networkActivities.push(`[${new Date().toISOString()}] >> ${req.method()} ${req.url()}`)
	);
	page.on('response', (res: any) =>
		networkActivities.push(`[${new Date().toISOString()}] << ${res.status()} ${res.url()}`)
	);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('SUB_CHATS_FLOW');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	// 1. Log in to the test account
	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(4000);

	log('Injecting mock sub-chats in IndexedDB...');
	
	// Inject a parent chat, a child sub-chat, and a grand-child sub-sub-chat programmatically via IndexedDB
	await page.evaluate(async () => {
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

		const parentId = 'e2e-parent-chat-uuid';
		const childId = 'e2e-child-chat-uuid';
		const grandId = 'e2e-grandchild-chat-uuid';

		const now = Math.floor(Date.now() / 1000);

		// Helper to delete item
		const deleteItem = (storeName: string, id: string): Promise<void> => {
			return new Promise((resolve, reject) => {
				const tx = db.transaction(storeName, 'readwrite');
				const store = tx.objectStore(storeName);
				const request = store.delete(id);
				request.onerror = () => reject(request.error);
				request.onsuccess = () => resolve();
			});
		};

		// Helper to add/put item
		const putItem = (storeName: string, item: any): Promise<void> => {
			return new Promise((resolve, reject) => {
				const tx = db.transaction(storeName, 'readwrite');
				const store = tx.objectStore(storeName);
				const request = store.put(item);
				request.onerror = () => reject(request.error);
				request.onsuccess = () => resolve();
			});
		};

		// Clean up any old ones
		await deleteItem(CHATS_STORE, parentId);
		await deleteItem(CHATS_STORE, childId);
		await deleteItem(CHATS_STORE, grandId);
		await deleteItem(MESSAGES_STORE, 'parent-msg-1');
		await deleteItem(MESSAGES_STORE, 'child-msg-1');
		await deleteItem(MESSAGES_STORE, 'grand-msg-1');

		// 1. Parent Chat (Root)
		const parentChat = {
			chat_id: parentId,
			encrypted_title: 'Parent Chat',
			title: 'Parent Chat',
			messages_v: 2,
			title_v: 1,
			last_edited_overall_timestamp: now,
			created_at: now,
			updated_at: now
		};

		// 2. Child Chat (Sub-chat)
		const childChat = {
			chat_id: childId,
			parent_id: parentId,
			is_sub_chat: true,
			encrypted_title: 'Research Apple Q1',
			title: 'Research Apple Q1',
			messages_v: 1,
			title_v: 1,
			last_edited_overall_timestamp: now,
			created_at: now,
			updated_at: now + 5 // Marked updated to show as completed
		};

		// 3. Grandchild Chat (Sub-sub-chat)
		const grandChat = {
			chat_id: grandId,
			parent_id: childId,
			is_sub_chat: true,
			encrypted_title: 'Grandchild Task',
			title: 'Grandchild Task',
			messages_v: 1,
			title_v: 1,
			last_edited_overall_timestamp: now,
			created_at: now,
			updated_at: now
		};

		// Save chats
		await putItem(CHATS_STORE, parentChat);
		await putItem(CHATS_STORE, childChat);
		await putItem(CHATS_STORE, grandChat);

		// Create messages so they are renderable
		const parentMsg = {
			message_id: 'parent-msg-1',
			chat_id: parentId,
			role: 'assistant',
			created_at: now,
			status: 'synced',
			content: 'I have started the sub-chat Apple research.'
		};

		const childMsg = {
			message_id: 'child-msg-1',
			chat_id: childId,
			role: 'user',
			created_at: now,
			status: 'synced',
			content: 'Analyze Apple financial performance.'
		};

		const grandMsg = {
			message_id: 'grand-msg-1',
			chat_id: grandId,
			role: 'user',
			created_at: now,
			status: 'synced',
			content: 'Verify Apple numbers.'
		};

		await putItem(MESSAGES_STORE, parentMsg);
		await putItem(MESSAGES_STORE, childMsg);
		await putItem(MESSAGES_STORE, grandMsg);

		db.close();

		// Trigger local lists changed event so UI updates
		window.dispatchEvent(new CustomEvent('localChatListChanged'));
	});

	await page.waitForTimeout(2000);
	await ensureSidebarOpen(page);
	await screenshot(page, 'sub-chats-injected');

	// 2. Assert Sidebar Tree Layout
	log('Verifying sidebar nested tree layout...');
	const sidebar = page.getByTestId('chat-history');
	await expect(sidebar).toBeVisible();

	// Verify that the sub-chats container and items render with indented styling
	const childItem = page.locator('[data-testid="sub-chat-item"]');
	await expect(childItem).toBeVisible({ timeout: 5000 });
	
	const grandItem = page.locator('[data-testid="grandchild-chat-item"]');
	await expect(grandItem).toBeVisible({ timeout: 5000 });

	// 3. Open Parent Chat and Verify Cards Carousel
	log('Opening parent chat...');
	await page.evaluate(() => {
		window.location.hash = 'chat-id=e2e-parent-chat-uuid';
	});
	await page.waitForTimeout(1500);
	await screenshot(page, 'parent-chat-opened');

	log('Verifying sub-chats horizontal carousel in assistant message...');
	const carousel = page.getByTestId('sub-chats-carousel');
	await expect(carousel).toBeVisible({ timeout: 5000 });

	const card = page.getByTestId('sub-chat-card');
	await expect(card).toBeVisible();
	await expect(card).toContainText('Research Apple Q1');
	await expect(card).toContainText('✓ Done');

	// 4. Click Card to Navigate to Sub-chat
	log('Navigating to child sub-chat via card click...');
	await card.click();
	await page.waitForTimeout(1500);
	await expect(page).toHaveURL(/chat-id=e2e-child-chat-uuid/);
	await screenshot(page, 'child-chat-opened');

	// 5. Verify Persistent "Return" Header Bar
	log('Verifying "Return" header bar in sub-chat...');
	const returnButton = page.getByTestId('return-to-parent-button');
	await expect(returnButton).toBeVisible();
	await expect(returnButton).toContainText('Return');

	// 6. Verify Broadcast Sibling Toggle
	log('Verifying "Share with sibling sub-chats" toggle in sub-chat...');
	const broadcastToggle = page.getByTestId('sub-chat-broadcast-toggle');
	await expect(broadcastToggle).toBeVisible();
	await expect(broadcastToggle).toContainText('Share with sibling sub-chats');

	// 7. Click Return to Go Back to Parent
	log('Clicking "Return" to navigate back to parent...');
	await returnButton.click();
	await page.waitForTimeout(1500);
	await expect(page).toHaveURL(/chat-id=e2e-parent-chat-uuid/);
	await screenshot(page, 'returned-to-parent');

	log('E2E Sub-chats flow test completed successfully!');
});
