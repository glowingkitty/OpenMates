/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Real encrypted offline draft replay and conflicts; core auth/crypto only, with no inference. */
const { test, expect } = require('./helpers/cookie-audit');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, waitForChatReady } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
import {
	setIsolatedCliHome,
	installOfflineWebSocketControl,
	expectBrowserDraftTransportOffline,
	deriveApiUrl,
	createIsolatedCliHome,
	cleanupIsolatedCliHome,
	runCli,
	runCliJson,
	pairCli,
	openSidebar,
	chatItem,
	activeMessageEditorEditable,
	replaceMessageEditorText,
	readQueuedDraftChanges,
	readServerDraftWithBrowserKey,
	resultChatId,
	expectCliPairedToBrowserAccount,
	openDraft,
} from './helpers/cross-client-draft-sync';

const CROSS_CLIENT_DRAFT_SYNC_TIMEOUT_MS = 480_000;
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount(1);

test.describe('Offline encrypted draft replay', () => {
	test.setTimeout(CROSS_CLIENT_DRAFT_SYNC_TIMEOUT_MS);

	// contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative,drafts.persistence.local-first-encrypted
	test('Offline encrypted draft edits replay in durable order and survive reload', async ({ page }: { page: any }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const log = createSignupLogger('OFFLINE_DRAFT_REPLAY');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'offline-draft-replay' });
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);
		const unique = Date.now().toString(36);
		const edits = [1, 2, 3].map((revision) => `Offline revision ${revision} ${unique}`);
		const newestText = edits[edits.length - 1];
		const cleanupDraftIds = new Set<string>();
		const cliHome = createIsolatedCliHome();
		const transport = await installOfflineWebSocketControl(page);
		const frames = transport.frames;
		let cliPaired = false;
		await loginToTestAccount(page, log, screenshot);
		try {
			setIsolatedCliHome(cliHome);
			await pairCli(page, apiUrl, baseUrl);
			cliPaired = true;
			await expectCliPairedToBrowserAccount(page, apiUrl);
			await page.goto(baseUrl);
			await waitForChatReady(page, log);
			const created = await runCliJson(apiUrl, ['drafts', 'create', `Before offline ${unique}`]);
			const chatId = resultChatId(created);
			cleanupDraftIds.add(chatId);
			await openDraft(page, apiUrl, chatId, `Before offline ${unique}`, true);
			await expect.poll(() => readQueuedDraftChanges(page, chatId)).toEqual([]);

			log('Saving three encrypted revisions through the browser while disconnected.');
			await transport.setOffline(true);
			await expectBrowserDraftTransportOffline(page);
			for (const text of edits) {
				const previousCount = (await readQueuedDraftChanges(page, chatId)).length;
				await replaceMessageEditorText(page, chatId, text);
				await expect.poll(async () => (await readQueuedDraftChanges(page, chatId)).length, { timeout: 15_000 }).toBeGreaterThan(previousCount);
			}
			const queued = await readQueuedDraftChanges(page, chatId, true);
			expect(queued.length).toBeGreaterThanOrEqual(3);
			expect(queued.every((row) => Number.isSafeInteger(row.queue_order) && row.queue_order > 0)).toBe(true);
			expect(new Set(queued.map((row) => row.queue_order)).size).toBe(queued.length);
			expect(queued.every((row) => row.type === 'draft' && typeof row.value === 'string' && !!row.encrypted_draft_preview)).toBe(true);
			for (const row of queued) {
				for (const text of edits) {
					expect(row.value).not.toContain(text);
					expect(row.encrypted_draft_preview).not.toContain(text);
				}
			}
			// getAll() returns primary-key order: deliberately make that the opposite of insertion order.
			const idbOrder = await readQueuedDraftChanges(page, chatId);
			expect(idbOrder.map((row) => row.queue_order)).toEqual(queued.map((row) => row.queue_order).reverse());
			const expectedIds = queued.map((row) => row.change_id);
			const reconnectFrameStart = frames.length;
			await transport.setOffline(false);
			await expect.poll(() => frames.slice(reconnectFrameStart).some((frame) =>
				frame.direction === 'sent' && frame.type === 'sync_offline_changes' &&
				JSON.stringify(frame.changeIds.filter((id) => expectedIds.includes(id))) === JSON.stringify(expectedIds)
			), { timeout: 60_000 }).toBe(true);
			await expect.poll(() => frames.slice(reconnectFrameStart).some((frame) =>
				frame.direction === 'received' && frame.type === 'offline_sync_complete' &&
				expectedIds.every((id) => frame.successfulChangeIds.includes(id))
			), { timeout: 60_000 }).toBe(true);
			await expect.poll(() => readQueuedDraftChanges(page, chatId), { timeout: 15_000 }).toEqual([]);
			await expect.poll(() => readServerDraftWithBrowserKey(page, apiUrl, chatId), { timeout: 30_000 }).toMatchObject({ markdown: newestText, preview: newestText });
			await page.reload();
			await waitForChatReady(page, log);
			await openDraft(page, apiUrl, chatId, newestText, true);
			await expect(await activeMessageEditorEditable(page, chatId)).toContainText(newestText);
			await openSidebar(page);
			await expect(chatItem(page, chatId)).toContainText(newestText);
			await screenshot(page, 'newest-offline-draft-restored');

			log('Keeping a genuine conflict queued when a second client advances the server version.');
			await transport.setOffline(true);
			await expectBrowserDraftTransportOffline(page);
			await replaceMessageEditorText(page, chatId, `Unsent conflict ${unique}`);
			await expect.poll(async () => (await readQueuedDraftChanges(page, chatId)).length, { timeout: 15_000 }).toBeGreaterThan(0);
			const conflictedRows = await readQueuedDraftChanges(page, chatId);
			const serverWinner = `Second client wins ${unique}`;
			await runCliJson(apiUrl, ['drafts', 'update', chatId, `Second client first edit ${unique}`]);
			const serverUpdate = await runCliJson(apiUrl, ['drafts', 'update', chatId, serverWinner]);
			expect(Number(serverUpdate.draftV)).toBeGreaterThan(Math.max(...conflictedRows.map((row) => row.version_before_edit)));
			const conflictFrameStart = frames.length;
			await transport.setOffline(false);
			await expect.poll(() => frames.slice(conflictFrameStart).some((frame) =>
				frame.direction === 'received' && frame.type === 'offline_sync_complete' && (frame.conflicts ?? 0) > 0
			), { timeout: 60_000 }).toBe(true);
			expect(await readQueuedDraftChanges(page, chatId)).toEqual(conflictedRows);
			await expect.poll(async () => (await readServerDraftWithBrowserKey(page, apiUrl, chatId)).markdown, { timeout: 30_000 }).toBe(serverWinner);
			log('Accepted rows were acknowledged and removed; conflicting encrypted rows remain recoverable.');
		} finally {
			// Stop the retained outbox before clearing this test's remote draft during cleanup.
			await page.close().catch(() => undefined);
			await page.context().setOffline(false).catch(() => undefined);
			for (const chatId of cleanupDraftIds) await runCli(apiUrl, ['drafts', 'clear', chatId], 10_000);
			if (cliPaired) await runCli(apiUrl, ['logout'], 10_000);
			cleanupIsolatedCliHome(cliHome);
		}
	});
});
