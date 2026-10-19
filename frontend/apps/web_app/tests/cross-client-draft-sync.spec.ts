/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Cross-client encrypted draft lifecycle, sending, and IdeaBucket contracts. */
const { test, expect } = require('./helpers/cookie-audit');
const fs = require('fs');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, waitForAssistantMessage, waitForChatReady } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
import {
	AUDIO_FIXTURE,
	CLI_DRAFT_REFRESH_TIMEOUT_MS,
	CHAT_DELETION_RECONCILE_TIMEOUT_MS,
	setIsolatedCliHome,
	getLastTransientCliFailure,
	installWebSocketFrameTracker,
	waitForDraftUpdateReceipt,
	waitForDraftDeleteReceipt,
	deriveApiUrl,
	createIsolatedCliHome,
	cleanupIsolatedCliHome,
	logCliCacheDiagnostics,
	logCliRestDraftDiagnostics,
	runCli,
	runCliJson,
	pairCli,
	openSidebar,
	chatItem,
	messageEditorEditable,
	messageEditorHost,
	messageInputSendButton,
	sendCurrentMessageWithE2EHook,
	activeMessageEditorEditable,
	replaceMessageEditorText,
	logDraftOpenDiagnostics,
	logServerDraftDiagnostics,
	readLocalDraftMarkdown,
	expectLocalDraftMarkdown,
	resultChatId,
	expectCliPairedToBrowserAccount,
	clearBrowserClientState,
	expectIdeaBucketDraftMarkers,
	expectSearchFindsChat,
	openDraftByHash,
	openDraft,
} from './helpers/cross-client-draft-sync';

const CROSS_CLIENT_DRAFT_SYNC_TIMEOUT_MS = 480_000;
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount(1);

test.describe('Cross-client encrypted draft sync', () => {
	test.describe.configure({ mode: 'serial' });
	test.setTimeout(CROSS_CLIENT_DRAFT_SYNC_TIMEOUT_MS);

	// contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted,drafts.draft-only.lifecycle,drafts.navigation.includes-draft-only
	test('CLI and web reconcile draft lifecycle and missed chat deletion', async ({ page }: { page: any }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const log = createSignupLogger('CROSS_CLIENT_DRAFT_SYNC');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'cross-client-draft-sync' });
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);
		const unique = Date.now().toString(36);
		const initialText = `CLI encrypted draft ${unique}`;
		const updatedText = `Web updated encrypted draft ${unique}`;
		const sentText = `Cross-client sent draft ${unique}`;
		const cleanupDraftIds = new Set<string>();
		const cleanupChatIds = new Set<string>();
		let cliPaired = false;
		const cliHome = createIsolatedCliHome();
		const wsFrames = installWebSocketFrameTracker(page);

		await loginToTestAccount(page, log, screenshot);
		try {
			setIsolatedCliHome(cliHome);
			log('Pairing CLI client.');
			await pairCli(page, apiUrl, baseUrl);
			cliPaired = true;
			await expectCliPairedToBrowserAccount(page, apiUrl);
			log('CLI client paired.');
			await page.goto(baseUrl);
			await waitForChatReady(page, log);

			log('Creating draft from CLI.');
			const created = await runCliJson(apiUrl, ['drafts', 'create', initialText]);
			const draftChatId = String(created.chatId);
			expect(draftChatId).toMatch(/^[0-9a-f-]{36}$/i);
			cleanupDraftIds.add(draftChatId);
			await openDraft(page, apiUrl, draftChatId, initialText, true);
			const draftEditor = await activeMessageEditorEditable(page, draftChatId);
			await expect(draftEditor).toContainText(initialText);
			await expect(page.getByTestId('chat-header-banner')).toHaveCount(0);
			const firstSavedVersion = (await readLocalDraftMarkdown(page, draftChatId)).draftV;
			expect(firstSavedVersion).toBeGreaterThan(0);
			const refreshedDraft = await runCliJson(apiUrl, ['drafts', 'get', draftChatId, '--refresh']);
			expect(Number.isInteger(refreshedDraft.draft?.draftV)).toBe(true);
			expect(refreshedDraft.draft.draftV).toBeGreaterThan(0);
			expect(refreshedDraft.draft.markdown).toBe(initialText);
			log('CLI-created draft opened in web client.');

			const draftUpdateFrameStart = wsFrames.length;
			log('Replacing CLI draft from web client.');
			await replaceMessageEditorText(page, draftChatId, updatedText);
			const firstDismissButton = page.getByTestId('input-dismiss-button');
			if (await firstDismissButton.isVisible({ timeout: 5_000 }).catch(() => false)) {
				await firstDismissButton.click();
			}
			const updatedLocalDraft = await expectLocalDraftMarkdown(page, draftChatId, updatedText, 'CROSS_CLIENT_DRAFT_SYNC');
			expect(updatedLocalDraft.draftV).toBeGreaterThan(firstSavedVersion!);
			await expect(page.getByTestId('chat-header-banner')).toHaveCount(0);
			log('Local web draft edit persisted; waiting for draft update receipt.');
			expect(await waitForDraftUpdateReceipt(wsFrames, draftChatId, 'CROSS_CLIENT_DRAFT_SYNC', draftUpdateFrameStart, Number(created.draftV) + 1)).toBe(true);
			log('Draft update receipt observed; polling CLI refresh.');
			try {
				await expect
					.poll(async () => {
						const result = await runCliJson(apiUrl, ['drafts', 'get', draftChatId, '--refresh'], CLI_DRAFT_REFRESH_TIMEOUT_MS, {
							allowTransientFailure: true,
						});
						const draft = result?.draft;
						return `${draft?.draftV ?? 0}:${draft?.markdown ?? ''}`;
					}, {
						timeout: 120_000,
						intervals: [1_000, 2_000, 5_000]
					})
					.toBe(`${Number(created.draftV) + 1}:${updatedText}`);
			} catch (error) {
				await logCliRestDraftDiagnostics(apiUrl, cliHome, draftChatId, 'CROSS_CLIENT_DRAFT_SYNC_CLI_REST_AFTER_EDIT');
				await logServerDraftDiagnostics(page, apiUrl, draftChatId, 'CROSS_CLIENT_DRAFT_SYNC_SERVER_ROUTE_AFTER_EDIT', updatedText);
				await logDraftOpenDiagnostics(page, draftChatId, 'CROSS_CLIENT_DRAFT_SYNC_SERVER_AFTER_EDIT', updatedText);
				logCliCacheDiagnostics(cliHome, draftChatId, 'CROSS_CLIENT_DRAFT_SYNC_CLI_AFTER_EDIT');
				throw error;
			}
			log('Web draft edit reconciled to CLI.');

			await openDraft(page, apiUrl, draftChatId, updatedText, true);
			const draftDeleteFrameStart = wsFrames.length;
			await replaceMessageEditorText(page, draftChatId, '');
			const dismissButton = page.getByTestId('input-dismiss-button');
			if (await dismissButton.isVisible({ timeout: 5_000 }).catch(() => false)) {
				await dismissButton.click();
			}
			log('Web draft emptied; waiting for CLI reconciliation.');
			expect(await waitForDraftDeleteReceipt(wsFrames, draftChatId, 'CROSS_CLIENT_DRAFT_SYNC', draftDeleteFrameStart)).toBe(true);
			await expect
				.poll(async () => {
					const result = await runCliJson(apiUrl, ['drafts', 'get', draftChatId, '--refresh'], CLI_DRAFT_REFRESH_TIMEOUT_MS, {
						allowTransientFailure: true,
					});
					return result ? result.draft : getLastTransientCliFailure() || 'transient-cli-fetch-failed';
				}, {
					timeout: 60_000,
					intervals: [1_000, 2_000]
				})
				.toBeNull();
			cleanupDraftIds.delete(draftChatId);
			await expect.poll(() => (page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? null), { timeout: 15_000 }).toBeNull();
			await expect.poll(() => new URL(page.url()).hash).not.toContain('chat-id=');
			log('Web draft clear reconciled to CLI.');

			log('Creating sendable draft from CLI.');
			const sendDraft = await runCliJson(apiUrl, ['drafts', 'create', sentText]);
			const sentChatId = String(sendDraft.chatId);
			cleanupDraftIds.add(sentChatId);
			await page.reload();
			await waitForChatReady(page, log);
			await openDraft(page, apiUrl, sentChatId, sentText, true);
			await replaceMessageEditorText(page, sentChatId, sentText);
			await messageEditorEditable(page, sentChatId).click();
			const sendButton = messageInputSendButton(page, sentChatId);
			await expect(sendButton).toBeVisible({ timeout: 15_000 });
			const sendDiagnostics = await sendCurrentMessageWithE2EHook(page, sentChatId);
			console.info(`[CROSS_CLIENT_DRAFT_SYNC] Send helper diagnostics: ${JSON.stringify(sendDiagnostics)}`);
			await expect(page.getByTestId('message-user').last()).toContainText(sentText, { timeout: 30_000 });
			await waitForAssistantMessage(page, { which: 'last', timeout: 120_000, logCheckpoint: log });
			await expect
				.poll(async () => {
					const result = await runCliJson(apiUrl, ['drafts', 'get', sentChatId, '--refresh'], CLI_DRAFT_REFRESH_TIMEOUT_MS, {
						allowTransientFailure: true,
					});
					return result ? result.draft : getLastTransientCliFailure() || 'transient-cli-fetch-failed';
				}, {
					timeout: 60_000,
					intervals: [1_000, 2_000]
				})
				.toBeNull();
			cleanupDraftIds.delete(sentChatId);
			cleanupChatIds.add(sentChatId);
			log('Web send cleared the CLI draft.');

			log('Deleting sent chat while web client is offline.');
			await page.context().setOffline(true);
			const deletion = await runCli(apiUrl, ['chats', 'delete', sentChatId, '--yes']);
			expect(deletion.code, `CLI chat deletion failed:\n${deletion.stderr}`).toBe(0);
			expect(deletion.stdout).toContain('1/1 chat(s) deleted.');
			cleanupChatIds.delete(sentChatId);
			await page.context().setOffline(false);
			await page.reload();
			await waitForChatReady(page, log);
			await openSidebar(page);
			await expect(chatItem(page, sentChatId)).toHaveCount(0, { timeout: CHAT_DELETION_RECONCILE_TIMEOUT_MS });
			log('Missed chat deletion reconciled after reconnect.');
		} finally {
			await page.context().setOffline(false).catch(() => undefined);
			for (const chatId of cleanupDraftIds) {
				await runCli(apiUrl, ['drafts', 'clear', chatId], 10_000);
			}
			for (const chatId of cleanupChatIds) {
				await runCli(apiUrl, ['chats', 'delete', chatId, '--yes'], 10_000);
			}
			if (cliPaired) await runCli(apiUrl, ['logout'], 10_000);
			cleanupIsolatedCliHome(cliHome);
		}
	});

	// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted,drafts.draft-only.lifecycle
	test('IdeaBucket drafts and processed chats keep encrypted provenance across web cold boot', async ({ page }: { page: any }) => {
		test.setTimeout(600_000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		expect(fs.existsSync(AUDIO_FIXTURE), `Missing audio fixture at ${AUDIO_FIXTURE}`).toBeTruthy();
		const log = createSignupLogger('IDEABUCKET_WEB_MARKERS');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'ideabucket-web-markers' });
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = deriveApiUrl(baseUrl);
		const unique = Date.now().toString(36);
		const draftText = `IdeaBucket editable draft ${unique}`;
		const editedDraftText = `IdeaBucket edited draft ${unique}`;
		const audioBucketId = `e2e-audio-${unique}`;
		const draftBucketId = `e2e-draft-${unique}`;
		const processBucketId = `e2e-process-${unique}`;
		const processText = `IdeaBucket processed history ${unique}`;
		const futureSchedule = String(Math.floor(Date.now() / 1000) + 3600);
		const cleanupDraftIds = new Set<string>();
		const cleanupChatIds = new Set<string>();
		let cliPaired = false;
		const cliHome = createIsolatedCliHome();
		const wsFrames = installWebSocketFrameTracker(page);

		await loginToTestAccount(page, log, screenshot);
		try {
			setIsolatedCliHome(cliHome);
			log('Pairing CLI client for IdeaBucket web coverage.');
			await pairCli(page, apiUrl, baseUrl);
			cliPaired = true;
			await expectCliPairedToBrowserAccount(page, apiUrl);
			await page.goto(baseUrl);
			await waitForChatReady(page, log);

			log('Creating encrypted IdeaBucket text draft from CLI.');
			const draft = await runCliJson(apiUrl, [
				'ideabucket',
				'add',
				draftText,
				'--bucket',
				draftBucketId,
				'--scheduled-at',
				futureSchedule
			]);
			const draftChatId = resultChatId(draft);
			cleanupDraftIds.add(draftChatId);
			await page.reload();
			await waitForChatReady(page, log);
			await expectIdeaBucketDraftMarkers(page, draftChatId, draftText);
			await screenshot(page, 'text-draft-markers');

			const draftUpdateFrameStart = wsFrames.length;
			const editor = await replaceMessageEditorText(page, draftChatId, editedDraftText);
			await expect(editor).toContainText(editedDraftText, { timeout: 10_000 });
			const dismissButton = page.getByTestId('input-dismiss-button');
			if (await dismissButton.isVisible({ timeout: 5_000 }).catch(() => false)) {
				await dismissButton.click();
			}
			const localDraft = await expectLocalDraftMarkdown(page, draftChatId, editedDraftText, 'IDEABUCKET_WEB_MARKERS');
			expect(await waitForDraftUpdateReceipt(wsFrames, draftChatId, 'IDEABUCKET_WEB_MARKERS', draftUpdateFrameStart, localDraft.draftV ?? 2)).toBe(true);
			try {
				await expect
					.poll(async () => {
						const result = await runCliJson(apiUrl, ['drafts', 'get', draftChatId, '--refresh'], CLI_DRAFT_REFRESH_TIMEOUT_MS, {
							allowTransientFailure: true,
						});
						const currentDraft = result?.draft;
						return currentDraft?.markdown ?? '';
					}, {
						timeout: 120_000,
						intervals: [1_000, 2_000, 5_000]
					})
					.toBe(editedDraftText);
			} catch (error) {
				await logCliRestDraftDiagnostics(apiUrl, cliHome, draftChatId, 'IDEABUCKET_WEB_MARKERS_CLI_REST_AFTER_EDIT');
				await logServerDraftDiagnostics(page, apiUrl, draftChatId, 'IDEABUCKET_WEB_MARKERS_SERVER_ROUTE_AFTER_EDIT', editedDraftText);
				await logDraftOpenDiagnostics(page, draftChatId, 'IDEABUCKET_WEB_MARKERS_SERVER_AFTER_EDIT', editedDraftText);
				logCliCacheDiagnostics(cliHome, draftChatId, 'IDEABUCKET_WEB_MARKERS_CLI_AFTER_EDIT');
				throw error;
			}
			log('IdeaBucket text draft remained editable in web.');

			const status = await runCli(apiUrl, ['ideabucket', 'status', draftBucketId, '--json']);
			expect(status.code, `IdeaBucket status failed:\n${status.stderr}`).toBe(0);
			expect(status.stdout).not.toContain(draftText);
			expect(status.stdout).not.toContain(editedDraftText);
			log('IdeaBucket status returned only sparse encrypted-safe metadata.');

			log('Cold booting browser state, then logging in again.');
			await clearBrowserClientState(page, baseUrl);
			await loginToTestAccount(page, log, screenshot);
			await waitForChatReady(page, log);
			await expectIdeaBucketDraftMarkers(page, draftChatId, editedDraftText);
			await screenshot(page, 'cold-boot-draft-markers');

			log('Creating encrypted IdeaBucket audio draft from CLI.');
			const audioDraft = await runCliJson(apiUrl, [
				'ideabucket',
				'audio',
				AUDIO_FIXTURE,
				'--bucket',
				audioBucketId,
				'--scheduled-at',
				futureSchedule
			], 120_000);
			const audioChatId = resultChatId(audioDraft);
			cleanupDraftIds.add(audioChatId);
			await page.reload();
			await waitForChatReady(page, log);
			const audioFixtureName = path.basename(AUDIO_FIXTURE);
			await expectIdeaBucketDraftMarkers(page, audioChatId, null);
			await expect
				.poll(async () => (await readLocalDraftMarkdown(page, audioChatId)).markdown ?? '', {
					timeout: 15_000,
					intervals: [500, 1_000]
				})
				.toContain(audioFixtureName);
			await expect(page.getByTestId('recording-preview').first()).toBeAttached({ timeout: 30_000 });
			await screenshot(page, 'audio-draft-embed-preview');

			log('Creating and processing due IdeaBucket chat from CLI.');
			const processedDraft = await runCliJson(apiUrl, [
				'ideabucket',
				'add',
				processText,
				'--bucket',
				processBucketId,
				'--scheduled-at',
				String(Math.floor(Date.now() / 1000) - 5)
			]);
			const processedChatId = resultChatId(processedDraft);
			cleanupDraftIds.add(processedChatId);
			const processed = await runCliJson(apiUrl, ['ideabucket', 'process', processBucketId, '--now'], 90_000);
			expect(processed.status).toBe('sent');
			expect(String(processed.chat_id)).toBe(processedChatId);
			cleanupDraftIds.delete(processedChatId);
			cleanupChatIds.add(processedChatId);

			await page.reload();
			await waitForChatReady(page, log);
			await openSidebar(page);
			const processedItem = chatItem(page, processedChatId);
			await expect(processedItem).toBeVisible({ timeout: 30_000 });
			await expect(processedItem.getByTestId('ideabucket-chat-badge')).toBeVisible({ timeout: 15_000 });
			await openDraftByHash(page, processedChatId);
			await waitForChatReady(page, log);
			await expect(messageEditorHost(page, processedChatId)).toBeVisible({ timeout: 30_000 });
			await expect(page.getByTestId('message-user').first()).toContainText(processText, { timeout: 60_000 });
			await expect(page.getByTestId('system-message-text').first()).toContainText('ideabucket_triggered_send', { timeout: 60_000 });
			await screenshot(page, 'processed-chat-marker-and-system-event');

			await expectSearchFindsChat(page, processText);
			await screenshot(page, 'processed-chat-search-result');
			log('Processed IdeaBucket chat was searchable from chat history.');
		} finally {
			for (const chatId of cleanupDraftIds) {
				await runCli(apiUrl, ['drafts', 'clear', chatId], 10_000);
			}
			for (const chatId of cleanupChatIds) {
				await runCli(apiUrl, ['chats', 'delete', chatId, '--yes'], 10_000);
			}
			if (cliPaired) await runCli(apiUrl, ['logout'], 10_000);
			cleanupIsolatedCliHome(cliHome);
		}
	});
});
