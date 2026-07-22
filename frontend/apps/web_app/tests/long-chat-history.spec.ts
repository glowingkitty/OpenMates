/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Long chat history boundaries.
 *
 * Seeds a provider-free, public-style chat into the real browser IndexedDB and
 * then exercises the deployed Svelte UI. This keeps regular regression coverage
 * deterministic and cheap while the executable spec separately requires one
 * on-demand real CLI/model compression validation after deploy.
 */

const fs = require('fs');
const JSZip = require('jszip');
const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const {
	archiveExistingScreenshots,
	createSignupLogger,
	createStepScreenshotter,
	getE2EDebugUrl,
	getTestAccount
} = require('./signup-flow-helpers');

const CHAT_ID = 'e2e-long-chat-history';
const CHECKPOINT_ID = `${CHAT_ID}-checkpoint-001`;
const BASE_TIMESTAMP = 1784700000;
const COMPRESSED_UP_TO_INDEX = 80;
const TOTAL_MESSAGE_COUNT = 161;
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function dismissSecurityReminder(page: any): Promise<void> {
	const reminder = page.getByTestId('notification').filter({ hasText: 'Security Reminder' });
	if (!(await reminder.isVisible({ timeout: 2000 }).catch(() => false))) return;
	await reminder.getByTestId('notification-dismiss').click();
	await expect(reminder).not.toBeVisible({ timeout: 10000 });
}

async function seedLongChatFixture(page: any): Promise<void> {
	await page.evaluate(
		async ({ chatId, checkpointId, baseTimestamp, compressedUpToIndex, totalMessageCount }) => {
			const openDb = () =>
				new Promise<IDBDatabase>((resolve, reject) => {
					const request = indexedDB.open('chats_db');
					request.onerror = () => reject(request.error ?? new Error('Failed to open chats_db'));
					request.onsuccess = () => resolve(request.result);
				});

			const db = await openDb();
			const requiredStores = ['chats', 'messages', 'chat_compression_checkpoints'];
			for (const storeName of requiredStores) {
				if (!db.objectStoreNames.contains(storeName)) {
					db.close();
					throw new Error(`Missing required IndexedDB store: ${storeName}`);
				}
			}

			await new Promise<void>((resolve, reject) => {
				const transaction = db.transaction(requiredStores, 'readwrite');
				const chatsStore = transaction.objectStore('chats');
				const messagesStore = transaction.objectStore('messages');
				const checkpointsStore = transaction.objectStore('chat_compression_checkpoints');

				transaction.onerror = () => reject(transaction.error ?? new Error('Failed to seed long chat fixture'));
				transaction.oncomplete = () => {
					db.close();
					resolve();
				};

				const deleteByChatId = (store: IDBObjectStore) => {
					const index = store.index('chat_id');
					const cursorRequest = index.openCursor(IDBKeyRange.only(chatId));
					cursorRequest.onsuccess = () => {
						const cursor = cursorRequest.result;
						if (!cursor) return;
						cursor.delete();
						cursor.continue();
					};
				};

				deleteByChatId(messagesStore);
				deleteByChatId(checkpointsStore);

				chatsStore.put({
					chat_id: chatId,
					encrypted_title: null,
					title: 'E2E long compressed history fixture',
					chat_summary: 'Provider-free fixture for long chat history boundaries.',
					category: 'coding',
					icon: 'messages-square',
					messages_v: totalMessageCount,
					title_v: 1,
					metadata_v: 1,
					draft_v: 0,
					encrypted_draft_md: null,
					encrypted_draft_preview: null,
					last_edited_overall_timestamp: baseTimestamp + totalMessageCount,
					unread_count: 0,
					created_at: baseTimestamp,
					updated_at: baseTimestamp + totalMessageCount,
					is_private: false,
					is_shared: false,
					pinned: false
				});

				for (let index = 1; index <= totalMessageCount; index += 1) {
					const padded = String(index).padStart(3, '0');
					const forgotten = index <= compressedUpToIndex;
					const role = index % 2 === 0 ? 'assistant' : 'user';
					const content = `${forgotten ? 'Forgotten' : 'Active'} ${role} message ${padded}: realistic project planning detail for the long chat compression history fixture.`;
					messagesStore.put({
						message_id: `${chatId}-msg-${padded}`,
						chat_id: chatId,
						role,
						created_at: baseTimestamp + index,
						status: 'synced',
						content,
						encrypted_content: content
					});
				}

				checkpointsStore.put({
					id: checkpointId,
					chat_id: chatId,
					summary: 'Compression summary: the first 80 planning messages covered goals, constraints, risks, and implementation tradeoffs.',
					compressed_up_to_timestamp: baseTimestamp + compressedUpToIndex,
					compressed_message_count: compressedUpToIndex,
					summary_token_estimate: 96,
					created_at: baseTimestamp + compressedUpToIndex + 0.5,
					updated_at: baseTimestamp + compressedUpToIndex + 0.5
				});
			});
		},
		{
			chatId: CHAT_ID,
			checkpointId: CHECKPOINT_ID,
			baseTimestamp: BASE_TIMESTAMP,
			compressedUpToIndex: COMPRESSED_UP_TO_INDEX,
			totalMessageCount: TOTAL_MESSAGE_COUNT
		}
	);
}

async function readZipMetadata(download: any, outputPath: string): Promise<Record<string, unknown>> {
	await download.saveAs(outputPath);
	const zip = await JSZip.loadAsync(fs.readFileSync(outputPath));
	const metadataFile = zip.file('export-metadata.json');
	expect(metadataFile, 'downloaded chat ZIP should include export metadata').toBeTruthy();
	return JSON.parse(await metadataFile.async('string')) as Record<string, unknown>;
}

test('loads long compressed history explicitly and exports hydrated metadata', async ({
	page
}: {
	page: any;
}, testInfo: any) => {
	test.slow();
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('LONG_CHAT_HISTORY');
	const screenshot = createStepScreenshotter(log);
	const providerRequests: string[] = [];
	page.on('request', (request: any) => {
		const url = request.url();
		if (/\/v1\/(ai\/|chat\/ask|tasks\/ai|apps\/ai\/skills\/ask)/.test(url)) {
			providerRequests.push(`${request.method()} ${url}`);
		}
	});

	await archiveExistingScreenshots(log);
	await loginToTestAccount(page, log, screenshot);
	await dismissSecurityReminder(page);
	await seedLongChatFixture(page);

	await page.goto(getE2EDebugUrl(`/#chat-id=${CHAT_ID}`), { waitUntil: 'domcontentloaded' });
	await dismissSecurityReminder(page);
	await expect(page.getByTestId('chat-history-container')).toBeVisible({ timeout: 45000 });
	const historyContent = page.getByTestId('chat-history-content');
	await expect(historyContent).toHaveAttribute('data-source-message-count', '40', { timeout: 45000 });
	await expect(page.getByText('Compression summary: the first 80 planning messages')).toBeVisible({
		timeout: 45000
	});
	await expect(page.getByText('Active assistant message 122')).toBeVisible({ timeout: 45000 });
	await expect(page.getByText('Active user message 081')).not.toBeVisible();
	await expect(page.getByTestId('show-older-messages')).toBeVisible({ timeout: 45000 });
	await screenshot(page, 'initial-latest-window');

	await page.getByTestId('show-older-messages').click();
	await expect(historyContent).toHaveAttribute('data-source-message-count', '80', { timeout: 45000 });
	await page.getByTestId('chat-history-container').evaluate((element: HTMLElement) => {
		element.scrollTop = 0;
	});
	await expect(page.getByText('Active assistant message 082')).toBeVisible({ timeout: 45000 });
	await expect(page.getByText('Active user message 081')).not.toBeVisible();
	await screenshot(page, 'older-active-page-loaded');

	await page.getByTestId('show-forgotten-messages').click();
	const forgottenRows = page.locator('[data-forgotten="true"]');
	await expect(forgottenRows.first()).toBeVisible({ timeout: 45000 });
	await expect(page.getByText('Forgotten user message 041')).toBeVisible({ timeout: 45000 });
	await expect(page.getByText(/readable history, but they are no longer part of the assistant's active context/i)).toBeVisible({
		timeout: 45000
	});
	expect(await forgottenRows.count()).toBe(40);
	await expect
		.poll(async () => Number(await forgottenRows.first().evaluate((element: HTMLElement) => getComputedStyle(element).opacity)), {
			timeout: 5000
		})
		.toBeCloseTo(0.6, 1);
	await screenshot(page, 'forgotten-page-revealed');

	const downloadPromise = page.waitForEvent('download', { timeout: 45000 });
	await page.getByTestId('chat-share-button').click();
	await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', /^chats\/[a-zA-Z0-9-]+\/share$/, {
		timeout: 10000
	});
	await expect(page.getByTestId('chat-settings-tabpanel-share')).toBeVisible({ timeout: 10000 });
	await page.getByRole('button', { name: /download chat zip/i }).click();
	const download = await downloadPromise;
	expect(download.suggestedFilename()).toMatch(/\.zip$/);
	const metadata = await readZipMetadata(download, testInfo.outputPath('long-chat-history.zip'));
	expect(metadata).toMatchObject({
		status: 'complete',
		requested_message_count: TOTAL_MESSAGE_COUNT,
		hydrated_message_count: TOTAL_MESSAGE_COUNT,
		checkpoint_count: 1,
		warnings: []
	});

	expect(providerRequests, 'regular long-chat history test must not call AI/provider endpoints').toEqual([]);
});
