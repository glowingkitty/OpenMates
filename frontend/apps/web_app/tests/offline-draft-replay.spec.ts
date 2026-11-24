/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Real encrypted offline draft replay and conflicts; core auth/crypto only, with no inference. */
const { test, expect } = require('./helpers/cookie-audit');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, waitForChatReady } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');
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
const L = ['web-laptop'];
const LOST_RECEIPT_CHECKPOINTS = ['lost-receipt-queued', 'lost-receipt-replayed', 'lost-receipt-second-reconnect'];
const LOST_RECEIPT_PROOF = defineVideoProof({
	id: 'offline-draft-lost-receipt',
	title: 'A draft saved just before the connection dropped syncs without a conflict warning',
	surface: 'web',
	devices: L,
	domain: 'app.dev.openmates.org',
	transcript: [
		{ id: 'queued', text: 'The draft reached the server, but the connection dropped before its receipt, so the browser queued it.', checkpoint: 'lost-receipt-queued', devices: L },
		{ id: 'replayed', text: 'After reconnecting the queued draft is acknowledged: no "changes had conflicts" warning, and the draft stays.', checkpoint: 'lost-receipt-replayed', devices: L },
		{ id: 'second', text: 'Another reconnect syncs a fresh offline edit without resending the acknowledged draft.', checkpoint: 'lost-receipt-second-reconnect', devices: L },
	],
	assertions: [
		{ id: 'offline.lost_receipt.queued', checkpoint: 'lost-receipt-queued', visual: 'The chat shows the draft text while offline.', devices: L },
		{ id: 'offline.lost_receipt.no_conflict', checkpoint: 'lost-receipt-replayed', visual: 'No offline-sync conflict toast; the editor still holds the draft.', devices: L },
		{ id: 'offline.lost_receipt.not_replayed_again', checkpoint: 'lost-receipt-second-reconnect', visual: 'No conflict toast after the second reconnect.', devices: L },
	],
	tutorial: { readingWordsPerSecond: 3, minimumHoldMs: 1200, maximumHoldMs: 4000 },
});
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

	// Prod issue 70f20bcf: the connection drops after the server saved a draft but before
	// its receipt arrives. The browser queues the same encrypted draft; its replay must be
	// acknowledged instead of warning "Offline sync: N changes had conflicts" on every reconnect.
	// contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative,chats.offline-outbox.ordered-replay
	test('A draft saved just before its receipt was lost replays without a conflict warning', async ({ page }: { page: any }, testInfo: any) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const log = createSignupLogger('OFFLINE_DRAFT_LOST_RECEIPT');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'offline-draft-lost-receipt' });
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);
		const unique = Date.now().toString(36);
		const savedText = `Saved before the receipt was lost ${unique}`;
		const cleanupDraftIds = new Set<string>();
		const cliHome = createIsolatedCliHome();
		const transport = await installOfflineWebSocketControl(page);
		const frames = transport.frames;
		const conflictToast = page.getByText(/changes had conflicts/i);
		const proof = createVideoProofRuntime(LOST_RECEIPT_PROOF, {
			device: 'web-laptop',
			checkpoints: LOST_RECEIPT_CHECKPOINTS,
			attach: testInfo.attach.bind(testInfo),
			captureFrame: () => page.screenshot({ type: 'png' }),
		});
		let cliPaired = false;
		await loginToTestAccount(page, log, screenshot);
		try {
			setIsolatedCliHome(cliHome);
			await pairCli(page, apiUrl, baseUrl);
			cliPaired = true;
			await expectCliPairedToBrowserAccount(page, apiUrl);
			await page.goto(baseUrl);
			await waitForChatReady(page, log);
			const created = await runCliJson(apiUrl, ['drafts', 'create', `Before lost receipt ${unique}`]);
			const chatId = resultChatId(created);
			cleanupDraftIds.add(chatId);
			await openDraft(page, apiUrl, chatId, `Before lost receipt ${unique}`, true);
			await expect.poll(() => readQueuedDraftChanges(page, chatId)).toEqual([]);

			log('Saving a draft while the server receipt is held back, then dropping the connection.');
			// The legacy path receipts update_draft; the Rust-core build publishes the draft
			// through sync_offline_changes and receipts it with offline_sync_complete.
			transport.withholdReceived(['draft_update_receipt', 'offline_sync_complete']);
			await replaceMessageEditorText(page, chatId, savedText);
			await expect.poll(async () => (await readServerDraftWithBrowserKey(page, apiUrl, chatId)).markdown, { timeout: 30_000 }).toBe(savedText);
			await transport.setOffline(true);
			await expectBrowserDraftTransportOffline(page);
			transport.withholdReceived([]);
			await expect.poll(async () => (await readQueuedDraftChanges(page, chatId)).length, { timeout: 15_000 }).toBeGreaterThan(0);
			const queued = await readQueuedDraftChanges(page, chatId);
			await proof.assert('offline.lost_receipt.queued', async () => {
				expect(queued.every((row) => row.type === 'draft')).toBe(true);
				await expect(await activeMessageEditorEditable(page, chatId)).toContainText(savedText);
			});
			await screenshot(page, 'draft-queued-after-lost-receipt');
			await proof.checkpoint('lost-receipt-queued');

			log('Reconnecting: the server already holds this draft, so the replay is acknowledged.');
			const reconnectFrameStart = frames.length;
			await transport.setOffline(false);
			const queuedIds = queued.map((row) => row.change_id);
			await expect.poll(() => frames.slice(reconnectFrameStart).some((frame) =>
				frame.direction === 'received' && frame.type === 'offline_sync_complete' &&
				queuedIds.every((id) => frame.successfulChangeIds.includes(id))
			), { timeout: 60_000 }).toBe(true);
			await proof.assert('offline.lost_receipt.no_conflict', async () => {
				const complete = frames.slice(reconnectFrameStart).find((frame) =>
					frame.direction === 'received' && frame.type === 'offline_sync_complete');
				expect(complete?.conflicts ?? 0).toBe(0);
				await expect.poll(() => readQueuedDraftChanges(page, chatId), { timeout: 15_000 }).toEqual([]);
				await expect(conflictToast).toHaveCount(0);
				await expect.poll(async () => (await readServerDraftWithBrowserKey(page, apiUrl, chatId)).markdown, { timeout: 30_000 }).toBe(savedText);
				await expect(await activeMessageEditorEditable(page, chatId)).toContainText(savedText);
			});
			await screenshot(page, 'reconnected-without-conflict-warning');
			await proof.checkpoint('lost-receipt-replayed');

			log('A second reconnect syncs a fresh edit without resending the acknowledged draft.');
			await transport.setOffline(true);
			await expectBrowserDraftTransportOffline(page);
			const nextText = `Edited offline after acknowledgement ${unique}`;
			await replaceMessageEditorText(page, chatId, nextText);
			await expect.poll(async () => (await readQueuedDraftChanges(page, chatId))
				.some((row) => row.type === 'draft' && !queuedIds.includes(row.change_id))).toBe(true);
			const newDraftIds = (await readQueuedDraftChanges(page, chatId))
				.filter((row) => row.type === 'draft' && !queuedIds.includes(row.change_id))
				.map((row) => row.change_id);
			expect(newDraftIds.length).toBeGreaterThan(0);
			const secondFrameStart = frames.length;
			await transport.setOffline(false);
			await expect.poll(() => frames.slice(secondFrameStart).some((frame) =>
				frame.direction === 'received' && frame.type === 'offline_sync_complete' &&
				newDraftIds.every((id) => frame.successfulChangeIds.includes(id))
			), { timeout: 60_000 }).toBe(true);
			await proof.assert('offline.lost_receipt.not_replayed_again', async () => {
				expect(frames.slice(secondFrameStart).some((frame) =>
					frame.direction === 'sent' && frame.type === 'sync_offline_changes' &&
					frame.changeIds.some((id) => queuedIds.includes(id)))).toBe(false);
				await expect.poll(() => readQueuedDraftChanges(page, chatId)).toEqual([]);
				await expect(conflictToast).toHaveCount(0);
			});
			await screenshot(page, 'second-reconnect-still-clean');
			await proof.checkpoint('lost-receipt-second-reconnect');
			await proof.attach();
		} finally {
			const context = page.context();
			if (!page.isClosed()) await page.close();
			await context.setOffline(false);
			for (const chatId of cleanupDraftIds) await runCli(apiUrl, ['drafts', 'clear', chatId], 10_000);
			if (cliPaired) await runCli(apiUrl, ['logout'], 10_000);
			cleanupIsolatedCliHome(cliHome);
		}
	});
});
