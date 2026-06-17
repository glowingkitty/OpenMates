/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Calendar connected-account permission UI flow.
 *
 * This spec intentionally avoids live Google OAuth. It drives the same browser
 * event and IndexedDB message surfaces used by websocket permission requests and
 * encrypted connected-account receipts, proving the UI does not need provider
 * tokens or plaintext account identity to render/act.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getE2EDebugUrl,
	getTestAccount,
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const CHAT_ID = 'e2e-calendar-permission-chat';
const USER_MESSAGE_ID = 'e2e-calendar-user-message';

async function seedCalendarPermissionChat(page: any): Promise<void> {
	await page.evaluate(async ({ chatId, userMessageId }) => {
		const DB_NAME = 'chats_db';
		const CHATS_STORE = 'chats';
		const MESSAGES_STORE = 'messages';
		const now = Math.floor(Date.now() / 1000);
		const cancelExpiresAt = now + 300;

		const openDB = (): Promise<IDBDatabase> => new Promise((resolve, reject) => {
			const request = indexedDB.open(DB_NAME);
			request.onerror = () => reject(request.error);
			request.onsuccess = () => resolve(request.result);
		});

		const putItem = (db: IDBDatabase, storeName: string, item: Record<string, unknown>): Promise<void> => new Promise((resolve, reject) => {
			const tx = db.transaction(storeName, 'readwrite');
			const store = tx.objectStore(storeName);
			const request = store.put(item);
			request.onerror = () => reject(request.error);
			request.onsuccess = () => resolve();
		});

		const db = await openDB();
		await putItem(db, CHATS_STORE, {
			chat_id: chatId,
			encrypted_title: 'Calendar permission flow',
			title: 'Calendar permission flow',
			messages_v: 3,
			title_v: 1,
			last_edited_overall_timestamp: now,
			created_at: now,
			updated_at: now
		});
		await putItem(db, MESSAGES_STORE, {
			message_id: userMessageId,
			chat_id: chatId,
			role: 'user',
			created_at: now,
			status: 'synced',
			content: 'Create and then delete my Calendar planning hold.'
		});
		await putItem(db, MESSAGES_STORE, {
			message_id: 'e2e-calendar-cancel-receipt',
			chat_id: chatId,
			role: 'system',
			created_at: now + 1,
			status: 'synced',
			content: JSON.stringify({
				type: 'connected_account_action_receipt',
				action_id: 'action-cancel',
				user_message_id: userMessageId,
				receipt: {
					app_id: 'calendar',
					skill_id: 'delete-event',
					action: 'delete',
					decision: 'pending_cancel_window',
					cancel_expires_at: cancelExpiresAt,
					undo_available: false
				}
			})
		});
		await putItem(db, MESSAGES_STORE, {
			message_id: 'e2e-calendar-undo-receipt',
			chat_id: chatId,
			role: 'system',
			created_at: now + 2,
			status: 'synced',
			content: JSON.stringify({
				type: 'connected_account_action_receipt',
				action_id: 'action-undo',
				user_message_id: userMessageId,
				receipt: {
					app_id: 'calendar',
					skill_id: 'create-event',
					action: 'write',
					decision: 'explicit_approval',
					undo_available: true,
					undo_type: 'delete_created_event'
				}
			})
		});
		await putItem(db, MESSAGES_STORE, {
			message_id: 'e2e-calendar-skill-embed',
			chat_id: chatId,
			role: 'assistant',
			created_at: now + 3,
			status: 'synced',
			content: '```json\n' + JSON.stringify({
				type: 'app_skill_use',
				embed_id: 'e2e-calendar-get-events-embed',
				app_id: 'calendar',
				skill_id: 'get-events',
				status: 'processing'
			}) + '\n```'
		});
		db.close();
		window.dispatchEvent(new CustomEvent('localChatListChanged', { detail: { chat_id: chatId } }));
	}, { chatId: CHAT_ID, userMessageId: USER_MESSAGE_ID });
}

test.describe('Calendar permission flow', () => {
	test.describe.configure({ timeout: 180000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('renders selected-action approval, account switching, cancel, and undo receipt controls', async ({ page }: { page: any }) => {
		const logCheckpoint = createSignupLogger('CALENDAR_PERMISSION_FLOW');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'calendar-permission-flow',
		});
		let cancelRequestBody: Record<string, unknown> | null = null;

		await archiveExistingScreenshots(logCheckpoint);
		await page.route('**/v1/connected-accounts/actions/action-cancel/cancel', async (route: any) => {
			cancelRequestBody = route.request().postDataJSON();
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					action_id: 'action-cancel',
					status: 'cancelled',
					receipt: { decision: 'user_cancelled', action: 'delete' }
				})
			});
		});

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await seedCalendarPermissionChat(page);
		await page.goto(getE2EDebugUrl(`/#chat-id=${CHAT_ID}`), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-system').first()).toBeVisible({ timeout: 20000 });
		const calendarSkillEmbed = page.locator(
			'[data-testid="embed-preview"][data-app-id="calendar"][data-skill-id="get-events"]'
		);
		await expect(calendarSkillEmbed.first()).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('message-assistant').first()).not.toContainText('"type":"app_skill_use"');
		await expect(page.getByTestId('message-assistant').first()).not.toContainText('calendar | get-events');

		await page.evaluate(({ chatId, userMessageId }) => {
			window.dispatchEvent(new CustomEvent('showConnectedAccountPermissionRequest', {
				detail: {
					requestId: 'permission-calendar-e2e',
					chatId,
					messageId: userMessageId,
					appId: 'calendar',
					skillId: 'delete-event',
					action: 'delete',
					requiredActions: ['delete'],
					accounts: [
						{
							connected_account_id: 'acct-work',
							app_id: 'calendar',
							account_ref: 'calendar-work',
							label: 'Work calendar',
							capabilities: ['read', 'write', 'delete'],
							runtime_modes: { read: 'always_ask', write: 'always_ask', delete: 'always_ask' }
						},
						{
							connected_account_id: 'acct-personal',
							app_id: 'calendar',
							account_ref: 'calendar-personal',
							label: 'Personal calendar',
							capabilities: ['read', 'write', 'delete'],
							runtime_modes: { read: 'auto_decide', write: 'always_ask', delete: 'always_ask' }
						}
					],
					requests: [
						{
							action_id: 'delete-event-1',
							action: 'delete',
							action_scope: { calendar_id: 'primary', event_id: 'event-1' },
							summary: { calendar_id: 'primary', event_id: 'event-1', event_title: 'Planning hold' }
						},
						{
							action_id: 'delete-event-2',
							action: 'delete',
							action_scope: { calendar_id: 'primary', event_id: 'event-2' },
							summary: { calendar_id: 'primary', event_id: 'event-2', event_title: 'Follow-up hold' }
						}
					],
					createdAt: Date.now()
				}
			}));
		}, { chatId: CHAT_ID, userMessageId: USER_MESSAGE_ID });

		const dialog = page.getByTestId('connected-account-permission-dialog');
		await expect(dialog).toBeVisible({ timeout: 15000 });
		const requestToggles = dialog.getByTestId('connected-account-permission-request-toggle');
		await expect(requestToggles).toHaveCount(2);
		await expect(requestToggles.nth(0)).toBeChecked();
		await expect(requestToggles.nth(1)).toBeChecked();
		await expect(dialog.getByTestId('btn-approve-connected-account')).toContainText('Approve selected');
		await expect(dialog.getByTestId('btn-reject-connected-account')).toContainText('Reject all');

		const accountSelects = dialog.getByTestId('connected-account-permission-request-account');
		await expect(accountSelects).toHaveCount(2);
		await accountSelects.nth(1).selectOption('acct-personal');
		await expect(accountSelects.nth(1)).toHaveValue('acct-personal');
		await requestToggles.nth(0).uncheck();
		await expect(requestToggles.nth(0)).not.toBeChecked();
		await expect(requestToggles.nth(1)).toBeChecked();

		await expect(page.getByTestId('connected-account-cancel-button')).toBeVisible({ timeout: 15000 });
		await page.getByTestId('connected-account-cancel-button').click();
		await expect.poll(() => cancelRequestBody, {
			message: 'cancel request body was captured',
			timeout: 10000
		}).toEqual({
			chat_id: CHAT_ID,
			message_id: USER_MESSAGE_ID
		});
		await expect(page.getByTestId('connected-account-undo-button')).toBeVisible({ timeout: 15000 });

		const visibleText = await page.locator('body').innerText();
		expect(visibleText).not.toContain('secret-refresh-token');
		expect(visibleText).not.toContain('work@example.test');
		await takeStepScreenshot(page, 'calendar-permission-ui');
	});
});
